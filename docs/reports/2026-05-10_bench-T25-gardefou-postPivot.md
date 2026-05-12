# POC — Bench garde-fou T25 (verdict post-pivot)
Date : 2026-05-10

## Contexte

Verdict du bench garde-fou T25 mesurant l'impact du pivot 2026-05-10 (templates `template_frieze_1xN` + `template_grid_3x3_imagier` réécrits en BEFORE/AFTER + SPOT THE DIFFERENCE) sur le taux de défauts composition (`image_pas_coherente` + `image_incomprehensible`).

Brief source : `docs/architect/briefs/2026-05-10_brief-bench-gardefou-T25.md`.

Annotations lues depuis : `docs\reports\poc-bench-T25-postPivot\annotations.json` (statut : OK).

## Leaves testées (index-bench-T25.json)

| # | leaf_id | workflow_class | seed | output_file |
|---|---|---|---|---|
| 1 | `teenager_with_backpack` | Frise narrative 1×N (pattern X2) | 9870 | `teenager_with_backpack_1376x768_T25_euler8s.png` |
| 2 | `child_at_school_age` | Frise narrative 1×N (pattern X2) | 9877 | `child_at_school_age_1376x768_T25_euler8s.png` |
| 3 | `life_cycle_full_poster` | Frise narrative 1×N (pattern X2) | 9884 | `life_cycle_full_poster_1376x768_T25_euler8s.png` |
| 4 | `toddler_learning_to_walk` | Frise narrative 1×N (pattern X2) | 9891 | `toddler_learning_to_walk_1376x768_T25_euler8s.png` |
| 5 | `parent_with_child` | Frise narrative 1×N (pattern X2) | 9898 | `parent_with_child_1376x768_T25_euler8s.png` |
| 6 | `baby_first_year` | Frise narrative 1×N (pattern X2) | 9905 | `baby_first_year_1376x768_T25_euler8s.png` |
| 7 | `grandparent_with_grandchild` | Frise narrative 1×N (pattern X2) | 9912 | `grandparent_with_grandchild_1376x768_T25_euler8s.png` |
| 8 | `young_adult_at_work` | Frise narrative 1×N (pattern X2) | 9919 | `young_adult_at_work_1376x768_T25_euler8s.png` |
| 9 | `classroom_with_teacher` | Multi-sujets (frise) | 10000 | `classroom_with_teacher_1376x768_T25_euler8s.png` |
| 10 | `school_bus_with_kids` | Multi-sujets (frise) | 10007 | `school_bus_with_kids_1376x768_T25_euler8s.png` |
| 11 | `ice_cream_and_sorbets` | Imagier différencié 3×3 | 10311 | `ice_cream_and_sorbets_1024x1024_T25_euler8s.png` |
| 12 | `dairy_products_milk` | Imagier différencié 3×3 | 10325 | `dairy_products_milk_1024x1024_T25_euler8s.png` |
| 13 | `vegetables_basket` | Imagier différencié 3×3 | 10332 | `vegetables_basket_1024x1024_T25_euler8s.png` |
| 14 | `fruits_basket` | Imagier différencié 3×3 | 10339 | `fruits_basket_1024x1024_T25_euler8s.png` |
| 15 | `bread_and_pastries` | Imagier différencié 3×3 | 10290 | `bread_and_pastries_1024x1024_T25_euler8s.png` |
| 16 | `decorative_number_ten_fingers` | Multi-sujets via grille (méta-pattern §2) | 10423 | `decorative_number_ten_fingers_1024x1024_T25_euler8s.png` |
| 17 | `number_zero_with_eggs` | Multi-sujets via grille (méta-pattern §2) | 10395 | `number_zero_with_eggs_1024x1024_T25_euler8s.png` |
| 18 | `number_three_with_birds` | Multi-sujets via grille (méta-pattern §2) | 10402 | `number_three_with_birds_1024x1024_T25_euler8s.png` |
| 19 | `number_one_with_apple` | Multi-sujets via grille (méta-pattern §2) | 10437 | `number_one_with_apple_1024x1024_T25_euler8s.png` |
| 20 | `number_nine_with_cars` | Multi-sujets via grille (méta-pattern §2) | 10416 | `number_nine_with_cars_1024x1024_T25_euler8s.png` |

## Annotations utilisateur

| filename | score | image_tags |
|---|---|---|
| `baby_first_year_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `bread_and_pastries_1024x1024_T25_euler8s.png` | 6 | `image_compo_bonne`, `image_coherente` |
| `child_at_school_age_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `classroom_with_teacher_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `dairy_products_milk_1024x1024_T25_euler8s.png` | 3 | — |
| `decorative_number_ten_fingers_1024x1024_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `fruits_basket_1024x1024_T25_euler8s.png` | 6 | — |
| `grandparent_with_grandchild_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `ice_cream_and_sorbets_1024x1024_T25_euler8s.png` | 6 | — |
| `life_cycle_full_poster_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `number_nine_with_cars_1024x1024_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `number_one_with_apple_1024x1024_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `number_three_with_birds_1024x1024_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `number_zero_with_eggs_1024x1024_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `parent_with_child_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `school_bus_with_kids_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `teenager_with_backpack_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `toddler_learning_to_walk_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |
| `vegetables_basket_1024x1024_T25_euler8s.png` | 6 | — |
| `young_adult_at_work_1376x768_T25_euler8s.png` | 1 | `image_pas_coherente`, `image_incomprehensible` |

## Calcul taux post-pivot vs baseline

| Métrique | Baseline pré-pivot | Post-pivot |
|---|---|---|
| N (leaves annotées) | 26 | 20 |
| `image_pas_coherente` | 14 | 15 |
| `image_incomprehensible` | 14 | 15 |
| Taux ((pc+inc) / (2×N)) | 53.85 % | 75.00 % |

Seuil retrait (70 % × baseline) = **37.69 %** (formule §84 du brief).

## Décision / Action suivante

**Verdict : RETRAIT T25** — pivot insuffisant, repli sur canal manuel.

taux_post = 0.7500 >= seuil 0.3769 (70 % x baseline 0.5385)

Action : activer le switch flag `_T2T3T23_GRID_AVAILABLE = False` dans `src/services/prompt_generator.py` (1 ligne) puis reporter T19+ sur canal manuel (cf. brief §13).

## Points d'attention

- RAS.
