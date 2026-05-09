# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Artiste Coloriage is a Python pipeline that turns a universal taxonomy of themes into line-art coloring images. It chains: taxonomy curation → LLM concept/prompt generation (Ollama) → image generation (ComfyUI) → editorial review → publication. UI is HTML + Tabulator.js served statically by FastAPI; there is no JS framework.

The README is in French and is the most complete reference; `architecture.md` is partly outdated (it describes a DuckDB-only design that has since moved to PostgreSQL — see "Database" below).

## Common commands

All commands run from the repo root. The API and CLI rely on `PYTHONPATH=src` (set automatically by `pytest.ini`, by `start.py`, and by running uvicorn from `src/`).

```bash
# Bootstrap
pip install -r requirements.txt
docker compose up -d postgres            # PostgreSQL 16 on :5432
alembic upgrade head                     # apply migrations
python scripts/init_db.py                # create tables + seed job_type_config
python scripts/seed_data.py              # optional demo data

# Unified start (API + workers + ComfyUI if a clone is found)
python start.py                          # singleton: a 2nd run exits via start.lock
python start.py --with-ollama            # also start `ollama serve` if not reachable
python start.py --no-reload --no-comfy   # common dev combo

# Run pieces individually
cd src && python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
python scripts/run_image_worker.py       # ComfyUI worker (loop, --once for single job)
python scripts/run_text_worker.py        # Ollama worker

# Tests (uses in-memory SQLite via tests/conftest.py — does NOT touch postgres)
pytest                                   # full suite
pytest tests/test_taxonomy_api.py        # one file
pytest -k taxonomy_loader                # by name pattern
pytest tests/test_taxonomy_api.py::test_name -x   # single test, fail fast

# CLI (Typer; the `jobs` subcommand is an HTTP client to the running API at ARTISTE_API_BASE)
python -m cli --help
python -m cli jobs --help
```

API: http://127.0.0.1:8000 · Swagger: `/docs` · Admin hub: `/data/admin.html`.

## Architecture (the parts that span multiple files)

### Database — PostgreSQL with a duckdb-shaped adapter

- Runtime DB is **PostgreSQL** (`docker-compose.yml`, `DATABASE_URL` in `.env`). The `data/artiste_coloriage.duckdb` file in the repo is **legacy** — do not assume DuckDB is the active store.
- All DB access goes through `src/api/db.py`. `DBConnAdapter` wraps a SQLAlchemy `Session` but exposes a `execute(sql, [params]) -> SqlResult` interface using `?` placeholders. `_qmark_to_named` rewrites `?` → `:p0, :p1…` so legacy SQL written for DuckDB still works against Postgres. When adding new SQL, keep using `?` placeholders to stay consistent.
- FastAPI route handlers depend on `get_db_read` / `get_db_write` (write commits on success, rolls back on exception). New route handlers should use these dependencies, not raw `SessionLocal()`.
- Tests override these dependencies with an in-memory SQLite connection from `tests/conftest.py`. Tests must work against SQLite — avoid Postgres-only SQL (e.g. `RETURNING`, `JSONB` operators) in the generic data layer; if you need it, branch on dialect or stay portable.

### Job queue — generic worker framework

Two active worker types share `src/workers/base_worker.py` (abstract):

| Type                      | Worker                          | Backend |
|---------------------------|---------------------------------|---------|
| `image_generation`        | `src/workers/image_worker.py`   | ComfyUI |
| `text_enrichment` + IA jobs | `src/workers/ai_pipeline_worker.py` / `text_worker` | Ollama |

Mechanics live entirely in `base_worker.py`:
- **fetch_and_start** picks the next `pending` job (priority ASC, date ASC), checks `job_type_config.enabled` and `max_concurrent=1`.
- **Heartbeat** thread (30 s); jobs without heartbeat for >5 min are recovered to `pending`.
- **Retry/backoff**: 3 attempts, delays `[60, 300, 900]` s (`RETRY_DELAYS`).
- A type can be auto-disabled by the worker on hard failure; the user re-enables it via `PUT /api/jobs/types/{type}` or the Jobs editor UI.

`api.db.DEFAULT_JOB_TYPES` is the seed list of job types used at API startup (`lifespan` → `ensure_default_job_types`). When you add a new job type: register it here AND implement the worker side.

### Image lifecycle

The `image.status` field progresses through this state machine (most transitions are automatic — see README "Pipeline image"):

```
draft → prompt_ready → scheduled → generating → generated
                                               ↘ awaiting_validation (job side) → apply/reject
                                                                                  ↘ approved/rejected → published
```

Important invariants:
- While a job is `awaiting_validation`, the image stays in `generating` until `POST /api/jobs/{id}/validate {action: apply|reject}`.
- Status never auto-regresses except: ComfyUI error (`generating` → `scheduled`), explicit reject, or `image_generation` type auto-disabled (job stays `pending`, image back to `scheduled`).
- Job result review/apply lives in `src/api/job_review_artifact.py` (contract) and `src/api/job_review_apply.py` (business apply). Adding a new reviewable job type means extending both.

### Routes layout

`src/api/main.py` mounts six routers under `/api/*` from `src/api/routes/`: `taxonomy`, `ai`, `generation`, `images`, `jobs`, `sites`. The full route table is in the README. The `/data/` mount serves the editor HTML files (`taxonomy_editor`, `images_editor`, `jobs_editor`, `sites_editor`, `admin`).

### Logging

`src/artiste_logging.py::setup_logging(component)` is called once per process (API, each worker). Logs go to stderr **and** to `logs/<component>.log` (rotating, 10 MB × 5) unless `ARTISTE_LOG_TO_FILE=0`. The pytest conftest sets it to `0`. Uvicorn `--reload` makes the parent and worker both write to `logs/api.log` and lines can interleave — prefer `--no-reload` when reading logs is critical.

## Project conventions (from `.cursor/rules/`)

These are project-specific rules that have caused real bugs; follow them.

### Always create an editor for any YAML/JSON deliverable

When adding a new YAML/JSON config (taxonomy, use cases, site registry, mapping…), also add an HTML editor next to it: file picker, Tabulator.js table with inline edit, downloadable Blob. Pattern reference: `docs/use-cases/use_cases_editor.html`.

### Keep `docs/use-cases/use_cases.yaml` in sync

When you implement a use case, update its `status` (`planned` → `in_progress` → `done`) and `related_files`. Each use case has a stable `id` (e.g. `TAXO_ADD_TERM`).

### NULL-safe DB → API

Numeric/text columns can be NULL. `dict.get("weight", 0)` returns `None` (not the default) when the key is present with a NULL value, and sorting/comparing `None` raises `TypeError`. Rules:
- Never use `x.get("weight", 0)` directly as a sort key. Use `int(w) if w is not None else 0`.
- Normalize numeric fields (`weight`, counts…) to `int`/`float` before returning them in JSON responses — clients sort/compare on these.
- Convert DuckDB/driver-native types (e.g. `numpy.int64`) to native JSON types at read time, otherwise FastAPI returns 500.
- When fixing a NULL issue, sweep all `sort`/`sorted` calls and numeric reads in the affected area, and add a pytest reproducing the case.

Reference fix: `src/api/routes/taxonomy.py` (`_term_row_to_dict`, `_build_terms_tree`, `_term_to_response`); tests in `tests/test_taxonomy_api.py`.

### DuckDB-style FK constraints (legacy code paths only)

Some scripts (`scripts/import_taxonomy_json_to_db.py`, parts of `taxonomy.py`) still target DuckDB, which validates FKs eagerly inside a transaction. If you touch them: do `DELETE`s **outside** any `BEGIN` (auto-commit each), then open a new transaction for `INSERT`s; and always delete children before parents. A full taxonomy replace cascades into `term`, `collection_image`, `export`, `image_taxonomy_tag`, `coverage_stats`, `site_taxonomy`, `vocabulary`, `taxonomy` (in that order). Document this in the API/script doc when relevant.

## Key environment variables

`OLLAMA_BASE_URL`, `OLLAMA_MODEL` (default `qwen3.5:4b` — voir routing LLM ci-dessous), `OLLAMA_TIMEOUT` · `COMFY_URL` (`http://127.0.0.1:8188`), `COMFY_POLL_INTERVAL`, `COMFY_TIMEOUT` · `DATABASE_URL` · `ARTISTE_LOG_LEVEL`, `ARTISTE_LOG_DIR`, `ARTISTE_LOG_TO_FILE` · `ARTISTE_API_HOST` (default `0.0.0.0` — bind interface uvicorn ; mettre `127.0.0.1` pour limiter au loopback), `ARTISTE_API_PORT`, `ARTISTE_API_BASE` (used by the CLI HTTP client) · `COMFYUI_HOME` / `COMFYUI_ROOT`, `COMFYUI_PYTHON`, `COMFYUI_HOST` (default `0.0.0.0` — bind interface ComfyUI passé à `--listen` ; idem pour limiter au loopback) (used by `start.py` to launch a ComfyUI clone). The README has the full table with defaults.

## Routing LLM (acté 2026-05-05)

Choix figés à l'issue de la séquence POC `llm-benchmark` v1 → v2 → `qwen35-retest` → `qwen35-volume` → `qwen35-vision` → `qualitative-mickey`. Détails et historique : `docs/reports/2026-05-05_decision-llm-finale.md`.

| Tâche | Modèle | Rôle | Justification courte |
|---|---|---|---|
| Texte (i18n EN/FR/AR, concepts, enrichissement) | **`qwen3.5:4b`** | **Primaire** | Champion bench (98.2/100), 5× plus rapide que qwen3:8b, 3.16 GB RAM. Validate-regen requis sur description AR + strip harakat post-process |
| Texte (fallback qualité) | `qwen3:8b` | Fallback qualité | Si qwen3.5:4b plante ou dérive sur volume — qualité 87.5/100 validée v2 |
| Concepts taxonomie (fallback cohérence) | `aya-expanse:8b` | Fallback concepts | 0/25 doublons et 0/25 cross-locale suspect — utile si suggest_children sature |
| QC vision (P3) | **`qwen3.5:9b`** | **Primaire vision** | Multimodal natif validé, 8.4× plus rapide que gemma4 (2.3 s vs 19 s/image), permet 2 workers parallèles sur 16 GB VRAM. **Volume 50+ images requis avant promotion prod** |
| QC vision (fallback) | `gemma4:26b` | Arbitre vision | Plus précis sur les couleurs subtiles (6/6 vs 5/6 sur mini-bench). À déclencher quand qwen3.5:9b dit "good" mais Pillow histogram suggère couleurs |
| Texte (fallback vitesse batch) | `qwen2.5:7b` | Fallback batch | 7× plus rapide en cas de saturation, mais regen loop **obligatoire** (bornes 0-4/10) |

**Mécaniques importantes :**
- **`/no_think` system tag** : injecté **uniquement pour `qwen3:` strict** (pas `qwen3.5`). Pour qwen3.5+, utiliser le paramètre natif Ollama `"think": false` dans le body de la requête. Géré automatiquement par `apply_no_think_system` + `_supports_native_think_disable` dans `src/services/ollama_json.py`.
- **Strip harakat post-process** sur tout output AR (regex codepoints explicites `[ؐ-ًؚ-ٟ]` — la version inline littérale est sensible au RTL trap au copier-coller). Appliqué après le LLM, instantané, n'altère pas le sens.
- **Validate-regen loop** sur description AR : ~37 % de retry attendu (pattern de dépassement +10/+20 chars sur la borne haute 100). Ajouter ~0.8 s de latence par image.
- **Surchargeable par requête** : `model` peut être passé dans le body API pour forcer un modèle spécifique sur une tâche donnée.

## Paramètres de génération image — base de connaissance empirique

Source : benchmarks humains 2026-05-06 (130+ images annotées, 8 concepts, euler/dpmpp_2m/dpmpp_2m_sde × steps × cfg × résolution).

### Défauts prod (ne pas changer sans nouveau benchmark)
- sampler_name : euler
- steps : 8
- cfg : 1.0
- scheduler : normal
- denoise : 1.0
- width / height : 1024×1024

### Règles validées empiriquement

| Règle | Valeur | Justification |
|---|---|---|
| Sampler | euler seul | +2 pts vs dpmpp_2m_sde, +2.6 pts vs dpmpp_2m. dpmpp_2m banni (tramage systémique). |
| Steps euler | 8 = optimum | 12s = creux (5.75 vs 7.50 à 8s). 20s utilisable pour scènes complexes mais gris résiduel. |
| CFG | 1.0 fixe si anatomie humaine/animale | cfg 1.5+ réintroduit 3_jambes sur soccer (score 1). cfg 1.5 acceptable sur inanimes simples. cfg 3.0 = dégradation universelle. |
| Résolution | 1024 pour personnages/scènes complexes | 768 = sweet spot pour objets/animaux simples (moins de traits discontinus). 512 = trop simple sur sujets riches. |
| Scheduler | normal uniquement | karras = catastrophique sur 2/3 concepts complexes (score 1). Réservé aux sujets simples mono-objet uniquement (soccer explicitement exclu — testé en variance seeds, échec total). |

### Spectrum de complexité des concepts

| Tier | Exemples | Score moyen | Défauts typiques |
|---|---|---|---|
| ✅ Simple inanime | hammer, flower, fish, guitar, train | 9-10/10 | aucun |
| ✅ Simple animé | cat, lion, bicycle | 7-9/10 | gris_résiduel mineur |
| ⚠️ Complexe animé | astronaut, soccer, dragon | 6-9/10 | anatomy si cfg>1.0, couleurs_résiduelles |
| ❌ Scène intérieure | refrigerator | 1-3/10 | color_prior + perspective_KO — traiter via two-step ou prompt_filter |

### Couleurs résiduelles
Aucun paramètre sampler/steps/cfg ne corrige les couleurs résiduelles. Fix uniquement upstream :
1. `strip_color_nouns` dans le prompt filter (POC 2026-05-05 validé)
2. Négatif additif couleur spécifique au concept
3. Two-step colored→lineart pour color_prior élevé (POC 2026-05-05 validé)

### Anatomie (3 jambes, membres surnuméraires)
- Garder cfg=1.0 (cfg>1.0 réintroduit le défaut)
- Négatif anatomy ciblé : "extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, wrong number of limbs, six fingers, deformed feet, no motion"
- Ne pas raccourcir le prompt writer (v2/v3 courts → 3_jambes même à euler 8s cfg 1.0)
- karras 8s = **piste invalidée** pour soccer (POC v1 favorable, POC variance seeds 2026-05-07 = échec total — toutes les images ratées). Ne pas tester à nouveau.

### Sampler blacklist
- dpmpp_2m : banni en prod (tramage quasi-systématique, score moyen 3.75/10)
- dpmpp_2m_sde : fallback expérimental uniquement (score moyen 4.38/10)
- Si sampler_name == "dpmpp_2m" dans job.config : warning ou refus si steps < 20

## Validation de contenu — HARD caps Zod plateforme vs SOFT caps éditoriaux pipeline

Source : réponse plateforme Alwan Books **2026-05-05** + ADR §1.13. Les hard caps Zod sont **uniformes pour toutes les locales** (EN/FR/AR). Le pipeline Python applique en plus des sweet spots éditoriaux internes plus stricts, distincts et **différenciés par locale** (densité lexicale AR ~50 % inférieure à EN/FR).

| Champ | HARD cap Zod plateforme (toutes locales) | SOFT cap éditorial pipeline EN/FR | SOFT cap éditorial pipeline AR |
|---|---|---|---|
| `title` | [5, 100] | [40, 60] | [25, 55] |
| `title_card` | [5, 40] | (cible ≤ 30) | ≤ 25 |
| `description` | [20, 200] | [80, 130] | [40, 115] |

**Règles d'implémentation pour la validate-regen loop :**
- **Rejeter sur SOFT caps**, pas sur HARD caps. Le pipeline Python est notre gate qualité interne, pas un miroir du Zod plateforme.
- Un contenu qui passe les SOFT caps est **toujours** publiable côté plateforme (la marge SOFT⊂HARD est confortable).
- Le build Astro plateforme ne cassera jamais sur nos longueurs AR.
- Les SOFT caps sont calibrables ; les HARD caps sont contractuels et ne peuvent pas être étendus sans renégocier le contrat plateforme.

Détails et historique : `docs/workflow-pipeline.md` §7 (Points d'attention) et `docs/reports/2026-05-05_analyse-bornes-validation.md`.

## PromptGenerator — base de connaissance empirique (acté 2026-05-09)

Source : audit cartographie 2026-05-09, poc-scale-benchmark (196 images annotées, 1376 feuilles). Fichier : `src/services/prompt_generator.py`.

### Architecture

`PromptGenerator` lit 3 JSON : `coloring_taxonomy_full.json` (1376 feuilles), `taxonomy_production_cartography.json` (stratégie par sous-catégorie), `coloring_taxonomy_seo.json` (enrichissement SEO). Aucun LLM — génération 100% template.

```python
gen = PromptGenerator()          # charge les 3 JSON depuis data/prompt_generator/
result = gen.build_prompt("lion_in_savanna")
# → {positive, negative, resolution, workflow_class, technique, pipeline, confidence, pitfalls, ...}
```

### Routing résolution par workflow_class (prod)

| workflow_class | Résolution | Raison |
|---|---|---|
| Solo humain en action, Solo humain pose active | 848×1264 (portrait) | Anatomie verticale, batch_size=3 recommandé |
| Solo objet (véhicule), Scène paysage | 1376×768 (landscape) | Composition horizontale |
| Tout le reste | 1024×1024 | Défaut universel |

### NEGATIVE_V3 (v3 + isolation 2026-05-09)

Contient en plus de l'anatomie de base : `"multiple animals, other animals, companion animal, group of animals, animal in background, second subject, multiple subjects"`. Ne pas supprimer ces termes — ils réduisent le taux 2_objets de ~8% à <1% estimé.

### Règles templates (validées poc-scale-benchmark)

| Règle | Détail |
|---|---|
| `_ISOLATION` suffix | Tous les templates Solo (animal/insect/fish/bird/reptile) ajoutent `"isolated subject, no other animals or objects nearby"` en fin de positif. |
| `LEAF_OVERRIDES` | Dict `leaf_id → positive_override` pour feuilles à nom ambigu. Actuellement : `sheep_with_lamb`, `eid_al_adha_sheep`. Étendre ici plutôt que dans les templates. |
| `_RISKY_MULTI_PATTERNS` | Patterns leaf_id (_with_friend, _with_chicks, _and_, …) → renforcement négatif automatique. |
| Insectes | `template_solo_insect` : clause pattes adaptative (6/8 selon espèce). Env. "on a simple leaf or flower". |
| Poissons/marins | `template_solo_fish` : corps/env selon morphologie (octopus, jellyfish, crab, seahorse, whale/dolphin, etc.) |
| Oiseaux | `template_solo_bird` : pose vol vs posée selon mots-clés dans le nom (flying, soaring, in cage, in lake…) |

### Défauts connus et taux observés (196 annotations)

| Défaut | Cas | Cause | Fix |
|---|---|---|---|
| `2_objets` | 16/196 (8%) | Modèle génère second sujet → réduit par NEGATIVE_V3 + _ISOLATION | Déjà appliqué |
| `3_jambes` | 12/196 (6%) | Pose dynamique humaine/animale → cfg=1.0 + negative anatomy | Limiter poses risquées |
| `prompt_incohérent` | 8/196 (4%) | Sujet difficile (cartoon sport, personnalité) | LEAF_OVERRIDES ou downgrade confidence |
| `traits_flous` | 4/196 (2%) | Résolution trop élevée pour sujet simple | Passer à 768×768 |

### QC vision (P3 — abandonné pour anatomie)

`qwen3.5:9b` et `gemma4:26b` testés sur détection `3_jambes` en line-art N&B : **0% recall** sur 5 variantes de prompt. La détection automatique d'anomalies anatomiques en coloriage N&B est impossible avec les LLM vision actuels. QC anatomie = **validation humaine uniquement**.

## Reporting convention (mandatory)

Every significant output the user must consult goes into `docs/reports/` **before ending the response**, without waiting to be asked. One report = one dated file = immutable (never overwrite).

**Le fichier est le livrable principal. Le chat est un résumé optionnel.**

**Déclencheurs — créer un rapport dans TOUS ces cas :**
- Un POC ou script de test a tourné (résultats + verdict)
- Une phase ou étape du plan est complétée (ce qui a été fait, fichiers touchés, critères de sortie)
- `pytest` a été exécuté (nb passed/failed, régressions éventuelles)
- Une migration Alembic a été appliquée (état schéma avant/après)
- Une analyse ou un arbitrage a été produit (options, recommandation, décision attendue)
- Un blocage ou une découverte inattendue survient en cours d'implémentation

**Naming**:
- POC : `YYYY-MM-DD_poc-<name>.md` + `YYYY-MM-DD_poc-<name>.json` (raw data, `ensure_ascii=False`)
- Phase complétée : `YYYY-MM-DD_phase-<N>-<name>.md`
- Tests : `YYYY-MM-DD_tests-<name>.md`
- Migration : `YYYY-MM-DD_migration-<name>.md`
- Analyse / arbitrage : `YYYY-MM-DD_analyse-<name>.md`

**Structure minimale** :
```markdown
# [Type] — [Nom]
Date : YYYY-MM-DD

## Contexte
(1-2 phrases)

## Résultats
(tableau ou liste)

## Points d'attention
(ce qui mérite arbitrage ou vérification)

## Décision / Action suivante
(verdict clair ou question posée)
```

**En cas de doute : écrire le rapport.**

## Things that are easy to get wrong

- "I'll just run a worker" — workers won't pick up jobs unless the matching `job_type_config.enabled = true`. Toggle via `PUT /api/jobs/types/{type}` or the Jobs editor.
- "Tests are failing because of Postgres" — they shouldn't touch Postgres. `tests/conftest.py` forces `DATABASE_URL=sqlite+pysqlite:///:memory:`. If you see Postgres connection errors in tests, something imported a module that opens the engine before conftest ran.
- "I'll launch a second `start.py`" — it exits immediately due to a file lock at `<ARTISTE_LOG_DIR>/start.lock`. Stop the first one first.
- The `data/artiste_coloriage.duckdb` file is checked in but is **not** the runtime database. Don't write code that reads from it for production paths.
