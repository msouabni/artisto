# Transfert skill — T2 + T3 + T23 (Grille imagier + dispatch solo visage)
Date : 2026-05-10

## Contexte

Transfert des règles T2 (contenu explicite par cellule), T3 (cellules composées) et T23 (heuristique dispatch solo visage expressif) du skill `prompt-taxonomy-ecosystem` (références : `references/techniques.md` §T2, §T3, §T23) vers `src/services/prompt_generator.py`. Brief source : `docs/architect/briefs/2026-05-10_brief-transfert-T2T3T23-grille-imagier.md`. Cible : les 4 workflow_classes grille (~60 défauts `image_pas_coherente` + `image_incomprehensible` baselines 50-100 % selon §3 #1 du rapport `2026-05-10_analyse-annotations-transferts-skill.md`). Garde-fou pivot ERNIE en place : si fix résiduel > 30 % → bascule T19+ #1 canal manuel (PIL/SVG).

## Modifications

| Fichier | Type | LOC | Résumé |
|---|---|---|---|
| `data/prompt_generator/grid_cell_contents.json` | NEW | 262 | 14 leafs grille couverts (>= 6 requis) répartis sur les 4 workflow_classes ciblées (Grille imagier annoté 6/8 ; Imagier différencié OU Solo 2/7 ; Imagier différencié 3×3 5/8 ; emotion → routée T23). Schéma : `{leaf_id: {title, cells:[{item, shape}\|{composed,container,items}]}}`. Avec `_doc` et `_note` documentant les choix de FILT. |
| `src/services/prompt_generator.py` | MODIFY | +330/-15 | + bloc T2/T3 (`_load_grid_cell_contents`, `set_grid_cell_contents`, `_format_grid_cell`, `_build_grid_cells_clause`) ; + bloc T23 (`_EXPRESSIVE_FACES`, `_T23_COLLECTIVE_MARKERS`, `_T23_ELIGIBLE_CLASSES`, `_detect_emotion`, `_is_t23_singular_face`, `template_solo_expressive_face`) ; rewrite `template_grid_3x3_imagier` + `template_grid_3x3_annotated` (T2/T3 si JSON présent, fallback warning sinon) ; hook T23 dans `build_prompt` après lookup TEMPLATE_DISPATCHER, avant LEAF_OVERRIDES (priorité préservée). Citations textuelles du skill en commentaire. |
| `tests/test_prompt_generator.py` | MODIFY | +261 | +17 nouveaux tests : couverture JSON, validation schéma, injection cellules dans positive (T2 + T3 composé), fallback warning via `caplog`, table émotions complète, détection préfixe (`_detect_emotion`), dispatch éligibilité (`_is_t23_singular_face`), bypass collective marker, smoke build_prompt complet T23 vs grid, non-régression Solo animal + before/after. |

**Disjonction zones P1** : aucune ligne touchée dans Solo animal/fish (T9), template_before_after (T25), prompt_filters (FILT), hook FILT — verifié par diff.

**Convention HTML editor** : asset traité comme cœur stable lecture-seule (cf. brief §Périmètre) — pas d'éditeur HTML créé. À reconsidérer si l'asset doit être édité fréquemment par d'autres rôles.

## Tests

| Suite | Résultat |
|---|---|
| `pytest tests/test_prompt_generator.py` | **39/39 verts** (22 baseline T9+T25 conservés + 17 nouveaux T2/T3/T23) |
| `pytest tests/test_prompt_filters.py` | **40/40 verts** (sanity FILT, non-régression) |
| `pytest --ignore=tests/test_content_generator.py` (suite complète) | 267/272 verts. 5 échecs préexistants concernent `tests/test_workflow_template_sidecar.py` + `tests/test_bulk_generation_jobs.py` + `tests/test_create_image_job_workflow.py` (ERNIE workflow sidecar `negative_prompt`/`unsupported`/`optional`) — **aucun lien avec prompt_generator**. Le fichier `tests/test_content_generator.py` ne collecte pas (ImportError pré-existant `HARAKAT_RE`). |

Sanity manuel sur les 10 leafs émotionnels du corpus : 9/10 routés correctement vers le template solo expressive face (`happy_child_smiling`, `sad_child_crying`, `angry_child_face`, `scared_child_face`, `surprised_child_face`, `calm_child_breathing`, `shy_child_face`, `proud_child_face`, `curious_child_face`) ; `emotion_chart_poster` reste sur la grille (marqueur collectif `chart` détecté). Sanity 8 leafs grille couverts : injection des cellules nommées correctement constatée dans le positive ; 1 leaf non couvert (`candy_shop_display`) tombe sur le fallback générique avec warning loggé via le logger nommé `services.prompt_generator`.

**Découverte FILT × T2** : le hook `apply_prompt_filters` post-template a une interaction non-triviale avec le contenu des cellules. Il strippe :
- les couleurs (`orange` même comme nom de fruit, `red`, `bright`…),
- les ancres 3D/matière (`glass` comme dans `milk glass`, `drinking glass`),
- les luminosités (`bright`, `dark`).

J'ai adapté en amont les items pour éviter ces collisions (`round orange with leaf` → `round citrus fruit with leaf` ; `tall glass of milk` → `tall cup of milk with handle` ; `eyes bright` → `wide open eyes` dans la table émotions). Notes inline dans le JSON sous `_note`. **C'est un point archi à arbitrer** : faut-il une whitelist contextuelle dans FILT pour les noms de fruits / contenants comestibles, ou continue-t-on à neutraliser systématiquement à la source côté JSON ?

## Mesure post-transfert (gate ERNIE)

**Procédure attendue** :
1. Rerun ComfyUI sur 8-10 leafs sélectionnés des 4 classes ciblées avec seed offset +300 :
   - Grille imagier annoté : `fruit_imagier_with_names`, `vegetable_imagier_with_names`, `weather_imagier_with_names`
   - Imagier différencié OU Solo : `balanced_lunch_plate`, `healthy_breakfast_plate`
   - Imagier annoté 3×3 OU Solo visage : `proud_child_face`, `sad_child_crying` (T23 → solo expressive face)
   - Imagier différencié 3×3 : `fruits_basket`, `vegetables_basket`, `bread_and_pastries`
2. Annoter manuellement avec grille v2 — au minimum les tags `image_pas_coherente` + `image_incomprehensible`.
3. Comparer baseline pré-transfert (Grille imagier annoté 8/8 = 100 % ; Imagier différencié OU Solo 7/7 = 100 % ; Imagier annoté 3×3 OU Solo visage 9/10 = 90 % ; Imagier différencié 3×3 4/8 = 50 %) vs post-transfert.

**Critère Go/No-Go** :
- Taux post-transfert ≤ 30 % → **Go** : transfert validé, le brief T2/T3/T23 est conclu et l'on peut empiler les autres briefs (T15-T21 supports de comptage).
- Taux post-transfert > 30 % → **No-Go** : reporter en T19+ #1 canal manuel, bascule pipeline grille en composition PIL/SVG (décision archi).

**État actuel de la mesure** : *en attente de mesure humaine*. ComfyUI non lancé dans cette session (rôle dev-claude-code, pas d'accès au runtime image). L'archi prendra en charge la mesure asynchrone et reportera le verdict définitif dans un complément à ce rapport (ou un nouveau rapport `2026-05-10_mesure-T2T3T23.md`).

## Décision / Action suivante

**Verdict gate** : **EN ATTENTE DE MESURE HUMAINE**. L'implémentation est terminée et testée unitairement (39/39), conforme au brief (T2 + T3 + T23, citations skill, fallback warning, JSON ≥ 6 leafs, non-régression P1). Le verdict Go/No-Go ERNIE dépend uniquement de la mesure ComfyUI à 8-10 leafs. Aucun fix résiduel n'est mesurable côté pipeline texte sans rendu visuel.

**Action archi suivante** :
1. Lancer le rerun ComfyUI sur les 8-10 leafs listés ci-dessus.
2. Annoter via `data/benchmark-annotator.html` ou équivalent.
3. Comparer baseline vs post-transfert et trancher Go/No-Go.
4. Si Go → procéder aux briefs T15-T21 (supports de comptage) et étendre `grid_cell_contents.json` aux leafs grille restants (~15-20 leafs non couverts dans cette PR).
5. Si No-Go → ouvrir un brief PIL/SVG composeur (T19+ #1 canal manuel) et garder T2/T3/T23 comme fallback dégradé pour le sous-ensemble qui passerait le gate à 30 %.

**Points d'attention archi non-triviaux** :
- **Interaction FILT × items grille** : `orange`, `glass`, `bright`, `red`, `dark` strippés systématiquement. La JSON est désormais blindée pour les 14 leafs couverts mais toute extension future doit être audited contre `_COLOR_NOUNS` + `_GLOSSY_TERMS` de `prompt_filters.py`. Considérer une whitelist contextuelle ou un raise warning sur collision en mode dev.
- **Périmètre `_T23_ELIGIBLE_CLASSES`** : actuellement limité à `Imagier annoté 3×3 OU Solo visage`. La variante `Imagier différencié 3×3 OU Solo visage` est listée hypothétiquement mais aucune workflow_class de la cartographie ne porte ce label. Si un nouveau leaf émotionnel apparaît sur une autre classe, il faudra l'ajouter ici.
- **`_T23_COLLECTIVE_MARKERS`** : 7 marqueurs (`imagier`, `grid`, `chart`, `panel`, `overview`, `collection`, `poster`). Filtre correctement `emotion_chart_poster` et `feeling_imagier_with_names`. Si un futur leaf émotionnel collectif sans aucun de ces mots-clés apparaît, T23 le bypasserait abusivement vers solo face — extension vocabulaire à faire le moment venu.
- **Templates grille frieze 1×N préservés** : `template_frieze_1xN` et `template_before_after` restent en mode T25 BEFORE/AFTER (zones T25 territory, hors scope). Pas de conflit avec le nouveau template_grid_3x3.
