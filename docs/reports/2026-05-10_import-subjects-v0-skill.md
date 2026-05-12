# Import — subjects v0 (skill)
Date : 2026-05-10

## Contexte
Import idempotent des leaves de `coloring_taxonomy_full.json` vers la table `subject` (source='skill_v0', status='draft'). Source : skill `prompt-taxonomy-ecosystem` v0.

## Compteurs

| Mesure | Valeur |
|---|---|
| Total leaves taxonomie | 1376 |
| Leaves considérés (limit appliqué) | 1376 |
| Subjects insérés | 1376 |
| Subjects déjà présents (idempotence) | 0 |
| Leaves orphelins (sans term en BD) | 0 |
| Source | `skill_v0` |
| Dry-run | False |
| Import run id | `20260510T191909Z` |

## Distribution par root

| Root | Subjects insérés |
|---|---|
| animals | 136 |
| alphabet_and_visual_language | 129 |
| fictional_characters | 114 |
| professions | 108 |
| vehicles_and_machines | 88 |
| sports_and_physical_activities | 86 |
| human_body_and_health | 74 |
| festivals_and_celebrations | 73 |
| tools_and_tooling | 70 |
| nature_and_environment | 66 |
| geometry_and_math | 64 |
| sports_personalities | 64 |
| daily_life_and_environments | 59 |
| household_appliances | 57 |
| fantasy_magic_and_tales | 55 |
| modern_themes_and_trends | 51 |
| sciences_and_technology | 43 |
| art_creativity_and_decorative_patterns | 39 |

## Échantillon (10 premiers)

| id | term_id | name |
|---|---|---|
| `sub_abstract_cubism_portrait` | `abstract_cubism_portrait` | Abstract Cubism Portrait |
| `sub_abstract_dripping_paint` | `abstract_dripping_paint` | Abstract Dripping Paint |
| `sub_abstract_zentangle` | `abstract_zentangle` | Abstract Zentangle |
| `sub_action_camera` | `action_camera` | Action Camera |
| `sub_actor_on_stage` | `actor_on_stage` | Actor on Stage |
| `sub_acute_angle` | `acute_angle` | Acute Angle |
| `sub_adjustable_wrench` | `adjustable_wrench` | Adjustable Wrench |
| `sub_advanced_mandala_for_teens` | `advanced_mandala_for_teens` | Advanced Mandala for Teens |
| `sub_adventure_time_finn` | `adventure_time_finn` | Adventure Time Finn |
| `sub_african_elephant` | `african_elephant` | African Elephant |

## Liste orphelins

_Aucun orphelin — tous les leaves ont un term en BD._

## Décision / Action suivante

**Go** — 1376 subjects insérés, 0 déjà présents. Prochaine étape : annotation manuelle (Vague 2) puis génération de `prompt_positive` (job `subject_prompt_generation`).

Rapport JSON brut : `data\import\subjects_v0_20260510T191909Z.json`
