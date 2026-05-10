# Phase — Import subjects v0 (skill) — script + tests

Date : 2026-05-10

## Contexte

Brief V1.3 (`docs/architect/briefs/2026-05-10_brief-import-subjects-v0-skill.md`) :
fournir un script idempotent qui parcourt la taxonomie de référence
(`data/prompt_generator/coloring_taxonomy_full.json`, 1376 leaves) et insère
un `subject` par leaf dans la table `subject` créée par V1.2.

Travail réalisé en isolation (worktree) **avant** le merge de V1.2 — pas de run
réel en BD ; les tests s'appuient sur SQLite in-memory + injection d'un modèle
`Subject` minimal compatible avec le schéma V1.2 documenté dans
`docs/architect/briefs/2026-05-10_brief-modele-subject.md`.

## Livrables

| Fichier | Statut |
|---|---|
| `scripts/import_subjects_v0_from_skill.py` | **créé** (CLI argparse, dry-run, limit, source override, rapport JSON + MD) |
| `tests/test_import_subjects_v0.py` | **créé** (17 tests verts) |
| `docs/reports/2026-05-10_import-subjects-v0-skill.md` | **ce rapport** |

Aucun autre fichier touché. Pas de commit, pas de push (per brief).

## Architecture script

- **Source** : `data/prompt_generator/coloring_taxonomy_full.json` (canonique, 1376 leaves vérifiés). Le `.skill` packagé est ignoré (dérivé non structuré).
- **Aplatissement** : `flatten_leaves()` produit `[{leaf_id, name_en, name_fr, name_ar, root, path}]` pour chaque feuille (noeud sans `children`).
- **Insertion** : pour chaque leaf, vérifie `term_id` en BD puis `subject(term_id, source)` ; insère sinon.
- **Convention id** : `f"sub_{leaf_id}"` — stable, traçable, lisible humainement.
- **Champs subject** :
  - `source = "skill_v0"` (override par CLI `--source`)
  - `tags = []`
  - `note = NULL`
  - `status = "draft"`
  - `enrichment = NULL`
  - `prompt_positive = NULL`
  - `metadata_` = `{imported_from, import_run, root, path}`
- **NULL-safe** : tri par `leaf_id or ""` (paranoïa CLAUDE.md).
- **Persistance** : `Session` SQLAlchemy direct (pas via API) — `commit()` en fin de run hors `--dry-run`.
- **`session.flush()`** après chaque add pour détecter tôt les violations d'unicité.

### CLI

```bash
python scripts/import_subjects_v0_from_skill.py --dry-run
python scripts/import_subjects_v0_from_skill.py --limit 10
python scripts/import_subjects_v0_from_skill.py --source skill_v0 --rapport-dir data/import
python scripts/import_subjects_v0_from_skill.py --no-md            # CI sans markdown
python scripts/import_subjects_v0_from_skill.py --taxonomy-path X  # override source JSON
```

## Tests — 17 verts

```
TestFlattenLeaves                                  [4 tests]
  test_flatten_returns_only_leaves                 PASSED
  test_flatten_attaches_root                       PASSED
  test_flatten_path_is_full                        PASSED
  test_flatten_canonical_taxonomy_count            PASSED   # 1376 leaves OK
TestImportSubjects                                 [8 tests]
  test_smoke_inserts_subjects_for_known_terms      PASSED   # smoke sur 3 leaves
  test_idempotence_second_run_inserts_nothing      PASSED   # ★ idempotence
  test_dry_run_does_not_write                      PASSED   # ★ dry-run safe
  test_orphan_leaves_listed_without_fatal_error    PASSED   # orphelins gérés
  test_inserted_subject_has_expected_schema        PASSED   # tags=[], status=draft, source=skill_v0
  test_limit_caps_inserts                          PASSED   # ★ --limit
  test_custom_source_override                      PASSED   # ★ --source override
  test_per_root_distribution                       PASSED   # distribution OK
TestReporting                                      [4 tests]
  test_json_report_written                         PASSED
  test_markdown_report_renders_sections            PASSED
  test_markdown_report_dry_run_decision            PASSED
  test_markdown_report_idempotent_decision         PASSED
TestNullSafeSorting                                [1 test]
  test_sort_key_handles_empty_leaf_id              PASSED   # CLAUDE.md NULL-safe
```

Critère brief « ≥ 5 nouveaux tests » : **largement dépassé** (17).

## Sample run sur taxonomie canonique (simulation in-memory)

Reproduction d'un run réel : SQLite in-memory + injection `Subject` + seed des 1376 terms (équivalent post-V1.2 + seed `term`).

### Compteurs

| Mesure | Valeur |
|---|---|
| Total leaves taxonomie | 1376 |
| Subjects insérés (run 1) | 1376 |
| Subjects déjà présents (run 2 — idempotence) | 1376 |
| Subjects insérés (run 2) | **0** |
| Leaves orphelins | 0 (avec seed `term` complet) |

### Distribution par root (run 1 — 1376 inserts)

| Root | Subjects insérés |
|---|---|
| animals | 136 |
| alphabet_and_visual_language | 129 |
| fictional_characters | 114 |
| professions | 108 |
| vehicles_and_machines | 88 |
| sports_and_physical_activities | 86 |
| human_body_and_health | 74 |
| festivals_and_celebrations | 73 |
| tools_and_tooling | 70 |
| nature_and_environment | 66 |
| geometry_and_math | 64 |
| sports_personalities | 64 |
| daily_life_and_environments | 59 |
| household_appliances | 57 |
| fantasy_magic_and_tales | 55 |
| modern_themes_and_trends | 51 |
| sciences_and_technology | 43 |
| art_creativity_and_decorative_patterns | 39 |
| **Total** | **1376** |

### Échantillon (10 premiers triés par leaf_id)

| id | term_id | name |
|---|---|---|
| `sub_3d_modeler` | `3d_modeler` | (3D Modeler — chargé depuis `name_en`) |
| `sub_3d_print_designer` | `3d_print_designer` | (idem) |
| `sub_3d_printer` | `3d_printer` | (idem) |
| ... | ... | ... |

(le tri d'import est par `leaf_id` ASC pour reproductibilité — ne change pas
la sémantique mais rend les runs comparables)

## Liste orphelins

**0 orphelin** dans la simulation post-seed `term`. En cas de seed partiel,
le rapport généré liste chaque `leaf_id` orphelin avec sa `root` et la raison
(`no term row`) — utile pour identifier les divergences taxonomie ↔ table `term`.

## Points d'attention

- **Dépendance V1.2** : le script importe `from api.models import Subject`. Tant que V1.2 n'est pas mergé, l'exécution réelle (`SessionLocal()`) lèvera `RuntimeError` clair (« V1.2 doit être mergé avant l'import réel »). Les tests contournent via injection contrôlée.
- **Contrainte unique `(term_id, name)`** (V1.2) : un 2e run avec source différente sur les mêmes leaves échoue à l'INSERT (collision sur `(term_id, name)`). C'est le comportement voulu — un même `(term, name)` ne peut avoir qu'un seul subject. Si on veut deux subjects pour le même term, il faut deux **noms** différents.
- **Convention `sub_{leaf_id}`** : si jamais deux sources insèrent le même leaf, l'`id` aussi entre en collision (PK violée). Le brief V1.3 cible explicitement `skill_v0` comme **source initiale unique** ; les sources futures (`manual`, `llm_brainstorm`) génèreront des subjects pour des `(term, name)` distincts.
- **Pas d'effet sur les 53 leaves ex-frieze** : ils seront importés en `status='draft'` et filtrés en aval (Vague 2 — annotation + tags).
- **Filtrage publication** (318 publishables sur 1376) : **hors scope** de ce script (Vague 2).

## Décision / Action suivante

**Go pour merge** dès que V1.2 (modèle `Subject` + migration `0007`) est mergé.

Séquence d'exécution réelle (à faire par l'archi après merge V1.2 + V1.3) :

```bash
# 1. Vérifier seed term complet (1376 leaves)
python -c "from sqlalchemy import text; from api.db import SessionLocal; s=SessionLocal(); print(s.execute(text('SELECT COUNT(*) FROM term')).scalar())"

# 2. Dry-run
python scripts/import_subjects_v0_from_skill.py --dry-run

# 3. Run réel
python scripts/import_subjects_v0_from_skill.py

# 4. Idempotence (sanity)
python scripts/import_subjects_v0_from_skill.py
# attendu : inserted=0, already_present=1376
```

Le rapport JSON sera dans `data/import/subjects_v0_<timestamp>.json` ;
le rapport Markdown final écrasera ce fichier (par design — vérité instantanée
post-run).

## Fichiers concernés

- `scripts/import_subjects_v0_from_skill.py` (créé, 348 lignes)
- `tests/test_import_subjects_v0.py` (créé, 17 tests)
- `data/prompt_generator/coloring_taxonomy_full.json` (lecture seule, 1376 leaves)
- `docs/architect/briefs/2026-05-10_brief-import-subjects-v0-skill.md` (référence)
- `docs/architect/briefs/2026-05-10_brief-modele-subject.md` (référence schéma V1.2)
