# Note pour l'équipe skill — vérification insight ERNIE variation/répétition

Date : 2026-05-10
Source : architecte / PMO Artiste Coloriage
Contexte : sujet H4 du handoff `docs/architect/handoff-2026-05-10.md`

## Insight observé

ERNIE est **fort en variation libre**, **faible en répétition stricte**.

Les 4 workflow_classes multi-cellules actuellement gérées par le `PromptGenerator` exigent une **répétition stricte avec un changement contrôlé par cellule** :

- `Grille imagier annoté` (template `template_grid_3x3_annotated`)
- `Imagier différencié 3×3` (template `template_grid_3x3_imagier`)
- `Frise narrative 1×N` (template `template_frieze_1xN`)
- `Multi-sujets via grille` (méta-pattern §2)

→ C'est ramer contre le modèle.

## Évidence empirique

Sur les 4 classes méta-patterns dans `docs/reports/poc-scale-benchmark/annotations.json` :
- **130+ tags** `image_pas_coherente` + `image_incomprehensible` cumulés
- Les 2 tags émergents les plus fréquents (66 et 64 occurrences) signalent un mismatch demande/capacité ERNIE non cartographié dans le skill actuel

## Questions à l'équipe skill

1. **Confirmation de l'insight** : observez-vous le même comportement (variation forte / répétition faible) sur d'autres usages d'ERNIE hors line-art coloriage ?
2. **Levier d'orientation** : existe-t-il une formulation de prompt qui force la répétition stricte de manière fiable (séparateurs, conditioning, regional prompting) ? Ou le modèle reste-t-il fondamentalement "variation-first" ?
3. **Stabilité dans le temps** : cet insight est-il robuste aux versions ERNIE futures, ou susceptible de bouger avec une mise à jour de checkpoint ?

## Pivot produit envisagé

Si l'insight est confirmé : réorienter les 4 workflow_classes ci-dessus vers un format **"jeu des différences"** qui exploite la variation native d'ERNIE plutôt que la répétition contrainte — la consigne pédagogique ("un changement par étape") serait libérée vers une consigne plus large ("trouve les différences entre ces N variations").

## Décision attendue

L'équipe skill peut répondre :
- **OK insight confirmé** → on cadre un brief de pivot des 4 templates
- **À nuancer** → on garde l'orientation actuelle mais on documente le mismatch comme attendu (capitalisation skill sans pivot)
- **À invalider** → contre-évidence factuelle ou levier de prompt méconnu de notre côté

## Artefacts pour analyse

- Templates concernés : `src/services/prompt_generator.py` lignes 388-432 (`template_grid_3x3_imagier`, `template_grid_3x3_annotated`, `template_frieze_1xN`)
- Annotations brutes : `docs/reports/poc-scale-benchmark/annotations.json` (filtrer sur les 4 classes ci-dessus)
- Insight mémoire user : `project_ernie_variation_insight.md`

Pas urgent — la décision H3 (test des 31 classes confidence non-Haute) en dépend mais l'échéance peut bouger en fonction du retour skill.
