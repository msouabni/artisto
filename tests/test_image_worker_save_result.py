from __future__ import annotations

import json

from PIL import Image, ImageDraw

import workers.image_worker as image_worker_mod
from workers.image_worker import ImageWorker


def test_image_worker_save_result_commits_updates(test_conn, tmp_path, monkeypatch):
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_worker', 'img_worker', 'generating', 'prompt', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, worker_id)
        VALUES ('job_worker', 'image_generation', 'running', 'img_worker', '{}', '2026-01-01T00:00:00Z', 'image', 'img_worker', 'worker_1')
        """
    )
    test_conn.session.commit()

    out_dir = tmp_path
    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", out_dir)
    png = out_dir / "img_worker_job_worker.png"
    im = Image.new("RGB", (256, 256), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    for i in range(24, 232, 6):
        dr.line([(i, 48), (i, 208)], fill=(0, 0, 0), width=2)
    im.save(png)

    worker = ImageWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn
    result = {
        "entity_id": "img_worker",
        "rel_path": "outputs/img_worker_job_worker.png",
        "prompt": "prompt",
        "negative_prompt": "",
        "used_comfy": True,
        "external_ref_id": "prompt-123",
        "generation_params": {"width": 1024, "height": 1024, "steps": 4},
    }

    try:
        worker.save_result({"job_id": "job_worker"}, result)
    finally:
        test_conn.close = original_close

    job_row = test_conn.execute(
        "SELECT status, progress, external_ref_id FROM job WHERE id = ?",
        ["job_worker"],
    ).fetchone()
    assert job_row[0] == "awaiting_validation"
    assert job_row[1] == 100
    assert job_row[2] == "prompt-123"

    result_json = test_conn.execute(
        "SELECT result FROM job WHERE id = ?",
        ["job_worker"],
    ).fetchone()[0]
    artifact = json.loads(result_json)
    qc = artifact.get("qc", {})
    assert qc.get("schema_version") == 1
    assert qc["status"] in ("pass", "warning", "fail")
    assert "technical_score" in qc
    assert len(qc.get("checks", [])) >= 4
    assert "qc_not_evaluated" not in qc.get("flags", [])

    image_row = test_conn.execute(
        "SELECT status, selected_output_id FROM image WHERE id = ?",
        ["img_worker"],
    ).fetchone()
    assert image_row == ("generating", None)

    output_row = test_conn.execute(
        "SELECT job_id, file_path, model_config FROM image_output WHERE id = ?",
        ["out_job_worker"],
    ).fetchone()
    assert output_row[0] == "job_worker"
    assert output_row[1] == "outputs/img_worker_job_worker.png"
    assert json.loads(output_row[2])["steps"] == 4


def test_image_worker_save_result_duration_ms_set(test_conn, tmp_path, monkeypatch):
    """duration_ms est persisté quand started_at est présent."""
    import workers.image_worker as image_worker_mod
    from workers.image_worker import ImageWorker

    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_dur', 'img_dur', 'generating', 'p', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id,
                         worker_id, started_at)
        VALUES ('job_dur', 'image_generation', 'running', 'img_dur', '{}',
                '2026-01-01T00:00:00Z', 'image', 'img_dur', 'w1', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.session.commit()

    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    from PIL import Image as PILImage
    png = tmp_path / "img_dur_job_dur.png"
    PILImage.new("RGB", (64, 64), (255, 255, 255)).save(png)

    worker = ImageWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn

    try:
        worker.save_result(
            {"job_id": "job_dur", "started_at": "2026-01-01T00:00:00Z"},
            {
                "entity_id": "img_dur",
                "rel_path": "outputs/img_dur_job_dur.png",
                "prompt": "p",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": None,
                "generation_params": {"width": 64, "height": 64},
            },
        )
    finally:
        test_conn.close = original_close

    row = test_conn.execute(
        "SELECT duration_ms FROM job WHERE id = ?",
        ["job_dur"],
    ).fetchone()
    assert row is not None
    assert row[0] is not None
    assert row[0] >= 0
