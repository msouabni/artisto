# Transition style pastel + promotion extract-palette en prod
Date : 2026-05-31

## Contexte

Adoption du **style pastel par défaut** dans le pipeline artiste-coloriage + promotion du sandbox `_lab/extract-palette/` en service prod, après validation sur 47 PNG ERNIE pastel + 3 leafs taxonomie réels.

Décision : promotion complète avec **traçabilité du changement** + **procédure rollback** documentée et testable.

## Changements appliqués

### 1. PromptGenerator — paramètre `style`

`src/services/prompt_generator.py` :

- **Param ajouté** : `build_prompt(leaf_id, style=None)` (lecture dynamique de `os.environ["ARTISTE_PROMPT_STYLE"]` ou `"pastel"` par défaut)
- **Champ ajouté** au dict retourné : `'style': effective_style` (= 'pastel' ou 'lineart')
- **Fonction `_pastelize_prompt(positive, negative)`** : transformation élégante validée sur 3 leafs taxonomie

| Aspect | Lineart (avant) | Pastel (après) |
|---|---|---|
| Header positif | `coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, …` | `soft pastel children's coloring illustration, …` |
| Suffixe positif | (aucun) | `, thick black outlines preserved around every region, filled with a soft pastel palette (pale yellow, peach, sky-blue, mint, lavender, blush-pink, sand, cream), each region one uniform color, no gradients` |
| Négatif retiré | – | `no colors`, `no fill colors`, `no intersection`, `no change in ink transparency …` |
| Négatif ajouté | – | `photographic, realistic, 3d render, gradient fill, soft shading transitions, blurry edges, dark colors, neon, oversaturated, painterly, line art only, uncolored` |

**Préservation** : sujet, isolation, contraintes anatomiques.

### 2. Service extract_palette

`src/services/extract_palette.py` : copie nettoyée depuis `_lab/extract-palette/extract.py`.

API publique :

```python
from services.extract_palette import (
    extract_palette,        # extract(png_path, params) -> PaletteResult
    make_params,            # construit ExtractPaletteParams depuis preset + overrides
    render_svg,             # PaletteResult -> SVG string (full / regions / blank_outlined / …)
    PROD_PRESET,            # = "iso_trait_v3_anomaly_split"
    PRESETS,                # dict de 46 presets historiques (immutable)
)
```

**Preset prod** : `iso_trait_v3_anomaly_split` (détection anomalie auto-correctif via re-k-means k=2 LAB local sur composantes > 30 % du canvas).

### 3. CLI

`scripts/extract_palette_cli.py` : sous-commandes `run`, `coloriage`, `bench`.

### 4. Tests

| Test | Statut |
|---|---|
| `tests/test_prompt_generator.py` (legacy) | **124 passants** avec `ARTISTE_PROMPT_STYLE=lineart` (conftest fixe l'env) |
| `tests/test_prompt_generator_pastel.py` (nouveau) | **14 passants** dédiés au mode pastel |

Total : **138 tests passants**, zéro régression.

### 5. Documentation

- `CLAUDE.md` : nouvelle section "Style pastel + pipeline coloriage" (avant section vectorisation)
- `requirements-extract-palette.txt` : vtracer + opencv + numpy + scipy + scikit-image
- Mémoires persistantes : `project_extract_palette_prod.md` mis à jour

## Validation production

| Lot | Volume | Couverture régions | Constat |
|---|---:|---:|---|
| Pastel initial | 7 PNG | 95–100 % | ★ production-ready |
| Pastel étendu | 47 PNG | 95–100 % | ★ production-ready |
| Taxonomie réelle | 3 leafs | 99.2–99.8 % | ★ pipeline complet validé |
| Vector flat | 8 PNG | – | abandonné (anomaly_split fragmente le fond multi-couleurs ; à reprendre dans un POC dédié) |

**Cas réels validés** : polar_bear_on_ice (`aldb-alqtby`), carpet_cleaner (`ala-tnzyf-alsjad`), bengal_tiger (`alnmr-albnghaly`).

## Procédure rollback

### Niveau 1 — Run isolé en lineart (sans modif code)

```bash
ARTISTE_PROMPT_STYLE=lineart python scripts/...
ARTISTE_PROMPT_STYLE=lineart python start.py
```

### Niveau 2 — Rollback global en .env

```
# .env
ARTISTE_PROMPT_STYLE=lineart
```

### Niveau 3 — Rollback complet code

1. `git revert <commit_transition>` puis `pytest` (les tests legacy doivent passer en mode lineart sans le conftest override)
2. Modifier `prompt_generator.py` : retirer la lecture env, hardcoder mode lineart si besoin
3. Modifier `extract_palette.py` : `PROD_PRESET = "iso_trait_v3_filled_no_gap_merged"` (ancien prod sans anomaly_split)
4. Re-générer les images affectées en lineart

## Décision / Action suivante

Promotion complète actée. Vérifications avant commit prod :
- [x] Tests passent (138/138)
- [x] CLI fonctionnel sur cas taxonomie
- [x] Documentation `CLAUDE.md` à jour
- [x] Procédure rollback documentée et testable
- [ ] Commit dédié avec message explicite "feat: switch default style to pastel + promote extract-palette"
- [ ] Validation user finale (lot étendu + cas taxonomie)

**Limites identifiées** :
- Mode vector flat (`E_vector` template + preset) reste un POC ouvert. Le bug "fond bicolore fragmenté" sur vector n'est pas adressé par le preset prod actuel. À reprendre dans un POC dédié si besoin produit.
- Le preset extract_palette est lent sur certaines images (jusqu'à 30 s sur cas pathologique pastel_car). Optimisations planifiées (vectoriser `_merge_small_regions` en numpy) dans `_lab/extract-palette/CAPITALISATION.md` § "Optimisations à faire".
