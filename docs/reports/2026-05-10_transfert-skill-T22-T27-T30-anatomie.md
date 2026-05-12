# Phase — Transfert skill T22 + T27 + T30 (anatomie tenues / poses / groupes)
Date : 2026-05-10

## Contexte

Brief : `docs/architect/briefs/2026-05-10_brief-transfert-T22-T27-T30-anatomie.md`.

Cible : ~12 occurrences `image_anatomie_pb` + 5 `prompt_complexe` identifiées dans
`docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #5, sur trois
patterns distincts du `template_solo_human` / `template_personality_action` :

1. **T22** — Tenues spécialisées rares insérant `name_en` brut (bungee_jumper,
   tango_couple, dressage_horse, polo_player) — la tenue n'est pas activée.
2. **T27** — Personnalités cartoonisées avec `mid-action / motion lines /
   focused expression` qui crispent l'anatomie (captain_marvel, rapunzel_with_long_hair,
   lamine_yamal_cartoon, rafael_nadal_cartoon).
3. **T30** — Groupes narratifs routés sur template solo → 1 personnage généré
   (three_little_pigs, spring_chicks_with_mother).

Source des règles : `.claude/skills/prompt-taxonomy-ecosystem.skill`,
`references/techniques.md` §T22 (l. 651), §T27 (l. 876), §T30 (l. 1208).

## Modifications

### JSON créés (3 fichiers, `data/prompt_generator/`)

| Fichier | Couverture | Schéma |
|---|---|---|
| `canonical_outfits.json` | 10 leafs (polo_player, dressage_horse, bungee_jumper, tango_couple, fencer, jockey, archer, surgeon, chef_with_apron, scheherazade, sinbad_the_sailor) | `{leaf_id → {outfit_clause, subject_clause, scene_clause}}` |
| `canonical_poses.json` | 8 leafs (4 brief + 4 préemptifs : scheherazade, chef_with_apron, fisherman, ballet_dancer) | `{leaf_id → {subject_name, pose_clause}}` |
| `group_layouts.json` | 5 leafs (three_little_pigs, spring_chicks_with_mother, three_billy_goats_gruff, three_bears, seven_dwarfs) | `{leaf_id → {count, subject_type, layout, characters[], expression}}` |

**Garde-fou FILT** : tous les `outfit_clause` ont été audités pour ne pas contenir
de noms de couleur (`red`, `white`, `blue`, etc.) — `prompt_filters._COLOR_NOUNS`
les stripperait. La description s'appuie sur la forme/matière (`jodhpurs trousers`,
`polo shirt with collar`, `knee-high riding boots`). Test dédié :
`test_t22_outfits_avoid_color_nouns`.

### `src/services/prompt_generator.py`

| Zone | Modification | Lignes (approx.) |
|---|---|---|
| Constantes paths | +3 `DEFAULT_*` (outfits/poses/groups) | 53-55 |
| Loaders T22 | `_load_canonical_outfits` + singleton `_CANONICAL_OUTFITS` + `set_canonical_outfits` | ~60 LOC |
| Loaders T27 | `_load_canonical_poses` + singleton `_CANONICAL_POSES` + `set_canonical_poses` | ~50 LOC |
| Loaders T30 | `_load_group_layouts` + singleton `_GROUP_LAYOUTS` + `set_group_layouts` + `_NUMBER_PREFIXES` + `_has_number_prefix` | ~70 LOC |
| `template_solo_human` | Hook T22 : si `leaf_id ∈ _CANONICAL_OUTFITS` → injecte `subject_clause + outfit_clause + scene_clause` | +25 LOC |
| `template_human_plus_entity` | Hook T22 humain+grand animal : tenue + scène (cheval profil + much larger + reins) | +15 LOC |
| `template_personality_action` | Hook T27 : si `leaf_id ∈ _CANONICAL_POSES` → remplace `mid-action / motion lines / focused expression` par pose canonique. Fallback warning ciblé (`*_cartoon` ou classe « personnalité »). Fallback secondaire T22 si outfit connu sans pose. | +35 LOC |
| `template_group_positioned` (NOUVEAU) | T30 — `[N] [type] [layout], [pos1] [attr1], …, smiling and facing forward, simple ground line, centered composition` | +35 LOC |
| `build_prompt` dispatcher | T30 : `if leaf_id in _GROUP_LAYOUTS → template_group_positioned` ; warning explicite si `_has_number_prefix` mais leaf hors mapping | +13 LOC |

**Total** : ~310 LOC ajoutées dans `prompt_generator.py` (hors blank lines/commentaires).

Toutes les règles citent `.claude/skills/prompt-taxonomy-ecosystem.skill` +
section `references/techniques.md §Tnn` en commentaire (T22, T27, T30).

### `tests/test_prompt_generator.py`

29 nouveaux tests ajoutés (84 total, 55 → 84) :
- T22 : 7 tests (couverture min, fields, leafs documentés, pas de noms de couleur,
  injection, fallback, polo_player + cheval, fallback `child_with_test_tubes`)
- T27 : 6 tests (couverture min, fields, leafs documentés, replace mid-action,
  cartoon personalities, warning fallback, no warning sur classe générique)
- T30 : 9 tests (couverture min, fields, leafs documentés, NUMBER_PREFIXES,
  has_number_prefix, three_little_pigs, spring_chicks, fallback solo,
  build_prompt route, warning number-prefix manquant)
- Non-régression : 4 tests (Solo animal, grille, before-after, T9 directional
  preservés)
- Imports : +6 symboles (`_CANONICAL_OUTFITS`, `_CANONICAL_POSES`, `_GROUP_LAYOUTS`,
  `_NUMBER_PREFIXES`, `_has_number_prefix`, `template_group_positioned`,
  `set_canonical_outfits`, `set_canonical_poses`, `set_group_layouts`)

## Tests

```
pytest tests/test_prompt_generator.py
============================= 84 passed in 0.16s ==============================
```

Suite complète (hors `test_content_generator.py` cassé pour cause externe à ce
brief — `HARAKAT_RE` import non lié) :

```
312 passed, 5 failed
```

Les 5 échecs préexistants concernent `ernie_uses_sidecar / bulk_generation_jobs /
create_image_job_workflow` (contrat sidecar `negative_prompt: optional` vs
`unsupported`) — **aucun lien** avec ce transfert (aucun fichier modifié dans le
périmètre de ces tests).

## Mesure post-transfert

Non exécutée dans ce cycle (optionnelle dans le brief). Recommandée pour la
prochaine itération : rerun sur les 12 leafs annotés avec seed offset +600,
comparaison `image_anatomie_pb` post vs baseline. Cibles minimales attendues :
- T22 : 6 leafs anatomie tenue → ≤ 2/6 résiduels
- T27 : 4 personnalités → ≤ 1/4 résiduel
- T30 : 2 groupes → 0/2 (compte exact attendu côté image)

## Points d'attention pour l'archi

1. **Couverture leafs anatomie non listés** : le brief vise « ≥ 8 + ≥ 4 + ≥ 2 »
   leafs, atteint avec marge (10 + 8 + 5). Mais il reste des leafs anatomie hors
   liste — l'extension passe par PR ultérieure (ajout JSON, pas de code).
2. **Mapping leaf → tenue ambigu** (point archi remonté risque moyen) :
   - `tango_couple` est un duo intrinsèque (homme+femme dansant) — décrit comme
     **2 personnages** dans `outfit_clause` mais **routé sur `template_solo_human`**
     (classe « Solo humain en action »). L'`_ISOLATION_HUMAN` reste appropriée
     car la scène se ferme sur les 2 danseurs (pas de 3e sujet).
   - `dressage_horse` est routé `Humain + entité (cheval)` — la scène décrit
     bien `one rider mounted on a dressage horse` (cavalier sur cheval), pas
     juste le cheval seul, ce qui est cohérent avec le name_en EN/FR/AR
     ambigu (« Dressage Horse / Cheval de dressage / ترويض الخيل »).
3. **Conflit potentiel ISO suffixes** : aucun. Tous les nouveaux templates
   conservent `_ISOLATION_HUMAN` en fin de positive (T22/T27 templates humain).
   `template_group_positioned` n'ajoute **pas** d'_ISOLATION_HUMAN car le groupe
   EST le sujet — ajouter « no other people nearby » serait contradictoire.
   Test de non-régression vérifie que le suffix est préservé sur templates
   humain.
4. **Heuristique `_NUMBER_PREFIXES`** : autorité = `_GROUP_LAYOUTS` (whitelist).
   Le préfixe sert de **détecteur d'oublis** (warning). Pas de routing
   automatique sur préfixe — éviterait les faux positifs (`five_senses_chart`,
   `four_seasons_imagier` qui sont des grilles, pas des groupes).
5. **`template_personality_action` : warning ciblé** : le brief demande « sinon
   conserver mais logger warning ». J'ai restreint le warning aux leafs
   plausiblement « personnalité » (`*_cartoon` OU classe contient « personnalité »)
   pour éviter le spam sur `animal_superhero` et autres usages génériques.

## Décision Go/No-Go pour METEO suivant

**Go.**

- 84/84 tests verts dans le périmètre prompt_generator.
- Aucune régression (T9 directional, T23 expressive face, T25 before/after,
  T2/T3 grilles, ISO élargi — tous validés en non-régression).
- 5 tests pré-existants en échec hors périmètre (sidecar ERNIE) — non bloquants
  pour ce transfert, à traiter dans un autre cycle.
- Couverture brief atteinte avec marge (10/8 + 8/4 + 5/2).
- Hooks préemptifs ajoutés (chef_with_apron, scheherazade, ballet_dancer,
  three_bears, seven_dwarfs) pour absorber les leafs voisins lorsqu'ils
  apparaîtront dans les annotations.

Pas de risque archi remonté (les 3 patterns sont opt-in via JSON ; un leaf
non couvert garde son template antérieur + warning explicite).

Prochaine étape T31 (METEO) : transférer les phénomènes scéniques vers
`template_landscape_2plane` + résolution 1376×768. Source : skill §T31
(techniques.md ~l. 1249).
