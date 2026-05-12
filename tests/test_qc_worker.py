"""Tests du worker QC déterministe ``image_qc_auto`` (brief 2026-05-10).

Couvre :
- les 5 règles déterministes (pures, pas de DB)
- la persistance ``qc_tags`` sur ``image_output``
- le pipeline complet ``run_qc_for_output`` (lecture + persistance)
- les 2 endpoints API ``POST /api/qc/run/{id}`` et ``GET /api/qc/tags/{id}``
- le trigger automatique du worker ``image_generation`` (création
  d'un job ``image_qc_auto`` en fin de ``save_result``)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import workers.image_worker as image_worker_mod
from workers.image_worker import ImageWorker
from workers.qc_worker import (
    QC_COLOR_RESIDUAL_THRESHOLD,
    QC_LOW_CONTRAST_STD_THRESHOLD,
    QC_LOW_COMPLEXITY_EDGE_THRESHOLD,
    QC_OVERSATURATED_BLACK_RATIO_THRESHOLD,
    QCWorker,
    compute_qc_metrics,
    evaluate_qc_tags,
    is_intrinsic_color_leaf,
    run_qc_for_output,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_lineart_png(path: Path, size: int = 256) -> None:
    """Génère un PNG line-art monochrome bien contrasté et complexe."""
    im = Image.new("RGB", (size, size), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    # Beaucoup d'arêtes : grille verticale + diagonales
    for i in range(20, size - 20, 8):
        dr.line([(i, 20), (i, size - 20)], fill=(0, 0, 0), width=2)
    for i in range(20, size - 20, 12):
        dr.line([(20, i), (size - 20, i)], fill=(0, 0, 0), width=2)
    im.save(path)


def _make_colored_png(path: Path, size: int = 256) -> None:
    """PNG fortement coloré (ratio chrominance >> 0.001)."""
    im = Image.new("RGB", (size, size), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    dr.rectangle([(20, 20), (size - 20, size - 20)], fill=(255, 50, 50))
    for i in range(40, size - 40, 8):
        dr.line([(i, 40), (i, size - 40)], fill=(0, 100, 0), width=2)
    im.save(path)


def _make_lowcontrast_png(path: Path, size: int = 256) -> None:
    """Image très grise/plate (std < 30)."""
    arr = np.full((size, size, 3), 128, dtype=np.uint8)
    # Un peu de bruit léger pour ne pas avoir std=0 exact
    rng = np.random.default_rng(0)
    arr = arr + rng.integers(-10, 10, size=arr.shape, dtype=np.int8).astype(np.int16)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    Image.fromarray(arr, "RGB").save(path)


def _make_oversaturated_png(path: Path, size: int = 256) -> None:
    """Image quasi-noire (>50% pixels intensité < 30)."""
    arr = np.full((size, size, 3), 5, dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path)


def _make_lowcomplexity_png(path: Path, size: int = 256) -> None:
    """PNG quasi-vide (edges < 500)."""
    im = Image.new("RGB", (size, size), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    # Une seule petite ligne fine → très peu d'arêtes
    dr.line([(120, 120), (140, 140)], fill=(0, 0, 0), width=1)
    im.save(path)


# ── Tests règles pures (pas de DB) ────────────────────────────────────────

def test_evaluate_qc_tags_lineart_clean(tmp_path: Path):
    p = tmp_path / "lineart.png"
    _make_lineart_png(p)
    metrics = compute_qc_metrics(p)
    assert metrics["readable"] is True
    tags = evaluate_qc_tags(metrics, leaf_id="cat")
    assert "qc_ok" in tags
    assert "qc_color_residual" not in tags
    assert "qc_low_contrast" not in tags
    assert "qc_low_complexity" not in tags
    assert "qc_oversaturated" not in tags


def test_evaluate_qc_tags_color_residual_fires(tmp_path: Path):
    p = tmp_path / "colored.png"
    _make_colored_png(p)
    metrics = compute_qc_metrics(p)
    assert metrics["color_ratio"] > QC_COLOR_RESIDUAL_THRESHOLD
    tags = evaluate_qc_tags(metrics, leaf_id="cat")
    assert "qc_color_residual" in tags
    assert "qc_ok" not in tags


def test_evaluate_qc_tags_low_contrast_fires(tmp_path: Path):
    p = tmp_path / "low_contrast.png"
    _make_lowcontrast_png(p)
    metrics = compute_qc_metrics(p)
    assert metrics["intensity_std"] < QC_LOW_CONTRAST_STD_THRESHOLD
    tags = evaluate_qc_tags(metrics, leaf_id="cat")
    assert "qc_low_contrast" in tags
    assert "qc_ok" not in tags


def test_evaluate_qc_tags_low_complexity_fires(tmp_path: Path):
    p = tmp_path / "empty.png"
    _make_lowcomplexity_png(p)
    metrics = compute_qc_metrics(p)
    assert metrics["edge_count"] < QC_LOW_COMPLEXITY_EDGE_THRESHOLD
    tags = evaluate_qc_tags(metrics, leaf_id="cat")
    assert "qc_low_complexity" in tags


def test_evaluate_qc_tags_oversaturated_fires(tmp_path: Path):
    p = tmp_path / "black.png"
    _make_oversaturated_png(p)
    metrics = compute_qc_metrics(p)
    assert metrics["black_ratio"] > QC_OVERSATURATED_BLACK_RATIO_THRESHOLD
    tags = evaluate_qc_tags(metrics, leaf_id="cat")
    assert "qc_oversaturated" in tags


def test_evaluate_qc_tags_intrinsic_color_does_not_block_qc_ok(tmp_path: Path):
    """Le tag qc_color_intrinsic est informatif, n'empêche pas qc_ok."""
    p = tmp_path / "lineart.png"
    _make_lineart_png(p)
    metrics = compute_qc_metrics(p)
    tags = evaluate_qc_tags(metrics, leaf_id="rainbow_arc")
    assert "qc_color_intrinsic" in tags
    assert "qc_ok" in tags


def test_is_intrinsic_color_leaf_null_safe():
    assert is_intrinsic_color_leaf(None) is False
    assert is_intrinsic_color_leaf("") is False
    assert is_intrinsic_color_leaf("   ") is False
    assert is_intrinsic_color_leaf("rainbow") is True
    assert is_intrinsic_color_leaf("rainbow_unicorn") is True
    assert is_intrinsic_color_leaf("CRYSTAL_skull") is True
    assert is_intrinsic_color_leaf("aurora_borealis") is True
    assert is_intrinsic_color_leaf("regular_cat") is False


def test_evaluate_qc_tags_unreadable():
    tags = evaluate_qc_tags({"readable": False, "error": "x"}, leaf_id="cat")
    assert tags == ["qc_unreadable"]


def test_compute_qc_metrics_missing_file(tmp_path: Path):
    metrics = compute_qc_metrics(tmp_path / "does_not_exist.png")
    assert metrics["readable"] is False


# ── Tests intégration DB (SQLite in-memory) ───────────────────────────────

def _seed_image_output(test_conn, image_output_id: str, file_path: str, leaf_id: str | None) -> None:
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, origin_term_id, file_path,
                           created_at, updated_at)
        VALUES (?, ?, 'generated', 'p', ?, '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [f"img_{image_output_id}", f"img_{image_output_id}", leaf_id],
    )
    test_conn.execute(
        """
        INSERT INTO image_output (id, image_id, file_path, created_at)
        VALUES (?, ?, ?, '2026-01-01T00:00:00Z')
        """,
        [image_output_id, f"img_{image_output_id}", file_path],
    )
    test_conn.session.commit()


def test_run_qc_for_output_persists_qc_tags(test_conn, tmp_path: Path):
    p = tmp_path / "out_clean.png"
    _make_lineart_png(p)
    _seed_image_output(test_conn, "out_clean", "outputs/out_clean.png", leaf_id="cat")

    res = run_qc_for_output(test_conn, "out_clean", outputs_root=tmp_path)
    assert "qc_ok" in res["tags"]

    row = test_conn.execute(
        "SELECT qc_tags FROM image_output WHERE id = ?", ["out_clean"]
    ).fetchone()
    raw = row[0]
    # SQLite stocke notre JSON-string ; loads doit rendre une liste
    parsed = raw if isinstance(raw, list) else json.loads(raw)
    assert "qc_ok" in parsed


def test_run_qc_for_output_intrinsic_leaf(test_conn, tmp_path: Path):
    p = tmp_path / "out_rainbow.png"
    _make_lineart_png(p)
    _seed_image_output(test_conn, "out_rainbow", "outputs/out_rainbow.png", leaf_id="rainbow_unicorn")

    res = run_qc_for_output(test_conn, "out_rainbow", outputs_root=tmp_path)
    assert "qc_color_intrinsic" in res["tags"]


def test_run_qc_for_output_missing_image_output(test_conn, tmp_path: Path):
    res = run_qc_for_output(test_conn, "does_not_exist", outputs_root=tmp_path)
    assert res["tags"] == ["qc_unreadable"]


# ── Tests endpoints API ───────────────────────────────────────────────────

def test_api_post_qc_run(app_with_test_db, test_conn, tmp_path, monkeypatch):
    p = tmp_path / "out_api.png"
    _make_lineart_png(p)
    _seed_image_output(test_conn, "out_api", "outputs/out_api.png", leaf_id="cat")

    # Pointe OUTPUTS_ROOT vers tmp_path
    import api.routes.qc as qc_mod
    monkeypatch.setattr(qc_mod, "OUTPUTS_ROOT", tmp_path)

    client = TestClient(app_with_test_db)
    resp = client.post("/api/qc/run/out_api")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image_output_id"] == "out_api"
    assert "qc_ok" in body["tags"]


def test_api_post_qc_run_404(app_with_test_db):
    client = TestClient(app_with_test_db)
    resp = client.post("/api/qc/run/missing_id")
    assert resp.status_code == 404


def test_api_get_qc_tags_after_run(app_with_test_db, test_conn, tmp_path, monkeypatch):
    p = tmp_path / "out_get.png"
    _make_lineart_png(p)
    _seed_image_output(test_conn, "out_get", "outputs/out_get.png", leaf_id="cat")

    import api.routes.qc as qc_mod
    monkeypatch.setattr(qc_mod, "OUTPUTS_ROOT", tmp_path)

    client = TestClient(app_with_test_db)
    client.post("/api/qc/run/out_get").raise_for_status()
    resp = client.get("/api/qc/tags/out_get")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image_output_id"] == "out_get"
    assert "qc_ok" in body["tags"]


def test_api_get_qc_tags_empty_when_unset(app_with_test_db, test_conn, tmp_path):
    _seed_image_output(test_conn, "out_unset", "outputs/x.png", leaf_id=None)
    client = TestClient(app_with_test_db)
    resp = client.get("/api/qc/tags/out_unset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tags"] == []


def test_api_get_qc_tags_404(app_with_test_db):
    client = TestClient(app_with_test_db)
    resp = client.get("/api/qc/tags/missing")
    assert resp.status_code == 404


# ── Test trigger auto depuis ImageWorker.save_result ──────────────────────

def test_image_worker_enqueues_qc_job_after_save_result(test_conn, tmp_path, monkeypatch):
    """Un job image_qc_auto est créé en fin de save_result avec
    entity_id=<image_output_id>."""
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_qct', 'img_qct', 'generating', 'p', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, worker_id)
        VALUES ('job_qct', 'image_generation', 'running', 'img_qct', '{}',
                '2026-01-01T00:00:00Z', 'image', 'img_qct', 'w1')
        """
    )
    test_conn.session.commit()

    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    png = tmp_path / "img_qct_job_qct.png"
    _make_lineart_png(png)

    worker = ImageWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn
    try:
        worker.save_result(
            {"job_id": "job_qct"},
            {
                "entity_id": "img_qct",
                "rel_path": "outputs/img_qct_job_qct.png",
                "prompt": "p",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": "ext-1",
                "generation_params": {"width": 256, "height": 256, "steps": 4},
            },
        )
    finally:
        test_conn.close = original_close

    # Un job image_qc_auto pending doit avoir été créé pour out_job_qct
    rows = test_conn.execute(
        """
        SELECT id, type, status, entity_type, entity_id
        FROM job
        WHERE type = ? AND entity_id = ?
        """,
        ["image_qc_auto", "out_job_qct"],
    ).fetchall()
    assert len(rows) == 1
    qc_job = rows[0]
    assert qc_job[1] == "image_qc_auto"
    assert qc_job[2] == "pending"
    assert qc_job[3] == "image_output"
    assert qc_job[4] == "out_job_qct"


def test_image_worker_enqueue_idempotent(test_conn, tmp_path, monkeypatch):
    """Si un job image_qc_auto pending existe déjà, on ne le double pas."""
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_idemp', 'img_idemp', 'generating', 'p', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id)
        VALUES ('job_idemp', 'image_generation', 'running', 'img_idemp', '{}',
                '2026-01-01T00:00:00Z', 'image', 'img_idemp')
        """
    )
    # Pré-créer un job qc en pending
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id)
        VALUES ('qc_pre', 'image_qc_auto', 'pending', '{}',
                '2026-01-01T00:00:00Z', 'image_output', 'out_job_idemp')
        """
    )
    test_conn.session.commit()

    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    png = tmp_path / "img_idemp_job_idemp.png"
    _make_lineart_png(png)

    worker = ImageWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn
    try:
        worker.save_result(
            {"job_id": "job_idemp"},
            {
                "entity_id": "img_idemp",
                "rel_path": "outputs/img_idemp_job_idemp.png",
                "prompt": "p",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": None,
                "generation_params": {"width": 256, "height": 256},
            },
        )
    finally:
        test_conn.close = original_close

    # Un seul job qc auto pour out_job_idemp
    rows = test_conn.execute(
        "SELECT id FROM job WHERE type = ? AND entity_id = ?",
        ["image_qc_auto", "out_job_idemp"],
    ).fetchall()
    assert len(rows) == 1


def test_image_qc_auto_in_default_job_types():
    """L'inscription dans DEFAULT_JOB_TYPES garantit le seed automatique."""
    from api.db import DEFAULT_JOB_TYPES

    types = {t["type"] for t in DEFAULT_JOB_TYPES}
    assert "image_qc_auto" in types
    spec = next(t for t in DEFAULT_JOB_TYPES if t["type"] == "image_qc_auto")
    assert spec["max_concurrent"] == 1
    assert spec["category"] == "image"


def test_qc_worker_save_result_marks_job_completed(test_conn, tmp_path, monkeypatch):
    """``QCWorker.save_result`` met le job en ``completed`` (pas de revue)."""
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, started_at)
        VALUES ('jqc1', 'image_qc_auto', 'running', '{}',
                '2026-01-01T00:00:00Z', 'image_output', 'out_jqc1', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.session.commit()

    worker = QCWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn
    try:
        worker.save_result(
            {"job_id": "jqc1", "started_at": "2026-01-01T00:00:00Z"},
            {
                "image_output_id": "out_jqc1",
                "tags": ["qc_ok"],
                "metrics": {"readable": True, "color_ratio": 0.0},
            },
        )
    finally:
        test_conn.close = original_close

    row = test_conn.execute(
        "SELECT status, progress, result FROM job WHERE id = ?", ["jqc1"]
    ).fetchone()
    assert row[0] == "completed"
    assert row[1] == 100
    payload = json.loads(row[2])
    assert payload["tags"] == ["qc_ok"]
