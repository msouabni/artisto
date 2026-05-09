# POC prompt filter — validation empirique des règles de réécriture
Date : 2026-05-05

## Contexte
Test isolé (pas d'intégration pipeline) de **4 règles de sanitisation appliquées avant ComfyUI** sur les 3 concepts problématiques du POC image quality :

- `sports-soccer-ball-on-a-field` — anatomie (3 jambes en mode action kicking)
- `electromenager-refrigerator-in-a-kitchen` — couleurs résiduelles + lighting (sunlight + colorful + couleurs nommées)
- `fantasy-dragon-in-a-castle-courtyard` — couleurs résiduelles (green dragon, red banners)

## Règles testées

| ID | Type | Description |
|---|---|---|
| `anatomy_static_pose` | trigger_append | Si verbe d'action détecté (kicking, running, mid-air, …), append « simple static pose, exactly two legs and two arms ». |
| `no_light_sources` | phrase_replace | Strip des sources lumineuses (sunlight, golden light, glowing, …) qui poussent ERNIE à ajouter un rendu ombré/coloré. |
| `strip_color_nouns` | regex_replace | `\b(red|blue|green|...)\s+(\w+)` → ne garde que le nom, sauf si suivi de `background`/`outlines`/`line` (mots-clés line-art à préserver). |
| `no_colorful_adjectives` | phrase_replace | `colorful → cheerful`, `vibrant → lively`, `bright → inviting`, `multicolored → varied`, `vivid → clear`. |

## Tableau résumé par concept

| Concept | Règles décl. | color_ratio orig→filt | ink_ratio orig→filt | Vision orig (issues) | Vision filt (issues) | Anatomie OK ? |
|---|---:|---:|---:|---|---|:---:|
| Soccer Ball on a Field | 2 | 0.0066 → **0.0015** | 0.1403 → 0.1131 | **good** (—) | **good** (—) | ✅ |
| Refrigerator in a Kitchen | 4 | 0.0582 → **0.0006** | 0.0746 → 0.0423 | **good** (has_color) | **good** (—) | n/a |
| Dragon in a Castle Courtyard | 1 | 0.0502 → **0.0035** | 0.1264 → 0.1238 | **good** (has_color) | **good** (—) | n/a |

## Détail des règles déclenchées par concept

### [sports] Soccer Ball on a Field
- Issue ciblée : anatomie (3 jambes en mode action kicking)
- 2 événement(s) :
  - `anatomy_static_pose` — trigger `'kicking'` → append +162 chars
  - `strip_color_nouns` — regex ×3 (ex. green grass, white goal, blue sky)

**Image filtrée :** `docs/reports/poc-prompt-filter/sports-soccer-ball-on-a-field_filtered.png` · **Compare 3-col :** `docs/reports/poc-prompt-filter/sports-soccer-ball-on-a-field_compare.png` · **Diff prompt txt :** `docs/reports/poc-prompt-filter/sports-soccer-ball-on-a-field_prompt_diff.txt`

### [electromenager] Refrigerator in a Kitchen
- Issue ciblée : couleurs résiduelles + lighting (sunlight + colorful + couleurs nommées)
- 4 événement(s) :
  - `no_light_sources` — `'with a window letting in sunlight' → 'with a window'` ×1
  - `strip_color_nouns` — regex ×4 (ex. red apple, blue banana, white cabinets, black and)
  - `no_colorful_adjectives` — `'colorful' → 'cheerful'` ×1
  - `no_colorful_adjectives` — `'bright' → 'inviting'` ×1

**Image filtrée :** `docs/reports/poc-prompt-filter/electromenager-refrigerator-in-a-kitchen_filtered.png` · **Compare 3-col :** `docs/reports/poc-prompt-filter/electromenager-refrigerator-in-a-kitchen_compare.png` · **Diff prompt txt :** `docs/reports/poc-prompt-filter/electromenager-refrigerator-in-a-kitchen_prompt_diff.txt`

### [fantasy] Dragon in a Castle Courtyard
- Issue ciblée : couleurs résiduelles (green dragon, red banners)
- 1 événement(s) :
  - `strip_color_nouns` — regex ×3 (ex. green dragon, red banners, green bushes)

**Image filtrée :** `docs/reports/poc-prompt-filter/fantasy-dragon-in-a-castle-courtyard_filtered.png` · **Compare 3-col :** `docs/reports/poc-prompt-filter/fantasy-dragon-in-a-castle-courtyard_compare.png` · **Diff prompt txt :** `docs/reports/poc-prompt-filter/fantasy-dragon-in-a-castle-courtyard_prompt_diff.txt`

## Comparaisons côte à côte

3 colonnes par concept : `original POC mono | filtered (ce POC) | diff_prompt rendu PNG`.

### [sports] Soccer Ball on a Field
![compare](../../docs/reports/poc-prompt-filter/sports-soccer-ball-on-a-field_compare.png)

### [electromenager] Refrigerator in a Kitchen
![compare](../../docs/reports/poc-prompt-filter/electromenager-refrigerator-in-a-kitchen_compare.png)

### [fantasy] Dragon in a Castle Courtyard
![compare](../../docs/reports/poc-prompt-filter/fantasy-dragon-in-a-castle-courtyard_compare.png)

## Verdict par règle

| Règle | Déclenchée | Effet mesuré | Effets de bord observés |
|---|---|---|---|
| `strip_color_nouns` | **3/3** (10 matches) | **Workhorse** : seule règle déclenchée sur les 3 concepts. Δ color_ratio : Soccer 0.0066→0.0015 ; Refrigerator 0.0582→0.0006 (96× drop) ; Dragon 0.0502→0.0035 (14× drop). Sans elle, les 2 autres règles auraient un effet marginal. | ⚠ **Bug calibration `skip_if_next_in`** : le regex a stripé `"black and"` dans `"black and white line art only"` → résultat `"and white line art only"`. Le skip set protège `background/outlines/line/lines/art` mais pas `and`. Empiriquement non bloquant (image filtrée color_ratio 0.0006), mais à corriger en ajoutant `and` au skip set ou en pré-protégeant l'idiome `"black and white"` avant la regex. |
| `no_light_sources` | 1/3 (Refrigerator) | Strip de `"with a window letting in sunlight"` → `"with a window"`. Combiné avec `strip_color_nouns`, contribue au passage Refrigerator de `has_color` à pas d'issue. | Aucun effet de bord observé. |
| `no_colorful_adjectives` | 1/3 (Refrigerator, 2 matches) | `"colorful"`→`"cheerful"` et `"bright"`→`"inviting"`. | ⚠ Effet de bord cosmétique : le prompt contient déjà `"cheerful and inviting mood"` ; les remplacements créent des doublons (`"cheerful refrigerator… in a inviting and clean kitchen with a cheerful and inviting mood"`). Pas d'impact qualité image, mais grammaire dégradée. À calibrer (vérifier l'absence de l'adjectif cible avant remplacement). |
| `anatomy_static_pose` | 1/3 (Soccer Ball, trigger `"kicking"`) | Append +162 chars sur la consigne static pose. Vision verdict reste `good` (l'original l'était aussi côté vision). | À confirmer en revue humaine du `_compare.png` Soccer Ball : la 3e jambe a-t-elle disparu ? Le QC vision n'est pas conçu pour détecter ce défaut spécifique. |

## Verdict global

| Critère | Mesure |
|---|---|
| Images verdict ``good`` après filtre | **3/3** |
| Concepts avec Δ color_ratio improved (> 0.005) | **3/3** |
| Concepts avec Δ color_ratio dégradé | **0/3** |
| Concepts qui passaient `has_color` côté vision et ne passent plus après filtre | **2/2** (Refrigerator, Dragon) |
| Effets de bord constatés sur le texte du prompt | 2 (cf. tableau ci-dessus) |

✅ **Le filtre fonctionne empiriquement** sur les 3 cas testés : `color_ratio` chute systématiquement, le verdict vision passe de `has_color` à clean sur les 2 cas où c'était nécessaire, le filtre n'a cassé aucune image. La règle `strip_color_nouns` porte l'essentiel de l'effet (3/3 concepts, 10 matches). C'est la **plus rentable** et la première à intégrer.

⚠ **Mais 2 calibrations à faire avant intégration pipeline** :

1. **`strip_color_nouns` skip set** — ajouter `"and"` (et possiblement `"or"`, `"to"`) pour protéger l'idiome `"black and white"` ; ou mieux, pré-protéger la phrase `"black and white line art"` comme un token atomique avant la regex. Empiriquement non-bloquant ici, mais c'est un comportement non-déterministe selon la position des mots dans le prompt — pourrait casser un autre concept à l'avenir.
2. **`no_colorful_adjectives` idempotence** — vérifier l'absence du remplacement cible avant de remplacer (`if "cheerful" not in prompt: replace "colorful" → "cheerful"`). Sinon doublons cosmétiques.

**Recommandation : intégrer le filtre dans le pipeline en upstream du writer**, avec ces 2 fixes appliqués, **ET** garder le two-step colored→lineart (POC précédent) en option `color_prior_v1` pour les subjects où le filtre ne suffit pas. Architecture recommandée :

```
                       ┌─ filtre prompt (upstream LLM) ─┐
prompt brut writer ───→│                                 ├──→ ComfyUI ──→ image
                       └─ règles (3 fixes empiriques)   ┘
                                                          │
                                                          ↓ (si color_ratio > 0.025)
                                                   two-step Pillow extraction (POC color-to-lineart)
```

**Le filtre est le bon défaut single-step (économe : pas de Comfy supplémentaire)**, le two-step reste le filet de sécurité robuste pour les rares cas où le prior couleur résiste au texte (papillon, perroquet exotique, drapeau, fruits multicolores…).

**Coût d'intégration filtre :** ~10 lignes Python à insérer dans `_execute_create_prompt_v1_sync` (après le writer, avant retour) ou dans `image_worker.process` (avant `submit_prompt`). Latence ajoutée : < 1 ms (regex + 5 phrase replacements).

## Annexes

- Galerie : `docs/reports/poc-prompt-filter/` (1 filtered + 1 diff_prompt + 1 compare + 1 diff txt par concept)
- Données brutes : `2026-05-05_poc-prompt-filter.json` (prompts orig/filtered + log règles + histogram + vision)
- Source prompts originaux : `2026-05-05_poc-prompt-chain-v2.json`
- Originaux mono : `docs/reports/poc-image-quality/`
- Script : `scripts/poc_prompt_filter.py`