"""Tests POST /api/images/{id}/jobs — workflow_template."""
from __future__ import annotations

import json
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")


def _insert_image(
    conn,
    image_id: str,
    *,
    prompt: str = "hello",
    negative_prompt: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES (?, ?, 'prompt_ready', ?, ?, '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [image_id, image_id, prompt, negative_prompt],
    )


@pytest.fixture
def client(app_with_test_db):
    return TestClient(app_with_test_db)


def test_create_job_unknown_workflow_422(client, test_conn):
    _insert_image(test_conn, "img_job_wf")
    test_conn.session.commit()
    r = client.post(
        "/api/images/img_job_wf/jobs",
        json={"prompt": "p", "tags": [], "workflow_template": "no_such_template"},
    )
    assert r.status_code == 422


def test_create_job_workflow_template_in_config(client, test_conn):
    _insert_image(test_conn, "img_job_wf2")
    test_conn.session.commit()
    r = client.post(
        "/api/images/img_job_wf2/jobs",
        json={"prompt": "p2", "tags": [], "workflow_template": "z_image_turbo_v1"},
    )
    assert r.status_code == 200
    row = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_job_wf2'").fetchone()
    cfg = json.loads(row[0])
    assert cfg["workflow_template"] == "z_image_turbo_v1"


def test_create_job_default_safe_workflow_ignores_negative_prompt_from_image(client, test_conn):
    _insert_image(test_conn, "img_job_neg", negative_prompt="  no shading  ")
    test_conn.session.commit()
    r = client.post(
        "/api/images/img_job_neg/jobs",
        json={"prompt": "p3", "tags": []},
    )
    assert r.status_code == 200
    row = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_job_neg'").fetchone()
    cfg = json.loads(row[0])
    assert cfg["workflow_template"] == "ernie-image-turbo-q8-api"
    assert cfg["workflow_contract_version"] == "workflow_contract_v1"
    assert "negative_prompt" not in cfg


def test_create_job_explicit_z_image_ignores_unsupported_negative_prompt(client, test_conn):
    _insert_image(test_conn, "img_job_neg_z", negative_prompt="  no shading  ")
    test_conn.session.commit()
    r = client.post(
        "/api/images/img_job_neg_z/jobs",
        json={"prompt": "p3", "tags": [], "workflow_template": "z_image_turbo_v1"},
    )
    assert r.status_code == 200
    row = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_job_neg_z'").fetchone()
    cfg = json.loads(row[0])
    assert cfg["workflow_template"] == "z_image_turbo_v1"
    assert cfg["positive_prompt"] == "p3"
    assert "negative_prompt" not in cfg


def test_create_job_preflight_removes_unsupported_negative_for_ernie(client, test_conn):
    _insert_image(test_conn, "img_job_ernie", negative_prompt="should be ignored")
    test_conn.session.commit()
    r = client.post(
        "/api/images/img_job_ernie/jobs",
        json={"prompt": "p4", "tags": [], "workflow_template": "ernie-image-turbo-q8-api"},
    )
    assert r.status_code == 200
    row = test_conn.execute("SELECT config FROM job WHERE image_id = 'img_job_ernie'").fetchone()
    cfg = json.loads(row[0])
    assert cfg["workflow_template"] == "ernie-image-turbo-q8-api"
    assert cfg["positive_prompt"] == "p4"
    assert "negative_prompt" not in cfg
    assert cfg["workflow_contract_version"] == "workflow_contract_v1"
