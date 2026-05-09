# POC qualitatif — Mickey Mouse (qwen3.5:4b)
Date : 2026-05-05

## Contexte
Test qualitatif de **qwen3.5:4b** en conditions réelles sur le thème *"Mickey Mouse"*. Étape 1 : génération de **20 sujets** (concepts) via le template `generate_concepts` du projet. Étape 2 : génération du contenu éditorial complet (title / title_card / description / keywords) dans les **3 locales (EN / FR / AR)** pour les **5 premiers concepts**, avec ancrage AR sur `ميكي ماوس` (Mickey Mouse) et strip harakat post-process. **Aucune métrique automatique** — la qualité linguistique est laissée à l'évaluation humaine.

## Étape 1 — 20 sujets de coloriage générés

| # | name_en | name_fr |
|---|---|---|
| 1 | Mickey Mouse in an Adventure Island | Mickey dans une île aventure |
| 2 | Mickey Mouse at a Pizza Party | Mickey à une fête de pizza |
| 3 | Mickey Mouse on a School Bus | Mickey dans un bus scolaire |
| 4 | Mickey Mouse in a Battle Ship | Mickey dans un navire de bataille |
| 5 | Mickey Mouse in a Moon Base | Mickey dans une base lunaire |
| 6 | Mickey Mouse in a Banana Tree | Mickey dans un arbre de bananes |
| 7 | Mickey Mouse in a Circus Camp | Mickey dans un camp de cirque |
| 8 | Mickey Mouse in a Tennis Match | Mickey dans un match de tennis |
| 9 | Mickey Mouse on a Rainbow Bridge | Mickey sur un pont arc-en-ciel |
| 10 | Mickey Mouse in a Flying Car | Mickey dans une voiture volante |
| 11 | Mickey Mouse at a Birthday Cake | Mickey à un gâteau d'anniversaire |
| 12 | Mickey Mouse in a Happy House | Mickey dans une maison heureuse |
| 13 | Mickey Mouse in a Garden Party | Mickey dans une fête de jardin |
| 14 | Mickey Mouse in a Space Station | Mickey dans une station spatiale |
| 15 | Mickey Mouse on a Pirate Ship | Mickey sur un navire pirate |
| 16 | Mickey Mouse at a Fashion Show | Mickey à un défilé de mode |
| 17 | Mickey Mouse in a Galaxy Party | Mickey dans une fête galactique |
| 18 | Mickey Mouse in a Candy Shop | Mickey dans une boutique de bonbons |
| 19 | Mickey Mouse in a Basketball Game | Mickey dans un match de basket |
| 20 | Mickey Mouse in a Magic Show | Mickey dans un spectacle de magie |

## Étape 2 — contenu éditorial i18n complet pour les 5 premiers

Bornes SOFT pipeline :
- **EN / FR** : title [40, 60] · title_card ≤ 30 · description [80, 130]
- **AR** : title [25, 55] · title_card ≤ 25 · description [40, 100] · post-process strip harakat

### 1. Mickey Mouse in an Adventure Island (Mickey dans une île aventure)

_Concept description EN_ : Exciting Mickey Mouse coloring page set on a tropical adventure island with palm trees.

| Champ | EN | FR | AR |
|---|---|---|---|
| **title** | `Mickey Mouse Adventure Island Coloring Page` *(43c)* | `Mickey Mouse dans une île aventure` *(34c)* | `ميكي ماوس في مغامرة جزيرة رائعة` *(31c)* |
| **title_card** | `Mickey Adventure Island` *(23c)* | `Mickey sur une île` *(18c)* | `ميكي ماوس في مغامرة` *(19c)* |
| **description** | `Color this fun page featuring Mickey Mouse exploring a tropical island filled with palm trees, blue oceans, and exciting adventures for young children to enjoy.` *(160c)* | `Découvrez Mickey Mouse en pleine exploration sur une île magique. Coloriez cette aventure fantastique avec vos enfants pour des heures de plaisir créatif.` *(154c)* | `استمتع بلوحة تلوين مميزة لميكي ماوس في مغامرة جزيرة مليئة بالمرح والتحديات الممتعة للأطفال.` *(91c)* |
| **keywords** | `Mickey Mouse`, `Adventure Island`, `Coloring Page`, `Childrens Art`, `Tropical Fun` | `Mickey`, `île`, `aventure`, `coloriage`, `enfants` | `ميكي ماوس`, `مغامرة`, `جزيرة`, `تلوين`, `أطفال` |

### 2. Mickey Mouse at a Pizza Party (Mickey à une fête de pizza)

_Concept description EN_ : Fun Mickey Mouse coloring page featuring a delicious pizza party scene for kids.

| Champ | EN | FR | AR |
|---|---|---|---|
| **title** | `Mickey Mouse at a Pizza Party Coloring Page` *(43c)* | `Mickey Mouse à la Fête de Pizza` *(31c)* | `ميكي ماوس في حفلة البيتزا الملونة` *(33c)* |
| **title_card** | `Mickey Pizza Party` *(18c)* | `Mickey et la pizza` *(18c)* | `ميكي ماوس في حفلة البيتزا` *(25c)* |
| **description** | `Join Mickey Mouse for a fun pizza party where he shares a delicious slice with his friends. This colorful page invites children to bring the happy gathering to life with their own creative crayons and markers.` *(209c)* | `Colorie Mickey Mouse en train de partager une délicieuse fête de pizza avec ses amis dans cette page d'activité amusante.` *(121c)* | `تصفح هذا القالب الملون لتمييز ميكي ماوس في حفلة البيتزا الممتعة مع أصدقائه في نشاط ترفيهي رائع للأطفال.` *(103c)* |
| **keywords** | `Mickey Mouse`, `pizza party`, `coloring page`, `kids activity`, `fun drawing` | `Mickey`, `pizza`, `enfants`, `coloriage`, `fête` | `ميكي ماوس`, `حفلة البيتزا`, `تلوين`, `أطفال`, `تعليمي` |

### 3. Mickey Mouse on a School Bus (Mickey dans un bus scolaire)

_Concept description EN_ : Cute Mickey Mouse coloring page showing him riding a colorful school bus.

| Champ | EN | FR | AR |
|---|---|---|---|
| **title** | `Mickey Mouse Coloring Page on School Bus` *(40c)* | `Mickey Mouse dans un Bus Scolaire Coloriage` *(43c)* | `ميكي ماوس في الحافلة المدرسية ملون` *(34c)* |
| **title_card** | `Mickey School Bus` *(17c)* | `Mickey dans le bus` *(18c)* | `ميكي ماوس في الحافلة` *(20c)* |
| **description** | `Color this fun image of Mickey Mouse driving a yellow school bus with happy children ready for their day of learning and adventure.` *(131c)* | `Colorie Mickey Mouse assis dans un bus scolaire jaune. Une activité amusante pour les enfants qui aiment les personnages Disney.` *(128c)* | `تصفح هذا الرسم التوضيحي الجميل لميكي ماوس في الحافلة المدرسية واستمتع باللعب بالألوان في صفحة التلوين الخاصة بالطفل.` *(116c)* |
| **keywords** | `Mickey Mouse`, `School Bus`, `Children`, `Coloring Page`, `Cartoon` | `Mickey Mouse`, `bus scolaire`, `coloriage`, `enfants`, `Disney` | `ميكي ماوس`, `حافلة مدرسية`, `رسم توضيحي`, `صفحة تلوين`, `أطفال` |

### 4. Mickey Mouse in a Battle Ship (Mickey dans un navire de bataille)

_Concept description EN_ : Action-packed Mickey Mouse coloring page featuring a brave battle ship at sea.

| Champ | EN | FR | AR |
|---|---|---|---|
| **title** | `Mickey Mouse Battles in a Giant Ship` *(36c)* | `Mickey Mouse dans un Navire de Bataille` *(39c)* | `ميكي ماوس في سفينة الحروب الملونة` *(33c)* |
| **title_card** | `Mickey Battle Ship` *(18c)* | `Mickey dans un navire` *(21c)* | `ميكي في سفينة الحروب` *(20c)* |
| **description** | `Join Mickey Mouse as he commands his mighty battle ship. Color the brave hero and his crew ready for action in this fun adventure.` *(130c)* | `Colorie Mickey Mouse en action sur un grand navire de bataille avec ses amis et des ennemis à combattre.` *(104c)* | `تصفح هذا القالب الملون لتمييز ميكي ماوس وهو يقود سفينة الحروب في مغامرة ممتعة مليئة بالخيال.` *(92c)* |
| **keywords** | `Mickey Mouse`, `Battle Ship`, `Coloring Page`, `Adventure`, `Kids Activity` | `Mickey`, `navire`, `bataille`, `enfants`, `coloriage` | `ميكي ماوس`, `سفينة الحروب`, `تلوين`, `أطفال`, `مغامرات` |

### 5. Mickey Mouse in a Moon Base (Mickey dans une base lunaire)

_Concept description EN_ : Space-themed Mickey Mouse coloring page set inside a futuristic moon base.

| Champ | EN | FR | AR |
|---|---|---|---|
| **title** | `Mickey Mouse in a Moon Base Coloring Page` *(41c)* | `Mickey Mouse dans une base lunaire coloriage` *(44c)* | `ميكي ماوس في قاعدة القمر` *(24c)* |
| **title_card** | `Mickey on the Moon` *(18c)* | `Mickey en base lunaire` *(22c)* | `ميكي في قاعدة القمر` *(19c)* |
| **description** | `Color this fun page featuring Mickey Mouse exploring a bright moon base with his friends and a big rocket ship.` *(111c)* | `Colorie Mickey Mouse dans une base lunaire avec des astronautes et des étoiles brillantes pour un dessin amusant.` *(113c)* | `تصميم ملون لميكي ماوس داخل قاعدة القمر، جاهز للأطفال للتلوين والاستمتاع بالخيال العلمي.` *(87c)* |
| **keywords** | `Mickey Mouse`, `Moon Base`, `Space Adventure`, `Coloring Page`, `Kids Activity` | `Mickey`, `lune`, `espace`, `enfant`, `coloriage` | `ميكي ماوس`, `قاعدة القمر`, `تلوين`, `خيال علمي`, `أطفال` |

## Annexes

- Données brutes : `2026-05-05_poc-qualitative-mickey.json` (concepts + locales + harakat avant/après strip)
- Script : `scripts/poc_qualitative_mickey.py`
- Modèle : `qwen3.5:4b` (T=0.5 pour concepts, T=0 pour locales)
- Bornes : cf. `CLAUDE.md` section *Validation de contenu*