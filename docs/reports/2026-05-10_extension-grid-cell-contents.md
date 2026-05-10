# Extension `grid_cell_contents.json` — couverture exhaustive grilles imagier
Date : 2026-05-10

## Contexte

Suite au verdict **Go** du bench gate ERNIE T2T3T23 (10 % résiduel vs baseline 95 %, seuil 30 %), exécution du brief `docs/architect/briefs/2026-05-10_brief-extension-grid-cell-contents.md` : compléter `data/prompt_generator/grid_cell_contents.json` pour atteindre 100 % de couverture sur les 4 workflow_classes grille.

État initial : 16 leafs déjà couverts (livraison T2T3T23 livrée à 16, brief annonçait 14 — écart résolu par lecture directe du JSON).

## Audit

### Workflow_classes ciblées (cartographie)

| Sous-catégorie | Workflow_class | Leaf count |
|---|---|---|
| `picture_word_imagier` | Grille imagier annoté | 8 |
| `healthy_eating` | Imagier différencié OU Solo | 7 |
| `emotions_and_expressions` | Imagier annoté 3×3 OU Solo visage | 10 |
| `food_categories` | Imagier différencié 3×3 | 8 |
| **Total cartographié** | | **33** |

### Diff vs JSON existant

**Déjà couverts (16) — inchangés :**
- picture_word_imagier (8/8) : `fruit_imagier_with_names`, `vegetable_imagier_with_names`, `color_imagier_with_names`, `feeling_imagier_with_names`, `clothing_imagier_with_names`, `weather_imagier_with_names`, `transport_imagier_with_names`, `house_object_imagier`
- healthy_eating (2/7) : `healthy_breakfast_plate`, `balanced_lunch_plate`
- food_categories (6/8) : `fruits_basket`, `vegetables_basket`, `bread_and_pastries`, `cakes_and_desserts`, `ice_cream_and_sorbets`, `dairy_products_milk`

**Manquants identifiés (17) :**
- `healthy_eating` (5) : `food_pyramid_for_kids`, `rainbow_fruit_plate`, `vegetable_garden_basket`, `child_drinking_water`, `healthy_snack_basket`
- `emotions_and_expressions` (10) : `happy_child_smiling`, `sad_child_crying`, `angry_child_face`, `scared_child_face`, `surprised_child_face`, `calm_child_breathing`, `shy_child_face`, `proud_child_face`, `curious_child_face`, `emotion_chart_poster`
- `food_categories` (2) : `meat_and_fish_market`, `candy_shop_display`

## Curation

17 entrées ajoutées dans `data/prompt_generator/grid_cell_contents.json` (9 cellules par grille, items concrets visuellement distincts).

### Audit FILT — décisions prises

| Token FILT | Stratégie |
|---|---|
| `orange` (couleur) | Whitelist contextuelle (`round/fresh/peeled + orange + with/of`) → `round orange with dimpled skin` préservé |
| `glass` (gloss) | Whitelist contextuelle (`drinking/tall + glass`, `glass of <liquide>`) → `tall drinking glass filled with water` préservé |
| `chocolate` | **Évité complètement** dans `candy_shop_display` (whitelist `dark + chocolate` ne protège que `dark`). Items décrits par silhouette : `wrapped candy bar`, `round bonbon`, `licorice rope`, etc. |
| `glass` (`magnifying glass`) | Reformulé : `round magnifier with handle near the eye` (whitelist ne couvre pas ce contexte) |
| `deep` | Évité dans `calm_child_breathing` : `deep breath` → `long breath` |
| `cream`, `gold/silver`, `red/yellow/blue` | Aucune occurrence dans les nouvelles entrées |
| `rainbow` (titre `rainbow_fruit_plate`) | Titre injecté = `FRUIT PLATE` (le `rainbow` du leaf_id n'apparaît jamais dans le prompt) |

### Note T23 (dispatch)

Pour `emotions_and_expressions`, T23 (`_is_t23_singular_face`) redirige les leafs préfixés émotion (9 sur 10) vers `template_solo_expressive_face` au runtime — donc en prod ces entrées grille servent uniquement de fallback si T23 est désactivé. Décision : ajouter quand même les entrées, conformément au critère "100 % couverture cartographiée" du brief. Seul `emotion_chart_poster` reste sur la grille en production normale.

## Tests

Test ajouté dans `tests/test_prompt_generator.py` :

- `test_t2_grid_cell_contents_covers_all_cartographed_grid_leafs` : charge `taxonomy_production_cartography.json` + `coloring_taxonomy_full.json`, identifie les leafs sous les 4 workflow_classes, asserte que chaque leaf a une entrée dans `_GRID_CELL_CONTENTS`. Échec explicite avec liste des manquants si nouveau leaf cartographié sans entrée JSON.

```bash
python -m pytest tests/test_prompt_generator.py -q
# 124 passed in 0.40s
```

Suite globale (hors `test_content_generator.py` qui a une `ImportError` legacy non liée — `HARAKAT_RE` non exporté) :

```bash
python -m pytest -q --ignore=tests/test_content_generator.py
# 5 failed, 387 passed in 3.18s
```

Les 5 failed sont la dette legacy annoncée (workflow ERNIE / negative-prompt). Aucune régression introduite.

## Smoke build_prompt

Sur 5 nouveaux leafs variés (incluant cas FILT critique et T23 dispatch) :

| leaf_id | Template effectif | Warning fallback ? | Items injectés |
|---|---|---|---|
| `food_pyramid_for_kids` | `template_grid_3x3_imagier` | Aucun | 9 cellules nommées présentes |
| `rainbow_fruit_plate` | `template_grid_3x3_imagier` | Aucun | Title `FRUIT PLATE` (rainbow évité) |
| `meat_and_fish_market` | `template_grid_3x3_imagier` | Aucun | OK |
| `candy_shop_display` | `template_grid_3x3_imagier` | Aucun | Aucune mention de `chocolate` (FILT-safe) |
| `emotion_chart_poster` | `template_grid_3x3_imagier` | Aucun | 9 émotions canoniques |
| `child_drinking_water` | `template_grid_3x3_imagier` | Aucun | `tall drinking glass` préservé (whitelist) |
| `sad_child_crying` | `template_solo_expressive_face` (T23) | Aucun | Bypass grille — entrée JSON inutilisée en prod |

Aucun warning `grid_cell_contents missing` détecté sur les nouveaux leafs.

## Points d'attention

1. **9 entrées émotions = fallback défensif uniquement.** En prod normale, T23 redirige `happy_*`, `sad_*`, `angry_*`, `scared_*`, `surprised_*`, `calm_*`, `shy_*`, `proud_*`, `curious_*` vers `template_solo_expressive_face`. Les entrées grille servent si T23 est désactivé ou si la heuristique évolue. Pas d'arbitrage requis — choix conservateur cohérent avec le brief.
2. **Whitelist FILT non-extension nécessaire.** Tous les items naturels souhaitables (orange fruit, drinking glass, glass of milk) sont déjà couverts par `_PROTECTED_NOMINAL_PATTERNS`. `chocolate` reste volontairement non protégé — contournement par silhouette appliqué dans `candy_shop_display`.
3. **`magnifying glass` non protégé.** Whitelist actuelle (`drinking|tall|small|empty|full|water|milk|juice|wine`) ne couvre pas `magnifying`. Si une demande future vise des grilles "outils du chercheur / lentille", ajouter `magnifying|reading` à la whitelist (~5 lignes dans `prompt_filters.py`). Pas urgent — un seul item dans toute la curation.
4. **Couverture exhaustive validée par test pytest.** Toute future leaf grille (nouveau sub-cat avec class dans `_T2_GRID_WORKFLOW_CLASSES`) déclenchera l'échec du test si pas d'entrée JSON associée — garde-fou en place.

## Décision / Action suivante

**Livré :**
- 17 leafs ajoutés (`grid_cell_contents.json`, schéma respecté).
- Test de couverture exhaustive ajouté (`tests/test_prompt_generator.py::test_t2_grid_cell_contents_covers_all_cartographed_grid_leafs`).
- Suite `test_prompt_generator.py` : 124 passed.
- Suite globale : 387 passed / 5 failed inchangé (dette legacy).
- Pas de modification du code Python.

**Pas de commit** — review archi puis validation. Critères d'acceptation du brief tous remplis.
