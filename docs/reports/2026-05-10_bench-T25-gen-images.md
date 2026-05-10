# POC — Bench garde-fou T25 (génération images post-pivot)
Date : 2026-05-10
Auteur : claude-code dev (Agent A — partie génération)

## Contexte

Brief source : `docs/architect/briefs/2026-05-10_brief-bench-gardefou-T25.md`.

Étape 1 du bench garde-fou T25 : générer 20 images post-pivot des templates
`template_frieze_1xN` (BEFORE/AFTER) et `template_grid_3x3_imagier`
(SPOT-THE-DIFFERENCE) refactorés le 2026-05-10, en vue de mesurer si le pivot
réduit le taux cumulé `image_pas_coherente` + `image_incomprehensible` sous le
seuil de 70 % de la baseline (53.8 % → seuil retrait T25 = 37.7 %).

L'Agent B traite en parallèle le script verdict (étape 3).

## Sélection des 20 leaves

10+10 leaves choisies depuis `docs/reports/poc-scale-benchmark/annotations.json`
en privilégiant celles avec défauts pré-pivot `image_pas_coherente` ou
`image_incomprehensible`. Workflow_classes ciblées : `Frise narrative 1×N
(pattern X2)`, `Multi-sujets (frise)`, `Imagier différencié 3×3`,
`Multi-sujets via grille (méta-pattern §2)`.

### Bloc frise (10 leaves — template_frieze_1xN)

| # | leaf_id | workflow_class | Résolution | Annotation pré-pivot |
|---|---------|----------------|-----------|----------------------|
| 1 | teenager_with_backpack | Frise narrative 1×N (pattern X2) | 1376×768 | score 1, pas_coherente + incomprehensible |
| 2 | child_at_school_age | Frise narrative 1×N (pattern X2) | 1376×768 | score 6 |
| 3 | life_cycle_full_poster | Frise narrative 1×N (pattern X2) | 1376×768 | score 1, pas_coherente + incomprehensible |
| 4 | toddler_learning_to_walk | Frise narrative 1×N (pattern X2) | 1376×768 | score 1, pas_coherente + incomprehensible |
| 5 | parent_with_child | Frise narrative 1×N (pattern X2) | 1376×768 | score 1, pas_coherente + incomprehensible |
| 6 | baby_first_year | Frise narrative 1×N (pattern X2) | 1376×768 | score 2 |
| 7 | grandparent_with_grandchild | Frise narrative 1×N (pattern X2) | 1376×768 | score 1, pas_coherente + incomprehensible |
| 8 | young_adult_at_work | Frise narrative 1×N (pattern X2) | 1376×768 | score 6 |
| 9 | classroom_with_teacher | Multi-sujets (frise) | 1376×768 | non annoté pré-pivot (pas dans bench) |
| 10 | school_bus_with_kids | Multi-sujets (frise) | 1376×768 | non annoté pré-pivot |

### Bloc grille (10 leaves — template_grid_3x3_imagier)

| # | leaf_id | workflow_class | Résolution | Annotation pré-pivot |
|---|---------|----------------|-----------|----------------------|
| 11 | ice_cream_and_sorbets | Imagier différencié 3×3 | 1024×1024 | score 3, pas_coherente + incomprehensible |
| 12 | dairy_products_milk | Imagier différencié 3×3 | 1024×1024 | score 1, pas_coherente + incomprehensible |
| 13 | vegetables_basket | Imagier différencié 3×3 | 1024×1024 | score 1, pas_coherente + incomprehensible |
| 14 | fruits_basket | Imagier différencié 3×3 | 1024×1024 | score 1, pas_coherente + incomprehensible |
| 15 | bread_and_pastries | Imagier différencié 3×3 | 1024×1024 | score 5 |
| 16 | decorative_number_ten_fingers | Multi-sujets via grille (méta-pattern §2) | 1024×1024 | score 1, pas_coherente + incomprehensible |
| 17 | number_zero_with_eggs | Multi-sujets via grille (méta-pattern §2) | 1024×1024 | score 1 |
| 18 | number_three_with_birds | Multi-sujets via grille (méta-pattern §2) | 1024×1024 | score 1 |
| 19 | number_one_with_apple | Multi-sujets via grille (méta-pattern §2) | 1024×1024 | score 1 |
| 20 | number_nine_with_cars | Multi-sujets via grille (méta-pattern §2) | 1024×1024 | score 1 |

Note méthodologique : 2 des 10 leaves frise (`classroom_with_teacher`,
`school_bus_with_kids`) n'avaient pas d'annotation pré-pivot. Elles ont été
ajoutées pour atteindre le quota 10 frise demandé par le brief sur le
template `template_frieze_1xN` (workflow_class `Multi-sujets (frise)` qui
emprunte ce template). Les 8 autres frise sont toutes issues de la baseline
poc-scale-benchmark.

## Résultats génération

**20 OK / 0 KO sur 20** (100 % de réussite).

- Output dir : `docs/reports/poc-bench-T25-postPivot/`
- Index : `docs/reports/poc-bench-T25-postPivot/index-bench-T25.json`
  (schéma `subjects` standard, clés `output_file`, `leaf_id`,
  `positive_prompt`, `negative_prompt`, `workflow_class`, `seed`,
  + métadonnées : `tier`, `resolution`, `seed_original`, `seed_offset`,
  `sampler`, `steps`, `cfg`, `scheduler`, `comfy_latency_s`, etc.)
- Annotations vide : `docs/reports/poc-bench-T25-postPivot/annotations.json`
  au format v2 attendu par l'annotateur (`{"dir": "...", "annotations": {}}`).

### Paramètres image (figés CLAUDE.md)

- sampler : `euler`
- steps : `8`
- cfg : `1.0`
- scheduler : `normal`
- résolution : adaptative selon workflow_class (1376×768 frise, 1024×1024 grille)
- seed_offset : **+800** (différent des reruns précédents : +100 v2_2objets)

### Latence ComfyUI

ComfyUI **partagé** avec un autre script (`poc_bench_gate_ernie.py`) tournant en
parallèle. Latences observées :
- Démarrage (avant partage) : ~26 s/image (8 frise narrative)
- Partage actif : ~46-53 s/image (10 grille + 2 multi-frise)
- Total ~13 min de génération réelle pour 20 images

Aucun échec, aucun retry. ComfyUI a tenu la charge sans plantage.

## Smoke annotateur

URL à ouvrir dans le navigateur après démarrage de l'API :
```
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-T25-postPivot
```

Le routeur `src/api/routes/benchmark.py::_safe_dir` valide le nom (regex
`^[a-zA-Z0-9._-]+$` — OK pour `poc-bench-T25-postPivot`), résout le chemin
sous `docs/reports/`, et liste les images depuis le dossier. L'annotateur
chargera automatiquement `annotations.json` (vide à ce stade) et permettra
l'annotation utilisateur (étape 2 hors brief, ~30 min).

## Tests pytest

Non-régression vérifiée : `pytest tests/test_prompt_generator.py -q` →
**124 passed in 0.34s** (le brief mentionnait 117 — la suite a été enrichie
depuis ; aucune régression). Le `PromptGenerator` n'a pas été modifié par ce
brief.

## Fichiers produits

| Path | Rôle |
|------|------|
| `scripts/poc_bench_T25_gen.py` | Script génération (jetable, lié brief) |
| `docs/reports/poc-bench-T25-postPivot/*.png` | 20 images line-art post-pivot |
| `docs/reports/poc-bench-T25-postPivot/index-bench-T25.json` | Index subjects |
| `docs/reports/poc-bench-T25-postPivot/annotations.json` | Annotations vides v2 |
| `docs/reports/2026-05-10_bench-T25-gen-images.md` | Ce rapport |

## Points d'attention

- Le brief précisait "10 frise" — j'ai inclus 2 leaves `Multi-sujets (frise)`
  non annotées en pré-pivot pour atteindre le quota (l'index frise narrative
  pré-pivot n'a que 8 entrées). Les 8 autres ont des annotations baseline
  exploitables pour comparaison A→B même périmètre.
- ComfyUI partagé n'a pas généré d'erreur ; le script aurait échoué fort
  (return code 2) si ComfyUI était inaccessible (cf. `is_available()` check).
- Aucune modif `src/services/prompt_generator.py`, ni du skill, ni des
  annotations existantes.

## Action suivante

1. **Utilisateur** : annoter les 20 entrées via l'annotateur v2 à l'URL
   ci-dessus (~30 min).
2. **Agent B / archi** : exécuter `scripts/poc_bench_T25_verdict.py` (à
   produire en parallèle) qui calcule le taux post-pivot vs baseline 53.8 %
   et produit le rapport final
   `docs/reports/2026-05-10_bench-T25-gardefou-postPivot.md`.
3. **Décision** : promotion T25 (taux < 37.7 %) ou retrait T25 (switch
   `_T2T3T23_GRID_AVAILABLE = False`).

## Décision / Action suivante

Génération **OK 20/20**. Étape 1 du brief complétée. Pas de commit (livraison
sans commit comme spécifié).
