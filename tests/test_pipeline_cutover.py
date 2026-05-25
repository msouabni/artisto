"""Tests pour le verbe ``cutover`` (approved → published)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


SITE_CONFIG = {
    "id": "alwanbooks",
    "default_branch": "main",
    "structure": {
        "posts_dir": "src/content/posts",
        "locales": ["ar", "fr", "en"],
    },
    "bot": {"name": "test-bot", "email": "test@bot.local"},
}


@pytest.fixture
def site_with_posts(tmp_path):
    """Crée un site avec posts approved, published, et draft."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    posts_dir = tmp_path / "src" / "content" / "posts"
    for locale in ("ar", "fr", "en"):
        d = posts_dir / locale
        d.mkdir(parents=True)

    (posts_dir / "fr" / "approved-post.md").write_text(
        "---\ntitle: 'Approuvé'\nstatus: 'approved'\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (posts_dir / "fr" / "published-post.md").write_text(
        "---\ntitle: 'Publié'\nstatus: 'published'\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (posts_dir / "fr" / "draft-post.md").write_text(
        "---\ntitle: 'Brouillon'\nstatus: 'draft'\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return tmp_path


def _mock_git_run_clean(site_root, args, **kwargs):
    result = MagicMock()
    result.returncode = 0
    if args == ["status", "--porcelain"]:
        result.stdout = ""
    elif args == ["branch", "--show-current"]:
        result.stdout = "main\n"
    else:
        result.stdout = ""
    result.stderr = ""
    return result


def test_cutover_bumps_approved_to_published(site_with_posts):
    from alwanbooks_pipeline import run_cutover

    with patch("alwanbooks_pipeline._git_run", side_effect=_mock_git_run_clean):
        summary = run_cutover(
            site_with_posts, SITE_CONFIG, no_git_push=True,
        )

    assert summary.modified == 1
    assert summary.already_published == 1
    assert summary.other_status == 1

    content = (
        site_with_posts / "src" / "content" / "posts" / "fr" / "approved-post.md"
    ).read_text(encoding="utf-8")
    assert "status: 'published'" in content
    assert "status: 'approved'" not in content


def test_cutover_preserves_other_fields_bytewise(site_with_posts):
    from alwanbooks_pipeline import run_cutover

    original = (
        site_with_posts / "src" / "content" / "posts" / "fr" / "approved-post.md"
    ).read_text(encoding="utf-8")

    with patch("alwanbooks_pipeline._git_run", side_effect=_mock_git_run_clean):
        run_cutover(site_with_posts, SITE_CONFIG, no_git_push=True)

    modified = (
        site_with_posts / "src" / "content" / "posts" / "fr" / "approved-post.md"
    ).read_text(encoding="utf-8")

    assert modified == original.replace("status: 'approved'", "status: 'published'")
    assert "title: 'Approuvé'" in modified


def test_cutover_refuses_dirty_working_tree(site_with_posts):
    from alwanbooks_pipeline import run_cutover

    def mock_dirty(site_root, args, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if args == ["status", "--porcelain"]:
            result.stdout = " M some/file.md\n"
        elif args == ["branch", "--show-current"]:
            result.stdout = "main\n"
        result.stderr = ""
        return result

    with patch("alwanbooks_pipeline._git_run", side_effect=mock_dirty):
        with pytest.raises(RuntimeError, match="not clean"):
            run_cutover(site_with_posts, SITE_CONFIG, no_git_push=True)


def test_cutover_skips_already_published(site_with_posts):
    from alwanbooks_pipeline import run_cutover

    with patch("alwanbooks_pipeline._git_run", side_effect=_mock_git_run_clean):
        summary = run_cutover(
            site_with_posts, SITE_CONFIG, no_git_push=True,
        )

    assert summary.already_published == 1
    content = (
        site_with_posts / "src" / "content" / "posts" / "fr" / "published-post.md"
    ).read_text(encoding="utf-8")
    assert "status: 'published'" in content
