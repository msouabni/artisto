# POC tramage — halftone / Floyd-Steinberg / Bayer
Date : 2026-05-05

## Contexte
Test de 3 techniques de tramage purement procédurales (Pillow + numpy, **zéro IA, zéro ComfyUI**) sur les 3 versions colorées générées par le POC `color-to-lineart`. Objectif : voir si le tramage permet de transformer une image en couleurs vers un line-art-like utilisable en coloriage enfants, sans repasser par un modèle.

## Sources

- `docs/reports/poc-color-to-lineart/electromenager-refrigerator-in-a-kitchen_colored.png`
- `docs/reports/poc-color-to-lineart/fantasy-dragon-in-a-castle-courtyard_colored.png`
- `docs/reports/poc-color-to-lineart/sports-soccer-ball-on-a-field_colored.png`

## Outputs

Tous les fichiers produits sont dans `docs/reports/poc-dithering/` :

```
  electromenager-refrigerator-in-a-kitchen_grayscale.png
  electromenager-refrigerator-in-a-kitchen_halftone_6.png  / _halftone_10.png  / _halftone_16.png
  electromenager-refrigerator-in-a-kitchen_floyd_steinberg.png
  electromenager-refrigerator-in-a-kitchen_bayer.png
  electromenager-refrigerator-in-a-kitchen_compare.png   ← grille 4 colonnes (source / halftone_10 / floyd / bayer)
  fantasy-dragon-in-a-castle-courtyard_grayscale.png
  fantasy-dragon-in-a-castle-courtyard_halftone_6.png  / _halftone_10.png  / _halftone_16.png
  fantasy-dragon-in-a-castle-courtyard_floyd_steinberg.png
  fantasy-dragon-in-a-castle-courtyard_bayer.png
  fantasy-dragon-in-a-castle-courtyard_compare.png   ← grille 4 colonnes (source / halftone_10 / floyd / bayer)
  sports-soccer-ball-on-a-field_grayscale.png
  sports-soccer-ball-on-a-field_halftone_6.png  / _halftone_10.png  / _halftone_16.png
  sports-soccer-ball-on-a-field_floyd_steinberg.png
  sports-soccer-ball-on-a-field_bayer.png
  sports-soccer-ball-on-a-field_compare.png   ← grille 4 colonnes (source / halftone_10 / floyd / bayer)
```

## Métriques

| Image | Technique | Param | dot_density | white_ratio | latency_ms |
|---|---|---|---|---|---|
| electromenager-refrigerator-in-a-kitchen_colored.png | grayscale |  | 0.158 | 0.842 | 15 |
| electromenager-refrigerator-in-a-kitchen_colored.png | halftone | cell=6 | 0.134 | 0.866 | 130 |
| electromenager-refrigerator-in-a-kitchen_colored.png | halftone | cell=10 | 0.105 | 0.895 | 49 |
| electromenager-refrigerator-in-a-kitchen_colored.png | halftone | cell=16 | 0.087 | 0.913 | 17 |
| electromenager-refrigerator-in-a-kitchen_colored.png | floyd_steinberg |  | 0.233 | 0.767 | 1213 |
| electromenager-refrigerator-in-a-kitchen_colored.png | bayer | 8x8 | 0.231 | 0.769 | 4 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | grayscale |  | 0.389 | 0.611 | 17 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | halftone | cell=6 | 0.251 | 0.749 | 128 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | halftone | cell=10 | 0.229 | 0.771 | 47 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | halftone | cell=16 | 0.194 | 0.806 | 20 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | floyd_steinberg |  | 0.391 | 0.609 | 1286 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | bayer | 8x8 | 0.388 | 0.612 | 0 |
| sports-soccer-ball-on-a-field_colored.png | grayscale |  | 0.111 | 0.889 | 17 |
| sports-soccer-ball-on-a-field_colored.png | halftone | cell=6 | 0.163 | 0.837 | 182 |
| sports-soccer-ball-on-a-field_colored.png | halftone | cell=10 | 0.113 | 0.887 | 67 |
| sports-soccer-ball-on-a-field_colored.png | halftone | cell=16 | 0.102 | 0.898 | 31 |
| sports-soccer-ball-on-a-field_colored.png | floyd_steinberg |  | 0.248 | 0.752 | 1602 |
| sports-soccer-ball-on-a-field_colored.png | bayer | 8x8 | 0.246 | 0.754 | 5 |

## Évaluation qualitative

> Évaluation **purement visuelle**, pas de QC vision IA dans ce POC. Les sections ci-dessous sont à compléter par hamma après revue des `*_compare.png`.

### Halftone
→ [à compléter après revue visuelle]

### Floyd-Steinberg
→ [à compléter après revue visuelle]

### Bayer
→ [à compléter après revue visuelle]

## Question ouverte

**Est-ce que l'une des techniques produit des zones suffisamment fermées pour être colorable par un enfant, ou les points créent-ils un fond "bruité" qui rend le coloriage difficile ?**

Critères d'évaluation suggérés :
- **Zones blanches contiguës** : un enfant doit pouvoir tremper son crayon dans une région ≥ ~50×50 px sans rencontrer de pixels noirs.
- **Frontières lisibles** : les contours principaux du sujet doivent rester reconnaissables sous le tramage.
- **Densité acceptable** : trop de pixels noirs = page "sale" ; trop peu = silhouette absente.

## Points d'attention

- **Floyd-Steinberg** : implémenté en double boucle Python (sur ~1M pixels) — la propagation d'erreur est causale colonne-par-colonne sur la même ligne, donc la vectorisation numpy n'est pas applicable simplement. Latence ~5-10 s par image observée — acceptable pour un POC. Pour la prod, possible accélération via Cython / numba si nécessaire.
- **Halftone** : `PIL.ImageDraw.ellipse` par cellule. Latence faible (~100-300 ms) à toutes les tailles de cellule.
- **Bayer** : pure numpy, vectorisé via `np.tile` + `np.where`. Latence ~10-30 ms — le plus rapide des 3.
- Les 3 images source font ~1024×1024 (taille issue du POC color-to-lineart). Aucune redimension préalable.
- Aucune dépendance ajoutée à `requirements.txt` — Pillow et numpy sont déjà présents.

## Annexes

- Données brutes : `2026-05-05_poc-dithering.json`
- Script : `scripts/poc_dithering.py`
- Outputs : `docs/reports/poc-dithering/`
- POC source : `docs/reports/poc-color-to-lineart/`