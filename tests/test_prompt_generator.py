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
    _CANONICAL_OUTFITS,
    _CANONICAL_POSES,
    _DIRECTIONAL_OVERRIDES,
    _EXPRESSIVE_FACES,
    _GRID_CELL_CONTENTS,
    _GROUP_LAYOUTS,
    _ISOLATION,
    _ISOLATION_HUMAN,
    _ISOLATION_OBJECT,
    _NUMBER_PREFIXES,
    _RISKY_BACKWARD_ELEMENTS,
    _detect_emotion,
    _has_number_prefix,
    _is_t23_singular_face,
    set_before_after_states,
    set_canonical_outfits,
    set_canonical_poses,
    set_grid_cell_contents,
    set_group_layouts,
    template_before_after,
    template_frieze_1xN,
    template_grid_3x3_annotated,
    template_grid_3x3_imagier,
    template_group_positioned,
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
    template_indoor_scene_threequarter,
    template_landscape_2plane,
    template_landscape_threequarter,
    _LANDSCAPE_THREEQUARTER_TEMPLATES,
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
    """Si leaf hors mapping → fallback générique + warning loggé via `logger`.

    Revert pivot T25 ex-frieze (2026-05-10) : le wording fallback restaure
    « one single change applied » (antipattern T25 documenté, accepté avec
    warning) suite au revert du pivot Option A.
    Cf. docs/reports/2026-05-10_bench-gate-ernie-verdicts.md.
    """
    # Snapshot puis purge pour forcer le fallback même si le JSON couvre le leaf
    original = dict(_BEFORE_AFTER_STATES)
    set_before_after_states({})
    try:
        leaf = {"id": "fictional_unknown_comparatif_leaf", "name_en": "Fictional Unknown"}
        with caplog.at_level(logging.WARNING, logger="services.prompt_generator"):
            positive = template_before_after(leaf, strategy={"class": "Comparatif before/after OU Solo"})
        # Comportement fallback historique restauré (revert pivot 2026-05-10)
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
# template_frieze_1xN — frise narrative N cellules (autonome).
#
# Décision archi 2026-05-10 — revert pivot T25 sur ex-frieze :
# Le pivot T25 (BEFORE/AFTER générique) ainsi que la réconciliation doublon
# Option A (wrapper unique vers `template_before_after`) ont été retirés. Verdict
# gate ERNIE 2026-05-10 : pivot frieze ❌ No-Go (90% défauts), T25 explicite ✅ Go (0%).
# Les 53 leafs ex-frieze sont classés hors-MEP v0.
# Cf. docs/reports/2026-05-10_bench-gate-ernie-verdicts.md
# Cf. docs/architect/briefs/2026-05-10_brief-revert-pivot-t25-frieze.md
# ===========================================================================
def test_frieze_generates_n_cell_horizontal_row():
    """Frise N cellules (corps historique restauré) : `n` cellules, séparées,
    chacune montre un stade/moment du sujet."""
    leaf = {"id": "spring_blooming_meadow", "name_en": "Spring Blooming Meadow"}
    out = template_frieze_1xN(leaf, strategy={"class": "Frise narrative 1×4"}, n=4)
    # Structure historique : N cellules horizontales
    assert "horizontal row of 4" in out
    assert "rectangular cells" in out
    # Chaque cellule = un stade/moment du sujet
    assert "spring blooming meadow" in out
    assert "stage or moment" in out
    # Dernière cellule = stade final (Insight B)
    assert "rightmost cell shows the final stage" in out
    # Plus de wording before/after (revert pivot)
    assert "BEFORE" not in out
    assert "AFTER" not in out
    assert "several differences hidden inside" not in out


def test_frieze_default_n_is_four():
    """Signature `(leaf, strategy, n=4)` : appel sans `n` doit produire 4 cellules."""
    leaf = {"id": "fictional_leaf", "name_en": "Fictional Leaf"}
    out = template_frieze_1xN(leaf, strategy={"class": "Multi-sujets"})
    assert "horizontal row of 4" in out


def test_frieze_respects_custom_n():
    """`n` paramétrable : 6 cellules génèrent un row de 6."""
    leaf = {"id": "fictional_leaf", "name_en": "Fictional Leaf"}
    out6 = template_frieze_1xN(leaf, strategy={"class": "Multi-sujets"}, n=6)
    assert "horizontal row of 6" in out6
    out3 = template_frieze_1xN(leaf, strategy={"class": "Multi-sujets"}, n=3)
    assert "horizontal row of 3" in out3
    # n différents → prompts différents (autonomie restaurée — plus de wrapper)
    assert out6 != out3


def test_frieze_is_autonomous_not_a_wrapper():
    """Garantie de revert : `template_frieze_1xN` ne délègue plus à
    `template_before_after` (déconnexion wrapper Option A). Les deux templates
    produisent des sorties structurellement différentes."""
    leaf = {"id": "fictional_leaf", "name_en": "Fictional Leaf"}
    original = dict(_BEFORE_AFTER_STATES)
    set_before_after_states({})  # purge → forcer fallback de l'éventuel wrapper résiduel
    try:
        frieze_out = template_frieze_1xN(leaf, strategy={"class": "Multi-sujets"})
        ba_out = template_before_after(leaf, strategy={"class": "Comparatif before/after OU Solo"})
        # Sorties distinctes : frise = N cellules, before_after = 2 cellules BEFORE/AFTER
        assert frieze_out != ba_out
        # Marqueurs structurels distincts
        assert "horizontal row of" in frieze_out
        assert "horizontal row of" not in ba_out
        assert "BEFORE" in ba_out
        assert "BEFORE" not in frieze_out
    finally:
        set_before_after_states(original)


def test_dispatcher_routes_frieze_classes_to_template_frieze_1xN():
    """Smoke routing : les workflow_classes ex-frieze routent vers
    `template_frieze_1xN` (frise autonome restaurée)."""
    from services.prompt_generator import TEMPLATE_DISPATCHER
    frieze_classes = [
        "Frise narrative 1×4",
        "Frise narrative 1×N (pattern X2)",
        "Multi-sujets",
        "Multi-sujets (frise)",
        "Multi-sujets ou Scène",
        "Multi-sujets ou Scène d'action",
    ]
    for cls in frieze_classes:
        assert TEMPLATE_DISPATCHER.get(cls) is template_frieze_1xN, (
            f"Dispatcher pour '{cls}' n'est plus aiguillé vers template_frieze_1xN"
        )


def test_dispatcher_routes_comparatif_classes_to_template_before_after():
    """Smoke routing : les classes Comparatif routent vers `template_before_after`
    (chemin canonique inchangé — T25 explicite Go)."""
    from services.prompt_generator import TEMPLATE_DISPATCHER
    for cls in ["Comparatif before/after OU Solo", "Solo objet ou comparatif"]:
        assert TEMPLATE_DISPATCHER.get(cls) is template_before_after, (
            f"Dispatcher pour '{cls}' n'est plus aiguillé vers template_before_after"
        )


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


# Workflow_classes qui routent vers `template_grid_3x3_imagier` ou
# `template_grid_3x3_annotated` (cf. TEMPLATE_DISPATCHER dans prompt_generator.py).
# Toute leaf cartographiée sous l'une de ces classes DOIT avoir une entrée dans
# data/prompt_generator/grid_cell_contents.json — sinon le runtime fallback
# logge un warning et produit un prompt T2-violant.
_T2_GRID_WORKFLOW_CLASSES = (
    "Grille imagier annoté",
    "Imagier différencié OU Solo",
    "Imagier annoté 3×3 OU Solo visage",
    "Imagier différencié 3×3",
)


def _collect_grid_leafs_from_cartography():
    """Charge cartographie + taxonomy_full, retourne la liste des leaf_ids présents
    sous une sous-catégorie dont la `production_strategy.class` est dans
    `_T2_GRID_WORKFLOW_CLASSES`."""
    import json
    import pathlib

    base = pathlib.Path(__file__).resolve().parent.parent / "data" / "prompt_generator"
    carto = json.loads((base / "taxonomy_production_cartography.json").read_text(encoding="utf-8"))
    taxo = json.loads((base / "coloring_taxonomy_full.json").read_text(encoding="utf-8"))

    # Index sub_id → workflow_class depuis la cartographie
    sub_classes = {}
    for cat in carto.get("categories", []):
        for sub in cat.get("subcategories", []):
            wf_class = (sub.get("production_strategy") or {}).get("class")
            if wf_class in _T2_GRID_WORKFLOW_CLASSES:
                sub_classes[sub["id"]] = wf_class

    # Parcours taxonomy_full : structure list[root cat → children (sub) → children (leaf)].
    leafs = []
    for cat in taxo:
        for sub in cat.get("children", []):
            sub_id = sub.get("id")
            if sub_id not in sub_classes:
                continue
            for child in sub.get("children", []):
                child_id = child.get("id")
                if child_id:
                    leafs.append((child_id, sub_classes[sub_id]))
    return leafs


def test_t2_grid_cell_contents_covers_all_cartographed_grid_leafs():
    """Couverture exhaustive : chaque leaf_id sous les 4 workflow_classes grille
    doit avoir une entrée dans `grid_cell_contents.json`. Si un nouveau leaf est
    cartographié et qu'aucune entrée JSON n'existe, ce test échoue avec la liste
    des manquants (à ajouter dans `data/prompt_generator/grid_cell_contents.json`)."""
    cartographed = _collect_grid_leafs_from_cartography()
    assert cartographed, (
        "Aucun leaf grille trouvé dans la cartographie — vérifier que "
        "_T2_GRID_WORKFLOW_CLASSES correspond aux libellés de "
        "taxonomy_production_cartography.json."
    )
    missing = [
        f"{lid} (workflow_class={wc})"
        for lid, wc in cartographed
        if lid not in _GRID_CELL_CONTENTS
    ]
    assert not missing, (
        f"Leafs grille cartographiés sans entrée dans grid_cell_contents.json "
        f"({len(missing)}/{len(cartographed)}) : {missing}. "
        f"Ajouter une entrée par leaf manquant dans "
        f"data/prompt_generator/grid_cell_contents.json (schema : voir _doc.schema)."
    )


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


# ===========================================================================
# T22 — Tenues spécialisées : description granulaire
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T22
# ===========================================================================
T22_COVERED_LEAFS = [
    "polo_player",
    "dressage_horse",
    "bungee_jumper",
    "tango_couple",
    "fencer",
    "jockey",
    "archer",
    "surgeon",
]


def test_t22_canonical_outfits_cover_min_eight_leafs():
    """Brief T22 : couverture minimale de 8 leafs annotés `image_anatomie_pb`."""
    assert len(_CANONICAL_OUTFITS) >= 8, (
        f"Couverture T22 insuffisante ({len(_CANONICAL_OUTFITS)} < 8). "
        f"Voir data/prompt_generator/canonical_outfits.json."
    )


def test_t22_outfits_have_required_fields():
    """Toutes les entrées doivent fournir un `outfit_clause` non vide."""
    for leaf_id, payload in _CANONICAL_OUTFITS.items():
        assert isinstance(payload.get("outfit_clause"), str)
        assert payload["outfit_clause"].strip(), f"{leaf_id}: outfit_clause vide"


def test_t22_covers_documented_outfit_leafs():
    """Les leafs documentés dans le brief T22 doivent être couverts."""
    missing = [lid for lid in T22_COVERED_LEAFS if lid not in _CANONICAL_OUTFITS]
    assert not missing, f"Leafs T22 non couverts : {missing}"


def test_t22_outfits_avoid_color_nouns():
    """Les outfit_clauses ne doivent pas contenir de noms de couleur explicites
    (FILT _COLOR_NOUNS strippe red/white/blue/etc. — l'outfit serait amputé)."""
    forbidden = {
        "red", "blue", "green", "yellow", "white", "black", "pink", "orange",
        "purple", "brown",
    }
    for leaf_id, payload in _CANONICAL_OUTFITS.items():
        words = set(payload["outfit_clause"].lower().split())
        # nettoyage simple ponctuation
        cleaned = {w.strip(",.;:") for w in words}
        intersect = cleaned & forbidden
        assert not intersect, (
            f"{leaf_id}: outfit_clause contient des noms de couleur strippés par FILT : {intersect}"
        )


def test_template_solo_human_t22_injects_outfit_when_present():
    """`bungee_jumper` doit recevoir la tenue granulaire (T22)."""
    leaf = {"id": "bungee_jumper", "name_en": "Bungee Jumper"}
    positive = template_solo_human(leaf, strategy={})
    payload = _CANONICAL_OUTFITS["bungee_jumper"]
    assert payload["outfit_clause"] in positive
    # Le bare nom ne doit pas s'afficher seul (`one single bungee jumper` est
    # remplacé par le subject_clause + outfit_clause)
    assert "harness around the chest and waist" in positive
    # _ISOLATION_HUMAN doit toujours être là
    assert _ISOLATION_HUMAN in positive


def test_template_solo_human_t22_fallback_no_outfit():
    """Un leaf non listé dans `_CANONICAL_OUTFITS` doit garder son template standard."""
    leaf = {"id": "child_reading", "name_en": "Child Reading"}
    positive = template_solo_human(leaf, strategy={})
    # Comportement antérieur conservé
    assert "one single child reading" in positive
    assert "three-quarter view from the side" in positive
    assert _ISOLATION_HUMAN in positive


def test_template_human_plus_entity_t22_injects_outfit_for_polo_player():
    """`polo_player` doit recevoir la tenue T22 + scène humain+grand animal."""
    leaf = {"id": "polo_player", "name_en": "Polo Player"}
    positive = template_human_plus_entity(leaf, strategy={"class": "Humain + entité (cheval)"})
    payload = _CANONICAL_OUTFITS["polo_player"]
    assert payload["outfit_clause"] in positive
    # Règles humain+grand animal (T22)
    assert "the horse much larger than the player" in positive or "the horse much larger" in positive
    assert "in profile" in positive  # le cheval est en profil
    assert "all four legs clearly separated" in positive
    # _ISOLATION_HUMAN conservé
    assert _ISOLATION_HUMAN in positive


def test_template_human_plus_entity_t22_fallback_no_outfit():
    """Un leaf hors mapping doit garder le template asymetric scene générique."""
    leaf = {"id": "child_with_test_tubes", "name_en": "Child with Test Tubes"}
    positive = template_human_plus_entity(leaf, strategy={"class": "Humain + entité"})
    assert "asymmetric scene of" in positive
    assert _ISOLATION_HUMAN in positive


# ===========================================================================
# T27 — Pose canonique vs pose forcée
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T27
# ===========================================================================
T27_COVERED_LEAFS = [
    "captain_marvel",
    "rapunzel_with_long_hair",
    "lamine_yamal_cartoon",
    "rafael_nadal_cartoon",
]


def test_t27_canonical_poses_cover_min_four_leafs():
    """Brief T27 : couverture minimale de 4 personnalités annotées."""
    assert len(_CANONICAL_POSES) >= 4, (
        f"Couverture T27 insuffisante ({len(_CANONICAL_POSES)} < 4). "
        f"Voir data/prompt_generator/canonical_poses.json."
    )


def test_t27_poses_have_required_fields():
    """Toutes les entrées doivent fournir une `pose_clause` non vide."""
    for leaf_id, payload in _CANONICAL_POSES.items():
        assert isinstance(payload.get("pose_clause"), str)
        assert payload["pose_clause"].strip(), f"{leaf_id}: pose_clause vide"


def test_t27_covers_documented_personality_leafs():
    """Les 4 personnalités documentées dans le brief sont couvertes."""
    missing = [lid for lid in T27_COVERED_LEAFS if lid not in _CANONICAL_POSES]
    assert not missing, f"Leafs T27 non couverts : {missing}"


def test_template_personality_action_t27_replaces_mid_action_when_present():
    """`captain_marvel` doit recevoir sa pose canonique et perdre l'antipattern T27."""
    leaf = {"id": "captain_marvel", "name_en": "Captain Marvel"}
    positive = template_personality_action(
        leaf, strategy={"class": "Solo humain (personnalité)"}
    )
    payload = _CANONICAL_POSES["captain_marvel"]
    assert payload["pose_clause"] in positive
    # L'antipattern T27 doit disparaître
    assert "mid-action" not in positive
    assert "dynamic pose with motion lines" not in positive
    assert "focused expression" not in positive
    # _ISOLATION_HUMAN conservé
    assert _ISOLATION_HUMAN in positive


def test_template_personality_action_t27_replaces_for_cartoon_personalities():
    """`lamine_yamal_cartoon` et `rafael_nadal_cartoon` doivent aussi basculer T27."""
    for leaf_id in ("lamine_yamal_cartoon", "rafael_nadal_cartoon"):
        leaf = {"id": leaf_id, "name_en": leaf_id.replace("_", " ").title()}
        positive = template_personality_action(
            leaf, strategy={"class": "Solo humain (personnalité) + action figée"}
        )
        assert "mid-action" not in positive, f"{leaf_id}: antipattern T27 résiduel"
        assert _CANONICAL_POSES[leaf_id]["pose_clause"] in positive


def test_template_personality_action_t27_fallback_logs_warning_for_named_personality(caplog):
    """Si leaf personnalité (`*_cartoon` ou classe personnalité) hors mapping →
    fallback antipattern + warning."""
    original = dict(_CANONICAL_POSES)
    set_canonical_poses({})
    try:
        leaf = {"id": "fictional_singer_cartoon", "name_en": "Fictional Singer"}
        with caplog.at_level(logging.WARNING, logger="services.prompt_generator"):
            positive = template_personality_action(
                leaf, strategy={"class": "Solo humain (personnalité)"}
            )
        # Antipattern v9 conservé en fallback
        assert "mid-action" in positive
        assert "motion lines" in positive
        # Warning explicite
        warning_lines = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("fictional_singer_cartoon" in r.getMessage() for r in warning_lines), (
            f"Warning T27 manquant. Records: {[r.getMessage() for r in warning_lines]}"
        )
    finally:
        set_canonical_poses(original)


def test_template_personality_action_t27_no_warning_for_generic_class():
    """Sur une classe générique (`Scène ou solo personnage`) sans `_cartoon` dans le
    leaf_id, on n'émet pas de warning T27 (cas `animal_superhero`)."""
    original = dict(_CANONICAL_POSES)
    set_canonical_poses({})
    try:
        leaf = {"id": "animal_superhero", "name_en": "Animal Superhero"}
        # Pas de mock de caplog — on vérifie juste que ça ne lève pas
        positive = template_personality_action(
            leaf, strategy={"class": "Scène ou solo personnage"}
        )
        assert "mid-action" in positive  # antipattern conservé en fallback
        assert _ISOLATION_HUMAN in positive
    finally:
        set_canonical_poses(original)


# ===========================================================================
# T30 — Groupe de personnages narratifs (positionnement explicite)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T30
# ===========================================================================
T30_COVERED_LEAFS = [
    "three_little_pigs",
    "spring_chicks_with_mother",
]


def test_t30_group_layouts_cover_min_two_leafs():
    """Brief T30 : couverture minimale de 2 leafs groupe annotés."""
    assert len(_GROUP_LAYOUTS) >= 2, (
        f"Couverture T30 insuffisante ({len(_GROUP_LAYOUTS)} < 2). "
        f"Voir data/prompt_generator/group_layouts.json."
    )


def test_t30_group_layouts_have_required_fields():
    """Toutes les entrées doivent fournir count + characters non vide,
    chaque character avec position + attribute."""
    for leaf_id, payload in _GROUP_LAYOUTS.items():
        assert isinstance(payload.get("count"), int) and payload["count"] >= 2
        chars = payload.get("characters")
        assert isinstance(chars, list) and chars, f"{leaf_id}: characters vide"
        for ch in chars:
            assert isinstance(ch.get("position"), str) and ch["position"].strip()
            assert isinstance(ch.get("attribute"), str) and ch["attribute"].strip()


def test_t30_covers_documented_group_leafs():
    """Les 2 leafs documentés dans le brief sont couverts."""
    missing = [lid for lid in T30_COVERED_LEAFS if lid not in _GROUP_LAYOUTS]
    assert not missing, f"Leafs T30 non couverts : {missing}"


def test_t30_number_prefixes_constants_defined():
    """`_NUMBER_PREFIXES` doit contenir les préfixes documentés dans le brief."""
    expected = {"three_", "four_", "five_", "six_", "seven_", "eight_",
                "nine_", "ten_", "twelve_"}
    assert expected.issubset(set(_NUMBER_PREFIXES)), (
        f"Préfixes manquants dans _NUMBER_PREFIXES : {expected - set(_NUMBER_PREFIXES)}"
    )


def test_t30_has_number_prefix_detection():
    """`_has_number_prefix` matche correctement (préfixe seul, pas substring)."""
    assert _has_number_prefix("three_little_pigs") is True
    assert _has_number_prefix("seven_dwarfs") is True
    assert _has_number_prefix("twelve_apostles") is True
    # Pas un préfixe → False
    assert _has_number_prefix("spring_chicks_with_mother") is False
    assert _has_number_prefix("house_cat") is False
    assert _has_number_prefix("") is False
    assert _has_number_prefix(None) is False


def test_template_group_positioned_three_little_pigs():
    """`three_little_pigs` doit produire un positive avec « three pigs » + layout
    (et NON « one pig »)."""
    leaf = {"id": "three_little_pigs", "name_en": "The Three Little Pigs"}
    positive = template_group_positioned(leaf, strategy={})
    # Compte explicite
    assert "3 little pigs" in positive
    # Positionnement explicite
    assert "on the left" in positive
    assert "in the middle" in positive
    assert "on the right" in positive
    # Attributs distinctifs (T30)
    assert "bundle of straw" in positive
    assert "wooden planks" in positive
    assert "bricks" in positive
    # Antipattern T30 absent
    assert "mid-action" not in positive
    assert "motion lines" not in positive
    assert "one single pig" not in positive
    # Expression collective T30
    assert "smiling and facing forward" in positive


def test_template_group_positioned_spring_chicks_with_mother():
    """`spring_chicks_with_mother` doit produire un groupe (pas un solo)."""
    leaf = {"id": "spring_chicks_with_mother", "name_en": "Spring Chicks with Mother"}
    positive = template_group_positioned(leaf, strategy={})
    payload = _GROUP_LAYOUTS["spring_chicks_with_mother"]
    # Compte = nb characters
    assert f"{payload['count']} chicks with their mother hen" in positive
    # Au moins une position et un attribut clés
    assert "mother hen" in positive
    assert "small chicks" in positive


def test_template_group_positioned_fallback_solo_when_missing():
    """Si appelé sans entrée _GROUP_LAYOUTS (garde-fou) → fallback solo human."""
    original = dict(_GROUP_LAYOUTS)
    set_group_layouts({})
    try:
        leaf = {"id": "fictional_group", "name_en": "Fictional Group"}
        positive = template_group_positioned(leaf, strategy={})
        # Fallback solo
        assert "one single fictional group" in positive
    finally:
        set_group_layouts(original)


def test_build_prompt_t30_routes_three_little_pigs_to_group_template():
    """Smoke build_prompt complet : `three_little_pigs` doit basculer T30 même si
    sa workflow_class est `Scène ou solo personnage` (template personnage)."""
    try:
        gen = PromptGenerator()
    except FileNotFoundError:
        pytest.skip("Données prompt_generator non disponibles dans cet environnement.")

    if "three_little_pigs" not in gen.leaf_index:
        pytest.skip("Leaf three_little_pigs absent de la taxonomie.")

    result = gen.build_prompt("three_little_pigs")
    pos = result["positive"]
    # Contenu T30
    assert "3 little pigs" in pos
    assert "on the left" in pos
    # Antipattern T27 (mid-action) doit être absent — c'est T30, pas template_personality_action
    assert "mid-action" not in pos
    assert "dynamic pose" not in pos


def test_build_prompt_t30_warns_on_number_prefix_missing(caplog):
    """Smoke : un leaf avec préfixe numéraire NON couvert par group_layouts doit
    émettre un warning (pour PR ultérieure)."""
    try:
        gen = PromptGenerator()
    except FileNotFoundError:
        pytest.skip("Données prompt_generator non disponibles dans cet environnement.")

    # On vide group_layouts pour forcer le warning même sur three_little_pigs
    original = dict(_GROUP_LAYOUTS)
    set_group_layouts({})
    try:
        if "three_little_pigs" not in gen.leaf_index:
            pytest.skip("Leaf three_little_pigs absent de la taxonomie.")
        with caplog.at_level(logging.WARNING, logger="services.prompt_generator"):
            gen.build_prompt("three_little_pigs")
        warning_lines = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "three_little_pigs" in r.getMessage()
            and "group_layouts missing" in r.getMessage()
            for r in warning_lines
        ), (
            f"Warning T30 number-prefix manquant. "
            f"Records: {[r.getMessage() for r in warning_lines]}"
        )
    finally:
        set_group_layouts(original)


# ===========================================================================
# Non-régression : T22/T27/T30 ne doivent pas affecter les voisins
# (Solo animal/fish/object/grilles/before-after restent fonctionnels)
# ===========================================================================
def test_t22_t27_t30_do_not_alter_solo_animal_template():
    """Sanity : Solo animal banal continue de produire son template attendu."""
    leaf = {"id": "house_cat", "name_en": "House Cat"}
    positive = template_solo_animal(leaf, strategy={})
    # Aucun marqueur des nouveaux templates
    assert "outfit" not in positive.lower()
    assert "pose_clause" not in positive
    assert "on the left" not in positive
    assert "in the middle" not in positive
    # Standard T9
    assert "standing in profile" in positive


def test_t22_t27_t30_do_not_alter_grid_template():
    """Sanity : grille imagier reste fonctionnelle."""
    leaf = {"id": "fruit_imagier_with_names", "name_en": "Fruit Imagier with Names"}
    positive = template_grid_3x3_imagier(leaf, strategy={"class": "Grille imagier annoté"})
    assert "tic-tac-toe grid" in positive
    # Pas de glissement T30
    assert "smiling and facing forward" not in positive


def test_t22_t27_t30_do_not_alter_before_after_template():
    """Sanity : T25 before/after reste intact."""
    leaf = {"id": "rainwater_collection_barrel", "name_en": "Rainwater Collection Barrel"}
    positive = template_before_after(
        leaf, strategy={"class": "Comparatif before/after OU Solo"}
    )
    assert "BEFORE" in positive
    assert "AFTER" in positive
    # Pas de glissement T22/T27/T30
    assert "outfit" not in positive.lower()


def test_t22_t27_t30_do_not_alter_t9_directional_overrides():
    """Sanity : les 6 leafs résiduels T9 conservent leur formule directionnelle."""
    leaf = {"id": "running_giraffe", "name_en": "Running Giraffe"}
    positive = template_solo_animal(leaf, strategy={})
    assert "in profile facing right" in positive
    assert "neck and tail extended right" in positive


# ---------------------------------------------------------------------------
# T26 + T31 — météo scénique + scènes intérieures (transfert skill 2026-05-10)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T26, §T31
# Brief : docs/architect/briefs/2026-05-10_brief-transfert-T26-T31-meteo-scenes.md
# ---------------------------------------------------------------------------
def test_template_landscape_2plane_no_horizon_line():
    """T26 : `template_landscape_2plane` ne doit plus écrire `divided by a horizon line`.

    Citation skill §T26 : « Remplacer `divided by a horizon line` par
    `viewed from a slight three-quarter angle` ».
    """
    leaf = {"id": "tropical_beach_with_palm_trees", "name_en": "Tropical Beach with Palm Trees"}
    positive = template_landscape_2plane(leaf, strategy={"class": "Scène paysage"})
    assert "divided by a horizon line" not in positive
    assert "the horizon line clearly drawn" not in positive
    assert "three-quarter angle" in positive
    assert "no horizontal dividing line" in positive


def test_template_landscape_threequarter_format():
    """T26+T31 : nouveau template paysage trois-quarts (météo scénique)."""
    leaf = {"id": "sunny_day_with_sun", "name_en": "Sunny Day with Sun"}
    positive = template_landscape_threequarter(leaf, strategy={"class": "Solo objet météo"})
    assert "three-quarter angle" in positive
    assert "background" in positive
    assert "middle ground" in positive
    assert "foreground" in positive
    assert "no horizontal dividing line" in positive
    # Pas de marqueurs solo_object
    assert "one single" not in positive
    assert "isolated subject, no other items nearby" not in positive
    # Pas de "ground line beneath" du solo_object (incohérent météo)
    assert "ground line beneath" not in positive


def test_template_indoor_scene_threequarter_format():
    """T26 : nouveau template scène intérieure trois-quarts."""
    leaf = {"id": "living_room_with_sofa", "name_en": "Living Room with Sofa"}
    positive = template_indoor_scene_threequarter(leaf, strategy={"class": "Scène intérieure"})
    assert "three-quarter perspective" in positive
    assert "foreground" in positive
    assert "midground" in positive
    assert "background" in positive
    assert "no horizon line" in positive
    # Pas de marqueurs solo_object
    assert "one single" not in positive
    assert "isolated subject, no other items nearby" not in positive


def test_landscape_threequarter_templates_constant():
    """La liste de templates qui forcent 1376×768 contient bien les 2 nouveaux."""
    assert "template_landscape_threequarter" in _LANDSCAPE_THREEQUARTER_TEMPLATES
    assert "template_indoor_scene_threequarter" in _LANDSCAPE_THREEQUARTER_TEMPLATES
    # Sanity : pas de fuite vers d'autres templates
    assert "template_solo_object" not in _LANDSCAPE_THREEQUARTER_TEMPLATES
    assert "template_landscape_2plane" not in _LANDSCAPE_THREEQUARTER_TEMPLATES


def test_build_prompt_solo_objet_meteo_routes_to_landscape_threequarter():
    """T31 : `Solo objet météo` ne route plus sur solo_object.

    Le positive ne doit pas contenir la signature solo_object
    (« centered on the page, viewed from a clear three-quarter angle, all main
    features fully visible, simple ground line beneath ») mais doit contenir
    `three-quarter angle` (perspective paysage).
    """
    gen = PromptGenerator()
    result = gen.build_prompt("sunny_day_with_sun")
    assert result["workflow_class"] == "Solo objet météo"
    positive = result["positive"]
    # Pas de signature solo_object
    assert "one single" not in positive
    assert "isolated subject, no other items nearby" not in positive
    assert "ground line beneath" not in positive
    # Signature paysage trois-quarts
    assert "three-quarter angle" in positive
    assert "foreground" in positive


def test_build_prompt_solo_objet_meteo_resolution_1376x768():
    """T31 : météo scénique → 1376×768 (override cartographie 1024×1024)."""
    gen = PromptGenerator()
    for leaf_id in ("sunny_day_with_sun", "thunderstorm_with_lightning",
                    "foggy_morning_landscape", "tornado_in_distance"):
        result = gen.build_prompt(leaf_id)
        assert result["resolution"] == (1376, 768), (
            f"{leaf_id} : résolution {result['resolution']} (attendu (1376, 768))"
        )


def test_build_prompt_scene_interieure_routes_to_indoor_threequarter():
    """T26 : `Scène intérieure` ne route plus sur solo_object."""
    gen = PromptGenerator()
    result = gen.build_prompt("living_room_with_sofa")
    assert result["workflow_class"] == "Scène intérieure"
    positive = result["positive"]
    # Pas de signature solo_object
    assert "one single" not in positive
    assert "isolated subject, no other items nearby" not in positive
    # Signature scène intérieure trois-quarts
    assert "three-quarter perspective" in positive
    assert "midground" in positive


def test_build_prompt_scene_interieure_resolution_1376x768():
    """T26 : scène intérieure → 1376×768 (override cartographie 1024×1024)."""
    gen = PromptGenerator()
    for leaf_id in ("living_room_with_sofa", "hallway_with_coat_rack",
                    "bedroom_with_bed", "kitchen_full_view"):
        result = gen.build_prompt(leaf_id)
        assert result["resolution"] == (1376, 768), (
            f"{leaf_id} : résolution {result['resolution']} (attendu (1376, 768))"
        )


def test_build_prompt_scene_paysage_keeps_landscape_2plane_no_horizon():
    """T26 : `Scène paysage` continue à utiliser landscape_2plane mais sans horizon line."""
    gen = PromptGenerator()
    result = gen.build_prompt("tropical_beach_with_palm_trees")
    assert result["workflow_class"] == "Scène paysage"
    assert result["resolution"] == (1376, 768)
    positive = result["positive"]
    assert "divided by a horizon line" not in positive
    assert "no horizontal dividing line" in positive
    assert "three-quarter angle" in positive


def test_t26_t31_do_not_alter_solo_object_template():
    """Non-régression : `template_solo_object` (autres classes) reste intact."""
    leaf = {"id": "hammer", "name_en": "Hammer"}
    positive = template_solo_object(leaf, strategy={})
    # Signature solo_object préservée
    assert "one hammer centered on the page" in positive
    assert "viewed from a clear three-quarter angle" in positive
    assert "simple ground line beneath" in positive
    assert "isolated subject, no other items nearby" in positive


def test_t26_t31_do_not_alter_solo_animal_template():
    """Non-régression : `template_solo_animal` reste intact (T9)."""
    leaf = {"id": "house_cat", "name_en": "House Cat"}
    positive = template_solo_animal(leaf, strategy={})
    assert "standing in profile" in positive
    # Pas de fuite des nouveaux templates
    assert "three-quarter perspective" not in positive
    assert "midground" not in positive


def test_t26_t31_do_not_alter_solo_objet_resolution_for_other_classes():
    """Non-régression : un solo objet standard (claw_hammer) garde 1024×1024."""
    gen = PromptGenerator()
    # `claw_hammer` est dans la sous-cat tools (Solo objet) → 1024×1024
    result = gen.build_prompt("claw_hammer")
    assert result["workflow_class"] == "Solo objet"
    assert result["resolution"] == (1024, 1024)


def test_t26_t31_do_not_alter_grid_imagier():
    """Non-régression : grille imagier reste fonctionnelle (T2/T3/T23)."""
    leaf = {"id": "fruit_imagier_with_names", "name_en": "Fruit Imagier with Names"}
    positive = template_grid_3x3_imagier(leaf, strategy={"class": "Grille imagier annoté"})
    assert "tic-tac-toe grid" in positive
    # Pas de fuite T26/T31
    assert "three-quarter perspective" not in positive
    assert "midground" not in positive


# ===========================================================================
# T28 + Z1 — Mapping anatomique précis (five_senses) + bascule grille labels
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill §T28, §Z1
# Brief : docs/architect/briefs/2026-05-10_brief-transfert-T28-Z1-anatomique-labels.md
# ===========================================================================
from services.prompt_generator import (  # noqa: E402
    _ANATOMICAL_OVERRIDES,
    _T2T3T23_GRID_AVAILABLE,
    _Z1_GRID_CLASSES,
    _count_anatomical_labels,
    _route_z1_anatomical_labels,
    set_anatomical_overrides,
)
import services.prompt_generator as _pg_mod  # noqa: E402


# T28 — les 5 leafs five_senses ont un override anatomique précis (skill §T28)
T28_LEAFS = [
    "sense_of_sight_eye",
    "sense_of_hearing_ear",
    "sense_of_smell_nose",
    "sense_of_taste_tongue",
    "sense_of_touch_hand",
]


# T28 — signatures attendues (extrait du prompt validé skill, sans STYLE_BLOCK)
T28_SIGNATURES = {
    "sense_of_sight_eye": ("one human eye centered on the page", "SIGHT"),
    "sense_of_hearing_ear": ("one human ear centered on the page", "HEARING"),
    "sense_of_smell_nose": ("one human nose drawn in profile view", "SMELL"),
    "sense_of_taste_tongue": ("one human tongue centered on the page", "TASTE"),
    "sense_of_touch_hand": ("one human hand centered on the page", "TOUCH"),
}


def test_t28_anatomical_overrides_loaded_for_five_senses():
    """T28 : les 5 leafs validés skill sont chargés au démarrage."""
    for leaf_id in T28_LEAFS:
        assert leaf_id in _ANATOMICAL_OVERRIDES, (
            f"{leaf_id} absent de _ANATOMICAL_OVERRIDES — vérifier "
            "data/prompt_generator/anatomical_overrides.json"
        )


@pytest.mark.parametrize("leaf_id", T28_LEAFS)
def test_t28_build_prompt_uses_validated_anatomical_clause(leaf_id):
    """T28 : `build_prompt` injecte la clause skill validée pour les 5 leafs."""
    gen = PromptGenerator()
    result = gen.build_prompt(leaf_id)
    positive = result["positive"]
    sig_subject, sig_title = T28_SIGNATURES[leaf_id]
    assert sig_subject in positive, (
        f"{leaf_id} : signature sujet T28 manquante ({sig_subject!r}) — "
        f"positive={positive[:200]!r}"
    )
    assert f'"{sig_title}"' in positive, (
        f"{leaf_id} : titre T28 majuscules absent ({sig_title!r})"
    )
    # On ne doit JAMAIS retomber sur l'antipattern v4 « one sense of … » brut
    assert "one sense of" not in positive.lower()
    # STYLE_BLOCK toujours présent en tête
    assert positive.startswith("coloring book page for kids")


def test_t28_fallback_warning_when_override_missing(caplog):
    """T28 fallback : un leaf 'organe sensoriel' sans override → warning loggé."""
    gen = PromptGenerator()
    # `five_senses_summary_poster` est en classe "Solo objet (organe sensoriel)"
    # mais n'a pas d'override → on doit voir le warning T28.
    with caplog.at_level(logging.WARNING, logger="services.prompt_generator"):
        result = gen.build_prompt("five_senses_summary_poster")
    assert any(
        "anatomical_overrides missing" in rec.message
        and "five_senses_summary_poster" in rec.message
        for rec in caplog.records
    ), f"Pas de warning T28 trouvé. Records: {[r.message for r in caplog.records]}"
    # Pas de crash : positive est généré (fallback solo_object)
    assert result["positive"]
    assert result["positive"].startswith("coloring book page for kids")


def test_t28_does_not_affect_unrelated_leaf():
    """Non-régression : un leaf hors `_ANATOMICAL_OVERRIDES` garde son template."""
    gen = PromptGenerator()
    # `claw_hammer` (Solo objet, classe différente) → solo_object intact
    result = gen.build_prompt("claw_hammer")
    assert "centered on the page, viewed from a clear three-quarter angle" in result["positive"]
    assert "isolated subject" in result["positive"]


# ---------------------------------------------------------------------------
# Z1 — bascule grille pour Solo objet anatomique + labels (≥4 labels)
# ---------------------------------------------------------------------------

# Z1 — leafs anatomique + labels routés vers grille 3×3
Z1_GRID_LEAFS = [
    "hand_with_fingers_named",
    "foot_with_toes",
    "full_body_with_parts_labelled",
    "child_face_features",
]


def test_z1_grid_classes_contains_anatomique_labels():
    """Z1 : la classe `Solo objet anatomique + labels` est ciblée par défaut."""
    assert "Solo objet anatomique + labels" in _Z1_GRID_CLASSES


def test_z1_count_anatomical_labels_workflow_class_priority():
    """Z1 heuristique : la classe `_Z1_GRID_CLASSES` force ≥4 labels par défaut."""
    assert _count_anatomical_labels(
        "anything", workflow_class="Solo objet anatomique + labels"
    ) >= 4
    # Hors classe ciblée → 1 (mono) sauf pattern leaf_id
    assert _count_anatomical_labels("hammer", workflow_class="Solo objet") == 1


def test_z1_count_anatomical_labels_pattern_named():
    """Z1 heuristique : pattern `_named` / `_labelled` / `_diagram` → ≥4."""
    assert _count_anatomical_labels("hand_with_fingers_named") >= 4
    assert _count_anatomical_labels("full_body_with_parts_labelled") >= 4
    assert _count_anatomical_labels("brain_simple_diagram") >= 4
    assert _count_anatomical_labels("kidneys_with_labels") >= 4
    # Sans pattern → 1
    assert _count_anatomical_labels("lion_in_savanna") == 1


@pytest.mark.parametrize("leaf_id", Z1_GRID_LEAFS)
def test_z1_anatomique_labels_fallback_to_solo_when_flag_false(leaf_id):
    """Z1 : depuis le verdict RETRAIT bench T25 2026-05-10, les leafs `anatomique +
    labels` retombent sur leur template d'origine (flag `_T2T3T23_GRID_AVAILABLE`
    = False par défaut). Plus de bascule grille 3×3 tant que le pivot canal manuel
    n'est pas validé.
    """
    gen = PromptGenerator()
    result = gen.build_prompt(leaf_id)
    assert result["workflow_class"] == "Solo objet anatomique + labels"
    positive = result["positive"]
    # Pas de signature grille 3×3 — fallback actif via le flag
    assert "three rows by three columns" not in positive, (
        f"{leaf_id} : routé vers grille 3×3 alors que le flag est False. "
        f"positive={positive[:200]!r}"
    )
    assert "tic-tac-toe grid" not in positive, (
        f"{leaf_id} : routé vers grille 3×3 alors que le flag est False. "
        f"positive={positive[:200]!r}"
    )


def test_z1_route_helper_returns_grid_when_threshold_met_and_flag_true():
    """Z1 helper unitaire : ≥4 labels + flag forcé True → bascule grille.

    Branche conservée pour la future PR archi qui re-activerait le flag si
    le pivot canal manuel (PIL/SVG) valide un nouveau chemin grille.
    """
    fake_template = lambda leaf, strategy: "fake"  # noqa: E731
    original = _pg_mod._T2T3T23_GRID_AVAILABLE
    _pg_mod._T2T3T23_GRID_AVAILABLE = True
    try:
        routed = _route_z1_anatomical_labels(
            "hand_with_fingers_named",
            "Solo objet anatomique + labels",
            fake_template,
        )
        assert routed.__name__ == "template_grid_3x3_imagier"
    finally:
        _pg_mod._T2T3T23_GRID_AVAILABLE = original


def test_z1_route_helper_keeps_template_below_threshold():
    """Z1 helper unitaire : <4 labels → no-op (template inchangé)."""
    fake_template = lambda leaf, strategy: "fake"  # noqa: E731
    routed = _route_z1_anatomical_labels(
        "hammer", "Solo objet", fake_template,
    )
    assert routed is fake_template


def test_z1_defensive_fallback_when_grid_unavailable(caplog):
    """Z1 garde-fou ERNIE : si `_T2T3T23_GRID_AVAILABLE = False`, fallback +
    warning. Permet une PR archi triviale si la mesure post repasse No-Go.
    """
    fake_template = lambda leaf, strategy: "fake"  # noqa: E731
    original = _pg_mod._T2T3T23_GRID_AVAILABLE
    _pg_mod._T2T3T23_GRID_AVAILABLE = False
    try:
        with caplog.at_level(logging.WARNING, logger="services.prompt_generator"):
            routed = _route_z1_anatomical_labels(
                "hand_with_fingers_named",
                "Solo objet anatomique + labels",
                fake_template,
            )
        # Fallback : on garde le template d'origine
        assert routed is fake_template
        # Warning loggé pour traçabilité
        assert any(
            "Z1 grid bypass disabled" in rec.message
            and "hand_with_fingers_named" in rec.message
            for rec in caplog.records
        ), f"Pas de warning Z1 fallback trouvé. Records: {[r.message for r in caplog.records]}"
    finally:
        _pg_mod._T2T3T23_GRID_AVAILABLE = original


def test_z1_default_flag_is_false():
    """Garde-fou : `_T2T3T23_GRID_AVAILABLE` est False par défaut depuis le verdict
    RETRAIT du bench garde-fou T25 (2026-05-10) — taux_post 75 % vs seuil 37.7 %.

    Le pivot pipeline grille/comparatif vers PIL/SVG est escaladé en T19+ canal
    manuel. Re-passer ce flag à True nécessitera un nouveau verdict humain (PR
    archi triviale) après validation d'un nouveau chemin grille.
    """
    assert _T2T3T23_GRID_AVAILABLE is False


def test_t28_z1_set_anatomical_overrides_helper():
    """Utilitaire test : `set_anatomical_overrides` injecte un mapping custom."""
    original = dict(_ANATOMICAL_OVERRIDES)
    try:
        set_anatomical_overrides({"sense_of_sight_eye": "test clause subject"})
        gen = PromptGenerator()
        result = gen.build_prompt("sense_of_sight_eye")
        assert "test clause subject" in result["positive"]
        # Le clause T28 standard doit avoir été remplacée
        assert "the iris circular in the center" not in result["positive"]
    finally:
        set_anatomical_overrides(original)
