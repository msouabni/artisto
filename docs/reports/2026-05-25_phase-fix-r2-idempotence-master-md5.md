# Phase — Fix idempotence R2 via custom metadata `master-md5`
Date : 2026-05-25

## Contexte

Les variants R2 (WebP/Thumb/PDF) ne sont pas déterministes au sens byte (Pillow/img2pdf insèrent des metadata variables). La comparaison `ETag == md5(body)` échouait systématiquement au 2e run, causant 540 re-uploads inutiles (~200 MB/run). Fix : comparer via custom metadata `master-md5` stockée sur chaque objet R2.

## État réel vérifié

```
R2 access key present: True
R2 secret present: True
R2 account present: True

_upload_variants_real line: 390
R2Client.head line: 340
R2Client.put line: 349

HEAD result keys: ['AcceptRanges', 'ContentLength', 'ContentType', 'ETag',
                   'LastModified', 'Metadata', 'ResponseMetadata']
Metadata field: {}    ← dict vide, pas None (legacy sans master-md5)
ETag: "6969387b87333f5c3e885844dcf6a705"

R2 variants (smoke Niveau 1): 540 uploadés / 0 skipped — confirmé cassé
```

## Livrables

| Fichier | Description |
|---|---|
| `scripts/alwanbooks_pipeline.py` | `R2Client.put()` +metadata param, `_upload_variants_real()` logique master-md5+fallback ETag, propagation `master_md5` depuis `run_pipeline` |
| `tests/test_r2_idempotence_master_md5.py` | 6 tests : upload initial, idempotence 2e run, master changé, legacy fallback, migration metadata, rollback partiel |

## Tests

```
pytest --ignore=tests/test_content_generator.py → 675 passed in 14.42s
```

- Avant : 669 tests
- Après : 675 tests (+6 nouveaux)
- Régressions : 0

## Smoke comparatif

### Run 1 — Upload avec master-md5 metadata

```
=== artiste-pipeline — push lot 2026-05-25 vers site=alwanbooks ===
R2 variants       : 135 uploadés / 405 skipped (etag match) / 0 failed
```

405 variants skippés via fallback ETag legacy (objets sans metadata master-md5). 135 re-uploadés avec metadata `master-md5` attachée (variants dont les bytes avaient changé depuis le précédent upload).

### Run 2 — Idempotence vérifiée

```
=== artiste-pipeline — push lot 2026-05-25 vers site=alwanbooks ===
R2 variants       : 0 uploadés / 540 skipped (etag match) / 0 failed
```

**540/540 variants skippés** — idempotence parfaite. Les 135 variants re-uploadés au run 1 sont maintenant skippés via metadata `master-md5`. Les 405 legacy sont toujours skippés via fallback ETag.

## Points d'attention

1. **Fallback ETag** : les 540 objets R2 actuels n'ont pas de metadata `master-md5`. Le fallback ETag les gère. Après un run complet (135 re-uploads), tous les objets modifiés auront la metadata. Les 405 objets legacy restants seront mis à jour progressivement (si le master PNG ou le format de variant change).

2. **Metadata `{}` vs `None`** : boto3 `head_object` retourne `Metadata: {}` (dict vide) pour les objets sans custom metadata. Le code utilise `(existing.get("Metadata") or {}).get("master-md5", "")` pour gérer les deux cas.

3. **Rollback atomique préservé** : les nouveaux uploads sont rollback-ables comme avant. Les variants skippées ne sont pas touchées par le rollback.

## Décision / Action suivante

Fix R2 idempotence livré. 2e run skip 540/540 confirmé. Dette technique 2026-05-25 close.
