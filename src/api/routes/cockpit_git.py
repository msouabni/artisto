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

from api.cockpit_models import WORK_ITEM_STATES
from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import json_response, transaction
from services.git_indexer import DEFAULT_REPO, reindex
from services.git_states import compute_drift, derive_git_state
from services.opportunity_import import import_opportunities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cockpit", tags=["cockpit-git"])

WORK_ITEM_COLS = [
    "id", "repo", "locale", "slug", "state", "opportunity_id",
    "last_synced_hash", "staging_state", "created_at", "updated_at",
]
WORK_ITEM_SELECT = ", ".join(WORK_ITEM_COLS)

OPPORTUNITY_COLS = [
    "id", "keyword", "sujet", "slug", "volume", "kd", "score",
    "cluster", "source", "imported_at",
]
OPPORTUNITY_SELECT = ", ".join(OPPORTUNITY_COLS)

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


def _opportunity_to_dict(row: Any) -> dict[str, Any]:
    d = dict(zip(OPPORTUNITY_COLS, row))
    # NULL-safe + types natifs JSON (clients trient/comparent sur ces champs).
    d["volume"] = int(d["volume"]) if d.get("volume") is not None else None
    d["kd"] = int(d["kd"]) if d.get("kd") is not None else None
    d["score"] = float(d["score"]) if d.get("score") is not None else None
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


def _fetch_opportunity_maps(
    conn: DBConnAdapter,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Charge ``opportunity`` indexé par ``id`` ET par ``slug``.

    Le score de demande est rattaché à un work_item par ``opportunity_id`` quand
    le lien a été posé à l'import ; on retombe sinon sur le ``slug`` (le lien est
    une commodité, l'affichage du score ne doit PAS dépendre de l'ordre import/
    création des work_items). Si plusieurs opportunités partagent un slug, on
    garde la mieux scorée.
    """
    rows = conn.execute(f"SELECT {OPPORTUNITY_SELECT} FROM opportunity").fetchall()
    by_id: dict[str, dict[str, Any]] = {}
    by_slug: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = _opportunity_to_dict(r)
        by_id[d["id"]] = d
        prev = by_slug.get(d["slug"])
        if prev is None or (d.get("score") or 0) > (prev.get("score") or 0):
            by_slug[d["slug"]] = d
    return by_id, by_slug


def _enrich_work_item(
    wi: dict[str, Any],
    git_map: dict[tuple, dict[str, Any]],
    opp_by_id: dict[str, dict[str, Any]] | None = None,
    opp_by_slug: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Joint un work_item à git_index + opportunité ; calcule état dérivé + drift.

    Tout est DÉRIVÉ de git_index (lecture) : le cockpit est un miroir, jamais
    une seconde vérité.
    """
    key = (wi["repo"], wi["locale"], wi["slug"])
    git_row = git_map.get(key)

    # Drift en 2 cas (cf. services/git_states.compute_drift) :
    #   (a) page absente de git ; (b) content_hash git ≠ last_synced_hash.
    drift, drift_reason = compute_drift(git_row, wi.get("last_synced_hash"))

    wi["git_index"] = git_row
    wi["derived_state"] = derive_git_state(git_row)
    wi["drift"] = drift
    wi["drift_reason"] = drift_reason
    wi["publish_date"] = git_row.get("publish_date") if git_row else None
    wi["content_hash"] = git_row.get("content_hash") if git_row else None

    # Score de demande : lien posé (opportunity_id) ou fallback slug.
    opp = None
    oid = wi.get("opportunity_id")
    if oid and opp_by_id:
        opp = opp_by_id.get(oid)
    if opp is None and opp_by_slug:
        opp = opp_by_slug.get(wi.get("slug"))
    wi["opportunity"] = opp
    wi["score"] = opp.get("score") if opp else None
    wi["volume"] = opp.get("volume") if opp else None
    return wi


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/reindex")
def reindex_route(repo: str = DEFAULT_REPO, conn: DBConnAdapter = Depends(get_db_write)):
    """Relance l'indexeur git sur ``CONTENT_REPO_PATH``. Autorité = git."""
    with transaction(conn):
        report = reindex(conn, repo=repo)
    return json_response(report.as_dict())


@router.post("/opportunities/import")
def import_opportunities_route(
    repo: str = DEFAULT_REPO, conn: DBConnAdapter = Depends(get_db_write)
):
    """Importe le CSV d'opportunités (score de demande) + relie les work_items.

    Source : ``data/clusters/cluster-marin-sujets.csv`` (proxy score = volume
    normalisé, faute de colonne score brute). Idempotent.
    """
    with transaction(conn):
        report = import_opportunities(conn, repo=repo)
    return json_response(report.as_dict())


@router.get("/opportunities")
def list_opportunities(conn: DBConnAdapter = Depends(get_db_read)):
    """Liste les opportunités importées (score de demande), triées par score."""
    rows = conn.execute(
        f"SELECT {OPPORTUNITY_SELECT} FROM opportunity ORDER BY score DESC NULLS LAST"
    ).fetchall()
    return json_response([_opportunity_to_dict(r) for r in rows])


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
    opp_by_id, opp_by_slug = _fetch_opportunity_maps(conn)
    items = [
        _enrich_work_item(_work_item_to_dict(r), git_map, opp_by_id, opp_by_slug)
        for r in rows
    ]
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
    opp_by_id, opp_by_slug = _fetch_opportunity_maps(conn)
    return json_response(_enrich_work_item(wi, git_map, opp_by_id, opp_by_slug))


@router.get("/kanban")
def kanban(
    repo: str | None = None,
    locale: str | None = None,
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Vue kanban : work_items groupés par **état d'orchestration**.

    Le cockpit est un MIROIR de git. Chaque carte porte des données **dérivées
    de git_index** (lecture) + le score de demande (opportunité reliée) :
      - ``derived_state`` (ecrit/programme/publie/absent) — badges git ;
      - ``drift`` (bool) + ``drift_reason`` — alarme (jamais correctif) ;
      - ``score`` / ``volume`` — score de demande ;
      - ``slug`` / ``locale`` / plaque (``plate_id`` si réf opportunité).

    Colonnes = ``WORK_ITEM_STATES`` (candidat|valide|construction|mesure|verdict),
    toujours présentes (même vides) pour un rendu stable.
    """
    sql = f"SELECT {WORK_ITEM_SELECT} FROM work_item"
    clauses: list[str] = []
    params: list[Any] = []
    if repo:
        clauses.append("repo = ?")
        params.append(repo)
    if locale:
        clauses.append("locale = ?")
        params.append(locale)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY repo, locale, slug"
    rows = conn.execute(sql, params).fetchall()

    git_map = _fetch_git_index_map(conn, repo)
    opp_by_id, opp_by_slug = _fetch_opportunity_maps(conn)
    items = [
        _enrich_work_item(_work_item_to_dict(r), git_map, opp_by_id, opp_by_slug)
        for r in rows
    ]

    # Groupe par état d'orchestration ; colonnes toujours présentes (rendu stable).
    columns: dict[str, list[dict[str, Any]]] = {st: [] for st in WORK_ITEM_STATES}
    drift_count = 0
    for it in items:
        st = it.get("state") or "candidat"
        columns.setdefault(st, []).append(it)
        if it.get("drift"):
            drift_count += 1

    # Tri intra-colonne : score de demande décroissant (NULL en dernier).
    for col in columns.values():
        col.sort(key=lambda x: (x.get("score") is None, -(x.get("score") or 0.0)))

    # Premier drift (pour un panneau « Reprends ici » côté UI).
    first_drift = next((it for it in items if it.get("drift")), None)

    payload = {
        "states": list(WORK_ITEM_STATES),
        "columns": columns,
        "totals": {
            "work_items": len(items),
            "drift": drift_count,
            "by_state": {st: len(columns.get(st, [])) for st in WORK_ITEM_STATES},
        },
        "first_drift": first_drift,
    }
    return json_response(payload)
