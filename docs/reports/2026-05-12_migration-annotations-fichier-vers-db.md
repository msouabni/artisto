# Migration annotations fichier → DB polymorphe
Date : 2026-05-12

## Contexte

Migration de toutes les annotations stockées sur disque
(``docs/reports/poc-*/annotations.json``) vers la table polymorphe
``annotation`` (``target_type='benchmark_file'``,
``target_id='{dir}/{filename}'``). Prépare Brief C3 (export depuis DB).

Brief : ``docs/architect/briefs/2026-05-12_brief-mep-v0-C1-migration-annotations-db.md``.

## Résultats

- Mode : **APPLY (UPSERT en DB Postgres)**
- Fichiers parcourus : **13**
- Entrées totales : **1014**
- INSERT (nouveaux, premier run) : **1014**
- UPDATE (rerun idempotent confirmé) : **1014**
- Anomalies (non bloquantes) : **0**
- Tags inconnus rencontrés : **0** (toutes les annotations sont conformes
  aux vocabulaires fermés v2 ``IMAGE_TAGS_VOCAB`` / ``PROMPT_TAGS_VOCAB``).
- Scores hors plage [1, 6] rencontrés : **0**.

### Détail par dir (premier run, INSERT)

| Dir | Total | INSERT | UPDATE | Anomalies |
|---|---:|---:|---:|---:|
| `poc-batch-size` | 40 | 40 | 0 | 0 |
| `poc-bench-T25-postPivot` | 20 | 20 | 0 | 0 |
| `poc-bench-gate-ernie-T25` | 18 | 18 | 0 | 0 |
| `poc-bench-gate-ernie-T2T3T23` | 10 | 10 | 0 | 0 |
| `poc-bench-gate-ernie-pivot` | 10 | 10 | 0 | 0 |
| `poc-generator-benchmark` | 27 | 27 | 0 | 0 |
| `poc-sampler-benchmark` | 24 | 24 | 0 | 0 |
| `poc-sampler-benchmark-v2` | 75 | 75 | 0 | 0 |
| `poc-sampler-benchmark-v3` | 31 | 31 | 0 | 0 |
| `poc-scale-benchmark` | 515 | 515 | 0 | 0 |
| `poc-seed-variance` | 30 | 30 | 0 | 0 |
| `poc-soccer-karras` | 10 | 10 | 0 | 0 |
| `poc-taxonomy-subjects` | 204 | 204 | 0 | 0 |
| **TOTAL** | **1014** | **1014** | **0** | **0** |

### Idempotence (second run consécutif)

Stats observées en relançant immédiatement le script :

- INSERT : **0**
- UPDATE : **1014**
- Anomalies : **0**
- ``COUNT(DISTINCT target_id)`` après second run : **1014** (pas un doublon).

Le pattern UPSERT cross-dialect (SELECT puis branche INSERT/UPDATE) est
portable SQLite (tests) et Postgres (prod) — aucun opérateur JSONB ou
``ON CONFLICT`` Postgres-only n'est utilisé.

### État DB après migration

- ``SELECT COUNT(*) FROM annotation WHERE target_type='benchmark_file'`` :
  **1014**
- ``SELECT COUNT(*) FROM annotation WHERE publishable = TRUE`` : **582**

Ces 582 entrées ``publishable=true`` constituent le corpus consommable
par Brief C3 (export MEP v0).

## Tests

- 12 tests dans ``tests/test_migrate_annotations_to_db.py`` (objectif brief :
  ≥ 5 dont 3 schémas index — atteint avec 7 cas fonctionnels + 5 cas
  schéma / helpers).
- Couverture :
  1. Entrée nouvelle → INSERT propre
  2. Entrée existante → UPDATE sans doublon
  3. Tag inconnu → anomalie consignée, non bloquant
  4. Score hors plage → anomalie consignée, non bloquant
  5. Schéma index ``subjects-index.json`` → pas d'impact
  6. Schéma index ``index-by-leaf.json`` (results-by-leaf-id) → pas d'impact
  7. Schéma index ``<dir>/<dir>.json`` (results-legacy) → pas d'impact
  8. Idempotence globale (rerun = 0 doublon)
  9. ``--dry-run`` → aucune écriture DB
  10. ``find_annotation_files`` filtre fnmatch (3 sous-cas)
  11. ``parse_entry`` non-dict → skip
  12. ``parse_entry`` flags manquants → défauts safe
- Suite globale ``pytest --ignore=tests/test_content_generator.py`` : **523
  passed** (aucune régression).

## Points d'attention

- **Aucune anomalie** rencontrée sur le corpus actuel — les vocabulaires
  fermés v2 sont respectés à 100 % côté fichiers (suite à la migration
  v1 → v2 livrée par ``migrate_benchmark_annotations.py`` 2026-05-09).
- **Trois schémas d'index POC supportés en lecture** (subjects,
  results-by-leaf-id, results-legacy) : sans impact sur cette migration
  car le fichier ``annotations.json`` est uniforme (dict
  ``annotations`` keyed par filename, schéma v2). La variété d'index
  POC est consommée par ``src/api/routes/benchmark.py`` indépendamment.
- **Les fichiers ``annotations.json`` ne sont pas modifiés** (legacy
  préservé pour le mode benchmark sur disque) — décommission planifiée
  dans un brief séparé post-MEP v0.
- **``target_id`` polymorphe** : la convention ``f'{dir}/{filename}'``
  garantit unicité entre dirs. Si deux POCs nomment leurs fichiers de la
  même manière (cas observé pour ``soccer_*.png``), ils sont distincts
  via leur préfixe dir.
- **Backfill prod** : les annotations existantes
  (``target_type='image_output'``) ne sont **pas** touchées par cette
  migration — elles vivent en parallèle dans la même table.

## Décision / Action suivante

- ✅ Brief C3 (export) peut maintenant filtrer ``publishable=true``
  depuis la table ``annotation`` (1014 lignes ``benchmark_file`` dont
  582 publishable) au lieu de relire 13 fichiers JSON.
- ✅ Un rerun de ce script est idempotent (UPDATE pur, 0 doublon).
- ➡️ Prochain brief logique : Brief C2 (slug utils) puis Brief C3
  (export MEP v0 sur corpus DB).
- 📌 Décommission des fichiers ``annotations.json`` : à planifier dans
  un brief séparé post-MEP v0 — ne pas supprimer tant que
  ``src/api/routes/benchmark.py`` n'a pas été basculé en lecture DB.
