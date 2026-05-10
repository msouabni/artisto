# Extension `grid_cell_contents.json` — couverture exhaustive grilles imagier

## ⚠️ Conditionnel : à lancer UNIQUEMENT après verdict Go gate ERNIE T2T3T23

Si le bench gate ERNIE conclut **Go** (taux résiduel ≤ 30 % sur les 4 workflow_classes grille), ce brief étend la couverture du JSON aux ~15-20 leafs grille restants non couverts dans la livraison initiale. Si **No-Go** (bascule T19+ #1 PIL/SVG), ce brief est annulé et remplacé par un brief composer Pillow.

## Contexte

`data/prompt_generator/grid_cell_contents.json` couvre actuellement 14 leafs (cf. `2026-05-10_transfert-skill-T2T3T23-grille-imagier.md`). Le brief T2T3T23 visait minimum 6, livré 14. Reste ~15-20 leafs grille non couverts (audit annotations + cartographie à faire). Pour ces leafs, le template fallback warning est actif — le résultat est dégradé.

Source : `docs/reports/2026-05-10_transfert-skill-T2T3T23-grille-imagier.md` §Décision / Action suivante point 4.

## Objectif

Étendre `grid_cell_contents.json` aux leafs grille non couverts pour atteindre 100 % de couverture sur les 4 workflow_classes ciblées.

## Périmètre

**Audit préalable** :

- Lister les leafs présents dans `Grille imagier annoté` / `Imagier différencié OU Solo` / `Imagier annoté 3×3 OU Solo visage` / `Imagier différencié 3×3` (cartographie + cartographie SEO).
- Comparer aux 14 leafs déjà couverts → liste exhaustive des manquants.

**Curation** :

- Pour chaque leaf manquant, créer entrée `{leaf_id: {title, cells: [...]}}` avec items concrets (T2 : nommer chaque cellule + forme géo si T3 applicable).
- **Garde-fou FILT** : items audités contre `_COLOR_NOUNS` + `_GLOSSY_TERMS` (ou utiliser whitelist contextuelle si brief whitelist livré entre temps).

**Modifier** :

- `data/prompt_generator/grid_cell_contents.json` : append des nouveaux leafs.
- `tests/test_prompt_generator.py` : test de couverture (chaque leaf grille listé en cartographie a une entrée JSON).
- Pas de modification du code Python (le mécanisme est en place depuis T2T3T23).

## Plan d'exécution suggéré (sous-agent general-purpose)

```
Phase 1 — Audit (Claude Code principal, ~15 min)
  - Grep cartographie pour les 4 workflow_classes
  - Diff avec leafs déjà couverts dans grid_cell_contents.json
  - Liste des manquants

Phase 2 — Curation (sous-agent general-purpose, ~30-45 min)
  - Pour chaque leaf manquant, générer item par cellule
  - Audit FILT (whitelist le cas échéant)
  - Validation que la cellule a un sens visuel cohérent

Phase 3 — Test couverture + smoke (Claude Code principal, ~10 min)
  - Test pytest qui vérifie chaque leaf cartographié a une entrée
  - Smoke build_prompt sur 5 nouveaux leafs
```

## Critères d'acceptation

- 100 % des leafs des 4 workflow_classes ont une entrée dans `grid_cell_contents.json`.
- Test de couverture en place (échec si nouveau leaf manqué).
- Aucun warning fallback loggé sur les classes ciblées (sauf erreur légitime).
- Audit FILT passé.

## Hors scope

- Modification du code Python (tout est déjà en place).
- Curation des leafs hors 4 workflow_classes (autres classes grille éventuelles).

## Reporting

`docs/reports/2026-05-10_extension-grid-cell-contents.md` — Audit / Curation / Tests / Smoke.

## Estimation

~60-90 min selon volume final de leafs manquants (~15-20).
