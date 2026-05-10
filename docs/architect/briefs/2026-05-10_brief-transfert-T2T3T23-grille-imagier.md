# Transfert T2 + T3 + T23 — templates Grille imagier (contenu explicite par cellule + heuristique solo vs grille)

## Contexte

L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #1 identifie le bottleneck qualité du corpus : **~60 défauts** `image_pas_coherente` + `image_incomprehensible` concentrés sur 4 workflow_classes de grille :

- Grille imagier annoté : 8/8 (100%)
- Imagier différencié OU Solo : 7/7 (100%)
- Imagier annoté 3×3 OU Solo visage : 9/10 (90%)
- Imagier différencié 3×3 : 4/8 (50%)

Diagnostic : `src/services/prompt_generator.py` `template_grid_3x3_imagier` (l. 388-402) et `template_grid_3x3_annotated` (l. 405-416) délèguent le contenu des cellules au modèle (`each cell contains one different item related to {name}`) — pile l'antipattern documenté en T2 du skill (`# ❌ contenu délégué…`).

Le skill `prompt-taxonomy-ecosystem` règle T2 + T3 + T23 (`references/techniques.md`) propose le fix validé hors-circuit :

- **T2** : contenu explicite par cellule (jamais déléguer au modèle).
- **T3** : cellules composées avec conteneur sémantique.
- **T23** : heuristique de dispatch — si feuille singulière (`_face`, `_child`, `_portrait` + workflow Imagier annoté) → bypass grille → solo.

## Garde-fou pivot ERNIE

Insight produit ERNIE 2026-05-10 (cf. T19+ #1 du rapport d'analyse) : le modèle est faible en répétition stricte avec contenu hétérogène. Si T2/T3 maxi appliqués ne descendent pas le taux `image_pas_coherente` sous **30 %** sur l'échantillon de mesure, **stopper le transfert et reporter en T19+ canal manuel** (bascule pipeline grille en composition PIL/SVG hors ERNIE — décision archi).

## Objectif

Transférer T2 + T3 + T23 dans `src/services/prompt_generator.py` :

1. Banque de connaissances par leaf : structure data `data/prompt_generator/grid_cell_contents.json` listant pour chaque leaf grille les cellules (item + forme géométrique).
2. Modifier `template_grid_3x3_imagier` et `template_grid_3x3_annotated` pour lire ce JSON + fallback comportement actuel + warning loggé.
3. Implémenter T23 (heuristique dispatch v2) : leaf singulier (`_face`, `_child`, `_portrait`) + workflow `Imagier annoté 3×3 OU Solo visage` → bypass grille → `template_solo_human` étendu avec table `expressive_face` (émotions dans le nom : `proud_`, `sad_`, `happy_`, `angry_`, `surprised_`, `sleepy_`, `scared_`, `calm_`, `excited_`, `shy_`).

## Périmètre

**Créer** :

- `data/prompt_generator/grid_cell_contents.json` :
  ```json
  {
    "<leaf_id>": {
      "title": "<TITLE_OVERRIDE>",
      "cells": [
        {"item": "round red apple with leaf", "shape": null},
        {"item": "yellow banana curved", "shape": null},
        ...
      ]
    }
  }
  ```
  Couvrir au minimum les **leafs annotés haute fréquence** sur les 4 classes ciblées (à extraire des annotations `Imagier différencié 3×3` / `Grille imagier annoté` / `Imagier annoté 3×3 OU Solo visage` / `Imagier différencié OU Solo` dans `docs/reports/poc-scale-benchmark/annotations.json`). Cible minimale : 6-8 leafs.

- `data/templates_catalog_editor.html` (convention projet — éditeur HTML pour tout YAML/JSON livrable) : pas obligatoire dans cette PR si l'asset est traité comme cœur stable lecture-seule pour l'instant ; sinon, créer.

**Modifier** :

- `src/services/prompt_generator.py` :
  - `template_grid_3x3_imagier` et `template_grid_3x3_annotated` : si `leaf_id ∈ grid_cell_contents` → générer le positive avec contenu explicite par cellule (T2). Sinon → comportement actuel + `logger.warning("grid_cell_contents missing for leaf_id=%s", leaf_id)` via `artiste_logging`.
  - Implémenter T23 dans le dispatcher : avant de router sur `template_grid_3x3_*`, vérifier si le `leaf_id` matche un pattern singulier OU contient une émotion → router sur `template_solo_human` enrichi avec table `expressive_face`.
  - Ajouter table `_EXPRESSIVE_FACES: dict[str, str]` mappant `proud_` → `proud expression with raised chin and slight smile`, etc.

- `tests/test_prompt_generator.py` :
  - Test : `leaf_id` présent dans `grid_cell_contents.json` → cellules nommées présentes dans positive.
  - Test : `leaf_id` absent → fallback comportement actuel + warning loggé (capturer via `caplog`).
  - Test : `leaf_id` avec émotion dans le nom + workflow `Imagier annoté 3×3 OU Solo visage` → bypass grille → `solo_expressive_face` (`expressive_face` injectée dans positive).
  - Test non-régression : leafs Solo animal/insect/fish/bird/reptile inchangés.

**Ne pas modifier** :

- `NEGATIVE_V3`, `_ISOLATION`, `_RISKY_MULTI_PATTERNS`, `LEAF_OVERRIDES` (transferts dédiés).
- Autres templates (Comparatif before/after = brief T25 séparé).

## Critères d'acceptation

- `data/prompt_generator/grid_cell_contents.json` créé avec ≥ 6 leafs couverts.
- `template_grid_3x3_imagier` et `template_grid_3x3_annotated` lisent ce JSON ; fallback fonctionne ; warning loggé.
- T23 actif dans le dispatcher : test passe sur un leaf émotionnel.
- Tests pytest verts (existants + nouveaux).
- Citation T2/T3/T23 en commentaire de code.

**Mesure post-transfert (obligatoire pour ce brief, du fait du garde-fou ERNIE)** :

- Rerun ComfyUI sur 8-10 leafs des 4 classes ciblées (1 image / leaf, seed offset +300).
- Annoter manuellement avec grille v2 — au moins les tags `image_pas_coherente` + `image_incomprehensible`.
- Comparer baseline (91-100% sur 3 classes, 50% sur Imagier différencié 3×3) vs post-transfert.
- **Décision Go/No-Go T19+ #1** :
  - Si taux post-transfert ≤ 30% → Go : transfert validé, brief T25 peut suivre.
  - Si taux post-transfert > 30% → No-Go : signaler dans le rapport, l'archi reportera en T19+ #1 canal manuel (bascule PIL/SVG).

## Reporting

Rapport obligatoire : `docs/reports/2026-05-10_transfert-skill-T2T3T23-grille-imagier.md`
Sections : Contexte / Modifications / Tests / Mesure post-transfert (obligatoire ici) / Décision (Go ou No-Go pivot ERNIE).

## Conventions à respecter

- Reporting daté.
- Convention editor HTML : à honorer ou explicitement justifier l'omission dans le rapport (cœur stable lecture-seule pour l'instant).
- NULL-safe avant tri.
- Tests SQLite-portables.
- Citation T2/T3/T23 en commentaire de code.

## Hors scope

- Couverture exhaustive de tous les leafs grille (extension par PR ultérieure si Go).
- Transfert T15-T21 (supports de comptage) — concerne `Multi-sujets via grille`, brief séparé.
- Refactor de `TEMPLATE_DISPATCHER` au-delà du minimum nécessaire pour T23.
- Bascule PIL/SVG (décision archi si No-Go).

## Estimation

~75-90 min dev + tests + mesure + rapport.

Si dépassement marqué : signaler à l'archi via le rapport et découper (data + code en 2 PR si nécessaire).
