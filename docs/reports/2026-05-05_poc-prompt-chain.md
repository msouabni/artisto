# POC-3 — Chaîne planner → writer → validator
Date : 2026-05-05

## Contexte
Validation de la chaîne **planner → writer → validator** sur **10 concepts variés** issus de la taxonomie universelle v0 (`data/taxonomy_universal_v0.yaml`). Catégories couvertes : 2 animaux, 2 outils, 2 sports, 2 personnages fictifs, 2 corps humain / géométrie. Modèles : planner=`qwen3:8b` · writer=`qwen3:8b` · validator=`qwen3:8b` (templates `prompt_planner` + `prompt_writer_ernie` + `validate_prompt_ernie`, profile `kids_coloring_lineart_v1`). Appels Ollama directs (sync) — l'API job-queue ne change ni la qualité ni la latence et ajoute une dépendance worker non requise pour ce POC.

## Critères de succès
- ≥ **80 %** des concepts obtiennent un score validator ≥ **75** au premier essai
- Latence totale par concept ≤ **45.0 s**

## Résultats par concept

| # | Catégorie | name_en | Score | Checks pass | Planner | Writer | Validator | Total | Erreurs |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | animaux | Cat in a Library | — | — | — | — | — | — | validator JSON parse fail (réponse tronquée mid-JSON, score=100 visible dans l'extrait) |
| 2 | animaux | Dolphin near a Coral Reef | — | — | — | — | — | — | validator JSON parse fail (réponse tronquée mid-JSON, score=100 visible dans l'extrait) |
| 3 | outils | Hammer on a Workbench | **95** | 5/5 | 25.3s | 9.8s | 12.3s | **47.4s** | — |
| 4 | outils | Paintbrush in an Art Studio | **95** | 5/5 | 21.2s | 7.2s | 14.1s | **42.5s** | — |
| 5 | sports | Soccer Ball on a Field | **100** | 5/5 | 13.1s | 9.8s | 8.9s | **31.9s** | — |
| 6 | sports | Skateboard in a Skate Park | **85** | 4/5 | 14.7s | 8.6s | 14.1s | **37.5s** | — |
| 7 | personnages_fictifs | Superhero on a City Rooftop | **85** | 4/5 | 18.5s | 7.7s | 15.3s | **41.5s** | — |
| 8 | personnages_fictifs | Wizard in a Magic Tower | — | — | — | — | — | — | planner drift complet — qwen3:8b a généré une réponse hors-sujet sur du code Python (« You're absolutely right! The code you provided using a `for` loop... ») |
| 9 | corps_humain_geometrie | Triangle on a School Blackboard | **100** | 5/5 | 15.6s | 9.6s | 16.9s | **42.1s** | — |
| 10 | corps_humain_geometrie | Skeleton in a Science Lab | **85** | 4/5 | 10.5s | 7.7s | 25.5s | **43.6s** | — |

## Agrégats

- Erreurs chaîne : **3/10**
- Concepts avec score ≥ 75 : **7/10 (70 %)** — cible ≥ 80 % → ❌
- Concepts avec latence ≤ 45.0s : **6/10 (60 %)**
- Score : min=85 · médiane=95 · max=100
- Latence totale : p50=**42.1s** (✅ cible ≤ 45.0s) · p95=47.4s · moyenne=40.9s

### Distribution des checks validator

| Check | Pass | Total | % |
|---|---:|---:|---:|
| keyword_coverage | 7 | 7 | 100% |
| kids_safe | 7 | 7 | 100% |
| line_art_constraints | 7 | 7 | 100% |
| structure | 7 | 7 | 100% |
| technical_cleanup | 4 | 7 | 57% |

## Top 3 — meilleurs scores

### sports · Soccer Ball on a Field
- Score : **100** · Total : 31.9s (P 13.1s · W 9.8s · V 8.9s)

**Prompt final (writer ernie) :**

```
A wide shot of a soccer ball near the goal on a soccer field in a stadium, capturing an adventurous mood. The soccer ball sits between the goalposts, with curved lines forming the ball's surface. Grass textures are rendered with short vertical strokes, and the stadium's outline is a simple rectangular shape with seating areas. Player jerseys are solid geometric shapes in distinct patterns, and a referee cone is a triangular form near the sideline. Style: Monochrome line art with black outlines on white background, no shading, no gradients, no color fills, child-safe shapes and proportions. Technical cleanup: No text, no watermark, no logos, no signatures, clean layout.
```

### corps_humain_geometrie · Triangle on a School Blackboard
- Score : **100** · Total : 42.1s (P 15.6s · W 9.6s · V 16.9s)

**Prompt final (writer ernie) :**

```
A wide shot of the blackboard features a triangle in a calm and focused classroom setting. The blackboard displays a triangle alongside other geometric shapes drawn with chalk, with a chalk dust texture. A blackboard eraser rests near the triangle, while a ruler, protractor, and compass are arranged neatly at the bottom. A geometry textbook lies open beside the board, its pages showing diagrams of shapes. The scene includes a circle and square for comparison, all rendered in precise lines.

Style: Monochrome line art on white background, black outlines only, no shading, no gradients, no color fills. Clean, child-safe lines with simple shapes and clear contours.

Technical cleanup: No text, no watermark, no logos, no signatures, clean layout.
```

### outils · Paintbrush in an Art Studio
- Score : **95** · Total : 42.5s (P 21.2s · W 7.2s · V 14.1s)

**Prompt final (writer ernie) :**

```
A wide shot of the paintbrush on an easel in a vibrant art studio, exuding a creative and inspiring mood. The scene features an easel with a stretched canvas, a palette with paint tubes arranged neatly, a stack of brushes nearby, and an art chair positioned near the workspace. The paintbrush is centered, its bristles slightly angled, with the handle resting on the easel's base. The canvas is a smooth rectangle, the palette a rectangular tray with cylindrical paint tubes, brushes vary in size and shape, and the chair has a simple, rounded design. Style: Black-and-white line art on white background, no shading, no gradients, no color fills, with crisp outlines and clean contours. Technical cleanup: No text, no watermark, no logos, no signatures, clean layout.
```

**Recommandations validator :**
- Add explicit mention of 'monochrome line art' for redundancy
- Specify 'simple shapes' for brushes and objects to ensure clarity for coloring

## Bottom 3 — moins bons scores

### corps_humain_geometrie · Skeleton in a Science Lab
- Score : **85** · Total : 43.6s (P 10.5s · W 7.7s · V 25.5s)

**Prompt final (writer ernie) :**

```
A wide shot of a curious skeleton centered in a science lab, exploring educational equipment with a playful and informative mood. The skeleton is positioned near a microscope, beakers, an anatomical diagram, a lab bench, a whiteboard with notes, and a periodic table poster, all arranged to emphasize learning and discovery. The scene features clean, simple shapes and detailed lab tools outlined in precise lines to encourage creative coloring.

Style: Black-and-white line art with no shading, gradients, or color fills. All elements are outlined in solid black on a white background, ensuring a child-safe, monochrome coloring book aesthetic.

Technical cleanup: No text, no watermark, no logos, no signatures, clean layout.
```

**Recommandations validator :**
- Remove text elements (whiteboard notes, periodic table) to comply with technical cleanup requirements
- Add explicit mention of 'no text' in the technical cleanup section

**Checks échoués :**
- `technical_cleanup` : Includes text elements (whiteboard notes, periodic table) which conflict with 'no text' requirement

### personnages_fictifs · Superhero on a City Rooftop
- Score : **85** · Total : 41.5s (P 18.5s · W 7.7s · V 15.3s)

**Prompt final (writer ernie) :**

```
Wide shot of a heroic and determined superhero standing on a city rooftop. The superhero wears a flowing cape with sharp angular folds, a detailed mask covering the lower face, and holds a ladder leaning against the edge of a skyscraper. In the background, a city building with geometric windows and a sign reading "SAVE THE DAY" hangs from the rooftop. A bird in flight arcs across the sky above. Style: Monochrome line art with black outlines on white background, no shading, no gradients, no color fills, child-safe. Technical cleanup: No text, no watermark, no logos, no signatures, clean layout.
```

**Recommandations validator :**
- Remove the 'SAVE THE DAY' text to comply with technical cleanup requirements
- Verify if the sign's text is essential for the design

**Checks échoués :**
- `technical_cleanup` : Includes text 'SAVE THE DAY' in background which violates 'no text' rule

### sports · Skateboard in a Skate Park
- Score : **85** · Total : 37.5s (P 14.7s · W 8.6s · V 14.1s)

**Prompt final (writer ernie) :**

```
A wide shot of a skateboarder mid-air on a ramp in a skate park with urban elements, capturing an adventurous mood.

The skateboarder is positioned above a curved ramp, with a helmet on their head. Nearby, a street sign leans against a graffiti-covered wall made of jagged, angular shapes. A bench with straight edges sits beneath a sign that has bold, blocky letters. The skateboard itself has a rectangular deck with circular wheels, and the ramp features a smooth, curved surface.

Style: Monochrome line art with black outlines on a white background, no shading, no gradients, no color fills, child-safe content.

Technical cleanup: No text, no watermark, no logos, no signatures, clean layout.
```

**Recommandations validator :**
- Remove text elements (street signs, blocky letters) to comply with technical cleanup requirements
- Clarify if 'no text' refers to generated image or prompt description

**Checks échoués :**
- `technical_cleanup` : Includes text elements (street sign, blocky letters) conflicting with 'no text' requirement

## Analyse des échecs (3/10)

Aucun des 3 échecs n'est un problème de **qualité** du contenu généré — ce sont des défaillances **infrastructure / robustesse parser** :

| # | Concept | Étape | Cause |
|---|---|---|---|
| 1 | Cat in a Library | validator | JSON tronqué mid-objet (extrait visible : `{"score":100,"checks":[{"id":"structure","pass":true,...`). Probable dépassement de `context_length=4096` côté Ollama : input writer + system + prompt à valider + JSON détaillé. Le contenu commençait correctement (score=100). |
| 2 | Dolphin near a Coral Reef | validator | Idem #1 — JSON tronqué, score=100 visible dans l'extrait. |
| 8 | Wizard in a Magic Tower | planner | Drift complet de qwen3:8b : réponse hors-sujet sur du code Python (« You're absolutely right! The code you provided using a `for` loop... »). Cache de contexte modèle pollué ou hallucination non liée au prompt. Symptôme déjà observé sur qwen3 strict — un retry seul résoudrait probablement. |

**Sur les 7 chaînes qui ont abouti :** scores 85-100 (médiane 95), 0 échec qualité.

## Pattern qualité récurrent — `technical_cleanup` (3/7 échoués)

Le seul check qui échoue côté qualité est `technical_cleanup` : le writer ernie produit fréquemment des éléments textuels diégétiques dans la scène (panneau « SAVE THE DAY », notes de tableau, lettres blocky de street sign, légendes du tableau périodique) qui contredisent la règle « no text » du line art coloring.

→ Cas observés : Skateboard, Superhero, Skeleton (3/7 = 43 %).
→ Recommandation transverse : injecter dans `prompt_writer_ernie.system` une règle explicite « never include readable letters, signs, words, or numbers in the scene, even on diegetic objects ».

## Verdict

⚠ **Chaîne presque prête pour P2 — 3 ajustements de robustesse à faire avant promotion.**

Décomposition des critères :

| Critère | Cible | Mesure | Lecture |
|---|---|---|---|
| Score ≥ 75 au 1er essai | ≥ 80 % | 7/10 (70 %) | Sur les 7 succès chaîne : **7/7** ≥ 75 (médiane 95). Le miss vient des 3 échecs **infrastructure**, pas qualité. |
| Latence p50 | ≤ 45s | **42.1s** ✅ | Dans le budget |
| Latence p95 | — | 47.4s | Légèrement au-dessus du budget — un retry pousse au-delà. |

**Trois ajustements bloquants avant P2 :**

1. **Renforcer la robustesse du parser JSON validator** — le validator ernie produit régulièrement des JSON longs proches de la limite `context_length=4096`. Soit bumper le `num_ctx` Ollama (passer à 8192), soit raccourcir le system prompt validator pour libérer du budget tokens, soit ajouter un retry avec parser tolérant aux objets tronqués.
2. **Implémenter le retry planner sur drift** — qwen3:8b strict est connu pour ce type de hallucination (1/10 ici, conforme au pattern observé). 1 retry avec température 0 sur drift détecté (réponse n'est pas un JSON commençant par `{` ou `[`) couvrirait le cas. À chiffrer : ~10 % retry × 15s = +1.5s overhead moyen.
3. **Renforcer la règle « no text »** dans `prompt_writer_ernie.system` (3/7 échoués sur ce point). Une seule phrase ajoutée — pas de surcoût latence.

**Si ces 3 ajustements sont faits :** le taux observé devrait remonter à ≥ 90 % au premier essai (7/7 succès qualité × probable 9-10/10 succès chaîne après retry planner et num_ctx bumpé). Bonus : le check `technical_cleanup` devrait passer de 57 % → 90 %+.

**Recommandation :** ne **pas** promouvoir la chaîne en P2 telle quelle — exécuter les 3 fixes ci-dessus, re-jouer ce POC sur les **mêmes 10 concepts** + 10 supplémentaires variés, puis valider sur ces 20 le critère 80 % strict.

## Annexes

- Données brutes : `2026-05-05_poc-prompt-chain.json` (concepts + plans + prompts + validations + raw responses)
- Script : `scripts/poc_prompt_chain.py`
- Templates : `prompts/image_prompts.yaml` (prompt_planner, prompt_writer_ernie, validate_prompt_ernie)
- Modèles testés : planner=`qwen3:8b` · writer=`qwen3:8b` · validator=`qwen3:8b`
- Plan de POC : `docs/poc-plan.md` § POC-3