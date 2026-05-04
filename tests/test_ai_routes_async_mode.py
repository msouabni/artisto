"""Tests routes /api/ai/* compute : HTTP 202 + {job_id, status, job_type}.

Toutes les routes compute renvoient désormais HTTP 202 systématiquement.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def async_client(app_with_test_db, test_conn):
    """Client avec tous les types IA activés."""
    test_conn.execute(
        """
        UPDATE job_type_config SET enabled = 1
        WHERE type IN (
            'taxonomy_enrich_term', 'taxonomy_enrich_terms_batch',
            'taxonomy_enrich_keywords', 'taxonomy_suggest_children',
            'taxonomy_generate_vocabulary', 'image_generate_concepts',
            'image_generate_prompts', 'image_prompt_suggest',
            'image_prompt_create', 'image_prompt_improve',
            'image_prompt_validate', 'image_prompts_bulk'
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
    assert data["job_id"].startswith("job_ai_")
    return data["job_id"]


def test_enrich_term_async(async_client, test_conn):
    test_conn.execute(
        "INSERT INTO term (id, vocabulary_id, slug, name_i18n) VALUES ('t1', 'themes', 't1', '{}')"
    )
    test_conn.session.commit()
    resp = async_client.post(
        "/api/ai/enrich-term",
        json={"term_id": "t1", "vocabulary_id": "themes"},
    )
    _assert_enqueued(resp, "taxonomy_enrich_term")


def test_enrich_terms_batch_async(async_client, test_conn):
    test_conn.execute(
        "INSERT INTO term (id, vocabulary_id, slug, name_i18n) VALUES ('t2', 'themes', 't2', '{}')"
    )
    test_conn.session.commit()
    resp = async_client.post(
        "/api/ai/enrich-terms-batch",
        json={"term_ids": ["t2"], "vocabulary_id": "themes"},
    )
    _assert_enqueued(resp, "taxonomy_enrich_terms_batch")


def test_suggest_children_async(async_client, test_conn):
    test_conn.execute(
        "INSERT INTO term (id, vocabulary_id, slug, name_i18n) VALUES ('t3', 'themes', 't3', '{}')"
    )
    test_conn.session.commit()
    resp = async_client.post(
        "/api/ai/suggest-children",
        json={"term_id": "t3", "vocabulary_id": "themes"},
    )
    _assert_enqueued(resp, "taxonomy_suggest_children")


def test_generate_vocabulary_async(async_client):
    resp = async_client.post(
        "/api/ai/generate-vocabulary",
        json={"theme": "animaux", "root_count": 3, "children_per_root": 2},
    )
    _assert_enqueued(resp, "taxonomy_generate_vocabulary")


def test_enrich_keywords_async(async_client, test_conn):
    test_conn.execute(
        "INSERT INTO term (id, vocabulary_id, slug, name_i18n) VALUES ('t4', 'themes', 't4', '{}')"
    )
    test_conn.session.commit()
    resp = async_client.post(
        "/api/ai/enrich-keywords",
        json={"term_id": "t4", "vocabulary_id": "themes"},
    )
    _assert_enqueued(resp, "taxonomy_enrich_keywords")


def test_generate_concepts_async(async_client):
    resp = async_client.post(
        "/api/ai/generate-concepts",
        json={"theme": "forêt", "count": 3},
    )
    _assert_enqueued(resp, "image_generate_concepts")


def test_generate_prompts_async(async_client):
    resp = async_client.post(
        "/api/ai/generate-prompts",
        json={"concepts": [{"id": "c1", "name_en": "Cat"}], "count": 2},
    )
    _assert_enqueued(resp, "image_generate_prompts")


def test_suggest_prompt_async(async_client):
    resp = async_client.post(
        "/api/ai/suggest-prompt",
        json={"title": "Chat mignon", "prompt": "cat", "count": 1},
    )
    _assert_enqueued(resp, "image_prompt_suggest")


def test_create_prompt_async(async_client):
    resp = async_client.post(
        "/api/ai/create-prompt",
        json={"keywords": "cat coloring", "title": ""},
    )
    _assert_enqueued(resp, "image_prompt_create")


def test_create_prompts_bulk_async(async_client):
    resp = async_client.post(
        "/api/ai/create-prompts-bulk",
        json={"items": [{"keywords": "cat", "title": "Cat"}]},
    )
    _assert_enqueued(resp, "image_prompts_bulk")


def test_improve_prompt_async(async_client):
    resp = async_client.post(
        "/api/ai/improve-prompt",
        json={"prompt": "cat line art", "count": 1},
    )
    _assert_enqueued(resp, "image_prompt_improve")


def test_validate_prompt_async(async_client):
    resp = async_client.post(
        "/api/ai/validate-prompt",
        json={"prompt": "cat line art on white"},
    )
    _assert_enqueued(resp, "image_prompt_validate")


def test_async_job_is_persisted_in_db(async_client, test_conn):
    """Le job enqueué est bien persisté dans la table job."""
    resp = async_client.post(
        "/api/ai/create-prompt",
        json={"keywords": "fox", "title": ""},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    row = test_conn.execute(
        "SELECT type, status FROM job WHERE id = ?", [job_id]
    ).fetchone()
    assert row is not None
    assert row[0] == "image_prompt_create"
    assert row[1] == "pending"


def test_async_disabled_type_returns_400(app_with_test_db, test_conn):
    """Un type désactivé renvoie 400."""
    # ne pas activer taxonomy_enrich_term
    client = TestClient(app_with_test_db)
    test_conn.execute(
        "INSERT INTO term (id, vocabulary_id, slug, name_i18n) VALUES ('tx', 'themes', 'tx', '{}')"
    )
    test_conn.session.commit()
    resp = client.post(
        "/api/ai/enrich-term",
        json={"term_id": "tx", "vocabulary_id": "themes"},
    )
    assert resp.status_code == 400


def test_prompts_admin_routes_not_affected(async_client):
    """Routes admin (prompts YAML, status) ne sont pas concernées par le mode async."""
    resp = async_client.get("/api/ai/status")
    # Status peut être 200 ou 503 selon disponibilité Ollama — mais pas 202
    assert resp.status_code != 202
