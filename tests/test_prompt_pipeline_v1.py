"""Tests API pipeline prompts v1 — mode async (enqueue HTTP 202).

Les routes /api/ai/* compute renvoient désormais HTTP 202 + {job_id, job_type, status}.
L'exécution synchrone (planner→writer, Ollama mocks) est couverte par les tests
des workers (test_ai_pipeline_worker.py) et services (test_ai_parse.py).
"""
from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")

from api.routes.ai import resolve_image_prompt_template_keys


@pytest.fixture
def client(app_with_test_db, test_conn):
    """Client avec tous les types IA activés."""
    test_conn.execute(
        """
        UPDATE job_type_config SET enabled = 1
        WHERE type IN (
            'image_prompt_create', 'image_prompt_improve', 'image_prompt_validate',
            'image_generate_prompts', 'image_prompt_suggest', 'image_prompts_bulk',
            'image_generate_concepts'
        )
        """
    )
    test_conn.session.commit()
    return TestClient(app_with_test_db)


def _assert_enqueued(resp, expected_type: str) -> str:
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "pending"
    assert data["job_type"] == expected_type
    assert data["job_id"]
    return data["job_id"]


def test_create_prompt_returns_202_job_id(client, test_conn):
    """POST /api/ai/create-prompt → HTTP 202 + job image_prompt_create en DB."""
    resp = client.post(
        "/api/ai/create-prompt",
        json={"keywords": "chat mignon", "title": "", "tags_context": ""},
    )
    job_id = _assert_enqueued(resp, "image_prompt_create")

    row = test_conn.execute(
        "SELECT type, status, config FROM job WHERE id = ?", [job_id]
    ).fetchone()
    assert row is not None
    assert row[0] == "image_prompt_create"
    assert row[1] == "pending"
    import json
    cfg = json.loads(row[2])
    assert cfg["keywords"] == "chat mignon"


def test_create_prompt_requires_keywords_or_title(client):
    """Sans keywords ni title : le job est quand même créé (validation côté worker)."""
    resp = client.post(
        "/api/ai/create-prompt",
        json={"keywords": "", "title": ""},
    )
    # Les routes async enfilent sans valider le contenu métier (la validation est côté worker)
    assert resp.status_code == 202


def test_improve_prompt_returns_202(client):
    resp = client.post(
        "/api/ai/improve-prompt",
        json={"title": "T", "prompt": "base prompt", "count": 2},
    )
    _assert_enqueued(resp, "image_prompt_improve")


def test_validate_prompt_returns_202(client):
    resp = client.post(
        "/api/ai/validate-prompt",
        json={"prompt": "some prompt text", "profile": "kids_coloring_lineart_v1"},
    )
    _assert_enqueued(resp, "image_prompt_validate")


def test_generate_prompts_returns_202(client):
    resp = client.post(
        "/api/ai/generate-prompts",
        json={"count": 1, "concepts": [{"id": "manual", "name_fr": "Renard", "name_en": "Fox"}]},
    )
    _assert_enqueued(resp, "image_generate_prompts")


def test_suggest_prompt_returns_202(client):
    resp = client.post(
        "/api/ai/suggest-prompt",
        json={"title": "x", "prompt": "y", "count": 1},
    )
    _assert_enqueued(resp, "image_prompt_suggest")


def test_create_prompts_bulk_returns_202(client):
    resp = client.post(
        "/api/ai/create-prompts-bulk",
        json={
            "items": [
                {"image_id": "", "keywords": "k1", "title": "T1"},
                {"image_id": "", "keywords": "k2", "title": "T2"},
            ],
            "validate_prompts": False,
        },
    )
    _assert_enqueued(resp, "image_prompts_bulk")


def test_create_prompts_bulk_empty_items_still_enqueues(client):
    """Même avec items vides la route enfile un job (validation côté worker)."""
    resp = client.post("/api/ai/create-prompts-bulk", json={"items": []})
    assert resp.status_code == 202


def test_create_prompts_bulk_workflow_template_in_config(client, test_conn):
    """workflow_template est transmis dans le config du job."""
    import json
    resp = client.post(
        "/api/ai/create-prompts-bulk",
        json={
            "items": [{"image_id": "", "keywords": "k1", "title": "T1"}],
            "validate_prompts": False,
            "workflow_template": "ernie-image-turbo-q8-api",
        },
    )
    job_id = _assert_enqueued(resp, "image_prompts_bulk")
    row = test_conn.execute("SELECT config FROM job WHERE id = ?", [job_id]).fetchone()
    cfg = json.loads(row[0])
    assert cfg.get("workflow_template") == "ernie-image-turbo-q8-api"


# ─── Tests template keys (non HTTP, restent valides) ──────────────────────────

def test_resolve_image_prompt_template_keys_default_ernie():
    z = resolve_image_prompt_template_keys(None)
    assert z["writer"] == "prompt_writer_ernie"
    assert z["validate"] == "validate_prompt_ernie"
    assert z["improve"] == "improve_prompt_ernie"
    assert z["planner"] == "prompt_planner"


def test_resolve_image_prompt_template_keys_z_image_explicit():
    z = resolve_image_prompt_template_keys("z_image_turbo_v1")
    assert z["writer"] == "prompt_writer_zimage"


def test_resolve_image_prompt_template_keys_ernie_explicit_same_as_default():
    e = resolve_image_prompt_template_keys("ernie-image-turbo-q8-api")
    assert e["writer"] == "prompt_writer_ernie"
    assert e["validate"] == "validate_prompt_ernie"
    assert e["improve"] == "improve_prompt_ernie"


def test_resolve_image_prompt_template_keys_unknown_falls_back_ernie():
    u = resolve_image_prompt_template_keys("some_future_workflow")
    assert u["writer"] == "prompt_writer_ernie"
