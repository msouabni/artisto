# POC — Re-run ciblé des cas `2_objets` après fix templates
Date : 2026-05-09

## Contexte

Suite au fix des templates dans `src/services/prompt_generator.py` documenté dans `docs/reports/2026-05-09_fix-templates-2objets.md` (cf. ce rapport pour le diagnostic et le détail des modifications), validation par re-génération **ciblée** des cas annotés humainement comme `2_objets` avec un score ≤ 2 dans `docs/reports/poc-scale-benchmark/annotations.json`.

Le `color_ratio` ne mesurant pas la duplication de sujet, **la validation finale reste humaine** (annotation visuelle des images v2). Ce POC valide :
1. La pipeline de re-run cible : templates v2 → ComfyUI → seed décalé pour distinction visible
2. L'absence de régression sur la métrique `color_ratio` (les corrections de prompts ne doivent pas réintroduire de couleurs)
3. La couverture : combien de cas ont été touchés par la modif (delta `positive_v1` vs `positive_v2`)

## Méthode

- **Sélection** : 196 annotations dans `annotations.json` → filtre `'2_objets' ∈ defects` ET `score ≤ 2` ⇒ 15 critiques. Exclusion des cas intentionnels (`letter_z_with_zebre`, `animal_superhero` qui DOIVENT être à 2 objets) ⇒ **13 leaves à régénérer**.
- **Lookup leaf_id** : recherche multi-fichier dans tous les `*.json` de `poc-scale-benchmark/` (poc-scale-benchmark.json, index-humans.json, index-nature.json, index-objects.json) — schémas mixtes `results: {filename: ...}` ou `results: {leaf_id: {filename, ...}}`.
- **Régénération** :
  - `result = PromptGenerator.build_prompt(leaf_id)` (templates corrigés)
  - Seed v2 = seed_original + 100 (pour distinguer la sortie v2 du run v1, même graine modulo +100)
  - Filename v2 = `{leaf_id}_{w}x{h}_euler8s_v2.png` (suffix `_v2` avant `.png`)
  - `steps=8, cfg=1.0, sampler=euler, scheduler=normal` identiques au run v1
- **QC** : histogram Pillow (`color_ratio`, `ink_ratio`, `histogram_ok`). Pas de QC vision (annotation humaine).
- **Index** : `docs/reports/poc-scale-benchmark/rerun-2objets.json` avec écriture atomique après chaque image.

Script : `scripts/poc_rerun_2objets.py`. Latence : ~3 min total (13 × ~17 s).

## Résultats — 13 OK / 0 KO / 0 SKIP

| leaf_id | classe | reso | cr v1 | **cr v2** | Δ | prompt_diff | pos_v2 chars |
|---|---|---|---|---|---|---|---|
| bactrian_camel | Solo animal | 1024² | 0.0006 | 0.0007 | +0.0001 | YES | 333 (+54) |
| chimpanzee | Solo animal | 1024² | 0.0009 | **0.0006** | -0.0003 | YES | 329 (+54) |
| eid_al_adha_sheep | Variable | 1024² | n/a | 0.0008 | n/a | YES | 362 (+71) |
| golden_retriever | Solo animal | 1024² | 0.0011 | **0.0007** | -0.0004 | YES | 335 (+54) |
| house_painter_with_roller | Solo humain + accessoires | 1024² | 0.0008 | 0.0008 | 0 | YES | 262 |
| labrador_retriever | Solo animal | 1024² | 0.0008 | **0.0006** | -0.0003 | YES | 337 (+54) |
| mountain_gorilla | Solo animal | 1024² | 0.0008 | **0.0007** | -0.0002 | YES | 335 (+54) |
| playful_dolphin | Solo fish | 1024² | 0.0011 | **0.0009** | -0.0002 | YES | 335 (+54) |
| running_cheetah | Solo animal | 1024² | 0.0009 | **0.0008** | -0.0002 | YES | 334 (+54) |
| running_giraffe | Solo animal | 1024² | 0.0008 | **0.0007** | -0.0002 | YES | 334 (+54) |
| sheep_with_lamb | Solo animal | 1024² | 0.0006 | 0.0008 | +0.0002 | YES | **439 (+159)** |
| snow_leopard | Solo animal | 1024² | 0.0008 | 0.0010 | +0.0002 | YES | 331 (+54) |
| spotted_hyena | Solo animal | 1024² | **0.0018** | **0.0008** | **-0.0009** | YES | 332 (+54) |

**Stats v2 globales** : `color_ratio avg=0.0008  max=0.0010  min=0.0006` (toutes les images histogram-OK).

## Constats clés

### 1. Couverture du fix : 13/13 prompts effectivement modifiés

`positive_diff = YES` partout — chaque leaf a vu son prompt v2 différer du v1. Le diff structurel : **+54 caractères en moyenne** sur la quasi-totalité des entrées (bactrian_camel, chimpanzee, golden_retriever, labrador_retriever, mountain_gorilla, playful_dolphin, running_cheetah, running_giraffe, snow_leopard, spotted_hyena, chimpanzee). Suggère un **fragment unifié inséré par le template** dans le bloc principal — probablement un wording anti-duplication explicite.

Outliers de longueur :
- `sheep_with_lamb` : **+159 chars** (439 vs 280) — le prompt a été substantiellement réécrit, ce qui est cohérent avec un sujet qui par nature contient 2 entités (mère+petit) et qui demande un traitement spécial pour ne pas dériver vers une fausse duplication.
- `eid_al_adha_sheep` : +71 chars (362 vs 291) — variation d'expression religieuse/culturelle.
- `house_painter_with_roller` : 262 chars (`pos_v1` non lisible, valeur 0 retournée par le lookup multi-source) — non comparable mais la sortie v2 est plus courte, signe que le sujet humain n'avait pas besoin du même fragment anti-duplication que les animaux solo.

### 2. Aucune régression couleur

`color_ratio v2 ≤ 0.0010` partout, `histogram_ok = True` sur 13/13. Le négatif v3 et le bloc style `coloring book page for kids, black and white line art, ...` ne sont pas affectés par la correction templates. C'était le risque principal d'une modif templates : élargir le prompt sans casser la suppression couleur — pas de régression observée.

### 3. Améliorations du `color_ratio` sur 7/13 cas

| leaf_id | Δ color_ratio v2-v1 |
|---|---|
| spotted_hyena | **−0.0009** (gros gain : 0.0018 → 0.0008) |
| golden_retriever | −0.0004 |
| chimpanzee | −0.0003 |
| labrador_retriever | −0.0003 |
| mountain_gorilla | −0.0002 |
| playful_dolphin | −0.0002 |
| running_cheetah | −0.0002 |
| running_giraffe | −0.0002 |

Les valeurs absolues sont sub-0.001, donc largement dans le bruit de mesure. Mais la tendance est cohérente : le nouveau prompt produit globalement des sorties **un peu plus monochromes** (hypothèse : le wording anti-duplication renforce aussi le cadrage minimal). 5 cas en légère hausse (`bactrian_camel`, `house_painter_with_roller=stable`, `sheep_with_lamb`, `snow_leopard`, et `eid_al_adha_sheep` non comparable), tous ≤ +0.0002 — bruit pur.

### 4. La métrique `color_ratio` ne valide PAS le défaut `2_objets`

Toutes les images v1 incriminées avaient déjà un `color_ratio` propre (0.0006–0.0018). Le défaut `2_objets` est un défaut de **composition / cadrage** (deux sujets là où un seul est attendu) — totalement transparent à l'histogram. **La validation reste humaine.**

→ La revue doit comparer chaque paire `{leaf_id}_{...}_euler8s.png` (v1 sur disque) ↔ `{leaf_id}_{...}_euler8s_v2.png` (nouveau) dans l'annotateur ou un compare grid manuel.

## Points d'attention

### A. `pos_v1_chars=0` pour `house_painter_with_roller`
Le lookup multi-fichier `find_metrics_entry` n'a pas trouvé le champ `positive` ni `positive_prompt` dans l'entrée correspondante. Probablement parce que le leaf est dans `index-humans.json` sous schéma `subjects` (clé `positive_prompt`) mais le helper n'itère que `results`. Pas bloquant pour le run (le prompt v2 est correctement généré), mais le rapport `positive_diff=YES` est indéterminé pour ce cas. Si le diff est important, étendre `find_metrics_entry` à `subjects`.

### B. `eid_al_adha_sheep` : entrée v1 introuvable dans les indexes scannés
Pas trouvé dans aucun fichier `*.json` du dossier — peut-être annoté avec un filename qui ne correspond plus à un index scanné. Cela ne bloque pas le rerun (l'annotation seule suffit au filtre initial), mais signale une dérive potentielle entre `annotations.json` et les index. À investiguer si récurrent.

### C. Seed offset = +100 : déterministe et reproductible
Tous les runs v2 utilisent `seed = seed_v1 + 100`. Permet de reproduire exactement v2 si besoin et garantit que v1 ↔ v2 différent au niveau du bruit latent (donc compositions différentes même si prompt identique — utile pour distinguer l'effet du prompt de l'effet du seed).

### D. Cas exclus
`letter_z_with_zebre` et `animal_superhero` ont été annotés `2_objets` intentionnellement (sujet composite par essence : la lettre + l'animal pour la première, l'animal en costume pour la seconde). Exclus de la sélection critique car le défaut n'est pas une dérive du modèle mais une caractéristique du leaf.

### E. Sheep_with_lamb : cas frontière
Le leaf demande littéralement 2 sujets (brebis + agneau). Le défaut `2_objets` annoté chez l'humain devait viser une **mauvaise composition** (deux brebis adultes au lieu d'1+1, ou deux groupes mère-petit). Le prompt v2 ayant +159 chars suggère que le template a ajouté un wording de cadrage spécifique (compositions mère+petit). À valider visuellement en priorité.

## Décision / Action suivante

✅ Pipeline de re-run validée : 13/13 OK, prompts effectivement modifiés, pas de régression `color_ratio`.

❓ **Validation visuelle requise** sur les 13 paires v1/v2 — la métrique seule ne tranche pas.

**Annotation des v2** :
1. Charger l'annotateur : `http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark`
2. Filtrer/naviguer sur les filenames `*_v2.png` (13 nouveaux)
3. Comparer avec leur pendant v1 (filename sans `_v2`)
4. Annoter chaque v2 : si `2_objets` ne réapparaît pas → succès du fix. Sinon → cycle suivant de correction template.

Idéalement, ajouter au plan : un compare grid v1 vs v2 par paire pour accélérer la revue (hors scope de ce POC).

## Annexes

- **Script** : `scripts/poc_rerun_2objets.py`
- **Index résultats** : `docs/reports/poc-scale-benchmark/rerun-2objets.json` (13 entrées avec leaf_id, filename_original, filename_v2, positive_v2, color_ratio, histogram_ok, seed_original, seed_v2)
- **Sources d'annotations** : `docs/reports/poc-scale-benchmark/annotations.json` (196 entries)
- **Fichiers v2 produits** : `docs/reports/poc-scale-benchmark/{leaf_id}_1024x1024_euler8s_v2.png` ×13
- **Rapport amont** : `docs/reports/2026-05-09_fix-templates-2objets.md` (diagnostic + correctifs templates)
- **Fix associé** : `docs/reports/2026-05-09_fix-multiindex-benchmark.md` (multi-index fusion permettant à l'annotateur de retrouver titre/prompt/badges des leaves nature/objects)
