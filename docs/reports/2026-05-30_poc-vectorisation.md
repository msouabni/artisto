# POC — Vectorisation post-ERNIE (PNG → SVG via VTracer)
Date : 2026-05-30

## Contexte
Ajout d'un service de vectorisation dans le pipeline cible :
**taxonomie → PromptGenerator → ComfyUI → QC → [Vectorizer] → SVG**.

Le service convertit les line-art ERNIE (1024×1024 ou 848×1264) en SVG **géométriquement fidèles** au raster d'entrée. Aucun enrichissement, aucune correction sémantique : un défaut 2_objets / 3_jambes / traits_flous est reproduit tel quel. Le filtrage qualité reste en amont (QC vision + humain).

Hors périmètre (phase 2 séparée) : **coloriage interactif web** — segmentation des régions blanches fermées en paths SVG remplissables. Voir §"Piste phase 2" en bas.

## Décision moteur — VTracer (Rust port via PyO3) plutôt que potrace

Mise à jour 2026-05-30 — après bench standalone `_lab/vectorize-bench/` :

| Critère | VTracer 0.6.15 | potrace 1.16 |
|---|---|---|
| Install | `pip install vtracer` (1 cmd, OS-agnostique) | binaire système (winget/apt/brew + check PATH) |
| Vitesse | 30–50 ms / image | comparable |
| API | Python natif, 12 params exposés | subprocess + intermédiaire PBM |
| Modes | spline + polygon + couleur | spline uniquement (binaire) |
| Maintenance | actif (visioncortex/vtracer, 3k★) | dormant depuis 2019 |
| Bench reel | 6 cas ERNIE x 4 presets, 0 erreur | non testé end-to-end (binaire absent du host) |

Détails : `_lab/vectorize-bench/VERDICT.md`.

## Recette technique

1. **Pre-clean OpenCV** (opt-in via `pre_clean=True`) — utile uniquement si raster dégradé :
   - `cv2.imread` GRAYSCALE
   - `medianBlur(3)` si `despeckle`
   - `normalize MINMAX`
   - Seuillage Otsu (ou adaptive 31×10 si `adaptive`)
   - Morpho CLOSE ellipse 2×2 si `close_gaps`
   - Sortie : ndarray uint8, 0=encre / 255=papier, écrit dans un tmpfile passé à VTracer.

2. **Tracé** : `vtracer.convert_image_to_svg_py(src, dst, colormode, mode, filter_speckle, corner_threshold, splice_threshold, path_precision)`.

Le pre-clean est **désactivé par défaut** : VTracer gère déjà un `filter_speckle` natif suffisant pour les sorties ERNIE propres.

## Presets prod (figés par le bench du 2026-05-30)

| Preset | Cas d'usage | mode | filter_speckle | corner | splice | path_prec | ratio PNG→SVG médian |
|---|---|---|---|---|---|---|---|
| `bw_default` | Prod générale, SVG impression/web | spline | 4 | 60 | 45 | 3 | **0.10** |
| `bw_clean` | CDN / impression légère | spline | 10 | 80 | 60 | 2 | 0.08 |
| `bw_detail` | Archivage éditorial | spline | 2 | 40 | 30 | 5 | 0.14 |
| `bw_polygon` | Piste phase 2 (coloriage interactif) | polygon | 4 | 60 | 45 | 3 | **0.03** |

## Livrables

| Fichier | Rôle |
|---|---|
| `src/services/vectorizer.py` | Service importable : `VectorizeParams`, `VectorizeResult`, `Vectorizer`, `PRESETS`. Constructeurs : `Vectorizer(params)` ou `Vectorizer.from_preset(name, **overrides)`. |
| `scripts/vectorize_cli.py` | CLI 2 sous-commandes : `run <folder> --out data/svg/` (SVG prod) et `report <folder> --out <html> --max N` (HTML auto-contenu). `--preset` + 12 overrides explicites. |
| `requirements-vectorize.txt` | `vtracer>=0.6.15`, `opencv-python-headless>=4.9`, `numpy>=1.24`. Aucun binaire système requis. |
| `scripts/_vectorize_smoketest.py` | Smoke test : génère 3 PNG synthétiques, lance les 4 presets + un cas pre_clean, vérifie SVG non vides et tmp nettoyé. |
| `_lab/vectorize-bench/bench.py` + `VERDICT.md` + `report.html` | Sandbox de benchmark — outil durable pour re-tester avec d'autres presets / images. |

## Commandes

```bash
# Installation
pip install -r requirements-vectorize.txt

# Vectorisation prod (chemin arbitraire — sortie ComfyUI externe au repo)
python scripts/vectorize_cli.py run "/chemin/comfy/output/" --out data/svg/

# Variante avec preset spécifique
python scripts/vectorize_cli.py run "/chemin/comfy/output/" --out data/svg/ --preset bw_clean

# Rapport HTML auto-contenu (visualiser les SVG inline)
python scripts/vectorize_cli.py report "/chemin/comfy/output/" \
    --out docs/reports/2026-MM-JJ_vectorize_review.html --max 30 --preset bw_default

# Pre-clean OpenCV (si raster dégradé)
python scripts/vectorize_cli.py run "/chemin/comfy/output/" --out data/svg/ --pre-clean

# Smoke test
python scripts/_vectorize_smoketest.py

# Re-bench (sandbox)
python _lab/vectorize-bench/bench.py
```

## Résultats des tests (2026-05-30)

### Smoke test (3 PNG synthétiques + 4 presets + pre_clean)

| Check | Statut | Détail |
|---|---|---|
| Génération PNG synthétiques | OK | 512×512 dégradés gris + speckle (poivre 0.3–0.5 %, bruit gaussien σ=12). |
| Preset `bw_default` | **OK** | HTML 287 KB, 3 SVG inline, 6 paths. |
| Preset `bw_clean` | **OK** | HTML 286 KB. |
| Preset `bw_detail` | **OK** | HTML 279 KB. |
| Preset `bw_polygon` | **OK** | HTML 263 KB. |
| `bw_default` + `--pre-clean` | **OK** | HTML 313 KB (intègre le PNG nettoyé en plus). |
| Nettoyage tmp | **OK** | Aucun dossier `vectorize_report_*` résiduel dans %TEMP%. |

**VERDICT : PASS sur l'intégralité.**

### Bench end-to-end (6 PNG ERNIE réels × 4 presets, `_lab/vectorize-bench/`)

| Cas | source KB | bw_default KB | bw_clean KB | bw_detail KB | bw_polygon KB | paths default | ms default |
|---|---:|---:|---:|---:|---:|---:|---:|
| lion savanna | 753 | 85 | 69 | 113 | 23 | 42 | 43 |
| claw hammer | 372 | 24 | 20 | 33 | 7 | 16 | 35 |
| letter_a + apple | 587 | 21 | 17 | 28 | 7 | 7 | 33 |
| child running | 375 | 61 | 52 | 76 | 16 | 24 | 38 |
| iron man | 557 | 134 | 108 | 152 | 30 | 29 | 48 |
| french bulldog | 551 | 45 | 37 | 58 | 13 | 27 | 46 |

Médianes : **35–45 ms** par image, ratio compression PNG→SVG = **0.06–0.18** (default), **0.02–0.06** (polygon). 0 erreur sur 24 traces.

## Limite cadrée (fidèle ≠ correctif)

Le service est **descripteur, pas correctif**. Il ne corrige aucun défaut sémantique :
- Un coloriage avec 3 jambes restera 3 jambes en SVG.
- Une scène à 2 sujets restera 2 sujets en SVG.
- Les couleurs résiduelles sont éliminées (binarisation), mais c'est un effet de bord du tracé, pas une correction du contenu.

Le filtrage qualité (QC vision + humain) reste **en amont** dans le pipeline. Le Vectorizer s'exécute uniquement sur les images déjà jugées publiables.

## Piste phase 2 — coloriage interactif web

Le preset **`bw_polygon`** est la piste sérieuse identifiée par le bench :
- SVG ×3-4 plus léger (Iron Man : 134 → 30 KB).
- Polygones droits = régions facilement identifiables pour découpage des zones blanches fermées.
- `n_subpaths` comparable au mode spline (62–199 selon complexité) → granularité suffisante.

Prochaine étape (hors périmètre actuel) : sous-bench sur 3 SVG `bw_polygon` + mini-extracteur de régions blanches fermées (algo even-odd fill rule + segmentation par cluster de coords) pour valider qu'on a bien N zones distinctes remplissables côté navigateur.

## Décision / Action suivante

- ✅ Service livré et **validé end-to-end** (smoke test PASS, bench réel sur 6 images ERNIE PASS).
- ✅ Capitalisation : section "Vectorisation post-ERNIE" mise à jour dans `CLAUDE.md` avec les 4 presets et l'API `from_preset`.
- ⏭️ Phase 2 (coloriage interactif) : démarrer le sous-bench `bw_polygon → regions` quand on l'attaquera, sur la base du sandbox `_lab/vectorize-bench/` déjà en place.
