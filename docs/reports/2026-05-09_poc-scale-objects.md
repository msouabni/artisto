# POC — Scale benchmark objects (50 feuilles)
Date : 2026-05-09

## Contexte

Premier passage à l'échelle du `PromptGenerator` sur les classes "objet"
au sens large (objets manufacturés, véhicules, objets historiques,
patterns "lettre + objet", composition variable). Objectif : valider
qu'au-delà des 8 cibles soigneusement choisies de `poc-generator-benchmark`
(2026-05-09 plus tôt dans la journée), les templates `Solo objet` /
`Lettre + objet` / `Variable` tiennent la route en aveugle sur 50
feuilles tirées au sort.

**Script** : `scripts/poc_scale_benchmark_objects.py` (créé ici).
**Output** : `docs/reports/poc-scale-benchmark/`
(50 PNG + `index-objects.json`).

Pipeline reprend strictement les défauts prod (steps=8, sampler=euler,
scheduler=normal, cfg=1.0, ERNIE-Image-Turbo Q8) — seuls les paramètres
fournis par `PromptGenerator` (positive, negative, resolution) varient.

### Sélection

- Classes ciblées (10 classes spécifiées) :
  `Solo objet` · `Solo objet véhicule` · `Solo objet historique` ·
  `Solo objet en vol OU au sol` · `Mandala` · `Éducatif` · `Lettre + objet` ·
  `Variable` · `Variable (solo objet ou frise)` · `Solo objet (véhicule)`.
- 6 classes / 10 ont effectivement des feuilles dans la cartographie.
  Les 4 autres (`Solo objet véhicule` sans parenthèses, `Mandala`,
  `Éducatif`, `Variable (solo objet ou frise)`) n'existent pas comme
  intitulé exact — voir Points d'attention.
- Univers candidat : **283 feuilles**.
- Échantillon aléatoire **n = 50**, `random.seed(2028)` (Python `random.Random.sample`).
- Seed ComfyUI par image : `7000 + idx*7` (idx = 0..49 dans l'ordre
  alphabétique du leaf_id après échantillonnage).

## Résultats

### Statut global

| Métrique | Valeur |
|---|---|
| Demandé | 50 |
| `status: ok` | **50** |
| `status: skip_unknown_leaf` | 0 |
| `status: comfy_error` / `build_prompt_error` | 0 |
| `histogram_ok = true` (color_ratio + ink_ratio dans la zone normale) | **50 / 50** |
| Flags QC technique levés | **0** sur l'ensemble |
| Latence ComfyUI cumulée | 2 802 s (≈ 47 min) |
| Latence p50 / min / max | 52.4 s / 36.5 s / 74.8 s |
| Résolutions | 1024×1024 (49) · 1376×768 (1, `fighter_jet`) |

Latence ≈ 2.5× plus élevée que `poc-generator-benchmark` (≈ 20 s/image)
parce que ComfyUI était partagé pendant tout le run avec deux autres
benchmarks parallèles (`index-humans.json`, `index-nature.json`
apparaissent dans le même dossier). C'est un effet de file d'attente,
pas un changement intrinsèque.

### Stats par classe

| Classe | N | avg latence | avg color_ratio | avg ink_ratio | flags QC |
|---|---:|---:|---:|---:|---:|
| Solo objet | **26** | 55.5 s | 0.0008 | 0.086 | 0 |
| Lettre + objet | **7** | 58.2 s | 0.0007 | 0.098 | 0 |
| Solo objet (véhicule) | **7** | 55.0 s | 0.0010 | 0.104 | 0 |
| Variable | **6** | 55.5 s | 0.0011 | 0.098 | 0 |
| Solo objet historique | **3** | 61.2 s | 0.0011 | **0.136** | 0 |
| Solo objet en vol OU au sol | **1** | 50.4 s | 0.0007 | 0.073 | 0 |
| Mandala | 0 | — | — | — | — |
| Éducatif | 0 | — | — | — | — |

`color_ratio` reste sous 0.002 partout — la consigne `STYLE_BLOCK + no
fill / no shading` du PromptGenerator est respectée par ERNIE en série.
Aucune sortie ne déclenche `strong_color` ni `noticeable_color` : le QC
technique automatique est *silent across the board*.

`ink_ratio` plus haut sur `Solo objet historique` (0.136 vs ~0.085 en
moyenne) — densité visuelle élevée sur les 3 sujets (`ancient_water_wheel`,
`first_steam_engine_train`, `wright_brothers_first_plane`), ce qui est
cohérent avec leur niveau de détail mécanique.

### Liste des feuilles générées (par classe)

#### Solo objet (26)

`air_fryer`, `carpet_cleaner`, `claw_hammer`, `e_book_reader`, `fireplace`,
`flat_screen_tv`, `hand_plane`, `industrial_3d_printer`, `industrial_press`,
`kitchen_oven`, `ladle_spoon`, `latkes_potato_pancakes`, `masking_tape_roll`,
`old_steam_train`, `smart_thermostat`, `smartwatch`, `solar_panel_on_roof`,
`spirit_level`, `steam_mop`, `thread_spool`, `vr_headset`, `watering_can`,
`weighing_scale`, `wifi_router`, `wood_chisel`, `wooden_cutting_board`.

#### Lettre + objet (7)

`letter_a_with_apple`, `letter_d_with_dog`, `letter_u_with_ufo`,
`letter_u_with_umbrella`, `letter_w_with_whale`, `letter_x_with_xylo`,
`letter_z_with_zebre`.

#### Solo objet (véhicule) (7)

`city_car`, `coast_guard_boat`, `double_decker_bus`, `manure_spreader`,
`police_car`, `subway_train`, `suv_off_road`.

#### Variable (6)

`crescent_moon_and_star`, `eid_al_adha_sheep`, `eid_al_fitr_celebration`,
`family_at_iftar_table`, `live_stream_setup`, `new_year_resolutions_list`.

#### Solo objet historique (3)

`ancient_water_wheel`, `first_steam_engine_train`, `wright_brothers_first_plane`.

#### Solo objet en vol OU au sol (1)

`fighter_jet` (résolution 1376×768).

## Points d'attention

### Mandala — **0 image générée**

L'ensemble `OBJECT_CLASSES` listait `"Mandala"` comme classe cible. Cette
classe **n'existe pas** comme intitulé exact dans
`data/prompt_generator/taxonomy_production_cartography.json` (vérifié
empiriquement : `python … cart classes` retourne 0 sous-catégorie nommée
`Mandala`). Conséquence : le tirage n'a sélectionné aucune feuille
mandala et la question "le style mandala est-il cohérent en série ?"
**ne peut pas être tranchée par ce run**.

Hypothèses :
1. Les feuilles mandala sont rangées sous `Pattern décoratif` /
   `Pattern décoratif (symétrie volontaire)` / `Pattern décoratif simple`
   (qui existent en cartographie). Ces classes ne sont pas dans
   `OBJECT_CLASSES` — il faudrait soit les ajouter, soit créer une
   classe `Mandala` distincte si on veut un template dédié (symétrie
   radiale, motifs concentriques, complexité géométrique).
2. Le concept "mandala" n'est peut-être pas modélisé du tout dans la
   taxonomie actuelle.

À arbitrer côté taxonomie/cartographie *avant* d'inclure `Mandala` dans
un futur scale-benchmark. En l'état, le ticket `mandala (style cohérent ?)`
n'est ni validé ni invalidé — il n'a pas eu de matière à tester.

### Éducatif — **0 image générée par cette classe, 7 par proxy "Lettre + objet"**

Même situation : la classe `Éducatif` n'existe pas dans la cartographie.
Le rapprochement le plus proche est `Lettre + objet` (52 feuilles
candidates → 7 sélectionnées dans l'échantillon).

Sur les 7 sorties Lettre + objet, le template utilisé est
`template_solo_object` (le dispatcher de `prompt_generator.py` mappe
`"Lettre + objet"` → `template_solo_object`). Le template ne
contient **aucune instruction explicite sur le rendu de la lettre**
(forme typographique, taille, alignement avec l'objet) — le prompt est
simplement `"one letter_a_with_apple centered on the page, …"`.

Conséquences à valider en annotation humaine
(`http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark`) :

1. **Lisibilité des lettres** : ERNIE rend-il une lettre "A" reconnaissable
   ou un magma graphique ? Le template ne lui dit pas de la dessiner en
   capitales bold — le modèle improvise.
2. **Présence effective de la lettre dans l'image** : la lettre est-elle
   *vraiment* tracée, ou seulement l'objet associé (apple, dog, ufo) ?
3. **Hiérarchie lettre / objet** : la lettre est-elle dominante (page
   éducative) ou secondaire (objet centré, lettre comme garniture) ?
4. **Hétérogénéité par lettre** : `letter_u_with_ufo` vs
   `letter_u_with_umbrella` — même lettre, deux objets — la lettre
   "U" est-elle dessinée de façon cohérente, ou ERNIE adapte-t-il le
   style à l'objet associé ?

Si l'annotation montre que la lettre est mal rendue ou absente, il faut
soit :
- Ajouter un `template_letter_object` dédié (pattern ABC : lettre
  capitale dominante en haut/gauche, objet illustratif à droite/en
  dessous), avec énumération anti-distortion de la lettre.
- Ou enrichir la stratégie côté cartographie (`Lettre + objet`) avec
  `negative_extra` ciblé (ex. "no decorative letter, no script font").

Aucun signal automatique ne couvre ce cas — `histogram_ok = true` sur
les 7 sorties n'a pas la résolution sémantique pour juger une lettre.

### Latence partagée

Le run a tourné **en parallèle** d'au moins deux autres benchmarks visant
le même dossier `docs/reports/poc-scale-benchmark/` (`index-humans.json`,
`index-nature.json` ainsi que `poc-scale-benchmark.json` ont été créés
indépendamment pendant l'exécution). ComfyUI étant sequentiel, la
latence p50 mesurée (52 s) ne reflète pas le temps "intrinsèque" d'une
génération PromptGenerator+ERNIE sur ce hardware. Pour une mesure
propre, refaire le run seul ; la valeur de référence reste celle de
`poc-generator-benchmark` (~20 s/image).

### Convention d'index : `index-objects.json` vs `<dir>/<dir>.json`

Le fichier d'index produit s'appelle `index-objects.json` (préfixe
`index-` pour permettre `index-humans.json`, `index-nature.json` côte à
côte dans le même dossier). Le code de l'annotateur
(`src/api/routes/benchmark.py`) cherche en priorité `<dir>/<dir>.json`
pour les métriques et applique des globs `poc-*.json` / `*-index.json`
/ `index.json` pour le prompt-index. **`index-objects.json` ne matche
aucun de ces globs**, donc l'annotateur via
`http://…/data/benchmark-annotator.html?dir=poc-scale-benchmark` ne
verra ni les métriques ni les prompts pour le moment.

Solutions possibles (hors-périmètre de ce run, à arbitrer) :
- Étendre `_PROMPT_INDEX_GLOBS` à `("poc-*.json", "*-index.json",
  "index.json", "index-*.json")` dans `src/api/routes/benchmark.py`.
- Ou renommer en `index-objects-index.json` (matche `*-index.json`).
- Ou produire en plus un `poc-scale-benchmark.json` agrégé si le
  besoin est de présenter les 3 axes (objects/humans/nature) dans une
  seule vue annotateur.

### Échantillon non stratifié par classe

`random.sample(283, 50)` donne 26 / 7 / 7 / 6 / 3 / 1 (proportionnel à
l'univers : 149 / 52 / 37 / 28 / 8 / 9). Les classes minoritaires
(`historique` n=3, `en vol OU au sol` n=1) sont sous-représentées et
toute conclusion les concernant sera fragile statistiquement. À
arbitrer si on veut un échantillonnage stratifié (ex. min 5 par classe
non-vide).

## Décision / Action suivante

**Action 1 (utilisateur) :** annoter les 50 images via
`http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark`
**après** avoir résolu le problème d'index ci-dessus (sans quoi
l'annotateur ne chargera pas les prompts). En attendant, l'inspection
visuelle directe des PNG dans `docs/reports/poc-scale-benchmark/` reste
possible.

**Action 2 (taxonomie) :** trancher la question Mandala — soit ajouter
des feuilles dont la cartographie pointe vers une classe `Mandala` (et
créer le template dédié), soit considérer que les patterns décoratifs
existants (`Pattern décoratif…`) couvrent le besoin et reformuler la
question initiale du ticket. **Pas relançable tant que la taxonomie
n'a pas été ajustée.**

**Action 3 (éducatif) :** observation visuelle ciblée des 7 sorties
`letter_*` pour décider si `template_solo_object` suffit ou s'il faut
un `template_letter_object` dédié. Critère : >=4/7 lettres lisibles et
dominantes → garder le template actuel ; <4/7 → ajouter un template
spécialisé dans le sprint suivant.

**Action 4 (annotateur) :** étendre `_PROMPT_INDEX_GLOBS` à
`index-*.json` côté `src/api/routes/benchmark.py` (1 ligne), pour que
les 3 index `index-objects/humans/nature.json` soient lus
indépendamment selon le dossier sélectionné — à coupler à un mécanisme
de switch quand un dossier en porte plusieurs.

**Tournants à anticiper :** si l'annotation humaine valide ≥80 % des 50
images comme publiables sans retouche, on a une base solide pour
généraliser le PromptGenerator à toute la classe `Solo objet` (149
feuilles) en production de masse. Sinon, isoler les défauts les plus
fréquents et ajuster les templates.
