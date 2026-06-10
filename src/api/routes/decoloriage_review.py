"""Routes API — surface de revue interne décoloriage (Phase 3, lecture seule).

Liste les ``image_output`` dont les métadonnées ``model_config`` (JSON TEXT,
peuplé en Phase 2 par ``image_post_processing_worker``) indiquent
``coloring_engine == "decoloriage"`` ET qui possèdent un ``coloring_svg_path``.

Lecture seule stricte : aucune écriture, aucune migration, aucun accès aux
chemins prod (front public, export, extract_palette intacts). Le SVG bicouche
est servi directement via le mount static ``/data/`` (pas d'endpoint de service
SVG dédié) : on expose un ``coloring_svg_url`` relatif (ex.
``/data/generated/<leaf>__<variant>_coloriage.svg``).

Conventions DB obligatoires (cf. CLAUDE.md) :
  - accès via ``get_db_read`` (jamais ``SessionLocal()`` brut) ;
  - placeholders SQL ``?`` (``DBConnAdapter`` les réécrit en ``:p0…``) ;
  - NULL-safe sur tout numérique (``int(x) if x is not None else 0``) avant tri ;
  - types JSON natifs en sortie (jamais ``numpy.*``) ;
  - parsing ``model_config`` défensif : ``None`` / JSON invalide / pas un objet
    → entrée IGNORÉE silencieusement (jamais de 500).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends

from api.db import DBConnAdapter, get_db_read
from api.helpers import json_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/decoloriage", tags=["decoloriage"])

ENGINE_DECOLORIAGE = "decoloriage"


def _coloring_svg_url(coloring_svg_path: str) -> str | None:
    """Convertit un ``coloring_svg_path`` stocké en URL servable par le mount
    static ``/data/``.

    Les chemins sont stockés relatifs à la racine projet (ex.
    ``data/generated/<leaf>__<variant>_coloriage.svg``). On normalise les
    séparateurs Windows puis on remplace le préfixe ``data/`` par ``/data/``.
    Retourne ``None`` si le chemin est vide ou non interprétable (entrée alors
    ignorée par l'appelant).
    """
    if not coloring_svg_path or not isinstance(coloring_svg_path, str):
        return None
    norm = coloring_svg_path.replace("\\", "/").strip()
    if not norm:
        return None
    # Déjà une URL servable.
    if norm.startswith("/data/"):
        return norm
    # Chemin relatif racine projet : data/generated/...svg
    if norm.startswith("data/"):
        return "/" + norm
    # Chemin absolu OU autre : tenter de retrouver le segment data/...
    idx = norm.find("/data/")
    if idx >= 0:
        return norm[idx:]
    if norm.startswith("generated/"):
        return "/data/" + norm
    return None


def _safe_int(value: Any) -> int:
    """NULL-safe + cast natif. ``None`` / non-numérique → 0."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    """NULL-safe + cast natif. ``None`` / non-numérique → 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_crayon_distribution(value: Any) -> dict[str, int]:
    """Normalise ``crayon_distribution`` : clés str, valeurs int natives,
    NULL-safe. Toute valeur non-dict → ``{}``."""
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in value.items():
        out[str(k)] = _safe_int(v)
    return out


def _parse_model_config(raw: Any) -> dict[str, Any] | None:
    """Parse défensif du ``model_config`` (TEXT JSON).

    Retourne le dict décodé, ou ``None`` si l'entrée doit être ignorée
    (``None``, chaîne vide, JSON invalide, ou racine non-objet). Ne lève jamais.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _build_artifact_entry(
    output_id: Any,
    image_id: Any,
    leaf_id: Any,
    created_at: Any,
    mc: dict[str, Any],
) -> dict[str, Any] | None:
    """Construit une entrée de listing depuis un ``model_config`` déjà parsé.

    Retourne ``None`` si l'entrée n'est PAS un artefact décoloriage exploitable
    (mauvais moteur, pas de ``coloring_svg_path`` interprétable). Tous les
    numériques sont natifs + NULL-safe.
    """
    if mc.get("coloring_engine") != ENGINE_DECOLORIAGE:
        return None

    svg_url = _coloring_svg_url(mc.get("coloring_svg_path"))
    if svg_url is None:
        return None

    return {
        "image_output_id": str(output_id) if output_id is not None else "",
        "image_id": str(image_id) if image_id is not None else None,
        "leaf_id": str(leaf_id) if leaf_id else None,
        "variant_name": (
            str(mc["variant_name"]) if mc.get("variant_name") else None
        ),
        "level": str(mc.get("level")) if mc.get("level") else "enfant",
        "coloring_svg_url": svg_url,
        "coloring_svg_path": str(mc.get("coloring_svg_path") or ""),
        "n_clickable": _safe_int(mc.get("n_clickable")),
        "n_ink_regions": _safe_int(mc.get("n_ink_regions")),
        "publishable_tp": bool(mc.get("publishable_tp")),
        "delta_e_median": _safe_float(mc.get("delta_e_median")),
        "crayon_distribution": _safe_crayon_distribution(
            mc.get("crayon_distribution")
        ),
        "created_at": str(created_at) if created_at is not None else None,
    }


@router.get("/artifacts")
def list_decoloriage_artifacts(
    limit: int = 500,
    offset: int = 0,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste les artefacts décoloriage (lecture seule) pour la revue interne.

    Sélectionne les ``image_output`` dont ``model_config`` mentionne le moteur
    décoloriage. Le filtrage fin (moteur + ``coloring_svg_path`` valide) est
    fait en Python après parsing défensif du JSON — une entrée ``extract_palette``,
    sans ``coloring_svg_path``, ou au ``model_config`` invalide/None est exclue
    sans erreur.

    Pré-filtre SQL ``LIKE`` (cross-dialect SQLite/Postgres) pour ne pas charger
    tous les outputs ; le contrat exact est garanti par le filtre Python.
    """
    safe_limit = _safe_int(limit) or 500
    safe_offset = max(_safe_int(offset), 0)

    # Pré-filtre cross-dialect : ne charge que les outputs dont le JSON
    # mentionne le moteur décoloriage (avec ou sans espace après ":").
    pattern_spaced = '%"coloring_engine": "decoloriage"%'
    pattern_compact = '%"coloring_engine":"decoloriage"%'

    rows = conn.execute(
        """
        SELECT io.id, io.image_id, io.model_config, io.created_at,
               img.origin_term_id
        FROM image_output io
        LEFT JOIN image img ON img.id = io.image_id
        WHERE io.model_config IS NOT NULL
          AND (io.model_config LIKE ? OR io.model_config LIKE ?)
        ORDER BY io.created_at DESC
        LIMIT ? OFFSET ?
        """,
        [pattern_spaced, pattern_compact, safe_limit, safe_offset],
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        output_id, image_id, model_config_raw, created_at, leaf_id = (
            row[0], row[1], row[2], row[3], row[4],
        )
        mc = _parse_model_config(model_config_raw)
        if mc is None:
            # model_config None / JSON invalide / non-objet → ignoré, pas de 500.
            continue
        entry = _build_artifact_entry(output_id, image_id, leaf_id, created_at, mc)
        if entry is not None:
            items.append(entry)

    # Tri NULL-safe en Python (created_at peut être NULL → "" comme clé, jamais
    # de TypeError sur None). Préserve l'ordre récent-d'abord du SQL.
    items.sort(key=lambda e: e.get("created_at") or "", reverse=True)

    return json_response({"count": len(items), "items": items})
