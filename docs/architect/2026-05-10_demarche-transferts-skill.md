# Démarche — Transferts skill → PromptGenerator

Date : 2026-05-10
Source : `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md`
Posture : intégration fidèle, efficace, simplifiée si complexe, reportée si bloquant. Documentation continue. Intervention utilisateur minimisée.

## Contexte

Le rapport d'analyse 2026-05-10 a identifié **10 opportunités de transfert** skill → PromptGenerator (catégorie 🟡) et **5 candidats T19+** pour le canal manuel (catégorie 🔴). L'archi prend en charge l'ordonnancement, la rédaction des briefs Claude Code d'exécution, et le suivi.

## Règles d'arbitrage auto-appliquées

| Règle | Déclencheur | Action |
|---|---|---|
| Pas de PR fourre-tout | 1 transfert = 1 PR | Brief séparé par règle skill |
| Brief borné | Estimation > 90 min dev | Découper en plusieurs briefs |
| Bascule pipeline = canal manuel | Transfert nécessite changement architectural ERNIE (PIL/SVG, Pillow compose, etc.) | Reporter en T19+ canal manuel utilisateur |
| Volume bas | < 5 occurrences adressées | Reporter en backlog (notes prochain cycle) |
| Mesure post-transfert | Si critère de succès du brief non atteint | Reporter le complément en T19+ |
| Volume corpus canonique | Rapport indique 515 entrées (vs 222 brief initial) | **Baseline 515** — divergence notée, le brief initial a été conservateur |

## Ordre d'attaque

| # | Brief | Règle skill | Impact estimé | Risque | Statut |
|---|---|---|---:|---|---|
| 1 | `2026-05-10_brief-transfert-T9-orientation.md` | T9 (profil + orientation directionnelle) | 13 occ | Faible (fix mécanique sur 6 leafs Solo animal résiduels) | rédigé |
| 2 | `2026-05-10_brief-transfert-T2T3T23-grille-imagier.md` | T2 + T3 + T23 (templates Grille) | ~60 occ | **Risque pivot ERNIE** : si fix < seuil → reporter en T19+ #1 (bascule PIL/SVG) | rédigé |
| 3 | `2026-05-10_brief-transfert-T25-before-after.md` | T25 (Comparatif before/after) | ~28 occ | **Même risque pivot ERNIE** : si fix < seuil → reporter en T19+ #2 | rédigé |
| 4 | `2026-05-10_brief-transfert-isolation-elargi.md` | NEGATIVE_V3 + _ISOLATION élargi | ~12 occ image_duplication non-Solo-animal | Faible | rédigé |
| 5 | `2026-05-10_brief-transfert-T22-T27-T30-anatomie.md` | T22 + T27 + T30 | ~12 occ image_anatomie_pb | Moyen (mapping leaf → tenue à constituer) | rédigé |
| 6 | `2026-05-10_brief-transfert-T28-Z1-anatomique-labels.md` | T28 + Z1 | 6 occ + 4 occ | Faible (dépendance #2 si grille améliorée) | rédigé |
| 7 | `2026-05-10_brief-transfert-T26-T31-meteo-scenes.md` | T26 + T31 | ~7 occ | Faible | rédigé |
| 8 | `2026-05-10_brief-transfert-T5-T6-T7-couleur-surfaces.md` | T5 + T6 + T7 | Bas dans corpus actuel | Prophylactique | rédigé |

Briefs 4-8 : préparation conditionnelle aux résultats de 1-3. Si 1-3 livrés sans pivot ERNIE déclenché, on continue. Sinon on attend la décision archi/utilisateur sur le pivot.

## Délégation au canal manuel utilisateur

Reporté en T19+ pour MAJ skill par utilisateur :

| T19+ | Sujet | Pourquoi canal manuel |
|---|---|---|
| #1 | Méta-pattern grille = limite ERNIE | Décision archi pipeline (PIL/SVG vs ERNIE) — hors compétence transfert simple |
| #2 | Méta-pattern Comparatif = limite ERNIE | Idem |
| #3 | `image_simpliste` symptôme richesse insuffisante | Hypothèse à valider — pas une règle T validée |
| #4 | Pattern `number_N_with_X` | Extension skill nécessaire (pattern non indexé) |
| #5 | Quantification seuil `prompt_complexe` | Étude statistique — pas un transfert simple |

L'utilisateur peut porter ces 5 prototypes (déjà rédigés au format skill dans le rapport d'analyse §4) au canal manuel à son rythme. Chaque T19+ retournée → nouveau brief de transfert ici.

Un T19+ vocabulaire v2/v1 (4 tags émergents non mappés) est aussi en attente. Posture pragmatique : laissé hors-priorité car ça n'adresse aucune occurrence de défaut.

## Suivi

| Brief | Rédigé | Lancé | Livré | Mesure post |
|---|:--:|:--:|:--:|---|
| T9 orientation | ✅ 2026-05-10 | — | — | À mesurer : rerun ComfyUI sur 6 leafs résiduels, comparer image_duplication v3 vs v2 |
| T2+T3+T23 grille | ✅ 2026-05-10 | — | — | À mesurer (obligatoire — garde-fou ERNIE) : rerun sur 8-10 leafs grille, comparer image_pas_coherente baseline 91-100% |
| T25 before/after | ✅ 2026-05-10 | — | — | À mesurer (obligatoire — garde-fou ERNIE) : rerun sur 6-8 leafs comparatif, comparer baseline 89% |
| _ISOLATION élargi | ✅ 2026-05-10 | — | — | Optionnel : rerun sur 8 leafs `image_duplication` non-Solo-animal |
| T22+T27+T30 anatomie | ✅ 2026-05-10 | — | — | Optionnel recommandé : rerun sur 12 leafs anatomie |
| T28+Z1 anatomique+labels | ✅ 2026-05-10 | — | — | Optionnel : rerun sur 5 organes sensoriels + 4 anatomique+labels |
| T26+T31 météo / scènes | ✅ 2026-05-10 | — | — | Optionnel : rerun sur 7 leafs météo / intérieurs |
| T5+T6+T7 couleur/surfaces | ✅ 2026-05-10 | — | — | Optionnel (volume corpus faible — prophylactique) |

Au fil de l'eau, MAJ de ce tableau et de MEMORY (Échéances + Décisions actées) — sans solliciter l'utilisateur sauf blocage.

## Reporting attendu côté Claude Code d'exécution

Chaque brief impose un rapport `docs/reports/YYYY-MM-DD_transfert-skill-<règle>-<sujet>.md` avec sections Contexte / Modifications / Tests / Mesure post-transfert / Décision (Go/No-Go pour le suivant). Si KO ou seuil non atteint, reporter le complément en T19+ canal manuel — l'archi met à jour la démarche en conséquence.
