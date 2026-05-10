# Brief — Bench garde-fou T25 (débloque H4 / H3)

Date : 2026-05-10
Auteur : architecte / PMO
Destinataire : claude-code dev
Sévérité : haute — débloque H4 (pivot T25) et H3 (décision 31 classes non-Haute)

## Objectif

Mesurer si le pivot T25 (templates `template_frieze_1xN` + `template_grid_3x3_imagier` réécrits 2026-05-10 en BEFORE/AFTER + SPOT THE DIFFERENCE) **réduit** le taux de défauts composition (`image_pas_coherente` + `image_incomprehensible`) **par rapport à la baseline pré-pivot**.

**Critère de retrait T25** (acté en décision archi 2026-05-10) :
- Si **taux post-pivot ≥ 70 % du taux baseline** → switch `_T2T3T23_GRID_AVAILABLE = False` (1 ligne) + report T19+ canal manuel
- Sinon → **promotion T25 en prod** (statu quo, pivot maintenu)

## Baseline (référence)

Source : `docs/reports/2026-05-10_analyse-annotations-poc-scale-benchmark.md` §3.

Sur 4 méta-patterns multi-cellules pré-pivot :

| Méta-pattern | N annoté | tags `image_pas_coherente` | tags `image_incomprehensible` | tag rate cumulé |
|---|---|---|---|---|
| Grille imagier annoté (template inchangé) | 8 | 8 | 8 | **HORS PIVOT** — sert de témoin |
| Imagier différencié 3×3 (= `template_grid_3x3_imagier` PIVOTÉ) | 8 | 4 | 4 | 8/8 = 100 % |
| Frise narrative 1×N (= `template_frieze_1xN` PIVOTÉ) | 8 | 5 | 5 | 5/8 = 62.5 % |
| Multi-sujets via grille (= `template_grid_3x3_imagier` PIVOTÉ) | 10 | 1 | 1 | 1/10 = 10 % |

→ **Baseline cumulée** sur les 26 leaves PIVOTÉES (Imagier différencié + Frise narrative + Multi-sujets via grille) : **14 occurrences `image_pas_coherente` + 14 `image_incomprehensible`** sur 26 images.

## Périmètre

### À générer

**N = 20 images post-pivot** : 10 sur `template_frieze_1xN` (workflow_classes Frise narrative et Multi-sujets frise) + 10 sur `template_grid_3x3_imagier` (workflow_classes Imagier différencié et Multi-sujets via grille).

Sélection des leaves : prendre des leaves déjà annotées en pré-pivot (couvertes par la baseline ci-dessus) pour comparer A→B même périmètre. Liste minimale (10+10 = 20 leaves) à extraire de `docs/reports/poc-scale-benchmark/annotations.json` filtrée sur les 4 workflow_classes pivotées.

### Output dir

`docs/reports/poc-bench-T25-postPivot/`
- 20 PNG générés
- `index-bench-T25.json` (schéma `subjects` standard, avec `output_file`, `leaf_id`, `positive_prompt`, `negative_prompt`, `workflow_class`, `seed`)
- `annotations.json` (créé vide, à remplir par l'utilisateur via annotateur v2 mode `?dir=poc-bench-T25-postPivot`)

### À ne pas modifier

- Pas de modification du `PromptGenerator` (il vient d'être pivoté, on le teste tel quel)
- Pas de modification du skill
- Pas de modification de la cartographie ni des annotations existantes

## Implémentation

### Étape 1 — Génération (claude-code dev)

Réutiliser un script POC existant (style `scripts/poc_*.py`) pour :
1. Charger les 20 leaves cibles
2. Générer le prompt via `PromptGenerator(...).build_prompt(leaf_id)` post-pivot
3. Soumettre à ComfyUI (voir `scripts/run_image_worker.py` pour la mécanique, ou le worker ComfyUI direct)
4. Sauver les 20 PNG dans `docs/reports/poc-bench-T25-postPivot/`
5. Produire `index-bench-T25.json` au schéma `subjects`

**Seed** : `seed_offset=800` (différent des reruns existants — cf. `2026-05-09_poc-rerun-2objets.md` qui utilisait offset 100).

**Paramètres image** : figés CLAUDE.md (`euler / 8 steps / cfg=1.0 / scheduler=normal`). Résolution selon `workflow_class` (cartographie déjà adaptative).

### Étape 2 — Annotation (utilisateur, hors brief)

L'utilisateur annote les 20 entrées via l'annotateur v2 :
```
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-T25-postPivot
```
Grille v2, score 1-6, image_tags habituels — la durée est ~30 min utilisateur, hors scope claude-code.

### Étape 3 — Verdict (claude-code dev)

Script `scripts/poc_bench_T25_verdict.py` (jetable, lié au brief) :

1. Charger `docs/reports/poc-bench-T25-postPivot/annotations.json`
2. Compter les tags `image_pas_coherente` + `image_incomprehensible` sur les 20 entrées scorées
3. Calculer `taux_post = (n_pas_coherente + n_incomprehensible) / (2 × N_annoté)`
4. Comparer à `taux_baseline = (14 + 14) / (2 × 26) = 53.8 %`
5. Verdict :
   - Si `taux_post < 70 % × 53.8 % = 37.7 %` → **PROMOTION T25**
   - Sinon → **RETRAIT T25** (switch flag `_T2T3T23_GRID_AVAILABLE = False`)
6. Produire un rapport markdown final.

## Critères d'acceptation

- [ ] 20 PNG générés dans `docs/reports/poc-bench-T25-postPivot/` avec PromptGenerator post-pivot
- [ ] `index-bench-T25.json` au schéma `subjects` complet (les 20 entrées avec `leaf_id`, `output_file`, `positive_prompt`, `negative_prompt`, `workflow_class`, `seed`)
- [ ] `annotations.json` créé vide et lu correctement par l'annotateur v2 (test : ouvrir l'URL et naviguer)
- [ ] Script `scripts/poc_bench_T25_verdict.py` opérationnel — produit un rapport `docs/reports/2026-05-10_bench-T25-gardefou-postPivot.md` après annotation
- [ ] Aucune modification de `src/services/prompt_generator.py` ni du skill
- [ ] Pas de régression — pytest `tests/test_prompt_generator.py` toujours 117/117 verts

## Reporting

Le rapport final `docs/reports/2026-05-10_bench-T25-gardefou-postPivot.md` doit contenir :
- Liste des 20 leaves testées + workflow_class
- Tableau des annotations utilisateur (score, image_tags)
- Calcul du taux post-pivot vs baseline
- Verdict final : PROMOTION ou RETRAIT
- Si RETRAIT : pointeur vers le switch flag à activer dans `src/services/prompt_generator.py`

## Hors-scope

- Pas de bench des autres règles transférées (T9, T22+T27+T30, T28+Z1, T26+T31, T5+T6+T7) — chacune a son propre garde-fou
- Pas de génération sur les leaves non-pivotées (Grille imagier annoté reste hors pivot, pas de mesure ici)
- Pas d'analyse fine par sous-classe — verdict cumulé sur les 20

## Estimation dev

- Sélection 20 leaves + script génération : ~20 min
- Génération ComfyUI 20 images (à 18-20s/img isolation, 50-75s/img si ComfyUI partagé) : 6-25 min selon contexte
- Création `index-bench-T25.json` + `annotations.json` vide : ~5 min
- Script verdict + smoke : ~15 min
- **Total claude-code dev : ~45-60 min** (hors annotation utilisateur ~30 min)

## Conventions à respecter

- Reporting obligatoire dans `docs/reports/`
- Image params figés : `sampler=euler`, `steps=8`, `cfg=1.0`, `scheduler=normal`
- NULL-safe : `int(w) if w is not None else 0` dans le script verdict
- Pas de commit auto — l'archi commit après revue

## Points d'attention

- **ComfyUI doit être démarré** avant lancement (cf. CLAUDE.md "I'll just run a worker"). Le script doit échouer fort si ComfyUI inaccessible (pas de fallback silencieux).
- **Sélection 10+10 leaves** : privilégier celles qui avaient `image_pas_coherente` ou `image_incomprehensible` en pré-pivot (signal le plus net).
- **Les 4 templates** dont le brief de pivot a remplacé le contenu (`template_frieze_1xN`, `template_grid_3x3_imagier`) ne génèrent plus de "frise N cellules" ni de "grille 3×3" mais des **prompts BEFORE/AFTER en 2 cellules**. C'est attendu — l'utilisateur l'annotera en regardant ce que ERNIE produit réellement, pas ce qu'il aurait produit avant.
- **Si ComfyUI partagé** (50-75s/img) : prévoir 25 min de génération seule. Lancer en background si besoin.
- **Garde-fou ComfyUI** : si le worker plante sur certaines leaves, livrer le verdict sur N réel (≥15) avec note explicite des échecs.
