"""Routes API pour la gestion des sites de publication."""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import json_response, to_i18n, get_i18n, transaction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sites", tags=["sites"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class SitePayload(BaseModel):
    id: str | None = None
    name_fr: str = ""
    name_en: str = ""
    name_ar: str = ""
    base_url: str = ""
    default_locale: str = "fr"
    country: str = ""
    audience: str = ""
    taxonomy_config_path: str = ""
    active: int = 1


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_dict(row: tuple, cols: list[str]) -> dict[str, Any]:
    d = dict(zip(cols, row))
    name_i18n = d.pop("name_i18n", None)
    d["name_fr"] = get_i18n(name_i18n, "fr")
    d["name_en"] = get_i18n(name_i18n, "en")
    d["name_ar"] = get_i18n(name_i18n, "ar")
    d["active"] = int(d.get("active") or 0)
    return d


def _get_site_row(conn: DBConnAdapter, site_id: str) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT id, name_i18n, base_url, default_locale, country, audience,
                  taxonomy_config_path, active, created_at, updated_at
           FROM site WHERE id = ?""",
        [site_id],
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' non trouvé")
    cols = ["id", "name_i18n", "base_url", "default_locale", "country", "audience",
            "taxonomy_config_path", "active", "created_at", "updated_at"]
    return _row_to_dict(list(rows[0]), cols)


SITE_COLS = ["id", "name_i18n", "base_url", "default_locale", "country", "audience",
             "taxonomy_config_path", "active", "created_at", "updated_at"]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("")
def list_sites(
    active_only: bool = False,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste tous les sites. Optionnel : filtrer par active=true."""
    sql = "SELECT id, name_i18n, base_url, default_locale, country, audience, taxonomy_config_path, active, created_at, updated_at FROM site"
    params: list = []
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY id"
    rows = conn.execute(sql, params).fetchall()
    items = [_row_to_dict(list(r), SITE_COLS) for r in rows]
    return json_response(items)


@router.get("/{site_id}")
def get_site(
    site_id: str,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Détail d'un site."""
    return json_response(_get_site_row(conn, site_id))


@router.post("")
def create_site(
    payload: SitePayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Crée un nouveau site."""
    site_id = (payload.id or "").strip()
    if not site_id:
        site_id = "site_" + str(int(time.time() * 1000))

    existing = conn.execute("SELECT 1 FROM site WHERE id = ?", [site_id]).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"Site '{site_id}' existe déjà")

    name_i18n = to_i18n(fr=payload.name_fr, en=payload.name_en, ar=payload.name_ar)
    now = _now()

    with transaction(conn):
        conn.execute(
            """INSERT INTO site (id, name_i18n, base_url, default_locale, country, audience,
                                 taxonomy_config_path, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [site_id, name_i18n, payload.base_url, payload.default_locale,
             payload.country, payload.audience, payload.taxonomy_config_path,
             payload.active, now, now],
        )

    return json_response({"status": "created", "id": site_id})


@router.put("/{site_id}")
def update_site(
    site_id: str,
    payload: SitePayload,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Met à jour un site existant. Crée-le si absent (upsert)."""
    name_i18n = to_i18n(fr=payload.name_fr, en=payload.name_en, ar=payload.name_ar)
    now = _now()

    existing = conn.execute("SELECT 1 FROM site WHERE id = ?", [site_id]).fetchone()

    with transaction(conn):
        if existing:
            conn.execute(
                """UPDATE site SET name_i18n=?, base_url=?, default_locale=?, country=?,
                                   audience=?, taxonomy_config_path=?, active=?, updated_at=?
                   WHERE id=?""",
                [name_i18n, payload.base_url, payload.default_locale, payload.country,
                 payload.audience, payload.taxonomy_config_path, payload.active, now, site_id],
            )
        else:
            conn.execute(
                """INSERT INTO site (id, name_i18n, base_url, default_locale, country, audience,
                                     taxonomy_config_path, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [site_id, name_i18n, payload.base_url, payload.default_locale,
                 payload.country, payload.audience, payload.taxonomy_config_path,
                 payload.active, now, now],
            )

    return json_response({"status": "ok", "id": site_id})


@router.delete("/{site_id}")
def delete_site(
    site_id: str,
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Supprime un site. 409 si le site a des publications ou des exports associés."""
    existing = conn.execute("SELECT 1 FROM site WHERE id = ?", [site_id]).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' non trouvé")

    # Vérifier les références
    refs: dict[str, int] = {}
    row = conn.execute("SELECT COUNT(*) FROM site_publication WHERE site_id = ?", [site_id]).fetchone()
    refs["publications"] = row[0] if row else 0
    row = conn.execute("SELECT COUNT(*) FROM export WHERE site_id = ?", [site_id]).fetchone()
    refs["exports"] = row[0] if row else 0

    if any(v > 0 for v in refs.values()):
        raise HTTPException(
            status_code=409,
            detail={"message": "Site encore référencé", "references": refs},
        )

    conn.execute("DELETE FROM site WHERE id = ?", [site_id])
    return json_response({"status": "deleted", "id": site_id})


# ─── Import diff ────────────────────────────────────────────────────────────────

_SITE_DIFF_FIELDS = [
    "name_fr", "name_en", "name_ar",
    "base_url", "default_locale", "country", "audience",
    "taxonomy_config_path", "active",
]

_SITE_VALID_OPS = {"add", "upsert", "update", "remove"}


def _site_normalize_diff_op(raw_op: dict) -> dict:
    op = raw_op.get("op", "")
    value = raw_op.get("value") or {}
    if op == "replace":
        op = "upsert"
    return {"op": op, "value": value}


def _site_to_flat(r: dict) -> dict:
    """Convertit une ligne DB en dict plat pour la comparaison."""
    return {
        "id": r.get("id", ""),
        "name_fr": get_i18n(r.get("name_i18n"), "fr"),
        "name_en": get_i18n(r.get("name_i18n"), "en"),
        "name_ar": get_i18n(r.get("name_i18n"), "ar"),
        "base_url": r.get("base_url") or "",
        "default_locale": r.get("default_locale") or "",
        "country": r.get("country") or "",
        "audience": r.get("audience") or "",
        "taxonomy_config_path": r.get("taxonomy_config_path") or "",
        "active": int(r.get("active") or 0),
    }


def _site_compute_diff(current: dict, incoming: dict) -> dict:
    """N'inclut que les champs explicitement fournis dans incoming."""
    diff: dict[str, dict] = {}
    for field in _SITE_DIFF_FIELDS:
        if field not in incoming:
            continue
        cur_val = current.get(field)
        inc_val = incoming.get(field)
        if field == "active":
            cur_val = int(cur_val) if cur_val is not None else 0
            inc_val = int(inc_val) if inc_val is not None else 0
        else:
            cur_val = (cur_val or "").strip()
            inc_val = (inc_val or "").strip()
        if cur_val != inc_val:
            diff[field] = {"from": cur_val, "to": inc_val}
    return diff


def _validate_site_diff_operations(
    operations: list[dict],
    existing_ids: set[str],
) -> list[dict]:
    batch_added_ids: set[str] = set()
    results: list[dict] = []

    for i, raw_op in enumerate(operations):
        normalized = _site_normalize_diff_op(raw_op)
        op = normalized["op"]
        value = normalized["value"]

        site_id = str(value.get("id") or "").strip()
        if not site_id:
            site_id = "site_" + str(int(time.time() * 1000) + i)

        result: dict[str, Any] = {
            "index": i,
            "op": op,
            "site_id": site_id,
            "status": "ready",
            "message": None,
            "incoming": {**value, "id": site_id},
            "current": None,
            "diff": None,
        }

        if op not in _SITE_VALID_OPS:
            result["status"] = "error"
            result["message"] = f"Opération inconnue : '{op}'"
            results.append(result)
            continue

        exists = site_id in existing_ids

        if op == "add":
            if exists:
                result["status"] = "conflict"
                result["message"] = f"Site '{site_id}' existe déjà (utilisez 'upsert')"
            else:
                result["status"] = "ready"
                batch_added_ids.add(site_id)

        elif op == "upsert":
            result["status"] = "update" if exists else "ready"
            if not exists:
                batch_added_ids.add(site_id)

        elif op == "update":
            if not exists:
                result["status"] = "error"
                result["message"] = f"Site '{site_id}' n'existe pas"
            else:
                result["status"] = "update"

        elif op == "remove":
            result["status"] = "skip" if not exists else "ready"
            if not exists:
                result["message"] = f"Site '{site_id}' introuvable"

        results.append(result)

    return results


@router.post("/import/diff")
def import_diff(
    operations: list = Body(...),
    dry_run: bool = True,
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """
    Import de diffs JSON pour les sites.
    dry_run=true : preview sans appliquer.
    dry_run=false : applique les opérations.
    Format : [{ "op": "add"|"upsert"|"remove", "value": {...} }]
    """
    rows = conn.execute(
        "SELECT id, name_i18n, base_url, default_locale, country, audience, "
        "taxonomy_config_path, active FROM site"
    ).fetchall()
    cols = ["id", "name_i18n", "base_url", "default_locale", "country", "audience",
            "taxonomy_config_path", "active"]
    existing_map: dict[str, dict] = {}
    for r in rows:
        d = _row_to_dict(list(r), cols)
        existing_map[d["id"]] = d
    existing_ids = set(existing_map.keys())

    validated = _validate_site_diff_operations(operations, existing_ids)

    for op_result in validated:
        if op_result["status"] == "update":
            current = existing_map.get(op_result["site_id"])
            if current:
                current_flat = _site_to_flat(current)
                op_result["current"] = current_flat
                op_result["diff"] = _site_compute_diff(current_flat, op_result["incoming"])
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
            site_id = op_result["site_id"]
            status = op_result["status"]
            value = op_result["incoming"]

            if status in ("skip", "conflict", "error"):
                continue

            if op in ("add", "upsert") and status in ("ready", "update"):
                # Pour upsert sur site existant : fusionner avec l'existant (ne pas écraser les champs absents)
                existing_row = existing_map.get(site_id)
                if existing_row and op == "upsert":
                    merged = dict(existing_row)
                    for field in _SITE_DIFF_FIELDS:
                        if field in value:
                            merged[field] = value[field]
                    value = merged

                name_i18n = to_i18n(
                    fr=value.get("name_fr", ""),
                    en=value.get("name_en", ""),
                    ar=value.get("name_ar", ""),
                )
                active = int(value.get("active", 1))
                existing = conn.execute("SELECT 1 FROM site WHERE id = ?", [site_id]).fetchone()

                if existing and op == "upsert":
                    conn.execute(
                        """UPDATE site SET name_i18n=?, base_url=?, default_locale=?,
                           country=?, audience=?, taxonomy_config_path=?, active=?, updated_at=?
                           WHERE id=?""",
                        [
                            name_i18n, value.get("base_url", ""),
                            value.get("default_locale", "fr"),
                            value.get("country", ""), value.get("audience", ""),
                            value.get("taxonomy_config_path", ""), active, now, site_id,
                        ],
                    )
                else:
                    conn.execute(
                        """INSERT INTO site (id, name_i18n, base_url, default_locale, country,
                           audience, taxonomy_config_path, active, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [
                            site_id, name_i18n, value.get("base_url", ""),
                            value.get("default_locale", "fr"),
                            value.get("country", ""), value.get("audience", ""),
                            value.get("taxonomy_config_path", ""), active, now, now,
                        ],
                    )
                applied.append(site_id)

            elif op == "remove" and status == "ready":
                conn.execute("DELETE FROM site WHERE id = ?", [site_id])
                applied.append(site_id)

    return json_response({
        "applied_count": len(applied),
        "applied_ids": applied,
    })


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
