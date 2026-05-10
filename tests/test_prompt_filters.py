"""Tests unitaires — ``src.services.prompt_filters`` (transfert skill T5 + T6 + T7).

Couvre :
- Strip noms de couleur explicites (T5).
- Remplacement ancres chromatiques implicites (T6).
- Strip surfaces brillantes / matières (extension T6).
- Strip termes 3D / rendu volumétrique (T7).
- Composition ``apply_all_filters``.
- Non-régression sur textes neutres.
"""

from __future__ import annotations

import pytest

from services.prompt_filters import (
    _3D_TERMS,
    _COLOR_ANCHORS,
    _COLOR_NOUNS,
    _GLOSSY_TERMS,
    apply_all_filters,
    describe_filters,
    replace_color_anchors,
    strip_3d_terms,
    strip_color_nouns,
    strip_glossy_terms,
)


# -------------------------------------------------------------------
# T5 — strip_color_nouns
# -------------------------------------------------------------------
class TestStripColorNouns:
    def test_basic_red(self):
        assert strip_color_nouns("a red apple") == "a apple"

    def test_multiple_colors(self):
        out = strip_color_nouns("a red and blue striped ball")
        assert "red" not in out.lower().split()
        assert "blue" not in out.lower().split()

    def test_case_insensitive(self):
        assert "red" not in strip_color_nouns("A RED ball").lower().split()

    def test_metal_named_color(self):
        # ``golden`` est T5 (nom de couleur), distinct des matières T7.
        assert "golden" not in strip_color_nouns("a golden retriever").lower().split()

    def test_neutral_text_unchanged(self):
        text = "a simple line drawing of a cat"
        assert strip_color_nouns(text) == text

    def test_substring_not_stripped(self):
        # ``orange`` strippé mais pas ``orangery``
        assert strip_color_nouns("the orangery is closed") == "the orangery is closed"

    def test_empty_input(self):
        assert strip_color_nouns("") == ""


# -------------------------------------------------------------------
# T6 — replace_color_anchors
# -------------------------------------------------------------------
class TestReplaceColorAnchors:
    def test_rainbow_to_colorful(self):
        out = replace_color_anchors("a rainbow over the mountain")
        assert "rainbow" not in out.lower()
        assert "colorful" in out.lower()

    def test_sunset_to_sky_scene(self):
        out = replace_color_anchors("painting a sunset")
        assert "sunset" not in out.lower()
        assert "sky scene" in out.lower()

    def test_autumn_to_seasonal(self):
        out = replace_color_anchors("autumn forest")
        assert "autumn" not in out.lower()
        assert "seasonal" in out.lower()

    def test_tropical_to_exotic(self):
        out = replace_color_anchors("a tropical beach")
        assert "tropical" not in out.lower()
        assert "exotic" in out.lower()

    def test_neutral_text_unchanged(self):
        text = "a simple house with a roof"
        assert replace_color_anchors(text) == text

    def test_empty_input(self):
        assert replace_color_anchors("") == ""


# -------------------------------------------------------------------
# Extension T6 — strip_glossy_terms
# -------------------------------------------------------------------
class TestStripGlossyTerms:
    def test_shiny_glossy_metallic(self):
        out = strip_glossy_terms("a shiny glossy metallic sphere").lower()
        for word in ("shiny", "glossy", "metallic"):
            assert word not in out.split()

    def test_chrome_glass(self):
        out = strip_glossy_terms("chrome and glass tower").lower()
        assert "chrome" not in out.split()
        assert "glass" not in out.split()

    def test_chocolate_stripped(self):
        # Skill T7 cite ``chocolate`` comme ancre matière (œuf de Pâques).
        assert "chocolate" not in strip_glossy_terms("a chocolate egg").lower().split()

    def test_neutral_text_unchanged(self):
        text = "a wooden box on a simple ground"
        assert strip_glossy_terms(text) == text

    def test_empty_input(self):
        assert strip_glossy_terms("") == ""


# -------------------------------------------------------------------
# T7 — strip_3d_terms
# -------------------------------------------------------------------
class TestStrip3dTerms:
    def test_volumetric_shaded(self):
        out = strip_3d_terms("a shaded volumetric ball").lower()
        assert "shaded" not in out.split()
        assert "volumetric" not in out.split()

    def test_realistic_textures_multiword(self):
        out = strip_3d_terms("ball with realistic textures").lower()
        assert "realistic textures" not in out
        assert "realistic" not in out.split()

    def test_depth_shading_multiword(self):
        out = strip_3d_terms("scene with depth shading effect").lower()
        assert "depth shading" not in out

    def test_neutral_text_unchanged(self):
        text = "a flat line illustration"
        assert strip_3d_terms(text) == text

    def test_empty_input(self):
        assert strip_3d_terms("") == ""


# -------------------------------------------------------------------
# Composition — apply_all_filters
# -------------------------------------------------------------------
class TestApplyAllFilters:
    def test_full_chain_kitchen_sink(self):
        text = "a shiny red rainbow chocolate egg with realistic textures"
        out = apply_all_filters(text).lower()
        # T5
        assert "red" not in out.split()
        # T6 — rainbow remplacé par colorful (présent), pas strippé
        assert "rainbow" not in out
        assert "colorful" in out
        # ext T6
        assert "shiny" not in out.split()
        assert "chocolate" not in out.split()
        # T7
        assert "realistic textures" not in out

    def test_preserves_subject(self):
        out = apply_all_filters("a shiny red rainbow chocolate egg with realistic textures")
        assert "egg" in out.lower()

    def test_neutral_text_unchanged(self):
        text = "a simple line drawing of a cat"
        assert apply_all_filters(text) == text

    def test_pure_color_text_collapses(self):
        # "red blue green" → tous strippés → résultat vide ou quasi.
        assert apply_all_filters("red blue green") == ""

    def test_empty_input(self):
        assert apply_all_filters("") == ""

    def test_none_safe(self):
        # Robustesse : faux input None ne doit pas planter (filtré upstream
        # côté générateur, mais on garde la garde).
        assert apply_all_filters(None) is None  # type: ignore[arg-type]


# -------------------------------------------------------------------
# Vocabulaires — sanity check
# -------------------------------------------------------------------
class TestVocabularies:
    def test_color_nouns_contains_skill_examples(self):
        for word in ("red", "blue", "golden", "silver"):
            assert word in _COLOR_NOUNS

    def test_color_anchors_contains_skill_examples(self):
        for word in ("rainbow", "sunset", "autumn", "tropical", "fire", "flame"):
            assert word in _COLOR_ANCHORS

    def test_glossy_contains_skill_examples(self):
        for word in ("shiny", "glossy", "metallic", "chrome", "glass", "wet", "chocolate"):
            assert word in _GLOSSY_TERMS

    def test_3d_terms_contains_skill_examples(self):
        joined = " | ".join(_3D_TERMS).lower()
        for word in ("shaded", "volumetric", "realistic textures"):
            assert word in joined

    def test_describe_filters_returns_counts(self):
        described = dict(describe_filters())
        assert described["T5_color_nouns"] == len(_COLOR_NOUNS)
        assert described["T6_color_anchors"] == len(_COLOR_ANCHORS)
        assert described["T6_ext_glossy_terms"] == len(_GLOSSY_TERMS)
        assert described["T7_3d_terms"] == len(_3D_TERMS)


# -------------------------------------------------------------------
# Cas edge regroupés
# -------------------------------------------------------------------
@pytest.mark.parametrize(
    "input_text",
    [
        "a cat",
        "one single dog standing",
        "two children playing in a park",
        "a wooden chair on a simple floor",
    ],
)
def test_neutral_inputs_are_idempotent(input_text):
    """Texte sans terme ciblé ⇒ inchangé (non-régression)."""
    assert apply_all_filters(input_text) == input_text


# -------------------------------------------------------------------
# Cas spécifique fire/flame — anti-double-substitution
# -------------------------------------------------------------------
def test_fire_does_not_create_double_replacement():
    """Garde-fou : ``fire`` → ``flame shape`` ne doit pas re-matcher
    ``flame`` et produire ``flame shape shape``.

    Cf. bug observé sur leaf ``fire_dragon`` lors du smoke 2026-05-10.
    """
    out = apply_all_filters("a fire dragon")
    assert "flame shape shape" not in out
    assert "flame shape" in out


def test_leaf_override_skipped_via_pipeline_hook():
    """Smoke d'intégration : un override humain (sheep_with_lamb) doit ressortir
    intégral, sans aucun strip — vérifie que le hook respecte la branche
    LEAF_OVERRIDES dans ``prompt_generator.build_prompt``.
    """
    pytest.importorskip("services.prompt_generator")
    from services.prompt_generator import PromptGenerator, LEAF_OVERRIDES

    gen = PromptGenerator()
    for leaf_id, raw_override in LEAF_OVERRIDES.items():
        result = gen.build_prompt(leaf_id)
        assert result["positive"] == raw_override, (
            f"LEAF_OVERRIDES[{leaf_id!r}] a été modifié par les filtres T5/T6/T7 — "
            "le hook doit court-circuiter cette branche."
        )
