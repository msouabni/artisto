"""Vocabulaires fermés v2 partagés (axes IMAGE / PROMPT) — single source of truth.

Source : brief 2026-05-09 (annotateur v2 + greffon prod). Tout payload qui
soumet un tag dans ``image_tags`` ou ``prompt_tags`` doit le faire dans la
whitelist correspondante. Les ``custom_tags`` restent libres.

Ce module est importé par :
- ``src/api/routes/benchmark.py`` (mode benchmark sur disque)
- ``src/api/routes/review.py`` (mode prod sur table ``annotation`` polymorphe)

Toute évolution des vocabulaires se fait ici uniquement, pour éviter la
divergence entre les deux modes.
"""
from __future__ import annotations

# 18 clés (cf. brief annotateur v2 §P3).
IMAGE_TAGS_VOCAB: frozenset[str] = frozenset({
    "image_compo_bonne",
    "image_coherente",
    "image_creative",
    "image_complexe",
    "image_compo_mauvaise",
    "image_pas_coherente",
    "image_simpliste",
    "image_incomprehensible",
    "image_traces_couleur",
    "image_gris_residuel",
    "image_symetrie_incomplete",
    "image_duplication",
    "image_flou",
    "image_anatomie_pb",
    "image_physique_pb",
    "image_traits_pb",
    "image_hors_sujet",
    "image_prompt_non_respecte",
})

# 8 clés.
PROMPT_TAGS_VOCAB: frozenset[str] = frozenset({
    "prompt_interessant",
    "prompt_creatif",
    "prompt_complexe",
    "prompt_ambigu",
    "prompt_approximatif",
    "prompt_vide",
    "prompt_creux",
    "prompt_ennuyeux",
})


__all__ = ["IMAGE_TAGS_VOCAB", "PROMPT_TAGS_VOCAB"]
