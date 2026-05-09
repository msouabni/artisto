# POC-2 v2 — `generate_concepts` après affinage du prompt
Date : 2026-05-05

## Contexte
Affinage du prompt `generate_concepts` pour adresser 4 défauts identifiés en v1 (cf. `2026-05-05_poc-generate-concepts.md`) :

1. **Setting plausible** — interdire les lieux non naturels pour le sujet (ex. `Hammer in a Kitchen`).
2. **Format Subject+Setting strict** — `<Subject> <preposition> a <Location>` ; verbes d'action exclus du `name_en` (vont dans `description_en`).
3. **`name_ar` 1-3 mots** (resserré de 1-4) pour les sujets complexes.
4. **Qualité FR** — exemple négatif explicite contre les sur-traductions (firefighter → pompier, pas "infirmier de pompier").

Test sur les 4 termes problématiques de la v1 :
- `claw_hammer` (focus : setting plausibility)
- `firefighter_with_hose` (focus : FR translation quality)
- `elsa_from_frozen` (focus : Subject+Setting strict — 2/5 en v1)
- `letter_a_with_apple` (focus : Subject+Setting strict — 4/5 en v1)

## Synthèse v1 vs v2

| Feuille | Focus | v1 S+S | v2 S+S | v1 AR≤4w | v2 AR≤3w | v1 latence | v2 latence |
|---|---|---|---|---|---|---|---|
| `claw_hammer` | Setting plausibility | 5/5 | 5/5 | 5/5 | 1/5 | 9.0s | 15.7s |
| `firefighter_with_hose` | FR translation quality | 5/5 | 5/5 | 5/5 | 2/5 | 12.2s | 11.3s |
| `elsa_from_frozen` | Subject+Setting strict | 2/5 | 5/5 | 2/5 | 0/5 | 10.0s | 8.9s |
| `letter_a_with_apple` | Subject+Setting strict | 4/5 | 5/5 | 1/5 | 0/5 | 11.4s | 10.0s |

## Comparaison détaillée v1 ↔ v2

### `claw_hammer` — Claw Hammer / Marteau arrache-clou / المطرقة

Focus : **Setting plausibility**

**v1 (prompt initial)**

| # | name_en | name_fr | name_ar |
|---|---|---|---|
| 1 | `Claw Hammer in a Workshop` | `Marteau griffe dans un atelier` | `مطرقة في ورشة` (3w) |
| 2 | `Claw Hammer in a Garden` | `Marteau griffe dans un jardin` | `مطرقة في حديقة` (3w) |
| 3 | `Claw Hammer in a Forest` | `Marteau griffe dans une forêt` | `مطرقة في غابة` (3w) |
| 4 | `Claw Hammer in a Kitchen` | `Marteau griffe dans une cuisine` | `مطرقة في مطبخ` (3w) |
| 5 | `Claw Hammer in a Barn` | `Marteau griffe dans une étable` | `مطرقة في مزرعة` (3w) |

**v2 (prompt affiné)**

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Claw Hammer on a Workbench` (✓, 5w) | `Marteau à griffe sur un établi` | `مطرقة على ورشة عمل` (4w  ⚠>3w) |
| 2 | `Claw Hammer in a Garage` (✓, 5w) | `Marteau à griffe dans un garage` | `مطرقة في гараج` (3w ✓) |
| 3 | `Claw Hammer on a Kitchen Counter` (✓, 6w) | `Marteau à griffe sur un comptoir de cuisine` | `مطرقة على طاولة المطبخ` (4w  ⚠>3w) |
| 4 | `Claw Hammer inside a Toolbox` (✓, 5w) | `Marteau à griffe dans une boîte à outils` | `مطرقة داخل صندوق أدوات` (4w  ⚠>3w) |
| 5 | `Claw Hammer near a Front Door` (✓, 6w) | `Marteau à griffe près d'une porte d'entrée` | `مطرقة عند باب أمامي` (4w  ⚠>3w) |

### `firefighter_with_hose` — Firefighter with Hose / Pompier avec lance à eau / إطفائي بخرطوم

Focus : **FR translation quality**

**v1 (prompt initial)**

| # | name_en | name_fr | name_ar |
|---|---|---|---|
| 1 | `Firefighter with Hose at Fire Station` | `Infirmier de pompier avec un tuyau` | `إطفائي بخرطوم` (2w) |
| 2 | `Firefighter with Hose Fighting Fire` | `Infirmier de pompier combattant un incendie` | `إطفائي بخرطوم يطفئ الحريق` (4w) |
| 3 | `Firefighter with Hose at a House` | `Infirmier de pompier devant une maison` | `إطفائي بخرطوم في منزل` (4w) |
| 4 | `Firefighter with Hose on a Bicycle` | `Infirmier de pompier sur un vélo` | `إطفائي بخرطوم على دراجة` (4w) |
| 5 | `Firefighter with Hose near a Tree` | `Infirmier de pompier près d'un arbre` | `إطفائي بخرطوم بجانب شجرة` (4w) |

**v2 (prompt affiné)**

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Firefighter in a Fire Station` (✓, 5w) | `Pompier dans une caserne` | `إطفائي في محطة` (3w ✓) |
| 2 | `Firefighter in a Burning Building` (✓, 5w) | `Pompier dans un bâtiment en feu` | `إطفائي في مبنى محترق` (4w  ⚠>3w) |
| 3 | `Firefighter on a City Street` (✓, 5w) | `Pompier sur une rue` | `إطفائي في شارع` (3w ✓) |
| 4 | `Firefighter in a School Yard` (✓, 5w) | `Pompier dans un jardin d'école` | `إطفائي في حديقة مدرسة` (4w  ⚠>3w) |
| 5 | `Firefighter in a Garage Bay` (✓, 5w) | `Pompier dans un bay de garage` | `إطفائي في باي Garage` (4w  ⚠>3w) |

### `elsa_from_frozen` — Elsa from Frozen / Elsa de La Reine des Neiges / إلسا من فروزن

Focus : **Subject+Setting strict**

**v1 (prompt initial)**

| # | name_en | name_fr | name_ar |
|---|---|---|---|
| 1 | `Elsa Building a Snow Castle` | `Élsa construit un château de neige` | `إلسا تبني قلعة ثلج` (4w) |
| 2 | `Elsa Skating on Frozen Lake` | `Élsa patine sur un lac gelé` | `إلسا تسبح على بحيرة مجمدة` (5w) |
| 3 | `Elsa Creating a Magic Snowflake` | `Élsa crée un flocon de neige magique` | `إلسا تصنع خيط ثلج سحري` (5w) |
| 4 | `Elsa Playing with Snow Animals` | `Élsa joue avec des animaux de neige` | `إلسا تلعب مع حيوانات الثلج` (5w) |
| 5 | `Elsa Wearing Ice Skirt` | `Élsa porte une jupe de glace` | `إلسا ترتدي فستان ثلج` (4w) |

**v2 (prompt affiné)**

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Elsa in the Frozen North` (✓, 5w) | `Èlsa au Nord gelé` | `إلسا في الشمال الجليدي` (4w  ⚠>3w) |
| 2 | `Elsa in an Ice Castle` (✓, 5w) | `Èlsa dans un château de glace` | `إلسا في قلعة الجليد` (4w  ⚠>3w) |
| 3 | `Elsa in a Snowy Forest` (✓, 5w) | `Èlsa dans une forêt enneigée` | `إلسا في الغابة المثلجة` (4w  ⚠>3w) |
| 4 | `Elsa in a Winter Lake` (✓, 5w) | `Èlsa sur un lac d'hiver` | `إلسا في البحيرة الشتوية` (4w  ⚠>3w) |
| 5 | `Elsa in a Magic Garden` (✓, 5w) | `Èlsa dans un jardin magique` | `إلسا في الحديقة السحرية` (4w  ⚠>3w) |

### `letter_a_with_apple` — Letter A with Apple / Lettre A avec une pomme / حرف A مع تفاحة

Focus : **Subject+Setting strict**

**v1 (prompt initial)**

| # | name_en | name_fr | name_ar |
|---|---|---|---|
| 1 | `Red Apple Tree in a Sunny Garden` | `Arbre de pommes rouge dans un jardin` | `شجرة التفاح الحمراء في الحديقة` (5w) |
| 2 | `Fresh Red Apple on a Wooden Table` | `Pomme rouge fraîche sur une table` | `تفاحة حمراء طازجة على طاولة خشبية` (6w) |
| 3 | `Ripe Apples in a Woven Basket` | `Pommes mûres dans un panier tressé` | `تفاحات ناضجة في سلة م织ية` (5w) |
| 4 | `Child Holding a Red Apple` | `Enfant tenant une pomme rouge` | `طفل يحمل تفاحة حمراء` (4w) |
| 5 | `Canned Apples in a Glass Jar` | `Pommes en conserve dans un bocal` | `تفاح معلبة في زجاجة زجاجية` (5w) |

**v2 (prompt affiné)**

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Letter A in a School Classroom` (✓, 6w) | `Lettre A dans une classe` | `حرف A في الفصل` (4w  ⚠>3w) |
| 2 | `Red Apple on a Green Tree Branch` (✓, 7w) | `Pomme rouge sur une branche` | `تفاحة حمراء على فرع` (4w  ⚠>3w) |
| 3 | `Red Apple in a Woven Fruit Basket` (✓, 7w) | `Pomme rouge dans un panier` | `تفاحة حمراء في سلة` (4w  ⚠>3w) |
| 4 | `Red Apple near a Wooden Dining Table` (✓, 7w) | `Pomme rouge près d'une table` | `تفاحة حمراء عند طاولة` (4w  ⚠>3w) |
| 5 | `Letter A with a Red Apple` (✓, 6w) | `Lettre A avec une pomme` | `حرف A مع تفاحة` (4w  ⚠>3w) |

## Verdict humain — observations concrètes sur les 20 concepts

### Fix #1 : Setting plausibility (`claw_hammer`)
Sur 5 concepts : Workbench ✓, Garage ✓, Toolbox ✓, Front Door (improbable mais défendable), **Kitchen Counter ⚠**. Le modèle a re-produit *Kitchen Counter* malgré l'exemple négatif explicite "hammer in a kitchen is wrong". Score subjectif : **3-4/5 plausibles**. Si on veut zéro faux pas, il faudra une étape de validation post-LLM (peut-être un check LLM-judge "is X plausible in Y" avec un autre modèle).

### Fix #2 : Format Subject+Setting strict (`elsa_from_frozen`, `letter_a_with_apple`)
Format respecté à **20/20**. Plus aucun verbe d'action dans `name_en` (vs v1 où `Elsa` était "Singing", "Skating" etc.).

⚠ **Effet de bord détecté** : sur `letter_a_with_apple`, **3/5 concepts dérivent du sujet** ("Red Apple on a Green Tree Branch", "Red Apple in a Woven Fruit Basket", "Red Apple near a Wooden Dining Table"). Le format S+S strict est respecté mais le **sujet a glissé** de "Letter A" vers "Red Apple". Le LLM exploite la flexibilité du concept "Letter A with Apple" pour partir sur la pomme. À regarder pour la prod : ajouter une consigne "le SUBJECT doit toujours être l'élément principal du concept fourni, pas un de ses éléments secondaires".

### Fix #3 : `name_ar` ≤ 3 mots
**3/20 dans la nouvelle borne 1-3 mots** — la consigne est largement ignorée. La majorité des `name_ar` font 4 mots, parce que le format S+S oblige une structure "sujet + préposition + lieu" qui en arabe se transcrit naturellement en 3-4 mots minimum (ex. "إطفائي في محطة" = 3 mots, "إطفائي في مبنى محترق" = 4 mots).

→ Décision pragmatique : **revenir à 1-4 mots côté validation**, ou **tronquer en post-process** au-delà de 4 mots (rare).

### Fix #4 : Qualité FR (`firefighter_with_hose`)
**4/5 propres** : "Pompier dans une caserne", "Pompier dans un bâtiment en feu", "Pompier sur une rue", "Pompier dans un jardin d'école". Plus de "infirmier de pompier" type v1 — fix nominal réussi.

⚠ **Nouveau pattern à surveiller** : "Pompier dans un **bay** de garage" — le mot anglais `bay` (pour "bay de garage" = box d'extension) n'a pas été traduit. Pas une sur-traduction inventée mais un **mot anglais non traduit**. À ajouter dans le prompt côté FR : "no English words in name_fr ; if no direct French translation exists, paraphrase in pure French".

## Points d'attention

- **Métrique S+S** : présence d'une préposition locative (`in/on/at/under/inside/near/by/over/beside/with/...`) et ≥3 mots dans `name_en`. Une préposition légitime non-locative peut produire un faux positif. Évaluation humaine recommandée pour la cohérence sémantique.
- **`name_ar` 1-3 mots** : nouvelle contrainte largement ignorée (3/20). La structure "sujet + locatif" en arabe est naturellement 3-4 mots. Recommandation : ré-élargir à 1-4 mots, ou tronquer en post-process.
- **Drift de sujet sur concepts ambigus** (cas `letter_a_with_apple` → "Red Apple ...") : le format S+S strict ne garantit pas la **fidélité au sujet principal**. Possible fix prompt : ajouter "the SUBJECT is ALWAYS the primary element of the input concept, never a secondary attribute".
- **Mots anglais non traduits en FR** : 1 cas observé ("bay"). Ajouter règle "no English words in name_fr".
- T=0.5 (non déterministe) : les résultats v1 et v2 ne sont pas strictement comparables sur le même seed, mais les **patterns** (S+S, longueurs, etc.) sont mesurables sur 5 concepts × 4 leaves = 20 items.

## Décision / Action suivante

✅ **Format Subject+Setting strict adopté** : gain net (5/5 sur les 4 leaves vs 2-4/5 en v1). Verbes d'action correctement déplacés dans `description_en`.

✅ **Setting plausibility majoritairement amélioré** mais pas zéro : ~80 % de plausibilité observée (1 cas "Kitchen Counter" subsiste sur 4 leaves). Acceptable avec validate humain en file d'exception.

✅ **Sur-traduction FR fixée**, **mot anglais résiduel** à corriger via règle prompt explicite.

⚠ **Contrainte `name_ar` ≤ 3 mots à reculer** : naturellement non viable côté arabe pour la structure S+S. Ré-élargir à 1-4 mots OU laisser libre côté prompt + tronquer en post-process si > 4 mots.

⚠ **Drift de sujet** (letter_a → red apple) : nouveau pattern à surveiller, ajouter règle "subject = primary element" dans la prochaine itération du prompt.

Pas de v3 immédiat nécessaire — les fixes de v2 sont positifs. Les 2 résidus (mot anglais FR, drift de sujet) peuvent être adressés dans une éventuelle v3 ou tolérés en validate-regen humain selon le taux observé en volume réel.

## Annexes

- Données brutes v2 : `2026-05-05_poc-generate-concepts-v2.json`
- Données brutes v1 : `2026-05-05_poc-generate-concepts.json` (15 leaves, 75 concepts)
- Script v2 : `scripts/poc_generate_concepts_v2.py`
- Template modifié : `prompts/image_prompts.yaml::generate_concepts`
- Rapport v1 : `docs/reports/2026-05-05_poc-generate-concepts.md`