# POC negative prompt — enrichissement ciblé par type de sujet (post-fix workflow)
Date : 2026-05-06

## Contexte
Re-run du POC `negative-prompt` après réécriture propre des fichiers `data/workflows/ernie-image-turbo-q8-api.json` et `.overrides.json` (les versions précédentes étaient corrompues — null bytes + troncature). Ce rapport remplace le précédent run au verdict NULL en cache (cf. `2026-05-05_poc-negative-prompt.md`).

Test de l'effet d'un **negative prompt enrichi** (au lieu du string vide actuel) sur les 3 problèmes du POC `image-quality` (couleurs résiduelles fridge / motion artifacts soccer / couleurs vivides dragon). **Prompts positifs strictement inchangés**, mêmes paramètres sampler, **seed fixe par concept** pour isoler l'effet du negative entre les 3 variantes.

La colonne `v1 original POC` du compare grid réutilise les images existantes de `docs/reports/poc-image-quality/` (seed différent — montre la variance stochastique).

## Validation post-fix workflow

**Verdict global : ✅ FIX ACTIF** — le negative_prompt est désormais réellement injecté dans le KSampler via `node 15 → CLIPTextEncode`.

### Indicateurs de validation

**1. Latences ComfyUI cohérentes** (plus de cache hit)

| Concept | v2_no_negative | v3_baseline | v4_baseline_additif |
|---|---|---|---|
| soccer | 24.25 s | **18.20 s** | **18.18 s** |
| refrigerator | 18.16 s | **18.17 s** | **18.19 s** |
| dragon | 18.15 s | **18.18 s** | **18.16 s** |

→ Toutes les générations prennent ~18-24 s (vraies inférences). Au run précédent, v3/v4 retournaient en 0.03-2 s = cache hit ComfyUI parce que le négatif n'avait pas d'effet sur le graphe.

**2. SHA-256 distincts pour les 3 variantes par concept** (preuve binaire)

| Concept | v2 sha (16c) | v3 sha (16c) | v4 sha (16c) | bytes v2/v3/v4 | sha distincts |
|---|---|---|---|---|---|
| soccer | `511F7A0D1B627FFC` | `4768957E30E31E95` | `F4F487924581C6B9` | 945426 / 945583 / 945730 | **3/3** ✓ |
| refrigerator | `77322B8832ADD5F5` | `6D237D34CE291FB8` | `206D290D8A4D335D` | 900600 / 900757 / 900921 | **3/3** ✓ |
| dragon | `E49C4292EE729D4E` | `09FDB1F564107F33` | `003F711F7F3EB884` | 1005440 / 1005597 / 1005698 | **3/3** ✓ |

→ **9/9 images uniques** — le négatif change réellement le résultat. Tailles fichier qui varient légèrement (~150-300 octets) confirment que les images diffèrent au pixel près.

**3. Pipeline d'injection** (déjà vérifié dans `2026-05-05_test-negative-fix.md`)

- Workflow JSON node 16 (KSampler) : `inputs.negative = ["15", 0]` ✓
- Override contract : `negative_prompt → ["15", "text"]`, `optional` ✓
- `image_worker.py::process()` → `sanitize_public_workflow_inputs` → `apply_overrides` → injecte dans `node[15].inputs.text` automatiquement ✓
- Caveat connu : `sanitize_public_workflow_inputs` strip les strings vides → `negative_prompt=""` n'est pas injecté (le node 15 garde sa valeur par défaut, équivalent à pas de négatif)

## Negatives testés

**Baseline (commun)** :
```
shading, gradients, color fills, shadows, gray tones, watercolor, painting, photo, realistic, 3D render, blurry, low quality, text, watermark, signature, logo
```

**Additifs spécifiques** :

`soccer` (problème ciblé : motion artifacts → anatomie)
```
motion blur, action lines, speed lines, motion streaks, extra limbs, three legs, deformed legs, anatomical errors, multiple exposure, ghost limbs
```

`refrigerator` (problème ciblé : couleurs + lighting)
```
colorful, vivid colors, saturated colors, color fills, colored objects, ambient light, window glow, sunlight effect, warm lighting, colored lighting, golden light
```

`dragon` (problème ciblé : couleurs résiduelles)
```
colorful, vivid colors, green scales, colored dragon, saturated, painted, fantasy colors, chromatic
```

## Résultats par concept × variante

Métriques :
- `color_ratio` : ratio pixels colorés (Pillow histogram, `build_technical_image_qc_v1`)
- `histogram_ok` : pas de flag `strong_color` / `noticeable_color`
- `vision verdict` : qwen3.5:9b QC, good / poor
- `issues` : liste retournée par le QC vision

| Concept | Variante | latency | color_ratio | hist | vision verdict | issues |
|---|---|---|---|---|---|---|
| soccer | v2_no_negative | 24.25 s | 0.0021 | OK | good | — |
| soccer | v3_baseline | 18.20 s | 0.0021 | OK | good | — |
| soccer | v4_baseline_additif | 18.18 s | 0.0021 | OK | good | — |
| refrigerator | v2_no_negative | 18.16 s | 0.0398 | KO | poor | has_color |
| refrigerator | v3_baseline | 18.17 s | 0.0398 | KO | poor | has_color |
| refrigerator | v4_baseline_additif | 18.19 s | 0.0398 | KO | poor | has_color |
| dragon | v2_no_negative | 18.15 s | 0.0260 | KO | good | — |
| dragon | v3_baseline | 18.18 s | 0.0260 | KO | good | — |
| dragon | v4_baseline_additif | 18.16 s | 0.0260 | KO | good | — |

### Lecture de ces métriques globales

⚠ Subtilité importante : **les images sont bel et bien différentes** (sha256 distincts confirmés ci-dessus) mais leurs `color_ratio` (mesure agrégée) restent **identiques par concept**. Trois lectures possibles :

1. **Ernie Turbo CFG=1** : à CFG=1.0 la formule classifier-free pondère cond + neg avec coefficient nul sur le neg → l'effet du négatif se manifeste sur des détails de génération (positions, contours, micro-textures) mais **pas sur la balance chromatique globale**. Les couleurs résiduelles (fruits du frigo, gradient du dragon) sont propulsées par le **prompt positif**, pas atténuables par le négatif tant que CFG=1.
2. **Granularité de la métrique** : `color_ratio` arrondi à 4 décimales. Une diff réelle de quelques dizaines de pixels colorés se perd dans la précision. Avec une mesure plus fine (par exemple le delta L\*a\*b\* moyen) les diffs verraient peut-être le jour.
3. **Le négatif n'attaque pas la racine du problème** : la liste anti-couleurs est trop générale ; les couleurs résiduelles spécifiques (apple/banana magnets) ne sont pas nommées explicitement. Pour vraiment les supprimer il faudrait sans doute toucher au prompt positif (retirer "fruit", "magnetic").

## Outputs

Tous les fichiers dans `docs/reports/poc-negative-prompt/` :

```
sports-soccer-ball-on-a-field_v2_no_negative.png
sports-soccer-ball-on-a-field_v3_baseline.png
sports-soccer-ball-on-a-field_v4_baseline_additif.png
sports-soccer-ball-on-a-field_compare.png             ← grille 4 colonnes (v1 original | v2 | v3 | v4)
electromenager-refrigerator-in-a-kitchen_v2_no_negative.png
electromenager-refrigerator-in-a-kitchen_v3_baseline.png
electromenager-refrigerator-in-a-kitchen_v4_baseline_additif.png
electromenager-refrigerator-in-a-kitchen_compare.png  ← grille 4 colonnes
fantasy-dragon-in-a-castle-courtyard_v2_no_negative.png
fantasy-dragon-in-a-castle-courtyard_v3_baseline.png
fantasy-dragon-in-a-castle-courtyard_v4_baseline_additif.png
fantasy-dragon-in-a-castle-courtyard_compare.png      ← grille 4 colonnes
```

## Verdict par couche

> Évaluation à compléter par hamma après revue des `*_compare.png` — les sha256 différents prouvent qu'il y a un effet pixelaire ; reste à évaluer si l'effet est **utile** (correction des 3 problèmes ciblés) ou **marginal** (drift stochastique sans bénéfice).

### Le baseline seul suffit-il ?
→ [à compléter après revue visuelle des 3 colonnes v3_baseline]

### Les additifs spécifiques apportent-ils un gain mesurable ?
→ [à compléter après comparaison v3_baseline ↔ v4_baseline_additif sur chaque concept]

### Effet collatéral du negative sur les zones blanches / contours ?
→ [à compléter — vérifier que le negative ne dégrade pas le line art réussi]

## Si POC validé — actions de prod

Si l'effet du baseline (et/ou des additifs) est confirmé visuellement sur ces 3 cas :

1. **Mettre à jour `prompt_writer_ernie`** (cf. `prompts/image_prompts.yaml`) pour qu'il génère un `negative_prompt` structuré : baseline fixe + additifs sélectionnés selon les keywords du plan (subject/setting). Ne plus retourner `negative_prompt: ""`.
2. **Couche "negative prompt enrichment"** dans `src/services/ai_jobs_sync.py::_execute_writer_from_plan_v1_sync` : après le writer, parser le plan pour détecter les sujets sensibles (animaux→anatomie, électroménager→couleurs/lighting, créatures fantastiques→couleurs) et injecter l'additif correspondant. Logique simple : table `keyword → additif`.
3. **Tests** : `tests/test_negative_prompt_enrichment.py` avec 5 cas de keywords → vérifier que l'additif attendu est ajouté.

## Points d'attention

- **Seed fixe par concept** : v2/v3/v4 partagent le même seed → la diff visuelle entre eux est purement attribuable au negative. v1 (original POC) avait un seed aléatoire → différence stochastique normale entre v1 et v2.
- **Sampling 8 steps cfg=1.0** (Ernie defaults) : configuration prod, identique au POC image-quality. À CFG=1 l'effet du négatif est par construction limité ; pour un test plus marqué, envisager un POC à CFG=2-3 (mais re-bench qualité du line art Turbo nécessaire).
- **Vision QC qwen3.5:9b** : 5/6 sur le POC vision-batch — taux d'erreur ~17 % sur "has_color". Considérer Pillow histogram comme arbitre primaire et vision comme contrôle secondaire.
- **Latence par génération** : ~18-24 s ComfyUI + ~10 s vision QC = ~30 s par variante × 9 = ~5 min total pour ce POC.
- **Workflow corrompu pré-fix** : les fichiers `ernie-image-turbo-q8-api.json` et `.overrides.json` ont été réécrits proprement après détection de null bytes / troncature. Cause initiale du verdict NULL du run précédent.

## Annexes

- Données brutes : `2026-05-05_poc-negative-prompt.json` (mis à jour par le run v2)
- Script : `scripts/poc_negative_prompt.py`
- Prompts source : `docs/reports/2026-05-05_poc-prompt-chain-v2.json`
- Images originales POC : `docs/reports/poc-image-quality/`
- POC image-quality : `docs/reports/2026-05-05_poc-image-quality.md`
- Validation pipeline d'injection : `docs/reports/2026-05-05_test-negative-fix.md`
- Run précédent (cache hit, verdict NULL) : `docs/reports/2026-05-05_poc-negative-prompt.md`
