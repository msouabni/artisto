"""Tests pour GET /api/jobs/stats : avg_duration_ms et comptages."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_stats_avg_duration_ms_present(app_with_test_db):
    """avg_duration_ms est présent dans le payload même si NULL."""
    client = TestClient(app_with_test_db)
    resp = client.get("/api/jobs/stats")
    assert resp.status_code == 200
    data = resp.json()
    # La table peut être vide — dans ce cas le dict est vide, c'est OK.
    for _type, info in data.items():
        assert "avg_duration_ms" in info


def test_stats_avg_duration_ms_computed(app_with_test_db, test_conn):
    """avg_duration_ms est calculé correctement depuis duration_ms."""
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, started_at, finished_at, duration_ms)
        VALUES
            ('s1', 'text_enrichment', 'awaiting_validation', '{}', '2026-01-01T00:00:00Z',
             '2026-01-01T00:00:00Z', '2026-01-01T00:00:02Z', 2000),
            ('s2', 'text_enrichment', 'applied', '{}', '2026-01-01T00:00:00Z',
             '2026-01-01T00:00:00Z', '2026-01-01T00:00:04Z', 4000),
            ('s3', 'text_enrichment', 'pending', '{}', '2026-01-01T00:00:00Z',
             NULL, NULL, NULL)
        """
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get("/api/jobs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "text_enrichment" in data
    stats = data["text_enrichment"]
    assert stats["pending"] >= 1
    # avg des 2 jobs terminés : (2000 + 4000) / 2 = 3000
    assert stats["avg_duration_ms"] == 3000


def test_stats_avg_duration_ms_null_when_no_finished_jobs(app_with_test_db, test_conn):
    """avg_duration_ms est null si aucun job terminé avec duration_ms."""
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at)
        VALUES ('p1', 'taxonomy_enrich_term', 'pending', '{}', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get("/api/jobs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "taxonomy_enrich_term" in data
    assert data["taxonomy_enrich_term"]["avg_duration_ms"] is None
