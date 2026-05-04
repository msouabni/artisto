# Scripts Artiste Coloriage

## Base PostgreSQL (Docker)

### Initialiser la base

```bash
python scripts/init_db.py
```

Crée/met à jour le schéma PostgreSQL via SQLAlchemy ORM.

### Importer la taxonomie JSON

```bash
python scripts/import_taxonomy_json_to_db.py [chemin_json]
```

Par défaut : `data/taxonomy_universal_v0.json` vers la base pointée par `DATABASE_URL`.

### Peupler les données de démo (images, sites, jobs, etc.)

```bash
python scripts/seed_data.py
python scripts/seed_data.py --reset   # vide puis réinsère
```

Crée des exemples pour tester l'éditeur images (`/data/images_editor.html`) :
- **Sites** : site_fr, site_en, site_ar, site_demo
- **Jobs** : génération (completed/running/failed), export, batch
- **Images** : 10 concepts avec statuts variés (draft, prompt_ready, scheduled, generating, generated, approved, published)
- **Outputs** : liés aux jobs de génération
- **Tags** : taxonomie themes (animaux, mandalas, véhicules, noël, etc.)
- **Collections** : animaux, mandalas, noël, véhicules
- **Batches** : batch_001 (done), batch_002 (prompts_ready), batch_003 (pending)

## CLI (Typer)

À la racine du dépôt, avec `PYTHONPATH=src` :

```bash
python -m cli --help
python -m cli jobs enqueue-text "Votre prompt" --entity-id TERM_ID -v themes
```

Documentation complète : [docs/cli-jobs-workflow.md](../docs/cli-jobs-workflow.md).

## API FastAPI

```bash
cd src && python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

- Éditeur taxonomie : http://127.0.0.1:8000/data/taxonomy_editor.html
- API docs : http://127.0.0.1:8000/docs

En cas de 500 : voir le corps de la réponse (DevTools → Network → Response) ou les logs du terminal serveur ; détail dans `tests/README.md`.

### IA — prompts image (v1)

Endpoints dédiés (Ollama, templates `prompts/image_prompts.yaml`) :

- `POST /api/ai/create-prompt` — pipeline planner → writer depuis mots-clés / titre / tags.
- `POST /api/ai/create-prompts-bulk` — même pipeline pour jusqu’à 10 concepts (éditeur images, modal bulk).
- `POST /api/ai/improve-prompt` — variantes depuis un prompt existant (ou `image_id`).
- `POST /api/ai/validate-prompt` — score + contrôles qualité avant génération.

Legacy : `POST /api/ai/generate-prompts`, `POST /api/ai/suggest-prompt`. Voir `docs/tuning-guide.md` (section workflow prompts v1).

## Worker de génération d'images

Le worker consomme les jobs `image_generation` (status=pending) et envoie le workflow ComfyUI défini dans `data/workflows/` (défaut opérationnel : `ernie-image-turbo-q8-api`; `z_image_turbo_v1` reste disponible via `workflow_template` explicite). Les paramètres de sampling peuvent être passés dans `job.config` (voir `POST /api/images/{id}/jobs` et `GET /api/generation/presets`). Le backend cible les `public_inputs` déclarés par le workflow. Guide d'affinage : `docs/tuning-guide.md`.

Après un nouvel export ComfyUI, mettre à jour le mapping des nœuds sans tout retenir : voir `data/workflows/README.md` et :

```bash
python scripts/inspect_workflow_for_mapping.py NOM_DU_TEMPLATE
python scripts/inspect_workflow_for_mapping.py NOM_DU_TEMPLATE --check
```

```bash
python scripts/run_image_worker.py          # boucle infinie (Ctrl+C pour arrêter)
python scripts/run_image_worker.py --once   # traite un seul job puis quitte
```

- Les images sont sauvegardées dans `data/outputs/`
- L'API rejette (409) si un job `pending`, `running` ou `awaiting_validation` existe déjà pour la même image
- Après génération, le job passe en `awaiting_validation` : valider ou rejeter via `POST /api/jobs/{id}/validate` (voir `docs/cli-jobs-workflow.md`)
- Avant d'executer les scripts, demarrez PostgreSQL local :
  - `docker compose up -d postgres`
  - `alembic upgrade head`
