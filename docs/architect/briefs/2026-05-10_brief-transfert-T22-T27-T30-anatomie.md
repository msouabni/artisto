# Transfert T22 + T27 + T30 — anatomie tenues / personnalités / groupes

## Contexte

L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #5 identifie **~12 occurrences `image_anatomie_pb`** + 5 `prompt_complexe` sur trois patterns :

1. **Tenues spécialisées** (T22) : `bungee_jumper` (×2), `tango_couple` (×2), `dressage_horse`, `polo_player` — `template_solo_human` insère le `name_en` brut sans description granulaire pièce par pièce.
2. **Personnalités cartoonisées** (T27) : `captain_marvel`, `rapunzel_with_long_hair`, `lamine_yamal_cartoon`, `rafael_nadal_cartoon` — `template_personality_action` (l. 374-385) écrit explicitement `in mid-action … dynamic pose with motion lines suggesting movement` (antipattern T27 : pose forcée crispe l'anatomie).
3. **Groupe narratif → solo template** (T30) : `three_little_pigs` (3 cochons → 1 cochon généré), `spring_chicks_with_mother` — pas de détection « nombre dans le nom » (`three_*`, `seven_*`, `twelve_*`).

Le skill `prompt-taxonomy-ecosystem` règles T22 + T27 + T30 (`references/techniques.md`) propose les fix validés hors-circuit.

## Objectif

Transférer T22 (tenues granulaires) + T27 (poses canoniques) + T30 (groupes positionnés explicitement).

## Périmètre

**Créer** :

- `data/prompt_generator/canonical_outfits.json` (T22) : mapping `leaf_id → description_granulaire` pour ≥ 8 leafs (bungee_jumper, tango_couple, dressage_horse, polo_player, chirurgien, schéhérazade, sinbad, chef). Le skill fournit les descriptions validées.
- `data/prompt_generator/canonical_poses.json` (T27) : mapping `leaf_id → pose_canonique` pour ≥ 4 leafs personnalités annotés (captain_marvel, rapunzel_with_long_hair, lamine_yamal_cartoon, rafael_nadal_cartoon). Pose canonique au lieu de `mid-action / dynamic pose with motion lines`.
- `data/prompt_generator/group_layouts.json` (T30) : mapping `leaf_id → {count, layout, character_list}` pour ≥ 2 leafs groupe (three_little_pigs, spring_chicks_with_mother).

**Modifier** :

- `src/services/prompt_generator.py` :
  - `template_solo_human` et `template_solo_human_accessories` : si `leaf_id ∈ canonical_outfits` → injecter description granulaire.
  - `template_personality_action` : si `leaf_id ∈ canonical_poses` → remplacer `mid-action / dynamic pose with motion lines` par la pose canonique. Sinon → conserver mais logger warning.
  - Ajouter détection `_NUMBER_PREFIXES = {'three_', 'four_', 'five_', 'six_', 'seven_', 'eight_', 'nine_', 'ten_', 'twelve_'}` : si leaf_id matche ET `leaf_id ∈ group_layouts` → router vers nouveau `template_group_positioned` (positionnement explicite par personnage). Sinon → fallback solo + warning.
  - Nouveau `template_group_positioned` minimal : `[N] [character_type] arranged in [layout], with [character_list described]`.
- `tests/test_prompt_generator.py` :
  - Tests présence/absence pour les 3 mappings.
  - Test `three_little_pigs` produit positive avec « three pigs » + layout (vs « one pig »).
  - Test non-régression : leafs non listés dans les 3 mappings utilisent leur template standard.

## Critères d'acceptation

- 3 fichiers JSON créés avec couverture minimale.
- Templates modifiés + nouveau `template_group_positioned`.
- Tests pytest verts.
- Citation T22/T27/T30 en commentaire de code.

**Mesure post-transfert (optionnelle, recommandée)** : rerun sur les 12 leafs identifiés ci-dessus (seed offset +600). Comparer `image_anatomie_pb` post vs baseline.

## Reporting

`docs/reports/2026-05-10_transfert-skill-T22-T27-T30-anatomie.md` — Contexte / Modifications / Tests / Mesure post / Décision.

## Hors scope

- Couverture exhaustive des leafs (extension par PR ultérieure).
- Refactor du dispatcher au-delà du minimum nécessaire pour la détection groupe.
- Quantification du seuil `prompt_complexe` (T19+ #5 du rapport — canal manuel).

## Estimation

~75-90 min dev + tests + rapport.

Si dépassement marqué : découper en 3 PR (T22, T27, T30 séparés).
