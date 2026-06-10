# POC — Décoloriage G4 — Hiérarchie de traits à 2 poids
Date : 2026-06-10

## Contexte

G4 du protocole `decoloriage-validation`. Verdict esthétique humain attendu.
Le squelette G3 (trait fin uniforme) a été validé comme topologie mais refusé
comme rendu final. G4 introduit une **hiérarchie de traits à 2 poids** :

- **Encre** : strokes épais sur les frontières qui coïncident avec le trait
  noir natif d'ERNIE (≥ 60 % des pixels de l'arc tombent dans le masque G2
  dilaté 3 px).
- **Shading** : strokes fins sur les autres frontières (subdivisions
  internes induites par la quantification couleur).

L'épaisseur du trait encre est **calibrée par image** sur l'épaisseur médiane
du trait ERNIE mesurée par distance transform sur le masque G2. Shading ≈ 1/3.

**Changement architectural majeur vs G3** : les strokes forment maintenant
une **couche topologique unique** (chaque frontière dessinée une seule fois,
arcs extraits du graphe de frontières partagées). Plus de doubles traits
aux interfaces inter-régions.

Hypothèse pré-enregistrée du skill : **régions(c) ≥ 2 × régions(a) sur les
5 animaux** (avec (a) = line art ERNIE direct, (c) = décoloriage). Si validée,
G4 pass et capitalisation T19.

## Pipeline

| Étage | Description |
|---|---|
| 1. Extraction arcs topologiques | `extract_topological_arcs` : vectorise les cracks, identifie les coins-jonctions (≥ 3 labels), trace les arcs jonction-à-jonction + boucles fermées. Padding sentinel pour cracks de bord. |
| 2. Mesure épaisseur trait ERNIE | `measure_line_thickness` : `cv2.distanceTransform` sur le masque G2, médiane des distances × 2 (px). Calibrage par image (variabilité ERNIE). |
| 3. Classification ink/shading | `classify_arc_into_ink_or_shading` : rasterise l'arc en 1-px sur canvas temporaire, calcule overlap avec masque G2 dilaté 3 px. Seuil 60 %. |
| 4. Lissage des arcs | DP tol 1.0 px + Chaikin ouvert 2 iter. Skip Chaikin si arc touche bord (préserve coins images). |
| 5. SVG 2-couches | Fill layer (per-region, G3 reuse) sans stroke + Stroke layer (arcs topologiques avec 2 poids), `stroke-linejoin="round"` et `stroke-linecap="round"`. |
| 6. Comptage (a) | CC du complément du masque de traits binarisé. |
| 7. Comptage (c) | `len(unique(region_map enfant))` (G2). |

Scripts : `poc/decoloriage/g4_two_weight.py`, `poc/decoloriage/make_contact_sheet_g4.py`.

## Paramètres

| Param | Valeur |
|---|---|
| Seuil ink overlap | 60 % |
| Dilatation masque traits | 3 px (square structuring element) |
| DP tolerance | 1,0 px |
| Chaikin arcs | 2 iter (open-curve) |
| Chaikin régions (fill) | 2 iter (closed-curve) |
| Ratio shading / encre | 1/3 |
| Stroke color | `#15151B` |
| `stroke-linejoin` / `stroke-linecap` | `round` |

## Résultats

### Hypothèse pré-enregistrée — animaux (5/5 pass)

| # | Sujet | (a) zones line art | (c) zones décoloriage | ratio c/a | Pass ≥ 2× |
|---|---|---:|---:|---:|---|
| 1 | pastel_dog | 7 | 32 | **4,57** | ✓ |
| 2 | pastel_horse | 14 | 44 | **3,14** | ✓ |
| 3 | pastel_cat | 8 | 60 | **7,5** | ✓ |
| 4 | pastel_elephant | 19 | 57 | **3,0** | ✓ |
| 5 | pastel_lion2 | 12 | 66 | **5,5** | ✓ |

**5/5 animaux satisfont le critère**. L'hypothèse pré-enregistrée est
**validée empiriquement** sur le corpus G0.

### Stats étendues — corpus complet

| # | Cat. | ID | (a) | (c) | ratio | arcs encre | arcs shading | ink stroke (px) | shading stroke (px) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | animal | pastel_dog | 7 | 32 | 4,57 | 37 | 37 | 6,4 | 2,1 |
| 2 | animal | pastel_horse | 14 | 44 | 3,14 | 49 | 46 | 4,4 | 1,5 |
| 3 | animal | pastel_cat | 8 | 60 | 7,5 | 63 | 84 | 6,4 | 2,1 |
| 4 | animal | pastel_elephant | 19 | 57 | 3,0 | 57 | 35 | 5,6 | 1,9 |
| 5 | animal | pastel_lion2 | 12 | 66 | 5,5 | 80 | 58 | 4,4 | 1,5 |
| 6 | scène | taxo_polar_bear_on_ice | 6 | 52 | 8,67 | 60 | 68 | 5,6 | 1,9 |
| 7 | scène | pastel_pirate_ship | 20 | 49 | 2,45 | 52 | 33 | 5,6 | 1,9 |
| 8 | objet | pastel_lighthouse | 14 | 50 | 3,57 | 32 | 61 | 4,4 | 1,5 |
| 9 | objet | pastel_castle | 49 | 76 | 1,55 | 75 | 20 | 4,4 | 1,5 |
| 10 | stress | pastel_peacock | 44 | 209 | 4,75 | 116 | 307 | 4,4 | 1,5 |

Note : 9/10 satisfont ≥ 2× même hors animaux. Seul `castle` (1,55×) ne le
satisfait pas — son line art ERNIE natif est déjà très riche (49 zones,
architecture détaillée).

Temps : 0,6–2,8 s/image. Moyenne ~1 s.

## Lecture visuelle

`contact_sheet_g4.png` (10×3 — colonnes (a), (b), (c)) :

| Sujet | (a) line art | (b) binarize+potrace | (c) décoloriage 2 poids |
|---|---|---|---|
| dog | 7 zones, oreilles + corps + paws confondus | Line drawing N&B, mêmes 7 zones implicites | Eye + truffe **noirs nets** (encre), shading internes pour les patches de couleur. Stroke épais 6 px autour silhouette. Coloring book qualité prod. |
| lion2 | 12 zones, crinière en 1-2 blocs | Identique (b)=(a) vectorisé | Mèches de crinière séparées (shading), 2 yeux + museau + nez en encre, moustaches fines en shading, paw pads. |
| polar_bear | 6 zones (ours+glace+fond) | Idem | Œil + truffe en encre, glace décomposée en shading. Le shading subtil de la glace devient enfin visible et coloriable. |
| peacock (stress) | 44 zones (plumes seulement) | Idem | 209 zones avec ocelles préservées en encre, plumes en shading. |
| castle | 49 zones (architecture fine native) | Idem | Seul sujet où (a) approche (c) — l'architecture ERNIE est déjà très détaillée. |

Le contraste (b) ↔ (c) est saisissant : la baseline (b) est une **page line
art noir/blanc**, alors que (c) est une **page coloring book complete**
(fills + 2 poids de traits) prête pour la publication ou l'interactivité.

## Vérification des critères pass

| Critère | Valeur | Statut |
|---|---|---|
| Hypothèse régions(c) ≥ 2× régions(a) sur 5 animaux | 5/5 | ✓ |
| Strokes en couche unique (pas de double trait) | Implémentation `extract_topological_arcs` — chaque crack visité une seule fois | ✓ |
| Calibrage stroke sur épaisseur médiane ERNIE | `measure_line_thickness` → 4,4–6,4 px ink, 1,5–2,1 px shading selon image | ✓ |
| Classification ink/shading via masque G2 dilaté 3 px, seuil 60 % | Implémenté `classify_arc_into_ink_or_shading` | ✓ |
| `stroke-linejoin` + `stroke-linecap` round | Présent dans le `<g id="strokes">` | ✓ |

## Points d'attention

1. **Architecture désormais propre** : le graphe topologique de frontières
   partagées (introduit en G4) est la fondation correcte pour G5 (coloriage
   interactif click-to-fill). Chaque frontière a une identité unique → on
   peut attacher des métadonnées (data-color, region-id) par frontière.
2. **Performance acceptable** : ~1 s/image. La passe Python sur les cracks
   (~ 30-100k/image) est la partie la plus lente mais reste tractable.
3. **`castle` à 1,55×** : sujet architectural avec line art ERNIE déjà très
   détaillé. Confirme l'observation G2 : les sujets composites/architecturaux
   bénéficient moins du décoloriage (hypothèse 2× plus difficile à
   satisfaire). N'invalide pas la validation animaux.
4. **Stroke shading très fin (1,5 px)** sur certains sujets : risque de
   lisibilité au print. À ajuster lors de la mise en prod (probablement un
   floor à 2 px shading + 4 px ink).
5. **Masque traits G2 = ground truth** pour la classification ink/shading.
   Si le masque a des trous (traits coupés), des arcs encre passeraient en
   shading. À surveiller en G5.

## Livrables

- `poc/decoloriage/g4_two_weight.py` — pipeline G4
- `poc/decoloriage/make_contact_sheet_g4.py` — planche verdict
- `poc/decoloriage/g4_out/<slot>_<id>_g4.svg` — **10 SVG 2 poids**
- `poc/decoloriage/g4_out/<slot>_<id>_g4_render.png` — rasterisation
- `poc/decoloriage/g4_out/<slot>_<id>_a_line_art.png` — visualisation (a)
- `poc/decoloriage/g4_out/<slot>_<id>_b_binarize_potrace.png` — simulation (b)
- `poc/decoloriage/g4_out/stats.json` — stats consolidées + hypothesis_check
- **`poc/decoloriage/contact_sheet_g4.png`** — planche verdict 10×3

## Décision / Action suivante

Verdict humain attendu sur `contact_sheet_g4.png` et au moins 3 SVG G4
ouverts (animal, scène, stress).

- **pass** → G5 (bout en bout produit : SVG bicouche avec data-color mappé
  sur 6 crayons, injection dans composant interactif click-to-fill) +
  **capitalisation T19** dans `references/techniques.md` :
  *prompts coloriés "flat colors, cel shading, no gradients" + pipeline
  décoloriage*.
- **kill** → rapport d'invalidation.
- **pivot** → ajustement (ex. floor 2 px shading, seuil ink 60 → 50 %).

Aucun gate G5 lancé sans verdict humain explicite.
