# Architect Memory — Artiste Coloriage

Mis à jour : 2026-05-24 (Cycle archi multi-sites + déblocage MEP v0 → prod alwanbooks.com — modèle A ADD-ONLY acté, themes industrialisés, brief Niveau 1 prêt à exécution. Rattrape 14 jours d'historique 2026-05-12 → 2026-05-24.)

## État courant du projet

Pipeline opérationnelle de bout en bout. MEP-v0/C1/C2/C3/D livrés 2026-05-12 (migration annotations DB, slug_utils FR/EN/AR, export_mep_v0 produisant 405 MDs, alwanbooks_pipeline R2 + rimalab-v2). Registry partagé categories cross-repo + flag `--sync-categories` mergés 2026-05-15 (commits `999baa4` → `72b1e94`). 411 posts × 3 locales pushés côté rimalab-v2 sur branche `content/export-mep-v0` (commit `6889870`), build Astro vert 857 pages, 0 erreur Zod. R2 à 6/137 masters live, 131 à uploader (creds en `.env`). Cycle archi 2026-05-23/24 : modèle A ADD-ONLY acté pour posts + themes, multi-sites Niveau 1 prêt à exécution (brief livré), themes industrialisés (seed 5 themes 32 leaves). **Centre de gravité : exécuter brief Niveau 1 + upload R2 + cutover J+30 (date à fixer)**.

## Cycle en cours

- **Intitulé** : Workflow git-as-CMS multi-sites + déblocage MEP v0 vers prod alwanbooks.com
- **Démarré** : 2026-05-23
- **Critères de sortie** :
  - ✅ Réponse rimalab globale obtenue 2026-05-23 (build vert, R2 6/137, bug B = non-bug, divergence main vs branche 6 categories)
  - ✅ Modèle workflow acté : Modèle A (ADD-ONLY + blocklist + regen explicite) pour posts ET themes ; sync strict (registry-driven) pour categories
  - ✅ Convention push C1 actée (pipeline push auto sur branche `bot/lot-{YYYY-MM-DD}[-N]`, identité bot `artiste-pipeline <bot@artiste-coloriage.local>`, SSH key système)
  - ✅ Architecture multi-sites Niveau 1 cadrée (refactor `destination_sites.json` + 1 entrée alwanbooks + clones `data/sites/<id>/` gitignored)
  - ✅ Themes industrialisés : `data/themes_registry.json` seed livré 2026-05-24 (5 themes, 32 leaves : arabic-alphabet récupéré + noel + ramadan + saison-hiver + saison-ete)
  - ✅ Lot A (5 décisions débloquant rimalab) acté : merge no-ff registry wins · upload R2 brief · statut piloté pipeline cutover J+30 · letters_arabic + règle Astro masquage si 0 post · placeholder récupéré
  - ✅ Lot B (4 paramètres techniques) acté : clones `data/sites/`, SSH key système, branche `bot/lot-{date}[-N]`, identité bot dédiée
  - ✅ 7 livrables architecte produits : notif rimalab, brief upload R2, doc workflow référence, seed themes_registry, brief Niveau 1, roadmap Niveau 2, /architect-save final
  - ⏳ Exécution brief upload R2 (claude artiste, ~15 min)
  - ⏳ Exécution brief Niveau 1 multi-sites (claude artiste, ~3-4h dev)
  - ⏳ Merge `content/export-mep-v0` → `main` côté rimalab + implémentation règle Astro "masquage catégorie si 0 post"
  - ⏳ Cutover J+30 (date à fixer ~2026-06-24)
- **Bloqueurs** :
  - Aucun bloqueur architectural (toutes décisions actées)
  - Bloqueurs opérationnels : exécution des 2 briefs côté claude artiste + actions côté claude rimalab

## Échéances / Deadlines

| Date cible | Quoi | Statut | Contexte |
|---|---|---|---|
| _2026-05-09 → 2026-05-10 (multiples)_ | _Briefs annotateur v2, greffon prod, vocab source unique, transferts skill P3 (8/8), pivot T25, copie prompt Tailscale, audit cartographie, Vague 1 MEP v0 (subject + qc + worker simplifié)_ | _fait_ | _Voir rapports `docs/reports/2026-05-09_*` et `2026-05-10_*` (16+ rapports). Consolidé pour lisibilité._ |
| 2026-05-12 | MEP-v0/C1 migration annotations fichier → DB polymorphe | fait | `2026-05-12_migration-annotations-fichier-vers-db.md`. 1014 annotations migrées. |
| 2026-05-12 | MEP-v0/C2 slug_utils FR/EN/AR (`r2_slug` + `post_slug`) | fait | `2026-05-12_phase-mep-v0-C2-slug-utils.md`. 52 tests verts. Corpus AR 31 entrées + table char-par-char. |
| 2026-05-12 | MEP-v0/C3 export_mep_v0 (manifest + 405 posts) | fait | `2026-05-12_phase-mep-v0-C-export-data.md`. 135 leaves × 3 locales. |
| 2026-05-12 | MEP-v0/D pipeline alwanbooks (R2 + rimalab-v2) | fait | `2026-05-12_phase-mep-v0-D-alwanbooks-pipeline.md`. Mock 540 variants + 405 MDs. |
| 2026-05-12 | Audit conformité contrat rimalab-v2 (99.75% → 100% post-patches) | fait | `2026-05-12_audit-contrat-rimalab-v2.md` + `..._v2.md`. 6 arbitrages rimalab reçus + patches mapper categoryId + dateModification. |
| 2026-05-12 | Smoke test prod rimalab-v2 (R2 firefighter 200 OK) | fait | `2026-05-12_smoke-test-prod-rimalab-v2.md`. 6/137 masters live, 131 à uploader. |
| 2026-05-14 | Création 7 catégories côté rimalab-v2 (commit `6889870`) | fait | `2026-05-14_phase-creation-categories-rimalab-v2.md`. Branche `content/export-mep-v0`. |
| 2026-05-15 | Registry partagé categories cross-repo + flag --sync-categories + mapper fail-fast | fait | `2026-05-15_phase-categories-registry-cross-repo.md`. 18 tests dédiés, 631 tests total. Commits `999baa4` + `b1df47f` + `72b1e94`. |
| 2026-05-23 | Réponse rimalab globale (build vert, R2 état, bug B, divergence main vs branche) | fait | Conversation 2026-05-23 (synthétisée dans cycle en cours) |
| 2026-05-24 | 7 livrables architecte cycle multi-sites + Lot A/B actés | fait | Cf. cycle en cours + sections Décisions actées 2026-05-24 |
| 2026-05-25 | Notif rimalab envoyée + brief upload R2 lancé | à faire | Notif : `docs/architect/notes/2026-05-24_notif-rimalab-decisions-lot-a.md`. Brief upload : `docs/architect/briefs/2026-05-24_brief-upload-r2-masters-restants.md` |
| 2026-05-27 | Brief Niveau 1 multi-sites exécuté (claude artiste, ~3-4h dev) | à faire | `docs/architect/briefs/2026-05-24_brief-niveau-1-multi-sites-add-only.md`. Prérequis : clone manuel rimalab dans `data/sites/alwanbooks/`. |
| 2026-05-27 | Merge `content/export-mep-v0` → `main` côté rimalab-v2 (no-ff -X theirs) + règle Astro "masquage si 0 post" | à faire | Action attendue de claude rimalab après réception notif. |
| 2026-06-24 (proposé) | Cutover J+30 alwanbooks.com : flip PUBLIC_SITE_STATE → production + script bump approved→published | à faire — date à confirmer | Coordination archi (script) + claude rimalab (flip env var). Verbe `pipeline cutover --site alwanbooks` à livrer dans brief Niveau 1. |

## Décisions architecturales actées

| Date | Décision | Statut | Rapport |
|---|---|---|---|
| 2026-05-05 | Routing LLM : `qwen3.5:4b` primaire texte, `qwen3.5:9b` primaire vision, `gemma4:26b` arbitre couleur, batching vision banni | Actée | `2026-05-05_decision-llm-finale.md` |
| 2026-05-05 | Mécanique `/no_think` qwen3 strict vs paramètre natif `"think": false` qwen3.5+ | Actée | Idem |
| 2026-05-05 | Bornes Zod HARD uniformes / SOFT caps pipeline différenciés par locale (AR plus stricte). Pipeline rejette sur SOFT, jamais sur HARD | Actée | Confirmation Alwan Books 2026-05-05 |
| 2026-05-06 | Paramètres image figés : `sampler=euler`, `steps=8`, `cfg=1.0`, `scheduler=normal`. Résolutions adaptatives par `workflow_class` | Actée | `2026-05-06_poc-seed-variance.md` + CLAUDE.md |
| 2026-05-09 → 10 | _Consolidation_ : `PromptGenerator` intégré service · audit cartographie 4 templates morphologiques · fix `2_objets` (NEGATIVE_V3 + `_ISOLATION` + `LEAF_OVERRIDES`) · multi-index annotateur · bind Tailscale · QC anatomie LLM invalidé · annotateur v2 + greffon prod + vocabulaires source unique · 8 transferts skill P3 → PromptGenerator · pivot T25 frieze (livré puis No-Go → réconciliation Option B wrapper) · gate ERNIE post-transfert (T2T3T23 ✅ Go, T25 explicite ✅ Go, Pivot T25 ❌ No-Go) · décision H3 45 sub-cats non-Haute (17 inclure / 13 POC / 15 exclure) · Plan MEP v0 par composant · décision archi worker image = pattern POC direct ComfyClient ERNIE-only · Spec MEP v0 modèle subject + flow pipeline · Vague 1 MEP v0 clôturée (4/4 mergés, migrations 0007+0008+0009, 1376 subjects, smoke E2E QC OK) | Actée — consolidée | Voir rapports `2026-05-09_*` et `2026-05-10_*` (16+ rapports) + MEMORY pré-2026-05-23 si besoin |
| 2026-05-12 | **MEP-v0/C1** migration annotations fichier → table DB polymorphe `annotation` (`target_type`, `target_id`, sans FK, whitelist API) | Actée — livrée | `2026-05-12_migration-annotations-fichier-vers-db.md` |
| 2026-05-12 | **MEP-v0/C2** slug_utils FR/EN/AR : `r2_slug` + `post_slug` par locale, corpus AR 31 entrées + table char-par-char + strip harakat. Convention métier : `name_*` ne doit contenir aucun chiffre (regex `r2_slug` lève ValueError) | Actée — livrée | `2026-05-12_phase-mep-v0-C2-slug-utils.md` |
| 2026-05-12 | **MEP-v0/C3** export_mep_v0 produisant `data/export/manifest.json` + `posts/{ar,fr,en}/*.json` (135 leaves × 3 locales = 405 fichiers). Filtrage `publishable=true` côté DB + gate HARD caps Zod | Actée — livrée | `2026-05-12_phase-mep-v0-C-export-data.md` |
| 2026-05-12 | **MEP-v0/D** pipeline alwanbooks (R2 + rimalab-v2) : 4 variants par master (PNG/WebP/Thumb/PDF), atomicité 4-ou-0, idempotence ETag, écriture MDs côté rimalab, push git optionnel | Actée — livrée | `2026-05-12_phase-mep-v0-D-alwanbooks-pipeline.md` |
| 2026-05-12 | **Audit contrat rimalab-v2 → 100% conforme** (post-patches) : 6 arbitrages reçus, patches mapper categoryId (8 règles ordonnées) + `dateModification` injecté + filtre keywords <2 chars. 608 tests verts | Actée | `2026-05-12_audit-contrat-rimalab-v2-v2.md` + `2026-05-12_phase-patch-mapper-firefighter.md` |
| 2026-05-12 | **Smoke prod rimalab-v2** : `firefighter-superhero.png` 200 OK sur `assets.alwanbooks.com`, custom domain validé. 131/137 masters restants à uploader | Actée — état mesuré | `2026-05-12_smoke-test-prod-rimalab-v2.md` |
| 2026-05-14 | **7 catégories créées côté rimalab-v2** (commit `6889870` branche `content/export-mep-v0`) : animals_birds/marine/pets/wild + general_humans + objects_things + letters_arabic | Actée — livrée | `2026-05-14_phase-creation-categories-rimalab-v2.md` |
| 2026-05-15 | **Registry partagé categories cross-repo** : `data/categories_registry.json` source unique de vérité (10 catégories), mapper `map_leaf_to_category()` refactoré fail-fast (`assert result in KNOWN_CATEGORY_IDS`), flag `--sync-categories` idempotent byte-identique (LF universel, UTF-8 sans BOM), 18 tests dédiés (10 registry + 8 sync). Mergé via PR commits `999baa4` → `b1df47f` → `72b1e94` | Actée — livrée + mergée | `2026-05-15_phase-categories-registry-cross-repo.md` |
| 2026-05-24 | **Modèle A — ADD-ONLY + blocklist + regen explicite** pour posts ET themes côté pipeline. La pipeline ne touche jamais un MD existant côté site destinataire. Verbe `--regen <slug>` pour overwrite ciblé explicite. Blocklist `data/pipeline_blocklist.json` (posts) + `data/pipeline_themes_blocklist.json` (themes). Categories restent en sync strict registry-driven (régime distinct par type) | Actée — brief Niveau 1 rédigé | `docs/architect/2026-05-24_workflow-pipeline-multi-sites.md` (référence d'archi) |
| 2026-05-24 | **C1 — Push automatique pipeline** sur branche `bot/lot-{YYYY-MM-DD}[-N]` avec suffixe -N si collision même jour. Identité bot `artiste-pipeline <bot@artiste-coloriage.local>` (séparation humain/bot dans git log). SSH key système (déjà configurée). Jamais de push direct sur main du site destinataire | Actée — brief Niveau 1 | Idem |
| 2026-05-24 | **Architecture multi-sites Niveau 1** : `data/destination_sites.json` registry (1 entrée alwanbooks au démarrage, schéma extensible), clones dans `data/sites/<id>/` gitignored, lecture path via `clone_path` du registry (plus de hardcode rimalab). Niveau 2 (commandes CLI `sites add/list/remove/etc.`) préparé en roadmap, à déclencher quand 2e site arrive | Actée — Niveau 1 brief rédigé, Niveau 2 roadmap | `docs/architect/2026-05-24_roadmap-multi-sites-niveau-2.md` |
| 2026-05-24 | **Themes industrialisés Modèle A** : `data/themes_registry.json` source unique (schéma parallèle categories + champs `editorial_body_i18n` multi-paragraphes et `leaves` mapping leaf→theme). Verbes `--sync-themes` (ADD-ONLY) + `--regen-theme <id>` (overwrite ciblé). Auto-tag `themeIds` à la création des posts. Seed 5 themes 32 leaves : arabic-alphabet récupéré + noel + ramadan + saison-hiver + saison-ete | Actée — seed livré, brief Niveau 1 | `data/themes_registry.json` + brief Niveau 1 |
| 2026-05-24 | **Lot A.1 — Merge `content/export-mep-v0` → `main` côté rimalab-v2** : `git merge --no-ff -X theirs content/export-mep-v0`. Registry wins sur les 6 categories manuelles de `5975195`. Trace claire des 2 lignées dans git log | Actée — exécution rimalab attendue | `docs/architect/notes/2026-05-24_notif-rimalab-decisions-lot-a.md` |
| 2026-05-24 | **Lot A.2 — Upload 131 masters R2 manquants** pris en charge côté artiste-coloriage (creds R2 déjà en `.env`). Brief court exécution `pipeline --upload-only` | Actée — brief livré | `docs/architect/briefs/2026-05-24_brief-upload-r2-masters-restants.md` |
| 2026-05-24 | **Lot A.3 — Statut posts piloté par pipeline (frontmatter `status`)** : posts restent `approved` jusqu'au cutover, verbe `pipeline cutover --site alwanbooks` réécrit massivement en `published` à J+30. Astro garde son filtre actuel (`PUBLIC_SITE_STATE=production` → published only) | Actée — verbe à livrer brief Niveau 1 | Brief Niveau 1 §9 |
| 2026-05-24 | **Lot A.4 — letters_arabic gardée + règle Astro générique** "masquage catégorie si 0 post en `PUBLIC_SITE_STATE=production`". Réutilisable pour toute catégorie orpheline future, pas spécifique à letters_arabic | Actée — implémentation Astro attendue rimalab | Notif rimalab §A.4 |
| 2026-05-24 | **Lot A.5 — Themes industrialisés + placeholder récupéré** : le placeholder existant côté rimalab s'appelle `arabic-alphabet.md` (PAS `seasonal_summer.md` comme indiqué par claude rimalab), récupéré byte-byte + intégré au seed registry comme première entrée (leaves: [] tant que batch alphabet AR pas livré). Cohérent avec letters_arabic category orpheline | Actée — seed livré | Cf. décision Themes 2026-05-24 + `data/themes_registry.json` `scope_note` |
| 2026-05-24 | **Bug B (5 slugs FR=EN identiques) = NON-bug** : build vert 857 pages, 0 erreur Zod. Entry IDs Astro distincts via sous-dossier locale (`fr/hamster` vs `en/hamster`), URLs disambiguées par préfixe locale + chemin catégorie. Cas attendu pour noms propres (Iron Man, Scooby-Doo) et standards taxonomiques (Labrador Retriever). Retiré du backlog | Actée — invalidation hypothèse | Réponse rimalab 2026-05-23 (synthétisée cycle en cours) |
| 2026-05-24 | **Convention de gouvernance idées structurantes** (rappel) : jamais classées, toujours reportées avec deadline relative (`MEP+30j`, `post-Niveau-1`, etc.) plutôt que supprimées du backlog | Actée — rappel | Conversation 2026-05-10 + 2026-05-24 |

## Dette technique connue

| Sujet | Origine / détail | Sévérité | Suite |
|---|---|---|---|
| Helper `find_metrics_entry` n'itère pas le schéma `subjects` | `scripts/poc_rerun_2objets.py:71` — produit `pos_v1_chars=0` pour 1 cas (`house_painter_with_roller`). Cf. `2026-05-09_poc-rerun-2objets.md` §A | Mineure | À corriger si on relance des POC `2_objets` |
| Import `HARAKAT_RE` cassé dans `tests/test_content_generator.py` | Empêche le module de s'importer ; pytest doit ignorer ce fichier (`--ignore=tests/test_content_generator.py`) | À investiguer | Stabilisation tests legacy |
| `data/artiste_coloriage.duckdb` checked-in mais legacy | Cf. CLAUDE.md "Things easy to get wrong" | Documentaire | Ne pas écrire de code qui le lit en prod |
| Bug B "5 slugs FR=EN" historiquement listé comme dette | Confirmé NON-bug 2026-05-23 par claude rimalab (build vert). Entry IDs distincts par locale | Documentaire | Retiré du backlog. Pour mémoire si re-questionnement futur |
| Placeholder côté rimalab nommé incorrectement dans rapport rimalab | Rapport rimalab 2026-05-23 disait `seasonal_summer.md`, fichier réel = `arabic-alphabet.md`. Ne pas se fier aux rapports écrits sans `ls` vérifiant | Mineure (process) | Toujours vérifier l'état réel du repo cible avant de baser une décision sur un rapport rédigé |
| Bornes deadline cutover J+30 imprécises | "J+30" = ~2026-06-24 si on prend la date du livrable C2 (2026-05-12) comme J0, mais c'est à confirmer | À clarifier | Demander date cible cutover précise à l'utilisateur avant de l'écrire dans le verbe `pipeline cutover` |

## Hypothèses en cours de validation

- **`Solo bird` à l'échelle** : template prêt, sous-routage flying / perched / cage / branch en place, mais `birds` étant `confidence: Moyenne` n'a jamais été testé en scale-bench. Hypothèse : Insight D (flying explicite dans positif) tient, à valider sur les 14 leaves dédiées (post-MEP v0).
- **Modèle A ADD-ONLY préserve les éditions manuelles en run réel** : modèle conçu sur papier 2026-05-24, hypothèse à valider lors des premiers usages réels post-livraison brief Niveau 1. Cas critique : un humain édite un post.md, lance `pipeline push`, vérifier que le diff est nul.
- **Auto-tagging `themeIds` à la création des posts** : pattern à valider sur le lot 2 (1er run réel post-livraison). Cross-overs intentionnels (noel + saison-hiver pour `olaf_the_snowman`) doivent produire `themeIds: ["noel", "saison-hiver"]` correctement.
- **Cutover via verbe pipeline** (script bump `approved→published`) : pattern à valider à J+30. Garde-fou "refuse si working tree dirty" critique.

## Pièges découverts

### LLM

- **`/no_think` tag opère uniquement sur `qwen3:` strict.** Pour `qwen3.5+`, utiliser le paramètre natif Ollama `"think": false`. Sans ce fix, qwen3.5* timeoutent systématiquement (modèles bloqués en `<think>…</think>`). Code : `apply_no_think_system` + `_supports_native_think_disable` dans `services/ollama_json.py`.
- **Batching vision dégrade fortement la précision** (verdicts corrects 6→2 quand on passe d'unit→batch 6). Toujours **1 image / call** pour la QC vision. Paralléliser via plusieurs workers, jamais via batch.
- **Description AR de qwen3.5:4b dépasse souvent la borne haute 100 caractères** (~37 % de retry attendu). Validate-regen loop obligatoire, +0.8 s/image en moyenne.
- **Harakat fréquents (~26 %) sur outputs AR de qwen3.5:4b**. Strip post-process systématique. Détails de la regex : voir `CLAUDE.md` §Routing LLM.
- **QC anatomie via LLM vision = invalidé.** `qwen3.5:9b` et `gemma4:26b` ont 0 % recall sur défauts `3_jambes` en line-art N&B (5 variantes de prompt testées). Validation humaine uniquement.
- **QC vision LLM peu utile au-delà de l'anatomie.** Verdicts trop souvent "good" en élargi → faible discrimination. Le bénéfice se trouve sur la simplification de la revue humaine (UI annotateur v2), pas sur l'auto-qualification.

### Image / sampler

- **`karras` catastrophique sur sujets complexes** (soccer, scénarios humains dynamiques) — testé 2× (POC v1 favorable mais POC variance seeds 2026-05-07 = échec total). **Piste invalidée définitivement.** Ne pas re-tester.
- **`dpmpp_2m` banni en prod** — tramage quasi-systémique (score moyen 3.75/10). `dpmpp_2m_sde` fallback expérimental uniquement. `euler` seul retenu.
- **`cfg ≥ 1.5` réintroduit `3_jambes`** sur anatomie humaine/animale. Garder `cfg=1.0` strict pour humains et animaux dynamiques.
- **Personnalités identifiables (super-héros costumés, sportifs en maillot)** = outliers couleur résiduelle. Le négatif v3 réduit mais ne supprime pas la trace chromatique caractéristique.
- **Sujets multi-couleur intrinsèques** (`rainbow_*`, `crystal_*`) restent outliers `color_ratio` malgré négatif v3 — cas hors-modèle attendu.
- **ComfyUI partagé = latence multipliée** (~50-75s/image vs 18-20s en isolation). À isoler en scale-up production.

### Pipeline / DB

- **NULL-safe avant tri numérique** : `int(w) if w is not None else 0`. `dict.get("weight", 0)` retourne `None` (pas le défaut) quand la clé existe avec valeur NULL.
- **DuckDB FK constraints eager** (legacy paths) : `DELETE`s **hors** `BEGIN` (auto-commit chacun), puis nouveau `BEGIN` pour `INSERT`s. Cascade ordre : term → collection_image → export → image_taxonomy_tag → coverage_stats → site_taxonomy → vocabulary → taxonomy.
- **Tests doivent rester SQLite-portables** (in-memory, `tests/conftest.py`). Éviter `RETURNING`, `JSONB` operators et autre Postgres-only dans le data layer générique.
- **Singleton `start.py`** : un 2e lancement exit immédiatement via `logs/start.lock`. Stop le 1er d'abord.

### Process / Coordination cross-repo

- **Ne pas se fier aux rapports écrits cross-repo sans vérifier l'état réel.** Rapport claude rimalab 2026-05-23 mentionnait `seasonal_summer.md`, fichier réel = `arabic-alphabet.md`. Toujours `ls` le repo cible avant de baser une décision sur un rapport rédigé.
- **Sync destructif vs ADD-ONLY = arbitrage par type de contenu.** Categories = sync strict (10 entrées stables, structure). Posts/Themes = ADD-ONLY (contenu éditorialement vivant). Ne pas appliquer aveuglément la même stratégie à tous les types.
- **Convention "registry wins" doit être actée AVANT divergence**, sinon merge coûteux. Cas vécu 2026-05-14 : claude rimalab a créé 6 categories manuelles sur main avant que le registry ne soit acté comme source unique → 6 versions divergentes nécessitant arbitrage merge no-ff `-X theirs` 2026-05-24.
- **Multi-sites = architecture, pas implémentation YAGNI.** Le besoin "1 site aujourd'hui, N demain" justifie de prévoir l'archi extensible (Niveau 1 livré) mais pas d'implémenter les commandes CLI (Niveau 2 préparé en roadmap, déclenchement sur signal concret = 2e site planifié).

## Top 5 rapports à charger en priorité

1. **`2026-05-12_audit-contrat-rimalab-v2-v2.md`** — référence conformité contrat 99.75% → 100% post-patches. Source de vérité pour toute évolution contrat plateforme.
2. **`2026-05-15_phase-categories-registry-cross-repo.md`** — registry partagé + flag --sync-categories + 18 tests. Pattern à imiter pour themes_registry.
3. **`docs/architect/2026-05-24_workflow-pipeline-multi-sites.md`** (note d'archi, pas rapport) — référence d'architecture git-as-CMS multi-sites. Lecture obligatoire avant tout brief touchant le pipeline.
4. **`2026-05-09_phase-integration-prompt-generator.md`** — pierre angulaire historique : PromptGenerator comme service Python. Pertinent pour toute évolution génération.
5. **`2026-05-12_phase-mep-v0-D-alwanbooks-pipeline.md`** — état pipeline alwanbooks (R2 + rimalab-v2). Base pour brief Niveau 1.

## Notes pour le prochain cycle

- **Action n°1 critique : envoyer notif rimalab + lancer briefs** (upload R2 + Niveau 1). 3 actions séquentielles, ~30 min côté humain + 15 min upload + 3-4h dev brief Niveau 1.
- **Action n°2 : surveiller exécution Niveau 1** (smoke runs en --no-git-push, vérifier ADD-ONLY préserve les posts existants, vérifier auto-tag themeIds correct sur cross-overs noel/saison-hiver). Rapport phase attendu côté reports.
- **Action n°3 : valider Lot A côté rimalab** : merge no-ff registry wins exécuté, règle Astro "masquage si 0 post" implémentée, build vert post-merge confirmé.
- **Action n°4 : cadrer cutover J+30** — date cible précise (~2026-06-24 ?) à acter. Coordination archi (script cutover livré dans Niveau 1) + rimalab (flip `PUBLIC_SITE_STATE`).
- **Action n°5 : enrichir themes_registry** après MEP v0 — ajouter rentrée scolaire, fête des mères, halloween, pâques selon besoin éditorial. PR sur `data/themes_registry.json` puis `pipeline --sync-themes`.
- **Action n°6 : monitorer divergences cross-repo** — si un humain édite un MD à la main côté rimalab et qu'on lance un push après, vérifier que ADD-ONLY a bien protégé. Hypothèse à valider en run réel.
- **Backlog post-Niveau 1** :
  - Vague 2 MEP v0 (annotateur HTML mode `target_type='subject'`, jobs enrichissement i18n + prompt + image + qc auto pour subjects sélectionnés)
  - POC `birds` 14 leaves Moyenne (post-MEP v0)
  - Plan B SubjectQualifier (post-MEP v0) : lint regex + blacklist apprenante
  - Plan C SubjectQualifier (MEP+30j) : brainstorm + qualification couplés
  - Niveau 2 multi-sites : déclencher si 2e site destinataire planifié concrètement
  - Niveau 3 envisagé : skill `artiste-pipeline-skill` (verbes humains les plus fréquents)
