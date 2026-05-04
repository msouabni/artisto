"""Routes API pour la gestion des images (concept pipeline)."""
from __future__ import annotations

import json
from pathlib import Path
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator

from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import get_i18n, json_response, transaction
from workers.comfy_client import (
    DEFAULT_WORKFLOW_TEMPLATE,
    list_workflow_template_names,
    load_workflow_template,
    sanitize_public_workflow_inputs,
    workflow_template_exists,
    workflows_json_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/images", tags=["images"])


def _ensure_origin_tag(
    conn: DBConnAdapter,
    image_id: str,
    origin_term_id: str | None,
    origin_taxonomy_id: str | None,
    now: str,
) -> None:
    """Insère le tag dérivé de origin_term_id si absent. Idempotent."""
    if not origin_term_id or not origin_taxonomy_id:
        return
    existing = conn.execute(
        "SELECT 1 FROM image_taxonomy_tag WHERE image_id=? AND taxonomy_id=? AND term_id=?",
        [image_id, origin_taxonomy_id, origin_term_id],
    ).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at) VALUES (?, ?, ?, ?)",
        [image_id, origin_taxonomy_id, origin_term_id, now],
    )

IMAGE_STATUSES = (
    "draft",        # idée initiale, minimum = titre
    "prompt_ready", # prompt(s) de génération saisi ou généré
    "scheduled",    # planifié pour génération
    "generating",   # job en cours
    "generated",    # au moins un output produit
    "approved",     # validé manuellement ou automatiquement
    "rejected",     # rejeté
    "published",    # exporté vers une collection/site
)


# ── Pydantic models ────────────────────────────────────────────────────────────

class ImagePayload(BaseModel):
    """Payload pour créer/mettre à jour un concept image."""
    id: str | None = None
    title: str = ""
    status: str = "draft"
    prompt: str = ""
    negative_prompt: str = ""
    origin_type: str = "manual"        # 'manual' | 'batch'
    origin_batch_id: str | None = None
    origin_term_id: str | None = None
    origin_taxonomy_id: str | None = None
    selected_output_id: str | None = None
    current_job_id: str | None = None


class ImageOutputPayload(BaseModel):
    """Payload pour attacher un output de génération à un concept image.
    file_path et/ou text_content requis (au moins un).
    """
    id: str | None = None
    job_id: str | None = None
    file_path: str = ""             # '' si output texte-only
    text_content: str | None = None
    file_format: str = ""
    width: int | None = None
    height: int | None = None
    quality_score: float | None = None
    model_name: str = ""
    job_config: str | None = None   # JSON sérialisé des paramètres job (évite model_config réservé Pydantic)

    @model_validator(mode="after")
    def require_file_or_text(self) -> "ImageOutputPayload":
        if not (self.file_path or self.text_content):
            raise ValueError("Au moins un de file_path ou text_content est requis")
        return self


class TagItem(BaseModel):
    """Un tag taxonomique (taxonomy_id + term_id)."""
    taxonomy_id: str
    term_id: str


class TagsPayload(BaseModel):
    """Payload pour remplacer les tags d'une image."""
    tags: list[TagItem] = []


class CreateJobPayload(BaseModel):
    """Payload pour créer un job de génération d'image."""
    prompt: str
    tags: list[TagItem] = []
    workflow_template: str | None = None
    steps: int | None = None
    cfg: float | None = None
    sampler_name: str | None = None
    scheduler: str | None = None
    denoise: float | None = None
    shift: float | None = None
    seed: int | None = None


class BulkCreateGenerationJobsPayload(BaseModel):
    """Création en masse de jobs image_generation (mêmes options optionnelles que CreateJobPayload)."""
    image_ids: list[str]
    workflow_template: str | None = None
    steps: int | None = None
    cfg: float | None = None
    sampler_name: str | None = None
    scheduler: str | None = None
    denoise: float | None = None
    shift: float | None = None
    seed: int | None = None


BULK_CREATE_GENERATION_JOBS_MAX = 25

_IMAGE_JOB_GEN_OPTIONAL_FIELDS = (
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "shift",
    "seed",
)


def _append_image_generation_optional_fields(
    config_data: dict[str, Any],
    source: CreateJobPayload | BulkCreateGenerationJobsPayload,
) -> None:
    for field in _IMAGE_JOB_GEN_OPTIONAL_FIELDS:
        val = getattr(source, field, None)
        if val is not None:
            config_data[field] = val


def build_image_generation_job_config(
    *,
    prompt: str,
    negative_prompt: str,
    tags: list[dict[str, str]],
    options: CreateJobPayload | BulkCreateGenerationJobsPayload,
    workflow_template: str | None,
) -> dict[str, Any]:
    """Construit ``job.config`` pour ``image_generation`` (même logique single et bulk)."""
    config_data: dict[str, Any] = {
        "prompt": prompt,
        "positive_prompt": prompt,
        "negative_prompt": negative_prompt,
        "tags": tags,
    }
    _append_image_generation_optional_fields(config_data, options)
    if workflow_template is not None:
        config_data["workflow_template"] = workflow_template
    return config_data


def _sanitize_image_generation_job_config(
    config_data: dict[str, Any],
    workflow_template: str | None,
) -> dict[str, Any]:
    """Préflight léger : ne garder dans `job.config` que les champs publics supportés par le workflow."""
    wf_name = workflow_template or DEFAULT_WORKFLOW_TEMPLATE
    wf_dir = workflows_json_dir()
    _, _, contract = load_workflow_template(wf_dir, wf_name)
    public_inputs = contract.get("public_inputs") or {}
    capabilities = contract.get("capabilities") or {}
    if "positive_prompt" not in public_inputs or capabilities.get("positive_prompt") == "unsupported":
        raise HTTPException(
            status_code=422,
            detail=f"Le workflow '{wf_name}' n'expose pas de `positive_prompt` public compatible.",
        )

    positive_prompt = str(config_data.get("positive_prompt") or config_data.get("prompt") or "").strip()
    candidate_values: dict[str, Any] = {
        "positive_prompt": positive_prompt,
        "negative_prompt": str(config_data.get("negative_prompt") or "").strip(),
        "seed": config_data.get("seed"),
        "steps": config_data.get("steps"),
        "cfg": config_data.get("cfg"),
        "width": config_data.get("width"),
        "height": config_data.get("height"),
        "batch_size": config_data.get("batch_size"),
        "sampler_name": config_data.get("sampler_name"),
        "scheduler": config_data.get("scheduler"),
        "denoise": config_data.get("denoise"),
        "shift": config_data.get("shift"),
    }
    allowed_public = sanitize_public_workflow_inputs(candidate_values, contract)

    sanitized = dict(config_data)
    sanitized["prompt"] = positive_prompt
    sanitized["positive_prompt"] = positive_prompt
    sanitized["workflow_template"] = wf_name
    sanitized["workflow_contract_version"] = contract.get("contract_version")

    managed_fields = (
        "negative_prompt",
        "seed",
        "steps",
        "cfg",
        "width",
        "height",
        "batch_size",
        "sampler_name",
        "scheduler",
        "denoise",
        "shift",
    )
    for field in managed_fields:
        if field in allowed_public:
            sanitized[field] = allowed_public[field]
        else:
            sanitized.pop(field, None)
    return sanitized


class JobsBatchPayload(BaseModel):
    """Payload pour mettre à jour les jobs d'une image (modal Enregistrer)."""
    current_job_id: str | None = None
    cancel_job_ids: list[str] = []


# ── Colonnes DB ────────────────────────────────────────────────────────────────

IMG_COLS = [
    "id", "title", "status", "prompt", "negative_prompt",
    "origin_type", "origin_batch_id", "origin_term_id", "origin_taxonomy_id",
    "selected_output_id", "current_job_id", "created_at", "updated_at",
]

IMG_OUTPUT_COLS = [
    "id", "image_id", "job_id", "file_path", "text_content", "file_format",
    "width", "height", "quality_score", "model_name", "model_config", "created_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_optional_workflow_template(value: str | None) -> str | None:
    """Si renseigné et non vide : valide l'existence de `data/workflows/{nom}.json`. Sinon None (défaut worker)."""
    if value is None:
        return None
    name = str(value).strip()
    if not name:
        return None
    wf_dir = workflows_json_dir()
    if not workflow_template_exists(wf_dir, name):
        available = list_workflow_template_names(wf_dir)
        hint = ", ".join(available) if available else "(aucun fichier *.json)"
        raise HTTPException(
            status_code=422,
            detail=f"workflow_template inconnu : {name!r}. Disponibles : {hint}",
        )
    return name


def _row_to_dict(row: tuple, cols: list[str]) -> dict[str, Any]:
    d = dict(zip(cols, row))
    for field in ("width", "height"):
        if d.get(field) is not None:
            d[field] = int(d[field])
    if d.get("quality_score") is not None:
        d["quality_score"] = float(d["quality_score"])
    return d


def _get_image_row(conn: DBConnAdapter, image_id: str) -> dict[str, Any]:
    rows = conn.execute(
        f"SELECT {', '.join(IMG_COLS)} FROM image WHERE id = ?", [image_id]
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")
    return _row_to_dict(rows[0], IMG_COLS)


def _validate_status(status: str) -> None:
    if status not in IMAGE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Statut invalide : '{status}'. Valeurs acceptées : {', '.join(IMAGE_STATUSES)}",
        )


# ── Endpoints image (concept) ──────────────────────────────────────────────────

@router.get("")
def list_images(
    status: str | None = None,
    status_in: str | None = None,
    origin_term_id: str | None = None,
    origin_batch_id: str | None = None,
    origin_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste les images-concepts avec filtres optionnels.
    status_in: valeurs séparées par virgule (ex: generating,scheduled)."""
    conditions: list[str] = []
    params: list[Any] = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    elif status_in:
        vals = [s.strip() for s in status_in.split(",") if s.strip()]
        if vals:
            placeholders = ", ".join("?" * len(vals))
            conditions.append(f"status IN ({placeholders})")
            params.extend(vals)
    if origin_term_id:
        conditions.append("origin_term_id = ?")
        params.append(origin_term_id)
    if origin_batch_id:
        conditions.append("origin_batch_id = ?")
        params.append(origin_batch_id)
    if origin_type:
        conditions.append("origin_type = ?")
        params.append(origin_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = (
        f"SELECT {', '.join(IMG_COLS)} FROM image "
        f"{where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])

    rows = conn.execute(sql, params).fetchall()
    items = [_row_to_dict(list(r), IMG_COLS) for r in rows]
    return json_response(items)


# ─── Import diff ────────────────────────────────────────────────────────────────

_IMG_DIFF_FIELDS = [
    "title", "status", "prompt", "negative_prompt",
    "origin_type", "origin_batch_id", "origin_term_id", "origin_taxonomy_id",
]

_IMG_VALID_OPS = {"add", "upsert", "update", "remove"}


def _img_normalize_diff_op(raw_op: dict) -> dict:
    op = raw_op.get("op", "")
    value = raw_op.get("value") or {}
    if op == "replace":
        op = "upsert"
    return {"op": op, "value": value}


def _img_to_flat(r: dict) -> dict:
    return {
        "id": r.get("id", ""),
        "title": r.get("title") or "",
        "status": r.get("status") or "draft",
        "prompt": r.get("prompt") or "",
        "negative_prompt": r.get("negative_prompt") or "",
        "origin_type": r.get("origin_type") or "manual",
        "origin_batch_id": r.get("origin_batch_id") or "",
        "origin_term_id": r.get("origin_term_id") or "",
        "origin_taxonomy_id": r.get("origin_taxonomy_id") or "",
    }


def _img_compute_diff(current: dict, incoming: dict) -> dict:
    """N'inclut que les champs explicitement fournis dans incoming."""
    diff: dict[str, dict] = {}
    for field in _IMG_DIFF_FIELDS:
        if field not in incoming:
            continue
        cur_val = (current.get(field) or "").strip() if isinstance(current.get(field), str) else (current.get(field) or "")
        inc_val = (incoming.get(field) or "").strip() if isinstance(incoming.get(field), str) else (incoming.get(field) or "")
        if cur_val != inc_val:
            diff[field] = {"from": cur_val, "to": inc_val}
    return diff


def _validate_img_diff_operations(
    operations: list[dict],
    existing_ids: set[str],
) -> list[dict]:
    batch_added_ids: set[str] = set()
    results: list[dict] = []

    for i, raw_op in enumerate(operations):
        normalized = _img_normalize_diff_op(raw_op)
        op = normalized["op"]
        value = normalized["value"]

        image_id = str(value.get("id") or "").strip()
        if not image_id:
            image_id = "img_" + str(int(time.time() * 1000) + i)

        result: dict[str, Any] = {
            "index": i,
            "op": op,
            "image_id": image_id,
            "status": "ready",
            "message": None,
            "incoming": {**value, "id": image_id},
            "current": None,
            "diff": None,
        }

        if op not in _IMG_VALID_OPS:
            result["status"] = "error"
            result["message"] = f"Opération inconnue : '{op}'"
            results.append(result)
            continue

        exists = image_id in existing_ids

        if op == "add":
            if exists:
                result["status"] = "conflict"
                result["message"] = f"Image '{image_id}' existe déjà (utilisez 'upsert')"
            else:
                result["status"] = "ready"
                batch_added_ids.add(image_id)

        elif op == "upsert":
            result["status"] = "update" if exists else "ready"
            if not exists:
                batch_added_ids.add(image_id)

        elif op == "update":
            if not exists:
                result["status"] = "error"
                result["message"] = f"Image '{image_id}' n'existe pas"
            else:
                result["status"] = "update"

        elif op == "remove":
            result["status"] = "skip" if not exists else "ready"
            if not exists:
                result["message"] = f"Image '{image_id}' introuvable"

        results.append(result)

    return results


@router.post("/import/diff")
def import_diff(
    operations: list = Body(...),
    dry_run: bool = True,
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """
    Import de diffs JSON pour les images-concepts.
    dry_run=true : preview sans appliquer.
    dry_run=false : applique les opérations.
    Format : [{ "op": "add"|"upsert"|"remove", "value": {...} }]
    """
    rows = conn.execute(
        f"SELECT {', '.join(IMG_COLS)} FROM image"
    ).fetchall()
    existing_map: dict[str, dict] = {}
    for r in rows:
        d = _row_to_dict(list(r), IMG_COLS)
        existing_map[d["id"]] = d
    existing_ids = set(existing_map.keys())

    validated = _validate_img_diff_operations(operations, existing_ids)

    for op_result in validated:
        if op_result["status"] == "update":
            current = existing_map.get(op_result["image_id"])
            if current:
                current_flat = _img_to_flat(current)
                op_result["current"] = current_flat
                op_result["diff"] = _img_compute_diff(current_flat, op_result["incoming"])
                if not op_result["diff"]:
                    op_result["status"] = "skip"
                    op_result["message"] = "Aucune modification détectée"

    summary: dict[str, int] = {"ready": 0, "update": 0, "conflict": 0, "error": 0, "skip": 0}
    for r in validated:
        s = r["status"]
        summary[s] = summary.get(s, 0) + 1

    if dry_run:
        return json_response({
            "dry_run": True,
            "summary": summary,
            "operations": validated,
        })

    applied: list[str] = []
    now = _now()

    with transaction(conn):
        for op_result in validated:
            op = op_result["op"]
            image_id = op_result["image_id"]
            status = op_result["status"]
            value = op_result["incoming"]

            if status in ("skip", "conflict", "error"):
                continue

            if op in ("add", "upsert") and status in ("ready", "update"):
                # Pour upsert sur image existante : fusionner avec l'existant (ne pas écraser les champs absents)
                existing_row = existing_map.get(image_id)
                if existing_row and op == "upsert":
                    current_flat = _img_to_flat(existing_row)
                    merged = dict(current_flat)
                    for field in _IMG_DIFF_FIELDS:
                        if field in value:
                            merged[field] = value[field]
                    value = merged

                title = (value.get("title") or image_id).strip()
                status_val = (value.get("status") or "draft").strip()
                _validate_status(status_val)
                prompt = (value.get("prompt") or "").strip()
                negative_prompt = (value.get("negative_prompt") or "").strip()
                origin_type = (value.get("origin_type") or "manual").strip()
                origin_batch_id = (value.get("origin_batch_id") or "").strip() or None
                origin_term_id = (value.get("origin_term_id") or "").strip() or None
                origin_taxonomy_id = (value.get("origin_taxonomy_id") or "").strip() or None
                existing = conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone()

                if existing and op == "upsert":
                    conn.execute(
                        """UPDATE image SET title=?, status=?, prompt=?, negative_prompt=?,
                           origin_type=?, origin_batch_id=?, origin_term_id=?,
                           origin_taxonomy_id=?, updated_at=? WHERE id=?""",
                        [
                            title, status_val, prompt, negative_prompt,
                            origin_type, origin_batch_id, origin_term_id,
                            origin_taxonomy_id, now, image_id,
                        ],
                    )
                    _ensure_origin_tag(conn, image_id, origin_term_id, origin_taxonomy_id, now)
                else:
                    conn.execute(
                        """INSERT INTO image
                           (id, title, status, prompt, negative_prompt,
                            origin_type, origin_batch_id, origin_term_id, origin_taxonomy_id,
                            selected_output_id, file_path, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [
                            image_id, title, status_val, prompt, negative_prompt,
                            origin_type, origin_batch_id, origin_term_id, origin_taxonomy_id,
                            None, "", now, now,
                        ],
                    )
                    _ensure_origin_tag(conn, image_id, origin_term_id, origin_taxonomy_id, now)
                applied.append(image_id)

            elif op == "remove" and status == "ready":
                conn.execute("DELETE FROM image WHERE id = ?", [image_id])
                applied.append(image_id)

    return json_response({
        "applied_count": len(applied),
        "applied_ids": applied,
    })


def _get_current_job(conn: DBConnAdapter, image_id: str) -> dict[str, Any] | None:
    """Retourne le current job pour une image.
    Si image.current_job_id est défini et le job existe, on l'utilise.
    Sinon : dernier job créé (ORDER BY created_at DESC).
    """
    try:
        # Vérifier si current_job_id est défini sur l'image
        row_img = conn.execute(
            "SELECT current_job_id FROM image WHERE id = ?", [image_id]
        ).fetchone()
        current_job_id = row_img[0] if row_img and row_img[0] else None

        if current_job_id:
            rows = conn.execute(
                """
                SELECT id, type, status, created_at, error_message
                FROM job
                WHERE id = ? AND image_id = ? AND type = 'image_generation'
                """,
                [current_job_id, image_id],
            ).fetchall()
            if rows:
                r = rows[0]
                return {
                    "id": r[0],
                    "type": r[1],
                    "status": r[2],
                    "created_at": r[3],
                    "error_message": r[4],
                }

        # Fallback : dernier créé
        rows = conn.execute(
            """
            SELECT id, type, status, created_at, error_message
            FROM job
            WHERE image_id = ? AND type = 'image_generation'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [image_id],
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        "id": r[0],
        "type": r[1],
        "status": r[2],
        "created_at": r[3],
        "error_message": r[4],
    }


def _get_current_job_output(
    conn: DBConnAdapter, image_id: str, job_id: str
) -> dict[str, Any] | None:
    """Retourne l'output du job si un fichier est associé (completed, awaiting_validation, applied), ou None.
    Inclut file_path, text_content, file_format, width, height, model_name, created_at pour le modal.
    """
    try:
        rows = conn.execute(
            """
            SELECT file_path, text_content, file_format, width, height,
                   quality_score, model_name, created_at
            FROM image_output
            WHERE job_id = ? AND image_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [job_id, image_id],
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        "file_path": r[0] or "",
        "text_content": r[1],
        "file_format": r[2] or "",
        "width": int(r[3]) if r[3] is not None else None,
        "height": int(r[4]) if r[4] is not None else None,
        "quality_score": float(r[5]) if r[5] is not None else None,
        "model_name": r[6] or "",
        "created_at": r[7],
    }


@router.post("/bulk-create-generation-jobs")
def bulk_create_generation_jobs(
    payload: BulkCreateGenerationJobsPayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """
    Crée un job `image_generation` pour chaque image listée, avec contrôles :
    - statut exactement `prompt_ready`
    - prompt non vide
    - aucun job pending/running/awaiting_validation du même type pour l'image (sinon erreur par ligne).

    Les tags sont lus depuis `image_taxonomy_tag`. Le prompt négatif est repris de l'image.
    Optionnel : `workflow_template` (nom sans `.json` sous `data/workflows/`) ; sinon défaut worker.
    """
    raw_ids = [str(x).strip() for x in (payload.image_ids or []) if str(x).strip()]
    image_ids: list[str] = []
    seen: set[str] = set()
    for i in raw_ids:
        if i not in seen:
            seen.add(i)
            image_ids.append(i)

    if not image_ids:
        raise HTTPException(status_code=400, detail="Fournir au moins un `image_id` dans `image_ids`.")
    if len(image_ids) > BULK_CREATE_GENERATION_JOBS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {BULK_CREATE_GENERATION_JOBS_MAX} images par requête.",
        )

    workflow_tpl = _normalize_optional_workflow_template(payload.workflow_template)

    results: list[dict[str, Any]] = []
    success = 0
    failed = 0

    for idx, image_id in enumerate(image_ids):
        row = conn.execute(
            "SELECT status, prompt, negative_prompt FROM image WHERE id = ?",
            [image_id],
        ).fetchone()
        if not row:
            failed += 1
            results.append({"image_id": image_id, "ok": False, "error": "Image introuvable."})
            continue

        status = str(row[0] or "").strip()
        prompt = str(row[1] or "").strip()
        negative_prompt = str(row[2] or "").strip()

        if status != "prompt_ready":
            failed += 1
            results.append(
                {
                    "image_id": image_id,
                    "ok": False,
                    "error": f"Statut « {status or 'vide'} » : requis « prompt_ready ».",
                }
            )
            continue

        if not prompt:
            failed += 1
            results.append({"image_id": image_id, "ok": False, "error": "Prompt vide."})
            continue

        existing = conn.execute(
            """
            SELECT 1 FROM job WHERE image_id = ? AND type = 'image_generation'
              AND status IN ('pending', 'running', 'awaiting_validation')
            """,
            [image_id],
        ).fetchone()
        if existing:
            failed += 1
            results.append(
                {
                    "image_id": image_id,
                    "ok": False,
                    "error": "Un job de génération est déjà en cours ou en attente de validation pour cette image.",
                }
            )
            continue

        tag_rows = conn.execute(
            "SELECT taxonomy_id, term_id FROM image_taxonomy_tag WHERE image_id = ?",
            [image_id],
        ).fetchall()
        tags = [{"taxonomy_id": str(t[0]), "term_id": str(t[1])} for t in tag_rows]

        job_id = f"job_gen_{time.time_ns()}_{idx}"
        now = _now()
        config_data = build_image_generation_job_config(
            prompt=prompt,
            negative_prompt=negative_prompt,
            tags=tags,
            options=payload,
            workflow_template=workflow_tpl,
        )
        config_data = _sanitize_image_generation_job_config(config_data, workflow_tpl)
        config = json.dumps(config_data, ensure_ascii=False)

        try:
            with transaction(conn):
                conn.execute(
                    """INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id)
                       VALUES (?, 'image_generation', 'pending', ?, ?, ?, 'image', ?)""",
                    [job_id, image_id, config, now, image_id],
                )
                conn.execute(
                    """UPDATE image SET status = 'scheduled', updated_at = ?
                       WHERE id = ? AND status NOT IN ('generating', 'generated', 'approved', 'published')""",
                    [now, image_id],
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("bulk_create_generation_jobs failed for %s", image_id)
            failed += 1
            results.append({"image_id": image_id, "ok": False, "error": str(exc)})
            continue

        success += 1
        results.append({"image_id": image_id, "ok": True, "job_id": job_id})

    return json_response(
        {
            "results": results,
            "summary": {"total": len(image_ids), "success": success, "failed": failed},
        }
    )


@router.get("/{image_id}")
def get_image(
    image_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Détail d'un concept image, avec current_job et current_job_output si applicable."""
    data = _get_image_row(conn, image_id)
    current_job = _get_current_job(conn, image_id)
    if current_job:
        data["current_job"] = current_job
        if current_job["status"] in ("completed", "awaiting_validation", "applied"):
            output = _get_current_job_output(conn, image_id, current_job["id"])
            if output:
                data["current_job_output"] = output
    else:
        data["current_job"] = None
    return json_response(data)


@router.get("/{image_id}/jobs")
def list_jobs(
    image_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste les jobs associés à l'image, triés par created_at DESC."""
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")
    try:
        rows = conn.execute(
            """
            SELECT j.id, j.type, j.status, j.started_at, j.finished_at,
                   j.error_message, j.created_at
            FROM job j
            WHERE j.image_id = ?
            ORDER BY j.created_at DESC
            """,
            [image_id],
        ).fetchall()
    except Exception as e:
        if "image_id" in str(e).lower():
            return json_response([])
        raise
    cols = [
        "id", "type", "status", "started_at", "finished_at",
        "error_message", "created_at",
    ]
    items = [dict(zip(cols, r)) for r in rows]
    return json_response(items)


@router.patch("/{image_id}/jobs")
def update_jobs_batch(
    image_id: str,
    payload: JobsBatchPayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Met à jour les jobs d'une image : current_job_id et/ou annulation de jobs.
    Après enregistrement, le formulaire et la table doivent être rafraîchis côté client.
    """
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    now = _now()
    with transaction(conn):
        # Mettre à jour current_job_id sur l'image
        if payload.current_job_id is not None:
            # Vérifier que le job appartient à l'image
            if payload.current_job_id:
                row = conn.execute(
                    "SELECT 1 FROM job WHERE id = ? AND image_id = ?",
                    [payload.current_job_id, image_id],
                ).fetchone()
                if not row:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Job '{payload.current_job_id}' n'appartient pas à l'image",
                    )
            conn.execute(
                "UPDATE image SET current_job_id = ?, updated_at = ? WHERE id = ?",
                [payload.current_job_id or None, now, image_id],
            )

        # Annuler les jobs (pending ou running uniquement)
        for job_id in payload.cancel_job_ids or []:
            conn.execute(
                """UPDATE job SET status = 'cancelled', error_message = 'Annulé par l''utilisateur'
                   WHERE id = ? AND image_id = ? AND status IN ('pending', 'running')""",
                [job_id, image_id],
            )

    return json_response({"status": "ok", "image_id": image_id})


@router.post("/{image_id}/jobs")
def create_job(
    image_id: str,
    payload: CreateJobPayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Crée un job de génération d'image (type=image_generation).
    Stocke prompt + tags + paramètres optionnels (workflow_template, steps, cfg,
    sampler_name, scheduler, denoise, shift, seed) dans job.config pour le worker ComfyUI.
    Rejette (409) si un job pending ou running existe déjà pour cette image.
    """
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    workflow_tpl = _normalize_optional_workflow_template(payload.workflow_template)

    row_neg = conn.execute(
        "SELECT negative_prompt FROM image WHERE id = ?",
        [image_id],
    ).fetchone()
    negative_from_image = str(row_neg[0] or "").strip() if row_neg else ""

    existing = conn.execute(
        """
        SELECT 1 FROM job WHERE image_id = ? AND type = 'image_generation'
          AND status IN ('pending', 'running', 'awaiting_validation')
        """,
        [image_id],
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Un job de génération est déjà en cours ou en attente de validation pour cette image.",
        )

    job_id = "job_gen_" + str(int(time.time() * 1000))
    now = _now()
    config_data = build_image_generation_job_config(
        prompt=payload.prompt,
        negative_prompt=negative_from_image,
        tags=[{"taxonomy_id": t.taxonomy_id, "term_id": t.term_id} for t in payload.tags],
        options=payload,
        workflow_template=workflow_tpl,
    )
    config_data = _sanitize_image_generation_job_config(config_data, workflow_tpl)
    config = json.dumps(config_data)

    with transaction(conn):
        conn.execute(
            """INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id)
               VALUES (?, 'image_generation', 'pending', ?, ?, ?, 'image', ?)""",
            [job_id, image_id, config, now, image_id],
        )
        conn.execute(
            """UPDATE image SET status = 'scheduled', updated_at = ?
               WHERE id = ? AND status NOT IN ('generating', 'generated', 'approved', 'published')""",
            [now, image_id],
        )
    return json_response({"status": "created", "id": job_id, "image_id": image_id})


@router.post("")
def create_image(
    payload: ImagePayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Crée un nouveau concept image."""
    image_id = (payload.id or "").strip()
    if not image_id:
        image_id = "img_" + str(int(time.time() * 1000))

    if conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=409, detail=f"Image '{image_id}' existe déjà")

    _validate_status(payload.status)
    now = _now()

    with transaction(conn):
        conn.execute(
            """INSERT INTO image
               (id, title, status, prompt, negative_prompt,
                origin_type, origin_batch_id, origin_term_id, origin_taxonomy_id,
                selected_output_id, file_path, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                image_id, payload.title or image_id, payload.status,
                payload.prompt, payload.negative_prompt,
                payload.origin_type, payload.origin_batch_id,
                payload.origin_term_id, payload.origin_taxonomy_id,
                payload.selected_output_id, "", now, now,
            ],
        )
        _ensure_origin_tag(conn, image_id, payload.origin_term_id, payload.origin_taxonomy_id, now)

    return json_response({"status": "created", "id": image_id})


@router.put("/{image_id}")
def update_image(
    image_id: str,
    payload: ImagePayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Met à jour un concept image (upsert)."""
    _validate_status(payload.status)
    now = _now()
    existing = conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone()

    with transaction(conn):
        if existing:
            # Ne pas écraser origin_term_id/origin_taxonomy_id si non fournis (dérivés des tags)
            origin_term_id = payload.origin_term_id
            origin_taxonomy_id = payload.origin_taxonomy_id
            if origin_term_id is None and origin_taxonomy_id is None:
                row = conn.execute(
                    "SELECT origin_term_id, origin_taxonomy_id FROM image WHERE id = ?",
                    [image_id],
                ).fetchone()
                if row:
                    origin_term_id, origin_taxonomy_id = row[0], row[1]
            # Préserver current_job_id si non fourni (géré via modal jobs)
            current_job_id = payload.current_job_id
            if current_job_id is None:
                row = conn.execute(
                    "SELECT current_job_id FROM image WHERE id = ?", [image_id]
                ).fetchone()
                current_job_id = row[0] if row else None
            # Auto-promouvoir draft → prompt_ready si prompt non vide
            row = conn.execute("SELECT status FROM image WHERE id = ?", [image_id]).fetchone()
            current_status = row[0] if row else None
            status_to_use = payload.status
            if current_status == "draft" and (payload.prompt or "").strip():
                status_to_use = "prompt_ready"
            conn.execute(
                """UPDATE image SET
                       title=?, status=?, prompt=?, negative_prompt=?,
                       origin_type=?, origin_batch_id=?, origin_term_id=?,
                       origin_taxonomy_id=?, selected_output_id=?, current_job_id=?, updated_at=?
                   WHERE id=?""",
                [
                    payload.title, status_to_use, payload.prompt, payload.negative_prompt,
                    payload.origin_type, payload.origin_batch_id, origin_term_id,
                    origin_taxonomy_id, payload.selected_output_id, current_job_id, now, image_id,
                ],
            )
            _ensure_origin_tag(conn, image_id, origin_term_id, origin_taxonomy_id, now)
        else:
            conn.execute(
                """INSERT INTO image
                   (id, title, status, prompt, negative_prompt,
                    origin_type, origin_batch_id, origin_term_id, origin_taxonomy_id,
                    selected_output_id, current_job_id, file_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    image_id, payload.title or image_id, payload.status,
                    payload.prompt, payload.negative_prompt,
                    payload.origin_type, payload.origin_batch_id,
                    payload.origin_term_id, payload.origin_taxonomy_id,
                    payload.selected_output_id, payload.current_job_id, "", now, now,
                ],
            )
            _ensure_origin_tag(conn, image_id, payload.origin_term_id, payload.origin_taxonomy_id, now)

    return json_response({"status": "ok", "id": image_id})


@router.delete("/{image_id}")
def delete_image(
    image_id: str,
    force: bool = False,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Supprime un concept image. 409 si des références existent (sauf si force=True)."""
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    refs: dict[str, int] = {}
    for table, col in [
        ("image_output",       "image_id"),
        ("image_taxonomy_tag", "image_id"),
        ("collection_image",   "image_id"),
        ("site_publication",   "image_id"),
        ("image_postprocess",  "image_id"),
        ("job",                "image_id"),
    ]:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", [image_id]).fetchone()
            refs[table] = int(row[0]) if row else 0
        except Exception:
            refs[table] = 0

    if not force and any(v > 0 for v in refs.values()):
        raise HTTPException(
            status_code=409,
            detail={"message": "Image encore référencée", "references": refs},
        )

    if force:
        for table, col in [
            ("image_output",       "image_id"),
            ("image_taxonomy_tag", "image_id"),
            ("collection_image",   "image_id"),
            ("site_publication",   "image_id"),
            ("image_postprocess",  "image_id"),
            ("job",                "image_id"),
        ]:
            try:
                conn.execute(f"DELETE FROM {table} WHERE {col} = ?", [image_id])
            except Exception:
                pass
    try:
        conn.execute("DELETE FROM image WHERE id = ?", [image_id])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return json_response({"status": "deleted", "id": image_id})


# ── Endpoints image_output ─────────────────────────────────────────────────────

@router.get("/{image_id}/outputs")
def list_outputs(
    image_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste tous les outputs de génération d'un concept image, avec infos job (type, status, etc.)."""
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    try:
        rows = conn.execute(
            """
            SELECT io.id, io.image_id, io.job_id, io.file_path, io.text_content, io.file_format,
                   io.width, io.height, io.quality_score, io.model_name, io.model_config, io.created_at,
                   j.type AS job_type, j.status AS job_status, j.started_at AS job_started_at,
                   j.finished_at AS job_finished_at, j.error_message AS job_error_message
            FROM image_output io
            LEFT JOIN job j ON j.id = io.job_id
            WHERE io.image_id = ?
            ORDER BY io.created_at DESC
            """,
            [image_id],
        ).fetchall()
        cols = IMG_OUTPUT_COLS + [
            "job_type", "job_status", "job_started_at", "job_finished_at", "job_error_message"
        ]
    except Exception:
        rows = conn.execute(
            """
            SELECT io.id, io.image_id, io.job_id, io.file_path, io.file_format,
                   io.width, io.height, io.quality_score, io.model_name, io.model_config, io.created_at,
                   j.type AS job_type, j.status AS job_status, j.started_at AS job_started_at,
                   j.finished_at AS job_finished_at, j.error_message AS job_error_message
            FROM image_output io
            LEFT JOIN job j ON j.id = io.job_id
            WHERE io.image_id = ?
            ORDER BY io.created_at DESC
            """,
            [image_id],
        ).fetchall()
        cols = [
            "id", "image_id", "job_id", "file_path", "file_format",
            "width", "height", "quality_score", "model_name", "model_config", "created_at",
        ] + [
            "job_type", "job_status", "job_started_at", "job_finished_at", "job_error_message"
        ]
    items = [_row_to_dict(r, cols) for r in rows]
    for item in items:
        if "text_content" not in item:
            item["text_content"] = None
    return json_response(items)


@router.post("/{image_id}/outputs")
def add_output(
    image_id: str,
    payload: ImageOutputPayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Attache un nouvel output de génération à un concept image.
    
    Met automatiquement à jour selected_output_id si c'est le premier output,
    et passe le statut de l'image à 'generated'.
    """
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    output_id = (payload.id or "").strip()
    if not output_id:
        output_id = "out_" + str(int(time.time() * 1000))

    if conn.execute("SELECT 1 FROM image_output WHERE id = ?", [output_id]).fetchone():
        raise HTTPException(status_code=409, detail=f"Output '{output_id}' existe déjà")

    now = _now()

    file_path = payload.file_path or ""
    with transaction(conn):
        try:
            conn.execute(
                """INSERT INTO image_output
                   (id, image_id, job_id, file_path, text_content, file_format,
                    width, height, quality_score, model_name, model_config, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    output_id, image_id, payload.job_id, file_path, payload.text_content,
                    payload.file_format, payload.width, payload.height,
                    payload.quality_score, payload.model_name, payload.job_config, now,
                ],
            )
        except Exception:
            conn.execute(
                """INSERT INTO image_output
                   (id, image_id, job_id, file_path, file_format,
                    width, height, quality_score, model_name, model_config, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    output_id, image_id, payload.job_id, file_path,
                    payload.file_format, payload.width, payload.height,
                    payload.quality_score, payload.model_name, payload.job_config, now,
                ],
            )

        # Mettre à jour le concept : selected_output_id + statut generated
        existing_output_count = conn.execute(
            "SELECT COUNT(*) FROM image_output WHERE image_id = ?", [image_id]
        ).fetchone()[0]

        update_selected = existing_output_count == 1  # premier output = sélectionné par défaut

        if update_selected:
            conn.execute(
                """UPDATE image SET
                       selected_output_id = ?,
                       status = CASE WHEN status IN ('scheduled','generating','draft','prompt_ready')
                                     THEN 'generated' ELSE status END,
                       updated_at = ?
                   WHERE id = ?""",
                [output_id, now, image_id],
            )
        else:
            conn.execute(
                """UPDATE image SET
                       status = CASE WHEN status IN ('scheduled','generating')
                                     THEN 'generated' ELSE status END,
                       updated_at = ?
                   WHERE id = ?""",
                [now, image_id],
            )

    return json_response({"status": "created", "id": output_id, "image_id": image_id})


@router.put("/{image_id}/outputs/{output_id}/select")
def select_output(
    image_id: str,
    output_id: str,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Sélectionne un output comme output principal du concept."""
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    if not conn.execute(
        "SELECT 1 FROM image_output WHERE id = ? AND image_id = ?", [output_id, image_id]
    ).fetchone():
        raise HTTPException(
            status_code=404,
            detail=f"Output '{output_id}' non trouvé pour l'image '{image_id}'",
        )

    now = _now()
    conn.execute(
        "UPDATE image SET selected_output_id = ?, updated_at = ? WHERE id = ?",
        [output_id, now, image_id],
    )
    return json_response({"status": "ok", "selected_output_id": output_id})


# ── Endpoints image_taxonomy_tag ───────────────────────────────────────────────

@router.get("/{image_id}/tags")
def list_tags(
    image_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste les tags taxonomiques d'un concept image (avec name_fr pour affichage)."""
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    rows = conn.execute(
        """
        SELECT it.taxonomy_id, it.term_id, t.name_i18n
        FROM image_taxonomy_tag it
        JOIN vocabulary v ON v.taxonomy_id = it.taxonomy_id
        JOIN term t ON t.id = it.term_id AND t.vocabulary_id = v.id
        WHERE it.image_id = ?
        ORDER BY it.taxonomy_id, it.term_id
        """,
        [image_id],
    ).fetchall()

    tags = []
    for row in rows:
        taxonomy_id, term_id, name_i18n = row
        name_fr = get_i18n(name_i18n, "fr") if name_i18n else ""
        tags.append({"taxonomy_id": taxonomy_id, "term_id": term_id, "name_fr": name_fr})
    return json_response({"tags": tags})


@router.put("/{image_id}/tags")
def update_tags(
    image_id: str,
    payload: TagsPayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Remplace tous les tags taxonomiques de l'image par la liste fournie."""
    if not conn.execute("SELECT 1 FROM image WHERE id = ?", [image_id]).fetchone():
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' non trouvée")

    now = _now()
    with transaction(conn):
        conn.execute("DELETE FROM image_taxonomy_tag WHERE image_id = ?", [image_id])
        first_tag = None
        for item in payload.tags:
            if not item.taxonomy_id.strip() or not item.term_id.strip():
                continue
            if first_tag is None:
                first_tag = (item.taxonomy_id.strip(), item.term_id.strip())
            conn.execute(
                """INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                [image_id, item.taxonomy_id.strip(), item.term_id.strip(), now],
            )
        # Dériver origin_term_id / origin_taxonomy_id du premier tag
        if first_tag:
            conn.execute(
                "UPDATE image SET origin_taxonomy_id = ?, origin_term_id = ? WHERE id = ?",
                [first_tag[0], first_tag[1], image_id],
            )
        else:
            conn.execute(
                "UPDATE image SET origin_taxonomy_id = NULL, origin_term_id = NULL WHERE id = ?",
                [image_id],
            )
    return json_response({"status": "ok", "count": len(payload.tags)})


# ── Endpoints output preview ────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_DIR = PROJECT_ROOT / "data" / "outputs"


@router.get("/{image_id}/latest-output-thumb")
def latest_output_thumb(
    image_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Renvoie le fichier image du dernier output pour un concept image (pour aperçu UI)."""
    row = conn.execute(
        """
        SELECT file_path FROM image_output
        WHERE image_id = ? AND file_path IS NOT NULL AND file_path != ''
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [image_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Aucun output pour cette image")
    file_path = row[0]
    abs_path = OUTPUTS_DIR.parent / file_path if not file_path.startswith("/") else Path(file_path)
    if not abs_path.exists():
        abs_path = PROJECT_ROOT / "data" / file_path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"Fichier introuvable : {file_path}")
    return FileResponse(str(abs_path), media_type="image/png")
