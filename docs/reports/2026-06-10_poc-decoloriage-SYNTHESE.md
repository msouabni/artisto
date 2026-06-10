# POC — Décoloriage — Synthèse finale
Date : 2026-06-10 (étendu avec batch G5 sur les 10 sujets le même soir)
Statut : **CLÔTURÉ — PASS** (v1) + **EXTENSION BATCH PASS** (v1.1)

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
| **b9** | **Repositionner Prune** : 0 régions / 10 sujets sur corpus pastel ERNIE → soit décaler vers un violet plus central (`#A78BFA`), soit assumer "crayon de choix utilisateur" jamais matché en solution. À traiter avec b5. | G5 batch | nouveau — décision design system |

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

## Extension batch G5 — les 9 sujets restants (v1.1)

Après G5 single-shot sur pastel_dog (v1), batch lancé sur les 9 autres
sujets du corpus avec le même pipeline pivot (encre = fill noir non
cliquable + shading masqué par défaut + toggle Guides).

### Pipeline batch

- Mode `--all` ajouté à `g5_product.py` : itère sur tous les slots du
  corpus, accumule les stats dans un `stats.json` consolidé avec
  `images: [...]` + agrégats globaux.
- **Check automatique tubes creux résiduels** par sujet : une région
  cliquable (non-encre, non-papier) dont l'overlap avec le masque G2
  dilaté dépasse **30 %** est flaggée comme candidate tube creux. Seuil
  intermédiaire entre 0 et le 50 % qui déclenche le classement
  ink-region.
- **ΔE médian** calculé par sujet et globalement.
- Planche galerie 10×2 (`contact_sheet_g5.png`) : blank | solution
  avec stats compactes par ligne (zones cliquables, régions encre,
  arcs, ΔE, distribution crayons, hollow-tube PASS/FAIL).

### Résultats batch

| # | Sujet | Cat. | Zones | Ink-reg. | ΔE méd. | Hollow-tube |
|---:|---|---|---:|---:|---:|---|
| 01 | pastel_dog | animal | 29 | 3 | 44,6 | ✓ |
| 02 | pastel_horse | animal | 37 | 7 | 52,3 | ✓ |
| 03 | pastel_cat | animal | 54 | 6 | 44,6 | ✓ |
| 04 | pastel_elephant | animal | 38 | 19 | 47,8 | ✓ |
| 05 | pastel_lion2 | animal | 52 | 14 | 39,7 | ✓ |
| 06 | taxo_polar_bear_on_ice | scène | 45 | 7 | 43,2 | ✓ |
| 07 | pastel_pirate_ship | scène | 40 | 9 | 46,8 | ✓ |
| 08 | pastel_lighthouse | objet | 46 | 4 | 38,5 | ✓ |
| 09 | pastel_castle | objet | 61 | 15 | 42,1 | ✓ |
| 10 | pastel_peacock | stress | 200 | 9 | 44,6 | ✗ (5 candidats) |

**Hollow-tube global : 9/10 PASS**. Seul peacock (stress-test plumes
répétitives) renvoie 5 candidats tubes creux résiduels : régions à
ocelles ou plumes très fines dont l'overlap est entre 30 % et 50 %.
Accepté tel quel en v1.1 — c'est précisément la sortie attendue du
check (signaler à la revue humaine, pas bloquer).

**Performance** : 15,4 s pour les 10 images. Moyenne ~1,5 s/image,
peacock seul ~3,8 s.

**ΔE médian global** : 44,6 — confirme la limite §2 ci-dessus
(palette saturée vs pastels ERNIE).

### Distribution crayons sur l'ensemble du corpus

| Crayon | Hex | Régions (cumul 10 sujets) |
|---|---|---:|
| Océan | `#118AB2` | 228 |
| Papier | `#ffffff` | 174 |
| Mandarine | `#FF8A2B` | 114 |
| Menthe | `#06D6A0` | 56 |
| Cerise | `#FF2E63` | 24 |
| Citron | `#FFD60A` | 6 |
| **Prune** | **`#8B5CF6`** | **0** ⚠️ |

**Prune n'est jamais utilisée** sur le corpus pastel ERNIE. Les violets
pastels (a\* positif modéré + b\* fortement négatif) sont systématiquement
plus proches de Océan en distance Lab (Océan a un b\* très négatif lui
aussi, et un L\* intermédiaire, alors que Prune a un L\* élevé qui
l'éloigne du violet "vrai"). Conséquences :

- Confirme l'urgence du backlog **b5** (ajout d'un crayon Noir `#15151B`
  pour ne pas forcer les détails sombres sur Océan — qui devient déjà
  saturé visuellement).
- Ouvre un nouveau backlog **b9** : revoir Prune. Soit la repositionner
  dans Lab (vers un violet plus central type `#A78BFA` ou `#9333EA`),
  soit la remplacer par un autre rôle (Magenta, Rose vif), soit accepter
  qu'elle reste un crayon de "choix utilisateur" jamais matché en
  solution.

### Validation visuelle (planche galerie)

`poc/decoloriage/contact_sheet_g5.png` : 10 lignes × 2 colonnes (blank |
solution). Tous les blanks ressemblent à des line-arts ERNIE
(traits noirs pleins, zéro tube creux visible). Toutes les solutions
sont reconnaissables comme leur sujet d'origine, avec quantification 6
crayons + papier.

## Tags

- `poc-decoloriage-v1` — POC initial (dog seul en G5 produit).
- `poc-decoloriage-v1.1` — extension batch (10 sujets + check auto
  tubes creux + planche galerie + insight Prune absente).

## Livrables (récap chemins)

```
poc/decoloriage/
  corpus.json
  g1a_v3_compact.py
  g2_partition.py
  g3_vectorize.py
  g4_two_weight.py
  g5_product.py                            # --all = mode batch (10 sujets)
  make_contact_sheet_g{1a,2,3,4,5}.py
  g{1a,2,3,4,5}_out/*.{npy,png,svg,html,json}
  contact_sheet_g{1a,2,3,4,5}.png          # contact_sheet_g5.png = galerie 10x2

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
