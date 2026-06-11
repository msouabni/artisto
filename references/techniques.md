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

### T20 — Styles de coloriage : architecture 2-modes (décoloriage couleur / lineart-fill N&B) + styles ornementaux natifs

**Statut** : exploration 2026-06-12 (POC 2 `decoloriage-styles`). 4 styles ornementaux natifs rendus coloriables production-ready via le mode **lineart-fill**. Pistes catalogue adulte, pas encore figées prod.

**Insight produit clé** : pour les styles ornementaux/décoratifs, NE PAS forcer la taxonomie sujet (chien/château/paon) — c'est « parachuté » et ça dévie le style de sa nature. Chaque style en sa **forme native** + **sujets adaptés** : zellige → étoiles/médaillons arabesques ; mandala → floral/géométrique/lotus ; zentangle → hibou/plume/papillon remplis de tangles ; mosaïque → poisson/oiseau romain/médaillon byzantin. Cible = motif hypnotique qui donne envie de colorier. (cf. mémoire `feedback_styles_ornementaux_sujet_natif`.)

**Architecture 2-modes (selon la source de l'image)** :
- **Mode décoloriage** (= T19) — image **COLORÉE** → régions (k-means Lab) + encre. Pour : pastel POC 1, kawaii contours, low-poly colorés.
- **Mode lineart-fill** (NOUVEAU) — **line-art N&B** → composantes connexes du blanc bornées par les traits noirs. Pour : mandala, zentangle, zellige, mosaïque, **et tout line-art** (y compris les prompts lineart d'origine pré-pastel).

**Recette styles ornementaux (lineart-fill)** :
1. Génération ERNIE turbo (params défaut), prompt natif par style + `coloring book line art, bold clean black outlines, white background` ; négatif `color, colored, grayscale shading, gradient`. Pas de chromakey (fond blanc → Papier via L*≥92).
2. **lineart-fill v2** (`poc/decoloriage_styles/lineart_fill_v2.py`) :
   - Binarisation encre (gris < ~110) + `MORPH_CLOSE` 3 px (soude les micro-trous de trait).
   - Composantes connexes 4-conn du NON-encre (blanc) = cellules ; fond = plus grande zone touchant le bord = Papier.
   - **Expansion Voronoi** (`scipy.ndimage.distance_transform_edt(return_indices=True)`) des cellules **sous le trait** → couverture canvas 100 %, **zéro halo blanc** au remplissage (fix production).
   - Cellules vectorisées (`g3_vectorize.extract_region_polygons`, Chaikin) ; **encre vectorisée** (`services.vectorizer.Vectorizer.from_preset("bw_default")`, VTracer) → traits lisses, 0 raster (fix production « traits smooth »).
   - SVG bicouche : `<g id="fills">` (1 path cliquable par cellule, `data-region-id`) + `<g id="strokes">` (encre vectorielle, `pointer-events:none`).
3. HTML click-to-fill standalone.

**Résultats** (4 styles × 3 sujets natifs) : couverture **100 %** (halo supprimé), cellules indépendantes (médiane ~480), traits vectoriels lisses (zoom AVANT/APRÈS validé), SVG ~770 Ko (encre vectorielle ; 392 Ko en variante raster). Pages adulte publiables. Réf : `poc/decoloriage_styles/EXPLORATION_LOG.md` + `fill_v3/`.

**Styles durs (manga/réaliste/peinture/3D)** : baseline POC 1 insuffisant (gate S1, diagnostic). Outils d'adaptation S2 **validés et disponibles** : **SAM 2** (segmentation, réduit la sur-fragmentation : peacock 641→49 régions) + **informative-drawings `contour_style`** (extraction de traits appris quand pas d'encre native → vrai line-art sur 3D). Non poursuivis (pivot styles-adaptés plus rentable), mais outils prêts si retour.

**Backlog prod (T20)** :
- (c1) Intégrer **lineart-fill comme 3e moteur** dans `image_post_processing_worker` (à côté de décoloriage + extract_palette rollback), sélection par style/variante.
- (c2) **Alléger l'encre** : exposer l'option raster (392 Ko) vs vectorielle (773 Ko), ou simplifier les paths VTracer.
- (c3) **Appliquer lineart-fill aux prompts lineart d'origine** (style historique) → débloque leur coloriage interactif.
- (c4) Re-gen des sujets à artefact gen (zentangle_dog « 2 chiens », low_poly_dog « 2 têtes »).
- (c5) stained_glass / mosaïque colorée : récupérables via sujet isolé chromakey + grandes vitres, ou SAM 2 — backlog.
- (c6) Figer les styles validés en variantes prod (`data/pipeline_variants.json`) + décision catalogue Alwan (mémoire).

## Invalidées

*(aucune entrée à ce jour)*
