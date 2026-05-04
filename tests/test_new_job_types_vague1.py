"""Tests Vague 1 : image_generate_prompts, image_prompt_suggest, image_prompts_bulk."""
from __future__ import annotations

import json
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _enable_type(test_conn, job_type: str) -> None:
    test_conn.execute(
        "UPDATE job_type_config SET enabled = 1 WHERE type = ?",
        [job_type],
    )
    test_conn.session.commit()


# ─── Tests enqueue validation ──────────────────────────────────────────────────

class TestEnqueueImageGeneratePrompts:
    def test_enqueue_with_concepts(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_generate_prompts")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_generate_prompts",
                "config": {
                    "concepts": [{"id": "c1", "name_en": "Cat coloring"}],
                    "count": 3,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "enqueued"
        assert data["type"] == "image_generate_prompts"

    def test_enqueue_with_anchor(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_generate_prompts")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_generate_prompts",
                "config": {
                    "term_id": "animals",
                    "vocabulary_id": "themes",
                },
            },
        )
        assert resp.status_code == 200

    def test_enqueue_missing_concepts_and_anchor_fails(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_generate_prompts")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_generate_prompts",
                "config": {},
            },
        )
        assert resp.status_code == 400

    def test_enqueue_invalid_count_fails(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_generate_prompts")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_generate_prompts",
                "config": {
                    "concepts": [{"id": "c1"}],
                    "count": 99,
                },
            },
        )
        assert resp.status_code == 400

    def test_enqueue_disabled_type_fails(self, app_with_test_db):
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_generate_prompts",
                "config": {"concepts": [{"id": "c1"}]},
            },
        )
        assert resp.status_code == 400


class TestEnqueueImagePromptSuggest:
    def test_enqueue_with_image_id(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_prompt_suggest")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_prompt_suggest",
                "config": {"image_id": "img_001"},
            },
        )
        assert resp.status_code == 200

    def test_enqueue_with_title(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_prompt_suggest")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_prompt_suggest",
                "config": {"title": "Cat coloring page"},
            },
        )
        assert resp.status_code == 200

    def test_enqueue_missing_image_and_title_fails(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_prompt_suggest")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_prompt_suggest",
                "config": {},
            },
        )
        assert resp.status_code == 400


class TestEnqueueImagePromptsBulk:
    def test_enqueue_bulk_valid(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_prompts_bulk")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_prompts_bulk",
                "config": {
                    "items": [
                        {"title": "Cat coloring", "keywords": "cat"},
                        {"title": "Dog coloring", "keywords": "dog"},
                    ]
                },
            },
        )
        assert resp.status_code == 200

    def test_enqueue_bulk_empty_fails(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_prompts_bulk")
        client = TestClient(app_with_test_db)
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_prompts_bulk",
                "config": {"items": []},
            },
        )
        assert resp.status_code == 400

    def test_enqueue_bulk_too_many_fails(self, app_with_test_db, test_conn):
        _enable_type(test_conn, "image_prompts_bulk")
        client = TestClient(app_with_test_db)
        items = [{"title": f"concept {i}", "keywords": f"kw{i}"} for i in range(11)]
        resp = client.post(
            "/api/jobs/enqueue",
            json={
                "type": "image_prompts_bulk",
                "config": {"items": items},
            },
        )
        assert resp.status_code == 400


# ─── Tests worker process/save_result ─────────────────────────────────────────

class TestAiPipelineWorkerNewTypes:
    def _make_worker(self, test_conn):
        from workers.ai_pipeline_worker import AiPipelineWorker
        worker = AiPipelineWorker()
        worker._conn = lambda read_only=False: test_conn
        original_close = test_conn.close
        test_conn.close = lambda: None
        return worker, original_close

    def _make_job(self, job_type: str, config: dict, test_conn) -> dict:
        job_id = f"job_{job_type}_test"
        test_conn.execute(
            """
            INSERT INTO job (id, type, status, config, created_at, started_at)
            VALUES (?, ?, 'running', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """,
            [job_id, job_type, json.dumps(config)],
        )
        test_conn.session.commit()
        return {
            "job_id": job_id,
            "type": job_type,
            "config": config,
            "entity_type": "image",
            "entity_id": "img_001",
            "started_at": "2026-01-01T00:00:00Z",
        }

    def test_save_result_image_generate_prompts(self, test_conn):
        worker, original_close = self._make_worker(test_conn)
        try:
            job = self._make_job(
                "image_generate_prompts",
                {"concepts": [{"id": "c1"}], "image_id": "img_001"},
                test_conn,
            )
            result = {
                "suggestions": [{"concept_id": "c1", "prompt": "a cat", "negative_prompt": ""}],
            }
            worker.save_result(job, result)
        finally:
            test_conn.close = original_close

        row = test_conn.execute(
            "SELECT status, result FROM job WHERE id = ?",
            ["job_image_generate_prompts_test"],
        ).fetchone()
        assert row[0] == "awaiting_validation"
        artifact = json.loads(row[1])
        assert "suggestions" in artifact.get("proposal", {})

    def test_save_result_image_prompt_suggest(self, test_conn):
        worker, original_close = self._make_worker(test_conn)
        try:
            job = self._make_job(
                "image_prompt_suggest",
                {"image_id": "img_001"},
                test_conn,
            )
            result = {
                "suggestions": [{"prompt": "a nice cat", "negative_prompt": "blurry"}],
            }
            worker.save_result(job, result)
        finally:
            test_conn.close = original_close

        row = test_conn.execute(
            "SELECT status, result FROM job WHERE id = ?",
            ["job_image_prompt_suggest_test"],
        ).fetchone()
        assert row[0] == "awaiting_validation"
        artifact = json.loads(row[1])
        proposal = artifact.get("proposal", {})
        assert "prompt" in proposal

    def test_save_result_image_prompts_bulk(self, test_conn):
        worker, original_close = self._make_worker(test_conn)
        try:
            job = self._make_job(
                "image_prompts_bulk",
                {"items": [{"title": "cat", "keywords": "cat"}]},
                test_conn,
            )
            result = {
                "results": [{"image_id": None, "ok": True, "prompt": "cat lineart", "negative_prompt": ""}],
                "summary": {"total": 1, "success": 1, "failed": 0},
            }
            worker.save_result(job, result)
        finally:
            test_conn.close = original_close

        row = test_conn.execute(
            "SELECT status, result FROM job WHERE id = ?",
            ["job_image_prompts_bulk_test"],
        ).fetchone()
        assert row[0] == "awaiting_validation"
        artifact = json.loads(row[1])
        proposal = artifact.get("proposal", {})
        assert "results" in proposal
        assert "summary" in proposal


# ─── Test NEW types présents dans job_type_config ─────────────────────────────

def test_new_job_types_in_job_type_config(test_conn):
    """Les 3 nouveaux types sont seedés dans job_type_config."""
    rows = test_conn.execute(
        "SELECT type FROM job_type_config WHERE type IN (?, ?, ?)",
        ["image_generate_prompts", "image_prompt_suggest", "image_prompts_bulk"],
    ).fetchall()
    types_found = {r[0] for r in rows}
    assert "image_generate_prompts" in types_found
    assert "image_prompt_suggest" in types_found
    assert "image_prompts_bulk" in types_found


def test_new_types_in_ai_pipeline_worker_types():
    """Les 3 nouveaux types sont déclarés dans AI_PIPELINE_JOB_TYPES."""
    from workers.ai_pipeline_worker import AI_PIPELINE_JOB_TYPES
    assert "image_generate_prompts" in AI_PIPELINE_JOB_TYPES
    assert "image_prompt_suggest" in AI_PIPELINE_JOB_TYPES
    assert "image_prompts_bulk" in AI_PIPELINE_JOB_TYPES


def test_new_types_in_enqueueable_job_types():
    """Les 3 nouveaux types sont dans ENQUEUEABLE_JOB_TYPES."""
    from api.routes.jobs import ENQUEUEABLE_JOB_TYPES
    assert "image_generate_prompts" in ENQUEUEABLE_JOB_TYPES
    assert "image_prompt_suggest" in ENQUEUEABLE_JOB_TYPES
    assert "image_prompts_bulk" in ENQUEUEABLE_JOB_TYPES
