# Artiste Coloriage — Pipeline de génération d'images

Plateforme de gestion et de génération automatique d'images de coloriage (line art), depuis la taxonomie des thèmes jusqu'à la publication multi-sites. Le pipeline couvre la gestion de la taxonomie, la génération de prompts par IA (Ollama), la génération d'images (ComfyUI) et la gestion éditoriale des contenus.

---

## Architecture globale

```
┌─────────────────────────────────────────────────────────────────┐
│                     Interfaces Web (HTML)                       │
│   admin · images_editor · jobs_editor · taxonomy_editor · sites │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────────────────┐
│                  FastAPI  (src/api/main.py)                      │
│  /api/taxonomy  /api/ai  /api/images  /api/jobs  /api/sites     │
└────┬─────────────────────────────────────────┬──────────────────┘
     │ PostgreSQL (Docker)                     │ HTTP
┌────▼──────────────────┐          ┌──────────▼──────────────────┐
│  postgres:5432        │          │  Ollama  (localhost:11434)   │
│  artiste_coloriage    │          │  modèle : qwen2.5:7b         │
└───────────────────────┘          └─────────────────────────────┘
     │
┌────▼──────────────────────────────────────────────────────────┐
│                  Workers (scripts/run_*.py)                    │
│  ImageWorker ──────────────────────────► ComfyUI (:8188)      │
│  TextWorker  ──────────────────────────► Ollama  (:11434)     │
└───────────────────────────────────────────────────────────────┘
```

---

## Pile technique

| Composant | Technologie |
|-----------|-------------|
| API | FastAPI + Uvicorn |
| Base de données | PostgreSQL 16 (Docker) |
| IA / LLM | Ollama (`qwen2.5:7b` par défaut) |
| Génération d'images | ComfyUI (workflow JSON) |
| UI | HTML + Tabulator.js (sans framework JS) |
| Tests | pytest + httpx |

---

## Structure du projet

```
artiste-coloriage/
├── src/
│   ├── api/
│   │   ├── main.py             # App FastAPI, middlewares, montage routes
│   │   ├── db.py               # Sessions SQLAlchemy (PostgreSQL)
│   │   ├── helpers.py          # Utilitaires partagés
│   │   ├── job_review_artifact.py  # Contrat job.result (revue v1)
│   │   ├── job_review_apply.py     # Apply/reject métier (image_generation)
│   │   └── routes/
│   │       ├── taxonomy.py     # CRUD taxonomie / termes
│   │       ├── ai.py           # Endpoints Ollama (prompts, enrichissement)
│   │       ├── images.py       # CRUD images + jobs de génération
│   │       ├── jobs.py         # Queue, diff, validate, enqueue
│   │       └── sites.py        # CRUD sites de publication
│   ├── workers/
│   │   ├── base_worker.py      # Worker abstrait (heartbeat, retry, queue)
│   │   ├── image_worker.py     # Worker image_generation (ComfyUI)
│   │   ├── text_worker.py      # Worker text_enrichment (Ollama)
│   │   └── comfy_client.py     # Client HTTP ComfyUI
│   ├── artiste_logging.py      # Logging console + fichier rotatif par composant
│   ├── taxonomy.py             # Logique métier taxonomie
│   ├── services/               # ollama_json (partagé worker / scripts)
│   ├── cli.py                  # Typer (`jobs enqueue-text`, `diff`, `validate`)
│   └── image_generation.py     # (hors pipeline principal)
├── data/
│   ├── workflows/                # Templates workflow ComfyUI (JSON)
│   ├── schema.sql                # Schéma complet
│   ├── migration_v*.sql          # Migrations incrémentales
│   ├── workflows/                # Templates workflow ComfyUI (JSON)
│   ├── outputs/                  # Images générées (runtime)
│   ├── shared/                   # editor-core.js, editor-core.css, utils.js
│   └── *.html                    # Interfaces web
├── prompts/
│   ├── taxonomy_prompts.yaml     # Prompts LLM pour la taxonomie
│   └── image_prompts.yaml        # Prompts LLM pour les images
├── scripts/                      # Initialisation, migrations, seeds, workers
├── docs/
│   └── use-cases/                # use_cases.yaml — spécifications fonctionnelles
├── tests/                        # Tests pytest
└── requirements.txt
```

---

## Pipeline image — statuts et transitions

Le cycle de vie d'une image suit un statut qui progresse automatiquement à chaque étape du pipeline :

```
draft
  │  [auto] PUT /api/images/{id} avec prompt non vide
  ▼
prompt_ready
  │  [auto] POST /api/images/{id}/jobs  (création d'un job de génération)
  ▼
scheduled
  │  [auto] ImageWorker.fetch_and_start()
  ▼
generating
  │  [auto] ImageWorker.save_result() — job → awaiting_validation, fichier dans image_output
  │  [manuel] POST /api/jobs/{id}/validate { "action": "apply" } (ou reject → prompt_ready)
  ▼
generated
  │  [manuel]
  ▼
approved / rejected
  │  [manuel]
  ▼
published
```

**Règles :**
- Tant que le job est en `awaiting_validation`, l’image reste en `generating` jusqu’à apply (ou reject). Voir [docs/cli-jobs-workflow.md](docs/cli-jobs-workflow.md).
- Le statut ne rétrograde jamais automatiquement (sauf en cas d'erreur ComfyUI : `generating` → `scheduled`, ou reject explicite).
- L'utilisateur peut forcer un statut à tout moment via les éditeurs web.
- Si ComfyUI est indisponible : le type `image_generation` est auto-désactivé, le job reste en `pending`, l'image revient à `scheduled`. L'utilisateur réactive manuellement via la page Jobs.

---

## Queue de jobs

Le système de jobs est générique et extensible (`job_type_config`).

### Types de jobs actifs

| Type | Worker | Rôle |
|------|--------|------|
| `image_generation` | `ImageWorker` | Génération d'image via ComfyUI |
| `text_enrichment` | `TextWorker` | Enrichissement de termes via Ollama |

### CLI (Typer)

Depuis la racine du projet avec `PYTHONPATH=src` : `python -m cli --help` (taxonomie locale) et `python -m cli jobs --help` (client HTTP vers l’API : enqueue texte, diff, validate). Guide détaillé : [docs/cli-jobs-workflow.md](docs/cli-jobs-workflow.md).

### Mécanique (base_worker.py)

- **fetch_and_start** : prend le prochain job `pending` (ordre priorité ASC, date ASC), vérifie que le type est activé et qu'aucun job ne tourne déjà (`max_concurrent=1`), passe le job en `running`.
- **Heartbeat** : thread daemon toutes les 30 s — évite les jobs fantômes.
- **Stale recovery** : jobs `running` sans heartbeat depuis > 5 min remis en `pending`.
- **Retry / backoff** : 3 tentatives max, délais 1 min → 5 min → 15 min.
- **Activation / désactivation** : chaque type peut être activé/désactivé via l'API (`PUT /api/jobs/types/{job_type}`) ou automatiquement par le worker en cas d'erreur.

---

## API REST

Démarrée sur `http://127.0.0.1:8000`.

### Taxonomie — `/api/taxonomy`

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/taxonomy` | Arbre complet |
| GET | `/api/taxonomy/vocabularies/{vocab}/terms` | Termes d'un vocabulaire |
| POST/PUT/DELETE | `/api/taxonomy/vocabularies/{vocab}/terms/…` | CRUD termes |
| GET | `/api/taxonomy/terms/search` | Recherche |
| GET | `/api/taxonomy/export/json` | Export JSON |
| POST | `/api/taxonomy/vocabularies/{vocab}/import/diff` | Import avec diff |

### IA / Ollama — `/api/ai`

| Méthode | Chemin | Description |
|---------|--------|-------------|
| POST | `/api/ai/enrich-term` | Enrichir un terme (descriptions, mots-clés) |
| POST | `/api/ai/enrich-terms-batch` | Enrichissement en lot |
| POST | `/api/ai/suggest-children` | Suggérer des sous-termes |
| POST | `/api/ai/generate-vocabulary` | Générer un vocabulaire pour un thème |
| POST | `/api/ai/generate-concepts` | Générer des concepts image depuis un thème |
| POST | `/api/ai/create-prompt` | **v1** Créer un prompt image (planner → writer ; défaut Ernie, opt-in Z-Image via `workflow_template`) |
| POST | `/api/ai/create-prompts-bulk` | **v1** Créer des prompts en lot (max 10 concepts ; option validation ; même sélection de templates) |
| POST | `/api/ai/improve-prompt` | **v1** Variantes depuis un prompt existant |
| POST | `/api/ai/validate-prompt` | **v1** Score + checks qualité line-art avant génération |
| POST | `/api/ai/generate-prompts` | Générer des prompts line art *(legacy)* |
| POST | `/api/ai/suggest-prompt` | Améliorer un prompt existant *(legacy)* |
| GET | `/api/ai/status` | Statut Ollama + modèles disponibles |
| GET/PUT/POST | `/api/ai/prompts/…` | Gestion des templates de prompts |

### Images — `/api/images`

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/images` | Liste (filtres : status, origin, batch, status_in) |
| POST | `/api/images` | Créer un concept image |
| GET/PUT/DELETE | `/api/images/{id}` | CRUD image |
| POST | `/api/images/{id}/jobs` | Créer un job de génération |
| GET | `/api/images/{id}/jobs` | Jobs de l'image |
| GET/POST | `/api/images/{id}/outputs` | Outputs générés |
| PUT | `/api/images/{id}/outputs/{out}/select` | Sélectionner l'output actif |
| GET/PUT | `/api/images/{id}/tags` | Tags taxonomiques |

### Jobs — `/api/jobs`

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/jobs` | Liste (filtres étendus) |
| GET | `/api/jobs/stats` | Compteurs par type et statut |
| GET/PUT | `/api/jobs/types/{type}` | Config d'un type (activer/désactiver) |
| POST | `/api/jobs/{id}/reschedule` | Reprogrammer un job échoué |
| POST | `/api/jobs/{id}/cancel` | Annuler |
| GET | `/api/jobs/{id}/diff` | Diff avant validation (text jobs) |
| POST | `/api/jobs/{id}/validate` | Appliquer ou rejeter un résultat |
| POST | `/api/jobs/bulk` | Actions en masse |

### Sites — `/api/sites`

CRUD complet + import avec diff pour les sites de publication.

---

## Interfaces web

Toutes servies statiquement par FastAPI sur `/data/`.

| URL | Description |
|-----|-------------|
| `/data/admin.html` | Hub d'administration |
| `/data/images_editor.html` | Éditeur des concepts images (statuts, jobs, IA, outputs, tags) |
| `/data/jobs_editor.html` | Gestionnaire de la queue de jobs (activation, reschedule, validation) |
| `/data/taxonomy_editor.html` | Éditeur de la taxonomie universelle |
| `/data/sites_editor.html` | Éditeur des sites de publication |

---

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL du serveur Ollama |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Modèle LLM utilisé |
| `OLLAMA_TIMEOUT` | `60` | Timeout des requêtes Ollama (secondes) — côté API Python |
| `COMFY_URL` | `http://127.0.0.1:8188` | URL de ComfyUI |
| `COMFY_POLL_INTERVAL` | `2.0` | Intervalle de polling ComfyUI (secondes) |
| `COMFY_TIMEOUT` | `300` | Timeout total de génération ComfyUI (secondes) |
| `ARTISTE_LOG_LEVEL` | (voir ci-dessous) | Niveau global : `DEBUG`, `INFO`, `WARNING`, etc. Si absent : `DEBUG` pour l'API, `INFO` pour les workers |
| `ARTISTE_LOG_DIR` | `logs/` à la racine du dépôt | Dossier des fichiers `.log` (chemin absolu ou relatif) |
| `ARTISTE_LOG_TO_FILE` | `1` (hors tests) | Mettre `0`, `false` ou `no` pour n'écrire que sur la console (pas de fichier) |
| `ARTISTE_API_PORT` | `8000` | Port de l'API (utilisé par [`start.py`](start.py) et documenté dans le récapitulatif) |
| `COMFYUI_HOME` ou `COMFYUI_ROOT` | (vide) | Dossier du clone ComfyUI (fichier `main.py`) pour lancer Comfy depuis [`start.py`](start.py). Si les deux sont absents, le script tente automatiquement `../comfy/ComfyUI` puis `../ComfyUI` par rapport à la racine du dépôt. |
| `COMFYUI_PYTHON` | (auto) | Exécutable pour lancer `main.py` : sinon recherche de `venv` / `.venv` / `python_embeded` sous le dossier Comfy, puis `sys.executable`. |

> `OLLAMA_TIMEOUT` contrôle le timeout de la requête HTTP faite par l'API FastAPI vers Ollama. Le serveur Ollama lui-même n'a pas de timeout configurable depuis ce projet.

**Choix des modèles LLM** (priorités UI / YAML / env, historique des changements, batch, impact perf, pistes queue) : voir [docs/ai-model-strategy.md](docs/ai-model-strategy.md).

---

## Logs

Chaque processus configure le logging via [`src/artiste_logging.py`](src/artiste_logging.py) : messages sur **stderr** et, par défaut, dans un **fichier rotatif** UTF-8 (10 Mo × 5 archives) sous le dossier des logs.

| Fichier | Composant |
|---------|-----------|
| `logs/api.log` | API FastAPI (`uvicorn api.main:app`) |
| `logs/image_worker.log` | `scripts/run_image_worker.py` |
| `logs/text_worker.log` | `scripts/run_text_worker.py` |

Les tests pytest fixent `ARTISTE_LOG_TO_FILE=0` dans `tests/conftest.py` : aucun fichier n'est créé pendant `pytest`.

**Uvicorn `--reload`** : le reloader et le worker enfant peuvent tous deux écrire dans `logs/api.log`, ce qui peut entrelacer les lignes. En production, sans `--reload`, un seul processus écrit dans le fichier.

**Lecture en direct (PowerShell)** :

```powershell
Get-Content -Path logs\api.log -Wait -Tail 100
```

**Git Bash / WSL** :

```bash
tail -f logs/api.log
```

---

## Installation et démarrage

### Prérequis

- Python 3.11+
- [Ollama](https://ollama.com/) avec le modèle `qwen2.5:7b` : `ollama pull qwen2.5:7b`
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) démarré sur `http://127.0.0.1:8188`

### Installation

```bash
pip install -r requirements.txt
```

### Initialiser la base

```bash
python scripts/init_db.py
# Optionnel : données de démo
python scripts/seed_data.py
```

### Démarrage unifié (`start.py`)

À la racine du dépôt :

```bash
python start.py
```

Démarre par défaut **Uvicorn** (API, `--reload`), les **deux workers**, et **ComfyUI** si un clone valide est trouvé (`COMFYUI_HOME` / `COMFYUI_ROOT`, ou dossiers voisins `../comfy/ComfyUI` et `../ComfyUI`). Les composants déjà actifs (port API, port Comfy, processus workers détectés via `psutil`) ne sont pas relancés.

`start.py` est aussi **singleton** : si tu le lances une deuxième fois pendant qu’une instance tourne déjà, il quitte immédiatement (verrou fichier `start.lock` dans `ARTISTE_LOG_DIR` ou `logs/`).

**Ollama n'est jamais lancé par défaut.** Pour démarrer `ollama serve` depuis ce script si le service n'est pas joignable :

```bash
python start.py --with-ollama
```

Autres options utiles : `--no-reload` (évite le double processus uvicorn / logs `api.log` entrelacés), `--no-comfy`, `--no-image-worker`, `--no-text-worker`, `--api-port N`.

Variables : `COMFYUI_HOME` / `COMFYUI_ROOT`, `COMFYUI_PYTHON`, `COMFY_URL`, `OLLAMA_BASE_URL`, `ARTISTE_API_PORT`, `ARTISTE_LOG_DIR` (chemins des fichiers listés en fin de script). Consulter les logs : section [Logs](#logs) ci-dessus.

### Démarrer l'API seule (sans start.py)

```bash
cd src
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

- API : http://127.0.0.1:8000
- Docs Swagger : http://127.0.0.1:8000/docs
- Admin : http://127.0.0.1:8000/data/admin.html

### Démarrer les workers seuls

Dans des terminaux séparés :

```bash
# Worker de génération d'images (nécessite ComfyUI)
python scripts/run_image_worker.py

# Worker d'enrichissement texte (nécessite Ollama)
python scripts/run_text_worker.py
```

Les workers tournent en boucle infinie (`Ctrl+C` pour arrêter). Option `--once` pour traiter un seul job.

---

## Schéma de données (tables principales)

```
taxonomy / vocabulary / term          ← taxonomie universelle i18n
site                                  ← sites de publication
image                                 ← concepts images (statut, prompt, output sélectionné)
image_output                          ← fichiers PNG générés (liés à un job)
image_tag                             ← association image ↔ term (taxonomie)
job                                   ← queue de jobs (type, status, retry, heartbeat)
job_type_config                       ← activation/désactivation par type
generation_batch / concept_batch      ← campagnes de génération en lot
ai_prompt_template                    ← surcharges DB des prompts YAML
```

---

## Tests

```bash
pytest
```

Les tests utilisent une base SQLAlchemy SQLite en mémoire (fixtures), avec schéma ORM identique.

---

## Migrations

Les migrations sont gérées avec Alembic.

```bash
docker compose up -d postgres
alembic upgrade head
```
