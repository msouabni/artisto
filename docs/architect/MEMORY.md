# Architect Memory — Artiste Coloriage

Mis à jour : 2026-05-09 (livraison annotateur v2)

## État courant du projet

Pipeline opérationnelle de bout en bout : taxonomie 1376 feuilles → `PromptGenerator` 100 % template (intégré comme service `src/services/prompt_generator.py`) → workflow ERNIE direct soumis à ComfyUI → QC histogram automatique (Pillow) → annotation humaine via `data/benchmark-annotator.html`. Paramètres image figés (euler / 8 steps / cfg=1.0 / scheduler normal). Routing LLM acté (qwen3.5:4b primaire texte, qwen3.5:9b vision). Couverture cumulée ~54/85 workflow_classes, ~470 images générées sur 4 runs scale benchmark. Tous les correctifs templates `2_objets` (NEGATIVE_V3 étendu + `_ISOLATION` + `LEAF_OVERRIDES`) appliqués et re-runs ciblés OK. La prochaine étape majeure est la validation humaine large des sorties pour figer le PromptGenerator avant scale-up production.

## Cycle en cours

- **Intitulé** : Validation humaine PromptGenerator + arbitrages cartographie résiduels
- **Démarré** : 2026-05-09
- **Critères de sortie** :
  - 13 paires v1/v2 du re-run `2_objets` annotées → confirmer extinction du défaut
  - Méta-patterns annotés en priorité (Grille imagier, Imagier 3×3, Frise narrative, Multi-sujets) — métrique `color_ratio` aveugle à la composition
  - Classes "OU" (12 cas) : variante choisie par PromptGenerator validée comme cohérente
  - Décision sur les ~31 classes restantes (confidence non-Haute strict) : couverture partielle, run dédié ou exclusion
  - ✅ **Annotateur v2 livré 2026-05-09** (UI compacte + raccourcis chord + grille 3 axes + score 1-6, migration v1→v2 appliquée sur les 9 fichiers existants — 539 annotations, 0 anomalie). Réf. `2026-05-09_phase-annotateur-v2.md`.
  - **Greffon prod livré** (table `annotation` polymorphe + endpoints `/api/review/*` + mode switch UI) pour brancher l'annotateur sur les `image_output` prod (pas avant fin annotation POC)
- **Bloqueurs** :
  - Helper `find_metrics_entry` (annotateur) n'itère pas le schéma `subjects` → `pos_v1_chars=0` sur certains diffs (mineur, pas bloquant)

## Échéances / Deadlines

| Date cible | Quoi | Statut | Contexte |
|---|---|---|---|
| 2026-05-09 | Restart ComfyUI avec `--listen 0.0.0.0` pour confirmer Tailscale end-to-end | fait | Confirmé par l'utilisateur 2026-05-09. Bloqueur levé du cycle en cours. |
| 2026-05-12 | Annotation des 13 paires v1/v2 du re-run `2_objets` | à faire | Volume modeste (~13 paires). Valide la sortie du fix templates `2_objets` (NEGATIVE_V3 + `_ISOLATION` + `LEAF_OVERRIDES`). Référence : `2026-05-09_poc-rerun-2objets.md`. |
| 2026-05-14 | Décision sur les ~31 classes confidence non-Haute strict | à faire | Arbitrage : run élargi `startswith("Haute")` vs exclusion vs traitement manuel. Estimation génération : 30-60 min si run élargi. Dépend partiellement de la visibilité que donne l'annotation en cours. |
| 2026-05-16 | Annotation des méta-patterns prioritaires (Grille imagier, Imagier 3×3, Frise narrative, Multi-sujets) | à faire | Volume plus important. Critique car `color_ratio` aveugle à la composition — seule validation visuelle peut confirmer la structure. |
| 2026-05-09 | Briefs annotateur (v2 + greffon prod) rédigés | fait | `docs/architect/briefs/2026-05-09_brief-annotateur-v2.md` (P1+P2+P3 consolidés) et `2026-05-09_brief-greffon-prod.md` (P4). Estimés ~6.5h dev chacun. |
| 2026-05-09 | Annotateur v2 livré (claude-code dev) — UI compacte + raccourcis chord + grille 3 axes + score 1-6 + script migration `annotations.json` | fait | Livré en 1 cycle agent. 24/24 tests verts. Migration `--apply` effectuée (539 annotations, 0 anomalie, `.bak` supprimés). Commits : `164c02c` (feat consolidé) + `ca7118f` (fix score-row au-dessus de l'image). Validation visuelle UI confirmée par l'utilisateur 2026-05-09. Réf. `2026-05-09_phase-annotateur-v2.md` + `2026-05-09_migration-annotateur-grille-v2.md`. |
| 2026-05-19 | Greffon prod livré (claude-code dev) — table `annotation` polymorphe + endpoints `/api/review/*` + mode switch UI | à faire | Bloqué par annotateur v2. Pas d'apply/reject : pipeline existante intacte. |

## Décisions architecturales actées

| Date | Décision | Statut | Rapport |
|---|---|---|---|
| 2026-05-05 | Routing LLM : `qwen3.5:4b` primaire texte (98.2/100, 5× plus rapide), `qwen3.5:9b` primaire vision (volume 50+ requis avant prod), `gemma4:26b` arbitre couleur, batching vision banni | Actée | `2026-05-05_decision-llm-finale.md` |
| 2026-05-05 | Mécanique `/no_think` qwen3 strict vs paramètre natif `"think": false` qwen3.5+ — fix code dans `services/ollama_json.py` | Actée | `2026-05-05_decision-llm-finale.md` |
| 2026-05-05 | Bornes Zod plateforme uniformes (HARD) vs SOFT caps pipeline différenciés par locale (AR plus stricte). Pipeline rejette sur SOFT, jamais sur HARD | Actée | confirmation Alwan Books 2026-05-05 |
| 2026-05-06 | Paramètres image figés sans nouveau benchmark : `sampler=euler`, `steps=8`, `cfg=1.0`, `scheduler=normal`. Résolutions adaptatives par `workflow_class` (1024² défaut, 848×1264 portraits humain, 1376×768 paysages) | Actée | `2026-05-06_poc-seed-variance.md` + CLAUDE.md |
| 2026-05-09 | `PromptGenerator` intégré comme service Python (`src/services/prompt_generator.py`) — 100 % template, 1376 leaves indexées, sortie `{positive, negative, resolution, workflow_class, technique, pipeline, confidence, pitfalls}` | Actée | `2026-05-09_phase-integration-prompt-generator.md` |
| 2026-05-09 | Audit cartographie : 4 nouveaux templates (`Solo insect`, `Solo fish`, `Solo bird`, `Solo reptile`) avec sous-routage morphologique. 3 sous-catégories re-routées (`insects_and_minibeasts`, `marine_animals`, `birds`). 41 leaves bénéficient d'un template adapté | Actée | `2026-05-09_audit-cartographie-templates.md` |
| 2026-05-09 | Fix `2_objets` : `NEGATIVE_V3` étendu (multiple animals / second subject / etc.), suffixe `_ISOLATION` injecté dans 5 templates Solo, `LEAF_OVERRIDES` (sheep_with_lamb, eid_al_adha_sheep), `_RISKY_MULTI_PATTERNS` (auto-renforcement négatif) | Actée — validation visuelle 13 v2 pendante | `2026-05-09_fix-templates-2objets.md` + `2026-05-09_poc-rerun-2objets.md` |
| 2026-05-09 | Multi-index fusion dans annotateur : 3 schémas supportés (`subjects`, `results` keyed par leaf_id, `results` legacy). 38 `index-*.json` fusionnés. 11 tests unitaires verts dans `tests/test_benchmark_routes.py` | Actée | `2026-05-09_fix-multiindex-benchmark.md` |
| 2026-05-09 | Bind réseau configurable via `ARTISTE_API_HOST` / `COMFYUI_HOST` (défaut `0.0.0.0`). Sondes santé restent sur `127.0.0.1`. API + ComfyUI testés Tailscale OK | Actée | `2026-05-09_tailscale-access.md` |
| 2026-05-09 | QC anatomie ligne-art = validation humaine uniquement (LLM vision recall=0% sur 5 variantes de prompt sur défauts `3_jambes`). Pas de QC automatique anatomique en pipeline | Actée — invalidation P3 partielle | `2026-05-07_poc-vision-qc-prompts.md` (réf.) + CLAUDE.md §PromptGenerator |
| 2026-05-09 | Annotateur v2 — refonte UI compacte + raccourcis chord + grille 3 axes (Image 18 / Prompt 8 / Custom libre) + flags pattern/sample/publishable + score 1-6 (migration auto 1-10 → 1-6, `score_legacy` conservé). Storage benchmark reste fichier `annotations.json`. Schéma annotation **figé** dès cette refonte (sera réutilisé tel quel par le greffon prod). | Actée — livrée 2026-05-09 (commits `164c02c` + `ca7118f`) | `2026-05-09_brief-annotateur-v2.md` + `2026-05-09_phase-annotateur-v2.md` |
| 2026-05-09 | Greffon prod via mapping (pas d'intégration profonde) : table `annotation` **polymorphe** (`target_type`, `target_id`, sans FK explicite, whitelist côté API) — peut s'attacher à `image_output` (cible prod), `image`, `term`, etc. Endpoints REST `/api/review/queue`, `/api/review/file`, `/api/annotation`. **Pas de boutons apply/reject** dans l'annotateur — pipeline existante intacte. GraphQL/BFF → backlog. | Actée — brief rédigé, dev pendant | `2026-05-09_brief-greffon-prod.md` |

## Hypothèses en cours de validation

- **Templates Solo durcis éliminent `2_objets`** : 13 cas critiques re-générés v2, métrique `color_ratio` propre, **validation visuelle pendante** (annotation humaine des paires v1/v2). Réf. `2026-05-09_poc-rerun-2objets.md`.
- **Méta-patterns (Grille / Imagier 3×3 / Frise / Multi-sujets)** : structures complexes avec `cr_avg` propre (0.0017–0.0022) mais le `color_ratio` ne mesure pas la composition. Hypothèse : la structure attendue tient, à valider visuellement en priorité.
- **Couverture ~31 classes confidence non-Haute strict** : nécessite arbitrage — run élargi (`startswith("Haute")`) vs exclusion explicite vs traitement manuel. Pas encore décidé.
- **qwen3.5:9b QC vision en volume 50+ images** : caveat acté à la décision LLM finale, pas encore lancé. Bloque la promotion vers prod du QC vision P3.
- **`Solo bird` à l'échelle** : template prêt, sous-routage flying / perched / cage / branch en place, mais `birds` étant `confidence: Moyenne` n'a jamais été testé en scale-bench. Hypothèse : Insight D (flying explicite dans positif) tient, à valider sur les 14 leaves dédiées.

## Pièges découverts

### LLM
- **`/no_think` tag opère uniquement sur `qwen3:` strict.** Pour `qwen3.5+`, utiliser le paramètre natif Ollama `"think": false`. Sans ce fix, qwen3.5* timeoutent systématiquement (modèles bloqués en `<think>…</think>`). Code : `apply_no_think_system` + `_supports_native_think_disable` dans `services/ollama_json.py`.
- **Batching vision dégrade fortement la précision** (verdicts corrects 6→2 quand on passe d'unit→batch 6). Toujours **1 image / call** pour la QC vision. Paralléliser via plusieurs workers, jamais via batch.
- **Description AR de qwen3.5:4b dépasse souvent la borne haute 100 caractères** (~37 % de retry attendu). Validate-regen loop obligatoire, +0.8 s/image en moyenne.
- **Harakat fréquents (~26 %) sur outputs AR de qwen3.5:4b**. Strip post-process systématique. Détails de la regex (codepoints explicites + warning RTL trap) : voir `CLAUDE.md` §Routing LLM.
- **QC anatomie via LLM vision = invalidé.** `qwen3.5:9b` et `gemma4:26b` ont 0 % recall sur défauts `3_jambes` en line-art N&B (5 variantes de prompt testées). Validation humaine uniquement.

### Image / sampler
- **`karras` catastrophique sur sujets complexes** (soccer, scénarios humains dynamiques) — testé 2× (POC v1 favorable mais POC variance seeds 2026-05-07 = échec total). **Piste invalidée définitivement.** Ne pas re-tester.
- **`dpmpp_2m` banni en prod** — tramage quasi-systémique (score moyen 3.75/10). `dpmpp_2m_sde` fallback expérimental uniquement. `euler` seul retenu.
- **`cfg ≥ 1.5` réintroduit `3_jambes`** sur anatomie humaine/animale (testé sur soccer). Garder `cfg=1.0` strict pour humains et animaux dynamiques. `cfg=1.5` acceptable uniquement sur inanimés simples.
- **Personnalités identifiables (super-héros costumés, sportifs en maillot d'équipe) = outliers couleur résiduelle.** Le négatif v3 réduit mais ne supprime pas la trace chromatique caractéristique. Si standard `cr < 0.001` exigé : négatif renforcé team-colors ou postprocess noir-et-blanc strict.
- **Sujets multi-couleur intrinsèques** (`rainbow_*`, `crystal_*`) restent outliers `color_ratio` malgré négatif v3 — cas hors-modèle attendu, à publier tel quel ou exclure de la prod selon le standard.
- **ComfyUI partagé = latence multipliée** (~50-75s/image vs 18-20s en isolation). Pas un problème intrinsèque, mais à isoler en scale-up production.

### Pipeline / DB
- **NULL-safe avant tri numérique** : `int(w) if w is not None else 0`. `dict.get("weight", 0)` retourne `None` (pas le défaut) quand la clé existe avec valeur NULL. Sweep complet sur les `sort/sorted` après chaque fix NULL.
- **DuckDB FK constraints eager** (legacy paths, `scripts/import_taxonomy_json_to_db.py`) : `DELETE`s **hors** `BEGIN` (auto-commit chacun), puis nouveau `BEGIN` pour `INSERT`s. Cascade ordre : term → collection_image → export → image_taxonomy_tag → coverage_stats → site_taxonomy → vocabulary → taxonomy.
- **Tests doivent rester SQLite-portables** (in-memory, `tests/conftest.py`). Éviter `RETURNING`, `JSONB` operators et autre Postgres-only dans le data layer générique.
- **Singleton `start.py`** : un 2e lancement exit immédiatement via `logs/start.lock`. Stop le 1er d'abord.

## Top 5 rapports à charger en priorité

1. **`2026-05-09_phase-integration-prompt-generator.md`** — pierre angulaire : intégration `PromptGenerator` comme service + premier scale POC validé (27/30 OK, max `color_ratio` 0.0019).
2. **`2026-05-09_audit-cartographie-templates.md`** — cartographie taxonomique : 4 nouveaux templates morphologiques + dispatcher entries + outliers résiduels à traiter via `leaf_overrides`.
3. **`2026-05-09_poc-scale-uncovered-classes.md`** — état le plus récent et global : 310/310 OK sur 37 classes Haute, couverture cumulée ~54/85 workflow_classes, recommandations annotation humaine prioritaire.
4. **`2026-05-09_fix-templates-2objets.md`** + **`2026-05-09_poc-rerun-2objets.md`** — diagnostic + correctif anti multi-sujet + validation par re-run ciblé 13 cas.
5. **`2026-05-05_decision-llm-finale.md`** — clôture chapitre LLM : routing acté + caveats AR + mécaniques `/no_think` vs `think: false` + bornes Zod HARD/SOFT.

## Notes pour le prochain cycle

- **Annotation humaine massive (~470 images)** : protocole et priorisation à formaliser. Ordre suggéré → méta-patterns (composition aveugle) → 13 v2 du re-run `2_objets` (validation fix) → personnalités outliers couleur (top-10 cr) → reste.
- **Couverture des ~31 classes confidence non-Haute strict** : décision attendue (run élargi `startswith("Haute")` vs exclusion vs manuel). Estimation 30-60 min de génération si run élargi.
- **Mécanisme `production_strategy.leaf_overrides`** dans `PromptGenerator.build_prompt` : permet de re-router ~12-15 outliers morphologiques (oiseaux dans farm_animals, reptiles dispersés, créatures fantasy mal classées) sans toucher la structure publique de la taxonomie. Estimation ~30 min patch + curation.
- **POC `birds` dédié** sur les 14 leaves `confidence: Moyenne` (jamais testées à l'échelle) pour valider Insight D (flying explicite dans positif) et débloquer la promotion `Haute`. ~4 min génération.
- **Volume vision 50+ sur qwen3.5:9b** : caveat acté pré-prod QC vision P3, pas encore lancé. À planifier avant tout codage worker QC vision.
- **Compare-grid v1↔v2 dans annotateur** : extension UI utile pour accélérer la revue de 13 paires (puis futures itérations templates). Pas dans la refonte annotateur v2 (qui se concentre sur la grille structurée mono-image), à reposer une fois la v2 livrée.
- **Restart ComfyUI** ✅ fait 2026-05-09 (Tailscale end-to-end opérationnel API + ComfyUI).
- **Annotateur — ouvertures futures** :
  - Migration des `data/<dir>/annotations.json` vers la table `annotation` polymorphe (`target_type='benchmark_file'`) pour unifier requêtes/dashboard. Non prioritaire, statu quo OK.
  - Annotation polymorphe sur `term`, `image`, `job` — la table le permet ; à activer cas par cas.
  - Auto-décision apply/reject basée sur tags/score — à évaluer **après** volume d'usage réel sur la grille v2.
  - Dashboard agrégation (annotations par concept / workflow_class / défaut / score moyen) — point de bascule vers GraphQL/BFF si ça se confirme.
