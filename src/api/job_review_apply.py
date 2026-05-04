"""Application et rejet des résultats de jobs (logique métier hors routes HTTP)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from api.db import DATA_DIR, DBConnAdapter
from api.job_review_artifact import (
    ARTIFACT_IMAGE_CONCEPTS_PROPOSAL,
    ARTIFACT_IMAGE_GENERATION_OUTPUT,
    get_proposal_for_diff,
    is_wrapped_v1,
)

logger = logging.getLogger(__name__)

OUTPUTS_DIR = DATA_DIR / "outputs"


def reject_image_generation_job(
    conn: DBConnAdapter,
    job_id: str,
    entity_id: str,
    now: str,
) -> None:
    """Supprime l'output technique du job, remet l'image en état cohérent (prompt_ready)."""
    rows = conn.execute(
        "SELECT id, file_path FROM image_output WHERE job_id = ? AND image_id = ?",
        [job_id, entity_id],
    ).fetchall()
    for out_id, file_path in rows or []:
        if file_path:
            rel = str(file_path).strip()
            abs_path = OUTPUTS_DIR.parent / rel if rel and not rel.startswith("/") else Path(rel)
            if abs_path.exists():
                try:
                    abs_path.unlink()
                except OSError as e:
                    logger.warning("Impossible de supprimer le fichier output %s : %s", abs_path, e)
        conn.execute("DELETE FROM image_output WHERE id = ?", [out_id])

    conn.execute(
        """
        UPDATE image SET status = 'prompt_ready', updated_at = ?
        WHERE id = ? AND status = 'generating'
        """,
        [now, entity_id],
    )


def apply_image_generation_job(
    conn: DBConnAdapter,
    job_id: str,
    entity_id: str,
    stored: dict[str, Any],
    now: str,
) -> None:
    """Promouvoir l'image_output du job : image.generated + selected_output_id."""
    if not is_wrapped_v1(stored) or stored.get("artifact_type") != ARTIFACT_IMAGE_GENERATION_OUTPUT:
        raise ValueError("Artifact image_generation_output attendu pour apply image_generation")

    plan = stored.get("apply_plan") or {}
    out_id = plan.get("output_id") or (stored.get("resources") or {}).get("image_output_id")
    if not out_id:
        raise ValueError("apply_plan.output_id manquant")

    row = conn.execute(
        "SELECT id FROM image_output WHERE id = ? AND image_id = ? AND job_id = ?",
        [out_id, entity_id, job_id],
    ).fetchone()
    if not row:
        raise ValueError(f"image_output {out_id} introuvable pour ce job")

    conn.execute(
        """
        UPDATE image SET
            status = CASE WHEN status IN ('scheduled','generating','draft','prompt_ready') THEN 'generated' ELSE status END,
            selected_output_id = ?,
            updated_at = ?
        WHERE id = ?
        """,
        [out_id, now, entity_id],
    )


def proposal_for_apply(stored: dict[str, Any]) -> dict[str, Any]:
    return get_proposal_for_diff(stored)


def apply_image_concepts_job(
    conn: DBConnAdapter,
    stored: dict[str, Any],
    config: dict[str, Any],
    now: str,
) -> dict[str, int]:
    """Crée des lignes ``image`` en brouillon + tag taxonomie si ancrage ; ignore les ids déjà présents."""
    if not is_wrapped_v1(stored) or stored.get("artifact_type") != ARTIFACT_IMAGE_CONCEPTS_PROPOSAL:
        raise ValueError("Artifact image_concepts_proposal attendu pour apply_image_concepts_job")

    prop = proposal_for_apply(stored)
    suggestions = prop.get("suggestions") or []
    anchor = prop.get("anchor") if isinstance(prop.get("anchor"), dict) else {}
    term_id = (config.get("term_id") or anchor.get("term_id") or "")
    term_id = str(term_id).strip() or None
    vocabulary_id = (config.get("vocabulary_id") or anchor.get("vocabulary_id") or "")
    vocabulary_id = str(vocabulary_id).strip() or None

    taxonomy_id: str | None = None
    if vocabulary_id:
        row = conn.execute(
            "SELECT taxonomy_id FROM vocabulary WHERE id = ?",
            [vocabulary_id],
        ).fetchone()
        taxonomy_id = row[0] if row else None

    created = 0
    skipped = 0
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            continue
        title = str(
            item.get("title") or item.get("name_en") or item.get("name_fr") or cid
        ).strip() or cid

        if conn.execute("SELECT 1 FROM image WHERE id = ?", [cid]).fetchone():
            skipped += 1
            continue

        conn.execute(
            """
            INSERT INTO image
                (id, title, status, prompt, negative_prompt,
                 origin_type, origin_batch_id, origin_term_id, origin_taxonomy_id,
                 selected_output_id, file_path, created_at, updated_at)
            VALUES (?, ?, 'draft', '', '', 'ai_concepts_job', NULL, ?, ?, NULL, '', ?, ?)
            """,
            [cid, title, term_id, taxonomy_id, now, now],
        )
        created += 1

        if taxonomy_id and term_id:
            existing_tag = conn.execute(
                """
                SELECT 1 FROM image_taxonomy_tag
                WHERE image_id = ? AND taxonomy_id = ? AND term_id = ?
                """,
                [cid, taxonomy_id, term_id],
            ).fetchone()
            if not existing_tag:
                conn.execute(
                    """
                    INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    [cid, taxonomy_id, term_id, now],
                )

    return {"created": created, "skipped_duplicate": skipped}
