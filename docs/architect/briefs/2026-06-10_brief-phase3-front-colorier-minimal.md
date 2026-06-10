# Brief d'exécution — Phase 3 : Front colorier minimal (viewer SVG + review admin)
Date : 2026-06-10
Destinataire : Claude Code d'exécution
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`
Pré-requis : Phase 1 (spike) PASS + Phase 2 (backend) PASS

## Contexte

Phase 2 a câblé le moteur décoloriage par défaut dans `image_post_processing_worker` : chaque image colorable produit un **SVG bicouche** dans `coloring_svg_path` (convention `data/generated/<leaf>__<variant>_coloriage.svg` via `coloring_storage`) + des métadonnées typées dans `ImageOutput.model_config` (`coloring_engine`, `level`, `n_clickable`, `n_ink_regions`, `publishable_tp`, `crayon_distribution`, `delta_e_median`, `processing_s`).

Phase 3 livre le **front colorier minimal interne** : une surface de revue (HTML servi en statique par FastAPI, pattern admin existant) qui liste les artefacts décoloriage produits et permet de les **colorier au clic** dans le navigateur. Objectif = **fonctionnel**, pas l'UX finale. L'artefact Claude Fable (UX riche) et l'intégration au site public (`ColorierApp.tsx`) sont des phases ultérieures (4+) — **ne pas les toucher ici**.

Un viewer minimal existe déjà (livré au spike) : `data/decoloriage_viewer.html` (charge un SVG via `?svg=`, champ URL ou file-picker ; palette 6 crayons + Papier ; Solution / Reset / toggle Guides) + une carte « Décoloriage - Viewer » dans `/data/admin.html`. Phase 3 le **fait évoluer en surface de revue branchée sur les artefacts réels** (liste depuis la DB), tout en conservant le chargement manuel en fallback.

État réel à connaître AVANT d'éditer (lis en entier) :
- `data/decoloriage_viewer.html` (le viewer du spike, JS click-to-fill à réutiliser)
- `data/admin.html` (carte existante + pattern des cartes)
- `src/api/routes/images.py` (routes images, `IMG_OUTPUT_COLS`, lecture `model_config`, dépendances `get_db_read`)
- `src/api/db.py` (`DBConnAdapter`, placeholders `?`, `get_db_read`)
- `src/services/coloring_storage.py` (convention de chemins `coloring_svg`)
- `src/api/main.py` (mount static `/data/`, montage des routers)
- la structure réelle de `ImageOutput.model_config` produite en Phase 2 (cf. `tests/test_decoloriage_phase2.py`)

## Objectif

Un éditeur ouvre l'admin → « Décoloriage », voit la **liste des artefacts décoloriage** disponibles (avec quelques métadonnées de revue), en sélectionne un → le SVG bicouche se charge dans le viewer click-to-fill et est coloriable. Le chargement manuel (URL / fichier) reste disponible en fallback.

## Décisions de cadrage à respecter
- **D5** Niveau `enfant` (les SVG produits sont enfant) — pas de sélecteur de niveau.
- **D6** Aucune migration Alembic. Lecture seule de `model_config` (JSON déjà peuplé en Phase 2).
- Front public `ColorierApp.tsx`, export `alwanbooks_pipeline`, artefact Fable : **HORS périmètre**.

## Périmètre

### DANS le périmètre

1. **API — endpoint(s) de listing (lecture seule)** dans `src/api/routes/` (nouveau routeur OU extension de `images.py`, au choix le plus cohérent) :
   - Liste les `image_output` dont `model_config` indique `coloring_engine="decoloriage"` ET possède un `coloring_svg_path`.
   - Retourne par entrée : `image_output_id`, `image_id`/leaf si dispo, `variant_name`, `coloring_svg_url` (chemin servable via le mount `/data/`, ex. `/data/generated/<...>_coloriage.svg`), et les métadonnées de revue (`n_clickable`, `n_ink_regions`, `publishable_tp`, `delta_e_median`, `crayon_distribution`).
   - **Conventions DB obligatoires** : via `get_db_read`, placeholders SQL `?` (`DBConnAdapter`), **NULL-safe** (`int(w) if w is not None else 0`), types JSON **natifs** (convertir tout `numpy.*`). Parser `model_config` (TEXT JSON) de façon défensive (peut être None / mal formé → ignorer l'entrée, pas de 500).
   - Optionnel si utile : un endpoint qui renvoie le SVG d'un `image_output_id` — mais privilégier le **chargement direct via le mount static** (`/data/generated/...svg`) pour rester simple.

2. **Viewer / surface de revue** — faire évoluer `data/decoloriage_viewer.html` (ou une page dédiée `data/decoloriage_review.html` qui réutilise le JS du viewer) :
   - Au chargement, appelle l'endpoint de listing et affiche la liste des artefacts (liste simple ou table ; Tabulator.js dispo dans le projet mais une liste sobre suffit). Colonnes utiles : leaf/variant, n_clickable, n_ink, publishable_tp, ΔE médian.
   - Clic sur une entrée → charge son `coloring_svg_url` dans le viewer click-to-fill existant.
   - **Conserve** le chargement manuel (`?svg=`, champ URL, file-picker) en fallback.
   - **Conserve** : palette 6 crayons + Papier, Solution (applique `data-color`), Reset, toggle Guides.
   - Gère le cas **liste vide** proprement (message « aucun artefact décoloriage généré pour l'instant » + fallback manuel actif).
   - Accessible depuis la carte admin (ajuster la carte existante si tu crées une page dédiée).

3. **Tests pytest** (`tests/test_decoloriage_review_api.py`), portables SQLite / sans ComfyUI :
   - Seed d'`image_output` avec `model_config` JSON contenant `coloring_engine="decoloriage"` + `coloring_svg_path` + métadonnées → l'endpoint les liste, expose `coloring_svg_url` et les métadonnées en types natifs.
   - Une entrée `coloring_engine="extract_palette"` (ou sans `coloring_svg_path`) **n'apparaît pas** dans la liste décoloriage.
   - `model_config` None / JSON invalide → entrée ignorée, **pas de 500**.
   - NULL-safe : métadonnée numérique absente/NULL → 0/0.0, pas de `TypeError` au tri.

4. **Lancer** `pytest tests/test_decoloriage_review_api.py` + une passe de non-régression sur `src/api/routes/images.py` (tests images existants) et garder la sortie.

### HORS périmètre (ne pas faire)
- `ColorierApp.tsx`, site alwanbooks, export pipeline (Phase 4).
- Intégration de l'artefact Claude Fable (phase ultérieure).
- Écriture/édition des artefacts (sauvegarde des coloriages utilisateur, persistance) — c'est un viewer de revue, pas un éditeur persistant.
- Migration Alembic, nouvelle table, modification du schéma DB.
- Sélecteur de niveau (tout-petit/adulte), re-tuning moteur.

## Critères d'acceptation
1. Endpoint de listing fonctionnel : renvoie les artefacts décoloriage avec `coloring_svg_url` servable + métadonnées, en JSON natif, NULL-safe, via `get_db_read` + placeholders `?`.
2. Une entrée non-décoloriage (extract_palette / sans coloring_svg_path) est exclue ; un `model_config` invalide/None n'provoque pas de 500.
3. Viewer : liste les artefacts, clic → charge le SVG dans le click-to-fill (palette 6 crayons + Papier, Solution, Reset, Guides) ; fallback manuel conservé ; cas liste vide géré ; accessible depuis l'admin.
4. `pytest tests/test_decoloriage_review_api.py` vert + aucune régression sur les tests images existants, sans Postgres.
5. Aucune migration Alembic ; front public / export / extract_palette non touchés.
6. **Rapport** `docs/reports/2026-06-10_phase3-front-colorier-minimal.md` (Contexte / Résultats / Points d'attention / Décision) : route(s) ajoutée(s) (fichier:lignes + méthode/chemin), contrat JSON du listing, fichiers front, sortie pytest, et description de l'usage (comment un éditeur ouvre et colorie). Verdict explicite : **Phase 3 PASS** / **blocage** / **pivot**.

## Conventions (rappel projet)
- Reporting obligatoire AVANT de clore.
- `PYTHONPATH=src`. Tests portables SQLite, jamais Postgres. `get_db_read`/`get_db_write` (pas de `SessionLocal()` brut). Placeholders SQL `?` via `DBConnAdapter`. NULL-safe + types JSON natifs.
- Tout livrable HTML reste dans `data/` (servi par le mount static). Pas de framework JS (HTML + JS vanilla, Tabulator.js dispo).
- Pas de `git commit`/`push`, pas de migration sauf demande explicite.
- Vérifier l'état réel AVANT d'éditer (viewer spike, admin, routes images).

## Reporting attendu
Fichier `docs/reports/2026-06-10_phase3-front-colorier-minimal.md`. Le fichier est le livrable principal. Conclure : **Phase 3 PASS** (front fonctionnel → Phase 4 export) / **blocage : <quoi/où>** / **pivot : <ajustement>**.
Ton message final DOIT contenir : verdict, chemin du rapport, résultat pytest, route(s) ajoutée(s) (fichier:lignes + chemin HTTP), liste des fichiers créés/modifiés.
