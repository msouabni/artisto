# Phase — Modèle `subject` (table + endpoints CRUD)
Date : 2026-05-10

## Contexte
Brief `docs/architect/briefs/2026-05-10_brief-modele-subject.md` — introduire un sous-objet éditorial `subject` rattaché à un `term` taxonomique pour matérialiser des sujets concrets (ex. term `lion` → subjects "lion mâle adulte sur rocher", "lionceau jouant"). Livraison : migration Alembic + modèle SQLAlchemy + 5 endpoints CRUD avec Pydantic strict + suite de tests.

## Migration

### Fichier
`alembic/versions/0007_subject_table.py` (rev `0007_subject_table` ← `0006_annotation_polymorphic`).

### Schéma `subject`

| Colonne            | Type Postgres | Nullable | Notes |
|--------------------|---------------|----------|-------|
| `id`               | TEXT          | NO (PK)  | UUID4 généré côté API si non fourni |
| `term_id`          | TEXT          | NO       | FK composite vers `term` |
| `vocabulary_id`    | TEXT          | NO       | FK composite vers `term` |
| `name`             | TEXT          | NO       | unique par `term_id` |
| `status`           | TEXT          | NO       | défaut `'draft'`, CHECK whitelist |
| `note`             | INTEGER       | YES      | CHECK `note IS NULL OR (note BETWEEN 0 AND 6)` |
| `tags`             | JSONB         | YES      | liste de tags whitelisted (validation API) |
| `brief`            | TEXT          | YES      | description éditoriale libre |
| `subject_metadata` | JSONB         | YES      | bloc libre (renommé pour éviter collision `Base.metadata`) |
| `created_at`       | TEXT          | NO       | ISO8601 UTC |
| `updated_at`       | TEXT          | NO       | ISO8601 UTC |

Contraintes :
- `subject_pkey` (PK sur `id`)
- `uq_subject_term_name` (UNIQUE `term_id, name`)
- `fk_subject_term` (FK composite `(term_id, vocabulary_id) → (term.id, term.vocabulary_id)`, `ON DELETE CASCADE`)
- `ck_subject_note_range` (CHECK 0..6)
- `ck_subject_status_whitelist` (CHECK `status IN ('draft','annotated','validated','enriched','prompted','generated','qc_done','published','rejected')`)

Index :
- `idx_subject_term` sur `(term_id, vocabulary_id)`
- `idx_subject_status` sur `status`
- `idx_subject_updated` sur `updated_at`

### Validation Postgres réelle

```bash
$ alembic upgrade head      # 0006 → 0007 OK
$ alembic downgrade -1      # 0007 → 0006 OK (table absente)
$ alembic upgrade head      # re-up OK
```

Tests live des CHECK constraints sur la base réelle (psycopg) :
- `INSERT … note=99` → `IntegrityError` (CHECK `ck_subject_note_range`) ✓
- `INSERT … status='wrong-status'` → `IntegrityError` (CHECK `ck_subject_status_whitelist`) ✓
- `INSERT … note=3, tags='["creatif"]'::jsonb, subject_metadata='{"k":1}'::jsonb` → roundtrip OK, JSONB natif ✓

## Modèle

### Fichier
`src/api/models.py` (ajout classe `Subject` + relation `Term.subjects`).

### Décisions techniques

1. **Colonne SQL `subject_metadata` (pas `metadata`)** : le nom Python `metadata` est réservé par `Base.metadata` (registre SQLAlchemy). Utiliser une colonne SQL à un autre nom évite la stack-trace de conflit. L'API expose le champ comme `metadata` côté JSON pour rester naturel pour le client (mapping fait dans `_row_to_dict` / payloads Pydantic).

2. **`sa.JSON` côté modèle, `JSONB` côté migration** : pattern déjà appliqué pour `Term.node_metadata` et `Annotation.image_tags`. Permet aux tests SQLite (qui passent par `Base.metadata.create_all`) de fonctionner sans driver JSONB.

3. **CheckConstraint définis côté modèle ET migration** : double barrière. SQLite enforce les CHECK depuis 3.3 → les tests in-memory rejettent aussi les valeurs invalides au cas où Pydantic serait court-circuité. La whitelist Pydantic reste la première ligne (renvoie 422 propre).

4. **FK composite `(term_id, vocabulary_id)` avec `ondelete="CASCADE"` + `relationship(back_populates, cascade="all, delete-orphan", passive_deletes=True)`** : delete d'un term cascade les subjects côté Postgres (FK SQL) ; côté ORM tests SQLite (où FK est désactivé par défaut), `cascade="all, delete-orphan"` gère via la session.

## Endpoints

### Fichier
`src/api/routes/subjects.py` — router `/api/subjects` monté dans `src/api/main.py`.

| Méthode | Route                       | Description |
|---------|-----------------------------|-------------|
| GET     | `/api/subjects`             | Liste filtrable (`term_id`, `vocabulary_id`, `status`) + pagination (`limit` ≤ 500, `offset`) |
| GET     | `/api/subjects/{id}`        | Détail (404 si absent) |
| POST    | `/api/subjects`             | Création (201 ; 404 si term absent ; 409 si `(term_id, name)` ou `id` dupliqué ; 422 sur validation) |
| PUT     | `/api/subjects/{id}`        | Update partiel (200 ; 404 si absent ; 409 si rename collision ; 422 sur validation) |
| DELETE  | `/api/subjects/{id}`        | Suppression (200 + `{deleted: true, id}` ; 404 si absent) |

### Validation Pydantic

- `SubjectCreate` : `term_id` + `vocabulary_id` + `name` requis ; `name` strip + non vide ; `status` whitelist ; `note ∈ [0,6]` ou null ; `tags ⊂ ALLOWED_TAGS`.
- `SubjectUpdate` : tous champs optionnels ; mêmes contraintes quand présents ; `note: null` = reset explicite (sentinel via `model_fields_set`).
- `term_id` / `vocabulary_id` immutables (un subject ne se reparente pas — créer un nouveau).

### Whitelists (frozenset, source unique côté API)

```python
ALLOWED_TAGS = {"ambigu", "simpliste", "incomprehensible", "creatif",
                "parfait", "complique", "bug", "blacklist"}
ALLOWED_STATUSES = {"draft", "annotated", "validated", "enriched",
                    "prompted", "generated", "qc_done", "published", "rejected"}
```

Test miroir `test_whitelist_constants_match_brief` casse si quelqu'un édite ces sets sans synchroniser brief + migration.

### NULL-safe (CLAUDE.md)
- `_row_to_dict` : `int(note_raw) if note_raw is not None else None`
- `tags` : décodage JSON cross-dialect (`_decode_json_field`) puis fallback `[]`
- `metadata` : décodage similaire, fallback `None`

## Tests

### Fichier
`tests/test_subjects_api.py` — **25 tests** (≥ 15 demandés).

### Couverture

| Catégorie             | Tests | Cas couverts |
|-----------------------|-------|--------------|
| GET liste             | 4     | empty, filtres `term_id`/`status`, status invalide → 400, pagination |
| GET détail            | 2     | 404, payload complet (NULL-safe note/tags/metadata) |
| POST création         | 9     | minimal id auto, id explicite, 404 term absent, 409 dup `(term_id,name)`, 409 dup id, 422 name vide, 422 status, 422 note out-of-range, 422 tag inconnu, all tags accepted |
| Whitelists            | 1     | constantes match brief (frozenset exacts) |
| PUT update            | 4     | 404, partiel sans écraser, 409 rename collision, 422 tag inconnu, reset note=null |
| DELETE                | 2     | 404, 200 + GET 404 ensuite |
| Relation ORM          | 1     | `Term.subjects` navigable + types |

### Exécution

```
$ python -m pytest tests/test_subjects_api.py -x
============================= 25 passed in 1.22s ==============================
```

Suite globale (hors `test_content_generator.py` qui était déjà cassée à l'arrivée par un import manquant `HARAKAT_RE`) :
```
5 failed, 213 passed in 3.28s
```

Les 5 échecs sont les régressions préexistantes annoncées dans le brief :
- `test_workflow_template_sidecar.py::test_ernie_uses_sidecar_from_repo`
- `test_create_image_job_workflow.py::test_create_job_default_safe_workflow_ignores_negative_prompt_from_image`
- `test_create_image_job_workflow.py::test_create_job_preflight_removes_unsupported_negative_for_ernie`
- `test_bulk_generation_jobs.py::TestBulkCreateGenerationJobs::test_dedup_and_partial_success`
- `test_bulk_generation_jobs.py::TestBulkCreateGenerationJobs::test_bulk_preflight_removes_unsupported_negative_for_ernie`

Tous liés au sidecar `ernie-image-turbo-q8-api` et au support `negative_prompt` (capability `optional` vs `unsupported`). Sans rapport avec `subject`.

## Points d'attention

1. **`test_content_generator.py` cassé à l'arrivée** (avant intervention) : `ImportError: cannot import name 'HARAKAT_RE' from 'services.ollama_json'`. Hors périmètre du brief subject — à mentionner dans la prochaine revue de l'architecte. Le test a été ignoré pour valider le reste de la suite (j'ai utilisé `--ignore=tests/test_content_generator.py`).

2. **Naming `subject_metadata` côté SQL vs `metadata` côté JSON** : convention pragmatique pour éviter le conflit `Base.metadata`. Documenté dans le docstring du modèle. Si dans un futur brief on ajoute un `MetadataMixin` partagé, harmoniser ici aussi.

3. **Status `draft` est défaut SQL ET Pydantic** : double-source, mais cohérent. Si le brief évolue, modifier les deux + migration.

4. **Pas d'éditeur HTML livré** : la convention CLAUDE.md "always create an editor for any YAML/JSON deliverable" cible les YAML/JSON config, pas une table SQL CRUD comme `subject`. Les UIs existantes (`taxonomy_editor`, `images_editor`) suivent ce pattern. Si un editor HTML pour `subject` est attendu, c'est un brief séparé (UX dédiée).

5. **Pas de seed `job_type_config` ajouté** : aucun job type lié à subject n'est introduit dans ce brief. À ouvrir dans un brief ultérieur si on veut un worker `subject_enrich` etc.

## Décision / Action suivante

**Livraison conforme au brief.** Migration appliquée+revertable côté Postgres réel, 25 tests verts, suite globale verte hors les 5 échecs préexistants. Pas de commit ni de push (l'architecte revoit avant de commit).

Files touchés (whitelist stricte respectée) :
- `alembic/versions/0007_subject_table.py` (nouveau)
- `src/api/models.py` (classe `Subject` + relation `Term.subjects`, imports élargis)
- `src/api/routes/subjects.py` (nouveau)
- `src/api/main.py` (import + `include_router` + entrée racine)
- `tests/test_subjects_api.py` (nouveau, 25 tests)
- `docs/reports/2026-05-10_modele-subject.md` (ce rapport)
