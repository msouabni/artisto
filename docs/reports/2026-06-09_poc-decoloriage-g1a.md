# POC — Décoloriage G1a (quantification couleur voie pauvre)
Date : 2026-06-09

## Contexte

Premier gate "voie pauvre" du protocole `decoloriage-validation` (G1a) sur le
corpus gelé en G0 (10 PNG ERNIE pastel). Objectif : tester si une simple
quantification k-means en Lab + connected components + fusion des petites
régions sépare déjà les détails internes des sujets (oreilles, taches, collier,
crinière). Si oui → SAM 2 (G1b) inutile, passage direct à G2.

## Paramètres

| Paramètre | Valeur |
|---|---|
| Espace couleur | Lab (skimage.color.rgb2lab) |
| Algo | cv2.kmeans, init kmeans++, attempts=4 |
| k | 12 (milieu de la plage 10–14 prescrite par le skill) |
| Connected components | scipy.ndimage.label, 4-connexité |
| Seuil fusion | aire < 0.3 % de l'image (≈ 3146 px sur 1024×1024) |
| Stratégie fusion | itérative, du plus petit au plus grand, vers le voisin direct de plus grande aire totale, max 6 passes |
| Rendu | couleur aléatoire par région + contour 1 px noir sur frontières |

Scripts : `poc/decoloriage/g1a_kmeans_lab.py`, `poc/decoloriage/make_contact_sheet_g1a.py`.
Sorties par image : `poc/decoloriage/g1a_out/<slot>_<id>_regions.png`.
Stats brutes : `poc/decoloriage/g1a_out/stats.json`.

## Résultats

### Tableau récap

| # | Catégorie | ID | CC bruts | Régions après fusion | Fusion | Temps total |
|---|---|---|---:|---:|---:|---:|
| 1 | animal | pastel_dog | 7 499 | **17** | 7 482 | 66,3 s |
| 2 | animal | pastel_horse | 8 910 | **16** | 8 894 | 79,6 s |
| 3 | animal | pastel_cat | 9 204 | **23** | 9 181 | 81,3 s |
| 4 | animal | pastel_elephant | 9 178 | **13** | 9 165 | 80,8 s |
| 5 | animal | pastel_lion2 | 11 799 | **22** | 11 777 | 101,4 s |
| 6 | scène | taxo_polar_bear_on_ice | 7 811 | **21** | 7 790 | 66,9 s |
| 7 | scène | pastel_pirate_ship | 7 813 | **16** | 7 797 | 66,6 s |
| 8 | objet | pastel_lighthouse | 4 917 | **25** | 4 892 | 41,5 s |
| 9 | objet | pastel_castle | 10 401 | **30** | 10 371 | 88,1 s |
| 10 | stress | pastel_peacock | 19 433 | **30** | 19 403 | 164,8 s |

Médiane : 21,5 régions après fusion. Plage : 13–30. Temps moyen : ~84 s/image.

### Lecture visuelle — animaux (critère pass)

Critère pass G1a (skill) : « sur les animaux, les détails internes (oreilles,
taches, collier, crinière) sortent comme régions distinctes ».

- **dog** (17 régions) : tête / museau / oreilles tombantes (les 2) / œil-tache /
  nez / langue / pattes avant / pattes arrière / balle / contour ressortent.
- **horse** (16 régions) : corps / crinière (bandes pastel) / queue / sabots /
  pattes séparées / contour.
- **cat** (23 régions) : oreilles, intérieur oreilles, moustaches, yeux, museau,
  pattes et queue distincts.
- **elephant** (13 régions) : corps massif unifié (test inverse passé), oreille,
  défense, œil, patte, sol sortent comme régions distinctes — pas de
  sur-segmentation.
- **lion2** (22 régions) : crinière multi-tons préservée (touffes haut séparées
  du dos), oreilles + intérieurs d'oreille distincts, œil, museau, pattes,
  queue + bout de queue, tapis.

→ Sur les 5 animaux : **5/5 satisfont le critère pass** (les détails internes
sont des régions séparées, le contour ERNIE est lui-même capturé comme une
fine région annulaire).

### Lecture visuelle — scènes / objets / stress

- **polar_bear_on_ice** : ours séparé du bloc de glace, face / corps / pattes /
  langue distincts ; ice block décomposé en glace, eau, poisson, accents.
- **pirate_ship** : coque / voiles / mât / drapeau / eau / vagues / ciel
  ressortent.
- **lighthouse** : bandes alternées du fût, balcon, cabine, île, mer, nuages.
- **castle** : tours, toits, drapeaux (petits), fenêtres, créneaux, porte.
- **peacock** (stress) : les 12 plumes séparées en éventail, **chaque ocelle
  (œil de plume) sort en région distincte** dans la plupart des plumes — c'est
  le résultat le plus fort de la planche.

### Observations utiles pour G2/G3

1. **Le trait noir ERNIE est capturé comme une fine région annulaire de
   couleur sombre** (visible sur chaque sujet en bordure). Bonne nouvelle pour
   G3 : on peut soit le garder comme une région à part traitée différemment
   (stroke), soit le fondre dans le voisin majoritaire selon l'angle adopté.
2. **Le seuil de fusion à 0,3 % est très agressif** (3 146 px sur 1024×1024).
   Il a fait passer de 4 917–19 433 CC bruts à 13–30 régions finales. Le cadran
   de difficulté demandé en G2 (tout-petit / enfant / adulte) sera facile à
   produire en faisant varier ce seuil — la nature de l'algo est bien
   monotone.
3. **Coût** : 84 s/image en médiane, soit ~14 min pour les 10. Goulot = la
   passe de fusion (`merge` représente ~99 % du temps). Pour G2 il faudra
   probablement vectoriser cette étape (RAG/skimage) si on doit la rejouer sur
   3 seuils × 10 images, mais ce n'est pas bloquant pour le verdict G1a.
4. **Robustesse** : aucune image n'a échoué, aucune crash, aucune région
   orpheline.

## Points d'attention

- Le contour annulaire ERNIE pourrait gonfler artificiellement le compte de
  régions en G4 (on compterait `contour` comme une région "coloriable") — à
  trancher en G3/G4.
- Sur `elephant`, le corps est très peu segmenté (13 régions au total) :
  c'est correct vis-à-vis du critère G1a mais cela montre que les défauts
  inverses (sous-segmentation) sont possibles sur silhouettes monochromes.
  À surveiller en G2 quand on calibrera les seuils par cadran.
- Le `min_area_px = 3146` à 0,3 % efface presque toutes les microvariations
  internes (œil de chat, narine, etc.). Le cadran "adulte" en G2 devra
  passer en dessous (probable 0,05–0,1 %) pour récupérer les micro-détails.

## Décision / Action suivante

Verdict humain attendu sur la planche `poc/decoloriage/contact_sheet_g1a.png`.

- Si **pass** → G1b inutile (skill), enchaîner sur **G2** (partition propre +
  3 seuils de fusion + crops zoomés frontières).
- Si **fail** sur certains animaux → G1b (SAM 2 / FastSAM).
- Si **pivot** → reparamétrer (k, seuil fusion, espace couleur) avant de
  passer au gate suivant.

Aucun gate n'est lancé sans verdict humain explicite.

## Livrables

- `poc/decoloriage/g1a_kmeans_lab.py` — pipeline
- `poc/decoloriage/make_contact_sheet_g1a.py` — planche contact
- `poc/decoloriage/g1a_out/*.png` — 10 régions colorées
- `poc/decoloriage/g1a_out/stats.json` — stats brutes
- `poc/decoloriage/contact_sheet_g1a.png` — **planche contact 5×2 (orig | régions)**
