# Brief d'exécution — Phase 1 : Spike end-to-end décoloriage (1 image)
Date : 2026-06-10
Destinataire : Claude Code d'exécution
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`

## Contexte

Le POC `decoloriage-validation` est CLÔTURÉ-PASS (`docs/reports/2026-06-10_poc-decoloriage-SYNTHESE.md`). Le pipeline `ERNIE pastel → segmentation → SVG bicouche click-to-fill` est validé. On migre ce POC en prod (remplace l'étage coloriage interactif d'`extract_palette`). **Cette Phase 1 est un spike** : prouver la chaîne complète sur **1 image réelle** avant d'industrialiser. Ne PAS chercher la perfection prod ici — chercher la preuve end-to-end.

Les scripts POC source sont dans `poc/decoloriage/` : `g1a_v3_compact.py`, `g2_partition.py`, `g3_vectorize.py`, `g4_two_weight.py`, `g5_product.py`. Le cœur métier réutilisable y est mêlé au harness POC (contact sheets) — **ne porter que le cœur métier**.

Décisions de cadrage à respecter : niveau **`enfant`** uniquement (D5) ; **aucune migration Alembic** (D6) ; **presets recopiés verbatim** depuis le POC, immutables (D7) ; le `vectorizer` print n'est pas touché (D4).

## Objectif

Sur **une seule image pastel réelle**, démontrer : `PNG colorié → service décoloriage → SVG bicouche → viewer minimal qui le colorie dans le navigateur`.

## Périmètre

### DANS le périmètre
1. **`src/services/decoloriage.py`** (nouveau, niveau spike acceptable mais propre) : porter le cœur réutilisable du POC. Fonctions à reprendre (depuis g1a/g2/g3/g4/g5) :
   - segmentation : `preprocess_meanshift`, `kmeans_lab`, `connected_regions`, `merge_v3` (params G1a v3 verbatim : `k=12, sp=12, sr=24, merge_thresh=0.0005, contrast_thresh=30`)
   - partition enfant : la logique G2 niveau `enfant` (`smooth_merge_similar(thresh=12)` avec immunité `protected_ids`) + extraction du **masque de traits** (`L<25` + close 3×3)
   - vectorisation + topologie : `extract_region_polygons` (find_contours **padding sentinel** + Douglas-Peucker tol 1 + Chaikin closed 2 iter + snap-to-edges), `extract_topological_arcs`, `classify_arc_into_ink_or_shading` (overlap ≥ 60 % masque dilaté 3 px), `measure_line_thickness`, `smooth_open_arc`
   - produit G5 : `compute_ink_regions` (overlap ≥ 50 % → région-encre `#111111` pointer-events:none, exclue du compteur), `nearest_crayon` (ΔE76 Lab vers les 6 crayons), exception Papier `#ffffff` si `L*≥92`
   - crayons verbatim : Cerise `#FF2E63`, Mandarine `#FF8A2B`, Citron `#FFD60A`, Menthe `#06D6A0`, Océan `#118AB2`, Prune `#8B5CF6`
2. **Façade** `decolorize(png_path: Path, level: str = "enfant") -> DecoloriageResult` où `DecoloriageResult` (dataclass) porte au minimum : `svg: str` (SVG bicouche `<g id="fills" fill-rule="evenodd">` + `<g id="strokes" pointer-events="none">` avec `.arc-shading` masqué par défaut), `regions: list[RegionMeta]` (id, crayon_name, crayon_hex, original_hex, is_ink, delta_e), `n_clickable`, `publishable_tp: bool`, `crayon_distribution: dict`, `delta_e_median: float`.
3. **CLI minimal** `scripts/decoloriage_cli.py` : `run <png_path> --out <svg_path> --level enfant`. Produire le SVG bicouche d'**1 image réelle**. Image d'entrée recommandée : une sortie pastel existante (ex. `data/outputs/test_e2e_polar_bear_on_ice_*_pastel_chromakey.png`) ou à défaut une image du corpus POC `poc/decoloriage/` (vérifier l'existence réelle sur disque AVANT, et choisir une image disponible — règle : vérifier l'état réel).
4. **Viewer SVG minimal** : page HTML standalone (servie via le mount static FastAPI existant, ex. `data/decoloriage_viewer.html`, accessible aussi via une carte depuis `/data/admin.html`) qui : charge un SVG bicouche (chemin paramétrable ou inline), affiche la **palette 6 crayons + Papier**, fait le **click-to-fill** au clic sur une région, expose les boutons **Solution**, **Tout effacer (Reset)**, **toggle Guides**. Porter le JS depuis le HTML standalone de `g5_product.py`.
5. **Test pytest minimal** (`tests/test_decoloriage_spike.py`) : sur l'image de test, `decolorize()` renvoie un SVG non vide contenant `<g id="fills"` ET `<g id="strokes"`, `n_clickable > 0`, chaque région cliquable a un `crayon_hex` parmi la palette autorisée, au moins 1 région-encre détectée. **Portable SQLite / sans DB** (le service ne touche pas la base).

### HORS périmètre (ne pas faire)
- Intégration profonde dans `image_post_processing_worker` (Phase 2).
- Helper typé `model_config`, métadonnées DB (Phase 2).
- Refonte de `ColorierApp.tsx`, export `alwanbooks_pipeline`, dépréciation `extract_palette` (Phases 3-5).
- Exposer les niveaux tout-petit/adulte au front.
- Toute génération ERNIE/ComfyUI (on part d'un PNG déjà colorié existant).
- Crayon Noir 7e (b5), Prune (b9), mode solution paramétrable (b6).

## Critères d'acceptation
1. `python scripts/decoloriage_cli.py run <png réel> --out out.svg --level enfant` produit un SVG bicouche valide (2 groupes `fills`/`strokes`, régions-encre en `#111111` non cliquables, arcs shading masqués par défaut).
2. Les régions cliquables portent `data-region-id`, `data-color` (crayon mappé ou Papier), `data-crayon-name`.
3. Le **viewer** ouvre dans un navigateur : un clic sur une zone la remplit ; Solution applique tous les `data-color` ; Reset repasse au blanc ; Guides affiche/masque les arcs shading.
4. `pytest tests/test_decoloriage_spike.py` passe (vert), sans toucher Postgres.
5. **Rapport** `docs/reports/2026-06-10_phase1-spike-decoloriage.md` (Contexte / Résultats / Points d'attention / Décision) avec : image utilisée, nb régions cliquables, nb régions-encre, distribution crayons, ΔE médian, `publishable_tp`, temps de traitement, et capture/description du viewer fonctionnel.

## Conventions (rappel projet)
- Reporting obligatoire (déclencheur : POC/spike a tourné + pytest exécuté) — écrire le rapport AVANT de clore.
- `PYTHONPATH=src` (pytest.ini le pose déjà). Tests portables SQLite, jamais Postgres.
- NULL-safe avant tri numérique (`int(w) if w is not None else 0`).
- Presets/constantes du POC **recopiés verbatim** — aucun reparamétrage.
- Editor HTML si un livrable JSON/config est introduit (ici le viewer HTML couvre déjà le besoin de revue).
- **Pas de `git push`, pas de migration Alembic, pas de commit** sauf demande explicite.
- Dépendances : `pip install -r requirements-extract-palette.txt` couvre opencv/numpy/scipy/scikit-image. Ajouter au besoin.

## Reporting attendu
Fichier `docs/reports/2026-06-10_phase1-spike-decoloriage.md`. Le fichier est le livrable principal ; le résumé chat est optionnel. Conclure par un verdict clair : **spike PASS** (chaîne prouvée → Phase 2) / **blocage** (quoi, où) / **pivot** (ajustement proposé).
