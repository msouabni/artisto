"""Tests dedies au mode pastel du PromptGenerator (transition 2026-05-31).

Verifie que :
    - Le style par defaut est pastel (sauf si env ARTISTE_PROMPT_STYLE=lineart)
    - La transformation pastelize_prompt() est correctement appliquee
    - Le style='lineart' explicite produit le prompt historique
    - Le sujet + l'isolation + l'anatomie sont preserves dans la transformation
    - Le champ 'style' est expose dans le dict retourne
"""
from __future__ import annotations

import os

import pytest

from services.prompt_generator import (
    PromptGenerator,
    _pastelize_prompt,
)


@pytest.fixture(autouse=True)
def _force_pastel_env(monkeypatch):
    """Force ARTISTE_PROMPT_STYLE=pastel sur ce fichier uniquement (override conftest)."""
    monkeypatch.setenv("ARTISTE_PROMPT_STYLE", "pastel")


@pytest.fixture(scope="module")
def gen():
    """Une instance PromptGenerator partagee par tous les tests."""
    return PromptGenerator()


# === Transformation pastelize_prompt =========================================
def test_pastelize_replaces_coloring_book_header():
    pos, _ = _pastelize_prompt(
        "coloring book page for kids, one single lion",
        "no colors",
    )
    assert pos.startswith("soft pastel children's coloring illustration"), pos


def test_pastelize_removes_anti_color_fragments():
    pos, _ = _pastelize_prompt(
        "coloring book page for kids, black and white line art, "
        "thick clean outlines, no shading, no fill, white background, "
        "one single lion",
        "no colors",
    )
    forbidden = [
        "black and white line art",
        "no shading",
        "no fill",
        "white background",
    ]
    for term in forbidden:
        assert term not in pos.lower(), f"'{term}' present dans le positif pastel"


def test_pastelize_adds_pastel_palette_suffix():
    pos, _ = _pastelize_prompt(
        "coloring book page for kids, one single lion",
        "no colors",
    )
    assert "soft pastel palette" in pos
    assert "pale yellow" in pos
    assert "peach" in pos
    assert "no gradients" in pos


def test_pastelize_preserves_subject():
    """Le sujet et les contraintes anatomiques sont preserves."""
    pos, _ = _pastelize_prompt(
        "coloring book page for kids, black and white line art, "
        "one single lion in the savanna standing in profile, "
        "all four legs visible on the ground, isolated subject",
        "no colors",
    )
    assert "one single lion in the savanna standing in profile" in pos
    assert "all four legs visible on the ground" in pos
    assert "isolated subject" in pos


def test_pastelize_removes_anti_color_negatives():
    _, neg = _pastelize_prompt(
        "coloring book page for kids",
        "no colors, no fill colors, "
        "no change in ink transparency for different plan only black stroke, "
        "extra legs, malformed anatomy",
    )
    forbidden = ["no colors", "no fill colors", "no change in ink transparency"]
    for term in forbidden:
        assert term not in neg.lower()


def test_pastelize_preserves_anatomical_negatives():
    """Les contraintes anatomiques restent dans le negatif pastel."""
    _, neg = _pastelize_prompt(
        "coloring book page for kids",
        "no colors, extra legs, third leg, malformed anatomy, multiple animals",
    )
    assert "extra legs" in neg
    assert "third leg" in neg
    assert "malformed anatomy" in neg
    assert "multiple animals" in neg


def test_pastelize_adds_anti_realistic_negative():
    _, neg = _pastelize_prompt(
        "coloring book page for kids",
        "no colors, extra legs",
    )
    assert "photographic" in neg
    assert "realistic" in neg
    assert "3d render" in neg
    assert "painterly" in neg


# === build_prompt() avec param style =========================================
def test_build_prompt_default_is_pastel(gen):
    """Default = pastel (env ARTISTE_PROMPT_STYLE=pastel ou pas set)."""
    r = gen.build_prompt("polar_bear_on_ice")
    assert r["style"] == "pastel"
    assert r["positive"].startswith("soft pastel children's coloring illustration")
    assert "soft pastel palette" in r["positive"]


def test_build_prompt_lineart_explicit(gen):
    """style='lineart' explicite = mode historique."""
    r = gen.build_prompt("polar_bear_on_ice", style="lineart")
    assert r["style"] == "lineart"
    assert r["positive"].startswith("coloring book page for kids")
    assert "black and white line art" in r["positive"]


def test_build_prompt_pastel_explicit(gen):
    """style='pastel' explicite = nouveau mode."""
    r = gen.build_prompt("polar_bear_on_ice", style="pastel")
    assert r["style"] == "pastel"
    assert "soft pastel" in r["positive"].lower()


def test_build_prompt_unknown_style_fallback(gen, caplog):
    """style inconnu = fallback lineart avec warning."""
    r = gen.build_prompt("polar_bear_on_ice", style="unknown_style")
    assert r["style"] == "lineart"


def test_build_prompt_preserves_other_fields(gen):
    """Le passage en pastel ne casse pas les autres champs."""
    r = gen.build_prompt("polar_bear_on_ice")
    assert r["leaf_id"] == "polar_bear_on_ice"
    assert r["workflow_class"] == "Solo animal"
    assert isinstance(r["resolution"], tuple)
    assert r["negative"]  # non vide


def test_build_prompt_pastel_on_object_class(gen):
    """Pastel fonctionne sur Solo objet (pas seulement Solo animal)."""
    r = gen.build_prompt("carpet_cleaner")
    assert r["style"] == "pastel"
    assert "carpet cleaner" in r["positive"]
    assert "soft pastel" in r["positive"].lower()


def test_build_prompt_pastel_isolation_preserved(gen):
    """Mode pastel preserve l'isolation (no other animals/objects nearby)."""
    r = gen.build_prompt("polar_bear_on_ice")
    pos = r["positive"]
    assert "isolated subject" in pos or "no other" in pos
