# Bench gate ERNIE — Protocole de livraison + annotation
Date : 2026-05-10

## Contexte

Brief source : `docs/architect/briefs/2026-05-10_brief-bench-gate-ernie.md`.

La séquence P3 transferts skill → PromptGenerator est livrée (8/8 règles).
3 transferts ont un garde-fou ERNIE : si le taux résiduel
(`image_pas_coherente` + `image_incomprehensible`) dépasse 30 % sur
l'échantillon mesuré, ils sont reportés en T19+ canal manuel.

Sans ce bench, **aucune promotion prod** des transferts mesurés. Cette
livraison rend l'annotation humaine possible et automatise la décision
Go/No-Go via un script de synthèse.

## Périmètre exécuté

### Phase 1 — Préparation (faite)

- API/ComfyUI vérifiés (HTTP 200 sur `/api/jobs/types` et
  `/system_stats`).
- `image_generation` job_type_config : `enabled=true`.
- Sous-dossiers annotables créés au niveau `docs/reports/` (le router
  `/api/benchmark/*` ne supporte qu'un dossier plat) :
  - `docs/reports/poc-bench-gate-ernie-T2T3T23/`
  - `docs/reports/poc-bench-gate-ernie-T25/`
  - `docs/reports/poc-bench-gate-ernie-pivot/`
- Dossier parent `docs/reports/poc-bench-gate-ernie-2026-05-10/` réservé
  à l'index global + le rapport.

### Phase 2 — Génération (faite)

Script unique paramétrable : `scripts/poc_bench_gate_ernie.py`. Pattern
direct ComfyClient (cf. `poc_scale_benchmark_humans.py`), pas via la
queue `/api/jobs` → reproductible et observable.

Paramètres figés (ne pas changer sans nouveau benchmark — cf. CLAUDE.md
§Paramètres de génération image) :

| Paramètre | Valeur |
|---|---|
| `workflow_template` | `ernie-image-turbo-q8-api` |
| `sampler_name` | `euler` |
| `steps` | 8 |
| `cfg` | 1.0 |
| `scheduler` | `normal` |
| `batch_size` | 1 |

Seeds (cf. brief §22-25) :

| Transfert | Leafs | seed_base | stride |
|---|---|---|---|
| T2T3T23 | 10 | 300 | 7 |
| T25 | 18 | 400 | 7 |
| pivot | 10 | 1000 | 7 |
| (bonus T9) | 6 | 200 | 7 |
| (bonus ISO) | 8 | 500 | 7 |
| (bonus ANAT) | 12 | 600 | 7 |
| (bonus METEO) | 7 | 800 | 7 |

Chaque sous-dossier reçoit :
- les PNG (`{leaf_id}_{w}x{h}_euler8s.png`)
- un fichier `<dir>.json` (schema poc-generator → consommé par
  `_normalize_results_index` pour les overlays QC)
- un fichier `index-bench-gate.json` (schema `subjects: [...]` →
  consommé par `_find_prompt_index` pour afficher prompt/title/tier
  dans l'annotateur)

Le dossier parent `poc-bench-gate-ernie-2026-05-10/` reçoit
`index-bench-gate.json` global mappant **filename → leaf_id →
workflow_class → transfert → seed → subdir**, ainsi que ce rapport et
le rapport verdicts (à venir).

### Phase 3 (bonus T9 / ISO élargi / ANAT / METEO) — non exécuté

Décision : reporté pour ne pas retarder le gate principal. Le script
supporte les 4 transferts bonus (`--transferts T9,ISO,ANAT,METEO`). À
relancer si l'archi le souhaite.

### Phase 4 — Annotation humaine (hors scope)

Voir « Protocole d'annotation » ci-dessous.

### Phase 5 — Synthèse verdicts (script livré)

Script : `scripts/synthesize_bench_gate.py`. Voir « Commande synthèse ».

## Protocole d'annotation humaine (Phase 4)

L'annotateur HTML supporte un dossier à la fois (le router
`/api/benchmark/*` n'est pas récursif). Trois sessions à enchaîner :

```
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-gate-ernie-T2T3T23
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-gate-ernie-T25
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-gate-ernie-pivot
```

Chaque image annotable affiche : prompt positif, négatif, workflow_class,
technique, pipeline, confidence, pitfalls, tier. Score 1-6 + tags image
+ tags prompt + flags (pattern, sample, publishable).

Tags critiques pour le gate (à cocher si applicable) :
- `image_pas_coherente` — éléments en désordre, scène non lisible
- `image_incomprehensible` — modèle a produit autre chose que demandé
- `image_duplication` — 2_objets / multi-sujet non demandé
- `image_anatomie_pb` — extra legs, etc.

Les `annotations.json` sont écrits en place dans chaque sous-dossier
(`POST /api/benchmark/annotate`).

## Commande synthèse (Phase 5)

À exécuter une fois les 3 dossiers annotés (au moins partiellement) :

```powershell
python scripts/synthesize_bench_gate.py
```

Sortie :
- `docs/reports/2026-05-10_bench-gate-ernie-verdicts.md` (tableau
  verdicts par transfert, prêt à coller en MEMORY).
- Verdict par transfert :
  - `Go` si taux principal ≤ 30 %
  - `No-Go` si > 30 %
  - `EN_ATTENTE` si aucune annotation

Options utiles :
```powershell
# Synthèse partielle (un seul transfert)
python scripts/synthesize_bench_gate.py --transferts T25

# Inclure les bonus (si générés)
python scripts/synthesize_bench_gate.py --transferts T2T3T23,T25,pivot,T9,ISO,ANAT,METEO

# Rapport custom
python scripts/synthesize_bench_gate.py --report docs/reports/2026-05-10_bench-gate-ernie-partiel.md
```

## Critères d'acceptation (brief §72-77)

- [x] Dossier `poc-bench-gate-ernie-2026-05-10/` créé (parent).
- [x] Sous-dossiers annotables `poc-bench-gate-ernie-{T2T3T23|T25|pivot}/`
      créés au niveau `docs/reports/`.
- [x] Index global `index-bench-gate.json` complet (filename → leaf_id
      → workflow_class → transfert → seed → subdir).
- [x] Toutes les images cibles (10 + 18 + 10 = 38) générées et placées
      dans le bon sous-dossier.
- [x] Script `scripts/synthesize_bench_gate.py` créé et fonctionnel
      (smoke testé : sortie « EN_ATTENTE » sur dossiers vides).
- [x] Rapport préliminaire `2026-05-10_bench-gate-ernie-protocole.md`
      (ce fichier).
- [x] Rapport verdicts `2026-05-10_bench-gate-ernie-verdicts.md`
      (généré, à mettre à jour quand `pivot` sera annoté).

## Points d'attention

- **Tests existants** : 5 failed legacy ERNIE/negative-prompt connus
  (`test_workflow_template_sidecar`, `test_create_image_job_workflow`,
  `test_bulk_generation_jobs`). 387 passed. Pas de régression introduite
  par cette livraison.
- **Annotateur récursif** : non supporté par
  `src/api/routes/benchmark.py:_safe_dir`. C'est pourquoi les 3 dossiers
  sont à plat sous `docs/reports/`. L'archi peut les ouvrir séparément.
- **Sous-dossiers à plat = rupture cosmétique avec le brief §73** mais
  fonctionnel et compatible existant. Si on veut plus tard un mode
  global, ajouter une option à `/api/benchmark/images?dir=`.
- **Pas de QC vision auto** : le pipeline `histogram_check` du
  `poc_scale_benchmark_humans.py` n'est pas lancé ici (pas de signal
  utile sur multi-sujets, et pas requis par le brief). Si l'archi
  souhaite un overlay QC, lancer manuellement
  `services.image_qc_technical.build_technical_image_qc_v1` après
  génération et écrire les flags dans `<dir>.json`.

## État annotation (constaté à la livraison)

L'utilisateur a commencé à annoter pendant la génération. État au moment
de l'écriture de ce rapport :

| Transfert | Annotées | Total | Verdict provisoire |
|---|---|---|---|
| T2T3T23 | 10 | 10 | **Go** (10 % — bien sous le seuil 30 %) |
| T25 | 18 | 18 | **Go** (0 % — aucun défaut détecté) |
| pivot | 0 | 10 | EN_ATTENTE |

Détail dans `docs/reports/2026-05-10_bench-gate-ernie-verdicts.md`
(régénéré par `scripts/synthesize_bench_gate.py`).

## Décision / Action suivante

- **Archi** : annoter le dossier `pivot` restant via
  `http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-gate-ernie-pivot`,
  puis relancer `python scripts/synthesize_bench_gate.py` pour mettre
  à jour le verdict pivot.
- Verdicts T2T3T23 et T25 déjà disponibles → si confirmés sur relecture,
  promotion prod possible (ces 2 transferts maintenus dans le
  `prompt_generator.py`).
- Optionnel : lancer la Phase 3 bonus
  (`PYTHONPATH=src python scripts/poc_bench_gate_ernie.py --transferts T9,ISO,ANAT,METEO`)
  pour mesures complémentaires non garde-fou.
