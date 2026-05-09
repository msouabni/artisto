# Phase complétée — P2 image_prompt_chain worker
Date : 2026-05-05

## Contexte
La chaîne planner → writer → validator a été validée par POC-3 v2 (95 % de succès, p50 17.6 s — cf. `docs/reports/2026-05-05_poc-prompt-chain-v2.md`). Cette tâche l'expose comme **job type `image_prompt_chain`** dans `AiPipelineWorker` + endpoint API synchrone. Les fixes embarqués du POC (drift retry sur le planner, `num_ctx=8192` sur le validator) sont déjà en place dans `run_image_prompt_create_sync` et `run_image_prompt_validate_sync` ; cette tâche les compose en un appel unifié.

## Fichiers touchés

| Fichier | Modification |
|---|---|
| `src/services/ai_jobs_sync.py` | Ajout `run_image_prompt_chain_sync(conn, config) -> dict` |
| `src/workers/ai_pipeline_worker.py` | Import + branche `process()` + branche `save_result()` |
| `src/api/db.py` | Entrée `DEFAULT_JOB_TYPES` pour `image_prompt_chain` (enabled=False par défaut) |
| `src/api/routes/ai.py` | `PromptChainRequest` + `POST /api/ai/prompt-chain` (endpoint sync) |
| `tests/test_image_prompt_chain.py` | 4 tests unitaires (mocks Ollama) |

## Architecture

### Signature

```python
def run_image_prompt_chain_sync(conn, config: dict) -> dict
```

`config` accepte :
- `image_id` (optionnel — si fourni, `title` / `keywords` / `tags_context` manquants sont remplis depuis la table `image`)
- `concept_name_en`, `title`, `keywords`, `tags_context` (au moins un parmi `concept_name_en` / `title` / `keywords` requis)
- `profile` (défaut `kids_coloring_lineart_v1`)
- `model`, `temperature` (surchargent les valeurs YAML)
- `workflow_template` (sélection planner/writer/validator alternatifs)

### Flow

```
1. Resolve title/keywords/tags_context (depuis image_id si nécessaire)
2. Planner :
   - prompt_planner template + drift retry
   - call_ollama_sync_with_drift_retry
   - mesure planner_latency_ms
   - parse → plan dict
3. Writer :
   - prompt_writer_ernie (ou variante via workflow_template)
   - call_ollama_sync(plan_json)
   - mesure writer_latency_ms
   - parse → final_prompt + final_negative
4. Validator :
   - validate_prompt_ernie + num_ctx=8192
   - call_ollama_sync(final_prompt, num_ctx=8192)
   - mesure validator_latency_ms
   - parse → score [0,100], checks[], recommendations[]
5. Aggrégation + ``low_score = (score < 75)``
```

### Retour

```python
{
    "prompt": str,
    "negative_prompt": str,
    "score": int,                  # 0..100
    "checks": list,                # détail validator
    "recommendations": list,       # suggestions validator
    "low_score": bool,             # True si score < 75
    "drift_retried": bool,         # planner a fait un retry T=0
    "planner_latency_ms": int,
    "writer_latency_ms": int,
    "validator_latency_ms": int,
    "total_latency_ms": int,
    "plan": dict,                  # plan structuré du planner
    "image_id": str | None,
    "model_planner": str,
    "model_writer": str,
    "model_validator": str,
    "profile": str,
    "raw_plan": str,
    "raw_writer": str,
    "raw_validator": str,
}
```

`raw_*` sont conservés pour debug ; l'endpoint HTTP les filtre par défaut (lourds en bandwidth).

### Câblage worker — `save_result()`

Le job passe en `awaiting_validation` avec un artifact `image_text_patch` (réutilise `build_image_text_patch_artifact` existant — pas de doublon). Champs proposal :

```python
{
    "prompt": ...,
    "negative_prompt": ...,
    "chain_score": int,
    "chain_checks": list,
    "chain_recommendations": list,
    "chain_low_score": bool,
    "chain_latencies_ms": {"planner": int, "writer": int, "validator": int, "total": int},
    "chain_drift_retried": bool,
}
```

L'admin voit, dans le UI de validation, le prompt généré + score + détail des checks + latences. Pattern identique à `image_prompt_create` (apply_plan=`merge_entity_fields`).

### Job type enregistré

```python
{
    "type": "image_prompt_chain",
    "label": "Prompt image : chaine complete (planner->writer->validator)",
    "enabled": False,
    "max_concurrent": 1,
    "description": "Genere et valide un prompt line-art en une seule passe (POC-3 v2)",
    "category": "text",
}
```

`enabled=False` au seed : à activer manuellement via `PUT /api/jobs/types/image_prompt_chain` ou l'éditeur jobs UI quand on est prêt à recevoir des jobs réels.

## Tests

Fichier : `tests/test_image_prompt_chain.py` — **4/4 PASSED**.

| Test | Vérifie |
|---|---|
| `test_chain_happy_path_score_above_75` | score ≥ 75, `low_score=False`, latences cohérentes (somme = total), plan présent, drift_retried=False |
| `test_chain_low_score_flag` | score = 60 → `low_score=True`, recommendations passées au consommateur |
| `test_chain_drift_retry` | drift_meta["drift_retry"]=True remonté dans le résultat |
| `test_chain_artifact_shape_in_save_result` | `build_image_text_patch_artifact` produit un artefact avec proposals correctes (chain_score, chain_latencies_ms, etc.) |

Mocks : `monkeypatch.setattr(ajs, "call_ollama_sync_with_drift_retry", ...)` + `monkeypatch.setattr(ajs, "call_ollama_sync", ...)` avec une queue ordonnée writer + validator.

### Suite complète après ajout

```
$ pytest --ignore=tests/test_start_singleton_lock.py
148 passed in 2.37s
```

(Le test `test_start_singleton_lock` était déjà cassé en amont — issue pré-existante PYTHONPATH.) **Zéro régression** sur les 144 tests existants.

## Endpoint API (utile pour tests manuels)

```
POST /api/ai/prompt-chain
Content-Type: application/json

{
    "concept_name_en": "Cat in a Library",
    "title": "Cat in a Library",
    "keywords": "cat, library",
    "model": "qwen3:8b",
    "profile": "kids_coloring_lineart_v1"
}
```

Retour 200 avec le ContentResult (sans `raw_*`). Erreurs : 400 si config insuffisant, 502 si LLM échoue.

Synchrone — pas de queue. Utiliser `POST /api/jobs/enqueue` avec `type=image_prompt_chain` pour batch async.

## Exemple de config de job

Pour enfiler un job via la queue :

```json
{
    "type": "image_prompt_chain",
    "config": {
        "image_id": "img_001",
        "concept_name_en": "Cat in a Library",
        "profile": "kids_coloring_lineart_v1"
    },
    "entity_type": "image",
    "entity_id": "img_001"
}
```

Sortie attendue après `awaiting_validation` (extrait artifact) :

```json
{
    "artifact_type": "image_text_patch",
    "entity_id": "img_001",
    "job_type": "image_prompt_chain",
    "proposal": {
        "prompt": "a curious cat sitting at a library desk surrounded by tall bookshelves, line art coloring page",
        "negative_prompt": "color, shading, photo realistic",
        "chain_score": 82,
        "chain_checks": [...],
        "chain_recommendations": [],
        "chain_low_score": false,
        "chain_latencies_ms": {"planner": 4200, "writer": 8100, "validator": 5300, "total": 17600},
        "chain_drift_retried": false
    },
    "apply_plan": {"mode": "merge_entity_fields"}
}
```

Si `chain_low_score=true`, l'admin peut soit accepter (apply), soit rejeter et déclencher un `image_prompt_improve` ou un nouveau `image_prompt_chain`.

## Points d'attention

- **Pas de concurrence parasite** : `max_concurrent=1` (cohérent avec les autres types image_prompt_*) — la chaîne fait 3 appels Ollama séquentiels, paralléliser plusieurs jobs en même temps stresserait l'instance distante. À ré-évaluer si on déploie 2 workers parallèles (cf. dette technique POC-LLM v2).
- **`low_score` n'est pas une erreur** : le résultat est sauvé en `awaiting_validation` quoi qu'il arrive. L'admin choisit en file d'exception. Cohérent avec le paradigme exception-driven du brief.
- **Drift retry** : déjà présent dans `call_ollama_sync_with_drift_retry`. Si le planner drift sur le 2e essai aussi, on échoue avec ValueError → job en retry standard via `base_worker` (3 tentatives, backoff 60/300/900 s).
- **Latence cumulée typique 17-25 s** par job (cf. POC v2). À considérer pour la planification batch : 100 images = ~30-40 min sur 1 worker. Si volumes plus élevés, paralléliser les workers (testé OK sur Ollama remote pour les jobs texte plus légers, à mesurer pour la chaîne).
- **`raw_*` champs lourds** : ils sont sauvés dans `result` du job (~8-15 KB par job en moyenne). Le UI de validation peut les masquer par défaut. L'endpoint `POST /api/ai/prompt-chain` les filtre déjà.

## Décision / Action suivante

✅ **Job type `image_prompt_chain` opérationnel** — enregistré, branché dans `process()` + `save_result()`, endpoint sync exposé, 4 tests unitaires verts, suite complète OK.

À adresser au moment de l'activation prod :
1. **Activer le type** : `PUT /api/jobs/types/image_prompt_chain` `{"enabled": true}` quand on veut recevoir des jobs réels.
2. **Câbler depuis le pipeline** : décider quand un `image_prompt_chain` est enfilé (depuis le UI image_editor ? automatiquement à la création d'image avec `concept_name_en` ?). Pas de blocker code, c'est une décision flow.
3. **Bench charge réelle** : 50 images en batch sur le worker, mesurer latence p50/p95 et taux d'échec planner. POC-3 v2 affichait 95 % de succès sur 25 — à confirmer à plus grande échelle.

Pas de modification immédiate à `image_prompt_create` ou `image_prompt_validate` — ils restent disponibles pour les workflows qui veulent un contrôle plus fin par étape.

## Annexes

- Service : `src/services/ai_jobs_sync.py::run_image_prompt_chain_sync` (lignes ~1100+)
- Worker : `src/workers/ai_pipeline_worker.py` (branche `image_prompt_chain` dans process + save_result)
- Job seed : `src/api/db.py::DEFAULT_JOB_TYPES`
- Endpoint : `src/api/routes/ai.py::prompt_chain_endpoint` + `PromptChainRequest`
- Tests : `tests/test_image_prompt_chain.py` (4 tests)
- Source POC-3 v2 : `scripts/poc_prompt_chain_v2.py` + `docs/reports/2026-05-05_poc-prompt-chain-v2.md`
- Helpers réutilisés : `src/api/job_review_artifact.py::build_image_text_patch_artifact`, `src/services/ollama_json.py::call_ollama_sync_with_drift_retry`
