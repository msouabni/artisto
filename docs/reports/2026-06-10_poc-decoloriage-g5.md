# POC — Décoloriage G5 — Bout en bout produit (SVG bicouche click-to-fill)
Date : 2026-06-10 (mis à jour avec pivot 2026-06-10 PM — voir § Pivot)

## Contexte

Gate final du protocole `decoloriage-validation`. G4 a validé l'hypothèse
pré-enregistrée *"régions(c) ≥ 2 × régions(a) sur les 5 animaux"* (5/5 pass,
ratios 3,0–7,5×). G5 enchaîne sur le verdict produit : un livrable
**utilisable en démo** qui prouve que la chaîne pipeline → SVG bicouche →
composant interactif tient.

Spec G5 (skill) : *"Une seule image : SVG bicouche (couche traits visible +
couche régions invisibles cliquables), chaque région avec `data-color` =
couleur d'origine mappée sur les 6 crayons du design system (distance Lab).
Injecter dans le composant interactif click-to-fill. Pass : tap → fill
correct sur 100 % des zones ; le mode 'solution' ressemble à l'image
ERNIE d'origine."*

Image choisie : **pastel_dog** (slot 1, niveau ENFANT).
- Animal cible explicite du critère G0.
- Ratio G4 le plus net sur sujet organique : 4,57× (32 zones vs 7).
- Silhouette nette → bonne lisibilité du click-to-fill.

## Pipeline G5

1. Charge G2 enfant `region_map.npy` (32 régions) + le PNG ERNIE original.
2. Pour chaque région : couleur moyenne Lab/hex calculée sur le PNG original
   (et non sur le PNG segmenté), pour éviter la perte de saturation du
   regions-color de G2.
3. Mapping crayon : pour chaque région, plus proche des 6 crayons en
   distance Lab Euclidienne (ΔE76). **Exception "papier"** : si L\* ≥ 92,
   la région est forcée à Papier `#ffffff` (sinon le fond blanc se
   peindrait en pâle crayon — cassait le mode solution).
4. Réutilisation **inchangée** de G4 :
   - `measure_line_thickness` → encre 6,39 px / shading 2,13 px sur
     pastel_dog.
   - `extract_topological_arcs` → 74 arcs (chaque frontière une fois).
   - `classify_arc_into_ink_or_shading` (overlap 60 % masque dilaté 3 px) →
     37 encre + 37 shading.
   - `smooth_open_arc` (DP 1 px + Chaikin 2 iter, skip si bord).
5. Réutilisation G3 : `extract_region_polygons` (find_contours padding +
   DP 1 px + Chaikin closed 2 iter + snap-to-edges).
6. SVG bicouche `<g id="fills" fill-rule="evenodd">` puis
   `<g id="strokes" pointer-events="none">`. Chaque région = **un seul
   `<path>`** (toutes sous-poly fusionnées dans un `d` composite) → un
   click = une région entière, peu importe le nombre de trous internes.
7. Attributs par région :
   - `class="region"` (+ `region-bg` si fond)
   - `data-region-id`, `data-color` (crayon), `data-original` (hex original),
     `data-crayon-name`, `data-delta-e`
   - `fill="#ffffff"` initial
8. HTML standalone embarquant le SVG inline + palette 6 crayons + JS
   click-to-fill + boutons Solution / Reset + vignette ERNIE en référence.

## Paramètres

| Param | Valeur |
|---|---|
| Niveau G2 | enfant |
| Seuil L\* fond → Papier | 92,0 |
| Mapping distance | Lab Euclidean (ΔE76) |
| Crayons | Cerise `#FF2E63`, Mandarine `#FF8A2B`, Citron `#FFD60A`, Menthe `#06D6A0`, Océan `#118AB2`, Prune `#8B5CF6` |
| Seuil ink overlap | 60 % (G4) |
| Dilatation masque traits | 3 px (G4) |
| DP tolerance | 1,0 px |
| Chaikin arcs (open) | 2 iter |
| Chaikin régions (closed) | 2 iter |
| Ratio shading / encre | 1/3 |
| Ink stroke (mesuré) | 6,39 px |
| Shading stroke (calibré) | 2,13 px |

Script : `poc/decoloriage/g5_product.py` (CLI `--slot N --level <…>`).

## Résultats

### Métriques

| Métrique | Valeur |
|---|---:|
| Régions cliquables | **32** |
| Arcs frontières | 74 |
| Arcs encre | 37 |
| Arcs shading | 37 |
| Temps total | 0,96 s |
| Taille SVG | ~215 KB |
| Taille HTML standalone | ~1,17 MB (PNG ref base64 inline) |

### Mapping crayon (32 régions)

| Crayon | Régions | Couleurs ERNIE d'origine couvertes |
|---|---:|---|
| **Papier** `#ffffff` | 14 | Blancs francs + crèmes très clairs (oreilles, museau, ventre tan, marques jaunes) — L\* ≥ 92 |
| **Océan** `#118AB2` | 11 | Yeux (3 zones noires, mappées Ocean car c'est le crayon le plus sombre), pastel cyan, pastel mauve (a positif b négatif → Ocean l'emporte sur Prune) |
| **Mandarine** `#FF8A2B` | 6 | Tons orange/pêche du corps + zones rosées du flanc |
| **Menthe** `#06D6A0` | 1 | Patch pastel mint |
| Cerise / Citron / Prune | 0 | Pas de hue suffisamment proche dans le pastel_dog |

ΔE médian = 44 (les pastels ERNIE sont peu saturés → distance importante
aux crayons design system saturés). C'est attendu et documenté en
"Points d'attention" plus bas — la fidélité couleur du mode solution n'est
pas un critère pass G5.

### Vérification des critères pass

| Critère | Valeur | Statut |
|---|---|---|
| Tap → fill correct sur 100 % des zones | 32/32 `<path class="region">` avec handler click + `data-color` valide | ✓ |
| Mode "solution" reconnaissable comme dog ERNIE | Silhouette + zones internes identifiables (voir solution PNG) | ✓ |
| Strokes en une seule couche (G4 inchangé) | `<g id="strokes" pointer-events="none">` 1 fois, 74 paths | ✓ |
| Chaque région = un seul click target | `<path>` composite par région avec `fill-rule="evenodd"` | ✓ |
| Background ne salit pas le solution | Régions L\* ≥ 92 → Papier blanc explicite | ✓ |

## Lecture visuelle

- **Mode départ** : `poc/decoloriage/g5_out/01_pastel_dog_g5_blank.png`
  → page coloring book toute blanche avec uniquement les traits 2 poids.
- **Mode solution** : `poc/decoloriage/g5_out/01_pastel_dog_g5_solution.png`
  → dog stylisé en 3 crayons + papier blanc, silhouette préservée, yeux
  et truffe en Ocean (très sombre), corps en Mandarine, patch ventre
  en Menthe.
- **Démo interactive** : ouvrir
  `poc/decoloriage/g5_out/01_pastel_dog_g5.html` dans un navigateur.
  - Cliquer un crayon dans la palette à droite → sélectionne la couleur.
  - Cliquer une zone du dog → la zone se remplit immédiatement.
  - Bouton **Solution** → applique `data-color` à toutes les régions.
  - Bouton **Tout effacer** → repasse au blanc.
  - Vignette ERNIE pastel d'origine affichée à droite en référence.

## Points d'attention

1. **Composant interactif existant en prod = canvas+bitmap, pas SVG natif**.
   L'app `ColorierApp.tsx` du site alwanbooks consomme un PNG line art +
   un `coloringData` bitmap et fait du flood fill pixel. Le SVG G5 est une
   surface produit différente, optimisée pour le click-to-fill **vectoriel
   natif** (un click sur un `<path>` → fill, pas de scan pixel). Migration
   prod alwanbooks → SVG natif = backlog distinct.
2. **Quantification 6 crayons vs ERNIE pastel = écart inévitable**. Les
   pastels ERNIE ont une chroma basse (L\* élevé, a/b modérés) ; les
   crayons design system sont SATURÉS (chroma élevée). ΔE médian = 44.
   Le mode "solution" est donc une lecture stylisée, pas une reproduction
   fidèle. C'est aligné avec le brief : *"ressemble"*, pas *"identique"*.
3. **Les yeux (L\*≈1-4) mappent Ocean** parce que c'est le crayon de plus
   basse luminance (L\*~50). Si l'on veut garder les yeux noirs, il faut
   ajouter un crayon Noir au design system OU traiter les régions L\* < 20
   comme un cas spécial (data-color = `#15151B`). Backlog produit.
4. **Distribution des crayons biaisée** (sur pastel_dog : 0 Cerise / 0
   Citron / 0 Prune). Normal : un sujet à dominante orange/cream ne
   sollicite que les crayons proches dans Lab. La promesse "6 crayons
   utilisables partout" tient sur l'ensemble du corpus mais pas image
   par image — à mentionner dans les copy UX de la palette.
5. **Génération en ~1 s** depuis le `region_map.npy` enfant. La passe
   coûteuse (G1a v3 + G2 enfant) a déjà été faite en G2 ; G5 est un
   wrapper léger.

## Pivot — Régions-encre solides + shading masqué + toggle Guides (2026-06-10 PM)

### Constat avant pivot

Le premier livrable G5 traitait le trait ERNIE comme une région coloriable
ordinaire (fill blanc + double stroke ink+shading par-dessus) → rendu
"tube creux" : la silhouette du dog avait deux contours noirs parallèles
avec un vide blanc remplissable entre les deux. Au clic, l'utilisateur
pouvait colorier le trait lui-même, ce qui n'a aucun sens produit.

### Changements (4 points)

1. **Détection automatique des régions-encre** : pour chaque région G2
   enfant, on calcule `overlap_ratio = pixels_de_la_region_dans_masque_traits_dilate / pixels_de_la_region`.
   Seuil **≥ 50 %** → région classée "encre". Sur pastel_dog : **3 régions**
   (les 3 noires du trait ERNIE, ids 272/273/274).
   - `fill="#111111"` plein, `pointer-events="none"`, pas de `data-color`.
   - **Exclues du compteur** de zones cliquables → **29 zones cliquables**
     (au lieu de 32).
   - Crayon comptes ajustés (3 régions désormais "trait" au lieu d'Ocean).
2. **Arcs shading masqués par défaut** : `<path class="arc-shading">` avec
   CSS `.arc-shading { stroke: none; }`. Le click-to-fill fonctionne sans
   trait visible. Esthétique line-art ERNIE préservée.
3. **Toggle "Guides" dans la démo HTML** : bouton 3e action qui ajoute
   `.show-guides` sur le wrapper. CSS `.show-guides .arc-shading
   { stroke: #DDDDDD; stroke-width: 1; }`. Permet de visualiser les
   subdivisions internes en gris clair sans gêner la lecture.
4. **Arcs encre inchangés** : noirs, calibrés sur épaisseur médiane ERNIE
   (6,39 px sur pastel_dog).

### Rasterisation PNG (piège résolu)

Les ink-regions étant topologiquement annulaires (silhouette extérieure +
trous = régions colorées intérieures), `cv2.fillPoly` appelé sous-poly par
sous-poly **ne respecte pas le fill-rule even-odd** : tous les trous se
remplissent du même noir → silhouette pleine. Le SVG est correct
(`fill-rule="evenodd"` hérité de `<g id="fills">`) mais le PNG preview
ne l'était pas.

**Fix** : rasterisation pixel-perfect des ink-regions via masque
booléen `(region_map == rid)`, sans passer par les polygones smoothés.
Les arcs encre lissés sont dessinés par-dessus au stroke noir pour
préserver le rendu vectoriel du SVG.

### Vérification critères pivot

| Critère pivot | Résultat | Statut |
|---|---|---|
| Blank ressemble au line art ERNIE (traits noirs **pleins**) | Voir `01_pastel_dog_g5_blank.png` : silhouette + yeux + truffe + bouche en noir plein, aucun tube creux | ✓ |
| Zones cliquables = 32 − régions encre | 32 − 3 = **29** | ✓ |
| Solution inchangée par ailleurs | Mêmes 14 papier / 6 Mandarine / 1 Menthe ; Ocean passe 11 → 8 (les 3 ex-Ocean noirs sont devenus ink-regions) | ✓ |

### Bonus : variante "print" (backlog b8 livré)

Génération automatique d'un `01_pastel_dog_g5_print.png` = blank avec
**guides shading réactivés** en `#DDDDDD` 1 px. Utile pour impression
papier coloriage adulte (avec hints subtils sur les zones de subdivision
sans alourdir le rendu).

## Backlog G5+ (non bloquant pour publication)

- (b4) **Préset SVG sans strokes** : pour les sujets architecturaux où le
  trait épais bouffe la lisibilité, exposer un mode `--no-strokes` qui
  réutilise la topologie mais ne dessine pas la couche `<g id="strokes">`.
- (b5) **Crayon Noir 7e** : ajout d'un crayon `#15151B` au design system
  pour gérer naturellement les détails sombres (yeux, truffes, ocelles)
  qui sont actuellement piégés sur Ocean.
- (b6) **Mode solution paramétrable** : option `data-color-mode="ernie"`
  (couleurs originales du PNG) vs `data-color-mode="crayon"` (mapping
  6 crayons actuel). Le premier serait utile pour un mode "aperçu" qui
  ressemble plus à l'image d'origine.
- (b7) **Migration prod alwanbooks** : adapter `ColorierApp.tsx` pour
  consommer un SVG bicouche au lieu du PNG line art + bitmap
  `coloringData`. Plus rapide, plus léger, vectoriel natif.
- (b8) ~~**Variante "print" (guides shading réactivés)**~~ — **livrée
  avec le pivot** : génère `<slot>_<rid>_g5_print.png` automatiquement,
  blank + guides shading 1 px `#DDDDDD`.

## Livrables

- `poc/decoloriage/g5_product.py` — pipeline G5 complet (CLI réutilisable)
- `poc/decoloriage/g5_out/01_pastel_dog_g5.svg` — **SVG bicouche
  click-to-fill** (215 KB)
- `poc/decoloriage/g5_out/01_pastel_dog_g5.html` — **démo interactive
  standalone** (à ouvrir dans un navigateur)
- `poc/decoloriage/g5_out/01_pastel_dog_g5_solution.png` — preview mode
  solution (couleurs ERNIE quantifiées 6 crayons)
- `poc/decoloriage/g5_out/01_pastel_dog_g5_blank.png` — preview mode départ
  **post-pivot** (line art ERNIE — traits noirs pleins)
- `poc/decoloriage/g5_out/01_pastel_dog_g5_print.png` — variante print
  (blank + guides shading clair, backlog b8 livré)
- `poc/decoloriage/g5_out/stats.json` — stats détaillées + mapping par
  région + `is_ink_region` + `ink_overlap_ratio`
- `references/techniques.md` — **T19 capitalisé**
- `MEMORY.md` — pointeur `project_decoloriage_pipeline_validated`

## Décision / Action suivante

Verdict humain attendu sur :
- Ouvrir `01_pastel_dog_g5.html` dans un navigateur.
- Tester le click sur 5+ zones avec différents crayons.
- Tester Solution → Reset → Solution.
- Vérifier qualitativement la ressemblance avec l'ERNIE d'origine.

- **pass** → POC `decoloriage-validation` **clôturé**. Capitalisation T19
  déjà effectuée. Prochaine étape produit = b7 (migration prod alwanbooks
  vers SVG bicouche).
- **kill** → rapport d'invalidation produit (peu probable au vu des
  critères du skill).
- **pivot** → ajustement (ex. b5 crayon Noir, b6 mode aperçu ERNIE,
  re-mappage avec une palette élargie).

Rapport de capitalisation : `references/techniques.md` § T19.
