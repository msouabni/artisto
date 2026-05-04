"""Tests du service QC technique sur PNG."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, "src")

from services.image_qc_technical import build_technical_image_qc_v1


def test_qc_missing_file():
    r = build_technical_image_qc_v1(Path("/nonexistent/path/no.png"))
    assert r["status"] == "fail"
    assert "image_file_missing" in r["flags"]


def test_qc_white_only_near_empty(tmp_path: Path):
    p = tmp_path / "white.png"
    Image.new("RGB", (128, 128), (255, 255, 255)).save(p)
    r = build_technical_image_qc_v1(p)
    ids = {c["id"] for c in r["checks"]}
    assert "empty_or_near_empty" in ids
    assert "ink_density" in ids
    assert r["status"] in ("fail", "warning")
    assert r["technical_score"] < 80


def test_qc_strong_color_fails(tmp_path: Path):
    p = tmp_path / "red.png"
    Image.new("RGB", (128, 128), (220, 30, 30)).save(p)
    r = build_technical_image_qc_v1(p)
    color_chk = next(c for c in r["checks"] if c["id"] == "color_presence")
    assert color_chk["severity"] == "fail"
    assert r["status"] == "fail"


def test_qc_reasonable_line_art_passes_or_warns(tmp_path: Path):
    p = tmp_path / "lines.png"
    im = Image.new("RGB", (256, 256), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for i in range(24, 232, 6):
        d.line([(i, 48), (i, 208)], fill=(0, 0, 0), width=2)
    d.rectangle([48, 48, 208, 208], outline=(0, 0, 0), width=3)
    im.save(p)
    r = build_technical_image_qc_v1(p)
    assert r["schema_version"] == 1
    assert r["relevance_score"] == 0
    assert r["safety_score"] == 0
    assert r["status"] in ("pass", "warning")
    assert r["technical_score"] >= 50
    assert "metrics" in r and "ink_ratio" in r["metrics"]
