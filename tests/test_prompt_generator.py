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
    PromptGenerator,
    _BEFORE_AFTER_STATES,
    _DIRECTIONAL_OVERRIDES,
    _RISKY_BACKWARD_ELEMENTS,
    set_before_after_states,
    template_before_after,
    template_solo_animal,
    template_solo_fish,
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
