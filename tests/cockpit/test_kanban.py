"""Tests de l'endpoint kanban (miroir git) sur Postgres éphémère.

Couvre : regroupement par état d'orchestration, badges état-git dérivés,
score de demande sur les cartes, 0 drift sur démo nominale, drift signalé
(absent + hash changé). Aucun SQLite.
"""
from __future__ import annotations

from services.git_indexer import DEFAULT_REPO

REPO = DEFAULT_REPO
STATES = ("candidat", "valide", "construction", "mesure", "verdict")


def _insert_work_item(conn, wid, slug, state="valide", last_synced_hash=None):
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, last_synced_hash, "
        "staging_state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, state, last_synced_hash, "none", "now", "now"],
    )
    conn.session.commit()


def _bootstrap(client, conn):
    """reindex git + import opportunités (lien par slug)."""
    client.post("/api/cockpit/reindex")
    client.post("/api/cockpit/opportunities/import")


def test_kanban_columns_always_present(client):
    resp = client.get("/api/cockpit/kanban")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["states"] == list(STATES)
    # Toutes les colonnes présentes même sans work_item.
    for st in STATES:
        assert st in body["columns"]
        assert body["columns"][st] == []
    assert body["totals"]["work_items"] == 0
    assert body["totals"]["drift"] == 0


def test_kanban_groups_by_orchestration_state_with_git_and_score(client, conn):
    _bootstrap(client, conn)
    _insert_work_item(conn, "wi_baleine", "baleine", state="construction")
    _insert_work_item(conn, "wi_crabe", "crabe", state="valide")
    _insert_work_item(conn, "wi_meduse", "meduse", state="valide")

    body = client.get("/api/cockpit/kanban").json()
    cols = body["columns"]
    assert len(cols["construction"]) == 1
    assert len(cols["valide"]) == 2
    assert body["totals"]["work_items"] == 3
    assert body["totals"]["by_state"]["valide"] == 2

    # Carte baleine : badge git dérivé + score de demande présents.
    card = cols["construction"][0]
    assert card["slug"] == "baleine"
    assert card["derived_state"] in ("programme", "publie")
    assert card["git_index"] is not None
    assert card["score"] == 100.0       # baleine = volume max → proxy 100
    assert card["volume"] == 1600
    assert card["drift"] is False

    # Tri intra-colonne par score décroissant (crabe 880 > meduse 480).
    valide_slugs = [c["slug"] for c in cols["valide"]]
    assert valide_slugs == ["crabe", "meduse"]


def test_kanban_zero_drift_on_nominal_demo(client, conn):
    _bootstrap(client, conn)
    slugs = [
        "baleine", "poisson-facile", "tortue-de-mer", "hippocampe", "crabe",
        "poisson-rouge", "pieuvre", "baleine-bleue", "meduse", "poisson-rigolo",
    ]
    for i, slug in enumerate(slugs):
        _insert_work_item(conn, f"wi_{i}", slug, state="valide")

    body = client.get("/api/cockpit/kanban").json()
    assert body["totals"]["work_items"] == 10
    assert body["totals"]["drift"] == 0
    assert body["first_drift"] is None
    # Tous les work_items reliés à une opportunité → score non nul.
    assert all(c["score"] is not None for c in body["columns"]["valide"])


def test_kanban_signals_drift_absent(client, conn):
    _bootstrap(client, conn)
    _insert_work_item(conn, "wi_ghost", "sujet-inexistant", state="candidat")

    body = client.get("/api/cockpit/kanban").json()
    assert body["totals"]["drift"] == 1
    assert body["first_drift"] is not None
    assert body["first_drift"]["slug"] == "sujet-inexistant"
    assert body["first_drift"]["drift_reason"] == "absent_from_git"
    card = body["columns"]["candidat"][0]
    assert card["drift"] is True


def test_kanban_signals_drift_hash_changed(client, conn):
    _bootstrap(client, conn)
    _insert_work_item(conn, "wi_bal", "baleine", state="mesure",
                      last_synced_hash="STALE")

    body = client.get("/api/cockpit/kanban").json()
    assert body["totals"]["drift"] == 1
    card = body["columns"]["mesure"][0]
    assert card["drift"] is True
    assert card["drift_reason"] == "content_hash_changed"
