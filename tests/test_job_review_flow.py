"""Tests artefact de revue v1, enqueue, validate apply/reject (image_generation)."""
from __future__ import annotations

import json
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")

from api.job_review_artifact import (
    build_image_concepts_artifact,
    build_image_generation_artifact,
    build_minimal_image_qc_v1,
    serialize_artifact,
)


def test_build_image_generation_artifact_includes_qc_v1():
    art = build_image_generation_artifact(
        entity_id="img_qc",
        image_output_id="out_qc",
        rel_path="outputs/img.png",
        generation_params={"prompt": "x"},
        prompt="x",
    )
    assert "qc" in art
    q = art["qc"]
    assert q["schema_version"] == 1
    assert q["status"] == "pending"
    assert "qc_not_evaluated" in q["flags"]
    assert q["checks"] == []
    assert isinstance(q["recommendations"], list)


def test_build_image_generation_artifact_custom_qc_override():
    custom = build_minimal_image_qc_v1()
    custom["status"] = "pass"
    custom["flags"] = []
    custom["technical_score"] = 80
    art = build_image_generation_artifact(
        entity_id="img_qc2",
        image_output_id="out_qc2",
        rel_path="outputs/y.png",
        generation_params={},
        prompt="p",
        qc=custom,
    )
    assert art["qc"]["status"] == "pass"
    assert art["qc"]["technical_score"] == 80


@pytest.fixture
def client(app_with_test_db):
    return TestClient(app_with_test_db)


def test_enqueue_text_enrichment(client, test_conn):
    r = client.post(
        "/api/jobs/enqueue",
        json={
            "type": "text_enrichment",
            "entity_type": "term",
            "entity_id": "t1",
            "vocabulary_id": "themes",
            "config": {"prompt": "Hello", "system": "You are a test assistant."},
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "enqueued"
    jid = data["id"]
    row = test_conn.execute(
        "SELECT type, status, entity_type, entity_id FROM job WHERE id = ?",
        [jid],
    ).fetchone()
    assert row[0] == "text_enrichment"
    assert row[1] == "pending"
    assert row[2] == "term"
    assert row[3] == "t1"


def test_enqueue_disabled_type_400(client, test_conn):
    test_conn.execute(
        "UPDATE job_type_config SET enabled = 0 WHERE type = 'text_enrichment'",
    )
    test_conn.session.commit()
    r = client.post(
        "/api/jobs/enqueue",
        json={"type": "text_enrichment", "config": {"prompt": "x"}},
    )
    assert r.status_code == 400


def test_validate_term_apply_wrapped_artifact(client, test_conn):
    test_conn.execute(
        """
        INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords, created_at, updated_at)
        VALUES ('term_rv', 'themes', NULL, 'term_rv', '{}', '{}', 0, '', '2026-01-01', '2026-01-01')
        """
    )
    proposal = {"name_i18n": {"fr": "Nom FR"}}
    artifact = {
        "artifact_version": 1,
        "artifact_type": "term_patch",
        "entity_type": "term",
        "entity_id": "term_rv",
        "proposal": proposal,
        "preview": {},
        "apply_plan": {"mode": "merge_entity_fields"},
        "resources": {},
    }
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_term_rv', 'text_enrichment', 'awaiting_validation',
          '{"vocabulary_id":"themes"}', '2026-01-01', 'term', 'term_rv', ?, '2026-01-01'
        )
        """,
        [json.dumps(artifact)],
    )
    test_conn.session.commit()

    r = client.post(
        "/api/jobs/job_term_rv/validate",
        json={"action": "apply", "fields": ["name_i18n"]},
    )
    assert r.status_code == 200
    row = test_conn.execute(
        "SELECT name_i18n FROM term WHERE id = 'term_rv' AND vocabulary_id = 'themes'",
    ).fetchone()
    d = json.loads(row[0])
    assert d.get("fr") == "Nom FR"


def test_validate_image_generation_apply_and_reject(client, test_conn, tmp_path, monkeypatch):
    from api import job_review_apply as jra

    out_root = tmp_path / "outputs"
    out_root.mkdir(parents=True)
    monkeypatch.setattr(jra, "OUTPUTS_DIR", out_root)

    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_rv', 'img_rv', 'generating', 'p', '', '', '2026-01-01', '2026-01-01')
        """
    )
    out_id = "out_job_img_rv"
    rel = "outputs/img_rv_job_img_rv.png"
    png = out_root.parent / rel  # data/outputs/file.png layout: parent + rel
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    artifact = build_image_generation_artifact(
        entity_id="img_rv",
        image_output_id=out_id,
        rel_path=rel,
        generation_params={"width": 512, "height": 512},
        prompt="p",
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_img_rv', 'image_generation', 'awaiting_validation', 'img_rv', '{}', '2026-01-01',
          'image', 'img_rv', ?, '2026-01-01'
        )
        """,
        [serialize_artifact(artifact)],
    )
    test_conn.execute(
        """
        INSERT INTO image_output (id, image_id, job_id, file_path, file_format, width, height, model_name, model_config, created_at)
        VALUES (?, 'img_rv', 'job_img_rv', ?, 'png', 512, 512, 'm', '{}', '2026-01-01')
        """,
        [out_id, rel],
    )
    test_conn.session.commit()

    r = client.post("/api/jobs/job_img_rv/validate", json={"action": "apply"})
    assert r.status_code == 200
    st = test_conn.execute(
        "SELECT status, selected_output_id FROM image WHERE id = 'img_rv'",
    ).fetchone()
    assert st[0] == "generated"
    assert st[1] == out_id
    job_st = test_conn.execute("SELECT status FROM job WHERE id = 'job_img_rv'").fetchone()
    assert job_st[0] == "applied"

    # Reject path (second job)
    test_conn.execute(
        """UPDATE image SET status = 'generating', selected_output_id = NULL WHERE id = 'img_rv'"""
    )
    test_conn.execute("DELETE FROM image_output WHERE id = ?", [out_id])
    test_conn.execute("DELETE FROM job WHERE id = 'job_img_rv'")
    artifact2 = build_image_generation_artifact(
        entity_id="img_rv",
        image_output_id=out_id,
        rel_path=rel,
        generation_params={},
        prompt="p",
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_img_rv2', 'image_generation', 'awaiting_validation', 'img_rv', '{}', '2026-01-01',
          'image', 'img_rv', ?, '2026-01-01'
        )
        """,
        [serialize_artifact(artifact2)],
    )
    test_conn.execute(
        """
        INSERT INTO image_output (id, image_id, job_id, file_path, file_format, width, height, model_name, model_config, created_at)
        VALUES (?, 'img_rv', 'job_img_rv2', ?, 'png', 512, 512, 'm', '{}', '2026-01-01')
        """,
        [out_id, rel],
    )
    test_conn.session.commit()

    r2 = client.post("/api/jobs/job_img_rv2/validate", json={"action": "reject"})
    assert r2.status_code == 200
    st2 = test_conn.execute("SELECT status FROM image WHERE id = 'img_rv'").fetchone()
    assert st2[0] == "prompt_ready"
    out_cnt = test_conn.execute("SELECT COUNT(*) FROM image_output WHERE job_id = 'job_img_rv2'").fetchone()[0]
    assert out_cnt == 0


def test_validate_image_generation_apply_with_qc_fail_not_blocked(client, test_conn, tmp_path, monkeypatch):
    """QC ``fail`` dans l'artefact n'empêche pas l'apply (QC informationnel)."""
    from api import job_review_apply as jra

    out_root = tmp_path / "outputs"
    out_root.mkdir(parents=True)
    monkeypatch.setattr(jra, "OUTPUTS_DIR", out_root)

    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_qc_fail', 'img_qc_fail', 'generating', 'p', '', '', '2026-01-01', '2026-01-01')
        """
    )
    out_id = "out_job_qc_fail"
    rel = "outputs/img_qc_fail_job.png"
    png = out_root.parent / rel
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    qc_fail = build_minimal_image_qc_v1()
    qc_fail["status"] = "fail"
    qc_fail["flags"] = ["strong_color"]
    qc_fail["technical_score"] = 0
    qc_fail["checks"] = [{"id": "color_presence", "pass": False, "severity": "fail", "detail": "test"}]

    artifact = build_image_generation_artifact(
        entity_id="img_qc_fail",
        image_output_id=out_id,
        rel_path=rel,
        generation_params={"width": 256, "height": 256},
        prompt="p",
        qc=qc_fail,
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_qc_fail', 'image_generation', 'awaiting_validation', 'img_qc_fail', '{}', '2026-01-01',
          'image', 'img_qc_fail', ?, '2026-01-01'
        )
        """,
        [serialize_artifact(artifact)],
    )
    test_conn.execute(
        """
        INSERT INTO image_output (id, image_id, job_id, file_path, file_format, width, height, model_name, model_config, created_at)
        VALUES (?, 'img_qc_fail', 'job_qc_fail', ?, 'png', 256, 256, 'm', '{}', '2026-01-01')
        """,
        [out_id, rel],
    )
    test_conn.session.commit()

    r_rev = client.get("/api/jobs/job_qc_fail/review")
    assert r_rev.status_code == 200
    assert r_rev.json()["qc"]["status"] == "fail"

    r = client.post("/api/jobs/job_qc_fail/validate", json={"action": "apply"})
    assert r.status_code == 200
    st = test_conn.execute(
        "SELECT status, selected_output_id FROM image WHERE id = 'img_qc_fail'",
    ).fetchone()
    assert st[0] == "generated"
    assert st[1] == out_id


def test_bulk_rejects_when_awaiting_validation(client, test_conn):
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_av', 'img_av', 'prompt_ready', 'x', '', '', '2026-01-01', '2026-01-01')
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id)
        VALUES ('job_av', 'image_generation', 'awaiting_validation', 'img_av', '{}', '2026-01-01', 'image', 'img_av')
        """
    )
    test_conn.session.commit()
    r = client.post(
        "/api/images/bulk-create-generation-jobs",
        json={"image_ids": ["img_av"]},
    )
    assert r.status_code == 200
    assert r.json()["summary"]["failed"] == 1


def test_enqueue_image_generate_concepts(client, test_conn):
    test_conn.execute(
        "UPDATE job_type_config SET enabled = 1 WHERE type = 'image_generate_concepts'",
    )
    test_conn.session.commit()
    r = client.post(
        "/api/jobs/enqueue",
        json={
            "type": "image_generate_concepts",
            "config": {"theme": "forests", "count": 3},
        },
    )
    assert r.status_code == 200
    jid = r.json()["id"]
    row = test_conn.execute(
        "SELECT type, status, entity_type FROM job WHERE id = ?",
        [jid],
    ).fetchone()
    assert row[0] == "image_generate_concepts"
    assert row[1] == "pending"
    assert row[2] == "concept_batch"


def test_validate_image_generate_concepts_apply(client, test_conn):
    test_conn.execute(
        """
        INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords, created_at, updated_at)
        VALUES ('term_gc', 'themes', NULL, 'term_gc', '{}', '{}', 0, '', '2026-01-01', '2026-01-01')
        """
    )
    artifact = build_image_concepts_artifact(
        job_id="job_gc_1",
        theme="animals",
        suggestions=[
            {"id": "img_concept_a", "title": "Cat scene", "name_en": "Cat", "name_fr": "Chat"},
        ],
        anchor={"term_id": "term_gc", "vocabulary_id": "themes"},
        job_type="image_generate_concepts",
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, result, finished_at)
        VALUES (
          'job_gc_1', 'image_generate_concepts', 'awaiting_validation',
          ?, '2026-01-01', 'concept_batch', 'job_gc_1', ?, '2026-01-01'
        )
        """,
        [
            json.dumps(
                {
                    "theme": "animals",
                    "vocabulary_id": "themes",
                    "term_id": "term_gc",
                }
            ),
            serialize_artifact(artifact),
        ],
    )
    test_conn.session.commit()

    r = client.post("/api/jobs/job_gc_1/validate", json={"action": "apply"})
    assert r.status_code == 200
    row = test_conn.execute(
        "SELECT title, status, origin_type, origin_term_id FROM image WHERE id = 'img_concept_a'",
    ).fetchone()
    assert row is not None
    assert row[0] == "Cat scene"
    assert row[1] == "draft"
    assert row[2] == "ai_concepts_job"
    assert row[3] == "term_gc"
    tag = test_conn.execute(
        "SELECT taxonomy_id, term_id FROM image_taxonomy_tag WHERE image_id = 'img_concept_a'",
    ).fetchone()
    assert tag is not None
    assert tag[0] == "universal_v0"
    assert tag[1] == "term_gc"
