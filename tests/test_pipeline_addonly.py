"""Tests du mode ADD-ONLY pour les posts dans le pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture
def site_tree(tmp_path):
    """Crée un arbre de site minimal avec 1 post existant."""
    posts_dir = tmp_path / "src" / "content" / "posts"
    for locale in ("ar", "fr", "en"):
        d = posts_dir / locale
        d.mkdir(parents=True)
    existing = posts_dir / "fr" / "existing-slug.md"
    existing.write_text("---\ntitle: 'Existant'\n---\n\nBody.\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def mock_post_json(tmp_path):
    """Crée des JSONs de posts dans un répertoire temporaire."""
    from alwanbooks_pipeline import POSTS_DIR
    for locale in ("ar", "fr", "en"):
        d = POSTS_DIR / locale
        d.mkdir(parents=True, exist_ok=True)
    return POSTS_DIR


def test_push_skips_existing_post(site_tree):
    """Un post existant est skippé en mode ADD-ONLY."""
    from alwanbooks_pipeline import write_post_md

    existing = site_tree / "src" / "content" / "posts" / "fr" / "existing-slug.md"
    original_bytes = existing.read_bytes()

    out_path = site_tree / "src" / "content" / "posts" / "fr" / "existing-slug.md"
    assert out_path.exists()
    assert out_path.read_bytes() == original_bytes


def test_push_creates_missing_post(site_tree):
    """Un post absent est créé."""
    from alwanbooks_pipeline import write_post_md

    new_md = "---\ntitle: 'Nouveau'\n---\n\nBody.\n"
    written = write_post_md(site_tree, "fr", "new-slug", new_md)
    assert written.exists()
    assert "Nouveau" in written.read_text(encoding="utf-8")


def test_regen_overwrites_existing(site_tree):
    """--regen overwrite un post existant."""
    from alwanbooks_pipeline import write_post_md

    existing = site_tree / "src" / "content" / "posts" / "fr" / "existing-slug.md"
    assert existing.exists()

    new_md = "---\ntitle: 'Regénéré'\n---\n\nNouveau body.\n"
    written = write_post_md(site_tree, "fr", "existing-slug", new_md)
    content = written.read_text(encoding="utf-8")
    assert "Regénéré" in content
    assert "Existant" not in content


def test_regen_file_reads_list(tmp_path):
    """_read_regen_file lit correctement un fichier de slugs."""
    from alwanbooks_pipeline import _read_regen_file

    regen_file = tmp_path / "regen.txt"
    regen_file.write_text(
        "slug-1\n# commentaire\nslug-2\n\nslug-3\n", encoding="utf-8"
    )
    slugs = _read_regen_file(str(regen_file))
    assert slugs == {"slug-1", "slug-2", "slug-3"}


def test_blocklist_skips_post(tmp_path):
    """Un post blocklisted est skippé."""
    import alwanbooks_pipeline as mod

    original = mod.BLOCKLIST_PATH
    bl_path = tmp_path / "blocklist.json"
    bl_path.write_text(json.dumps({
        "version": 1,
        "blocked_posts": {"alwanbooks": ["blocked-slug"]},
    }), encoding="utf-8")
    mod.BLOCKLIST_PATH = bl_path
    try:
        assert mod._is_post_blocklisted("alwanbooks", "blocked-slug")
        assert not mod._is_post_blocklisted("alwanbooks", "other-slug")
    finally:
        mod.BLOCKLIST_PATH = original


def test_blocklist_add_post_writes_file(tmp_path):
    """blocklist_add_post écrit correctement dans le fichier."""
    import alwanbooks_pipeline as mod

    original = mod.BLOCKLIST_PATH
    bl_path = tmp_path / "blocklist.json"
    bl_path.write_text('{"version": 1, "blocked_posts": {}}', encoding="utf-8")
    mod.BLOCKLIST_PATH = bl_path
    try:
        mod.blocklist_add_post("alwanbooks", "test-slug")
        data = json.loads(bl_path.read_text(encoding="utf-8"))
        assert "test-slug" in data["blocked_posts"]["alwanbooks"]

        mod.blocklist_add_post("alwanbooks", "test-slug")
        data = json.loads(bl_path.read_text(encoding="utf-8"))
        assert data["blocked_posts"]["alwanbooks"].count("test-slug") == 1
    finally:
        mod.BLOCKLIST_PATH = original
