# Transfert skill — T28 + Z1 (anatomique + labels)

Date : 2026-05-10

## Contexte

Dernier transfert de la séquence P3 (skill `prompt-taxonomy-ecosystem`). Adresse les deux poches identifiées dans `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #7 et #8 :

1. **Solo objet (organe sensoriel)** — 5 leafs `sense_of_*` + `five_senses_summary_poster`. Score baseline 1.0/10, 0/6 publishable. Cause : `template_solo_object` insère `name_en` brut (`one sense of sight eye…`) → sujet syntaxiquement bizarre (bug v4 du skill).
2. **Solo objet anatomique + labels** — 4+ occurrences (`hand_with_fingers_named`, `foot_with_toes`, `full_body_with_parts_labelled`, `child_face_features`, …). Score baseline 1.86/10. Z1 (skill) : pattern flèches+labels tient jusqu'à 3 labels max ; au-delà → bascule grille 3×3.

Brief source : `docs/architect/briefs/2026-05-10_brief-transfert-T28-Z1-anatomique-labels.md`.
Source skill : `.claude/skills/prompt-taxonomy-ecosystem.skill` — `references/techniques.md` §T28, §Z1.

## Modifications

### Fichiers nouveaux

- **`data/prompt_generator/anatomical_overrides.json`** : mapping `leaf_id → positive_subject_clause` pour les 5 prompts T28 validés clé-en-main par le skill (sense_of_sight_eye, sense_of_hearing_ear, sense_of_smell_nose, sense_of_taste_tongue, sense_of_touch_hand). Schéma documenté dans `_metadata` du JSON (clause sans STYLE_BLOCK ni isolation, ceux-ci wrappés côté code).

### `src/services/prompt_generator.py`

LOC nettes : **+155** environ (loaders + helpers + dispatch + flag défensif + commentaires skill).

Sections nouvelles :

- **`DEFAULT_ANATOMICAL_OVERRIDES`** (constante chemin JSON).
- **`_T2T3T23_GRID_AVAILABLE = True`** — flag défensif gate ERNIE (cf. plus bas).
- **`_load_anatomical_overrides()` + `_ANATOMICAL_OVERRIDES` (singleton) + `set_anatomical_overrides()`** — même pattern que `_GROUP_LAYOUTS`, `_CANONICAL_OUTFITS` etc.
- **`_Z1_GRID_CLASSES = frozenset({"Solo objet anatomique + labels"})`** — autorité de classe pour bascule Z1 par défaut.
- **`_count_anatomical_labels(leaf_id, workflow_class)`** — heuristique label count : classe ciblée ou pattern leaf_id (`_named`, `_labelled`, `_labels`, `_with_parts`, `_diagram`) → 4 ; sinon → 1.
- **`_route_z1_anatomical_labels(...)`** — applique Z1 (≥4 → grille). Garde-fou : si flag `_T2T3T23_GRID_AVAILABLE = False`, fallback solo + warning loggé.

Modifications du dispatcher `PromptGenerator.build_prompt` :

1. **Z1** : `template_fn = _route_z1_anatomical_labels(leaf_id, strategy.get("class"), template_fn)` injecté APRÈS T30 (group_layouts) et AVANT le rendu — de sorte que pour `Solo objet anatomique + labels`, la bascule grille s'applique systématiquement (sauf flag OFF).
2. **T28** : nouvelle branche `elif leaf_id in _ANATOMICAL_OVERRIDES:` dans le if/else `LEAF_OVERRIDES`. Injecte directement `f"{STYLE_BLOCK}, {clause}"` — pas de filtrage T5+T6+T7 (politique LEAF_OVERRIDES : prompts validés humainement = pas de mutation).
3. **Fallback warning T28** : si `strategy.class == "Solo objet (organe sensoriel)"` ET pas d'override → warning loggé + fallback solo_object (antipattern v4 conservé pour ne pas casser le pipeline le temps d'enrichir le JSON).

### Fallback warning gate ERNIE — switch défensif

Le flag `_T2T3T23_GRID_AVAILABLE` (défaut `True`) gouverne la bascule Z1 vers grille. Verdict mesure post-T2T3T23 humaine encore en attente. Deux chemins codés :

- **Flag ON (défaut)** : `_route_z1_anatomical_labels` route vers `template_grid_3x3_imagier` quand label_count ≥ 4. Comportement nominal.
- **Flag OFF** (PR archi triviale si verdict No-Go) : `_route_z1_anatomical_labels` retombe sur `template_solo_object` + warning explicite (`"Z1 grid bypass disabled (_T2T3T23_GRID_AVAILABLE=False)…"`). Z1 reste fonctionnel sans grille améliorée — pas de crash, traçabilité maintenue.

L'archi switche le flag en haut de fichier (1 ligne) si la mesure repasse No-Go.

### `tests/test_prompt_generator.py`

LOC ajoutées : **+150** environ (20 nouveaux tests).

Couverture :

- T28 : 5 leafs validés (parametrize) — vérifie injection clause skill + titre majuscules + absence antipattern v4.
- T28 fallback : warning loggé pour `five_senses_summary_poster` (pas d'override, mais classe ciblée) — assertion via `caplog`.
- T28 non-régression : leaf hors mapping (`claw_hammer`) garde solo_object intact.
- Z1 : 4 leafs `anatomique + labels` (parametrize) routés vers grille 3×3.
- Z1 helpers : `_count_anatomical_labels` (workflow_class + patterns), `_route_z1_anatomical_labels` (bascule + no-op + fallback flag OFF).
- Z1 garde-fou : `_T2T3T23_GRID_AVAILABLE` défaut True ; toggle OFF dynamique → warning + fallback (assertion via `caplog`).
- `set_anatomical_overrides` : utilitaire test.

## Tests

```
python -m pytest tests/test_prompt_generator.py -q
117 passed in 0.38s
```

- **97/97** tests pré-existants : verts (non-régression).
- **20/20** tests nouveaux T28+Z1 : verts.
- Suite globale (hors `test_content_generator.py` qui a une erreur d'import préalable indépendante `HARAKAT_RE`) : **345 passed, 5 failed (pré-existants)**. Les 5 échecs (`test_bulk_generation_jobs`, `test_create_image_job_workflow`, `test_workflow_template_sidecar`) sont indépendants — confirmés en stash baseline (mêmes 5 échecs avant transfert).

## Mesure post (à venir, optionnelle)

Brief mentionne mesure rerun ComfyUI sur 5 leafs T28 + 4 leafs `anatomique + labels` (seed offset +700) — dépend de la disponibilité ComfyUI/archi. Non bloquant pour la clôture P3.

À mesurer sur baseline (1.0 / 0% publishable) :

- **T28** : 5 prompts validés skill — score attendu ≥ 7/10, publishable ≥ 60% (les prompts sont validés clé-en-main, peu de risque).
- **Z1** : 4 leafs grille 3×3 — score attendu ≥ 5/10. Risque : grille fallback générique (T2-violant) car `grid_cell_contents.json` n'a pas encore d'entrées pour `hand_with_fingers_named` etc. Verdict gate T2T3T23 (en attente) influence directement.

## Points d'attention

- **`grid_cell_contents.json` non couvert pour les leafs Z1** : la bascule grille produit un prompt T2-violant (warning loggé `grid_cell_contents missing for…`). À enrichir dans une PR ultérieure (un leaf = ~9 cellules) — c'est cohérent avec le brief : « si T2+T3+T23 No-Go pivot ERNIE, Z1 reste fonctionnel mais sans grille améliorée — accepter le warning fallback ».
- **`five_senses_summary_poster` en classe organe sensoriel mais sans override T28** : leaf collectif (5 organes ensemble) — warning T28 loggé + fallback solo_object (antipattern v4). Le skill ne fournit pas de prompt validé pour ce cas ; bascule probable vers grille 3×3 dans une PR ultérieure (chaque case = un sens).
- **Z1 heuristique conservative** : tous les leafs « anatomique + labels » basculent grille (label_count = 4 par défaut sur la classe). Si certains leafs (ex. `tooth_and_dental_anatomy`) ont en réalité 1-3 labels, la bascule grille reste un meilleur défaut que solo_object brut (qui produit aussi du baratin avec name_en composé).
- **Flag défensif ERNIE** : si la mesure post-T2T3T23 revient No-Go, l'archi peut désactiver Z1 en switchant le flag — Z1 retombe gracefully sur solo_object + warning. Codage défensif validé par 1 test dédié.

## Décision / Action suivante

**Verdict : Go — clôture P3.**

- Toutes les règles skill (T9, T25, T2/T3/T23, FILT, ISO élargi, T22+T27+T30 anatomie, T26+T31 météo/scènes, T28, Z1) sont transférées dans `prompt_generator.py`.
- 117/117 tests verts sur le module ; 0 régression.
- Switch défensif gate ERNIE en place pour Z1.

Actions archi suivantes (hors scope ce ticket) :

1. Commit de la livraison T28+Z1 + récap final P3.
2. Lancement mesure ComfyUI post-transfert (T2T3T23 grid + T28 sense + Z1 anatomique) sur dataset témoin → décision Go/No-Go gate ERNIE → switch flag `_T2T3T23_GRID_AVAILABLE` si nécessaire.
3. PR ultérieure : enrichir `anatomical_overrides.json` (couverture exhaustive — `child_face_features`, `skeleton_for_children`, `hand_with_fingers_named`, etc. avec prompts ad hoc) + `grid_cell_contents.json` (cellules pour les leafs Z1).
