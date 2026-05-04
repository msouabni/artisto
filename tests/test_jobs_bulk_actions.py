"""Tests POST /api/jobs/bulk (set_priority, validate, erreurs)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_bulk_set_priority_only_pending(app_with_test_db, test_conn):
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, priority)
        VALUES ('job_p', 'text_enrichment', 'pending', '{}', '2026-01-01', 5)
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, priority)
        VALUES ('job_r', 'text_enrichment', 'running', '{}', '2026-01-01', 5)
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, priority)
        VALUES ('job_f', 'text_enrichment', 'failed', '{}', '2026-01-01', 5)
        """
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    r = client.post(
        "/api/jobs/bulk",
        json={"action": "set_priority", "ids": ["job_p", "job_r", "job_f"], "priority": 88},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "set_priority"
    assert data["affected"] == 1

    p = test_conn.execute("SELECT priority FROM job WHERE id = 'job_p'").fetchone()[0]
    assert int(p) == 88
    pr = test_conn.execute("SELECT priority FROM job WHERE id = 'job_r'").fetchone()[0]
    assert int(pr) == 5
    pf = test_conn.execute("SELECT priority FROM job WHERE id = 'job_f'").fetchone()[0]
    assert int(pf) == 5


def test_bulk_set_priority_invalid_value(app_with_test_db, test_conn):
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, priority)
        VALUES ('job_p2', 'text_enrichment', 'pending', '{}', '2026-01-01', 5)
        """
    )
    test_conn.session.commit()
    client = TestClient(app_with_test_db)

    r0 = client.post(
        "/api/jobs/bulk",
        json={"action": "set_priority", "ids": ["job_p2"], "priority": 0},
    )
    assert r0.status_code == 400

    r1 = client.post(
        "/api/jobs/bulk",
        json={"action": "set_priority", "ids": ["job_p2"], "priority": "x"},
    )
    assert r1.status_code == 400


def test_bulk_validate_apply_mixed(app_with_test_db, test_conn):
    test_conn.execute(
        """
        INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords, created_at, updated_at)
        VALUES ('term_bulk', 'themes', NULL, 'term_bulk', '{}', '{}', 0, '', '2026-01-01', '2026-01-01')
        """
    )
    proposal = {"name_i18n": {"fr": "Nom bulk"}}
    artifact = {
        "artifact_version": 1,
        "artifact_type": "term_patch",
        "entity_type": "term",
        "entity_id": "term_bulk",
        "proposal": proposal,
        "preview": {},
        "apply_plan": {"mode": "merge_entity_fields"},
        "resources": {},
    }
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_bulk_val', 'text_enrichment', 'awaiting_validation',
          '{"vocabulary_id":"themes"}', '2026-01-01', 'term', 'term_bulk', ?, '2026-01-01'
        )
        """,
        [json.dumps(artifact)],
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_bulk_done', 'text_enrichment', 'completed',
          '{}', '2026-01-01', 'term', 'term_bulk', '{}', '2026-01-01'
        )
        """
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    r = client.post(
        "/api/jobs/bulk",
        json={
            "action": "validate",
            "ids": ["job_bulk_val", "job_bulk_done"],
            "validate_action": "apply",
            "fields": ["name_i18n"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "job_bulk_val" in data["applied"]
    assert len(data["errors"]) == 1
    assert data["errors"][0]["id"] == "job_bulk_done"
    assert "awaiting_validation" in data["errors"][0]["message"]

    row = test_conn.execute(
        "SELECT name_i18n FROM term WHERE id = 'term_bulk' AND vocabulary_id = 'themes'",
    ).fetchone()
    d = json.loads(row[0])
    assert d.get("fr") == "Nom bulk"


def test_bulk_validate_reject(app_with_test_db, test_conn):
    test_conn.execute(
        """
        INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords, created_at, updated_at)
        VALUES ('term_rej', 'themes', NULL, 'term_rej', '{}', '{}', 0, '', '2026-01-01', '2026-01-01')
        """
    )
    artifact = {
        "artifact_version": 1,
        "artifact_type": "term_patch",
        "entity_type": "term",
        "entity_id": "term_rej",
        "proposal": {"name_i18n": {"fr": "X"}},
        "preview": {},
        "apply_plan": {"mode": "merge_entity_fields"},
        "resources": {},
    }
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_bulk_rej', 'text_enrichment', 'awaiting_validation',
          '{"vocabulary_id":"themes"}', '2026-01-01', 'term', 'term_rej', ?, '2026-01-01'
        )
        """,
        [json.dumps(artifact)],
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    r = client.post(
        "/api/jobs/bulk",
        json={"action": "validate", "ids": ["job_bulk_rej"], "validate_action": "reject"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["rejected"] == ["job_bulk_rej"]
    assert data["applied"] == []
    assert data["errors"] == []
    st = test_conn.execute("SELECT status FROM job WHERE id = 'job_bulk_rej'").fetchone()[0]
    assert st == "rejected"


def test_bulk_unknown_action(app_with_test_db):
    client = TestClient(app_with_test_db)
    r = client.post(
        "/api/jobs/bulk",
        json={"action": "frobnicate", "ids": ["x"]},
    )
    assert r.status_code == 400
