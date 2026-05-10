# Phase — QC auto worker (image_qc_auto)
Date : 2026-05-10

## Contexte

Brief 2026-05-10 — créer un job type `image_qc_auto` + worker dédié qui pose 5
tags QC déterministes (no LLM) sur `image_output.qc_tags` après chaque
génération d'image, en remplacement du QC vision invalidé (verdicts trop
souvent "good" en élargi sur qwen3.5:9b et gemma4:26b — voir
`docs/reports/2026-05-09_*.md`).

## Migration

Migration `0008_image_output_qc_tags.py` (down_revision : `0006_annotation_polymorphic`).

| Aspect | Détail |
|---|---|
| Cible | `image_output` |
| Action | `ADD COLUMN qc_tags JSONB NULL` |
| SQL upgrade | `ALTER TABLE image_output ADD COLUMN qc_tags JSONB;` |
| SQL downgrade | `ALTER TABLE image_output DROP COLUMN qc_tags;` |
| Tests SQLite | OK via `Base.metadata.create_all` (modèle `JSON` cross-dialect) |
| Test offline alembic upgrade | OK (SQL généré conforme, voir vérification `alembic upgrade --sql`) |
| Test offline alembic downgrade | OK |

La migration n'a **pas** été appliquée sur la base partagée prod (refus
auto-mode protégeant l'infra) ; vérification offline via
`alembic upgrade --sql 0006:0008`. À appliquer manuellement par l'archi
au moment du merge :

```bash
DATABASE_URL=postgresql+psycopg://... alembic upgrade head
```

## Worker (`src/workers/qc_worker.py`)

Classe `QCWorker(BaseWorker)`, `job_type = "image_qc_auto"`, `category = "image"`.

### 5 règles déterministes

| Tag | Condition | Seuil | Source mesure |
|---|---|---|---|
| `qc_color_residual` | chrominance pixels > 0.001 | `QC_COLOR_RESIDUAL_THRESHOLD = 0.001` | `(chroma > 0.12 & max(rgb) > 0.12).mean()` (Pillow + NumPy) |
| `qc_color_intrinsic` | leaf_id matche `{rainbow_*, crystal_*, prism_*, spectrum_*, aurora_*}` | n/a | `image.origin_term_id` |
| `qc_low_contrast` | std(intensité) < 30 | `QC_LOW_CONTRAST_STD_THRESHOLD = 30.0` | `np.std(luma_u8)` sur 0-255 |
| `qc_low_complexity` | edges Canny < 500 | `QC_LOW_COMPLEXITY_EDGE_THRESHOLD = 500` | Sobel après flou 3x3, magnitude > 80 |
| `qc_oversaturated` | % pixels intensité < 30 > 50% | `QC_OVERSATURATED_BLACK_RATIO_THRESHOLD = 0.50` | `(luma_u8 < 30).mean()` |

Si **aucun tag de défaut** n'est posé (qc_color_intrinsic est informatif) →
ajout de `qc_ok`. Si l'image n'est pas lisible (fichier manquant, format
invalide, < 8x8) → `["qc_unreadable"]`.

### Architecture

- `compute_qc_metrics(image_path) -> dict` : calcul pur, retourne
  `readable, color_ratio, intensity_std, edge_count, black_ratio, width, height`.
- `evaluate_qc_tags(metrics, leaf_id) -> list[str]` : applique les règles,
  NULL-safe sur `leaf_id`.
- `is_intrinsic_color_leaf(leaf_id) -> bool` : matche prefixes + mots exacts
  (`"rainbow"`, `"aurora"`, …), case-insensitive.
- `run_qc_for_output(conn, image_output_id, outputs_root) -> dict` :
  pipeline complet (lookup `file_path` + `origin_term_id`, compute,
  evaluate, persist `qc_tags`).
- `QCWorker.process(job)` : lit `entity_id = <image_output_id>`, exécute le
  pipeline.
- `QCWorker.save_result(job, result)` : marque le job `completed`
  (pas de revue humaine — c'est du QC déterministe).

### Pas d'opencv

Approximation Canny en NumPy pur (flou gaussien 3x3 séparable + Sobel +
seuil haut 80). Évite la dépendance opencv (déjà transitive via Pillow
mais pas garantie). Performant : ~1-2 ms sur 1024×1024 dans nos POCs.

## Trigger automatique post-image_generation

Modification minimale de `src/workers/image_worker.py::ImageWorker.save_result` :

- Nouvelle méthode `_enqueue_qc_job(conn, image_output_id, now)` appelée
  juste avant `conn.session.commit()`.
- Crée un `job` de type `image_qc_auto` avec `entity_type='image_output'`,
  `entity_id=<out_id>`, `status='pending'`, `priority=5`.
- **Idempotent** : skip si un job `image_qc_auto` est déjà
  `pending`/`running` pour cet `image_output_id`.
- **Best-effort** : si `job_type_config.image_qc_auto` n'existe pas
  (déploiement progressif) ou si l'enqueue échoue, on logge un warning
  et on continue. Le QC peut toujours être (re)lancé via
  `POST /api/qc/run/{image_output_id}`.

## Endpoints (`src/api/routes/qc.py`)

| Méthode | Path | Rôle | Codes |
|---|---|---|---|
| `POST` | `/api/qc/run/{image_output_id}` | Exécute les 5 règles synchrone, persiste `qc_tags`, retourne `{image_output_id, tags, metrics, leaf_id}` | 200 / 404 |
| `GET` | `/api/qc/tags/{image_output_id}` | Retourne `{image_output_id, tags}` (vide si jamais évalué) | 200 / 404 |

Mounted dans `src/api/main.py` après `review.router`.

## Job type

Ajouté dans `api.db.DEFAULT_JOB_TYPES` :

```python
{
    "type": "image_qc_auto",
    "label": "QC auto image (deterministe)",
    "enabled": False,
    "max_concurrent": 1,
    "description": "5 regles deterministes (couleur/contraste/complexite/saturation) -> qc_tags sur image_output",
    "category": "image",
}
```

Comme tous les autres types, `enabled=False` par défaut. Pour activer :
`PUT /api/jobs/types/image_qc_auto {"enabled": true}` ou via l'éditeur Jobs.

## Tests

Fichier : `tests/test_qc_worker.py` (21 tests, **tous verts**) :

| Catégorie | Tests | But |
|---|---|---|
| Règles pures (no DB) | 9 | Validation des 5 règles + null-safety + unreadable |
| Pipeline DB SQLite | 3 | `run_qc_for_output` lit, calcule, persiste |
| Endpoints API | 5 | POST run / GET tags / 404 / état initial vide |
| Trigger auto | 2 | `ImageWorker.save_result` enqueue + idempotence |
| Job type seed | 1 | `image_qc_auto` est dans `DEFAULT_JOB_TYPES` |
| Job lifecycle | 1 | `QCWorker.save_result` marque `completed` |

Toute la suite tourne en SQLite in-memory via `tests/conftest.py`.
**Pas de régression** sur les 4 tests existants `test_image_worker_*`.

```
pytest tests/test_qc_worker.py
============================== 21 passed in 1.06s ==============================
```

Suite complète :

```
207 passed, 5 failed
```

Les 5 échecs sont **pré-existants** (négative prompt ernie, sans aucun
rapport avec QC ; ne touchent ni `qc_*` ni les fichiers modifiés).
2 modules ne collectent pas (`test_content_generator`, `test_start_singleton_lock`)
pour des erreurs d'import pré-existantes (`HARAKAT_RE`, `start`).

## Calibration des seuils (20 PNG réels)

Script : `scripts/calibrate_qc_thresholds.py`. Sortie raw dans
`docs/reports/2026-05-10_qc-auto-worker.json` (20 lignes).

### Distribution observée

| Métrique | min | médiane | p90 | max |
|---|---|---|---|---|
| `color_ratio` | 0.0000 | 0.0011 | 0.0570 | 0.2010 |
| `intensity_std` | 39.69 | 72.16 | 87.20 | 90.57 |
| `edge_count` | 10464 | 81807 | 157423 | 220882 |
| `black_ratio` | 0.0207 | 0.0753 | 0.1320 | 0.1456 |

### Fréquence des tags posés

| Tag | Cas / 20 |
|---|---|
| `qc_color_residual` | 10 / 20 |
| `qc_ok` | 10 / 20 |
| `qc_low_contrast` | 0 / 20 |
| `qc_low_complexity` | 0 / 20 |
| `qc_oversaturated` | 0 / 20 |

### Lecture / arbitrage

- **`qc_color_residual` (seuil 0.001) — fire 50%** : la distribution a
  une médiane à 0.0011, donc le seuil est *au niveau de la médiane*. Cohérent
  avec le brief (le moindre pixel coloré sur un coloriage line-art est un
  défaut). Acceptable comme **gate strict**, mais à surveiller : si en prod
  ça génère trop de revues, pousser à 0.005 ou 0.01 (séparerait les "vraies"
  fuites couleur des artefacts d'anti-aliasing).
- **`qc_low_contrast` (seuil 30 sur std)** : la valeur min observée est
  39.7. Marge confortable, le tag ne fire que sur des images vraiment
  plates/grises. **Bien calibré.**
- **`qc_low_complexity` (seuil 500 edges)** : valeur min = 10464 (>20× le
  seuil). Sécurité large, ne fire que sur les vraies images
  quasi-vides. **Bien calibré** comme garde-fou.
- **`qc_oversaturated` (seuil 0.50 black_ratio)** : valeur max = 0.146
  (>3× plus bas que le seuil). Ne fire jamais sur des line-art normaux,
  uniquement sur des images sur-encrées ou quasi-noires. **Bien
  calibré.**
- **`qc_color_intrinsic`** : aucun PNG d'échantillon n'a un nom matchant
  `rainbow_*`/`crystal_*`/etc. — règle non déclenchée sur ce sample,
  testée unitairement avec un nom synthétique `rainbow_unicorn`.

### Décision seuils (acté brief)

Les seuils restent **conformes au brief** sans ajustement :

| Seuil | Valeur | Justification calibration |
|---|---|---|
| `QC_COLOR_RESIDUAL_THRESHOLD` | 0.001 | Strict comme demandé ; ~50% fire sur outputs réels — attendu pour une gate "couleur résiduelle" sur coloriage line-art |
| `QC_LOW_CONTRAST_STD_THRESHOLD` | 30.0 | Marge ×1.3 sur le min observé — fire uniquement sur images réellement plates |
| `QC_LOW_COMPLEXITY_EDGE_THRESHOLD` | 500 | Marge ×20 sur le min observé — garde-fou pour images vides |
| `QC_OVERSATURATED_BLACK_RATIO_THRESHOLD` | 0.50 | Marge ×3 sur le max observé — fire uniquement sur images sur-encrées |

À ré-évaluer après ~100 images annotées humainement (corrélation tag QC /
décision éditoriale).

## Fichiers touchés

| Fichier | Type | Lignes |
|---|---|---|
| `alembic/versions/0008_image_output_qc_tags.py` | nouveau | 47 |
| `src/api/models.py` | modifié | +5 (colonne `qc_tags` sur `ImageOutput`) |
| `src/api/db.py` | modifié | +9 (entrée `image_qc_auto` dans `DEFAULT_JOB_TYPES`) |
| `src/api/routes/qc.py` | nouveau | 87 |
| `src/api/main.py` | modifié | +2 (import + mount) |
| `src/workers/qc_worker.py` | nouveau | 250 |
| `src/workers/image_worker.py` | modifié | +50 (méthode `_enqueue_qc_job` + appel en fin de `save_result`, **rien dans `process`**) |
| `tests/test_qc_worker.py` | nouveau | 320 (21 tests) |
| `scripts/calibrate_qc_thresholds.py` | nouveau | 95 |
| `docs/reports/2026-05-10_qc-auto-worker.json` | données calibration | 20 lignes |

## Points d'attention

1. **Migration non appliquée prod** : auto-mode a refusé `alembic upgrade
   head` sur la base partagée. Vérification offline via
   `alembic upgrade --sql 0006:0008` OK. À appliquer côté archi avant
   merge.
2. **Conflit prévisible avec V1.2 (Subject)** : ce worktree ajoute uniquement
   la colonne `qc_tags` sur `ImageOutput` ; pas de touche à la classe
   `Subject` qui sera ajoutée par V1.2. Merge linéaire attendu.
3. **Conflit prévisible avec V1.1 (refactor image_worker)** : modifs
   localisées dans `save_result` uniquement (rien dans `process`).
   Conflit sémantique très faible.
4. **Le worker `image_qc_auto` est `enabled=False` par défaut** comme tous
   les autres types. À activer côté admin avant qu'un worker ne traite la
   queue.
5. **Lancement du worker** : aucun script `run_qc_worker.py` créé — pour
   tester en CLI, ajouter un script analogue à `scripts/run_image_worker.py`
   instanciant `QCWorker()` (hors brief, à faire si besoin).

## Décision / Action suivante

- ✅ Migration 0008 prête (upgrade + downgrade SQL valides).
- ✅ Worker QC opérationnel (5 règles + qc_ok + qc_unreadable).
- ✅ Trigger auto post-`image_generation` (idempotent, best-effort).
- ✅ 2 endpoints (POST run / GET tags) + 404.
- ✅ 21 tests pytest verts.
- ✅ Calibration documentée sur 20 PNG réels — seuils brief conformes.
- ⏭️ Action archi avant merge : `alembic upgrade head` sur la base prod.
- ⏭️ Action après merge : activer `image_qc_auto` via
  `PUT /api/jobs/types/image_qc_auto {"enabled": true}` et brancher un
  worker (script `run_qc_worker.py` à ajouter).
