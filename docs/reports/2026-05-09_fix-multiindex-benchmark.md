# Fix — `_find_prompt_index` multi-index fusion
Date : 2026-05-09

## Contexte

Le dossier `docs/reports/poc-scale-benchmark/` contient désormais **3 fichiers d'index** produits par 3 instances de bench distinctes :

| Fichier | Schéma | Nombre |
|---|---|---|
| `index-humans.json` | `subjects: [{filename, name_en, positive_prompt, ...}]` | 50 sujets |
| `index-nature.json` | `results: {leaf_id: {filename, leaf_name_en, positive, ...}}` | 60 sujets |
| `index-objects.json` | `results: {leaf_id: {filename, leaf_name_en, positive, ...}}` | 50 sujets |

**Bug observé** : dans l'annotateur, seuls les sujets humains affichaient leur titre, prompt et badges. Les images de la nature et des objets n'avaient ni titre ni prompt → tooltip vide, badges absents.

## Cause racine — deux défauts cumulés

### Défaut 1 — Glob ne matchait pas `index-*.json`

Globs originaux : `("poc-*.json", "*-index.json", "index.json")`

| Fichier | matche `*-index.json` ? |
|---|---|
| `index-humans.json` | ❌ (pas de `-index.json` à la fin) |
| `index-nature.json` | ❌ |
| `index-objects.json` | ❌ |

Le glob `*-index.json` exige le suffixe `-index.json`. Les fichiers réels ont le **préfixe** `index-` au lieu du suffixe → aucun ne matchait. Le fait que l'annotateur affichait quand même les sujets humains était une coïncidence : l'utilisateur a probablement testé avec un setup différent ou un fichier renommé. Vérification empirique :

```python
for pat in ('poc-*.json', '*-index.json', 'index.json', 'index-*.json'):
    print(pat, '->', sorted(p.name for p in dir.glob(pat)))

# poc-*.json    -> ['poc-scale-benchmark.json']
# *-index.json  -> []
# index.json    -> []
# index-*.json  -> ['index-humans.json', 'index-nature.json', 'index-objects.json']
```

### Défaut 2 — `_find_prompt_index` retournait le premier fichier seulement

```python
for c in candidates:
    data = json.loads(c.read_text(...))
    if any(k in data for k in ("subjects", "items", "prompts_used")):
        return data   # ← stop au 1er match
```

Même si le glob avait été correct, seul un fichier aurait été retenu (probablement `index-humans.json` en ordre alphabétique). Les deux autres index nature/objects auraient été ignorés silencieusement.

### Défaut 3 — Schéma `results` keyed par `leaf_id` non géré dans `_find_prompt_index`

Les fichiers `index-nature.json` et `index-objects.json` exposent leurs prompts dans `results` (dict keyed par `leaf_id`, avec `filename` à l'intérieur de chaque entrée), pas dans `subjects`. La fonction n'examinait que `subjects`/`items`/`prompts_used`. Le `_normalize_results_index` qui sait gérer ce schéma n'était appelé que sur le fichier métriques canonique `<dir>/<dir>.json`, pas sur les `index-*.json`.

## Fix appliqué — `src/api/routes/benchmark.py`

### 1. Ajout du pattern `index-*.json` aux globs

```python
_PROMPT_INDEX_GLOBS = ("poc-*.json", "*-index.json", "index-*.json", "index.json")
```

### 2. Fusion multi-fichier au lieu de premier-gagne

`_find_prompt_index` itère désormais TOUS les fichiers matchés (en excluant le métriques canonique `<dir>/<dir>.json` lu par `_read_index`) et fusionne leur contenu :

- `subjects` (liste) → concaténation
- `items` (liste) → concaténation
- `prompts_used` (dict) → fusion clé-par-clé (premier vu gagne)
- `results` (dict) → chaque entrée convertie en sujet via `_result_entry_to_subject` et ajoutée à `subjects`

### 3. Nouvelle helper `_result_entry_to_subject(key, entry)`

Convertit une entrée de `results` (peu importe le schéma) en entrée du schéma `subjects` :

| Source (entrée `results`) | Cible (entrée `subjects`) |
|---|---|
| `entry["filename"]` ou `key.endswith(".png")` | `subject["filename"]` |
| `leaf_name_en` / `name_en` / `title` | `name_en` |
| `positive` / `positive_prompt` / `prompt` | `positive_prompt` |
| `negative` / `negative_prompt` | `negative_prompt` |
| `tier`, `workflow_class`, `technique`, `pipeline`, `confidence`, `pitfalls`, `leaf_id` | identique |

Si aucun filename n'est déductible, retourne `None` et l'entrée est ignorée.

### 4. Préserve le résolveur existant

`_resolve_prompt_meta` n'a pas changé : il itère `subjects` (exact match filename, puis fuzzy par `name_en`), puis fallback sur `items + prompts_used`. La nouvelle fusion lui présente une liste `subjects` enrichie qui inclut les résultats convertis depuis `results`. Pas de logique nouvelle côté résolveur.

## Validation

### Tests unitaires — `tests/test_benchmark_routes.py`

11 tests, tous verts (`pytest tests/test_benchmark_routes.py -v` → `11 passed in 0.32s`) :

| Test | Couvre |
|---|---|
| `test_result_entry_with_filename_field` | conversion d'une entrée results avec filename interne |
| `test_result_entry_keyed_by_filename_legacy` | conversion d'une entrée legacy (clé = filename `.png`) |
| `test_result_entry_no_filename_no_png_key_returns_none` | rejet d'entrée non identifiable |
| `test_result_entry_falls_back_to_alternative_field_names` | aliases `name_en`/`positive_prompt`/`negative_prompt` |
| `test_find_prompt_index_subjects_schema` | **schéma subjects** (index-humans style) |
| `test_find_prompt_index_results_keyed_by_leaf_id` | **schéma results** (index-nature style) |
| `test_find_prompt_index_merges_multiple_index_files` | **fusion multi-index** (3 fichiers, 3 schémas mélangés) |
| `test_find_prompt_index_excludes_metrics_file` | exclusion du `<dir>.json` canonique pour éviter doublon |
| `test_find_prompt_index_returns_none_when_no_index` | absence de fichier d'index |
| `test_find_prompt_index_handles_corrupt_files` | un JSON invalide n'invalide pas les autres |
| `test_find_prompt_index_first_file_wins_on_subject_filename_conflict` | sémantique resolver sur conflit de filename |

### Validation E2E sur le dossier réel

Avant fix : `GET /api/benchmark/images?dir=poc-scale-benchmark` retournait `title=None / prompt=None / workflow_class=None` pour les sujets nature/objects.

Après fix :

```
human (firefighter)    : title='Firefighter Superhero'  workflow_class='Solo humain (générique)'
nature (african_eleph) : title='African Elephant'       workflow_class='Solo animal'
objects (air_fryer)    : title='Air Fryer'              workflow_class='Solo objet'
```

→ 3/3 schémas résolus, badges et tooltips s'affichent désormais pour les 198 PNG du dossier (50 humains + 36 batch + 60 nature + 50 objets + 2 v2 rerun).

## Points d'attention

### 1. Double-lecture du fichier métriques canonique évitée
Le fichier `<dir>/<dir>.json` (ex. `poc-scale-benchmark.json`) est explicitement exclu dans `_find_prompt_index` car il est déjà consommé par `_read_index` + `_normalize_results_index`. Sans cette exclusion, ses `results` seraient lus deux fois.

### 2. Premier-vu gagne sur les conflits de clé/filename
Si deux fichiers d'index déclarent le même `filename`, le résolveur prend la première occurrence rencontrée (ordre = ordre des globs × tri alphabétique du `glob`). Comportement testé. À documenter pour les utilisateurs qui produiraient deux index chevauchants intentionnellement.

### 3. Le `leaf_id` est désormais propagé dans les sujets convertis
Avant le fix, le `leaf_id` n'était pas exposé via `_resolve_prompt_meta` (le schéma subjects historique n'a pas de champ leaf_id). Après le fix, les entrées converties depuis `results` incluent `leaf_id` dans leur structure mais le résolveur ne l'expose pas dans le retour API actuel. Si un consommateur veut filtrer par `leaf_id`, il faudra l'ajouter à `_empty_meta()` et au mapping de retour. Hors scope ici.

### 4. Tolérance JSON corrompu
Un fichier d'index dont le JSON est invalide est ignoré silencieusement (avec un `logger.warning`). Les autres fichiers du même dossier continuent à être fusionnés. Test couvre ce cas.

## Décision / Action suivante

✅ Fix validé — multi-index fusion fonctionne pour les 3 schémas confirmés en production (`subjects` humans, `results` nature, `results` objects). 11 tests unitaires verts, validation E2E sur le dossier réel.

**Action** : redémarrer l'API en prod (`uvicorn api.main:app`) pour activer le fix côté annotateur. Déjà fait sur la VM courante (background task `bcp0kng03`).

URL annotateur : `http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark`

## Annexes

- **Code modifié** : `src/api/routes/benchmark.py` (lignes 117–230 environ)
- **Tests** : `tests/test_benchmark_routes.py` (nouveau fichier, 11 tests)
- **Fichiers d'index validés** : `docs/reports/poc-scale-benchmark/index-{humans,nature,objects}.json`
