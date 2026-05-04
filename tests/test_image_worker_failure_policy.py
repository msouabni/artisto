from __future__ import annotations

from workers.image_worker import ImageWorker


def _prepare_running_job(test_conn, *, image_id: str, job_id: str) -> None:
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES (?, ?, 'generating', 'prompt', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [image_id, image_id],
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, worker_id, retry_count, max_retries)
        VALUES (?, 'image_generation', 'running', ?, '{}', '2026-01-01T00:00:00Z', 'image', ?, 'worker_1', 0, 3)
        """,
        [job_id, image_id, image_id],
    )
    test_conn.execute(
        "UPDATE job_type_config SET enabled = 1 WHERE type = 'image_generation'"
    )
    test_conn.session.commit()


def test_image_worker_handle_failure_retries_without_disabling_type(test_conn):
    _prepare_running_job(test_conn, image_id="img_fail_retry", job_id="job_fail_retry")
    worker = ImageWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn

    try:
        worker.handle_failure(
            {"job_id": "job_fail_retry", "entity_id": "img_fail_retry", "retry_count": 0, "max_retries": 3},
            RuntimeError("oom workflow"),
        )
    finally:
        test_conn.close = original_close

    job_row = test_conn.execute(
        "SELECT status, retry_count, scheduled_at FROM job WHERE id = ?",
        ["job_fail_retry"],
    ).fetchone()
    assert job_row[0] == "pending"
    assert job_row[1] == 1
    assert job_row[2]

    image_row = test_conn.execute(
        "SELECT status FROM image WHERE id = ?",
        ["img_fail_retry"],
    ).fetchone()
    assert image_row[0] == "scheduled"

    type_row = test_conn.execute(
        "SELECT enabled FROM job_type_config WHERE type = 'image_generation'"
    ).fetchone()
    assert bool(type_row[0]) is True


def test_image_worker_handle_failure_marks_image_prompt_ready_after_last_retry(test_conn):
    _prepare_running_job(test_conn, image_id="img_fail_final", job_id="job_fail_final")
    worker = ImageWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn

    try:
        worker.handle_failure(
            {"job_id": "job_fail_final", "entity_id": "img_fail_final", "retry_count": 3, "max_retries": 3},
            RuntimeError("still failing"),
        )
    finally:
        test_conn.close = original_close

    job_row = test_conn.execute(
        "SELECT status, finished_at FROM job WHERE id = ?",
        ["job_fail_final"],
    ).fetchone()
    assert job_row[0] == "failed"
    assert job_row[1]

    image_row = test_conn.execute(
        "SELECT status FROM image WHERE id = ?",
        ["img_fail_final"],
    ).fetchone()
    assert image_row[0] == "prompt_ready"
