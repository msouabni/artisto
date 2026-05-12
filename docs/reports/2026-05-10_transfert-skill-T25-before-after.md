# Transfert — Skill T25 (Comparatif before/after, états explicites)
Date : 2026-05-10
Type : Transfert skill → PromptGenerator (brief #2 du rapport `2026-05-10_analyse-annotations-transferts-skill.md`)
Brief source : `docs/architect/briefs/2026-05-10_brief-transfert-T25-before-after.md`

## Contexte

L'analyse des annotations `poc-scale-benchmark` (515 entrées scorées) a identifié ~28 défauts `image_pas_coherente` + `image_incomprehensible` concentrés à 89 % sur 2 workflow_classes Comparatif :

- `Comparatif before/after OU Solo` : 8/10 (80 %, score moyen 1.00, 10 % publishable)
- `Solo objet ou comparatif` : 6/8 (75 %, score moyen 1.00, 0 % publishable)

Diagnostic : `template_before_after` (`src/services/prompt_generator.py`) générait `the right cell shows the same scene with one single change applied` — antipattern explicitement listé en T25 (skill `prompt-taxonomy-ecosystem`, `references/techniques.md` ~l. 794) :

> Une différence explicite doit être concrète, visuelle et localisée.
> `tap closed -> tap open + bucket` fonctionne.
> `one single change applied` est trop vague — modèle reproduit la même scène.

Bug v5 (techniques.md ~l. 1004) précise le fix attendu : champs `before_state` / `after_state` explicites dans la cartographie ou en JSON dédié.

**Garde-fou pivot ERNIE** (acté côté brief) : si la mesure post-transfert montre un taux résiduel `image_pas_coherente` > 30 %, le complément est reporté en T19+ canal manuel (bascule pipeline composition PIL 2-tiles hors ERNIE).

## Modifications

| Fichier | LOC ajoutées | LOC modifiées | Nature |
|---|---:|---:|---|
| `data/prompt_generator/before_after_states.json` | 79 (nouveau) | 0 | Banque de connaissances {leaf_id → before/after_state} pour 18 leafs |
| `src/services/prompt_generator.py` | ~85 | ~12 | Loader `_load_before_after_states` + `_BEFORE_AFTER_STATES` singleton + `set_before_after_states` (test util) ; refonte `template_before_after` (mode T25 explicite + fallback warning) ; logger module-level |
| `tests/test_prompt_generator.py` | ~110 | 4 | 8 nouveaux tests T25 (couverture, format, injection, fallback warning, alias `leaf_id`, NULL-safe strategy, non-régression) |
| **Total** | **~274** | **~16** | — |

### Diff résumé `src/services/prompt_generator.py`

1. Ajout `import logging` + `logger = logging.getLogger(__name__)` (module-level).
2. Ajout `DEFAULT_BEFORE_AFTER_STATES` constante de chemin.
3. Ajout bloc T25 avec citation textuelle skill (Insight C + Bug v5) en commentaire.
4. Ajout `_load_before_after_states(path)` (chargement JSON tolérant aux erreurs, validation des champs).
5. Ajout singleton `_BEFORE_AFTER_STATES` chargé à l'import.
6. Ajout `set_before_after_states(states)` (utilitaire test pour injecter / purger le mapping).
7. Refonte `template_before_after` :
   - Si `_BEFORE_AFTER_STATES[leaf_id]` présent → injection des deux états explicites dans les cellules (T25 mode 1).
   - Sinon → fallback comportement antérieur + `logger.warning("before_after_states missing for leaf_id=%s …")` avec instruction d'ajout.
   - Accepte aussi bien `leaf['id']` que `leaf['leaf_id']`.
   - NULL-safe sur `strategy=None`.

### `before_after_states.json`

18 leafs couverts, extraits des `index-comparatif_before_after_ou_solo.json` et `index-solo_objet_ou_comparatif.json` :

- **Comparatif before/after OU Solo** (10) : `rainwater_collection_barrel`, `kid_recycling_bin_sorting`, `beach_cleanup_volunteers`, `compost_bin_in_garden`, `earth_with_protective_hands`, `solar_panels_on_roof`, `polar_bear_on_melting_ice`, `wind_turbines_on_hill`, `kid_planting_a_tree`, `deforestation_before_after`.
- **Solo objet ou comparatif** (8) : `vegetable_garden_at_home`, `electric_car_charging`, `reusable_shopping_tote_bag`, `eco_friendly_house_with_panels`, `zero_waste_kitchen`, `bike_to_work_commute`, `kids_picking_up_litter`, `reusable_water_bottle`.

Chaque entrée respecte le critère T25 « concret, visuel, localisé » (action ou objet précis identifiable cellule à cellule).

### Editor HTML

**Non créé** dans cette PR. Justification : le JSON est traité comme cœur stable lecture-seule pour l'instant (option mentionnée explicitement dans le brief). À ouvrir si extension à l'ensemble des leafs Comparatif est demandée — laisser un follow-up éditeur après validation Go.

## Tests

Suite `tests/test_prompt_generator.py` — **22/22 passants** (14 existants T9/baseline + 8 nouveaux T25).

Nouveaux tests T25 :

| Test | Vérifie |
|---|---|
| `test_t25_states_cover_min_six_leafs` | Couverture minimale ≥ 6 leafs (brief). Actuel : 18. |
| `test_t25_states_have_required_fields` | Chaque entrée a `before_state` + `after_state` non vides. |
| `test_t25_covers_documented_comparatif_leafs` | Les 18 leafs annotés des 2 classes Comparatif sont tous présents. |
| `test_template_before_after_injects_states_when_present` | Quand le mapping couvre le leaf, les deux états sont dans le positive ET l'antipattern `one single change applied` / `in its initial state` disparaît. |
| `test_template_before_after_fallback_logs_warning_when_missing` | Quand le leaf est hors mapping, fallback générique préservé + warning loggé via `caplog` (capturable). |
| `test_template_before_after_handles_leaf_id_alias` | Accepte `leaf_id` ou `id` comme clé d'identification. |
| `test_template_before_after_strategy_none_safe` | `strategy=None` ne casse pas le fallback (NULL-safe). |
| `test_t25_does_not_alter_solo_animal_template` | Non-régression : les autres templates (Solo animal) ne contiennent ni « BEFORE » ni « AFTER ». |

Suite plus large `tests/test_prompt_generator.py` + `test_prompt_pipeline_v1.py` : **35/35 passants**.

5 échecs pytest hors scope identifiés dans la suite globale (`test_bulk_generation_jobs.py`, `test_create_image_job_workflow.py`, `test_workflow_template_sidecar.py`) — liés au handling `negative_prompt` ERNIE `optional` vs `unsupported`. Pas de causalité avec ce transfert. 1 ImportError dans `test_content_generator.py` (`HARAKAT_RE`) — module ollama_json modifié par un autre travail en parallèle.

## Mesure post-transfert

**Non exécutée dans cette session** — la mesure ComfyUI requiert un environnement opérationnel (worker image démarré, modèle chargé, ~15-25 min de run + annotation humaine). Documentée ci-dessous comme protocole en attente d'exécution opérateur.

### Protocole proposé (cf. brief §critères d'acceptation)

1. **Échantillon** : les 18 leafs couverts dans `before_after_states.json` (cible minimale brief : 6-8 ; on tient les 18 d'un coup pour gagner en signal).
2. **Génération** : 1 image par leaf, seed offset `+400` (dans `config.seed`), workflow `ernie-image-turbo-q8-api`, sampler `euler`, steps 8, cfg 1.0, résolution déterminée par strategy (1376×768 pour les paysages/scènes, 1024×1024 par défaut).
3. **Annotation** : grille v2, focus sur tags `image_pas_coherente` + `image_incomprehensible` (les deux dominent la baseline 89 %).
4. **Comparaison** :
   - Baseline (annotations existantes poc-scale-benchmark) : 14/18 sur les 2 classes (`image_pas_coherente`+`image_incomprehensible`) ≈ **78 %** sur ces leafs spécifiques. Brief cite 89 % (28/(8+10+6+8) sur les 2 classes complètes — leger glissement statistique selon le découpage).
   - Cible Go : ≤ 30 % post-transfert.
   - Cible No-Go (pivot ERNIE) : > 30 % → bascule T19+ #2 canal manuel (composition PIL 2-tiles).
5. **Restitution** : annotations consignées dans `docs/reports/poc-scale-benchmark/` ou un nouveau dossier `2026-05-10_rerun-T25/`. Compléter ce rapport (section dédiée) ou créer `2026-05-10_mesure-T25-rerun.md`.

### Verdict en attente de mesure humaine

Tant que la mesure n'a pas été exécutée :

- **Critère de succès code** atteint : couverture ≥ 6 leafs (18 réalisés), template lit le JSON, fallback + warning fonctionnels, citation T25 présente, tests verts.
- **Critère de succès produit** : à confirmer après le rerun ComfyUI.

## Décision Go/No-Go

**Verdict provisoire : Go conditionnel — pré-validé code, en attente confirmation produit.**

- **Go (côté code)** : transfert techniquement complet, conforme au brief, tests verts. Le pipeline génère désormais des prompts T25-compliants pour 18 leafs et bascule explicitement les leafs non couverts vers le fallback historique avec traçabilité (warning).
- **Décision finale Go/No-Go** : doit être prise par l'archi après mesure post-transfert (rerun ComfyUI sur les 18 leafs + annotation manuelle). Si le taux résiduel `image_pas_coherente`+`image_incomprehensible` ≤ 30 % → Go définitif et extension à d'autres leafs Comparatif éventuellement. Si > 30 % → No-Go T25 stand-alone, déclencher T19+ #2 (bascule PIL 2-tiles documentée dans l'analyse).

## Coordination avec agents parallèles

Au moment de l'implémentation, deux autres modifications étaient en cours sur le même fichier :

1. **Agent T9** (Solo animal — orientation directionnelle) : a ajouté `_DIRECTIONAL_OVERRIDES`, `_RISKY_BACKWARD_ELEMENTS`, `_apply_directional_override`, et utilisé ces hooks dans `template_solo_animal` / `template_solo_fish`. **Zone disjointe** de la mienne (template_before_after vs Solo animal/fish). Les imports communs (`Dict`, `Optional`) étaient déjà présents.
2. **Agent T5+T6+T7** (`src/services/prompt_filters.py`) : a créé un module de filtrage post-template (strip noms couleur, ancres conceptuelles, surfaces 3D) et l'a câblé dans `build_prompt` après l'appel template (`apply_all_filters` sur le tail post STYLE_BLOCK). **Effet observé sur mes states** : 2 entrées sur 18 voient un mot strippé en sortie (`green hill` → `hill`, `dark smoke` → `smoke`, `glass jars` → `jars`). Sémantiquement OK — la lisibilité « before/after » est préservée. **Aucune action requise** côté T25.

**Aucune zone partagée modifiée** dans cette PR : pas de touche à `NEGATIVE_V3`, `_ISOLATION`, `LEAF_OVERRIDES`, `_RISKY_MULTI_PATTERNS`, `STYLE_BLOCK`, `WORKFLOW_TEMPLATE`, `TEMPLATE_DISPATCHER`, `PromptGenerator.build_prompt` (sauf via le hook `template_before_after` qu'il appelle).

## Points d'attention

- **Filtrage post-template T5/T6/T7** : actif sur les states injectés. Si l'archi veut shielder les states de ce filtrage (au cas où une couleur serait sémantiquement importante dans une comparaison « avant/après »), il faudrait soit bypasser le filtre quand `_BEFORE_AFTER_STATES[leaf_id]` est utilisé, soit pré-filtrer le JSON. Pour l'instant : status quo, le filtrage est conservateur.
- **Couverture exhaustive Comparatif non visée** : 18 leafs annotés couverts. Les autres feuilles routées via `template_before_after` (au-delà des 2 sous-catégories testées) basculeront sur le fallback + warning. Ouvrir un follow-up si extension demandée.
- **Aucun editor HTML** créé pour `before_after_states.json` : à ouvrir si l'archi décide qu'on en fait un asset éditable. Convention projet honorée par défaut explicite (« asset cœur stable lecture-seule »).
- **`scripts/generate_taxonomy_prompts.py`** non revu — si un script génère des prompts en batch, vérifier qu'il s'appuie sur `PromptGenerator.build_prompt` (pas un appel direct à `template_before_after`). Quick check via grep `template_before_after` montre qu'il n'est appelé que via le dispatcher → OK.

## Décision / Action suivante

1. **Archi** : déclencher le rerun ComfyUI sur les 18 leafs (seed offset +400) et l'annotation humaine.
2. **Archi** : trancher Go/No-Go définitif après mesure (cible ≤ 30 % image_pas_coherente).
3. **Si Go** : ouvrir un follow-up pour étendre `before_after_states.json` aux autres leafs Comparatif découverts en production + créer l'editor HTML associé si volume justifie.
4. **Si No-Go** : déclencher T19+ #2 — bascule pipeline Comparatif en composition PIL 2-tiles (script Pillow indépendant ERNIE pour ces 2 sous-catégories).
