# Brief d'exécution — Phase 2 : Industrialisation backend décoloriage
Date : 2026-06-10
Destinataire : Claude Code d'exécution
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`
Pré-requis : Phase 1 (spike) PASS — `docs/reports/2026-06-10_phase1-spike-decoloriage.md`

## Contexte

Le spike Phase 1 a prouvé la chaîne `PNG pastel → src/services/decoloriage.py (G1a→G5) → SVG bicouche → viewer`. Phase 2 **industrialise le backend** : promotion du module en service propre, et branchement dans le pipeline de post-traitement image **en remplacement** de l'étage coloriage interactif d'`extract_palette`, derrière un flag de rollback.

État réel à connaître AVANT toute édition (règle « vérifier l'état réel ») — lis-les en entier :
- `src/services/decoloriage.py` (le module spike à promouvoir) + `scripts/decoloriage_cli.py` + `tests/test_decoloriage_spike.py`
- `src/workers/image_post_processing_worker.py` (≈ l.99-200 : branche coloriage actuelle via `extract_palette` + `vectorizer`, enrichissement `model_config`)
- `src/services/coloring_storage.py` (`get_storage_paths`, convention de chemins)
- `src/workers/image_worker.py` (`_enrich_model_config_with_variant`, ≈ l.64-124)
- `src/services/extract_palette.py` (API `extract_palette`/`make_params`/`render_svg`, mode `blank_outlined` — le chemin remplacé)
- Toute lecture de `model_config` côté API/routes (`grep -rn "model_config" src/`) pour ne rien casser en aval.

## Objectif

Le pipeline de post-traitement produit l'artefact **coloriage interactif** via le **moteur décoloriage** (SVG bicouche) par défaut, avec rollback `extract_palette` par flag d'environnement. Les métadonnées décoloriage sont persistées de façon typée dans `ImageOutput.model_config`. Le tout couvert par des tests portables SQLite.

## Décisions de cadrage à respecter
- **D1** Remplacement propre : décoloriage = chemin coloriage interactif par défaut ; `extract_palette` conservé comme rollback (NE PAS le supprimer en Phase 2).
- **D4** `vectorizer` (SVG **print**, `bw_default`) **inchangé** — orthogonal, ne pas y toucher.
- **D5** Niveau **`enfant`** uniquement. `level` câblé en paramètre, tout-petit/adulte non exposés.
- **D6** **Aucune migration Alembic.** Métadonnées dans `ImageOutput.model_config` (JSON), via helper typé.
- **D7** Presets/constantes du POC **immutables** — aucun reparamétrage du moteur.

## Périmètre

### DANS le périmètre

1. **Promotion `src/services/decoloriage.py` en service propre** (sans changer les presets/résultats numériques) :
   - Dataclasses claires (`DecoloriageResult`, `RegionMeta`) — déjà présentes, à solidifier (types natifs JSON-sérialisables, NULL-safe sur les champs numériques).
   - Logging via `src/artiste_logging.py::setup_logging` (composant cohérent), gestion d'erreurs explicite (image illisible, 0 région, masque de traits vide → exception claire, pas de crash silencieux).
   - Une méthode/fonction de **sérialisation des métadonnées** (`DecoloriageResult.to_metadata() -> dict` JSON-safe : `coloring_engine="decoloriage"`, `level`, `n_clickable`, `n_ink_regions`, `publishable_tp`, `crayon_distribution`, `delta_e_median`, `processing_s`).
   - Le SVG et les fonctions cœur restent inchangés fonctionnellement (mêmes sorties que le spike).

2. **Branchement dans `image_post_processing_worker`** :
   - Extraire/identifier la production de l'artefact **coloriage interactif** (aujourd'hui `extract_palette` → `render_svg(..., mode="blank_outlined")` → `coloring_svg`).
   - Introduire une **fonction pure testable** `produce_coloring_artifact(png_path, out_svg_path, engine, level="enfant") -> dict` (ou équivalent) qui dispatche selon le moteur et retourne les métadonnées. Cela rend le branchement testable sans ComfyUI ni queue.
   - **Flag** `ARTISTE_COLORING_ENGINE` ∈ {`decoloriage` (défaut), `extract_palette` (rollback)} lu via `os.environ` (lecture à chaque appel, pattern `ARTISTE_PROMPT_STYLE`).
     - `decoloriage` → écrit le SVG bicouche dans le `coloring_svg` (chemin via `coloring_storage`) + métadonnées `model_config`.
     - `extract_palette` → comportement actuel **inchangé** (rollback).
   - Le **SVG print** (`vectorizer bw_default`) reste produit comme aujourd'hui, quel que soit le moteur coloriage (D4).
   - L'enrichissement `model_config` ajoute les clés décoloriage (via le helper typé) sans casser les clés existantes (`variant_name`, `extract_preset`, `vector_svg_path`, `coloring_svg_path`…).

3. **Tests pytest** (`tests/test_decoloriage_phase2.py`), portables SQLite / sans ComfyUI :
   - `produce_coloring_artifact(..., engine="decoloriage")` sur une **petite image fixture réelle** (réutiliser l'image du spike ou une vignette) → SVG bicouche écrit + métadonnées attendues (`coloring_engine=="decoloriage"`, `n_clickable>0`, `delta_e_median` float, `crayon_distribution` dict).
   - Dispatch flag : `engine="extract_palette"` sélectionne bien le chemin legacy (mock d'`extract_palette` acceptable pour ne pas dépendre de son preset).
   - Helper `to_metadata()` : toutes les valeurs sont JSON-sérialisables (`json.dumps` ne lève pas) et numériques natives (pas de `numpy.float64`).
   - Enrichissement `model_config` : les clés existantes sont préservées, les clés décoloriage ajoutées.
   - Le service ne touche AUCUNE base (vérifier : pas d'import qui ouvre l'engine).

4. **Lancer la suite** : `pytest tests/test_decoloriage_phase2.py tests/test_decoloriage_spike.py -v` et garder la sortie. Vérifier qu'aucune régression n'est introduite sur la zone touchée (lancer aussi les tests du worker si présents).

### HORS périmètre (ne pas faire)
- Suppression ou dépréciation d'`extract_palette` (Phase 5).
- Migration Alembic / nouvelle table / colonnes DB (D6).
- Front : `ColorierApp.tsx`, viewer prod, export `alwanbooks_pipeline` (Phases 3-4).
- Exposer tout-petit/adulte.
- Re-tuning des presets/seuils du moteur (D7).
- Génération ERNIE/ComfyUI réelle (tests sur PNG existants).

## Critères d'acceptation
1. `ARTISTE_COLORING_ENGINE=decoloriage` (ou défaut) : le post-traitement produit le SVG bicouche pour l'artefact coloriage interactif, le SVG print restant produit par `vectorizer` (D4).
2. `ARTISTE_COLORING_ENGINE=extract_palette` : comportement legacy strictement inchangé (rollback prouvé par test).
3. `ImageOutput.model_config` porte les métadonnées décoloriage typées (clés listées), sans perte des clés existantes ; tout est JSON-sérialisable (types natifs).
4. `pytest tests/test_decoloriage_phase2.py tests/test_decoloriage_spike.py` vert, sans Postgres ni ComfyUI.
5. **Aucune migration Alembic**, `extract_palette`/`vectorizer`/front non supprimés ni cassés.
6. **Rapport** `docs/reports/2026-06-10_phase2-industrialisation-decoloriage.md` (Contexte / Résultats / Points d'attention / Décision) : point d'intégration exact dans le worker (fichier:lignes), schéma des métadonnées `model_config`, sortie pytest, preuve du dispatch flag (les 2 moteurs), et liste des lecteurs `model_config` en aval impactés (ou « aucun »). Verdict explicite : **Phase 2 PASS** / **blocage** / **pivot**.

## Conventions (rappel projet)
- Reporting obligatoire AVANT de clore (POC/phase + pytest exécutés).
- `PYTHONPATH=src` (pytest.ini). Tests portables SQLite, jamais Postgres. Placeholders SQL `?` via `DBConnAdapter` si tu touches du SQL (a priori non).
- NULL-safe avant tri/retour numérique (`int(w) if w is not None else 0`) ; types JSON natifs (convertir `numpy.*`).
- Flag lu à chaque appel (pas figé à l'import), pattern `ARTISTE_PROMPT_STYLE`.
- **Pas de `git commit`/`push`, pas de migration** sauf demande explicite.
- Vérifier l'état réel du worker AVANT d'éditer ; ne pas inventer la structure.

## Reporting attendu
Fichier `docs/reports/2026-06-10_phase2-industrialisation-decoloriage.md`. Le fichier est le livrable principal. Conclure par : **Phase 2 PASS** (backend prêt → Phase 3 front) / **blocage : <quoi/où>** / **pivot : <ajustement>**.
Ton message final de retour DOIT contenir : verdict, chemin du rapport, résultat pytest (passed/failed), point d'intégration worker (fichier:lignes), liste des fichiers créés/modifiés.
