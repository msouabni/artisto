"""Tests pour la sémantique répétable de ``--regen`` et ``--regen-theme``.

Brief : ``docs/architect/briefs/2026-05-26_brief-mini-bundle-categories-editorial-drop-theme-argparse.md``

Bug #17 (dette MEMORY) : ``nargs="*"`` causait l'écrasement silencieux des
occurrences précédentes — `--regen-theme noel --regen-theme ramadan` produisait
`['ramadan']` au lieu de `['noel', 'ramadan']`. Fix : ``action="append"``.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ── --regen-theme ────────────────────────────────────────────────────────────


def test_regen_theme_repeated_flag_aggregates():
    """``--regen-theme a --regen-theme b`` → ``['a', 'b']`` (pas ``['b']``)."""
    from alwanbooks_pipeline import _build_parser

    parser = _build_parser()
    args = parser.parse_args(
        ["--regen-theme", "noel", "--regen-theme", "ramadan"],
    )
    assert args.regen_theme == ["noel", "ramadan"], (
        f"expected ['noel', 'ramadan'], got {args.regen_theme!r}"
    )


def test_regen_theme_three_repeats_aggregates():
    """3 répétitions sont toutes conservées."""
    from alwanbooks_pipeline import _build_parser

    parser = _build_parser()
    args = parser.parse_args([
        "--regen-theme", "noel",
        "--regen-theme", "ramadan",
        "--regen-theme", "saison-hiver",
    ])
    assert args.regen_theme == ["noel", "ramadan", "saison-hiver"]


def test_regen_theme_single_flag_still_works():
    """Rétrocompat : une seule occurrence reste valide."""
    from alwanbooks_pipeline import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["--regen-theme", "noel"])
    assert args.regen_theme == ["noel"]


def test_regen_theme_absent_returns_none():
    """Sans flag, ``regen_theme`` reste ``None`` (convention default=None)."""
    from alwanbooks_pipeline import _build_parser

    parser = _build_parser()
    args = parser.parse_args([])
    assert args.regen_theme is None


# ── --regen (posts) ──────────────────────────────────────────────────────────


def test_regen_repeated_flag_aggregates():
    """Même fix symétrique côté posts : ``--regen a --regen b`` → ``['a', 'b']``."""
    from alwanbooks_pipeline import _build_parser

    parser = _build_parser()
    args = parser.parse_args(
        ["--regen", "slug-1", "--regen", "slug-2"],
    )
    assert args.regen == ["slug-1", "slug-2"], (
        f"expected ['slug-1', 'slug-2'], got {args.regen!r}"
    )


def test_regen_single_flag_still_works():
    """Rétrocompat : une seule occurrence reste valide côté posts."""
    from alwanbooks_pipeline import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["--regen", "slug-1"])
    assert args.regen == ["slug-1"]


def test_regen_absent_returns_none():
    """Sans flag, ``regen`` reste ``None``."""
    from alwanbooks_pipeline import _build_parser

    parser = _build_parser()
    args = parser.parse_args([])
    assert args.regen is None
