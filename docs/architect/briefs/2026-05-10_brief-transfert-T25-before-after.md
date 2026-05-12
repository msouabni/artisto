# Transfert T25 — template Comparatif before/after (états explicites)

## Contexte

L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #2 identifie **~28 défauts** `image_pas_coherente` + `image_incomprehensible` concentrés sur 2 workflow_classes Comparatif :

- Comparatif before/after OU Solo : 8/10 (80%, score moyen 1.00, 10% pub)
- Solo objet ou comparatif : 6/8 (75%, score moyen 1.00, 0% pub)

Diagnostic : `template_before_after` (`src/services/prompt_generator.py` l. 433-446) écrit `the right cell shows the same scene with one single change applied` — antipattern explicitement listé en T25 du skill (`# ❌ trop vague — modèle reproduit la même scène`).

Le skill `prompt-taxonomy-ecosystem` règle T25 (`references/techniques.md`) propose le fix validé hors-circuit : **différence concrète, visuelle, localisée** via champs `before_state` / `after_state` explicites.

## Garde-fou pivot ERNIE

Insight produit ERNIE 2026-05-10 (cf. T19+ #2 du rapport d'analyse) : le modèle est faible en répétition stricte avec contenu hétérogène. Si T25 maxi appliqué ne descend pas le taux `image_pas_coherente` sous **30 %** sur l'échantillon de mesure, **stopper le transfert et reporter en T19+ canal manuel** (bascule pipeline comparatif en composition PIL 2-tiles hors ERNIE — décision archi).

## Objectif

Transférer T25 dans `src/services/prompt_generator.py` (template `template_before_after`) : injecter `before_state` et `after_state` explicites au lieu du wording générique. Mesurer la réduction du défaut.

## Périmètre

**Créer / Étendre** :

- `data/prompt_generator/before_after_states.json` (ou enrichir `taxonomy_production_cartography.json` sur les sous-catégories visées — cf. décision archi sur le placement) :
  ```json
  {
    "<leaf_id>": {
      "before_state": "<description concrète localisée>",
      "after_state":  "<description concrète localisée>"
    }
  }
  ```
  Couvrir au minimum les **leafs annotés** des 2 classes Comparatif dans `docs/reports/poc-scale-benchmark/annotations.json`. Cible minimale : 6-8 leafs.
- Si fichier séparé créé : `data/before_after_states_editor.html` (convention projet) — facultatif si l'asset est traité comme cœur stable lecture-seule pour l'instant.

**Modifier** :

- `src/services/prompt_generator.py` :
  - `template_before_after` :
    - Si `before_state ET after_state` présents → injecter dans les cellules au lieu de `in its initial state` / `with one single change applied`.
    - Sinon → conserver le comportement actuel + `logger.warning("before_after_states missing for leaf_id=%s", leaf_id)` via `artiste_logging`.

- `tests/test_prompt_generator.py` :
  - Test : leaf avec `before_state`/`after_state` défini → présence dans positive.
  - Test : leaf sans → fallback + warning loggé (capturer via `caplog`).
  - Test non-régression : autres templates inchangés.

**Ne pas modifier** :

- Autres templates.
- `NEGATIVE_V3`, `_ISOLATION`, etc.

## Critères d'acceptation

- `data/prompt_generator/before_after_states.json` créé avec ≥ 6 leafs couverts.
- `template_before_after` lit le JSON ; fallback fonctionne ; warning loggé.
- Tests pytest verts.
- Citation T25 en commentaire de code.

**Mesure post-transfert (obligatoire pour ce brief, du fait du garde-fou ERNIE)** :

- Rerun ComfyUI sur 6-8 leafs des 2 classes (1 image / leaf, seed offset +400).
- Annoter manuellement grille v2 — tags `image_pas_coherente` + `image_incomprehensible`.
- Comparer baseline (89%) vs post-transfert.
- **Décision Go/No-Go T19+ #2** :
  - Si taux post-transfert ≤ 30% → Go : transfert validé.
  - Si taux post-transfert > 30% → No-Go : signaler dans le rapport, l'archi reportera en T19+ #2 canal manuel (bascule PIL 2-tiles).

## Reporting

Rapport obligatoire : `docs/reports/2026-05-10_transfert-skill-T25-before-after.md`
Sections : Contexte / Modifications / Tests / Mesure post-transfert (obligatoire) / Décision (Go ou No-Go pivot ERNIE).

## Conventions à respecter

- Reporting daté.
- Convention editor HTML : à honorer ou justifier explicitement.
- NULL-safe avant tri.
- Tests SQLite-portables.
- Citation T25 en commentaire de code.

## Hors scope

- T25 mode 3 (différences libres — workflow distinct de production). Ouvrir un ticket suivant si pertinent.
- Couverture exhaustive de tous les leafs Comparatif (extension par PR ultérieure si Go).
- Bascule PIL 2-tiles (décision archi si No-Go).

## Estimation

~60-75 min dev + tests + mesure + rapport.

Si dépassement marqué : signaler à l'archi via le rapport et découper.
