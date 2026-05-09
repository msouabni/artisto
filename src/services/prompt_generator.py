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
import sys
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ===================================================================
# CONFIGURATION — chemins par défaut
# ===================================================================
DEFAULT_TAXONOMY = str(PROJECT_ROOT / "data/prompt_generator/coloring_taxonomy_full.json")
DEFAULT_CARTOGRAPHY = str(PROJECT_ROOT / "data/prompt_generator/taxonomy_production_cartography.json")
DEFAULT_SEO = str(PROJECT_ROOT / "data/prompt_generator/coloring_taxonomy_seo.json")

# Negative prompt v3 (validé Phase H)
# Negative prompt v3 (validé Phase H) + isolation clause (fix 2_objets 2026-05-09)
NEGATIVE_V3 = (
    "no colors, extra legs, third leg, duplicate limbs, fused legs, "
    "malformed anatomy, wrong number of limbs, six fingers, deformed feet "
    "no motion, no fill colors, no intersection, no change in ink "
    "transparency for different plan only black stroke, "
    "multiple animals, other animals, companion animal, group of animals, "
    "animal in background, second subject, multiple subjects"
)

# Bloc style coloriage (immutable §5.2 + 5.3)
STYLE_BLOCK = (
    "coloring book page for kids, black and white line art, "
    "thick clean outlines, no shading, no fill, white background"
)

# Isolation suffix appended to solo-subject positive prompts (fix 2_objets 2026-05-09)
_ISOLATION = "isolated subject, no other animals or objects nearby"

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
    """Solo animal classique (mammifère 4 pattes) avec décor minimal (§6.1)."""
    name = leaf['name_en'].lower()
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
    """
    name = leaf['name_en'].lower()
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
    """Solo humain avec quantification 'one single' (§6.2)."""
    name = leaf['name_en'].lower()
    # Détection action implicite dans le nom de la feuille
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name}, three-quarter view from the side, full body, "
        f"simple ground line, off-center composition, friendly expression"
    )


def template_solo_object(leaf, strategy):
    """Solo objet centré (catégorie outils, véhicules, électroménager)."""
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"one {name} centered on the page, viewed from a clear three-quarter angle, "
        f"all main features fully visible, simple ground line beneath, "
        f"clean uncluttered composition"
    )


def template_human_plus_entity(leaf, strategy):
    """Humain + entité avec formule asymétrie validée (§6.3)."""
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"asymmetric scene of {name}, "
        f"the human positioned on the left side, the other element on the right side, "
        f"both fully visible, the human smiling, asymmetric composition, "
        f"full body of both, simple ground line"
    )


def template_personality_action(leaf, strategy):
    """Personnalité nommée en mid-action (Z7 + §6.2)."""
    name = leaf['name_en']
    # Retire le suffix "Cartoon" si présent
    name = name.replace(" Cartoon", "").replace(" cartoon", "")
    return (
        f"{STYLE_BLOCK}, "
        f"one single {name} in mid-action, viewed from the side, "
        f"dynamic pose with motion lines suggesting movement, "
        f"two arms total, full body view, simple ground line, "
        f"off-center composition, focused expression"
    )


def template_grid_3x3_imagier(leaf, strategy):
    """Grille 3×3 imagier différencié (X1 perfect)."""
    name = leaf['name_en'].lower()
    # Heuristique : si le nom contient "imagier", on l'utilise
    title = leaf['name_en'].upper().split(' ')[0]
    return (
        f"{STYLE_BLOCK}, "
        f"a tic-tac-toe game grid of three rows by three columns making nine empty square cells, "
        f"the grid centered on the page, "
        f"each cell contains one different item related to {name}, "
        f"each item clearly distinct from the others, "
        f"every cell contains exactly one item, "
        f"the title \"{title}\" written above the grid in bold letters, "
        f"no other elements"
    )


def template_grid_3x3_annotated(leaf, strategy):
    """Grille 3×3 avec annotations (X6 OK)."""
    name = leaf['name_en'].lower()
    title = leaf['name_en'].upper()
    return (
        f"{STYLE_BLOCK}, "
        f"a tic-tac-toe game grid of three rows by three columns making nine empty square cells, "
        f"the grid centered on the page, "
        f"each cell contains one drawing of a {name} item with its name written below "
        f"in capital letters inside the same cell, each cell shows a different item, "
        f"the title \"{title}\" written above the grid"
    )


def template_frieze_1xN(leaf, strategy, n=4):
    """Frise narrative 1×N (X2 perfect, Insight B pour dernière case)."""
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"a horizontal row of {n} empty rectangular cells drawn with thick black lines, "
        f"all cells the same size and clearly separated by vertical lines, "
        f"the row of cells fills the entire panoramic page width, "
        f"each cell shows one stage or moment of {name}, "
        f"the rightmost cell shows the final stage with detailed elements, "
        f"balanced composition, simple ground line beneath each cell"
    )


def template_before_after(leaf, strategy):
    """Comparatif before/after (X4 perfect, Insight C : une transition à la fois)."""
    name = leaf['name_en'].lower()
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
    """Paysage 2 plans avec horizon (P3)."""
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"a {name} scene divided by a horizon line across the middle of the page, "
        f"in the upper half elements of the sky fully visible, "
        f"in the lower half elements of the ground or water fully visible, "
        f"the horizon line clearly drawn as a continuous line, "
        f"all elements drawn with the same uniform black line thickness"
    )


def template_pose_static(leaf, strategy):
    """Solo humain en pose statique (yoga, méditation)."""
    name = leaf['name_en'].lower()
    return (
        f"{STYLE_BLOCK}, "
        f"one single person in {name}, calm and balanced pose, "
        f"full body view from the side or three-quarter angle, "
        f"two arms total, both legs fully visible, simple ground line, "
        f"peaceful expression, off-center composition"
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
    "Solo objet météo": template_solo_object,
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
    "Scène intérieure": template_solo_object,
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
        
        # LEAF_OVERRIDES : prompt manuel prioritaire sur le template
        if leaf_id in LEAF_OVERRIDES:
            positive = LEAF_OVERRIDES[leaf_id]
        else:
            positive = template_fn(leaf, strategy)

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
        
      