"""Vocabulaires fermés v2 partagés (axes IMAGE / PROMPT) — single source of truth.

Source : brief 2026-05-09 (annotateur v2 + greffon prod) puis brief
2026-05-09 ``vocabulaires-source-unique`` (élimination de la duplication
back/front : ce module devient l'unique source de vérité).

Les listes ``IMAGE_AXIS`` / ``PROMPT_AXIS`` sont **ordonnées** ; l'ordre
détermine la numérotation des raccourcis "chord" côté front (touche ``D``
pour image, ``T`` pour prompt — la k-ième entrée correspond à la touche
``k+1``, jusqu'à 9). Toute permutation casse l'expérience utilisateur :
ne pas réordonner sans synchroniser le front.

Chaque entrée est un dict :
  - ``key`` : identifiant stable (utilisé en DB + payload API)
  - ``label`` : libellé affichable FR (rendu sur le pill)
  - ``polarity`` : ``"pos"`` | ``"neut"`` | ``"neg"`` (couleur du pill)

Les ``frozenset`` ``IMAGE_TAGS_VOCAB`` / ``PROMPT_TAGS_VOCAB`` sont
**dérivés** des listes (rétrocompat avec les imports existants — la
validation ``POST /annotate`` les utilise tels quels).

Ce module est importé par :
- ``src/api/routes/benchmark.py`` (mode benchmark sur disque)
- ``src/api/routes/review.py`` (mode prod sur table ``annotation`` polymorphe)

Toute évolution des vocabulaires se fait ici uniquement, pour éviter la
divergence entre les deux modes et entre back/front.
"""
from __future__ import annotations

from typing import Literal, TypedDict


class AxisTag(TypedDict):
    """Entrée typée d'un axe annotation."""

    key: str
    label: str
    polarity: Literal["pos", "neut", "neg"]


# 18 entrées (cf. brief annotateur v2 §P3). L'ordre POS → NEUT → NEG est
# celui historiquement utilisé pour la numérotation chord côté front
# (constante ``flatAxisKeys`` dans ``data/benchmark-annotator.html``).
# Les ``label`` sont extraits à l'identique du HTML actuel pour éviter
# toute dérive cosmétique lors de la bascule front → fetch back.
IMAGE_AXIS: list[AxisTag] = [
    # POS (3)
    {"key": "image_compo_bonne",         "label": "Bonne compo",  "polarity": "pos"},
    {"key": "image_coherente",           "label": "Cohérente",    "polarity": "pos"},
    {"key": "image_creative",            "label": "Créative",     "polarity": "pos"},
    # NEUT (1)
    {"key": "image_complexe",            "label": "Complexe",     "polarity": "neut"},
    # NEG (14)
    {"key": "image_compo_mauvaise",      "label": "Mauv. compo",  "polarity": "neg"},
    {"key": "image_pas_coherente",       "label": "Pas cohér.",   "polarity": "neg"},
    {"key": "image_simpliste",           "label": "Simpliste",    "polarity": "neg"},
    {"key": "image_incomprehensible",    "label": "Incompr.",     "polarity": "neg"},
    {"key": "image_traces_couleur",      "label": "Couleurs",     "polarity": "neg"},
    {"key": "image_gris_residuel",       "label": "Gris résid.",  "polarity": "neg"},
    {"key": "image_symetrie_incomplete", "label": "Sym. inc.",    "polarity": "neg"},
    {"key": "image_duplication",         "label": "Duplication",  "polarity": "neg"},
    {"key": "image_flou",                "label": "Flou",         "polarity": "neg"},
    {"key": "image_anatomie_pb",         "label": "Anatomie",     "polarity": "neg"},
    {"key": "image_physique_pb",         "label": "Pb physique",  "polarity": "neg"},
    {"key": "image_traits_pb",           "label": "Pb traits",    "polarity": "neg"},
    {"key": "image_hors_sujet",          "label": "Hors sujet",   "polarity": "neg"},
    {"key": "image_prompt_non_respecte", "label": "Prompt KO",    "polarity": "neg"},
]

# 8 entrées.
PROMPT_AXIS: list[AxisTag] = [
    # POS (2)
    {"key": "prompt_interessant",   "label": "Intéressant", "polarity": "pos"},
    {"key": "prompt_creatif",       "label": "Créatif",     "polarity": "pos"},
    # NEUT (1)
    {"key": "prompt_complexe",      "label": "Complexe",    "polarity": "neut"},
    # NEG (5)
    {"key": "prompt_ambigu",        "label": "Ambigu",      "polarity": "neg"},
    {"key": "prompt_approximatif",  "label": "Approx.",     "polarity": "neg"},
    {"key": "prompt_vide",          "label": "Vide",        "polarity": "neg"},
    {"key": "prompt_creux",         "label": "Creux",       "polarity": "neg"},
    {"key": "prompt_ennuyeux",      "label": "Ennuyeux",    "polarity": "neg"},
]


# Frozensets dérivés (validation rapide ⊂ vocab — utilisés par
# ``benchmark.py`` et ``review.py`` pour valider les payloads
# ``POST /annotate`` et ``POST /api/annotation``). Les imports existants
# de ces noms restent stables : c'est le contrat de rétrocompat.
IMAGE_TAGS_VOCAB: frozenset[str] = frozenset(t["key"] for t in IMAGE_AXIS)
PROMPT_TAGS_VOCAB: frozenset[str] = frozenset(t["key"] for t in PROMPT_AXIS)


# Garde-fous (assertions au chargement du module — détectent toute
# régression sur les comptes attendus par le brief, peu coûteux).
assert len(IMAGE_AXIS) == 18, f"IMAGE_AXIS doit contenir 18 entrées, trouvé {len(IMAGE_AXIS)}"
assert len(PROMPT_AXIS) == 8, f"PROMPT_AXIS doit contenir 8 entrées, trouvé {len(PROMPT_AXIS)}"
assert len(IMAGE_TAGS_VOCAB) == len(IMAGE_AXIS), "IMAGE_AXIS contient des doublons de clé"
assert len(PROMPT_TAGS_VOCAB) == len(PROMPT_AXIS), "PROMPT_AXIS contient des doublons de clé"


__all__ = [
    "AxisTag",
    "IMAGE_AXIS",
    "PROMPT_AXIS",
    "IMAGE_TAGS_VOCAB",
    "PROMPT_TAGS_VOCAB",
]
