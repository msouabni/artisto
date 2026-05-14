"""Pipeline alwanbooks — consomme ``data/export/`` → R2 + ``rimalab-v2``.

Brief : MEP-v0/D — étape 7-9 du contrat (cf. ``docs/xchange/PIPELINE-CONTRACT.md`` §9).

Pipeline complète :

1. Lit ``data/export/manifest.json`` (output Brief C3).
2. Pour chaque leaf :
   a. Résout le PNG master (via ``export_mep_v0._resolve_master_png``).
   b. Génère les 4 variants R2 (PNG / WebP / Thumb / PDF) via Pillow + img2pdf.
   c. Upload atomique des 4 variants vers Cloudflare R2 (boto3 S3-compat).
3. Pour chaque Post JSON × 3 locales :
   a. Convertit le frontmatter JSON → YAML Astro (fichier ``.md``).
   b. Écrit dans ``rimalab-v2/src/content/posts/<locale>/<post_slug>.md``.
4. (optionnel) git add + commit + push sur ``rimalab-v2``.

Modes
-----
::

    # Mock complet (pas d'upload R2, pas de git push) — pour test pipeline
    python scripts/alwanbooks_pipeline.py --mock

    # R2 réel + écriture rimalab-v2 LOCAL (pas de push)
    python scripts/alwanbooks_pipeline.py --no-git-push

    # Production complète (R2 + push rimalab-v2)
    python scripts/alwanbooks_pipeline.py

    # Cibler un seul leaf (smoke test)
    python scripts/alwanbooks_pipeline.py --leaf-id firefighter_superhero --mock

Variables d'environnement
-------------------------

R2 (Cloudflare S3-compatible) :
- ``CLOUDFLARE_R2_ACCOUNT_ID``    : ID du compte Cloudflare.
- ``CLOUDFLARE_R2_ACCESS_KEY_ID`` : Access key R2.
- ``CLOUDFLARE_R2_SECRET_KEY``    : Secret key R2.
- ``CLOUDFLARE_R2_BUCKET``        : Bucket cible (défaut ``alwanbooks-assets``).
- ``CLOUDFLARE_R2_PUBLIC_BASE``   : Base URL publique (défaut
  ``https://assets.alwanbooks.com``).

rimalab-v2 :
- ``RIMALAB_REPO_PATH`` : path local du clone (défaut ``D:/projets/rimalab-v2``).

Idempotence et atomicité
------------------------

- Idempotent par hash : un variant déjà uploadé avec le même contenu est
  skip (``HEAD`` request avant upload, ETag comparison).
- Atomique par leaf : si l'upload d'un variant échoue, les autres variants
  du même leaf sont supprimés du bucket (rollback) — sauf en ``--mock``.
- Idempotent côté git : commit unique par run, message
  ``feat(content): export <N> coloriages depuis artiste-coloriage``.
  Pas de force push.

Sécurité
--------

- Les creds R2 ne sont **jamais** loggés ; seuls bucket/region/account_id
  hash sont visibles dans les logs.
- En ``--mock`` aucune connexion réseau n'est tentée.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Console Windows par défaut cp1252 → utf-8 explicit
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Réutilisation du résolveur PNG du script export (single source of truth).
import export_mep_v0  # noqa: E402

logger = logging.getLogger("alwanbooks_pipeline")

EXPORT_DIR = PROJECT_ROOT / "data" / "export"
MANIFEST_PATH = EXPORT_DIR / "manifest.json"
POSTS_DIR = EXPORT_DIR / "posts"
REPORT_PATH = PROJECT_ROOT / "docs" / "reports" / "2026-05-12_phase-mep-v0-D-alwanbooks-pipeline.md"

# Mock outputs (--mock mode)
MOCK_R2_DIR = EXPORT_DIR / "r2_simulated"

# R2 conventions (cf. PIPELINE-CONTRACT.md §3)
R2_PATHS = {
    "master": "coloriages/png/{slug}.png",
    "web":    "coloriages/webp/{slug}.webp",
    "thumb":  "coloriages/thumbs/{slug}.webp",
    "pdf":    "coloriages/pdf/{slug}.pdf",
}

# Configuration de conversion d'images (cf. contrat §3)
WEB_QUALITY = 85
WEB_METHOD = 6
THUMB_MAX = (400, 400)
THUMB_QUALITY = 80
PDF_PAGE_MM = (210, 297)         # A4 portrait
PDF_MARGIN_MM = 10

DEFAULT_RIMALAB_PATH = Path(os.environ.get(
    "RIMALAB_REPO_PATH", "D:/projets/rimalab-v2",
))


# ── Données ──────────────────────────────────────────────────────────────────


@dataclass
class LeafResult:
    """Résultat de traitement d'un leaf (1 image + 3 Posts)."""

    leaf_id: str
    r2_slug: str
    post_slugs: dict[str, str]
    image_id: str
    master_path: Path | None = None
    variants_uploaded: dict[str, str] = field(default_factory=dict)  # variant -> r2_key
    variants_skipped: dict[str, str] = field(default_factory=dict)   # idempotent skip
    posts_written: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PipelineRunSummary:
    mode: str
    total_leaves: int = 0
    leaves_ok: int = 0
    leaves_failed: int = 0
    leaves_no_master: int = 0
    variants_uploaded: int = 0
    variants_skipped: int = 0
    posts_written: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    leaves: list[LeafResult] = field(default_factory=list)


# ── Conversion d'images (Pillow + img2pdf) ──────────────────────────────────


def _ensure_rgb(im):
    """Force RGB pour WebP (Pillow le supporte RGBA mais on uniformise)."""
    if im.mode in ("RGBA", "LA"):
        bg = im.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def convert_master_to_variants(master: Path) -> dict[str, bytes]:
    """Convertit un PNG master en 4 variants (bytes).

    Retourne ``{'master': png_bytes, 'web': webp_bytes, 'thumb': webp_bytes,
    'pdf': pdf_bytes}``. Le master est lu tel quel (pas de re-encoding) pour
    préserver la transparence si présente (cf. contrat §3).
    """
    from PIL import Image
    import img2pdf

    out: dict[str, bytes] = {}
    out["master"] = master.read_bytes()

    with Image.open(master) as im:
        im.load()  # déterministe pour Pillow lazy load
        # Web variant — même résolution, qualité 85, RGB
        web_im = _ensure_rgb(im.copy())
        buf = io.BytesIO()
        web_im.save(buf, format="WEBP", quality=WEB_QUALITY, method=WEB_METHOD)
        out["web"] = buf.getvalue()

        # Thumb — 400×400 max, Lanczos, qualité 80
        thumb_im = _ensure_rgb(im.copy())
        thumb_im.thumbnail(THUMB_MAX, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        thumb_im.save(buf, format="WEBP", quality=THUMB_QUALITY)
        out["thumb"] = buf.getvalue()

    # PDF A4 portrait, fit, marges 10 mm
    layout = img2pdf.get_layout_fun(
        pagesize=(
            img2pdf.mm_to_pt(PDF_PAGE_MM[0]), img2pdf.mm_to_pt(PDF_PAGE_MM[1]),
        ),
        imgsize=None,
        border=(img2pdf.mm_to_pt(PDF_MARGIN_MM), img2pdf.mm_to_pt(PDF_MARGIN_MM)),
        fit=img2pdf.FitMode.into,
        auto_orient=False,
    )
    out["pdf"] = img2pdf.convert(out["master"], layout_fun=layout)

    return out


# ── Upload R2 (boto3 S3-compatible) ─────────────────────────────────────────


class R2Client:
    """Client R2 minimaliste — wrapper boto3 S3 endpoint Cloudflare."""

    def __init__(self, *, account_id: str, access_key: str, secret_key: str,
                 bucket: str):
        import boto3
        self.bucket = bucket
        self._endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        self._s3 = boto3.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )

    def head(self, key: str) -> dict | None:
        from botocore.exceptions import ClientError
        try:
            return self._s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def put(self, key: str, body: bytes, content_type: str) -> str:
        """Upload un objet, retourne l'ETag."""
        resp = self._s3.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type,
        )
        return resp.get("ETag", "").strip('"')

    def delete(self, key: str) -> None:
        from botocore.exceptions import ClientError
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=key)
        except ClientError:
            pass  # best-effort rollback


def _md5(body: bytes) -> str:
    return hashlib.md5(body).hexdigest()  # noqa: S324 — used only for ETag comparison


def _r2_client_from_env() -> R2Client | None:
    """Construit le client R2 depuis l'environnement. ``None`` si creds absents."""
    account = os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID")
    access = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID")
    secret = os.environ.get("CLOUDFLARE_R2_SECRET_KEY")
    bucket = os.environ.get("CLOUDFLARE_R2_BUCKET", "alwanbooks-assets")
    if not (account and access and secret):
        return None
    return R2Client(
        account_id=account, access_key=access, secret_key=secret,
        bucket=bucket,
    )


_CONTENT_TYPES = {
    "master": "image/png",
    "web":    "image/webp",
    "thumb":  "image/webp",
    "pdf":    "application/pdf",
}


def _upload_variants_real(
    r2: R2Client, slug: str, variants: dict[str, bytes],
) -> tuple[dict[str, str], dict[str, str]]:
    """Upload réel. Retourne ``(uploaded, skipped)`` keyed par variant.

    Idempotence : ``HEAD`` puis comparaison ETag. Si ETag matche le MD5 local,
    on saute l'upload.
    """
    uploaded: dict[str, str] = {}
    skipped: dict[str, str] = {}
    rollback_keys: list[str] = []
    try:
        for variant, body in variants.items():
            key = R2_PATHS[variant].format(slug=slug)
            existing = r2.head(key)
            if existing is not None:
                existing_etag = existing.get("ETag", "").strip('"')
                if existing_etag == _md5(body):
                    skipped[variant] = key
                    continue
            r2.put(key, body, _CONTENT_TYPES[variant])
            uploaded[variant] = key
            rollback_keys.append(key)
    except Exception:
        # Rollback : supprimer les variants déjà uploadés DANS CE CALL
        for k in rollback_keys:
            r2.delete(k)
        raise
    return uploaded, skipped


def _upload_variants_mock(
    slug: str, variants: dict[str, bytes],
) -> tuple[dict[str, str], dict[str, str]]:
    """Mock : écrit dans ``data/export/r2_simulated/<r2_path>``."""
    uploaded: dict[str, str] = {}
    for variant, body in variants.items():
        key = R2_PATHS[variant].format(slug=slug)
        out = MOCK_R2_DIR / key
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)
        uploaded[variant] = key
    return uploaded, {}


# ── Conversion JSON Post → MD Astro ─────────────────────────────────────────


_YAML_SCALAR_PASSTHROUGH = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")


def _yaml_quote(value: str) -> str:
    """Quote une string pour YAML (simple quote, escape doublé)."""
    return "'" + value.replace("'", "''") + "'"


def _emit_yaml_value(value: Any, indent: int = 0) -> str:
    """Émet une valeur YAML simple. Supporte str, int, bool, None, list[str]."""
    pad = "  " * indent
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _yaml_quote(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            lines.append(f"{pad}  - {_emit_yaml_value(item, indent + 1)}")
        return "\n" + "\n".join(lines)
    raise ValueError(f"YAML value not supported: {type(value).__name__}")


# Champs à écrire dans le frontmatter (ordre stable, cohérent avec
# l'exemple PIPELINE-CONTRACT.md). Whitelist stricte : ``r2_slug``,
# ``image_id``, ``_pipeline``, ``schema_version`` ne sont **pas** émis dans
# le MD (passthrough toléré côté rimalab-v2 mais on garde le frontmatter
# propre — arbitrage 2026-05-12).
_FRONTMATTER_ORDER = [
    "locale", "slug", "title", "title_card", "description", "keywords",
    "categoryId", "themeIds", "ageMin", "ageMax", "niveauDifficulte",
    "imageSource", "imageWeb", "imageThumb", "imagePdf",
    "status", "datePublication", "dateModification", "featured",
]


#: Clés où émettre la valeur **sans quotes** (date YAML native, scalaires
#: booléens/entiers, etc.). Le sample ``chat-bibliotheque.md`` montre que
#: ``datePublication: 2026-04-25`` est sans quotes (date YAML inférée).
_FRONTMATTER_DATE_KEYS = frozenset({"datePublication", "dateModification"})


def post_json_to_md(post: dict, *, body_text: str | None = None) -> str:
    """Convertit un Post JSON (frontmatter v2.4) en MD Astro complet.

    Le body markdown par défaut est un placeholder simple. ``body_text`` peut
    fournir un contenu rédigé (généré par LLM en amont, par exemple).
    """
    lines: list[str] = ["---"]
    for key in _FRONTMATTER_ORDER:
        if key not in post:
            continue
        val = post[key]
        # Skip champs vides scalaires (sauf bool=False qu'on garde)
        if val is None:
            continue
        if isinstance(val, str) and not val:
            continue
        if isinstance(val, list) and not val and key != "themeIds":
            # themeIds: [] est attendu par Zod (default []), on le garde.
            continue
        # Dates : émission sans quotes (YAML date scalar).
        if key in _FRONTMATTER_DATE_KEYS and isinstance(val, str):
            lines.append(f"{key}: {val}")
            continue
        emitted = _emit_yaml_value(val)
        if emitted.startswith("\n"):
            lines.append(f"{key}:{emitted}")
        else:
            lines.append(f"{key}: {emitted}")

    lines.append("---")
    lines.append("")
    if body_text:
        lines.append(body_text.rstrip())
    else:
        # Placeholder minimal — sera enrichi par un brief content-writing post-D.
        title = post.get("title", "")
        description = post.get("description", "")
        lines.append(f"## {title}")
        lines.append("")
        lines.append(description)
    lines.append("")
    return "\n".join(lines)


#: Mapping ``leaf_id`` → ``categoryId`` côté rimalab-v2.
#:
#: Arbitrages reçus de rimalab-v2 (2026-05-12, commit rimalab ``5975195``) :
#: 6 nouvelles Categories créées côté plateforme :
#:
#: - ``animals_lions``  (existant — big cats / lion)
#: - ``animals_birds``  (oiseaux : peacock, owl, turkey_bird, penguin…)
#: - ``animals_marine`` (faune marine : crab, shark, whale, octopus…)
#: - ``animals_pets``   (animaux domestiques : rabbit, hamster, cat,
#:   bulldog, labrador, donkey, sheep_with_lamb…)
#: - ``animals_wild``   (faune sauvage : elephant, fox, wolf, tiger,
#:   leopard, bear, kangaroo, butterfly, bee, dragon…)
#: - ``general_humans`` (humains / personnages / professions / sports)
#: - ``objects_things`` (objets / véhicules / outils / motifs — fallback)
#: - ``animals_cats``   (chats — existant, conservé pour compat)
#: - ``letters_arabic`` (alphabet — existant)
#:
#: Le mapper applique les règles **dans l'ordre du brief
#: 2026-05-12** (par priorité) — premier match gagne.
#:
#: Depuis 2026-05-15 : registry partagé ``data/categories_registry.json``
#: est la source unique de vérité pour les categoryId acceptés. Le mapper
#: refuse fail-fast d'émettre un id qui n'y est pas présent.

#: Path du registry partagé (source unique de vérité des categoryId).
CATEGORIES_REGISTRY_PATH = PROJECT_ROOT / "data" / "categories_registry.json"


def _load_categories_registry() -> dict:
    """Charge le registry JSON depuis ``data/categories_registry.json``.

    Cache module-level : le fichier n'est lu qu'une fois au boot.
    """
    return json.loads(CATEGORIES_REGISTRY_PATH.read_text(encoding="utf-8"))


#: Cache module-level du registry (chargé une fois au boot).
CATEGORIES_REGISTRY = _load_categories_registry()

#: frozenset des IDs valides — utilisé par l'assert fail-fast du mapper.
KNOWN_CATEGORY_IDS = frozenset(
    c["id"] for c in CATEGORIES_REGISTRY["categories"]
)

#: Big cats à exclure de ``animals_pets`` même si "cat" matche dans le
#: nom (utilisé en règle 4).
_BIG_CATS_PATTERNS = (
    "tiger", "leopard", "jaguar", "cheetah", "puma", "panther", "lynx",
    "cougar",
)

#: Règle 2 — oiseaux.
_BIRDS_RE = re.compile(
    r"peacock|owl|turkey_bird|penguin|parrot|eagle|hawk|swan|falcon|"
    r"flamingo|hummingbird|crow|sparrow|pigeon|dove|woodpecker",
)

#: Règle 3 — faune marine.
_MARINE_RE = re.compile(
    r"crab|shark|sea_turtle|seahorse|starfish|whale|harp_seal|dolphin|"
    r"octopus|jellyfish|stingray|squid|lobster|clownfish",
)

#: Règle 4 — animaux domestiques (le filtre big_cats est appliqué
#: séparément avant le match ``cat``).
_PETS_RE = re.compile(
    r"rabbit|hamster|guinea_pig|french_bulldog|labrador|pet_turtle|"
    r"dairy_cow|donkey|sheep_with_lamb|eid_al_adha_sheep|persian_cat|"
    r"british_shorthair_cat|maine_coon_cat",
)

#: Règle 5 — faune sauvage (non chat, non oiseau, non marin, non pet).
_WILD_RE = re.compile(
    r"elephant|fox|wolf|tiger|leopard|jaguar|bear|alpaca|armadillo|"
    r"chimpanzee|orangutan|sloth|hyena|zebra|buffalo|musk_ox|beaver|"
    r"butterfly|bee|snail|spider|griffin|phoenix|dragon|kangaroo|"
    r"antelope|giraffe|rhino|hippo|gorilla|panda|deer|moose",
)

#: Règle 6a — humains via préfixe profession / personnage.
_HUMANS_PREFIXES = (
    "firefighter", "police", "doctor", "teacher", "baker", "astronaut",
    "pilot", "farmer", "fisherman", "dancer", "chef", "musician",
    "painter", "locksmith", "roofer", "tour_guide", "house_painter",
    "snowboarder", "speed_skater", "breakdancer", "wizard", "knight",
    "princess", "fairy", "elf_", "iron_man", "captain_america",
    "robot_superhero", "scooby_doo", "spongebob", "stitch_from",
    "mirabel", "moana", "tintin", "yeti", "football_coach",
)

#: Règle 6b — humains via mots-clés contenus dans le ``leaf_id``.
_HUMANS_RE = re.compile(
    r"human|kid|child|woman|man\b|baby|teenager|cartoon|yoga_pose|"
    r"family_|water_skiing|superhero",
)

#: Règle 7 — lettres / alphabet.
_LETTERS_RE = re.compile(r"lettre|letter_|alphabet|arabic")

#: Fallback ultime (règle 8) : objets / véhicules / outils / motifs.
_CATEGORY_DEFAULT = "objects_things"


def map_leaf_to_category(leaf_id: str | None) -> str:
    """Mappe un ``leaf_id`` taxonomique à un ``categoryId`` rimalab-v2.

    Routing par règles ordonnées (brief 2026-05-12) :

    1. ``leaf_id`` startswith ``lion``                 → ``animals_lions``
    2. match oiseaux                                    → ``animals_birds``
    3. match faune marine                               → ``animals_marine``
    4. match animaux domestiques (ou ``cat`` non big cat) → ``animals_pets``
    5. match faune sauvage                              → ``animals_wild``
    6. match humains (préfixe profession / mots-clés)   → ``general_humans``
    7. match lettres / alphabet                          → ``letters_arabic``
    8. fallback                                          → ``objects_things``

    Retourne le fallback si ``leaf_id`` est ``None`` / vide.

    Garantie : la valeur retournée est **toujours** présente dans
    ``KNOWN_CATEGORY_IDS`` (cf. registry ``data/categories_registry.json``).
    Si une nouvelle règle est ajoutée qui émet un id inconnu, l'assert
    final lève ``AssertionError`` pour fail-fast (bug détecté en local
    avant push).
    """
    if not leaf_id:
        result = _CATEGORY_DEFAULT
    else:
        lid = leaf_id.lower()
        result = None

        # 1. Lions (gardé sur startswith pour matcher "lion_in_savanna",
        # "lion_cub", etc. sans capturer ``animal_mandala_lion_head``).
        if lid.startswith("lion"):
            result = "animals_lions"
        # Cas particulier : feuille décorative ``animal_mandala_lion_head`` —
        # malgré ``lion`` à l'intérieur, c'est un motif → ``objects_things``
        # (matche via fallback final). Pas de règle dédiée.

        # 2. Oiseaux
        elif _BIRDS_RE.search(lid):
            result = "animals_birds"

        # 3. Faune marine
        elif _MARINE_RE.search(lid):
            result = "animals_marine"

        # 4. Animaux domestiques. Le mot-clé ``cat`` doit matcher seulement
        # si ce n'est pas un big cat (tigre / léopard / jaguar / etc.).
        elif _PETS_RE.search(lid):
            result = "animals_pets"
        elif ("_cat" in lid or "cat_" in lid) and not any(
            bc in lid for bc in _BIG_CATS_PATTERNS
        ):
            result = "animals_pets"

        # 5. Faune sauvage
        elif _WILD_RE.search(lid):
            result = "animals_wild"

        # 6. Humains — préfixe profession ou mots-clés
        if result is None:
            for prefix in _HUMANS_PREFIXES:
                if lid.startswith(prefix) or f"_{prefix}" in lid:
                    result = "general_humans"
                    break
        if result is None and _HUMANS_RE.search(lid):
            result = "general_humans"

        # 7. Lettres alphabet
        if result is None and _LETTERS_RE.search(lid):
            result = "letters_arabic"

        # 8. Fallback
        if result is None:
            result = _CATEGORY_DEFAULT

    # Fail-fast : refuse d'émettre un id qui n'est pas dans le registry.
    assert result in KNOWN_CATEGORY_IDS, (
        f"mapper emitted unknown categoryId: {result!r} "
        f"(leaf_id={leaf_id!r}). Known ids: {sorted(KNOWN_CATEGORY_IDS)}"
    )
    return result


def _ensure_post_complete(post: dict) -> dict:
    """Comble les champs requis manquants avec des défauts sains.

    Le contrat exige ``categoryId``, ``ageMin``, ``ageMax``, ``niveauDifficulte``.
    En v0, ces champs sont vides côté pipeline ; on injecte des fallbacks
    pour que le build Astro Zod passe quand même.

    ``categoryId`` est calculé via ``map_leaf_to_category`` depuis le bloc
    ``_pipeline.leaf_id`` si présent (ajouté par l'export script C3).

    Filtre côté ``keywords`` : strip items <2 chars (HARD cap Zod
    ``items 2-30``). Garde l'ordre original.
    """
    p = dict(post)
    p.setdefault("locale", "fr")
    p.setdefault("slug", post.get("slug", ""))
    p.setdefault("title", "")
    p.setdefault("title_card", post.get("title", "")[:40] if post.get("title") else "")
    p.setdefault("description", "")

    # Filtrer keywords <2 ou >30 chars (HARD cap Zod plateforme).
    raw_kw = p.get("keywords") or []
    if isinstance(raw_kw, list):
        p["keywords"] = [
            k for k in raw_kw
            if isinstance(k, str) and 2 <= len(k) <= 30
        ]
    else:
        p["keywords"] = []

    # categoryId : si vide, mapper depuis leaf_id (bloc _pipeline).
    if not p.get("categoryId"):
        leaf_id = None
        pipeline_block = post.get("_pipeline") or {}
        if isinstance(pipeline_block, dict):
            leaf_id = pipeline_block.get("leaf_id")
        p["categoryId"] = map_leaf_to_category(leaf_id)

    if not p.get("themeIds"):
        p["themeIds"] = []
    if "ageMin" not in p:
        p["ageMin"] = 4
    if "ageMax" not in p:
        p["ageMax"] = 10
    if "niveauDifficulte" not in p:
        p["niveauDifficulte"] = "easy"
    p.setdefault("status", "approved")
    if "datePublication" not in p or not p["datePublication"]:
        p["datePublication"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # ``dateModification`` est requis par Zod V2 plateforme (bloqueur B3
    # acté avec dev rimalab 2026-05-12). Au premier export il vaut
    # ``datePublication`` ; à chaque ré-export il sera mis à jour (logique
    # à brancher dans un brief séparé — pour l'instant : valeur initiale).
    if "dateModification" not in p or not p["dateModification"]:
        p["dateModification"] = p["datePublication"]
    p.setdefault("featured", False)
    return p


# ── Écriture rimalab-v2 ──────────────────────────────────────────────────────


def write_post_md(
    rimalab_root: Path, locale: str, slug: str, md_content: str,
) -> Path:
    """Écrit un fichier MD Astro dans ``rimalab-v2/src/content/posts/<loc>/``."""
    out_dir = rimalab_root / "src" / "content" / "posts" / locale
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.md"
    out_path.write_text(md_content, encoding="utf-8")
    return out_path


# ── Sync categories (registry → rimalab MDs) ────────────────────────────────


#: Ordre déterministe des champs YAML frontmatter pour les MDs catégories.
#: (cohérent avec le brief tactique 2026-05-14 et calque des .md existants).
_CATEGORY_FRONTMATTER_ORDER = (
    "id", "slug_i18n", "name_i18n", "description_i18n", "keywords_i18n",
    "parent_id", "weight",
)

#: Ordre déterministe des locales dans les blocs i18n.
_CATEGORY_I18N_LOCALES_ORDER = ("ar", "fr", "en")


def category_to_md(category: dict) -> str:
    """Convertit une entrée registry en MD Astro frontmatter complet.

    Calque le format des `.md` existants côté ``rimalab-v2/src/content/categories/``:

    - Quote simple sur les strings (apostrophe doublée pour escape).
    - Ordre déterministe des champs : id → slug_i18n → name_i18n →
      description_i18n → keywords_i18n → parent_id → weight.
    - Locales toujours dans l'ordre ar/fr/en.
    - Indentation 2 espaces.
    - Newlines en LF universel.
    - Newline final unique après le body.
    - ``scope_note`` **n'est PAS émis** (champ interne du registry).
    """
    lines: list[str] = ["---"]

    for key in _CATEGORY_FRONTMATTER_ORDER:
        if key == "id":
            lines.append(f"id: {_yaml_quote(category['id'])}")
        elif key == "parent_id":
            pid = category.get("parent_id")
            if pid is None:
                lines.append("parent_id: null")
            else:
                lines.append(f"parent_id: {_yaml_quote(pid)}")
        elif key == "weight":
            lines.append(f"weight: {int(category['weight'])}")
        elif key in ("slug_i18n", "name_i18n", "description_i18n"):
            lines.append(f"{key}:")
            block = category[key]
            for loc in _CATEGORY_I18N_LOCALES_ORDER:
                lines.append(f"  {loc}: {_yaml_quote(block[loc])}")
        elif key == "keywords_i18n":
            lines.append("keywords_i18n:")
            block = category[key]
            for loc in _CATEGORY_I18N_LOCALES_ORDER:
                lines.append(f"  {loc}:")
                for kw in block[loc]:
                    lines.append(f"    - {_yaml_quote(kw)}")

    lines.append("---")
    lines.append("")
    lines.append(category["body"].rstrip())
    lines.append("")  # newline final
    return "\n".join(lines)


def _write_if_changed(path: Path, content: str) -> bool:
    """Écrit ``content`` dans ``path`` uniquement si les bytes diffèrent.

    Compare les bytes existants vs nouveaux (SHA-256 inutile vu la taille
    < 2 KB). LF universel — pas de transformation OS-spécifique. Encodage
    UTF-8 sans BOM (cohérent avec les .md existants).

    Retourne ``True`` si écrit, ``False`` si skipped (idempotent).
    """
    new_bytes = content.encode("utf-8")
    # Vérif anti-BOM : on n'émet jamais de BOM.
    assert not new_bytes.startswith(b"\xef\xbb\xbf"), (
        "_write_if_changed must never emit a UTF-8 BOM"
    )
    if path.exists():
        existing = path.read_bytes()
        if existing == new_bytes:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline='' pour éviter la traduction CRLF par Python sur Windows.
    with path.open("wb") as f:
        f.write(new_bytes)
    return True


@dataclass
class SyncCategoriesSummary:
    total: int = 0
    wrote: int = 0
    skipped: int = 0
    files_wrote: list[Path] = field(default_factory=list)
    files_skipped: list[Path] = field(default_factory=list)


def sync_categories(rimalab_root: Path, registry: dict | None = None) -> SyncCategoriesSummary:
    """Régénère les MDs ``src/content/categories/*.md`` depuis le registry.

    Idempotent byte-identique : un fichier dont le contenu ne change pas
    n'est pas réécrit (compare bytes). Retourne un summary
    ``(wrote, skipped, total)``.

    Le champ interne ``scope_note`` n'est jamais propagé dans les MDs.
    """
    if registry is None:
        registry = CATEGORIES_REGISTRY
    out_dir = rimalab_root / "src" / "content" / "categories"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = SyncCategoriesSummary()
    for cat in registry["categories"]:
        md = category_to_md(cat)
        # Filet de sécurité : scope_note JAMAIS dans le contenu écrit.
        assert "scope_note" not in md, (
            f"category {cat['id']}: scope_note leaked into MD content"
        )
        out_path = out_dir / f"{cat['id']}.md"
        if _write_if_changed(out_path, md):
            summary.wrote += 1
            summary.files_wrote.append(out_path)
        else:
            summary.skipped += 1
            summary.files_skipped.append(out_path)
        summary.total += 1
    logger.info(
        "[sync-categories] wrote=%d skipped=%d total=%d",
        summary.wrote, summary.skipped, summary.total,
    )
    return summary


#: Nom de branche par défaut pour les exports MEP v0. Rimalab-v2 review
#: en PR avant merge — pas de push direct sur ``main`` (arbitrage 2026-05-12).
DEFAULT_EXPORT_BRANCH = "content/export-mep-v0"


def git_commit_push(
    rimalab_root: Path, message: str, *,
    branch: str = DEFAULT_EXPORT_BRANCH, push: bool = True,
) -> tuple[int, str]:
    """Crée une branche dédiée, commit, et push optionnellement.

    Workflow :
    1. ``git checkout -B <branch>`` (depuis l'état courant — sera créé ou
       remis à zéro si la branche existait déjà).
    2. ``git add src/content/posts/`` et commit (idempotent : si rien à
       commiter, on continue sans erreur).
    3. Si ``push=True`` : ``git push -u origin <branch>`` (le PR doit être
       ouvert ensuite manuellement côté rimalab-v2 ou via ``gh pr create``
       dans un brief séparé).

    Retourne ``(exit_code, log_concaténé)``. ``exit_code=0`` si OK.
    """
    if not (rimalab_root / ".git").exists():
        return 1, f"Not a git repo: {rimalab_root}"

    cmds: list[list[str]] = [
        ["git", "checkout", "-B", branch],
        ["git", "add", "src/content/posts/"],
        ["git", "commit", "-m", message],
    ]
    if push:
        cmds.append(["git", "push", "-u", "origin", branch])

    out_chunks: list[str] = []
    for cmd in cmds:
        r = subprocess.run(  # noqa: S603 — controlled commands
            cmd, cwd=str(rimalab_root), capture_output=True, text=True,
            encoding="utf-8",
        )
        out_chunks.append(f"$ {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
        # Tolérer "nothing to commit" sur le commit (rerun idempotent).
        if r.returncode != 0:
            stdout_lower = (r.stdout or "").lower()
            if "nothing to commit" in stdout_lower:
                continue
            return r.returncode, "\n".join(out_chunks)
    return 0, "\n".join(out_chunks)


# ── Orchestrateur ────────────────────────────────────────────────────────────


def run_pipeline(
    *, mock: bool, no_git_push: bool, leaf_id: str | None,
    limit: int | None, rimalab_root: Path,
) -> PipelineRunSummary:
    """Exécute la pipeline complète. Retourne le summary."""
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Manifest introuvable : {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    leaves = manifest.get("leaves", [])
    if leaf_id is not None:
        leaves = [l for l in leaves if l["leaf_id"] == leaf_id]
    if limit is not None and limit >= 0:
        leaves = leaves[:limit]

    mode = "MOCK" if mock else ("NO-GIT-PUSH" if no_git_push else "PRODUCTION")
    summary = PipelineRunSummary(mode=mode, total_leaves=len(leaves))

    r2: R2Client | None = None
    if not mock:
        r2 = _r2_client_from_env()
        if r2 is None:
            raise RuntimeError(
                "Creds R2 absents (CLOUDFLARE_R2_ACCOUNT_ID, "
                "CLOUDFLARE_R2_ACCESS_KEY_ID, CLOUDFLARE_R2_SECRET_KEY). "
                "Lancer avec --mock pour bypass."
            )

    logger.info("Pipeline %s — %d leaves à traiter", mode, len(leaves))

    for leaf in leaves:
        leaf_id_v = leaf["leaf_id"]
        r2_slug_v = leaf["r2_slug"]
        post_slugs = leaf["post_slugs"]
        image_id = leaf["image_id"]

        result = LeafResult(
            leaf_id=leaf_id_v, r2_slug=r2_slug_v, post_slugs=post_slugs,
            image_id=image_id,
        )

        # 1. Résoudre le master
        target_id = image_id.replace("benchmark:", "")
        master = export_mep_v0._resolve_master_png(target_id)
        if master is None:
            result.errors.append(f"master PNG introuvable pour {target_id}")
            summary.leaves_no_master += 1
            summary.leaves_failed += 1
            summary.errors.append((leaf_id_v, result.errors[-1]))
            summary.leaves.append(result)
            continue
        result.master_path = master

        # 2. Convertir en 4 variants
        try:
            variants = convert_master_to_variants(master)
        except Exception as exc:
            result.errors.append(f"conversion failed: {exc}")
            summary.leaves_failed += 1
            summary.errors.append((leaf_id_v, result.errors[-1]))
            summary.leaves.append(result)
            logger.exception("Conversion failed for %s", leaf_id_v)
            continue

        # 3. Upload R2 (réel ou mock)
        try:
            if mock:
                uploaded, skipped = _upload_variants_mock(r2_slug_v, variants)
            else:
                assert r2 is not None
                uploaded, skipped = _upload_variants_real(r2, r2_slug_v, variants)
            result.variants_uploaded = uploaded
            result.variants_skipped = skipped
            summary.variants_uploaded += len(uploaded)
            summary.variants_skipped += len(skipped)
        except Exception as exc:
            result.errors.append(f"upload failed: {exc}")
            summary.leaves_failed += 1
            summary.errors.append((leaf_id_v, result.errors[-1]))
            summary.leaves.append(result)
            logger.exception("Upload failed for %s", leaf_id_v)
            continue

        # 4. Convertir + écrire les Posts MD × 3 locales
        for locale, post_slug in post_slugs.items():
            json_path = POSTS_DIR / locale / f"{post_slug}.json"
            if not json_path.is_file():
                result.errors.append(f"post JSON manquant: {json_path}")
                continue
            post = json.loads(json_path.read_text(encoding="utf-8"))
            post = _ensure_post_complete(post)
            md = post_json_to_md(post)
            written = write_post_md(rimalab_root, locale, post_slug, md)
            result.posts_written.append(written)
            summary.posts_written += 1

        summary.leaves_ok += 1
        summary.leaves.append(result)

    # 5. (optionnel) git commit + push sur rimalab-v2
    if not mock and not no_git_push and summary.posts_written > 0:
        msg = (
            f"feat(content): export {summary.leaves_ok} coloriages depuis "
            "artiste-coloriage MEP v0"
        )
        rc, out = git_commit_push(rimalab_root, msg)
        if rc != 0:
            summary.errors.append(("__git__", f"git push failed (rc={rc}): {out[-500:]}"))
        else:
            logger.info("git commit+push OK sur %s", rimalab_root)

    return summary


# ── Rapport + stdout summary ─────────────────────────────────────────────────


def write_report(summary: PipelineRunSummary) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Phase MEP v0 / D — Pipeline alwanbooks (R2 + rimalab-v2)")
    lines.append("Date : 2026-05-12")
    lines.append("")
    lines.append("## Contexte")
    lines.append("")
    lines.append(
        "Pipeline qui consomme `data/export/` (output Brief C3) et produit "
        "les 4 variants R2 (PNG/WebP/Thumb/PDF) + écrit les MD Astro dans "
        "`rimalab-v2/src/content/posts/{ar,fr,en}/`."
    )
    lines.append("")
    lines.append("## Résultats")
    lines.append("")
    lines.append(f"- Mode : **{summary.mode}**")
    lines.append(f"- Leaves traités : {summary.total_leaves}")
    lines.append(f"  - OK : **{summary.leaves_ok}**")
    lines.append(f"  - Failed : {summary.leaves_failed}")
    lines.append(f"  - No master PNG : {summary.leaves_no_master}")
    lines.append(f"- Variants R2 uploaded : {summary.variants_uploaded}")
    lines.append(f"- Variants R2 skipped (idempotent ETag match) : {summary.variants_skipped}")
    lines.append(f"- Posts MD écrits : {summary.posts_written}")
    lines.append("")
    if summary.errors:
        lines.append("### Erreurs (extrait, max 20)")
        lines.append("")
        for leaf_id, msg in summary.errors[:20]:
            lines.append(f"- `{leaf_id}` : {msg}")
        if len(summary.errors) > 20:
            lines.append(f"- … ({len(summary.errors) - 20} autres tronquées)")
        lines.append("")
    lines.append("## Points d'attention")
    lines.append("")
    lines.append(
        "- **Mode MOCK** : écrit les 4 variants dans `data/export/r2_simulated/` "
        "au lieu d'upload Cloudflare R2. Utile pour smoke test sans creds."
    )
    lines.append(
        "- **Idempotence R2** : HEAD + ETag comparison avant PUT. Un rerun "
        "sur les mêmes masters skip 100 % des variants (skipped count)."
    )
    lines.append(
        "- **Atomicité par leaf** : si un variant échoue, les autres variants "
        "du même leaf sont supprimés du bucket (rollback)."
    )
    lines.append(
        "- **Champs `categoryId` / `ageMin` / `ageMax` / `niveauDifficulte`** : "
        "défauts injectés (`uncategorized` / 4 / 10 / `easy`) car la table "
        "`image_taxonomy_tag` n'est pas peuplée. À enrichir dans un brief séparé."
    )
    lines.append(
        "- **PNG masters** : résolus via `ARTISTE_MASTER_ROOTS` (env) ou "
        "`D:/projets/artiste-coloriage` par défaut. Le worktree peut donc "
        "consommer les masters du repo principal sans les dupliquer."
    )
    lines.append("")
    lines.append("## Décision / Action suivante")
    lines.append("")
    if summary.mode == "MOCK":
        lines.append(
            f"- ✅ Mock OK sur {summary.leaves_ok} leaves. Vérifier "
            "`data/export/r2_simulated/` puis configurer creds R2."
        )
    elif summary.mode == "NO-GIT-PUSH":
        lines.append(
            f"- ✅ R2 uploadé pour {summary.leaves_ok} leaves, fichiers MD "
            "écrits dans rimalab-v2 (pas pushé). Vérifier localement puis "
            "`cd rimalab-v2 && git push`."
        )
    else:
        lines.append(
            f"- ✅ Pipeline complète OK pour {summary.leaves_ok} leaves. "
            "Build Cloudflare Workers déclenché par push rimalab-v2."
        )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def _print_summary(summary: PipelineRunSummary) -> None:
    print(f"[{summary.mode}] leaves={summary.total_leaves} ok={summary.leaves_ok} "
          f"failed={summary.leaves_failed} no_master={summary.leaves_no_master}")
    print(f"  variants uploaded={summary.variants_uploaded} "
          f"skipped={summary.variants_skipped} posts={summary.posts_written}")
    if summary.errors:
        for leaf_id, msg in summary.errors[:5]:
            print(f"  err {leaf_id}: {msg}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Pipeline alwanbooks — exports data/export/ vers R2 + rimalab-v2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Mock complet (écrit data/export/r2_simulated/ au lieu d'upload R2 + pas de git push).",
    )
    parser.add_argument(
        "--no-git-push", action="store_true",
        help="Upload R2 + écrit MD dans rimalab-v2 mais pas de git push.",
    )
    parser.add_argument(
        "--leaf-id", default=None,
        help="Cible un seul leaf par son leaf_id (smoke test).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limite le nombre de leaves traités.",
    )
    parser.add_argument(
        "--rimalab-path", default=str(DEFAULT_RIMALAB_PATH),
        help="Path du clone local rimalab-v2 (override env RIMALAB_REPO_PATH).",
    )
    parser.add_argument(
        "--sync-categories", action="store_true",
        help=(
            "Régénère uniquement les MDs `src/content/categories/*.md` côté "
            "rimalab-v2 depuis le registry `data/categories_registry.json`. "
            "Idempotent byte-identique (skip si contenu inchangé). Ignore "
            "manifest/posts/R2. Combiner avec --no-git-push pour test local."
        ),
    )
    args = parser.parse_args(argv)

    # Mode dédié sync-categories : ne touche pas R2, ne lit pas le manifest.
    if args.sync_categories:
        rimalab_root = Path(args.rimalab_path)
        summary = sync_categories(rimalab_root)
        print(
            f"[sync-categories] wrote={summary.wrote} "
            f"skipped={summary.skipped} total={summary.total}"
        )
        for p in summary.files_wrote:
            try:
                rel = p.relative_to(rimalab_root)
            except ValueError:
                rel = p
            print(f"  wrote   {rel}")
        for p in summary.files_skipped:
            try:
                rel = p.relative_to(rimalab_root)
            except ValueError:
                rel = p
            print(f"  skipped {rel}")
        return 0

    summary = run_pipeline(
        mock=args.mock,
        no_git_push=args.no_git_push,
        leaf_id=args.leaf_id,
        limit=args.limit,
        rimalab_root=Path(args.rimalab_path),
    )
    _print_summary(summary)
    write_report(summary)
    print(f"[info] rapport : {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    return 0 if summary.leaves_failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
