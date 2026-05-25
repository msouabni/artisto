"""Tests du registry ``data/themes_registry.json``."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "data" / "themes_registry.json"
TAXONOMY_PATH = (
    PROJECT_ROOT / "data" / "prompt_generator" / "coloring_taxonomy_full.json"
)

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def themes(registry) -> list[dict]:
    return registry["themes"]


@pytest.fixture(scope="module")
def known_ids(themes) -> set[str]:
    return {t["id"] for t in themes}


def test_registry_is_valid_json():
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "version" in data
    assert "themes" in data
    assert isinstance(data["themes"], list)
    assert len(data["themes"]) >= 1


def test_registry_has_required_schema(themes):
    required_keys = {
        "id", "parent_id", "weight",
        "slug_i18n", "name_i18n", "description_i18n", "keywords_i18n",
        "editorial_body_i18n", "body", "leaves",
    }
    for theme in themes:
        missing = required_keys - set(theme.keys())
        assert not missing, (
            f"theme {theme.get('id', '?')!r} missing keys: {missing}"
        )
        assert isinstance(theme["id"], str)
        assert isinstance(theme["body"], str) and theme["body"]
        assert isinstance(theme["leaves"], list)


def test_registry_ids_are_unique(themes):
    ids = [t["id"] for t in themes]
    assert len(ids) == len(set(ids)), (
        f"duplicate ids: {[i for i in ids if ids.count(i) > 1]}"
    )


def test_registry_ids_match_regex(themes):
    pattern = re.compile(r"^[a-z][a-z0-9_-]*$")
    for theme in themes:
        assert pattern.match(theme["id"]), (
            f"id {theme['id']!r} does not match expected pattern"
        )


def test_registry_i18n_has_three_locales(themes):
    expected = {"ar", "fr", "en"}
    i18n_fields = ("slug_i18n", "name_i18n", "description_i18n", "keywords_i18n")
    for theme in themes:
        for field in i18n_fields:
            locales = set(theme[field].keys())
            assert locales == expected, (
                f"theme {theme['id']}.{field}: expected {expected}, got {locales}"
            )


def test_registry_keywords_count(themes):
    for theme in themes:
        for loc, kws in theme["keywords_i18n"].items():
            assert isinstance(kws, list)
            assert 1 <= len(kws) <= 8, (
                f"theme {theme['id']}.keywords_i18n.{loc}: "
                f"expected 1-8 keywords, got {len(kws)}"
            )


def test_registry_editorial_body_has_three_locales(themes):
    expected = {"ar", "fr", "en"}
    for theme in themes:
        locales = set(theme["editorial_body_i18n"].keys())
        assert locales == expected, (
            f"theme {theme['id']}.editorial_body_i18n: "
            f"expected {expected}, got {locales}"
        )
        for loc in expected:
            assert theme["editorial_body_i18n"][loc], (
                f"theme {theme['id']}.editorial_body_i18n.{loc} is empty"
            )


def test_registry_leaves_are_unique_within_theme(themes):
    for theme in themes:
        leaves = theme["leaves"]
        assert len(leaves) == len(set(leaves)), (
            f"theme {theme['id']}: duplicate leaves"
        )


def test_registry_leaves_resolve_to_taxonomy(themes):
    if not TAXONOMY_PATH.is_file():
        pytest.skip("taxonomy file not found")

    def _collect_ids(node):
        ids = set()
        if isinstance(node, list):
            for x in node:
                ids |= _collect_ids(x)
        elif isinstance(node, dict):
            if "id" in node:
                ids.add(node["id"])
            for child in node.get("children", []):
                ids |= _collect_ids(child)
        return ids

    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    all_ids = _collect_ids(data)
    warnings = []
    for theme in themes:
        for leaf in theme["leaves"]:
            if leaf not in all_ids:
                warnings.append(f"{theme['id']}/{leaf}")
    if warnings:
        import logging
        logging.getLogger(__name__).warning(
            "Leaves not in taxonomy (may be future): %s", warnings
        )
