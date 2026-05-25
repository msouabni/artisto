"""Tests pour le registry ``data/destination_sites.json``."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "data" / "destination_sites.json"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_load_sites_registry_ok(registry):
    assert "version" in registry
    assert "sites" in registry
    assert isinstance(registry["sites"], list)
    assert len(registry["sites"]) >= 1


def test_get_site_unknown_raises():
    from alwanbooks_pipeline import get_site

    with pytest.raises(ValueError, match="not found"):
        get_site("nonexistent_site_xyz")


def test_get_site_disabled_raises(tmp_path):
    from alwanbooks_pipeline import (
        DESTINATION_SITES_PATH,
        _load_destination_sites,
        get_site,
    )
    import alwanbooks_pipeline as mod

    original = mod.DESTINATION_SITES_PATH
    disabled_registry = {
        "version": 1,
        "sites": [{"id": "disabled_test", "enabled": False}],
    }
    tmp_file = tmp_path / "sites.json"
    tmp_file.write_text(json.dumps(disabled_registry), encoding="utf-8")
    mod.DESTINATION_SITES_PATH = tmp_file
    try:
        with pytest.raises(ValueError, match="disabled"):
            get_site("disabled_test")
    finally:
        mod.DESTINATION_SITES_PATH = original


def test_sites_registry_schema_valid(registry):
    required_site_keys = {
        "id", "name", "repo_url", "default_branch",
        "clone_path", "enabled", "structure", "bot",
    }
    for site in registry["sites"]:
        missing = required_site_keys - set(site.keys())
        assert not missing, f"site {site.get('id', '?')!r} missing keys: {missing}"
        assert isinstance(site["id"], str)
        assert isinstance(site["enabled"], bool)
        struct = site["structure"]
        assert "posts_dir" in struct
        assert "categories_dir" in struct
        assert "themes_dir" in struct
        assert "locales" in struct
        assert set(struct["locales"]) == {"ar", "fr", "en"}
        bot = site["bot"]
        assert "name" in bot
        assert "email" in bot
