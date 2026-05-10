"""Routes API pour le modèle ``subject`` (sous-objet éditorial d'un ``term``).

Brief : ``docs/architect/briefs/2026-05-10_brief-modele-subject.md``.

Un ``subject`` matérialise un sujet concret rattaché à un term taxonomique
(ex. term=``lion`` → subjects=``lion mâle adulte sur rocher``). Endpoints CRUD
minimaux avec validation Pydantic stricte (whitelist tags, whitelist status,
note 0-6, unicité ``(term_id, name)``).

5 endpoints :

- ``GET    /api/subjects``           : liste avec filtres optionnels
  (``term_id``, ``status``, pagination)
- ``GET    /api/subjects/{subject_id}`` : détail
- ``POST   /api/subjects``           : création (404 si term_id absent,
  409 si ``(term_id, name)`` déjà pris)
- ``PUT    /api/subjects/{subject_id}`` : update partiel (champs optionnels)
- ``DELETE /api/subjects/{subject_id}`` : suppression
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from api.db import DBConnAdapter, get_db_read, get_db_write

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


# Whitelist stricte des tags acceptés (cf. brief 2026-05-10).
ALLOWED_TAGS: frozenset[str] = frozenset({
    "ambigu",
    "simpliste",
    "incomprehensible",
    "creatif",
    "parfait",
    "complique",
    "bug",
    "blacklist",
})

# Whitelist stricte des status (cf. brief 2026-05-10). En miroir de la
# CheckConstraint Postgres définie dans migration 0007 et le modèle Subject.
ALLOWED_STATUSES: frozenset[str] = frozenset({
    "draft",
    "annotated",
    "validated",
    "enriched",
    "prompted",
    "generated",
    "qc_done",
    "published",
    "rejected",
})


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_json_field(raw: Any) -> Any:
    """Décode une colonne JSON cross-dialect (TEXT côté SQLite, JSONB Postgres).

    Identique au helper de ``review.py`` : les colonnes ``sqlalchemy.JSON``
    sont exposées par les drivers comme str (SQLite/psycopg) ou comme objet
    Python (psycopg JSONB native). On normalise.
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
            logger.warning("subjects: champ JSON illisible : %r", s[:60])
            return None
    return raw


def _normalise_tags(raw: list | None) -> list[str]:
    """Normalise une liste de tags : strip, dédup, ordre conservé.

    La validation whitelist est faite en amont (Pydantic). Ce helper sert
    surtout à garder l'ordre stable et éliminer les vides/doublons.
    """
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _row_to_dict(row: tuple) -> dict[str, Any]:  # noqa: D401
    # Schéma row : id, term_id, vocabulary_id, name, source, status, note,
    #              tags, brief, subject_metadata, created_at, updated_at
    """Convertit une ligne SQL en dict réponse (NULL-safe).

    Colonnes attendues dans cet ordre :
        id, term_id, vocabulary_id, name, status, note,
        tags, brief, subject_metadata, created_at, updated_at
    """
    note_raw = row[6]
    tags = _decode_json_field(row[7]) or []
    metadata = _decode_json_field(row[9])
    return {
        "id": row[0],
        "term_id": row[1],
        "vocabulary_id": row[2],
        "name": row[3],
        "source": row[4],
        "status": row[5],
        # CLAUDE.md NULL-safe : `note` peut être NULL → None explicite.
        "note": int(note_raw) if note_raw is not None else None,
        "tags": tags if isinstance(tags, list) else [],
        "brief": row[8] or "",
        "metadata": metadata if isinstance(metadata, dict) else None,
        "created_at": row[10],
        "updated_at": row[11],
    }


SUBJECT_COLS_SELECT = (
    "id, term_id, vocabulary_id, name, source, status, note, "
    "tags, brief, subject_metadata, created_at, updated_at"
)


# ── Pydantic models ─────────────────────────────────────────────────────────


class SubjectCreate(BaseModel):
    """Payload de création.

    - ``id`` : optionnel ; si absent, généré côté serveur (UUID4).
    - ``term_id`` + ``vocabulary_id`` : requis ; FK composite vers term.
    - ``name`` : requis (non vide). Unicité ``(term_id, name)``.
    - ``status`` : défaut ``"draft"`` ; whitelist ALLOWED_STATUSES.
    - ``note`` : 0-6 ou null.
    - ``tags`` : sous-ensemble strict de ALLOWED_TAGS.
    - ``brief`` / ``metadata`` : libres.
    """

    id: str | None = None
    term_id: str
    vocabulary_id: str
    name: str
    source: str = "manual"
    status: str = "draft"
    note: int | None = None
    tags: list[str] = Field(default_factory=list)
    brief: str | None = None
    metadata: dict | None = None

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def _status_whitelisted(cls, v: str) -> str:
        if v not in ALLOWED_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALLOWED_STATUSES)}"
            )
        return v

    @field_validator("note")
    @classmethod
    def _note_range(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not (0 <= int(v) <= 6):
            raise ValueError("note must be between 0 and 6")
        return int(v)

    @field_validator("tags")
    @classmethod
    def _tags_whitelisted(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        bad = sorted({t for t in v if t not in ALLOWED_TAGS})
        if bad:
            raise ValueError(f"unknown tags: {bad}")
        return v


class SubjectUpdate(BaseModel):
    """Payload d'update partiel : tous les champs optionnels.

    Les mêmes contraintes que ``SubjectCreate`` s'appliquent quand le
    champ est présent. ``term_id`` / ``vocabulary_id`` ne peuvent pas être
    modifiés (un subject est lié structurellement à son term — créer un
    nouveau subject pour reparenter).
    """

    name: str | None = None
    status: str | None = None
    note: int | None = None
    tags: list[str] | None = None
    brief: str | None = None
    metadata: dict | None = None

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def _status_whitelisted(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALLOWED_STATUSES)}"
            )
        return v

    @field_validator("note")
    @classmethod
    def _note_range(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not (0 <= int(v) <= 6):
            raise ValueError("note must be between 0 and 6")
        return int(v)

    @field_validator("tags")
    @classmethod
    def _tags_whitelisted(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        bad = sorted({t for t in v if t not in ALLOWED_TAGS})
        if bad:
            raise ValueError(f"unknown tags: {bad}")
        return v


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("")
def list_subjects(
    term_id: str | None = Query(None),
    vocabulary_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste les subjects, filtrable par term_id / vocabulary_id / status.

    Pagination : ``limit`` (défaut 100, max 500) + ``offset``.
    Tri : ``updated_at DESC, id ASC``.
    """
    if status is not None and status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown status filter: {status!r} (allowed: {sorted(ALLOWED_STATUSES)})",
        )

    sql = f"SELECT {SUBJECT_COLS_SELECT} FROM subject"
    params: list[Any] = []
    where: list[str] = []
    if term_id:
        where.append("term_id = ?")
        params.append(term_id)
    if vocabulary_id:
        where.append("vocabulary_id = ?")
        params.append(vocabulary_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])

    rows = conn.execute(sql, params).fetchall()
    items = [_row_to_dict(tuple(r)) for r in rows]
    return JSONResponse({"count": len(items), "items": items})


@router.get("/{subject_id}")
def get_subject(
    subject_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Détail d'un subject par son id."""
    row = conn.execute(
        f"SELECT {SUBJECT_COLS_SELECT} FROM subject WHERE id = ?",
        [subject_id],
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"subject not found: {subject_id}"
        )
    return JSONResponse(_row_to_dict(tuple(row)))


@router.post("")
def create_subject(
    payload: SubjectCreate = Body(...),
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Crée un subject.

    - 404 si ``(term_id, vocabulary_id)`` n'existe pas dans ``term``.
    - 409 si ``(term_id, name)`` déjà pris (unicité).
    - 409 si ``id`` fourni déjà existant.
    """
    # Vérification d'existence du term parent (FK composite).
    term_row = conn.execute(
        "SELECT id FROM term WHERE id = ? AND vocabulary_id = ?",
        [payload.term_id, payload.vocabulary_id],
    ).fetchone()
    if term_row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"term not found: id={payload.term_id!r} "
                f"vocabulary_id={payload.vocabulary_id!r}"
            ),
        )

    # Unicité (term_id, name) — check explicite avant l'INSERT pour renvoyer
    # un 409 propre plutôt qu'une 500 sur violation contrainte.
    dup = conn.execute(
        "SELECT id FROM subject WHERE term_id = ? AND name = ?",
        [payload.term_id, payload.name],
    ).fetchone()
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"subject already exists for (term_id={payload.term_id!r}, "
                f"name={payload.name!r})"
            ),
        )

    subject_id = (payload.id or str(uuid.uuid4())).strip()
    if not subject_id:
        raise HTTPException(status_code=400, detail="id must not be empty")

    # Si un id explicite est fourni, on vérifie qu'il n'est pas déjà pris
    # (collision globale — ex. UUID régénéré côté client).
    if payload.id is not None:
        clash = conn.execute(
            "SELECT id FROM subject WHERE id = ?",
            [subject_id],
        ).fetchone()
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"subject id already exists: {subject_id}",
            )

    tags = _normalise_tags(payload.tags)
    tags_json = json.dumps(tags, ensure_ascii=False)
    metadata_json = (
        json.dumps(payload.metadata, ensure_ascii=False)
        if payload.metadata is not None
        else None
    )
    now = _now()

    conn.execute(
        """
        INSERT INTO subject (
            id, term_id, vocabulary_id, name, source, status, note,
            tags, brief, subject_metadata, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            subject_id,
            payload.term_id,
            payload.vocabulary_id,
            payload.name,
            payload.source,
            payload.status,
            payload.note,
            tags_json,
            payload.brief,
            metadata_json,
            now,
            now,
        ],
    )

    return JSONResponse(
        {
            "id": subject_id,
            "term_id": payload.term_id,
            "vocabulary_id": payload.vocabulary_id,
            "name": payload.name,
            "source": payload.source,
            "status": payload.status,
            "note": payload.note,
            "tags": tags,
            "brief": payload.brief or "",
            "metadata": payload.metadata,
            "created_at": now,
            "updated_at": now,
        },
        status_code=201,
    )


@router.put("/{subject_id}")
def update_subject(
    subject_id: str,
    payload: SubjectUpdate = Body(...),
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Update partiel : seuls les champs fournis sont modifiés.

    - 404 si subject_id absent.
    - 409 si rename collision sur ``(term_id, name)``.
    """
    existing = conn.execute(
        f"SELECT {SUBJECT_COLS_SELECT} FROM subject WHERE id = ?",
        [subject_id],
    ).fetchone()
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"subject not found: {subject_id}"
        )

    current = _row_to_dict(tuple(existing))
    new_name = payload.name if payload.name is not None else current["name"]

    # Si rename effectif → vérifier l'unicité ``(term_id, name)`` en excluant
    # la ligne courante.
    if payload.name is not None and payload.name != current["name"]:
        dup = conn.execute(
            "SELECT id FROM subject WHERE term_id = ? AND name = ? AND id <> ?",
            [current["term_id"], new_name, subject_id],
        ).fetchone()
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"subject already exists for (term_id={current['term_id']!r}, "
                    f"name={new_name!r})"
                ),
            )

    new_status = payload.status if payload.status is not None else current["status"]
    # ``note`` : on ne peut pas distinguer "absent" de "explicitement null"
    # via Pydantic v2 sans model_fields_set. On considère qu'envoyer
    # ``"note": null`` est une remise à zéro explicite ; sinon laisser tel
    # quel implique d'utiliser le sentinel "champ absent".
    note_set = "note" in payload.model_fields_set
    new_note = payload.note if note_set else current["note"]

    tags_set = "tags" in payload.model_fields_set
    new_tags = (
        _normalise_tags(payload.tags) if tags_set else (current["tags"] or [])
    )

    brief_set = "brief" in payload.model_fields_set
    new_brief = payload.brief if brief_set else current["brief"]

    metadata_set = "metadata" in payload.model_fields_set
    new_metadata = payload.metadata if metadata_set else current["metadata"]

    tags_json = json.dumps(new_tags, ensure_ascii=False)
    metadata_json = (
        json.dumps(new_metadata, ensure_ascii=False)
        if new_metadata is not None
        else None
    )
    now = _now()

    conn.execute(
        """
        UPDATE subject SET
            name = ?,
            status = ?,
            note = ?,
            tags = ?,
            brief = ?,
            subject_metadata = ?,
            updated_at = ?
        WHERE id = ?
        """,
        [
            new_name,
            new_status,
            new_note,
            tags_json,
            new_brief,
            metadata_json,
            now,
            subject_id,
        ],
    )

    return JSONResponse(
        {
            "id": subject_id,
            "term_id": current["term_id"],
            "vocabulary_id": current["vocabulary_id"],
            "name": new_name,
            "status": new_status,
            "note": new_note,
            "tags": new_tags,
            "brief": new_brief or "",
            "metadata": new_metadata,
            "created_at": current["created_at"],
            "updated_at": now,
        }
    )


@router.delete("/{subject_id}")
def delete_subject(
    subject_id: str,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Supprime un subject. 404 si absent, 200 + ``{deleted: true}`` sinon."""
    existing = conn.execute(
        "SELECT id FROM subject WHERE id = ?",
        [subject_id],
    ).fetchone()
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"subject not found: {subject_id}"
        )
    conn.execute("DELETE FROM subject WHERE id = ?", [subject_id])
    return JSONResponse({"deleted": True, "id": subject_id})
