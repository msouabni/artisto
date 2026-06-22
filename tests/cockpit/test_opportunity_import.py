"""Tests de l'import des opportunités (score de demande) sur Postgres éphémère.

Couvre : parsing CSV + proxy score depuis volume, upsert idempotent, lien
work_item.opportunity_id par slug. Aucun SQLite (cf. tests/cockpit/conftest.py).
"""
from __future__ import annotations

from pathlib import Path

from services.git_indexer import DEFAULT_REPO
from services.opportunity_import import (
    DEFAULT_OPPORTUNITY_CSV,
    import_opportunities,
    parse_csv,
)

REPO = DEFAULT_REPO


def _insert_work_item(conn, wid, slug, state="valide"):
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_state, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, state, "none", "now", "now"],
    )
    conn.session.commit()


def test_parse_csv_scores_proxy_from_volume():
    opps, proxy = parse_csv(DEFAULT_OPPORTUNITY_CSV)
    assert len(opps) == 10
    # Le CSV n'a pas de colonne score brute → proxy volume appliqué.
    assert proxy is True
    by_slug = {o.slug: o for o in opps}
    # baleine = volume max (1600) → score 100.
    assert by_slug["baleine"].volume == 1600
    assert by_slug["baleine"].score == 100.0
    # poisson-rigolo = volume 390 → score = 100*390/1600 = 24.4.
    assert by_slug["poisson-rigolo"].score == round(100 * 390 / 1600, 1)
    # cluster dérivé du pilier_fr.
    assert by_slug["baleine"].cluster == "animaux marins"


def test_import_opportunities_inserts_and_is_idempotent(conn):
    r1 = import_opportunities(conn, repo=REPO)
    conn.session.commit()
    assert r1.parsed == 10
    assert r1.inserted == 10
    assert r1.updated == 0
    assert r1.score_proxy_used is True

    r2 = import_opportunities(conn, repo=REPO)
    conn.session.commit()
    # 2e run : upsert → tout en update, rien de neuf.
    assert r2.inserted == 0
    assert r2.updated == 10
    rows = conn.execute("SELECT count(*) FROM opportunity").fetchone()
    assert rows[0] == 10


def test_import_links_work_items_by_slug(conn):
    # work_items préexistants (dont un sans opportunité correspondante).
    _insert_work_item(conn, "wi_baleine", "baleine")
    _insert_work_item(conn, "wi_crabe", "crabe")
    _insert_work_item(conn, "wi_orphan", "sujet-hors-cluster")

    report = import_opportunities(conn, repo=REPO)
    conn.session.commit()

    # 2 des 3 work_items ont un slug présent dans le cluster → reliés.
    assert report.linked == 2

    row = conn.execute(
        "SELECT opportunity_id FROM work_item WHERE id = ?", ["wi_baleine"]
    ).fetchone()
    assert row[0] is not None
    # Le lien pointe une opportunité de slug baleine.
    opp = conn.execute(
        "SELECT slug, score FROM opportunity WHERE id = ?", [row[0]]
    ).fetchone()
    assert opp[0] == "baleine"
    assert opp[1] == 100.0

    orphan = conn.execute(
        "SELECT opportunity_id FROM work_item WHERE id = ?", ["wi_orphan"]
    ).fetchone()
    assert orphan[0] is None


def test_import_endpoint(client, conn):
    _insert_work_item(conn, "wi_baleine", "baleine")
    resp = client.post("/api/cockpit/opportunities/import")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parsed"] == 10
    assert body["linked"] == 1
    assert body["score_proxy_used"] is True

    resp2 = client.get("/api/cockpit/opportunities")
    opps = resp2.json()
    assert len(opps) == 10
    # Triées par score décroissant → baleine en tête.
    assert opps[0]["slug"] == "baleine"
    assert opps[0]["score"] == 100.0
