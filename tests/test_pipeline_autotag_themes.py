"""Tests pour l'auto-tagging ``themeIds`` dans les posts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture
def themes_registry():
    return {
        "version": 1,
        "themes": [
            {
                "id": "noel",
                "leaves": ["santa_claus_with_sack", "reindeer_in_snow", "olaf_the_snowman"],
            },
            {
                "id": "saison-hiver",
                "leaves": ["reindeer_in_snow", "olaf_the_snowman", "polar_bear_on_ice"],
            },
        ],
    }


def test_post_gets_themeIds_from_registry(themes_registry):
    from alwanbooks_pipeline import compute_theme_ids

    result = compute_theme_ids("reindeer_in_snow", themes_registry)
    assert result == ["noel", "saison-hiver"]

    result = compute_theme_ids("santa_claus_with_sack", themes_registry)
    assert result == ["noel"]


def test_post_with_no_matching_theme_gets_empty_themeIds(themes_registry):
    from alwanbooks_pipeline import compute_theme_ids

    result = compute_theme_ids("lion_in_savanna", themes_registry)
    assert result == []


def test_regen_recomputes_themeIds_from_current_registry(themes_registry):
    from alwanbooks_pipeline import compute_theme_ids

    result1 = compute_theme_ids("olaf_the_snowman", themes_registry)
    assert result1 == ["noel", "saison-hiver"]

    modified = {
        "version": 1,
        "themes": [
            {"id": "noel", "leaves": ["santa_claus_with_sack"]},
            {"id": "saison-hiver", "leaves": ["olaf_the_snowman"]},
        ],
    }
    result2 = compute_theme_ids("olaf_the_snowman", modified)
    assert result2 == ["saison-hiver"]
