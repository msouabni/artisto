# Réconciliation doublon T25 — `template_frieze_1xN` ⇆ `template_before_after`
Date : 2026-05-10
Type : Refactor / consolidation post-pivot T25
Brief source : `docs/architect/briefs/2026-05-10_brief-reconciliation-doublon-t25.md`

## Contexte

Deux briefs T25 ont été livrés en parallèle 2026-05-10 :

1. **Pivot** (`docs/reports/2026-05-10_pivot-templates-narratifs-jeu-differences.md`) — `template_frieze_1xN` pivoté en BEFORE/AFTER « jeu des différences » (variation-first ERNIE), wording « several differences hidden inside ».
2. **Transfert T25** (`docs/reports/2026-05-10_transfert-skill-T25-before-after.md`) — `template_before_after` enrichi d'un mapping `before_after_states.json` (18 leafs Comparatif annotés) avec injection d'états explicites + fallback antipattern « one single change applied » conservé.

Le doublon fonctionnel a été explicitement signalé par l'agent pivot (point 2 de ses points d'attention). Cette PR le réconcilie en une seule logique BEFORE/AFTER.

## Décision design — Option A retenue

| Critère | Option A (wrapper) | Option B (fusion totale) |
|---|---|---|
| Surface modifiée | `template_frieze_1xN` (corps remplacé par 1-ligne wrapper) + `template_before_after` (consolidation wording fallback) | suppression `template_frieze_1xN` + edits `TEMPLATE_DISPATCHER` (10+ lignes) + renommage |
| Risque cassure dispatcher | nul (dispatcher inchangé) | élevé (risque oubli d'une classe) |
| Clarté API | légèrement moins claire (2 noms pour 1 logique) | plus claire à terme |
| Testabilité du contrat de wrapping | `assert via_wrapper == via_canonical` couvre tout | identité textuelle à recouvrir par 6+ tests routing |
| Compat ascendante callers | param `n=4` préservé | rupture de signature |

**Choix** : Option A (recommandation par défaut du brief). Aucune raison forte identifiée à la lecture du code de basculer en Option B — le dispatcher actuel a 6 entrées frieze + 2 entrées comparatif, modifier les 6 frieze entries pour viser `template_before_after` directement aurait un coût de churn supérieur au bénéfice de clarté.

## Modifications

| Fichier | Nature | LOC |
|---|---|---:|
| `src/services/prompt_generator.py` | Refactor `template_frieze_1xN` en wrapper 1-ligne ; consolidation wording fallback de `template_before_after` (« one single change applied » → « several differences hidden inside ») ; docstrings citent T25 + les 2 rapports source + le brief de réconciliation | ~30 net |
| `tests/test_prompt_generator.py` | Mise à jour `test_template_before_after_fallback_logs_warning_when_missing` (wording fallback unifié) ; ajout de 7 tests réconciliation (identité wrapper/canonique, ignore `n`, signature compat, wording uniforme, routing dispatcher frieze, routing dispatcher comparatif) ; import `template_frieze_1xN` | ~95 ajout, ~6 modif |

### Diff résumé `src/services/prompt_generator.py`

1. `template_before_after` :
   - Docstring élargie : cite le brief de réconciliation + les 2 rapports sources.
   - Branche T25 mode (states présents) : inchangée — injection `before_state` / `after_state` explicites.
   - Branche fallback : wording « one single change applied » remplacé par « several differences hidden inside » (uniformisation avec ex-pivot frieze). Warning loggé clarifié.
2. `template_frieze_1xN(leaf, strategy, n=4)` :
   - Corps réduit à `return template_before_after(leaf, strategy)`.
   - Docstring : Option A, citation T25, citation des 2 rapports + brief, mention que `n` est conservé pour compat de signature mais ignoré.
3. Ordre source du fichier : `template_before_after` placé **avant** `template_frieze_1xN` (le wrapper appelle la canonique). Le `TEMPLATE_DISPATCHER` (parsé en fin de module) résout les deux noms — pas d'impact.

### Wording unifié

- **Mode explicite (states présents)** : injection des `before_state` / `after_state` du JSON. Pas de wording générique « several differences » (T25 Insight C — différence concrète/visuelle/localisée).
- **Mode fallback (states absents)** : wording uniforme « several differences hidden inside » sur les deux entrées (`template_frieze_1xN` ⇆ `template_before_after`).

## Tests

### Suite `tests/test_prompt_generator.py`

**Avant refactor** : 117/117 verts (baseline post pivot + post transfert T25).
**Après refactor** : **124/124 verts** (117 inchangés + 1 ajusté pour wording unifié + 7 nouveaux).

Nouveaux tests :

| Test | Vérifie |
|---|---|
| `test_frieze_wraps_before_after_for_covered_leaf` | Sur leaf couvert par mapping, `template_frieze_1xN` produit EXACTEMENT le même prompt que `template_before_after`. |
| `test_frieze_wraps_before_after_for_uncovered_leaf` | Sur leaf hors mapping (cas typique ex-frieze), identité textuelle wrapper ⇆ canonique en mode fallback. |
| `test_frieze_ignores_n_param_compat` | `n=4`, `n=9`, défaut produisent le même prompt — param ignoré conformément au brief. |
| `test_frieze_default_n_signature_preserved` | Smoke compat : signature `(leaf, strategy, n=N)` reste appelable sans casser les callers historiques. |
| `test_reconciliation_uniform_wording_several_differences` | Critère d'acceptation brief — « several differences hidden inside » présent côté frieze ET côté before_after en fallback ; antipattern « one single change applied » éradiqué. |
| `test_reconciliation_dispatcher_routes_frieze_classes` | Smoke routing — les 6 workflow_classes ex-frieze pointent toujours vers `template_frieze_1xN`. |
| `test_reconciliation_dispatcher_routes_comparatif_classes` | Smoke routing — les 2 classes Comparatif pointent toujours vers `template_before_after`. |

Test ajusté :

| Test | Ajustement |
|---|---|
| `test_template_before_after_fallback_logs_warning_when_missing` | Vérifie désormais `"several differences hidden inside" in positive` + `"one single change applied" not in positive`, en lieu et place de l'assertion sur l'antipattern historique. Le commentaire cite la réconciliation. |

### Suite globale

- **387 passed, 5 failed** (hors `test_content_generator.py` ImportError documenté pré-existant).
- Les 5 échecs identifiés (`test_bulk_generation_jobs::test_dedup_and_partial_success`, `test_bulk_generation_jobs::test_bulk_preflight_removes_unsupported_negative_for_ernie`, `test_create_image_job_workflow::test_create_job_default_safe_workflow_ignores_negative_prompt_from_image`, `test_create_image_job_workflow::test_create_job_preflight_removes_unsupported_negative_for_ernie`, `test_workflow_template_sidecar::test_ernie_uses_sidecar_from_repo`) sont strictement les échecs pré-existants documentés dans le brief comme « workflow Ernie / negative-prompt sans rapport ». **Aucune régression introduite par ce refactor.**

## Smoke build_prompt — 6 leafs

### 3 leafs ex-Frise (post-refactor wrapper, fallback uniforme)

**`baby_first_year`** (workflow_class : `Frise narrative 1×N (pattern X2)`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side, the cells separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows baby first year in its initial state, the right cell shows the same scene with several differences hidden inside, both cells drawn from the same wide angle for clear comparison, all elements with uniform black line thickness

**`spring_blooming_meadow`** (workflow_class : `Frise narrative 1×4`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side, the cells separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows spring blooming meadow in its initial state, the right cell shows the same scene with several differences hidden inside, both cells drawn from the same wide angle for clear comparison, all elements with uniform black line thickness

**`football_match_scene`** (workflow_class : `Multi-sujets ou Scène d'action`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side, the cells separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows football match scene in its initial state, the right cell shows the same scene with several differences hidden inside, both cells drawn from the same wide angle for clear comparison, all elements with uniform black line thickness

### 3 leafs Comparatif (mode T25 explicite — states injectés)

**`rainwater_collection_barrel`** (workflow_class : `Comparatif before/after OU Solo`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side, the cells separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows an empty rain barrel standing under a roof gutter, no water inside, dry ground around the barrel, the right cell shows the same barrel now full of water with a small stream of rainwater pouring from the gutter into the barrel, a watering can being filled from the tap at the bottom, both cells drawn from the same wide angle for clear comparison, all elements with uniform black line thickness

**`vegetable_garden_at_home`** (workflow_class : `Solo objet ou comparatif`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side, the cells separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows an empty rectangular garden plot with bare soil, a shovel and a watering can resting against a fence, the right cell shows the same plot now planted with rows of leafy vegetables (lettuce, carrot tops, tomato plants on stakes), the watering can tipped pouring a few drops, both cells drawn from the same wide angle for clear comparison, all elements with uniform black line thickness

**`kid_planting_a_tree`** (workflow_class : `Comparatif before/after OU Solo`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side, the cells separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows a child holding a small tree sapling and a shovel, an empty round hole dug in the ground in front of them, the right cell shows the same child standing next to a young tree planted in the hole, the shovel resting on the ground, a watering can pouring water at the base of the tree, both cells drawn from the same wide angle for clear comparison, all elements with uniform black line thickness

### Vérifications smoke

- ✅ Wording uniforme « several differences hidden inside » sur les 3 leafs ex-Frise (mode fallback).
- ✅ States explicites concrets/visuels/localisés sur les 3 leafs Comparatif (mode T25).
- ✅ Wrapping textuel identique : `template_frieze_1xN(leaf, strategy)` ≡ `template_before_after(leaf, strategy)` sur tous les leafs testés.
- ✅ Antipattern « one single change applied » absent partout.

## Critères d'acceptation du brief — état

| Critère | État |
|---|---|
| 1 seule logique BEFORE/AFTER active (Option A : wrapper) | ✅ `template_frieze_1xN` = wrapper 1-ligne vers `template_before_after` |
| `before_after_states.json` consulté pour les leafs couverts (frieze ET comparatif) | ✅ via wrapping, le mapping est consulté quel que soit l'entrée |
| Wording uniforme « several differences hidden inside » sur les deux chemins | ✅ vérifié par `test_reconciliation_uniform_wording_several_differences` + smoke |
| 117 tests existants verts + tests nouveaux | ✅ 124/124 dans `test_prompt_generator.py` (1 test ajusté pour le wording uniforme) |
| Citation T25 + des 2 rapports source en commentaire | ✅ docstring de `template_before_after` + de `template_frieze_1xN` |
| `TEMPLATE_DISPATCHER` non modifié | ✅ inchangé (Option A) |

## Points d'attention

1. **Ajustement d'un test pré-existant** : `test_template_before_after_fallback_logs_warning_when_missing` a été ajusté de la baseline 117 → 117 (le test reste, mais ses assertions changent pour refléter le wording fallback unifié). Le compteur global du brief « 117 tests existants verts + tests nouveaux » est respecté : 117 tests baseline persistent (tous passants), 7 nouveaux tests ajoutés (124 total).
2. **`before_after_states.json` couvre 18 leafs Comparatif uniquement**. Les ~53 leafs ex-frieze (Frise narrative, Multi-sujets…) tombent en fallback générique avec warning loggé. Conforme au scope du brief (« Pas d'extension de `before_after_states.json` aux nouvelles classes ex-frieze »). PR de suivi recommandée pour étendre la couverture si la mesure post-transfert le justifie.
3. **Wording fallback non encore validé empiriquement** sur les classes ex-frieze (53 leafs concernés). La valeur ajoutée du pivot était la rupture conceptuelle « variation-first » ; la mesure ComfyUI sur `image_pas_coherente` reste à programmer pour valider la généralisation.
4. **Aucun appel direct identifié** à `template_frieze_1xN` ou `template_before_after` hors `TEMPLATE_DISPATCHER` (vérifié par grep). Pas de risque de bypass du wrapping.
5. **`template_grid_3x3_imagier` (SPOT THE DIFFERENCE)** non touché — il reste sur sa logique propre (wording « several differences hidden inside » mais sans BEFORE/AFTER, juste « SPOT THE DIFFERENCE »). Hors scope du présent brief de réconciliation (qui cible uniquement le doublon frieze ⇆ before_after).

## Décision Go/No-Go

**Verdict : Go technique — réconciliation propre, identité textuelle wrapper ⇆ canonique vérifiée, wording unifié, 0 régression.**

- À l'archi : valider le périmètre Option A (dispatcher inchangé, `n` conservé en compat).
- À l'archi : décider si la PR de suivi « extension `before_after_states.json` aux ex-frieze » doit être planifiée immédiatement ou attendre une mesure ComfyUI sur les classes Frise/Multi-sujets.
- À l'archi : décider si le `template_grid_3x3_imagier` (SPOT THE DIFFERENCE) doit lui aussi consulter `before_after_states.json` à terme (suit la même logique de fallback wording unifié, mais nécessite un mapping différent — `spot_difference_states.json` ?).
