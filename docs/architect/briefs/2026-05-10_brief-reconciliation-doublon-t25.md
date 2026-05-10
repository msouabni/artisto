# Réconciliation doublon T25 — `template_frieze_1xN` ⇆ `template_before_after`

## Contexte

Deux briefs T25 ont été livrés en parallèle 2026-05-10 :

1. **Pivot** (`2026-05-10_pivot-templates-narratifs-jeu-differences.md`) — `template_frieze_1xN` a été pivoté en BEFORE/AFTER + SPOT THE DIFFERENCE pour exploiter la variation native d'ERNIE.
2. **Transfert T25 before/after** (`2026-05-10_transfert-skill-T25-before-after.md`) — `template_before_after` a été enrichi avec un mapping `before_after_states.json` (18 leafs Comparatif).

**Doublon fonctionnel** explicitement signalé par l'agent pivot (point 2 de ses points d'attention) :

> Les deux produisent maintenant des prompts BEFORE/AFTER ; les variantes diffèrent marginalement (`name_en` vs `name.lower()`, "several differences hidden inside" vs "one single change applied", "uniform black line thickness" en clôture vs plus verbeux).

Le `template_before_after` (transfert T25) bénéficie de la richesse des `before_after_states.json` (états explicites par leaf) ; le `template_frieze_1xN` (pivot) reste générique (s'appuie uniquement sur `name_en`).

## Objectif

Consolider en un seul template BEFORE/AFTER cohérent, et router les workflow_classes appropriées vers ce template unifié, sans perte de fonctionnalité ni de couverture.

## Périmètre

**Décision design à prendre dans le brief** :

- **Option A** (recommandée) : conserver `template_before_after` comme implémentation unique BEFORE/AFTER (avec lookup `before_after_states.json`). `template_frieze_1xN` devient un wrapper qui appelle `template_before_after` et accepte/ignore le param `n`. Routing dispatcher inchangé.
- **Option B** : fusionner les 2 templates en un seul `template_before_after_universal` (suppression `template_frieze_1xN`). Mettre à jour `TEMPLATE_DISPATCHER` pour pointer toutes les workflow_classes ex-frieze vers `template_before_after_universal`.

**Modifier** :

- `src/services/prompt_generator.py` :
  - Selon option choisie : refactor `template_frieze_1xN` (Option A) ou suppression + redirection dispatcher (Option B).
  - Cas où le leaf n'a pas d'entrée dans `before_after_states.json` : fallback générique cohérent (warning loggé).
  - Conserver le même wording cible « several differences hidden inside » (variant pivot, plus efficace selon le rapport pivot).
- `tests/test_prompt_generator.py` :
  - Tests sur `template_frieze_1xN` : produit le même résultat que `template_before_after` pour leafs couverts.
  - Tests routing : `Frise narrative 1×N` continue de fonctionner (smoke test).
  - Non-régression : 117 tests existants verts.

## Plan d'exécution suggéré (sous-agent unique)

```
Phase 1 — Décision design (Claude Code principal, ~10 min)
  - Lire les 2 templates actuels (post-pivot et post-transfert) côté code.
  - Choisir Option A ou Option B en pesant : risque cassure dispatcher (B>A),
    clarté API (A légèrement moins clair), simplicité fix (A léger, B plus lourd).
  - Reco par défaut : Option A (moins risqué, dispatcher inchangé).

Phase 2 — Implémentation (Claude Code principal, ~30 min)
  - Refactor / suppression selon décision.
  - Tests unitaires + non-régression.

Phase 3 — Smoke build_prompt sur 6 leafs représentatifs
  - 3 leafs Frise narrative (post-refactor)
  - 3 leafs Comparatif (template_before_after)
  - Vérifier homogénéité du wording "several differences hidden inside".
```

## Critères d'acceptation

- 1 seule logique BEFORE/AFTER active (Option A : wrapper ; Option B : template unique).
- `before_after_states.json` consulté pour les leafs couverts (frieze ET comparatif).
- Wording uniforme « several differences hidden inside » sur les deux chemins.
- 117 tests existants verts + tests nouveaux.
- Citation T25 + cite des 2 rapports source en commentaire.

## Hors scope

- Refonte du `TEMPLATE_DISPATCHER` au-delà du minimum nécessaire (Option B uniquement).
- Extension de `before_after_states.json` aux nouvelles classes ex-frieze (PR de suivi).
- Modification du skill ou MEMORY.

## Reporting

`docs/reports/2026-05-10_reconciliation-doublon-t25.md` — Contexte / Décision design / Modifications / Tests / Smoke / Décision Go.

## Estimation

~45-60 min dev + tests + rapport (Option A) ; ~75-90 min (Option B).
