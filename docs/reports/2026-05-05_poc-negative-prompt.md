# POC negative prompt — enrichissement ciblé par type de sujet
Date : 2026-05-06

## Contexte
Test de l'effet d'un **negative prompt enrichi** (au lieu du string vide actuel) sur les 3 problèmes du POC `image-quality` (couleurs résiduelles fridge / motion artifacts soccer / couleurs vivides dragon). **Prompts positifs strictement inchangés**, mêmes paramètres sampler, **seed fixe par concept** pour isoler l'effet du negative entre les 3 variantes.

La colonne ``v1 original POC`` du compare grid réutilise les images existantes de ``docs/reports/poc-image-quality/`` (seed différent — montre la variance stochastique).

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

| Concept | Variante | color_ratio | hist | vision verdict | issues |
|---|---|---|---|---|---|
| soccer | v2_no_negative | 0.0021 | OK | good | — |
| soccer | v3_baseline | 0.0021 | OK | good | — |
| soccer | v4_baseline_additif | 0.0021 | OK | good | — |
| refrigerator | v2_no_negative | 0.0398 | KO | poor | has_color |
| refrigerator | v3_baseline | 0.0398 | KO | poor | has_color |
| refrigerator | v4_baseline_additif | 0.0398 | KO | poor | has_color |
| dragon | v2_no_negative | 0.0260 | KO | good | — |
| dragon | v3_baseline | 0.0260 | KO | good | — |
| dragon | v4_baseline_additif | 0.0260 | KO | good | — |

## Outputs

Tous les fichiers dans `docs/reports/poc-negative-prompt/` :

```
  sports-soccer-ball-on-a-field_v2_no_negative.png
  sports-soccer-ball-on-a-field_v3_baseline.png
  sports-soccer-ball-on-a-field_v4_baseline_additif.png
  sports-soccer-ball-on-a-field_compare.png   ← grille 4 colonnes (v1 original | v2 no_neg | v3 baseline | v4 baseline+additif)
  electromenager-refrigerator-in-a-kitchen_v2_no_negative.png
  electromenager-refrigerator-in-a-kitchen_v3_baseline.png
  electromenager-refrigerator-in-a-kitchen_v4_baseline_additif.png
  electromenager-refrigerator-in-a-kitchen_compare.png   ← grille 4 colonnes (v1 original | v2 no_neg | v3 baseline | v4 baseline+additif)
  fantasy-dragon-in-a-castle-courtyard_v2_no_negative.png
  fantasy-dragon-in-a-castle-courtyard_v3_baseline.png
  fantasy-dragon-in-a-castle-courtyard_v4_baseline_additif.png
  fantasy-dragon-in-a-castle-courtyard_compare.png   ← grille 4 colonnes (v1 original | v2 no_neg | v3 baseline | v4 baseline+additif)
```

## Verdict par couche

> Évaluation à compléter par hamma après revue des `*_compare.png`.

### Le baseline seul suffit-il ?
→ [à compléter après revue visuelle des 3 colonnes v3_baseline]

### Les additifs spécifiques apportent-ils un gain mesurable ?
→ [à compléter après comparaison v3_baseline ↔ v4_baseline_additif sur chaque concept]

### Effet collatéral du negative sur les zones blanches / contours ?
→ [à compléter — vérifier que le negative ne dégrade pas le line art réussi]

## Si POC validé — actions de prod

Si l'effet du baseline (et/ou des additifs) est confirmé sur ces 3 cas :

1. **Mettre à jour `prompt_writer_ernie`** (cf. `prompts/image_prompts.yaml`) pour qu'il génère un `negative_prompt` structuré : baseline fixe + additifs sélectionnés selon les keywords du plan (subject/setting). Ne plus retourner `negative_prompt: ""`.
2. **Couche "negative prompt enrichment"** dans `src/services/ai_jobs_sync.py::_execute_writer_from_plan_v1_sync` : après le writer, parser le plan pour détecter les sujets sensibles (animaux→anatomie, électroménager→couleurs/lighting, créatures fantastiques→couleurs) et injecter l'additif correspondant. Logique simple : table `keyword → additif`.
3. **Tests** : `tests/test_negative_prompt_enrichment.py` avec 5 cas de keywords → vérifier que l'additif attendu est ajouté.

## Points d'attention

- **Seed fixe par concept** : v2/v3/v4 partagent le même seed → la diff visuelle est purement attribuable au negative. v1 (original POC) avait un seed aléatoire → différence stochastique normale.
- **Sampling 8 steps cfg=1.0** (Ernie defaults) : configuration prod, identique au POC image-quality.
- **Vision QC qwen3.5:9b** : 5/6 sur le POC vision-batch — taux d'erreur ~17 % sur "has_color". Considérer Pillow histogram comme arbitre primaire et vision comme contrôle secondaire.
- **Latence par génération** : ~10-20s ComfyUI + ~10s vision QC = ~30s par variante × 9 = ~5 min total pour ce POC.

## Annexes

- Données brutes : `2026-05-05_poc-negative-prompt.json`
- Script : `scripts/poc_negative_prompt.py`
- Prompts source : `docs/reports/2026-05-05_poc-prompt-chain-v2.json`
- Images originales POC : `docs/reports/poc-image-quality/`
- POC image-quality : `docs/reports/2026-05-05_poc-image-quality.md`