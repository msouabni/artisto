# Bench gate ERNIE — mesure post-transferts T2T3T23 + T25 + Pivot

## Contexte

La séquence P3 transferts skill → PromptGenerator est livrée (8/8 règles, 117/117 tests verts). Trois transferts ont un **garde-fou ERNIE** explicite : si le taux de défauts résiduel dépasse 30% sur l'échantillon mesuré, ils sont reportés en T19+ canal manuel (bascule pipeline PIL/SVG) :

- **T2T3T23 grille** — baseline 91-100% `image_pas_coherente` + `image_incomprehensible` sur 4 workflow_classes
- **T25 before/after** — baseline 89% sur 2 workflow_classes Comparatif
- **Pivot T25 (frieze + grid)** — bench obligatoire (brief le précisait, pas encore lancé)

Sans ce bench, **aucune promotion prod** n'est possible : les transferts sont implémentés mais leur efficacité produit n'est pas mesurée.

## Objectif

Lancer une campagne de génération ComfyUI ciblée + faciliter l'annotation humaine pour produire les verdicts Go/No-Go gate ERNIE des 3 transferts à risque pivot.

## Périmètre

**Génération ComfyUI** :

- **T2T3T23 (8-10 leafs)** : `fruit_imagier_with_names`, `vegetable_imagier_with_names`, `weather_imagier_with_names`, `balanced_lunch_plate`, `healthy_breakfast_plate`, `proud_child_face`, `sad_child_crying`, `fruits_basket`, `vegetables_basket`, `bread_and_pastries`. Seed offset +300.
- **T25 before/after (18 leafs)** : tous ceux couverts dans `data/prompt_generator/before_after_states.json` (extraits du rapport `2026-05-10_transfert-skill-T25-before-after.md` §before_after_states.json). Seed offset +400.
- **Pivot T25 (8-10 leafs sur 4 méta-patterns)** : sélection des classes `Frise narrative 1×N`, `Imagier différencié 3×3`, `Multi-sujets via grille`, `Imagier différencié OU Solo`. Couvrir au moins 2 leafs par classe. Seed offset +1000.

Pour les 3 transferts non-garde-fou, **mesure optionnelle bonus** dans la même campagne (T9 sur 6 leafs résiduels Solo animal seed +200, ISO élargi sur 8 leafs seed +500, ANAT sur 12 leafs seed +600, METEO sur 7 leafs seed +800) — à effort marginal vu que le pipeline est déjà chaud.

**Annotation** :

- Fournir un dossier de sortie unifié `docs/reports/poc-bench-gate-ernie-2026-05-10/` avec sous-dossiers par transfert.
- Fichier d'index `index-bench-gate.json` mappant filename → leaf_id → workflow_class → transfert (T2T3T23 / T25 / pivot / etc.) → seed.
- Annotateur HTML (`benchmark-annotator.html`) doit pouvoir charger ce dossier en mode benchmark — vérifier compat schéma v2.

**Calcul des verdicts** :

- Script de synthèse à exécuter après l'annotation humaine — agrège les tags `image_pas_coherente` + `image_incomprehensible` (+ `image_duplication`, `image_anatomie_pb` pour les autres transferts) par transfert et compare à la baseline.
- Sortie : tableau verdict par transfert (`Go ≤ 30%` / `No-Go > 30%`) prêt à coller en MEMORY.

## Plan d'exécution suggéré (sous-agents Claude Code)

Recommandation : déléguer la génération à des **sous-agents general-purpose** parallèles, un par transfert, pour réduire la durée wall-clock.

```
Phase 1 — Préparation (Claude Code principal)
  - Créer dossier docs/reports/poc-bench-gate-ernie-2026-05-10/
  - Préparer index-bench-gate.json vide
  - Vérifier API ComfyUI accessible + worker actif

Phase 2 — Génération (parallèle, 3 sous-agents general-purpose)
  - Sous-agent A : génération T2T3T23 (8-10 leafs, seed +300)
  - Sous-agent B : génération T25 before/after (18 leafs, seed +400)
  - Sous-agent C : génération Pivot T25 (8-10 leafs, seed +1000)
  Chaque sous-agent : crée image + job ComfyUI via /api/jobs, attend completion,
  télécharge image dans le bon sous-dossier, met à jour index-bench-gate.json.

Phase 3 — Génération bonus mesures (parallèle, 4 sous-agents — optionnel)
  - Sous-agent D : T9 (6 leafs, seed +200)
  - Sous-agent E : ISO élargi (8 leafs, seed +500)
  - Sous-agent F : ANAT (12 leafs, seed +600)
  - Sous-agent G : METEO (7 leafs, seed +800)

Phase 4 — Annotation humaine (hors Claude Code, archi déclenche)
  - URL : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-gate-ernie-2026-05-10
  - Délai estimé : 1-2h selon le volume

Phase 5 — Synthèse verdicts (Claude Code principal, après annotation)
  - Script scripts/synthesize_bench_gate.py qui lit annotations.json + index-bench-gate.json
  - Calcule taux par transfert et applique les seuils
  - Sortie : tableau verdict prêt à coller dans rapport
```

## Critères d'acceptation

- Dossier `poc-bench-gate-ernie-2026-05-10/` créé avec sous-dossiers par transfert.
- Index file `index-bench-gate.json` complet (filename → leaf_id → transfert → seed).
- Toutes les images cibles générées et placées correctement.
- Script `scripts/synthesize_bench_gate.py` créé et fonctionnel (à exécuter post-annotation).
- Rapport préliminaire `docs/reports/2026-05-10_bench-gate-ernie-protocole.md` documente le périmètre + commande d'exécution finale du script de synthèse.

## Hors scope

- L'**annotation humaine elle-même** (dehors Claude Code, archi/utilisateur la fait).
- Décision Go/No-Go finale (archi tranche après lecture du tableau verdict).
- Réécriture des transferts si No-Go (gérée séparément via T19+ canal manuel).

## Reporting

`docs/reports/2026-05-10_bench-gate-ernie-protocole.md` (livraison génération + protocole annotation + commande synthèse).
Après annotation et exécution synthèse : `docs/reports/2026-05-10_bench-gate-ernie-verdicts.md` (verdicts finaux par transfert).

## Estimation

- Phase 1 : ~10 min.
- Phase 2 (3 sous-agents parallèles) : ~30 min wall-clock (sequentiel ComfyUI ~15 min/transfert × 3 = 45 min, parallèle si workers multiples = wall-clock 15-20 min).
- Phase 3 (optionnelle, 4 sous-agents) : ~30 min wall-clock supplémentaire.
- Phase 5 (synthèse) : ~15 min après annotation humaine.

Total Claude Code (hors annotation humaine) : ~1h-1h30.
