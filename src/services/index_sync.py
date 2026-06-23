"""Sync du cache d'indexation ``index_status`` — Phase 1, prio 4.

Orchestre : work_items d'un cluster/repo → URLs publiques → provider
(``src/services/index_providers.py``, mock par défaut, réel gated creds) →
**upsert** dans ``index_status`` (cache lecture, clé ``(engine, url)``).

Cap : ``index_status`` est un **cache**, jamais une vérité de contenu. La sync
ne fait que rafraîchir l'instantané (``fetched_at``). Aucun appel réseau sans
creds (la sélection retombe sur le mock).

Lecture / état dérivé ``indexe`` : ``derive_index_state`` (fonction pure) +
``fetch_coverage_map`` (charge le cache par URL). L'état dérivé n'est JAMAIS
stocké (cohérent avec git_states : git/moteur = vérité, cockpit = miroir).

PostgreSQL unique. Upsert portable (SELECT puis INSERT/UPDATE) via le
``DBConnAdapter`` (placeholders ``?``).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from api.cockpit_models import INDEX_ENGINES
from services.index_providers import (
    IndexProvider,
    category_slug_for_cluster,
    provider_is_live,
    select_provider,
    work_item_url,
)

logger = logging.getLogger(__name__)

INDEX_STATUS_COLS = [
    "id", "url", "engine", "coverage_state", "last_crawl", "fetched_at",
]
INDEX_STATUS_SELECT = ", ".join(INDEX_STATUS_COLS)

_ID_COUNTER = 0


def _new_id(prefix: str) -> str:
    global _ID_COUNTER
    _ID_COUNTER += 1
    return f"{prefix}_{int(time.time() * 1_000_000)}_{_ID_COUNTER}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def index_status_to_dict(row: Any) -> dict[str, Any]:
    return dict(zip(INDEX_STATUS_COLS, row))


# ── État dérivé ``indexe`` (fonction pure, jamais stockée) ──────────────────────

def derive_index_state(coverage: dict[str, Any] | None) -> bool:
    """L'état dérivé ``indexe`` d'une page = ``coverage_state == 'indexed'``.

    ``coverage`` est le dict de couverture (mock/réel) pour l'URL/engine
    considéré (clé ``coverage_state``), ou ``None`` si la page n'a jamais été
    inspectée (→ pas indexée connue). Fonction pure — la décision n'est jamais
    persistée (cohérent avec ``git_states``).
    """
    if not coverage:
        return False
    return coverage.get("coverage_state") == "indexed"


# ── Upsert ``index_status`` (cache lecture) ─────────────────────────────────────

def _upsert_index_status(
    conn: Any, url: str, engine: str, coverage_state: str,
    last_crawl: str | None, now: str,
) -> str:
    """Upsert idempotent sur ``(engine, url)``. Retourne 'inserted'/'updated'."""
    rows = conn.execute(
        "SELECT id FROM index_status WHERE engine = ? AND url = ?",
        [engine, url],
    ).fetchall()
    if rows:
        conn.execute(
            "UPDATE index_status SET coverage_state = ?, last_crawl = ?, "
            "fetched_at = ? WHERE id = ?",
            [coverage_state, last_crawl, now, rows[0][0]],
        )
        return "updated"
    conn.execute(
        "INSERT INTO index_status (id, url, engine, coverage_state, last_crawl, "
        "fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
        [_new_id("idx"), url, engine, coverage_state, last_crawl, now],
    )
    return "inserted"


@dataclass
class IndexSyncReport:
    """Résultat d'une sync de cache d'indexation."""

    engine: str
    provider: str            # 'mock' | 'live'
    requested: int = 0       # nb d'URLs envoyées au provider
    inserted: int = 0
    updated: int = 0
    indexed: int = 0         # nb d'URLs revenues 'indexed'
    by_state: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "provider": self.provider,
            "requested": self.requested,
            "inserted": self.inserted,
            "updated": self.updated,
            "indexed": self.indexed,
            "by_state": self.by_state,
        }


def _work_item_urls(conn: Any, repo: str | None, cluster: str | None) -> list[tuple[str, str, str]]:
    """Retourne ``[(url, locale, slug)]`` pour les work_items du périmètre.

    Périmètre = ``repo`` (clé de jointure git) et/ou ``cluster`` (via la
    jointure souple work_item.opportunity_id → opportunity.cluster, ou
    opportunity.slug == work_item.slug). Sans filtre → tous les work_items.

    L'URL produite est la **feuille SEO catégorie-nichée** (cf.
    ``work_item_url``) : le slug catégorie est résolu depuis le ``cluster`` de
    l'opportunité liée (jointure souple par opportunity_id ou par slug). Un
    work_item sans opportunité retombe sur la catégorie par défaut.
    """
    # On ramène le cluster de l'opportunité liée (LEFT JOIN souple) pour dériver
    # le slug catégorie de chaque planche. Un work_item peut n'avoir aucune
    # opportunité → cluster NULL → catégorie par défaut côté résolveur.
    sql = (
        "SELECT DISTINCT wi.locale, wi.slug, o.cluster FROM work_item wi "
        "LEFT JOIN opportunity o ON (o.id = wi.opportunity_id OR o.slug = wi.slug)"
    )
    clauses: list[str] = []
    params: list[Any] = []
    if cluster:
        clauses.append("o.cluster = ?")
        params.append(cluster)
    if repo:
        clauses.append("wi.repo = ?")
        params.append(repo)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = conn.execute(sql, params).fetchall()
    out: list[tuple[str, str, str]] = []
    for locale, slug, wi_cluster in rows:
        category_slug = category_slug_for_cluster(wi_cluster)
        out.append((work_item_url(locale, slug, category_slug), locale, slug))
    return out


def sync_index_status(
    conn: Any,
    repo: str | None = None,
    cluster: str | None = None,
    engine: str = "gsc",
    provider: IndexProvider | None = None,
    urls: list[str] | None = None,
) -> IndexSyncReport:
    """Sync le cache ``index_status`` pour un lot d'URLs (cluster/repo en cours).

    Étapes : dérive les URLs des work_items du périmètre (ou ``urls`` fourni) →
    appelle le provider (``provider`` injecté, sinon ``select_provider(engine)``
    → mock par défaut, réel gated creds) → upsert ``index_status``.

    **Aucun appel réseau sans creds** : sans creds, ``select_provider`` renvoie
    le mock (déterministe, hors-ligne). Le ``provider`` injectable permet aux
    tests de simuler le réel sans réseau.

    Args:
        conn: DBConnAdapter.
        repo / cluster: filtres de périmètre (cf. ``_work_item_urls``).
        engine: 'gsc' | 'bing'.
        provider: provider explicite (tests / forçage) ; défaut = sélection auto.
        urls: liste d'URLs explicite (court-circuite la dérivation work_items).

    Returns:
        ``IndexSyncReport``.
    """
    if engine not in INDEX_ENGINES:
        raise ValueError(f"engine inconnu : {engine!r} (attendu {INDEX_ENGINES})")

    prov = provider or select_provider(engine)
    # Étiquette provider : 'live' si un provider réel serait/est sélectionné
    # (creds présentes), 'mock' sinon. Sert à l'UI/diagnostic, pas à la logique.
    is_live = provider_is_live(engine)
    report = IndexSyncReport(engine=engine, provider="live" if is_live else "mock")

    if urls is None:
        triples = _work_item_urls(conn, repo, cluster)
        target_urls = [t[0] for t in triples]
    else:
        target_urls = list(urls)

    report.requested = len(target_urls)
    if not target_urls:
        logger.info("sync_index_status: aucune URL dans le périmètre (engine=%s)", engine)
        return report

    coverage = prov.inspect(target_urls)
    now = _now_iso()
    for url in target_urls:
        info = coverage.get(url) or {"coverage_state": "unknown", "last_crawl": None}
        state = info.get("coverage_state", "unknown")
        outcome = _upsert_index_status(
            conn, url, engine, state, info.get("last_crawl"), now,
        )
        if outcome == "inserted":
            report.inserted += 1
        else:
            report.updated += 1
        report.by_state[state] = report.by_state.get(state, 0) + 1
        if state == "indexed":
            report.indexed += 1

    logger.info(
        "sync_index_status: engine=%s provider=%s requested=%d indexed=%d (%s)",
        engine, report.provider, report.requested, report.indexed, report.by_state,
    )
    return report


# ── Lecture du cache (pour enrichir kanban / work-items) ────────────────────────

def fetch_coverage_map(
    conn: Any, engine: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Charge le cache ``index_status`` indexé par ``url`` → coverage.

    Si ``engine`` est fourni, ne retourne que ce moteur ; sinon, en cas de
    multi-moteur sur une même URL, garde la couverture la **plus favorable**
    (``indexed`` prime) pour dériver ``indexe`` (une page indexée sur l'un des
    deux moteurs est considérée indexée). Chaque entrée porte aussi ``engines``
    (dict ``engine → coverage_state``) pour un affichage détaillé.
    """
    sql = f"SELECT {INDEX_STATUS_SELECT} FROM index_status"
    params: list[Any] = []
    if engine:
        sql += " WHERE engine = ?"
        params.append(engine)
    rows = conn.execute(sql, params).fetchall()

    # Priorité de couverture (plus favorable en premier) pour l'agrégat multi-moteur.
    rank = {"indexed": 4, "crawled_not_indexed": 3, "discovered": 2, "excluded": 1, "unknown": 0}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = index_status_to_dict(r)
        url = d["url"]
        entry = out.setdefault(url, {
            "url": url, "coverage_state": "unknown", "last_crawl": None, "engines": {},
        })
        entry["engines"][d["engine"]] = d["coverage_state"]
        # Agrégat = couverture la plus favorable + dernier crawl associé.
        if rank.get(d["coverage_state"], 0) >= rank.get(entry["coverage_state"], 0):
            entry["coverage_state"] = d["coverage_state"]
            entry["last_crawl"] = d["last_crawl"]
    return out
