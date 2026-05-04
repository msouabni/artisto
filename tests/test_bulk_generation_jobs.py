"""Tests POST /api/images/bulk-create-generation-jobs."""
from __future__ import annotations

import json
import sys

import pytest

sys.path.insert(0, "src")
from fastapi.testclient import TestClient


def _insert_image(conn, image_id: str, *, status: str, prompt: str, negative_prompt: str = "") -> None:
    conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [image_id, image_id, status, prompt, negative_prompt],
    )


@pytest.fixture
def client(app_with_test_db):
    return TestClient(app_with_test_db)


class TestBulkCreateGenerationJobs:
    def test_empty_ids_400(self, client):
        r = client.post("/api/images/bulk-create-generation-jobs", json={"image_ids": []})
        assert r.status_code == 400

    def test_too_many_ids_400(self, client):
        ids = [f"img_{i}" for i in range(26)]
        r = client.post("/api/images/bulk-create-generation-jobs", json={"image_ids": ids})
        assert r.status_code == 400

    def test_dedup_and_partial_success(self, client, test_conn):
        _insert_image(test_conn, "img_ok", status="prompt_ready", prompt="hello", negative_prompt="bad")
        test_conn.execute(
            "INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at) VALUES (?, 'universal_v0', 'themes', '2026-01-01')",
            ["img_ok"],
        )
        _insert_image(test_conn, "img_draft", status="draft", prompt="has text")
        _insert_image(test_conn, "img_empty", status="prompt_ready", prompt="   ")

        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_ok", "img_ok", "img_draft", "img_empty", "missing"], "steps": 9},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["summary"] == {"total": 4, "success": 1, "failed": 3}
        by_id = {row["image_id"]: row for row in data["results"]}
        assert by_id["img_ok"]["ok"] is True
        assert by_id["img_ok"]["job_id"]
        job_cfg = json.loads(
            test_conn.execute("SELECT config FROM job WHERE image_id = 'img_ok'").fetchone()[0]
        )
        assert job_cfg["workflow_template"] == "ernie-image-turbo-q8-api"
        assert by_id["img_draft"]["ok"] is False
        assert "draft" in by_id["img_draft"]["error"].lower()
        assert by_id["img_empty"]["ok"] is False
        assert "Prompt vide" in by_id["img_empty"]["error"]
        assert by_id["missing"]["ok"] is False

        row = test_conn.execute("SELECT status FROM image WHERE id = 'img_ok'").fetchone()
        assert row[0] == "scheduled"

        job = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_ok'").fetchone()
        cfg = json.loads(job[0])
        assert cfg["prompt"] == "hello"
        assert "negative_prompt" not in cfg
        assert cfg["steps"] == 9
        assert cfg["tags"] == [{"taxonomy_id": "universal_v0", "term_id": "themes"}]

    def test_workflow_template_stored_in_config(self, client, test_conn):
        _insert_image(test_conn, "img_wf_ok", status="prompt_ready", prompt="wf")
        test_conn.execute(
            "INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at) VALUES (?, 'universal_v0', 'themes', '2026-01-01')",
            ["img_wf_ok"],
        )
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_wf_ok"], "workflow_template": "z_image_turbo_v1"},
        )
        assert r.status_code == 200
        job = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_wf_ok'").fetchone()
        cfg = json.loads(job[0])
        assert cfg["workflow_template"] == "z_image_turbo_v1"

    def test_bulk_explicit_z_image_ignores_unsupported_negative_prompt(self, client, test_conn):
        _insert_image(test_conn, "img_wf_neg", status="prompt_ready", prompt="wf", negative_prompt="bad")
        test_conn.execute(
            "INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at) VALUES (?, 'universal_v0', 'themes', '2026-01-01')",
            ["img_wf_neg"],
        )
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_wf_neg"], "workflow_template": "z_image_turbo_v1"},
        )
        assert r.status_code == 200
        job = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_wf_neg'").fetchone()
        cfg = json.loads(job[0])
        assert cfg["positive_prompt"] == "wf"
        assert "negative_prompt" not in cfg

    def test_unknown_workflow_template_422(self, client):
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_any"], "workflow_template": "template_inexistant_xyz"},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert isinstance(detail, str)
        assert "inconnu" in detail.lower() or "disponibles" in detail.lower()

    def test_rejects_when_job_pending(self, client, test_conn):
        _insert_image(test_conn, "img_busy", status="prompt_ready", prompt="x")
        test_conn.execute(
            """
            INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id)
            VALUES ('job_existing', 'image_generation', 'pending', 'img_busy', '{}', '2026-01-01', 'image', 'img_busy')
            """
        )
        r = client.post("/api/images/bulk-create-generation-jobs", json={"image_ids": ["img_busy"]})
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["success"] == 0
        assert data["summary"]["failed"] == 1
        assert "déjà" in data["results"][0]["error"].lower() or "pending" in data["results"][0]["error"].lower()

    def test_bulk_preflight_removes_unsupported_negative_for_ernie(self, client, test_conn):
        _insert_image(
            test_conn,
            "img_ernie_safe",
            status="prompt_ready",
            prompt="wf",
            negative_prompt="legacy negative",
        )
        test_conn.execute(
            "INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at) VALUES (?, 'universal_v0', 'themes', '2026-01-01')",
            ["img_ernie_safe"],
        )
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_ernie_safe"], "workflow_template": "ernie-image-turbo-q8-api"},
        )
        assert r.status_code == 200
        job = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_ernie_safe'").fetchone()
        cfg = json.loads(job[0])
        assert cfg["workflow_template"] == "ernie-image-turbo-q8-api"
        assert cfg["positive_prompt"] == "wf"
        assert "negative_prompt" not in cfg
