"""Routes API pour la gestion des jobs (queue, types, bulk, diff, validate)."""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from api.db import DATA_DIR, DBConnAdapter, get_db_read, get_db_write
from api.helpers import json_response, transaction
from api.job_review_artifact import (
    ARTIFACT_IMAGE_CONCEPTS_PROPOSAL,
    ARTIFACT_IMAGE_GENERATION_OUTPUT,
    ARTIFACT_IMAGE_TEXT_PATCH,
    ARTIFACT_TAXONOMY_BATCH_PATCH,
    ARTIFACT_TAXONOMY_IMPORT_OPS,
    get_proposal_for_diff,
    is_wrapped_v1,
    parse_stored_job_result,
)
from api.job_review_image import build_image_generation_review_payload
from api.job_review_apply import (
    apply_image_concepts_job,
    apply_image_generation_job,
    proposal_for_apply,
    reject_image_generation_job,
)
from api.routes.taxonomy import apply_taxonomy_import_operations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JOB_STATUSES = (
    "pending", "running", "completed", "failed", "cancelled",
    "awaiting_validation", "applied", "rejected",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ENQUEUEABLE_JOB_TYPES = frozenset(
    {
        "text_enrichment",
        "taxonomy_enrich_term",
        "taxonomy_enrich_terms_batch",
        "taxonomy_enrich_keywords",
        "taxonomy_suggest_children",
        "taxonomy_generate_vocabulary",
        "image_prompt_create",
        "image_prompt_improve",
        "image_prompt_validate",
        "image_generate_concepts",
        "image_generate_prompts",
        "image_prompt_suggest",
        "image_prompts_bulk",
    }
)


def _validate_enqueue_config(job_type: str, body: dict[str, Any]) -> None:
    """Lève HTTPException si config ou champs requis sont invalides."""
    config = body.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="config doit être un objet JSON")

    def _req_str(key: str) -> str:
        v = config.get(key)
        return str(v).strip() if v is not None else ""

    if job_type == "text_enrichment":
        if not str(config.get("prompt") or "").strip():
            raise HTTPException(status_code=400, detail="config.prompt (non vide) requis")
        return

    if job_type == "taxonomy_enrich_term":
        if not _req_str("vocabulary_id") or not _req_str("term_id"):
            raise HTTPException(status_code=400, detail="config.vocabulary_id et config.term_id requis")
        return

    if job_type == "taxonomy_enrich_terms_batch":
        ids = config.get("term_ids")
        if not isinstance(ids, list) or not ids:
            raise HTTPException(status_code=400, detail="config.term_ids (liste non vide) requis")
        if not _req_str("vocabulary_id"):
            raise HTTPException(status_code=400, detail="config.vocabulary_id requis")
        return

    if job_type in ("taxonomy_enrich_keywords", "taxonomy_suggest_children"):
        if not _req_str("vocabulary_id") or not _req_str("term_id"):
            raise HTTPException(status_code=400, detail="config.vocabulary_id et config.term_id requis")
        return

    if job_type == "taxonomy_generate_vocabulary":
        if not str(config.get("theme") or "").strip():
            raise HTTPException(status_code=400, detail="config.theme requis")
        if not _req_str("target_vocabulary_id") and not _req_str("vocabulary_id"):
            raise HTTPException(
                status_code=400,
                detail="config.target_vocabulary_id (vocabulaire d'application) requis",
            )
        return

    if job_type == "image_prompt_create":
        if not _req_str("image_id"):
            raise HTTPException(status_code=400, detail="config.image_id requis")
        if not str(config.get("keywords") or "").strip() and not str(config.get("title") or "").strip():
            raise HTTPException(status_code=400, detail="config.keywords et/ou config.title requis")
        return

    if job_type == "image_prompt_improve":
        if not _req_str("image_id"):
            raise HTTPException(status_code=400, detail="config.image_id requis")
        return

    if job_type == "image_prompt_validate":
        if not _req_str("image_id"):
            raise HTTPException(status_code=400, detail="config.image_id requis")
        if not str(config.get("prompt") or "").strip():
            raise HTTPException(status_code=400, detail="config.prompt requis")
        return

    if job_type == "image_generate_concepts":
        if not str(config.get("theme") or "").strip():
            raise HTTPException(status_code=400, detail="config.theme requis")
        cnt = config.get("count")
        if cnt is not None:
            if not isinstance(cnt, int) or cnt < 1 or cnt > 15:
                raise HTTPException(status_code=400, detail="config.count doit être un entier entre 1 et 15")
        return

    if job_type == "image_generate_prompts":
        concepts = config.get("concepts")
        term_id = str(config.get("term_id") or "").strip()
        vocabulary_id = str(config.get("vocabulary_id") or "").strip()
        has_concepts = isinstance(concepts, list) and len(concepts) > 0
        has_anchor = bool(term_id and vocabulary_id)
        if not has_concepts and not has_anchor:
            raise HTTPException(
                status_code=400,
                detail="config.concepts (liste) ou config.term_id + config.vocabulary_id requis",
            )
        cnt = config.get("count")
        if cnt is not None and (not isinstance(cnt, int) or cnt < 1 or cnt > 10):
            raise HTTPException(status_code=400, detail="config.count doit être un entier entre 1 et 10")
        return

    if job_type == "image_prompt_suggest":
        image_id = str(config.get("image_id") or "").strip()
        title = str(config.get("title") or "").strip()
        if not image_id and not title:
            raise HTTPException(
                status_code=400,
                detail="config.image_id ou config.title requis",
            )
        cnt = config.get("count")
        if cnt is not None and (not isinstance(cnt, int) or cnt < 1 or cnt > 5):
            raise HTTPException(status_code=400, detail="config.count doit être un entier entre 1 et 5")
        return

    if job_type == "image_prompts_bulk":
        items = config.get("items")
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=400, detail="config.items (liste non vide) requis")
        if len(items) > 10:
            raise HTTPException(status_code=400, detail="Maximum 10 items par job image_prompts_bulk")
        return

    raise HTTPException(status_code=400, detail=f"Type de job non pris en charge : {job_type}")


def _row_to_job(row: tuple) -> dict[str, Any]:
    cols = [
        "id", "type", "status", "image_id", "config", "started_at", "finished_at", "error_message", "created_at",
        "priority", "retry_count", "max_retries", "scheduled_at", "entity_type", "entity_id", "result",
        "external_ref_id", "progress", "progress_message", "worker_id", "last_heartbeat_at", "batch_ref",
        "duration_ms",
    ]
    d = {}
    for i, c in enumerate(cols):
        if i < len(row):
            d[c] = row[i]
    return d


@router.get("")
def list_jobs(
    conn: DBConnAdapter = Depends(get_db_read),
    type: list[str] | None = Query(None, alias="type[]"),
    status: list[str] | None = Query(None, alias="status[]"),
    entity_type: str | None = None,
    entity_id: str | None = None,
    batch_ref: str | None = None,
    priority_min: int | None = None,
    priority_max: int | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    scheduled_before: str | None = None,
    has_error: bool | None = None,
    page: int = 1,
    page_size: int = 50,
    sort: str = "created_at",
    order: str = "desc",
) -> Any:
    """Liste les jobs avec filtres poussés."""
    conditions = ["1=1"]
    params: list[Any] = []

    if type:
        placeholders = ",".join("?" * len(type))
        conditions.append(f"type IN ({placeholders})")
        params.extend(type)
    if status:
        placeholders = ",".join("?" * len(status))
        conditions.append(f"status IN ({placeholders})")
        params.extend(status)
    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        conditions.append("entity_id = ?")
        params.append(entity_id)
    if batch_ref:
        conditions.append("batch_ref = ?")
        params.append(batch_ref)
    if priority_min is not None:
        conditions.append("priority >= ?")
        params.append(priority_min)
    if priority_max is not None:
        conditions.append("priority <= ?")
        params.append(priority_max)
    if created_after:
        conditions.append("created_at >= ?")
        params.append(created_after)
    if created_before:
        conditions.append("created_at <= ?")
        params.append(created_before)
    if scheduled_before:
        conditions.append("(scheduled_at IS NULL OR scheduled_at <= ?)")
        params.append(scheduled_before)
    if has_error is True:
        conditions.append("error_message IS NOT NULL AND error_message != ''")
    elif has_error is False:
        conditions.append("(error_message IS NULL OR error_message = '')")

    where = " AND ".join(conditions)
    valid_sorts = {"created_at", "priority", "started_at", "finished_at", "type", "status"}
    sort_col = sort if sort in valid_sorts else "created_at"
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    offset = (page - 1) * page_size

    rows = conn.execute(
        f"""
        SELECT id, type, status, image_id, config, started_at, finished_at, error_message, created_at,
               priority, retry_count, max_retries, scheduled_at, entity_type, entity_id, result,
               external_ref_id, progress, progress_message, worker_id, last_heartbeat_at, batch_ref,
               duration_ms
        FROM job
        WHERE {where}
        ORDER BY {sort_col} {order_dir}
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()

    total = conn.execute(
        f"SELECT COUNT(*) FROM job WHERE {where}",
        params,
    ).fetchone()[0]

    jobs = [_row_to_job(r) for r in rows]
    return json_response({"jobs": jobs, "total": total, "page": page, "page_size": page_size})


@router.get("/stats")
def get_stats(conn: DBConnAdapter = Depends(get_db_read)) -> Any:
    """Stats par type : pending, running, failed, awaiting_validation, avg_duration_ms."""
    rows = conn.execute("""
        SELECT type,
               SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
               SUM(CASE WHEN status = 'awaiting_validation' THEN 1 ELSE 0 END) AS awaiting_validation,
               AVG(CASE WHEN status IN ('awaiting_validation', 'completed', 'applied', 'rejected')
                             AND duration_ms IS NOT NULL
                        THEN duration_ms END) AS avg_duration_ms
        FROM job
        GROUP BY type
    """).fetchall()
    stats = {}
    for r in rows:
        avg = r[5]
        stats[r[0]] = {
            "pending": r[1],
            "running": r[2],
            "failed": r[3],
            "awaiting_validation": r[4],
            "avg_duration_ms": round(avg) if avg is not None else None,
        }
    return json_response(stats)


@router.get("/types")
def list_types(conn: DBConnAdapter = Depends(get_db_read)) -> Any:
    """Liste les job_type_config."""
    rows = conn.execute("""
        SELECT type, label, enabled, max_concurrent, description, category, updated_at
        FROM job_type_config
        ORDER BY category, type
    """).fetchall()
    types = [
        {
            "type": r[0],
            "label": r[1],
            "enabled": bool(r[2]),
            "max_concurrent": r[3] or 1,
            "description": r[4],
            "category": r[5],
            "updated_at": r[6],
        }
        for r in rows
    ]
    return json_response(types)


@router.put("/types/{job_type}")
def update_type(
    job_type: str,
    body: dict[str, Any],
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """Active/désactive un type de job. Body: {enabled: bool}."""
    enabled = body.get("enabled")
    if enabled is None:
        raise HTTPException(status_code=400, detail="enabled requis")
    if not conn.execute("SELECT 1 FROM job_type_config WHERE type = ?", [job_type]).fetchone():
        raise HTTPException(status_code=404, detail=f"Type '{job_type}' non trouvé")
    now = _now()
    conn.execute(
        "UPDATE job_type_config SET enabled = ?, updated_at = ? WHERE type = ?",
        [bool(enabled), now, job_type],
    )
    return json_response({"status": "ok", "type": job_type, "enabled": enabled})


@router.post("/enqueue")
def enqueue_job(
    body: dict[str, Any],
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """Insère un job `pending` pour les types IA texte / taxonomie / prompts image."""
    job_type = body.get("type")
    if not job_type or job_type not in ENQUEUEABLE_JOB_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"type requis parmi : {', '.join(sorted(ENQUEUEABLE_JOB_TYPES))}",
        )
    _validate_enqueue_config(job_type, body)
    config = dict(body.get("config") or {})
    vocab = body.get("vocabulary_id")
    if vocab:
        config.setdefault("vocabulary_id", str(vocab).strip())

    entity_type = body.get("entity_type")
    entity_id = body.get("entity_id")
    if entity_type is None:
        if job_type == "taxonomy_enrich_terms_batch":
            entity_type = "taxonomy_batch"
            entity_id = entity_id or config.get("vocabulary_id") or ""
        elif job_type == "taxonomy_generate_vocabulary":
            entity_type = "vocabulary"
            entity_id = entity_id or config.get("target_vocabulary_id") or config.get("vocabulary_id") or ""
        elif job_type.startswith("image_prompt_"):
            entity_type = "image"
            entity_id = entity_id or config.get("image_id") or ""
        elif job_type == "image_generate_concepts":
            entity_type = "concept_batch"
            entity_id = entity_id or ""
        else:
            entity_type = "term"
            entity_id = entity_id or config.get("term_id") or config.get("image_id") or ""
    entity_type = entity_type or "term"
    entity_id = entity_id if entity_id is not None else ""

    row = conn.execute(
        "SELECT enabled FROM job_type_config WHERE type = ?",
        [job_type],
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail=f"Type de job '{job_type}' inconnu dans job_type_config. "
            "Redémarrez l'API (seed au démarrage) ou exécutez init_db / migrations.",
        )
    if not bool(row[0]):
        raise HTTPException(status_code=400, detail=f"Le type de job '{job_type}' est désactivé")

    job_id = (body.get("id") or "").strip() or f"job_txt_{time.time_ns()}_{random.randint(1000, 9999)}"
    if conn.execute("SELECT 1 FROM job WHERE id = ?", [job_id]).fetchone():
        raise HTTPException(status_code=409, detail=f"Un job avec l'id '{job_id}' existe déjà")

    now = _now()
    priority = body.get("priority")
    if priority is not None and not isinstance(priority, int):
        raise HTTPException(status_code=400, detail="priority doit être un entier")
    batch_ref = body.get("batch_ref")
    config_json = json.dumps(config, ensure_ascii=False)

    with transaction(conn):
        conn.execute(
            """
            INSERT INTO job (
                id, type, status, image_id, config, created_at,
                entity_type, entity_id, priority, batch_ref
            )
            VALUES (?, ?, 'pending', NULL, ?, ?, ?, ?, ?, ?)
            """,
            [
                job_id,
                job_type,
                config_json,
                now,
                entity_type,
                entity_id or None,
                priority if priority is not None else 5,
                batch_ref or None,
            ],
        )
    return json_response({"status": "enqueued", "id": job_id, "type": job_type})


OUTPUTS_DIR = DATA_DIR / "outputs"


@router.get("/{job_id}/output-image")
def get_job_output_image(
    job_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Renvoie l'image générée pour un job image_generation (pour visualisation dans l'éditeur)."""
    row = conn.execute(
        "SELECT type FROM job WHERE id = ?",
        [job_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
    if row[0] != "image_generation":
        raise HTTPException(status_code=400, detail="Output image uniquement pour les jobs image_generation")
    out_row = conn.execute(
        """
        SELECT file_path FROM image_output
        WHERE job_id = ? AND file_path IS NOT NULL AND file_path != ''
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [job_id],
    ).fetchone()
    if not out_row:
        raise HTTPException(status_code=404, detail="Aucun output pour ce job")
    file_path = out_row[0]
    abs_path = OUTPUTS_DIR.parent / file_path if not file_path.startswith("/") else Path(file_path)
    if not abs_path.exists():
        abs_path = DATA_DIR / file_path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"Fichier introuvable : {file_path}")
    return FileResponse(str(abs_path), media_type="image/png")


@router.get("/{job_id}/review")
def get_job_review(
    job_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
) -> Any:
    """Payload structuré pour la revue d'un job ``image_generation`` (aperçu, QC, plan apply/reject)."""
    row = conn.execute(
        """
        SELECT type, status, entity_id, image_id, result
        FROM job WHERE id = ?
        """,
        [job_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
    job_type, status, entity_id, image_id, result_json = row
    if job_type != "image_generation":
        raise HTTPException(
            status_code=400,
            detail="Revue structurée disponible uniquement pour les jobs image_generation",
        )
    if status != "awaiting_validation":
        raise HTTPException(
            status_code=400,
            detail="Revue disponible uniquement pour les jobs awaiting_validation",
        )
    entity = (entity_id or image_id or "").strip()
    if not entity:
        raise HTTPException(status_code=422, detail="entity_id / image_id manquant pour ce job")

    stored = parse_stored_job_result(result_json)
    img_row = conn.execute(
        "SELECT status, selected_output_id FROM image WHERE id = ?",
        [entity],
    ).fetchone()
    image_status = img_row[0] if img_row else None
    image_sel = img_row[1] if img_row else None

    payload = build_image_generation_review_payload(
        job_id=job_id,
        job_status=status,
        entity_id=entity,
        stored=stored,
        image_status=image_status,
        image_selected_output_id=image_sel,
    )
    return json_response(payload)


@router.post("/{job_id}/reschedule")
def reschedule_job(
    job_id: str,
    body: dict[str, Any] | None = None,
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """Replanifie un job failed. Body: {reset_retry: bool} (optionnel)."""
    body = body or {}
    reset_retry = body.get("reset_retry", True)
    now = _now()
    with transaction(conn):
        row = conn.execute(
            "SELECT status, retry_count FROM job WHERE id = ?",
            [job_id],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
        if row[0] != "failed":
            raise HTTPException(status_code=400, detail="Seuls les jobs failed peuvent être replanifiés")
        retry_count = 0 if reset_retry else (row[1] or 0)
        conn.execute(
            """
            UPDATE job SET status = 'pending', error_message = NULL, scheduled_at = NULL,
                           retry_count = ?, started_at = NULL, finished_at = NULL, worker_id = NULL
            WHERE id = ?
            """,
            [retry_count, job_id],
        )
    return json_response({"status": "ok", "id": job_id})


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """Annule un job pending ou running."""
    row = conn.execute("SELECT status FROM job WHERE id = ?", [job_id]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
    if row[0] not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Seuls les jobs pending ou running peuvent être annulés")
    now = _now()
    conn.execute(
        """
        UPDATE job SET status = 'cancelled', error_message = 'Annulé par l''utilisateur', finished_at = ?
        WHERE id = ? AND status IN ('pending', 'running')
        """,
        [now, job_id],
    )
    return json_response({"status": "ok", "id": job_id})


@router.get("/{job_id}/diff")
def get_diff(
    job_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
) -> Any:
    """Calcule le diff JSON (résultat texte vs entité actuelle) pour les jobs awaiting_validation."""
    row = conn.execute(
        "SELECT type, status, entity_type, entity_id, config, result FROM job WHERE id = ?",
        [job_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
    job_type, status, entity_type, entity_id, config_json, result_json = row
    if status != "awaiting_validation":
        raise HTTPException(status_code=400, detail="Diff disponible uniquement pour les jobs awaiting_validation")
    if not result_json:
        return json_response({"fields": [], "current": {}, "proposed": {}})

    stored = parse_stored_job_result(result_json)
    if not stored:
        return json_response({"fields": [], "current": {}, "proposed": {}})

    if is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_IMAGE_GENERATION_OUTPUT:
        return json_response(
            {
                "redirect_to": "review",
                "review_url": f"/api/jobs/{job_id}/review",
                "fields": [],
                "current": {},
                "proposed": {},
            }
        )

    proposed = get_proposal_for_diff(stored)

    config = json.loads(config_json) if config_json else {}
    current: dict[str, Any] = {}

    if is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_TAXONOMY_BATCH_PATCH and isinstance(proposed, dict):
        vocab_id = proposed.get("vocabulary_id") or config.get("vocabulary_id")
        terms_prop = proposed.get("terms") or {}
        current_terms: dict[str, Any] = {}
        if vocab_id and isinstance(terms_prop, dict):
            for tid in terms_prop:
                current_terms[tid] = _get_term_current(conn, vocab_id, tid)
        current = {"terms": current_terms}
    elif is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_TAXONOMY_IMPORT_OPS and isinstance(proposed, dict):
        ops_raw = proposed.get("operations") or []
        ops_out = [
            {
                "op": op.get("op", "add"),
                "id": str(op.get("value", {}).get("id") or op.get("id") or "").strip(),
                "name_fr": str(op.get("value", {}).get("name_fr") or op.get("name_fr") or "").strip(),
                "name_en": str(op.get("value", {}).get("name_en") or op.get("name_en") or "").strip(),
                "parent_id": op.get("value", {}).get("parent_id") or op.get("parent_id"),
            }
            for op in ops_raw
            if isinstance(op, dict)
        ]
        return json_response({
            "view_type": "taxonomy_import",
            "fields": [],
            "operations": ops_out,
            "summary": {
                "add": sum(1 for o in ops_out if o["op"] == "add"),
                "update": sum(1 for o in ops_out if o["op"] != "add"),
            },
            "current": {},
            "proposed": {},
        })
    elif is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_IMAGE_TEXT_PATCH:
        if entity_id:
            current = _get_image_current(conn, entity_id)
    elif is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_IMAGE_CONCEPTS_PROPOSAL and isinstance(proposed, dict):
        suggestions_list = proposed.get("suggestions") or []
        concepts_out: list[dict[str, Any]] = []
        for s in suggestions_list:
            if not isinstance(s, dict):
                continue
            cid = str(s.get("id") or "").strip()
            if not cid:
                continue
            existing = conn.execute(
                "SELECT title FROM image WHERE id = ?",
                [cid],
            ).fetchone()
            concepts_out.append({
                "id": cid,
                "title": s.get("title") or s.get("name_en") or s.get("name_fr") or cid,
                "name_fr": s.get("name_fr", ""),
                "name_en": s.get("name_en", ""),
                "is_new": existing is None,
                "existing_title": existing[0] if existing else None,
            })
        new_count = sum(1 for c in concepts_out if c["is_new"])
        return json_response({
            "view_type": "concepts_cards",
            "fields": [],
            "concepts": concepts_out,
            "summary": {"new": new_count, "duplicate": len(concepts_out) - new_count},
            "anchor": proposed.get("anchor"),
            "current": {},
            "proposed": {},
        })
    elif entity_type == "term" and entity_id:
        vocab_id = config.get("vocabulary_id") or _get_vocabulary_for_term(conn, entity_id)
        if vocab_id:
            current = _get_term_current(conn, vocab_id, entity_id)
    elif entity_type == "image" and entity_id:
        current = _get_image_current(conn, entity_id)

    fields = _compute_diff_fields(current, proposed)
    return json_response({"view_type": "field_table", "fields": fields, "current": current, "proposed": proposed})


def _get_vocabulary_for_term(conn: DBConnAdapter, term_id: str) -> str | None:
    row = conn.execute(
        "SELECT vocabulary_id FROM term WHERE id = ? LIMIT 1",
        [term_id],
    ).fetchone()
    return row[0] if row else None


def _get_term_current(conn: DBConnAdapter, vocabulary_id: str, term_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT name_i18n, description_i18n, keywords FROM term WHERE id = ? AND vocabulary_id = ?",
        [term_id, vocabulary_id],
    ).fetchone()
    if not row:
        return {}
    return {
        "name_i18n": json.loads(row[0]) if row[0] else {},
        "description_i18n": json.loads(row[1]) if row[1] else {},
        "keywords": row[2] or "",
    }


def _get_image_current(conn: DBConnAdapter, image_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT title, prompt, negative_prompt FROM image WHERE id = ?",
        [image_id],
    ).fetchone()
    if not row:
        return {}
    return {"title": row[0] or "", "prompt": row[1] or "", "negative_prompt": row[2] or ""}


def _compute_diff_fields(current: dict, proposed: dict) -> list[dict[str, Any]]:
    """Calcule les champs différés (field-level). Utilise deepdiff si dispo."""
    try:
        from deepdiff import DeepDiff
        diff = DeepDiff(current, proposed, ignore_order=True, threshold_to_diff_deeper=0)
        fields = []
        for path_key, change in diff.get("values_changed", {}).items():
            path = path_key.replace("root[", "").replace("]", "").replace("'", "")
            fields.append({
                "path": path,
                "current": change.get("old_value"),
                "proposed": change.get("new_value"),
            })
        for path_key in diff.get("dictionary_item_added", []):
            path = path_key.replace("root[", "").replace("]", "").replace("'", "")
            fields.append({"path": path, "current": None, "proposed": "added"})
        for path_key in diff.get("dictionary_item_removed", []):
            path = path_key.replace("root[", "").replace("]", "").replace("'", "")
            fields.append({"path": path, "current": "removed", "proposed": None})
        return fields
    except ImportError:
        return _compute_diff_fields_fallback(current, proposed)


def _compute_diff_fields_fallback(current: dict, proposed: dict) -> list[dict[str, Any]]:
    """Fallback sans deepdiff : comparaison récursive simple."""
    fields = []

    def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
        out = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and not (isinstance(v, dict) and all(isinstance(x, str) for x in v.values())):
                out.update(_flatten(v, key))
            else:
                out[key] = v
        return out

    flat_curr = _flatten(current)
    flat_prop = _flatten(proposed)
    all_keys = set(flat_curr) | set(flat_prop)
    for k in sorted(all_keys):
        c = flat_curr.get(k)
        p = flat_prop.get(k)
        if c != p:
            fields.append({"path": k, "current": c, "proposed": p})
    return fields


def _validate_job_execute(
    conn: DBConnAdapter,
    job_id: str,
    action: str,
    fields: list[Any],
    now: str,
) -> str:
    """Apply or reject one job. Must run inside ``transaction(conn)``.

    Returns ``\"applied\"`` or ``\"rejected\"``. Raises ``HTTPException`` on errors.
    """
    row = conn.execute(
        "SELECT type, status, entity_type, entity_id, config, result FROM job WHERE id = ?",
        [job_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
    job_type, status, entity_type, entity_id, config_json, result_json = row
    config = json.loads(config_json) if config_json else {}
    if status != "awaiting_validation":
        raise HTTPException(status_code=400, detail="Validation uniquement pour jobs awaiting_validation")

    if action == "reject":
        if job_type == "image_generation" and entity_id:
            reject_image_generation_job(conn, job_id, entity_id, now)
        conn.execute(
            "UPDATE job SET status = 'rejected', finished_at = ? WHERE id = ?",
            [now, job_id],
        )
        return "rejected"

    stored = parse_stored_job_result(result_json)
    if job_type == "image_generation" and entity_id:
        try:
            apply_image_generation_job(conn, job_id, entity_id, stored, now)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    elif is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_TAXONOMY_BATCH_PATCH:
        prop = proposal_for_apply(stored)
        vocab_id = prop.get("vocabulary_id") or config.get("vocabulary_id")
        terms = prop.get("terms") or {}
        if not vocab_id:
            raise HTTPException(status_code=422, detail="vocabulary_id manquant pour appliquer le lot")
        if isinstance(terms, dict):
            for tid, patch in terms.items():
                if isinstance(patch, dict):
                    _apply_term_updates(conn, vocab_id, str(tid), patch, fields, now)
    elif is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_TAXONOMY_IMPORT_OPS:
        prop = proposal_for_apply(stored)
        vocab_id = prop.get("vocabulary_id") or config.get("vocabulary_id")
        ops = prop.get("operations") or []
        if not vocab_id:
            raise HTTPException(status_code=422, detail="vocabulary_id manquant pour l'import")
        apply_taxonomy_import_operations(conn, vocab_id, ops)
    elif is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_IMAGE_TEXT_PATCH:
        proposed_img = proposal_for_apply(stored)
        img_patch = {k: v for k, v in proposed_img.items() if k in ("title", "prompt", "negative_prompt")}
        if entity_type == "image" and entity_id and img_patch:
            _apply_image_updates(conn, entity_id, img_patch, fields, now)
    elif is_wrapped_v1(stored) and stored.get("artifact_type") == ARTIFACT_IMAGE_CONCEPTS_PROPOSAL:
        try:
            apply_image_concepts_job(conn, stored, config, now)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    else:
        proposed = proposal_for_apply(stored)
        if entity_type == "term" and entity_id:
            vocab_id = config.get("vocabulary_id") or _get_vocabulary_for_term(conn, entity_id)
            if vocab_id:
                _apply_term_updates(conn, vocab_id, entity_id, proposed, fields, now)
        elif entity_type == "image" and entity_id:
            _apply_image_updates(conn, entity_id, proposed, fields, now)

    conn.execute(
        "UPDATE job SET status = 'applied', finished_at = ? WHERE id = ?",
        [now, job_id],
    )
    return "applied"


@router.post("/{job_id}/validate")
def validate_job(
    job_id: str,
    body: dict[str, Any],
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """Valide (apply) ou rejette le résultat texte. Body: {action: 'apply'|'reject', fields?: list[str]}."""
    action = body.get("action")
    if action not in ("apply", "reject"):
        raise HTTPException(status_code=400, detail="action doit être 'apply' ou 'reject'")
    fields = body.get("fields", [])

    now = _now()
    with transaction(conn):
        out = _validate_job_execute(conn, job_id, action, fields, now)
    if out == "rejected":
        return json_response({"status": "ok", "action": "rejected"})
    return json_response({"status": "ok", "action": "applied"})


@router.get("/{job_id}")
def get_job(
    job_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
) -> Any:
    """Détail d'un job (déclaré après les sous-chemins ``/{job_id}/…`` pour éviter toute ambiguïté de routage)."""
    row = conn.execute(
        """
        SELECT id, type, status, image_id, config, started_at, finished_at, error_message, created_at,
               priority, retry_count, max_retries, scheduled_at, entity_type, entity_id, result,
               external_ref_id, progress, progress_message, worker_id, last_heartbeat_at, batch_ref
        FROM job
        WHERE id = ?
        """,
        [job_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
    return json_response(_row_to_job(row))


def _apply_term_updates(
    conn: DBConnAdapter,
    vocabulary_id: str,
    term_id: str,
    proposed: dict,
    fields: list[str],
    now: str,
) -> None:
    """Applique les mises à jour partielles sur un terme."""
    if not fields:
        fields = list(proposed.keys())
    if "name_i18n" in proposed and ("name_i18n" in fields or any(f.startswith("name_i18n.") for f in fields)):
        curr = conn.execute(
            "SELECT name_i18n FROM term WHERE id = ? AND vocabulary_id = ?",
            [term_id, vocabulary_id],
        ).fetchone()
        curr_val = json.loads(curr[0]) if curr and curr[0] else {}
        for k, v in proposed.get("name_i18n", {}).items():
            if f"name_i18n.{k}" in fields or "name_i18n" in fields:
                curr_val[k] = v
        conn.execute(
            "UPDATE term SET name_i18n = ?, updated_at = ? WHERE id = ? AND vocabulary_id = ?",
            [json.dumps(curr_val), now, term_id, vocabulary_id],
        )
    if "description_i18n" in proposed and ("description_i18n" in fields or any(f.startswith("description_i18n.") for f in fields)):
        curr = conn.execute(
            "SELECT description_i18n FROM term WHERE id = ? AND vocabulary_id = ?",
            [term_id, vocabulary_id],
        ).fetchone()
        curr_val = json.loads(curr[0]) if curr and curr[0] else {}
        for k, v in proposed.get("description_i18n", {}).items():
            if f"description_i18n.{k}" in fields or "description_i18n" in fields:
                curr_val[k] = v
        conn.execute(
            "UPDATE term SET description_i18n = ?, updated_at = ? WHERE id = ? AND vocabulary_id = ?",
            [json.dumps(curr_val), now, term_id, vocabulary_id],
        )
    if "keywords" in proposed and "keywords" in fields:
        conn.execute(
            "UPDATE term SET keywords = ?, updated_at = ? WHERE id = ? AND vocabulary_id = ?",
            [proposed["keywords"], now, term_id, vocabulary_id],
        )


def _apply_image_updates(
    conn: DBConnAdapter,
    image_id: str,
    proposed: dict,
    fields: list[str],
    now: str,
) -> None:
    """Applique les mises à jour partielles sur une image."""
    if not fields:
        fields = list(proposed.keys())
    updates = []
    params = []
    if "title" in proposed and "title" in fields:
        updates.append("title = ?")
        params.append(proposed["title"])
    if "prompt" in proposed and "prompt" in fields:
        updates.append("prompt = ?")
        params.append(proposed["prompt"])
    if "negative_prompt" in proposed and "negative_prompt" in fields:
        updates.append("negative_prompt = ?")
        params.append(proposed["negative_prompt"])
    if updates:
        params.extend([now, image_id])
        conn.execute(
            f"UPDATE image SET {', '.join(updates)}, updated_at = ? WHERE id = ?",
            params,
        )


@router.post("/cleanup")
def cleanup_jobs(
    body: dict[str, Any] | None = None,
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """Purge les jobs terminés vieux de plus de X jours. Body: {days: int} (défaut 30)."""
    body = body or {}
    days = body.get("days", 30)
    if not isinstance(days, (int, float)) or days < 1:
        raise HTTPException(status_code=400, detail="days doit être un entier >= 1")
    from datetime import timedelta
    threshold = (datetime.now(timezone.utc) - timedelta(days=int(days))).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction(conn):
        conn.execute(
            """
            DELETE FROM job
            WHERE status IN ('completed', 'failed', 'cancelled', 'applied', 'rejected')
              AND (finished_at IS NOT NULL AND finished_at < ?)
            """,
            [threshold],
        )
    return json_response({"status": "ok", "message": f"Jobs terminés avant {threshold} purgés"})


def _http_detail_str(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(detail)


@router.post("/bulk")
def bulk_action(
    body: dict[str, Any],
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """Actions en masse.

    Body selon ``action`` :

    - ``cancel`` / ``reschedule`` / ``delete`` : ``{action, ids, reset_retry?: bool}`` (reschedule).
    - ``set_priority`` : ``{action, ids, priority: int 1..100}``.
    - ``validate`` : ``{action, ids, validate_action: 'apply'|'reject', fields?: list}``.
    """
    action = body.get("action")
    ids = body.get("ids", [])
    if action not in ("cancel", "reschedule", "delete", "set_priority", "validate"):
        raise HTTPException(
            status_code=400,
            detail="action doit être cancel, reschedule, delete, set_priority ou validate",
        )
    if not ids:
        raise HTTPException(status_code=400, detail="ids requis")

    now = _now()

    if action == "validate":
        validate_action = body.get("validate_action")
        if validate_action not in ("apply", "reject"):
            raise HTTPException(status_code=400, detail="validate_action doit être apply ou reject")
        fields = body.get("fields", [])
        applied: list[str] = []
        rejected: list[str] = []
        errors: list[dict[str, Any]] = []
        for job_id in ids:
            try:
                with transaction(conn):
                    out = _validate_job_execute(conn, job_id, validate_action, fields, now)
                if out == "rejected":
                    rejected.append(job_id)
                else:
                    applied.append(job_id)
            except HTTPException as he:
                errors.append({"id": job_id, "message": _http_detail_str(he.detail)})
        return json_response(
            {
                "status": "ok",
                "action": action,
                "ids_count": len(ids),
                "applied": applied,
                "rejected": rejected,
                "errors": errors,
            }
        )

    if action == "set_priority":
        priority = body.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise HTTPException(status_code=400, detail="priority doit être un entier entre 1 et 100")
        if priority < 1 or priority > 100:
            raise HTTPException(status_code=400, detail="priority doit être un entier entre 1 et 100")
        placeholders = ",".join("?" * len(ids))
        with transaction(conn):
            rows = conn.execute(
                f"""
                UPDATE job SET priority = ?
                WHERE id IN ({placeholders}) AND status = 'pending'
                RETURNING id
                """,
                [priority] + ids,
            ).fetchall()
        affected = len(rows)
        return json_response(
            {"status": "ok", "action": action, "ids_count": len(ids), "affected": affected}
        )

    with transaction(conn):
        if action == "cancel":
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                UPDATE job SET status = 'cancelled', error_message = 'Annulé (bulk)', finished_at = ?
                WHERE id IN ({placeholders}) AND status IN ('pending', 'running')
                """,
                [now] + ids,
            )
        elif action == "reschedule":
            reset_retry = body.get("reset_retry", True)
            placeholders = ",".join("?" * len(ids))
            if reset_retry:
                conn.execute(
                    f"""
                    UPDATE job SET status = 'pending', error_message = NULL, scheduled_at = NULL,
                                   retry_count = 0, started_at = NULL, finished_at = NULL
                    WHERE id IN ({placeholders}) AND status = 'failed'
                    """,
                    ids,
                )
            else:
                conn.execute(
                    f"""
                    UPDATE job SET status = 'pending', error_message = NULL, scheduled_at = NULL,
                                   started_at = NULL, finished_at = NULL
                    WHERE id IN ({placeholders}) AND status = 'failed'
                    """,
                    ids,
                )
        elif action == "delete":
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                DELETE FROM job WHERE id IN ({placeholders})
                  AND status IN ('completed', 'failed', 'cancelled', 'applied', 'rejected')
                """,
                ids,
            )

    return json_response({"status": "ok", "action": action, "ids_count": len(ids)})
