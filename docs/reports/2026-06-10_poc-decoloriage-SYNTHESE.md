# POC — Décoloriage — Synthèse finale
Date : 2026-06-10
Statut : **CLÔTURÉ — PASS**

## Hypothèse pré-enregistrée

> *Sur 5 sujets animaliers, le pipeline « décoloriage » produit ≥ 2× plus
> de régions coloriables que le line art ERNIE direct, avec des frontières
> fermées par construction. Si < 2× au gate G4 → kill assumé, documenter
> dans la section "Invalidées" de `references/techniques.md`.*

Source : `.claude/skills/ecoloriage-validation/SKILL.md` § Hypothèse.

## Verdict

**Validée empiriquement** sur 5/5 animaux du corpus G0 figé :

| # | Sujet | (a) line art ERNIE direct | (c) décoloriage enfant | ratio c/a |
|---|---|---:|---:|---:|
| 1 | pastel_dog | 7 | 32 | **4,57×** ✓ |
| 2 | pastel_horse | 14 | 44 | **3,14×** ✓ |
| 3 | pastel_cat | 8 | 60 | **7,50×** ✓ |
| 4 | pastel_elephant | 19 | 57 | **3,00×** ✓ |
| 5 | pastel_lion2 | 12 | 66 | **5,50×** ✓ |

Hors animaux : 9/10 du corpus passent ≥ 2×. Seul `pastel_castle` à 1,55×
(architecture déjà très détaillée en line art ERNIE natif).

G5 (produit) livré et validé humainement : SVG bicouche click-to-fill,
mapping 6 crayons par ΔE Lab, démo standalone fonctionnelle (palette,
solution, reset, toggle Guides).

## Les 5 gates

| Gate | Date | Verdict | Livrables clés | Rapport |
|---|---|---|---|---|
| G0 — Corpus gelé | 2026-06-09 | pass | `poc/decoloriage/corpus.json` (10 images, 5 animaux+2 scènes+2 objets+1 stress), planche contact | inclus dans pivots G1a |
| G1a — Quantification couleur OpenCV | 2026-06-09 | pass après 2 pivots (seuil 0,05 % + ΔE ≥ 30 ; puis pyrMeanShift + compacité 3×3) | `g1a_v3_compact.py`, planche 10×4 + 4 zooms | [g1a](2026-06-09_poc-decoloriage-g1a.md), [pivot](2026-06-09_poc-decoloriage-g1a-pivot.md), [v3](2026-06-09_poc-decoloriage-g1a-v3.md) |
| G2 — Partition propre 3 cadrans | 2026-06-10 | pass conditionnel sur tout-petit (familles + fallback greedy) | `g2_partition.py`, 3 niveaux × 10 images + `lines/*.png` | [g2](2026-06-10_poc-decoloriage-g2.md) |
| G3 — Vectorisation anti-slivers | 2026-06-10 | pass (0,000 % non couvert) après 2 fixes (padding sentinel + skip-Chaikin sur bords) | `g3_vectorize.py`, 10 SVG, diff, zooms triples, browser test | [g3](2026-06-10_poc-decoloriage-g3.md) |
| G4 — Hiérarchie de traits 2 poids | 2026-06-10 | **pass — hypothèse validée 5/5** | `g4_two_weight.py`, 10 SVG topologiques, planche 10×3 (a/b/c) | [g4](2026-06-10_poc-decoloriage-g4.md) |
| G5 — Bout en bout produit | 2026-06-10 | pass après pivot (régions-encre noir non cliquables + shading masqué + toggle Guides) | `g5_product.py`, SVG + HTML standalone + blank/solution/print PNG, mapping 6 crayons ΔE Lab | [g5](2026-06-10_poc-decoloriage-g5.md) |

## Pipeline final (récap technique)

```
ERNIE pastel (PNG colorié)
    │
    │  prompt : "soft pastel children's coloring illustration"
    │           + flat colors / cel shading / no gradients
    ▼
G1a v3 : pyrMeanShiftFiltering(sp=12,sr=24) + k-means Lab k=12
         + connected components 4-conn + fusion < 0,05 %
         + protection ΔE ≥ 30 + compacité 3×3
    ▼
G2 enfant : smooth_merge_similar(thresh=12)
            avec immunité protected_ids
    │       (tout-petit conditionnel — voir limites)
    ▼
G3 : find_contours padding sentinel + Douglas-Peucker tol 1 px
     + Chaikin closed 2 iter + snap-to-edges
    ▼
G4 : graphe topologique des frontières partagées
     (chaque arc dessiné UNE fois)
     + classification ink/shading via overlap ≥ 60 % avec masque G2 dilaté 3 px
     + calibrage : ink = 2·median(distanceTransform(line_mask))
                   shading = ink/3
    ▼
G5 (pivot 2026-06-10 PM) :
     + détection régions-encre : overlap ≥ 50 % → fill #111111,
       pointer-events:none, exclues du compteur
     + arcs shading : class="arc-shading" + CSS stroke:none par défaut
     + toggle Guides → .show-guides .arc-shading { stroke:#DDDDDD; stroke-width:1 }
     + mapping data-color = nearest crayon ΔE Lab
       (Cerise/Mandarine/Citron/Menthe/Océan/Prune)
     + L* ≥ 92 → Papier (fond ne se peint pas)
    ▼
SVG bicouche click-to-fill + HTML standalone
```

## Limites assumées

### 1. Tout-petit conditionnel

Validé sur sujets organiques mono-sujet (dog, polar_bear, lion2…). Échoue
sur composites/architecturaux (castle, pirate_ship, peacock) — la fusion
par familles de couleurs n'écrase pas les zones distinctes (drapeaux,
voiles, ocelles), résultat = trop de protected restants. Heuristique
publication :

```
publishable_tp = (non_protected_final ≤ 12) AND (protected_immune ≤ 15)
```

Sur le corpus : 5/10 sont `publishable_tp`. Les 5 autres restent
publiables en niveau enfant et adulte uniquement.

Mémoire : [[decoloriage-tout-petit-conditional]].

### 2. Palette crayons saturés vs pastels ERNIE — ΔE médian ~44

Les pastels ERNIE ont une chroma basse (L\* élevé, a\*/b\* modérés). Les
6 crayons design system sont saturés (chroma élevée). Conséquence :

- ΔE médian mesuré sur pastel_dog = ~44 (très loin du seuil de
  perception 2–3).
- Distribution biaisée : pastel_dog n'utilise que 3 crayons en mode
  solution (Ocean, Mandarine, Menthe — pas de Cerise/Citron/Prune).
- Le mode solution est une lecture **stylisée**, pas une reproduction
  fidèle. La spec G5 du skill demandait "ressemble", pas "identique" → OK.

Conséquence produit : copy UX de la palette à formuler en termes de
"6 crayons pour s'exprimer" plutôt que "6 crayons qui matchent ta photo".

## Backlog (non bloquant pour publication)

| # | Item | Source | État |
|---|---|---|---|
| b1 | Détecter et fusionner les `protected` répétitifs (≥ 5 régions de signature très proche = motif décoratif) | G2 closure | non implémenté |
| b2 | Fusion contrainte par le masque de traits : épais = barrière, fin = franchissable. Donnerait un tout-petit propre sur sujets architecturaux | G2 closure | non implémenté |
| b3 | Approche topologique pure pour les fills (suppression du stroke anti-sliver de G3) | G3 closure | non implémenté — non requis depuis G4 (topologie déjà appliquée aux strokes) |
| b4 | Préset SVG sans strokes pour sujets architecturaux | G5 closure | non implémenté |
| **b5** | **Ajouter un crayon Noir #15151B au design system** pour gérer naturellement les yeux/truffes/ocelles qui sont aujourd'hui forcés sur Ocean | G5 closure | non implémenté (décision design system) |
| **b6** | **Mode solution paramétrable** : option `data-color-mode="ernie"` (couleurs originales) vs `data-color-mode="crayon"` (mapping actuel) | G5 closure | non implémenté |
| **b7** | **Migration prod alwanbooks** : adapter `ColorierApp.tsx` pour consommer un SVG bicouche au lieu du PNG + bitmap | G5 closure | non implémenté — chantier prod distinct |
| **b8** | **Variante "print" (guides shading réactivés en clair)** pour impression papier coloriage adulte | G5 pivot | **livrée** : `<slot>_<rid>_g5_print.png` généré automatiquement, guides 1 px `#DDDDDD` |

## Capitalisations

- `references/techniques.md` § **T19** — Décoloriage : ERNIE pastel +
  segmentation → coloriage 2 poids. Pipeline complet G0→G5, tableau
  5/5 animaux, mention pivot encre/shading, mention 6 crayons +
  exception Papier L\* ≥ 92.
- `MEMORY.md` →
  [[decoloriage-pipeline-validated]] — décision archi : remplace le
  pipeline binarisation+potrace pour le coloriage interactif.
- `MEMORY.md` → [[decoloriage-tout-petit-conditional]] —
  pré-existant, limite assumée.

## Tag

`poc-decoloriage-v1` — sentinel de l'état final du POC, contenant les
scripts G1a→G5, les rapports gates + synthèse, et les capitalisations
T19 + MEMORY.

## Livrables (récap chemins)

```
poc/decoloriage/
  corpus.json
  g1a_v3_compact.py
  g2_partition.py
  g3_vectorize.py
  g4_two_weight.py
  g5_product.py
  make_contact_sheet_g{1a,2,3,4}.py
  g{1a,2,3,4,5}_out/*.{npy,png,svg,html,json}
  contact_sheet_g{1a,2,3,4}.png

docs/reports/
  2026-06-09_poc-decoloriage-g1a.md
  2026-06-09_poc-decoloriage-g1a-pivot.md
  2026-06-09_poc-decoloriage-g1a-v3.md
  2026-06-10_poc-decoloriage-g2.md
  2026-06-10_poc-decoloriage-g3.md
  2026-06-10_poc-decoloriage-g4.md
  2026-06-10_poc-decoloriage-g5.md
  2026-06-10_poc-decoloriage-SYNTHESE.md   # ce document

references/techniques.md                    # T19 capitalisé
```

## Décision

POC `decoloriage-validation` **clôturé**. Hypothèse pré-enregistrée
validée. Pipeline prêt pour la prod via chantier b7 (migration
`ColorierApp.tsx` vers SVG bicouche). Tag `poc-decoloriage-v1` créé.
