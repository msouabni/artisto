# Analyse — Annotations poc-scale-benchmark vs skill prompt-taxonomy-ecosystem

Date : 2026-05-10
Type : Analyse / arbitrage (gap inventory)
Posture : Inventaire de gap, **pas d'évaluation qualité du PromptGenerator**. Le skill est en avance sur le code ; les défauts observés sont attendus.

## Contexte

`docs/reports/poc-scale-benchmark/annotations.json` (schema v2, 515 entrées scorées) couvre des images générées par `src/services/prompt_generator.py` (730 LOC, NEGATIVE_V3 + `_ISOLATION` + `LEAF_OVERRIDES` + `_RISKY_MULTI_PATTERNS` + ~60 entrées `TEMPLATE_DISPATCHER`). Le skill `prompt-taxonomy-ecosystem.skill` (dézippé en `%TEMP%\skill_extract\`) capitalise 32 techniques (T1–T32) issues du canal manuel. L'objet de cette analyse est de cartographier ce qui est transférable et ce qui doit passer par capitalisation T19+.

Mappage filename → metadata via les 38 `index-*.json` + heuristique `_bN_` strip (515/515 records mappés à un `workflow_class`).

## 1. Inventaire défauts

Vocabulaire libre extrait des `image_tags` + `prompt_tags` + `custom_tags` (schema v2). Le mapping v1→v2 (cf. `scripts/migrate_benchmark_annotations.py`) est rappelé entre parenthèses pour rapprocher du vocabulaire skill (v1 canonique).

| défaut (v2) | n_obs | % corpus | leaf_ids dominants (extraits) | workflow_classes dominantes |
|---|---:|---:|---|---|
| `image_pas_coherente` | 66 | 12.8% | dispersé (1 occ par leaf) | Imagier annoté 3×3 OU Solo visage (9), Grille imagier annoté (8), Comparatif before/after OU Solo (8), Imagier différencié OU Solo (6), Solo objet ou comparatif (6) |
| `image_incomprehensible` | 64 | 12.4% | dispersé | Grille imagier annoté (8), Comparatif before/after OU Solo (8), Imagier annoté 3×3 OU Solo visage (8), Imagier différencié OU Solo (6), Solo objet ou comparatif (6) |
| `image_duplication` (≈ v1 `2_objets`) | 28 | 5.4% | bactrian_camel (2), golden_retriever (2), mountain_gorilla (2), running_cheetah (2), running_giraffe (2), playful_dolphin (2), eid_al_adha_sheep, sheep_with_lamb, animal_superhero, house_painter_with_roller, three_little_pigs, gaming_setup_with_keyboard, laptop_open_with_code, child_with_test_tubes, optometrist_eye_test, horse_racing, grasshopper, letter_z_with_zebre… | Solo animal (15), Solo fish (2), Solo objet ou Humain + entité (2), Humain + entité (instrument) (1), Humain + entité (cheval) (1), Scène ou solo personnage (1), Solo humain (générique) (1), Solo humain + accessoires (1), Solo insect (1), Variable (1), Lettre + objet (1) |
| `image_anatomie_pb` (≈ v1 `3_jambes`) | 23 | 4.5% | tango_couple (2), captain_marvel, rapunzel_with_long_hair, beluga_whale, lamine_yamal_cartoon, husky_dog, rafael_nadal_cartoon, snowboarder_jump, maine_coon_cat, pegasus, running_cheetah, child_with_test_tubes, doctor_with_stethoscope, dressage_horse, esthetician_at_work, five_senses_summary_poster, flying_carpet_over_city, hand_with_fingers_named, horse_racing, kawaii_cat_with_big_eyes, spring_chicks_with_mother, three_little_pigs | Solo animal (5), Solo humain en action (3), Solo humain (personnalité) (2), Solo humain (personnalité) + action figée (2), Humain + entité (cheval) (2), Humain + entité OU Solo humain pose statique (1), Solo objet (organe sensoriel) (1), Solo objet anatomique + labels (1), Solo objet ou scène (1), Solo objet style kawaii (1), Scène ou solo personnage (1), Humain + entité OU Solo (1) |
| `image_compo_bonne` (positif) | 15 | 2.9% | dispersé | mixte |
| `image_simpliste` | 14 | 2.7% | latkes_potato_pancakes, christmas_stocking_fireplace, foot_with_toes, hot_air_balloon, kawaii_cloud_with_face, living_room_with_sofa, sense_of_hearing_ear, smart_speaker_assistant, space_rocket, sunny_day_with_sun, thunderstorm_with_lightning, valentines_day_heart_card, wavy_lines_abstract, wrapped_birthday_presents | Solo objet météo (2), Solo objet en vol OU au sol (2), Pattern décoratif simple (1), Solo objet anatomique + labels (1), Solo objet (organe sensoriel) (1), Solo objet style kawaii (1), Variable selon sujet (1), Solo objet ou personnage robot (1), Variable (solo objet ou frise pour party) (1), Solo objet (1), Scène intérieure (1), Solo objet ou humain+entité (1) |
| `image_prompt_non_respecte` (≈ v1 `prompt_incohérent`) | 9 | 1.7% | bungee_jumper (2), captain_marvel, animal_superhero, fishmonger_at_market, rapunzel_with_long_hair, firefighter_with_hose, grasshopper, balanced_lunch_plate | Solo humain (personnalité) (2), Solo humain en action (2), Solo humain (générique) (1), Solo humain + accessoires (1), Solo humain pose active (1), Solo insect (1), Imagier différencié OU Solo (1) |
| `prompt_complexe` | 8 | 1.6% | concentré sur Solo humain en action (5/8) | Solo humain en action (5) |
| `image_creative` (positif) | 7 | 1.4% | — | mixte |
| `bizarre` (custom) | 7 | 1.4% | magic_potion_cauldron, mardi_gras_beads_necklace, nativity_scene, polo_player, sense_of_sight_eye, valentines_day_cupid_arrow, venetian_carnival_mask | Solo humain OU objet (2), Variable selon sujet (1), Humain + entité (cheval) (1), Solo objet (organe sensoriel) (1), Solo humain ou objet (1), Solo objet ou humain+entité (1) |
| `comptage` (custom) | 7 | 1.4% | number_*_with_* (7 occ uniques) | Multi-sujets via grille (méta-pattern §2) (7/10) |
| `image_coherente` (positif) | 6 | 1.2% | — | — |
| `image_flou` (≈ v1 `traits_flous`) | 5 | 1.0% | dairy_cow, lion_in_savanna, snowy_owl, warthog, foggy_morning_landscape | Solo animal (4), Solo objet météo (1) |
| `image_physique_pb` (≈ v1 `perspective_KO`) | 4 | 0.8% | animal_superhero, gaming_setup_with_keyboard, hallway_with_coat_rack, kid_using_microscope | Solo humain (générique), Solo objet ou Humain + entité, Scène intérieure, Humain + entité (instrument) |
| `prompt_complexe` / `prompt_ambigu` / `prompt_approximatif` / `prompt_creatif` / `prompt_interessant` | 19 cumul | — | — | mixte |
| `incomplet` (custom) | 2 | — | — | — |
| `image_gris_residuel` (≈ v1 `gris_résiduel`) | 1 | 0.2% | jaguar_in_jungle | Solo animal |
| Autres custom singletons | 14 | — | — | — |

**Co-occurrence forte** : `image_pas_coherente` ∩ `image_incomprehensible` = 62 entrées (91 % des cas, l'un appelle l'autre) et se concentrent à 91 %–100 % sur 6 workflow_classes (Imagier annoté 3×3 OU Solo visage 90 %, Grille imagier annoté 100 %, Comparatif before/after OU Solo 80 %, Imagier différencié OU Solo 100 %, Solo objet ou comparatif 75 %, Frise narrative 1×N 62 %, Imagier différencié 3×3 50 %).

**Distribution des scores** (v2 1–6) : score=1 → 165, score=2 → 26, score=3 → 27, score=4 → 38, score=5 → 63, score=6 → 196 (factuel, sans verdict).
**Publishable** : True 336 / False 122 / None 57.

## 2. Triage en 3 catégories

Vocabulaire skill (v1 canonique) ↔ vocabulaire annotation (v2) selon `scripts/migrate_benchmark_annotations.py`.

### 🟢 Couvert ET partiellement transféré (vérifier l'application)

| défaut | règle skill | présence dans `prompt_generator.py` | gap résiduel |
|---|---|---|---|
| `image_duplication` (`2_objets`) sur `Solo animal` / `Solo fish` / `Solo insect` / `Solo bird` / `Solo reptile` | NEGATIVE_V3 + `_ISOLATION` ; `_RISKY_MULTI_PATTERNS` ; `LEAF_OVERRIDES` (sheep_with_lamb, eid_al_adha_sheep) ; T9 (profil + orientation directionnelle) | NEGATIVE_V3 ✅, `_ISOLATION` ajouté dans templates `solo_animal/insect/fish/bird/reptile` ✅, `_RISKY_MULTI_PATTERNS` ✅, `LEAF_OVERRIDES` (2 entrées) ✅. `apply_no_think_system` non-applicable ici. | T9 (profil + orientation) **pas appliqué** par défaut sur `Solo animal` — les leafs `bactrian_camel`, `golden_retriever`, `mountain_gorilla`, `playful_dolphin`, `running_cheetah`, `running_giraffe` re-dupliquent en v2 (cf. critère A §5) malgré l'isolation. Skill T9 demande `in profile facing left/right` + orientation directionnelle pour les éléments qui s'étendent derrière le sujet (queue, manche, cape). Pas de paramètre `direction` dans le template. |
| `image_anatomie_pb` (`3_jambes`) | NEGATIVE_V3 (`extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, wrong number of limbs, six fingers, deformed feet`) ; cfg=1.0 fixé (CLAUDE.md) ; T22 (description granulaire tenues spécialisées) ; T27 (pose canonique vs forcée) ; T30 (groupe → positionnement explicite) | NEGATIVE_V3 ✅ ; cfg=1.0 figé en config (workflow KSampler widget_values) ✅. T22/T27/T30 → **non transférés** (`template_solo_human`, `template_personality_action`, `template_human_plus_entity` sont génériques, pas de `LEAF_OVERRIDES` pour les personnalités/groupes) | Personnalités sportives (`lamine_yamal_cartoon`, `rafael_nadal_cartoon`, `captain_marvel`, `rapunzel_with_long_hair`) → tenue / accessoire générique. Groupe narratif (`three_little_pigs`) → solo template. Pose forcée (`tango_couple` ×2 sur Solo humain en action, `snowboarder_jump`, `bungee_jumper` ×2) → `mid-action` + `dynamic pose with motion lines` (cf. T27, source identifiée). |
| `image_simpliste` sur `Solo objet météo` | T31 (phénomènes météo scéniques → template paysage 1376×768) ; T26 (vue trois-quarts pas horizon line) ; bug v8 (scènes atmosphériques traitées comme solo_object) | `Solo objet météo` est mappé sur `template_solo_object` dans `TEMPLATE_DISPATCHER` (ligne 532). Pas de basculement scénique. | Le skill connaît bug v8 (T31) et a un fix template ; pas dans le code. |
| `image_pas_coherente` + `image_incomprehensible` sur `Imagier différencié 3×3` / `Imagier annoté 3×3 OU Solo visage` / `Grille imagier annoté` / `Imagier différencié OU Solo` | T2 (contenu explicite par cellule, jamais `one item related to X`) ; T3 (cellules composées avec conteneur sémantique) | `template_grid_3x3_imagier` (l. 388–402) écrit littéralement `each cell contains one different item related to {name}` — **pile l'antipattern documenté en T2** (`# ❌ contenu délégué …each cell contains one different item related to balanced lunch plate…`). `template_grid_3x3_annotated` similaire. | T2 disponible mais inversement appliqué (ce qui explique le 100 % `image_incomprehensible` sur Grille imagier annoté). Skill propose un dict `leaf_id → [(item, shape), …]` prédéfini — **pas de structure data dans le code**. |
| `image_pas_coherente` + `image_incomprehensible` sur `Frise narrative 1×N (pattern X2)` | T4 (rappel synthétique en fin de prompt + énumération des stages) ; bug v3 (frises temporelles sans banque de connaissances stages) | `template_frieze_1xN` (l. 419–430) écrit `each cell shows one stage or moment of {name}` + `the rightmost cell shows the final stage with detailed elements` — pas d'énumération stage par stage, pas de rappel synthétique global type `[N] cells total showing [item1] then [item2]…`. | Banque de connaissances stages par leaf manquante (life cycle, baby stages, saisons). |
| `image_pas_coherente` + `image_incomprehensible` sur `Comparatif before/after OU Solo` / `Solo objet ou comparatif` (16/18 = 89 %) | T25 (jeu des différences — `one single change applied` = trop vague) ; bug v5 (template before/after sans explicitation des états) | `template_before_after` (l. 433–446) écrit `the right cell shows the same scene with one single change applied` — antipattern T25 (`# ❌ trop vague — modèle reproduit la même scène`). | Ni `before_state` ni `after_state` dans la cartographie ni dans le template ; pas de description narrative des deux états. |
| `comptage` sur `Multi-sujets via grille (méta-pattern §2)` (7/10 = 70 %) | T15 (positionnement gauche/droite + total no more no less) ; T16 (pattern carte à jouer) ; T17 (pattern dé isométrique) ; T18 (caisse à étages) ; T19 (façade immeuble) ; T20 (corde à linge) ; T21 (étal de marché) | `template_grid_3x3_imagier` re-mappé sur Multi-sujets via grille (`TEMPLATE_DISPATCHER` l. 546). T15–T21 → **aucun** template dans le code. Pas de support « carte à jouer », « dé », « caisse », « façade », « corde », « étal ». | Skill couvre 7 supports de comptage validés ; code n'en a aucun. |

### 🟡 Couvert par skill, NON transféré (opportunité de transfert)

| défaut observé | règle skill | gap concret dans `prompt_generator.py` |
|---|---|---|
| `image_duplication` sur leafs `running_*`, `bactrian_camel`, `golden_retriever`, `mountain_gorilla`, `playful_dolphin` (résiduels après v2) | T9 — éléments derrière le sujet (queue, manche, cape, lance) → profil strict + orientation directionnelle | `template_solo_animal` n'a pas de variante directionnelle (`facing left/right`). `_ISOLATION` ne suffit pas pour les morphologies à queue ample / cou long / patte arrière. |
| `image_duplication` sur `Solo humain (générique)`, `Solo humain + accessoires`, `Humain + entité (cheval)`, `Humain + entité (instrument)`, `Humain + entité OU Solo humain pose statique`, `Scène ou solo personnage`, `Solo objet ou Humain + entité` | T9 + Règle générale « moins de mise en scène = plus de fiabilité » + T27 (pose canonique) | Aucun de ces templates n'inclut `_ISOLATION` (vérifié : `template_solo_human`, `template_solo_object`, `template_human_plus_entity`, `template_personality_action`, `template_pose_static`, `template_grid_*`, `template_frieze_*`, `template_before_after`, `template_landscape_2plane`, `template_multiplane_stacked`). Seuls `template_solo_animal/insect/fish/bird/reptile` l'ont. NEGATIVE_V3 contient des termes anti-multi-animaux (`multiple animals, other animals, companion animal, group of animals, animal in background, second subject, multiple subjects`) **mais pas anti-multi-humains/objets** explicites. |
| `image_anatomie_pb` sur tenues spécialisées (`bungee_jumper`, `tango_couple`, `dressage_horse`, `polo_player`) | T22 — description granulaire pièce par pièce pour tenues rares | `template_solo_human` insère le `name_en` brut. Pas de mapping `leaf_id → tenue détaillée`. Skill fournit déjà `polo_player`, `chirurgien`, `Schéhérazade`, `Sinbad le marin` validés — table T27. |
| `image_anatomie_pb` sur personnalités (`captain_marvel`, `rapunzel_with_long_hair`, `lamine_yamal_cartoon`, `rafael_nadal_cartoon`) + `prompt_complexe` ×5 sur `Solo humain en action` | T27 — pose canonique vs forcée (`mid-action`, `dynamic pose with motion lines` génère crispation) | `template_personality_action` (l. 374–385) écrit explicitement `in mid-action … dynamic pose with motion lines suggesting movement` — antipattern T27 documenté. Skill propose table `personnage → pose canonique` (Schéhérazade, Sinbad, polo player, chef, pêcheur, danseur, chirurgien). |
| `image_anatomie_pb` sur `three_little_pigs` (groupe narratif → solo template) | T30 — groupe de personnages (positionnement explicite par personnage) | Pas de détection « nombre dans le nom » (`three_*`, `seven_*`, `twelve_*`). Bug générateur v9 documenté dans skill. |
| `image_anatomie_pb` + `bizarre` + `image_simpliste` sur `Solo objet (organe sensoriel)` (`sense_of_hearing_ear`, `sense_of_sight_eye`, `five_senses_summary_poster`, `hand_with_fingers_named`, `foot_with_toes`) — score moyen=1.0, 0/6 publishable | T28 — pattern five_senses + Z1 (max 3 labels) + bug v4 (name_en brut non projetable) | `Solo objet (organe sensoriel)` mappé sur `template_solo_object` (l. 525). Pas de mapping `sense_of_*` → prompt anatomique précis. Skill fournit 5 prompts validés clé-en-main. |
| `image_simpliste` + `image_pas_coherente` sur `Solo objet météo` (`sunny_day_with_sun`, `thunderstorm_with_lightning`, `foggy_morning_landscape`) — score 2.62, 62 % pub | T31 + bug v8 — météo scénique = paysage 1376×768, pas solo_object | `Solo objet météo` mappé sur `template_solo_object` (l. 532). |
| `image_pas_coherente` + `image_incomprehensible` sur grilles imagier (Grille imagier annoté 100 %, Imagier différencié OU Solo 100 %, Imagier annoté 3×3 OU Solo visage 90 %, Imagier différencié 3×3 50 %) | T2 — contenu explicite par cellule + bug 1 (dispatch grille vs solo trop grossier, T23) | `template_grid_3x3_imagier` et `template_grid_3x3_annotated` délèguent au modèle (`one different item related to {name}`). Aucune banque `leaf_id → [(cell_label, geometric_shape), …]`. Aucune heuristique « si feuille singulière (proud_child_face) → solo_expressive_face plutôt que grille » (cf. T23). |
| `image_pas_coherente` + `image_incomprehensible` sur Frise narrative 1×N | T4 — rappel synthétique systématique + bug 3 — banque de connaissances stages | `template_frieze_1xN` paramètre `n=4` figé, énumération absente. |
| `image_pas_coherente` + `image_incomprehensible` sur Comparatif before/after (89 %) | T25 — différence concrète, visuelle, localisée + bug v5 — `before_state` / `after_state` explicites | `template_before_after` ne lit aucun champ from `strategy` ou `leaf` pour ces deux états. |
| `comptage` sur Multi-sujets via grille (7 occ sur 10) | T15 + T16 + T17 + T18 + T19 + T20 + T21 — banque de supports de comptage | Aucun template `playing_card_layout`, `dice_face_isometric`, `crate_shelves`, `building_facade`, `clothesline`, `market_stall` n'existe dans le code. La règle générale « counting is more important than proportions, make each item as small as needed to fit » n'est nulle part. |
| `image_pas_coherente` + `image_pas_coherente` sur `Solo objet anatomique + labels` (`hand_with_fingers_named`, `five_senses_summary_poster`, `foot_with_toes`) — score 1.86 | T28 + Limite Z1 (max 3 labels) | Pas de gestion limites labels ; pas de bascule grille 3×3 si N labels ≥ 4. |
| Aucune ancre couleur conceptuelle (`rainbow`, `sunset`, `autumn`, `tropical`) ni couleur explicite (T5) ni surface 3D (T7 `shiny`, `glossy`, `metallic`, `chrome`, `glass`, `wet`, `chocolate`) n'est filtrée | T5 + T6 + Extension T6 + T7 — strip noms de couleur, ancres conceptuelles, termes surface réfléchissante avant injection | Aucun filtre `strip_color_nouns` / `strip_glossy_terms` / `replace_color_anchors` n'existe en pre-processing du `name_en` ou de la description. Ni dans le template, ni en post. Le skill mentionne ce fix comme validé ; il n'est pas déployé. (Volume observé bas dans annotations — `image_gris_residuel`=1, pas de tag couleur résiduelle dédié dans schéma v2 — mais c'est aussi parce que le QC histogram Pillow est en amont et que le schéma v2 ne porte pas la dimension couleur résiduelle hors `image_gris_residuel`.) |
| `image_simpliste` sur mandalas / motifs décoratifs (`wavy_lines_abstract`) | T29 — template `decorative_surface` + bug v7 (`spirals_and_swirls` etc. mappé sur solo_object) | `Pattern décoratif simple` mappé sur `template_solo_object` (l. 578). Pas de template `decorative_surface`. |
| Catégorie `daily_life_and_environments`, `nature_and_environment` (`living_room_with_sofa`, `gaming_setup_with_keyboard`, `hallway_with_coat_rack`, `kid_using_microscope`) — `image_simpliste` + `image_physique_pb` | T26 — vue trois-quarts pour scènes avec profondeur, pas `divided by horizon line` | `template_landscape_2plane` (l. 462–472) écrit `divided by a horizon line across the middle of the page` — antipattern T26. `template_solo_object` utilisé pour scènes intérieures (Scène intérieure → `template_solo_object`, l. 558). |
| `bizarre` + `image_anatomie_pb` sur sujets religieux/mythologiques (`nativity_scene`, `valentines_day_cupid_arrow`, `magic_potion_cauldron`, `flying_carpet_over_city`) | Extension blacklist religieuse + Principe éditorial « ne pas générer à tout prix » | Aucune blacklist en code. Pas de champ `status: excluded` lu dans la cartographie. |

### 🔴 Non couvert par skill (candidats T19+)

Tags émergents schéma v2 sans correspondance directe dans techniques.md :

| défaut observé | n_obs | caractéristiques | piste prototype |
|---|---:|---|---|
| `image_pas_coherente` + `image_incomprehensible` (cumul 130 occurrences) | 130 | Tag schéma v2 introduit mais sans mapping dans le skill v1. Ces deux tags couvrent un spectre **plus large** que `prompt_incohérent` v1 ; ils incluent des cas où la composition globale (méta-pattern) est ratée même si chaque cellule isolée serait OK. | Voir T19+ #1 et #2 ci-dessous (Méta-pattern grille + Comparatif before/after). |
| `image_simpliste` (14 occurrences) | 14 | Tag schéma v2 hors mapping skill v1. Indique un défaut de richesse — sujet présent mais sous-développé. Concentré sur `Solo objet météo`, `Solo objet en vol OU au sol`, `Pattern décoratif simple`, `Solo objet (organe sensoriel)`, `Solo objet anatomique + labels`. | Voir T19+ #3 ci-dessous. |
| `comptage` (custom, 7 occ) sur les `number_*_with_*` | 7 | Concept de feuille = comptage (`number_one_with_apple`, `number_three_with_birds`…) mais template grille 3×3 sans support comptage. Skill T15–T21 couvrent les supports de comptage **mais aucun n'est lié à des feuilles `number_N_with_X`** (le pattern « chiffre + N items » n'est pas indexé dans le skill). | Voir T19+ #4 ci-dessous. |
| `bizarre` (custom, 7 occ) | 7 | Sujets religieux/mythologiques + costumes culturels rares (`nativity_scene`, `mardi_gras_beads_necklace`, `venetian_carnival_mask`, `valentines_day_cupid_arrow`, `polo_player`, `sense_of_sight_eye`, `magic_potion_cauldron`). Catégorie hétérogène — mélange « représentation problématique » (skill = blacklist religieuse) ET « rendu morphologiquement bizarre » (organe seul). | Le sous-cas religieux relève de T1313 (extension blacklist religieuse — déjà skill). Le reste : pas couvert. |
| `prompt_complexe` (8 occ) concentré sur `Solo humain en action` (5/8) | 8 | Tag schéma v2. Hypothèse plausible : prompt action humaine = trop dense (cf. règle générale skill « moins de mise en scène = plus de fiabilité ») mais pas de quantification skill « si len(action_clauses) > N → simplifier ». | Voir T19+ #5 ci-dessous. |
| `prompt_ambigu`, `prompt_approximatif`, `prompt_creatif`, `prompt_interessant` (cumul 11) | 11 | Tags schéma v2 sans mapping skill v1. Probablement éditoriaux (qualité subjective du prompt) plus que techniques. | Pas un défaut technique, à laisser hors scope T19+. |
| `image_compo_bonne`, `image_creative`, `image_coherente` (positifs cumul 28) | 28 | Tags positifs — pas un défaut. |
| Custom singletons (`dysmorphie`, `effryant`, `incoherent angle`, `sujet en double`, `sujets en double`, `tramage en gris`, `traits epais`, `variations non significative`, `distinction race animal`, `deformation sujet`, `deformatiion`, `payasage`, `angle`, `incomplet`, `finalisation ko`, `on a donner un choix important`) | ~17 | Vocabulaire annotateur non standardisé, faible volume — bruit. À surveiller si réémergence. | — |

## 3. Plan de transferts (🟡, priorisé)

Tri par impact estimé = % défauts adressés × volume corpus.

| # | défaut adressé | règle skill | impact estimé (n_obs adressables) |
|---|---|---|---:|
| 1 | `image_pas_coherente` + `image_incomprehensible` sur Grille imagier (3 classes : Grille imagier annoté, Imagier différencié OU Solo, Imagier annoté 3×3 OU Solo visage, Imagier différencié 3×3) | T2 + T3 + bug 1 (T23) — contenu explicite par cellule + heuristique solo vs grille | ~60 occurrences (29/33 entrées des 4 classes) |
| 2 | `image_pas_coherente` + `image_incomprehensible` sur Comparatif before/after (Comparatif before/after OU Solo, Solo objet ou comparatif) | T25 + bug v5 — `before_state` / `after_state` explicites | ~28 occurrences (16/18 entrées) |
| 3 | `image_pas_coherente` + `image_incomprehensible` sur Frise narrative 1×N | T4 + bug 3 — banque stages par leaf + rappel synthétique | ~10 occurrences (5/8 entrées) |
| 4 | `image_duplication` résiduel sur `Solo animal` (6 leafs récidivistes) | T9 — profil + orientation directionnelle | 13 occurrences (toutes Solo animal résiduelles après v2) + Solo fish (2) |
| 5 | `image_anatomie_pb` sur tenues spécialisées + personnalités + groupes (`tango_couple`, `polo_player`, `bungee_jumper`, `captain_marvel`, `rapunzel_with_long_hair`, `lamine_yamal_cartoon`, `rafael_nadal_cartoon`, `three_little_pigs`, `dressage_horse`) | T22 + T27 + T30 — pose canonique, tenue granulaire, groupe positionné | ~12 occurrences |
| 6 | `image_simpliste` + `image_pas_coherente` sur `Solo objet météo` + scènes naturelles | T26 + T31 + bug v8 — basculer météo en paysage T26 | ~5 occurrences directes + scènes intérieures et paysages |
| 7 | `image_anatomie_pb` + `image_simpliste` sur `Solo objet (organe sensoriel)` (5/6 leafs avec défaut) | T28 + Z1 (limite labels) + bug v4 (name_en brut) | 6 occurrences |
| 8 | `image_pas_coherente` + `bizarre` sur `Solo objet anatomique + labels` | T28 + Z1 — basculer en grille 3×3 si N≥4 labels | 4 occurrences |
| 9 | `image_simpliste` sur Pattern décoratif simple + mandalas | T29 + bug v7 — template decorative_surface | ~3 occurrences directes (volume aussi limité car peu testé) |
| 10 | Préparation T5/T6/T7 — strip noms couleur + ancres conceptuelles + surfaces 3D | T5 + T6 + Extension T6 + T7 | Volume bas dans corpus actuel (1 `image_gris_residuel`) mais critère prod CLAUDE.md ; transfert prophylactique. |

### Top 3 — briefs Claude Code prêts à coller

#### Brief #1 — Transfert T2 + T3 + T23 (templates Grille imagier)

```
Contexte : 60 défauts image_pas_coherente + image_incomprehensible (sur 130 cumulés
dans le corpus poc-scale-benchmark) sont concentrés sur 4 workflow_classes de grille :
- Grille imagier annoté (8/8 = 100%)
- Imagier différencié OU Solo (7/7 = 100%)
- Imagier annoté 3×3 OU Solo visage (9/10 = 90%)
- Imagier différencié 3×3 (4/8 = 50%)

Diagnostic : src/services/prompt_generator.py templates template_grid_3x3_imagier
(l. 388-402) et template_grid_3x3_annotated (l. 405-416) délèguent le contenu des
cellules au modèle (`each cell contains one different item related to {name}`).
Le skill prompt-taxonomy-ecosystem T2 documente ce pattern comme antipattern et
fournit le fix : contenu explicite + forme géométrique par cellule.

Tâche :
1. Créer un fichier data/prompt_generator/grid_cell_contents.json structuré :
   { "<leaf_id>": { "title": "<TITLE_OVERRIDE>",
                    "cells": [ {"item": "round apple with leaf", "shape": null}, ... ] } }
2. Couvrir au minimum les 4 leafs déjà annotés haute fréquence sur ces 4 classes
   (à extraire des annotations `Imagier différencié 3×3` / `Grille imagier annoté` /
   `Imagier annoté 3×3 OU Solo visage` / `Imagier différencié OU Solo`).
3. Modifier template_grid_3x3_imagier et template_grid_3x3_annotated pour lire
   ce JSON ; si leaf_id absent → fallback sur le comportement actuel (avec un
   warning loggé via artiste_logging).
4. Implémenter T23 (heuristique dispatch v2) : si leaf_id contient un singulier
   `_face`, `_child`, `_portrait` ET workflow_class == 'Imagier annoté 3×3 OU Solo visage'
   → bypass template_grid_3x3 → utiliser template_solo_human (à étendre avec
   `expressive_face` table T23 si l'émotion est dans le nom : proud_, sad_, happy_,
   angry_, surprised_, sleepy_, scared_, calm_, excited_, shy_).
5. Ajouter tests pytest tests/test_prompt_generator.py couvrant :
   - leaf_id présent dans grid_cell_contents.json → cellules nommées présentes dans positive
   - leaf_id absent → fallback comportement actuel
   - leaf_id avec emotion in name + workflow Imagier annoté → solo_expressive_face
   - non-régression sur leafs Solo animal/insect/fish

Sources skill (à citer en commentaire de code) :
- T2 (techniques.md ligne ~106)
- T3 (techniques.md ligne ~133)
- T23 (techniques.md ligne ~676)
- Bug 1 dispatch grille vs solo (techniques.md "Bugs générateur identifiés")

Posture : ne pas modifier NEGATIVE_V3 / _ISOLATION / _RISKY_MULTI_PATTERNS /
LEAF_OVERRIDES dans cette PR — chacun fait l'objet d'un transfert dédié.

Output attendu : PR avec data + code + tests, rapport
docs/reports/YYYY-MM-DD_transfert-skill-T2T3T23-grille-imagier.md.
```

#### Brief #2 — Transfert T25 + bug v5 (template before/after)

```
Contexte : 28 défauts image_pas_coherente + image_incomprehensible (sur 130) sont
concentrés sur 2 workflow_classes Comparatif :
- Comparatif before/after OU Solo (8/10 = 80% — score moyen 1.00, 10% pub)
- Solo objet ou comparatif (6/8 = 75% — score moyen 1.00, 0% pub)

Diagnostic : template_before_after (src/services/prompt_generator.py l. 433-446)
écrit `the right cell shows the same scene with one single change applied` —
pattern explicitement listé en antipattern dans le skill T25 ("Insight C checklist :
`one single change applied` est trop vague — modèle reproduit la même scène").

Tâche :
1. Étendre data/prompt_generator/taxonomy_production_cartography.json sur les
   sous-catégories visées par les 2 classes Comparatif pour ajouter par leaf
   les champs optionnels :
     "before_state": "<description concrète localisée>",
     "after_state":  "<description concrète localisée>"
   (ou en JSON séparé data/prompt_generator/before_after_states.json).
2. Modifier template_before_after :
   - si before_state ET after_state présents → injecter dans les cellules au lieu de
     `in its initial state` / `with one single change applied`
   - sinon : conserver le comportement actuel ET émettre un warning via
     artiste_logging (à minima logger le leaf_id sans before/after).
3. Couvrir au minimum les leafs des 2 classes annotés dans poc-scale-benchmark
   (à extraire des annotations).
4. Tests pytest :
   - leaf avec before/after défini → présence dans positive
   - leaf sans → fallback + warning loggé (capturer via caplog)
5. Documenter en commentaire dans le code la citation exacte du skill T25.

Out of scope :
- Le mode "différences libres" (T25 mode 3) qui est un workflow distinct de
  production — pas dans ce ticket. Si pertinent, ouvrir un ticket suivant.

Output : PR + tests + rapport
docs/reports/YYYY-MM-DD_transfert-skill-T25-before-after.md.
```

#### Brief #3 — Transfert T9 (profil + orientation directionnelle Solo animal)

```
Contexte : Le rerun-2objets a déjà transféré v1 → v2 (NEGATIVE_V3 + _ISOLATION).
Mesure factuelle sur les 13 paires v1/v2 : v1 image_duplication = 13/13 (100%) ;
v2 = 6/13 (46%). Les 6 leafs résiduels :
  bactrian_camel, golden_retriever, mountain_gorilla, playful_dolphin,
  running_cheetah, running_giraffe
ont en commun une morphologie à élément étendu (queue ample, cou long, patte
arrière) qui s'étend derrière le sujet et déclenche la duplication par symétrie.

Le skill T9 (techniques.md ~ligne 234) documente ce pattern précisément :
"Le modèle perd la cohérence du point de vue sur tout élément qui s'étend derrière
le sujet → duplication symétrique. Contraintes de comptage inefficaces. Fix :
Profil strict + orientation directionnelle explicite."

Formule validée :
  `one single [sujet] in profile facing [left/right], [élément] pointing/curving [direction]`

Tâche :
1. Étendre src/services/prompt_generator.py :
   - ajouter une constante _RISKY_BACKWARD_ELEMENTS (queue_ample, cou_long,
     patte_arrière, manche, cape, lance, bâton, parapluie) — vocabulaire skill T9.
   - ajouter un mapping leaf_id → {direction: 'left'|'right',
     backward_element: 'tail'|'neck'|'mane'|'fin'} couvrant minimum les 6 leafs
     ci-dessus (extension par PR ultérieure).
2. Modifier template_solo_animal et template_solo_fish :
   - si le leaf_id est dans le mapping : utiliser la formule T9 au lieu de
     `standing in profile`.
   - sinon : conserver l'isolation existante.
3. Pour les 6 leafs résiduels, configurer explicitement :
     bactrian_camel    → facing right, tail curving right
     golden_retriever  → facing left, tail curving left
     mountain_gorilla  → facing right
     playful_dolphin   → facing left, tail and dorsal fin pointing left
     running_cheetah   → facing right, tail extended right
     running_giraffe   → facing right, neck and tail extended right
4. Tests pytest :
   - les 6 leafs résiduels produisent un positive contenant `facing [direction]`
   - non-régression : sheep_with_lamb / eid_al_adha_sheep continuent d'utiliser
     leur LEAF_OVERRIDE existant (priorité override > template T9).
5. Si possible : rerun ComfyUI sur les 6 leafs (1 image / leaf, seed offset +200)
   et annoter manuellement pour mesurer image_duplication v3 vs v2.

Source skill (à citer en commentaire) :
- T9 — Symétrie : éléments s'étendant derrière le sujet (techniques.md)

Output : PR + tests + (optionnel) rapport rerun
docs/reports/YYYY-MM-DD_transfert-skill-T9-orientation-directionnelle.md.
```

## 4. Opportunités T19+ (🔴, prêtes pour canal manuel)

### T19+ #1 — Méta-pattern grille comme limite ERNIE-Image-Turbo (insight produit 2026-05-10)

```
Hypothèse : Les défauts image_pas_coherente + image_incomprehensible massifs
(91 %–100 %) sur les 4 workflow_classes de grille (Grille imagier annoté,
Imagier différencié OU Solo, Imagier annoté 3×3 OU Solo visage, Imagier
différencié 3×3) ne sont pas (uniquement) un déficit de prompt — ils peuvent
refléter un mismatch structurel entre la demande "répétition stricte avec
contenu hétérogène différencié" et la capacité native d'ERNIE-Image-Turbo Q8
qui (insight utilisateur 2026-05-10) est forte en variation libre, faible en
répétition stricte.

Variable testée : Application T2 + T3 (contenu explicite par cellule + cellules
composées) à pleine puissance (banque de connaissances par leaf, formes géo
explicites) vs basculement de stratégie (composition PIL multi-tiles : 9 images
mono-sujet générées indépendamment puis composées par un script Pillow / SVG).

Défaut ciblé : image_pas_coherente + image_incomprehensible (cumul ~60 occ
adressables sur ces 4 classes) — baseline 100 % sur Grille imagier annoté.

Échantillon : 8-10 leafs des 4 classes (extrait des annotations existantes,
inclure leafs de référence : `clothing_imagier_with_names`,
`color_imagier_with_names`, `balanced_lunch_plate`, `farm_animals_imagier`).

Critère de succès : taux image_pas_coherente après fix < 30% sur l'échantillon
(vs 91-100% baseline). Si T2 maxi appliqué ne descend pas sous ~50% → arbitrage :
basculer le pipeline de production des grilles vers PIL/SVG hors ERNIE.

Précédent : insight produit ERNIE 2026-05-10 (variation libre forte, répétition
stricte faible) ; T2 + T3 dans techniques.md ; fix bug 1 (T23) dans techniques.md ;
docs/reports/2026-05-10_analyse-annotations-poc-scale-benchmark.md (analyse
préalable identifiant ces 2 tags émergents).
```

### T19+ #2 — Méta-pattern Comparatif before/after comme limite ERNIE

```
Hypothèse : Les défauts image_pas_coherente + image_incomprehensible (89 % sur
Comparatif before/after OU Solo + Solo objet ou comparatif) reflètent comme
en T19+ #1 un mismatch structurel : le modèle reproduit la même scène à droite
ET à gauche au lieu de différencier (cf. T25 mode "différence unique explicite").
T25 documente le fix narratif (`tap closed → tap open + bucket`) mais ne mesure
pas si ce fix tient à grande échelle ou si la stratégie devrait être :
générer 2 scènes indépendantes + composition Pillow.

Variable testée : T25 mode 1 (différence unique explicite) appliquée systématiquement
via before_state / after_state dans la cartographie vs composition PIL 2-tiles
(2 images mono-scène générées indépendamment + bandeau "BEFORE"/"AFTER" en post).

Défaut ciblé : image_pas_coherente + image_incomprehensible (cumul ~28 occ).

Échantillon : 8-10 leafs Comparatif (extraire des annotations).

Critère de succès : taux < 30% sur l'échantillon avec T25 maxi. Si pas atteint
→ basculer en composition PIL 2-tiles.

Précédent : T25 (techniques.md) ; bug v5 (techniques.md) ; insight produit ERNIE
2026-05-10.
```

### T19+ #3 — `image_simpliste` comme symptôme de richesse insuffisante du prompt

```
Hypothèse : Le tag schéma v2 image_simpliste (14 occurrences, sans mapping skill v1)
indique un déficit de richesse — le sujet est présent mais le rendu manque de
détails coloriables. Concentré sur `Solo objet météo` (2), `Solo objet en vol OU
au sol` (2), `Solo objet (organe sensoriel)` (1), `Solo objet anatomique + labels`
(1), `Solo objet style kawaii` (1), `Pattern décoratif simple` (1), `Variable
selon sujet` (1), `Solo objet` (1), `Scène intérieure` (1), `Solo objet ou
humain+entité` (1), `Solo objet ou personnage robot` (1), `Variable (solo objet
ou frise pour party)` (1).

Hypothèse alternative : ces leafs sont génériquement pauvres parce que les
templates les routent tous sur template_solo_object qui n'a aucune description
morphologique enrichie (à comparer avec template_solo_animal qui détaille
"all four legs visible on the ground", template_solo_insect qui adapte la
clause pattes, etc.).

Variable testée : enrichir template_solo_object avec une banque de descripteurs
morphologiques par leaf_id (à l'instar du template_solo_fish qui a déjà des
clauses spécifiques par espèce — octopus, jellyfish, crab, seahorse, whale,
dolphin) — y inclure une clause "all distinctive features clearly visible".

Défaut ciblé : image_simpliste.

Échantillon : 14 leafs annotés image_simpliste + 5 contrôles haut score.

Critère de succès : taux image_simpliste < 5% sur l'échantillon (baseline 2.7%
corpus, mais 100% sur les leafs ciblés).

Précédent : T1 (Ratio description/instruction — techniques.md) ; absence dans
le mapping v1→v2 du tag image_simpliste.
```

### T19+ #4 — Pattern `number_N_with_X` (alphabet_and_visual_language)

```
Hypothèse : Les feuilles `number_<N>_with_<X>` (ex. number_one_with_apple,
number_three_with_birds, number_seven_with_butterflies) demandent une
composition chiffre + N items, mais sont actuellement routées via le template
grille 3×3 (Multi-sujets via grille (méta-pattern §2)) qui produit du `comptage`
défaillant (7/10 = 70%, taux moyen 1.50 / 6, 10 % publishable).

Le skill couvre 7 supports de comptage (T15 positionnement gauche/droite,
T16 carte à jouer 1-10, T17 dé sur cube 2-12, T18 caisse à étages 1-20,
T19 façade immeuble, T20 corde à linge, T21 étal de marché) — mais aucun
pattern dédié "chiffre N + N copies du sujet X" n'est indexé dans le skill.

Variable testée : pattern dédié `numeral_with_N_subjects` :
  `the numeral [N] written large on the left side of the page,
   N [sujets] arranged in a [layout] on the right side,
   N [sujets] total no more no less`
  où layout dépend de N (1=centered, 2=left-right, 3=triangle, 4=2×2,
  5=playing-card-5, 6=2×3, 7=playing-card-7, 8=2×4, 9=3×3, 10=playing-card-10, 0=oval+empty).

Défaut ciblé : `comptage` (custom 7 occ, exclusivement sur ces leafs).

Échantillon : les 11 leafs `number_*_with_*` (couvrir 0 à 10).

Critère de succès : taux comptage défaillant < 20% sur l'échantillon
(baseline 70%).

Précédent : T15 + T16 (techniques.md) ; CLAUDE.md "Pattern carte à jouer pour
comptage". Pas de pattern dédié `chiffre+N items` dans le skill — c'est une
extension demandée.
```

### T19+ #5 — Quantification du seuil "prompt_complexe" sur Solo humain en action

```
Hypothèse : Le tag schéma v2 prompt_complexe (8 occ, dont 5/8 = 62 % concentré
sur Solo humain en action — 40 entrées, score moyen 4.00) indique que le prompt
généré dépasse une borne de complexité au-delà de laquelle le modèle dégrade.
Le skill mentionne la règle générale "moins de mise en scène = plus de fiabilité"
(post-T20) mais sans seuil chiffré.

Variable testée : compter les clauses (séparées par virgule) dans le positive
généré pour les 40 leafs Solo humain en action et corréler avec le score / les
défauts. Hypothèse : seuil > N clauses → dégradation. Définir une heuristique
de simplification automatique (exemple : si N > 10 → garder uniquement le
STYLE_BLOCK + nom + 3 clauses morphologiques canoniques + ground_line).

Défaut ciblé : prompt_complexe + image_anatomie_pb (3 occ Solo humain en action).

Échantillon : les 40 leafs Solo humain en action déjà annotés.

Critère de succès : identification du seuil N tel que % défaut chute <10% en
deçà du seuil et >25% au-dessus. Si N exploitable → règle bornage automatique
template_solo_human + template_solo_human (l. 340-348).

Précédent : T1 ratio description/instruction (techniques.md) ; règle générale
"moins de mise en scène" (techniques.md) ; pas de seuil chiffré.
```

## 5. Focus sur les 3 critères de sortie du cycle (factuel, sans verdict)

### A — taux `image_duplication` (≈ v1 `2_objets`) v1 vs v2 sur les 13 paires `rerun-2objets.json`

Source : `docs/reports/poc-scale-benchmark/rerun-2objets.json` croisé avec
`docs/reports/poc-scale-benchmark/annotations.json`.

| leaf_id | v1 `image_duplication` | v1 score | v2 `image_duplication` | v2 score |
|---|:--:|:--:|:--:|:--:|
| bactrian_camel | True | 1 | True | 5 |
| chimpanzee | True | 1 | False | 6 |
| eid_al_adha_sheep | True | 1 | False | 6 |
| golden_retriever | True | 1 | True | 1 |
| house_painter_with_roller | True | 1 | False | 5 |
| labrador_retriever | True | 1 | False | 6 |
| mountain_gorilla | True | 1 | True | 1 |
| playful_dolphin | True | 1 | True | 1 |
| running_cheetah | True | 1 | True | 1 |
| running_giraffe | True | 1 | True | 1 |
| sheep_with_lamb | True | 1 | False | 6 |
| snow_leopard | True | 1 | False | 6 |
| spotted_hyena | True | 1 | False | 6 |
| **TOTAL** | **13/13 (100%)** | — | **6/13 (46 %)** | — |

7 leafs sortent du défaut : `chimpanzee`, `eid_al_adha_sheep` (LEAF_OVERRIDE),
`house_painter_with_roller`, `labrador_retriever`, `sheep_with_lamb`
(LEAF_OVERRIDE), `snow_leopard`, `spotted_hyena`.
6 leafs persistent : `bactrian_camel` (v2 score=5 mais tag présent),
`golden_retriever`, `mountain_gorilla`, `playful_dolphin`, `running_cheetah`,
`running_giraffe` — tous score=1 sauf bactrian_camel. Caractéristique commune :
morphologie à élément étendu derrière le sujet (queue, cou, fin). Couvert par
skill T9 — voir transfert #4 (brief #3 §3).

Sur l'ensemble du corpus 515 entrées : `image_duplication` = 28 occurrences
(5.4 %). 16 sont sur les 13 paires v1/v2 ci-dessus ; les 12 autres :
`animal_superhero`, `letter_z_with_zebre` (exclus du rerun), `grasshopper`
(Solo insect), `bactrian_camel` v2 (1 occ score=5), `golden_retriever` v2,
`mountain_gorilla` v2, `playful_dolphin` v2, `running_cheetah` v2,
`running_giraffe` v2, `child_with_test_tubes`, `gaming_setup_with_keyboard`,
`horse_racing`, `laptop_open_with_code`, `optometrist_eye_test`,
`three_little_pigs`. Cas non-Solo-animal → templates qui n'ont pas reçu
`_ISOLATION` (cf. §2 🟡 ligne « Solo humain (générique), Solo humain + accessoires,
Humain + entité (cheval), Humain + entité (instrument), Humain + entité OU
Solo humain pose statique, Scène ou solo personnage, Solo objet ou Humain +
entité »). Transfert _ISOLATION à ces templates = à intégrer dans une PR
distincte (gap 🟡 documenté).

### B — défauts dominants par méta-pattern (4 classes)

Périmètre : `Imagier différencié 3×3`, `Imagier différencié OU Solo`, `Imagier
annoté 3×3 OU Solo visage`, `Grille imagier annoté` (Grille imagier) ; `Frise
narrative 1×N (pattern X2)` (Frise) ; `Multi-sujets via grille (méta-pattern §2)`
(Multi-sujets via grille).

| classe | n | score moy | pub % | top tags (image+prompt+custom) |
|---|---:|---:|---:|---|
| Grille imagier annoté | 8 | 1.00 | 0 % | image_pas_coherente:8, image_incomprehensible:8 |
| Imagier annoté 3×3 OU Solo visage | 10 | 1.10 | 10 % | image_pas_coherente:9, image_incomprehensible:8, variations non significative:1 |
| Imagier différencié OU Solo | 7 | 1.57 | 0 % | image_incomprehensible:6, image_pas_coherente:6, image_compo_bonne:1, image_prompt_non_respecte:1, prompt_approximatif:1 |
| Imagier différencié 3×3 | 8 | 3.38 | 50 % | image_pas_coherente:4, image_incomprehensible:4 |
| Frise narrative 1×N (pattern X2) | 8 | 2.38 | 25 % | image_pas_coherente:5, image_incomprehensible:5, image_compo_bonne:2, prompt_ambigu:1, prompt_approximatif:1 |
| Multi-sujets via grille (méta-pattern §2) | 10 | 1.50 | 10 % | comptage:7, image_pas_coherente:1, image_incomprehensible:1 |

Le défaut dominant sur 5 des 6 méta-patterns est le couple
`image_pas_coherente` + `image_incomprehensible` (corrélation 91 % — voir §1).
Sur Multi-sujets via grille, le défaut dominant bascule sur `comptage`.

### C — défauts dominants par classe « OU » (17 classes au libellé contenant OU/ou)

| classe | n | score | pub % | top tags |
|---|---:|---:|---:|---|
| Solo personnage ou créature | 2 | 6.00 | 100 % | (aucun tag) |
| Solo objet ou personnage robot | 8 | 4.88 | 88 % | image_compo_bonne, image_creative, prompt_interessant, prompt_creatif |
| Humain + entité OU Solo humain pose statique | 10 | 4.70 | 80 % | image_anatomie_pb:1, image_pas_coherente:1, image_incomprehensible:1, image_duplication:1 |
| Solo objet ou humain en scaphandre | 10 | 4.60 | 90 % | image_compo_bonne, image_coherente, image_creative |
| Solo objet en vol OU au sol | 9 | 4.56 | 100 % | image_simpliste:2 |
| Scène ou solo personnage | 10 | 4.30 | 70 % | image_anatomie_pb:2, image_pas_coherente:1, image_incomprehensible:1 |
| Humain + entité OU Solo | 9 | 4.22 | 78 % | image_anatomie_pb:1, image_pas_coherente:1, image_incomprehensible:1 |
| Solo humain OU objet | 6 | 3.83 | 50 % | bizarre:2, image_compo_bonne:1, image_pas_coherente:1 |
| Variable (solo objet ou frise pour party) | 6 | 3.83 | 100 % | image_simpliste:1 |
| Solo objet ou humain+entité | 7 | 3.71 | 57 % | bizarre:1, image_simpliste:1 |
| Solo humain ou objet | 10 | 3.00 | 60 % | image_pas_coherente:2, image_incomprehensible:2, image_creative:1, bizarre:1 |
| Solo objet ou Humain + entité | 8 | 3.00 | 50 % | image_pas_coherente:2, image_incomprehensible:2, image_duplication:2, image_physique_pb:1 |
| Solo objet ou scène | 6 | 3.00 | 83 % | image_anatomie_pb:1 |
| Imagier différencié OU Solo | 7 | 1.57 | 0 % | image_incomprehensible:6, image_pas_coherente:6 |
| Imagier annoté 3×3 OU Solo visage | 10 | 1.10 | 10 % | image_pas_coherente:9, image_incomprehensible:8 |
| Comparatif before/after OU Solo | 10 | 1.00 | 10 % | image_pas_coherente:8, image_incomprehensible:8, finalisation ko:1 |
| Solo objet ou comparatif | 8 | 1.00 | 0 % | image_pas_coherente:6, image_incomprehensible:6 |

Les 4 classes de bas de tableau (score ≤ 1.57) sont toutes des classes « OU »
de type imagier ou comparatif. Les classes « OU » de type humain/objet sont
réparties autour de 3.00–4.88. Les classes « OU » avec « scaphandre », « vol OU
au sol », « créature » et « personnage robot » (pubs 88-100 %) tirent vers le
haut. Le libellé « OU » en lui-même n'est donc pas corrélé directement à un
défaut — c'est la stratégie de production sous-jacente (grille / comparatif /
solo) qui structure le résultat.

## Points d'attention (cas ambigus, données manquantes)

- **Schéma v2 vs vocab skill v1** : 4 tags v2 majeurs (`image_pas_coherente`,
  `image_incomprehensible`, `image_simpliste`, `image_compo_bonne`) ne sont pas
  dans le mapping `scripts/migrate_benchmark_annotations.py`. Le skill ne
  référence donc directement que `image_duplication`, `image_anatomie_pb`,
  `image_traces_couleur`, `image_flou`, `image_traits_pb`, `image_physique_pb`,
  `image_gris_residuel`, `image_prompt_non_respecte`. Les 4 tags émergents
  ci-dessus ont été classés par contenu et concentration sur classes — à
  arbitrer si l'archi veut consolider le vocabulaire (un T19+ vocab pourrait
  s'imposer).
- **Volume corpus** : 515 entrées scorées dans `poc-scale-benchmark/annotations.json`
  (le brief mentionnait 222 — la valeur 222 vient d'un sous-ensemble partiellement
  annoté ailleurs ; la valeur actuelle est 515, à vérifier avec l'archi quelle
  baseline est canonique). Les 8 dossiers POC secondaires (438 entrées
  cumulées selon le brief) n'ont pas été agrégés dans cette analyse — uniquement
  cités. Ouvrable si l'archi le demande.
- **`image_pas_coherente` vs `image_incomprehensible`** : co-occurrence 91 %.
  Soit l'annotateur les utilise quasi-interchangeablement, soit ils captent
  deux dimensions corrélées d'un même défaut. Pas tranché.
- **Critère A — score=5 avec tag présent (`bactrian_camel` v2)** : la grille v2
  permet à un défaut d'être taggé tout en ayant un score haut (interprétation :
  défaut mineur ou défaut résiduel acceptable). À surveiller comme noise factor
  dans le critère A — la valeur quantitative « 6/13 v2 » est donc une borne
  haute.
- **`prompt_complexe` (8 occ)** : le tag schéma v2 est suffisamment vague pour
  capter à la fois "prompt techniquement trop dense" et "concept trop ambitieux".
  La séparation est laissée à T19+ #5 si l'archi veut tranché.
- **Insight produit ERNIE 2026-05-10** : appliqué dans T19+ #1 et #2 comme
  hypothèse alternative. L'archi tranche si on tente d'abord les transferts T2/
  T3/T25 maxi, ou si on bascule directement le pipeline grille/comparatif sur
  une stratégie de composition PIL/SVG.
- **Custom singletons** (~17 tags annotateurs uniques) : pas un gap, mais un
  signal de besoin de standardisation du vocabulaire d'annotation. Hors scope.

## Décision / Action suivante

(Laisser vide — l'archi priorise.)
