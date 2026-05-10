# Simplification worker image — pattern POC ComfyClient direct (ERNIE-only)

## Contexte

Décision archi 2026-05-10 : MEP v0 = ERNIE-only. Le worker image actuel utilise la couche `load_workflow_template` + `sanitize_public_workflow_inputs` (capability check sidecar `negative_prompt: optional vs unsupported`) + `apply_overrides`. Cette couche :

- Source des **5 tests rouges** restants (préflight sidecar API + worker sanitize).
- **Non utilisée empiriquement** : tous les POC scale-benchmark (`poc_scale_benchmark_humans.py`, `poc_bench_gate_ernie.py`) passent en `ComfyClient` direct et fonctionnent production-like.
- Surcouche YAGNI : le negative est figé dans `data/workflows/ernie-image-turbo-q8-api.json` depuis 2026-05-05 (CLIPTextEncode node 15) → rien à stripper.

Décision : worker image = pattern POC direct, **ERNIE-only**, plus de préflight ni capability check sur la voie image. Cf. `docs/architect/2026-05-10_spec-mep-v0.md` §V1.1.

## Objectif

Remplacer dans `src/workers/image_worker.py` la chaîne `load_workflow_template → sanitize → apply_overrides` par une injection directe par node id (pattern `poc_bench_gate_ernie.py::submit_to_comfy`). Supprimer la couche préflight côté route API. Nettoyer les 5 tests obsolètes.

## Périmètre — diff précis

### `src/workers/image_worker.py`

**Supprimer (imports lignes 105-111)** :

```python
from workers.comfy_client import (
    ComfyClient,
    ComfyError,
    apply_overrides,
    load_workflow_template,
    sanitize_public_workflow_inputs,
)
```

**Remplacer par** :

```python
from workers.comfy_client import ComfyClient, ComfyError, workflows_json_dir
```

**Remplacer (corps `process` lignes 115-144)** la chaîne `wf_base, public_inputs_map, contract = load_workflow_template(...)` ... `apply_overrides(...)` ... `client.submit_prompt(workflow)` **par** :

```python
# Pattern POC direct (cf. scripts/poc_bench_gate_ernie.py::submit_to_comfy)
wf_path = WORKFLOWS_DIR / f"{workflow_template}.json"
wf = json.loads(wf_path.read_text(encoding="utf-8"))
contract_version = wf.get("__meta__", {}).get("contract_version")
wf.pop("__meta__", None)

# Lecture des valeurs avec fallback sur defaults ERNIE
seed = int(config.get("seed", random.randint(0, 2**32 - 1)))
steps = int(config.get("steps", _ERNIE_SAMPLER_DEFAULTS["steps"]))
cfg = float(config.get("cfg", _ERNIE_SAMPLER_DEFAULTS["cfg"]))
width = int(config.get("width", _ERNIE_SAMPLER_DEFAULTS["width"]))
height = int(config.get("height", _ERNIE_SAMPLER_DEFAULTS["height"]))
batch_size = int(config.get("batch_size", _ERNIE_SAMPLER_DEFAULTS["batch_size"]))
sampler_name = config.get("sampler_name", _ERNIE_SAMPLER_DEFAULTS["sampler_name"])
scheduler = config.get("scheduler", _ERNIE_SAMPLER_DEFAULTS["scheduler"])
denoise = float(config.get("denoise", _ERNIE_SAMPLER_DEFAULTS["denoise"]))

# Injection directe par node id (mapping ERNIE connu)
wf["13"]["inputs"]["width"] = width
wf["13"]["inputs"]["height"] = height
wf["13"]["inputs"]["batch_size"] = batch_size
wf["14"]["inputs"]["text"] = prompt           # positive
# NE PAS injecter wf["15"] (negative) — figé dans le workflow
wf["16"]["inputs"]["seed"] = seed
wf["16"]["inputs"]["steps"] = steps
wf["16"]["inputs"]["sampler_name"] = sampler_name
wf["16"]["inputs"]["scheduler"] = scheduler
wf["16"]["inputs"]["cfg"] = cfg

external_ref_id = client.submit_prompt(wf)
negative_prompt_meta = ""  # negative figé dans workflow, pas du payload
```

**Adapter `generation_params`** (lignes 162-177) en conséquence — `shift` retiré (spécifique z_image, non géré ERNIE-only), `contract_version` lu depuis le `__meta__` capturé plus haut.

**Le reste du worker est inchangé** : `fetch_and_start`, `save_result`, `handle_failure`, polling, QC, persistance, BaseWorker.

### `_ERNIE_SAMPLER_DEFAULTS` (lignes 40-49) — inchangé

Reste comme source de vérité des défauts ERNIE.

### `_Z_IMAGE_SAMPLER_DEFAULTS` (lignes 29-39) — supprimer

ERNIE-only en MEP v0. Le bloc `if workflow_template == "z_image_turbo_v1"` ligne 119 disparaît avec la simplification.

### Route API `/api/jobs` et préflight

Identifier le code de préflight sidecar (probablement `src/api/routes/generation.py` ou `src/api/services/workflow_capability.py`) et :

- **Supprimer** la branche qui strippe `negative_prompt` selon `capability == "unsupported"`.
- Conserver le passage du `negative_prompt` au worker dans `job.config` si présent (mais le worker ne s'en sert plus côté ERNIE).

Effet : les 5 tests rouges (préflight strip) deviennent obsolètes.

### Tests à nettoyer (suppression complète)

- `tests/test_bulk_generation_jobs.py::test_dedup_and_partial_success`
- `tests/test_bulk_generation_jobs.py::test_bulk_preflight_removes_unsupported_negative_for_ernie`
- `tests/test_create_image_job_workflow.py::test_create_job_default_safe_workflow_ignores_negative_prompt_from_image`
- `tests/test_create_image_job_workflow.py::test_create_job_preflight_removes_unsupported_negative_for_ernie`
- `tests/test_workflow_template_sidecar.py::test_ernie_uses_sidecar_from_repo`

**Ajouter** un nouveau test ciblé sur le pattern POC du worker :

- `tests/test_image_worker_direct_pattern.py::test_image_worker_injects_positive_at_node_14`
- `tests/test_image_worker_direct_pattern.py::test_image_worker_ignores_negative_for_ernie`
- `tests/test_image_worker_direct_pattern.py::test_image_worker_uses_workflow_meta_contract_version`

### `data/workflows/ernie-image-turbo-q8-api.json` — non touché

Le workflow conserve son negative interne figé (CLIPTextEncode node 15).

### `data/workflows/ernie-image-turbo-q8-api.overrides.json` — non touché

Sidecar peut rester en repo comme documentation, mais n'est plus consulté par le worker ni la route préflight.

### `PromptGenerator.negative` — non touché

Reste produit pour traçabilité. N'est plus injecté en prod ERNIE. Le champ est conservé pour migration future éventuelle.

## Critères d'acceptation

- Worker image utilise `ComfyClient` direct + injection par node id (no `apply_overrides`, no `sanitize`).
- ERNIE-only : le worker rejette ou traite par défaut tout `workflow_template` autre que `ernie-image-turbo-q8-api` (au choix : lever une exception explicite ou fallback ERNIE — préférer exception pour clarté).
- Préflight sidecar `negative_prompt` retiré de la route API.
- 5 tests préexistants en échec **supprimés** (ne plus apparaître).
- 3 nouveaux tests sur le pattern POC du worker.
- Suite pytest globale verte hors `test_content_generator.py` (dette legacy non liée).
- Smoke E2E : 1 job image créé via API → worker → ComfyUI → image générée → image_output persisté → QC histogram OK.
- Citation décision archi 2026-05-10 (`docs/architect/2026-05-10_spec-mep-v0.md`) en commentaire du worker.

## Hors scope

- Modification de `BaseWorker` (heartbeat / retry / auto-disable préservés).
- Modification des workflows JSON ComfyUI.
- Suppression de `negative` dans `PromptGenerator.build_prompt(...)`.
- Support multi-workflow image (z_image, etc.) — supprimé pour MEP v0.

## Plan d'exécution suggéré (sous-agent unique)

```
Phase 1 — Audit (~15 min)
  - Localiser le code préflight côté route API (grep "sanitize_public_workflow_inputs" + "negative_prompt" dans src/api/)
  - Confirmer le mapping node id du workflow ERNIE (lire ernie-image-turbo-q8-api.json)

Phase 2 — Refactor worker (~30 min)
  - Modifier image_worker.py (injection directe)
  - Supprimer _Z_IMAGE_SAMPLER_DEFAULTS si plus utilisé

Phase 3 — Suppression préflight route (~20 min)
  - Retirer strip negative_prompt selon capability
  - Vérifier que le job.config est créé sans préflight

Phase 4 — Tests (~30 min)
  - Supprimer les 5 tests obsolètes
  - Créer les 3 nouveaux tests pattern POC
  - Suite globale verte

Phase 5 — Smoke E2E (~15 min)
  - 1 job image via API
  - Vérifier worker → ComfyUI → image → image_output
```

## Reporting

`docs/reports/2026-05-10_simplification-worker-image-pattern-poc.md` — Contexte / Modifications / Tests / Smoke E2E / Décision (clôture dette sidecar).

## Estimation

~1h30 dev + tests + rapport (parallélisable avec les autres briefs V1.2, V1.3, V1.4 du plan MEP v0).
