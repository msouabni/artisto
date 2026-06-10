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

    def test_workflow_template_stored_in_config(self, client, test_conn):
        _insert_image(test_conn, "img_wf_ok", status="prompt_ready", prompt="wf")
        test_conn.execute(
            "INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at) VALUES (?, 'universal_v0', 'themes', '2026-01-01')",
            ["img_wf_ok"],
        )
        # variants=["lineart"] : mode legacy explicite (Image.prompt direct,
        # pas de PromptGenerator). Requis depuis C1.2 (2026-06-01) : le défaut
        # registre est désormais ``pastel_chromakey`` qui exige un leaf_id.
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={
                "image_ids": ["img_wf_ok"],
                "variants": ["lineart"],
                "workflow_template": "z_image_turbo_v1",
            },
        )
        assert r.status_code == 200
        job = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_wf_ok'").fetchone()
        cfg = json.loads(job[0])
        assert cfg["workflow_template"] == "z_image_turbo_v1"

    def test_unknown_workflow_template_422(self, client):
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={
                "image_ids": ["img_any"],
                "variants": ["lineart"],
                "workflow_template": "template_inexistant_xyz",
            },
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
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_busy"], "variants": ["lineart"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["success"] == 0
        assert data["summary"]["failed"] == 1
        assert "déjà" in data["results"][0]["error"].lower() or "pending" in data["results"][0]["error"].lower()

