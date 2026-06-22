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
    "featured", "launchSet", "clusterId", "plateId",
]

# Clés date émises sans quotes (YAML date scalar natif), comme côté pipeline.
_DATE_KEYS = frozenset({"publishDate", "datePublication", "dateModification"})


class CockpitPublishError(RuntimeError):
    """Erreur métier du commit cockpit → git (collision ADD-ONLY, staging vide…)."""


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
    rel_path: str,
    message: str,
    *,
    bot_name: str,
    bot_email: str,
) -> tuple[str, bool]:
    """Stage + commit ``rel_path`` via l'identité bot.

    Retourne ``(commit_hash, created)`` : ``created`` est ``False`` si le commit
    n'a rien produit (contenu byte-identique sur un ``force`` rewrite) — cas
    idempotent toléré, pas une erreur. ``commit_hash`` est alors le HEAD courant.
    """
    r = _git_run(repo_root, ["add", rel_path])
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

    Returns:
        ``PublishResult``.
    """
    root = (repo_root or content_repo_path())
    bot_name = bot_name or DEFAULT_BOT_NAME
    bot_email = bot_email or DEFAULT_BOT_EMAIL

    wi = _fetch_work_item(conn, work_item_id)
    locale = wi["locale"]
    slug = wi["slug"]

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

    md = serialize_post_md(fm, body)

    rel_path = f"src/content/posts/{locale}/{slug}.md"
    notes: list[str] = []

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
    )

    if dry_run:
        notes.append("dry-run : aucun fichier écrit, aucun commit, aucune écriture DB")
        result.notes = notes
        return result

    abs_path = root / rel_path

    # ADD-ONLY : ne réécrit pas un .md existant sans force.
    if abs_path.exists() and not force:
        raise CockpitPublishError(
            f"ADD-ONLY : {rel_path} existe déjà — utilisez force=True pour réécrire"
        )

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(md, encoding="utf-8")

    # content_hash = même calcul que l'indexeur (parse_doc), pour que
    # last_synced_hash == git_index.content_hash → drift 0 garanti.
    parsed = parse_doc(abs_path, locale, rel_path)
    content_hash = parsed.content_hash
    result.content_hash = content_hash

    msg = commit_message or f"feat(content): publish {locale}/{slug} via cockpit (bot)"
    commit_hash, created = _bot_commit(
        root, rel_path, msg, bot_name=bot_name, bot_email=bot_email
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
