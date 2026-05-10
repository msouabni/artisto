# Transfert skill T9 — profil + orientation directionnelle (Solo animal résiduels)

Date : 2026-05-10

## Contexte

Le rerun-2objets v2 (NEGATIVE_V3 + `_ISOLATION` + `LEAF_OVERRIDES` partiels) a ramené `image_duplication` de 13/13 à 6/13. Les 6 leafs résiduels (`bactrian_camel`, `golden_retriever`, `mountain_gorilla`, `playful_dolphin`, `running_cheetah`, `running_giraffe`) partagent une morphologie à élément étendu derrière le sujet (queue ample, long cou, fin dorsale) qui déclenche une duplication par symétrie. La règle T9 du skill `prompt-taxonomy-ecosystem` (`references/techniques.md` §T9) propose un fix validé : profil strict + orientation directionnelle explicite (`one single [sujet] in profile facing [left/right], [élément] pointing/curving [direction]`).

## Modifications

### Fichiers touchés

| Fichier | LOC ajoutées | LOC modifiées | Nature |
|---|---|---|---|
| `src/services/prompt_generator.py` | ~85 | ~12 | Ajout T9 (constantes + helper + branchement templates) |
| `tests/test_prompt_generator.py` | 162 (nouveau) | 0 | Suite de tests dédiée |

### Diff résumé

`src/services/prompt_generator.py` :

1. Nouveau bloc commentaire T9 (citation textuelle de la règle skill avec lien vers le brief).
2. Constante `_RISKY_BACKWARD_ELEMENTS = ("tail_ample", "long_neck", "mane", "dorsal_fin", "extended_limb")` — vocabulaire skill conservé en référence (audit/évolution future).
3. Constante `_DIRECTIONAL_OVERRIDES: Dict[str, dict]` couvrant les 6 leafs résiduels avec champs `facing` (left/right) + `backward` (clause libre ou None pour gorilla qui n'a pas d'élément arrière).
4. Helper `_apply_directional_override(name, leaf_id, env_clause) -> Optional[str]` qui construit le positive en injectant la formule T9 si `leaf_id` est mappé, sinon retourne `None`.
5. `template_solo_animal` : appel du helper en début de fonction (env_clause = `"all four legs visible on the ground, simple ground line"`). Retombe sur le template historique si pas de match.
6. `template_solo_fish` : appel du helper après le calcul de `env_clause` (qui peut donc varier selon morphologie marine), ce qui permet à `playful_dolphin` de court-circuiter la branche dolphin par défaut.

**Priorité résolue** : `LEAF_OVERRIDES` (existant, `build_prompt`) > `_DIRECTIONAL_OVERRIDES` (nouveau, dans templates) > template par défaut. La résolution `LEAF_OVERRIDES` se fait dans `build_prompt` avant l'appel au template, donc `sheep_with_lamb` et `eid_al_adha_sheep` ne passent jamais par les nouveaux helpers.

## Tests

### Suite dédiée `tests/test_prompt_generator.py`

14 tests (tous verts, 0.09 s). Couverture :

- Mapping complet : `_DIRECTIONAL_OVERRIDES` couvre les 6 leafs résiduels.
- Validation : `facing` ∈ {left, right} pour toutes les entrées.
- Vocabulaire T9 (`_RISKY_BACKWARD_ELEMENTS`) traçable.
- Comportement T9 : 5 leafs animal terrestre + 1 leaf marin (dolphin) produisent `in profile facing [direction]` avec leur clause `backward` correcte.
- Non-régression : `playful_dolphin` ne retombe PAS sur la branche dolphin par défaut (`swimming horizontally`).
- Non-régression : leaf hors mapping (`house_cat`, `rainbow_trout`) garde son template standard.
- Non-régression : `sheep_with_lamb` et `eid_al_adha_sheep` restent dans `LEAF_OVERRIDES` (priorité 1) et hors `_DIRECTIONAL_OVERRIDES`.
- Smoke `build_prompt` : `running_giraffe` (T9 actif) vs `sheep_with_lamb` (LEAF_OVERRIDE actif).

### Suite globale

`pytest --ignore=tests/test_content_generator.py` : **202 passed, 5 failed**.

Les 5 échecs sont **pré-existants et non liés** à ce transfert :

- `test_bulk_generation_jobs.py` (2 tests), `test_create_image_job_workflow.py` (2 tests), `test_workflow_template_sidecar.py` (1 test) : tous liés à la config ERNIE `negative_prompt: optional vs unsupported` (problème workflow ComfyUI).
- `tests/test_content_generator.py` collecte interrompue pour `ImportError: cannot import name 'HARAKAT_RE' from 'services.ollama_json'` — pré-existant, hors scope.

Aucun test prompt_generator/templates ne régresse.

## Mesure post-transfert

**Procédure documentée — exécution humaine requise** :

La mesure ComfyUI sur les 6 leafs résiduels n'a pas été lancée par l'agent (pas d'accès worker ComfyUI dans le run dev). Procédure à exécuter manuellement :

```bash
# 1. Régénérer les prompts via PromptGenerator
python -c "from src.services.prompt_generator import PromptGenerator; \
    g = PromptGenerator(); \
    print(g.build_prompt('running_giraffe')['positive'])"
# → vérifier la présence de 'in profile facing right, neck and tail extended right'

# 2. Lancer un job ComfyUI pour chacun des 6 leafs (1 image, seed offset +200)
#    via API /api/jobs ou directement worker run_image_worker.py --once
for leaf in bactrian_camel golden_retriever mountain_gorilla playful_dolphin running_cheetah running_giraffe; do
    # créer image + scheduler job avec seed v2_seed + 200
done

# 3. Annoter manuellement avec la grille v2 (a minima tag image_duplication)
# 4. Comparer : image_duplication v3 vs v2
#    - v2 : 6/13 (46%)
#    - cible v3 : < 2/13 (< 15%)
```

**Verdict mesure : en attente de mesure humaine.** Le transfert code est déterministe et testé ; le critère de succès "facing [direction] présent dans le positive" est atteint pour les 6 leafs (cf. tests). Le critère de succès image (réduction `image_duplication` < 2/13) nécessite un rerun ComfyUI.

## Points d'attention

- **Mapping facing left/right des 6 leafs** : choisi tel quel d'après le brief. Le choix L/R est arbitraire (le modèle est invariant par symétrie), mais une fois fixé il faut conserver la même direction pour chaque leaf afin de comparer v3 vs v2 sur seed comparable.
- **`mountain_gorilla` sans `backward`** : conservé `None` selon brief — le gorille n'a pas de queue/long cou. La formule devient `one single mountain gorilla in profile facing right, full body view, ...`. À surveiller en mesure : le bénéfice T9 vient principalement de la clause backward ; sans backward, le gain attendu est plus faible.
- **`_RISKY_BACKWARD_ELEMENTS` non utilisé pour le matching auto** : laissé documentaire pour l'instant, on s'appuie sur curated mapping (fidélité au brief). Une PR future pourra ajouter un matching automatique sur ces tokens si on étend la liste à 20+ leafs.
- **Insertion T9 dans `template_solo_fish` après le calcul de `env_clause`** : permet à dolphin de court-circuiter la branche par défaut tout en réutilisant `simple water line at bottom`. Cohérent avec l'usage dolphin → mais à revoir si on étend le mapping à des espèces avec `env_clause` très spécifique (ex : seahorse `simple water bubbles around`).

## Décision / Action suivante

**Go pour les briefs T2 + T3 + T23 et T25.** Aucun blocage structurel rencontré :

- Le pattern `helper_apply_X_override` se transpose bien (séparation claire constantes/helper/branchement template).
- L'ordre de priorité `LEAF_OVERRIDES > règle skill > template défaut` est respecté et testable.
- Les tests unit-level templates (sans DB) tournent en < 0.1 s — facile à étendre.

**Action suivante côté archi** :

1. Planifier la mesure ComfyUI (1 image / leaf × 6 leafs, seed v2+200) pour valider le critère final image_duplication < 2/13.
2. Si succès mesure → étendre `_DIRECTIONAL_OVERRIDES` à d'autres leafs morphologiquement similaires (audit annotations v3).
3. Si échec partiel sur `mountain_gorilla` (pas de backward) → envisager ajout d'une clause `arms wrapped close to torso` ou équivalent.
