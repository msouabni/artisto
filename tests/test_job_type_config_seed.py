from __future__ import annotations

from api.db import DEFAULT_JOB_TYPES, ensure_default_job_types


def test_ensure_default_job_types_seeds_required_rows(test_conn):
    test_conn.execute("DELETE FROM job_type_config")
    test_conn.session.commit()

    ensure_default_job_types(test_conn.session)
    test_conn.session.commit()

    rows = test_conn.execute(
        "SELECT type, enabled, category FROM job_type_config ORDER BY type"
    ).fetchall()

    expected = sorted(
        (spec["type"], spec["enabled"], spec["category"]) for spec in DEFAULT_JOB_TYPES
    )
    assert [(r[0], bool(r[1]), r[2]) for r in rows] == expected
