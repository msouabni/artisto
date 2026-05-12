# Transfert T28 + Z1 — Solo objet (organe sensoriel) + Solo objet anatomique + labels

## Contexte

L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #7 et #8 identifie deux poches de défauts liées au pattern « organe / anatomie + labels » :

1. **`Solo objet (organe sensoriel)`** (5 leafs / 6 défaut, score moyen 1.0, 0/6 publishable) : `sense_of_hearing_ear`, `sense_of_sight_eye`, `five_senses_summary_poster`, `hand_with_fingers_named`, `foot_with_toes`.
2. **`Solo objet anatomique + labels`** (4 occ, score 1.86) — même pattern.

Diagnostic : ces leafs sont mappés sur `template_solo_object` (`TEMPLATE_DISPATCHER` l. 525) qui insère le `name_en` brut sans projection anatomique précise (bug v4 du skill). Les noms `sense_of_*` / `hand_with_*` ne sont pas exploitables tels quels par ERNIE.

Règles skill (`references/techniques.md`) :

- **T28** : pattern `five_senses` + projection anatomique précise. Le skill fournit **5 prompts validés clé-en-main**.
- **Z1** : limite labels ≤ 3 ; au-delà, basculer en grille 3×3.

## Objectif

Transférer T28 (mapping leaf → prompt anatomique précis) + Z1 (limite labels + bascule grille).

## Périmètre

**Créer** :

- `data/prompt_generator/anatomical_overrides.json` : mapping `leaf_id → positive_override` pour les 5 leafs T28 + leafs `*_anatomique + labels` annotés. Le skill fournit les prompts validés (sense_of_hearing_ear, sense_of_sight_eye, etc.).

**Modifier** :

- `src/services/prompt_generator.py` :
  - Avant `template_solo_object` (priorité), vérifier `leaf_id ∈ anatomical_overrides` → utiliser le prompt validé directement.
  - Implémenter Z1 : compter le nombre de labels attendus (mots après `_named` / `_with_*_named` / `_labels`). Si N ≥ 4 → router vers `template_grid_3x3_imagier` (avec contenu explicite si présent dans `grid_cell_contents.json` du brief T2+T3+T23, sinon warning).
  - Fallback : warning loggé si le leaf attendu n'a pas d'override anatomique.
- `tests/test_prompt_generator.py` :
  - Test : 5 leafs T28 → positive contient le prompt validé skill.
  - Test : leaf avec ≥4 labels → router sur grille 3×3.
  - Test non-régression.

## Critères d'acceptation

- `anatomical_overrides.json` créé avec ≥ 5 leafs (les 5 prompts validés skill).
- Routing T28 + Z1 actif.
- Tests pytest verts.
- Citation T28 + Z1 en commentaire.

**Mesure post-transfert (optionnelle)** : rerun sur les 5 leafs T28 + 4 leafs `anatomique + labels` (seed offset +700). Comparer score / publishable post vs baseline (1.0 / 0%).

## Reporting

`docs/reports/2026-05-10_transfert-skill-T28-Z1-anatomique-labels.md`.

## Dépendances

- Idéalement après le brief T2+T3+T23 (`grid_cell_contents.json` créé) pour que Z1 puisse router proprement vers grille avec contenu explicite. Si T2+T3+T23 No-Go pivot ERNIE, Z1 reste fonctionnel mais sans grille améliorée — accepter le warning fallback.

## Hors scope

- Couverture exhaustive `anatomique + labels` (extension par PR ultérieure).
- Refactor `TEMPLATE_DISPATCHER` au-delà du minimum.

## Estimation

~45-60 min dev + tests + rapport.
