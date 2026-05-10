# Extension `before_after_states.json` — couverture exhaustive Comparatif

## ⚠️ Conditionnel : à lancer UNIQUEMENT après verdict Go gate ERNIE T25

Si le bench gate ERNIE conclut **Go** (taux résiduel ≤ 30 % sur les 2 workflow_classes Comparatif), ce brief étend la couverture du JSON aux leafs Comparatif restants. Si **No-Go** (bascule T19+ #2 PIL 2-tiles), ce brief est annulé et remplacé par un brief composer Pillow.

## Contexte

`data/prompt_generator/before_after_states.json` couvre 18 leafs (cf. `2026-05-10_transfert-skill-T25-before-after.md`). Le brief T25 visait minimum 6, livré 18 (couverture des leafs annotés des 2 sous-catégories). Reste les leafs Comparatif non annotés dans `poc-scale-benchmark` mais présents en cartographie.

Source : `2026-05-10_transfert-skill-T25-before-after.md` §Décision / Action suivante point 3.

## Objectif

Étendre `before_after_states.json` à tous les leafs des workflow_classes `Comparatif before/after OU Solo` et `Solo objet ou comparatif` (et autres classes Comparatif éventuelles), atteindre couverture exhaustive.

## Périmètre

**Audit préalable** :

- Lister les leafs des 2 workflow_classes Comparatif (cartographie).
- Diff avec les 18 déjà couverts.

**Curation** :

- Pour chaque leaf manquant, écrire `{leaf_id: {before_state, after_state}}` selon T25 « concret, visuel, localisé ».
- Audit FILT (couleurs nues, surfaces) — whitelist le cas échéant.

**Modifier** :

- `data/prompt_generator/before_after_states.json` : append.
- `tests/test_prompt_generator.py` : test couverture (chaque leaf Comparatif cartographié a une entrée).
- Pas de modification du code Python.

## Plan d'exécution suggéré (sous-agent general-purpose)

```
Phase 1 — Audit (Claude Code principal, ~10 min)
Phase 2 — Curation (sous-agent general-purpose, ~30-45 min)
Phase 3 — Test couverture + smoke (Claude Code principal, ~10 min)
```

## Critères d'acceptation

- 100 % des leafs Comparatif cartographiés ont une entrée.
- Test de couverture en place.
- Aucun warning fallback loggé.
- Audit FILT passé.

## Hors scope

- Modification code Python.
- Pivot T25 sur autres classes (ex-frieze) — couvert par brief réconciliation doublon.

## Reporting

`docs/reports/2026-05-10_extension-before-after-states.md`.

## Estimation

~45-75 min selon volume final.
