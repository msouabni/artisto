# Brief — Pivot templates narratifs vers "jeu des différences" (T25)

Date : 2026-05-10
Auteur : architecte / PMO
Destinataire : claude-code dev
Source : retour équipe skill (insight ERNIE variation/répétition validé) — réponse 2026-05-10
Note architecte : `docs/architect/notes/2026-05-10_note-skill-insight-ernie-variation.md`

## Contexte

Le `PromptGenerator` applique deux templates à **répétition stricte** sur des workflow_classes narratives :

- `template_frieze_1xN` — frise 1×N
- `template_grid_3x3_imagier` (mappé sur `Multi-sujets via grille (méta-pattern §2)` dans `TEMPLATE_DISPATCHER`)

Validation empirique (annotations `poc-scale-benchmark`) : **130+ tags `image_pas_coherente` + `image_incomprehensible`** sur les 4 méta-patterns multi-cellules. ERNIE est **variation-first** (validé skill 2026-05-10) — la consigne de répétition contrainte rame contre le modèle.

Le pattern **T25 (jeu des différences)** documenté dans `.claude/skills/prompt-taxonomy-ecosystem.skill` (références/techniques.md) exploite la variation native d'ERNIE en remplaçant la consigne stricte par une consigne **BEFORE/AFTER avec différences cachées**.

## Objectif

Remplacer les deux templates ci-dessus dans `src/services/prompt_generator.py` par le pattern T25.

## Périmètre

### À lire avant de toucher

- `.claude/skills/prompt-taxonomy-ecosystem.skill` → `references/techniques.md` section T25 (référence canonique)
- `src/services/prompt_generator.py` :
  - `template_frieze_1xN` (l. 419 environ)
  - `template_grid_3x3_imagier` (l. 388 environ)
  - `TEMPLATE_DISPATCHER` (l. 501) — pour identifier les workflow_classes pointant vers ces deux fonctions
- `data/prompt_generator/taxonomy_production_cartography.json` — identifier toutes les leaves mappées sur ces deux workflow_classes

### À modifier

`src/services/prompt_generator.py` uniquement — les deux fonctions ci-dessus.

### À NE PAS modifier

- `template_grid_3x3_annotated` (Imagier annoté 3×3) — **inchangé**
- Tout autre template (`template_solo_*`, `template_human_plus_entity`, `template_landscape_2plane`, `template_pose_static`, etc.)
- `TEMPLATE_DISPATCHER` (les workflow_classes restent mappées sur les **mêmes** noms de fonctions ; seul le **corps** des deux fonctions change)
- La cartographie (`taxonomy_production_cartography.json`)
- Le skill (la maj est faite côté équipe skill)

## Implémentation

### Important — adaptation à la signature actuelle

Les fonctions templates dans `prompt_generator.py` sont des **fonctions module-level** (pas de méthodes), avec la signature :

```python
def template_xxx(leaf, strategy, ...):
    ...
```

`leaf` est le dict leaf complet (avec `name_en`, `name_fr`, etc.) et `strategy` est le dict `production_strategy`. Le retour est une **string** (le `positive`).

→ Le retour skill team utilise `def x(self, leaf_id, leaf_name_en, ...)` avec `self` ; **adapter à la signature actuelle**, accéder à `leaf_name_en` via `leaf.get("name_en")`, conserver les noms de fonctions actuels (`template_frieze_1xN` et `template_grid_3x3_imagier`) pour ne pas avoir à toucher au `TEMPLATE_DISPATCHER`.

### Nouveau corps `template_frieze_1xN`

Conserver la signature `def template_frieze_1xN(leaf, strategy, n=4):` (le param `n` reste en place pour compat même s'il n'est plus utilisé — ne pas casser des appels existants éventuels).

```python
def template_frieze_1xN(leaf, strategy, n=4):
    name_en = leaf.get("name_en") or leaf.get("id")
    return (
        f"coloring book page for kids, black and white line art, thick clean outlines, "
        f"no shading, no fill, white background, "
        f"a horizontal grid of two large rectangular cells side by side "
        f"separated by a thick black vertical line, "
        f"the word \"BEFORE\" written above the left cell, "
        f"the word \"AFTER\" written above the right cell, "
        f"the left cell shows {name_en} in its initial state, "
        f"the right cell shows the same scene with several differences hidden inside, "
        f"uniform black line thickness, full scene visible, centered composition"
    )
```

### Nouveau corps `template_grid_3x3_imagier`

Conserver la signature actuelle.

```python
def template_grid_3x3_imagier(leaf, strategy):
    name_en = leaf.get("name_en") or leaf.get("id")
    return (
        f"coloring book page for kids, black and white line art, thick clean outlines, "
        f"no shading, no fill, white background, "
        f"a horizontal grid of two large rectangular cells side by side "
        f"separated by a thick black vertical line, "
        f"the word \"SPOT THE DIFFERENCE\" written above both cells, "
        f"the left cell shows {name_en} scene with all elements clearly visible, "
        f"the right cell shows the same scene with several differences hidden inside, "
        f"uniform black line thickness, full scene visible, centered composition"
    )
```

### Si l'on veut garder l'ancien comportement de la grille 3×3 imagier différencié

Le commentaire skill team dit "**Templates imagier différencié 3×3 (`template_grid_3x3_imagier`) — inchangé**" mais nomme aussi `template_grid_multisujets` à modifier. Le code n'a **pas** de fonction `template_grid_multisujets` ; l'unique candidat code-réel pour "Multi-sujets via grille" est `template_grid_3x3_imagier`.

**Décision architecte à valider en début de tâche** : confirmer avec l'équipe skill (1 ligne de réponse) si le périmètre cible bien `template_grid_3x3_imagier`, ou si elle pensait à une fonction qui n'existe pas encore dans le code (auquel cas il faut créer une nouvelle fonction et adapter `TEMPLATE_DISPATCHER` au lieu de remplacer `template_grid_3x3_imagier`).

→ **Par défaut** : on remplace `template_grid_3x3_imagier` (option la plus probable au vu des évidences empiriques sur "Multi-sujets via grille").

## Critères d'acceptation

- [ ] Les deux fonctions modifiées renvoient la string T25 attendue (BEFORE/AFTER pour `template_frieze_1xN`, SPOT THE DIFFERENCE pour `template_grid_3x3_imagier`)
- [ ] `template_grid_3x3_annotated` inchangé (vérifier diff)
- [ ] `TEMPLATE_DISPATCHER` inchangé
- [ ] `python -c "from services.prompt_generator import PromptGenerator; g=PromptGenerator(); print(g.build_prompt('lion_in_savanna')['positive'][:80])"` (ou équivalent) tourne sans erreur — smoke test que l'import et le build fonctionnent
- [ ] **3 prompts de test par template** générés et inspectés pour vérifier la structure :
  - 3 leaves dont `production_strategy.class` ∈ workflow_classes routées vers `template_frieze_1xN`
  - 3 leaves dont `production_strategy.class` ∈ workflow_classes routées vers `template_grid_3x3_imagier`
- [ ] Pas de génération massive — 3 tests par template suffisent (génération coûteuse inutile à ce stade)
- [ ] Pas de modification de la cartographie
- [ ] Pas de modification du skill (la maj est portée par l'équipe skill)
- [ ] Tests pytest existants verts (pas de régression sur les autres templates)

## Reporting

Rapport obligatoire : `docs/reports/2026-05-10_pivot-templates-narratifs-jeu-differences.md`

Structure minimale :

```markdown
# Pivot templates narratifs → jeu des différences
Date : 2026-05-10

## Contexte
(reprendre 2-3 lignes du brief)

## Templates modifiés
- template_frieze_1xN → corps T25 BEFORE/AFTER
- template_grid_3x3_imagier → corps T25 SPOT THE DIFFERENCE

## Feuilles concernées
[liste des workflow_classes mappées sur ces deux fonctions dans TEMPLATE_DISPATCHER + nb estimé de leaves impactées via la cartographie]

## Tests
[3 prompts générés par template, copier-coller le positive complet]

## Points d'attention
[cas limites, feuilles qui ne s'adaptent pas bien au format BEFORE/AFTER, ou décision sur le périmètre exact si l'équipe skill confirme un autre nom de fonction]

## Décision / Action suivante
[OK pour intégration ; bench à lancer ; etc.]
```

## Hors scope

- Pas de génération massive ou de scale-bench (laisser à un cycle ultérieur après validation manuelle)
- Pas de modification du skill (déjà à jour côté équipe)
- Pas de refactor des autres templates
- Pas de mise à jour MEMORY.md (architecte s'en charge à la clôture)
- Pas de changement des paramètres image figés (`euler / 8 steps / cfg=1.0 / scheduler=normal`)

## Conventions à respecter

- Reporting obligatoire dans `docs/reports/`
- NULL-safe : `int(w) if w is not None else 0` avant tri (n'a probablement pas d'impact direct ici, juste un rappel)
- Editor HTML obligatoire pour tout YAML/JSON livrable (sans objet ici, pas de YAML/JSON modifié)
- Image : sampler=euler, steps=8, cfg=1.0, scheduler=normal **figés** — ne pas changer
- Pas de commit auto — l'architecte review puis valide

## Estimation dev

- Lecture skill T25 + identification workflow_classes : ~15 min
- Modification des 2 fonctions : ~10 min
- Smoke test + génération 3+3 prompts de test : ~10 min
- Rapport : ~10 min
- **Total ~45 min** (estimation skill team confirmée)
