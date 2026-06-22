"""Tests indexation — cache ``index_status`` + providers (prio 4, DIRECTION-2026-06-22).

Couvre :
  - **upsert/lecture** ``index_status`` (Postgres éphémère) : insert puis update
    idempotent sur la clé ``(engine, url)`` ;
  - **sélection provider** : mock par défaut (aucun env), réel sélectionné quand
    les env GSC/Bing sont simulées — **mais appel mocké, zéro réseau** ;
  - **sync (mock)** : peuple le cache pour un lot d'URLs, états déterministes ;
  - **kanban / work-items** : affichent le ``coverage_state`` par item + l'état
    dérivé ``indexed`` (== ``coverage_state == 'indexed'``) ;
  - **next-action** : signal « publiées non indexées » (priorité basse).

PostgreSQL uniquement (aucun SQLite). Aucun réseau : le mock est hors-ligne ;
les providers réels ne sont jamais *appelés* (on teste seulement leur sélection,
et on monkeypatche ``inspect`` pour simuler un retour sans I/O).
"""
from __future__ import annotations

from datetime import date

import pytest

from services.git_indexer import DEFAULT_REPO
from services.index_providers import (
    BingWebmasterProvider,
    GscUrlInspectionProvider,
    MockIndexProvider,
    provider_is_live,
    select_provider,
    work_item_url,
)
from services.index_sync import (
    _upsert_index_status,
    derive_index_state,
    fetch_coverage_map,
    sync_index_status,
)

REPO = DEFAULT_REPO


# ── work_item_url (dérivation URL) ──────────────────────────────────────────────

def test_work_item_url_canonical(monkeypatch):
    monkeypatch.delenv("COCKPIT_SITE_BASE", raising=False)
    assert work_item_url("fr", "baleine") == "https://alwanbooks.com/fr/colorier/baleine/"
    assert work_item_url("ar", "حوت") == "https://alwanbooks.com/ar/colorier/حوت/"


def test_work_item_url_respects_site_base(monkeypatch):
    monkeypatch.setenv("COCKPIT_SITE_BASE", "https://staging.example.com/")
    assert work_item_url("en", "whale") == "https://staging.example.com/en/colorier/whale/"


# ── derive_index_state (fonction pure) ──────────────────────────────────────────

def test_derive_index_state():
    assert derive_index_state({"coverage_state": "indexed"}) is True
    assert derive_index_state({"coverage_state": "discovered"}) is False
    assert derive_index_state({"coverage_state": "crawled_not_indexed"}) is False
    assert derive_index_state(None) is False
    assert derive_index_state({}) is False


# ── Sélection provider (mock défaut ; réel gated env, jamais appelé) ────────────

def test_select_provider_mock_by_default(monkeypatch):
    for k in ("GSC_SERVICE_ACCOUNT_JSON", "GSC_PROPERTY", "BING_WEBMASTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert isinstance(select_provider("gsc"), MockIndexProvider)
    assert isinstance(select_provider("bing"), MockIndexProvider)
    assert provider_is_live("gsc") is False
    assert provider_is_live("bing") is False


def test_select_gsc_real_when_creds_present(monkeypatch):
    monkeypatch.setenv("GSC_SERVICE_ACCOUNT_JSON", "/tmp/fake-sa.json")
    monkeypatch.setenv("GSC_PROPERTY", "https://alwanbooks.com/")
    prov = select_provider("gsc")
    assert isinstance(prov, GscUrlInspectionProvider)
    assert provider_is_live("gsc") is True


def test_select_bing_real_when_key_present(monkeypatch):
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "fake-key")
    prov = select_provider("bing")
    assert isinstance(prov, BingWebmasterProvider)
    assert provider_is_live("bing") is True


def test_real_provider_never_calls_network_in_test(monkeypatch):
    # Le réel est sélectionné, mais son ``inspect`` est monkeypatché (zéro réseau).
    monkeypatch.setenv("GSC_SERVICE_ACCOUNT_JSON", "/tmp/fake-sa.json")
    monkeypatch.setenv("GSC_PROPERTY", "https://alwanbooks.com/")
    prov = select_provider("gsc")

    def _fake_inspect(urls):
        return {u: {"coverage_state": "indexed", "last_crawl": "2026-06-22T00:00:00Z"} for u in urls}

    monkeypatch.setattr(prov, "inspect", _fake_inspect)
    out = prov.inspect(["https://alwanbooks.com/fr/colorier/baleine/"])
    assert out["https://alwanbooks.com/fr/colorier/baleine/"]["coverage_state"] == "indexed"


# ── MockIndexProvider (déterministe, hors-ligne) ────────────────────────────────

def test_mock_provider_deterministic():
    prov = MockIndexProvider(engine="gsc")
    url = "https://alwanbooks.com/fr/colorier/baleine/"
    r1 = prov.inspect([url])
    r2 = prov.inspect([url])
    assert r1 == r2  # déterministe
    assert r1[url]["coverage_state"] in (
        "indexed", "discovered", "crawled_not_indexed",
    )


def test_mock_provider_overrides():
    prov = MockIndexProvider(engine="gsc", overrides={
        "https://alwanbooks.com/fr/colorier/meduse/": "discovered",
    })
    out = prov.inspect(["https://alwanbooks.com/fr/colorier/meduse/"])
    assert out["https://alwanbooks.com/fr/colorier/meduse/"]["coverage_state"] == "discovered"


# ── upsert/lecture index_status (DB éphémère) ───────────────────────────────────

def test_upsert_index_status_insert_then_update(conn):
    url = "https://alwanbooks.com/fr/colorier/baleine/"
    assert _upsert_index_status(conn, url, "gsc", "discovered", None, "2026-06-22T00:00:00Z") == "inserted"
    conn.session.commit()

    cov = fetch_coverage_map(conn)
    assert cov[url]["coverage_state"] == "discovered"
    assert cov[url]["engines"] == {"gsc": "discovered"}

    # Update même clé (engine, url) → pas de doublon.
    assert _upsert_index_status(conn, url, "gsc", "indexed", "2026-06-21T00:00:00Z", "2026-06-22T01:00:00Z") == "updated"
    conn.session.commit()
    cov = fetch_coverage_map(conn)
    assert cov[url]["coverage_state"] == "indexed"
    assert len(cov) == 1


def test_fetch_coverage_aggregates_multi_engine(conn):
    url = "https://alwanbooks.com/fr/colorier/crabe/"
    _upsert_index_status(conn, url, "gsc", "discovered", None, "now")
    _upsert_index_status(conn, url, "bing", "indexed", "now", "now")
    conn.session.commit()
    cov = fetch_coverage_map(conn)
    # Agrégat = couverture la plus favorable (indexed via bing).
    assert cov[url]["coverage_state"] == "indexed"
    assert cov[url]["engines"] == {"gsc": "discovered", "bing": "indexed"}


# ── Helpers DB ──────────────────────────────────────────────────────────────────

def _insert_work_item(conn, wid, slug, locale="fr"):
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_state, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, locale, slug, "valide", "none", "now", "now"],
    )


def _insert_git_index(conn, slug, publish_date, locale="fr"):
    conn.execute(
        "INSERT INTO git_index (id, repo, locale, slug, exists, publish_date, "
        "content_hash, last_indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [f"gi_{slug}", REPO, locale, slug, True, publish_date, f"hash_{slug}", "now"],
    )


MARINE_SLUGS = [
    "baleine", "poisson-facile", "tortue-de-mer", "hippocampe", "crabe",
    "poisson-rouge", "pieuvre", "baleine-bleue", "meduse", "poisson-rigolo",
]


# ── sync (mock) peuple le cache pour les 10 URLs marines ────────────────────────

def test_sync_index_status_mock_populates_cache(conn, monkeypatch):
    for k in ("GSC_SERVICE_ACCOUNT_JSON", "GSC_PROPERTY", "BING_WEBMASTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for slug in MARINE_SLUGS:
        _insert_work_item(conn, f"wi_{slug}", slug)
    conn.session.commit()

    report = sync_index_status(conn, repo=REPO, engine="gsc")
    conn.session.commit()

    assert report.provider == "mock"
    assert report.requested == 10
    assert report.inserted == 10
    assert report.updated == 0
    # Tous les états sont dans le vocabulaire normalisé.
    assert set(report.by_state).issubset(
        {"indexed", "discovered", "crawled_not_indexed", "excluded", "unknown"}
    )
    # Le mock indexe la majorité (~80%).
    assert report.indexed >= 1

    cov = fetch_coverage_map(conn)
    assert len(cov) == 10
    for slug in MARINE_SLUGS:
        assert work_item_url("fr", slug) in cov


def test_sync_index_status_idempotent(conn, monkeypatch):
    monkeypatch.delenv("GSC_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GSC_PROPERTY", raising=False)
    _insert_work_item(conn, "wi_baleine", "baleine")
    conn.session.commit()

    r1 = sync_index_status(conn, repo=REPO, engine="gsc")
    conn.session.commit()
    assert r1.inserted == 1 and r1.updated == 0

    r2 = sync_index_status(conn, repo=REPO, engine="gsc")
    conn.session.commit()
    assert r2.inserted == 0 and r2.updated == 1  # même clé → update


def test_sync_index_status_explicit_provider_no_network(conn, monkeypatch):
    # Forçage d'un provider à états maîtrisés (aucun réseau) → couverture précise.
    _insert_work_item(conn, "wi_baleine", "baleine")
    _insert_work_item(conn, "wi_meduse", "meduse")
    conn.session.commit()

    forced = MockIndexProvider(engine="gsc", overrides={
        work_item_url("fr", "baleine"): "indexed",
        work_item_url("fr", "meduse"): "discovered",
    })
    report = sync_index_status(conn, repo=REPO, engine="gsc", provider=forced)
    conn.session.commit()
    assert report.by_state.get("indexed") == 1
    assert report.by_state.get("discovered") == 1


# ── kanban / work-items affichent la couverture + état dérivé ───────────────────

def test_kanban_shows_coverage_and_indexed(client, conn, monkeypatch):
    for k in ("GSC_SERVICE_ACCOUNT_JSON", "GSC_PROPERTY", "BING_WEBMASTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    _insert_work_item(conn, "wi_baleine", "baleine")
    _insert_git_index(conn, "baleine", date(2026, 6, 1))
    conn.session.commit()

    # Sync ciblé sur la baleine, forcé 'indexed' (déterministe).
    forced = MockIndexProvider(engine="gsc", overrides={
        work_item_url("fr", "baleine"): "indexed",
    })
    sync_index_status(conn, repo=REPO, engine="gsc", provider=forced)
    conn.session.commit()

    body = client.get("/api/cockpit/kanban").json()
    # Retrouve la carte baleine, vérifie coverage + indexed dérivé.
    cards = [c for col in body["columns"].values() for c in col]
    baleine = next(c for c in cards if c["slug"] == "baleine")
    assert baleine["coverage_state"] == "indexed"
    assert baleine["indexed"] is True
    assert baleine["url"] == work_item_url("fr", "baleine")
    assert body["totals"]["indexed"] == 1


def test_work_items_endpoint_exposes_coverage(client, conn):
    _insert_work_item(conn, "wi_meduse", "meduse")
    forced = MockIndexProvider(engine="gsc", overrides={
        work_item_url("fr", "meduse"): "crawled_not_indexed",
    })
    sync_index_status(conn, repo=REPO, engine="gsc", provider=forced)
    conn.session.commit()

    body = client.get("/api/cockpit/work-items").json()
    meduse = next(w for w in body if w["slug"] == "meduse")
    assert meduse["coverage_state"] == "crawled_not_indexed"
    assert meduse["indexed"] is False


def test_work_item_without_cache_is_unknown_not_indexed(client, conn):
    # Jamais synchronisé → coverage None → unknown / indexed False (pas de crash).
    _insert_work_item(conn, "wi_pieuvre", "pieuvre")
    conn.session.commit()
    body = client.get("/api/cockpit/work-items").json()
    pieuvre = next(w for w in body if w["slug"] == "pieuvre")
    assert pieuvre["coverage_state"] == "unknown"
    assert pieuvre["indexed"] is False
    assert pieuvre["coverage"] is None


# ── endpoint sync + list ────────────────────────────────────────────────────────

def test_endpoint_sync_mock(client, conn, monkeypatch):
    for k in ("GSC_SERVICE_ACCOUNT_JSON", "GSC_PROPERTY", "BING_WEBMASTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for slug in MARINE_SLUGS:
        _insert_work_item(conn, f"wi_{slug}", slug)
    conn.session.commit()

    resp = client.post("/api/cockpit/index-status/sync")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "mock"
    assert body["requested"] == 10
    assert body["inserted"] == 10

    listing = client.get("/api/cockpit/index-status").json()
    assert listing["count"] == 10
    assert listing["provider"]["gsc"] == "mock"
    assert listing["provider"]["bing"] == "mock"


def test_endpoint_sync_rejects_unknown_engine(client):
    resp = client.post("/api/cockpit/index-status/sync?engine=yandex")
    assert resp.status_code == 400


# ── next-action surface « publiées non indexées » ───────────────────────────────

def test_next_action_published_not_indexed(client, conn, monkeypatch):
    for k in ("GSC_SERVICE_ACCOUNT_JSON", "GSC_PROPERTY", "BING_WEBMASTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    # Page publiée (git, publishDate passée), buildée (pas de rebuild dû), sans drift.
    _insert_work_item(conn, "wi_meduse", "meduse")
    _insert_git_index(conn, "meduse", date(2026, 6, 1))
    conn.execute(
        "UPDATE work_item SET last_synced_hash = ? WHERE id = ?",
        ["hash_meduse", "wi_meduse"],
    )
    conn.execute(
        "INSERT INTO schedule (id, work_item_id, publish_date, last_build_at, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ["sched_m", "wi_meduse", date(2026, 6, 1), "2026-06-22T00:00:00Z", "now", "now"],
    )
    conn.session.commit()

    # Cache: publiée mais NON indexée (discovered).
    forced = MockIndexProvider(engine="gsc", overrides={
        work_item_url("fr", "meduse"): "discovered",
    })
    sync_index_status(conn, repo=REPO, engine="gsc", provider=forced)
    conn.session.commit()

    body = client.get("/api/cockpit/next-action").json()
    assert body["kind"] == "published_not_indexed", body
    assert body["priority"] == "low"
    assert body["count"] == 1
    assert body["items"][0]["slug"] == "meduse"
    assert body["action"]["endpoint"] == "/api/cockpit/index-status/sync"


def test_next_action_none_when_indexed(client, conn):
    # Publiée + buildée + indexée + pas de drift → rien à faire.
    _insert_work_item(conn, "wi_baleine", "baleine")
    _insert_git_index(conn, "baleine", date(2026, 6, 1))
    conn.execute(
        "UPDATE work_item SET last_synced_hash = ? WHERE id = ?",
        ["hash_baleine", "wi_baleine"],
    )
    conn.execute(
        "INSERT INTO schedule (id, work_item_id, publish_date, last_build_at, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ["sched_b", "wi_baleine", date(2026, 6, 1), "2026-06-22T00:00:00Z", "now", "now"],
    )
    conn.session.commit()
    forced = MockIndexProvider(engine="gsc", overrides={
        work_item_url("fr", "baleine"): "indexed",
    })
    sync_index_status(conn, repo=REPO, engine="gsc", provider=forced)
    conn.session.commit()

    body = client.get("/api/cockpit/next-action").json()
    assert body["kind"] == "none", body
