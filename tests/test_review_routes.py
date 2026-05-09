"""Tests pour ``src/api/routes/review.py`` (greffon prod).

Brief : ``docs/architect/briefs/2026-05-09_brief-greffon-prod.md``.

Couvre :
- ``GET /api/review/queue``    : empty, avec annotation jointe, filtres status / workflow_class
- ``GET /api/review/file``     : 404 sur id inconnu, 200 sur cas valide, refus path traversal
- ``POST /api/annotation``     : upsert nouveau / existant (pas de doublon),
  validation 400 (score, image_tag, prompt_tag, target_type),
  validation 404 (target_id absent)
- Cohérence des vocabulaires partagés (18 / 8 — single source of truth)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")

from api.annotation_vocab import IMAGE_TAGS_VOCAB, PROMPT_TAGS_VOCAB


# ── Helpers ──────────────────────────────────────────────────────────────────


def _client(app):
    return TestClient(app)


def _insert_image(
    conn, *,
    image_id: str,
    status: str = "awaiting_validation",
    prompt: str = "a lion in savanna",
    negative: str = "no colors",
    title: str = "Lion",
) -> None:
    conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path,
                           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, '', '2026-05-09', '2026-05-09')
        """,
        [image_id, title, status, prompt, negative],
    )


def _insert_job(
    conn, *,
    job_id: str,
    image_id: str,
    job_type: str = "image_generation",
    status: str = "awaiting_validation",
    config: str | None = None,
    result: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at,
                         entity_type, entity_id, result)
        VALUES (?, ?, ?, ?, ?, '2026-05-09', 'image', ?, ?)
        """,
        [job_id, job_type, status, image_id, config or "{}", image_id, result],
    )


def _insert_image_output(
    conn, *,
    output_id: str,
    image_id: str,
    job_id: str | None = None,
    file_path: str = "outputs/test.png",
    quality_score: float | None = 0.85,
    model_name: str = "z-image-turbo",
) -> None:
    conn.execute(
        """
        INSERT INTO image_output (id, image_id, job_id, file_path, file_format,
                                  width, height, quality_score, model_name,
                                  created_at)
        VALUES (?, ?, ?, ?, 'png', 1024, 1024, ?, ?, '2026-05-09')
        """,
        [output_id, image_id, job_id, file_path, quality_score, model_name],
    )


# ── GET /api/review/queue ────────────────────────────────────────────────────


def test_queue_empty(app_with_test_db):
    """DB vide → count=0, items=[]."""
    r = _client(app_with_test_db).get("/api/review/queue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 0
    assert body["items"] == []


def test_queue_basic_join(app_with_test_db, test_conn):
    """Insert image+job+image_output sans annotation → l'item apparaît,
    annotation=None, identifiants polymorphes corrects."""
    _insert_image(test_conn, image_id="img_1", status="awaiting_validation")
    _insert_job(test_conn, job_id="job_1", image_id="img_1")
    _insert_image_output(
        test_conn, output_id="out_1", image_id="img_1", job_id="job_1",
        file_path="outputs/lion.png",
    )
    test_conn.session.commit()

    r = _client(app_with_test_db).get("/api/review/queue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["target_type"] == "image_output"
    assert item["target_id"] == "out_1"
    assert item["image_id"] == "img_1"
    assert item["job_id"] == "job_1"
    assert item["image_status"] == "awaiting_validation"
    assert item["job_status"] == "awaiting_validation"
    assert item["filename"] == "lion.png"
    assert item["image_url"] == "/api/review/file?image_output_id=out_1"
    assert item["prompt"] == "a lion in savanna"
    assert item["negative"] == "no colors"
    assert item["annotation"] is None


def test_queue_with_annotation_joined(app_with_test_db, test_conn):
    """Si une annotation existe pour image_output, elle est jointe et exposée."""
    _insert_image(test_conn, image_id="img_2", status="awaiting_validation")
    _insert_job(test_conn, job_id="job_2", image_id="img_2")
    _insert_image_output(
        test_conn, output_id="out_2", image_id="img_2", job_id="job_2",
    )
    test_conn.session.commit()

    # Save annotation via POST /api/annotation
    client = _client(app_with_test_db)
    r = client.post("/api/annotation", json={
        "target_type": "image_output",
        "target_id": "out_2",
        "score": 4,
        "image_tags": ["image_compo_bonne", "image_anatomie_pb"],
        "prompt_tags": ["prompt_complexe"],
        "custom_tags": ["alpha"],
        "flags": {"pattern": True, "pattern_note": "sym", "sample": False, "publishable": True},
    })
    assert r.status_code == 200, r.text

    # Now queue should include the annotation joined
    r2 = client.get("/api/review/queue")
    assert r2.status_code == 200
    item = r2.json()["items"][0]
    a = item["annotation"]
    assert a is not None
    assert a["score"] == 4
    assert a["image_tags"] == ["image_compo_bonne", "image_anatomie_pb"]
    assert a["prompt_tags"] == ["prompt_complexe"]
    assert a["custom_tags"] == ["alpha"]
    assert a["flags"]["pattern"] is True
    assert a["flags"]["pattern_note"] == "sym"
    assert a["flags"]["publishable"] is True


def test_queue_filter_by_status(app_with_test_db, test_conn):
    """Le filtre ``status`` matche ``image.status``."""
    _insert_image(test_conn, image_id="img_a", status="awaiting_validation")
    _insert_image(test_conn, image_id="img_b", status="generated")
    _insert_image_output(test_conn, output_id="out_a", image_id="img_a")
    _insert_image_output(test_conn, output_id="out_b", image_id="img_b")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r1 = client.get("/api/review/queue?status=awaiting_validation")
    assert r1.status_code == 200
    ids1 = {item["target_id"] for item in r1.json()["items"]}
    assert ids1 == {"out_a"}

    r2 = client.get("/api/review/queue?status=generated")
    assert r2.status_code == 200
    ids2 = {item["target_id"] for item in r2.json()["items"]}
    assert ids2 == {"out_b"}

    r3 = client.get("/api/review/queue?status=all")
    assert r3.status_code == 200
    ids3 = {item["target_id"] for item in r3.json()["items"]}
    assert ids3 == {"out_a", "out_b"}


def test_queue_filter_unknown_status_400(app_with_test_db):
    """``status`` hors whitelist → 400."""
    r = _client(app_with_test_db).get("/api/review/queue?status=bogus")
    assert r.status_code == 400


def test_queue_filter_workflow_class(app_with_test_db, test_conn):
    """Le filtre ``workflow_class`` fait un LIKE best-effort sur job.config."""
    _insert_image(test_conn, image_id="img_w1", status="awaiting_validation")
    _insert_image(test_conn, image_id="img_w2", status="awaiting_validation")
    _insert_job(
        test_conn, job_id="job_w1", image_id="img_w1",
        config=json.dumps({"workflow_class": "Solo animal"}),
    )
    _insert_job(
        test_conn, job_id="job_w2", image_id="img_w2",
        config=json.dumps({"workflow_class": "Solo objet"}),
    )
    _insert_image_output(test_conn, output_id="out_w1", image_id="img_w1", job_id="job_w1")
    _insert_image_output(test_conn, output_id="out_w2", image_id="img_w2", job_id="job_w2")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r = client.get("/api/review/queue?workflow_class=Solo+animal")
    assert r.status_code == 200
    ids = {item["target_id"] for item in r.json()["items"]}
    assert ids == {"out_w1"}


# ── GET /api/review/file ─────────────────────────────────────────────────────


def test_file_404_on_unknown_id(app_with_test_db):
    """L'``image_output_id`` doit exister en DB."""
    r = _client(app_with_test_db).get("/api/review/file?image_output_id=does_not_exist")
    assert r.status_code == 404


def test_file_404_on_empty_path(app_with_test_db, test_conn):
    """Un image_output sans file_path → 404."""
    _insert_image(test_conn, image_id="img_np", status="generating")
    _insert_image_output(test_conn, output_id="out_np", image_id="img_np", file_path="")
    test_conn.session.commit()

    r = _client(app_with_test_db).get("/api/review/file?image_output_id=out_np")
    assert r.status_code == 404


def test_file_200_on_valid_id(app_with_test_db, test_conn, tmp_path, monkeypatch):
    """Fichier réel sous DATA_DIR → 200 + bytes PNG."""
    # On patche DATA_DIR vers tmp_path et on y crée un fichier sous outputs/.
    import api.routes.review as review_mod
    monkeypatch.setattr(review_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(review_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    png = outputs / "ok.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    _insert_image(test_conn, image_id="img_ok", status="awaiting_validation")
    _insert_image_output(
        test_conn, output_id="out_ok", image_id="img_ok",
        file_path="outputs/ok.png",
    )
    test_conn.session.commit()

    r = _client(app_with_test_db).get("/api/review/file?image_output_id=out_ok")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")


def test_file_refuses_path_outside_data_dir(app_with_test_db, test_conn, tmp_path, monkeypatch):
    """Un file_path qui résoudrait hors DATA_DIR doit être refusé (404)."""
    import api.routes.review as review_mod
    # Même DATA_DIR isolé.
    monkeypatch.setattr(review_mod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(review_mod, "OUTPUTS_DIR", tmp_path / "data" / "outputs")
    (tmp_path / "data").mkdir()

    # On crée un fichier en DEHORS de data/ et on tente d'y accéder via un
    # chemin absolu (l'attaquant pourrait avoir injecté cela en DB).
    outsider = tmp_path / "outside.png"
    outsider.write_bytes(b"\x89PNG")
    _insert_image(test_conn, image_id="img_evil", status="awaiting_validation")
    _insert_image_output(
        test_conn, output_id="out_evil", image_id="img_evil",
        file_path=str(outsider),
    )
    test_conn.session.commit()

    r = _client(app_with_test_db).get("/api/review/file?image_output_id=out_evil")
    assert r.status_code == 404


# ── POST /api/annotation ─────────────────────────────────────────────────────


def test_annotate_creates_new(app_with_test_db, test_conn):
    """Premier upsert : insert + retour avec updated_at."""
    _insert_image(test_conn, image_id="img_n", status="awaiting_validation")
    _insert_image_output(test_conn, output_id="out_n", image_id="img_n")
    test_conn.session.commit()

    r = _client(app_with_test_db).post("/api/annotation", json={
        "target_type": "image_output",
        "target_id": "out_n",
        "score": 5,
        "image_tags": ["image_creative"],
        "prompt_tags": ["prompt_creatif"],
        "custom_tags": [" foo ", "foo", "bar"],  # strip + dédup
        "flags": {"pattern": False, "sample": True, "publishable": False},
    })
    assert r.status_code == 200, r.text
    a = r.json()["annotation"]
    assert a["score"] == 5
    assert a["image_tags"] == ["image_creative"]
    assert a["prompt_tags"] == ["prompt_creatif"]
    assert a["custom_tags"] == ["foo", "bar"]
    assert a["flags"]["sample"] is True
    assert a["flags"]["pattern_note"] == ""
    assert a["updated_at"] is not None

    # Vérification base : exactement 1 row
    rows = test_conn.execute(
        "SELECT COUNT(*) FROM annotation WHERE target_type=? AND target_id=?",
        ["image_output", "out_n"],
    ).fetchone()
    assert rows[0] == 1


def test_annotate_upsert_existing_no_duplicate(app_with_test_db, test_conn):
    """Deuxième POST avec mêmes ``(target_type, target_id)`` → UPDATE
    (pas d'INSERT, pas de violation UNIQUE)."""
    _insert_image(test_conn, image_id="img_u", status="awaiting_validation")
    _insert_image_output(test_conn, output_id="out_u", image_id="img_u")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r1 = client.post("/api/annotation", json={
        "target_type": "image_output", "target_id": "out_u", "score": 3,
        "image_tags": [], "prompt_tags": [], "custom_tags": [],
    })
    assert r1.status_code == 200

    r2 = client.post("/api/annotation", json={
        "target_type": "image_output", "target_id": "out_u", "score": 6,
        "image_tags": ["image_compo_bonne"], "prompt_tags": [], "custom_tags": ["x"],
    })
    assert r2.status_code == 200, r2.text
    a = r2.json()["annotation"]
    assert a["score"] == 6
    assert a["image_tags"] == ["image_compo_bonne"]
    assert a["custom_tags"] == ["x"]

    rows = test_conn.execute(
        "SELECT COUNT(*) FROM annotation WHERE target_type=? AND target_id=?",
        ["image_output", "out_u"],
    ).fetchone()
    assert rows[0] == 1, "upsert ne doit pas créer de doublon"


def test_annotate_score_out_of_range_400(app_with_test_db, test_conn):
    _insert_image(test_conn, image_id="img_s", status="awaiting_validation")
    _insert_image_output(test_conn, output_id="out_s", image_id="img_s")
    test_conn.session.commit()

    for bad in (0, 7, -1, 100):
        r = _client(app_with_test_db).post("/api/annotation", json={
            "target_type": "image_output", "target_id": "out_s", "score": bad,
        })
        assert r.status_code == 400, f"score={bad} should be rejected"


def test_annotate_score_null_accepted(app_with_test_db, test_conn):
    """``score: null`` est valide (reset)."""
    _insert_image(test_conn, image_id="img_null", status="awaiting_validation")
    _insert_image_output(test_conn, output_id="out_null", image_id="img_null")
    test_conn.session.commit()

    r = _client(app_with_test_db).post("/api/annotation", json={
        "target_type": "image_output", "target_id": "out_null", "score": None,
    })
    assert r.status_code == 200
    assert r.json()["annotation"]["score"] is None


def test_annotate_unknown_image_tag_400(app_with_test_db, test_conn):
    _insert_image(test_conn, image_id="img_it", status="awaiting_validation")
    _insert_image_output(test_conn, output_id="out_it", image_id="img_it")
    test_conn.session.commit()

    r = _client(app_with_test_db).post("/api/annotation", json={
        "target_type": "image_output", "target_id": "out_it",
        "image_tags": ["image_compo_bonne", "image_unknown_xxx"],
    })
    assert r.status_code == 400
    assert "image_unknown_xxx" in r.json()["detail"]


def test_annotate_unknown_prompt_tag_400(app_with_test_db, test_conn):
    _insert_image(test_conn, image_id="img_pt", status="awaiting_validation")
    _insert_image_output(test_conn, output_id="out_pt", image_id="img_pt")
    test_conn.session.commit()

    r = _client(app_with_test_db).post("/api/annotation", json={
        "target_type": "image_output", "target_id": "out_pt",
        "prompt_tags": ["prompt_creatif", "totally_made_up"],
    })
    assert r.status_code == 400
    assert "totally_made_up" in r.json()["detail"]


def test_annotate_unknown_target_type_400(app_with_test_db):
    """Toute valeur hors whitelist → 400 (avant même tout lookup DB)."""
    r = _client(app_with_test_db).post("/api/annotation", json={
        "target_type": "image",  # whitelist = {"image_output"} initialement
        "target_id": "anything",
    })
    assert r.status_code == 400
    assert "target_type" in r.json()["detail"]


def test_annotate_unknown_target_id_404(app_with_test_db):
    """Avec un target_type valide mais un target_id absent en DB → 404."""
    r = _client(app_with_test_db).post("/api/annotation", json={
        "target_type": "image_output", "target_id": "ghost_id_42",
    })
    assert r.status_code == 404


def test_annotate_pattern_note_cleared_when_pattern_off(app_with_test_db, test_conn):
    """``pattern_note`` doit être vidé si ``pattern=False``."""
    _insert_image(test_conn, image_id="img_pn", status="awaiting_validation")
    _insert_image_output(test_conn, output_id="out_pn", image_id="img_pn")
    test_conn.session.commit()

    r = _client(app_with_test_db).post("/api/annotation", json={
        "target_type": "image_output", "target_id": "out_pn",
        "flags": {"pattern": False, "pattern_note": "should be cleared"},
    })
    assert r.status_code == 200
    assert r.json()["annotation"]["flags"]["pattern_note"] == ""


# ── Cohérence des vocabulaires partagés ──────────────────────────────────────


def test_vocabularies_match_brief_count():
    """Les vocabulaires partagés doivent matcher le brief (18 image, 8 prompt).

    Test miroir de ``test_benchmark_routes.test_vocabularies_match_brief_count``
    pour garantir la cohérence single-source-of-truth après le refactor.
    """
    assert len(IMAGE_TAGS_VOCAB) == 18
    assert len(PROMPT_TAGS_VOCAB) == 8


def test_vocab_module_is_single_source_of_truth():
    """Le module ``annotation_vocab`` est bien la source partagée par
    ``benchmark.py`` ET ``review.py`` (identité d'objet, pas seulement
    valeurs égales)."""
    from api.routes import benchmark as bm_mod
    from api.routes import review as rv_mod
    from api import annotation_vocab as av

    assert bm_mod.IMAGE_TAGS_VOCAB is av.IMAGE_TAGS_VOCAB
    assert bm_mod.PROMPT_TAGS_VOCAB is av.PROMPT_TAGS_VOCAB
    assert rv_mod.IMAGE_TAGS_VOCAB is av.IMAGE_TAGS_VOCAB
    assert rv_mod.PROMPT_TAGS_VOCAB is av.PROMPT_TAGS_VOCAB
