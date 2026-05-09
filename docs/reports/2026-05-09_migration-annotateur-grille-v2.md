# Migration — Annotateur grille v2
Date : 2026-05-09

## Contexte
Migration des ``annotations.json`` v1 (defects/notes/score 1-10) vers le schéma v2 (image_tags / prompt_tags / custom_tags / flags / score 1-6). Cf. brief `2026-05-09_brief-annotateur-v2.md`.

## Résultats

- Mode : **APPLY (écriture)**
- Fichiers traités : **9**
- Annotations totales : **539**
- Déjà en v2 (idempotent) : 0
- Migrées v1 → v2 : **539**
- Anomalies relevées : 0

### Détail par fichier

| Fichier | Total | v2 | Migrées | Anomalies | Écrit |
|---|---:|---:|---:|---:|:---:|
| `docs\reports\poc-batch-size\annotations.json` | 40 | 0 | 40 | 0 | ✅ |
| `docs\reports\poc-generator-benchmark\annotations.json` | 27 | 0 | 27 | 0 | ✅ |
| `docs\reports\poc-sampler-benchmark\annotations.json` | 24 | 0 | 24 | 0 | ✅ |
| `docs\reports\poc-sampler-benchmark-v2\annotations.json` | 75 | 0 | 75 | 0 | ✅ |
| `docs\reports\poc-sampler-benchmark-v3\annotations.json` | 31 | 0 | 31 | 0 | ✅ |
| `docs\reports\poc-scale-benchmark\annotations.json` | 213 | 0 | 213 | 0 | ✅ |
| `docs\reports\poc-seed-variance\annotations.json` | 30 | 0 | 30 | 0 | ✅ |
| `docs\reports\poc-soccer-karras\annotations.json` | 10 | 0 | 10 | 0 | ✅ |
| `docs\reports\poc-taxonomy-subjects\annotations.json` | 89 | 0 | 89 | 0 | ✅ |

## Points d'attention

- Aucune anomalie détectée — toutes les valeurs v1 sont mappables.

## Décision / Action suivante

- Migration appliquée. Vérifier 1 ou 2 fichiers à la main puis supprimer les ``.bak`` quand tout est OK.
