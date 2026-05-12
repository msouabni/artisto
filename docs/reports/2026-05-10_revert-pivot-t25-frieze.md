# Revert — Pivot T25 sur ex-frieze + déconnexion réconciliation Option A
Date : 2026-05-10

## Contexte

Verdicts gate ERNIE 2026-05-10 (`docs/reports/2026-05-10_bench-gate-ernie-verdicts.md`) :
T25 explicite (states injectés) ✅ Go (0 % défauts), pivot T25 sur frieze ❌ No-Go
(90 % défauts), T2T3T23 grille ✅ Go (10 %). Décision archi : revert ciblé du pivot
T25 sur les 53 leafs ex-frieze + déconnexion du wrapper Option A. Conservation
intacte du mode T25 explicite (18 leafs Comparatif Go).

## Modifications

| Fichier | LOC ajoutées | LOC supprimées | Nature |
|---|---|---|---|
| `src/services/prompt_generator.py` | +47 | -41 | `template_frieze_1xN` restauré (corps autonome frise N cellules) ; fallback `template_before_after` restauré sur wording « one single change applied » ; commentaires citant décision archi 2026-05-10 + rapport gate verdicts |
| `tests/test_prompt_generator.py` | +73 | -85 | 7 tests réconciliation Option A supprimés (`test_frieze_wraps_*`, `test_reconciliation_*`, `test_frieze_ignores_n_param_compat`, `test_frieze_default_n_signature_preserved`) ; 5 tests historiques frise restaurés (`test_frieze_generates_n_cell_horizontal_row`, `test_frieze_default_n_is_four`, `test_frieze_respects_custom_n`, `test_frieze_is_autonomous_not_a_wrapper`, `test_dispatcher_routes_*`) ; ajustement `test_template_before_after_fallback_logs_warning_when_missing` (assertion « one single change applied ») |

**Commit pré-pivot référence** : `81b4dc5` (commit initial du module
`prompt_generator.py`) — corps historique de `template_frieze_1xN` (frise N
cellules) récupéré via `git show 81b4dc5:src/services/prompt_generator.py`.

**Préservé intact** :
- `template_before_after` mode T25 explicite (states injectés) — wording
  « several differences hidden inside » conservé sur les états concrets.
- `data/prompt_generator/before_after_states.json` (18 leafs Comparatif Go).
- `template_grid_3x3_imagier` (hors scope, mention §43 du brief).

## Tests

- `pytest tests/test_prompt_generator.py` : **123/123 verts** (0.44 s).
- `pytest --ignore=tests/test_content_generator.py` : **386 passed, 5 failed**.
  Les 5 échecs (`test_bulk_generation_jobs`, `test_create_image_job_workflow`,
  `test_workflow_template_sidecar`) sont **préexistants** (validés via `git stash`
  avant modifs) et ne concernent ni `prompt_generator.py` ni `frieze`/`before_after`.
  Erreur de collection sur `test_content_generator.py` (`HARAKAT_RE` import) =
  également préexistante, hors scope.
- 7 anciens tests réconciliation supprimés ; 5 nouveaux tests frise
  autonome ajoutés ; 8 tests T25 explicite (mode states injectés) conservés.

## Smoke

3 leafs frise (corps autonome restauré, frise N cellules) :
- `spring_blooming_meadow` → contient `horizontal row of 4`, ne contient
  ni `BEFORE`/`AFTER` ni `several differences hidden inside`. ✅
- `football_match_scene` → idem. ✅
- `seasons_changing` → idem. ✅

3 leafs Comparatif T25 explicite (states injectés conservés) :
- `rainwater_collection_barrel` → contient `before_state` + `after_state` du JSON,
  pas de wording fallback. ✅
- `kid_recycling_bin_sorting` → idem. ✅
- `beach_cleanup_volunteers` → idem. ✅

Vérification exhaustive : **18/18 leafs Comparatif Go** conservent leurs états
explicites injectés (aucun ne tombe dans le fallback « one single change applied »).

## Points d'attention

- Commentaire docstring `template_before_after` mentionne « wording "several
  differences hidden inside" sur les états injectés validé Go 0% » — cohérent
  avec le brief §28-29 (à conserver intact dans le mode explicite).
- Aucune référence dans le code à un wrapper Option A actif. Les seules mentions
  restantes (`Option A`, `wrapper`, `réconciliation`) sont en commentaires de
  docstring explicitant le revert.
- 5 tests préexistants en échec (sidecar ERNIE / negative_prompt support) :
  hors scope brief — à arbitrer dans un brief séparé si besoin.

## Décision / Action suivante

**Sujet pivot ex-frieze : clos.**

- `template_frieze_1xN` redevient autonome (frise N cellules, corps pré-pivot
  `81b4dc5` restauré). Plus de wrapper Option A.
- `template_before_after` mode T25 explicite (Go 0 %) inchangé.
- Les 53 leafs ex-frieze sont classés hors-MEP v0 côté cartographie (cadrage
  séparé — pas dans ce brief).
- Pas de commit dans cette livraison (l'archi commit après livraison).
