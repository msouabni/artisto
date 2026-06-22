"""Tests des endpoints work-items + reindex sur Postgres éphémère.

Couvre : POST /reindex peuple git_index ; GET /work-items joint git_index par
(repo,locale,slug) et expose l'état dérivé ; drift quand un work_item n'a pas
de git_index ; GET /work-items/{id}. Aucun SQLite.
"""
from __future__ import annotations

from services.git_indexer import DEFAULT_REPO

REPO = DEFAULT_REPO


def _insert_work_item(client_db_conn, wid, slug, state="valide"):
    client_db_conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_state, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, state, "none", "now", "now"],
    )
    client_db_conn.session.commit()


def test_reindex_endpoint_returns_report(client):
    resp = client.post("/api/cockpit/reindex")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] == 10
    assert body["inserted"] == 10
    assert body["repo"] == REPO


def test_work_items_join_git_index_and_derived_state(client, conn):
    # Indexe git d'abord (via l'endpoint, même DB éphémère).
    client.post("/api/cockpit/reindex")

    # work_item baleine (publishDate future → programme).
    _insert_work_item(conn, "wi_baleine", "baleine")
    # work_item poisson-rigolo (index 9 → passé → publie).
    _insert_work_item(conn, "wi_rigolo", "poisson-rigolo")

    resp = client.get("/api/cockpit/work-items")
    assert resp.status_code == 200, resp.text
    items = {i["slug"]: i for i in resp.json()}

    assert "baleine" in items
    assert items["baleine"]["git_index"] is not None
    assert items["baleine"]["derived_state"] == "programme"
    assert items["baleine"]["drift"] is False
    assert items["baleine"]["content_hash"]

    assert items["poisson-rigolo"]["derived_state"] == "publie"
    assert items["poisson-rigolo"]["drift"] is False


def test_work_item_drift_when_no_git_index(client, conn):
    client.post("/api/cockpit/reindex")
    # work_item pointant un slug absent de git → drift.
    _insert_work_item(conn, "wi_ghost", "sujet-inexistant")

    resp = client.get("/api/cockpit/work-items")
    items = {i["slug"]: i for i in resp.json()}
    assert items["sujet-inexistant"]["drift"] is True
    assert items["sujet-inexistant"]["derived_state"] == "absent"
    assert items["sujet-inexistant"]["git_index"] is None


def test_get_single_work_item(client, conn):
    client.post("/api/cockpit/reindex")
    _insert_work_item(conn, "wi_crabe", "crabe")

    resp = client.get("/api/cockpit/work-items/wi_crabe")
    assert resp.status_code == 200, resp.text
    item = resp.json()
    assert item["id"] == "wi_crabe"
    assert item["slug"] == "crabe"
    assert item["drift"] is False
    assert item["derived_state"] in ("publie", "programme")


def test_get_work_item_404(client):
    resp = client.get("/api/cockpit/work-items/does-not-exist")
    assert resp.status_code == 404


def test_demo_ten_marine_work_items(client, conn):
    """Démo : 10 work_items marins reliés à git → états dérivés cohérents."""
    client.post("/api/cockpit/reindex")
    slugs = [
        "baleine", "poisson-simple", "tortue-de-mer", "hippocampe", "crabe",
        "poisson-rouge", "pieuvre", "baleine-bleue", "meduse", "poisson-rigolo",
    ]
    for i, slug in enumerate(slugs):
        _insert_work_item(conn, f"wi_{i}", slug)

    resp = client.get("/api/cockpit/work-items")
    items = resp.json()
    assert len(items) == 10
    states = {i["slug"]: i["derived_state"] for i in items}
    # 3 premiers (gros volume) en futur → programme ; reste → publie.
    assert states["baleine"] == "programme"
    assert states["tortue-de-mer"] == "programme"
    n_programme = sum(1 for v in states.values() if v == "programme")
    n_publie = sum(1 for v in states.values() if v == "publie")
    assert n_programme == 3
    assert n_publie == 7
    assert all(not i["drift"] for i in items)
