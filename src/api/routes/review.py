"""Routes API pour le greffon prod (annotation humaine sur ``image_output``).

Brief : ``docs/architect/briefs/2026-05-09_brief-greffon-prod.md``.

Ce routeur greffe l'annotateur (livré v2 sur disque pour le mode benchmark)
sur les images générées par la pipeline production. Le contrat exposé est
le même ``AnnotatorItem`` côté front : seules la source des items et la
cible de persistance changent (table ``annotation`` polymorphe au lieu
de ``annotations.json``).

3 endpoints :

- ``GET  /api/review/queue``     : liste des ``image_output`` joints à leur
  ``image`` / ``job`` / ``annotation`` éventuelle, filtrable par status
  et workflow_class.
- ``GET  /api/review/file``      : sert le PNG depuis ``image_output.file_path``
  (avec validation existence en DB et garde-fou path traversal).
- ``POST /api/annotation``       : upsert sur ``(target_type, target_id)``,
  whitelist ``target_type`` (``image_output`` initialement), validation
  des tags via le module partagé ``api.annotation_vocab``.

Pas de routes ``/api/jobs/*`` modifiées : la validation effective des jobs
(``apply``/``reject``) reste dans ``jobs_editor.html``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.annotation_vocab import IMAGE_TAGS_VOCAB, PROMPT_TAGS_VOCAB
from api.db import DBConnAdapter, get_db_read, get_db_write

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["review"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = DATA_DIR / "outputs"

# Whitelist des target_type acceptés par ``POST /api/annotation``. Toute
# extension future (image, term, …) doit passer par une revue explicite
# (ajout d'un adaptateur côté API + UI éventuellement adaptée).
ALLOWED_TARGET_TYPES: frozenset[str] = frozenset({"image_output"})

# Statuts ``image.status`` acceptés en query — défaut: ``awaiting_validation``
# (≈ ce qui attend un humain). La valeur ``all`` est une convention interne
# pour ne pas filtrer.
ALLOWED_QUEUE_STATUSES: frozenset[str] = frozenset({
    "awaiting_validation",
    "generated",
    "approved",
    "rejected",
    "generating",
    "scheduled",
    "all",
})


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_resolve_image_output_path(file_path: str) -> Path:
    """Résout un ``image_output.file_path`` (relatif) en chemin absolu sûr.

    Le ``file_path`` enregistré en DB est typiquement relatif à la racine
    du projet ou au dossier ``data/outputs``. On essaye plusieurs bases et
    on garde la première qui existe ET reste sous ``DATA_DIR`` (garde-fou
    path traversal — l'attaquant pourrait insérer ``../`` via un import de
    job mal validé).
    """
    candidates: list[Path] = []
    if file_path.startswith("/") or (len(file_path) > 1 and file_path[1] == ":"):
        # Chemin absolu ou Windows drive (D:\...). On le prend tel quel
        # mais on refuse plus bas s'il sort de DATA_DIR.
        candidates.append(Path(file_path))
    else:
        candidates.append(DATA_DIR / file_path)
        candidates.append(PROJECT_ROOT / file_path)
        candidates.append(OUTPUTS_DIR / file_path)
    data_root = DATA_DIR.resolve()
    for c in candidates:
        try:
            resolved = c.resolve()
        except Exception:
            continue
        if not resolved.is_file():
            continue
        # Garde-fou path traversal : on impose que la résolution finale
        # reste sous data/.
        try:
            resolved.relative_to(data_root)
        except ValueError:
            logger.warning("review: path escapes DATA_DIR (%s)", resolved)
            continue
        return resolved
    raise HTTPException(
        status_code=404,
        detail=f"Fichier introuvable ou hors DATA_DIR : {file_path}",
    )


def _decode_json_field(raw: Any) -> Any:
    """Décode une colonne JSON cross-dialect (TEXT côté SQLite, JSONB Postgres).

    SQLAlchemy + SQLite expose les colonnes ``JSON`` comme str ou objet selon
    le driver. On normalise : str → json.loads, sinon valeur telle quelle.
    """
    if raw is None:
        return None
    if isinstance(raw, (list, dict, bool, int, float)):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            logger.warning("review: champ JSON illisible : %r", s[:50])
            return None
    return raw


def _annotation_row_to_dict(row: Any) -> dict | None:
    """Convertit une ligne SQL d'``annotation`` (avec alias ``a_*``) en dict.

    Retourne ``None`` si la jointure n'a pas matché (id NULL).
    Les colonnes attendues (dans cet ordre dans la query) :
        a_id, a_score, a_image_tags, a_prompt_tags, a_custom_tags,
        a_pattern, a_pattern_note, a_sample, a_publishable,
        a_created_at, a_updated_at
    """
    if row is None:
        return None
    a_id = row[0] if len(row) > 0 else None
    if a_id is None:
        return None
    image_tags = _decode_json_field(row[2]) or []
    prompt_tags = _decode_json_field(row[3]) or []
    custom_tags = _decode_json_field(row[4]) or []
    return {
        "id": int(a_id),
        "score": int(row[1]) if row[1] is not None else None,
        "image_tags": image_tags if isinstance(image_tags, list) else [],
        "prompt_tags": prompt_tags if isinstance(prompt_tags, list) else [],
        "custom_tags": custom_tags if isinstance(custom_tags, list) else [],
        "flags": {
            "pattern": bool(row[5]) if row[5] is not None else False,
            "pattern_note": row[6] or "",
            "sample": bool(row[7]) if row[7] is not None else False,
            "publishable": (
                bool(row[8]) if row[8] is not None else None
            ),
        },
        "created_at": row[9],
        "updated_at": row[10],
    }


# ── Pydantic models ─────────────────────────────────────────────────────────

class FlagsPayload(BaseModel):
    pattern: bool | None = False
    pattern_note: str | None = ""
    sample: bool | None = False
    publishable: bool | None = None


class AnnotationPayload(BaseModel):
    """Payload pour ``POST /api/annotation`` (upsert polymorphe).

    Validation :
    - ``score`` ∈ [1, 6] ou null
    - ``target_type`` ∈ ALLOWED_TARGET_TYPES (initialement ``image_output``)
    - ``image_tags`` ⊂ IMAGE_TAGS_VOCAB
    - ``prompt_tags`` ⊂ PROMPT_TAGS_VOCAB
    - ``custom_tags`` libres (strip + dédup côté serveur)
    """

    target_type: str
    target_id: str
    score: int | None = None
    image_tags: list[str] = Field(default_factory=list)
    prompt_tags: list[str] = Field(default_factory=list)
    custom_tags: list[str] = Field(default_factory=list)
    flags: FlagsPayload | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/review/queue")
def review_queue(
    status: str = Query("awaiting_validation"),
    workflow_class: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste les ``image_output`` joints à leur ``image`` / ``job`` / ``annotation``.

    Filtrage :
    - ``status`` : matche ``image.status`` (utiliser ``all`` pour ne pas
      filtrer). Défaut : ``awaiting_validation`` (typiquement les outputs en
      attente d'une décision humaine).
    - ``workflow_class`` : optionnel — filtre via ``job.config`` (le greffon
      ne stocke pas le workflow_class en colonne dédiée ; on fait un
      ``LIKE`` sur le JSON sérialisé du config — best effort).

    Pagination : ``limit`` (défaut 50, max 500) + ``offset``.

    Retour :
    ```json
    {
      "count": 12,
      "items": [
        {
          "filename": "...",
          "image_url": "/api/review/file?image_output_id=...",
          "prompt": "...",
          "negative": "...",
          "metrics": {"histogram": {...}, "vision_qc": {...}},
          "target_type": "image_output",
          "target_id": "<image_output.id>",
          "image_id": "...",
          "job_id": "...",
          "image_status": "...",
          "job_status": "...",
          "annotation": {...} | null
        }
      ]
    }
    ```
    """
    if status not in ALLOWED_QUEUE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown status filter: {status!r} (allowed: {sorted(ALLOWED_QUEUE_STATUSES)})",
        )

    # On stocke ``annotation.target_id`` en TEXT alors que ``image_output.id``
    # peut être TEXT côté Postgres : on cast en TEXT côté SQL pour rester
    # portable SQLite (où ``CAST(x AS TEXT)`` fonctionne aussi).
    sql = """
        SELECT
            io.id, io.file_path, io.quality_score, io.model_name,
            i.id, i.prompt, i.negative_prompt, i.status, i.title,
            j.id, j.status, j.result, j.config,
            a.id, a.score, a.image_tags, a.prompt_tags, a.custom_tags,
            a.pattern, a.pattern_note, a.sample, a.publishable,
            a.created_at, a.updated_at
        FROM image_output io
        LEFT JOIN image i ON i.id = io.image_id
        LEFT JOIN job   j ON j.id = io.job_id
        LEFT JOIN annotation a
               ON a.target_type = 'image_output'
              AND a.target_id   = CAST(io.id AS TEXT)
    """
    params: list[Any] = []
    where: list[str] = []
    if status != "all":
        where.append("i.status = ?")
        params.append(status)
    if workflow_class:
        # Best-effort LIKE sur le config JSON. Pas d'opérateur JSONB → on
        # match une sous-chaîne. C'est volontairement laxiste — le
        # ``workflow_class`` est rarement urgent à filtrer côté API et on
        # peut affiner front-side. Documenté dans le brief comme acceptable.
        where.append("j.config LIKE ?")
        params.append(f"%{workflow_class}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY io.created_at DESC NULLS LAST, io.id DESC"
    sql += " LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])

    # ``NULLS LAST`` n'est pas supporté par SQLite ; on prépare un fallback.
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        sql_fallback = sql.replace(" NULLS LAST", "")
        rows = conn.execute(sql_fallback, params).fetchall()

    items: list[dict[str, Any]] = []
    for r in rows:
        io_id = r[0]
        io_file_path = r[1] or ""
        io_quality = float(r[2]) if r[2] is not None else None
        io_model = r[3]
        image_id = r[4]
        prompt = r[5] or ""
        negative = r[6] or ""
        image_status = r[7]
        image_title = r[8]
        job_id = r[9]
        job_status = r[10]
        job_result_raw = r[11]
        job_config_raw = r[12]
        ann_row = r[13:24]

        # Best-effort metrics : on essaye de lire ``job.result`` (JSON
        # serialisé) pour exposer ``histogram`` / ``vision_qc`` si présents.
        # Pas d'opérateur JSONB → décodage Python.
        metrics: dict[str, Any] = {}
        job_result = _decode_json_field(job_result_raw)
        if isinstance(job_result, dict):
            for k in ("histogram", "vision_qc"):
                if isinstance(job_result.get(k), dict):
                    metrics[k] = job_result[k]
        # Récupère workflow_class depuis job.config si disponible.
        wf_class = None
        job_config = _decode_json_field(job_config_raw)
        if isinstance(job_config, dict):
            wf_class = job_config.get("workflow_class")

        annotation = _annotation_row_to_dict(ann_row)

        filename = Path(io_file_path).name if io_file_path else f"output-{io_id}"

        items.append({
            "filename": filename,
            "image_url": f"/api/review/file?image_output_id={io_id}",
            "prompt": prompt,
            "negative": negative,
            "metrics": metrics or None,
            "workflow_class": wf_class,
            # identifiants polymorphes (contrat AnnotatorItem)
            "target_type": "image_output",
            "target_id": str(io_id),
            # méta pipeline (traçabilité prod)
            "image_id": image_id,
            "image_title": image_title,
            "image_status": image_status,
            "job_id": job_id,
            "job_status": job_status,
            "quality_score": io_quality,
            "model_name": io_model,
            # annotation existante (jointure)
            "annotation": annotation,
        })

    return JSONResponse({"count": len(items), "items": items})


@router.get("/review/file")
def review_file(
    image_output_id: str = Query(...),
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Sert le fichier image depuis ``image_output.file_path``.

    Sécurité :
    - L'``image_output_id`` doit exister en DB (404 sinon — jamais d'accès
      filesystem direct).
    - La résolution finale doit rester sous ``DATA_DIR`` (garde-fou path
      traversal — cf. ``_safe_resolve_image_output_path``).
    """
    row = conn.execute(
        "SELECT file_path FROM image_output WHERE id = ?",
        [image_output_id],
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"image_output not found: {image_output_id}",
        )
    file_path = row[0] or ""
    if not file_path:
        raise HTTPException(
            status_code=404,
            detail=f"image_output {image_output_id} has no file_path",
        )
    abs_path = _safe_resolve_image_output_path(file_path)
    return FileResponse(str(abs_path), media_type="image/png")


@router.post("/annotation")
def upsert_annotation(
    payload: AnnotationPayload = Body(...),
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Upsert d'une annotation polymorphe sur ``(target_type, target_id)``.

    Validation :
    - ``target_type`` ∈ ALLOWED_TARGET_TYPES (400 sinon).
    - Pour ``target_type='image_output'`` : ``target_id`` doit exister
      (lookup léger sur ``image_output``, 404 si absent).
    - ``score`` ∈ [1, 6] ou null (400 sinon).
    - ``image_tags`` ⊂ IMAGE_TAGS_VOCAB, ``prompt_tags`` ⊂ PROMPT_TAGS_VOCAB
      (400 sinon).
    """
    if payload.target_type not in ALLOWED_TARGET_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unsupported target_type: {payload.target_type!r}"
                f" (allowed: {sorted(ALLOWED_TARGET_TYPES)})"
            ),
        )
    if not payload.target_id or not str(payload.target_id).strip():
        raise HTTPException(status_code=400, detail="target_id is required")

    if payload.score is not None and not (1 <= int(payload.score) <= 6):
        raise HTTPException(status_code=400, detail="score must be between 1 and 6")

    image_tags = list(payload.image_tags or [])
    unknown_image = sorted({t for t in image_tags if t not in IMAGE_TAGS_VOCAB})
    if unknown_image:
        raise HTTPException(
            status_code=400, detail=f"unknown image_tags: {unknown_image}"
        )
    prompt_tags = list(payload.prompt_tags or [])
    unknown_prompt = sorted({t for t in prompt_tags if t not in PROMPT_TAGS_VOCAB})
    if unknown_prompt:
        raise HTTPException(
            status_code=400, detail=f"unknown prompt_tags: {unknown_prompt}"
        )

    # Custom tags : strip + dédup, garde l'ordre.
    custom_tags: list[str] = []
    seen_custom: set[str] = set()
    for t in payload.custom_tags or []:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s or s in seen_custom:
            continue
        seen_custom.add(s)
        custom_tags.append(s)

    # Vérification light d'existence du target_id.
    if payload.target_type == "image_output":
        exists = conn.execute(
            "SELECT 1 FROM image_output WHERE id = ?",
            [payload.target_id],
        ).fetchone()
        if not exists:
            raise HTTPException(
                status_code=404,
                detail=f"image_output not found: {payload.target_id}",
            )

    flags_in = payload.flags or FlagsPayload()
    pattern = bool(flags_in.pattern)
    pattern_note = (flags_in.pattern_note or "").strip()
    if not pattern:
        pattern_note = ""
    sample = bool(flags_in.sample)
    publishable = (
        bool(flags_in.publishable) if flags_in.publishable is not None else None
    )

    now = _now()

    # On sérialise les listes JSON en str pour rester portable SQLite/Postgres
    # (sqlalchemy.JSON gère les deux via le driver, mais via notre adapter
    # qmark→named on passe en raw text(); sérialiser explicitement évite tout
    # surprise de driver). Postgres acceptera ce TEXT car la colonne est
    # JSONB-compatible avec un cast implicite côté driver psycopg.
    image_tags_json = json.dumps(image_tags, ensure_ascii=False)
    prompt_tags_json = json.dumps(prompt_tags, ensure_ascii=False)
    custom_tags_json = json.dumps(custom_tags, ensure_ascii=False)

    existing = conn.execute(
        "SELECT id, created_at FROM annotation WHERE target_type = ? AND target_id = ?",
        [payload.target_type, payload.target_id],
    ).fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO annotation (
                target_type, target_id, score,
                image_tags, prompt_tags, custom_tags,
                pattern, pattern_note, sample, publishable,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                payload.target_type, payload.target_id, payload.score,
                image_tags_json, prompt_tags_json, custom_tags_json,
                pattern, pattern_note, sample, publishable,
                now, now,
            ],
        )
    else:
        conn.execute(
            """
            UPDATE annotation SET
                score = ?,
                image_tags = ?,
                prompt_tags = ?,
                custom_tags = ?,
                pattern = ?,
                pattern_note = ?,
                sample = ?,
                publishable = ?,
                updated_at = ?
            WHERE target_type = ? AND target_id = ?
            """,
            [
                payload.score,
                image_tags_json, prompt_tags_json, custom_tags_json,
                pattern, pattern_note, sample, publishable,
                now,
                payload.target_type, payload.target_id,
            ],
        )

    return JSONResponse({
        "annotation": {
            "target_type": payload.target_type,
            "target_id": payload.target_id,
            "score": payload.score,
            "image_tags": image_tags,
            "prompt_tags": prompt_tags,
            "custom_tags": custom_tags,
            "flags": {
                "pattern": pattern,
                "pattern_note": pattern_note,
                "sample": sample,
                "publishable": publishable,
            },
            "created_at": existing[1] if existing is not None else now,
            "updated_at": now,
        }
    })
