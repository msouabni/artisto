"""Tests pour `src/services/prompt_generator.py`.

Couvre :
- Transfert T9 (profil + orientation directionnelle) pour les 6 leafs résiduels.
- Transfert T25 (Comparatif before/after — états explicites).
- Non-régression LEAF_OVERRIDES (sheep_with_lamb, eid_al_adha_sheep) prioritaires.
- Non-régression : un leaf hors mapping garde son template Solo animal standard.
- Smoke build_prompt sur quelques cas représentatifs.

Ces tests touchent uniquement la couche template (in-memory) — pas de DB ni HTTP.
Compatible SQLite-portable / sans Postgres.
"""
from __future__ import annotations

import logging
import sys

import pytest

sys.path.insert(0, "src")

from services.prompt_generator import (  # noqa: E402  (sys.path tweak)
    LEAF_OVERRIDES,
    NEGATIVE_V3,
    PromptGenerator,
    _BEFORE_AFTER_STATES,
    _DIRECTIONAL_OVERRIDES,
    _EXPRESSIVE_FACES,
    _GRID_CELL_CONTENTS,
    _ISOLATION,
    _ISOLATION_HUMAN,
    _ISOLATION_OBJECT,
    _RISKY_BACKWARD_ELEMENTS,
    _detect_emotion,
    _is_t23_singular_face,
    set_before_after_states,
    set_grid_cell_contents,
    template_before_after,
    template_grid_3x3_annotated,
    template_grid_3x3_imagier,
    template_human_plus_entity,
    template_personality_action,
    template_pose_static,
    template_solo_animal,
    template_solo_bird,
    template_solo_expressive_face,
    template_solo_fish,
    template_solo_human,
    template_solo_insect,
    template_solo_object,
    template_solo_reptile,
)


# ---------------------------------------------------------------------------
# T9 — _DIRECTIONAL_OVERRIDES couvrent les 6 leafs résiduels
# ---------------------------------------------------------------------------
RESIDUAL_LEAFS = [
    "bactrian_camel",
    "golden_retriever",
    "mountain_gorilla",
    "playful_dolphin",
    "running_cheetah",
    "running_giraffe",
]


def test_directional_overrides_cover_residual_leafs():
    """Les 6 leafs résiduels doivent tous figurer dans `_DIRECTIONAL_OVERRIDES`."""
    for leaf_id in RESIDUAL_LEAFS:
        assert leaf_id in _DIRECTIONAL_OVERRIDES, (
            f"{leaf_id} manquant dans _DIRECTIONAL_OVERRIDES"
        )


def test_directional_overrides_have_valid_facing():
    """Toutes les entrées doivent avoir `facing` ∈ {left, right}."""
    for leaf_id, payload in _DIRECTIONAL_OVERRIDES.items():
        assert payload["facing"] in {"left", "right"}, (
            f"{leaf_id} : facing invalide ({payload['facing']})"
        )


def test_risky_backward_elements_documented():
    """Le vocabulaire T9 doit rester traçable dans le module pour audit."""
    assert isinstance(_RISKY_BACKWARD_ELEMENTS, tuple)
    assert "tail_ample" in _RISKY_BACKWARD_ELEMENTS
    assert "long_neck" in _RISKY_BACKWARD_ELEMENTS


# ---------------------------------------------------------------------------
# T9 — `template_solo_animal` injecte `facing [direction]` pour les leafs ciblés
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("leaf_id,name_en", [
    ("bactrian_camel", "Bactrian Camel"),
    ("golden_retriever", "Golden Retriever"),
    ("mountain_gorilla", "Mountain Gorilla"),
    ("running_cheetah", "Running Cheetah"),
    ("running_giraffe", "Running Giraffe"),
])
def test_solo_animal_directional_for_residual_leafs(leaf_id, name_en):
    """Pour un leaf résiduel, le positive doit contenir `facing left|right`."""
    leaf = {"id": leaf_id, "name_en": name_en}
    positive = template_solo_animal(leaf, strategy={})
    assert "in profile facing " in positive, positive
    facing = _DIRECTIONAL_OVERRIDES[leaf_id]["facing"]
    assert f"facing {facing}" in positive
    backward = _DIRECTIONAL_OVERRIDES[leaf_id].get("backward")
    if backward:
        assert backward in positive, (
            f"{leaf_id}: clause backward `{backward}` manquante"
        )


def test_solo_fish_directional_for_dolphin():
    """`playful_dolphin` doit basculer sur la formule T9 et NON sur le branch dolphin par défaut."""
    leaf = {"id": "playful_dolphin", "name_en": "Playful Dolphin"}
    positive = template_solo_fish(leaf, strategy={})
    assert "in profile facing left" in positive
    assert "tail and dorsal fin pointing left" in positive
    # On ne doit PAS retomber sur la branche dolphin par défaut
    assert "swimming horizontally" not in positive


# ---------------------------------------------------------------------------
# Non-régression : leaf Solo animal hors mapping garde le template standard
# ---------------------------------------------------------------------------
def test_solo_animal_non_overridden_keeps_default_template():
    """Un leaf banal doit garder `standing in profile, full body view, all four legs`."""
    leaf = {"id": "house_cat", "name_en": "House Cat"}
    positive = template_solo_animal(leaf, strategy={})
    assert "standing in profile" in positive
    assert "all four legs visible on the ground" in positive
    # On n'a pas la formule directionnelle T9
    assert "in profile facing " not in positive


def test_solo_fish_non_overridden_keeps_default_template():
    """Un poisson banal doit garder le branche par défaut (swimming horizontally)."""
    leaf = {"id": "rainbow_trout", "name_en": "Rainbow Trout"}
    positive = template_solo_fish(leaf, strategy={})
    assert "swimming horizontally" in positive
    assert "in profile facing " not in positive


# ---------------------------------------------------------------------------
# Non-régression : LEAF_OVERRIDES prioritaire sur _DIRECTIONAL_OVERRIDES
# ---------------------------------------------------------------------------
def test_leaf_override_priority_sheep_with_lamb():
    """`sheep_with_lamb` doit conserver son LEAF_OVERRIDE manuel (priorité 1)."""
    assert "sheep_with_lamb" in LEAF_OVERRIDES
    assert "sheep_with_lamb" not in _DIRECTIONAL_OVERRIDES


def test_leaf_override_priority_eid_al_adha_sheep():
    """`eid_al_adha_sheep` doit conserver son LEAF_OVERRIDE manuel (priorité 1)."""
    assert "eid_al_adha_sheep" in LEAF_OVERRIDES
    assert "eid_al_adha_sheep" not in _DIRECTIONAL_OVERRIDES


def test_build_prompt_priority_order():
    """Vérifie l'ordre LEAF_OVERRIDES > _DIRECTIONAL_OVERRIDES > template par défaut.

    Smoke test sur le `build_prompt` complet pour l'un des leafs résiduels et pour
    `sheep_with_lamb` (LEAF_OVERRIDE).
    """
    try:
        gen = PromptGenerator()
    except FileNotFoundError:
        pytest.skip("Données prompt_generator non disponibles dans cet environnement.")

    # Cas 1 : leaf résiduel → bascule T9
    if "running_giraffe" in gen.leaf_index:
        result = gen.build_prompt("running_giraffe")
        assert "in profile facing right" in result["positive"]
        assert "neck and tail extended right" in result["positive"]

    # Cas 2 : LEAF_OVERRIDE prioritaire
    if "sheep_with_lamb" in gen.leaf_index:
        result = gen.build_prompt("sheep_with_lamb")
        # La formule T9 ne doit PAS être là — c'est le LEAF_OVERRIDE qui s'applique
        assert "in profile facing" not in result["positive"]
        assert "small lamb outline" in result["positive"]


# ===========================================================================
# T25 — Comparatif before/after (états explicites)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T25
# ===========================================================================
T25_COVERED_LEAFS = [
    # Comparatif before/after OU Solo (10 leafs)
    "rainwater_collection_barrel",
    "kid_recycling_bin_sorting",
    "beach_cleanup_volunteers",
    "compost_bin_in_garden",
    "earth_with_protective_hands",
    "solar_panels_on_roof",
    "polar_bear_on_melting_ice",
    "wind_turbines_on_hill",
    "kid_planting_a_tree",
    "deforestation_before_after",
    # Solo objet ou comparatif (8 leafs)
    "vegetable_garden_at_home",
    "electric_car_charging",
    "reusable_shopping_tote_bag",
    "eco_friendly_house_with_panels",
    "zero_waste_kitchen",
    "bike_to_work_commute",
    "kids_picking_up_litter",
    "reusable_water_bottle",
]


def test_t25_states_cover_min_six_leafs():
    """Brief T25 : couverture minimale de 6 leafs annotés des 2 classes Comparatif."""
    assert len(_BEFORE_AFTER_STATES) >= 6, (
        f"Couverture T25 insuffisante ({len(_BEFORE_AFTER_STATES)} < 6). "
        f"Voir data/prompt_generator/before_after_states.json."
    )


def test_t25_states_have_required_fields():
    """Toutes les entrées doivent fournir before_state ET after_state non vides."""
    for leaf_id, payload in _BEFORE_AFTER_STATES.items():
        assert "before_state" in payload and isinstance(payload["before_state"], str)
        assert "after_state" in payload and isinstance(payload["after_state"], str)
        assert payload["before_state"].strip(), f"{leaf_id}: before_state vide"
        assert payload["after_state"].strip(), f"{leaf_id}: after_state vide"


def test_t25_covers_documented_comparatif_leafs():
    """Les 18 leafs des 2 classes Comparatif annotés en poc-scale-benchmark sont couverts."""
    missing = [lid for lid in T25_COVERED_LEAFS if lid not in _BEFORE_AFTER_STATES]
    assert not missing, f"Leafs Comparatif non couverts par T25 : {missing}"


def test_template_before_after_injects_states_when_present():
    """Si before/after défini → les deux états apparaissent dans le positive,
    et l'antipattern `one single change applied` disparaît."""
    leaf = {"id": "rainwater_collection_barrel", "name_en": "Rainwater Collection Barrel"}
    positive = template_before_after(leaf, strategy={"class": "Comparatif before/after OU Solo"})
    states = _BEFORE_AFTER_STATES["rainwater_collection_barrel"]
    assert states["before_state"] in positive
    assert states["after_state"] in positive
    # L'antipattern T25 doit disparaître quand on est en mode explicite
    assert "one single change applied" not in positive
    assert "in its initial state" not in positive
    # Garde-fous structurels conservés
    assert "BEFORE" in positive
    assert "AFTER" in positive


def test_template_before_after_fallback_logs_warning_when_missing(caplog):
    """Si leaf hors mapping → fallback générique + warning loggé via `logger`."""
    # Snapshot puis purge pour forcer le fallback même si le JSON couvre le leaf
    original = dict(_BEFORE_AFTER_STATES)
    set_before_after_states({})
    try:
        leaf = {"id": "fictional_unknown_comparatif_leaf", "name_en": "Fictional Unknown"}
        with caplog.at_level(logging.WARNING, logger="services.prompt_generator"):
            positive = template_before_after(leaf, strategy={"class": "Comparatif before/after OU Solo"})
        # Comportement actuel conservé en fallback
        assert "fictional unknown in its initial state" in positive
        assert "one single change applied" in positive
        # Warning émis avec le leaf_id
        warning_lines = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("fictional_unknown_comparatif_leaf" in r.getMessage() for r in warning_lines), (
            f"Aucun warning loggé avec le leaf_id manquant. Records: {[r.getMessage() for r in warning_lines]}"
        )
    finally:
        # Restaure le mapping original pour ne pas polluer les autres tests
        set_before_after_states(original)


def test_template_before_after_handles_leaf_id_alias():
    """Le template doit accepter `leaf_id` aussi bien que `id` comme clé."""
    original = dict(_BEFORE_AFTER_STATES)
    set_before_after_states({
        "alias_leaf": {
            "before_state": "an alias before scene",
            "after_state": "an alias after scene",
        }
    })
    try:
        leaf = {"leaf_id": "alias_leaf", "name_en": "Alias Leaf"}
        positive = template_before_after(leaf, strategy={})
        assert "an alias before scene" in positive
        assert "an alias after scene" in positive
    finally:
        set_before_after_states(original)


def test_template_before_after_strategy_none_safe():
    """Un strategy=None ne doit pas casser le fallback (NULL-safe)."""
    original = dict(_BEFORE_AFTER_STATES)
    set_before_after_states({})
    try:
        leaf = {"id": "any_unknown", "name_en": "Any Unknown"}
        # Ne doit pas lever
        positive = template_before_after(leaf, strategy=None)
        assert "BEFORE" in positive
    finally:
        set_before_after_states(original)


# ===========================================================================
# Non-régression : autres templates inchangés (T25 ne doit pas affecter les
# voisins — Solo animal/fish/object/grid/frieze/landscape/multiplane).
# ===========================================================================
def test_t25_does_not_alter_solo_animal_template():
    """Sanity : Solo animal banal continue de produire son template attendu (cf. tests T9)."""
    leaf = {"id": "house_cat", "name_en": "House Cat"}
    positive = template_solo_animal(leaf, strategy={})
    assert "BEFORE" not in positive
    assert "AFTER" not in positive


# ===========================================================================
# T2 + T3 — Grilles : contenu explicite par cellule (+ cellules composées)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T2 + §T3
# ===========================================================================
T2_COVERED_LEAFS = [
    # Grille imagier annoté (haute fréquence baseline 100% incohérent)
    "fruit_imagier_with_names",
    "vegetable_imagier_with_names",
    "weather_imagier_with_names",
    # Imagier différencié OU Solo
    "balanced_lunch_plate",
    "healthy_breakfast_plate",
    # Imagier différencié 3×3
    "fruits_basket",
    "vegetables_basket",
    "bread_and_pastries",
]


def test_t2_grid_cell_contents_cover_min_six_leafs():
    """Brief T2 : couverture minimale de 6 leafs grille à haute fréquence."""
    assert len(_GRID_CELL_CONTENTS) >= 6, (
        f"Couverture T2 insuffisante ({len(_GRID_CELL_CONTENTS)} < 6). "
        f"Voir data/prompt_generator/grid_cell_contents.json."
    )


def test_t2_grid_cells_have_required_fields():
    """Toutes les entrées doivent fournir au moins 1 cellule valide.
    Cellule simple → `item` ; cellule composée → `container` + `items`."""
    for leaf_id, payload in _GRID_CELL_CONTENTS.items():
        assert isinstance(payload.get("cells"), list), f"{leaf_id}: cells absent"
        assert payload["cells"], f"{leaf_id}: cells vide"
        for cell in payload["cells"]:
            if cell.get("composed"):
                assert isinstance(cell.get("container"), str) and cell["container"].strip()
                assert isinstance(cell.get("items"), list) and cell["items"]
            else:
                assert isinstance(cell.get("item"), str) and cell["item"].strip(), (
                    f"{leaf_id}: cellule simple sans item"
                )


def test_t2_covers_documented_grid_leafs():
    """Les leafs Grille à haute fréquence des 4 classes ciblées sont couverts."""
    missing = [lid for lid in T2_COVERED_LEAFS if lid not in _GRID_CELL_CONTENTS]
    assert not missing, f"Leafs Grille non couverts par T2 : {missing}"


def test_template_grid_imagier_injects_cells_when_present():
    """Si grid_cell_contents défini → les cellules nommées apparaissent dans positive,
    et l'antipattern T2 (`each cell contains one different item related to`) disparaît."""
    leaf = {"id": "fruit_imagier_with_names", "name_en": "Fruit Imagier with Names"}
    positive = template_grid_3x3_imagier(leaf, strategy={"class": "Grille imagier annoté"})
    payload = _GRID_CELL_CONTENTS["fruit_imagier_with_names"]
    # Au moins 3 items distinctifs doivent apparaître
    assert "round apple with leaf" in positive
    assert "long curved banana" in positive
    assert "triangular watermelon slice with seeds" in positive
    # L'antipattern T2 doit disparaître quand on est en mode explicite
    assert "each cell contains one different item related to" not in positive
    assert "one drawing of a" not in positive
    # Title injecté
    assert payload["title"] in positive


def test_template_grid_annotated_injects_cells_when_present():
    """T3 — Grille annotée doit aussi injecter les cellules + clause label texte."""
    leaf = {"id": "vegetable_imagier_with_names", "name_en": "Vegetable Imagier with Names"}
    positive = template_grid_3x3_annotated(
        leaf, strategy={"class": "Grille imagier annoté"}
    )
    assert "long pointed carrot with top leaves" in positive
    assert "round broccoli" in positive
    # Clause label texte sous chaque cellule (variante annotée)
    assert "english name written below" in positive
    assert "VEGETABLES" in positive


def test_template_grid_imagier_fallback_logs_warning_when_missing(caplog):
    """Si leaf hors mapping → fallback générique + warning loggé via `logger`."""
    original = dict(_GRID_CELL_CONTENTS)
    set_grid_cell_contents({})
    try:
        leaf = {"id": "fictional_unknown_grid_leaf", "name_en": "Fictional Unknown"}
        with caplog.at_level(logging.WARNING, logger="services.prompt_generator"):
            positive = template_grid_3x3_imagier(
                leaf, strategy={"class": "Imagier différencié 3×3"}
            )
        # Comportement antérieur conservé en fallback (antipattern T2 connu)
        assert "tic-tac-toe game grid" in positive
        # Warning émis avec le leaf_id
        warning_lines = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "fictional_unknown_grid_leaf" in r.getMessage() for r in warning_lines
        ), (
            f"Aucun warning loggé avec le leaf_id manquant. "
            f"Records: {[r.getMessage() for r in warning_lines]}"
        )
    finally:
        set_grid_cell_contents(original)


def test_template_grid_supports_composed_cells_t3():
    """T3 — cellule composée : `container with item1, item2, item3` doit apparaître."""
    original = dict(_GRID_CELL_CONTENTS)
    set_grid_cell_contents({
        "test_composed_grid": {
            "title": "TEST",
            "cells": [
                {"item": "round apple with leaf", "shape": "round"},
                {"composed": True, "container": "wooden basket",
                 "items": ["round apple", "long banana", "small grape cluster"]},
            ] + [{"item": f"item {i}"} for i in range(7)],
        }
    })
    try:
        leaf = {"id": "test_composed_grid", "name_en": "Test Composed Grid"}
        positive = template_grid_3x3_imagier(leaf, strategy={})
        # Cellule simple
        assert "cell 1: round apple with leaf" in positive
        # Cellule composée (T3 — conteneur sémantique)
        assert "cell 2 contains a wooden basket with" in positive
        assert "round apple" in positive
        assert "long banana" in positive
    finally:
        set_grid_cell_contents(original)


# ===========================================================================
# T23 — Solo visage expressif (heuristique dispatch v2)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T23
# ===========================================================================
def test_t23_expressive_faces_table_complete():
    """Brief T23 : la table doit couvrir au moins les 10 émotions documentées."""
    required = {"proud", "sad", "happy", "angry", "surprised", "sleepy",
                "scared", "calm", "excited", "shy"}
    missing = required - set(_EXPRESSIVE_FACES.keys())
    assert not missing, f"Émotions manquantes dans _EXPRESSIVE_FACES : {missing}"


def test_t23_detect_emotion_prefix_only():
    """`_detect_emotion` doit matcher uniquement les préfixes (pas les substrings)."""
    assert _detect_emotion("proud_child_face") == "proud"
    assert _detect_emotion("sad_child_crying") == "sad"
    # Pas un préfixe → None
    assert _detect_emotion("happy_meal") == "happy"  # OK, c'est un préfixe
    assert _detect_emotion("emotion_chart_poster") is None
    assert _detect_emotion("kid_running_outdoors") is None
    assert _detect_emotion("") is None
    assert _detect_emotion(None) is None


def test_t23_dispatch_emotional_singular_leaf():
    """`_is_t23_singular_face` doit retourner l'émotion sur un leaf émotionnel
    + workflow_class éligible."""
    assert _is_t23_singular_face("proud_child_face",
                                 "Imagier annoté 3×3 OU Solo visage") == "proud"
    assert _is_t23_singular_face("sad_child_crying",
                                 "Imagier annoté 3×3 OU Solo visage") == "sad"


def test_t23_dispatch_collective_leaf_stays_grid():
    """Un leaf collectif (`emotion_chart_poster`, `feeling_imagier_with_names`)
    doit RESTER sur le template grille même sur la classe éligible."""
    assert _is_t23_singular_face("emotion_chart_poster",
                                 "Imagier annoté 3×3 OU Solo visage") is None
    assert _is_t23_singular_face("feeling_imagier_with_names",
                                 "Imagier annoté 3×3 OU Solo visage") is None


def test_t23_dispatch_non_eligible_class_stays_grid():
    """Une classe non éligible (Solo animal, Frise…) ne doit pas activer T23
    même si le leaf_id contient une émotion."""
    assert _is_t23_singular_face("happy_dog", "Solo animal") is None
    assert _is_t23_singular_face("proud_lion", "Solo animal") is None


def test_template_solo_expressive_face_injects_emotion_markers():
    """Le template doit injecter les marqueurs visuels propres à l'émotion."""
    leaf = {"id": "proud_child_face", "name_en": "Proud Child Face"}
    positive = template_solo_expressive_face(leaf, strategy={})
    assert "one single child face viewed from the front" in positive
    assert "proud expression" in positive
    # Au moins un marqueur visuel propre à 'proud'
    assert "head held high" in positive
    # Title en capitales
    assert "\"PROUD\"" in positive


def test_build_prompt_t23_bypasses_grid_for_emotional_leaf():
    """Smoke build_prompt complet : `proud_child_face` doit produire le solo expressive
    face (et NON la grille imagier)."""
    try:
        gen = PromptGenerator()
    except FileNotFoundError:
        pytest.skip("Données prompt_generator non disponibles dans cet environnement.")

    if "proud_child_face" not in gen.leaf_index:
        pytest.skip("Leaf proud_child_face absent de la taxonomie.")

    result = gen.build_prompt("proud_child_face")
    pos = result["positive"]
    # Bypass grille → solo expressive face
    assert "one single child face" in pos
    assert "head held high" in pos
    # Grille NE doit pas s'être appliquée
    assert "tic-tac-toe" not in pos


def test_build_prompt_t23_keeps_grid_for_collective_leaf():
    """Smoke build_prompt complet : `emotion_chart_poster` doit RESTER sur la grille
    (mot collectif `chart` détecté)."""
    try:
        gen = PromptGenerator()
    except FileNotFoundError:
        pytest.skip("Données prompt_generator non disponibles dans cet environnement.")

    if "emotion_chart_poster" not in gen.leaf_index:
        pytest.skip("Leaf emotion_chart_poster absent de la taxonomie.")

    result = gen.build_prompt("emotion_chart_poster")
    pos = result["positive"]
    # Doit rester en mode grille (chart est un marqueur collectif)
    assert "tic-tac-toe" in pos
    # NE doit PAS basculer sur expressive face
    assert "one single child face" not in pos


# ===========================================================================
# Non-régression : T2/T3/T23 ne doivent pas affecter les voisins
# (Solo animal/fish, before/after, frieze, etc.)
# ===========================================================================
def test_t2_does_not_alter_solo_animal_template():
    """Sanity : Solo animal banal continue de produire son template attendu."""
    leaf = {"id": "house_cat", "name_en": "House Cat"}
    positive = template_solo_animal(leaf, strategy={})
    assert "tic-tac-toe" not in positive
    assert "cell 1:" not in positive


def test_t23_does_not_break_before_after_template():
    """Sanity : T25 before_after reste fonctionnel après ajout de T23."""
    leaf = {"id": "rainwater_collection_barrel", "name_en": "Rainwater Collection Barrel"}
    positive = template_before_after(
        leaf, strategy={"class": "Comparatif before/after OU Solo"}
    )
    assert "BEFORE" in positive
    assert "AFTER" in positive
    # T23 ne doit pas s'être glissé dans le before/after
    assert "one single child face" not in positive


# ===========================================================================
# Transfert _ISOLATION élargi (humain / objet / humain+entité)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill
#  - T9 : Profil + orientation (déjà couvert pour Solo animal/fish)
#  - Règle générale skill : « Moins de mise en scène = plus de fiabilité »
# Brief : docs/architect/briefs/2026-05-10_brief-transfert-isolation-elargi.md
# ===========================================================================
def test_isolation_suffixes_constants_defined():
    """Les trois variantes _ISOLATION* doivent être disponibles, distinctes et non vides."""
    assert isinstance(_ISOLATION, str) and _ISOLATION.strip()
    assert isinstance(_ISOLATION_HUMAN, str) and _ISOLATION_HUMAN.strip()
    assert isinstance(_ISOLATION_OBJECT, str) and _ISOLATION_OBJECT.strip()
    # Les trois variantes ciblent des familles distinctes — elles doivent différer
    assert _ISOLATION != _ISOLATION_HUMAN
    assert _ISOLATION != _ISOLATION_OBJECT
    assert _ISOLATION_HUMAN != _ISOLATION_OBJECT
    # Le terme « isolated subject » est le marqueur stable partagé
    assert "isolated subject" in _ISOLATION
    assert "isolated subject" in _ISOLATION_HUMAN
    assert "isolated subject" in _ISOLATION_OBJECT


def test_negative_v3_extended_with_anti_multi_humans_and_objects():
    """NEGATIVE_V3 doit contenir les nouveaux termes anti-multi-humains et anti-multi-objets
    (transfert skill 2026-05-10)."""
    expected_human_terms = [
        "multiple people",
        "group of people",
        "second person",
        "person in background",
    ]
    expected_object_terms = [
        "multiple objects",
        "group of objects",
        "second object",
    ]
    for term in expected_human_terms + expected_object_terms:
        assert term in NEGATIVE_V3, f"NEGATIVE_V3 ne contient pas `{term}`"


def test_negative_v3_keeps_legacy_animal_terms():
    """Non-régression : les termes anti-multi-animaux historiques restent présents."""
    legacy_terms = [
        "multiple animals",
        "other animals",
        "companion animal",
        "group of animals",
        "animal in background",
        "second subject",
        "multiple subjects",
    ]
    for term in legacy_terms:
        assert term in NEGATIVE_V3, f"NEGATIVE_V3 a perdu `{term}` (régression)"


# --- Templates humain : _ISOLATION_HUMAN injecté ----------------------------
def test_template_solo_human_injects_isolation_human_suffix():
    """`template_solo_human` doit terminer par le suffixe _ISOLATION_HUMAN."""
    leaf = {"id": "child_reading", "name_en": "Child Reading"}
    positive = template_solo_human(leaf, strategy={})
    assert _ISOLATION_HUMAN in positive
    # Et SURTOUT pas le suffixe animal (qui parlerait d'autres animaux)
    assert _ISOLATION not in positive
    assert _ISOLATION_OBJECT not in positive


def test_template_personality_action_injects_isolation_human_suffix():
    """`template_personality_action` (Scène ou solo personnage, personnalité…) → _ISOLATION_HUMAN."""
    leaf = {"id": "animal_superhero", "name_en": "Animal Superhero"}
    positive = template_personality_action(leaf, strategy={})
    assert _ISOLATION_HUMAN in positive
    assert _ISOLATION not in positive


def test_template_pose_static_injects_isolation_human_suffix():
    """`template_pose_static` (yoga, méditation) → _ISOLATION_HUMAN."""
    leaf = {"id": "yoga_warrior_pose", "name_en": "Warrior Pose"}
    positive = template_pose_static(leaf, strategy={})
    assert _ISOLATION_HUMAN in positive


def test_template_human_plus_entity_injects_isolation_human_suffix():
    """`template_human_plus_entity` doit empêcher l'ajout d'un 3e sujet (cf. brief)."""
    leaf = {"id": "child_with_test_tubes", "name_en": "Child with Test Tubes"}
    positive = template_human_plus_entity(leaf, strategy={})
    assert _ISOLATION_HUMAN in positive


# --- Templates objet : _ISOLATION_OBJECT injecté ----------------------------
def test_template_solo_object_injects_isolation_object_suffix():
    """`template_solo_object` (et toutes les variantes routées dessus) → _ISOLATION_OBJECT."""
    leaf = {"id": "wooden_hammer", "name_en": "Wooden Hammer"}
    positive = template_solo_object(leaf, strategy={})
    assert _ISOLATION_OBJECT in positive
    # Et SURTOUT pas les autres variantes
    assert _ISOLATION not in positive
    assert _ISOLATION_HUMAN not in positive


# --- Non-régression : Solo animal / insect / fish / bird / reptile ---------
# Les 5 templates morphologiques animaux doivent rester sur _ISOLATION (animal),
# pas sur _ISOLATION_HUMAN ou _ISOLATION_OBJECT.
def test_template_solo_animal_keeps_isolation_animal():
    """Non-régression T9 : Solo animal doit conserver _ISOLATION animal."""
    leaf = {"id": "house_cat", "name_en": "House Cat"}
    positive = template_solo_animal(leaf, strategy={})
    assert _ISOLATION in positive
    assert _ISOLATION_HUMAN not in positive
    assert _ISOLATION_OBJECT not in positive


def test_template_solo_insect_keeps_isolation_animal():
    """Non-régression : Solo insect doit conserver _ISOLATION animal."""
    leaf = {"id": "honey_bee", "name_en": "Honey Bee"}
    positive = template_solo_insect(leaf, strategy={})
    assert _ISOLATION in positive
    assert _ISOLATION_HUMAN not in positive
    assert _ISOLATION_OBJECT not in positive


def test_template_solo_fish_keeps_isolation_animal():
    """Non-régression : Solo fish doit conserver _ISOLATION animal."""
    leaf = {"id": "rainbow_trout", "name_en": "Rainbow Trout"}
    positive = template_solo_fish(leaf, strategy={})
    assert _ISOLATION in positive
    assert _ISOLATION_HUMAN not in positive
    assert _ISOLATION_OBJECT not in positive


def test_template_solo_bird_keeps_isolation_animal():
    """Non-régression : Solo bird doit conserver _ISOLATION animal."""
    leaf = {"id": "robin_on_branch", "name_en": "Robin on Branch"}
    positive = template_solo_bird(leaf, strategy={})
    assert _ISOLATION in positive
    assert _ISOLATION_HUMAN not in positive
    assert _ISOLATION_OBJECT not in positive


def test_template_solo_reptile_keeps_isolation_animal():
    """Non-régression : Solo reptile doit conserver _ISOLATION animal."""
    leaf = {"id": "green_iguana", "name_en": "Green Iguana"}
    positive = template_solo_reptile(leaf, strategy={})
    assert _ISOLATION in positive
    assert _ISOLATION_HUMAN not in positive
    assert _ISOLATION_OBJECT not in positive


# --- Non-régression : templates exclus du brief (T25 + grilles) ------------
def test_template_before_after_does_not_inject_isolation_human():
    """T25 (before/after) a sa logique propre — ne doit PAS recevoir _ISOLATION_HUMAN
    ou _ISOLATION_OBJECT. (Le brief exclut explicitement template_before_after.)"""
    leaf = {"id": "rainwater_collection_barrel", "name_en": "Rainwater Collection Barrel"}
    positive = template_before_after(
        leaf, strategy={"class": "Comparatif before/after OU Solo"}
    )
    assert _ISOLATION_HUMAN not in positive
    assert _ISOLATION_OBJECT not in positive


def test_template_grid_imagier_does_not_inject_isolation():
    """T2 (grilles imagier) a sa logique propre — pas de suffixe d'isolation."""
    leaf = {"id": "fruit_imagier_with_names", "name_en": "Fruit Imagier with Names"}
    positive = template_grid_3x3_imagier(leaf, strategy={"class": "Grille imagier annoté"})
    assert _ISOLATION_HUMAN not in positive
    assert _ISOLATION_OBJECT not in positive


# --- Smoke : build_prompt complet propage le suffixe via le pipeline -------
def test_build_prompt_solo_human_propagates_isolation_human():
    """Smoke : build_prompt complet sur un leaf humain doit conserver _ISOLATION_HUMAN
    après FILT (les filtres ne doivent pas le stripper)."""
    try:
        gen = PromptGenerator()
    except FileNotFoundError:
        pytest.skip("Données prompt_generator non disponibles dans cet environnement.")

    # Cherche un leaf routé sur template_solo_human ou variantes
    candidate = None
    for leaf_id, (_root, _sub, _leaf) in gen.leaf_index.items():
        strategy = gen.strategy_index.get(_sub["id"])
        if not strategy:
            continue
        if strategy.get("class") in {
            "Solo humain",
            "Solo humain (générique)",
            "Solo humain + accessoires",
        }:
            candidate = leaf_id
            break
    if candidate is None:
        pytest.skip("Aucun leaf Solo humain disponible dans la taxonomie locale.")

    result = gen.build_prompt(candidate)
    assert _ISOLATION_HUMAN in result["positive"], (
        f"Suffixe _ISOLATION_HUMAN absent du build complet pour {candidate}"
    )
