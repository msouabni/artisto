# POC — Décoloriage G3 — Vectorisation niveau enfant
Date : 2026-06-10

## Contexte

G3 du protocole `decoloriage-validation` après clôture G2 (5/10 publishable_tp,
décision produit tout-petit conditionnel). G3 vectorise le label_map ENFANT
des 10 images du corpus G0 en SVG, avec :
- marching squares (skimage.measure.find_contours)
- Douglas-Peucker (skimage.measure.approximate_polygon)
- lissage Chaikin (corner-cutting récursif)
- pivot anti-sliver **pré-autorisé** : stroke noir épais (2 px) sur frontières

Critères pass pré-enregistrés :
1. < 0,5 % de surface non couverte (diff rouge)
2. Jonctions triples sans trous
3. 0 marche d'escalier visible à zoom 200 %

## Paramètres

| Param | Valeur |
|---|---|
| Input | `g2_out/enfant/<slot>_<id>_regionmap.npy` |
| Tolérance Douglas-Peucker | 1,0 px |
| Itérations Chaikin | 2 |
| Stroke color | `#15151B` (RGB 21, 21, 27) |
| Stroke width | 2 px |
| Snap-to-edges | eps = 3 px (polygones touchant les bords) |
| Chaikin sur polygones touchant les bords | **désactivé** (préserve coins images) |
| Padding find_contours | 1 px sentinel hors-domaine |

Scripts : `poc/decoloriage/g3_vectorize.py`, `poc/decoloriage/make_contact_sheet_g3.py`.

## Pièges rencontrés et résolutions

| Piège | Diagnostic | Fix |
|---|---|---|
| 67 % non couvert à la 1ère itération | `skimage.find_contours` n'inclut pas les contours qui sortent du frame → contour des régions touchant le bord = ouvert | **Padding sentinel** : entourer le label_map d'une bordure 1 px avec un label inexistant, puis décaler les contours retournés de -1 |
| Encore 15,3 % non couvert (coins images en rouge) | Chaikin applique son corner-cutting sur la rectangle externe du fond → les coins (0,0), (0,W), (H,0), (H,W) deviennent arrondis → pixels coins non couverts par le polygone | **Skip Chaikin** sur les polygones dont au moins un vertex est à moins de 3 px d'un bord image. + **snap-to-edges** des vertices proches du bord vers -1 ou H/W exacts. |

## Résultats

| # | ID | régions | polylines | points total | non couvert (%) | jonctions 3 / 4+ | t (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | pastel_dog | 32 | 41 | 7706 | **0.000** | 44 / 0 | 0,36 |
| 2 | pastel_horse | 44 | 59 | 9228 | **0.000** | 56 / 0 | 0,42 |
| 3 | pastel_cat | 60 | 73 | 10782 | **0.000** | 92 / 0 | 0,52 |
| 4 | pastel_elephant | 57 | 94 | 10175 | **0.000** | 38 / 0 | 0,53 |
| 5 | pastel_lion2 | 66 | 91 | 13068 | **0.000** | 80 / 0 | 0,64 |
| 6 | taxo_polar_bear_on_ice | 52 | 63 | 10384 | **0.000** | 78 / 1 | 0,51 |
| 7 | pastel_pirate_ship | 49 | 77 | 7586 | **0.000** | 41 / 0 | 0,44 |
| 8 | pastel_lighthouse | 50 | 75 | 7661 | **0.000** | 44 / 0 | 0,47 |
| 9 | pastel_castle | 76 | 138 | 12607 | **0.000** | 27 / 0 | 0,68 |
| 10 | pastel_peacock | 209 | 283 | 25796 | **0.000** | 258 / 5 | 1,55 |

**Total** : 10/10 à 0,000 % non couvert. **Tous les sujets passent largement
le critère < 0,5 %**.

Temps moyen : ~0,6 s / image.

## Vérification des critères pass

| Critère | Mesure | Statut |
|---|---|---|
| < 0,5 % non couvert | 0,000 % sur les 10 images | ✓ |
| Jonctions triples sans trous | 758 jonctions à 3 labels + 6 à 4 labels sur le corpus. Le stroke 2 px les couvre intégralement, visible sur `zoom_g3_junction_peacock.png` (4 labels autour d'une jonction) | ✓ |
| 0 escalier visible à zoom 200 % | Voir `zoom_g3_junction_dog.png` à zoom ×4 : courbes parfaitement lisses, aucune marche d'escalier ; le contour ERNIE pixelisé du PNG d'origine se traduit en courbes Chaikin franches dans le SVG | ✓ |

## Lecture visuelle

- **`contact_sheet_g3.png`** : 10 lignes (orig | SVG rendu | diff). La colonne
  diff est uniformément blanche (pas de rouge visible) — cohérent avec les
  0,000 % mesurés.
- **`zoom_g3_junction_dog.png`** (zoom ×4 sur jonction triple) : courbes
  parfaitement smoothes, trait noir uniforme épais, jonctions sans trous.
- **`zoom_g3_junction_peacock.png`** (zoom ×4 sur jonction à 4 labels) :
  cas-test difficile (ocelle / plume / corps / contour se rejoignent). Le
  stroke épais couvre intégralement la jonction, les couleurs des 4 régions
  sont distinctes et propres.
- **`g3_browser_test.html`** : page de validation navigateur — affiche les
  10 SVG en `<img src="...svg">`. Zoom navigateur ×2 et ×4 confirment la
  qualité vectorielle (pas de pixelisation, courbes lisses).

## Pivot anti-sliver — bilan

Le pivot pré-autorisé (stroke noir épais) a été appliqué **dès la première
implémentation** (sans attendre de découvrir des slivers). C'est ce qui
permet :
- de masquer les micro-divergences entre les contours simplifiés de régions
  adjacentes (DP + Chaikin appliqués indépendamment par région)
- d'offrir une esthétique "page coloriage" cohérente avec les ERNIE pastels
  (trait noir épais natif)
- d'éviter l'implémentation plus lourde d'un graphe topologique de frontières
  partagées (qui aurait été l'approche "propre" pour éviter les slivers
  proprement, mais beaucoup plus complexe à implémenter)

## Livrables

- `poc/decoloriage/g3_vectorize.py` — pipeline vectorisation
- `poc/decoloriage/make_contact_sheet_g3.py` — planche + zooms + HTML
- `poc/decoloriage/g3_out/<slot>_<id>_enfant.svg` — **10 SVG ouvrables dans le navigateur**
- `poc/decoloriage/g3_out/<slot>_<id>_svg_render.png` — rasterisation pour diff
- `poc/decoloriage/g3_out/<slot>_<id>_diff.png` — diff rouge sur non couvert
- `poc/decoloriage/g3_out/<slot>_<id>_junctions_overlay.png` — jonctions triples en cyan/orange
- `poc/decoloriage/g3_out/stats.json` — stats consolidées
- **`poc/decoloriage/contact_sheet_g3.png`** — planche 10×3
- **`poc/decoloriage/zoom_g3_junction_{dog,lion,polar_bear,peacock}.png`** — 4 zooms triples
- **`poc/decoloriage/g3_browser_test.html`** — validation navigateur

## Points d'attention

1. **Approche per-region + stroke** vs approche topologique pure : la version
   livrée applique DP + Chaikin par région, donc chaque côté d'une frontière
   est simplifié indépendamment. En théorie, sans le stroke, on aurait des
   slivers (gaps entre régions adjacentes). Le stroke 2 px les couvre. La
   conséquence : si on veut un jour un SVG SANS stroke (par exemple pour un
   coloriage interactif où les régions doivent être "remplissables au clic"),
   il faudrait passer à l'approche topologique propre (graphe de frontières
   partagées). Pour le POC G3 et l'esthétique coloriage actuelle, le stroke
   suffit.
2. **Performance** : 0,4–1,6 s/image, ~6,4 s pour les 10. Tractable.
3. **Peacock à 209 régions** : c'est le stress-test, accepté tel quel depuis
   G1a v3. 283 polylines + 25 k points → SVG d'environ 600 KB (large mais
   acceptable pour un sujet aussi détaillé).
4. **6 jonctions à 4 labels** détectées sur le corpus (5 sur peacock, 1 sur
   polar_bear). Ces cas-limites sont visuellement OK dans le rendu — le
   stroke ne crée pas d'artefact aux jonctions de 4 régions.

## Décision / Action suivante

Verdict humain attendu sur :
- `poc/decoloriage/contact_sheet_g3.png`
- `poc/decoloriage/zoom_g3_junction_*.png`
- `poc/decoloriage/g3_browser_test.html`
- au moins un SVG ouvert dans le navigateur (`01_pastel_dog_enfant.svg`)

- **pass** → G4 (extraction de traits par modèle appris + verdict
  esthétique humain final).
- **kill** → fin de l'hypothèse.
- **pivot** → ajustement (ex. réduire stroke 2→1 px, augmenter DP tol, etc.).

Aucun gate G4 lancé sans verdict humain explicite.
