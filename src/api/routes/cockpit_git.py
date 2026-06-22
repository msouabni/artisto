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

from fastapi import APIRouter, Body, Depends, HTTPException

from api.cockpit_models import WORK_ITEM_STATES
from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import json_response, transaction
from services.cockpit_git_publish import CockpitPublishError, commit_work_item
from services.git_indexer import DEFAULT_REPO, reindex
from services.git_states import compute_drift, derive_git_state
from services.index_providers import provider_is_live, work_item_url
from services.index_sync import (
    derive_index_state,
    fetch_coverage_map,
    sync_index_status,
)
from services.opportunity_import import import_opportunities
from services.rebuild import (
    compute_rebuild_due,
    fetch_due_schedules,
    rebuild_due_run,
    sync_schedule_from_git,
    trigger_rebuild,
)

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


def _fetch_schedule_map(conn: DBConnAdapter) -> dict[str, dict[str, Any]]:
    """Charge ``schedule`` indexé par ``work_item_id`` (pour le badge rebuild dû)."""
    rows = conn.execute(
        "SELECT work_item_id, publish_date, last_build_at FROM schedule"
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        pub = r[1]
        out[r[0]] = {
            "publish_date": pub.isoformat() if pub is not None and hasattr(pub, "isoformat")
            else (str(pub) if pub is not None else None),
            "last_build_at": r[2],
        }
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
    sched_map: dict[str, dict[str, Any]] | None = None,
    coverage_map: dict[str, dict[str, Any]] | None = None,
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

    # Signal « rebuild dû » (site statique : page programmée échue mais pas
    # encore rebuildée). Dérivé — jamais stocké. publish_date = miroir git_index ;
    # last_build_at = dernier build déployé (schedule). Sans ligne schedule, on
    # retombe sur publish_date git (last_build_at NULL → due si échue).
    sched = (sched_map or {}).get(wi.get("id")) or {}
    last_build_at = sched.get("last_build_at")
    wi["last_build_at"] = last_build_at
    wi["rebuild_due"] = compute_rebuild_due(wi.get("publish_date"), last_build_at)

    # Couverture moteur (cache index_status, dérivé de l'URL publique). L'état
    # ``indexe`` est DÉRIVÉ (jamais stocké) : indexé == coverage_state 'indexed'.
    # Sans cache (jamais synchronisé) → coverage None → indexe False.
    url = work_item_url(wi["locale"], wi["slug"])
    coverage = (coverage_map or {}).get(url)
    wi["url"] = url
    wi["coverage"] = coverage
    wi["coverage_state"] = coverage.get("coverage_state") if coverage else "unknown"
    wi["indexed"] = derive_index_state(coverage)
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
    sched_map = _fetch_schedule_map(conn)
    coverage_map = fetch_coverage_map(conn)
    items = [
        _enrich_work_item(_work_item_to_dict(r), git_map, opp_by_id, opp_by_slug,
                          sched_map, coverage_map)
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
    sched_map = _fetch_schedule_map(conn)
    coverage_map = fetch_coverage_map(conn)
    return json_response(
        _enrich_work_item(wi, git_map, opp_by_id, opp_by_slug, sched_map, coverage_map)
    )


@router.post("/work-items/{work_item_id}/commit")
def commit_work_item_route(
    work_item_id: str,
    body: dict[str, Any] | None = Body(default=None),
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Commite un work_item prêt comme Post ``.md`` dans le clone de contenu.

    **Seule porte d'entrée dans git** : sérialise le staging → écrit
    ``src/content/posts/<locale>/<slug>.md`` → commit identité bot → met à jour
    le miroir (``last_synced_hash`` + ``git_index``). ADD-ONLY (refuse de
    réécrire un ``.md`` existant sans ``force``).

    Corps optionnel (JSON) :
      - ``launch_set`` : marqueur de lot à stamper (``frontmatter['launchSet']``) ;
      - ``dry_run`` : ne touche rien, retourne le ``.md`` qui SERAIT écrit ;
      - ``force`` : autorise la réécriture (sinon ADD-ONLY) ;
      - ``commit_message`` / ``repo`` : surcharges optionnelles.
    """
    opts = body or {}
    with transaction(conn):
        try:
            result = commit_work_item(
                conn,
                work_item_id,
                repo=opts.get("repo", DEFAULT_REPO),
                launch_set=opts.get("launch_set"),
                commit_message=opts.get("commit_message"),
                force=bool(opts.get("force", False)),
                dry_run=bool(opts.get("dry_run", False)),
            )
        except CockpitPublishError as exc:
            # Erreur métier (staging vide, collision ADD-ONLY, work_item absent) → 4xx.
            # Levée en HTTPException ici → traverse ``transaction`` sans devenir un 500.
            msg = str(exc)
            status = 404 if "introuvable" in msg else 409
            raise HTTPException(status_code=status, detail=msg) from exc
    return json_response(result.as_dict())


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
    sched_map = _fetch_schedule_map(conn)
    coverage_map = fetch_coverage_map(conn)
    items = [
        _enrich_work_item(_work_item_to_dict(r), git_map, opp_by_id, opp_by_slug,
                          sched_map, coverage_map)
        for r in rows
    ]

    # Groupe par état d'orchestration ; colonnes toujours présentes (rendu stable).
    columns: dict[str, list[dict[str, Any]]] = {st: [] for st in WORK_ITEM_STATES}
    drift_count = 0
    rebuild_due_count = 0
    indexed_count = 0
    published_not_indexed = 0
    for it in items:
        st = it.get("state") or "candidat"
        columns.setdefault(st, []).append(it)
        if it.get("drift"):
            drift_count += 1
        if it.get("rebuild_due"):
            rebuild_due_count += 1
        if it.get("indexed"):
            indexed_count += 1
        # Signal SEO : page publiée (git) mais pas indexée (moteur).
        if it.get("derived_state") == "publie" and not it.get("indexed"):
            published_not_indexed += 1

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
            "rebuild_due": rebuild_due_count,
            "indexed": indexed_count,
            "published_not_indexed": published_not_indexed,
            "by_state": {st: len(columns.get(st, [])) for st in WORK_ITEM_STATES},
        },
        "first_drift": first_drift,
    }
    return json_response(payload)


# ── Rebuild (prio 3 — décision 4 DIRECTION-2026-06-22) ──────────────────────────

@router.post("/rebuild")
def rebuild_now_route(
    repo: str = DEFAULT_REPO, conn: DBConnAdapter = Depends(get_db_write)
):
    """Rebuild **à la demande** (publication immédiate) — bouton cockpit.

    Aligne d'abord ``schedule`` sur ``git_index`` (miroir publishDate), déclenche
    **un** build+deploy (configurable : ``REBUILD_HOOK_URL`` / ``REBUILD_CMD``,
    sinon **mock** no-op loggué), puis pose ``last_build_at`` sur toutes les
    pages du repo (un build couvre tout le site statique).

    Renvoie l'état du déclenchement (``triggered`` / ``mode`` hook|cmd|mock /
    ``built_at``). **Aucun deploy réel** tant qu'aucune variable d'env n'est
    configurée (le câblage Cloudflare effectif = track Hamma).
    """
    with transaction(conn):
        sync_schedule_from_git(conn, repo)
        result = trigger_rebuild()
        updated = 0
        if result.triggered and result.built_at:
            # Build à la demande : couvre tout le site → stampe toutes les pages
            # du repo (pas seulement les dues) pour refléter qu'elles sont à jour.
            sched_ids = conn.execute(
                "SELECT s.id FROM schedule s JOIN work_item wi ON wi.id = s.work_item_id "
                "WHERE wi.repo = ?", [repo],
            ).fetchall()
            from services.rebuild import _now_iso  # local : helper interne

            ts = _now_iso()
            for (sid,) in sched_ids:
                conn.execute(
                    "UPDATE schedule SET last_build_at = ?, updated_at = ? WHERE id = ?",
                    [result.built_at, ts, sid],
                )
                updated += 1
    payload = result.as_dict()
    payload["updated_schedules"] = updated
    return json_response(payload)


@router.post("/rebuild/run-due")
def rebuild_run_due_route(
    repo: str = DEFAULT_REPO, conn: DBConnAdapter = Depends(get_db_write)
):
    """Passage **cron horaire** : ne rebuild que si des pages programmées sont dues.

    Aligne ``schedule`` sur git, trouve les pages ``rebuild_due`` (programmées
    échues, pas encore rebuildées), déclenche **un** build (mock par défaut) et
    pose ``last_build_at``. No-op si rien n'est dû (pas de build inutile).

    Pensé pour 3 déclencheurs possibles (cf. PLAN-PHASE1) : Cloudflare Cron
    Trigger, cron CI, ou le cockpit lui-même. Aucun cron système n'est installé
    ici — c'est une fonction appelable + cet endpoint.
    """
    with transaction(conn):
        sync_schedule_from_git(conn, repo)
        report = rebuild_due_run(conn)
    return json_response(report.as_dict())


@router.get("/rebuild/due")
def rebuild_due_route(conn: DBConnAdapter = Depends(get_db_read)):
    """Liste les pages actuellement **dues au rebuild** (dérivé, pas stocké)."""
    due = fetch_due_schedules(conn)
    return json_response({"count": len(due), "items": due})


# ── Indexation (prio 4 — cache index_status, provider mock/réel gated creds) ────

@router.post("/index-status/sync")
def index_status_sync_route(
    repo: str = DEFAULT_REPO,
    cluster: str | None = None,
    engine: str = "gsc",
    conn: DBConnAdapter = Depends(get_db_write),
):
    """Sync le **cache** ``index_status`` (couverture moteur) sur un lot d'URLs.

    Dérive les URLs publiques des work_items du périmètre (``repo`` / ``cluster``)
    → provider (``MockIndexProvider`` par défaut ; **GSC/Bing réels gatés sur
    creds** — *track Hamma*) → upsert ``index_status``. C'est un **cache**, jamais
    une vérité de contenu.

    **Aucun appel réseau sans creds** : sans ``GSC_*`` / ``BING_WEBMASTER_API_KEY``,
    le mock déterministe alimente le cache. ``provider`` dans la réponse vaut
    ``mock`` tant que les creds ne sont pas branchées, ``live`` ensuite.
    """
    if engine not in ("gsc", "bing"):
        raise HTTPException(status_code=400, detail=f"engine inconnu : {engine!r}")
    with transaction(conn):
        report = sync_index_status(conn, repo=repo, cluster=cluster, engine=engine)
    return json_response(report.as_dict())


@router.get("/index-status")
def index_status_list(
    engine: str | None = None, conn: DBConnAdapter = Depends(get_db_read)
):
    """Liste le cache d'indexation par URL (agrégat multi-moteur + détail engines)."""
    cov = fetch_coverage_map(conn, engine)
    return json_response({
        "count": len(cov),
        "provider": {
            "gsc": "live" if provider_is_live("gsc") else "mock",
            "bing": "live" if provider_is_live("bing") else "mock",
        },
        "items": list(cov.values()),
    })


# ── Next-action (« Reprends ici ») ──────────────────────────────────────────────

@router.get("/next-action")
def next_action(
    repo: str | None = None, conn: DBConnAdapter = Depends(get_db_read)
):
    """Signal « Reprends ici » : LA prochaine action prioritaire du cockpit.

    Priorité (haute → basse) :
      1. **rebuild dû** — N page(s) programmée(s) échue(s) en attente de build.
         Action = lancer le rebuild (``POST /api/cockpit/rebuild/run-due``).
         C'est l'urgence : du contenu prêt mais invisible (site statique).
      2. **drift** — une page éditée hors cockpit / absente de git. Action =
         resynchroniser / réindexer.
      3. rien — tout est à jour.
    """
    sql = f"SELECT {WORK_ITEM_SELECT} FROM work_item"
    params: list[Any] = []
    if repo:
        sql += " WHERE repo = ?"
        params.append(repo)
    rows = conn.execute(sql, params).fetchall()

    git_map = _fetch_git_index_map(conn, repo)
    opp_by_id, opp_by_slug = _fetch_opportunity_maps(conn)
    sched_map = _fetch_schedule_map(conn)
    coverage_map = fetch_coverage_map(conn)
    items = [
        _enrich_work_item(_work_item_to_dict(r), git_map, opp_by_id, opp_by_slug,
                          sched_map, coverage_map)
        for r in rows
    ]

    due = [it for it in items if it.get("rebuild_due")]
    if due:
        n = len(due)
        payload = {
            "kind": "rebuild_due",
            "priority": "high",
            "count": n,
            "message": (
                f"{n} page(s) programmée(s) en attente de rebuild — "
                "lancez le rebuild pour les publier."
            ),
            "action": {
                "label": "Lancer le rebuild",
                "method": "POST",
                "endpoint": "/api/cockpit/rebuild/run-due",
            },
            "items": [
                {"work_item_id": it["id"], "slug": it["slug"], "locale": it["locale"],
                 "publish_date": it.get("publish_date"), "last_build_at": it.get("last_build_at")}
                for it in due
            ],
        }
        return json_response(payload)

    drift = next((it for it in items if it.get("drift")), None)
    if drift:
        payload = {
            "kind": "drift",
            "priority": "medium",
            "count": sum(1 for it in items if it.get("drift")),
            "message": (
                f"Drift détecté sur « {drift['slug']} » ({drift.get('drift_reason')}) — "
                "page éditée hors cockpit ou absente de git."
            ),
            "action": {
                "label": "Resynchroniser",
                "method": "POST",
                "endpoint": "/api/cockpit/reindex",
            },
            "items": [drift],
        }
        return json_response(payload)

    # Signal SEO (priorité basse) : pages publiées (git) mais pas indexées
    # (moteur). N'a de sens qu'une fois les creds branchées (track Hamma) — en
    # mode mock le cache reste plausible mais non autoritaire. Surfacé seulement
    # si au moins une page concernée a effectivement un cache (sync passée).
    not_indexed = [
        it for it in items
        if it.get("derived_state") == "publie"
        and not it.get("indexed")
        and it.get("coverage") is not None
    ]
    if not_indexed:
        n = len(not_indexed)
        payload = {
            "kind": "published_not_indexed",
            "priority": "low",
            "count": n,
            "message": (
                f"{n} page(s) publiée(s) mais pas (encore) indexée(s) côté moteur "
                "— surveillez la couverture (creds GSC/Bing requis pour fiabilité)."
            ),
            "action": {
                "label": "Resynchroniser l'indexation",
                "method": "POST",
                "endpoint": "/api/cockpit/index-status/sync",
            },
            "items": [
                {"work_item_id": it["id"], "slug": it["slug"], "locale": it["locale"],
                 "url": it.get("url"), "coverage_state": it.get("coverage_state")}
                for it in not_indexed
            ],
        }
        return json_response(payload)

    return json_response({
        "kind": "none",
        "priority": "none",
        "count": 0,
        "message": "Tout est à jour — aucune action prioritaire.",
        "action": None,
        "items": [],
    })
