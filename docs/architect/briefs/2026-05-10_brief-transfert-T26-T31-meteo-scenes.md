# Transfert T26 + T31 — météo / scènes intérieures (basculer en paysage trois-quarts)

## Contexte

L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #6 identifie deux poches de défauts liées au routing template :

1. **`Solo objet météo`** (`sunny_day_with_sun`, `thunderstorm_with_lightning`, `foggy_morning_landscape`) → `image_simpliste` + `image_pas_coherente`. Score moyen 2.62, 62 % publishable. Routé sur `template_solo_object` (l. 532) — bug v8 (météo scénique traitée comme solo objet).
2. **Scènes intérieures + paysages** (`living_room_with_sofa`, `gaming_setup_with_keyboard`, `hallway_with_coat_rack`, `kid_using_microscope`) → `image_simpliste` + `image_physique_pb`. Routé sur `template_solo_object` (l. 558) ; `template_landscape_2plane` (l. 462-472) écrit `divided by a horizon line across the middle of the page` — antipattern T26.

Règles skill (`references/techniques.md`) :

- **T26** : vue trois-quarts pour scènes avec profondeur, **pas** `divided by horizon line`.
- **T31** : météo scénique = paysage 1376×768, pas solo_object.
- **Bug v8** : scènes atmosphériques mappées par erreur sur solo_object.

## Objectif

Transférer T26 (vue trois-quarts) + T31 (routing météo en paysage).

## Périmètre

**Modifier** :

- `src/services/prompt_generator.py` :
  - `TEMPLATE_DISPATCHER` :
    - `Solo objet météo` → router sur nouveau `template_landscape_threequarter` (résolution 1376×768) au lieu de `template_solo_object`.
    - `Scène intérieure` → router sur `template_landscape_threequarter` ou nouveau `template_indoor_scene_threequarter` (résolution 1376×768).
  - Nouveau `template_landscape_threequarter` : `[scene description] viewed from a three-quarter perspective, foreground items detailed, midground and background simplified, no horizon line, decorative elements visible`.
  - `template_landscape_2plane` : remplacer `divided by a horizon line across the middle of the page` par `viewed from a three-quarter angle with foreground and background suggested by depth`.
- `tests/test_prompt_generator.py` :
  - Test : leaf `Solo objet météo` produit positive sans `solo object on white background` mais avec `three-quarter perspective`.
  - Test : `template_landscape_2plane` n'écrit plus `divided by horizon line`.
  - Test résolution : leafs météo / scènes intérieures → 1376×768 (pas 1024×1024).
  - Test non-régression.

## Critères d'acceptation

- Routing `Solo objet météo` et `Scène intérieure` modifié.
- Nouveau template `template_landscape_threequarter`.
- Suppression `divided by horizon line` de `template_landscape_2plane`.
- Tests pytest verts.
- Citation T26 + T31 + bug v8 en commentaire.

**Mesure post-transfert (optionnelle)** : rerun sur les 7 leafs identifiés (seed offset +800). Comparer `image_simpliste` + `image_physique_pb` post vs baseline.

## Reporting

`docs/reports/2026-05-10_transfert-skill-T26-T31-meteo-scenes.md`.

## Hors scope

- Refonte complète du sous-système paysage (`Scène paysage` reste sur son template existant si non concerné).
- Couverture des autres scènes naturelles non listées.

## Estimation

~45-60 min dev + tests + rapport.
