# Phase MEP v0 / C — Export `data/export/`
Date : 2026-05-12

## Contexte

Export du corpus MEP v0 (manifest + posts × 3 locales + images PNG) consommable par `alwanbooks-pipeline`. Filtre `publishable=true` **depuis la table `annotation` en DB** (post Brief C1), pas depuis les fichiers `annotations.json`. Gate HARD caps Zod strict [5,100] titre / [20,200] description. Soft caps éditoriaux internes tolérés (cf. CLAUDE.md §Validation).

## Résultats

- Mode : **APPLY**
- Leaves i18n total : **150**
  - status=ok : 1
  - status=soft_caps_violated : 149
  - status=autre : 0
- Leaves passant HARD caps : **135**
- Leaves échouant HARD caps : 15
- Leaves sans annotation publishable : 0
- **Leaves exportés : 135**

### DB writes

- image INSERT : 0
- image UPDATE : 135
- image_publication INSERT : 0
- image_publication UPDATE : 405

### Fichiers écrits

- Posts JSON (3 par leaf) : 405
- PNG copiés : 0
- PNG master manquants : 135

### Leaves bloqués par HARD caps Zod (extrait, max 20)

- `blue_whale` : description_en len=230 hors [20,200]
- `fighter_jet` : description_en len=226 hors [20,200]
- `garden_spider` : description_en len=230 hors [20,200]
- `knight_in_shining_armor` : description_en len=207 hors [20,200]
- `letter_a_with_apple` : description_fr len=277 hors [20,200]
- `letter_u_with_umbrella` : description_en len=201 hors [20,200]
- `letter_x_with_xylo` : description_en len=237 hors [20,200]
- `nowruz_goldfish_in_bowl` : description_en len=215 hors [20,200]
- `olaf_the_snowman` : description_en len=230 hors [20,200]
- `police_officer_on_duty` : description_en len=202 hors [20,200]
- `soaring_eagle` : description_en len=205 hors [20,200]
- `tango_couple` : description_en len=202 hors [20,200]
- `thread_spool` : description_en len=207 hors [20,200]
- `weighing_scale` : description_en len=219 hors [20,200]
- `wooden_cutting_board` : description_en len=308 hors [20,200]

### PNG masters manquants (extrait, max 10)

- `abstract-zentangle` (target_id: `poc-scale-benchmark/abstract_zentangle_1024x1024_euler8s.png`)
- `advanced-mandala-for-teens` (target_id: `poc-scale-benchmark/advanced_mandala_for_teens_1024x1024_euler8s.png`)
- `african-elephant` (target_id: `poc-generator-benchmark/african_elephant_1024x1024_euler8s.png`)
- `ai-brain-with-circuits` (target_id: `poc-scale-benchmark/ai_brain_with_circuits_1024x1024_euler8s.png`)
- `air-fryer` (target_id: `poc-scale-benchmark/air_fryer_1024x1024_euler8s.png`)
- `aladdin-with-magic-lamp` (target_id: `poc-scale-benchmark/aladdin_with_magic_lamp_1024x1024_euler8s.png`)
- `alpaca` (target_id: `poc-scale-benchmark/alpaca_1024x1024_euler8s.png`)
- `ancient-water-wheel` (target_id: `poc-scale-benchmark/ancient_water_wheel_1024x1024_euler8s.png`)
- `animal-mandala-lion-head` (target_id: `poc-scale-benchmark/animal_mandala_lion_head_1024x1024_euler8s.png`)
- `antique-radio-set` (target_id: `poc-scale-benchmark/antique_radio_set_1024x1024_euler8s.png`)
- … (125 autres)

## Points d'attention

- **HARD caps Zod stricts** : gate contractuelle plateforme appliquée. Les leaves qui violent [5,100]/[20,200] sont **explicitement bloqués** et listés ici — pas d'export silencieux.
- **Soft caps éditoriaux tolérés** : 149/150 leaves ont `status='soft_caps_violated'` mais respectent les HARD caps Zod. Le pipeline accepte ce contenu (soft caps = préférences internes, pas contrat plateforme).
- **Convention chiffres en lettres** (i18n une fois pour toutes) : les `name_*` source ne doivent contenir aucun chiffre. `r2_slug` lève `ValueError` sur tout `name_en` commençant par un chiffre (cf. brief C2). À documenter pour les futurs runs de batch i18n côté Brief B.
- **PNG masters absents du repo** : les fichiers PNG référencés par les annotations publishable ne sont pas tous présents sur disque (stockés hors repo). Les Posts JSON sont produits avec URLs R2 prédites ; les masters seront uploadés par `alwanbooks-pipeline` depuis le bucket source réel.
- **Collisions slug** : aucune collision intra-export détectée sur le corpus actuel. Stratégie de déduplication post-collision (suffixe numérique) à implémenter si besoin futur (cf. contrat §5).
- **categoryId / themeIds vides en v0** : la table `image_taxonomy_tag` n'est pas peuplée pour le corpus benchmark — à compléter dans un brief post-v0 (mapping leaf_id → categoryId via taxonomy production cartography).

## Décision / Action suivante

- ✅ 135 leaves exportés en DB + sur disque (`data/export/`).
- ✅ Manifest `data/export/manifest.json` produit pour `alwanbooks-pipeline`.
- ➡️ Brief D (post-v0) : peupler `image_taxonomy_tag` pour les leaves benchmark exportés (`categoryId` non vide).
- ➡️ Action Brief B : relancer batch i18n pour les 15 leaves bloqués HARD caps (descriptions trop longues principalement).
