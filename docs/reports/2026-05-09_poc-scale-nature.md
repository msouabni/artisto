# POC scale-benchmark NATURE
Date : 2026-05-09

## Contexte

Premier passage à l'échelle du `PromptGenerator` post-audit cartographie
(2026-05-09) sur les classes nature. Objectif : valider que les templates
mis à jour (`Solo animal`, `Solo insect`, `Solo fish`, plus les classes
prêtes mais non encore activées `Solo bird`, `Solo reptile`,
`Solo animal (mammifère marin)`) tiennent au QC technique automatique
(Pillow histogram) sur un sample représentatif de feuilles haute confiance.

**Pipeline :** `services.prompt_generator.PromptGenerator` → workflow
`ernie-image-turbo-q8-api` (JSON brut, modifications nodes 13/14/15/16) →
ComfyUI direct → `build_technical_image_qc_v1` Pillow.

**Paramètres figés** : sampler `euler`, steps `8`, scheduler `normal`,
`cfg=1.0`, `denoise=1.0`, `batch_size=1`, seed = `5000 + idx × 7`.

**Sélection :**
1. `gen.list_high_confidence_leaves()` → 898 leaves disponibles
2. Filtre par `workflow_class ∈ NATURE_CLASSES` → 110 leaves nature
3. `random.Random(2026).sample(..., 60)` → 60 leaves capés

**Distribution du sample (60) :**
- **Solo animal** : 49 (mammifères 4 pattes + fantasy_animals + outliers `pet_turtle`, `beluga_whale`, `snowy_owl`, `turkey_bird`, `rising_phoenix`, `fairy_with_wings`)
- **Solo fish** : 8 (sample sur les 15 marines)
- **Solo insect** : 3 (sample sur les 12 insectes/arachnides)
- **Solo bird** : **0** — `birds` est en confiance `Moyenne` dans la cartographie, exclu de `list_high_confidence_leaves()`. Le template `Solo bird` est en place mais pas exercé sur ce POC.
- **Solo reptile / Solo animal (mammifère marin)** : 0 — aucune sub n'utilise ces classes actuellement (réservées pour activation future via `leaf_overrides`).

## Stats par classe

| Classe | n | n_ok | hist_ok | color_ratio_avg | color_ratio_max | violators (>0.025) |
|---|---:|---:|---:|---:|---:|---:|
| **Solo animal** | 49 | 49 | 49 | **0.00084** | 0.00175 | **0** |
| **Solo fish** | 8 | 8 | 8 | **0.00085** | 0.00118 | **0** |
| **Solo insect** | 3 | 3 | 3 | **0.00090** | 0.00114 | **0** |
| **Total** | **60** | **60** | **60** | 0.00085 | 0.00175 | **0** |

→ **100 % des images** passent le QC histogram (`color_ratio < 0.025`,
pas de flags `noticeable_color` / `strong_color` / `near_empty` / `overdrawn`).
**0 erreur ComfyUI** sur 60 générations. Zéro violator couleur.

`color_ratio_avg ≈ 0.00085` est ~30× sous le seuil `noticeable_color`
(0.025) et ~95× sous `strong_color` (0.08). Les prompts produits par
le `PromptGenerator` post-audit portent fortement la contrainte
monochrome — aucun « color leak » résiduel sur ce sample.

`ink_ratio` est sain partout : 0.05–0.16 en moyenne, soit la zone cible
coloriage enfant (ni `near_empty` ni `overdrawn`).

## Latence

- **Solo animal** (49 images, durée la première moitié du run) :
  50–75 s par image (pic à 75 s côté ComfyUI partagé). Médiane ~52 s.
- **Solo fish + Solo insect** (11 images, fin du run) :
  18 s par image, latence stable. ComfyUI a libéré la charge concurrente
  pendant cette phase.
- **Total wall-time** : ~50 min pour 60 images (≈ 50 s/image moyenne, dominé
  par la phase Solo animal en charge concurrente).

La latence Solo fish/insect (18 s) correspond au régime nominal
`euler 8 steps 1024×1024 cfg=1.0` mesuré sur les POCs précédents
(POC seed-variance, POC batch-size).

## Points d'attention

### 1. QC technique automatique ≠ QC anatomique

Le QC histogram passe à 100 %, mais il **ne dit rien sur l'anatomie** :
- les outliers structurels (`fairy_with_wings`, `rising_phoenix`,
  `pet_turtle`, `snowy_owl`, `turkey_bird`, `beluga_whale`) ont reçu
  un prompt « 4 pattes au sol » (template `Solo animal` générique)
  alors que leur morphologie réelle est différente. Le QC histogram
  n'a aucun moyen de détecter cette dissonance prompt/sujet.
- la validation **anatomy** passe **uniquement** par revue humaine
  (cf. POC vision QC 2026-05-07 : LLM vision `qwen3.5:9b` et
  `gemma4:26b` recall=0 sur défauts anatomy en line art).

→ La revue humaine via `benchmark-annotator.html?dir=poc-scale-benchmark`
est obligatoire avant tout scale-up production. Attendre 60 annotations
humaines pour confirmer la qualité réelle.

### 2. `Solo bird` non exercé sur ce POC

`birds` (14 leaves) est marqué `confidence: Moyenne` dans la cartographie.
Il n'apparaît donc pas dans `list_high_confidence_leaves()` et le sample
de 60 contient zéro `Solo bird`. Le template `Solo bird` (avec sous-routage
flying / perched / standing in water / peacock / cage / branch — Insight D
respecté) est en place dans le code mais **non testé empiriquement à
l'échelle**.

→ Action suivante : un POC dédié `birds` sur les 14 leaves (peu importe
le label de confidence), pour valider l'Insight D et débloquer la
promotion `birds.confidence: Haute`.

### 3. Outliers connus encore présents (audit 2026-05-09)

Le sample contient 6 leaves dont la classe `Solo animal` est inadaptée à
la morphologie :

| Leaf | Sous-cat | Problème prompt |
|---|---|---|
| `pet_turtle` | pet_animals | Reptile, vue dessus + carapace ignorée |
| `beluga_whale` | arctic_animals | Mammifère marin, pas de "4 legs on ground" |
| `snowy_owl` | arctic_animals | Oiseau, devrait perché ou en vol |
| `turkey_bird` | farm_animals | Oiseau, pas de "4 legs on ground" |
| `rising_phoenix` | fantasy_animals | Créature volante, devrait flying |
| `fairy_with_wings` | fantasy_animals | Humanoïde ailé, pas un quadrupède |

Toutes ces images ont passé le QC histogram (color < 0.002), mais la
revue humaine devra signaler la dissonance morphologique. Le mécanisme
de fix proposé dans l'audit (`production_strategy.leaf_overrides`)
permettra de re-router ces 6 leaves vers `Solo bird` / `Solo fish` /
`Solo reptile` / `Solo humain` sans toucher la sous-catégorie.

### 4. Latence ComfyUI à 50–75 s sur la première phase

La phase Solo animal a tourné à 50-75 s par image, contre 18 s en phase
finale. Cause probable : ComfyUI partagé avec une autre tâche en
parallèle (instance Comfy unique). Pas un problème intrinsèque du
pipeline : la latence nominale `euler 8s 1024² cfg=1.0` reste à ~18 s.

→ Action si scale-up prod : isoler ComfyUI ou prévoir une queue
dédiée pour ne pas concurrencer les jobs interactifs.

### 5. Sample sous-représente Solo insect (3/60 = 5 %)

`Solo insect` n'a que 3 leaves dans le sample alors que la sous-population
disponible était 12 (25 % de 110). Le `random.sample` est mathématiquement
correct mais statistiquement moins informatif sur cette classe. Si on
veut un verdict robuste sur Solo insect, le re-bench sur les 12 leaves
complètes prend 12 × 18 s = 4 min.

## Action suivante

1. **Annotation humaine** des 60 images via le benchmark-annotator
   (mode 1 image plein écran ; ~3-5 s par image au pacing optimisé →
   ~3-5 min pour le batch). Critères à vérifier : anatomie correcte,
   morphologie cohérente avec le sujet, pas d'éléments parasites.
2. **POC `birds` dédié** sur les 14 leaves (env. 4 min de génération
   + 1-2 min annotation), pour valider `Solo bird` à l'échelle et
   débloquer la promotion `birds.confidence: Haute`.
3. **Compléter Solo insect** sur les 12 leaves complètes (4 min de
   génération supplémentaire) si on veut un verdict statistiquement
   robuste sur cette classe.
4. **Implémenter `production_strategy.leaf_overrides`** dans
   `services.prompt_generator.PromptGenerator.build_prompt` pour
   permettre de re-router les ~12-15 outliers identifiés dans l'audit
   2026-05-09 sans toucher la structure publique de la taxonomie.
5. **Re-bench scale après leaf_overrides** sur les mêmes 60 leaves
   pour mesurer le gain QC (attendu : aucun gain sur le QC technique
   puisqu'il passait déjà à 100 %, mais gain anatomique mesurable côté
   revue humaine).

## Annexes

- Index complet : `docs/reports/poc-scale-benchmark/index-nature.json`
  (60 entrées avec leaf_id, workflow_class, resolution, positive,
  negative, filename, color_ratio, ink_ratio, white_ratio, flags,
  comfy_latency_s, stats_by_class agrégées).
- Galerie : `docs/reports/poc-scale-benchmark/*.png` (60 PNG, naming
  `{leaf_id}_{w}x{h}_euler8s.png`).
- Annotation humaine : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark
- Script : `scripts/poc_scale_benchmark_nature.py`
- POCs amont :
  - `docs/reports/2026-05-09_audit-cartographie-templates.md` (audit ayant
    introduit `Solo insect` / `Solo fish` / `Solo bird` / `Solo reptile`)
  - `docs/reports/2026-05-09_fix-metrics-overlay.md` (frontend overlay
    métriques pour le nouveau schéma flat)
- Code modifié dans cette session :
  - `src/services/prompt_generator.py` : sync des 4 templates +
    dispatcher entries depuis la copie `docs/xchange/` (audit 2026-05-09)
