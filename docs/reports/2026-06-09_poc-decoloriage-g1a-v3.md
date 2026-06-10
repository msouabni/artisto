# POC — Décoloriage G1a v3 — pyrMeanShift + compacité 3×3 + protection ΔE
Date : 2026-06-09

## Contexte

Pivot 2 demandé après G1a v2 : la protection ΔE seule a explosé le nombre de
régions à cause des micro-pixels d'anti-aliasing en bordure de clusters. v3
ajoute (a) un pré-traitement edge-preserving avant k-means pour aplatir les
dégradés et l'AA à la source, et (b) une protection **double** : ΔE76 ≥ 30
**ET** compacité (la région doit survivre à une érosion 3×3). Sinon = sliver
→ fusion forcée.

## Paramètres v3 (delta vs v2)

| Paramètre | v1 | v2 | **v3** |
|---|---|---|---|
| Pré-traitement | — | — | **cv2.pyrMeanShiftFiltering(sp=12, sr=24)** |
| Espace couleur | Lab | Lab | Lab |
| k-means | k=12 | k=12 | k=12 |
| CC | 4-connex. | 4-connex. | 4-connex. |
| Seuil fusion | 0,3 % | 0,05 % | 0,05 % |
| Protection ΔE | — | ΔE76 ≥ 30 | ΔE76 ≥ 30 |
| Protection compacité | — | — | **érosion 3×3 vectorisée (interior_mask_8)** |
| Sliver = non-compact | — | — | **fusion forcée vers voisin de plus grande aire** |

Scripts : `poc/decoloriage/g1a_v3_compact.py`, `poc/decoloriage/make_contact_sheet_g1a_v3.py`.
Sorties : `poc/decoloriage/g1a_out_v3/<slot>_<id>_regions_v3.png`.
Stats : `poc/decoloriage/g1a_out_v3/stats.json`.

## Résultats — récap 3 colonnes (brut / protégées légitimes / final)

| # | Catégorie | ID | brut (CC bruts) | protégées légitimes | **final** | slivers forcés | t v3 |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | animal | pastel_dog | 6 145 | 5 | **35** | 6 109 | 1,08 s |
| 2 | animal | pastel_horse | 8 020 | 14 | **46** | 7 973 | 1,17 s |
| 3 | animal | pastel_cat | 7 710 | 12 | **62** | 7 648 | 1,16 s |
| 4 | animal | pastel_elephant | 8 210 | 29 | **58** | 8 150 | 1,20 s |
| 5 | animal | pastel_lion2 | 9 403 | 21 | **67** | 9 335 | 1,32 s |
| 6 | scène | taxo_polar_bear_on_ice | 6 187 | 22 | **59** | 6 116 | 1,14 s |
| 7 | scène | pastel_pirate_ship | 6 860 | 18 | **53** | 6 802 | 1,24 s |
| 8 | objet | pastel_lighthouse | 3 818 | 9 | **52** | 3 753 | 1,11 s |
| 9 | objet | pastel_castle | 9 229 | 15 | **76** | 9 151 | 1,33 s |
| 10 | stress | pastel_peacock | 17 092 | 105 | **214** | 16 868 | 1,78 s |

**Cible utilisateur 30–150 régions/image** :
- 9/10 dans la cible (35–76 régions). Médiane = 58,5.
- 1/10 hors cible : peacock (214) — stress test, 12 plumes × 3-5 ocelles
  chacune = naturellement plus dense.

## Comparaison G1a v1 → v2 → v3

| ID | v1 (0,3%, sans prot) | v2 (0,05% + ΔE) | **v3 (+ pyrMS + compacité)** |
|---|---:|---:|---:|
| dog | 17 | 6 450 | **35** |
| horse | 16 | 7 922 | **46** |
| cat | 23 | 7 568 | **62** |
| elephant | 13 | 8 001 | **58** |
| lion2 | 22 | 10 158 | **67** |
| polar_bear | 21 | 5 267 | **59** |
| pirate_ship | 16 | 7 030 | **53** |
| lighthouse | 25 | 2 411 | **52** |
| castle | 30 | 9 766 | **76** |
| peacock | 30 | 14 843 | **214** |

v3 multiplie le compte légitime par ~2-3× vs v1 (objectif G4 « régions(c) ≥ 2× régions(a) » déjà
atteint sur 9/10 vs le baseline v1), tout en évacuant 99,5 % des slivers AA qui
parasitaient v2.

## Lecture visuelle des crops zoomés

### Crop œil/face — `pastel_cat`
Livrable : `poc/decoloriage/zoom_crop_eye_v3.png`.
- Les **2 yeux** sortent en région distincte (point sombre central)
- **Truffe** rose sortie distinctement
- **Moustaches** : les traits horizontaux sont préservés en régions étirées
- **Bouche** (ligne sourire) : préservée
- **Intérieurs d'oreille** : pastel rose distinct du contour
- **Joues** : zones de teinte légèrement différente conservées
Critère G1a (skill) « oreilles, taches, collier, crinière sortent comme
régions distinctes » : **satisfait**.

### Crop dégradé/plumes — `pastel_peacock` (stress)
Livrable : `poc/decoloriage/zoom_crop_gradient_v3.png`.
- Les **12 plumes** séparées
- Chaque **ocelle (œil de plume)** sortie avec sa structure concentrique :
  centre sombre + anneau coloré + halo pastel
- Variations chromatiques internes aux plumes préservées sans fragmentation
  excessive
- Le **bec, l'œil et la huppe** du paon clairement isolés
Le compte global (214) est élevé mais visuellement justifié — chaque entité
sémantique a sa région.

## Observations utiles pour G2

1. **pyrMeanShift fait le job amont** : ~3-4× moins de CC bruts qu'en v1/v2
   sur la plupart des images (4-9k au lieu de 7-19k pour peacock). Le coût
   ~1 s/image en plus est compensé par la fusion qui passe de 80 s (v1) à
   ~0,3 s (adjacence vectorisée + moins de candidats).
2. **Compacité 3×3 = filtre AA propre** : 6109/6145 (99,4 %) des CC bruts
   sont des slivers non-compacts sur dog, traités sans aucune décision
   chromatique. Le critère est binaire et déterministe.
3. **Protections « légitimes »** = 5 à 105 par image. Ce sont les entités
   qu'on veut absolument coloriables (yeux, truffes, ocelles, petits motifs).
   Tracking de cette colonne devient une vraie métrique de qualité pour G4.
4. **Pas de pixel orphelin** : la passe de translation finale est exhaustive,
   chaque pixel reçoit un label final.
5. **Performance globale** : 1,1–1,8 s/image (vs 0,7–1,0 s en v2 et 41–165 s
   en v1). Le pré-traitement pyrMS représente ~50 % du coût mais reste
   tractable pour les ×3 seuils de G2.

## Points d'attention

- **Peacock à 214 dépasse la cible 30–150** : on peut redescendre en
  augmentant `protect_contrast` à 35 ou 40 (filtre plus strict, accepterait
  moins de protégées). Mais on perdrait probablement des ocelles. À
  trancher : faut-il une cible/sujet, ou la cible 30–150 est-elle stricte ?
  → La règle G2 « 15–80 régions au seuil médian » sera de toute façon
  recalibrée en G2 avec 3 seuils ; le « adulte » prendrait 100+.
- **Le contour ERNIE est toujours capturé comme région annulaire** (visible
  sur tous les sujets en couleur uniforme). À traiter en G3 (stroke vs
  région coloriable — convention graphique).
- **pyrMeanShift n'a pas perdu les vraies frontières nettes** : les lignes
  ERNIE restent franches après lissage, ce qui valide l'usage de
  pyrMeanShift sur les sorties ERNIE pastel (sujet à valider en G2 sur les
  3 seuils).

## Décision / Action suivante

Verdict humain attendu sur :
- planche `poc/decoloriage/contact_sheet_g1a_v3.png`
- crop œil `poc/decoloriage/zoom_crop_eye_v3.png`
- crop dégradé `poc/decoloriage/zoom_crop_gradient_v3.png`

Trois suites possibles :

- **pass** → G1a clos en v3, G1b inutile (skill), enchaîner G2 (partition
  propre + 3 seuils de fusion + crops zoomés frontières). Le pipeline v3
  servira de socle.
- **fail** → G1b (SAM 2 / FastSAM).
- **pivot** → ajuster (par exemple `protect_contrast` 30 → 35 pour redescendre
  peacock sous 150, ou ajouter une condition topologique supplémentaire).

Aucun gate n'est lancé sans verdict humain explicite.

## Livrables

- `poc/decoloriage/g1a_v3_compact.py` — pipeline v3
- `poc/decoloriage/make_contact_sheet_g1a_v3.py` — planche + crops
- `poc/decoloriage/g1a_out_v3/*.png` — 10 régions colorées v3
- `poc/decoloriage/g1a_out_v3/stats.json`
- `poc/decoloriage/contact_sheet_g1a_v3.png` — **planche contact 5×2 + recap 3 colonnes**
- `poc/decoloriage/zoom_crop_eye_v3.png` — **crop œil/face pastel_cat**
- `poc/decoloriage/zoom_crop_gradient_v3.png` — **crop dégradé/plumes pastel_peacock**

## Notes de cadrage post-verdict (2026-06-10) — à ne pas traiter en G1a

1. **Escalier des frontières (jaggies raster) — résolution en G3.** Le rendu
   v3 actuel laisse des marches d'escalier visibles à zoom 200 % le long des
   frontières (artefact raster attendu de la combinaison kmeans + CC sur une
   grille de pixels). À résoudre en G3 par : simplification Douglas-Peucker
   sur le **graphe de frontières partagées** + lissage de courbe (Chaikin
   subdivision ou fit spline). **Ajouter au critère pass G3** : zéro marche
   d'escalier visible à zoom 200 %.
2. **peacock à 214 régions accepté tel quel.** C'est le stress-test, le
   cadran de fusion G2 gérera la granularité. Ne pas modifier
   `protect_contrast` (laisser à 30).
