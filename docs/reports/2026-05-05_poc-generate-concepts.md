# POC-2 — `generate_concepts` sur la nouvelle taxonomie
Date : 2026-05-05

## Contexte
Test du prompt `generate_concepts` (modifié pour inclure `name_ar` + ancrage `theme_name_ar`) sur **15 feuilles variées** de la nouvelle taxonomie. Modèle : **qwen3.5:4b** (T=0.5). 5 concepts par feuille → 75 concepts au total. **Aucun jugement automatique de qualité linguistique** — la lisibilité est laissée à l'humain.

## Synthèse

| Métrique | Valeur |
|---|---|
| Feuilles ciblées / réelles | 15 / 15 |
| Appels JSON valides | 15 / 15 |
| Concepts générés | 75 |
| `name_en` Subject + Setting (≥3 mots + préposition) | 69/75 |
| `name_ar` présent | 75/75 |
| `name_ar` 1–4 mots | 49/75 |
| `name_ar` sans harakat | 74/75 |
| Latence moyenne / appel | 10.85 s |

## Concepts générés (lecture humaine)

### Animaux

#### Feuille `labrador_retriever` (parent: `pet_animals`)
- name_en : **Labrador Retriever**
- name_fr : **Labrador retriever**
- name_ar : **كلب اللابرادور** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Labrador Retriever Running in a Park` (✓, 6w) | `Labrador qui court dans un parc` | `لابرادور يركض في حديقة` (4w) |
| 2 | `Labrador Retriever Helping on a Farm` (✓, 6w) | `Labrador aidant sur une ferme` | `لابرادور يساعد في المزرعة` (4w) |
| 3 | `Labrador Retriever Playing in the Sea` (✓, 6w) | `Labrador jouant dans la mer` | `لابرادور يلعب في البحر` (4w) |
| 4 | `Labrador Retriever Resting in a Bed` (✓, 6w) | `Labrador reposant dans un lit` | `لابرادور يرتاح في السرير` (4w) |
| 5 | `Labrador Retriever Working in a Garden` (✓, 6w) | `Labrador travaillant dans un jardin` | `لابرادور يعمل في الحديقة` (4w) |

#### Feuille `dairy_cow` (parent: `farm_animals`)
- name_en : **Dairy Cow**
- name_fr : **Vache laitière**
- name_ar : **البقرة الحلوب** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Dairy Cow in a Milking Stall` (✓, 6w) | `Vache laitière dans un étalage` | `بقرة في حظيرة` (3w) |
| 2 | `Dairy Cow in a Green Field` (✓, 6w) | `Vache laitière dans un champ vert` | `بقرة في حقل` (3w) |
| 3 | `Dairy Cow with Baby Cow` (✓, 5w) | `Vache laitière avec sa veau` | `بقرة مع صغرتها` (3w) |
| 4 | `Dairy Cow in a Milk Shop` (✓, 6w) | `Vache laitière dans une boutique de lait` | `بقرة في متجر الحليب` (4w) |
| 5 | `Dairy Cow in a Hay Barn` (✓, 6w) | `Vache laitière dans une grange de foin` | `بقرة في حظيرة العشب` (4w) |

#### Feuille `lion_in_savanna` (parent: `african_wild_animals`)
- name_en : **Lion in the Savanna**
- name_fr : **Lion dans la savane**
- name_ar : **الأسد في السافانا** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Lion in the Savanna` (✓, 4w) | `Lion dans la savane` | `أسد في السافانا` (3w) |
| 2 | `Lion with Cubs in Savanna` (✓, 5w) | `Lion avec ses petits` | `أسد مع صغاره` (3w) |
| 3 | `Lion Hunting in Savanna` (✓, 4w) | `Lion chasseur` | `أسد صائد` (2w) |
| 4 | `Lion Sleeping in Grass` (✓, 4w) | `Lion qui dort` | `أسد نائم` (2w) |
| 5 | `Lion and Elephant in Savanna` (✓, 5w) | `Lion et éléphant` | `أسد وفيل` (2w) |

### Outils

#### Feuille `claw_hammer` (parent: `hand_tools`)
- name_en : **Claw Hammer**
- name_fr : **Marteau arrache-clou**
- name_ar : **المطرقة** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Claw Hammer in a Workshop` (✓, 5w) | `Marteau griffe dans un atelier` | `مطرقة في ورشة` (3w) |
| 2 | `Claw Hammer in a Garden` (✓, 5w) | `Marteau griffe dans un jardin` | `مطرقة في حديقة` (3w) |
| 3 | `Claw Hammer in a Forest` (✓, 5w) | `Marteau griffe dans une forêt` | `مطرقة في غابة` (3w) |
| 4 | `Claw Hammer in a Kitchen` (✓, 5w) | `Marteau griffe dans une cuisine` | `مطرقة في مطبخ` (3w) |
| 5 | `Claw Hammer in a Barn` (✓, 5w) | `Marteau griffe dans une étable` | `مطرقة في مزرعة` (3w) |

#### Feuille `garden_shovel` (parent: `gardening_tools`)
- name_en : **Garden Shovel**
- name_fr : **Pelle de jardin**
- name_ar : **مجرفة البستان** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Red Shovel in a Sunny Garden` (✓, 6w) | `Pelle rouge dans un jardin ensoleillé` | `مجرفة في البستان` (3w) |
| 2 | `Shovel Digging in Green Bushes` (✓, 5w) | `Pelle creusant dans des buissons verts` | `مجرفة في الشجيرات` (3w) |
| 3 | `Wooden Shovel Near a Wooden Fence` (✓, 6w) | `Pelle en bois près d'une clôture` | `مجرفة خشبية بجانب الحصار` (4w) |
| 4 | `Shovel Turning Dark Garden Soil` (✗, 5w) | `Pelle retournant la terre du jardin` | `مجرفة تترسب التربة` (3w) |
| 5 | `Shovel Playing in Sandy Beach` (✓, 5w) | `Pelle jouant sur la plage de sable` | `مجرفة في الرمال` (3w) |

### Professions

#### Feuille `doctor_with_stethoscope` (parent: `health_professions`)
- name_en : **Doctor with Stethoscope**
- name_fr : **Médecin avec stéthoscope**
- name_ar : **طبيب بسماعة** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Doctor with Stethoscope in Hospital Room` (✓, 6w) | `Médicant avec stéthoscope dans une chambre` | `طبيب بسماعة في غرفة المستشفى` (5w ⚠wc) |
| 2 | `Doctor with Stethoscope in School Clinic` (✓, 6w) | `Médecin avec stéthoscope dans une clinique scolaire` | `طبيب بسماعة في عيادة المدرسة` (5w ⚠wc) |
| 3 | `Doctor with Stethoscope on Couch with Patient` (✓, 7w) | `Médecin avec stéthoscope sur canapé avec patient` | `طبيب بسماعة على السرير مع مريض` (6w ⚠wc) |
| 4 | `Doctor with Stethoscope in Lab with Microscope` (✓, 7w) | `Médecin avec stéthoscope dans un laboratoire avec microscope` | `طبيب بسماعة في المختبر مع مجهر` (6w ⚠wc) |
| 5 | `Doctor with Stethoscope in Emergency Room` (✓, 6w) | `Médecin avec stéthoscope dans une salle d'urgence` | `طبيب بسماعة في غرفة الطوارئ` (5w ⚠wc) |

#### Feuille `firefighter_with_hose` (parent: `security_and_emergency`)
- name_en : **Firefighter with Hose**
- name_fr : **Pompier avec lance à eau**
- name_ar : **إطفائي بخرطوم** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Firefighter with Hose at Fire Station` (✓, 6w) | `Infirmier de pompier avec un tuyau` | `إطفائي بخرطوم` (2w) |
| 2 | `Firefighter with Hose Fighting Fire` (✓, 5w) | `Infirmier de pompier combattant un incendie` | `إطفائي بخرطوم يطفئ الحريق` (4w) |
| 3 | `Firefighter with Hose at a House` (✓, 6w) | `Infirmier de pompier devant une maison` | `إطفائي بخرطوم في منزل` (4w) |
| 4 | `Firefighter with Hose on a Bicycle` (✓, 6w) | `Infirmier de pompier sur un vélo` | `إطفائي بخرطوم على دراجة` (4w) |
| 5 | `Firefighter with Hose near a Tree` (✓, 6w) | `Infirmier de pompier près d'un arbre` | `إطفائي بخرطوم بجانب شجرة` (4w) |

### Sports

#### Feuille `football_match_scene` (parent: `team_sports`)
- name_en : **Football Match Scene**
- name_fr : **Match de football**
- name_ar : **مباراة كرة القدم** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Team in a Football Stadium` (✓, 5w) | `Équipe dans un stade` | `فريق في استاد كرة قدم` (5w ⚠wc) |
| 2 | `Goalkeeper in a Football Net` (✓, 5w) | `Gardien dans un filet` | `حارس في شبكة` (3w) |
| 3 | `Referee on a Green Field` (✓, 5w) | `Arbitre sur un terrain` | `حكم على الملعب` (3w) |
| 4 | `Soccer Ball on Grass` (✓, 4w) | `Balle de soccer sur l'herbe` | `كرة قدم على العشب` (4w) |
| 5 | `Fans in Stadium Seats` (✓, 4w) | `Supports dans les sièges` | `مشجع في مقاعد الاستاد` (4w) |

#### Feuille `tennis_player_serving` (parent: `individual_sports`)
- name_en : **Tennis Player Serving**
- name_fr : **Joueur de tennis au service**
- name_ar : **لاعب التنس** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Tennis Player Serving on the Court` (✓, 6w) | `Joueur de tennis qui sert sur le court` | `لاعب التنس على الملعب` (4w) |
| 2 | `Tennis Player Holding Racket in Stadium` (✓, 6w) | `Joueur de tenant une raquette dans un stade` | `لاعب التنس مع المضرب في الملعب` (6w ⚠wc) |
| 3 | `Tennis Player Winning Match on Green Court` (✓, 7w) | `Joueur de tennis gagnant un match sur le court vert` | `لاعب التنس يفوز بالمباراة على الملعب الأخضر` (7w ⚠wc) |
| 4 | `Tennis Player Running to Ball on Clay` (✓, 7w) | `Joueur de tennis courant vers la balle sur terre battue` | `لاعب التنس يركض نحو الكرة على الأرض الطينية` (8w ⚠wc) |
| 5 | `Tennis Player Serving Outside in Park` (✓, 6w) | `Joueur de tennis servant dehors dans le parc` | `لاعب التنس يخدم خارجاً في الحديقة` (6w ⚠harakat ⚠wc) |

### Personnages fictifs

#### Feuille `elsa_from_frozen` (parent: `disney_universe`)
- name_en : **Elsa from Frozen**
- name_fr : **Elsa de La Reine des Neiges**
- name_ar : **إلسا من فروزن** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Elsa Building a Snow Castle` (✗, 5w) | `Élsa construit un château de neige` | `إلسا تبني قلعة ثلج` (4w) |
| 2 | `Elsa Skating on Frozen Lake` (✓, 5w) | `Élsa patine sur un lac gelé` | `إلسا تسبح على بحيرة مجمدة` (5w ⚠wc) |
| 3 | `Elsa Creating a Magic Snowflake` (✗, 5w) | `Élsa crée un flocon de neige magique` | `إلسا تصنع خيط ثلج سحري` (5w ⚠wc) |
| 4 | `Elsa Playing with Snow Animals` (✓, 5w) | `Élsa joue avec des animaux de neige` | `إلسا تلعب مع حيوانات الثلج` (5w ⚠wc) |
| 5 | `Elsa Wearing Ice Skirt` (✗, 4w) | `Élsa porte une jupe de glace` | `إلسا ترتدي فستان ثلج` (4w) |

#### Feuille `spiderman_swinging` (parent: `marvel_universe`)
- name_en : **Spider-Man Swinging**
- name_fr : **Spider-Man en plein vol**
- name_ar : **الرجل العنكبوت** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Spider-Man Swinging in New York City` (✓, 6w) | `Spider-Man balançant dans la ville` | `الرجل العنكبوت يهبط في مدينة نيويورك` (6w ⚠wc) |
| 2 | `Spider-Man Swinging in the Park` (✓, 5w) | `Spider-Man balançant dans le parc` | `الرجل العنكبوت يهبط في الحديقة` (5w ⚠wc) |
| 3 | `Spider-Man Swinging Under the Moon` (✓, 5w) | `Spider-Man balançant sous la lune` | `الرجل العنكبوت يهبط تحت القمر` (5w ⚠wc) |
| 4 | `Spider-Man Swinging Near School` (✓, 4w) | `Spider-Man balançant près de l'école` | `الرجل العنكبوت يهبط بالقرب من المدرسة` (6w ⚠wc) |
| 5 | `Spider-Man Swinging Over the Bridge` (✓, 5w) | `Spider-Man balançant au-dessus du pont` | `الرجل العنكبوت يهبط فوق الجسر` (5w ⚠wc) |

### Géométrie / Alphabet

#### Feuille `circle_shape` (parent: `basic_shapes`)
- name_en : **Circle Shape**
- name_fr : **Cercle**
- name_ar : **الدائرة** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Circles in a Winter Snowflake` (✓, 5w) | `Cercles dans une flocon` | `دوائر في زهرة ثلج` (4w) |
| 2 | `Circles on a Sandy Beach` (✓, 5w) | `Cercles sur une plage` | `دوائر على شاطئ رمال` (4w) |
| 3 | `Circles in a Green Tree` (✓, 5w) | `Cercles dans un arbre vert` | `دوائر في شجرة خضراء` (4w) |
| 4 | `Circles in a Pizza Slice` (✓, 5w) | `Cercles dans une tranche de pizza` | `دوائر في شريحة بيتزا` (4w) |
| 5 | `Circles in a Flower Garden` (✓, 5w) | `Cercles dans un jardin de fleurs` | `دوائر في حديقة زهور` (4w) |

#### Feuille `letter_a_with_apple` (parent: `english_alphabet_illustrated`)
- name_en : **Letter A with Apple**
- name_fr : **Lettre A avec une pomme**
- name_ar : **حرف A مع تفاحة** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Red Apple Tree in a Sunny Garden` (✓, 7w) | `Arbre de pommes rouge dans un jardin` | `شجرة التفاح الحمراء في الحديقة` (5w ⚠wc) |
| 2 | `Fresh Red Apple on a Wooden Table` (✓, 7w) | `Pomme rouge fraîche sur une table` | `تفاحة حمراء طازجة على طاولة خشبية` (6w ⚠wc) |
| 3 | `Ripe Apples in a Woven Basket` (✓, 6w) | `Pommes mûres dans un panier tressé` | `تفاحات ناضجة في سلة م织ية` (5w ⚠wc) |
| 4 | `Child Holding a Red Apple` (✗, 5w) | `Enfant tenant une pomme rouge` | `طفل يحمل تفاحة حمراء` (4w) |
| 5 | `Canned Apples in a Glass Jar` (✓, 6w) | `Pommes en conserve dans un bocal` | `تفاح معلبة في زجاجة زجاجية` (5w ⚠wc) |

### Corps humain

#### Feuille `child_face_features` (parent: `external_anatomy`)
- name_en : **Child Face Features**
- name_fr : **Traits du visage d'enfant**
- name_ar : **ملامح وجه الطفل** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Child Face in a Mirror` (✓, 5w) | `Visage d'enfant dans un miroir` | `وجه طفل في مرآة` (4w) |
| 2 | `Baby Face on a Park Bench` (✓, 6w) | `Visage de bébé sur un banc` | `وجه طفل على مقعد` (4w) |
| 3 | `Toddler Face in a Stroller` (✓, 5w) | `Visage de tout-petit dans un poussette` | `وجه طفل في عربة` (4w) |
| 4 | `Child Face at a Birthday Party` (✓, 6w) | `Visage d'enfant à une fête d'anniversaire` | `وجه طفل في حفلة عيد ميلاد` (6w ⚠wc) |
| 5 | `Kiddo Face in a Bed` (✓, 5w) | `Visage d'enfant dans un lit` | `وجه طفل في سرير` (4w) |

#### Feuille `heart_with_blood_circulation` (parent: `internal_organs_educational`)
- name_en : **Heart with Blood Circulation**
- name_fr : **Cœur avec circulation sanguine**
- name_ar : **القلب مع الدورة الدموية** (ancre)

| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |
|---|---|---|---|
| 1 | `Red Heart Beating in Human Chest` (✓, 6w) | `Cœur rouge battant dans la poitrine` | `قلب ينبض في الصدر` (4w) |
| 2 | `Blue Blood Flow in Red Veins` (✓, 6w) | `Sang bleu en veines rouges` | `دم أزرق في وعاء أحمر` (5w ⚠wc) |
| 3 | `Muscle Pump in Heart Chamber` (✓, 5w) | `Pompe musculaire dans la chambre du cœur` | `ضخامة عضلية في غرفة القلب` (5w ⚠wc) |
| 4 | `Red Arteries Branching Out` (✗, 4w) | `Artères rouges qui se branchent` | `عروق حمراء تتفرع` (3w) |
| 5 | `Tiny Capillaries Near Skin` (✓, 4w) | `Capillaires près de la peau` | `أوعية دقيقة بالقرب من الجلد` (5w ⚠wc) |

## Points d'attention

- Métrique « Subject + Setting » heuristique : présence d'une préposition (`in/on/at/under/with/...`) et ≥ 3 mots dans `name_en`. Cela peut produire des faux positifs (préposition non-locative) mais détecte la majorité des titres concrets.
- Le caractère « 5 concepts par feuille » dépend du modèle : si le modèle renvoie moins (4) ou plus (6+), pas d'erreur.
- L'**ancre AR** (`theme_name_ar` passée dans le prompt) est censée orienter le LLM vers le bon mot racine arabe pour le sujet. Évaluer humainement si les `name_ar` retournés réutilisent cet ancrage ou divergent.
- **Aucun jugement automatique de cohérence cross-locale** dans ce rapport ; la table ci-dessus permet la revue côte à côte FR/EN/AR.
- **Bug regex harakat** (déjà rencontré sur ce projet — RTL trap au copier-coller) : la regex inline `[ؐ-ًؚ-ٟ]` peut être réécrite par le rendu RTL et inclure toutes les lettres arabes. Corrigé ici via codepoints explicites `[\u0610-\u061A\u064B-\u065F]`. Le metric `name_ar sans harakat` est désormais correct.

## Annexes

- Données brutes : `2026-05-05_poc-generate-concepts.json`
- Script : `scripts/poc_generate_concepts.py`
- Template modifié : `prompts/image_prompts.yaml::generate_concepts` (ajout `name_ar` + placeholder `theme_name_ar`)
- Caller modifié : `src/services/ai_jobs_sync.py` (extraction `theme_name_ar` depuis le term)