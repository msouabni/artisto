"""Tests de la détection de drift (fonction pure + via endpoints).

Deux cas de drift (cap : git = vérité, le cockpit SIGNALE, ne corrige jamais) :
  (a) work_item → page absente de git (pas de git_index / exists faux) ;
  (b) content_hash git ≠ last_synced_hash (édition hors cockpit).
Aucun SQLite.
"""
from __future__ import annotations

from services.git_indexer import DEFAULT_REPO
from services.git_states import (
    DRIFT_ABSENT,
    DRIFT_HASH_CHANGED,
    compute_drift,
)

REPO = DEFAULT_REPO


# ── Fonction pure ───────────────────────────────────────────────────────────────

def test_drift_absent_when_no_git_row():
    drift, reason = compute_drift(None, last_synced_hash="abc")
    assert drift is True
    assert reason == DRIFT_ABSENT


def test_drift_absent_when_exists_false():
    drift, reason = compute_drift({"exists": False, "content_hash": "abc"}, "abc")
    assert drift is True
    assert reason == DRIFT_ABSENT


def test_no_drift_when_hash_matches():
    drift, reason = compute_drift(
        {"exists": True, "content_hash": "abc"}, last_synced_hash="abc"
    )
    assert drift is False
    assert reason is None


def test_drift_when_hash_changed():
    drift, reason = compute_drift(
        {"exists": True, "content_hash": "NEWHASH"}, last_synced_hash="OLDHASH"
    )
    assert drift is True
    assert reason == DRIFT_HASH_CHANGED


def test_no_drift_when_never_synced():
    # last_synced_hash NULL → page existante jamais synchronisée → PAS en drift hash.
    drift, reason = compute_drift({"exists": True, "content_hash": "abc"}, None)
    assert drift is False
    assert reason is None


# ── Via endpoint /work-items ────────────────────────────────────────────────────

def _insert_work_item(conn, wid, slug, last_synced_hash=None, state="valide"):
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, last_synced_hash, "
        "staging_state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, state, last_synced_hash, "none", "now", "now"],
    )
    conn.session.commit()


def test_endpoint_drift_absent_from_git(client, conn):
    client.post("/api/cockpit/reindex")
    _insert_work_item(conn, "wi_ghost", "sujet-inexistant")
    items = {i["slug"]: i for i in client.get("/api/cockpit/work-items").json()}
    assert items["sujet-inexistant"]["drift"] is True
    assert items["sujet-inexistant"]["drift_reason"] == DRIFT_ABSENT


def test_endpoint_drift_hash_changed(client, conn):
    """work_item dont last_synced_hash diffère du content_hash git → drift (b)."""
    client.post("/api/cockpit/reindex")
    # On mémorise un hash périmé : la page baleine a été éditée hors cockpit.
    _insert_work_item(conn, "wi_baleine", "baleine", last_synced_hash="STALE_HASH")

    items = {i["slug"]: i for i in client.get("/api/cockpit/work-items").json()}
    bal = items["baleine"]
    assert bal["git_index"] is not None
    assert bal["drift"] is True
    assert bal["drift_reason"] == DRIFT_HASH_CHANGED


def test_endpoint_no_drift_when_synced_hash_matches(client, conn):
    """last_synced_hash == content_hash git courant → pas de drift."""
    client.post("/api/cockpit/reindex")
    # Récupère le hash réel de la page crabe puis l'enregistre comme synchronisé.
    row = conn.execute(
        "SELECT content_hash FROM git_index WHERE slug = ?", ["crabe"]
    ).fetchone()
    real_hash = row[0]
    _insert_work_item(conn, "wi_crabe", "crabe", last_synced_hash=real_hash)

    items = {i["slug"]: i for i in client.get("/api/cockpit/work-items").json()}
    assert items["crabe"]["drift"] is False
    assert items["crabe"]["drift_reason"] is None
