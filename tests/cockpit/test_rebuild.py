"""Tests du rebuild (prio 3 — décision 4 DIRECTION-2026-06-22).

Couvre :
  - ``compute_rebuild_due`` (fonction pure, ``now`` injecté) : avant date = non
    due, après date sans build = due, après build = non due ;
  - ``rebuild_due_run`` (DB Postgres éphémère) : déclenche le mock, pose
    ``last_build_at``, repasse non-due (idempotent) ;
  - endpoints à la demande (``POST /api/cockpit/rebuild``) + cron
    (``POST /api/cockpit/rebuild/run-due``), tous deux en **mode mock**
    (aucun deploy réel : ni REBUILD_HOOK_URL ni REBUILD_CMD) ;
  - ``GET /api/cockpit/next-action`` surface le rebuild dû en priorité haute.

Postgres uniquement (aucun SQLite). Aucun deploy réel : hook/cmd jamais
configurés dans ces tests → ``trigger_rebuild`` reste un no-op loggué.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from services.git_indexer import DEFAULT_REPO
from services.rebuild import (
    TRIGGER_MODE_MOCK,
    compute_rebuild_due,
    fetch_due_schedules,
    rebuild_due_run,
    sync_schedule_from_git,
    trigger_rebuild,
)

REPO = DEFAULT_REPO
NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


# ── compute_rebuild_due (fonction pure) ─────────────────────────────────────────

def test_not_due_before_publish_date():
    # publishDate future → pas censée être live → pas de rebuild dû.
    assert compute_rebuild_due(date(2026, 7, 1), None, now=NOW) is False


def test_due_when_past_and_never_built():
    # Échue + jamais buildée → due.
    assert compute_rebuild_due(date(2026, 6, 1), None, now=NOW) is True


def test_due_when_past_and_build_predates_publish():
    # Échue + dernier build ANTÉRIEUR à publishDate → build ne couvre pas la page → due.
    assert compute_rebuild_due(
        date(2026, 6, 20), "2026-06-19T08:00:00Z", now=NOW
    ) is True


def test_not_due_when_build_after_publish():
    # Échue MAIS buildée après publishDate → page déjà live → non due.
    assert compute_rebuild_due(
        date(2026, 6, 20), "2026-06-21T08:00:00Z", now=NOW
    ) is False


def test_not_due_when_no_publish_date():
    # Pas de publishDate → publiée à la date de commit → jamais « en attente ».
    assert compute_rebuild_due(None, None, now=NOW) is False


def test_due_at_exact_publish_date():
    # publishDate == now (échéance pile) → due si jamais buildée.
    assert compute_rebuild_due(date(2026, 6, 22), None, now=NOW) is True


def test_default_now_is_utc_now():
    # publishDate très ancienne, jamais buildée → due même sans now injecté.
    assert compute_rebuild_due(date(2000, 1, 1), None) is True


# ── trigger_rebuild en mode mock (aucun env configuré) ──────────────────────────

def test_trigger_rebuild_mock(monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)
    result = trigger_rebuild(now=NOW)
    assert result.mode == TRIGGER_MODE_MOCK
    assert result.triggered is True          # mock = succès virtuel
    assert result.built_at is not None
    assert result.error is None


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


# ── rebuild_due_run (DB éphémère, mock) ─────────────────────────────────────────

def test_rebuild_due_run_triggers_mock_and_clears_due(conn, monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)

    # Page programmée échue (publishDate passée), jamais buildée.
    _insert_work_item(conn, "wi_baleine", "baleine")
    _insert_git_index(conn, "baleine", date(2026, 6, 1))
    conn.session.commit()

    sync_schedule_from_git(conn, REPO, now=NOW)
    conn.session.commit()

    # Due avant le run.
    due = fetch_due_schedules(conn, now=NOW)
    assert len(due) == 1
    assert due[0]["slug"] == "baleine"

    report = rebuild_due_run(conn, now=NOW)
    conn.session.commit()
    assert report.due_before == 1
    assert report.triggered is True
    assert report.mode == TRIGGER_MODE_MOCK
    assert report.updated_schedules == 1
    assert report.due_after == 0
    assert "baleine" in report.slugs

    # last_build_at posé → plus due.
    assert fetch_due_schedules(conn, now=NOW) == []


def test_rebuild_due_run_noop_when_nothing_due(conn, monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)

    # Page programmée dans le FUTUR → pas due.
    _insert_work_item(conn, "wi_future", "futur-sujet")
    _insert_git_index(conn, "futur-sujet", date(2026, 7, 1))
    conn.session.commit()
    sync_schedule_from_git(conn, REPO, now=NOW)
    conn.session.commit()

    report = rebuild_due_run(conn, now=NOW)
    assert report.due_before == 0
    assert report.triggered is False         # aucun build inutile
    assert report.updated_schedules == 0


def test_rebuild_due_run_idempotent(conn, monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)

    _insert_work_item(conn, "wi_crabe", "crabe")
    _insert_git_index(conn, "crabe", date(2026, 5, 1))
    conn.session.commit()
    sync_schedule_from_git(conn, REPO, now=NOW)
    conn.session.commit()

    first = rebuild_due_run(conn, now=NOW)
    conn.session.commit()
    assert first.updated_schedules == 1

    # Second passage immédiat → plus rien de dû.
    second = rebuild_due_run(conn, now=NOW)
    assert second.due_before == 0
    assert second.triggered is False


# ── Endpoints (mock, aucun deploy réel) ─────────────────────────────────────────

def _bootstrap(client):
    """Réindexe les mocks git (peuple git_index) — réutilise l'indexeur réel."""
    client.post("/api/cockpit/reindex")


def test_endpoint_rebuild_on_demand_mock(client, monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)
    _bootstrap(client)

    resp = client.post("/api/cockpit/rebuild")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "mock"
    assert body["triggered"] is True
    assert body["built_at"] is not None


def test_endpoint_run_due_mock(client, conn, monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)

    # Insère une page programmée échue + son git_index, sans passer par reindex
    # (publishDate maîtrisée). publishDate très ancienne → due maintenant.
    _insert_work_item(conn, "wi_echue", "sujet-echu")
    _insert_git_index(conn, "sujet-echu", date(2020, 1, 1))
    conn.session.commit()

    resp = client.post("/api/cockpit/rebuild/run-due")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["due_before"] == 1
    assert body["triggered"] is True
    assert body["updated_schedules"] == 1
    assert body["due_after"] == 0

    # GET /rebuild/due → vide après le build.
    due = client.get("/api/cockpit/rebuild/due").json()
    assert due["count"] == 0


# ── next-action surface le rebuild dû ───────────────────────────────────────────

def test_next_action_surfaces_rebuild_due(client, conn, monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)

    _insert_work_item(conn, "wi_due", "baleine")
    _insert_git_index(conn, "baleine", date(2020, 1, 1))
    conn.session.commit()

    body = client.get("/api/cockpit/next-action").json()
    assert body["kind"] == "rebuild_due"
    assert body["priority"] == "high"
    assert body["count"] == 1
    assert "rebuild" in body["message"].lower()
    assert body["action"]["endpoint"] == "/api/cockpit/rebuild/run-due"
    assert body["items"][0]["slug"] == "baleine"


def test_next_action_rebuild_takes_priority_over_drift(client, conn, monkeypatch):
    monkeypatch.delenv("REBUILD_HOOK_URL", raising=False)
    monkeypatch.delenv("REBUILD_CMD", raising=False)

    # Une page due au rebuild...
    _insert_work_item(conn, "wi_due", "baleine")
    _insert_git_index(conn, "baleine", date(2020, 1, 1))
    # ...ET une page en drift (absente de git).
    _insert_work_item(conn, "wi_ghost", "sujet-fantome")
    conn.session.commit()

    body = client.get("/api/cockpit/next-action").json()
    # Rebuild dû passe avant le drift.
    assert body["kind"] == "rebuild_due"


def test_next_action_none_when_all_up_to_date(client, conn):
    # Page publiée + buildée → ni due ni drift.
    _insert_work_item(conn, "wi_ok", "baleine")
    _insert_git_index(conn, "baleine", date(2026, 6, 1))
    conn.session.commit()
    # Pose un last_build_at postérieur via schedule.
    conn.execute(
        "INSERT INTO schedule (id, work_item_id, publish_date, last_build_at, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ["sched_ok", "wi_ok", date(2026, 6, 1), "2026-06-22T00:00:00Z", "now", "now"],
    )
    # last_synced_hash = hash git → pas de drift hash.
    conn.execute(
        "UPDATE work_item SET last_synced_hash = ? WHERE id = ?",
        ["hash_baleine", "wi_ok"],
    )
    conn.session.commit()

    body = client.get("/api/cockpit/next-action").json()
    assert body["kind"] == "none", body
    assert body["action"] is None
