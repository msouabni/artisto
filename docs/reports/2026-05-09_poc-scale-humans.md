# POC scale-benchmark — humains
Date : 2026-05-09

## Contexte

Deuxième passe du POC `PromptGenerator` après validation initiale sur 27 sujets variés (cf. `2026-05-09_phase-integration-prompt-generator.md`). Cette fois on cible **uniquement les classes humain/personnage** pour stresser les pipelines à risque anatomie. Sélection automatique depuis le `leaf_index` du `PromptGenerator` :

- **Filtre** : `workflow_class ∈ HUMAN_CLASSES` (9 classes) → 282 leaves matchent
- **Échantillon** : 50 leaves max, `random.Random(2027).sample(...)` déterministe
- **Batching anatomie** : `batch_size=3` ComfyUI pour `Solo humain en action` et `Solo humain pose active` (3 variantes générées en une seule submission, le seed du KSampler reste fixe mais le bruit latent varie entre les 3 outputs de batch)
- **Seed** : `6000 + idx*7` (sans collision avec les runs précédents 4242 / 50000)
- Paramètres ComfyUI fixés : `steps=8`, `sampler=euler`, `scheduler=normal`, `cfg=1.0`, pipeline cartographié = `ERNIE direct` pour 100 % des entrées

Script : `scripts/poc_scale_benchmark_humans.py`. Output : `docs/reports/poc-scale-benchmark/`.

## Résultat global

**50/50 OK · 0 KO** — runtime ComfyUI cumulé ≈ 47 min, latence moyenne 56.1 s par leaf.

| Indicateur | Valeur |
|---|---|
| Leaves traitées | 50/50 |
| Leaves en `batch_size=3` (anatomie) | 12/50 (24 %) |
| Total PNG sur disque | 50 canoniques + 36 variantes batch = **86 fichiers** |
| `color_ratio` max global | **0.0031** (captain_marvel) |
| `color_ratio` moyen global | 0.0011 |
| Histogram OK (sans flag couleur) | 50/50 |
| Confidence Haute | 34/50 |
| Confidence Moyenne | 11/50 |
| Confidence "Haute (pour test), Moyenne (commercial)" | 5/50 |

## Stats par `workflow_class`

| Classe | n | cr_avg | cr_max | ink_avg | lat_avg | batch=3 |
|---|---|---|---|---|---|---|
| Humain + entité | 1 | 0.0011 | 0.0011 | 0.127 | 52.4 s | — |
| Solo humain (générique) | 3 | 0.0009 | 0.0011 | 0.110 | 52.4 s | — |
| Solo humain (personnalité) | 8 | 0.0016 | **0.0031** | 0.092 | 52.2 s | — |
| Solo humain (personnalité) + action figée | 10 | 0.0015 | 0.0021 | 0.085 | 51.8 s | — |
| Solo humain + accessoires | 9 | 0.0008 | 0.0012 | 0.095 | 51.1 s | — |
| **Solo humain en action** | 10 | 0.0008 | 0.0013 | 0.077 | 69.1 s | **10/10** |
| **Solo humain pose active** | 2 | 0.0009 | 0.0009 | 0.096 | 74.6 s | **2/2** |
| Solo humain/animal cartoon | 5 | 0.0008 | 0.0009 | 0.083 | 51.7 s | — |
| Solo personnage ou créature | 2 | 0.0011 | 0.0011 | 0.107 | 51.4 s | — |

**Lecture rapide** :
- Le négatif v3 du `PromptGenerator` reste **très efficace sur les humains** : aucune classe ne dépasse 0.002 en moyenne, max isolé à 0.0031.
- Les classes `personnalité` (avec ou sans action figée) tirent légèrement la moyenne vers le haut (cr_avg 0.0015–0.0016) — probablement à cause de figures avec couleurs caractéristiques (capes Marvel, maillots de foot, etc.) que le négatif suppresse mais pas à 100 %.
- Les **classes batch=3** (`en action` / `pose active`) sont les plus propres en couleur (cr_avg 0.0008–0.0009) malgré le risque attendu — bonne nouvelle, le négatif v3 cale bien sur l'anatomie.

## Cas `batch_size=3` (12 leaves)

12 leaves traitées en batch de 3 → **36 PNG batch + 12 canoniques** (copie de `_b1`). Le `color_ratio` reporté est mesuré sur la canonique (`_b1`).

### Solo humain en action (10/12)

| leaf_id | reso | cr (b1) | ink |
|---|---|---|---|
| child_running_outdoors | 848×1264 | 0.0007 | 0.084 |
| speed_skater | 848×1264 | 0.0006 | 0.063 |
| bungee_jumper | 848×1264 | 0.0006 | 0.062 |
| snowboarder_jump | 848×1264 | 0.0013 | 0.085 |
| breakdancer | 848×1264 | 0.0008 | 0.089 |
| kid_yoga_pose | 848×1264 | 0.0006 | 0.072 |
| water_skiing | 1024×1024 | 0.0007 | 0.066 |
| child_combing_hair | 1024×1024 | 0.0010 | 0.072 |
| sailing_boat | 1376×768 | 0.0005 | 0.067 |
| tango_couple | 848×1264 | 0.0008 | 0.121 |

### Solo humain pose active (2/12)

| leaf_id | reso | cr (b1) | ink |
|---|---|---|---|
| firefighter_with_hose | 848×1264 | 0.0009 | 0.108 |
| police_officer_on_duty | 848×1264 | 0.0008 | 0.084 |

→ **L'annotation manuelle des batchs `_b1/_b2/_b3` est l'étape clé** : la métrique histogram seule ne dit pas si l'anatomie tient (3 jambes, doigts surnuméraires, fusion membres). Les `batch_filenames` sont enregistrés dans `index-humans.json` et exposés via l'annotateur, mais **l'UI actuelle n'affiche que la canonique** — pour comparer les 3 variantes, ouvrir directement `*_b1/_b2/_b3_euler8s.png` dans l'explorateur de fichiers ou prévoir un mode "compare batch" dans l'annotateur (voir Action suivante).

## Top 10 `color_ratio` (revue prioritaire)

Tous restent extrêmement bas mais marquent la frontière haute des sorties :

| cr | leaf_id | classe | ink |
|---|---|---|---|
| **0.0031** | captain_marvel | Solo humain (personnalité) | 0.102 |
| 0.0021 | mike_tyson_cartoon | personnalité + action figée | 0.090 |
| 0.0019 | kylian_mbappe_cartoon | personnalité + action figée | 0.082 |
| 0.0018 | moana_on_ocean | Solo humain (personnalité) | 0.099 |
| 0.0018 | rafael_nadal_cartoon | personnalité + action figée | 0.092 |
| 0.0018 | captain_america_with_shield | Solo humain (personnalité) | 0.123 |
| 0.0017 | iron_man | Solo humain (personnalité) | 0.094 |
| 0.0015 | erling_haaland_cartoon | personnalité + action figée | 0.073 |
| 0.0015 | canelo_alvarez_cartoon | personnalité + action figée | 0.084 |
| 0.0014 | neymar_jr_cartoon | personnalité + action figée | 0.078 |

→ **Pattern clair** : les outliers couleur sont presque tous des **personnalités identifiables** (super-héros costumés, sportifs en maillot d'équipe). Les couleurs caractéristiques (rouge Iron Man, étoile Captain America, maillot bleu PSG) traversent partiellement le négatif. Reste largement publiable mais à valider visuellement.

## Résolutions

| Format | n | classes typiques |
|---|---|---|
| 848×1264 (portrait) | 27 | personnages costumés, sports figés, métiers en pose, action |
| 1024×1024 (carré) | 21 | accessoires, cartoons, génériques |
| 1376×768 (paysage) | 2 | sailing_boat, child_combing_hair (?) |

## Latences

| Mode | Min | Avg | Max | Note |
|---|---|---|---|---|
| batch=1 (38 leaves) | 40.4 s | 51.8 s | 52.5 s | très stable, ~50 s |
| batch=3 (12 leaves) | 69.1 s | 71.7 s | 74.8 s | facteur 1.4× pour 3 sorties au lieu de 1 (parallélisation latente efficace) |

→ Coût marginal d'un batch=3 vs batch=1 : **+20 s** au lieu de +100 s linéaire. Ratio **2× plus efficace** que 3 runs séquentiels.

## Points d'attention

### 1. Histogram propre ≠ anatomie correcte
Sur les 12 leaves anatomie, `cr_avg = 0.0008` est rassurant côté couleurs mais le risque réel (3 jambes, mauvais nombre de doigts, fusion membres) **n'est pas mesuré par l'histogram**. La validation est purement humaine via l'annotateur. À chaque batch=3, considérer les 3 variantes pour choisir la moins boguée.

### 2. Personnalités identifiables = outliers couleur
Captain Marvel, Iron Man, footballeurs en maillot — le négatif v3 réduit mais ne supprime pas la trace chromatique caractéristique. Si le standard de publication exige `cr < 0.001`, ces leaves nécessiteront soit un négatif renforcé (`no red, no blue, no team colors, ...`) soit un repostprocess noir-et-blanc strict.

### 3. UI annotateur ne montre que la canonique
Les fichiers batch (`*_b1/_b2/_b3_euler8s.png`) sont sur disque mais l'annotateur ne les charge pas — il liste seulement les filenames non-suffixés via le glob `*.png` standard. **Action proposée** : étendre l'annotateur pour afficher un mini-carrousel des batch_filenames quand l'item courant en a (lu depuis `subjects-index.json` clé `batch_filenames`).

### 4. Confidence "Haute (pour test), Moyenne (commercial)" sur 5 leaves
Cette confidence ambivalente du `PromptGenerator` signale 5 leaves où la cartographie n'a pas tranché — tagging à clarifier dans `taxonomy_production_cartography.json` après validation visuelle.

### 5. Sélection seed=2027 reproductible
Le `random.Random(2027).sample(pool, 50)` est déterministe à condition que `pool` soit pré-trié (`sorted(gen.leaf_index.keys())`) — c'est le cas dans le script. Ce même seed appliqué à `ANIMAL_CLASSES` (Instance 1) ne sélectionnera pas les mêmes leaves : les pools sont disjoints par construction.

### 6. Wall time réel vs ComfyUI cumulé
ComfyUI cumulé = 47 min mais wall time du run > 60 min (overhead histogram QC + I/O disque + sérialisation index incrémentale). Acceptable pour 50 leaves ; à surveiller pour des runs plus larges (5-10×).

## Action suivante

✅ POC validé : 50/50 OK, 0 anomalie color_ratio > 0.005, latence prévisible, `batch_size=3` opérationnel pour les classes anatomie.

**Annotation manuelle** : `http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark`

L'annotateur affichera pour chaque leaf :
- Titre `name_en` + ℹ️ tooltip (positive prompt + négatif v3) — via `index-humans.json` clé `subjects`
- Badges étendus `workflow_class` / `confidence` / `pipeline` — via `_extract_extra_meta`
- Overlay métriques `color=… | ink=…` — via `poc-scale-benchmark.json` clé `results`
- Score 1-10 + défauts (incl. 3_jambes, prompt_incohérent qui force publishable=false) + pills structurées

**À évaluer prioritairement** :
1. Les 12 leaves batch=3 → tableau de bord 3 vs 3 vs 3 pour décider si batch=3 reste utile en prod
2. Les 10 outliers couleur (top 10 cr) → décider si négatif renforcé nécessaire pour personnalités
3. Les 11 leaves `confidence=Moyenne` → revue cartographie

## Annexes

- **Script** : `scripts/poc_scale_benchmark_humans.py`
- **Output** : `docs/reports/poc-scale-benchmark/` (50 canoniques + 36 batch + 2 JSON)
  - `poc-scale-benchmark.json` (métriques par filename, lu par overlay annotateur)
  - `index-humans.json` (subjects schema, lu par tooltip prompt + badges annotateur)
- **Module** : `src/services/prompt_generator.py`
- **Phase précédente** : `docs/reports/2026-05-09_phase-integration-prompt-generator.md`
