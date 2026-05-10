# QC auto worker — tags déterministes simples (no LLM, no ComfyUI)

## Contexte

Vision MEP v0 (cf. `docs/architect/2026-05-10_spec-mep-v0.md`) : après génération image, un **QC auto** pose des tags simples sur `image_output` pour informer l'utilisateur en queue de validation. **Pas de LLM** (vision QC LLM invalidé empiriquement — cf. décisions 2026-05-10). **Pas d'auto-décision** : l'utilisateur tranche, le QC informe.

Posture utilisateur 2026-05-10 : « pense utilité et simplicité droit au but ».

État actuel :
- `src/services/image_qc_technical.py::build_technical_image_qc_v1(path)` existe — produit un QC report Pillow histogram (color_ratio, ink_ratio).
- Table `image_output` stocke les images générées.
- Pas de table `image_qc_tag` ni mécanisme de tags QC dédié.

## Objectif

Créer un job type `image_qc_auto` + un worker dédié (`qc_worker`) qui applique 5 règles déterministes sur une image et pose des tags sur `image_output`. Trigger automatique post-`image_generation` ou job standalone manuel.

## Périmètre

### 5 tags QC (vocabulaire fixé)

| Tag | Règle de détection | Coût | Lib |
|---|---|---|---|
| `qc_color_residual` | `color_ratio > 0.001` (existant `build_technical_image_qc_v1`) | <0.5s | Pillow |
| `qc_color_intrinsic` | leaf_id matches whitelist `{rainbow_*, crystal_*, prism_*, spectrum_*, aurora_*}` | instantané | regex |
| `qc_low_contrast` | std intensité pixels < 30 (sur 255) | <0.5s | Pillow + numpy |
| `qc_low_complexity` | nombre d'edges Canny < seuil (ex. 500 sur image 1024² — à calibrer) | <1s | Pillow + numpy (skimage optionnel) |
| `qc_oversaturated` | percent pixels noirs (intensité < 30) > 50% → trop d'encre | <0.5s | Pillow + numpy |

Si aucun tag négatif détecté → tag `qc_ok` posé.

Note : les seuils (30, 500, 50%) sont indicatifs. Le brief acceptera des seuils ajustés à la première mesure sur un échantillon de 20 images réelles — l'agent doit ajuster + documenter dans le rapport.

### Job type + worker

| Composant | Action |
|---|---|
| `job_type` `image_qc_auto` | Seed dans `api/db.py::DEFAULT_JOB_TYPES` (auto-applied via `ensure_default_job_types` au startup) |
| `qc_worker.py` (NOUVEAU dans `src/workers/`) | Hérite de `BaseWorker` (`job_type='image_qc_auto'`, `category='qc'`) |
| `process(job)` | Charge `image_output` via `job.entity_id`, applique les 5 règles, pose tags |
| `save_result(job, result)` | Enregistre tags sur `image_output` (cf. stockage ci-dessous) + status job `awaiting_validation` |

### Stockage des tags QC

Option A (recommandée — simple) : ajouter colonne `qc_tags JSON` à `image_output` via migration Alembic `0008_image_output_qc_tags.py`. Tags = `list[str]`.

Option B (rejetée pour MEP v0) : table dédiée `image_qc_tag` polymorphe. Inutile vu la simplicité requise.

### Trigger post-`image_generation`

Le worker `image_worker` (simplifié V1.1) écrit `image_output` puis met le job `image_generation` à `awaiting_validation`. **Trigger QC** :

- Option A (recommandée) : après le `save_result` de `image_worker`, créer automatiquement un job `image_qc_auto` avec `entity_id=<image_output_id>`. Job queue le prend en charge sans intervention.
- Option B (rejetée) : appeler le QC en synchrone dans `image_worker.save_result` — couplage fort, blocage du worker image en cas de QC lent.

L'option A est cohérente avec le principe « tout via jobs » de la vision utilisateur.

### Endpoints API (minimaux)

`src/api/routes/jobs.py` (existant) accepte déjà la création de jobs via `/api/jobs`. Ajouter une route ciblée :

| Méthode | Path | Effet |
|---|---|---|
| `POST /api/qc/run/{image_output_id}` | Créer manuellement un job `image_qc_auto` sur une image existante (utile pour re-run après ajustement seuils) | `get_db_write` |
| `GET /api/qc/tags/{image_output_id}` | Lire les tags QC d'une image | `get_db_read` |

### Tests

`tests/test_qc_worker.py` (nouveau) :

- 5 tests unitaires sur les règles de détection (image fabriquée Pillow par règle).
- Test de tag `qc_ok` quand aucun tag négatif (image neutre).
- Test idempotence : 2 runs QC sur la même image → tags identiques.
- Test trigger auto : après `image_generation` complet, job `image_qc_auto` créé automatiquement.
- Test endpoint manual run + read.
- NULL-safe : `image_output.qc_tags=NULL` géré correctement avant 1er run.
- Tests SQLite-portables.

## Critères d'acceptation

- Migration Alembic `0008_image_output_qc_tags.py` appliquée + downgrade OK.
- Job type `image_qc_auto` seedé.
- Worker `qc_worker.py` opérationnel avec les 5 règles déterministes.
- Trigger auto post-`image_generation` fonctionnel.
- 2 endpoints API opérationnels.
- Tests pytest verts (≥ 10 nouveaux tests).
- Suite globale verte hors dette legacy.
- Smoke E2E : générer 1 image → vérifier que `qc_tags` est peuplé automatiquement après quelques secondes (le QC tourne dans le worker queue).

## Hors scope

- QC vision LLM (abandonné).
- Auto-décision publishable/rejected sur la base des tags (l'utilisateur tranche).
- Tags QC qualitatifs (composition, anatomie) — invalidés (cf. décisions 2026-05-10).
- Calibration fine des seuils (l'agent ajuste à la 1ère mesure, refinement post-MEP v0).
- Recalcul QC sur images historiques (à faire séparément si besoin via endpoint manual run).

## Plan d'exécution suggéré (sous-agent unique)

```
Phase 1 — Migration + modèle (~15 min)
  - 0008 ajout qc_tags JSON sur image_output
  - Adapter modèle SQLAlchemy

Phase 2 — Worker + règles (~45 min)
  - qc_worker.py hérite BaseWorker
  - 5 règles déterministes (Pillow + numpy)
  - save_result enregistre tags

Phase 3 — Trigger auto (~15 min)
  - Modifier image_worker.save_result pour créer un job qc auto après image_generation

Phase 4 — Endpoints + tests (~30 min)
  - 2 routes API
  - 10 tests pytest

Phase 5 — Smoke E2E + calibration seuils (~15 min)
  - Run sur 20 images existantes (depuis poc-scale-benchmark)
  - Distribuer les tags, ajuster les seuils si distribution aberrante
  - Rapport
```

## Reporting

`docs/reports/2026-05-10_qc-auto-worker.md` — Contexte / Migration / Worker / Trigger / Endpoints / Tests / Calibration seuils / Smoke E2E / Décision.

## Estimation

~1h-1h30 dev + tests + rapport + calibration.

## Dépendances

- V1.1 (simplification image_worker) : pas bloquant — le trigger auto post-`image_generation` peut être branché sur le worker simplifié (ajout d'un `_enqueue_qc_job` à la fin du `save_result`).
- V1.2 (modèle `subject`) : non requis (QC pose ses tags sur `image_output`, pas sur `subject`).
- V1.3 (import skill) : non requis.
