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
    _PROTECTED_NOMINAL_PATTERNS,
    _WHITELISTED_TOKENS,
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


# -------------------------------------------------------------------
# Whitelist FILT contextuelle — fruits / contenants comestibles
# Cf. brief 2026-05-10_brief-whitelist-filt-contextuelle.md
#     + rapport 2026-05-10_transfert-skill-T2T3T23-grille-imagier.md §FILT × T2
# -------------------------------------------------------------------
class TestProtectedNominalWhitelistVocabulary:
    """Sanity check sur la définition de la whitelist."""

    def test_at_least_six_patterns_defined(self):
        """Brief : >= 6 patterns documentés."""
        assert len(_PROTECTED_NOMINAL_PATTERNS) >= 6

    def test_whitelisted_tokens_are_in_filtered_vocabularies(self):
        """Cohérence : un token protégé doit appartenir à au moins un
        des vocabulaires filtrés (sinon protection inutile)."""
        all_filtered = _COLOR_NOUNS | _GLOSSY_TERMS
        for token in _WHITELISTED_TOKENS:
            assert token in all_filtered, (
                f"Token {token!r} whitelisté mais absent des vocabulaires filtrés "
                "(_COLOR_NOUNS ∪ _GLOSSY_TERMS)."
            )

    def test_orange_is_whitelisted(self):
        assert "orange" in _WHITELISTED_TOKENS

    def test_glass_is_whitelisted(self):
        assert "glass" in _WHITELISTED_TOKENS

    def test_bright_is_whitelisted(self):
        assert "bright" in _WHITELISTED_TOKENS


class TestStripColorNounsWithWhitelistPositive:
    """Tests positifs : token preserved dans contexte nominal protégé."""

    def test_orange_fruit_with_leaf_preserved(self):
        # Cas direct du JSON grille : `round orange with leaf`.
        out = strip_color_nouns("round orange with leaf")
        assert "orange" in out.lower().split()

    def test_orange_dimpled_skin_preserved(self):
        out = strip_color_nouns("round orange with dimpled skin")
        assert "orange" in out.lower().split()

    def test_sliced_orange_on_plate_preserved(self):
        out = strip_color_nouns("sliced orange on a plate")
        assert "orange" in out.lower().split()

    def test_an_orange_slice_preserved(self):
        out = strip_color_nouns("an orange slice on the table")
        assert "orange" in out.lower().split()

    def test_bright_idea_preserved(self):
        out = strip_color_nouns("a bright idea on a chalkboard")
        assert "bright" in out.lower().split()

    def test_bright_smile_preserved(self):
        out = strip_color_nouns("a bright smile on a face")
        assert "bright" in out.lower().split()

    def test_dark_age_preserved(self):
        out = strip_color_nouns("a dark age castle scene")
        assert "dark" in out.lower().split()

    def test_red_carpet_preserved(self):
        out = strip_color_nouns("a long red carpet leading to the door")
        assert "red" in out.lower().split()


class TestStripColorNounsWithWhitelistNegative:
    """Tests négatifs : strip toujours actif hors contexte protégé."""

    def test_orange_car_stripped(self):
        # `orange car` n'a pas de contexte fruit → strip standard.
        out = strip_color_nouns("an orange car")
        assert "orange" not in out.lower().split()

    def test_orange_alone_stripped(self):
        out = strip_color_nouns("orange and blue")
        assert "orange" not in out.lower().split()

    def test_red_apple_stripped(self):
        # Pas un pattern protégé → strip standard.
        out = strip_color_nouns("a red apple")
        assert "red" not in out.lower().split()

    def test_bright_color_stripped(self):
        # `bright` sans contexte sémantique protégé → strip standard.
        out = strip_color_nouns("a bright object")
        assert "bright" not in out.lower().split()

    def test_dark_room_stripped(self):
        out = strip_color_nouns("a dark room")
        assert "dark" not in out.lower().split()

    def test_blue_unaffected_by_whitelist(self):
        # Aucun token bleu n'est whitelisté → strip standard.
        out = strip_color_nouns("a blue sphere")
        assert "blue" not in out.lower().split()


class TestStripGlossyTermsWithWhitelistPositive:
    """Tests positifs : `glass` preserved comme contenant."""

    def test_drinking_glass_preserved(self):
        out = strip_glossy_terms("tall drinking glass on the table")
        assert "glass" in out.lower().split()

    def test_tall_glass_preserved(self):
        out = strip_glossy_terms("a tall glass with a striped pattern")
        assert "glass" in out.lower().split()

    def test_glass_of_milk_preserved(self):
        out = strip_glossy_terms("a glass of milk on the counter")
        assert "glass" in out.lower().split()

    def test_glass_of_juice_preserved(self):
        out = strip_glossy_terms("a glass of juice next to the plate")
        assert "glass" in out.lower().split()

    def test_empty_glass_preserved(self):
        out = strip_glossy_terms("an empty glass on a wooden table")
        assert "glass" in out.lower().split()


class TestStripGlossyTermsWithWhitelistNegative:
    """Tests négatifs : `glass` strippé hors contexte contenant."""

    def test_glass_surface_stripped(self):
        out = strip_glossy_terms("a glass surface")
        assert "glass" not in out.lower().split()

    def test_glass_tower_stripped(self):
        # Cas existant `chrome and glass tower` → glass strippé.
        out = strip_glossy_terms("chrome and glass tower")
        assert "glass" not in out.lower().split()

    def test_shiny_metallic_still_stripped(self):
        # Aucun token shiny/metallic whitelisté → strip standard.
        out = strip_glossy_terms("a shiny metallic sphere")
        assert "shiny" not in out.lower().split()
        assert "metallic" not in out.lower().split()


class TestApplyAllFiltersWithWhitelistIntegration:
    """Intégration : composition des filtres respecte la whitelist."""

    def test_grid_cell_round_orange_with_leaf_preserved(self):
        # Cas exact d'un item de `grid_cell_contents.json` (fruits_basket).
        out = apply_all_filters("round orange with leaf")
        assert "orange" in out.lower().split()
        assert "leaf" in out.lower().split()

    def test_grid_cell_drinking_glass_preserved(self):
        # Cas d'un item maison (`tall drinking glass`).
        out = apply_all_filters("tall drinking glass")
        assert "glass" in out.lower().split()
        assert "drinking" in out.lower().split()

    def test_grid_cell_glass_of_milk_preserved(self):
        out = apply_all_filters("a glass of milk on a tray")
        assert "glass" in out.lower().split()
        assert "milk" in out.lower().split()

    def test_grid_cell_round_orange_with_dimpled_skin_preserved(self):
        out = apply_all_filters("round orange with dimpled skin")
        assert "orange" in out.lower().split()

    def test_full_pipeline_keeps_orange_fruit_strips_extras(self):
        # Mix : on doit garder `orange` (fruit) mais stripper `red`/`shiny`.
        out = apply_all_filters("a shiny red round orange with leaf").lower()
        assert "orange" in out.split()
        assert "red" not in out.split()
        assert "shiny" not in out.split()

    def test_full_pipeline_strips_color_when_no_protective_context(self):
        # `orange car` : pas de contexte protégé → strip standard.
        out = apply_all_filters("an orange car")
        assert "orange" not in out.lower().split()

    def test_full_pipeline_keeps_bright_idea_strips_other_anchor(self):
        # `bright idea` protégé. `rainbow` reste remplacé en `colorful`.
        out = apply_all_filters("a rainbow with a bright idea")
        assert "bright" in out.lower().split()
        assert "idea" in out.lower().split()
        assert "rainbow" not in out.lower()
        assert "colorful" in out.lower()

    def test_full_pipeline_neutral_text_unchanged(self):
        # Non-régression — texte sans token ciblé reste inchangé.
        text = "a simple line drawing of a cat"
        assert apply_all_filters(text) == text
