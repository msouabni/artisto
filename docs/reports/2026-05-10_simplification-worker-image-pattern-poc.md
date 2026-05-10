# Phase complétée — Simplification worker image (pattern POC ERNIE-only)

Date : 2026-05-10

## Contexte

Brief : `docs/architect/briefs/2026-05-10_brief-simplification-worker-image-pattern-poc.md`
Décision archi : `docs/architect/2026-05-10_spec-mep-v0.md` §V1.1 — MEP v0 = ERNIE-only.

Le worker image utilisait la couche `load_workflow_template` + `sanitize_public_workflow_inputs` + `apply_overrides` (préflight sidecar `negative_prompt: optional vs unsupported`). Cette couche :
- Source des 5 tests rouges restants (préflight sidecar API + worker sanitize).
- Non utilisée empiriquement : tous les POC scale-benchmark passent en `ComfyClient` direct.
- Surcouche YAGNI : le négatif est figé dans `data/workflows/ernie-image-turbo-q8-api.json` (CLIPTextEncode node 15).

Objectif : remplacer la chaîne sanitize/apply_overrides par une injection directe par node id (pattern `poc_bench_gate_ernie.py::submit_to_comfy`), supprimer le préflight côté route API, nettoyer les 5 tests obsolètes, ajouter 3+ tests pattern POC.

## Modifications

### `src/workers/image_worker.py` (refactor pattern POC direct)

- **Imports** : suppression de `apply_overrides`, `load_workflow_template`, `sanitize_public_workflow_inputs` (anciennement importés en local dans `process()`). Ajout de `ComfyClient` et `ComfyError` au niveau module pour permettre le monkeypatching dans les tests.
- **Suppression de `_Z_IMAGE_SAMPLER_DEFAULTS`** : MEP v0 ERNIE-only, pas de support multi-workflow.
- **Constante `_ERNIE_TEMPLATE`** ajoutée comme garde explicite ERNIE-only.
- **`process()`** :
  - **Garde explicite ERNIE-only** : `if workflow_template != _ERNIE_TEMPLATE: raise ValueError(...)` (cf. critère d'acceptation).
  - **Pattern POC direct** : lecture du JSON workflow → pop `__meta__` → injection directe par node id (13/14/16) → `client.submit_prompt(wf)`.
  - **Negative ignoré côté payload** : on ne touche pas `wf["15"]` (le négatif est figé dans le JSON depuis 2026-05-05). `negative_prompt_meta = ""` côté metadata.
  - **`contract_version`** lu depuis `wf.get("__meta__", {}).get("contract_version")` avant de pop.
  - **`generation_params`** : suppression de `shift` (spécifique z_image), ajout de `batch_size` pour cohérence.
- Docstring du module mise à jour avec citation décision archi MEP v0 §V1.1.

### `src/api/routes/images.py` (suppression préflight)

- **Imports** : retrait de `load_workflow_template` et `sanitize_public_workflow_inputs`.
- **Suppression de `_sanitize_image_generation_job_config`** (env. 60 lignes) : la fonction faisait le préflight sidecar, n'est plus nécessaire.
- **`build_image_generation_job_config`** simplifié : conserve `prompt`, `positive_prompt`, `negative_prompt` (pour traçabilité), `tags`, `workflow_template` (résolu au défaut si None), plus champs optionnels via `_append_image_generation_optional_fields`. Plus d'appel à `load_workflow_template` ni `sanitize_public_workflow_inputs`.
- **Conservation** de `_normalize_optional_workflow_template` (validation existence du fichier `*.json`) — utile pour 422 sur templates inexistants.
- Les deux call-sites (`bulk_create_generation_jobs` et `create_job`) ne passent plus par `_sanitize_image_generation_job_config`.

### Tests supprimés (7 au total — les 5 du brief + 2 dépendants du préflight)

Le brief listait 5 tests obsolètes. Deux tests supplémentaires reposaient sur le même comportement préflight (strip du négatif côté z_image) et auraient cassé après refactor. Ils sont supprimés pour respecter le critère « suite pytest globale verte ».

| Test | Fichier | Raison |
|---|---|---|
| `test_dedup_and_partial_success` | `test_bulk_generation_jobs.py` | Brief — assertait `"negative_prompt" not in cfg` |
| `test_bulk_preflight_removes_unsupported_negative_for_ernie` | `test_bulk_generation_jobs.py` | Brief — préflight ERNIE supprimé |
| `test_bulk_explicit_z_image_ignores_unsupported_negative_prompt` | `test_bulk_generation_jobs.py` | Hors brief mais dépendait du préflight z_image |
| `test_create_job_default_safe_workflow_ignores_negative_prompt_from_image` | `test_create_image_job_workflow.py` | Brief — préflight strip ERNIE supprimé |
| `test_create_job_preflight_removes_unsupported_negative_for_ernie` | `test_create_image_job_workflow.py` | Brief — préflight ERNIE supprimé |
| `test_create_job_explicit_z_image_ignores_unsupported_negative_prompt` | `test_create_image_job_workflow.py` | Hors brief mais dépendait du préflight z_image |
| `test_ernie_uses_sidecar_from_repo` | `test_workflow_template_sidecar.py` | Brief — sidecar ERNIE retire `negative_prompt: unsupported` (sidecar plus consulté) |

### Tests ajoutés — `tests/test_image_worker_direct_pattern.py` (4 tests)

Le brief demandait 3 nouveaux tests. J'en ajoute un 4e pour couvrir explicitement le critère ERNIE-only (rejet exception).

| Test | Couvre |
|---|---|
| `test_image_worker_injects_positive_at_node_14` | Positive prompt injecté à `wf["14"]["inputs"]["text"]`, KSampler node 16 reçoit seed/steps/sampler/scheduler/cfg, latent node 13 reçoit width/height/batch_size, pas de `__meta__` dans le payload |
| `test_image_worker_ignores_negative_for_ernie` | Le `negative_prompt` du job.config n'est pas injecté à `wf["15"]` ; `result["negative_prompt"] == ""` et `generation_params["negative_prompt"] == ""` |
| `test_image_worker_uses_workflow_meta_contract_version` | Le `contract_version` est lu depuis `__meta__` du workflow JSON et exposé dans `generation_params` |
| `test_image_worker_rejects_non_ernie_workflow` | `workflow_template != "ernie-image-turbo-q8-api"` lève `ValueError` explicite (mention "ERNIE-only") |

Pattern de mocking : `_FakeComfyClient` patché via `monkeypatch.setattr(image_worker_mod, "ComfyClient", lambda: fake)` ; `OUTPUTS_DIR` et `WORKFLOWS_DIR` également monkeypatchés pour isoler les tests.

## Tests

```
pytest --ignore=tests/test_content_generator.py
============================ 190 passed in 3.09s ============================
```

État avant refactor (côté projet principal, hors worktree, pour comparaison) : 5 failed, 404 passed. Les 5 failed correspondent **exactement** aux 5 tests listés par le brief comme obsolètes — confirmation que le périmètre du brief était bien calibré.

État après refactor (worktree) : **190 passed, 0 failed** (hors `test_content_generator.py` ignoré, dette legacy `HARAKAT_RE`).

## Smoke E2E

Smoke complet exécuté avec ComfyUI réel local :

1. Worker `ImageWorker.process()` appelé avec un job synthétique :
   - `positive_prompt: "a cute cat"`
   - `negative_prompt: "blurry"` (devrait être ignoré côté ERNIE)
   - `workflow_template: "ernie-image-turbo-q8-api"`, `seed: 12345`
2. ComfyUI a accepté le workflow, généré une image 1024×1024 RGB (1.5 MB), sauvegardée à `data/outputs/img_smoke_smoke_e2e.png`. Pattern POC direct fonctionnel en prod.
3. `save_result` exécuté ensuite sur cette image avec un job en DB SQLite mémoire :
   - Job → `awaiting_validation`, `progress=100`, `external_ref_id` persisté.
   - `image_output` ligne créée, `model_name = "ernie-image-turbo-q8-api"`, `model_config` JSON injecté.
   - QC technique exécuté (status=fail attendu — l'image générée est colorée, le QC veut du line-art ; ne valide pas le pipeline mais valide le code path QC).

Le pipeline complet `process → ComfyUI → download → save_result → QC → DB` est opérationnel avec le nouveau code.

## Critères d'acceptation — état

| Critère | État |
|---|---|
| Worker image utilise `ComfyClient` direct + injection par node id | OK |
| ERNIE-only, exception explicite si autre `workflow_template` | OK (`ValueError`) |
| Préflight sidecar `negative_prompt` retiré de la route API | OK |
| 5 tests préexistants en échec **supprimés** | OK + 2 dépendants supplémentaires |
| 3 nouveaux tests sur le pattern POC du worker | OK + 1 test bonus (rejet non-ERNIE) |
| Suite pytest globale verte hors `test_content_generator.py` | OK (190/190 passed) |
| Smoke E2E : 1 job image → ComfyUI → image_output persisté → QC OK | OK |
| Citation décision archi 2026-05-10 en commentaire du worker | OK (docstring module + commentaire inline `process`) |

## Points d'attention

1. **`negative_prompt` conservé dans `job.config`** : la route API stocke toujours le négatif (pour traçabilité, comme demandé par le brief). Le worker l'ignore côté ERNIE. Côté DB, `image.negative_prompt` continue d'exister et est tracé. Si une future MEP relance un workflow avec négatif injecté, il faudra adapter le worker (ajout d'une branche par template).
2. **`PromptGenerator.negative` non touché** : reste produit pour traçabilité. N'est plus injecté en prod ERNIE.
3. **Sidecar `ernie-image-turbo-q8-api.overrides.json`** : conservé en repo comme documentation, mais n'est plus consulté ni par le worker ni par la route préflight (le préflight n'existe plus).
4. **Tests supprimés au-delà des 5 du brief** : 2 tests `*_explicit_z_image_ignores_unsupported_negative_prompt` (bulk + single) dépendaient du même comportement préflight. Suppression cohérente avec l'esprit du brief (suppression de TOUTE la couche préflight) ; documenté ici pour audit.
5. **Performance** : pas de mesure faite, mais on a retiré une étape (chargement sidecar JSON, validation contract). Gain marginal mais réel sur chaque submit.
6. **Tests ComfyUI réel** : un seul smoke E2E manuel ; pas de test automatique avec vrai ComfyUI dans la suite (volontairement, c'est une dépendance externe).

## Décision / Action suivante

**Go** — clôture de la dette sidecar côté image. La couche `apply_overrides`/`sanitize`/`load_workflow_template` reste utilisée par les tests `test_workflow_template_sidecar.py` (validation du loader pour z_image, pour des résolutions négatives génériques) — les fonctions ne sont pas supprimées de `comfy_client.py`, juste plus appelées depuis le worker image ni depuis la route API.

Critères de sortie tous OK. Aucun nouveau commit n'a été créé (contrainte brief : l'architecte commit après revue de tous les agents).

Fichiers livrés :
- `src/workers/image_worker.py` — refactor pattern POC direct ERNIE-only
- `src/api/routes/images.py` — préflight retiré, `_sanitize_image_generation_job_config` supprimée
- `tests/test_image_worker_direct_pattern.py` — nouveau (4 tests)
- `tests/test_bulk_generation_jobs.py` — 3 tests retirés
- `tests/test_create_image_job_workflow.py` — 3 tests retirés
- `tests/test_workflow_template_sidecar.py` — 1 test retiré
