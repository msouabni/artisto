"""Tests pour le push automatique sur branche bot."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def test_branch_name_uses_today_date():
    from alwanbooks_pipeline import _find_available_branch

    mock_result = MagicMock()
    mock_result.stdout = ""

    with patch("alwanbooks_pipeline.subprocess.run", return_value=mock_result):
        branch = _find_available_branch(Path("/tmp/fake"), "2026-05-24")

    assert branch == "bot/lot-2026-05-24"


def test_branch_name_increments_suffix_on_collision():
    from alwanbooks_pipeline import _find_available_branch

    mock_result = MagicMock()
    mock_result.stdout = (
        "abc123\trefs/heads/bot/lot-2026-05-24\n"
        "def456\trefs/heads/bot/lot-2026-05-24-2\n"
    )

    with patch("alwanbooks_pipeline.subprocess.run", return_value=mock_result):
        branch = _find_available_branch(Path("/tmp/fake"), "2026-05-24")

    assert branch == "bot/lot-2026-05-24-3"


def test_commit_uses_bot_identity():
    from alwanbooks_pipeline import git_bot_push

    calls = []

    def mock_run(args, **kwargs):
        calls.append(args)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    site_config = {
        "bot": {"name": "test-bot", "email": "test@bot.local"},
    }

    with patch("alwanbooks_pipeline.subprocess.run", side_effect=mock_run):
        with patch(
            "alwanbooks_pipeline._find_available_branch",
            return_value="bot/lot-2026-05-24",
        ):
            branch, rc = git_bot_push(
                Path("/tmp/fake"),
                site_config,
                commit_messages=[
                    ("test commit", ["src/content/posts/"]),
                ],
            )

    assert branch == "bot/lot-2026-05-24"
    commit_calls = [c for c in calls if "commit" in c]
    assert len(commit_calls) >= 1
    commit_cmd = commit_calls[0]
    assert "user.name=test-bot" in " ".join(str(a) for a in commit_cmd)
    assert "user.email=test@bot.local" in " ".join(str(a) for a in commit_cmd)


def test_no_git_push_skips_push():
    """En mode --no-git-push, la fonction git_bot_push n'est jamais appelée."""
    from alwanbooks_pipeline import main

    calls = []

    def mock_run(args, **kwargs):
        calls.append(args)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with patch("alwanbooks_pipeline.subprocess.run", side_effect=mock_run):
        push_calls = [c for c in calls if "push" in str(c)]
        assert len(push_calls) == 0
