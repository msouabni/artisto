"""Tests d'intégration pour le câblage push auto via git_bot_push.

Vérifient que ``run_pipeline`` appelle ``git_bot_push`` (et non plus
``git_commit_push`` legacy), que la branche bot remonte jusqu'à
``print_deployment_recap``, et que les modes ``--no-git-push`` / ``--mock``
short-circuitent toujours le push.

Brief : 2026-05-27_brief-fix-pipeline-push-auto-bot-branch.md
"""
from __future__ import annotations

import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _stub_pipeline_inputs(monkeypatch, tmp_path):
    """Stub minimal pour faire tourner run_pipeline sans I/O réel.

    - Manifest avec 1 leaf.
    - export_mep_v0._resolve_master_png → un PNG factice.
    - convert_master_to_variants → 4 paths factices.
    - R2 client mocké (upload = ok, idempotent).
    - JSONs posts présents dans POSTS_DIR (locale fr/en/ar).
    """
    import alwanbooks_pipeline as p

    # Manifest factice
    manifest = {"leaves": [{
        "leaf_id": "fake_leaf",
        "r2_slug": "fake-slug",
        "post_slugs": {"fr": "fake-slug", "en": "fake-slug", "ar": "fake-slug"},
        "image_id": "benchmark:fake-id",
    }]}

    manifest_path = tmp_path / "manifest.json"
    import json
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(p, "MANIFEST_PATH", manifest_path)

    # POSTS_DIR avec JSON minimal pour chaque locale
    posts_dir = tmp_path / "data_posts"
    for locale in ("fr", "en", "ar"):
        d = posts_dir / locale
        d.mkdir(parents=True, exist_ok=True)
        post_json = d / "fake-slug.json"
        post_json.write_text(json.dumps({
            "slug": "fake-slug",
            "title": "Fake",
            "description": "Fake description for tests.",
            "categoryId": "uncategorized",
            "ageMin": 4,
            "ageMax": 10,
            "niveauDifficulte": "easy",
            "tags": [],
            "themeIds": [],
            "imageId": "benchmark:fake-id",
            "dateAjout": "2026-05-27",
            "dateModification": "2026-05-27",
            "status": "approved",
        }), encoding="utf-8")
    monkeypatch.setattr(p, "POSTS_DIR", posts_dir)

    # Master + variants factices
    fake_master = tmp_path / "fake_master.png"
    fake_master.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    monkeypatch.setattr(
        p.export_mep_v0, "_resolve_master_png",
        lambda target_id: fake_master,
    )

    fake_variants = {
        "master": tmp_path / "v_master.png",
        "webp": tmp_path / "v.webp",
        "thumb": tmp_path / "v_thumb.webp",
        "pdf": tmp_path / "v.pdf",
    }
    for fv in fake_variants.values():
        fv.write_bytes(b"fakebytes")
    monkeypatch.setattr(p, "convert_master_to_variants", lambda m: fake_variants)
    monkeypatch.setattr(p, "_md5", lambda path: "fakemd5")

    # R2 client mocké : non-None, _upload_variants_real renvoie (uploaded, skipped)
    monkeypatch.setattr(p, "_r2_client_from_env", lambda: MagicMock(name="r2_client"))
    monkeypatch.setattr(
        p, "_upload_variants_real",
        lambda r2, slug, variants, md5: (["master", "webp", "thumb", "pdf"], []),
    )

    # themes_registry vide
    monkeypatch.setattr(p, "_load_themes_registry", lambda: {"themes": []})
    monkeypatch.setattr(p, "compute_theme_ids", lambda leaf, registry: [])
    # Pas de blocklist
    monkeypatch.setattr(p, "_is_post_blocklisted", lambda site_id, slug: False)

    # site_config minimal pour get_site
    monkeypatch.setattr(p, "get_site", lambda site_id: {
        "bot": {"name": "test-bot", "email": "test@bot.local"},
        "default_branch": "main",
        "repo_url": "git@github.com:test/repo.git",
        "structure": {
            "posts_dir": "src/content/posts",
            "themes_dir": "src/content/themes",
            "locales": ["ar", "fr", "en"],
        },
    })

    # sync_themes mocké pour éviter d'avoir à fournir themes_registry complet
    fake_themes = MagicMock()
    fake_themes.created = 0
    fake_themes.skipped_existing = 0
    fake_themes.files_created = []
    monkeypatch.setattr(p, "sync_themes", lambda *a, **k: fake_themes)

    return p


def test_run_pipeline_calls_git_bot_push_not_legacy(tmp_path, monkeypatch):
    """run_pipeline en mode push appelle git_bot_push, pas git_commit_push."""
    p = _stub_pipeline_inputs(monkeypatch, tmp_path)

    bot_called = {"count": 0}
    legacy_called = {"count": 0}

    def fake_bot(site_root, site_config, *, commit_messages):
        bot_called["count"] += 1
        return "bot/lot-2026-05-27", len(commit_messages)

    def fake_legacy(*args, **kwargs):
        legacy_called["count"] += 1
        return 0, ""

    monkeypatch.setattr(p, "git_bot_push", fake_bot)
    monkeypatch.setattr(p, "git_commit_push", fake_legacy)

    rimalab_root = tmp_path / "site_clone"
    rimalab_root.mkdir()

    summary = p.run_pipeline(
        mock=False, no_git_push=False, leaf_id=None, limit=None,
        rimalab_root=rimalab_root, site_id="alwanbooks",
    )

    assert bot_called["count"] == 1, "git_bot_push doit être appelé"
    assert legacy_called["count"] == 0, "git_commit_push legacy ne doit plus être appelé"
    assert summary.posts_written > 0


def test_run_pipeline_passes_branch_name_to_summary(tmp_path, monkeypatch):
    """summary.bot_branch_name est rempli après run réussi."""
    p = _stub_pipeline_inputs(monkeypatch, tmp_path)

    def fake_bot(site_root, site_config, *, commit_messages):
        return "bot/lot-2026-05-27", 1

    monkeypatch.setattr(p, "git_bot_push", fake_bot)

    rimalab_root = tmp_path / "site_clone"
    rimalab_root.mkdir()

    summary = p.run_pipeline(
        mock=False, no_git_push=False, leaf_id=None, limit=None,
        rimalab_root=rimalab_root, site_id="alwanbooks",
    )

    assert summary.bot_branch_name == "bot/lot-2026-05-27"
    assert summary.bot_commit_count == 1


def test_main_passes_branch_name_to_recap(tmp_path, monkeypatch):
    """print_deployment_recap reçoit branch_name non-None pour run réel."""
    p = _stub_pipeline_inputs(monkeypatch, tmp_path)

    monkeypatch.setattr(
        p, "git_bot_push",
        lambda site_root, site_config, *, commit_messages: ("bot/lot-2026-05-27", 1),
    )

    captured = {}

    def fake_recap(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(p, "print_deployment_recap", fake_recap)
    # _resolve_site_root → tmp_path/site_clone
    rimalab_root = tmp_path / "site_clone"
    rimalab_root.mkdir()
    monkeypatch.setattr(p, "_resolve_site_root", lambda args: rimalab_root)

    rc = p.main([
        "--site", "alwanbooks",
        "--limit", "1",
    ])

    assert rc == 0
    assert captured.get("branch_name") == "bot/lot-2026-05-27"
    assert captured.get("commit_count") == 1


def test_no_git_push_skips_bot_push(tmp_path, monkeypatch):
    """--no-git-push skip le bot push, summary.bot_branch_name reste None."""
    p = _stub_pipeline_inputs(monkeypatch, tmp_path)

    bot_called = {"count": 0}

    def fake_bot(site_root, site_config, *, commit_messages):
        bot_called["count"] += 1
        return "bot/lot-2026-05-27", 1

    monkeypatch.setattr(p, "git_bot_push", fake_bot)

    rimalab_root = tmp_path / "site_clone"
    rimalab_root.mkdir()

    summary = p.run_pipeline(
        mock=False, no_git_push=True, leaf_id=None, limit=None,
        rimalab_root=rimalab_root, site_id="alwanbooks",
    )

    assert bot_called["count"] == 0
    assert summary.bot_branch_name is None
    assert summary.bot_commit_count == 0


def test_mock_skips_bot_push(tmp_path, monkeypatch):
    """--mock skip aussi le bot push."""
    p = _stub_pipeline_inputs(monkeypatch, tmp_path)

    bot_called = {"count": 0}

    def fake_bot(site_root, site_config, *, commit_messages):
        bot_called["count"] += 1
        return "bot/lot-2026-05-27", 1

    monkeypatch.setattr(p, "git_bot_push", fake_bot)
    # Mock mode bypass R2
    monkeypatch.setattr(
        p, "_upload_variants_mock",
        lambda slug, variants: (["master", "webp", "thumb", "pdf"], []),
    )

    rimalab_root = tmp_path / "site_clone"
    rimalab_root.mkdir()

    summary = p.run_pipeline(
        mock=True, no_git_push=False, leaf_id=None, limit=None,
        rimalab_root=rimalab_root, site_id="alwanbooks",
    )

    assert bot_called["count"] == 0
    assert summary.bot_branch_name is None


def test_bot_branch_name_format(tmp_path, monkeypatch):
    """Le nom de branche matche ^bot/lot-\\d{4}-\\d{2}-\\d{2}(-\\d+)?$."""
    import alwanbooks_pipeline as p

    # ls-remote vide → pas de collision, nom base utilisé
    mock_result = MagicMock()
    mock_result.stdout = ""

    with patch("alwanbooks_pipeline.subprocess.run", return_value=mock_result):
        branch_base = p._find_available_branch(tmp_path, "2026-05-27")

    assert re.match(r"^bot/lot-\d{4}-\d{2}-\d{2}$", branch_base)

    # Collision → suffixe -N
    mock_collision = MagicMock()
    mock_collision.stdout = (
        "abc\trefs/heads/bot/lot-2026-05-27\n"
        "def\trefs/heads/bot/lot-2026-05-27-2\n"
    )
    with patch("alwanbooks_pipeline.subprocess.run", return_value=mock_collision):
        branch_n = p._find_available_branch(tmp_path, "2026-05-27")

    assert re.match(r"^bot/lot-\d{4}-\d{2}-\d{2}(-\d+)?$", branch_n)
    assert branch_n == "bot/lot-2026-05-27-3"


def test_recap_prints_branch_section_when_branch_name_set():
    """Bloc 'Branche push / Commits / URL' présent dans stdout quand branch_name fourni."""
    from alwanbooks_pipeline import print_deployment_recap

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_deployment_recap(
            site_id="alwanbooks",
            site_config={"default_branch": "main"},
            posts_created=3,
            branch_name="bot/lot-2026-05-27",
            commit_count=2,
            no_git_push=False,
            repo_url="git@github.com:test/repo.git",
        )
    out = buf.getvalue()
    assert "Branche push" in out
    assert "bot/lot-2026-05-27" in out
    assert "Commits" in out
    assert "URL branche" in out
    assert "https://github.com/test/repo/tree/bot/lot-2026-05-27" in out
    assert "À faire côté site destinataire" in out


def test_recap_omits_branch_section_when_no_git_push():
    """Bloc 'Branche push' absent en --no-git-push, même si branch_name fourni."""
    from alwanbooks_pipeline import print_deployment_recap

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_deployment_recap(
            site_id="alwanbooks",
            site_config={"default_branch": "main"},
            posts_created=3,
            branch_name=None,
            commit_count=0,
            no_git_push=True,
            repo_url="git@github.com:test/repo.git",
        )
    out = buf.getvalue()
    assert "Mode --no-git-push" in out
    assert "Branche push" not in out
    assert "URL branche" not in out
