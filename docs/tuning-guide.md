# Guide d’affinage — génération d’images (ComfyUI)

Ce document décrit une démarche fiable pour aligner la qualité des images produites par **artiste-coloriage** sur celle obtenue dans l’interface ComfyUI, puis pour optimiser le pipeline (line art, absence de couleurs parasites, etc.).

## Chaîne technique

1. L’éditeur d’images envoie un `POST /api/images/{id}/jobs` avec `prompt`, `tags` et éventuellement des **paramètres avancés** (sampler, scheduler, cfg, steps, shift, denoise, seed).
2. Ces valeurs sont stockées dans `job.config` (JSON).
3. Le worker `image_generation` lit `config`, applique les **overrides** sur le template [`data/workflows/ernie-image-turbo-q8-api.json`](../data/workflows/ernie-image-turbo-q8-api.json) par défaut (ou [`data/workflows/z_image_turbo_v1.json`](../data/workflows/z_image_turbo_v1.json) si `workflow_template` vaut `z_image_turbo_v1`), puis soumet le graphe à ComfyUI.
4. Les paramètres **effectivement utilisés** sont enregistrés dans `image_output.model_config` pour la traçabilité.

Les valeurs par défaut du projet sont exposées par `GET /api/generation/presets` (listes d’options, `defaults`, `comfy_blueprint_ernie_image_turbo_q8_api`, et `comfy_blueprint_text_to_image_z_image_turbo` pour l’opt-in Z-Image). Par défaut, `defaults` suit le graphe **Ernie** (`steps`: 8, `euler` / `normal`). Pour reproduire une session **Z-Image-Turbo** (ex. `steps`: 4), choisissez le workflow `z_image_turbo_v1` et/ou appliquez le preset blueprint Z-Image dans l’éditeur, ou passez les valeurs dans `job.config`.

---

## Étape 1 — Obtenir les paramètres de référence depuis ComfyUI

Quand une image générée **directement dans ComfyUI** (ex. nœud « Text to Image (Z-Image-Turbo) ») est meilleure que celle du projet, il faut récupérer les réglages réels du sampler :

1. Générer une image satisfaisante dans ComfyUI avec le même modèle / VAE / CLIP que le workflow projet.
2. Activer le mode développeur : **Settings → Dev mode** (ComfyUI).
3. Utiliser **Save (API Format)** pour exporter le workflow au format API (JSON).
4. Dans le JSON, repérer le nœud **KSampler** (ou équivalent) et noter au minimum :
   - `sampler_name`
   - `scheduler`
   - `cfg`
   - `steps`
   - `denoise` (souvent `1.0` pour une génération complète)
5. Pour **Z-Image** : repérer le nœud **ModelSamplingAuraFlow** (ou équivalent) et noter **`shift`**. (Le workflow **Ernie** par défaut n’expose pas `shift` publiquement.)
6. Reporter ces valeurs dans le projet :
   - **Défauts du graphe** : champs correspondants dans `data/workflows/<template>.json`.
   - **Défauts du worker** : valeurs passées à `config.get(..., défaut)` dans [`src/workers/image_worker.py`](../src/workers/image_worker.py) (deux jeux de défauts : Ernie vs Z-Image).
   - **Défauts API / UI** : objet `DEFAULTS` dans [`src/api/routes/generation.py`](../src/api/routes/generation.py) pour que l’endpoint `/api/generation/presets` reste cohérent avec le workflow par défaut.

Tant que les trois sources (JSON workflow, worker, `DEFAULTS`) divergent, le comportement « sans paramètres dans le job » peut ne pas correspondre à ComfyUI.

---

## Étape 2 — Protocole de tests A / B

1. Choisir **3 à 5 prompts représentatifs** (animaux, véhicules, paysages, personnages, scènes chargées).
2. Pour chaque prompt, fixer un **seed** explicite (ex. `42`) via le panneau « Paramètres avancés » de l’éditeur d’images, afin de pouvoir comparer uniquement un paramètre à la fois.
3. **Ne faire varier qu’un seul paramètre** entre deux runs (ex. `shift` = 1.5, puis 3, puis 6).
4. Comparer les sorties dans [`data/jobs_editor.html`](../data/jobs_editor.html) : le `config` du job et le `model_config` de l’output conservent les valeurs utilisées.

Documenter dans un tableur ou un fichier markdown : `prompt_id`, `seed`, paramètre modifié, chemin du fichier output, note subjective (1–5).

---

## Étape 3 — Grille de qualité (line art / coloriage)

| Critère | Description |
|--------|-------------|
| Noir et blanc | Pas de couleurs parasites ; pas de gris de remplissage si le brief impose du line art pur. |
| Traits | Contours nets, épaisseur relativement homogène. |
| Fond | Fond blanc ou très clair si demandé dans le prompt. |
| Zones coloriables | Formes fermées, peu de zones ambiguës ou coupées. |
| Artefacts | Pas de texte illisible, doubles contours graves, ou déformations structurelles majeures. |

Adapter la grille si le produit cible un style différent (ex. esquisse grise volontaire).

---

## Étape 4 — Figer les bons défauts

Une fois un jeu de paramètres validé :

1. Mettre à jour les valeurs par défaut dans `z_image_turbo_v1.json`.
2. Mettre à jour les `config.get(..., défaut)` dans `image_worker.py`.
3. Mettre à jour `DEFAULTS` (et les listes `SAMPLER_NAMES` / `SCHEDULERS` si de nouveaux choix sont pertinents) dans `generation.py`.
4. Consigner dans ce fichier (section ci-dessous ou changelog interne) **la date**, **les valeurs retenues** et **une phrase de justification** (ex. « aligné sur export API ComfyUI du … »).

---

## Étape 5 — Itération continue

- Le panneau **Paramètres avancés** dans le modal Jobs de l’éditeur d’images permet d’expérimenter **sans redéployer** le code pour chaque test.
- Les jobs terminés gardent l’historique dans la base ; réutiliser les mêmes prompts + seeds pour comparer des changements de workflow (nouvelle version du JSON).

---

## Workflow prompts v1 (Ollama / Z-Image-Turbo)

Depuis la refonte « pipeline prompt », l’éditeur d’images et l’API exposent **trois actions explicites** (en plus des endpoints legacy) :

| Action | Endpoint | Rôle |
|--------|----------|------|
| **Créer depuis mots-clés** | `POST /api/ai/create-prompt` | Deux appels LLM : `prompt_planner` (plan JSON) → `prompt_writer_zimage` (prompt final structuré). |
| **Améliorer prompt** | `POST /api/ai/improve-prompt` | Variantes à partir du prompt courant (`improve_prompt_zimage`). |
| **Valider prompt** | `POST /api/ai/validate-prompt` | Score 0–100 + liste `checks` + `recommendations` (`validate_prompt_zimage`). |
| **Créer en masse (éditeur)** | `POST /api/ai/create-prompts-bulk` | Jusqu’à 10 concepts : même pipeline planner → writer par item ; option `validate_prompts` pour un score par ligne. |

**Corps JSON typiques**

- **create-prompt** : au moins `keywords` *ou* `title` ; optionnel `tags_context`, `profile` (défaut `kids_coloring_lineart_v1`).
- **create-prompts-bulk** : `items` (liste de `{ image_id?, keywords?, title?, tags_context?, profile? }`), `validate_prompts` (bool), `model` / `temperature` optionnels. Réponse : `results[]` avec `ok`, `prompt`, `plan`, `validation?`, `error?` ; `summary` avec `total`, `success`, `failed`.
- **improve-prompt** : `prompt` non vide, ou `image_id` pour charger titre/prompt/tags depuis la base ; `count` 1–5.
- **validate-prompt** : `prompt` obligatoire ; `profile` optionnel.

**Réponses**

- `create-prompt` renvoie `prompt`, `plan` (objet JSON du planner), et les métadonnées modèle/température par étape.
- `validate-prompt` renvoie `score` (entier clampé 0–100), `checks` (liste d’objets ou de chaînes selon le modèle), `recommendations` (liste de chaînes).

**Exemple (mots-clés → prompt)**

1. Saisir dans l’UI : mots-clés `ferme, vaches, tracteur` + titre optionnel.
2. Cliquer **Créer depuis mots-clés** : le planner remplit sujet / cadre / contraintes ; le writer produit un prompt line-art cohérent pour Z-Image.
3. Avant de lancer un job image, utiliser **Valider prompt** : un score bas ou des checks en échec invitent à réécrire ou à utiliser **Améliorer prompt**.

Les templates YAML vivent dans [`prompts/image_prompts.yaml`](../prompts/image_prompts.yaml) (`prompt_planner`, `prompt_writer_zimage`, `improve_prompt_zimage`, `validate_prompt_zimage`). Les endpoints historiques `POST /api/ai/generate-prompts` et `POST /api/ai/suggest-prompt` restent disponibles pour compatibilité.

---

## Références rapides

| Élément | Emplacement |
|--------|-------------|
| Overrides du graphe | `data/workflows/z_image_turbo_v1.json` → `__meta__.overrides` |
| Application des overrides | `src/workers/comfy_client.py` → `apply_overrides` |
| Lecture `job.config` + envoi ComfyUI | `src/workers/image_worker.py` |
| Création du job + `config` | `src/api/routes/images.py` → `CreateJobPayload`, `create_job` |
| Presets pour l’UI | `GET /api/generation/presets` |
| Prompts image (planner / writer / improve / validate / bulk) | `prompts/image_prompts.yaml` + `POST /api/ai/create-prompt`, `/create-prompts-bulk`, `/improve-prompt`, `/validate-prompt` |

En cas de divergence persistante avec ComfyUI, vérifier aussi : version des custom nodes, poids du modèle, et que le **même** fichier workflow (UNET / CLIP / VAE) est bien chargé des deux côtés.
