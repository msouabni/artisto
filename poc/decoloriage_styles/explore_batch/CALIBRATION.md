# CALIBRATION — POC2 exploration 4 styles ornementaux

Date : 2026-06-11 · Mode **EXPLORATION** (rien figé catalogue).
Corpus : 4 styles × 3 sujets (dog, castle, peacock) = 12 images ERNIE turbo,
seed=42, 1024×1024. Pipeline POC1 réutilisé par import (g2/g3/g4/g5 +
`_detect_chromakey_mask`). Aucune modif POC1/POC2.

## Distinction structurelle (détermine tout le calibrage)

| Classe | Styles | Fond | Encre native | Approche |
|---|---|---|---|---|
| **Tuiles** | mosaic, zellige | chromakey vert | joints sombres | décoloriage complet (fond→papier, tuiles fidèles, joints=encre) |
| **Line-art natif** | mandala, zentangle | blanc | traits noirs | déjà une page : cellules blanches=régions, traits noirs=encre, pas de couleur d'origine |

## Tableau de calibrage par style (calé, appliqué, mesuré)

| Style | Fond | Partition (niveau + merge ΔE) | Source d'encre | color_mode | Stroke | n_regions méd. | n_clickable méd. | ink_reg méd. |
|---|---|---|---|---|---|---|---|---|
| **mosaic** | chromakey (Δ40) → Papier | adulte + smooth_merge ΔE=16 | joints L<25 → ink-regions (overlap≥0.5) | faithful (hex tuile) | noir #15151B 2px | 1954 | 1465 | 488 |
| **zellige** | chromakey (Δ40) → Papier | adulte + smooth_merge ΔE=14 | joints L<25 → ink-regions | faithful (hex tuile) | noir #15151B 2px | 831 | 481 | 368 |
| **mandala** | blanc L*≥92 → Papier | adulte + smooth_merge ΔE=6 | trait natif L<25 (mince), régions L_moy<28 = encre | blank (blanc-remplissable) | noir #15151B 1.5px | 792 | 720 | 71 |
| **zentangle** | blanc L*≥92 → Papier | adulte + smooth_merge ΔE=6 | trait natif L<25, régions L_moy<28 = encre | blank | noir #15151B 1.5px | 520 | 491 | 28 |

n_clickable par sujet :

| Style | dog | castle | peacock |
|---|---|---|---|
| mosaic | 498 | **1465** | **1515** |
| zellige | 481 | 462 | 694 |
| mandala | 699 | 751 | 720 |
| zentangle | 491 | 450 | 534 |

(En gras : au-dessus de la cible adulte ~800 → page surchargée, voir réserves.)

## Rationale par style

### mosaic (tuiles)
Décoloriage complet : chromakey isole le sujet, les tuiles colorées deviennent
des régions fidèles, les joints sombres l'encre. Itéré 1× (merge ΔE 8→16) pour
réduire le nombre de régions. **Le `dog` (498 régions, grandes plages
cohérentes) est exploitable** : blank = tuiles blanches à joints fins, solution =
tons d'origine. **castle/peacock explosent (1465/1515)** : les tuiles sont si
petites/nombreuses que (a) le compte dépasse largement la cible adulte et (b) le
blank devient une masse noire (les joints L<25 dominent le canvas, il ne reste
que des îlots blancs minuscules). Au-delà de ΔE=16 le merge détruirait
l'esthétique mosaïque. → réserve majeure ci-dessous.

### zellige (tuiles)
Même recette que mosaic, ΔE=14. **Plus robuste** : les 3 sujets restent ≤694
clickable (tuiles géométriques plus grandes que la mosaïque byzantine). dog/castle
~470, peacock 694 (borderline mais < 800). Blank dog/castle lisibles ; peacock
plus chargé. Solution fidèle recognizable sur les 3. Meilleur compromis des deux
styles à tuiles.

### mandala (line-art natif)
Fond blanc → Papier (L*≥92, pas de chromakey nécessaire, ck%=0 confirmé). C'est
déjà une page de coloriage : on garde le trait noir natif fin (L<25) comme encre
et on rend coloriables les cellules blanches. **Itéré 1×** : la 1re passe utilisait
`compute_ink_regions` (overlap avec joints dilatés) qui en line-art dense avalait
TOUTES les cellules en encre (clickable tombait à 11-75). Fix = mode `dark`
(région encre seulement si L_moyen<28 = vrai noir) → clickable remonte à 699-751.
2e itération sur le rendu : le blank PNG empâtait en redessinant 30k+ arcs ; fix =
blank = masque natif fin uniquement (les arcs restent vectoriels dans le SVG
zoomable). **Résultat : blanks propres, fidèles à l'original, exploitables sur les
3 sujets.** Pas de solution couleur (source N&B).

### zentangle (line-art natif)
Même recette que mandala (ΔE=6, mode dark). Encore plus propre : ink_reg médian=28,
clickable 450-534, n_regions le plus bas des 4 styles (520 méd). Blanks =
pages de coloriage adulte denses et nettes sur les 3 sujets. **Le plus régulier
des 4 styles.**

## Réserves / artefacts (à arbitrer côté humain)

- **mosaic castle/peacock = blank trop noir + sur-fragmenté** (1465/1515 régions,
  joints dominants). Même classe de problème que `stained_glass` au POC1.
  Pistes non explorées ici : prompt « larger tesserae » / tuiles plus grandes,
  rendu joints en traits fins (arcs) au lieu de régions pleines, ou SAM2. mosaic
  reste exploitable sur **dog** uniquement en l'état.
- **zellige peacock** borderline (694) — acceptable mais dense.
- **mandala/zentangle = SVG lourds** (8-10 MB, 21k-33k arcs ink). Vectoriel
  zoomable OK, mais à surveiller pour le web (compression / simplification arcs).
- **zentangle_dog : artefact de génération = 2 chiens** (seed 42, prompt
  « single dog »). Le pipeline le reproduit fidèlement (descripteur, pas
  correctif). Re-gen seed si retenu.
- Les blanks PNG des styles à tuiles (mosaic/zellige) sont des **previews** ; le
  livrable interactif réel est le SVG/HTML (régions cliquables vectorielles).

## Synthèse exploitabilité (cible adulte, jugement à l'humain)

| Style | dog | castle | peacock | Note |
|---|---|---|---|---|
| mosaic | OK | blank noir + 1465 | blank noir + 1515 | exploitable seulement sur sujets à grandes plages |
| zellige | OK | OK | borderline | style à tuiles le plus robuste |
| mandala | OK | OK | OK | line-art natif propre, SVG lourd |
| zentangle | OK | OK | OK | le plus régulier des 4 |

Verdict pass/kill **par style = décision humaine** (non rendue ici).
