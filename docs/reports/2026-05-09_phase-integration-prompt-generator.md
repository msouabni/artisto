# Phase — Intégration PromptGenerator + POC benchmark v3
Date : 2026-05-09

## Contexte

Phase d'intégration de `PromptGenerator` (taxonomie 1376 feuilles + cartographie + SEO) en service interne (`src/services/prompt_generator.py`) et validation pratique via un POC benchmark image-generation : 30 feuilles représentatives par classe, prompts générés par le service, soumission ERNIE direct via injection JSON brute, QC histogram automatique.

Référence : tâche utilisateur du 2026-05-09 — corriger les leaf_ids hardcodés (23/30 introuvables au premier essai sur la liste initiale), valider la qualité des prompts template du `PromptGenerator`.

## Tâche A — Intégration PromptGenerator

| Action | Source | Cible |
|---|---|---|
| Module Python | `docs/xchange/prompt_generator.py` | `src/services/prompt_generator.py` |
| Taxonomy | `docs/xchange/coloring_taxonomy_full.json` | `data/prompt_generator/coloring_taxonomy_full.json` |
| Cartographie | `docs/xchange/taxonomy_production_cartography.json` | `data/prompt_generator/taxonomy_production_cartography.json` |
| SEO | `docs/xchange/coloring_taxonomy_seo.json` | `data/prompt_generator/coloring_taxonomy_seo.json` |

`DEFAULT_*` ajustés en absolu via `PROJECT_ROOT = Path(__file__).resolve().parents[2]`. Import validé avec `PYTHONPATH=src` :
```python
from services.prompt_generator import PromptGenerator
gen = PromptGenerator()  # 1376 leaves chargées, leaf_index OK
result = gen.build_prompt("lion_in_savanna")
# → keys : leaf_id, leaf_name_en/fr/ar, subcategory_id/name, category_root,
#          positive, negative, resolution, workflow_class, technique,
#          pipeline, confidence, pitfalls, notes, seo
```

## Tâche B — POC benchmark : 27 OK / 3 SKIP / 0 KO

### Plan v2 (corrigé)

30 IDs validés contre `leaf_index` avant lancement. 3 introuvables détectés en pré-check ; le script les `SKIP` proprement (tracé `status: skip_unknown_leaf` dans l'index).

### IDs trouvés (27)

```
lion_in_savanna · african_elephant · farm_horse · pet_turtle · sea_turtle_swimming
monarch_butterfly · garden_spider
nowruz_goldfish_in_bowl · playful_dolphin · clownfish_in_anemone
soaring_eagle · peacock_with_open_tail · emperor_penguin
firefighter_with_hose · baker_with_bread · doctor_with_stethoscope · ballet_dancer_pose · astronaut_floating_in_space
princess_in_tower · knight_in_shining_armor · wizard_with_staff
sailing_boat · hot_air_balloon · first_steam_engine_train
birthday_cake_with_candles · musician_with_guitar · medieval_castle_with_moat
```

### IDs introuvables (3)

| ID demandé | Suggestion taxonomie réelle |
|---|---|
| `honeybee_on_flower` | aucun match `honeybee*` ; alternatives candidates : `garden_spider`, `monarch_butterfly` (déjà testés) |
| `pirate_ship_captain` | `pirate_ship` existe (Solo objet véhicule) — pas de variante "captain" |
| `vintage_car_convertible` | `vintage_car_1920s` (1920s touring car), `vintage_radio`, `vintage_game_controller` |

### Tableau de résultats

Tous les paramètres ComfyUI fixes : `steps=8, sampler=euler, scheduler=normal, cfg=1.0`. Seed déterministe `4242 + idx*7`. Pipeline cible = `ERNIE direct` (lu depuis cartographie).

| leaf_id | workflow_class (cartographie) | résolution | color_ratio | ink_ratio | latence | confidence |
|---|---|---|---|---|---|---|
| lion_in_savanna | Solo animal | 1024×1024 | 0.0007 | 0.098 | 18.4s | Haute |
| african_elephant | Solo animal | 1024×1024 | 0.0011 | 0.088 | 18.1s | Haute |
| farm_horse | Solo animal | 1024×1024 | 0.0010 | 0.121 | 18.2s | Haute |
| pet_turtle | Solo animal | 1024×1024 | 0.0007 | 0.084 | 20.2s | Haute |
| sea_turtle_swimming | Solo fish | 1024×1024 | 0.0012 | 0.084 | 18.1s | Haute |
| monarch_butterfly | Solo insect | 1024×1024 | 0.0009 | 0.112 | 18.2s | Haute |
| garden_spider | Solo insect | 1024×1024 | 0.0009 | 0.117 | 18.2s | Haute |
| nowruz_goldfish_in_bowl | Variable | 1024×1024 | 0.0010 | 0.097 | 18.2s | Haute |
| playful_dolphin | Solo fish | 1024×1024 | 0.0008 | 0.072 | 18.1s | Haute |
| clownfish_in_anemone | Solo fish | 1024×1024 | 0.0006 | 0.140 | 18.2s | Haute |
| soaring_eagle | Solo bird | 1024×1024 | 0.0010 | 0.090 | 18.2s | Moyenne |
| peacock_with_open_tail | Solo bird | 1024×1024 | 0.0013 | 0.139 | 18.2s | Moyenne |
| emperor_penguin | Solo animal | 1024×1024 | **0.0002** | 0.050 | 18.2s | Haute |
| firefighter_with_hose | Solo humain pose active | 848×1264 | 0.0010 | 0.125 | 18.1s | Haute |
| baker_with_bread | Solo humain + accessoires | 1024×1024 | 0.0006 | 0.070 | 18.1s | Haute |
| doctor_with_stethoscope | Humain + entité OU Solo humain pose statique | 1024×1024 | 0.0009 | 0.119 | 18.2s | Haute |
| ballet_dancer_pose | Solo humain + accessoires | 1024×1024 | 0.0006 | 0.053 | 18.2s | Haute |
| astronaut_floating_in_space | Solo objet ou humain en scaphandre | 848×1264 | 0.0010 | 0.117 | 18.2s | Haute |
| princess_in_tower | Solo personnage ou créature | 848×1264 | **0.0017** | 0.093 | 18.2s | Haute |
| knight_in_shining_armor | Solo personnage ou créature | 848×1264 | **0.0019** | 0.111 | 18.2s | Haute |
| wizard_with_staff | Solo personnage ou créature | 848×1264 | 0.0013 | 0.118 | 18.2s | Haute |
| sailing_boat | Solo humain en action | 1376×768 | **0.0004** | 0.066 | 18.2s | Haute |
| hot_air_balloon | Solo objet en vol OU au sol | 1376×768 | **0.0004** | 0.040 | 18.2s | Haute |
| first_steam_engine_train | Solo objet historique | 1024×1024 | 0.0007 | 0.146 | 18.2s | Haute |
| birthday_cake_with_candles | Variable (solo objet ou frise) | 1024×1024 | 0.0009 | 0.099 | 18.2s | Haute |
| musician_with_guitar | Solo humain + accessoires | 1024×1024 | 0.0010 | 0.085 | 18.1s | Haute |
| medieval_castle_with_moat | Solo personnage ou créature | 848×1264 | 0.0011 | 0.149 | 18.2s | Haute |

### Stats color_ratio par classe (cartographie réelle)

| workflow_class | n | cr_avg | cr_max | ink_avg |
|---|---|---|---|---|
| Solo animal | 5 | 0.00074 | 0.0011 | 0.088 |
| Solo bird | 2 | 0.00115 | 0.0013 | 0.115 |
| Solo fish | 3 | 0.00087 | 0.0012 | 0.099 |
| Solo insect | 2 | 0.00090 | 0.0009 | 0.115 |
| Solo humain + accessoires | 3 | 0.00073 | 0.0010 | 0.069 |
| Solo humain pose active | 1 | 0.00100 | 0.0010 | 0.125 |
| Humain + entité OU pose statique | 1 | 0.00090 | 0.0009 | 0.119 |
| Solo humain en action (sailing_boat) | 1 | 0.00040 | 0.0004 | 0.066 |
| Solo personnage ou créature | 4 | 0.00150 | **0.0019** | 0.118 |
| Solo objet historique | 1 | 0.00070 | 0.0007 | 0.146 |
| Solo objet en vol OU au sol | 1 | 0.00040 | 0.0004 | 0.040 |
| Solo objet ou humain en scaphandre | 1 | 0.00100 | 0.0010 | 0.117 |
| Variable | 1 | 0.00100 | 0.0010 | 0.097 |
| Variable (solo objet ou frise) | 1 | 0.00090 | 0.0009 | 0.099 |

**color_ratio max global : 0.0019** (knight_in_shining_armor) — dix fois plus bas que le seuil d'attention `0.05`. Aucune image n'a déclenché de flag `strong_color` ou `noticeable_color`.

## Points d'attention

### 1. Aucun outlier `color_ratio > 0.05`
Le négatif v3 du `PromptGenerator` (`"no colors, extra legs, third leg, ..., no fill colors, ..., only black stroke"`) est manifestement efficace : 27/27 entrées sous `0.002`. À comparer avec les 192/204 sujets sans négatif du benchmark `poc-taxonomy-subjects` qui montaient régulièrement à `color_ratio` 0.3–0.5 sur des sujets colorés (red_airplane, rainbow_garden). **Confirmation forte de l'apport du négatif v3 unifié**.

### 2. Mismatch classification `workflow_class` ↔ classe sémantique demandée
Plusieurs leaves ont une `workflow_class` cartographiée qui surprend par rapport à la classe sémantique de la liste utilisateur :

| leaf_id | classe demandée (liste user) | workflow_class (cartographie) |
|---|---|---|
| sea_turtle_swimming | Solo animal — mammifères | **Solo fish** |
| nowruz_goldfish_in_bowl | Solo fish / marine | **Variable** |
| sailing_boat | Solo objet véhicule | **Solo humain en action** |
| medieval_castle_with_moat | Solo objet | **Solo personnage ou créature** |
| birthday_cake_with_candles | Solo objet | **Variable (solo objet ou frise)** |

Ces classifications proviennent de `taxonomy_production_cartography.json`. À investiguer si certaines sont des erreurs à corriger côté cartographie (ex. `medieval_castle_with_moat` étiqueté "Solo personnage ou créature" semble incorrect).

### 3. Confidence "Moyenne" sur les 2 oiseaux
`soaring_eagle` et `peacock_with_open_tail` portent le seul tag `confidence: Moyenne` du run. Leurs sorties méritent une revue visuelle prioritaire — la cartographie signale un risque de ratage anatomie / ailes / queue.

### 4. Résolutions hétérogènes selon `workflow_class`
Le `PromptGenerator` choisit la résolution selon la classe :
- 1024² (carré) : animaux, insectes, poissons, oiseaux, baker, doctor, ballet, locomotive, cake, guitar
- 848×1264 (portrait) : humains pose active/personnage (firefighter, princess, knight, wizard, astronaut, castle)
- 1376×768 (paysage) : véhicule + objet en vol (sailing_boat, hot_air_balloon)

Cela implique que toute comparaison entre images doit tenir compte du format. Le compare-grid devra normaliser ou afficher les ratios.

### 5. Latences ultra-stables (≈ 18.2s)
Toutes les générations 1024² + 848×1264 tournent à **18.1–18.4s**, sauf `pet_turtle` à 20.2s (probablement variance ComfyUI sans cause structurelle). Les 1376×768 (paysage 1.06 Mpx) restent à 18.2s. Pas de surcoût notable malgré format non-carré.

### 6. 3 IDs introuvables — prochaine itération de la liste
- `honeybee_on_flower` : taxonomie ne couvre pas l'abeille en solo (à ajouter à `coloring_taxonomy_full.json` ou substituer par `monarch_butterfly` / `garden_spider`).
- `pirate_ship_captain` : seul `pirate_ship` existe. À ajouter ou remplacer par `pirate_ship`.
- `vintage_car_convertible` : `vintage_car_1920s` est la variante existante.

## Décision / Action suivante

✅ **POC validé** : qualité histogram constante très propre, génération stable, négatif v3 efficace.

**Prochaine étape (humain)** : annotation visuelle des 27 images via l'annotateur — score 1-10, défauts, pills "prompt vague / surchargé / hors catégorie / tronqué / déséquilibré / etc." — pour décider si un prompt est publiable tel quel ou s'il faut un v2 du template.

**URL annotateur** : `http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-generator-benchmark`

L'annotateur affichera automatiquement :
- Titre `name_en` + ℹ️ tooltip (positive prompt ERNIE + négatif v3)
- Badges `workflow_class` / `confidence` / `pipeline` (via mod récente du résolveur backend)
- Overlay métriques `color=… | ink=… | vision=…` bas-gauche image
- Score 1-10, défauts (incl. `prompt_incohérent` qui force `publishable=false`), pills structurées

## Annexes

- **Script** : `scripts/poc_generator_benchmark.py`
- **Module** : `src/services/prompt_generator.py`
- **Données** : `data/prompt_generator/{coloring_taxonomy_full,taxonomy_production_cartography,coloring_taxonomy_seo}.json`
- **Output images** : `docs/reports/poc-generator-benchmark/*.png` (27 fichiers)
- **Index brut** : `docs/reports/poc-generator-benchmark/poc-generator-benchmark.json`
- **Annotateur** : `data/benchmark-annotator.html`
- **API router** : `src/api/routes/benchmark.py` (ajout `_extract_extra_meta` pour les badges étendus)
