"""Routes du cockpit git-autoritaire — Phase 1, incrément 1.

Cap : git = vérité du contenu. Ces endpoints ne servent JAMAIS de contenu
autoritaire. Ils exposent :
  - ``POST /api/cockpit/reindex`` : relance l'indexeur git sur ``CONTENT_REPO_PATH``
    (reflète le dépôt dans ``git_index``).
  - ``GET  /api/cockpit/work-items`` : liste les ``work_item`` joints à
    ``git_index`` par ``(repo, locale, slug)``, avec l'**état dérivé de git**.
  - ``GET  /api/cockpit/work-items/{id}`` : détail d'un work_item.

Conventions projet : ``get_db_read`` / ``get_db_write``, placeholders ``?`` via
``DBConnAdapter``, NULL-safe + types natifs JSON au retour.

Namespace ``/api/cockpit/...`` distinct du router legacy (``cockpit.py`` :
``/api/pages`` etc.) qui relève du knowledge L1-L4 (aucune migration).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import json_response, transaction
from services.git_indexer import DEFAULT_REPO, reindex
from services.git_states import derive_git_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cockpit", tags=["cockpit-git"])

WORK_ITEM_COLS = [
    "id", "repo", "locale", "slug", "state", "opportunity_id",
    "staging_state", "created_at", "updated_at",
]
WORK_ITEM_SELECT = ", ".join(WORK_ITEM_COLS)

GIT_INDEX_COLS = [
    "id", "repo", "locale", "slug", "exists", "publish_date",
    "frontmatter_digest", "content_hash", "rel_path", "last_indexed_at",
]
GIT_INDEX_SELECT = ", ".join(GIT_INDEX_COLS)


def _work_item_to_dict(row: Any) -> dict[str, Any]:
    return dict(zip(WORK_ITEM_COLS, row))


def _git_index_to_dict(row: Any) -> dict[str, Any]:
    d = dict(zip(GIT_INDEX_COLS, row))
    d["exists"] = bool(d.get("exists"))
    pub = d.get("publish_date")
    # publish_date : Date natif → ISO string (JSON-safe, stable client).
    d["publish_date"] = pub.isoformat() if pub is not None and hasattr(pub, "isoformat") else (
        str(pub) if pub is not None else None
    )
    return d


def _fetch_git_index_map(conn: DBConnAdapter, repo: str | None = None) -> dict[tuple, dict[str, Any]]:
    """Charge ``git_index`` indexé par ``(repo, locale, slug)``."""
    sql = f"SELECT {GIT_INDEX_SELECT} FROM git_index"
    params: list[Any] = []
    if repo:
        sql += " WHERE repo = ?"
        params.append(repo)
    rows = conn.execute(sql, params).fetchall()
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        d = _git_index_to_dict(r)
        out[(d["repo"], d["locale"], d["slug"])] = d
    return out


def _enrich_work_item(wi: dict[str, Any], git_map: dict[tuple, dict[str, Any]]) -> dict[str, Any]:
    """Joint un work_item à git_index et calcule l'état dérivé + le drift."""
    key = (wi["repo"], wi["locale"], wi["slug"])
    git_row = git_map.get(key)
    wi["git_index"] = git_row
    wi["derived_state"] = derive_git_state(git_row)
    # Drift : un work_item qui pointe une page absente de git (jamais indexée,
    # ou marquée absente). Visible, jamais une seconde vérité.
    wi["drift"] = git_row is None or not git_row.get("exists", False)
    wi["publish_date"] = git_row.get("publish_date") if git_row else None
    wi["content_hash"] = git_row.get("content_hash") if git_row else None
    return wi


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/reindex")
def reindex_route(repo: str = DEFAULT_REPO, conn: DBConnAdapter = Depends(get_db_write)):
    """Relance l'indexeur git sur ``CONTENT_REPO_PATH``. Autorité = git."""
    with transaction(conn):
        report = reindex(conn, repo=repo)
    return json_response(report.as_dict())


@router.get("/work-items")
def list_work_items(
    repo: str | None = None,
    locale: str | None = None,
    state: str | None = None,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste les work_items avec leur état **dérivé de git** (jointure git_index)."""
    sql = f"SELECT {WORK_ITEM_SELECT} FROM work_item"
    clauses: list[str] = []
    params: list[Any] = []
    if repo:
        clauses.append("repo = ?")
        params.append(repo)
    if locale:
        clauses.append("locale = ?")
        params.append(locale)
    if state:
        clauses.append("state = ?")
        params.append(state)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY repo, locale, slug"
    rows = conn.execute(sql, params).fetchall()

    git_map = _fetch_git_index_map(conn, repo)
    items = [_enrich_work_item(_work_item_to_dict(r), git_map) for r in rows]
    return json_response(items)


@router.get("/work-items/{work_item_id}")
def get_work_item(work_item_id: str, conn: DBConnAdapter = Depends(get_db_read)):
    """Détail d'un work_item + état dérivé de git + drift."""
    rows = conn.execute(
        f"SELECT {WORK_ITEM_SELECT} FROM work_item WHERE id = ?", [work_item_id],
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"work_item '{work_item_id}' introuvable")
    wi = _work_item_to_dict(rows[0])
    git_map = _fetch_git_index_map(conn, wi["repo"])
    return json_response(_enrich_work_item(wi, git_map))
