# Techniques — référence vivante

Liste des techniques validées et invalidées au fil des POC, à mettre à jour
après chaque verdict final.

Format : un ID stable `Tnn` par technique, statut, contexte, livrables.

## Validées

### T19 — Décoloriage : ERNIE pastel + segmentation → coloriage 2 poids

**Statut** : validée 2026-06-10 (POC `decoloriage-validation`, gates G0→G5).

**Pipeline** :

1. **Génération ERNIE colorié** avec prompt pastel (template F : *"soft pastel
   children's coloring illustration"*) + contraintes :
   - `flat colors`
   - `cel shading` (pas de dégradés)
   - `no gradients`
   - palette pastel nommée
   - sujet isolé + contraintes anatomiques (gardées de v3 NEGATIVE).
2. **Segmentation G1a v3** : `cv2.pyrMeanShiftFiltering(sp=12, sr=24)` +
   k-means Lab k=12 + connected components 4-connectivity + fusion < 0,05 %
   d'aire + protection ΔE ≥ 30 + compacité 3×3.
3. **Partition G2** : 3 cadrans (tout-petit / enfant / adulte) à partir
   d'une base v3 unique avec `protected_ids` canoniques. Niveau **enfant** =
   `smooth_merge_similar(thresh=12)` immunisant les `protected_ids`.
   Niveau **tout-petit** = familles de couleurs (k=5 sur centroïdes Lab) +
   fallback greedy ΔE — **conditionnel**, validé sur sujets organiques
   mono-sujet uniquement (cf. heuristique `publishable_tp`).
4. **Vectorisation G3** : `find_contours` par région avec padding sentinel +
   Douglas-Peucker tol 1 px + Chaikin closed 2 iter + snap-to-edges +
   skip-Chaikin sur polygones touchant le bord image.
5. **Hiérarchie de traits G4** : graphe topologique de frontières partagées
   (chaque frontière dessinée **une fois**) avec classification :
   - **arcs encre** : arc dont ≥ 60 % des pixels rasterisés tombent dans le
     masque de traits G2 dilaté 3 px → stroke épais
   - **arcs shading** : sinon → stroke ~1/3 (subdivisions internes de la
     quantification couleur)
   - Calibrage stroke = épaisseur médiane du trait ERNIE mesurée par
     `2 × median(distanceTransform)`.
6. **Produit G5** : SVG bicouche click-to-fill.
   - **Régions-encre** (= régions G2 dont ≥ 50 % des pixels chevauchent le
     masque de traits dilaté) → `fill="#111111"`, `pointer-events="none"`,
     **pas de `data-color`**, **exclues du compteur** de zones cliquables.
     Résout le bug visuel "tube creux coloriable" du trait ERNIE.
   - **Régions colorables** : `<path class="region">` avec `data-color`
     = couleur d'origine mappée sur le crayon le plus proche en distance
     Lab parmi les 6 crayons design system :
     - Cerise `#FF2E63`
     - Mandarine `#FF8A2B`
     - Citron `#FFD60A`
     - Menthe `#06D6A0`
     - Océan `#118AB2`
     - Prune `#8B5CF6`
     - Régions à L\* ≥ 92 → mappées sur Papier `#ffffff` (le fond ne se
       peint pas en pâle crayon).
   - **Arcs encre** : stroke noir épais, toujours visibles.
   - **Arcs shading** : `class="arc-shading"` + CSS `stroke: none` par
     défaut. Esthétique line-art ERNIE conservée.
   - **Toggle "Guides"** dans la démo HTML : ajoute `.show-guides` au
     wrapper, CSS révèle les arcs shading en `#DDDDDD` 1 px (utile pour
     impression papier coloriage adulte = variante `_g5_print.png`).
   - SVG utilise `fill-rule="evenodd"` sur `<g id="fills">` pour gérer
     les régions-encre topologiquement annulaires. Rasterisation PNG :
     ne pas s'appuyer sur `cv2.fillPoly` per-poly (ne respecte pas
     even-odd) — utiliser le masque pixel `(region_map == rid)`.

**Résultat de l'hypothèse pré-enregistrée** :

> *"régions(c) ≥ 2 × régions(a) sur les 5 animaux"*
>
> où (a) = nombre de zones fermées du line art ERNIE direct (CC du
> complément du masque de traits), (c) = nombre de régions du label map
> niveau enfant.

| Animal | (a) line art | (c) décoloriage | ratio |
|---|---:|---:|---:|
| pastel_dog | 7 | 32 | 4,57× |
| pastel_horse | 14 | 44 | 3,14× |
| pastel_cat | 8 | 60 | 7,5× |
| pastel_elephant | 19 | 57 | 3,0× |
| pastel_lion2 | 12 | 66 | 5,5× |

**5/5 animaux satisfont le critère**. Hypothèse validée empiriquement.

Hors animaux : 9/10 du corpus G0 satisfont ≥ 2× (seul `castle` à 1,55× car
son line art ERNIE natif est déjà très détaillé — architecture fine).

**Reports** :
- `docs/reports/2026-06-09_poc-decoloriage-g1a.md`
- `docs/reports/2026-06-09_poc-decoloriage-g1a-v3.md`
- `docs/reports/2026-06-09_poc-decoloriage-g1a-pivot.md`
- `docs/reports/2026-06-10_poc-decoloriage-g2.md`
- `docs/reports/2026-06-10_poc-decoloriage-g3.md`
- `docs/reports/2026-06-10_poc-decoloriage-g4.md`
- `docs/reports/2026-06-10_poc-decoloriage-g5.md` (avec pivot encre/shading)
- `docs/reports/2026-06-10_poc-decoloriage-SYNTHESE.md` — **synthèse finale**

**Tags git** :
- `poc-decoloriage-v1` — POC initial (dog seul en G5 produit)
- `poc-decoloriage-v1.1` — extension batch : 10 sujets, check auto tubes
  creux résiduels (overlap > 30 %), 9/10 PASS (seul peacock 5 candidats =
  ocelles répétitives), galerie 10×2, insight Prune jamais utilisée.

**Scripts** :
- `poc/decoloriage/g1a_v3_compact.py`
- `poc/decoloriage/g2_partition.py`
- `poc/decoloriage/g3_vectorize.py`
- `poc/decoloriage/g4_two_weight.py`
- `poc/decoloriage/g5_product.py`

**Pourquoi remplacer le pipeline `binarisation+potrace`** :

- (a) line art ERNIE direct = page noir/blanc, ~7–20 zones fermées par animal.
- (b) binarisation+potrace = simple vectorisation N&B, même nombre de zones.
- (c) décoloriage 2 poids = page coloring book complète (fills + traits
  hiérarchisés), 32–66 zones cliquables par animal, prête pour
  l'interactivité click-to-fill et pour l'impression couleur.

Le contraste (a)/(b) ↔ (c) est saisissant sur la planche verdict
`poc/decoloriage/contact_sheet_g4.png`.

**Backlog technique** (non bloquant pour la mise en prod) :

- (b1) `protected` répétitifs : si ≥ 5 régions de signature très proche sont
  détectées comme motif décoratif (ocelles, taches), proposer une fusion
  optionnelle. Cas typique : peacock (∼80 ocelles répétitives).
- (b2) Fusion contrainte par le masque de traits : un trait épais = barrière
  infranchissable, un trait fin = barrière franchissable. Donnerait un
  tout-petit plus propre sur sujets architecturaux (castle).
- (b3) Approche topologique pure pour les fills (suppression du stroke
  anti-sliver) : graphe de frontières partagées pour les fills aussi, comme
  pour les strokes G4. Le stroke 2 px du G3 reste suffisant pour le rendu
  actuel — partiellement levé en G4 puisque les strokes utilisent déjà
  la topologie.
- (b4) Préset SVG sans strokes pour sujets architecturaux où le trait
  épais bouffe la lisibilité.
- (b5) **Crayon Noir 7e** : ajouter `#15151B` au design system pour gérer
  naturellement yeux/truffes/ocelles aujourd'hui forcés sur Ocean. Décision
  design system.
- (b6) **Mode solution paramétrable** : option `data-color-mode="ernie"`
  (couleurs originales) vs `data-color-mode="crayon"` (mapping 6 crayons).
- (b7) **Migration prod alwanbooks** : adapter `ColorierApp.tsx` pour
  consommer un SVG bicouche au lieu du PNG + bitmap `coloringData`.
  Chantier prod distinct.
- (b8) ~~Variante print (guides shading clairs)~~ — **livrée** en G5 pivot :
  génère `<slot>_<rid>_g5_print.png` automatiquement.
- (b9) Repositionner Prune `#8B5CF6` : 0/10 sujets sur corpus pastel ERNIE
  l'utilisent (Océan plus proche pour tous les violets pastels en distance
  Lab). Soit décaler vers un violet plus central (`#A78BFA`), soit assumer
  "crayon de choix utilisateur" jamais matché en solution. Décision design
  system, à traiter avec b5.

## Invalidées

*(aucune entrée à ce jour)*
