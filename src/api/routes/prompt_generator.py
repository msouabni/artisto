"""Routes API pour le PromptGenerator playground.

Endpoints :
    GET /api/prompt-generator/leafs?search=...
        Liste des leaf_ids (filtree par search). Pour autocomplete UI.

    GET /api/prompt-generator/{leaf_id}?style=pastel|lineart
        Renvoie le prompt complet pour un leaf donne (direct).

    GET /api/prompt-generator/resolve?q=...&style=pastel|lineart
        Resolution intelligente multi-format :
            - leaf_id direct (ex 'polar_bear_on_ice')
            - slug nu (ex 'aldb-alqtby')
            - URL relative (ex 'ar/colorier/aldb-alqtby/')
            - URL absolue (ex 'https://alwanbooks.com/ar/.../alnmr-albnghaly/')

        Lookup : data/export/posts/{ar,fr,en}/<slug>.json (avec fallback
        sites destinataires data/sites/alwanbooks/src/content/posts/).
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query

from services.prompt_generator import STYLE_CONFIGS, PromptGenerator

logger = logging.getLogger(__name__)

# Pattern de validation du parametre style : derive de STYLE_CONFIGS + 'lineart'
# (mode historique). Toute entree ajoutee a STYLE_CONFIGS dans prompt_generator
# elargit automatiquement le pattern (recalcule au boot de l'API).
_STYLE_PATTERN = "^(lineart|" + "|".join(STYLE_CONFIGS.keys()) + ")$"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPORT_POSTS_DIR = PROJECT_ROOT / "data" / "export" / "posts"
SITES_POSTS_DIR = PROJECT_ROOT / "data" / "sites" / "alwanbooks" / "src" / "content" / "posts"
LOCALES = ("ar", "fr", "en")

router = APIRouter(prefix="/api/prompt-generator", tags=["prompt-generator"])


@lru_cache(maxsize=1)
def _get_gen() -> PromptGenerator:
    """Singleton PromptGenerator (chargement taxonomie unique par process)."""
    return PromptGenerator()


# === GET /api/prompt-generator/leafs ========================================
@router.get("/leafs")
def list_leafs(
    search: Optional[str] = Query(None, description="Filtre substring (case insensitive)"),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """Liste les leaf_ids disponibles, optionnellement filtres.

    Sert pour l'autocomplete UI. Retour : {count, leafs: [...]}.
    """
    gen = _get_gen()
    all_leafs = list(gen.leaf_index.keys())
    if search:
        s = search.lower()
        filtered = [lid for lid in all_leafs if s in lid.lower()]
    else:
        filtered = all_leafs
    return {
        "count": len(filtered),
        "total": len(all_leafs),
        "leafs": sorted(filtered)[:limit],
    }


# === GET /api/prompt-generator/resolve?q=... ================================
# IMPORTANT : doit etre defini AVANT /{leaf_id} sinon FastAPI matche
# leaf_id="resolve" et retourne 404.
_IMAGE_ID_LEAF_RE = re.compile(r"benchmark:[^/]+/([a-zA-Z0-9_]+?)_\d+x\d+")


def _extract_slug_from_input(q: str) -> str:
    """Extrait le slug a chercher depuis input arbitraire (leaf_id, slug, URL)."""
    q = q.strip().rstrip("/").rstrip()
    if not q:
        return ""
    # URL absolue ?
    if "://" in q:
        parsed = urlparse(q)
        segments = [s for s in parsed.path.split("/") if s]
        return segments[-1] if segments else ""
    # URL relative ou path-like ?
    if "/" in q:
        segments = [s for s in q.split("/") if s]
        return segments[-1] if segments else ""
    # Slug nu / leaf_id direct
    return q


def _leaf_id_from_post(post: dict) -> Optional[str]:
    """Extrait le leaf_id depuis un post JSON.

    Sources possibles :
        - post['image_id'] qui contient 'benchmark:poc-scale-benchmark/<leaf>_1024x...'
        - post['r2_slug'] qui est en kebab-case (conversion -> snake_case)
    """
    image_id = post.get("image_id") or ""
    m = _IMAGE_ID_LEAF_RE.match(image_id)
    if m:
        return m.group(1)
    r2_slug = post.get("r2_slug")
    if r2_slug:
        return r2_slug.replace("-", "_")
    return None


def _lookup_post(slug: str) -> Optional[tuple[str, str, dict]]:
    """Cherche le post dans les exports puis fallback sites.

    Retour : (locale, source, post_dict) ou None.
        source = 'export' | 'sites_md'
    """
    # 1. data/export/posts/{locale}/<slug>.json
    if EXPORT_POSTS_DIR.exists():
        for locale in LOCALES:
            p = EXPORT_POSTS_DIR / locale / f"{slug}.json"
            if p.is_file():
                try:
                    return locale, "export", json.loads(p.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning("Lecture impossible %s : %s", p, e)
    # 2. Fallback : data/sites/alwanbooks/src/content/posts/<locale>/<slug>.md
    if SITES_POSTS_DIR.exists():
        for locale in LOCALES:
            p = SITES_POSTS_DIR / locale / f"{slug}.md"
            if p.is_file():
                # Le frontmatter MD contient leaf_id ou r2_slug ; parse simple.
                text = p.read_text(encoding="utf-8")
                fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
                if fm_match:
                    frontmatter = {}
                    for line in fm_match.group(1).splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            frontmatter[k.strip()] = v.strip().strip('"\'')
                    return locale, "sites_md", frontmatter
    return None


@router.get("/resolve")
def resolve_prompt(
    q: str = Query(..., description="leaf_id, slug, URL relative ou absolue"),
    style: str = Query("pastel", pattern=_STYLE_PATTERN),
) -> dict:
    """Resolution multi-format vers un prompt PromptGenerator complet."""
    gen = _get_gen()
    q_clean = q.strip()
    if not q_clean:
        raise HTTPException(400, "Parametre q vide")

    # 1. Direct leaf_id ?
    if q_clean in gen.leaf_index:
        result = gen.build_prompt(q_clean, style=style)
        return {
            "leaf_id": q_clean,
            "input_format": "leaf_id_direct",
            "locale_detected": None,
            "slug_used": None,
            "post_metadata": None,
            "prompt": result,
        }

    # 2. Extrait slug depuis input
    slug = _extract_slug_from_input(q_clean)
    if not slug:
        raise HTTPException(404, f"Impossible d'extraire un slug de : {q!r}")

    # 2 bis. Slug correspond directement a un leaf_id ?
    if slug in gen.leaf_index:
        result = gen.build_prompt(slug, style=style)
        return {
            "leaf_id": slug,
            "input_format": "leaf_id_via_path",
            "locale_detected": None,
            "slug_used": slug,
            "post_metadata": None,
            "prompt": result,
        }

    # 3. Lookup dans exports posts
    lookup = _lookup_post(slug)
    if lookup is None:
        raise HTTPException(
            404,
            f"Pas de leaf trouvé pour '{q}' (slug extrait : '{slug}'). "
            f"Verifier que le post est dans data/export/posts/{{ar,fr,en}}/ "
            f"ou data/sites/alwanbooks/src/content/posts/{{ar,fr,en}}/.",
        )
    locale, source, post = lookup
    leaf_id = _leaf_id_from_post(post)
    if not leaf_id or leaf_id not in gen.leaf_index:
        raise HTTPException(
            404,
            f"Slug '{slug}' resolu (locale={locale}, source={source}) "
            f"mais leaf_id '{leaf_id}' introuvable dans la taxonomie.",
        )
    result = gen.build_prompt(leaf_id, style=style)
    return {
        "leaf_id": leaf_id,
        "input_format": (
            "url_absolute" if "://" in q_clean
            else "url_relative" if "/" in q_clean
            else "slug_nu"
        ),
        "locale_detected": locale,
        "slug_used": slug,
        "post_metadata": {
            "title": post.get("title"),
            "r2_slug": post.get("r2_slug"),
            "image_id": post.get("image_id"),
            "source": source,
        },
        "prompt": result,
    }


# === GET /api/prompt-generator/{leaf_id} ====================================
# IMPORTANT : doit etre defini APRES /resolve sinon FastAPI matche
# leaf_id="resolve" et retourne 404 pour les requetes /resolve.
@router.get("/{leaf_id}")
def get_prompt(
    leaf_id: str,
    style: str = Query("pastel", pattern=_STYLE_PATTERN),
) -> dict:
    """Renvoie le prompt complet pour un leaf_id direct (style applique)."""
    gen = _get_gen()
    if leaf_id not in gen.leaf_index:
        raise HTTPException(404, f"leaf_id introuvable : {leaf_id}")
    try:
        result = gen.build_prompt(leaf_id, style=style)
    except Exception as e:
        logger.exception("Echec build_prompt leaf_id=%s style=%s", leaf_id, style)
        raise HTTPException(500, str(e)) from e
    return {
        "leaf_id": leaf_id,
        "input_format": "leaf_id_direct",
        "prompt": result,
    }
