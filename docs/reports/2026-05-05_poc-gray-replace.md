# POC zone-selective — traitement des gris uniquement
Date : 2026-05-05

## Contexte
Test de **traitements zone-selective** sur les 3 images colorées du POC `color-to-lineart`. L'idée : préserver les contours noirs et les zones blanches, mais remplacer la **zone grise intermédiaire** par un motif (dots / hatching / stippling) plutôt que de tout convertir en B/W via dithering global. Pillow + numpy, **zéro IA**.

## Algorithme

Pour chaque pixel après conversion grayscale (L) :

- `L < 80` → **noir pur** (contour préservé)
- `L > 200` → **blanc pur** (zone vide préservée)
- `80 ≤ L ≤ 200` → **zone grise** → traitement W/D/H/S

## 4 traitements

| Code | Nom | Description |
|---|---|---|
| **W** | white | Zone grise → blanc pur. Baseline = line art brut. |
| **D** | dots | Halftone : cellule 6×6 px, cercle noir centré, rayon ∝ noirceur moyenne. |
| **H** | hatching | Lignes diagonales 45° (x+y=const), spacing variable par patch 32×32 : foncé=2px, clair=8px. |
| **S** | stippling | Points noirs aléatoires, p=(200−L)/120, seed=42. |

## Décomposition par image (zones)

| Image | contour (L<80) | zone grise (80-200) | blanc (L>200) |
|---|---|---|---|
| electromenager-refrigerator-in-a-kitchen_colored.png | 9.8% | 23.9% | 66.3% |
| fantasy-dragon-in-a-castle-courtyard_colored.png | 15.6% | 52.6% | 31.8% |
| sports-soccer-ball-on-a-field_colored.png | 7.4% | 46.2% | 46.4% |

## Métriques par variante

| Image | Variante | ink_ratio | dot_density | latency_ms |
|---|---|---|---|---|
| electromenager-refrigerator-in-a-kitchen_colored.png | W (white) | 0.098 | 0.098 | 3 |
| electromenager-refrigerator-in-a-kitchen_colored.png | D (dots) | 0.173 | 0.173 | 86 |
| electromenager-refrigerator-in-a-kitchen_colored.png | H (hatching) | 0.143 | 0.143 | 37 |
| electromenager-refrigerator-in-a-kitchen_colored.png | S (stippling) | 0.186 | 0.186 | 157 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | W (white) | 0.156 | 0.156 | 3 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | D (dots) | 0.340 | 0.340 | 115 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | H (hatching) | 0.279 | 0.279 | 29 |
| fantasy-dragon-in-a-castle-courtyard_colored.png | S (stippling) | 0.426 | 0.426 | 14 |
| sports-soccer-ball-on-a-field_colored.png | W (white) | 0.074 | 0.074 | 1 |
| sports-soccer-ball-on-a-field_colored.png | D (dots) | 0.163 | 0.163 | 92 |
| sports-soccer-ball-on-a-field_colored.png | H (hatching) | 0.153 | 0.153 | 20 |
| sports-soccer-ball-on-a-field_colored.png | S (stippling) | 0.221 | 0.221 | 12 |

> `ink_ratio` et `dot_density` sont identiques par construction : ratio de pixels noirs sur le total. Doublés pour cohérence avec les autres POC.

## Outputs

Tous les fichiers dans `docs/reports/poc-gray-replace/` :

```
  electromenager-refrigerator-in-a-kitchen_zone_W.png  / _zone_D.png  / _zone_H.png  / _zone_S.png
  electromenager-refrigerator-in-a-kitchen_compare.png   ← grille 5 colonnes (original | W | D | H | S)
  fantasy-dragon-in-a-castle-courtyard_zone_W.png  / _zone_D.png  / _zone_H.png  / _zone_S.png
  fantasy-dragon-in-a-castle-courtyard_compare.png   ← grille 5 colonnes (original | W | D | H | S)
  sports-soccer-ball-on-a-field_zone_W.png  / _zone_D.png  / _zone_H.png  / _zone_S.png
  sports-soccer-ball-on-a-field_compare.png   ← grille 5 colonnes (original | W | D | H | S)
```

## Évaluation qualitative

> Évaluation **purement visuelle** — à compléter par hamma sur les `*_compare.png`.

### Variante W (baseline white)
→ [à compléter après revue visuelle]

### Variante D (dots halftone)
→ [à compléter après revue visuelle]

### Variante H (hatching)
→ [à compléter après revue visuelle]

### Variante S (stippling)
→ [à compléter après revue visuelle]

## Question ouverte

Comparé au POC `dithering` (qui transforme TOUTE l'image, contours compris), cette approche **préserve les contours noirs** et ne traite que les zones grises ambiguës. Question :

**Est-ce que ce contraste (contours nets + zone grise texturée) donne un résultat plus exploitable comme page de coloriage qu'un line art brut (variante W) ou qu'un dithering global (POC précédent) ?**

Critères suggérés :
- **Lisibilité du sujet** : les contours principaux restent-ils bien définis sous le motif appliqué dans la zone grise ?
- **Densité du motif dans les zones grises** : trop dense → l'enfant ne peut pas colorier ; trop épars → l'effet décoratif disparaît.
- **Continuité visuelle** : hatching et dots créent-ils un rendu "esquisse" (pro) ou un fond bruité (parasite) ?

## Points d'attention

- **Seuils L<80 / L>200** : choisis par défaut. Si trop de pixels finissent en "contour noir" (zones très foncées de l'image colorée), envisager un seuil plus bas (50). Si trop peu (image plate), monter le seuil de blanc (180).
- **Stippling reproductible** : seed fixe (42) pour que les runs successifs produisent exactement les mêmes points. Pour A/B test sur seeds différents, exposer le paramètre.
- **Hatching** : la vectorisation par champ `spacing[H,W]` produit des lignes potentiellement fragmentées entre patches. À l'œil, l'effet devrait rester acceptable pour `patch=32` (32 lignes max par bloc). Si besoin de continuité parfaite, passer à un dessin de lignes Bresenham par patch.
- **Performance** : aucun traitement ne dépasse ~200 ms sur 1024². Largement sous le budget < 2s/image demandé.
- **Aucune dépendance ajoutée** à `requirements.txt`.

## Annexes

- Données brutes : `2026-05-05_poc-gray-replace.json`
- Script : `scripts/poc_gray_replace.py`
- Outputs : `docs/reports/poc-gray-replace/`
- POC source colorée : `docs/reports/poc-color-to-lineart/`
- POC dithering global (comparaison) : `docs/reports/2026-05-05_poc-dithering.md`