# Fiche — Preset prod vectorisation coloriage
Date : 2026-05-31
Statut : production validée — 47 PNG pastel ERNIE + 3 leafs taxonomie réels

**Preset** : `iso_trait_v3_anomaly_split`
**Module** : `src/services/extract_palette.py`
**Adopté en prod** : 2026-05-31 (cf. `docs/reports/2026-05-31_transition-pastel.md`)

---

## Architecture en 2 lignes indépendantes

```
PNG ERNIE pastel colorié
        │
        ├──────────────────────────────────┐
        │                                  │
        ▼                                  ▼
  LIGNE A : TRACÉ NOIR              LIGNE B : RÉGIONS COLORÉES
  (immutable, fidèle V3)            (auto-correctif, anomaly split)
        │                                  │
        ▼                                  ▼
  VTracer bw_polygon              Composantes connexes + SVG paths
        │                                  │
        └──────────────┬───────────────────┘
                       ▼
               SVG composé final
        (background blanc + regions + trait overlay)
```

Le trait et les régions sont traités sur **2 entrées d'image distinctes** (séparation actée 2026-05-30) — c'est ce qui garantit que ni l'un ni l'autre ne pollue le résultat de l'autre.

---

## LIGNE A — Détection et vectorisation du tracé noir

### Méthode

Pipeline HSV + Otsu plafonné, sur l'**image originale** (jamais simplifiée).

### Paramètres effectifs

| Paramètre | Valeur | Rôle |
|---|---:|---|
| `ink_pipeline` | `"simple"` | Pipeline historique (HSV/Otsu, vs alternative `"skeleton"`) |
| `ink_max_value` | `80` | HSV V max : pixels avec V < 80 considérés sombres = encre |
| `ink_max_saturation` | `60` | HSV S max : pixels avec S < 60 considérés peu colorés = encre |
| `use_otsu_grayscale` | `True` | Combine HSV avec Otsu grayscale (logique OR) pour rattraper l'anti-aliasing |
| `otsu_max_threshold` | `90` | Plafond dur sur Otsu : limite la prise des couleurs sombres comme trait |
| `ink_dilate` | `1` | Dilatation finale du masque trait (1 px) — couvre les pixels mixtes |
| `close_radius` | `3` | Morpho CLOSE (3 px) : ressoude les micro-coupures du trait |
| `ink_kmeans_dilate` | `2` | Dilatation **séparée** pour exclusion du k-means (n'impacte pas le trait visible) |

### Vectorisation

| Outil | Mode | Paramètres |
|---|---|---|
| **VTracer** (Rust port via PyO3) | `bw_polygon` | filter_speckle=4, corner_threshold=60, splice_threshold=45, path_precision=3 |

### Caractéristiques du trait

- **Continu** (Otsu + dilate ferment les gaps invisibles)
- **Épais** (~12-15 % du canvas en pixels, vs 4-5 % avec V1 strict)
- **Immutable** : aucun traitement de la ligne B ne peut modifier le trait visible
- **Vectorisation indépendante** : appliquée sur `ink_mask` après morpho, séparée des régions

---

## LIGNE B — Extraction et délimitation des régions colorées

### Méthode

K-means BGR sur image lissée + détection **auto-correctif** des anomalies + expansion Voronoi.

### Paramètres effectifs

| Paramètre | Valeur | Rôle |
|---|---:|---|
| `n_colors` | `12` | Nombre de couleurs k-means (ou bypass si palette imposée) |
| `kmeans_color_space` | `"bgr"` | Espace BGR (LAB possible mais non actif dans preset prod) |
| `kmeans_attempts` | `5` | Tentatives k-means pour stabilité |
| `merge_similar_delta_e` | `0.0` | **Désactivé** (le k-means BGR à n=12 suffit) |
| `expand_to_ink` | `True` | Expansion Voronoi des régions jusqu'aux pixels du trait |
| `expand_max_distance` | `0` | Pas de plafond → expansion complète |
| `simplify_ratio` | `0.0005` | Douglas-Peucker : contours 4× plus fidèles que default 0.002 |
| `region_stroke_width` | `1` | Stroke même couleur que fill (comble les micro-écarts DP) |
| `merge_small_regions_px` | `400` | Composantes < 400 px fusionnées dans voisin majoritaire (3 passes) |
| `isolate_background` | `True` | Détache fragments intérieurs partageant le label fond (passe 1) |
| `min_region_area_ratio` | `0.001` | Surface minimale d'une région = 0.1 % du canvas |
| `max_regions_per_color` | `50` | Cap dur sur le nombre de composantes par couleur |

### Détection auto-correctif (la clé du preset)

Innovation 2026-05-31 résolvant le bug "fond fuit dans la silhouette" :

| Paramètre | Valeur | Rôle |
|---|---:|---|
| `anomaly_detection_enabled` | `True` | Détection activée |
| `anomaly_size_pct_threshold` | `0.30` | Composante > 30 % du canvas = anomalie suspecte |
| `anomaly_min_delta_e` | `10.0` | ΔE LAB minimum entre les 2 sous-clusters pour valider un split |
| `anomaly_max_passes` | `2` | Multi-passes (un split peut créer une autre anomalie) |

**Algorithme** :
```
Pour chaque composante connexe d'aire > 30 % du canvas :
    Re-k-means k=2 LAB local (sur les pixels de cette composante uniquement)
    Si ΔE LAB entre les 2 sous-centres > 10 ET un seul touche le bord du canvas :
        → split confirmé (un sous-cluster = fond, l'autre = intérieur)
        → le sous-cluster intérieur reçoit un nouveau label
    Sinon (composante homogène OU 2 sous-clusters touchent le bord) :
        → laisser tel quel (zéro risque de régression)
```

**Avantages** : auto-correctif sur les bugs sans risque de régression sur les images saines. Ne touche **que** les zones suspectes.

### Vectorisation des régions

Pour chaque label :
1. `cv2.findContours` (RETR_EXTERNAL + CHAIN_APPROX_SIMPLE)
2. `cv2.approxPolyDP` (Douglas-Peucker, epsilon = 0.0005 × périmètre)
3. Émission SVG `<path d="M..L..Z" fill="rgb(...)" stroke="rgb(...)" stroke-width="1">`

Le stroke même couleur sert à combler les micro-écarts Douglas-Peucker entre régions adjacentes.

---

## Composition finale SVG

Ordre d'empilement (du fond vers le dessus) :

```
1. <rect> background blanc (toujours)
2. <g class="regions"> tous les <path> régions colorées (z-order par area DESC)
3. <g class="ink-layer"> trait noir vectorisé VTracer (pointer-events:none)
```

---

## Métriques validées en production

| Métrique | Valeur |
|---|---:|
| **Couverture régions** | 99.5 – 100 % du canvas (médiane 99.7 %) |
| **Pourcentage trait visible** | 7 – 15 % du canvas selon densité du sujet |
| **Cardinalité régions** | 23 – 140 par image (médiane ~36) |
| **Temps extraction** | 1.7 – 30 s par image (médiane ~4 s) |
| **Cas pathologique** | 30 s sur images très texturées avec beaucoup de petites composantes |

**Validation production** :
- 7 PNG pastel initial : production-ready confirmé
- 40 PNG pastel étendu (sujets variés) : production-ready confirmé
- 3 leafs taxonomie réels (polar_bear_on_ice, carpet_cleaner, bengal_tiger) : pipeline complet validé

**Limites identifiées** :
- Pipeline non couvert pour **vector flat** (fond bicolore légitime) — POC dédié à reprendre
- Performance : `_merge_small_regions` à vectoriser en numpy (× 5-10 gain estimé)

---

## API publique et usage

### Service Python

```python
from services.extract_palette import (
    extract_palette,      # extraction principale
    make_params,          # construit ExtractPaletteParams depuis preset + overrides
    render_svg,           # rendu SVG (modes : full, regions, line_only, blank_outlined, ...)
    PROD_PRESET,          # = "iso_trait_v3_anomaly_split"
    PRESETS,              # dict de 46 presets historiques
)

params = make_params(PROD_PRESET)
result = extract_palette(png_path, params)
svg = render_svg(result, mode="full")
```

### CLI

```bash
python scripts/extract_palette_cli.py run <png> --out output.svg
python scripts/extract_palette_cli.py coloriage <png> --out coloriage.html
python scripts/extract_palette_cli.py bench <folder> --out bench.html
```

### Endpoint API

```
GET /api/extract-palette/coloriage?filename=<png>&preset=iso_trait_v3_anomaly_split
GET /api/extract-palette/detect-palette?filename=<png>&n=16
```

Overrides supportés en query string : `colors`, `mask_smooth`, `merge_small`, `no_anomaly`, `lock_bg`, et 9 overrides du trait.

---

## Rollback (si besoin)

| Niveau | Action | Effet |
|---|---|---|
| 1 — preset alternatif | `make_params("iso_trait_v3_filled_no_gap_merged")` | Ancien preset (sans anomaly detection) |
| 2 — désactivation locale | `?no_anomaly=true` sur endpoint | Bypasse anomaly_detection au runtime |
| 3 — modification code | `PROD_PRESET = "iso_trait_v3_filled_no_gap_merged"` dans `src/services/extract_palette.py` | Revient au prod précédent |

Les 46 presets historiques restent **immutables** dans `PRESETS` — chaque évolution crée un nouveau preset, jamais n'écrase un existant.

---

## Dépendances

`requirements-extract-palette.txt` :
- `vtracer >= 0.6.15` (vectorisation trait, OS-agnostique via pip)
- `opencv-python >= 4.9` (k-means, morpho, contours)
- `numpy >= 1.24`
- `scipy >= 1.10` (`distance_transform_edt` pour expansion Voronoi)
- `scikit-image >= 0.22` (pipeline skeleton optionnel)

Aucun binaire système requis (potrace abandonné après bench `_lab/vectorize-bench/`).

---

## Documentation complémentaire

- **CAPITALISATION** : `_lab/extract-palette/CAPITALISATION.md` (historique évolution presets, décisions actées)
- **POC méthodologie** : `_lab/POC_METHODOLOGY.md` (sandbox isolé, presets immutables, bench multi-preset)
- **Transition pastel** : `docs/reports/2026-05-31_transition-pastel.md` (changement style par défaut + promotion service)
- **Section CLAUDE.md** : "Style pastel + pipeline coloriage" et "Playground ERNIE"
