# Fix — overlay métriques vide sur poc-generator-benchmark
Date : 2026-05-09

## Contexte

Le frontend `benchmark-annotator.html` affiche un overlay par image avec les
champs `metrics.histogram.color_ratio`, `metrics.histogram.ink_ratio`,
`metrics.histogram.flags` et `metrics.vision_qc.verdict`. Sur les POCs legacy
(`poc-sampler-benchmark`, `poc-sampler-benchmark-v2`, `poc-seed-variance`,
`poc-batch-size`…) ces champs sont **déjà imbriqués** dans chaque entrée :

```json
{
  "filename": "soccer_var01_s616025_b1.png",
  "histogram": { "color_ratio": 0.00213, "ink_ratio": 0.13579, "white_ratio": 0.81828, "flags": [] },
  "vision_qc": { "verdict": "good", "issues": [], "confidence": 100 }
}
```

Sur le **nouveau schéma `poc-generator-benchmark`** (sortie du nouveau
`prompt_generator.py`), les mêmes champs sont écrits **à plat** au niveau de
l'entrée :

```json
{
  "leaf_id": "lion_in_savanna",
  "filename": "lion_in_savanna_1024x1024_euler8s.png",
  "color_ratio": 0.00074,
  "ink_ratio": 0.09808,
  "white_ratio": 0.88222,
  "flags": []
}
```

Résultat : `_normalize_results_index()` retournait l'entrée brute, le frontend
lisait `entry.histogram.color_ratio` → `undefined`, l'overlay restait vide.

## Changement appliqué

Modification limitée à `src/api/routes/benchmark.py`, fonction
`_normalize_results_index()`. Avant de stocker l'entrée dans `metrics_by_fn`,
on synthétise les sous-objets `histogram` et `vision_qc` **uniquement s'ils
sont absents** (préservation de la forme nested existante des POCs legacy) :

```python
entry_out = dict(entry)
if not isinstance(entry_out.get("histogram"), dict):
    entry_out["histogram"] = {
        "color_ratio": entry.get("color_ratio"),
        "ink_ratio":   entry.get("ink_ratio"),
        "white_ratio": entry.get("white_ratio"),
        "flags":       entry.get("flags", []),
    }
if not isinstance(entry_out.get("vision_qc"), dict):
    entry_out["vision_qc"] = {
        "verdict": entry.get("vision_verdict") or entry.get("verdict"),
    }
metrics_by_fn[fname] = entry_out
```

Choix de design :
- **Pas de mutation de l'entrée d'origine** (`entry_out = dict(entry)` shallow copy) — évite tout effet de bord sur d'autres consommateurs ou sur des itérations ultérieures.
- **Préservation des nested existants** — si un POC legacy a déjà `histogram` ou `vision_qc` imbriqués, on les laisse intacts (rétrocompat stricte).
- **Tolérance aux valeurs absentes** — si une entrée nouveau-schéma n'a aucun champ flat (cas `poc-generator-benchmark` actuel : pas de `vision_verdict`), `vision_qc.verdict` vaut `None` → le frontend affichera `—`.
- **Champs flat conservés** — `color_ratio` et autres restent visibles à plat dans `entry_out` au cas où un autre consommateur les lirait.

Aucun autre fichier touché.

## Vérification rétrocompat

Test isolé sur les 3 schémas représentatifs :

### 1. Nouveau schéma (poc-generator-benchmark) — fields à plat

Entrée :
```python
{
  'leaf_id': 'lion_in_savanna', 'filename': 'lion_in_savanna_1024x1024_euler8s.png',
  'color_ratio': 0.00074, 'ink_ratio': 0.09808, 'white_ratio': 0.88222, 'flags': []
}
```

Sortie après `_normalize_results_index` :
```python
metrics['lion_in_savanna_1024x1024_euler8s.png'] = {
  'leaf_id': 'lion_in_savanna', 'filename': 'lion_in_savanna_1024x1024_euler8s.png',
  'color_ratio': 0.00074, 'ink_ratio': 0.09808, 'white_ratio': 0.88222, 'flags': [],
  'histogram': {'color_ratio': 0.00074, 'ink_ratio': 0.09808, 'white_ratio': 0.88222, 'flags': []},
  'vision_qc': {'verdict': None},   # pas de vision sur ce POC
}
```

→ **Synthèse appliquée**, l'overlay frontend lira correctement les champs.

### 2. Legacy nested (poc-seed-variance, poc-batch-size, poc-soccer-karras…)

Entrée déjà imbriquée :
```python
{
  'concept': 'soccer', 'filename': 'soccer_var01_s616025_b1.png',
  'histogram': {'color_ratio': 0.00213, 'ink_ratio': 0.13579, 'white_ratio': 0.81828, 'flags': []},
  'vision_qc': {'verdict': 'good', 'issues': [], 'confidence': 100, 'json_ok': True}
}
```

Sortie : **inchangée** — `histogram` et `vision_qc` déjà des dicts → la condition
`if not isinstance(... , dict)` rejette la synthèse.

### 3. Legacy keyed-par-filename (poc-sampler-benchmark, poc-sampler-benchmark-v2)

Cas où la clé du dict `results` est elle-même le filename, sans champ `filename`
dans l'entrée :

```python
results = {
  'astronaut_08s_normal_euler_cfg10_42006.png': {
    'histogram': {'color_ratio': 0.001, 'ink_ratio': 0.1, 'white_ratio': 0.85, 'flags': []},
    'vision_qc': {'verdict': 'good'}
  }
}
```

Sortie : **inchangée** sur le contenu, le filename est résolu via la clé (logique
existante `fname = key if isinstance(key, str) and key.lower().endswith(".png") else None`).

### Tableau de couverture

| POC (dossier) | Schéma | `histogram` nested ? | `vision_qc` nested ? | Effet du patch |
|---|---|:---:|:---:|---|
| `poc-sampler-benchmark` | legacy keyed | ✅ | ✅ | aucun (préservé) |
| `poc-sampler-benchmark-v2` | legacy keyed | ✅ | ✅ | aucun (préservé) |
| `poc-sampler-benchmark-v3` | legacy keyed | ✅ | ✅ | aucun (préservé) |
| `poc-seed-variance` | legacy nested + filename field | ✅ | ✅ | aucun (préservé) |
| `poc-soccer-karras` | legacy nested + filename field | ✅ | ✅ | aucun (préservé) |
| `poc-batch-size` | legacy nested + batch dict | ✅ | ✅ | aucun (préservé) |
| `poc-generator-benchmark` | new flat | ❌ → synthétisé | ❌ → synthétisé | **synthèse appliquée** ✅ |

## Points d'attention

1. **`vision_qc.verdict` reste `None` sur `poc-generator-benchmark`** — le POC actuel
   ne fait pas tourner le QC vision, donc l'overlay vision affichera `—`.
   Quand le POC sera étendu pour exécuter qwen3.5:9b et stocker `vision_verdict`
   à plat dans l'entrée, le patch le remontera automatiquement (le code lit déjà
   `entry.get("vision_verdict") or entry.get("verdict")`). Si le futur schéma
   choisit plutôt `vision_qc.verdict` nested, c'est tout aussi compatible.

2. **Si un POC futur expose à la fois flat ET nested** — la version nested gagne
   (préservation prioritaire). C'est le comportement le plus prudent : un POC
   qui se donne la peine d'écrire la forme imbriquée le fait probablement
   intentionnellement avec plus de richesse (ex. `vision_qc.issues`,
   `vision_qc.confidence`, `vision_qc.latency_s` que la synthèse ignore).

3. **Pas de schéma `metrics` séparé** — le contrat actuel est que
   `metrics_by_fn[fname]` contient l'entrée complète (avec en plus les nested
   synthétisés si besoin). Le frontend n'a pas à connaître le schéma source ;
   il accède toujours à `metrics.histogram.*` et `metrics.vision_qc.*`. Aucune
   migration de format n'est nécessaire pour les annotations existantes
   (`annotations.json`) — ce fichier est indépendant.

4. **Champs flat préservés en parallèle** — `entry_out` garde aussi
   `color_ratio` au top-level. Si un consommateur (script externe, audit) lit
   les champs flat, ils restent disponibles. Aucune duplication problématique
   puisque les valeurs sont identiques entre flat et nested.

5. **Tests automatiques** — le contrat n'est pas couvert par un test unit
   pytest aujourd'hui ; à ajouter dans un suivi `tests/test_benchmark_routes.py`
   (3 cas : new flat / legacy nested / legacy keyed) si on veut blinder contre
   une régression future.
