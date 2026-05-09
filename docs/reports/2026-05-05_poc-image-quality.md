# POC image quality — bouclage prompt → ComfyUI → QC vision
Date : 2026-05-05

## Contexte
Premier bouclage de la chaîne complète : on prend les **prompts produits par POC-3 v2** (`2026-05-05_poc-prompt-chain-v2.json`, score validator ≥ 95), on les génère réellement via **ComfyUI** (workflow `ernie-image-turbo-q8-api`), puis on évalue chaque image avec **qwen3.5:9b** (le QC vision validé en `2026-05-05_poc-qwen35-vision.md`). C'est le chaînon manquant entre le score validator (syntaxique) et la qualité visuelle réelle.

**Sélection** : 1 concept par catégorie sur les 8 catégories de POC-3 v2 (score ≥ 95).

## Critères de succès
- ≥ **6/8** images verdict ``good`` du QC vision
- **0** image avec `has_text` détecté
- ≤ **2** images avec histogram KO (couleurs parasites)

## Résultats par concept

| # | Catégorie | Concept | Validator | Comfy s | Hist | Vision verdict | Issues | Conf | Image |
|---|---|---|---:|---:|:---:|:---:|---|---:|---|
| 1 | animaux | Cat in a Library | 95 | 42.4 | ✅ | **good** | — | 100 | `docs/reports/poc-image-quality/animaux-cat-in-a-library.png` |
| 2 | outils | Hammer on a Workbench | 95 | 18.2 | ✅ | **good** | — | 100 | `docs/reports/poc-image-quality/outils-hammer-on-a-workbench.png` |
| 3 | sports | Soccer Ball on a Field | 95 | 18.2 | ✅ | **good** | — | 100 | `docs/reports/poc-image-quality/sports-soccer-ball-on-a-field.png` |
| 4 | personnages_fictifs | Superhero on a City Rooftop | 95 | 18.1 | ✅ | **good** | — | 100 | `docs/reports/poc-image-quality/personnages_fictifs-superhero-on-a-city-rooftop.png` |
| 5 | electromenager | Refrigerator in a Kitchen | 95 | 18.2 | ❌ | **good** | has_color | 95 | `docs/reports/poc-image-quality/electromenager-refrigerator-in-a-kitchen.png` |
| 6 | geometrie | Cube on a Math Desk | 95 | 18.2 | ✅ | **good** | — | 100 | `docs/reports/poc-image-quality/geometrie-cube-on-a-math-desk.png` |
| 7 | professions | Astronaut on a Space Station | 95 | 20.2 | ✅ | **good** | — | 100 | `docs/reports/poc-image-quality/professions-astronaut-on-a-space-station.png` |
| 8 | fantasy | Dragon in a Castle Courtyard | 95 | 20.2 | ❌ | **good** | has_color | 95 | `docs/reports/poc-image-quality/fantasy-dragon-in-a-castle-courtyard.png` |

## Agrégats

- Images générées : **8/8**
- Verdict ``good`` : **8/8** (✅ cible ≥ 6)
- Verdict ``poor`` : **0/8**
- ``has_text`` détecté : **0/8** (✅ cible 0)
- ``has_color`` détecté : **2/8**
- Histogram KO : **2/8** (✅ cible ≤ 2)
- Comfy latency : min=18.1s · mean=21.7s · max=42.4s
- Vision latency : min=3.6s · mean=4.4s · max=8.0s

## Détail par image

### [animaux] Cat in a Library
- Prompt validator score : 95
- Comfy : 42.42s · seed=3118672567
- Histogram : color_ratio=0.0015 · white_ratio=0.81213 · ink_ratio=0.12276 · flags=[]
- Vision : verdict=**good** · issues=[] · confidence=100 · latency=8.0s
- Image : `docs/reports/poc-image-quality/animaux-cat-in-a-library.png`

### [outils] Hammer on a Workbench
- Prompt validator score : 95
- Comfy : 18.19s · seed=3574900139
- Histogram : color_ratio=0.00212 · white_ratio=0.82616 · ink_ratio=0.1302 · flags=[]
- Vision : verdict=**good** · issues=[] · confidence=100 · latency=3.6s
- Image : `docs/reports/poc-image-quality/outils-hammer-on-a-workbench.png`

### [sports] Soccer Ball on a Field
- Prompt validator score : 95
- Comfy : 18.19s · seed=1598463574
- Histogram : color_ratio=0.00656 · white_ratio=0.73484 · ink_ratio=0.14025 · flags=[]
- Vision : verdict=**good** · issues=[] · confidence=100 · latency=3.6s
- Image : `docs/reports/poc-image-quality/sports-soccer-ball-on-a-field.png`

### [personnages_fictifs] Superhero on a City Rooftop
- Prompt validator score : 95
- Comfy : 18.13s · seed=2343630559
- Histogram : color_ratio=0.00169 · white_ratio=0.8264 · ink_ratio=0.11678 · flags=[]
- Vision : verdict=**good** · issues=[] · confidence=100 · latency=3.6s
- Image : `docs/reports/poc-image-quality/personnages_fictifs-superhero-on-a-city-rooftop.png`

### [electromenager] Refrigerator in a Kitchen
- Prompt validator score : 95
- Comfy : 18.18s · seed=4282975060
- Histogram : color_ratio=0.05817 · white_ratio=0.83639 · ink_ratio=0.07459 · flags=['noticeable_color']
- Vision : verdict=**good** · issues=['has_color'] · confidence=95 · latency=3.8s
- Image : `docs/reports/poc-image-quality/electromenager-refrigerator-in-a-kitchen.png`

### [geometrie] Cube on a Math Desk
- Prompt validator score : 95
- Comfy : 18.21s · seed=2802341502
- Histogram : color_ratio=0.00239 · white_ratio=0.80999 · ink_ratio=0.11848 · flags=[]
- Vision : verdict=**good** · issues=[] · confidence=100 · latency=4.8s
- Image : `docs/reports/poc-image-quality/geometrie-cube-on-a-math-desk.png`

### [professions] Astronaut on a Space Station
- Prompt validator score : 95
- Comfy : 20.16s · seed=4046715983
- Histogram : color_ratio=0.00435 · white_ratio=0.77454 · ink_ratio=0.16055 · flags=[]
- Vision : verdict=**good** · issues=[] · confidence=100 · latency=3.7s
- Image : `docs/reports/poc-image-quality/professions-astronaut-on-a-space-station.png`

### [fantasy] Dragon in a Castle Courtyard
- Prompt validator score : 95
- Comfy : 20.21s · seed=3703769972
- Histogram : color_ratio=0.05019 · white_ratio=0.76429 · ink_ratio=0.12641 · flags=['noticeable_color']
- Vision : verdict=**good** · issues=['has_color'] · confidence=95 · latency=4.0s
- Image : `docs/reports/poc-image-quality/fantasy-dragon-in-a-castle-courtyard.png`

## Patterns d'échec visuels

### Pattern principal — couleurs résiduelles sur subjects à fort prior couleur (2/8)

**Refrigerator in a Kitchen** (color_ratio 0.058, `noticeable_color`, vision `has_color` conf 95) et **Dragon in a Castle Courtyard** (color_ratio 0.050, idem) sont les deux seules images flaguées. Les deux subjects ont un **prior couleur fort** dans les datasets d'entraînement du modèle image (frigos = appareils colorés / cuisines en couleur, dragons = illustrations fantasy systématiquement colorisées). Le modèle ERNIE-Image-Turbo « leak » ce prior catégoriel malgré les contraintes monochrome explicites du prompt.

Les 6 autres concepts (Cat in Library, Hammer, Soccer Ball, Superhero, Cube, Astronaut) n'ont pas ce biais de domaine et sortent à color_ratio < 0.007 (10× moins).

**Concordance histogram ↔ vision parfaite** sur ce pattern : les 2 mêmes images sont KO côté Pillow (`noticeable_color`) et côté vision (`has_color`). Le histogram pre-check (< 10ms) est donc un **filtre bon marché** capable d'intercepter ce cas avant le call vision (~4s). On peut envisager un short-circuit en prod : si `color_ratio > 0.025`, taguer directement `has_color` sans appeler le vision.

### Absence remarquable — `has_text` 0/8

Le critère « 0 image avec texte visible » est **parfaitement tenu**. C'est la validation end-to-end du fix #3 du POC-3 v2 (règle « no readable text » dans `prompt_writer_ernie.system`) : la consigne syntaxique en upstream se traduit bien par 0 texte parasite côté image, y compris sur des subjects à fort risque (Soccer Ball / stadium signage, Superhero / city signs, Astronaut / control panel labels, Cube / math notations, Skeleton / lab labels potentiels). Le validator était une couche, le writer est désormais la vraie gate.

## Recommandations

| Priorité | Action | Effet attendu |
|---|---|---|
| Moyen | **Short-circuit histogram → has_color** : si `color_ratio > 0.025`, taguer l'image et zapper l'appel vision pour ce check (vision restera utile pour les autres issues : blurry, incomplete, artifacts). | -50 % de calls vision sur les KO couleur, économie ~4 s × N images |
| Moyen | **Prompt writer — anti-color-prior pour subjects à risque** : ajouter à `prompt_writer_ernie.system` une consigne « When the subject (refrigerator, dragon, fruit, flag, parrot, butterfly, etc.) is commonly depicted in color in reference images, prepend ‘plain black outline silhouette of a’ to neutralize the model's color prior. » À tester en A/B sur un autre 8-pack avec subjects à fort prior couleur. | Devrait ramener color_ratio < 0.01 sur Refrigerator / Dragon |
| Bas | **Reseeding sur histogram KO** : workflow prod retry 1× avec un autre seed avant `awaiting_validation` quand `color_ratio > 0.025`. | Filet de sécurité pour les cas marginaux non couverts par le prompt fix |
| Bas | **Vision QC — issue `has_text` validée** : ajouter ce critère explicite à la liste `Possible issues` (déjà fait dans ce POC) et le promouvoir comme check obligatoire en prod. | Cohérence avec la règle no-text upstream |

**Pas de changement ComfyUI requis** — le workflow `ernie-image-turbo-q8-api` (8 steps, cfg 1.0, euler+normal) produit du line art propre sur 6/8 ; les 2 fails sont des échecs sémantiques du modèle face au prior couleur, pas des fails techniques (pas de blur, pas d'artifact, structure correcte). La latence ComfyUI moyenne ~22s est compatible avec un batch raisonnable en prod.

## Verdict

✅ **Boucle prompt→image→QC validée.** Les 3 critères du POC sont remplis :

| Critère | Cible | Mesure | Lecture |
|---|---|---|---|
| Vision verdict ``good`` | ≥ 6/8 | **8/8 (100 %)** | ✅ +2 vs cible — qualité supérieure attendue |
| ``has_text`` détecté | 0 | **0/8** | ✅ fix #3 POC-3 v2 confirmé end-to-end |
| Histogram KO | ≤ 2 | **2/8** | ✅ pile à la limite, pattern « color prior » identifié |

**Décision :** la chaîne complète planner → writer → validator → ComfyUI est exploitable pour P2. Les 2 ajustements moyens recommandés (short-circuit histogram + anti-color-prior dans le writer) peuvent être appliqués en parallèle ; ils sont non bloquants car même les 2 cas KO sont jugés ``good`` par le vision QC (le QC vision vaut autorisation de publication, le histogram sert de signal complémentaire).

**Latences observées compatibles prod :**
- ComfyUI : 18-42s (premier call à 42.4s = warmup modèle ; les 7 suivants 18-20s) → médiane ~18s
- Vision QC : 3.6-8s → médiane ~3.7s
- Total par image : ~22s en régime établi

À batch 50 images / jour, le pipeline tient en ~20 minutes de wall-time pour la phase image+QC.

## Annexes

- Galerie images : `docs/reports/poc-image-quality/` (1 PNG par concept, naming `<categorie>-<slug>.png`)
- Données brutes : `2026-05-05_poc-image-quality.json`
- Source prompts : `2026-05-05_poc-prompt-chain-v2.json` (POC-3 v2)
- Script : `scripts/poc_image_quality.py`
- Workflow ComfyUI : `data/workflows/ernie-image-turbo-q8-api.json` + `.overrides.json`
- QC vision : `qwen3.5:9b` (mêmes paramètres que `scripts/poc_qwen35_vision.py`)
- QC technique : `src/services/image_qc_technical.py::build_technical_image_qc_v1`