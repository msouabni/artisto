# Bench gate ERNIE — Verdicts par transfert
Date : 2026-05-10

## Contexte

Verdicts garde-fou ERNIE pour les 3 transferts à risque pivot (T2T3T23 grille, T25 before/after, Pivot T25 frieze+grid). Calculs depuis les annotations humaines, seuil garde-fou : **30%**.

Brief source : `docs/architect/briefs/2026-05-10_brief-bench-gate-ernie.md`.

## Résumé verdicts

| Transfert | N annoté | `image_pas_coherente` | `image_incomprehensible` | Taux principal | Baseline pré | Verdict |
|---|---|---|---|---|---|---|
| **T2T3T23** | 10 | 1 | 1 | 10.00 % | 95% | **Go** |
| **T25** | 18 | 0 | 0 | 0.00 % | 89% | **Go** |
| **pivot** | 10 | 9 | 9 | 90.00 % | — | **No-Go** |

## T2T3T23 — T2T3T23 grille

- Sous-dossier : `docs/reports/poc-bench-gate-ernie-T2T3T23/`
- Statut annotations : `OK`
- Baseline pré-transfert : 91-100 % `image_pas_coherente` + `image_incomprehensible` sur 4 workflow_classes (pré-transfert)

| Métrique | Valeur |
|---|---|
| N images annotées | 10 |
| `image_pas_coherente` | 1 |
| `image_incomprehensible` | 1 |
| `image_duplication` | 0 |
| `image_anatomie_pb` | 0 |
| Taux principal (pc+inc)/(2N) | 10.00 % |
| Taux duplication | 0.00 % |
| Taux anatomie | 0.00 % |

**Verdict** : Go

_taux_primary = 10.00% ≤ seuil 30% (baseline 95% si pré-transfert)_

Détail annotations :

| Filename | Score | Tags |
|---|---|---|
| `balanced_lunch_plate_1024x1024_euler8s.png` | 6 | — |
| `bread_and_pastries_1024x1024_euler8s.png` | 6 | — |
| `fruit_imagier_with_names_1024x1024_euler8s.png` | 6 | — |
| `fruits_basket_1024x1024_euler8s.png` | 6 | — |
| `healthy_breakfast_plate_1024x1024_euler8s.png` | 6 | — |
| `proud_child_face_1024x1024_euler8s.png` | 6 | — |
| `sad_child_crying_1024x1024_euler8s.png` | 6 | — |
| `vegetable_imagier_with_names_1024x1024_euler8s.png` | 6 | — |
| `vegetables_basket_1024x1024_euler8s.png` | 6 | — |
| `weather_imagier_with_names_1024x1024_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |

## T25 — T25 before/after

- Sous-dossier : `docs/reports/poc-bench-gate-ernie-T25/`
- Statut annotations : `OK`
- Baseline pré-transfert : 89 % sur 2 workflow_classes Comparatif (pré-transfert)

| Métrique | Valeur |
|---|---|
| N images annotées | 18 |
| `image_pas_coherente` | 0 |
| `image_incomprehensible` | 0 |
| `image_duplication` | 0 |
| `image_anatomie_pb` | 0 |
| Taux principal (pc+inc)/(2N) | 0.00 % |
| Taux duplication | 0.00 % |
| Taux anatomie | 0.00 % |

**Verdict** : Go

_taux_primary = 0.00% ≤ seuil 30% (baseline 89% si pré-transfert)_

Détail annotations :

| Filename | Score | Tags |
|---|---|---|
| `beach_cleanup_volunteers_1376x768_euler8s.png` | 6 | — |
| `bike_to_work_commute_1024x1024_euler8s.png` | 6 | — |
| `compost_bin_in_garden_1376x768_euler8s.png` | 6 | — |
| `deforestation_before_after_1376x768_euler8s.png` | 6 | — |
| `earth_with_protective_hands_1376x768_euler8s.png` | 6 | — |
| `eco_friendly_house_with_panels_1024x1024_euler8s.png` | 6 | — |
| `electric_car_charging_1024x1024_euler8s.png` | 3 | — |
| `kid_planting_a_tree_1376x768_euler8s.png` | 1 | — |
| `kid_recycling_bin_sorting_1376x768_euler8s.png` | 6 | — |
| `kids_picking_up_litter_1024x1024_euler8s.png` | 6 | — |
| `polar_bear_on_melting_ice_1376x768_euler8s.png` | 6 | — |
| `rainwater_collection_barrel_1376x768_euler8s.png` | 6 | — |
| `reusable_shopping_tote_bag_1024x1024_euler8s.png` | 6 | — |
| `reusable_water_bottle_1024x1024_euler8s.png` | 6 | — |
| `solar_panels_on_roof_1376x768_euler8s.png` | 6 | — |
| `vegetable_garden_at_home_1024x1024_euler8s.png` | 6 | — |
| `wind_turbines_on_hill_1376x768_euler8s.png` | 6 | — |
| `zero_waste_kitchen_1024x1024_euler8s.png` | 6 | — |

## pivot — Pivot T25 (frieze + grid)

- Sous-dossier : `docs/reports/poc-bench-gate-ernie-pivot/`
- Statut annotations : `OK`
- Baseline pré-transfert : Bench obligatoire — pas de baseline figée pré-pivot

| Métrique | Valeur |
|---|---|
| N images annotées | 10 |
| `image_pas_coherente` | 9 |
| `image_incomprehensible` | 9 |
| `image_duplication` | 0 |
| `image_anatomie_pb` | 0 |
| Taux principal (pc+inc)/(2N) | 90.00 % |
| Taux duplication | 0.00 % |
| Taux anatomie | 0.00 % |

**Verdict** : No-Go

_taux_primary = 90.00% > seuil 30% → report T19+ canal manuel_

Détail annotations :

| Filename | Score | Tags |
|---|---|---|
| `baby_first_year_1376x768_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `cakes_and_desserts_1024x1024_euler8s.png` | 6 | — |
| `candy_shop_display_1024x1024_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `food_pyramid_for_kids_1024x1024_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `number_one_with_apple_1024x1024_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `number_zero_with_eggs_1024x1024_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `rainbow_fruit_plate_1024x1024_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `spring_blooming_meadow_1376x768_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `summer_beach_day_1376x768_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `winter_snowman_in_garden_1376x768_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |

## Décision / Action suivante

- Verdicts émis :
  - `T2T3T23` → **Go**
  - `T25` → **Go**
  - `pivot` → **No-Go**

Pour les No-Go : activer le report sur canal manuel (T19+) selon le transfert concerné. Cf. brief §13 et MEMORY.md cycle 2026-05-10.
