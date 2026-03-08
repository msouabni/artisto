# Architecture Technique – Artiste Coloriage

Ce document décrit l’architecture technique cible du projet **Artiste Coloriage**, en cohérence avec le plan par phases :

- Modèles locaux en priorité.
- Taxonomie universelle comme source de vérité.
- Stockage hybride (YAML + DuckDB).
- Orchestration par script `pipeline.py`, puis intégration agent (Phase 6).

## 1. Langage et organisation du code

- **Langage** : Python 3.x.
- **Structure** :
  - `src/` : code Python (taxonomie, LLM local, génération d’images, post-traitement, pipeline, futur agent).
  - `data/` : fichiers YAML de configuration (taxonomies, sites, mapping).
  - `outputs/` : images générées, exports de collections/PDF.
  - `docs/` : documentation complémentaire.

## 2. Taxonomie et stockage

- **Taxonomie universelle** :
  - Base DuckDB : `data/artiste_coloriage.duckdb` (éditeur : `data/taxonomy_editor.html` via API FastAPI).
  - Fallback JSON : `data/taxonomy_universal_v0.json` si la base n'existe pas.
  - Chargée par `src/taxonomy.py` (`get_taxonomy()`, `get_terms_for_branch(...)`).

- **Taxonomies de sortie** :
  - Fichiers YAML dédiés par site ou famille de sites (ex. `data/taxonomy_site_fr_v1.yaml`), dérivés de la taxonomie universelle (simplification, filtrage, traduction).

- **Stockage hybride** :
  - **YAML** : vérité éditoriale pour les taxonomies, le registre de sites et les règles de dérivation.
  - **DuckDB** (`data/artiste_coloriage.duckdb`) : état dynamique du système :
    - `taxonomy`, `vocabulary`, `term` : taxonomie universelle (i18n).
    - `images`, `image_taxonomy_tag` : métadonnées images, liens taxonomie.
    - `jobs` : suivi des jobs de génération/post-traitement/export.
    - `site_publications` : quelles images sont publiées sur quels sites.
  - **API FastAPI** (`src/api/`) : expose la taxonomie et les entités pour l'éditeur et le pipeline.

## 3. Génération d'idées et de prompts (LLM)

- **LLM local en priorité** (ex. Ollama avec Llama 3 ou modèle similaire) pour :
  - Générer des **concepts** (sous-thèmes) à partir d’un thème et de la taxonomie.
  - Générer des **prompts détaillés** optimisés pour du line art (sans ombrage).
- Le module correspondant (`src/concepts.py`) :
  - Expose une fonction appelable par le pipeline et, demain, par un agent : entrée = thème + taxonomie ; sortie = JSON (concepts + prompts).
  - Peut, à terme, s’appuyer sur un LLM distant (OpenAI, Groq) en alternative, mais la cible reste le local.

## 4. Génération d'images (Line Art)

- **Solution recommandée : Génération Locale (Hugging Face Diffusers)** :
  - Modèle : Stable Diffusion XL (SDXL) ou Flux.dev avec un LoRA spécialisé « coloring book / line art ».
  - Implémentation : module `src/image_generation.py` utilisant `diffusers` lorsque l’environnement le permet.
- En parallèle, pour le MVP, un mode dégradé peut générer des images simples (ex. via Pillow) pour tester le pipeline sans gros modèle.
- Chaque image générée est :
  - Sauvegardée dans `outputs/…`.
  - Référencée dans la base DuckDB (`images` + `image_taxonomy_tag`).

## 5. Post-traitement des images

- Outils Python :
  - **Pillow** : chargement, conversion en niveaux de gris, binarisation simple, export.
  - **OpenCV (`opencv-python`)** : seuillage plus fin, débruitage, éventuelle détection de contours.
- Module `src/postprocess.py` :
  - Applique les filtres nécessaires pour obtenir un line art propre (noir/blanc).
  - Met à jour le statut de l’image dans DuckDB (ex. `raw` → `cleaned`).

## 6. Orchestration, export et monitoring

- **Pipeline principal** : `src/pipeline.py`
  - Enchaîne : saisie du thème → lecture taxonomie → concepts/prompts → génération d’images → post-traitement → export.
  - Produit des collections dans `outputs/<slug_theme>/` avec, si besoin, un PDF pour impression.

- **Monitoring** :
  - S’appuie sur les tables DuckDB (`jobs`, `images`, `site_publications`) pour suivre :
    - Statut des jobs (en cours, réussi, en erreur).
    - Couverture de la taxonomie (combien d’images par branche).
    - Publication par site (retard, erreurs, etc.).

## 7. Intégration d’un agent (Phase 6)

- Le système est conçu pour qu’un agent (ex. avec LangGraph) puisse :
  - Observer l’état (taxonomie, images, jobs, publications).
  - Décider des actions (quels thèmes traiter, quels prompts relancer, quelles images publier où).
  - Appeler les **outils** exposés par les modules (`taxonomy`, `concepts`, `image_generation`, `postprocess`, `export`).
- Les modifications critiques (taxonomie universelle, validation des taxonomies de sortie) restent sous contrôle humain ; l’agent propose, l’humain valide.

