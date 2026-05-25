"""Tests pour ``sync_themes()`` — parallèle exact de ``test_sync_categories.py``."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture
def minimal_themes_registry() -> dict:
    return {
        "version": 1,
        "themes": [
            {
                "id": "test-theme",
                "parent_id": None,
                "weight": 10,
                "slug_i18n": {"ar": "test-ar", "fr": "test-fr", "en": "test-en"},
                "name_i18n": {"ar": "اختبار", "fr": "Test", "en": "Test"},
                "description_i18n": {
                    "ar": "وصف اختبار",
                    "fr": "Description test",
                    "en": "Test description",
                },
                "keywords_i18n": {
                    "ar": ["كلمة"],
                    "fr": ["mot"],
                    "en": ["word"],
                },
                "editorial_body_i18n": {
                    "ar": "فقرة أولى عربية.\n\nفقرة ثانية عربية.",
                    "fr": "Premier paragraphe français.\n\nDeuxième paragraphe.",
                    "en": "First English paragraph.\n\nSecond paragraph.",
                },
                "body": "Hub thématique : test.",
                "leaves": ["leaf_a", "leaf_b"],
                "scope_note": "INTERNE — ne doit jamais apparaître",
            },
            {
                "id": "test-theme-2",
                "parent_id": None,
                "weight": 20,
                "slug_i18n": {"ar": "t2-ar", "fr": "t2-fr", "en": "t2-en"},
                "name_i18n": {"ar": "اختبار2", "fr": "Test2", "en": "Test2"},
                "description_i18n": {
                    "ar": "وصف2", "fr": "Desc2", "en": "Desc2",
                },
                "keywords_i18n": {
                    "ar": ["ك"], "fr": ["m"], "en": ["w"],
                },
                "editorial_body_i18n": {
                    "ar": "نص عربي.", "fr": "Texte.", "en": "Text.",
                },
                "body": "Hub test 2.",
                "leaves": [],
                "scope_note": "INTERNE",
            },
        ],
    }


@pytest.fixture
def site_id():
    return "alwanbooks"


def _sync(tmp_path, registry, site_id, **kwargs):
    import alwanbooks_pipeline as mod
    original_bl = mod.THEMES_BLOCKLIST_PATH
    bl = tmp_path / "themes_bl.json"
    bl.write_text('{"version":1,"blocked_themes":{}}', encoding="utf-8")
    mod.THEMES_BLOCKLIST_PATH = bl
    try:
        return mod.sync_themes(
            tmp_path, site_id, registry=registry, **kwargs
        )
    finally:
        mod.THEMES_BLOCKLIST_PATH = original_bl


def test_sync_themes_writes_md_files(tmp_path, minimal_themes_registry, site_id):
    summary = _sync(tmp_path, minimal_themes_registry, site_id)
    assert summary.total == 2
    assert summary.created == 2
    themes_dir = tmp_path / "src" / "content" / "themes"
    assert (themes_dir / "test-theme.md").is_file()
    assert (themes_dir / "test-theme-2.md").is_file()


def test_sync_themes_md_content_structure(tmp_path, minimal_themes_registry, site_id):
    _sync(tmp_path, minimal_themes_registry, site_id)
    md = (tmp_path / "src" / "content" / "themes" / "test-theme.md").read_text(
        encoding="utf-8"
    )
    assert md.startswith("---\n")
    assert "\n---\n" in md
    assert "id: 'test-theme'" in md
    assert "weight: 10" in md
    assert "parent_id: null" in md
    assert "  ar: 'test-ar'" in md
    assert "اختبار" in md
    assert "editorial_body_i18n:" in md
    assert "  ar: |" in md
    assert "Hub thématique : test." in md


def test_sync_themes_skips_existing_md_addonly(tmp_path, minimal_themes_registry, site_id):
    s1 = _sync(tmp_path, minimal_themes_registry, site_id)
    assert s1.created == 2

    s2 = _sync(tmp_path, minimal_themes_registry, site_id)
    assert s2.created == 0
    assert s2.skipped_existing == 2


def test_sync_themes_regen_theme_overwrites(tmp_path, minimal_themes_registry, site_id):
    _sync(tmp_path, minimal_themes_registry, site_id)

    modified = json.loads(json.dumps(minimal_themes_registry))
    modified["themes"][0]["body"] = "Nouveau body modifié."

    s2 = _sync(
        tmp_path, modified, site_id,
        regen_themes=["test-theme"],
    )
    assert s2.overwritten == 1
    assert s2.skipped_existing == 1

    md = (tmp_path / "src" / "content" / "themes" / "test-theme.md").read_text(
        encoding="utf-8"
    )
    assert "Nouveau body modifié." in md


def test_sync_themes_editorial_body_preserves_paragraphs(
    tmp_path, minimal_themes_registry, site_id
):
    _sync(tmp_path, minimal_themes_registry, site_id)
    md = (tmp_path / "src" / "content" / "themes" / "test-theme.md").read_text(
        encoding="utf-8"
    )
    assert "Premier paragraphe français." in md
    assert "Deuxième paragraphe." in md
    fr_section = md.split("  fr: |")[1].split("  en: |")[0]
    assert "\n\n" in fr_section


def test_sync_themes_no_utf8_bom(tmp_path, minimal_themes_registry, site_id):
    _sync(tmp_path, minimal_themes_registry, site_id)
    raw = (tmp_path / "src" / "content" / "themes" / "test-theme.md").read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf"


def test_sync_themes_lf_line_endings(tmp_path, minimal_themes_registry, site_id):
    _sync(tmp_path, minimal_themes_registry, site_id)
    raw = (tmp_path / "src" / "content" / "themes" / "test-theme.md").read_bytes()
    assert b"\r\n" not in raw


def test_sync_themes_scope_note_never_in_md(tmp_path, minimal_themes_registry, site_id):
    _sync(tmp_path, minimal_themes_registry, site_id)
    for fname in ("test-theme.md", "test-theme-2.md"):
        md = (tmp_path / "src" / "content" / "themes" / fname).read_text(
            encoding="utf-8"
        )
        assert "scope_note" not in md
        assert "INTERNE" not in md
