"""Tests du registre des variantes pipeline (C1.1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from services.pipeline_variants import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    Variant,
    _clear_cache,
    get_active_variants,
    get_variant,
    load_variants,
    validate_registry,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    _clear_cache()
    yield
    _clear_cache()


def _base_registry() -> dict:
    return {
        "version": 1,
        "default_active": ["pastel_chromakey"],
        "variants": {
            "pastel_chromakey": {
                "prompt_style": "pastel",
                "force_chromakey": True,
                "chromakey_rgb": [0, 177, 64],
                "extract_preset": "floodfill_chromakey_v1",
                "output_kind": "online_coloring",
                "label": "Pastel chromakey",
            },
            "lineart": {
                "prompt_style": "lineart",
                "force_chromakey": False,
                "chromakey_rgb": None,
                "extract_preset": None,
                "output_kind": "print",
                "label": "Lineart",
            },
        },
        "per_category_override": {},
    }


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "pipeline_variants.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_default_registry():
    variants = load_variants()
    assert set(variants.keys()) == {
        "pastel_chromakey",
        "flat_cartoon_chromakey",
        "lineart",
    }
    pc = variants["pastel_chromakey"]
    assert isinstance(pc, Variant)
    assert pc.prompt_style == "pastel"
    assert pc.force_chromakey is True
    assert pc.chromakey_rgb == (0, 177, 64)
    assert pc.extract_preset == "floodfill_chromakey_v1"
    assert pc.output_kind == "online_coloring"


def test_get_active_variants_no_override():
    active = get_active_variants()
    assert len(active) == 1
    assert active[0].name == "pastel_chromakey"


def test_get_active_variants_with_category_override(tmp_path):
    data = _base_registry()
    data["per_category_override"] = {
        "letters_arabic": ["pastel_chromakey", "lineart"],
    }
    p = _write(tmp_path, data)

    active_default = get_active_variants(category_id="other", path=p)
    assert [v.name for v in active_default] == ["pastel_chromakey"]

    active_override = get_active_variants(
        category_id="letters_arabic", path=p
    )
    assert [v.name for v in active_override] == ["pastel_chromakey", "lineart"]


def test_validate_invalid_prompt_style(tmp_path):
    data = _base_registry()
    data["variants"]["pastel_chromakey"]["prompt_style"] = "invalid"
    errors = validate_registry(data)
    assert any("prompt_style" in e and "invalid" in e for e in errors)


def test_validate_force_chromakey_no_rgb(tmp_path):
    data = _base_registry()
    data["variants"]["pastel_chromakey"]["force_chromakey"] = True
    data["variants"]["pastel_chromakey"]["chromakey_rgb"] = None
    errors = validate_registry(data)
    assert any("force_chromakey=true" in e and "chromakey_rgb" in e for e in errors)


def test_validate_extract_preset_inexistant(tmp_path):
    data = _base_registry()
    data["variants"]["pastel_chromakey"]["extract_preset"] = "bogus_preset"
    errors = validate_registry(data)
    assert any(
        "extract_preset" in e and "bogus_preset" in e for e in errors
    )


def test_get_variant_existant():
    v = get_variant("pastel_chromakey")
    assert v is not None
    assert v.name == "pastel_chromakey"
    assert v.prompt_style == "pastel"


def test_get_variant_inconnu():
    assert get_variant("xxx") is None


def test_validate_default_active_unknown_variant():
    data = _base_registry()
    data["default_active"] = ["yyy"]
    errors = validate_registry(data)
    assert any("default_active" in e and "yyy" in e for e in errors)


def test_validate_registry_ok_on_default():
    """Le registre par defaut doit toujours rester valide."""
    raw = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert validate_registry(raw) == []


def test_load_invalid_registry_raises(tmp_path):
    data = _base_registry()
    data["version"] = 99
    p = _write(tmp_path, data)
    with pytest.raises(ValueError, match="version"):
        load_variants(path=p)
