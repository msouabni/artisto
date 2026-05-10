# Extension `anatomical_overrides.json` — couverture exhaustive Solo objet anatomique + organe sensoriel

## ⚠️ Conditionnel : à lancer après livraison T28+Z1 + après cadrage MEP v0

Si MEP v0 confirme que les classes `Solo objet (organe sensoriel)` et `Solo objet anatomique + labels` sont en scope, ce brief étend la couverture du JSON `anatomical_overrides.json` au-delà des 5 leafs T28 initiaux pour absorber les autres leafs anatomiques (ex. `child_face_features`, `skeleton_for_children`, `hand_with_fingers_named`, `tooth_and_dental_anatomy`).

Le brief peut aussi être lancé **inconditionnellement** si l'archi décide de pré-charger la couverture en parallèle du gate ERNIE (faible risque, le mécanisme T28+Z1 est en place).

## Contexte

`data/prompt_generator/anatomical_overrides.json` couvre actuellement les 5 prompts T28 validés clé-en-main par le skill (sense_of_sight_eye, sense_of_hearing_ear, sense_of_smell_nose, sense_of_taste_tongue, sense_of_touch_hand). Le rapport T28+Z1 (`2026-05-10_transfert-skill-T28-Z1-anatomique-labels.md` §Points d'attention) signale :

- `five_senses_summary_poster` reste sans override → fallback solo_object antipattern v4.
- Les leafs `Solo objet anatomique + labels` basculent grille via Z1, mais `grid_cell_contents.json` n'a pas d'entrée pour eux → warning loggé.

Source : `2026-05-10_transfert-skill-T28-Z1-anatomique-labels.md` §Décision / Action suivante point 3.

## Objectif

Étendre `anatomical_overrides.json` aux leafs anatomiques restants pour produire des prompts validés humainement (pas de fallback antipattern). Si extension à `grid_cell_contents.json` requise, créer entrées correspondantes.

## Périmètre

**Audit préalable** :

- Lister les leafs des 2 classes (`Solo objet (organe sensoriel)`, `Solo objet anatomique + labels`).
- Diff avec les 5 déjà couverts.

**Curation** :

- Pour chaque leaf anatomique sans override, écrire un prompt validé clé-en-main (s'inspirer du style des 5 T28 du skill).
- Pour les leafs `+ labels` qui basculent grille via Z1, créer entrée dans `grid_cell_contents.json` avec cellules anatomiques (chaque case = une partie du corps avec label).
- Audit FILT systématique.

**Modifier** :

- `data/prompt_generator/anatomical_overrides.json` : append.
- `data/prompt_generator/grid_cell_contents.json` : append entrées Z1 si nécessaire.
- `tests/test_prompt_generator.py` : test couverture.

## Plan d'exécution suggéré (sous-agent unique general-purpose)

```
Phase 1 — Audit (Claude Code principal, ~10 min)
Phase 2 — Curation prompts T28 (sous-agent general-purpose, ~30 min)
  - 5-10 leafs anatomiques restants
Phase 3 — Curation cellules Z1 (sous-agent general-purpose, ~30 min)
  - 4-8 leafs `+ labels` avec cellules anatomiques
Phase 4 — Test couverture + smoke (Claude Code principal, ~10 min)
  - Aucun warning fallback sur les classes ciblées
```

## Critères d'acceptation

- Couverture exhaustive Solo objet (organe sensoriel) + Solo objet anatomique + labels.
- Aucun warning fallback loggé sur ces classes.
- Tests pytest verts (existants + nouveau test couverture).
- Audit FILT passé.

## Hors scope

- Modification code Python (mécanisme T28+Z1 + flag défensif déjà en place).
- Génération images (gérée par bench gate ERNIE).
- Cadrage MEP v0 (décision archi).

## Reporting

`docs/reports/2026-05-10_extension-anatomical-overrides.md`.

## Estimation

~75-90 min selon volume final.
