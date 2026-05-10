"""Routes API pour le QC déterministe ``image_qc_auto`` (brief 2026-05-10).

Deux endpoints :

- ``POST /api/qc/run/{image_output_id}`` : exécute les 5 règles QC
  immédiatement (synchrone, pas de queue), persiste ``image_output.qc_tags``
  et retourne ``{tags, metrics, leaf_id}``.
- ``GET /api/qc/tags/{image_output_id}`` : lit ``qc_tags`` (peut être
  vide / null si jamais évalué).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import json_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qc", tags=["qc"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_ROOT = PROJECT_ROOT / "data" / "outputs"


@router.post("/run/{image_output_id}")
def run_qc(
    image_output_id: str,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Exécute le QC déterministe sur ``image_output_id`` et persiste
    ``qc_tags``. Retourne ``{image_output_id, tags, metrics, leaf_id}``.

    404 si l'image_output n'existe pas.
    """
    # Import local pour éviter de charger numpy/Pillow tant que pas appelé.
    from workers.qc_worker import run_qc_for_output

    row = conn.execute(
        "SELECT id FROM image_output WHERE id = ?",
        [image_output_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"image_output {image_output_id} introuvable")

    res = run_qc_for_output(conn, image_output_id, OUTPUTS_ROOT)
    return json_response(res)


@router.get("/tags/{image_output_id}")
def get_qc_tags(
    image_output_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Retourne ``{image_output_id, tags}``. ``tags=[]`` si jamais évalué.

    404 si l'image_output n'existe pas.
    """
    row = conn.execute(
        "SELECT qc_tags FROM image_output WHERE id = ?",
        [image_output_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"image_output {image_output_id} introuvable")
    raw = row[0]
    tags: list[str] = []
    if raw is not None:
        if isinstance(raw, list):
            tags = [str(t) for t in raw if t is not None]
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    tags = [str(t) for t in parsed if t is not None]
            except (json.JSONDecodeError, TypeError):
                tags = []
    return json_response({"image_output_id": image_output_id, "tags": tags})
