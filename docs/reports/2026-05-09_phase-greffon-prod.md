# Phase — Greffon prod (P4)

Date : 2026-05-09
Brief : `docs/architect/briefs/2026-05-09_brief-greffon-prod.md`
Use case : `REVIEW_PROD_ANNOTATE`

## Contexte

Greffe l'annotateur v2 (livré P3, déjà actif sur les benchmarks disque) sur les `image_output` produits par la pipeline production, via une table polymorphe `annotation` et 3 endpoints REST. Aucune modification des routes `/api/jobs/*` (apply/reject reste dans `jobs_editor.html`).

## Résultats

### Fichiers touchés

| Fichier | Statut | LOC ajoutées (≈) |
|---|---|---|
| `alembic/versions/0006_annotation_polymorphic.py` | NEW | 81 |
| `src/api/annotation_vocab.py` | NEW (refactor partagé) | 51 |
| `src/api/routes/review.py` | NEW | 538 |
| `tests/test_review_routes.py` | NEW | 462 |
| `src/api/models.py` | MOD (+ class Annotation) | +39 |
| `src/api/routes/benchmark.py` | MOD (purge sets locaux → import partagé) | -42 / +13 |
| `src/api/main.py` | MOD (1 import + 1 mount) | +2 |
| `data/benchmark-annotator.html` | MOD (mode switch + badge PROD + branchement endpoints) | +277 / -23 |
| `docs/workflow-pipeline.md` | MOD (section greffon prod) | +48 |
| `docs/use-cases/use_cases.yaml` | MOD (REVIEW_PROD_ANNOTATE) | +31 |

Total ajouté : ~1130 LOC nouvelles (dont 462 de tests). Bench / jobs existants : zéro modification de comportement.

### Critères d'acceptation (10/10 cochés)

- [x] Migration `0006_annotation_polymorphic` appliquée Postgres + tests in-memory SQLite verts
- [x] `GET /api/review/queue` retourne les `image_output` joints à leur annotation éventuelle
- [x] `GET /api/review/file` sert correctement les fichiers + refuse path traversal + 404 sur id absent
- [x] `POST /api/annotation` upsert OK + validation tags/score + refus `target_type` hors whitelist + 404 sur target_id absent
- [x] UI mode switch fonctionnel (URL + persistance localStorage `benchmarkAnnotatorMode`)
- [x] Badge "PROD" orange visible en mode prod (avec sous-titre image_id + job_id)
- [x] Grille P3, raccourcis P2, lightbox P1 identiques dans les 2 modes (un seul code de rendu, branchement par mode dans `loadItems()` / `saveCurrent()` / `imageUrlFor()`)
- [x] Aucune route `/api/jobs/*` modifiée
- [x] Aucun test cassé — `test_job_review_flow.py` (10 tests) + `test_job_review_image_endpoint.py` (8 tests) verts
- [x] Tests `test_review_routes.py` (21 tests) couvrent : queue empty, queue avec annotation jointe, filtres status/workflow_class, status invalide 400, file 404 (id inconnu / path vide / path hors DATA_DIR) + 200 sur cas valide, annotate upsert nouveau / existant sans doublon, validation 400 (score, image_tag, prompt_tag, target_type) + 404 (target_id), pattern_note vidé si pattern=False, cohérence 18/8 + identité d'objet vocab partagé

### Tests pytest

```
tests/test_review_routes.py                 21 passed
tests/test_benchmark_routes.py              24 passed (zéro régression après refactor vocab)
tests/test_job_review_flow.py               10 passed
tests/test_job_review_image_endpoint.py      8 passed
─────────────────────────────────────────────────────
Total                                       63 passed in 1.00s
```

Suite complète (`pytest --ignore=tests/test_content_generator.py`) : 185 passed, 5 failed. Les 5 échecs sont **pré-existants** (vérifiés via `git stash` : `test_bulk_generation_jobs.py`, `test_create_image_job_workflow.py`, `test_workflow_template_sidecar.py` échouent avant nos changements — problème ERNIE/negative_prompt orthogonal au greffon). `tests/test_content_generator.py` est aussi cassé en collection (import `HARAKAT_RE` manquant) — pré-existant également.

### Refactor vocabulaires partagés

**Avant** : `IMAGE_TAGS_VOCAB` et `PROMPT_TAGS_VOCAB` définis localement dans `src/api/routes/benchmark.py`.

**Après** : extraits dans `src/api/annotation_vocab.py` (`frozenset[str]`, 18 + 8). Importés par `benchmark.py` ET `review.py`. Le test `test_benchmark_routes.test_vocabularies_match_brief_count` continue de passer (il fait `from api.routes.benchmark import IMAGE_TAGS_VOCAB`, qui est désormais le re-export du module partagé). Test miroir ajouté dans `test_review_routes.py` + `test_vocab_module_is_single_source_of_truth` qui vérifie l'**identité d'objet** Python (`is`) entre les 3 sites.

### Migration Alembic

Postgres dispo (Docker `artiste-postgres`). Vérifié :

```
$ alembic current   → 0005_term_metadata_jsonb
$ alembic upgrade head
INFO  Running upgrade 0005_term_metadata_jsonb -> 0006_annotation_polymorphic, create annotation table (polymorphic)

$ \d annotation
- 13 colonnes (id INTEGER PK auto, target_type/target_id TEXT NOT NULL,
  score INTEGER, image_tags/prompt_tags/custom_tags JSONB,
  pattern/sample/publishable BOOLEAN DEFAULT FALSE, pattern_note TEXT,
  created_at/updated_at TEXT NOT NULL)
- 4 indexes : pkey, idx_annotation_target, idx_annotation_updated, uq_annotation_target UNIQUE
```

Côté SQLite (tests) : `Base.metadata.create_all` produit la même structure via `sqlalchemy.JSON` cross-dialect. Conftest n'exécute jamais la migration — il reconstruit depuis le modèle.

## Points d'attention

1. **Sérialisation JSON cross-dialect** : les colonnes `image_tags` / `prompt_tags` / `custom_tags` sont sérialisées explicitement en `json.dumps(...)` côté insert/update via `DBConnAdapter` (qui utilise `text()` brut + binding nommé). Postgres accepte le TEXT pour une colonne JSONB (cast implicite côté driver psycopg) ; SQLite stocke comme TEXT. Le décodage côté `GET /api/review/queue` passe par `_decode_json_field()` qui gère str → `json.loads`, dict/list → tel quel. **Aucun opérateur JSONB Postgres-only** n'est utilisé. Conforme à CLAUDE.md.

2. **Filtre `workflow_class` best-effort** : pas de colonne dédiée sur `image_output` ni `job` ; on fait un `LIKE %workflow_class%` sur `job.config` (JSON sérialisé). Documenté dans le code comme "best-effort, laxiste par design". À promouvoir vers une vraie colonne dénormalisée (`image_output.workflow_class` ou `job.workflow_class`) si le filtre devient critique en volume — non bloquant pour P4.

3. **`NULLS LAST` non supporté SQLite** : `ORDER BY io.created_at DESC NULLS LAST` est tenté en premier puis fallback sans `NULLS LAST` si le driver refuse. Fonctionne côté Postgres ET SQLite (couvert par `test_queue_basic_join`).

4. **Whitelist `target_type` initiale = `{'image_output'}`** : la table le permet pour `image`, `term`, `job` etc. mais l'API refuse 400 avant tout lookup DB. Toute extension future = revue explicite (nouveau lookup d'existence + adaptateur UI éventuel). Le test `test_annotate_unknown_target_type_400` verrouille le comportement.

5. **Lookup d'existence `target_id` pour `image_output`** : un simple `SELECT 1 FROM image_output WHERE id=?`. Si `target_type` s'étend à `image` ou `term`, ajouter un dispatch (probablement un dict `target_type → table_name` ou des branches if/elif claires).

6. **Annotation conservée après apply/reject** : la table `annotation` n'a pas de FK vers `image_output` ; un apply qui change `image.status` ne touche pas l'annotation. C'est volontaire (trace audit). Si on devait nettoyer après reject définitif, ce serait un job de housekeeping séparé.

7. **UI : préférence localStorage non écrasée par URL** : si l'utilisateur ouvre `?mode=production`, on applique le mode prod et on persiste comme nouvelle préférence. Si on voulait un comportement non-persistant pour les liens partagés, il faudrait passer `skipPersist: true` dans `setMode` au boot — choix laissé tel quel (cohérent avec le pattern theme déjà en place) mais à arbitrer par l'archi si retour utilisateur.

8. **Sub-filename `image_id` + `job_id` + statuses** : affiché systématiquement en mode prod sous le filename. C'est davantage que demandé dans le brief (qui parle de "sous-titre image_id + job_id") — j'ai ajouté `image_status` et `job_status` car ils tiennent en une ligne et donnent du contexte utile. Réversible si l'archi préfère un affichage plus minimal.

9. **`save-status.error` reste affiché en cas d'échec d'upsert** : cohérent avec le mode benchmark. Les 400/404 du serveur sont remontés tels quels dans le badge (texte tronqué à 100 chars).

## Décision / Action suivante

P4 livré, les 10 critères d'acceptation sont cochés, zéro régression sur les 4 suites de tests cibles (63 passed). Le greffon est prêt pour mise en main archi/utilisateur :

- [Action archi] Review du diff puis arbitrer 3 points soft :
  - Volume d'info dans le sub-filename prod (4 champs vs 2 demandés)
  - Comportement localStorage sur mode initial via URL (écrase la pref ou non)
  - Filtre `workflow_class` LIKE → faut-il dénormaliser ?
- [Action user] Tester l'UI : `?mode=production`, vérifier le toggle, le badge PROD, la sauvegarde polymorphe.
- [Hors scope cette phase] Migration `data/<dir>/annotations.json` benchmark → table polymorphe (`target_type='benchmark_file'`) — non prioritaire (statu quo OK).

Pas de commit fait — la review architecte précède.
