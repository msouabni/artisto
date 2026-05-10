# Transfert skill — T26 + T31 (météo / scènes intérieures, vue trois-quarts)
Date : 2026-05-10

## Contexte

Brief : `docs/architect/briefs/2026-05-10_brief-transfert-T26-T31-meteo-scenes.md`.

L'analyse `2026-05-10_analyse-annotations-transferts-skill.md` §3 #6 a identifié
deux poches de défauts dans `src/services/prompt_generator.py` :

1. **`Solo objet météo`** (`sunny_day_with_sun`, `thunderstorm_with_lightning`,
   `foggy_morning_landscape`, `tornado_in_distance`, …) routé sur
   `template_solo_object` — bug v8 (météo scénique traitée comme solo objet
   ponctuel + ground line incongrue). Score moyen 2.62, 62 % publishable.
2. **Scènes intérieures** (`living_room_with_sofa`, `hallway_with_coat_rack`,
   `kid_using_microscope`, …) routées sur `template_solo_object` →
   `image_simpliste` (un seul meuble isolé sur ligne de sol) +
   `image_physique_pb` (perspective KO).
3. **Antipattern T26 dans `template_landscape_2plane`** : la ligne
   `divided by a horizon line across the middle of the page` aplatit la scène
   et empêche le modèle d'organiser la profondeur.

Règles skill (`.claude/skills/prompt-taxonomy-ecosystem.skill` —
`references/techniques.md` §T26, §"Extension T26 — Scènes atmosphériques", §T31) :

- **T26** : remplacer `divided by a horizon line` par `viewed from a slight
  three-quarter angle` ; ajouter `no horizontal dividing line` pour éviter la
  régression.
- **Extension T26 — Scènes atmosphériques** : `sunny day`, `rainy day`, etc.
  sont des scènes, pas des objets ; appliquer le template paysage trois-quarts.
- **T31** : phénomènes météo scéniques (`thunderstorm`, `blizzard`, `hurricane`,
  `tornado`) → paysage T26 + résolution **1376×768 par défaut**.
- **Bug v8** : scènes atmosphériques mappées par erreur sur solo_object
  (combinaison `three-quarter angle` + `ground line` → résultat incohérent).

## Modifications

### `src/services/prompt_generator.py` (~95 LOC ajoutées, 1 template modifié)

| Élément | Action | Source skill |
|---|---|---|
| `template_landscape_2plane` | Réécriture : suppression `divided by a horizon line across the middle of the page` + `the horizon line clearly drawn as a continuous line`. Remplacé par `viewed from a three-quarter angle with foreground and background suggested by depth` + `no horizontal dividing line`. | §T26 |
| `template_landscape_threequarter` (NEW) | Nouveau template trois-plans (background / middle ground / foreground) sans horizon line. Cible : `Solo objet météo`. | §T26, §"Extension T26 — Scènes atmosphériques", §T31 |
| `template_indoor_scene_threequarter` (NEW) | Nouveau template scène intérieure trois-quarts : foreground items détaillés / midground meubles / background mur simplifié, `no horizon line`. Cible : `Scène intérieure`. | §T26 |
| `_LANDSCAPE_THREEQUARTER_TEMPLATES` (NEW frozenset) | Liste des deux nouveaux templates qui forcent la résolution 1376×768 dans `build_prompt`, indépendamment de la cartographie (qui reste 1024×1024 pour ces sous-cat). | §T31 |
| `TEMPLATE_DISPATCHER` | `Solo objet météo` : `template_solo_object` → `template_landscape_threequarter`. | §T31 |
| `TEMPLATE_DISPATCHER` | `Scène intérieure` : `template_solo_object` → `template_indoor_scene_threequarter`. | §T26 |
| `PromptGenerator.build_prompt` | +6 LOC : override résolution `(1376, 768)` quand `template_fn.__name__ in _LANDSCAPE_THREEQUARTER_TEMPLATES`. | §T31 |

Toutes les modifications citent T26 / T31 / bug v8 en commentaire (citation textuelle de `references/techniques.md`).

### `tests/test_prompt_generator.py` (+13 tests, +160 LOC)

| Test | Vérifie |
|---|---|
| `test_template_landscape_2plane_no_horizon_line` | Plus de `divided by a horizon line` ; présence de `three-quarter angle` + `no horizontal dividing line`. |
| `test_template_landscape_threequarter_format` | Nouveau template : 3 plans, pas de signature solo_object (`one single`, `ground line beneath`, `_ISOLATION_OBJECT`). |
| `test_template_indoor_scene_threequarter_format` | Nouveau template : 3 plans intérieurs (foreground/midground/background), `no horizon line`. |
| `test_landscape_threequarter_templates_constant` | Le frozenset contient les 2 templates et exclut les autres. |
| `test_build_prompt_solo_objet_meteo_routes_to_landscape_threequarter` | `sunny_day_with_sun` → positive sans signature solo_object, avec `three-quarter angle`. |
| `test_build_prompt_solo_objet_meteo_resolution_1376x768` | 4 leafs météo (`sunny_day_with_sun`, `thunderstorm_with_lightning`, `foggy_morning_landscape`, `tornado_in_distance`) → résolution `(1376, 768)`. |
| `test_build_prompt_scene_interieure_routes_to_indoor_threequarter` | `living_room_with_sofa` → positive avec `three-quarter perspective` + `midground`. |
| `test_build_prompt_scene_interieure_resolution_1376x768` | 4 leafs intérieurs (`living_room_with_sofa`, `hallway_with_coat_rack`, `bedroom_with_bed`, `kitchen_full_view`) → `(1376, 768)`. |
| `test_build_prompt_scene_paysage_keeps_landscape_2plane_no_horizon` | `tropical_beach_with_palm_trees` (Scène paysage) reste sur `template_landscape_2plane` mais sans horizon line, résolution 1376×768 (cartographie). |
| `test_t26_t31_do_not_alter_solo_object_template` | `template_solo_object` (autres classes) reste intact. |
| `test_t26_t31_do_not_alter_solo_animal_template` | T9 préservé sur `house_cat`. |
| `test_t26_t31_do_not_alter_solo_objet_resolution_for_other_classes` | `claw_hammer` (Solo objet standard) reste à 1024×1024. |
| `test_t26_t31_do_not_alter_grid_imagier` | Grille imagier intact. |

## Tests

```
pytest tests/test_prompt_generator.py
97 passed in 0.25s
```

- Baseline avant transfert : **84 / 84 verts**.
- Après transfert : **97 / 97 verts** (+13 nouveaux).
- Pas de régression sur les 84 tests existants (T9, T22, T23, T25, T27, T30,
  ISO, FILT, before_after, grid imagier, group positioned).

Suite globale (hors fichiers cassés à la baseline avant ce brief) :
**325 passed, 5 failed**. Les 5 failed sont **strictement préexistants** (non
liés au prompt_generator — `tests/test_bulk_generation_jobs.py`,
`tests/test_create_image_job_workflow.py`, `tests/test_workflow_template_sidecar.py`)
et le `tests/test_content_generator.py` était déjà cassé avant
(import `HARAKAT_RE` manquant dans `services.ollama_json` — préexistant,
confirmé par `git stash` avant/après).

## Mesure post (non exécutée — laissée à l'archi)

Brief = mesure post-transfert optionnelle (rerun sur 7 leafs météo / intérieurs,
seed offset +800, comparer `image_simpliste` + `image_physique_pb` post vs
baseline). **Non exécuté ici** — le rerun image relève d'un cycle d'annotation
distinct, hors périmètre de la livraison code.

Inspection visuelle des prompts générés (smoke) confirme :

- `sunny_day_with_sun` : positive paysage trois-quarts, pas de `one single`
  ni `ground line beneath`, résolution `(1376, 768)`.
- `thunderstorm_with_lightning` : idem, format paysage cohérent avec T31.
- `living_room_with_sofa` : positive scène intérieure trois-quarts, foreground/
  midground/background, résolution `(1376, 768)`.
- `tropical_beach_with_palm_trees` : `template_landscape_2plane` réécrit, plus
  de horizon line, format paysage 1376×768 conservé via cartographie.

## Points d'attention

1. **Cartographie non touchée** : `data/prompt_generator/taxonomy_production_cartography.json`
   conserve `resolution: "1024x1024"` pour `weather_phenomena` et
   `house_room_by_room`. L'override est porté **dans le code** (via
   `_LANDSCAPE_THREEQUARTER_TEMPLATES`) plutôt que dans la donnée pour deux
   raisons :
   - Garder la traçabilité skill→code dans le module Python (plus lisible
     pour audit).
   - Permettre un rollback rapide en commentant la ligne `resolution = (1376, 768)`
     sans rejouer une migration data.
   - À tertio : si une nouvelle classe rejoint le routing landscape
     three-quarter (ex. `Scène spatiale` dans un T26 v3), il suffit
     d'ajouter le nom du template au frozenset.
2. **Dépendance avec FILT** : la chaîne `apply_all_filters` strippe `black`
   ("uniform black line thickness" → "uniform line thickness"). Comportement
   préexistant — observé sur les anciens templates aussi. Pas de régression.
3. **Pas de JSON externalisé** : contrairement à T22/T27/T30 (canonical_outfits,
   canonical_poses, group_layouts), T26/T31 n'a **pas besoin de mapping
   leaf→spec** — les templates sont génériques (s'appuient uniquement sur
   `name_en`). Aucun nouveau JSON sous `data/prompt_generator/`.
4. **Hors scope respecté** :
   - `Scène paysage` reste sur `template_landscape_2plane` (modifié pour
     supprimer horizon line) — pas de refonte.
   - `Scène spatiale`, `Scène inspirée œuvre`, `Scène ou solo personnage` non
     touchés (pas dans le brief).
   - T9, T25, T2/T3/T23, FILT, ISO, T22/T27/T30 strictement intacts —
     vérifié par 4 tests de non-régression dédiés.

## Décision / Action suivante

**Verdict : Go pour LABELS suivant.**

Critères d'acceptation tous remplis :

- [x] Routing `Solo objet météo` modifié → `template_landscape_threequarter`.
- [x] Routing `Scène intérieure` modifié → `template_indoor_scene_threequarter`.
- [x] Nouveau template `template_landscape_threequarter` (T26+T31).
- [x] Nouveau template `template_indoor_scene_threequarter` (T26).
- [x] Suppression `divided by horizon line` de `template_landscape_2plane`.
- [x] Résolution forcée 1376×768 pour les deux nouveaux templates.
- [x] Tests pytest verts (97 / 97 dans `test_prompt_generator.py`).
- [x] Citations T26 / T31 / bug v8 dans le code.

**Pas de commit dans cette livraison** — l'archi commit après revue.
