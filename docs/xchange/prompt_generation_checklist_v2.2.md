# Checklist de génération de prompts — Plateforme coloriage Alwan Books

**Version** : 2.2  
**Modèle cible** : ERNIE-Image-Turbo Q8_0 GGUF (ComfyUI custom workflow)  
**Statut** : règles validées empiriquement sur 14 phases de tests + 14 prompts d'échantillon de validation (moyenne 8.5/10)  
**Public final** : enfants 3–12 ans

---

## 0. Préambule — pourquoi cette v2.0

La v1.x supposait que le modèle cible était Z-Image Turbo. La v2.0 est entièrement recalibrée sur **ERNIE-Image-Turbo Q8 quantifié GGUF** dans le setup ComfyUI réel : Mistral 3B comme text encoder, flux2-vae, CFG 1.0, 8 steps euler/normal. Les patterns observés sont propres à cette config et peuvent ne pas s'appliquer à d'autres setups ERNIE.

13 phases de tests ont été menées (A à Z avec sous-phases), couvrant la calibration technique, les patterns comportementaux, les frontières de capacité, les cas hors-portée, et les zones débloquées créativement.

---

## 1. Configuration technique validée

### 1.1 Workflow ComfyUI — paramètres de référence

| Paramètre | Valeur retenue | Notes |
|---|---|---|
| Modèle UNET | `ernie-image-turbo-Q8_0.gguf` | Quantification 8-bit, quasi-lossless |
| VAE | `flux2-vae.safetensors` | |
| Text encoder | `ministral-3-3b.safetensors` | Mode `stable_diffusion`, device `default` |
| Sampler | `euler` | Validé Phase 2 (test sampler implicite) |
| Scheduler | `normal` | |
| Steps | **8** | Optimum confirmé pour version Turbo |
| CFG | **1.0** | Standard pour les modèles distillés Turbo |
| Denoise | `1` | |

### 1.2 Résolutions

| Résolution | Usage | Verdict |
|---|---|---|
| **1024 × 1024** | Sujets équilibrés, scènes carrées (humain+entité, multi-sujets en file horizontale courte) | Validé |
| **1376 × 768** | Sujets panoramiques, frises narratives, scènes multi-zones | Validé Phase G |
| **848 × 1264** | Sujets verticaux (humain debout, animal grand, paysage portrait, format A4) | Validé G2 = `perfect` |
| **896 × 1200** | — | ⚠️ **À éviter** — produit un effet photocopie sur l'arrière-plan (G3 KO) |

### 1.3 Negative prompt standard v3 (validé Phase H)

```
no colors, extra legs, third leg, duplicate limbs, fused legs, 
malformed anatomy, wrong number of limbs, six fingers, deformed feet 
no motion, no fill colors, no intersection, no change in ink 
transparency for different plan only black stroke
```

**Insight critique sur "no change in ink transparency for different plan only black stroke"** : le modèle appliquait inconsciemment une convention de dessinateur (perspective atmosphérique = traits gris pâle pour les éléments éloignés, traits noirs uniformes pour le sujet principal). Cette convention casse l'imprimabilité pour le coloriage (formes non fermées, traits gris). L'instruction explicite force un trait noir uniforme partout. **Six phases successives présentaient ce défaut avant cette correction.**

---

## 2. Méta-pattern fondamental — le substrat spatial

C'est l'apprentissage le plus important de toute la session de tests, et il dépasse largement le cas `decorative_numbers` d'origine.

### 2.1 Énoncé

> ERNIE-Turbo Q8 ne sait pas compter dans l'absolu. Il dérive systématiquement de ±1 ou ±2 dès que N ≥ 6 en composition libre.  
>  
> En revanche, il sait **suivre un layout** et **placer des objets dans un substrat spatial régulier**.  
>  
> **Toute tâche de comptage exact ou de gestion de N éléments distincts doit être reformulée en tâche de placement spatial dans une grille structurée.**

### 2.2 Grilles validées

| Type de grille | Capacité | Usages |
|---|---|---|
| **Linéaire 1×N (N ≤ 7)** | ✅ Validé | Frises narratives (life cycles, étapes, séquences temporelles), scènes d'équipe alignées |
| **Carrée 3×3 = 9 cases** | ✅ Validé | Comptage 6-9, imagiers différenciés, émotions, vocabulaire visuel |
| **Rectangulaire 2×4 = 8 cases** | ⚠️ Limite haute | OK structurellement mais bias culturel sur sujets distribués (X3 — voir §5.4) |
| **Carrée 4×4 = 16 cases** | ✅ Validé pour contenu simple | Sudoku visuel, page-énigme, contenus répétitifs |
| **Maze 5×5** | ✅ Validé | Labyrinthes, pages-jeux |
| **Damier 8×8 alterné** | ❌ Hors capacité | Pas plus de 9 cases avec alternance |

### 2.3 Cas d'usage débloqués par le méta-pattern

| Type de page | Volume taxonomie estimé |
|---|---|
| Imagiers différenciés 3×3 (fruits, vêtements, instruments…) | ~80 feuilles |
| Frises narratives 1×N (life cycles, saisons, recettes étapes) | ~30 feuilles |
| Comparatifs avant/après 1×2 | ~20 feuilles |
| Imagiers avec annotations textuelles 3×3 (émotions, couleurs nommées) | ~50 feuilles |
| Pages-jeux labyrinthes 5×5 | bonus inattendu |
| Pages-énigmes sudoku 4×4 | bonus inattendu |

**Total débloqué : environ 180 feuilles** auparavant considérées difficiles ou hors-pattern.

---

## 3. Quand utiliser cette checklist

Pour chaque génération de prompt destiné à une page de coloriage. Suivre les étapes dans l'ordre.

Pour une génération en lot (ex : 50 feuilles d'un sous-thème), valider sur un échantillon aléatoire de 3 prompts, puis appliquer en masse via template.

---

## 4. Phase amont — avant d'écrire le prompt

### 4.1 Identifier la classe du sujet

Cinq classes, chacune avec ses pièges propres et son pattern validé.

| Classe | Pattern à appliquer | Pièges principaux |
|---|---|---|
| **Solo objet/animal** | Composition centrée simple | Vue frontale risquée, fond trop chargé |
| **Solo humain** | Quantification "one single" obligatoire | Duplication par effet miroir (cf. piège "both") |
| **Humain + entité** | Formule asymétrie gauche/droite | Symétrie miroir, taille relative incohérente |
| **Multi-sujets ≤ 3** | Formule procession | Symétrie persistante |
| **Multi-sujets 4-9** | **Grille visible obligatoire** (méta-pattern) | Composition plate, comptage incorrect, scène incohérente |
| **Multi-sujets ≥ 10** | Composition PIL post-traitement | Hors capacité du modèle |

### 4.2 Identifier le risque IP

| Type | Action |
|---|---|
| Personnage nommé sous copyright (Pikachu, Batman, Elsa) | Production en version générique pour usage commercial. Version A pour benchmark/test interne uniquement. |
| Personnage de domaine public (contes européens, mythologies, figures historiques avant 1928) | Production directe. |
| Sujet générique (animaux, métiers, objets) | Production directe. |

### 4.3 Sujets explicitement hors capacité

Ne pas tenter avec ce setup. Basculer sur pipeline alternatif.

| Sujet | Raison | Alternative |
|---|---|---|
| Texte arabe (lettres, mots, calligraphie) | Faible représentation dataset | Pipeline SVG avec polices Reem Kufi / Tajawal |
| Géométrie 3D exacte (solides platoniciens) | Pas de précision mathématique | Manim / Pythreejs / SVG paramétrique |
| Tessellations parfaites (zellige, kufique) | Combo niche dataset + structure stricte | SVG paramétrique |
| Comptage exact ≥ 10 | Limite architecturale | Composition PIL post-génération |
| Sujets géographiques distribués (8 continents avec animaux) | Bias asiatique du modèle Baidu | Une feuille par sujet, pas regroupés |
| Compositions non-linéaires (vol en V, cercle, dispersion) | Indices spatiaux contradictoires | Disposition linéaire ou en grille |
| Tracking de membres en pose active | Le modèle compense en ajoutant un bras | Pose statique ou énumération explicite |

---

## 5. Structure standard du prompt

### 5.1 Architecture en 6 blocs (cas standard)

```
[1 STYLE COLORIAGE] , [2 QUALITÉ LIGNE] , [3 FOND] ,
[4 SUJET QUANTIFIÉ + POSITIONNÉ] ,
[5 ATTRIBUTS / VÊTEMENTS / EXPRESSION] ,
[6 COMPOSITION + CADRAGE] , [7 ÉLÉMENTS DE DÉCOR MINIMAUX]
```

### 5.2 Bloc 1 — Style coloriage (immutable)
```
coloring book page for kids
```
**Ne jamais omettre.** Active le mode "ligne pure" du modèle.

### 5.3 Bloc 2 — Qualité de la ligne (immutable v2)
```
black and white line art, thick clean outlines, no shading, 
no grayscale, no fill
```

### 5.4 Bloc 3 — Fond (immutable)
```
white background
```
Sauf cas spécifique extrêmement rare (scène spatiale avec fond noir étoilé), toujours fond blanc pour préserver l'imprimabilité.

### 5.5 Bloc 4 — Sujet (le bloc critique)

**Cinq sous-cas selon la classe** — voir §6.

### 5.6 Bloc 5 — Attributs

- Décrire l'expression du visage : `smiling`, `happy face`, `friendly expression`
- 2-3 éléments vestimentaires max, sinon le modèle s'éparpille
- ✅ OK : `the child wears overalls and a sun hat`
- ❌ Trop : `overalls, sun hat, red boots, checkered shirt, backpack with flowers, bracelet`

### 5.7 Bloc 6 — Composition

Phrases-clés validées par classe :

| Phrase | Cas d'usage |
|---|---|
| `full body view` | Par défaut humains/animaux |
| `centered composition` | Solo simple |
| `asymmetric composition` | **Obligatoire** humain+entité |
| `three quarter view` | Casser la frontalité |
| `off-center composition` | Force secondaire anti-symétrie |
| `procession from left to right` | Multi-sujets en file |
| `balanced spacing` | Multi-sujets sans ordre directionnel |

### 5.8 Bloc 7 — Décor minimal

Pour préserver l'imprimabilité :
- ✅ `simple ground line` (préféré à un sol détaillé)
- ✅ `simple background`
- ✅ `a few simple clouds`
- ❌ `detailed mountain range with rivers and forests` — sature la page

---

## 6. Patterns par classe

### 6.1 Solo objet ou animal

**Formule** :
```
[ARTICLE] [SUJET] [POSITION] [POSE/CONTEXTE]
```

**Exemple validé** :
```
a single farm horse standing in profile in a meadow
```

**Règles** :
- ✅ Article indéfini singulier (`a`, `an`)
- ✅ Préciser la **vue** (`in profile`, `from a three-quarter angle`, `front view`)
- ✅ Préciser la **pose** (`standing`, `running`, `sitting`)
- ⚠️ Vues frontales d'animaux possibles avec quantification mais à valider au cas par cas

### 6.2 Solo humain

**Formule** :
```
one single [HUMAIN] [POSITION DANS LE CADRE] [ACTION] [ATTRIBUTS]
```

**Règles critiques** :
- ✅ **`one single`** au lieu de `a` — quantification explicite obligatoire (validé empiriquement)
- ✅ Expression au singulier : `the child smiling`, jamais `both smiling`
- ❌ **JAMAIS le mot "both"** si tu veux un seul humain — déclencheur de duplication confirmé
- ⚠️ Devant un miroir/objet réfléchissant : préciser `viewed from the side, three-quarter angle` pour casser le bias miroir
- Pour un objet de décor unique mentionné (`a bathroom mirror`, `a window`) : ajouter `only one [OBJET], no other [OBJET] in the scene` (le modèle peut dupliquer les objets de décor même si le sujet humain est correct)

### 6.3 Humain + entité (formule canonique validée)

**Formule** :
```
one single [HUMAIN] standing on the [LEFT/RIGHT] side of [ENTITÉ] in [LIEU],
the [HUMAIN] [ACTION], the [HUMAIN] smiling, the [HUMAIN] wears [ATTRIBUTS],
asymmetric composition, [ENTITÉ] positioned on the [RIGHT/LEFT] side of the image,
full body of both, simple ground line
```

**Les 3 leviers indispensables** (sinon → duplication ou symétrie systématique) :
1. **`one single child`** — bloque la duplication quantitative
2. **Positionnement explicite gauche/droite** — casse le réflexe symétrique
3. **`asymmetric composition`** — instruction stylistique directe

**Cas spécial** : interaction main-objet mécanique (vélo, etc.) moins fiable que main-organique (chien, plante). Pour vélos/voitures/etc., préférer `child sitting on a bicycle, riding it` à `child holding bicycle handlebars`.

### 6.4 Multi-sujets identiques (procession)

**Formule canonique** :
```
exactly N [SUJETS] walking in a single procession from [LEFT/RIGHT]
to [RIGHT/LEFT], all N [SUJETS] in profile facing [RIGHT/LEFT],
the first [SUJET] at the leftmost position, the second [SUJET]
behind the first, the [Nth] [SUJET] at the rightmost position,
all moving in the same direction, no [SUJETS] facing each other,
asymmetric processional composition
```

**Mots-clés critiques** :
- ✅ **"procession"** ou **"single file"** — pas "in a row"
- ✅ **"from left to right"** ou **"from right to left"** explicite
- ✅ **"first... behind first... behind second..."** — séquence narrative
- ✅ **"no [SUJETS] facing each other"** dans le prompt **et** dans le negative

⚠️ **Limite cartographiée** : à partir de 5 sujets, l'espacement se dégrade. Au-delà de 6, instabilité forte. **Au-delà de 7, basculer sur grille** (voir §6.5).

### 6.5 Multi-sujets via grille (méta-pattern)

C'est le pattern le plus puissant validé en session. Voir §2.

**Formule grille 3×3 (pour 6 à 9 éléments)** :
```
a tic-tac-toe game grid of three rows by three columns making nine 
empty square cells, the grid centered on the page, place one [OBJET] 
in the top-left cell, place one [OBJET] in the top-center cell, 
place one [OBJET] in the top-right cell, place one [OBJET] in the 
middle-left cell, [...continuer cellule par cellule...], 
leave the [CELLULES RESTANTES] completely empty, only [N] [OBJETS] 
total, no other elements
```

**Formule frise 1×N (pour séquences narratives ou scènes d'équipe)** :
```
a horizontal row of [N] empty rectangular cells drawn with thick 
black lines, all cells the same size and clearly separated, each cell 
shows [DESCRIPTION DE LA CASE], [...énumération case par case...], 
balanced composition
```

**Variantes débloquées** (validées Phase X) :
- Imagier différencié 3×3 (9 objets différents même catégorie)
- Frise narrative 1×5 (cycle de vie, saisons)
- Comparatif 1×2 avant/après
- Sudoku visuel 4×4 partiel
- Labyrinthe 5×5 avec parcours
- Imagier annoté 3×3 (objet + mot par case)

### 6.6 Multi-sujets différenciés (Justice League, scène de famille)

Lister chaque sujet avec attributs distinctifs en utilisant des tirets :

```
group of [NOMBRE] [DESCRIPTION GLOBALE] —
one with [TRAIT 1],
one with [TRAIT 2],
one with [TRAIT 3] —
all [ACTION COMMUNE], full body, balanced spacing
```

⚠️ **Anti-pattern validé Z5b** : pour 4+ personnages dans une scène d'équipe partagée (cuisine, bureau, classe), **utiliser frise 1×N visible** plutôt que panoramique partagé. Le panoramique sans grille produit des compositions plates ou des incohérences spatiales.

---

## 7. Negative prompt — par défaut + variantes

### 7.1 Negative standard v3 (toujours appliqué)

```
no colors, extra legs, third leg, duplicate limbs, fused legs, 
malformed anatomy, wrong number of limbs, six fingers, deformed feet 
no motion, no fill colors, no intersection, no change in ink 
transparency for different plan only black stroke
```

### 7.2 Ajouts pour solo humain (anti-duplication)

Ajouter au negative standard :
```
two children, multiple children, twin children, mirrored children,
duplicate person, symmetric composition, mirror image, identical figures
```

### 7.3 Ajouts pour scènes humain + entité

Combiner 7.2 + :
```
mirrored figures, centered composition
```

### 7.4 Ajouts pour multi-sujets identiques

```
fused subjects, merged figures, identical poses,
overlapping bodies, indistinct faces
```

### 7.5 Ajouts pour scènes kid-friendly (anti-effrayant)

```
scary, dark, gloomy, frightening, sharp teeth, blood,
dark shadows, menacing expression, evil look
```

À ajouter pour : antagonistes (sorcières, dragons, Joker), mythologie (Méduse, Anubis), Halloween.

### 7.6 Ajouts pour scènes avec comptage

```
extra elements, additional items, wrong count, N+1 elements,
more than expected, fewer than expected
```

Pour comptage > 4 : ajouter aussi par type d'objet :
```
extra [OBJECT], additional [OBJECT], duplicate [OBJECT]
```

### 7.7 Ajouts anti-membres en trop pour pose active

Dès qu'un personnage est en pose active (écrire, pointer, lever, tendre, frapper) :
```
extra arm, third arm, three arms, multiple arms,
extra leg, third leg, additional limb, duplicate limb, extra hand
```

---

## 8. Vérification post-génération

### 8.1 Grille de scoring 0-3 sur 5 critères (max 15)

| Critère | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Style coloriage** | Couleur ou photo | Beaucoup de gris/hachures | Quelques zones grises | B&W strict, lignes propres |
| **Anatomie** | Inexploitable | Erreurs visibles | Mineures | Correcte |
| **Conformité au prompt** | Hors-sujet | Sujet OK mais scène fausse | Sujet + scène mais détails manqués | Tout y est |
| **Imprimabilité** | Trop dense | Densité limite | Bon équilibre | Excellentes zones blanches |
| **Kid-friendly** | Effrayant | Limite | OK | Parfait pour 3-12 ans |

**Seuils** :
- < 9 → inutilisable, régénérer
- 9-12 → retouche manuelle acceptable
- ≥ 13 → exploitable directement

### 8.2 Détection des erreurs récurrentes

| Symptôme | Cause | Correction |
|---|---|---|
| Deux humains identiques côte à côte | Mot "both" + composition centrée | Section 6.2 |
| Animal centré + sujets dupliqués des deux côtés | Bias miroir | Ajouter `asymmetric composition` + position explicite |
| Faces mélangées en multi-sujets | Pas de différenciation | Section 6.6 — attributs distinctifs |
| Cheval/animal avec 5-6 pattes | Pose dynamique | Réduire complexité ou ajouter `four legs visible` |
| Sabots/mains/pieds déformés | Détails complexes en bord | `full body view, centered framing with margin` |
| Page envahie de traits | Trop d'éléments décor | Simplifier décor, garder `simple ground line` seul |
| Shading/grisé persistant | Bias modèle | Renforcer bloc 2 : `ABSOLUTELY no shading, no gray tones, no hatching, no crosshatching` |
| Personnage avec bras/jambes en trop | Pose active sollicitant un membre | Énumérer chaque membre : `one arm holding X, the other arm at his side, two arms total` |
| Comptage incorrect ±1 ou ±2 | Faiblesse architecturale > 4 | Énumérer positions + `only N total no more no less`, ou basculer en grille |
| "1" élément demandé mais 2 produits | Paradoxe du singulier | Triple emphase : `exactly one single X, only one X no more, no duplicate X` |
| Multi-sujets en file produits en miroir | Bias symétrie persistant | Formule "procession" + direction explicite + séquence narrative |
| Texte arabe corrompu | Hors capacité | Pipeline SVG avec polices |
| Géométrie pure ratée (solides 3D) | Architecture diffusion | Pipeline SVG/manim |
| Effet photocopie sur arrière-plan | Résolution non native (ex : 896×1200) | Utiliser 1024×1024 ou 848×1264 ou 1376×768 |
| Duplication d'objet de décor (mur en double) | Le modèle duplique objets décoratifs nommés | Quantifier les objets décor : `only one [OBJET], no other [OBJET]` |
| Composition plate avec 4+ personnages | Anti-pattern panoramique partagé | Basculer en frise 1×N visible |
| **Même sujet répliqué N fois quand on demandait "N different X"** | Modèle ne fait pas de boucles de variation depuis catégorie générique | **Énumérer chaque variant explicitement** : `first a rabbit, second a fox, third a deer, fourth a bear` |
| **Vocabulaire spécialisé interprété en chimère** (flying squirrel → chauve-souris) | Termes rares confondus | Utiliser noms d'animaux universels |
| **Catégories trop proches confondues** (sparrow/swallow/hawk) | Silhouettes peu distinctes | Choisir des silhouettes franchement différentes (owl, eagle, duck) |
| **Le modèle "triche"** : items quasi-identiques avec micro-différences | Pas de variations dans le dataset pour cette catégorie | Reformuler avec items vraiment différents OU accepter et capitaliser sur "presque pareil" |

---

## 9. Workflow recommandé pour génération en lot

Pour 50+ feuilles d'un sous-thème :

1. **Sélectionner 3 feuilles aléatoires** dans le sous-thème
2. **Construire les prompts** avec cette checklist
3. **Générer 4 variantes** de chaque (seeds différents) → 12 images
4. **Scorer** avec la grille §8.1
5. **Si moyenne ≥ 11/15** : valider le pattern, appliquer en masse via template
6. **Si moyenne < 11/15** : itérer avant de continuer

Cette boucle évite de générer 50 images ratées d'un coup. Coût : ~10 minutes de calibration par sous-thème, économise des heures de retouche.

---

## 10. Cas d'usage débloqués créativement (Phase X)

Six nouveaux types de pages validés en session de tests, à intégrer dans la stratégie de production :

| Type | Pattern | Volume taxonomie estimé |
|---|---|---|
| **Imagier différencié 3×3** | Grille 3×3 avec un objet différent par case + titre | 80 feuilles |
| **Frise narrative 1×5** | Rangée de cases avec progression temporelle | 30 feuilles |
| **Comparatif before/after 1×2** | Deux cases avec même sujet en deux états | 20 feuilles |
| **Imagier annoté 3×3** | Grille 3×3 avec objet + mot dans chaque case | 50 feuilles |
| **Pages-jeux (labyrinthes)** | Grille 5×5 avec parcours start/end | bonus |
| **Pages-énigmes (sudoku visuel)** | Grille 4×4 partiellement remplie + instruction | bonus |

---

## 11. Patterns artistiques validés (Phase Z)

Sept patterns avancés validés en session. À intégrer dans le répertoire de production.

| Pattern | Note Z | Application taxonomie |
|---|---|---|
| Coupe transversale + labels (Z1) | 7/10 | Anatomie pédagogique, fruits coupés, schémas |
| Réflexion miroir contrôlée (Z2) | 9/10 | Scènes lac/étang/eau calme |
| Texture nommée (tricot, grain de bois) (Z3) | 8/10 | Vêtements, surfaces, motifs structurés |
| Cadrage dans cadrage (Z4) | 9/10 | Intérieur+extérieur via fenêtre |
| 4 personnages activités distinctes en panoramique (Z5) | 6/10 → frise 1×4 → 8/10 | Toujours préférer frise (anti-pattern Z5b) |
| Symétrie volontaire (papillon, mandala) (Z6) | Perfect | Mandalas, motifs décoratifs |
| Action figée + motion lines (Z7) | Perfect | Sports en plein action, cascades, sauts |

---

## 11bis. Compositions multi-plans validées (Phase P)

Trois conventions multi-plans validées empiriquement, à intégrer dans la stratégie de production.

### 11bis.1 — Convention positionnelle pure (top/middle/bottom)

**Validée P4 = perfect.** Le pattern le plus solide pour 2 ou 3 plans. La page est divisée par des **lignes horizontales explicites** en sections, chaque section contenant son propre groupe d'éléments. Ne mentionne jamais les concepts photographiques (foreground/background) qui peuvent réveiller le bias de transparence d'encre.

**Formule** :
```
the page is divided into [N] horizontal sections by [N-1] parallel ground lines, 
in the top section [CONTENU AVEC SUJETS NOMMÉS], in the middle section 
[CONTENU AVEC SUJETS NOMMÉS], in the bottom section [CONTENU AVEC SUJETS NOMMÉS], 
all sections clearly separated by horizontal lines, all elements drawn with 
the same uniform black line thickness, no perspective distortion between sections
```

### 11bis.2 — Convention foreground/background (avec énumération)

**Validée P2c = perfect.** Convention photographique acceptable **à condition** de :
- Énumérer explicitement chaque sujet
- Renforcer le bloc anti-transparence dans le prompt
- Ajouter `no atmospheric perspective, all lines equally bold black`

**Formule** :
```
two distinct planes composition: in the background plane [SUJET 1 SIMPLE 
COMME UNE SILHOUETTE], in the foreground plane [SUJETS NOMMÉS UN PAR UN 
EN ÉNUMÉRATION], both planes drawn with identical line weight and same ink 
intensity, no atmospheric perspective, all lines equally bold black
```

### 11bis.3 — Grille empilée multi-plans

**Validée P6c = perfect.** Combine deux méta-patterns validés : la grille (§2.2) + les plans (§11bis). Le **pattern le plus puissant** pour les compositions structurées riches.

**Formule** :
```
the page is divided into [N] stacked horizontal frames each containing its 
own row of cells, the top frame contains a row of [M] cells, first cell with 
[ITEM 1], second cell with [ITEM 2], [...], the middle frame contains a row 
of [M] cells, first cell with [...], the bottom frame contains a row of 
[M] cells, [...], the [N] frames clearly separated by thick horizontal lines, 
all cells the same size within each frame, balanced composition
```

### 11bis.4 — Anti-patterns multi-plans

| Anti-pattern | Pourquoi | Solution |
|---|---|---|
| **Plans avec catégories très proches** (sparrow/swallow/hawk) | Le modèle confond et finit par dupliquer | Prendre des silhouettes très différentes (owl, eagle, duck) |
| **Plans avec vocabulaire spécialisé** (flying squirrel) | Le modèle interprète mal et fabrique des chimères | Utiliser les noms les plus universels possibles |
| **3 plans + écosystème complexe** (canopée/tronc/sol avec poses physiques) | Surcharge cognitive | Simplifier l'organisation OU simplifier les sujets, pas les deux |
| **Demande "N different X"** sans énumération | Le modèle réplique le même prototype N fois | Énumérer explicitement chaque variant |

---

---

## 11ter. Règles affinées par échantillon de validation production

Quatre règles supplémentaires identifiées en validation sur 14 prompts d'échantillon réels de la taxonomie. Ces règles complètent les patterns de §6, §10, §11.

### 11ter.1 — Règle des décors entièrement visibles (Insight A)

Quand on mentionne un élément de décor dans le prompt, le modèle peut le **dessiner partiellement** (tronqué au bord, à moitié visible, sortant du cadre). C'est récurrent et systémique.

**Règle** : pour tout élément de décor mentionné, préciser explicitement qu'il doit être **entièrement visible**.

| ❌ À éviter | ✅ Préférer |
|---|---|
| `one acacia tree silhouette in the distance` | `one full acacia tree silhouette completely visible in the distance` |
| `a bicycle in the corner` | `one complete bicycle fully visible` |
| `a window with curtains` | `one full window with curtains, the entire window frame visible` |

**Mots-clés à ajouter** : `fully visible`, `completely visible`, `entire X visible`, `the whole X drawn`.

### 11ter.2 — Épuisement attention en fin de frise (Insight B)

Sur les frises 1×N, la **dernière case** est moins bien rendue que les premières. Le modèle "épuise son attention" au fil de l'énumération.

**Règles** :
- Pour les frises 1×3 : pas de précaution particulière, OK direct
- Pour les frises 1×4 : enrichir la dernière case avec **plus de détails** que les cases précédentes (compenser l'épuisement)
- Pour les frises 1×5 et plus : non testé empiriquement, **valider sur 1×3 ou 1×4 d'abord**, ne pas généraliser sans contrôle

**Pattern à appliquer** :
```
[...première case description courte...]
[...deuxième case description courte...]
[...troisième case description courte...]
the rightmost cell shows [DESCRIPTION DÉTAILLÉE ET ENRICHIE], 
[ATTRIBUTS SPÉCIFIQUES DE LA FIN], [POSE OU ACTION CLAIRE]
```

Ou alternative : terminer le prompt par un **rappel synthétique** des 4 cases pour réactiver l'attention.

### 11ter.3 — Règle "une transition à la fois" (Insight C)

Pour les comparatifs **avant/après** ou les frises avec **persistance d'identité** (le même sujet dans plusieurs cases), le modèle gère **une transition à la fois**. Plusieurs changements simultanés produisent des incohérences (ex : main qui écrit dans le vide quand le bureau a disparu).

**Règle** : entre deux cases d'un comparatif/persistance, ne demander **qu'une seule différence**.

| Cas | ✅ OK | ❌ Risqué |
|---|---|---|
| Avant/après chambre rangée | "même chambre, dans le before le sol est jonché de jouets / dans le after le sol est dégagé" | "même chambre + enfant qui range + lumière allumée vs éteinte" |
| Saisons d'un arbre | "même arbre, seules les feuilles changent" | "même arbre + animaux qui changent + sol qui change" |
| Avant/après deforestation | "mêmes arbres et animaux disparus" | "arbres disparus + sol pollué + ciel plus sombre + animaux différents" |

Si tu veux deux ou plusieurs changements, **deux options** :
1. Accepter une incohérence partielle et corriger en post
2. Découper en **deux comparatifs distincts** (chacun avec son propre changement isolé)

### 11ter.4 — Règle de la posture explicite (Insight D)

Pour les **postures non-standard**, le modèle revient à la **pose de repos par défaut** si on ne précise pas explicitement la posture du corps. Symptôme typique : "oiseau debout dans le ciel" (corps vertical, pattes pendantes) au lieu de l'oiseau en vol.

**Règle** : pour tout sujet en posture non-statique-au-sol, expliciter la position du corps.

| Cas | ❌ Insuffisant | ✅ Explicite |
|---|---|---|
| Oiseau en vol | `a bird flying in the sky` | `a bird flying with wings spread open and body horizontal in flight pose` |
| Animal qui saute | `a rabbit jumping` | `a rabbit mid-jump with all four legs off the ground and body fully extended` |
| Plongeur dans l'air | `a diver jumping into water` | `a diver mid-air in horizontal diving pose with arms stretched forward` |
| Ballon qui flotte | `a balloon floating up` | `a balloon floating high in the air with its string trailing below` |
| Feuilles qui tombent | `falling leaves` | `leaves falling through the air at various tilted angles, some upside down, in mid-fall poses` |

**Application taxonomie** : règle critique pour `birds` (en vol), `sports_in_action`, `weather_phenomena` (objets qui tombent), `dance_in_motion`, `gymnastics`.

---

## 12. Maintenance de la checklist

Cette checklist évolue. Règles d'amendement :

- ✅ Ajouter un pattern à §10 ou §11 quand un nouveau prompt est validé ≥ 13/15 (ou 9/10 dans la notation utilisée)
- ✅ Ajouter une entrée au tableau §8.2 quand un nouveau symptôme récurrent est identifié
- ✅ Ajouter une variante de negative prompt à §7 quand un nouveau type d'erreur résiste
- ⚠️ Ne **jamais retirer** un bloc immutable sans avoir testé la déviation sur ≥ 5 prompts
- ⚠️ Ne **jamais raccourcir** le bloc qualité ligne (§5.3) — chaque mot a été validé empiriquement
- ⚠️ Le negative prompt v3 est validé. Toute modification doit passer par un test comparatif côté à côté.

---

## 13. Limites connues — ce que cette checklist ne résout pas

Pour transparence et planification du backlog :

- **Texte arabe** : nécessite pipeline SVG séparé, hors scope de cette checklist
- **Géométrie 3D pure** : idem, pipeline parallèle nécessaire
- **Comptage exact ≥ 10** : composition PIL post-génération obligatoire
- **Sujets géographiques distribués** : doivent être traités feuille par feuille, jamais regroupés
- **Vol en V / formations non-linéaires** : à substituer par dispositions linéaires
- **Effet photocopie** sur résolutions non-natives autres que 1024², 848×1264, 1376×768

Ces limites sont **architecturales**, pas des bugs à résoudre. Elles définissent le périmètre où le pipeline ERNIE-Turbo Q8 ComfyUI est productif. Pour le hors-périmètre, prévoir d'autres outils.

---

**Fin de la checklist v2.0**
