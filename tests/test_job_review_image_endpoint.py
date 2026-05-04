"""Tests GET /api/jobs/{id}/review et redirection /diff pour image_generation."""
from __future__ import annotations

import json
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")

from api.job_review_artifact import build_image_generation_artifact, serialize_artifact
from api.job_review_image import build_image_generation_review_payload


@pytest.fixture
def client(app_with_test_db):
    return TestClient(app_with_test_db)


def _insert_image_job_review(
    test_conn,
    *,
    job_id: str,
    image_id: str,
    status: str,
    job_type: str = "image_generation",
    result_json: str | None = None,
) -> None:
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES (?, ?, 'generating', 'p', '', '', '2026-01-01', '2026-01-01')
        """,
        [image_id, image_id],
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (?, ?, ?, ?, '{}', '2026-01-01', 'image', ?, ?, '2026-01-01')
        """,
        [job_id, job_type, status, image_id, image_id, result_json],
    )
    test_conn.session.commit()


def test_build_image_generation_review_payload_v1():
    stored = build_image_generation_artifact(
        entity_id="img_x",
        image_output_id="out_j1",
        rel_path="outputs/x.png",
        generation_params={"width": 1024, "workflow_template": "z_v1"},
        prompt="hello",
        negative_prompt="neg",
        qc={"schema_version": 1, "status": "fail", "technical_score": 12, "overall_score": 12, "checks": []},
    )
    payload = build_image_generation_review_payload(
        job_id="job_x",
        job_status="awaiting_validation",
        entity_id="img_x",
        stored=stored,
        image_status="generating",
        image_selected_output_id=None,
    )
    assert payload["legacy"] is False
    assert payload["artifact_type"] == "image_generation_output"
    assert payload["preview"]["prompt"] == "hello"
    assert payload["preview"]["negative_prompt"] == "neg"
    assert payload["preview"]["image_url"] == "/api/jobs/job_x/output-image"
    assert payload["qc"]["status"] == "fail"
    assert payload["qc"]["technical_score"] == 12
    steps = {s["field"]: s for s in payload["apply_plan_summary"]}
    assert steps["status"]["from"] == "generating"
    assert steps["status"]["to"] == "generated"
    assert steps["selected_output_id"]["to"] == "out_j1"


def test_build_image_generation_review_payload_legacy():
    payload = build_image_generation_review_payload(
        job_id="job_legacy",
        job_status="awaiting_validation",
        entity_id="img_l",
        stored={"prompt": "old", "qc": {"schema_version": 1, "status": "pass"}},
        image_status="generating",
        image_selected_output_id=None,
    )
    assert payload["legacy"] is True
    assert payload["apply_plan_summary"] == []
    assert payload["qc"]["status"] == "pass"


def test_get_review_200_and_structure(client, test_conn):
    art = build_image_generation_artifact(
        entity_id="img_rev_api",
        image_output_id="out_rev_api",
        rel_path="outputs/rev.png",
        generation_params={"width": 512, "height": 512},
        prompt="p1",
        negative_prompt="n1",
    )
    _insert_image_job_review(
        test_conn,
        job_id="job_rev_api",
        image_id="img_rev_api",
        status="awaiting_validation",
        result_json=serialize_artifact(art),
    )
    test_conn.execute(
        "UPDATE image SET status = 'generating' WHERE id = 'img_rev_api'",
    )
    test_conn.session.commit()

    r = client.get("/api/jobs/job_rev_api/review")
    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] == "job_rev_api"
    assert data["entity_id"] == "img_rev_api"
    assert data["legacy"] is False
    assert "preview" in data and "qc" in data
    assert data["preview"]["image_url"] == "/api/jobs/job_rev_api/output-image"
    assert data["qc"]["schema_version"] == 1
    fields = {s["field"]: s for s in data["apply_plan_summary"]}
    assert fields["status"]["to"] == "generated"
    assert fields["selected_output_id"]["to"] == "out_rev_api"
    assert any("delete" in (x.get("action") or "").lower() or "delete" in (x.get("detail") or "").lower() for x in data["reject_plan_summary"])


def test_get_review_404(client):
    r = client.get("/api/jobs/job_does_not_exist_zz/review")
    assert r.status_code == 404


def test_get_review_400_wrong_status(client, test_conn):
    _insert_image_job_review(
        test_conn,
        job_id="job_pending_rv",
        image_id="img_pending_rv",
        status="pending",
        result_json="{}",
    )
    r = client.get("/api/jobs/job_pending_rv/review")
    assert r.status_code == 400


def test_get_review_400_wrong_type(client, test_conn):
    test_conn.execute(
        """
        INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords, created_at, updated_at)
        VALUES ('t_rv_type', 'themes', NULL, 't_rv_type', '{}', '{}', 0, '', '2026-01-01', '2026-01-01')
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_text_rv', 'text_enrichment', 'awaiting_validation',
          '{}', '2026-01-01', 'term', 't_rv_type', '{}', '2026-01-01'
        )
        """
    )
    test_conn.session.commit()
    r = client.get("/api/jobs/job_text_rv/review")
    assert r.status_code == 400


def test_get_diff_redirects_for_image_generation_output(client, test_conn):
    art = build_image_generation_artifact(
        entity_id="img_diff_redir",
        image_output_id="out_dr",
        rel_path="outputs/dr.png",
        generation_params={},
        prompt="x",
    )
    _insert_image_job_review(
        test_conn,
        job_id="job_diff_redir",
        image_id="img_diff_redir",
        status="awaiting_validation",
        result_json=serialize_artifact(art),
    )
    r = client.get("/api/jobs/job_diff_redir/diff")
    assert r.status_code == 200
    data = r.json()
    assert data.get("redirect_to") == "review"
    assert data.get("review_url") == "/api/jobs/job_diff_redir/review"
    assert data.get("fields") == []


def test_get_review_legacy_result(client, test_conn):
    _insert_image_job_review(
        test_conn,
        job_id="job_legacy_rv",
        image_id="img_legacy_rv",
        status="awaiting_validation",
        result_json=json.dumps({"prompt": "raw", "negative_prompt": "n"}),
    )
    r = client.get("/api/jobs/job_legacy_rv/review")
    assert r.status_code == 200
    data = r.json()
    assert data["legacy"] is True
    assert "legacy_note" in data
