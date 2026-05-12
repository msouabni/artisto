# Pivot templates narratifs → jeu des différences (T25)
Date : 2026-05-10

## Contexte

Le `PromptGenerator` appliquait deux templates à répétition stricte sur des
`workflow_class` narratives (`template_frieze_1xN` et `template_grid_3x3_imagier`).
Les annotations `poc-scale-benchmark` (130+ tags `image_pas_coherente` /
`image_incomprehensible` sur les 4 méta-patterns multi-cellules) ont validé
empiriquement qu'ERNIE est **variation-first** : la consigne de répétition rame
contre le modèle. Le pattern T25 du skill `prompt-taxonomy-ecosystem`
(jeu des différences BEFORE/AFTER + SPOT THE DIFFERENCE) exploite cette
variation native plutôt que de la combattre.

Brief : `docs/architect/briefs/2026-05-10_brief-pivot-templates-narratifs-jeu-differences.md`.

## Templates modifiés

`src/services/prompt_generator.py` — corps remplacés ; signatures et noms inchangés.

| Fonction | Avant | Après |
|---|---|---|
| `template_frieze_1xN(leaf, strategy, n=4)` | Frise narrative 1×N (rangée de N cellules, chacune une étape) | T25 BEFORE/AFTER (2 cellules, scène initiale vs scène avec différences cachées). Param `n` conservé pour compat de signature, plus utilisé. |
| `template_grid_3x3_imagier(leaf, strategy)` | Grille 3×3 (9 cellules tic-tac-toe, 1 item par cellule) | T25 SPOT THE DIFFERENCE (2 cellules, scène complète vs scène avec différences cachées). |

`TEMPLATE_DISPATCHER` **inchangé** (vérifié par diff). `template_grid_3x3_annotated`
(Imagier annoté 3×3, X6 OK) **inchangé**. Aucune modification de la cartographie
ni du skill.

## Périmètre — workflow_classes et leaves impactées

### `template_frieze_1xN` (6 workflow_classes, ~53 leaves)

| workflow_class | sous-catégorie | n leaves |
|---|---|---|
| `Frise narrative 1×4` | `four_seasons` | 8 |
| `Frise narrative 1×N (pattern X2)` | `life_cycle_and_aging` | 8 |
| `Multi-sujets` | `diversity_and_inclusion` | 7 |
| `Multi-sujets (frise)` | `school_life` | 10 |
| `Multi-sujets ou Scène` | `national_teams_and_clubs` | 9 |
| `Multi-sujets ou Scène d'action` | `team_sports` | 11 |

### `template_grid_3x3_imagier` (3 workflow_classes, 4 sous-catégories, ~38 leaves)

| workflow_class | sous-catégorie(s) | n leaves |
|---|---|---|
| `Imagier différencié 3×3` | `food_categories` | 8 |
| `Imagier différencié OU Solo` | `healthy_eating` | 7 |
| `Multi-sujets via grille (méta-pattern §2)` | `illustrated_numbers` (12), `decorative_numbers` (11) | 23 |

**Total impact ~91 leaves** sur 9 workflow_classes / 10 sous-catégories.

## Tests

### Critères acceptation (brief) — état

- ✅ Les deux fonctions modifiées renvoient la string T25 attendue (verification dans les 6 prompts ci-dessous).
- ✅ `template_grid_3x3_annotated` inchangé.
- ✅ `TEMPLATE_DISPATCHER` inchangé.
- ✅ Smoke test `PromptGenerator().build_prompt('lion_in_savanna')` OK (workflow_class `Solo animal`, hors pivot — non régressé).
- ✅ 3+3 prompts de test inspectés (cf. infra).
- ✅ Pas de génération massive (uniquement smoke + 6 prompts de structure).
- ✅ Pas de modif cartographie / skill.
- ✅ pytest non régressé : `tests/test_prompt_generator.py` 14/14 verts. 5 échecs préexistants (workflow Ernie / negative-prompt) déjà documentés en dette technique (MEMORY architecte ligne 79) — sans rapport avec l'edit.

### 3 prompts `template_frieze_1xN`

**`baby_first_year`** (workflow_class : `Frise narrative 1×N (pattern X2)`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows Baby First Year in its initial state, the right cell shows the same scene with several differences hidden inside, uniform black line thickness, full scene visible, centered composition

**`spring_blooming_meadow`** (workflow_class : `Frise narrative 1×4`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows Spring Blooming Meadow in its initial state, the right cell shows the same scene with several differences hidden inside, uniform black line thickness, full scene visible, centered composition

**`football_match_scene`** (workflow_class : `Multi-sujets ou Scène d'action`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side separated by a thick black vertical line, the word "BEFORE" written above the left cell, the word "AFTER" written above the right cell, the left cell shows Football Match Scene in its initial state, the right cell shows the same scene with several differences hidden inside, uniform black line thickness, full scene visible, centered composition

### 3 prompts `template_grid_3x3_imagier`

**`fruits_basket`** (workflow_class : `Imagier différencié 3×3`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side separated by a thick black vertical line, the word "SPOT THE DIFFERENCE" written above both cells, the left cell shows Fruits Basket scene with all elements clearly visible, the right cell shows the same scene with several differences hidden inside, uniform black line thickness, full scene visible, centered composition

**`food_pyramid_for_kids`** (workflow_class : `Imagier différencié OU Solo`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side separated by a thick black vertical line, the word "SPOT THE DIFFERENCE" written above both cells, the left cell shows Food Pyramid for Kids scene with all elements clearly visible, the right cell shows the same scene with several differences hidden inside, uniform black line thickness, full scene visible, centered composition

**`number_zero_with_eggs`** (workflow_class : `Multi-sujets via grille (méta-pattern §2)`)
> coloring book page for kids, black and white line art, thick clean outlines, no shading, no fill, white background, a horizontal grid of two large rectangular cells side by side separated by a thick black vertical line, the word "SPOT THE DIFFERENCE" written above both cells, the left cell shows Number Zero with Eggs scene with all elements clearly visible, the right cell shows the same scene with several differences hidden inside, uniform black line thickness, full scene visible, centered composition

Script de smoke réutilisable : `scripts/smoke_pivot_t25.py` (jetable, lié à ce brief).

## Points d'attention

1. **Décision archi par défaut retenue** (brief l. 102-107) : remplacement de
   `template_grid_3x3_imagier` (et non d'une fonction `template_grid_multisujets`
   qui n'existe pas dans le code). Cohérent avec le mapping
   `Multi-sujets via grille (méta-pattern §2) → template_grid_3x3_imagier` dans
   `TEMPLATE_DISPATCHER` (l. 644). Si l'équipe skill voulait viser une nouvelle
   fonction, il faudra créer une fonction dédiée dans un cycle ultérieur et ajuster
   le dispatcher.

2. **Doublon fonctionnel à terme** entre `template_frieze_1xN` (post-pivot T25
   BEFORE/AFTER) et `template_before_after` existant (l. 535-548). Les deux
   produisent maintenant des prompts BEFORE/AFTER ; les variantes diffèrent
   marginalement (`name_en` vs `name.lower()`, "several differences hidden inside"
   vs "one single change applied", "uniform black line thickness" en clôture vs
   plus verbeux). À consolider en cycle ultérieur si on confirme la pertinence du
   pivot — hors scope ici par le brief (« Pas de refactor des autres templates »).

3. **Constante `DEFAULT_BEFORE_AFTER_STATES` (l. 51) déjà présente dans le fichier**
   en arrivant — vient d'un brief T25 distinct en parallèle
   (`brief-transfert-T25-before-after.md`) qui prévoit un fichier
   `data/prompt_generator/before_after_states.json` curaté pour piloter
   `template_before_after`. **Inutilisée par mes templates pivotés** : le brief
   « jeu des différences » ne demande explicitement aucune donnée externe, juste
   le `name_en` au runtime. Coordination architecte requise pour réconcilier les
   deux briefs T25 (refactor commun ou conservation des deux pistes).

4. **Heuristique titre supprimée** : l'ancien `template_grid_3x3_imagier` posait
   `title = leaf['name_en'].upper().split(' ')[0]` pour afficher le premier mot
   du nom dans la grille. Le nouveau corps utilise `name_en` complet (pas
   d'upper/split). Conforme au brief — à noter pour la revue empirique
   (`Fruits Basket` au lieu de `FRUITS`).

5. **Param `n=4` de `template_frieze_1xN` désormais ignoré** : conservé par le
   brief « pour compat même s'il n'est plus utilisé ». Aucun appel direct
   identifié hors `TEMPLATE_DISPATCHER` qui n'utilise pas cet argument.
   Sans risque immédiat.

6. **Garde-fou ERNIE explicite (cf. démarche transferts skill)** : si un bench
   ultérieur démontre un fix < 30 % du taux `image_pas_coherente` /
   `image_incomprehensible` sur les 4 méta-patterns, T25 est à reporter au
   canal manuel T19+. Aucun bench n'est inclus dans ce cycle (brief explicite
   « Pas de génération massive ou de scale-bench »).

## Décision / Action suivante

- **Livré** : pivot des 2 templates en place, 6 prompts inspectés, pytest
  `prompt_generator` 14/14 verts, aucune régression introduite.
- **À l'architecte** : valider la décision par défaut (point 1), arbitrer la
  réconciliation avec le brief T25 parallèle (point 3), planifier le bench de
  validation T25 sur méta-patterns (point 6 — garde-fou ERNIE).
- **Hors scope, à backlog** : déduplication `template_frieze_1xN` ⇆
  `template_before_after` (point 2), intégration éventuelle de
  `before_after_states.json` dans les deux templates pivotés (point 3).
