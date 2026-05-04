from __future__ import annotations

from fastapi.testclient import TestClient

from api.db import ensure_default_job_types


def test_update_job_type_enabled(app_with_test_db, test_conn):
    ensure_default_job_types(test_conn.session)
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    response = client.put("/api/jobs/types/image_generation", json={"enabled": True})

    assert response.status_code == 200
    assert response.json()["enabled"] is True

    row = test_conn.execute(
        "SELECT enabled FROM job_type_config WHERE type = ?",
        ["image_generation"],
    ).fetchone()
    assert row[0] in (True, 1)
