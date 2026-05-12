# Transfert skill — T5 + T6 + T7 (couleur / surfaces / 3D, prophylactique)

Date : 2026-05-10

## Contexte

Transfert prophylactique des règles `T5` (strip noms couleur explicites),
`T6` + extension T6 (remplacement ancres chromatiques implicites + strip
matières brillantes) et `T7` (strip rendu 3D involontaire) du skill
`prompt-taxonomy-ecosystem` (`references/techniques.md` §T5/§T6/§T7) vers
le pipeline `PromptGenerator`.

Brief source : `docs/architect/briefs/2026-05-10_brief-transfert-T5-T6-T7-couleur-surfaces.md`.
Volume corpus actuel : 1 occurrence `image_gris_residuel` (`jaguar_in_jungle`)
— transfert prophylactique en vue du critère prod `cr < 0.001`.

## Modifications

### Nouveau module — `src/services/prompt_filters.py` (278 LOC)

API publique :

| Fonction                | Règle skill        | Effet                                                      |
|-------------------------|--------------------|------------------------------------------------------------|
| `strip_color_nouns`     | T5                 | Supprime `red`, `blue`, `golden`, `silver`, … (49 entrées) |
| `replace_color_anchors` | T6 + Extension T6  | `rainbow → colorful`, `sunset → sky scene`, `autumn → seasonal scene`, `tropical → exotic`, `fire/flame → flame shape` (7 entrées, substitution atomique pour éviter double-replacement) |
| `strip_glossy_terms`    | Extension T6 (≡§T7 ancres matière) | Supprime `shiny`, `glossy`, `metallic`, `chrome`, `glass`, `wet`, `chocolate`, … (12 entrées) |
| `strip_3d_terms`        | T7                 | Supprime `shaded`, `volumetric`, `realistic textures`, `depth shading`, `photorealistic`, … (13 entrées) |
| `apply_all_filters`     | Composition        | Pipe T6 → T5 → ext T6 → T7 (ordre : remplacements avant strips)|
| `describe_filters`      | Introspection      | Retourne tailles vocabulaires (utile reporting)            |

Implémentation :
- Pattern unique compilé par filtre (`_word_boundary_pattern`) avec
  `(?<![A-Za-z])…(?![A-Za-z])` — évite les faux positifs de sous-chaîne
  (ex. `orangery` n'est pas matché par `orange`).
- Tri longueur décroissante des tokens pour préférer multi-mots (ex.
  `realistic textures` est strippé en bloc avant que `realistic` seul
  ne soit considéré).
- `_collapse_whitespace` nettoie virgules orphelines / espaces multiples
  introduits par les strips.
- Vocabulaires `frozenset` immuables, citations skill en commentaire de chaque bloc.

### Hook dans `src/services/prompt_generator.py` (5 lignes)

Localisation : `build_prompt`, juste après le choix `LEAF_OVERRIDES vs template_fn`.
Le hook est **inactif** pour les `LEAF_OVERRIDES` (humains validés) et **actif**
pour le retour template — sur la portion **après le `STYLE_BLOCK`**, qui contient
volontairement « black and white line art, no shading, no fill, white background »
(instructions style anti-couleur/anti-3D — filtrer ce bloc serait un bug).

```python
# Hook prophylactique T5+T6+T7 : strip noms couleur / ancres / surfaces 3D
# On ne filtre QUE la portion sujet (après STYLE_BLOCK)…
if positive.startswith(STYLE_BLOCK):
    tail = positive[len(STYLE_BLOCK):].lstrip(", ")
    filtered_tail = _apply_prompt_filters(tail)
    positive = f"{STYLE_BLOCK}, {filtered_tail}" if filtered_tail else STYLE_BLOCK
else:
    positive = _apply_prompt_filters(positive)
```

Import ajouté en tête de fichier : `from services.prompt_filters import apply_all_filters as _apply_prompt_filters`.

## Tests

### Nouveau — `tests/test_prompt_filters.py` (258 LOC, 40 tests)

| Bloc                       | # tests | Couverture                                        |
|----------------------------|---------|---------------------------------------------------|
| `TestStripColorNouns`      | 7       | T5, casse, mot entier, neutre, vide               |
| `TestReplaceColorAnchors`  | 6       | T6 (rainbow / sunset / autumn / tropical), neutre, vide |
| `TestStripGlossyTerms`     | 5       | Ext T6 (shiny/glossy/metallic/chrome/glass/chocolate), neutre, vide |
| `TestStrip3dTerms`         | 5       | T7 mono- et multi-mots, neutre, vide              |
| `TestApplyAllFilters`      | 6       | Composition kitchen-sink, sujet préservé, idempotence, robustesse `None` |
| `TestVocabularies`         | 5       | Sanity check vocabulaires vs exemples skill       |
| Paramétrés                 | 4       | Inputs neutres → identité (non-régression)        |
| Anti-double-substitution   | 1       | `fire` ne produit pas `flame shape shape`         |
| Intégration LEAF_OVERRIDES | 1       | Aucun override n'est filtré par le hook           |

Résultats : `40 passed in 0.06s`.

### Régression suite globale

`pytest --ignore=tests/test_content_generator.py` (fichier cassé pré-existant
indépendant : `ImportError: cannot import name 'HARAKAT_RE' from 'services.ollama_json'`) :
- **250 passed**, **5 failed** — 5 échecs **pré-existants** orthogonaux
  (`test_workflow_template_sidecar`, `test_create_image_job_workflow`,
  `test_bulk_generation_jobs`) sur la capability `negative_prompt` ERNIE
  (`'optional'` vs `'unsupported'`). Aucun lien avec le module prompt_filters.

## Mesure post-transfert (smoke)

Smoke d'intégration sur 6 leafs avec triggers couleur/surface/3D :

| leaf_id                          | Avant filtre (sujet)                   | Après filtre (sujet)               | Règle |
|----------------------------------|----------------------------------------|------------------------------------|-------|
| `red_panda`                      | `one single red panda standing…`       | `one single panda standing…`       | T5    |
| `fire_dragon`                    | `one single fire dragon standing…`     | `one single flame shape dragon…`   | T6    |
| `rainbow_fruit_plate`            | `…rainbow Fruit Plate scene…`          | `…colorful Fruit Plate scene…`     | T6    |
| `autumn_falling_leaves`          | `…autumn scene Falling Leaves…`        | `…seasonal scene Falling Leaves…`  | T6    |
| `tropical_rainforest_canopy`     | `…tropical rainforest canopy…`         | `…exotic rainforest canopy…`       | T6    |
| `hanukkah_gelt_chocolate_coins`  | `one chocolate hanukkah gelt coins…`   | `one hanukkah gelt coins…`         | Ext T6|

Non-régression vérifiée :
- `lion_in_savanna`, `jaguar_in_jungle` : positive **inchangé** (aucun trigger).
- `sheep_with_lamb`, `eid_al_adha_sheep` (`LEAF_OVERRIDES`) : positive **inchangé**
  (le hook saute cette branche).
- `STYLE_BLOCK` (« black and white line art, no shading, white background ») :
  **toujours préservé** (head-protection).

Volume corpus actuel ne permet pas de mesure `cr < 0.001` significative —
conforme au caractère prophylactique du brief.

## Points d'attention

1. **Bug fixé pendant le dev** : substitution naïve T6 en boucle produisait
   `flame shape shape` sur `fire dragon` (token `fire → flame shape` puis
   `flame` re-matché). Corrigé par substitution atomique en un seul `re.sub`
   avec lambda + map. Test garde-fou ajouté (`test_fire_does_not_create_double_replacement`).

2. **STYLE_BLOCK head-protection** : sans cela, le filtre supprimait
   `black`, `white`, `shading` du bloc style — instructions méta volontairement
   anti-couleur/anti-3D. Le hook détecte le préfixe `STYLE_BLOCK` et ne filtre
   que la portion sujet. Pattern simple, robuste tant que tous les templates
   commencent par `STYLE_BLOCK` (vérifié sur les 11 templates actifs).

3. **Vocabulaire T5 étendu au-delà du skill strict** : ajout de nuances
   (`crimson`, `magenta`, `lavender`, etc.) et intensités (`dark`, `light`,
   `bright`, `vivid`) en plus des couleurs de base — le skill cite « tous les
   noms de couleur » sans liste exhaustive, on a élargi prudemment. Mots
   blacklistés : 49 entrées, tous testés négatifs sur les leafs neutres existants.

4. **Conflits avec autres agents parallèles** : aucun observé. Les modifs T9
   (`_DIRECTIONAL_OVERRIDES`) et T25 (`template_before_after`,
   `DEFAULT_BEFORE_AFTER_STATES`) coexistent proprement avec mes 5 lignes de
   hook + 1 ligne d'import. Les tests d'intégration sur leafs T9
   (`golden_retriever`, `running_giraffe`) et T25 (templates `before_after` —
   ex. `autumn_falling_leaves`) passent sans régression côté sujet.

5. **Hors scope confirmé** : `NEGATIVE_V3` non touché ; filtres AR
   (`ollama_json.py`) non touchés.

## Décision / Action suivante

**Go** pour merge :
- Module isolé, vocabulaire cité (skill `references/techniques.md`),
  40 tests verts, hook localisé (5 lignes) qui respecte `LEAF_OVERRIDES` et
  `STYLE_BLOCK`.
- Aucune régression sur la suite pytest (les 5 échecs pré-existants sont
  orthogonaux et antérieurs à ce transfert).
- Smoke d'intégration cohérent avec les attendus du brief.

Action de suivi suggérée (post-merge, hors brief) :
- Mesurer `cr` sur un batch de 20-30 leafs filtrés vs non-filtrés (seed offset
  +900 selon brief) **dès que le volume corpus le permettra** — pour confirmer
  empiriquement le gain prophylactique.
- Étendre `_COLOR_ANCHOR_REPLACEMENTS` si de nouveaux triggers conceptuels
  émergent en annotation (`fall season`, `winter wonderland`, etc.).
