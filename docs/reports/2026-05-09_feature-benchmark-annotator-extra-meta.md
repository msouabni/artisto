# Feature — Benchmark annotator : champs étendus poc-generator-benchmark
Date : 2026-05-09

## Contexte

Le nouveau POC `poc-generator-benchmark` introduit dans son index JSON
(`docs/reports/poc-generator-benchmark/poc-generator-benchmark.json`) cinq
champs supplémentaires par image, absents des POCs précédents :
`workflow_class`, `technique`, `pipeline`, `confidence`, `pitfalls[]`.

L'annotateur visuel `data/benchmark-annotator.html` ne savait afficher que
le couple `title` / `prompt` / `negative` / `tier` historique ; ces nouveaux
champs n'apparaissaient nulle part dans l'UI. Côté API
(`/api/benchmark/images`), la structure d'index de ce POC est aussi
inédite : `results` est keyed par `leaf_id` (et non par filename), et chaque
entrée embarque à la fois métriques **et** prompts/extra-meta. Les helpers
existants (`_resolve_prompt_meta`, `_find_prompt_index`) ne reconnaissaient
ni ce schéma ni les nouveaux champs.

## Résultats

### Fichiers modifiés

| Fichier | Nature des changements |
|---|---|
| `data/benchmark-annotator.html` | CSS badges + 1 conteneur `meta-badges` sous le titre + 2 sections tooltip (`tt-tech-block`, `tt-pitfalls-block`) + branchement JS dans `renderCurrent()` |
| `src/api/routes/benchmark.py` | `_EXTRA_META_KEYS`, `_extract_extra_meta()`, `_empty_meta()`, `_normalize_results_index()` ; extension de `_resolve_prompt_meta()` aux nouveaux champs ; refonte de `list_images()` pour normaliser les deux schémas `results` |

Aucun fichier créé. Aucun test ajouté (cf. Points d'attention).

### HTML — comportement final

Sous le titre du sujet, une ligne de badges inline est rendue dans
`#meta-badges`, dans cet ordre :

1. `workflow_class` — fond `#3b4a6b`, texte blanc, classe CSS `.workflow-class`
2. `confidence: <valeur>` — classe dynamique :
   - `Haute` → `.confidence-haute` (fond `#166534`)
   - `Moyenne` → `.confidence-moyenne` (fond `#92400e`)
   - `Faible` → `.confidence-faible` (fond `#7f1d1d`)
   - autre valeur → badge sans classe de couleur (style de base seulement)
3. `pipeline` — fond transparent, bordure `#9aa0a6` (clair) / `#64748b` (sombre)

Style commun appliqué via `.meta-badge` : `border-radius: 10px;
padding: 2px 8px; font-size: 0.7rem; line-height: 1.4; white-space: nowrap`.

Le slug de confidence passe par `String(...).normalize("NFD").replace(/[̀-ͯ]/g, "")`
pour matcher les classes CSS sans accents.

Si tous les champs étendus sont absents, `#meta-badges` reste `hidden` →
rétrocompat préservée pour les POCs antérieurs.

Tooltip de l'icône ℹ️ : deux nouvelles sections rendues après les blocs
prompt/négatif :

- `tt-tech-block` — titre **Technique :**, contenu = `item.technique`
- `tt-pitfalls-block` — titre **Pièges :**, contenu = `pitfalls.join(" • ")`

L'icône ℹ️ s'affiche désormais dès qu'au moins un de
`{prompt, technique, pitfalls}` est présent (avant : `prompt` seul). Chaque
section est masquée individuellement via `hidden` si vide, comme pour le
bloc négatif existant.

### API — comportement final

`GET /api/benchmark/images` retourne désormais ces clés supplémentaires
par item :

```
workflow_class, technique, pipeline, confidence, pitfalls
```

Tous valent `null` (ou `[]` pour `pitfalls`) si le POC n'expose pas ces
champs.

`_normalize_results_index(raw_results)` produit deux maps indexées par
filename :

- `metrics_by_fn` : tous les champs de l'entrée (sert au champ `metrics`).
- `embedded_meta_by_fn` : `{title, prompt, negative, tier, workflow_class,
  technique, pipeline, confidence, pitfalls}` quand au moins un de ces
  champs est présent.

Détection du schéma : si `entry.filename` existe, c'est le canonical
filename (cas `poc-generator-benchmark` keyed par leaf_id) ; sinon la clé
elle-même est utilisée si elle se termine par `.png` (legacy `poc-sampler-benchmark`).
Les entrées `status: skip_unknown_leaf` (sans filename) sont ignorées
silencieusement.

Dans `list_images()` la résolution de meta est désormais :

1. si `name in embedded_meta_by_fn` → utiliser cette meta (priorité).
2. sinon → fallback sur `_resolve_prompt_meta(name, prompt_index)` (chemin
   subjects / items+prompts_used inchangé).

`_resolve_prompt_meta()` a aussi été étendu pour propager les cinq
nouveaux champs sur les schémas existants (`subjects`, `items` +
`prompts_used`) : utile si un futur POC utilise une mise en page legacy
mais avec ces champs.

### Smoke test

Sur `docs/reports/poc-generator-benchmark/poc-generator-benchmark.json`
(8 entrées avec `status: ok`, 5 entrées `skip_unknown_leaf` ignorées) :

- `metrics_by_fn` → 8 filenames, OK
- `embedded_meta_by_fn` → 8 filenames, OK
- exemple `lion_in_savanna_1024x1024_euler8s.png` :
  - `workflow_class = "Solo animal"`
  - `confidence = "Haute"`
  - `pipeline = "ERNIE direct"`
  - `technique = "Solo en profil + savane/jungle silhouette en arrière-plan"`
  - `pitfalls = ["Acacia tree à préciser 'fully visible' (Insight A)"]`
  - `title = "Lion in the Savanna"`, prompt + negative présents.

`_find_prompt_index()` retourne toujours `None` pour ce POC (le fichier
`poc-generator-benchmark.json` n'a ni `subjects`, ni `items`, ni
`prompts_used`) — ce qui est attendu : c'est `_normalize_results_index`
qui prend le relais.

Validation syntaxique : `python -c "import ast; ast.parse(...)"` → OK.

## Points d'attention

- **Encodage console Windows** : le smoke test imprime `arri�re-plan` /
  `pr�ciser` — c'est un artefact d'affichage cp1252 dans le terminal,
  les chaînes Python en mémoire sont correctes (l'API renvoie du JSON
  UTF-8). À vérifier visuellement dans le navigateur lors du premier
  chargement.
- **Métriques affichées dans l'overlay** : la frontend lit
  `metrics.histogram.color_ratio` / `.ink_ratio` / `.flags` et
  `metrics.vision_qc.verdict`. Le nouveau schéma met ces champs **à plat**
  (`color_ratio`, `ink_ratio`, `flags` au top-level de l'entrée, pas de
  sous-objet `histogram` ni `vision_qc`). Conséquence : l'overlay
  métriques en bas-gauche de l'image **n'affichera rien** sur les images
  `poc-generator-benchmark` tant qu'on n'a pas adapté soit le frontend,
  soit `_normalize_results_index` pour reconstruire le sous-objet
  `histogram`. Hors-périmètre du ticket actuel — à arbitrer.
- **`_PROMPT_INDEX_GLOBS` inclut `poc-*.json`** : le fichier
  `poc-generator-benchmark.json` matche ce glob mais est rejeté par
  `_find_prompt_index` parce qu'il n'a aucune des clés
  `subjects/items/prompts_used`. Pas d'effet de bord, mais le code essaie
  inutilement de le parser. Acceptable.
- **Aucun test pytest n'a été ajouté.** Le module `tests/` n'a pas de
  fichier dédié à `benchmark.py`. La suite ne couvre donc pas la
  régression. À envisager (`tests/test_benchmark_routes.py` avec un
  fixture pour chacun des trois schémas : sampler-benchmark legacy,
  taxonomy-subjects, generator-benchmark).
- **Champ `tier` absent** dans le nouveau schéma → `prompt-tier` reste
  caché, comportement attendu.
- **Validation manuelle UI non effectuée** : l'API n'a pas été démarrée
  pour ouvrir l'annotateur dans un navigateur ; uniquement validation
  syntaxique + smoke test du helper Python.

## Décision / Action suivante

**Action immédiate (utilisateur) :** ouvrir l'API
(`python start.py --no-comfy`) et naviguer sur
`http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-generator-benchmark`
pour valider visuellement :

1. Apparition des 3 badges sous le titre.
2. Couleurs correctes selon `confidence`.
3. Tooltip ℹ️ affiche bien Technique + Pièges (séparateur " • ").
4. Comportement inchangé sur `poc-sampler-benchmark` /
   `poc-sampler-benchmark-v3` (rétrocompat — pas de badges, tooltip
   inchangé).

**Action de suite recommandée :** trancher si on adapte le frontend pour
lire les métriques au top-level (alternative : faire que
`_normalize_results_index` synthétise un sous-objet `histogram` à la
volée). Sans ça, l'overlay métrique reste vide sur ce POC.

**À faire si la validation UI passe :** ajouter
`tests/test_benchmark_routes.py` couvrant les trois schémas avec un
fixture sur disque et 1 assertion par champ étendu.
