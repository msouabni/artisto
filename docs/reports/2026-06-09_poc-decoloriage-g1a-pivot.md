# POC — Décoloriage G1a (pivot) — seuil 0,05 % + protection ΔE Lab
Date : 2026-06-09

## Contexte

Pivot demandé sur G1a après le run v1 (seuil 0,3 %). Hypothèse à tester :
en abaissant le seuil de fusion à 0,05 % **ET** en protégeant les régions à
fort contraste Lab moyen avec leurs voisines, on récupère les détails fins
écrasés en v1 (yeux, truffes, ocelles, taches).

## Paramètres v2 (delta vs v1)

| Paramètre | v1 | v2 (pivot) |
|---|---|---|
| Espace couleur | Lab | Lab |
| k | 12 | 12 |
| Connected components | 4-connexité | 4-connexité |
| Seuil fusion | 0,3 % (≈ 3 146 px) | **0,05 % (≈ 524 px)** |
| Règle de protection | aucune | **ΔE76 moyen ≥ 30 ⇒ région non fusionnable** |
| Métrique contraste | — | Euclidien Lab sur la moyenne Lab par région |
| Adjacence | dilation par région (O(K·N)) | **vectorisée np.unique + union-find** |

Scripts : `poc/decoloriage/g1a_v2_protected.py`, `poc/decoloriage/make_contact_sheet_g1a_v2.py`.
Sorties : `poc/decoloriage/g1a_out_v2/<slot>_<id>_regions_v2.png`.
Stats : `poc/decoloriage/g1a_out_v2/stats.json`.

## Résultats — récap avant/après

| # | Catégorie | ID | régions v1 (0,3% sans prot.) | **régions v2 (0,05% + prot.)** | fusion v2 | protected v2 | t v2 |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | animal | pastel_dog | 17 | **6 450** | 1 049 | 6 420 | 0,73 s |
| 2 | animal | pastel_horse | 16 | **7 922** | 988 | 7 889 | 0,81 s |
| 3 | animal | pastel_cat | 23 | **7 568** | 1 636 | 7 518 | 0,82 s |
| 4 | animal | pastel_elephant | 13 | **8 001** | 1 177 | 7 971 | 0,81 s |
| 5 | animal | pastel_lion2 | 22 | **10 158** | 1 641 | 10 111 | 0,86 s |
| 6 | scène | taxo_polar_bear_on_ice | 21 | **5 267** | 2 544 | 5 230 | 0,81 s |
| 7 | scène | pastel_pirate_ship | 16 | **7 030** | 783 | 6 995 | 0,88 s |
| 8 | objet | pastel_lighthouse | 25 | **2 411** | 2 506 | 2 369 | 0,76 s |
| 9 | objet | pastel_castle | 30 | **9 766** | 635 | 9 705 | 0,89 s |
| 10 | stress | pastel_peacock | 30 | **14 843** | 4 590 | 14 735 | 1,05 s |

## Lectures visuelles

- **Effets recherchés OBTENUS** : sur `pastel_dog`, l'œil (point rouge), la
  truffe (gris foncé), la ligne de bouche, l'oreille intérieure sortent comme
  petites régions distinctes. Sur `pastel_peacock`, chaque ocelle de plume
  reste préservée avec ses 2-3 cercles concentriques de teinte. Sur
  `taxo_polar_bear_on_ice`, le museau, l'œil, le bord de patte et les détails
  du bloc de glace sont retenus.

- **Effet secondaire massif et indésirable** : ~99 % des « régions protégées »
  sont en réalité des **micro-pixels d'anti-aliasing** sur les frontières
  entre clusters k-means. Ils sont visuellement absorbés par le trait noir
  (ils tombent dans le contour ERNIE) mais ils gonflent le compte à 2 411 –
  14 843 par image, contre 13 – 30 en v1.

## Analyse du « pourquoi 6 000+ régions protégées »

La protection ΔE76 ≥ 30 appliquée **après** un k-means k=12 est, par
construction, presque toujours vraie : les centroïdes Lab des 12 clusters
sont par définition étalés dans l'espace Lab, donc deux régions voisines
issues de clusters différents ont **toujours** un grand ΔE entre elles
(typiquement 30+). Toute composante connexe sub-pixel à une frontière de
cluster (= bord de transition) est donc protégée d'office.

Le seuil de fusion 0,05 % (~524 px) n'attrape même pas la majorité de ces
micro-régions : la plupart font 1–20 px (anti-aliasing à 1024×1024). Elles
**deviennent éligibles** au merge mais la règle ΔE les en empêche.

→ Le pivot remplit son objectif **sémantique** (préserver yeux/truffes/ocelles)
mais **invalide la métrique** « nombre de régions » comme proxy de qualité,
car le compte est dominé par les artefacts AA.

## Points d'attention pour G2

1. **Métrique de qualité** : il faut compter les régions « utilisables »
   (aire > X px, ex. 100 ou 200 px) et non toutes les composantes connexes.
   Sinon, le critère G4 « régions(c) ≥ 2× régions(a) » devient ininterprétable.
2. **Filtre anti-AA avant protection** : avant d'évaluer ΔE, faire passer
   chaque petite région par un test « ai-je un voisin de la même classe
   k-means via une chaîne d'AA ? ». Si oui, fusion forcée. Ce serait
   l'application du *« filtre global vs critère spatial »* déjà capitalisé
   en mémoire : ici, ne pas filtrer par ΔE seul, mais identifier les pixels
   adverses (AA) et basculer sur un critère spatial (longueur de la frontière
   commune > seuil) ou de population (présence d'un même cluster k-means
   adjacent).
3. **Seuil 0,05 % VS protection** : les deux paramètres jouent sur des plans
   différents. Le seuil de fusion contrôle la taille minimale ; la protection
   contrôle l'identité chromatique. On peut combiner avec un critère
   topologique (ex. *« la région est-elle entourée à >70 % par un même
   voisin ? »* → fusion forcée même si ΔE haute).
4. **Performance** : adjacence vectorisée + union-find = ~0,8 s/image (vs 84 s
   en v1). Le coût n'est plus un problème pour G2 (×3 seuils sur 10 images).

## Décision / Action suivante

Le pivot a **rempli son but explicite** (protéger les détails fins) mais
**révèle un effet secondaire critique** : la métrique « nombre de régions »
n'est plus opérante sans filtre anti-AA. Trois options pour la suite :

- **A. Accepter v2 tel quel** comme état G1a et passer à G2 — on traitera
  l'anti-aliasing comme un problème distinct en G2 (post-process : fusion par
  longueur de frontière, par topologie, ou simple ouverture morphologique
  avant CC).
- **B. Pivot supplémentaire G1a v3** : ajouter dans la même passe un filtre
  anti-AA (ex. exiger que la région ait au moins N pixels de bordure communs
  avec un seul voisin pour passer la protection) avant de relancer.
- **C. Garder v1 comme baseline pour G2** et traiter les détails fins
  uniquement en G2 via un seuil de fusion variable (le cadran de difficulté
  prévu : tout-petit / enfant / adulte). Le « adulte » prendra naturellement
  les yeux / truffes / ocelles.

Verdict humain attendu sur la planche `poc/decoloriage/contact_sheet_g1a_v2.png`.

## Livrables

- `poc/decoloriage/g1a_v2_protected.py` — pipeline v2
- `poc/decoloriage/make_contact_sheet_g1a_v2.py` — planche v1 vs v2
- `poc/decoloriage/g1a_out_v2/*.png` — 10 régions colorées v2
- `poc/decoloriage/g1a_out_v2/stats.json` — stats v2
- `poc/decoloriage/contact_sheet_g1a_v2.png` — **planche contact 5×2 avec colonne avant/après**
