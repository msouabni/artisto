# CLI — guide d’utilisation

Le fichier [`src/cli.py`](../src/cli.py) expose une application **Typer** avec deux familles de commandes :

| Famille | Besoin | Rôle |
|--------|--------|------|
| **Taxonomie** (`list-themes`, `show-branch`, `input-theme`) | Aucune API | Lit la taxonomie embarquée (module `taxonomy`) — utile en local sans serveur. |
| **Jobs** (`jobs …`) | **API FastAPI démarrée** | Client HTTP vers `ARTISTE_API_BASE` : enfiler un job texte, afficher le diff, appliquer ou rejeter. |

---

## Prérequis

1. **Répertoire** : racine du dépôt `artiste-coloriage`.
2. **PYTHONPATH** : le package `api`, `workers`, `services`, etc. vit sous `src` :

**PowerShell**

```powershell
cd D:\projets\artiste-coloriage
$env:PYTHONPATH = "src"
```

**cmd**

```bat
cd D:\projets\artiste-coloriage
set PYTHONPATH=src
```

3. **API** (pour les commandes `jobs`) : par défaut le CLI appelle `http://127.0.0.1:8000`. Pour changer :

```powershell
$env:ARTISTE_API_BASE = "http://127.0.0.1:8000"
```

---

## Aide intégrée (Typer)

```powershell
python -m cli --help
python -m cli jobs --help
python -m cli jobs enqueue-text --help
python -m cli jobs generate-concepts --help
python -m cli jobs images export-ids --help
python -m cli jobs ai bulk-create-prompts --help
python -m cli jobs images bulk-create-generation-jobs --help
python -m cli jobs ai bulk-image-prompt-create --help
python -m cli jobs wizard bulk-prompts --help
```

### Export d’ids + génération bulk de prompts (via la file de jobs)

Ces commandes passent par la file d’attente : elles enfilent un job `image_prompts_bulk` via `POST /api/jobs/enqueue` puis attendent la completion par polling. Le worker `AiPipelineWorker` (lancé par `scripts/run_text_worker.py`) exécute le travail IA. **L’API et le worker doivent être démarrés** (`python start.py`).

1. **Exporter les ids** (pagination automatique, une id par ligne en `.txt`, ou objet JSON avec `image_ids` si extension `.json`) :

```powershell
python -m cli jobs images export-ids --out data/draft_ids.txt --status draft
python -m cli jobs images export-ids --out data/multi.json --status-in draft,prompt_ready
```

2. **Générer les prompts en lots** (paquets de 10 max, aligné sur l’API) :

```powershell
python -m cli jobs ai bulk-create-prompts data/draft_ids.txt --dry-run
python -m cli jobs ai bulk-create-prompts data/draft_ids.txt --persist `
  --checkpoint data/draft_ids.checkpoint.txt
python -m cli jobs ai bulk-create-prompts data/draft_ids.txt --resume `
  --checkpoint data/draft_ids.checkpoint.txt
```

Options utiles : `--workflow-template z_image_turbo_v1` (sinon défaut Ernie côté API), `--validate`, `--results-out run.ndjson`.

Les commandes bulk basées sur un **fichier d’`image_id`** partagent le même contrat d’entrée (`.txt` une id par ligne, JSON tableau, ou export `.json` avec `image_ids`) et les mêmes options : `--chunk-size`, `--dry-run`, `--checkpoint`, `--resume`, `--results-out`, plus un résumé terminal `success` / `failed` / `chunks`.

---

### Export d’ids + création bulk de jobs `image_generation`

Après avoir des concepts en **`prompt_ready`** avec un prompt non vide :

1. **Exporter les ids** (comme ci-dessus), par ex. :

```powershell
python -m cli jobs images export-ids --out data/prompt_ready_ids.txt --status prompt_ready
```

2. **Créer les jobs de génération** (paquets de 25 max, aligné sur `POST /api/images/bulk-create-generation-jobs`) :

```powershell
python -m cli jobs images bulk-create-generation-jobs data/prompt_ready_ids.txt --dry-run
python -m cli jobs images bulk-create-generation-jobs data/prompt_ready_ids.txt `
  --workflow-template z_image_turbo_v1 `
  --checkpoint data/gen.checkpoint.txt
python -m cli jobs images bulk-create-generation-jobs data/prompt_ready_ids.txt --resume `
  --checkpoint data/gen.checkpoint.txt
```

Options optionnelles alignées sur l’API : `--steps`, `--cfg`, `--sampler-name`, `--scheduler`, `--denoise`, `--shift`, `--seed`.

---

### Export d’ids + enqueue bulk `image_prompt_create`

Un job **`image_prompt_create`** est enfilé par image (`POST /api/jobs/enqueue`). Sans `--keywords` / `--title` globaux, le CLI complète par **`GET /api/images/{id}`** (titre + prompt de l’image). Avec **`--dry-run`**, il faut fournir au moins **`--keywords` et/ou `--title`** (aucun GET).

```powershell
python -m cli jobs images export-ids --out data/draft_ids.txt --status draft
python -m cli jobs ai bulk-image-prompt-create data/draft_ids.txt --keywords "coloriage enfant" `
  --workflow-template z_image_turbo_v1 --checkpoint data/ipc.ckpt
python -m cli jobs ai bulk-image-prompt-create data/draft_ids.txt --dry-run --keywords "test"
```

Flux homogène (exemple) :

```powershell
python -m cli jobs images export-ids --out data/prompt_ready_ids.txt --status prompt_ready
python -m cli jobs images bulk-create-generation-jobs data/prompt_ready_ids.txt --workflow-template z_image_turbo_v1 --checkpoint data/gen.ckpt
python -m cli jobs ai bulk-image-prompt-create data/prompt_ready_ids.txt --workflow-template z_image_turbo_v1 --keywords "coloriage"
```

3. **Assistant interactif** (filtre statut → export → confirmation → bulk + checkpoint optionnel) :

```powershell
python -m cli jobs wizard bulk-prompts
```

---

## Commandes taxonomie (sans API)

```powershell
python -m cli list-themes
python -m cli show-branch themes
python -m cli input-theme
```

Ces commandes utilisent les données chargées par le module `taxonomy` (pas les endpoints REST).

---

## Commandes jobs (avec API + workers)

Flux typique pour un job **`text_enrichment`** :

1. Démarrer l’API (`uvicorn` ou `start.py`).
2. Activer le type **`text_enrichment`** si besoin : `PUT /api/jobs/types/text_enrichment` avec `{"enabled": true}`.
3. **Enfiler** un job :

```powershell
python -m cli jobs enqueue-text "Propose un titre court pour ce terme" `
  --entity-id mon_terme `
  --vocabulary-id themes `
  --system "Réponds uniquement en JSON."
```

La réponse JSON contient `"id"` : c’est le **`job_id`**.

4. Lancer le **worker texte** (autre terminal, même `PYTHONPATH`) :

```powershell
python scripts/run_text_worker.py --once
```

5. Quand le job est en **`awaiting_validation`** :

```powershell
python -m cli jobs diff JOB_ID
python -m cli jobs validate JOB_ID apply
# ou
python -m cli jobs validate JOB_ID reject
```

Pour un job **`image_generation`**, la création se fait plutôt via l’éditeur ou `POST /api/images/{id}/jobs` ; le CLI expose surtout **`validate`** avec le même `JOB_ID` :

```powershell
python -m cli jobs validate job_gen_xxxxx apply
```

**Revue & QC (UI)** : dans [`data/jobs_editor.html`](../data/jobs_editor.html) et [`data/images_editor.html`](../data/images_editor.html), le bouton **« Revue image »** ouvre une modale dédiée (aperçu PNG, rapport QC technique, plan d’effet apply/reject). Le diff générique n’est plus adapté à ce type de job.

**API** : `GET /api/jobs/{id}/review` renvoie le payload structuré (preview, `qc`, `apply_plan_summary`, `reject_plan_summary`). Pour inspection en CLI / navigateur :

```text
GET http://127.0.0.1:8000/api/jobs/job_gen_xxxxx/review
```

`GET /api/jobs/{id}/diff` sur un artefact `image_generation_output` renvoie désormais une redirection explicite : `{ "redirect_to": "review", "review_url": "/api/jobs/{id}/review", "fields": [] }` (évite l’affichage trompeur « title/prompt removed »). Les autres types de jobs conservent le diff champ à champ.

| Champ principal (review) | Rôle |
|--------------------------|------|
| `preview` | `rel_path`, `image_url` (même logique que `/output-image`), `prompt`, `negative_prompt` |
| `qc` | Rapport QC v1 (`status`, scores, `flags`, `checks`, `recommendations`, `metrics`) — **informationnel** : un `fail` n’empêche pas `validate apply`. |
| `apply_plan_summary` | Changements DB attendus (`image.status`, `image.selected_output_id`) ; **aucun** titre/prompt texte n’est modifié à l’apply. |
| `reject_plan_summary` | Suppression fichier + ligne `image_output` + retour `prompt_ready` si `generating`. |

### Job `image_generate_concepts` (concepts image, même logique que `POST /api/ai/generate-concepts`)

1. Enfiler :

**Thème libre** (sans ancrage terme, comme avant) :

```powershell
python -m cli jobs generate-concepts "Mon thème" --count 5
```

**Uniquement un terme** (comme l’UI images : le CLI appelle l’API taxonomie pour dériver `theme` = `name_en` | `name_fr`, et envoie `term_id` + `vocabulary_id`) :

```powershell
python -m cli jobs generate-concepts --term-id mon_terme --vocabulary-id themes --count 5
```

Si `-v` est omis avec `--term-id`, le vocabulaire utilisé est **`themes`**. Tu peux encore passer un **THEME** en premier argument pour forcer le libellé tout en gardant l’ancrage :  
`python -m cli jobs generate-concepts "Sous-thème marketing" --term-id mon_terme -v themes`

Le CLI active automatiquement le type de job `image_generate_concepts` via l’API avant d’enfiler le job.

2. Lancer `python scripts/run_text_worker.py --once` (ou boucle).
3. Quand le job est en `awaiting_validation` : `python -m cli jobs diff JOB_ID` puis `validate JOB_ID apply` pour créer les lignes `image` en brouillon (et le tag taxonomie si ancrage `term_id` + `vocabulary_id`).

### `jobs image-prompt-create`

Enfile un job `image_prompt_create` (planner + writer). **Défaut templates Ernie** ; passez `--workflow-template z_image_turbo_v1` pour forcer le pack Z-Image.

```powershell
python -m cli jobs image-prompt-create -i IMAGE_ID -k "mots" --workflow-template z_image_turbo_v1
```

---

## Dépannage

| Problème | Piste |
|----------|--------|
| `ModuleNotFoundError: api` ou `taxonomy` | Définir `PYTHONPATH=src` depuis la racine du projet. |
| `401` / connexion refusée | Vérifier que l’API tourne et que `ARTISTE_API_BASE` est correct. |
| `400` type désactivé | `PUT /api/jobs/types/text_enrichment` avec `enabled: true`. |
| `404` sur `/diff` | Le job n’est pas en `awaiting_validation` (encore `pending`/`running` : lancer le worker). |
| `400` sur `/api/jobs/enqueue` « Type … inconnu dans job_type_config » | Base sans seed des types de jobs : redémarrer l’API (synchronisation au démarrage) ou lancer `python scripts/init_db.py`. |
| `400` « type … désactivé » sur `jobs generate-concepts` | Le CLI tente déjà l’activation automatique ; si l’erreur persiste, vérifier que l’API expose bien `PUT /api/jobs/types/{type}` et que l’utilisateur / la DB autorise l’écriture. |

---

## Modèle métier (rappel)

- `job.result` suit le contrat **artefact de revue v1** (`artifact_version`, `artifact_type`, `proposal`, `preview`, `apply_plan`, `resources`) pour les jobs concernés.
- **`image_generation`** : après ComfyUI, le job passe en **`awaiting_validation`** ; l’image reste **`generating`** jusqu’à **apply** (**`generated`** + `selected_output_id`) ou **reject** (retour **`prompt_ready`**). Le worker calcule un **QC technique** (`job.result.qc`) ; la validation humaine reste possible même si le QC est en échec (décision manuelle).
- **`text_enrichment`** : après Ollama, **`awaiting_validation`** ; la persistance sur `term` se fait au **validate** `apply`.

## API équivalente

| Méthode | Rôle |
|--------|------|
| `POST /api/jobs/enqueue` | Crée un job `text_enrichment` |
| `GET /api/jobs/{id}/diff` | Diff champ à champ (sauf `image_generation_output` → voir `redirect_to` / `review_url`) |
| `GET /api/jobs/{id}/review` | Payload revue image (`image_generation` + `awaiting_validation` uniquement) |
| `POST /api/jobs/{id}/validate` | `{ "action": "apply" \| "reject", "fields"?: [...] }` |

## Workers

- `python scripts/run_text_worker.py` — `text_enrichment`
- `python scripts/run_image_worker.py` — `image_generation`

Les routes **`/api/ai/*`** synchrones restent utilisées par l’UI pour des suggestions sans passer par la queue ; la chaîne **persistée** via jobs utilise la queue et `src/services/ollama_json.py` côté worker texte.
