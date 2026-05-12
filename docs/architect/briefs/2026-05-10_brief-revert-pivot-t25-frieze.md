# Revert pivot T25 sur ex-frieze + déconnexion réconciliation Option A

## Contexte

Verdicts gate ERNIE 2026-05-10 (cf. `docs/reports/2026-05-10_bench-gate-ernie-verdicts.md`) :

| Transfert | Verdict | Action |
|---|---|---|
| T2T3T23 grille | ✅ Go (10% défauts) | Conserver |
| **T25 before/after explicite (states injectés)** | ✅ Go (0% défauts) | **Conserver** |
| **Pivot T25 (frieze + spot diff générique)** | ❌ No-Go (90% défauts) | **Revert** |

La réconciliation doublon T25 Option A (cf. `docs/reports/2026-05-10_reconciliation-doublon-t25.md`) a propagé le wording « several differences hidden inside » du pivot aux 53 leafs ex-frieze via wrapper. Ce wording est désormais invalidé empiriquement.

**Décision archi 2026-05-10** : ces 53 leafs ex-frieze (Frise narrative, Multi-sujets, classes méta-narratives) sont **classés hors-MEP v0** — pas critiques pour le scope publication initial. Pas d'extension `before_after_states.json` aux ex-frieze. Pas de bascule PIL/SVG. Revert ciblé puis abandon temporaire de ces classes.

## Objectif

Restaurer `template_frieze_1xN` à son comportement pré-pivot (corps original, génération de frise N-cellules narrative) et déconnecter le wrapper Option A. Conserver intact `template_before_after` mode T25 explicite (Go validé) pour les 18 leafs Comparatif.

## Périmètre

**Modifier** :

- `src/services/prompt_generator.py` :
  - Restaurer le corps historique de `template_frieze_1xN` depuis l'historique git (commit pré-pivot — chercher via `git log --all --oneline -- src/services/prompt_generator.py | head -20` puis `git show <sha>:src/services/prompt_generator.py`).
  - Déconnecter le wrapper Option A : `template_frieze_1xN` redevient une fonction autonome indépendante de `template_before_after`.
  - Conserver `template_before_after` tel quel (mode T25 explicite Go = intact).
  - Conserver le wording « several differences hidden inside » dans `template_before_after` mode T25 (states injectés) — c'est ce qui a été validé Go à 0%, distinct du fallback.
  - Pour le fallback de `template_before_after` (leafs sans states) : restaurer le wording historique « one single change applied » (cohérent avec antipattern T25 fallback explicit, accepter le warning loggé).
  - Citer en commentaire la décision archi 2026-05-10 + le rapport gate ERNIE verdicts.

- `tests/test_prompt_generator.py` :
  - Restaurer les tests historiques `template_frieze_1xN` pré-pivot (frise N cellules).
  - Ajuster `test_template_before_after_fallback_logs_warning_when_missing` : restaurer wording « one single change applied » dans l'assertion.
  - Supprimer les 7 tests de réconciliation Option A (devenus obsolètes : wrapper supprimé).
  - Conserver les 8 tests T25 explicite (mode states injectés) — Go validé.

**Ne pas modifier** :

- `template_before_after` mode T25 explicite (states injectés via `before_after_states.json`).
- `data/prompt_generator/before_after_states.json` (18 leafs Comparatif Go).
- `template_grid_3x3_imagier` (a été pivoté en SPOT THE DIFFERENCE, peut rester en l'état si non utilisé en MEP v0 ; voir Hors scope).

## Critères d'acceptation

- `template_frieze_1xN` restauré, autonome, génère frise N cellules historique.
- `template_before_after` mode T25 explicite intact (Go 0%).
- `template_before_after` mode fallback : wording « one single change applied » restauré.
- Tests pytest verts (suite `test_prompt_generator.py`).
- Citation décision archi 2026-05-10 + rapport gate verdicts en commentaire.
- Aucune référence dans le code à la réconciliation Option A wrapper.

## Hors scope

- **`template_grid_3x3_imagier` SPOT THE DIFFERENCE** : non touché dans ce brief. Si l'archi décide aussi de le revert, brief séparé. Pour l'instant : ces classes (Multi-sujets via grille) sont hors-MEP v0, pas critique.
- **Extension `before_after_states.json` aux ex-frieze** : abandonné (décision archi).
- **Bascule PIL/SVG composer** : abandonné (décision archi).
- **Classement explicite des 53 leafs ex-frieze hors-MEP v0** : géré côté cartographie / MEP v0 cadrage (pas dans ce brief).

## Plan d'exécution suggéré

```
Phase 1 — Recherche historique (Claude Code principal, ~10 min)
  - git log --all --oneline -- src/services/prompt_generator.py
  - Identifier le commit pré-pivot (avant 2026-05-10 pivot)
  - git show <sha>:src/services/prompt_generator.py | grep -A 30 "def template_frieze_1xN"

Phase 2 — Revert ciblé (Claude Code principal, ~15 min)
  - Restaurer template_frieze_1xN
  - Restaurer fallback template_before_after wording
  - Tests pytest

Phase 3 — Vérifications (Claude Code principal, ~5 min)
  - Smoke build_prompt sur 3 leafs frise + 3 leafs Comparatif (T25 explicite Go)
  - Vérifier que les 18 leafs Comparatif Go conservent leur wording « several differences hidden inside »
```

## Reporting

`docs/reports/2026-05-10_revert-pivot-t25-frieze.md` — Contexte / Modifications / Tests / Smoke / Décision (clôture sujet pivot).

## Estimation

~30-45 min dev + tests + rapport.
