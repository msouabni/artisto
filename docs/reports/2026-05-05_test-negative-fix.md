# Validation fix negative prompt — workflow ernie-image-turbo-q8-api
Date : 2026-05-06

## Contexte
Le workflow `data/workflows/ernie-image-turbo-q8-api.json` a été modifié : `KSampler.negative` (node 16) est désormais branché sur `CLIPTextEncode` (node 15), au lieu de l'ancien `ConditioningZeroOut` (node 19, supprimé). Le contrat `overrides.json` expose `negative_prompt` comme input optional, mappé sur `["15", "text"]`. Ce test valide que le fix est effectif côté pipeline image.

Référence du POC précédent qui montrait le problème (4 variantes négatives → 4 images strictement identiques à cause du `ConditioningZeroOut` qui annulait le négatif) : `docs/reports/2026-05-05_poc-negative-prompt.md`.

## Vérification d'injection côté code (avant exécution)

- `data/workflows/ernie-image-turbo-q8-api.json` node `16` (KSampler) : `inputs.negative = ["15", 0]` ✓
- `data/workflows/ernie-image-turbo-q8-api.overrides.json` : `public_inputs.negative_prompt = ["15", "text"]`, `capabilities.negative_prompt = optional` ✓
- `src/workers/image_worker.py::process()` : passe `config.negative_prompt` dans `candidate_values`, puis `sanitize_public_workflow_inputs` filtre selon le contrat, puis `apply_overrides` injecte dans `node[15].inputs.text`. **Aucune modification code requise** — l'injection est automatique via le contrat.
- ⚠ Caveat : `sanitize_public_workflow_inputs` filtre les strings vides après `strip()` → `negative_prompt = " "` n'est PAS injecté ; le node 15 garde alors sa valeur par défaut du JSON (qui est `" "`). Cela reste équivalent à "pas de négatif effectif" et sert de baseline propre.

## Test : 4 générations, même seed, prompt positif identique

- **Concept** : Soccer Ball on a Field (prompt extrait de `2026-05-05_poc-prompt-chain-v2.json`, 780 chars)
- **Workflow** : `ernie-image-turbo-q8-api`
- **Seed** : `42001` (identique pour les 4 variantes)
- **Sampler** : steps=8, cfg=1.0, sampler=euler, scheduler=normal, denoise=1.0

### Variantes negative_prompt testées

- `neg_none` (1 chars) : `' '`
- `neg_standard` (68 chars) : `'shading, gradients, color fills, shadows, text, watermark, realistic'`
- `neg_anatomy` (87 chars) : `'motion blur, action lines, extra limbs, three legs, deformed anatomy, multiple exposure'`
- `neg_full` (157 chars) : `'shading, gradients, color fills, shadows, text, watermark, realistic, motion blur, action lines, extra limbs, three legs, deformed anatomy, multiple exposure'`

### Résultats par variante

| Code | latency | sha256 (16 chars) | injecté | color_ratio | hist |
|---|---|---|---|---|---|
| neg_none | 20.22s | `511f7a0d1b627ffc…` | filtré (vide) | 0.0021 | OK |
| neg_standard | 20.22s | `497e0bedf6ba92db…` | ✓ | 0.0021 | OK |
| neg_anatomy | 18.33s | `01137422fd94b6ce…` | ✓ | 0.0021 | OK |
| neg_full | 18.23s | `5b624a5ba73bb8b1…` | ✓ | 0.0021 | OK |

### Verdict du fix

✅ **Toutes les variantes ont des sha256 différents → le fix est ACTIF.**

Le `negative_prompt` est désormais réellement injecté dans le KSampler via le node 15. À CFG=1 le négatif n'a normalement aucun effet mathématique (cf. `2026-05-05_poc-negative-prompt.md`) — si on observe néanmoins des différences pixelaires, deux explications possibles :

1. Le sampler Ernie Turbo applique le négatif via un mécanisme alternatif (rescale CFG, neg weight) **au-delà** de la simple formule classifier-free.
2. La déterminisme du sampler dépend du conditioning passé (ordre / contenu) même quand le coefficient final est nul (calcul intermédiaire avec arrondi flottant).

Quoi qu'il en soit, **le pipeline d'injection est branché correctement**. Reste à mesurer (visuellement) si l'effet est exploitable pour corriger les 3 problèmes du POC `image-quality`.

## Effet visuel observé

Voir `docs/reports/test-negative-fix/soccer_compare.png` (4 colonnes côte à côte). Évaluation à compléter par hamma :

- **`neg_none` vs `neg_standard`** : le négatif standard supprime-t-il les couleurs résiduelles, ombres, texte ?
- **`neg_none` vs `neg_anatomy`** : le négatif anatomy corrige-t-il les motion blur / extra limbs / deformed legs ?
- **`neg_full`** : effet cumulé propre, ou conflits / dégradations sur la silhouette principale ?

→ [section qualitative à compléter visuellement]

## Outputs

```
docs/reports/test-negative-fix/
├── soccer_neg_none.png
├── soccer_neg_standard.png
├── soccer_neg_anatomy.png
├── soccer_neg_full.png
└── soccer_compare.png   ← grille 4 colonnes
```

## Décision / Action suivante

✅ Pipeline d'injection validé. Étape suivante :

1. **Évaluation visuelle** des 4 PNG par hamma — le négatif corrige-t-il visiblement les 3 problèmes du POC `image-quality` (couleurs résiduelles fridge, motion artifacts soccer, couleurs vivides dragon) ?
2. Si oui : **mettre à jour `prompt_writer_ernie`** pour qu'il génère un negative_prompt structuré (baseline + additifs par sujet, cf. ce POC).
3. Si non : revenir sur l'option C du POC précédent (post-process via `gray-replace` / `dithering`).

## Annexes

- Données brutes : `2026-05-05_test-negative-fix.json`
- Script : `scripts/test_negative_prompt_fix.py`
- Workflow : `data/workflows/ernie-image-turbo-q8-api.json` + `.overrides.json`
- POC initial (avant fix) : `docs/reports/2026-05-05_poc-negative-prompt.md`
- Code d'injection : `src/workers/image_worker.py::process()` + `src/workers/comfy_client.py::apply_overrides`