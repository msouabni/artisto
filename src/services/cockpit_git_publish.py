"""Cockpit → git : commit d'un ``work_item`` prêt comme Post ``.md`` (Phase 1).

Cap (cf. ``alwanbooks-docs/DIRECTION-PHASE-2026-06-22.md`` + ``PLAN-PHASE1.md``) :

    git = vérité du contenu. **Le commit (identité bot) est la SEULE porte
    d'entrée dans git.** Ce service prend un ``work_item`` dont le buffer de
    staging est prêt, sérialise le Post ``.md`` (frontmatter depuis
    ``staging_frontmatter`` + corps depuis ``staging_body``), l'écrit dans un
    **clone du repo contenu** (``CONTENT_REPO_PATH``) sous
    ``src/content/posts/<locale>/<slug>.md``, commite via l'identité bot
    partagée, puis met à jour le miroir (``work_item.last_synced_hash`` +
    réindexation ``git_index``) pour que le drift repasse à 0 immédiatement.

ADD-ONLY : un ``.md`` déjà présent n'est jamais réécrit sans ``force=True``
explicite (même garde-fou que le pipeline alwanbooks). Le contrat de marqueur
de lot — ``launchSet`` (frontmatter) — est posé ICI au commit des pages curées ;
le front (``rimalab-v2``) filtre dessus, jamais sur ``categoryId``.

PostgreSQL unique. SQLite interdit (y compris tests).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.git_indexer import (
    DEFAULT_REPO,
    content_repo_path,
    parse_doc,
)

logger = logging.getLogger(__name__)

# Identité bot par défaut (miroir de ``data/destination_sites.json``). On la
# reprend en dur ici pour ne pas dépendre du registre destinataire si le service
# tourne sur un clone jetable ; surchargeable via ``bot=`` ou ``CONTENT_BOT_*``.
DEFAULT_BOT_NAME = "artiste-pipeline"
DEFAULT_BOT_EMAIL = "bot@artiste-coloriage.local"

# Ordre stable du frontmatter sérialisé. ``launchSet`` (marqueur de lot) figure
# explicitement — c'est le contrat partagé cockpit ↔ front. Toute clé présente
# dans ``staging_frontmatter`` mais absente de cet ordre est émise après, triée,
# pour ne JAMAIS perdre un champ (imageSvg, plateId, clusterId…).
FRONTMATTER_ORDER = [
    "locale", "slug", "title", "title_card", "description", "keywords",
    "categoryId", "themeIds", "ageMin", "ageMax", "niveauDifficulte",
    "imageSource", "imageWeb", "imageThumb", "imagePdf", "imageSvg",
    "status", "publishDate", "datePublication", "dateModification",
    "featured", "launchSet", "clusterId", "plateId", "profil", "variantes",
]

# Style OBLIGATOIRE + en PREMIER de toute galerie de variantes (convention
# d'assets verrouillée). Le scan place toujours ``classique`` en tête, le reste
# trié alphabétiquement.
CLASSIQUE_STYLE = "classique"

# Convention d'assets verrouillée :
#   {slug-planche}/{id-style}.png   ← source / affichage (galerie)
#   {slug-planche}/{id-style}.svg   ← impression (chargée au clic, pas en galerie)
# Le style = basename du fichier sans extension. Pas de table de mapping.
_IMAGE_EXT = ".png"
_PRINT_EXT = ".svg"

# Clés date émises sans quotes (YAML date scalar natif), comme côté pipeline.
_DATE_KEYS = frozenset({"publishDate", "datePublication", "dateModification"})


class CockpitPublishError(RuntimeError):
    """Erreur métier du commit cockpit → git (collision ADD-ONLY, staging vide…)."""


class CockpitDriftError(CockpitPublishError):
    """Conflit d'optimistic concurrency sur un commit UPDATE.

    Git a changé entre le ``edit-load`` et le commit (édition hors cockpit) :
    le ``content_hash`` courant de git ≠ ``last_synced_hash`` mémorisé. On
    REFUSE le commit (jamais d'écrasement). Porte les hash pour exposer le drift
    côté API (409 + détail).
    """

    def __init__(
        self,
        message: str,
        *,
        expected_hash: str | None = None,
        current_hash: str | None = None,
    ) -> None:
        super().__init__(message)
        self.expected_hash = expected_hash
        self.current_hash = current_hash

    def drift_detail(self) -> dict[str, Any]:
        return {
            "error": "drift",
            "message": str(self),
            "drift": True,
            "drift_reason": "content_hash_changed",
            "expected_hash": self.expected_hash,
            "current_hash": self.current_hash,
        }


@dataclass
class PublishResult:
    """Résultat d'un commit cockpit → git (ou d'un dry-run)."""

    work_item_id: str
    repo: str
    locale: str
    slug: str
    rel_path: str
    md: str
    committed: bool = False
    dry_run: bool = False
    commit_hash: str | None = None
    content_hash: str | None = None
    bot_name: str | None = None
    bot_email: str | None = None
    reindex: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    # Variantes (V5) : bloc émis dans le frontmatter + images placées (convention).
    variantes: list[dict[str, Any]] = field(default_factory=list)
    images_placed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "repo": self.repo,
            "locale": self.locale,
            "slug": self.slug,
            "rel_path": self.rel_path,
            "md": self.md,
            "committed": self.committed,
            "dry_run": self.dry_run,
            "commit_hash": self.commit_hash,
            "content_hash": self.content_hash,
            "bot_name": self.bot_name,
            "bot_email": self.bot_email,
            "reindex": self.reindex,
            "notes": self.notes,
            "variantes": self.variantes,
            "images_placed": self.images_placed,
        }


# ── Sérialisation YAML (autonome, pas d'import de scripts/) ────────────────────

def _yaml_quote(value: str) -> str:
    """Quote une chaîne YAML. Simple quote sauf si caractères problématiques."""
    if value == "":
        return "''"
    if "'" in value and '"' not in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if "'" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "'" + value + "'"


def _emit_value(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _yaml_quote(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = [f"{pad}  - {_emit_value(item, indent + 1)}" for item in value]
        return "\n" + "\n".join(lines)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for k in sorted(value.keys()):
            emitted = _emit_value(value[k], indent + 1)
            sep = "" if emitted.startswith("\n") else " "
            lines.append(f"{pad}  {k}:{sep}{emitted}")
        return "\n" + "\n".join(lines)
    raise CockpitPublishError(f"Valeur YAML non supportée : {type(value).__name__}")


def _coerce_date_scalar(value: Any) -> str | None:
    """Rend une valeur date émissible sans quotes (YYYY-MM-DD), ou None si N/A."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):  # date
        try:
            return value.isoformat()[:10]
        except Exception:  # noqa: BLE001
            return None
    if isinstance(value, str):
        txt = value.strip()
        return txt[:10] if txt else None
    return None


def serialize_post_md(frontmatter: dict[str, Any], body: str | None) -> str:
    """Sérialise un Post ``.md`` (frontmatter ordonné + corps).

    PRÉSERVE toutes les clés du frontmatter (ordre stable connu d'abord, puis
    le reste trié) — aucune perte de ``launchSet`` / ``imageSvg`` / ``plateId``.
    """
    fm = dict(frontmatter or {})
    lines: list[str] = ["---"]

    ordered = [k for k in FRONTMATTER_ORDER if k in fm]
    rest = sorted(k for k in fm if k not in FRONTMATTER_ORDER)

    for key in ordered + rest:
        val = fm[key]
        if val is None:
            continue
        if isinstance(val, str) and not val:
            continue
        # Listes vides : on garde ``themeIds: []`` (attendu par Zod), on omet le reste.
        if isinstance(val, list) and not val and key != "themeIds":
            continue
        if key in _DATE_KEYS:
            scalar = _coerce_date_scalar(val)
            if scalar is not None:
                lines.append(f"{key}: {scalar}")
                continue
        emitted = _emit_value(val)
        sep = "" if emitted.startswith("\n") else " "
        lines.append(f"{key}:{sep}{emitted}")

    lines.append("---")
    lines.append("")
    if body and body.strip():
        lines.append(body.strip("\n"))
    else:
        title = fm.get("title", "")
        description = fm.get("description", "")
        lines.append(f"## {title}")
        lines.append("")
        lines.append(str(description))
    lines.append("")
    return "\n".join(lines)


# ── Scan d'assets → variantes[] (convention verrouillée, pas de mapping) ───────

@dataclass
class ScannedVariante:
    """Une variante de style scannée dans un dossier d'assets ``{slug}/``."""

    style: str           # basename du fichier sans extension (= id du style)
    image: str           # chemin source/affichage (.png) — relatif à la convention
    print: str | None    # chemin impression (.svg) s'il existe, sinon None
    image_path: Path     # chemin absolu du .png sur disque (pour la copie au commit)
    print_path: Path | None  # chemin absolu du .svg sur disque (idem), ou None


def scan_variantes(
    asset_dir: Path | str,
    *,
    slug: str | None = None,
) -> list[ScannedVariante]:
    """Scanne un dossier d'assets ``{slug}/`` → ``variantes[]`` (convention).

    Convention verrouillée (pas de table de mapping) :
        {slug-planche}/{id-style}.png   ← source / affichage
        {slug-planche}/{id-style}.svg   ← impression

    Le **style = basename du fichier sans extension**. La liste est triée avec
    ``classique`` TOUJOURS en premier (obligatoire), le reste alphabétiquement.
    Les chemins ``image`` / ``print`` retournés sont à la convention publique
    ``/img/{slug}/{style}.{png,svg}`` (servie par le front) si ``slug`` est
    fourni ; sinon relatifs au nom de fichier.

    Args:
        asset_dir: dossier ``{slug}/`` contenant les ``.png`` (+ ``.svg`` optionnels).
        slug: slug de la planche (pour préfixer les chemins publics ``/img/{slug}/``).
            Défaut : nom du dossier ``asset_dir``.

    Returns:
        Liste de ``ScannedVariante`` (``classique`` en premier).

    Raises:
        CockpitPublishError: dossier absent, ou aucune variante ``classique.png``
            (la classique est obligatoire + en premier — sinon le front casse :
            la galerie d'un sujet doit au moins porter la classique).
    """
    d = Path(asset_dir)
    if not d.is_dir():
        raise CockpitPublishError(f"scan_variantes : dossier d'assets introuvable : {d}")
    slug = slug or d.name

    by_style: dict[str, dict[str, Path]] = {}
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in (_IMAGE_EXT, _PRINT_EXT):
            continue
        style = f.stem  # basename sans extension = id du style (pas de mapping)
        by_style.setdefault(style, {})[ext] = f

    # ``classique`` obligatoire + en premier ; le reste alpha.
    if CLASSIQUE_STYLE not in by_style or _IMAGE_EXT not in by_style[CLASSIQUE_STYLE]:
        raise CockpitPublishError(
            f"scan_variantes : '{CLASSIQUE_STYLE}{_IMAGE_EXT}' obligatoire et absent de {d} "
            f"(la classique est la variante de base, en premier)"
        )

    ordered_styles = [CLASSIQUE_STYLE] + sorted(
        s for s in by_style if s != CLASSIQUE_STYLE
    )

    variantes: list[ScannedVariante] = []
    for style in ordered_styles:
        files = by_style[style]
        png = files.get(_IMAGE_EXT)
        if png is None:
            # Un .svg seul (sans .png d'affichage) n'est pas une variante de
            # galerie valide — on l'ignore (l'image source/affichage manque).
            continue
        svg = files.get(_PRINT_EXT)
        variantes.append(ScannedVariante(
            style=style,
            image=f"/img/{slug}/{style}{_IMAGE_EXT}",
            print=(f"/img/{slug}/{style}{_PRINT_EXT}" if svg else None),
            image_path=png,
            print_path=svg,
        ))
    return variantes


def _derive_alt(fm: dict[str, Any], style: str) -> str:
    """``alt`` dérivé d'une variante si non fourni (« coloriage {sujet} {style} … »).

    Le sujet est dérivé du ``title_card`` / ``title`` / ``slug`` du post. Le
    libellé du style est laissé brut (id) — le front rend le vrai ``label`` du
    style via ``getEntry`` ; l'``alt`` n'est qu'un repli SEO recherche d'images.
    Borné à 160 chars (contrainte schéma front ``boundedString(5, 160)``).
    """
    sujet = (
        str(fm.get("title_card") or "").strip()
        or str(fm.get("title") or "").strip()
        or str(fm.get("slug") or "").replace("-", " ").strip()
    )
    # Nettoie un éventuel préfixe « Coloriage » déjà présent dans title_card.
    sujet_clean = sujet
    for pref in ("Coloriage ", "coloriage "):
        if sujet_clean.startswith(pref):
            sujet_clean = sujet_clean[len(pref):]
            break
    alt = f"coloriage {sujet_clean} {style} à imprimer".strip()
    return alt[:160]


def variantes_to_frontmatter(
    scanned: list[ScannedVariante],
    fm: dict[str, Any],
    *,
    explicit: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Transforme des ``ScannedVariante`` en bloc ``variantes`` du frontmatter.

    Format émis (lisible par le schéma front : ``{ style: ref→styles, image, alt }``).
    ``alt`` = ``explicit[style]`` si fourni, sinon dérivé (``_derive_alt``).
    """
    explicit = explicit or {}
    out: list[dict[str, Any]] = []
    for v in scanned:
        out.append({
            "style": v.style,
            "image": v.image,
            "alt": explicit.get(v.style) or _derive_alt(fm, v.style),
        })
    return out


# ── Garde de distribution (profil page ↔ profils du style) — miroir front V3 ───

def _load_style_profils(
    styles_dir: Path,
) -> dict[str, list[str]]:
    """Charge ``styleId → profils[]`` depuis ``src/content/styles/*.json`` du clone.

    Miroir CÔTÉ COCKPIT de la garde de distribution du build front (V3). Permet
    de PRÉVENIR avant le commit qu'une variante d'un style interdit sur une page
    ``profil:'facile'`` casserait le build. Si le dossier styles est absent (clone
    sans la feature front), on ne peut pas garder → retourne ``{}`` (pas de blocage,
    le build front reste l'autorité finale).
    """
    import json

    out: dict[str, list[str]] = {}
    if not styles_dir.is_dir():
        return out
    for f in sorted(styles_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        profils = data.get("profils")
        if isinstance(profils, list):
            out[f.stem] = [str(p) for p in profils]
    return out


def check_distribution(
    variantes_fm: list[dict[str, Any]],
    profil: str,
    style_profils: dict[str, list[str]],
) -> list[str]:
    """Vérifie qu'aucune variante d'un style interdit n'est posée sur ``profil:facile``.

    Retourne la liste des **violations** (messages). Vide = OK. Miroir de la
    garde de distribution du build front (``validate-collections.ts`` point 8) :
    une page ``profil:'facile'`` ne peut référencer un style dont ``profils``
    n'inclut pas ``'facile'`` (sinon le build front CASSERAIT). On PRÉVIENT ici,
    AVANT le commit. Si ``style_profils`` est vide (styles inconnus du clone), on
    ne peut pas juger → aucune violation (le build reste l'autorité).
    """
    violations: list[str] = []
    if profil != "facile":
        return violations
    for v in variantes_fm:
        style = v.get("style")
        profils = style_profils.get(str(style))
        if profils is None:
            continue  # style inconnu du clone → laissé au build front
        if "facile" not in profils:
            violations.append(
                f"style '{style}' (profils {profils}) interdit sur une planche "
                f"profil:'facile' — le build front casserait (garde de distribution)"
            )
    return violations


def _content_styles_dir(repo_root: Path) -> Path:
    return repo_root / "src" / "content" / "styles"


def _place_variante_images(
    repo_root: Path,
    slug: str,
    scanned: list[ScannedVariante],
    *,
    force: bool = False,
) -> list[str]:
    """Copie les images de variantes à la convention ``public/img/{slug}/{style}.{png,svg}``.

    ADD-ONLY : une image déjà présente n'est PAS écrasée (sauf ``force`` — update
    contrôlé tracké). Retourne la liste des chemins relatifs placés (ou laissés
    en place s'ils existaient déjà). Crée le dossier cible au besoin.
    """
    import shutil

    target_dir = repo_root / "public" / "img" / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    placed: list[str] = []

    def _copy(src: Path, dst_name: str) -> None:
        dst = target_dir / dst_name
        rel = f"public/img/{slug}/{dst_name}"
        if dst.exists() and not force:
            placed.append(rel)  # ADD-ONLY : conservée, jamais écrasée
            return
        shutil.copyfile(src, dst)
        placed.append(rel)

    for v in scanned:
        _copy(v.image_path, f"{v.style}{_IMAGE_EXT}")
        if v.print_path is not None:
            _copy(v.print_path, f"{v.style}{_PRINT_EXT}")
    return placed


# ── Git plomberie (identité bot) ───────────────────────────────────────────────

def _git_run(repo_root: Path, args: list[str]):
    import subprocess

    return subprocess.run(
        ["git"] + args,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _bot_commit(
    repo_root: Path,
    rel_path: str | list[str],
    message: str,
    *,
    bot_name: str,
    bot_email: str,
) -> tuple[str, bool]:
    """Stage + commit ``rel_path`` (un chemin ou plusieurs) via l'identité bot.

    Retourne ``(commit_hash, created)`` : ``created`` est ``False`` si le commit
    n'a rien produit (contenu byte-identique sur un ``force`` rewrite) — cas
    idempotent toléré, pas une erreur. ``commit_hash`` est alors le HEAD courant.
    """
    paths = [rel_path] if isinstance(rel_path, str) else list(rel_path)
    r = _git_run(repo_root, ["add", *paths])
    if r.returncode != 0:
        raise CockpitPublishError(f"git add a échoué : {r.stderr or r.stdout}")
    r = _git_run(repo_root, [
        "-c", f"user.name={bot_name}",
        "-c", f"user.email={bot_email}",
        "commit", "-m", message,
    ])
    created = True
    if r.returncode != 0:
        out = ((r.stdout or "") + (r.stderr or "")).lower()
        if "nothing to commit" in out:
            created = False  # contenu identique : no-op idempotent
        else:
            raise CockpitPublishError(f"git commit a échoué : {r.stderr or r.stdout}")
    rev = _git_run(repo_root, ["rev-parse", "HEAD"])
    return (rev.stdout or "").strip(), created


# ── Service principal ──────────────────────────────────────────────────────────

def _fetch_work_item(conn: Any, work_item_id: str) -> dict[str, Any]:
    cols = [
        "id", "repo", "locale", "slug", "state",
        "last_synced_hash", "staging_frontmatter", "staging_body", "staging_state",
        "staging_variantes",
    ]
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM work_item WHERE id = ?",
        [work_item_id],
    ).fetchall()
    if not rows:
        raise CockpitPublishError(f"work_item '{work_item_id}' introuvable")
    return dict(zip(cols, rows[0]))


def _normalize_frontmatter(raw: Any) -> dict[str, Any]:
    """staging_frontmatter peut arriver en dict (JSONB) ou en str JSON."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        import json

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CockpitPublishError(f"staging_frontmatter JSON invalide : {exc}") from exc
        if not isinstance(data, dict):
            raise CockpitPublishError("staging_frontmatter n'est pas un objet JSON")
        return data
    raise CockpitPublishError(
        f"staging_frontmatter type inattendu : {type(raw).__name__}"
    )


def _normalize_variantes(raw: Any) -> list[dict[str, Any]]:
    """``staging_variantes`` peut arriver en list (JSONB) ou en str JSON. ``None``→[]."""
    if raw is None:
        return []
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CockpitPublishError(f"staging_variantes JSON invalide : {exc}") from exc
    if not isinstance(raw, list):
        raise CockpitPublishError(
            f"staging_variantes doit être une liste, reçu {type(raw).__name__}"
        )
    out: list[dict[str, Any]] = []
    for v in raw:
        if not isinstance(v, dict) or not v.get("style") or not v.get("image"):
            raise CockpitPublishError(
                "staging_variantes : chaque entrée doit porter au moins {style, image}"
            )
        out.append(dict(v))
    return out


def commit_work_item(
    conn: Any,
    work_item_id: str,
    *,
    repo_root: Path | None = None,
    repo: str = DEFAULT_REPO,
    launch_set: str | None = None,
    commit_message: str | None = None,
    bot_name: str | None = None,
    bot_email: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    reindex_after: bool = True,
    require_approved: bool | None = None,
    mode: str = "create",
    asset_dir: Path | str | None = None,
) -> PublishResult:
    """Commite un ``work_item`` prêt comme Post ``.md`` dans le clone de contenu.

    Args:
        conn: ``DBConnAdapter`` (Postgres).
        work_item_id: id du work_item à publier (staging prêt).
        repo_root: racine du clone de contenu (défaut : ``content_repo_path()``
            = ``CONTENT_REPO_PATH``). Le ``.md`` est écrit sous
            ``src/content/posts/<locale>/<slug>.md``.
        repo: nom logique du repo (clé de jointure git_index ; défaut rimalab-v2).
        launch_set: si fourni, STAMPÉ dans ``frontmatter['launchSet']`` (le
            cockpit pose le marqueur de lot au commit des pages curées). Ne
            modifie pas le staging si ``None`` (le frontmatter peut déjà le porter).
        commit_message: message de commit (défaut généré).
        bot_name / bot_email: identité bot (défaut artiste-pipeline).
        force: autorise la réécriture d'un ``.md`` existant (sinon ADD-ONLY → erreur).
        dry_run: ne touche ni le FS ni git ni la DB ; retourne juste le ``.md``.
        reindex_after: réindexe ``git_index`` pour ce slug après commit (drift → 0).
        require_approved: gate HITL « seul l'approuvé entre dans git ».
            - ``None`` (défaut intelligent) : exige ``staging_state == 'approved'``
              UNIQUEMENT pour les items passés par le flux HITL Phase 2 (états
              ``generating`` / ``review_image`` / ``review_text`` / ``rejected``)
              — un item dans un de ces états n'a PAS fini sa revue → refus. Les
              chemins Phase 1 (``pending_commit`` / ``draft`` / ``none``) passent.
            - ``True`` : exige strictement ``approved`` (refuse tout le reste).
            - ``False`` : aucun gate (compat / commandes outillage).
        mode: ``"create"`` (défaut) = création ADD-ONLY (refuse de réécrire un
            ``.md`` existant sans ``force``). ``"update"`` = édition gardée d'une
            page DÉJÀ publiée : le ``.md`` DOIT exister, et on n'écrit que si le
            ``content_hash`` courant de git == ``last_synced_hash`` (optimistic
            concurrency). Si git a changé entre-temps → ``CockpitDriftError``
            (409 + drift), JAMAIS d'écrasement. Pas de ``force`` en update.
        asset_dir: (V5) dossier d'assets ``{slug}/`` à SCANNER (convention
            verrouillée ``{style}.png`` + ``{style}.svg``). Si fourni :
            ``scan_variantes`` produit ``variantes[]`` (``classique`` obligatoire
            + en premier, reste alpha), le bloc est émis dans le frontmatter du
            ``.md``, et les images sont COPIÉES (ADD-ONLY) sous
            ``public/img/{slug}/{style}.{png,svg}`` puis committées avec le ``.md``.
            La garde de distribution (profil page ↔ profils du style) est vérifiée
            AVANT le commit (refus si un style interdit est posé sur ``profil:facile``).
            Sans ``asset_dir`` : on retombe sur ``staging_variantes`` du work_item
            (émis tel quel, classique forcé en premier, sans copie d'images), ou
            aucun bloc variantes (back-compat : galerie front = image unique).

    Returns:
        ``PublishResult``.

    Raises:
        CockpitDriftError: mode ``update`` et git a changé depuis l'edit-load.
        CockpitPublishError: erreur métier (staging vide, collision ADD-ONLY,
            page absente en update, work_item introuvable…).
    """
    if mode not in ("create", "update"):
        raise CockpitPublishError(f"mode inconnu : {mode!r} (create|update)")
    root = (repo_root or content_repo_path())
    bot_name = bot_name or DEFAULT_BOT_NAME
    bot_email = bot_email or DEFAULT_BOT_EMAIL

    wi = _fetch_work_item(conn, work_item_id)
    locale = wi["locale"]
    slug = wi["slug"]

    # Gate HITL : seul l'approuvé entre dans git (cf. ADR §5). Vérifié AVANT toute
    # écriture FS/git.
    staging_state = (wi.get("staging_state") or "none")
    # États « en cours de revue HITL » : un commit y est interdit (revue non finie).
    _HITL_IN_PROGRESS = ("generating", "review_image", "review_text", "rejected")
    if require_approved is None:
        # Défaut intelligent : on bloque seulement si l'item est manifestement en
        # cours de revue HITL (non approuvé). Les chemins Phase 1 passent.
        gate = staging_state in _HITL_IN_PROGRESS
    else:
        gate = bool(require_approved)
    if gate and staging_state != "approved":
        raise CockpitPublishError(
            f"commit refusé : staging_state '{staging_state}' "
            f"(la revue HITL doit aboutir à 'approved' avant le commit)"
        )

    # En mode UPDATE, l'erreur la plus pertinente quand la page n'existe pas
    # encore dans git est « absente de git » (passer par la création) — vérifiée
    # AVANT le contrôle de staging vide (sinon on masque la vraie cause).
    if mode == "update":
        _upd_abs = root / f"src/content/posts/{locale}/{slug}.md"
        if not _upd_abs.exists():
            raise CockpitPublishError(
                f"UPDATE impossible : src/content/posts/{locale}/{slug}.md absent de git "
                f"(une page non publiée passe par la création, mode=create)"
            )

    fm = _normalize_frontmatter(wi.get("staging_frontmatter"))
    if not fm:
        raise CockpitPublishError(
            f"work_item '{work_item_id}' n'a pas de staging_frontmatter — rien à committer"
        )
    body = wi.get("staging_body")

    # Cohérence : le frontmatter doit refléter la clé d'identité du work_item.
    fm.setdefault("locale", locale)
    fm.setdefault("slug", slug)

    # Marqueur de lot (contrat partagé). Posé au commit des pages curées.
    if launch_set:
        fm["launchSet"] = launch_set

    notes: list[str] = []

    # ── Variantes (V5) : scan d'assets OU buffer staging → bloc frontmatter ──────
    # Source des variantes (priorité) :
    #   1. ``asset_dir`` fourni → SCAN du dossier ``{slug}/`` (convention). Le bot
    #      d'ingestion (V7) passe par là. Pas de table de mapping.
    #   2. sinon ``staging_variantes`` du work_item (porté en amont par le cockpit).
    # Absent des deux ⇒ pas de bloc variantes (back-compat : galerie front = image
    # unique). ``classique`` reste obligatoire + en premier (garanti par le scan).
    scanned: list[ScannedVariante] = []
    explicit_alt: dict[str, str] = {}
    staged = _normalize_variantes(wi.get("staging_variantes"))
    if asset_dir is not None:
        scanned = scan_variantes(asset_dir, slug=slug)
        # Un buffer staging peut porter des ``alt`` curés à respecter par style.
        explicit_alt = {
            str(v["style"]): str(v["alt"]) for v in staged if v.get("alt")
        }
    elif staged:
        # Variantes pré-portées dans le staging (pas de scan) : on émet tel quel,
        # ``classique`` forcé en premier (convention). Pas de placement d'images
        # (les chemins sont supposés déjà servis / placés par ailleurs).
        staged.sort(key=lambda v: (v.get("style") != CLASSIQUE_STYLE, str(v.get("style"))))

    variantes_fm: list[dict[str, Any]] = []
    if scanned:
        variantes_fm = variantes_to_frontmatter(scanned, fm, explicit=explicit_alt)
    elif staged:
        variantes_fm = staged

    if variantes_fm:
        # Garde de distribution (miroir front V3) : un style sans 'facile' sur une
        # planche profil:'facile' CASSERAIT le build front. On PRÉVIENT au commit.
        profil = str(fm.get("profil") or "enfant")
        style_profils = _load_style_profils(_content_styles_dir(root))
        violations = check_distribution(variantes_fm, profil, style_profils)
        if violations:
            raise CockpitPublishError(
                "garde de distribution : "
                + " ; ".join(violations)
                + " — retire la variante, change le profil de la planche, ou "
                "élargis les profils du style."
            )
        fm["variantes"] = variantes_fm
        result_variantes = variantes_fm
    else:
        result_variantes = []

    md = serialize_post_md(fm, body)

    rel_path = f"src/content/posts/{locale}/{slug}.md"

    result = PublishResult(
        work_item_id=work_item_id,
        repo=repo,
        locale=locale,
        slug=slug,
        rel_path=rel_path,
        md=md,
        dry_run=dry_run,
        bot_name=bot_name,
        bot_email=bot_email,
        variantes=result_variantes,
    )

    if dry_run:
        notes.append("dry-run : aucun fichier écrit, aucun commit, aucune écriture DB")
        if result_variantes:
            notes.append(
                f"dry-run : {len(result_variantes)} variante(s) seraient émises "
                f"(classique en premier) + images placées sous public/img/{slug}/"
            )
        result.notes = notes
        return result

    abs_path = root / rel_path

    if mode == "update":
        # Édition d'une page DÉJÀ publiée : le .md DOIT exister, et on n'écrit que
        # si le content_hash courant de git == last_synced_hash (optimistic
        # concurrency). Si git a bougé hors cockpit → refus (drift), pas d'écrasement.
        if not abs_path.exists():
            raise CockpitPublishError(
                f"UPDATE impossible : {rel_path} absent de git "
                f"(une page non publiée passe par la création, mode=create)"
            )
        expected = wi.get("last_synced_hash")
        if not expected:
            raise CockpitPublishError(
                "UPDATE impossible : last_synced_hash absent — chargez d'abord le "
                "buffer depuis git (edit-load) pour fixer la référence de concurrence"
            )
        current = parse_doc(abs_path, locale, rel_path).content_hash
        if current != expected:
            raise CockpitDriftError(
                f"UPDATE refusé : {rel_path} a changé dans git depuis le chargement "
                f"(édition hors cockpit) — réindexez et rechargez avant d'éditer",
                expected_hash=expected,
                current_hash=current,
            )
    else:
        # ADD-ONLY (création) : ne réécrit pas un .md existant sans force.
        if abs_path.exists() and not force:
            raise CockpitPublishError(
                f"ADD-ONLY : {rel_path} existe déjà — utilisez force=True pour réécrire "
                f"(ou mode=update pour éditer une page publiée)"
            )

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(md, encoding="utf-8")

    # Place les images de variantes à la convention public/img/{slug}/{style}.{png,svg}
    # (ADD-ONLY : une image existante n'est jamais écrasée sauf force). Seules les
    # variantes issues d'un SCAN (asset_dir) portent des fichiers source à copier ;
    # les variantes pré-portées (staged) supposent les images déjà servies.
    commit_paths: list[str] = [rel_path]
    if scanned:
        placed = _place_variante_images(root, slug, scanned, force=force)
        result.images_placed = placed
        if placed:
            commit_paths.append(f"public/img/{slug}")
            notes.append(f"{len(placed)} image(s) de variantes placée(s) sous public/img/{slug}/")

    # content_hash = même calcul que l'indexeur (parse_doc), pour que
    # last_synced_hash == git_index.content_hash → drift 0 garanti.
    parsed = parse_doc(abs_path, locale, rel_path)
    content_hash = parsed.content_hash
    result.content_hash = content_hash

    if commit_message:
        msg = commit_message
    elif mode == "update":
        msg = f"fix(content): update {locale}/{slug} via cockpit (bot)"
    else:
        msg = f"feat(content): publish {locale}/{slug} via cockpit (bot)"
    commit_hash, created = _bot_commit(
        root, commit_paths, msg, bot_name=bot_name, bot_email=bot_email
    )
    result.commit_hash = commit_hash
    result.committed = True
    if created:
        notes.append(f"commit {commit_hash[:10]} par {bot_name} <{bot_email}>")
    else:
        notes.append(f"contenu identique : aucun nouveau commit (HEAD {commit_hash[:10]})")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Met à jour le miroir : last_synced_hash + staging consommé.
    conn.execute(
        "UPDATE work_item SET last_synced_hash = ?, staging_state = ?, updated_at = ? "
        "WHERE id = ?",
        [content_hash, "none", now, work_item_id],
    )

    # Réindexe git_index pour ce slug (le miroir reflète le commit émis → drift 0).
    if reindex_after:
        from services.git_indexer import _upsert_git_index  # noqa: PLC0415

        outcome = _upsert_git_index(conn, repo, parsed, now)
        result.reindex = {"slug": f"{locale}/{slug}", "outcome": outcome}
        notes.append(f"git_index réindexé ({outcome})")

    result.notes = notes
    return result
