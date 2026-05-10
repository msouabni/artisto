"""
prompt_generator.py — Générateur automatique de prompts pour Alwan Books

Lit la taxonomie + cartographie + SEO et produit des prompts compliants
avec la checklist v2.2 pour ERNIE-Image-Turbo Q8 dans ComfyUI.

USAGE CLI :
    # Générer un prompt pour une feuille
    python prompt_generator.py --leaf lion_in_savanna

    # Générer tous les prompts d'une sous-catégorie en JSON
    python prompt_generator.py --subcategory african_wild_animals --output animals_prompts.json

    # Générer un workflow ComfyUI prêt à charger
    python prompt_generator.py --leaf lion_in_savanna --workflow lion.json

    # Générer pour toutes les feuilles haute confiance volumées
    python prompt_generator.py --batch high_confidence --output batch.json

USAGE API PYTHON :
    from prompt_generator import PromptGenerator
    gen = PromptGenerator()
    result = gen.build_prompt("lion_in_savanna")
    print(result['positive'])
"""

import json
import argparse
import copy
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Hook prophylactique T5+T6+T7 (transfert skill prompt-taxonomy-ecosystem 2026-05-10)
from services.prompt_filters import apply_all_filters as _apply_prompt_filters


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Module-level logger — laisse `setup_logging` (api/workers) configurer les
# handlers root. Ici on émet juste vers le logger nommé.
logger = logging.getLogger(__name__)

# ===================================================================
# CONFIGURATION — chemins par défaut
# ===================================================================
DEFAULT_TAXONOMY = str(PROJECT_ROOT / "data/prompt_generator/coloring_taxonomy_full.json")
DEFAULT_CARTOGRAPHY = str(PROJECT_ROOT / "data/prompt_generator/taxonomy_production_cartography.json")
DEFAULT_SEO = str(PROJECT_ROOT / "data/prompt_generator/coloring_taxonomy_seo.json")
DEFAULT_BEFORE_AFTER_STATES = str(PROJECT_ROOT / "data/prompt_generator/before_after_states.json")
DEFAULT_GRID_CELL_CONTENTS = str(PROJECT_ROOT / "data/prompt_generator/grid_cell_contents.json")
DEFAULT_CANONICAL_OUTFITS = str(PROJECT_ROOT / "data/prompt_generator/canonical_outfits.json")
DEFAULT_CANONICAL_POSES = str(PROJECT_ROOT / "data/prompt_generator/canonical_poses.json")
DEFAULT_GROUP_LAYOUTS = str(PROJECT_ROOT / "data/prompt_generator/group_layouts.json")
DEFAULT_ANATOMICAL_OVERRIDES = str(PROJECT_ROOT / "data/prompt_generator/anatomical_overrides.json")

# Negative prompt v3 (validé Phase H) + isolation clause (fix 2_objets 2026-05-09)
# Élargi 2026-05-10 (transfert skill — brief 2026-05-10_brief-transfert-isolation-elargi.md)
# avec termes anti-multi-humains et anti-multi-objets pour adresser ~12 occurrences
# `image_duplication` non-Solo-animal (humain seul, objet seul, humain+entité).
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — règle générale
# « Moins de mise en scène = plus de fiabilité » + T9 (orientation directionnelle).
NEGATIVE_V3 = (
    "no colors, extra legs, third leg, duplicate limbs, fused legs, "
    "malformed anatomy, wrong number of limbs, six fingers, deformed feet "
    "no motion, no fill colors, no intersection, no change in ink "
    "transparency for different plan only black stroke, "
    "multiple animals, other animals, companion animal, group of animals, "
    "animal in background, second subject, multiple subjects, "
    "multiple people, group of people, second person, person in background, "
    "multiple objects, group of objects, second object"
)

# Bloc style coloriage (immutable §5.2 + 5.3)
STYLE_BLOCK = (
    "coloring book page for kids, black and white line art, "
    "thick clean outlines, no shading, no fill, white background"
)

# ===================================================================
# Suffixes _ISOLATION — fix 2_objets / image_duplication
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill
# - T9 : Profil strict + orientation directionnelle (cf. references/techniques.md §T9)
# - Règle générale (citation textuelle skill — references/techniques.md L582+) :
#   > Moins de mise en scène = plus de fiabilité.
#   > Les contraintes architecturales superflues créent des conflits spatiaux que
#   > le modèle résout en sacrifiant le comptage ou l'orientation des éléments.
#   > Fix : réduire la mise en scène au minimum nécessaire — le support suffit.
#
# Trois variantes adaptées au type de sujet :
# - `_ISOLATION` : Solo animal/insect/fish/bird/reptile (déjà appliqué — zone T9).
# - `_ISOLATION_HUMAN` : Solo humain / Humain+entité / personnalité / pose statique.
# - `_ISOLATION_OBJECT` : Solo objet et variantes routées dessus.
# ===================================================================

# Isolation suffix appended to solo-subject positive prompts (fix 2_objets 2026-05-09)
_ISOLATION = "isolated subject, no other animals or objects nearby"

# Isolation suffix pour templates humains (fix image_duplication 2026-05-10)
_ISOLATION_HUMAN = "isolated subject, no other people or objects nearby"

# Isolation suffix pour templates objet (fix image_duplication 2026-05-10)
_ISOLATION_OBJECT = "isolated subject, no other items nearby"

# Leaf overrides — prompts manuels pour feuilles dont le nom implique plusieurs sujets
# ou dont la génération automatique échoue systématiquement (leaf_id → positive_override)
LEAF_OVERRIDES: dict = {
    # sheep_with_lamb : nom ambigu → on cadre sur la brebis seule avec agneau discret
    "sheep_with_lamb": (
        f"{STYLE_BLOCK}, one single adult sheep standing in profile, full body view, "
        "all four legs visible on the ground, a very small lamb outline tucked close "
        "against the ewe's body (same outline weight, not a separate subject), "
        "simple ground line, off-center composition, friendly expression, "
        + _ISOLATION
    ),
    # eid_al_adha_sheep : contexte religieux → une brebis décorée seule
    "eid_al_adha_sheep": (
        f"{STYLE_BLOCK}, one single decorated sheep standing in profile, full body view, "
        "all four legs visible on the ground, festive ribbon around neck, "
        "simple ground line, off-center composition, friendly expression, "
        + _ISOLATION
    ),
}

# Patterns de leaf_id signalant un risque multi-sujets élevé
# → renforce le négatif avec extra_isolation
_RISKY_MULTI_PATTERNS = (
    "_with_friend", "_with_chicks", "_and_", "_in_anemone",
    "_with_school", "_with_cub", "_with_pup",
)

# ===================================================================
# T9 — Symétrie : éléments s'étendant derrière le sujet
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T9
# Transfert : 2026-05-10 (cf. docs/architect/briefs/2026-05-10_brief-transfert-T9-orientation.md)
#
# Règle citée textuellement :
# > Le modèle perd la cohérence du point de vue sur tout élément qui s'étend derrière
# > le sujet → duplication symétrique. Contraintes de comptage inefficaces.
# > Fix : Profil strict + orientation directionnelle explicite.
# > Formule : one single [sujet] in profile facing [left/right],
# >          [élément] pointing/curving [direction]
#
# Vocabulaire des "éléments arrières" (queue ample, long cou, crinière, fin dorsale,
# membre arrière étendu) qui déclenchent la duplication par symétrie. Conservé en
# référence — actuellement non utilisé pour matching automatique : on s'appuie sur
# _DIRECTIONAL_OVERRIDES (curated par leaf_id) pour rester fidèle au brief T9.
# ===================================================================
_RISKY_BACKWARD_ELEMENTS = (
    "tail_ample",
    "long_neck",
    "mane",
    "dorsal_fin",
    "extended_limb",
)

# Mapping leaf_id → (facing direction, backward element clause)
# - facing : "left" ou "right" — orientation strict profil
# - backward : clause libre type "tail curving right" / None si pas d'élément arrière
#
# Couvre les 6 leafs résiduels post v2 (image_duplication 6/13 → cible <2/13).
# Étendre via PR ultérieure pour d'autres leafs morphologiquement similaires.
_DIRECTIONAL_OVERRIDES: Dict[str, dict] = {
    "bactrian_camel":   {"facing": "right", "backward": "tail curving right"},
    "golden_retriever": {"facing": "left",  "backward": "tail curving left"},
    "mountain_gorilla": {"facing": "right", "backward": None},
    "playful_dolphin":  {"facing": "left",  "backward": "tail and dorsal fin pointing left"},
    "running_cheetah":  {"facing": "right", "backward": "tail extended right"},
    "running_giraffe":  {"facing": "right", "backward": "neck and tail extended right"},
}


def _apply_directional_override(name: str, leaf_id: str, env_clause: str) -> Optional[str]:
    """T9 — construit le positive en profil strict + orientation directionnelle.

    Retourne None si `leaf_id` n'est pas dans `_DIRECTIONAL_OVERRIDES` (caller continue
    avec le template par défaut).

    Args:
        name: nom EN du sujet (déjà lowercased par le template appelant)
        leaf_id: id de la feuille à matcher contre _DIRECTIONAL_OVERRIDES
        env_clause: clause environnement déjà choisie par le template (ground line,
                    water line, etc.) — permet de partager fish vs animal terrestre.

    Returns:
        positive str complet (avec STYLE_BLOCK + _ISOLATION) ou None.
    """
    override = _DIRECTIONAL_OVERRIDES.get(leaf_id)
    if not override:
        return None
    facing = override["facing"]
    backward = override.get("backward")
    backward_clause = f", {backward}" if backward else ""
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name} in profile facing {facing}{backward_clause}, "
        f"full body view, all visible limbs clearly drawn, "
        f"{env_clause}, "
        f"off-center composition, friendly expression, "
        + _ISOLATION
    )


# ===================================================================
# T25 — Jeu des différences / Comparatif before/after (états explicites)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T25
# Transfert : 2026-05-10 (cf. docs/architect/briefs/2026-05-10_brief-transfert-T25-before-after.md)
#
# Règle T25 — Insight C checklist (citation textuelle skill) :
# > Une différence explicite doit être concrète, visuelle et localisée.
# > `tap closed -> tap open + bucket` fonctionne.
# > `one single change applied` est trop vague — modèle reproduit la même scène.
#
# Bug générateur v5 (citation textuelle skill) :
# > Le template comparatif insère `one single change applied` sans décrire le changement.
# > Fix v2 : champ `before_state` et `after_state` explicites dans la cartographie,
# > ou description narrative des deux états dans le prompt.
#
# Implémentation : on charge un dict {leaf_id → {before_state, after_state}} depuis
# data/prompt_generator/before_after_states.json. Si un leaf est trouvé, on injecte les
# deux états dans `template_before_after`. Sinon, fallback comportement actuel + warning.
#
# Garde-fou pivot ERNIE (cf. brief) : si la mesure post-transfert montre un taux
# image_pas_coherente résiduel > 30 %, l'archi reportera le complément en T19+ canal
# manuel (bascule pipeline comparatif en composition PIL 2-tiles).
# ===================================================================
def _load_before_after_states(path: str = DEFAULT_BEFORE_AFTER_STATES) -> Dict[str, dict]:
    """Charge le mapping {leaf_id → {before_state, after_state}} depuis JSON.

    Retourne un dict vide si le fichier n'existe pas ou est invalide — le template
    bascule alors sur le fallback (comportement antérieur + warning loggé).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, IOError, json.JSONDecodeError) as exc:
        logger.warning(
            "before_after_states JSON load failed (path=%s): %s — fallback générique",
            path, exc,
        )
        return {}
    states = data.get("states", {}) if isinstance(data, dict) else {}
    if not isinstance(states, dict):
        return {}
    # Filtre les entrées valides (besoin des deux clés non vides)
    cleaned: Dict[str, dict] = {}
    for leaf_id, payload in states.items():
        if not isinstance(payload, dict):
            continue
        before = payload.get("before_state")
        after = payload.get("after_state")
        if isinstance(before, str) and isinstance(after, str) and before.strip() and after.strip():
            cleaned[leaf_id] = {"before_state": before.strip(), "after_state": after.strip()}
    return cleaned


# Singleton chargé à l'import — coût ~ms (20 entrées). Override via
# `set_before_after_states(...)` côté tests si besoin.
_BEFORE_AFTER_STATES: Dict[str, dict] = _load_before_after_states()


def set_before_after_states(states: Dict[str, dict]) -> None:
    """Injecte un dict de remplacement (utilitaire test). Garde la même contrainte
    de structure que `_load_before_after_states` (champs `before_state` / `after_state`).
    """
    global _BEFORE_AFTER_STATES
    _BEFORE_AFTER_STATES = dict(states or {})


# ===================================================================
# T2 + T3 — Grilles : contenu explicite par cellule + cellules composées
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T2 + §T3
# Transfert : 2026-05-10 (cf. docs/architect/briefs/2026-05-10_brief-transfert-T2T3T23-grille-imagier.md)
#
# Règle T2 (citation textuelle skill) :
# > Ne jamais déléguer le choix du contenu des cellules au modèle.
# > Chaque cellule doit être spécifiée avec sa forme géométrique de base.
# > # ❌ contenu délégué : "each cell contains one different item related to X"
# > # ✅ contenu explicite : "1-round apple with leaf, 2-long pointed carrot, ..."
#
# Règle T3 (citation textuelle skill) :
# > Une cellule peut contenir 3-4 items si introduite par un conteneur sémantique.
# > Conteneur obligatoire — `cell N contains a [conteneur] with [item1], [item2], [item3]`
# > Pas de forme géométrique dans les cellules composées — le conteneur suffit.
#
# Implémentation : on charge un dict {leaf_id → {title, cells: [{item, shape} | {container, items}]}}
# depuis data/prompt_generator/grid_cell_contents.json. Si un leaf est trouvé, on injecte
# les 9 cellules nommées dans le template grille. Sinon : fallback comportement antérieur
# + warning loggé pour traçabilité.
#
# Garde-fou pivot ERNIE (cf. brief) : si la mesure post-transfert montre un taux
# image_pas_coherente résiduel > 30 %, l'archi reportera le complément en T19+ canal
# manuel (bascule pipeline grille en composition PIL/SVG).
# ===================================================================
def _load_grid_cell_contents(path: str = DEFAULT_GRID_CELL_CONTENTS) -> Dict[str, dict]:
    """Charge le mapping {leaf_id → {title, cells: [...]}} depuis JSON.

    Retourne un dict vide si le fichier n'existe pas ou est invalide — les templates
    bascule alors sur le fallback (antipattern T2 connu + warning loggé).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, IOError, json.JSONDecodeError) as exc:
        logger.warning(
            "grid_cell_contents JSON load failed (path=%s): %s — fallback générique",
            path, exc,
        )
        return {}
    states = data.get("states", {}) if isinstance(data, dict) else {}
    if not isinstance(states, dict):
        return {}
    cleaned: Dict[str, dict] = {}
    for leaf_id, payload in states.items():
        if not isinstance(payload, dict):
            continue
        cells = payload.get("cells")
        if not isinstance(cells, list) or len(cells) < 1:
            continue
        # Filtre des cellules valides (item simple OU container+items composé)
        valid_cells = []
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            if cell.get("composed") is True or cell.get("container"):
                container = cell.get("container")
                items = cell.get("items")
                if isinstance(container, str) and container.strip() \
                        and isinstance(items, list) and items:
                    valid_cells.append({
                        "composed": True,
                        "container": container.strip(),
                        "items": [str(i).strip() for i in items if isinstance(i, str) and i.strip()],
                    })
            else:
                item = cell.get("item")
                if isinstance(item, str) and item.strip():
                    valid_cells.append({
                        "composed": False,
                        "item": item.strip(),
                        "shape": cell.get("shape") if isinstance(cell.get("shape"), str) else None,
                    })
        if not valid_cells:
            continue
        title = payload.get("title")
        cleaned[leaf_id] = {
            "title": title.strip() if isinstance(title, str) and title.strip() else None,
            "cells": valid_cells,
        }
    return cleaned


# Singleton chargé à l'import. Override via `set_grid_cell_contents(...)` côté tests.
_GRID_CELL_CONTENTS: Dict[str, dict] = _load_grid_cell_contents()


def set_grid_cell_contents(contents: Dict[str, dict]) -> None:
    """Injecte un dict de remplacement (utilitaire test). Même contrainte de
    structure que `_load_grid_cell_contents`.
    """
    global _GRID_CELL_CONTENTS
    _GRID_CELL_CONTENTS = dict(contents or {})


def _format_grid_cell(idx: int, cell: dict) -> str:
    """Formate une cellule pour injection dans le positive prompt.

    T2 (simple) : `cell N: <shape> <item>` (shape facultatif)
    T3 (composée) : `cell N contains a <container> with <item1>, <item2>, <item3>`
    """
    if cell.get("composed"):
        container = cell["container"]
        items = cell.get("items", [])
        items_clause = ", ".join(items) if items else ""
        return f"cell {idx} contains a {container} with {items_clause}"
    item = cell["item"]
    shape = cell.get("shape")
    # Si shape déjà présent dans l'item (ex: "round apple with leaf"), ne pas dupliquer.
    if shape and shape.lower() not in item.lower():
        return f"cell {idx}: {shape} {item}"
    return f"cell {idx}: {item}"


# ===================================================================
# T23 — Solo visage expressif (emotions_and_expressions)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T23
# Transfert : 2026-05-10 (cf. docs/architect/briefs/2026-05-10_brief-transfert-T2T3T23-grille-imagier.md)
#
# Règle T23 (citation textuelle skill) :
# > Les feuilles à sujet singulier (`proud_child_face`, `sad_child_face`) doivent
# > utiliser le template solo visage expressif, pas le template grille imagier.
# > Heuristique dispatch v2 :
# > - Mots-clés dans leaf_id → `imagier, grid, chart, panel, overview, collection` → grille
# > - Sinon → template solo
#
# Implémentation : avant de router sur `template_grid_3x3_*`, le dispatcher vérifie
# si le leaf_id matche un pattern d'émotion ET une classe « Imagier annoté 3×3 OU
# Solo visage » (ou variantes) → bascule sur `template_solo_expressive_face`.
# Les leafs collectifs (`emotion_chart_poster`, `feeling_imagier_with_names`) restent
# sur la grille car ils contiennent un mot-clé collectif (`chart`, `imagier`).
# ===================================================================
_EXPRESSIVE_FACES: Dict[str, str] = {
    # NB : on évite les ancres FILT (bright/dark/black…) — voir prompt_filters._COLOR_NOUNS.
    # Le skill T23 mentionne `eyes bright` mais FILT strippe « bright » (luminosité = ancre couleur).
    # Adaptation : `wide open eyes` conserve l'idée sans déclencher FILT.
    "proud":     "confident smile, head held high, chest out, wide open eyes, eyebrows slightly raised",
    "sad":       "corners of mouth turned down, drooping eyelids, slight tear in one eye",
    "happy":     "wide smile showing teeth, eyes squinted with joy, raised cheeks",
    "angry":     "furrowed eyebrows pointing down, mouth pressed in a frown, clenched teeth",
    "surprised": "wide round eyes, mouth open in O shape, raised eyebrows",
    "sleepy":    "half-closed eyelids, mouth open in yawn, head slightly tilted",
    "scared":    "wide eyes, mouth in worried oh shape, eyebrows raised in middle",
    "calm":      "eyes gently closed or half-closed, soft smile, relaxed face",
    "excited":   "huge open smile, sparkling eyes, raised eyebrows, slight mouth open",
    "shy":       "slight smile, looking sideways, one hand to the cheek, blushing by simple curves",
    "curious":   "raised eyebrows, slight smile, head tilted to one side, eyes wide open",
}

# Mots-clés "collectif" : si un leaf_id en contient un, on garde le template grille
# même si le leaf contient aussi un mot d'émotion (ex: emotion_chart_poster).
_T23_COLLECTIVE_MARKERS = (
    "imagier", "grid", "chart", "panel", "overview", "collection", "poster",
)

# Workflow_classes pour lesquelles T23 doit s'activer (mixed grille/solo)
_T23_ELIGIBLE_CLASSES = (
    "Imagier annoté 3×3 OU Solo visage",
    "Imagier différencié 3×3 OU Solo visage",  # variante hypothétique
)


def _detect_emotion(leaf_id: str) -> Optional[str]:
    """Retourne le nom de l'émotion détectée dans `leaf_id` (préfixe `<emotion>_`)
    ou None. La détection est restreinte au préfixe pour éviter les faux positifs
    (`happy_meal` ne matche pas, mais `happy_child_smiling` matche).
    """
    if not leaf_id:
        return None
    lid = leaf_id.lower()
    for emotion in _EXPRESSIVE_FACES:
        if lid.startswith(f"{emotion}_"):
            return emotion
    return None


def _is_t23_singular_face(leaf_id: str, workflow_class: Optional[str]) -> Optional[str]:
    """T23 — heuristique dispatch v2.

    Retourne le nom de l'émotion si :
    - workflow_class éligible (mixed grille/solo visage), ET
    - leaf_id préfixé par une émotion connue, ET
    - leaf_id ne contient AUCUN marqueur collectif (chart, imagier, …).

    Sinon retourne None (le caller continue sur le template d'origine = grille).
    """
    if workflow_class not in _T23_ELIGIBLE_CLASSES:
        return None
    emotion = _detect_emotion(leaf_id)
    if not emotion:
        return None
    lid = leaf_id.lower()
    if any(marker in lid for marker in _T23_COLLECTIVE_MARKERS):
        return None
    return emotion


def template_solo_expressive_face(leaf, strategy):
    """T23 — Solo visage expressif (emotions_and_expressions).

    Bascule activée par le dispatcher quand un leaf_id a un préfixe d'émotion connu
    sur une workflow_class mixed grille/solo visage. Le titre dans le visuel reste
    en majuscules pour rester compréhensible côté enfant.
    """
    leaf_id = leaf.get("id") or leaf.get("leaf_id") or ""
    emotion = _detect_emotion(leaf_id)
    if not emotion:
        # Garde-fou : ne devrait pas arriver (le dispatcher a déjà filtré),
        # mais on évite tout KeyError.
        emotion = "calm"
    markers = _EXPRESSIVE_FACES.get(emotion, _EXPRESSIVE_FACES["calm"])
    title = emotion.upper()
    return (
        f"{STYLE_BLOCK}, "
        f"one single child face viewed from the front, "
        f"the child showing a {emotion} expression with {markers}, "
        f"simple shoulders visible at the bottom, "
        f"the title \"{title}\" written in capital letters above the head, "
        f"centered composition"
    )


# ===================================================================
# T22 — Tenues spécialisées : description granulaire
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T22
# Transfert : 2026-05-10 (cf. docs/architect/briefs/2026-05-10_brief-transfert-T22-T27-T30-anatomie.md)
#
# Règle T22 (citation textuelle skill) :
# > Le nom du métier ou du sport n'active pas automatiquement la tenue correcte
# > dans le dataset. Plus la tenue est spécialisée et rare, plus la description
# > doit être granulaire pièce par pièce.
# > Tenues courantes → nom suffit (doctor white coat, chef hat and apron).
# > Tenues rares → décrire pièce par pièce (polo player, fencer, jockey, archer).
#
# Règles humain + grand animal (T22) :
# > 1. Animal `in profile facing left/right` + `all four legs clearly separated`
# > 2. `the animal much larger than the human` — fixe le rapport de taille
# > 3. Tenue du joueur décrite explicitement pièce par pièce
# > 4. `holding [objet] with both hands` — ancre l'accessoire au personnage
#
# NB FILT : les descriptions de tenue n'utilisent PAS de noms de couleur
# (red/white/blue/etc.) — _COLOR_NOUNS strippe ces termes. On décrit la forme
# et la matière (jodhpurs trousers, polo shirt with collar, knee-high riding
# boots, helmet on head) sans nommer les couleurs.
# ===================================================================
def _load_canonical_outfits(path: str = DEFAULT_CANONICAL_OUTFITS) -> Dict[str, dict]:
    """Charge le mapping {leaf_id → {outfit_clause, subject_clause, scene_clause?}} depuis JSON.

    Retourne un dict vide si le fichier n'existe pas ou est invalide — les templates
    bascule alors sur le fallback (comportement antérieur + warning loggé).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, IOError, json.JSONDecodeError) as exc:
        logger.warning(
            "canonical_outfits JSON load failed (path=%s): %s — fallback générique",
            path, exc,
        )
        return {}
    outfits = data.get("outfits", {}) if isinstance(data, dict) else {}
    if not isinstance(outfits, dict):
        return {}
    cleaned: Dict[str, dict] = {}
    for leaf_id, payload in outfits.items():
        if not isinstance(payload, dict):
            continue
        outfit = payload.get("outfit_clause")
        if not (isinstance(outfit, str) and outfit.strip()):
            continue
        subject = payload.get("subject_clause")
        scene = payload.get("scene_clause")
        cleaned[leaf_id] = {
            "outfit_clause": outfit.strip(),
            "subject_clause": subject.strip() if isinstance(subject, str) and subject.strip() else None,
            "scene_clause": scene.strip() if isinstance(scene, str) and scene.strip() else None,
        }
    return cleaned


_CANONICAL_OUTFITS: Dict[str, dict] = _load_canonical_outfits()


def set_canonical_outfits(outfits: Dict[str, dict]) -> None:
    """Injecte un dict de remplacement (utilitaire test). Même contrainte de
    structure que `_load_canonical_outfits`.
    """
    global _CANONICAL_OUTFITS
    _CANONICAL_OUTFITS = dict(outfits or {})


# ===================================================================
# T27 — Pose naturelle vs pose forcée (personnalités cartoonisées)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T27
# Transfert : 2026-05-10 (même brief T22+T27+T30).
#
# Règle T27 (citation textuelle skill) :
# > `mid-action`, `dynamic pose`, `motion lines` génèrent de la crispation
# > quand la pose demandée contredit la représentation dominante du personnage
# > dans le dataset.
# > Fix : Identifier la pose canonique du personnage ou du métier et la décrire
# > naturellement avec des gestes précis plutôt que des instructions de dynamisme.
# > Travailler avec cette pose plutôt que contre elle.
#
# Implémentation : on charge un dict {leaf_id → {subject_name, pose_clause}}.
# Si un leaf est trouvé, `template_personality_action` remplace la formule
# `in mid-action … dynamic pose with motion lines suggesting movement` par
# la pose canonique. Sinon : conserve le comportement antérieur + warning loggé.
# ===================================================================
def _load_canonical_poses(path: str = DEFAULT_CANONICAL_POSES) -> Dict[str, dict]:
    """Charge le mapping {leaf_id → {subject_name, pose_clause}} depuis JSON.

    Retourne un dict vide si le fichier n'existe pas ou est invalide.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, IOError, json.JSONDecodeError) as exc:
        logger.warning(
            "canonical_poses JSON load failed (path=%s): %s — fallback générique",
            path, exc,
        )
        return {}
    poses = data.get("poses", {}) if isinstance(data, dict) else {}
    if not isinstance(poses, dict):
        return {}
    cleaned: Dict[str, dict] = {}
    for leaf_id, payload in poses.items():
        if not isinstance(payload, dict):
            continue
        pose = payload.get("pose_clause")
        if not (isinstance(pose, str) and pose.strip()):
            continue
        subject = payload.get("subject_name")
        cleaned[leaf_id] = {
            "subject_name": subject.strip() if isinstance(subject, str) and subject.strip() else None,
            "pose_clause": pose.strip(),
        }
    return cleaned


_CANONICAL_POSES: Dict[str, dict] = _load_canonical_poses()


def set_canonical_poses(poses: Dict[str, dict]) -> None:
    """Injecte un dict de remplacement (utilitaire test)."""
    global _CANONICAL_POSES
    _CANONICAL_POSES = dict(poses or {})


# ===================================================================
# T30 — Groupe de personnages narratifs (positionnement explicite)
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T30
# Transfert : 2026-05-10 (même brief T22+T27+T30).
#
# Règle T30 (citation textuelle skill) :
# > Un groupe de personnages (conte, famille, équipe) ne peut pas utiliser
# > le template solo. Chaque personnage doit être positionné explicitement
# > avec son attribut distinctif.
# > 1. Position explicite pour chaque personnage — left / middle / right
# > 2. Attribut distinctif par personnage — objet tenu, vêtement, accessoire
# > 3. Supprimé `mid-action`, `motion lines`, `focused expression` — inadaptés aux contes
# > 4. `smiling and facing forward` — expression enfantine naturelle pour les contes
#
# Bug v9 (citation textuelle skill) :
# > Les feuilles représentant un groupe connu (`three_little_pigs`, `three_bears`,
# > `seven_dwarfs`) reçoivent le template solo_human → un seul personnage dessiné
# > ou comptage instable.
# > Fix v2 : détecter les feuilles avec nombre dans le nom (`three_*`, `seven_*`,
# > `twelve_*`) → template group avec positionnement explicite par personnage.
#
# Implémentation : la **présence dans `_GROUP_LAYOUTS`** est l'autorité (liste
# blanche curée). `_NUMBER_PREFIXES` sert d'alerte heuristique pour signaler
# les leafs « numériques » non couverts → fallback solo + warning explicite
# pour qu'ils soient ajoutés au JSON via PR ultérieure.
# ===================================================================
_NUMBER_PREFIXES = (
    "three_", "four_", "five_", "six_", "seven_", "eight_", "nine_",
    "ten_", "eleven_", "twelve_",
)


def _load_group_layouts(path: str = DEFAULT_GROUP_LAYOUTS) -> Dict[str, dict]:
    """Charge le mapping {leaf_id → {count, subject_type, layout, characters, expression?}}.

    Retourne un dict vide si le fichier n'existe pas ou est invalide.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, IOError, json.JSONDecodeError) as exc:
        logger.warning(
            "group_layouts JSON load failed (path=%s): %s — fallback générique",
            path, exc,
        )
        return {}
    groups = data.get("groups", {}) if isinstance(data, dict) else {}
    if not isinstance(groups, dict):
        return {}
    cleaned: Dict[str, dict] = {}
    for leaf_id, payload in groups.items():
        if not isinstance(payload, dict):
            continue
        characters = payload.get("characters")
        if not (isinstance(characters, list) and characters):
            continue
        valid_chars = []
        for ch in characters:
            if not isinstance(ch, dict):
                continue
            pos = ch.get("position")
            attr = ch.get("attribute")
            if isinstance(pos, str) and pos.strip() and isinstance(attr, str) and attr.strip():
                valid_chars.append({"position": pos.strip(), "attribute": attr.strip()})
        if not valid_chars:
            continue
        subject_type = payload.get("subject_type")
        layout = payload.get("layout")
        expression = payload.get("expression")
        count = payload.get("count")
        cleaned[leaf_id] = {
            "count": int(count) if isinstance(count, (int, float)) else len(valid_chars),
            "subject_type": subject_type.strip() if isinstance(subject_type, str) and subject_type.strip() else None,
            "layout": layout.strip() if isinstance(layout, str) and layout.strip() else None,
            "characters": valid_chars,
            "expression": expression.strip() if isinstance(expression, str) and expression.strip() else None,
        }
    return cleaned


_GROUP_LAYOUTS: Dict[str, dict] = _load_group_layouts()


def set_group_layouts(groups: Dict[str, dict]) -> None:
    """Injecte un dict de remplacement (utilitaire test)."""
    global _GROUP_LAYOUTS
    _GROUP_LAYOUTS = dict(groups or {})


def _has_number_prefix(leaf_id: str) -> bool:
    """Vrai si `leaf_id` commence par un préfixe numéraire (T30 heuristique)."""
    if not leaf_id:
        return False
    lid = leaf_id.lower()
    return any(lid.startswith(p) for p in _NUMBER_PREFIXES)


# ===================================================================
# T28 + Z1 — Mapping leaf_id → prompt anatomique précis + bascule grille labels
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T28, §Z1
# Transfert : 2026-05-10 (cf. docs/architect/briefs/2026-05-10_brief-transfert-T28-Z1-anatomique-labels.md)
#
# Règle T28 (citation textuelle skill) :
# > Les feuilles `sense_of_*` ont un `name_en` brut non projetable dans le template
# > solo_object (`one sense of sight eye` → bizarre). Utiliser le sujet anatomique
# > précis avec énumération des composants + titre du sens en majuscules.
# > Bug générateur v4 — name_en brut non projetable :
# > Pour les feuilles à nom composé abstrait (`sense of sight eye`,
# > `sense of smell nose`), le générateur insère le name_en tel quel → sujet
# > syntaxiquement bizarre. Fix v2 : mapping leaf_id → prompt_subject pour la
# > sous-catégorie five_senses.
#
# Règle Z1 (citation textuelle skill) :
# > Le pattern Z1 (coupe transversale + flèches + labels) tient jusqu'à
# > **3 labels maximum** par image. Au-delà → surcharge cognitive modèle → KO.
# > 1-3 labels : pattern Z1 fiable
# > 4-5 labels : surcharge — modèle s'embrouille
# > Fix pour 4+ labels nécessaires :
# > - Basculer sur grille 3×3 — un label par case
#
# Implémentation :
#   1. T28 : `_ANATOMICAL_OVERRIDES[leaf_id]` → si présent, prompt validé clé-en-main
#      injecté en priorité, AVANT le dispatch sur `template_solo_object`.
#   2. Z1 : pour la classe `Solo objet anatomique + labels` (par défaut N≥4 labels
#      attendus — heuristique `_count_anatomical_labels`), bascule vers
#      `template_grid_3x3_imagier` (un label par case). Si le leaf est aussi dans
#      `_ANATOMICAL_OVERRIDES` (T28 prime) → l'override est utilisé.
#
# Garde-fou pivot ERNIE — flag défensif `_T2T3T23_GRID_AVAILABLE` :
#   La bascule Z1 vers grille dépend de la viabilité du pattern grille T2/T3 sur
#   ERNIE (verdict en attente, mesure post-T2T3T23 humaine non encore réalisée).
#   Si le verdict revient No-Go pivot ERNIE : passer ce flag à False (PR archi
#   triviale) → la bascule Z1 retombe gracefully sur `template_solo_object` +
#   warning loggé pour traçabilité. Z1 reste fonctionnel sans grille améliorée.
# ===================================================================
_T2T3T23_GRID_AVAILABLE = True
"""Flag défensif : disponibilité du pattern grille 3×3 (T2+T3+T23) sur ERNIE.

Switcher à `False` si la mesure humaine post-transfert T2T3T23 révèle un taux
`image_pas_coherente` résiduel > 30 % → bascule Z1 retombe sur solo_object +
warning. Permet une PR de switch trivial sans toucher à la logique de routing.
"""


def _load_anatomical_overrides(path: str = DEFAULT_ANATOMICAL_OVERRIDES) -> Dict[str, str]:
    """Charge le mapping {leaf_id → positive_subject_clause} depuis JSON.

    Schéma source (`anatomical_overrides.json`) :
        {"overrides": {"<leaf_id>": {"positive_subject_clause": "<clause>"}}}

    Retourne un dict aplati `{leaf_id: clause}`. Vide si fichier manquant ou
    invalide → bascule fallback (warning loggé côté dispatcher).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, IOError, json.JSONDecodeError) as exc:
        logger.warning(
            "anatomical_overrides JSON load failed (path=%s): %s — fallback générique T28",
            path, exc,
        )
        return {}
    overrides = data.get("overrides", {}) if isinstance(data, dict) else {}
    if not isinstance(overrides, dict):
        return {}
    cleaned: Dict[str, str] = {}
    for leaf_id, payload in overrides.items():
        if not isinstance(payload, dict):
            continue
        clause = payload.get("positive_subject_clause")
        if isinstance(clause, str) and clause.strip():
            cleaned[leaf_id] = clause.strip()
    return cleaned


_ANATOMICAL_OVERRIDES: Dict[str, str] = _load_anatomical_overrides()


def set_anatomical_overrides(overrides: Dict[str, str]) -> None:
    """Injecte un dict {leaf_id → clause} de remplacement (utilitaire test)."""
    global _ANATOMICAL_OVERRIDES
    _ANATOMICAL_OVERRIDES = dict(overrides or {})


# Workflow classes pour lesquelles Z1 considère par défaut N≥4 labels (bascule
# grille). Le contrat de la classe « Solo objet anatomique + labels » implique
# nominalement plusieurs étiquettes (doigts, parties du corps, organes…), au-delà
# du seuil Z1 = 3.
_Z1_GRID_CLASSES = frozenset({
    "Solo objet anatomique + labels",
})


def _count_anatomical_labels(leaf_id: str, workflow_class: Optional[str] = None) -> int:
    """Heuristique Z1 : estimation grossière du nombre de labels attendus.

    Règle (skill §Z1) : 1-3 labels OK pattern Z1 (solo + flèches), 4+ → bascule
    grille 3×3 (un label par case).

    Heuristique :
    - Workflow class dans `_Z1_GRID_CLASSES` → renvoie 4 (au-delà du seuil par
      défaut, car la classe implique nominalement plusieurs labels).
    - Patterns leaf_id `_named`, `_labelled`, `_labels`, `_with_*_named` →
      indicateur de labels multiples → 4 par défaut.
    - Sinon → 1 (mono-label, traité en solo).

    Cette estimation est volontairement conservative : on bascule large vers
    grille pour la classe « anatomique + labels ». Une heuristique plus fine
    (extraction du contenu via `grid_cell_contents.json`) sera ajoutée au
    chargement, dans une PR ultérieure.
    """
    if workflow_class and workflow_class in _Z1_GRID_CLASSES:
        return 4
    if not leaf_id:
        return 1
    lid = leaf_id.lower()
    label_patterns = ("_named", "_labelled", "_labeled", "_labels",
                      "_with_parts", "_diagram")
    if any(p in lid for p in label_patterns):
        return 4
    return 1


def _route_z1_anatomical_labels(
    leaf_id: str,
    workflow_class: Optional[str],
    current_template_fn,
):
    """Applique la règle Z1 : si N labels attendus ≥ 4, bascule vers grille 3×3
    (sous réserve du flag `_T2T3T23_GRID_AVAILABLE`). Sinon → no-op.

    Retourne le `template_fn` à utiliser (potentiellement modifié).

    Garde-fou pivot ERNIE : si `_T2T3T23_GRID_AVAILABLE = False`, on garde le
    template solo_object + warning loggé pour traçabilité (l'archi pourra
    réactiver le flag dans une PR ultérieure si la mesure post repasse Go).
    """
    label_count = _count_anatomical_labels(leaf_id, workflow_class)
    if label_count < 4:
        return current_template_fn
    if not _T2T3T23_GRID_AVAILABLE:
        logger.warning(
            "Z1 grid bypass disabled (_T2T3T23_GRID_AVAILABLE=False) for "
            "leaf_id=%s (workflow_class=%s, labels~=%d) — fallback %s. "
            "Réactiver le flag dans prompt_generator.py si la mesure ERNIE "
            "post-T2T3T23 repasse Go.",
            leaf_id, workflow_class, label_count, current_template_fn.__name__,
        )
        return current_template_fn
    return template_grid_3x3_imagier


# ===================================================================
# WORKFLOW COMFYUI — squelette de base (ERNIE-Turbo Q8)
# ===================================================================
WORKFLOW_TEMPLATE = {
    "id": "auto-generated",
    "revision": 0,
    "last_node_id": 19,
    "last_link_id": 18,
    "nodes": [
        {"id": 10, "type": "UnetLoaderGGUF", "pos": [100, 130], "size": [270, 58],
         "flags": {}, "order": 0, "mode": 0,
         "inputs": [{"localized_name": "unet_name", "name": "unet_name", "type": "COMBO", "widget": {"name": "unet_name"}, "link": None}],
         "outputs": [{"localized_name": "MODÈLE", "name": "MODEL", "type": "MODEL", "links": [12]}],
         "properties": {"Node name for S&R": "UnetLoaderGGUF"},
         "widgets_values": ["ernie-image-turbo-Q8_0.gguf"]},
        {"id": 11, "type": "VAELoader", "pos": [100, 318], "size": [270, 58],
         "flags": {}, "order": 1, "mode": 0,
         "inputs": [{"localized_name": "nom_vae", "name": "vae_name", "type": "COMBO", "widget": {"name": "vae_name"}, "link": None}],
         "outputs": [{"localized_name": "VAE", "name": "VAE", "type": "VAE", "links": [17]}],
         "properties": {"Node name for S&R": "VAELoader"},
         "widgets_values": ["flux2-vae.safetensors"]},
        {"id": 12, "type": "CLIPLoader", "pos": [100, 506], "size": [270, 106],
         "flags": {}, "order": 2, "mode": 0,
         "inputs": [
            {"localized_name": "clip_name", "name": "clip_name", "type": "COMBO", "widget": {"name": "clip_name"}, "link": None},
            {"localized_name": "type", "name": "type", "type": "COMBO", "widget": {"name": "type"}, "link": None},
            {"localized_name": "appareil", "name": "device", "shape": 7, "type": "COMBO", "widget": {"name": "device"}, "link": None}],
         "outputs": [{"localized_name": "CLIP", "name": "CLIP", "type": "CLIP", "links": [10, 11]}],
         "properties": {"Node name for S&R": "CLIPLoader"},
         "widgets_values": ["ministral-3-3b.safetensors", "stable_diffusion", "default"]},
        {"id": 13, "type": "EmptyFlux2LatentImage", "pos": [100, 742], "size": [270, 106],
         "flags": {}, "order": 3, "mode": 0,
         "inputs": [
            {"localized_name": "largeur", "name": "width", "type": "INT", "widget": {"name": "width"}, "link": None},
            {"localized_name": "hauteur", "name": "height", "type": "INT", "widget": {"name": "height"}, "link": None},
            {"localized_name": "taille_lot", "name": "batch_size", "type": "INT", "widget": {"name": "batch_size"}, "link": None}],
         "outputs": [{"localized_name": "LATENT", "name": "LATENT", "type": "LATENT", "links": [15]}],
         "properties": {"Node name for S&R": "EmptyFlux2LatentImage"},
         "widgets_values": [1024, 1024, 1]},
        {"id": 16, "type": "KSampler", "pos": [970, 130], "size": [270, 262],
         "flags": {}, "order": 7, "mode": 0,
         "inputs": [
            {"localized_name": "model", "name": "model", "type": "MODEL", "link": 12},
            {"localized_name": "positive", "name": "positive", "type": "CONDITIONING", "link": 13},
            {"localized_name": "negative", "name": "negative", "type": "CONDITIONING", "link": 14},
            {"localized_name": "latent_image", "name": "latent_image", "type": "LATENT", "link": 15},
            {"localized_name": "seed", "name": "seed", "type": "INT", "widget": {"name": "seed"}, "link": None},
            {"localized_name": "steps", "name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": None},
            {"localized_name": "cfg", "name": "cfg", "type": "FLOAT", "widget": {"name": "cfg"}, "link": None},
            {"localized_name": "sampler_name", "name": "sampler_name", "type": "COMBO", "widget": {"name": "sampler_name"}, "link": None},
            {"localized_name": "scheduler", "name": "scheduler", "type": "COMBO", "widget": {"name": "scheduler"}, "link": None},
            {"localized_name": "denoise", "name": "denoise", "type": "FLOAT", "widget": {"name": "denoise"}, "link": None}],
         "outputs": [{"localized_name": "LATENT", "name": "LATENT", "type": "LATENT", "links": [16]}],
         "properties": {"Node name for S&R": "KSampler"},
         "widgets_values": [12345, "randomize", 8, 1.0, "euler", "normal", 1]},
        {"id": 17, "type": "VAEDecode", "pos": [1340, 130], "size": [151, 46],
         "flags": {}, "order": 8, "mode": 0,
         "inputs": [
            {"localized_name": "échantillons", "name": "samples", "type": "LATENT", "link": 16},
            {"localized_name": "vae", "name": "vae", "type": "VAE", "link": 17}],
         "outputs": [{"localized_name": "IMAGE", "name": "IMAGE", "type": "IMAGE", "links": [18]}],
         "properties": {"Node name for S&R": "VAEDecode"}, "widgets_values": []},
        {"id": 18, "type": "SaveImage", "pos": [1591, 130], "size": [314, 270],
         "flags": {}, "order": 9, "mode": 0,
         "inputs": [
            {"localized_name": "images", "name": "images", "type": "IMAGE", "link": 18},
            {"localized_name": "préfixe_du_nom_de_fichier", "name": "filename_prefix", "type": "STRING", "widget": {"name": "filename_prefix"}, "link": None}],
         "outputs": [], "properties": {}, "widgets_values": ["alwan"]},
        {"id": 15, "type": "CLIPTextEncode", "pos": [470, 460], "size": [400, 200],
         "flags": {}, "order": 6, "mode": 0,
         "inputs": [
            {"localized_name": "clip", "name": "clip", "type": "CLIP", "link": 11},
            {"localized_name": "text", "name": "text", "type": "STRING", "widget": {"name": "text"}, "link": None}],
         "outputs": [{"localized_name": "CONDITIONNEMENT", "name": "CONDITIONING", "type": "CONDITIONING", "links": [14]}],
         "properties": {"Node name for S&R": "CLIPTextEncode"}, "widgets_values": [""]},
        {"id": 14, "type": "CLIPTextEncode", "pos": [470, 130], "size": [400, 200],
         "flags": {}, "order": 5, "mode": 0,
         "inputs": [
            {"localized_name": "clip", "name": "clip", "type": "CLIP", "link": 10},
            {"localized_name": "text", "name": "text", "type": "STRING", "widget": {"name": "text"}, "link": None}],
         "outputs": [{"localized_name": "CONDITIONNEMENT", "name": "CONDITIONING", "type": "CONDITIONING", "links": [13]}],
         "properties": {"Node name for S&R": "CLIPTextEncode"}, "widgets_values": [""]}
    ],
    "links": [
        [10, 12, 0, 14, 0, "CLIP"], [11, 12, 0, 15, 0, "CLIP"],
        [12, 10, 0, 16, 0, "MODEL"], [13, 14, 0, 16, 1, "CONDITIONING"],
        [14, 15, 0, 16, 2, "CONDITIONING"], [15, 13, 0, 16, 3, "LATENT"],
        [16, 16, 0, 17, 0, "LATENT"], [17, 11, 0, 17, 1, "VAE"],
        [18, 17, 0, 18, 0, "IMAGE"]],
    "groups": [], "config": {},
    "extra": {"ds": {"scale": 1.0, "offset": [0, 0]}},
    "version": 0.4
}


# ===================================================================
# TEMPLATES DE PROMPT PAR CLASSE
# ===================================================================
# Chaque template est une fonction qui prend (leaf_data, strategy) et retourne le prompt positif.

def template_solo_animal(leaf, strategy):
    """Solo animal classique (mammifère 4 pattes) avec décor minimal (§6.1).

    T9 (2026-05-10) : pour les leafs avec élément étendu derrière le sujet
    (queue ample, long cou, crinière), on bascule sur profil strict +
    orientation directionnelle via `_DIRECTIONAL_OVERRIDES`.
    """
    name = leaf['name_en'].lower()
    leaf_id = leaf.get('id', '')
    env_clause = "all four legs visible on the ground, simple ground line"
    overridden = _apply_directional_override(name, leaf_id, env_clause)
    if overridden is not None:
        return overridden
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name} standing in profile, full body view, "
        f"all four legs visible on the ground, simple ground line, "
        f"off-center composition, friendly expression, "
        + _ISOLATION
    )


def template_solo_insect(leaf, strategy):
    """Solo insecte / araignée / petite bête — pattes correctes, décor botanique (audit 2026-05-09).

    Compte de pattes adapté au sujet (6 par défaut insecte, 8 araignée, 0 ver/escargot).
    """
    name = leaf['name_en'].lower()
    n = name
    if "spider" in n:
        legs_clause = "eight legs clearly visible"
    elif "snail" in n or "worm" in n:
        legs_clause = "no legs, soft body fully visible"
    elif "scorpion" in n:
        legs_clause = "eight legs and curved tail with stinger clearly visible"
    elif "ant" in n or "bee" in n or "ladybug" in n or "beetle" in n or "mantis" in n or "grasshopper" in n:
        legs_clause = "six legs clearly visible"
    else:
        # Papillons, libellules, etc. — focus sur les ailes
        legs_clause = "six legs and wings spread open clearly visible"
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name}, top view, "
        f"{legs_clause}, "
        f"on a simple leaf or flower, "
        f"off-center composition, friendly expression, "
        + _ISOLATION
    )


def template_solo_fish(leaf, strategy):
    """Solo animal marin (poisson, mammifère marin, céphalopode, crustacé) — pas de pattes (audit 2026-05-09).

    Posture nageant ou posée, pas de "ground line" — water line à la place.

    T9 (2026-05-10) : pour les leafs avec fin dorsale / queue étendue
    (ex: playful_dolphin), on bascule sur profil strict + orientation directionnelle
    via `_DIRECTIONAL_OVERRIDES`. L'override est résolu en premier afin de
    court-circuiter la branche whale/dolphin par défaut.
    """
    name = leaf['name_en'].lower()
    leaf_id = leaf.get('id', '')
    n = name
    if "octopus" in n or "squid" in n or "kraken" in n:
        body_clause = "tentacles spread around the body, side view"
        env_clause = "simple water bubbles around"
    elif "jellyfish" in n:
        body_clause = "bell-shaped body with long flowing tentacles below, side view"
        env_clause = "simple water bubbles around"
    elif "starfish" in n:
        body_clause = "five arms radiating from the center, top view"
        env_clause = "on a simple seabed line"
    elif "crab" in n or "lobster" in n:
        body_clause = "all legs and claws clearly visible, top view"
        env_clause = "on a simple ground line at the bottom"
    elif "turtle" in n:
        body_clause = "shell and four flippers clearly visible, side view, swimming"
        env_clause = "simple water line at bottom"
    elif "seahorse" in n:
        body_clause = "curled tail and dorsal fin clearly visible, side view, upright"
        env_clause = "simple water bubbles around"
    elif "whale" in n or "dolphin" in n or "orca" in n:
        body_clause = "side view, swimming horizontally, fins and tail clearly visible"
        env_clause = "simple water line at bottom"
    else:
        # Poissons standard
        body_clause = "side view, swimming horizontally, fins and tail clearly visible"
        env_clause = "simple water line at bottom"
    overridden = _apply_directional_override(name, leaf_id, env_clause)
    if overridden is not None:
        return overridden
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name}, {body_clause}, "
        f"{env_clause}, "
        f"off-center composition, friendly expression, "
        + _ISOLATION
    )


def template_solo_bird(leaf, strategy):
    """Solo oiseau — bec, plumes, perché ou en vol selon le nom (audit 2026-05-09).

    Insight D : un oiseau « en vol » DOIT préciser explicitement la pose ailes
    déployées, sinon ERNIE rabat sur la pose de repos.
    """
    name = leaf['name_en'].lower()
    n = name
    if "flying" in n or "soaring" in n or "hunting" in n or "running" in n or "rising" in n:
        body_clause = (
            "flying with wings spread open and body horizontal in flight pose, "
            "tail feathers fan visible, beak forward"
        )
        env_clause = "no ground, simple cloud or sky line for context"
    elif "open tail" in n or "peacock" in n:
        body_clause = "standing with tail feathers spread wide open in a fan, three-quarter view, beak visible"
        env_clause = "simple ground line at bottom"
    elif "in cage" in n:
        body_clause = "perched on a horizontal bar inside a simple birdcage outline, side view, beak and tail visible"
        env_clause = "no extra ground, the cage is the frame"
    elif "in lake" in n or "on pond" in n or "in pond" in n:
        body_clause = "standing in shallow water, side view, long legs visible, beak forward, wings folded"
        env_clause = "simple water line crossing the legs"
    elif "in jungle" in n or "with flower" in n or "on branch" in n or "robin" in n or "lovebird" in n:
        body_clause = "perched on a simple branch, three-quarter view, wings folded, tail and beak visible"
        env_clause = "no ground line, branch only"
    else:
        # Défaut : posé au sol
        body_clause = "standing on the ground, three-quarter view, wings folded, tail and beak visible"
        env_clause = "simple ground line at bottom"
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name}, {body_clause}, "
        f"{env_clause}, "
        f"off-center composition, friendly expression, "
        + _ISOLATION
    )


def template_solo_reptile(leaf, strategy):
    """Solo reptile — adapter selon morphologie (tortue / serpent / lézard) (audit 2026-05-09)."""
    name = leaf['name_en'].lower()
    n = name
    if "turtle" in n or "tortoise" in n:
        body_clause = "top view, shell pattern clearly visible, four short legs poking out"
        env_clause = "simple ground line at bottom"
    elif "snake" in n or "serpent" in n or "python" in n or "cobra" in n:
        body_clause = "coiled in a spiral, top view, scales pattern clearly visible, head raised slightly"
        env_clause = "simple ground line at bottom"
    elif "crocodile" in n or "alligator" in n:
        body_clause = "side view, full body horizontal on the ground, four legs and long tail visible, jaws closed"
        env_clause = "simple ground or water line at bottom"
    elif "komodo" in n or "lizard" in n or "gecko" in n or "chameleon" in n or "iguana" in n:
        body_clause = "side view, four legs splayed wide on the ground, tail extended"
        env_clause = "simple ground line at bottom"
    else:
        body_clause = "side view, full body, all visible limbs clearly drawn"
        env_clause = "simple ground line at bottom"
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name}, {body_clause}, "
        f"{env_clause}, "
        f"off-center composition, friendly expression, "
        + _ISOLATION
    )


def template_solo_human(leaf, strategy):
    """Solo humain avec quantification 'one single' (§6.2).

    _ISOLATION_HUMAN (transfert skill 2026-05-10) : suffixe d'isolation injecté
    pour adresser image_duplication sur templates humain (générique, accessoires).
    Source : règle générale skill « Moins de mise en scène = plus de fiabilité ».

    T22 (transfert skill 2026-05-10) : si le leaf est dans `_CANONICAL_OUTFITS`,
    on injecte la description granulaire de la tenue (pièce par pièce) + scène
    canonique. Cible : tenues spécialisées rares (bungee_jumper, tango_couple,
    fencer, jockey, archer, surgeon, scheherazade, sinbad…) où le `name_en`
    brut ne suffit pas à activer la tenue correcte.
    Source : .claude/skills/prompt-taxonomy-ecosystem.skill §T22.
    """
    leaf_id = leaf.get("id") or leaf.get("leaf_id") or ""
    name = leaf["name_en"].lower()

    # T22 — bascule vers description granulaire si tenue canonique connue
    outfit = _CANONICAL_OUTFITS.get(leaf_id)
    if outfit:
        subject = outfit["subject_clause"] or f"one single {name}"
        outfit_clause = outfit["outfit_clause"]
        scene_clause = outfit["scene_clause"]
        if scene_clause:
            return (
                f"{STYLE_BLOCK}, "
                f"{subject}, {outfit_clause}, "
                f"{scene_clause}, "
                f"off-center composition, friendly expression, "
                + _ISOLATION_HUMAN
            )
        return (
            f"{STYLE_BLOCK}, "
            f"{subject}, {outfit_clause}, "
            f"three-quarter view from the side, full body, simple ground line, "
            f"off-center composition, friendly expression, "
            + _ISOLATION_HUMAN
        )

    # Détection action implicite dans le nom de la feuille
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name}, three-quarter view from the side, full body, "
        f"simple ground line, off-center composition, friendly expression, "
        + _ISOLATION_HUMAN
    )


def template_solo_object(leaf, strategy):
    """Solo objet centré (catégorie outils, véhicules, électroménager).

    _ISOLATION_OBJECT (transfert skill 2026-05-10) : suffixe d'isolation injecté
    pour adresser image_duplication sur templates objet (et variantes routées
    dessus : véhicule, drapeau, plante, scène intérieure, pattern…).
    Source : règle générale skill « Moins de mise en scène = plus de fiabilité ».
    """
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"one {name} centered on the page, viewed from a clear three-quarter angle, "
        f"all main features fully visible, simple ground line beneath, "
        f"clean uncluttered composition, "
        + _ISOLATION_OBJECT
    )


def template_human_plus_entity(leaf, strategy):
    """Humain + entité avec formule asymétrie validée (§6.3).

    _ISOLATION_HUMAN (transfert skill 2026-05-10) : on applique l'isolation
    « pas d'autres personnes/objets » même sur la scène duo, pour empêcher
    le modèle d'introduire un troisième sujet dans le décor (cas observé sur
    `child_with_test_tubes`, `house_painter_with_roller`).
    Source : règle générale skill « Moins de mise en scène = plus de fiabilité ».

    T22 (transfert skill 2026-05-10) : si le leaf est dans `_CANONICAL_OUTFITS`,
    on injecte la tenue granulaire + scène humain+grand animal (cheval `in
    profile facing left/right`, `the animal much larger than the human`,
    `holding [objet] with both hands`). Cible : `polo_player`, `dressage_horse`
    (Humain+entité cheval) où le name_en brut ne suffit pas.
    Source : .claude/skills/prompt-taxonomy-ecosystem.skill §T22.
    """
    leaf_id = leaf.get("id") or leaf.get("leaf_id") or ""
    name = leaf["name_en"].lower()

    # T22 — bascule vers description granulaire (tenue + scène humain+grand animal)
    outfit = _CANONICAL_OUTFITS.get(leaf_id)
    if outfit:
        subject = outfit["subject_clause"] or f"one {name}"
        outfit_clause = outfit["outfit_clause"]
        scene_clause = outfit["scene_clause"] or "asymmetric composition, full body of both visible, simple ground line"
        return (
            f"{STYLE_BLOCK}, "
            f"{subject}, {outfit_clause}, "
            f"{scene_clause}, "
            + _ISOLATION_HUMAN
        )

    return (
        f"{STYLE_BLOCK}, "
        f"asymmetric scene of {name}, "
        f"the human positioned on the left side, the other element on the right side, "
        f"both fully visible, the human smiling, asymmetric composition, "
        f"full body of both, simple ground line, "
        + _ISOLATION_HUMAN
    )


def template_personality_action(leaf, strategy):
    """Personnalité nommée en mid-action (Z7 + §6.2).

    _ISOLATION_HUMAN (transfert skill 2026-05-10) : couvre les classes
    « Solo humain (personnalité) », « Solo humain ou animal cartoon »,
    « Scène ou solo personnage », « Solo humain ou créature », routées
    sur ce template. Cas observés : `animal_superhero`, leafs cartoon
    génériques où le modèle ajoute un compagnon.
    Source : règle générale skill « Moins de mise en scène = plus de fiabilité ».

    T27 (transfert skill 2026-05-10) : si le leaf est dans `_CANONICAL_POSES`,
    on remplace la formule `in mid-action … dynamic pose with motion lines
    suggesting movement … focused expression` par la pose canonique
    (gestes précis, tenue décrite). Sinon : conserve l'antipattern v9 + warning
    loggé pour traçabilité.
    Source : .claude/skills/prompt-taxonomy-ecosystem.skill §T27 :
    > `mid-action`, `dynamic pose`, `motion lines` génèrent de la crispation
    > quand la pose demandée contredit la représentation dominante du personnage
    > dans le dataset. Travailler avec la pose canonique plutôt que contre elle.
    """
    leaf_id = leaf.get("id") or leaf.get("leaf_id") or ""
    name = leaf["name_en"]
    # Retire le suffix "Cartoon" si présent
    name = name.replace(" Cartoon", "").replace(" cartoon", "")

    # T27 — bascule vers pose canonique si connue
    pose = _CANONICAL_POSES.get(leaf_id)
    if pose:
        subject_name = pose["subject_name"] or name
        return (
            f"{STYLE_BLOCK}, "
            f"one single {subject_name}, {pose['pose_clause']}, "
            f"two arms total, full body view, "
            f"off-center composition, "
            + _ISOLATION_HUMAN
        )

    # T22 — fallback : si tenue canonique connue mais pas de pose, on bascule sur
    # `template_solo_human` (qui consulte aussi `_CANONICAL_OUTFITS`) — court-circuit
    # de l'antipattern T27 « mid-action » sans crisper l'anatomie.
    if leaf_id in _CANONICAL_OUTFITS:
        return template_solo_human(leaf, strategy)

    # Fallback antipattern v9 : mid-action / dynamic pose / motion lines
    # Warning loggé uniquement si le leaf semble être une personnalité connue
    # (présence de `_cartoon` dans le nom OU classe `personnalité`) — heuristique
    # pour ne pas spammer sur les usages génériques (animal_superhero…).
    is_named_personality = (
        "_cartoon" in leaf_id.lower()
        or "personnalité" in (strategy or {}).get("class", "").lower()
    )
    if is_named_personality:
        logger.warning(
            "canonical_poses missing for personality leaf_id=%s (workflow_class=%s) — "
            "fallback antipattern T27 (mid-action / motion lines). Ajouter une entrée "
            "dans data/prompt_generator/canonical_poses.json.",
            leaf_id, (strategy or {}).get("class"),
        )

    return (
        f"{STYLE_BLOCK}, "
        f"one single {name} in mid-action, viewed from the side, "
        f"dynamic pose with motion lines suggesting movement, "
        f"two arms total, full body view, simple ground line, "
        f"off-center composition, focused expression, "
        + _ISOLATION_HUMAN
    )


def template_group_positioned(leaf, strategy):
    """T30 — Groupe de personnages narratifs (positionnement explicite).

    Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T30
    > Un groupe de personnages (conte, famille, équipe) ne peut pas utiliser
    > le template solo. Chaque personnage doit être positionné explicitement
    > avec son attribut distinctif.

    Pattern T30 :
        [N] [character_type] [layout],
        [character 1 position] [character 1 attribute],
        [character 2 position] [character 2 attribute],
        …
        [expression collective], simple ground line, centered composition

    Si `_GROUP_LAYOUTS[leaf_id]` est défini → injecte les N personnages positionnés.
    Sinon : fallback minimal (le dispatcher ne devrait pas appeler ce template
    sans entrée — garde-fou).
    """
    leaf_id = leaf.get("id") or leaf.get("leaf_id") or ""
    name = leaf["name_en"].lower()
    payload = _GROUP_LAYOUTS.get(leaf_id)

    if not payload:
        # Garde-fou : ne devrait pas arriver (le dispatcher filtre via la présence
        # dans `_GROUP_LAYOUTS`). On loggue + fallback solo.
        logger.warning(
            "template_group_positioned called without group_layouts entry "
            "(leaf_id=%s) — fallback solo human.",
            leaf_id,
        )
        return template_solo_human(leaf, strategy)

    count = payload["count"]
    subject_type = payload["subject_type"] or name
    layout = payload["layout"] or "standing together on a simple ground line"
    chars_clause = ", ".join(
        f"{ch['position']} {ch['attribute']}" for ch in payload["characters"]
    )
    expression = payload["expression"] or f"all {count} smiling and facing forward, full body of all visible"

    return (
        f"{STYLE_BLOCK}, "
        f"{count} {subject_type} {layout}, "
        f"{chars_clause}, "
        f"{expression}, simple ground line, centered composition"
    )


def _build_grid_cells_clause(cells: List[dict]) -> str:
    """Concatène les 9 premières cellules formattées T2/T3 pour injection dans le positive."""
    formatted = [_format_grid_cell(i + 1, c) for i, c in enumerate(cells[:9])]
    return ", ".join(formatted)


def template_grid_3x3_imagier(leaf, strategy):
    """T2/T3 — Grille 3×3 imagier différencié (contenu explicite par cellule).

    Source skill — T2 (citation textuelle) :
    > Ne jamais déléguer le choix du contenu des cellules au modèle.
    > # ❌ contenu délégué : `each cell contains one different item related to X`
    > # ✅ contenu explicite : `cell 1: round apple with leaf, cell 2: long pointed carrot…`

    Si `_GRID_CELL_CONTENTS[leaf_id]` est défini → injecte les 9 cellules nommées (T2).
    Sinon → fallback comportement antérieur (antipattern T2 connu) + warning loggé pour
    traçabilité (le leaf_id manquant doit être ajouté à
    `data/prompt_generator/grid_cell_contents.json` lors d'une PR ultérieure).
    """
    leaf_id = leaf.get("id") or leaf.get("leaf_id")
    name = (leaf.get("name_en") or leaf_id or "").lower()
    name_upper = (leaf.get("name_en") or leaf_id or "").upper()
    payload = _GRID_CELL_CONTENTS.get(leaf_id) if leaf_id else None

    if payload and payload.get("cells"):
        title = payload.get("title") or name_upper
        cells_clause = _build_grid_cells_clause(payload["cells"])
        return (
            f"{STYLE_BLOCK}, "
            f"a tic-tac-toe grid of three rows by three columns making nine empty square cells, "
            f"the grid centered on the page, thick black grid lines, "
            f"the title \"{title}\" written in capital letters above the grid, "
            f"{cells_clause}, "
            f"each item drawn inside its own cell with uniform black line thickness, "
            f"balanced composition"
        )

    # Fallback : leaf non couvert → log + comportement antérieur (antipattern T2 connu)
    logger.warning(
        "grid_cell_contents missing for leaf_id=%s (workflow_class=%s) — "
        "fallback générique T2-violant. Ajouter une entrée dans "
        "data/prompt_generator/grid_cell_contents.json.",
        leaf_id, (strategy or {}).get("class"),
    )
    return (
        f"{STYLE_BLOCK}, "
        f"a tic-tac-toe game grid of three rows by three columns making nine empty square cells, "
        f"the grid centered on the page, "
        f"each cell contains one drawing of a {name} item, "
        f"each cell shows a different item, "
        f"the title \"{name_upper}\" written above the grid"
    )


def template_grid_3x3_annotated(leaf, strategy):
    """T2/T3 — Grille 3×3 imagier annoté (chaque case a son label texte).

    Source skill — T2 + T3 (références dans `_GRID_CELL_CONTENTS` plus haut).
    Variante avec label texte sous chaque cellule (« picture-word imagier »).

    Si `_GRID_CELL_CONTENTS[leaf_id]` est défini → injecte les cellules nommées
    + instruction d'écriture du label sous chaque cellule. Sinon → fallback +
    warning loggé.
    """
    leaf_id = leaf.get("id") or leaf.get("leaf_id")
    name = (leaf.get("name_en") or leaf_id or "").lower()
    name_upper = (leaf.get("name_en") or leaf_id or "").upper()
    payload = _GRID_CELL_CONTENTS.get(leaf_id) if leaf_id else None

    if payload and payload.get("cells"):
        title = payload.get("title") or name_upper
        cells_clause = _build_grid_cells_clause(payload["cells"])
        return (
            f"{STYLE_BLOCK}, "
            f"a tic-tac-toe grid of three rows by three columns making nine empty square cells, "
            f"the grid centered on the page, thick black grid lines, "
            f"the title \"{title}\" written in capital letters above the grid, "
            f"{cells_clause}, "
            f"each item drawn inside its own cell with its english name written below in "
            f"capital letters inside the same cell, uniform black line thickness, "
            f"balanced composition"
        )

    # Fallback : leaf non couvert → log + comportement antérieur (antipattern T2 connu)
    logger.warning(
        "grid_cell_contents missing for leaf_id=%s (workflow_class=%s) — "
        "fallback générique T2-violant. Ajouter une entrée dans "
        "data/prompt_generator/grid_cell_contents.json.",
        leaf_id, (strategy or {}).get("class"),
    )
    return (
        f"{STYLE_BLOCK}, "
        f"a tic-tac-toe game grid of three rows by three columns making nine empty square cells, "
        f"the grid centered on the page, "
        f"each cell contains one drawing of a {name} item with its name written below "
        f"in capital letters inside the same cell, each cell shows a different item, "
        f"the title \"{name_upper}\" written above the grid"
    )


def template_frieze_1xN(leaf, strategy, n=4):
    """Pivot T25 (jeu des différences BEFORE/AFTER) — variation-first ERNIE (2026-05-10).

    Le param `n` est conservé pour compat de signature (plus utilisé par le corps T25).
    """
    name_en = leaf.get("name_en") or leaf.get("id")
    return (
        f"coloring book page for kids, black and white line art, thick clean outlines, "
        f"no shading, no fill, white background, "
        f"a horizontal grid of two large rectangular cells side by side "
        f"separated by a thick black vertical line, "
        f"the word \"BEFORE\" written above the left cell, "
        f"the word \"AFTER\" written above the right cell, "
        f"the left cell shows {name_en} in its initial state, "
        f"the right cell shows the same scene with several differences hidden inside, "
        f"uniform black line thickness, full scene visible, centered composition"
    )


def template_before_after(leaf, strategy):
    """Comparatif before/after — T25 (différences localisées explicites).

    Source skill — Insight C checklist (citation textuelle) :
    > Une différence explicite doit être concrète, visuelle et localisée.
    > `tap closed -> tap open + bucket` fonctionne.
    > `one single change applied` est trop vague — modèle reproduit la même scène.

    Si `_BEFORE_AFTER_STATES[leaf_id]` est défini, on injecte les deux états
    concrets dans les cellules. Sinon : fallback générique (comportement antérieur)
    avec warning loggé pour traçabilité (le leaf_id manquant doit être ajouté
    à `data/prompt_generator/before_after_states.json` lors d'une PR ultérieure).
    """
    name = leaf['name_en'].lower()
    leaf_id = leaf.get('id') or leaf.get('leaf_id')
    states = _BEFORE_AFTER_STATES.get(leaf_id) if leaf_id else None

    if states:
        before = states["before_state"]
        after = states["after_state"]
        # T25 mode 1 — différence unique explicite, états concrets/visuels/localisés
        return (
            f"{STYLE_BLOCK}, "
            f"a horizontal grid of two large rectangular cells side by side, "
            f"the cells separated by a thick black vertical line, "
            f"the word \"BEFORE\" written above the left cell, "
            f"the word \"AFTER\" written above the right cell, "
            f"the left cell shows {before}, "
            f"the right cell shows {after}, "
            f"both cells drawn from the same wide angle for clear comparison, "
            f"all elements with uniform black line thickness"
        )

    # Fallback : leaf non couvert → log + comportement actuel (antipattern T25 connu)
    logger.warning(
        "before_after_states missing for leaf_id=%s (workflow_class=%s) — "
        "fallback générique T25-violant. Ajouter une entrée dans "
        "data/prompt_generator/before_after_states.json.",
        leaf_id, (strategy or {}).get("class"),
    )
    return (
        f"{STYLE_BLOCK}, "
        f"a horizontal grid of two large rectangular cells side by side, "
        f"the cells separated by a thick black vertical line, "
        f"the word \"BEFORE\" written above the left cell, "
        f"the word \"AFTER\" written above the right cell, "
        f"the left cell shows {name} in its initial state, "
        f"the right cell shows the same scene with one single change applied, "
        f"both cells drawn from the same wide angle for clear comparison, "
        f"all elements with uniform black line thickness"
    )


def template_multiplane_stacked(leaf, strategy):
    """Composition multi-plans empilée (P6c perfect)."""
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"the page is divided into three stacked horizontal frames each containing "
        f"its own row of cells, each frame showing a different layer of {name}, "
        f"the three frames clearly separated by thick horizontal lines, "
        f"all cells the same size within each frame, balanced composition, "
        f"all elements drawn with uniform black line thickness"
    )


def template_landscape_2plane(leaf, strategy):
    """Paysage 2 plans : vue trois-quarts (T26 — anti horizon line).

    T26 (transfert skill 2026-05-10) — citation textuelle skill
    (`.claude/skills/prompt-taxonomy-ecosystem.skill` — references/techniques.md §T26) :
    > Le trait horizontal (`horizon line`, `divided by a line`) crée une coupure
    > artificielle qui aplatit la scène. La vue trois-quarts crée la profondeur
    > naturellement sans division visible — arrière-plan et premier plan
    > s'organisent organiquement.
    > Fix : Remplacer `divided by a horizon line` par `viewed from a slight
    > three-quarter angle`. Ajouter `no horizontal dividing line` pour éviter
    > la régression.

    Avant transfert (P3) : `divided by a horizon line across the middle of the page`
    + `the horizon line clearly drawn as a continuous line` → bug T26 (aplatit).
    Après transfert : trois-quarts + foreground/background, pas de ligne horizon.
    """
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"a {name} scene viewed from a three-quarter angle "
        f"with foreground and background suggested by depth, "
        f"sky elements visible in the background, "
        f"ground or water elements visible in the foreground, "
        f"no horizontal dividing line, full scene visible, centered composition, "
        f"all elements drawn with the same uniform black line thickness"
    )


def template_landscape_threequarter(leaf, strategy):
    """Paysage / scène atmosphérique vue trois-quarts (T26 + T31).

    T26 (citation textuelle skill — references/techniques.md §T26) :
    > La vue trois-quarts crée la profondeur naturellement sans division visible
    > — arrière-plan et premier plan s'organisent organiquement.

    Extension T26 — Scènes atmosphériques (citation skill §"Extension T26") :
    > Les feuilles de type condition météo (`sunny day`, `rainy day`, `snowy day`,
    > `stormy night`) sont des scènes, pas des objets. Appliquer le template
    > paysage T26 (vue trois-quarts, trois plans) plutôt que solo_object.

    T31 — Phénomènes météo scéniques (citation skill §T31) :
    > Les phénomènes atmosphériques scéniques (`thunderstorm`, `blizzard`,
    > `hurricane`, `tornado`) ne sont pas des objets ponctuels — ce sont des
    > paysages. Template paysage T26 + résolution 1376×768 par défaut.

    Bug v8 (citation skill §"Extension T26 — Bug générateur v8") :
    > `sunny day`, `rainy day` etc. reçoivent le template solo_object avec
    > `three-quarter angle` et `ground line` → résultat incohérent
    > (un soleil isolé avec une ligne de sol).
    > Fix v2 : détecter les feuilles contenant `day`, `night`, `weather`,
    > `season` → template paysage.

    La résolution 1376×768 est forcée pour ce template via
    `_LANDSCAPE_THREEQUARTER_TEMPLATES` dans `PromptGenerator.build_prompt`,
    indépendamment de la `resolution` de la cartographie (qui peut rester
    1024×1024 pour la sous-catégorie).
    """
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"a {name} scene viewed from a slight three-quarter angle, "
        f"main atmospheric elements in the background, "
        f"intermediate elements in the middle ground, "
        f"foreground details visible at the bottom, "
        f"no horizontal dividing line, full scene visible, centered composition, "
        f"all elements drawn with the same uniform black line thickness"
    )


def template_indoor_scene_threequarter(leaf, strategy):
    """Scène intérieure vue trois-quarts (T26 — pièce, mobilier minimal).

    T26 (citation textuelle skill — references/techniques.md §T26) :
    > Le trait horizontal crée une coupure artificielle qui aplatit la scène.
    > La vue trois-quarts crée la profondeur naturellement sans division visible
    > — arrière-plan et premier plan s'organisent organiquement.

    Bug v8 (citation skill §"Extension T26") : les scènes intérieures
    (`living_room_with_sofa`, `gaming_setup_with_keyboard`, `hallway_with_coat_rack`,
    `kid_using_microscope`) routées sur `template_solo_object` produisent
    `image_simpliste` + `image_physique_pb` — un seul meuble isolé sur ligne
    de sol au lieu d'une pièce avec profondeur.

    La résolution 1376×768 est forcée pour ce template via
    `_LANDSCAPE_THREEQUARTER_TEMPLATES` dans `PromptGenerator.build_prompt`.
    """
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"an indoor {name} viewed from a three-quarter perspective, "
        f"foreground items detailed and fully visible, "
        f"midground furniture or objects clearly drawn, "
        f"background wall and decorative elements simplified, "
        f"no horizon line, decorative elements visible, "
        f"all elements drawn with the same uniform black line thickness"
    )


# Templates qui forcent la résolution 1376×768 (paysage horizontal) — T26+T31.
# Source : .claude/skills/prompt-taxonomy-ecosystem.skill §T31 :
# > Phénomènes atmosphériques scéniques + scènes intérieures avec profondeur
# > → format paysage 1376×768.
# Cette liste est consultée par `PromptGenerator.build_prompt` après le dispatch
# de template, et override la résolution venant de la cartographie quand le
# template dispatché est l'un des landscape three-quarter.
_LANDSCAPE_THREEQUARTER_TEMPLATES = frozenset({
    "template_landscape_threequarter",
    "template_indoor_scene_threequarter",
})


def template_pose_static(leaf, strategy):
    """Solo humain en pose statique (yoga, méditation).

    _ISOLATION_HUMAN (transfert skill 2026-05-10) : couvre la classe
    « Solo humain en pose » (yoga, méditation, postures calmes) où le modèle
    a tendance à ajouter un partenaire de pratique.
    Source : règle générale skill « Moins de mise en scène = plus de fiabilité ».
    """
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"one single person in {name}, calm and balanced pose, "
        f"full body view from the side or three-quarter angle, "
        f"two arms total, both legs fully visible, simple ground line, "
        f"peaceful expression, off-center composition, "
        + _ISOLATION_HUMAN
    )


def template_alternative_pipeline(leaf, strategy):
    """Cas pipeline alternatif (SVG, composition PIL, hybride)."""
    name = leaf['name_en']
    return (
        f"# PIPELINE ALTERNATIF — {strategy.get('pipeline', 'à définir')}\n"
        f"# Cette feuille ({name}) ne se produit pas en ERNIE direct.\n"
        f"# Stratégie : {strategy.get('technique', 'à définir')}\n"
        f"# Notes : {strategy.get('notes', '')}\n"
    )


# ===================================================================
# DISPATCHER : choix du template selon la classe + technique
# ===================================================================
TEMPLATE_DISPATCHER = {
    "Solo animal": template_solo_animal,
    "Solo insect": template_solo_insect,
    "Solo fish": template_solo_fish,
    "Solo bird": template_solo_bird,
    "Solo reptile": template_solo_reptile,
    "Solo humain": template_solo_human,
    "Solo humain pose active": template_solo_human,
    "Solo humain en action": template_solo_human,
    "Solo humain en pose": template_pose_static,
    "Solo humain (générique)": template_solo_human,
    "Solo humain (personnalité)": template_personality_action,
    "Solo humain (personnalité) + action figée": template_personality_action,
    "Solo humain ou animal cartoon": template_personality_action,
    "Solo humain ou objet": template_solo_object,
    "Solo humain ou créature": template_personality_action,
    "Solo humain ou personnage robot": template_solo_object,
    "Solo objet": template_solo_object,
    "Solo objet (véhicule)": template_solo_object,
    "Solo objet (drapeau)": template_solo_object,
    "Solo objet (bulle texte)": template_solo_object,
    "Solo objet (plante)": template_solo_object,
    "Solo objet géométrique": template_solo_object,
    "Solo objet anatomique + labels": template_solo_object,
    "Solo objet (organe sensoriel)": template_solo_object,
    "Solo objet (plat)": template_solo_object,
    "Solo objet en vol OU au sol": template_solo_object,
    "Solo objet sur eau": template_solo_object,
    "Solo objet en espace": template_solo_object,
    "Solo objet en mouvement": template_solo_object,
    "Solo objet historique": template_solo_object,
    # T26+T31 (transfert skill 2026-05-10) : météo scénique = paysage 1376×768,
    # pas solo_object. Bug v8 : `sunny_day_with_sun`, `thunderstorm_with_lightning`,
    # `foggy_morning_landscape` traités comme solo_object → image_simpliste.
    # Cf. references/techniques.md §T31, §"Extension T26 — Scènes atmosphériques".
    "Solo objet météo": template_landscape_threequarter,
    "Solo objet style kawaii": template_solo_object,
    "Solo objet ou humain en scaphandre": template_solo_object,
    "Humain + entité": template_human_plus_entity,
    "Humain + entité (cheval)": template_human_plus_entity,
    "Humain + entité (instrument)": template_human_plus_entity,
    "Humain + véhicule": template_human_plus_entity,
    "Humain + entité OU Solo humain pose statique": template_human_plus_entity,
    "Humain + entité OU Multi-sujets": template_human_plus_entity,
    "Humain + entité OU Solo": template_human_plus_entity,
    "Imagier différencié OU Solo": template_grid_3x3_imagier,
    "Imagier différencié 3×3": template_grid_3x3_imagier,
    "Imagier annoté 3×3 OU Solo visage": template_grid_3x3_annotated,
    "Grille imagier annoté": template_grid_3x3_annotated,
    "Multi-sujets via grille (méta-pattern §2)": template_grid_3x3_imagier,
    "Multi-sujets (frise)": template_frieze_1xN,
    "Multi-sujets ou Scène": template_frieze_1xN,
    "Multi-sujets ou Scène d'action": template_frieze_1xN,
    "Multi-sujets": template_frieze_1xN,
    "Frise narrative 1×N (pattern X2)": template_frieze_1xN,
    "Frise narrative 1×4": template_frieze_1xN,
    "Comparatif before/after OU Solo": template_before_after,
    "Scène multi-plans OU multi-sujets": template_multiplane_stacked,
    "Scène panoramique": template_landscape_2plane,
    "Scène paysage": template_landscape_2plane,
    "Scène": template_landscape_2plane,
    # T26 (transfert skill 2026-05-10) : scène intérieure avec profondeur =
    # vue trois-quarts 1376×768, pas solo_object. Bug v8 : `living_room_with_sofa`,
    # `hallway_with_coat_rack`, etc. traités comme solo_object → image_simpliste
    # (un seul meuble isolé au lieu d'une pièce avec profondeur).
    # Cf. references/techniques.md §T26.
    "Scène intérieure": template_indoor_scene_threequarter,
    "Scène spatiale": template_solo_object,
    "Scène inspirée œuvre": template_solo_object,
    "Scène ou solo personnage": template_personality_action,
    "Solo personnage ou créature": template_personality_action,
    "Solo personnage mythologique": template_personality_action,
    "Solo objet ou personnage": template_solo_object,
    "Solo humain OU objet": template_solo_human,
    "Solo humain ou objet": template_solo_human,
    "Solo objet ou humain+entité": template_solo_object,
    "Solo objet ou comparatif": template_before_after,
    "Solo objet ou pattern": template_solo_object,
    "Solo objet ou scène": template_solo_object,
    "Solo objet ou Humain + entité": template_solo_object,
    "Solo humain + accessoires": template_solo_human,
    "Solo humain + accessoires + pose active": template_solo_human,
    "Solo objet ou humain en scaphandre": template_solo_object,
    "Pattern décoratif": template_solo_object,
    "Pattern décoratif (symétrie volontaire)": template_solo_object,
    "Pattern décoratif (texte stylisé)": template_solo_object,
    "Pattern décoratif simple": template_solo_object,
    "Pattern pixelisé": template_solo_object,
    "Solo humain (mère)": template_solo_human,
    "Variable": template_solo_object,
    "Variable selon sujet": template_solo_object,
    "Variable (solo objet ou frise pour party)": template_solo_object,
    "Lettre + objet": template_solo_object,
    "Pipeline alternatif": template_alternative_pipeline,
    "Pipeline alternatif (lettre) + ERNIE (objet)": template_alternative_pipeline,
}


# ===================================================================
# CLASSE PRINCIPALE
# ===================================================================
class PromptGenerator:
    """Générateur principal de prompts."""
    
    def __init__(self,
                 taxonomy_path=DEFAULT_TAXONOMY,
                 cartography_path=DEFAULT_CARTOGRAPHY,
                 seo_path=DEFAULT_SEO):
        """Charge les 3 sources de données."""
        self.taxonomy = self._load_json(taxonomy_path)
        self.cartography = self._load_json(cartography_path)
        # SEO est optionnel
        try:
            self.seo = self._load_json(seo_path)
        except (FileNotFoundError, IOError):
            self.seo = None
        
        # Index pour recherche rapide
        self._build_indexes()
    
    @staticmethod
    def _load_json(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _build_indexes(self):
        """Construit des dictionnaires d'index pour accès O(1)."""
        # Index feuille_id -> (root_data, sub_data, leaf_data)
        self.leaf_index = {}
        for root in self.taxonomy:
            for sub in root.get('children', []):
                for leaf in sub.get('children', []):
                    self.leaf_index[leaf['id']] = (root, sub, leaf)
        
        # Index sub_id -> production_strategy
        self.strategy_index = {}
        for root in self.cartography['categories']:
            for sub in root['subcategories']:
                self.strategy_index[sub['id']] = sub['production_strategy']
        
        # Index SEO si dispo
        self.seo_index = {}
        if self.seo:
            for root in self.seo:
                for sub in root.get('children', []):
                    for leaf in sub.get('children', []):
                        self.seo_index[leaf['id']] = leaf
    
    # ===================================================================
    # CŒUR : construction du prompt
    # ===================================================================
    def build_prompt(self, leaf_id: str) -> Dict:
        """
        Construit le prompt complet pour une feuille donnée.
        
        Returns dict avec :
            - positive : prompt positif prêt à coller
            - negative : negative v3 + extras
            - resolution : (width, height)
            - workflow : classe à utiliser
            - leaf_metadata : infos sur la feuille
            - strategy : stratégie de production
        """
        if leaf_id not in self.leaf_index:
            raise ValueError(f"Feuille introuvable : {leaf_id}")
        
        root, sub, leaf = self.leaf_index[leaf_id]
        strategy = self.strategy_index.get(sub['id'])
        
        if not strategy:
            raise ValueError(f"Stratégie introuvable pour la sous-catégorie : {sub['id']}")
        
        # Choix du template
        template_fn = TEMPLATE_DISPATCHER.get(strategy['class'])
        if not template_fn:
            # Fallback : solo objet
            template_fn = template_solo_object

        # T23 — heuristique dispatch v2 : leaf singulier (préfixe émotion) sur
        # workflow mixed grille/solo visage → bypass grille → solo expressive face.
        # Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T23
        if _is_t23_singular_face(leaf_id, strategy.get("class")):
            template_fn = template_solo_expressive_face

        # T30 — détection groupe narratif : leaf présent dans `_GROUP_LAYOUTS`
        # (autorité curée) → bypass solo → template_group_positioned.
        # Source : .claude/skills/prompt-taxonomy-ecosystem.skill — references/techniques.md §T30
        # Heuristique complémentaire : leafs avec préfixe numéraire (`three_*`,
        # `seven_*`, `twelve_*`…) NON couverts par le JSON sont signalés en
        # warning pour PR ultérieure (fallback solo conservé en attendant).
        if leaf_id in _GROUP_LAYOUTS:
            template_fn = template_group_positioned
        elif _has_number_prefix(leaf_id):
            logger.warning(
                "group_layouts missing for number-prefixed leaf_id=%s "
                "(workflow_class=%s) — fallback %s. Ajouter une entrée dans "
                "data/prompt_generator/group_layouts.json si c'est un groupe narratif.",
                leaf_id, strategy.get("class"), template_fn.__name__,
            )

        # Z1 — bascule grille pour Solo objet anatomique + labels (≥4 labels).
        # Source : .claude/skills/prompt-taxonomy-ecosystem.skill §Z1
        # Appliquée AVANT T28 (qui a la priorité absolue ci-dessous via
        # _ANATOMICAL_OVERRIDES) — l'ordre n'importe pas car T28 court-circuite
        # le template_fn en injectant directement le `positive`.
        # Garde-fou ERNIE : `_route_z1_anatomical_labels` retombe sur solo_object
        # + warning si le flag `_T2T3T23_GRID_AVAILABLE` est désactivé.
        template_fn = _route_z1_anatomical_labels(
            leaf_id, strategy.get("class"), template_fn,
        )

        # LEAF_OVERRIDES : prompt manuel prioritaire sur le template
        if leaf_id in LEAF_OVERRIDES:
            # Overrides validés humainement — pas de filtrage (cf. brief T5+T6+T7).
            positive = LEAF_OVERRIDES[leaf_id]
        elif leaf_id in _ANATOMICAL_OVERRIDES:
            # T28 — prompt anatomique précis validé skill (5 prompts five_senses).
            # Source : .claude/skills/prompt-taxonomy-ecosystem.skill §T28.
            # On wrappe la clause sujet (sans STYLE_BLOCK ni isolation) avec le
            # bloc style standard — pas d'isolation suffix ici car le prompt
            # canonique T28 s'autosuffit (sujet anatomique unique avec titre).
            positive = f"{STYLE_BLOCK}, {_ANATOMICAL_OVERRIDES[leaf_id]}"
            # On NE filtre PAS les overrides T28 (validés humainement clé-en-main,
            # même politique que LEAF_OVERRIDES).
        else:
            # Z1 — fallback warning : leaf "organe sensoriel" (T28) non couvert
            # par `_ANATOMICAL_OVERRIDES` → solo_object brut produira un sujet
            # syntaxiquement bizarre. On loggue pour traçabilité (le leaf devra
            # être ajouté à `data/prompt_generator/anatomical_overrides.json`).
            if strategy.get("class") == "Solo objet (organe sensoriel)":
                logger.warning(
                    "anatomical_overrides missing for leaf_id=%s (workflow_class=%s) "
                    "— fallback solo_object antipattern T28 (name_en brut). Ajouter "
                    "une entrée dans data/prompt_generator/anatomical_overrides.json.",
                    leaf_id, strategy.get("class"),
                )
            positive = template_fn(leaf, strategy)
            # Hook prophylactique T5+T6+T7 : strip noms couleur / ancres / surfaces 3D
            # On ne filtre QUE la portion sujet (après STYLE_BLOCK) : le bloc
            # boilerplate « black and white line art, no shading, white background »
            # est une instruction de style anti-couleur/anti-3D — la filtrer
            # supprimerait les protections existantes.
            if positive.startswith(STYLE_BLOCK):
                tail = positive[len(STYLE_BLOCK):].lstrip(", ")
                filtered_tail = _apply_prompt_filters(tail)
                positive = f"{STYLE_BLOCK}, {filtered_tail}" if filtered_tail else STYLE_BLOCK
            else:
                positive = _apply_prompt_filters(positive)

        # Negative = v3 + extras
        negative = NEGATIVE_V3
        if strategy.get('negative_extra'):
            negative += ", " + ", ".join(strategy['negative_extra'])
        # Feuilles à risque multi-sujets : renforcement isolation dans le négatif
        if any(pattern in leaf_id for pattern in _RISKY_MULTI_PATTERNS):
            negative += ", two animals, pair of animals, multiple animals together"
        
        # Résolution
        res_str = strategy['resolution']
        if 'x' in res_str.lower():
            try:
                w, h = res_str.lower().split('x')
                resolution = (int(w.strip()), int(h.strip()))
            except (ValueError, AttributeError):
                resolution = (1024, 1024)
        else:
            resolution = (1024, 1024)

        # T26+T31 (transfert skill 2026-05-10) : override résolution pour les
        # templates landscape three-quarter (météo scénique + scène intérieure).
        # Ces classes sont déclarées 1024×1024 dans la cartographie historique
        # mais doivent être produites en 1376×768 pour exprimer la profondeur
        # (cf. references/techniques.md §T31 : « paysage T26 + résolution
        # 1376×768 par défaut »).
        if template_fn.__name__ in _LANDSCAPE_THREEQUARTER_TEMPLATES:
            resolution = (1376, 768)
        
        # Métadonnées
        seo_data = self.seo_index.get(leaf_id, {})
        
        return {
            'leaf_id': leaf_id,
            'leaf_name_en': leaf.get('name_en'),
            'leaf_name_fr': leaf.get('name_fr'),
            'leaf_name_ar': leaf.get('name_ar'),
            'subcategory_id': sub['id'],
            'subcategory_name': sub.get('name_en'),
            'category_root': root.get('name_en'),
            'positive': positive,
            'negative': negative,
            'resolution': resolution,
            'workflow_class': strategy['class'],
            'technique': strategy['technique'],
            'pipeline': strategy['pipeline'],
            'confidence': strategy['confidence'],
            'pitfalls': strategy.get('pitfalls', []),
            'notes': strategy.get('notes', ''),
            'seo': {
                'volume_bucket': seo_data.get('search_volume_bucket'),
                'priority_en': (seo_data.get('seo_priority') or {}).get('en'),
                'priority_fr': (seo_data.get('seo_priority') or {}).get('fr'),
                'priority_ar': (seo_data.get('seo_priority') or {}).get('ar'),
                'seasonality': seo_data.get('seasonality'),
            } if seo_data else None,
        }
    
    def build_workflow_json(self, leaf_id: str, output_path: Optional[str] = None) -> Dict:
        """
        Construit un workflow ComfyUI JSON prêt à charger.
        Si output_path fourni, sauvegarde directement.
        """
        result = self.build_prompt(leaf_id)
        
      