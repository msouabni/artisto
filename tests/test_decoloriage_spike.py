"""Test minimal Phase 1 (spike) du service décoloriage.

Portable SQLite / sans DB : le service ``decolorize`` ne touche aucune base.
Vérifie la chaîne complète G1a→G5 sur une image pastel réelle existante.

Critères vérifiés (cf. brief Phase 1) :
  - SVG non vide contenant ``<g id="fills"`` ET ``<g id="strokes"``
  - n_clickable > 0
  - chaque région cliquable porte un crayon_hex dans la palette autorisée
  - au moins 1 région-encre détectée
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.decoloriage import ALLOWED_FILL_HEXES, INK_REGION_FILL, decolorize

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Image pastel réelle (sortie ERNIE prod, leaf taxonomie polar_bear_on_ice).
TEST_PNG = (
    PROJECT_ROOT
    / "data" / "outputs"
    / "test_e2e_polar_bear_on_ice_job_gen_1780755027700885100_0_pastel_chromakey.png"
)


@pytest.fixture(scope="module")
def result():
    if not TEST_PNG.exists():
        pytest.skip(f"Image de test absente : {TEST_PNG}")
    return decolorize(TEST_PNG, level="enfant")


def test_svg_non_empty_bilayer(result):
    """Le SVG est non vide et bicouche (fills + strokes)."""
    assert result.svg
    assert '<g id="fills"' in result.svg
    assert '<g id="strokes"' in result.svg
    # fill-rule even-odd sur la couche fills (un click = une région entière).
    assert 'fill-rule="evenodd"' in result.svg


def test_clickable_regions_present(result):
    """Au moins une région cliquable."""
    assert result.n_clickable > 0
    clickable = [r for r in result.regions if not r.is_ink]
    assert len(clickable) == result.n_clickable


def test_clickable_regions_have_allowed_crayon(result):
    """Chaque région cliquable porte un crayon_hex dans la palette autorisée."""
    clickable = [r for r in result.regions if not r.is_ink]
    assert clickable
    for r in clickable:
        assert r.crayon_hex in ALLOWED_FILL_HEXES, (
            f"region {r.id} crayon_hex {r.crayon_hex} hors palette"
        )


def test_at_least_one_ink_region(result):
    """Au moins une région-encre détectée (overlap >= 50 % masque de traits)."""
    assert result.n_ink_regions >= 1
    ink = [r for r in result.regions if r.is_ink]
    assert len(ink) == result.n_ink_regions
    for r in ink:
        assert r.crayon_hex == INK_REGION_FILL  # #111111, non cliquable


def test_ink_regions_not_in_svg_clickable_class(result):
    """Les régions-encre sont rendues en class="ink-region" (pointer-events:none)."""
    assert 'class="ink-region"' in result.svg
    assert result.svg.count('class="ink-region"') == result.n_ink_regions


def test_result_metadata_consistency(result):
    """Cohérence des métriques de la dataclass DecoloriageResult."""
    assert result.level == "enfant"
    assert result.image_size[0] > 0 and result.image_size[1] > 0
    assert result.delta_e_median >= 0.0
    assert isinstance(result.publishable_tp, bool)
    assert isinstance(result.crayon_distribution, dict)
    # Tous les hex de distribution sont des crayons ou Papier.
    for hex_str in result.crayon_distribution:
        assert hex_str in ALLOWED_FILL_HEXES


def test_only_enfant_level_supported():
    """Les autres niveaux lèvent une ValueError explicite (D5)."""
    with pytest.raises(ValueError):
        decolorize(TEST_PNG, level="tout_petit")
