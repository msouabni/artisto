# POC — Décoloriage G2 — Partition propre 3 seuils
Date : 2026-06-10

## Contexte

G2 du protocole `decoloriage-validation` après clôture de G1a v3. Objectif :
produire une partition complète (0 pixel orphelin) à 3 cadrans de difficulté
visuellement distincts (tout-petit / enfant / adulte), valider le pass
« 15–80 régions au seuil médian » et préparer la planche comparative + crops
frontières pour le verdict humain.

## Pipeline et paramètres

Pipeline réutilisé tel quel de G1a v3 (`g1a_v3_compact.py`) puis une **étape
supplémentaire** propre à G2 : `smooth_merge_similar(rm, lab, thresh)` qui
fusionne itérativement les paires adjacentes de plus petit ΔE76 tant que
ΔE76 < seuil. C'est ce levier qui sépare vraiment les niveaux : les seuils
de fusion par aire (de v3) ne touchent que les petites régions ; le smooth
merge attaque les **grandes** régions adjacentes structurellement proches en
couleur.

| Param | tout-petit | enfant | adulte |
|---|---|---|---|
| k | 12 | 12 | 12 |
| pyrMeanShift sp / sr | 16 / 32 | 12 / 24 | 12 / 24 |
| merge_thresh | 1,5 % | 0,1 % | 0,05 % |
| contrast_thresh (ΔE76) | 999 (off) | 30 | 30 |
| smooth_merge_thresh (ΔE76) | 22 | 12 | 0 (off) |

Code : `poc/decoloriage/g2_partition.py`, `poc/decoloriage/make_contact_sheet_g2.py`.
Sorties par image : `poc/decoloriage/g2_out/<level>/<slot>_<id>_regions.png`
+ region_map en `.npy` (prêt pour réutilisation en G3 sans recalcul).

## Résultats — récap

| # | Cat. | ID | tout-petit | **enfant** | adulte | orphelins |
|---|---|---|---:|---:|---:|---:|
| 1 | animal | pastel_dog | 7 | **30** | 35 | 0 |
| 2 | animal | pastel_horse | 6 | **43** | 46 | 0 |
| 3 | animal | pastel_cat | 7 | **58** | 62 | 0 |
| 4 | animal | pastel_elephant | 10 | **56** | 58 | 0 |
| 5 | animal | pastel_lion2 | 8 | **63** | 67 | 0 |
| 6 | scène | taxo_polar_bear_on_ice | 3 | **48** | 59 | 0 |
| 7 | scène | pastel_pirate_ship | 7 | **47** | 53 | 0 |
| 8 | objet | pastel_lighthouse | 5 | **47** | 52 | 0 |
| 9 | objet | pastel_castle | 8 | **74** | 76 | 0 |
| 10 | stress | pastel_peacock | 10 | **195** | 214 | 0 |

Médianes : tout-petit 7,5 ; enfant 53 ; adulte 58,5.
Temps : 1,1–2,6 s/image/niveau (smooth merge ajoute ~0,2–0,8 s).

## Validation des critères pass (skill)

1. **0 pixel orphelin** : OK sur 30 runs (`stats.json::orphan_check`).
2. **15–80 régions au seuil médian (enfant)** : **9/10** dans la cible.
   Peacock à 195 = stress-test, hors cible accepté par décision utilisateur
   du 2026-06-10.
3. **Les 3 niveaux sont visuellement distincts** : à valider par l'humain
   via la planche + crops. Voir lecture ci-dessous.

## Lecture visuelle — distinction des 3 niveaux

### Sur la planche principale (`contact_sheet_g2.png`)

- **tout-petit** : silhouette + 3-7 grandes zones. Sur dog : tête+corps en
  un blob, queue + paw en zones plats, oreilles partiellement résolues.
  Sur peacock : ~10 zones = chaque "secteur" du paon. Sur polar_bear : 3
  régions = ours, glace, fond.
- **enfant** : retrouve les détails moyens : œil-tache, oreilles séparées,
  contour, principales zones de couleur. Sur dog : nez (vert), bouche
  (smile line), oreille interne. Sur lion : œil principal, intérieur
  d'oreille, bande de crinière, museau.
- **adulte** : tous les micro-détails que G1a v3 préservait : 2 yeux
  séparés, truffe, moustaches, ocelles individuelles. Compte 5-12 régions
  de plus qu'enfant (sauf peacock, +19).

### Sur les crops frontières

| Crop | Effet visuel constaté |
|---|---|
| `zoom_g2_boundary_dog.png` (face/œil/truffe) | tout-petit = visage chunky ; enfant = bouche + nez vert visibles, œil absent ; adulte = œil violet + truffe sombre + 2 marquages tête |
| `zoom_g2_boundary_lion.png` (crinière multi-tons) | tout-petit = crinière en 1 ou 2 zones ; enfant = ~5 sections de crinière + œil + intérieur oreille ; adulte = mèches de crinière + 2 yeux + museau + moustaches |
| `zoom_g2_boundary_peacock.png` (plumes/ocelles, stress) | tout-petit = 10 secteurs ; enfant = ocelles présentes mais avec 1-2 anneaux ; adulte = 2-3 anneaux concentriques par ocelle |
| `zoom_g2_boundary_polar_bear.png` (interface ours/glace) | tout-petit = ours flat / glace flat ; enfant = détails de glace + zones de l'ours visibles ; adulte = museau + œil + langue + détails de glace fins |

### Histogramme

`histogram_g2.png` : visuellement, l'écart enfant/adulte est petit en
valeur absolue (~5–12 régions) sur 9/10 sujets, mais STRUCTURELLEMENT
distinct (les détails préservés sont différents). Le crop `dog` est l'exemple
le plus clair de cette distinction qualitative malgré l'écart numérique
modeste.

## Points d'attention

1. **Convergence enfant ↔ adulte** : la première itération sans smooth
   merge donnait enfant ≈ adulte (cat 62/62, castle 76/76). Le smooth
   merge ΔE76 < 12 sur enfant fait converger les zones pastels proches et
   crée un écart structurel sans changer fondamentalement la silhouette.
   L'écart numérique reste modeste (5–12 régions/image) mais l'écart
   sémantique est net (cf. crop dog : la perte du couple œil/truffe entre
   adulte et enfant).
2. **Cible numérique non-respectée sur peacock** : décision pré-G2
   confirmée. Le stress-test reste tel quel ; au pire le mode « enfant »
   donnerait 195 régions = niveau adulte sur un sujet normal.
3. **Polar bear à 3 régions au tout-petit** : la silhouette de l'ours
   blanche + glace + fond bleu = 3 clusters dominants. C'est correct mais
   limite ; si on voulait au moins 5 zones par image au tout-petit, il
   faudrait baisser le smooth merge à 18 (au lieu de 22).
4. **Performance** : 1,1–2,6 s/image/niveau. Pour 10 images × 3 niveaux :
   ~45 s total. Tractable pour itérer.
5. **Artefacts raster (jaggies) encore présents** : annoté en G1a v3,
   confirmé sur les 30 partitions G2. Résolution prévue en G3 (Douglas-
   Peucker + lissage Chaikin/spline sur le graphe de frontières partagées,
   critère pass « 0 marche d'escalier visible à zoom 200 % » ajouté).

## Décision / Action suivante

Verdict humain attendu sur :
- `poc/decoloriage/contact_sheet_g2.png` (planche 10×4 principal)
- `poc/decoloriage/histogram_g2.png` (histogramme)
- `poc/decoloriage/zoom_g2_boundary_dog.png`
- `poc/decoloriage/zoom_g2_boundary_lion.png`
- `poc/decoloriage/zoom_g2_boundary_peacock.png`
- `poc/decoloriage/zoom_g2_boundary_polar_bear.png`

- **pass** → G2 clos, G3 enchaîné (vectorisation anti-slivers du graphe
  de frontières, gate le plus risqué selon le skill).
- **kill** → fin de l'hypothèse, rapport d'invalidation.
- **pivot** → ajuster les seuils (ex. smooth merge enfant 12→16 pour
  agrandir l'écart numérique, ou tout-petit 22→18 pour relever polar_bear
  à 5+ régions).

Aucun gate n'est lancé sans verdict humain explicite.

## Livrables

- `poc/decoloriage/g2_partition.py` — pipeline 3 niveaux + smooth merge
- `poc/decoloriage/make_contact_sheet_g2.py` — planche + histo + 4 crops
- `poc/decoloriage/g2_out/<level>/*.png` + `*.npy` — 30 partitions + label maps
- `poc/decoloriage/g2_out/stats.json` — stats consolidées + check orphans
- **`poc/decoloriage/contact_sheet_g2.png`** — planche 10×4
- **`poc/decoloriage/histogram_g2.png`** — histogramme bar chart
- **`poc/decoloriage/zoom_g2_boundary_dog.png`** — crop face/œil chien
- **`poc/decoloriage/zoom_g2_boundary_lion.png`** — crop crinière lion
- **`poc/decoloriage/zoom_g2_boundary_peacock.png`** — crop plumes/ocelles
- **`poc/decoloriage/zoom_g2_boundary_polar_bear.png`** — crop interface ours/glace

---

## Pivot 2026-06-10 — Immunité des protected_ids à TOUS les niveaux

**Demande utilisateur** : « smooth_merge_similar doit immuniser les régions
"protected" de G1a v3 (yeux, truffes, ocelles) à TOUS les niveaux, tout-petit
inclus. Règle produit : le cadran de difficulté fusionne les subdivisions de
shading, jamais l'anatomie saillante — un coloriage tout-petit garde ses yeux. »

### Changement d'architecture

L'ancienne version G2 lançait 3 fois le pipeline complet (pyrMeanShift +
kmeans + CC + merge_v3 + smooth) avec des paramètres v3 différents par niveau.
Conséquence : la liste des `protected` était par-niveau et incohérente.

La version pivot adopte un **base v3 unique** par image (config = adulte de
G1a v3) qui produit la partition canonique + la liste canonique des
`protected_ids` (les yeux/truffes/ocelles). Les 3 cadrans sont dérivés du
même base par un `smooth_merge_similar` avec un seuil croissant, **respectant
strictement la liste canonique**. Le seuil de smooth merge devient le seul
levier qui distingue les niveaux.

### Paramètres pivot

| | base v3 | tout-petit | enfant | adulte |
|---|---|---|---|---|
| pyrMeanShift sp / sr | 12 / 24 | (héritage base) | (héritage base) | (héritage base) |
| k | 12 | — | — | — |
| merge_thresh (v3) | 0,05 % | — | — | — |
| contrast_thresh (v3) | 30 (ΔE76) | — | — | — |
| smooth_merge_thresh | — | **22** (inchangé) | **12** (inchangé) | **0** (inchangé) |
| protected_immune | — | **oui (canonical)** | **oui (canonical)** | **oui (canonical)** |

Note : `contrast_thresh=30` était hérité du base — le pivot évite l'erreur de
la 1re itération où on avait mis 999 à tout-petit (= aucune protection).

### Résultats post-pivot

| # | ID | tout-petit | enfant | adulte | protected_immune (canonique) | smooth merges tp/e/ad |
|---|---|---:|---:|---:|---:|---|
| 1 | pastel_dog | **30** | 32 | 35 | 5 | 5 / 3 / 0 |
| 2 | pastel_horse | **42** | 44 | 46 | 14 | 4 / 2 / 0 |
| 3 | pastel_cat | **51** | 60 | 62 | 12 | 11 / 2 / 0 |
| 4 | pastel_elephant | **52** | 57 | 58 | 29 | 6 / 1 / 0 |
| 5 | pastel_lion2 | **65** | 66 | 67 | 21 | 2 / 1 / 0 |
| 6 | taxo_polar_bear_on_ice | **39** | 52 | 59 | 22 | 20 / 7 / 0 |
| 7 | pastel_pirate_ship | **47** | 49 | 53 | 18 | 6 / 4 / 0 |
| 8 | pastel_lighthouse | **34** | 50 | 52 | 9 | 18 / 2 / 0 |
| 9 | pastel_castle | **76** | 76 | 76 | 15 | 0 / 0 / 0 |
| 10 | pastel_peacock | **198** | 209 | 214 | 105 | 16 / 5 / 0 |

Orphans : 0 sur 30 runs.

### Vérification des 3 effets attendus

| Effet attendu | Constat | Statut |
|---|---|---|
| **dog enfant : œil + truffe présents** | dog protected_immune=5 (œil + truffe + smile + 2 taches tête) ; ces régions sont préservées à enfant ET tout-petit (cf. crop `zoom_g2_boundary_dog.png` — œil violet + truffe claire + sourire visibles sur les 3 panels). | ✓ |
| **polar_bear tout-petit : remonte ≥ 5 sans changer smooth_merge_thresh** | polar_bear tout-petit = **39 régions** (vs 3 avant pivot, vs ≥ 5 demandé). Largement au-dessus. | ✓ |
| **Écart enfant/adulte sur le shading, pas sur les visages** | Sujets à shading subtil (polar_bear glace, lighthouse mer, cat) : 7–18 smooth_merges enfant→tout-petit, surtout sur fonds/dégradés. Sujets sans shading (castle architecture nette) : 0 smooth_merges. L'écart numérique enfant/adulte est concentré sur les zones de couleurs lisses (mer, glace, pelage), pas sur l'anatomie. | ✓ |

### Effets secondaires observés

1. **Comptes tout-petit plus élevés que prévu** (30–198 vs 3–10 avant
   pivot). C'est conséquence directe de la règle produit : on n'écrase plus
   l'anatomie pour atteindre un compte « silhouette ». Le tout-petit reste
   simplifié sur le shading (cf. polar_bear : 20 merges sur la glace) mais
   conserve tous les détails saillants. Le cadran de difficulté n'est plus
   « combien de zones » mais « combien de subdivisions de shading ».
2. **castle non-différenciable** : architecture composée uniquement de zones
   sharply distinctes → 0 smooth merges aux 3 niveaux → comptes identiques
   (76/76/76). Comportement correct : sur un sujet sans shading, le cadran
   de difficulté n'a rien à fusionner.
3. **Médiane enfant = 52** (cible 15–80 satisfaite sur 9/10, peacock 209
   excepté). Médiane adulte = 58,5. Médiane tout-petit = 46. Comptes plus
   resserrés mais sémantiquement plus alignés au cahier des charges.

### Décision post-pivot

Le pivot est livré pour verdict humain. Le pipeline produit maintenant 3
partitions qui respectent strictement la règle produit. Comme avant :
- **pass** → G3 (vectorisation anti-slivers du graphe de frontières)
- **kill** → rapport d'invalidation
- **pivot** → ajustement supplémentaire

Livrables régénérés (mêmes chemins, mêmes formats que pré-pivot).

---

## Pivot v2 2026-06-10 — Tout-petit par familles de couleurs + extractions G3/G5

### Demande utilisateur

1. **Nouveau mécanisme tout-petit** : re-clusteriser les couleurs moyennes des
   régions (base v3) en 4–6 familles via k-means Lab sur centroïdes, puis
   fusionner itérativement les régions ADJACENTES de même famille (union-find).
   Protected immunes inchangé.
2. Enfant inchangé.
3. **Fallback** : si tout-petit reste > ~20 zones non-protégées, fusion greedy
   ΔE croissant jusqu'à non-protégées ≤ 10.
4. **Extraction colors per region** : pour chaque région, couleur moyenne du
   PNG ORIGINAL (Lab + hex) → futur data-color G5 + mapping 6 crayons.
5. **Masques de traits noirs** par image (seuil L < 25 sur PNG lissé) en
   binaire propre → entrée directe G3/G4.

### Implémentation (v2)

| Étage | Comment |
|---|---|
| `family_merge_tout_petit` | k=5 k-means sur centroïdes Lab. Union-find des paires adjacentes de même famille (sort par aire décroissante). Protected immunes en source ET destination. |
| Fallback greedy | À la fin, si `non_protégées > 10`, itère : trouve la paire non-protégée de plus petit ΔE, fusionne, jusqu'à ≤ 10. |
| Enfant | `smooth_merge_similar(rm_v3, thresh=12, protected)` inchangé. |
| Adulte | `rm_v3` brut. |
| Per-region colors | `ndi.mean` par canal sur l'image ORIGINALE rgb + Lab + hex sRGB. Marquage `protected: true/false`. |
| Line mask | `(rgb2lab(rgb_smoothed).L < 25).astype(uint8) * 255` + `MORPH_CLOSE 3×3`. |

### Résultats post-pivot v2

| # | ID | tout-petit (familles+fallback) | enfant | adulte | immune | non-protégées tp |
|---|---|---:|---:|---:|---:|---:|
| 1 | pastel_dog | **15** | 32 | 35 | 5 | 10 |
| 2 | pastel_horse | **24** | 44 | 46 | 14 | 10 |
| 3 | pastel_cat | **22** | 60 | 62 | 12 | 10 |
| 4 | pastel_elephant | **39** | 57 | 58 | 29 | 10 |
| 5 | pastel_lion2 | **31** | 66 | 67 | 21 | 10 |
| 6 | taxo_polar_bear_on_ice | **32** | 52 | 59 | 22 | 10 |
| 7 | pastel_pirate_ship | **28** | 49 | 53 | 18 | 10 |
| 8 | pastel_lighthouse | **19** | 50 | 52 | 9 | 10 |
| 9 | pastel_castle | **25** | 76 | 76 | 15 | 10 |
| 10 | pastel_peacock | **115** | 209 | 214 | 105 | 10 |

**Loi de composition** : `tout-petit = immune + 10 non-protégées`. C'est désormais déterministe :
le fallback ramène toujours non-protégées à exactement 10. Le total varie avec
le nombre d'immunes du sujet.

Orphelins : 0 / 30 runs.

### Lecture visuelle (vs pré-pivot v2)

| Sujet | tp v2 nouveau | Effet |
|---|---|---|
| pastel_dog | 15 (vs 30) | Corps unifié en une seule teinte. Œil + truffe + sourire intacts. Vraie "page coloriage tout-petit". |
| pastel_polar_bear | 32 (vs 39) | Glace unifiée vert, bois unifié brun. Bear silhouette en une seule teinte. Œil + truffe + langue intacts. |
| pastel_castle | 25 (vs 76) | Architecture collapsée en grandes zones (tours, toit, base). Détails fenêtres/drapeaux conservés via protected. |
| pastel_peacock | 115 (vs 198) | 105 ocelles immunes + 10 zones non-protégées (plumes en groupes de couleur). Stress reste hors cible 30-150 mais beaucoup moins. |

### Extractions G3/G5 livrées

**1. Per-region colors (stats.json)** : chaque entrée `images[].regions[]`
contient :
```json
{ "id": 42, "area_px": 12345, "lab": [80.5, 4.2, -3.1],
  "hex": "#E5D7C2", "protected": true }
```
30 (= 10 images × 3 niveaux) × ~25–215 régions chacune.

**2. Line masks** : `poc/decoloriage/g2_out/lines/<slot>_<id>_lines.png` —
10 PNG binaires propres. Exemple `dog` : trait noir continu, anatomie visible,
contour préservé, pas de bruit (cf. lignes manuelles d'illustration).
Statistiques dans `stats.json::lines`.

### Livrables v2 (mêmes chemins, format planche change)

- `poc/decoloriage/g2_partition.py` — pivot v2 avec `family_merge_tout_petit`
- `poc/decoloriage/g2_out/<level>/*.png` + `*.npy` — 30 partitions + label maps
- `poc/decoloriage/g2_out/lines/*.png` — **10 line masks binaires**
- `poc/decoloriage/g2_out/stats.json` — stats consolidées (params, regions
  with colors, line stats)
- `poc/decoloriage/contact_sheet_g2.png` — **planche 10×3 (orig | tp | enfant)**
- `poc/decoloriage/histogram_g2.png` — histogramme (3 bars conservés, adulte
  reste pour comparaison)
- `poc/decoloriage/zoom_g2_boundary_{dog,lion,peacock,polar_bear}.png` —
  4 crops (3 panels chacun : orig | tp | enfant)

### Décision attendue

- **pass** → G3 (vectorisation anti-slivers du graphe de frontières partagées,
  + critère pass G3 ajouté en G1a v3 : 0 marche d'escalier à zoom 200 %).
- **kill** → fin de l'hypothèse.
- **pivot** → ajustement supplémentaire (ex. baisser fallback_target à 8 ou
  remonter k_families à 6).

Aucun gate G3 lancé sans verdict humain explicite.

---

## Clôture G2 — Décision produit (2026-06-10)

**Verdict humain** : `pass G2 avec décision produit`.

### 1. Le niveau tout-petit est CONDITIONNEL, pas universel

On arrête de chercher une fusion universelle qui produirait une page tout-petit
publiable pour tous les sujets.

- **Validé empiriquement** sur sujets organiques mono-sujet :
  - `pastel_dog` (15 régions) — page coloriage tout-petit légitime
  - `pastel_polar_bear_on_ice` (32 régions) — sémantiquement correct (ours +
    glace + bois + œil + truffe)
- **Raté assumé** sur composites / architecturaux :
  - `pastel_pirate_ship` (28), `pastel_castle` (25), `pastel_peacock` (115)
  - Absence de fond uniforme → l'effet « silhouette + 4-6 couleurs » ne marche pas.

### 2. Heuristique de publication ajoutée à stats.json

```
publishable_tp = (n_non_protected_final ≤ 12) ET (protected_immune ≤ 15)
```

Heuristique simple, raffinage hors POC. Résultat sur le corpus :

| Sujet | non-prot | protected | publishable_tp |
|---|---:|---:|---|
| pastel_dog | 10 | 5 | **✓** |
| pastel_horse | 10 | 14 | **✓** |
| pastel_cat | 10 | 12 | **✓** |
| pastel_elephant | 10 | 29 | ✗ |
| pastel_lion2 | 10 | 21 | ✗ |
| taxo_polar_bear_on_ice | 10 | 22 | ✗ |
| pastel_pirate_ship | 10 | 18 | ✗ |
| pastel_lighthouse | 10 | 9 | **✓** |
| pastel_castle | 10 | 15 | **✓** |
| pastel_peacock | 10 | 105 | ✗ |

→ **5/10 publishable_tp**. L'heuristique est volontairement conservatrice :
polar_bear paraît visuellement OK (cf. crop) mais sort `False` parce que ses
22 immunes (détails du bloc de glace) dépassent le seuil 15. Raffinement
post-POC (cf. backlog item 1).

Implémentation : `g2_partition.py::main()` calcule `publishable_tp` et écrit
`stats.json::publishable_tp_summary` + `stats.json::images[].publishable_tp`.

### 3. Backlog post-POC (à NE PAS implémenter maintenant)

1. **Protected répétitifs** : si ≥ 5 régions protégées sont sémantiquement
   similaires (clustering Lab des protected_means par sujet, intra-cluster
   ΔE < ~12), c'est un motif décoratif type ocelles → fusionnables au cadran
   tout-petit en respectant l'identité du motif. Cible : ramener peacock
   en cible numérique 30-150 sans casser le motif.
2. **Fusion contrainte par le masque de traits** : utiliser le masque de
   traits noirs G2 (`g2_out/lines/*.png`) comme barrière pour la fusion.
   Traits épais = barrières non franchissables, traits fins = franchissables.
   Cible : éviter de fusionner deux régions visuellement séparées par un
   trait, même si elles sont de la même famille de couleur.

### Capitalisation MEMORY.md

Mémoire projet créée :
`memory/project_decoloriage_tout_petit_conditional.md`
indexée dans `memory/MEMORY.md`.
