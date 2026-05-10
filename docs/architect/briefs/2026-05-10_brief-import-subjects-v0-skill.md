# Import subjects v0 depuis skill — script one-shot idempotent

## Contexte

Vision MEP v0 (cf. `docs/architect/2026-05-10_spec-mep-v0.md`) : la **source initiale des subjects** est le skill `prompt-taxonomy-ecosystem` (référence v0). Pour amorcer la pipeline, il faut alimenter la table `subject` (créée par brief V1.2) avec un subject par leaf de la taxonomie de référence.

État actuel :
- Taxonomie 1376 leaves : `data/prompt_generator/coloring_taxonomy_full.json` (consommé par `PromptGenerator`).
- Skill packagé : `.claude/skills/prompt-taxonomy-ecosystem.skill` (zip avec `SKILL.md` + `references/taxonomy_full.md` + `references/techniques.md` + `references/taxonomy_summary.md`).
- Table `term` : existe et contient les leaves taxonomie.
- Table `subject` : créée par V1.2.

## Objectif

Créer un script `scripts/import_subjects_v0_from_skill.py` qui parcourt la taxonomie de référence et **insère un subject par leaf** dans la table `subject`. Idempotent (réexécutable sans doublon ni erreur).

## Périmètre

### Script

`scripts/import_subjects_v0_from_skill.py` :

**Source de données** : `data/prompt_generator/coloring_taxonomy_full.json` est la source canonique (cf. `PromptGenerator` qui l'utilise déjà). Le skill packagé contient une version dérivée (`references/taxonomy_full.md`) mais non structurée — préférer le JSON.

**Logique** :

1. Lire `data/prompt_generator/coloring_taxonomy_full.json`.
2. Aplatir la structure arbre → liste de leaves (`leaf_id`, `name_en`, parent path).
3. Pour chaque leaf :
   - Vérifier que le `term_id` correspondant existe en BD (table `term`).
   - Vérifier qu'aucun `subject` n'existe déjà avec `(term_id=<leaf>, source='skill_v0')` (idempotence).
   - Insérer un subject :
     - `id` : généré (`f"sub_{leaf_id}"` ou UUID — choisir une convention stable, préférer `sub_{leaf_id}` pour traçabilité humaine)
     - `term_id` : leaf_id
     - `name` : `name_en` du leaf
     - `source` : `'skill_v0'`
     - `tags` : `[]`
     - `note` : NULL
     - `status` : `'draft'`
     - `enrichment` : NULL
     - `prompt_positive` : NULL (sera renseigné par job `subject_prompt_generation` plus tard)
     - `metadata` : `{"imported_from": "coloring_taxonomy_full.json", "import_run": "<timestamp>"}`
4. Persister via `Session` SQLAlchemy directement (`get_db_write` ou `SessionLocal()` selon convention scripts).
5. Reporter : nombre total leaves, nombre insérés, nombre déjà présents (idempotence), liste des leaves sans `term_id` en BD (anomalie).

**CLI** : Typer ou argparse minimal.

| Option | Effet |
|---|---|
| `--dry-run` | N'écrit pas, affiche le résumé attendu |
| `--limit N` | Pour tests, limite à N leaves |
| `--source skill_v0` | Override source (utile pour future réimportation depuis autre référence) |
| `--rapport-dir PATH` | Où écrire le rapport JSON (`data/import/subjects_v0_<timestamp>.json`) |

### Rapport généré

`docs/reports/2026-05-10_import-subjects-v0-skill.md` + `data/import/subjects_v0_<timestamp>.json` :

| Section | Contenu |
|---|---|
| Compteurs | Total leaves dans la taxonomie / leaves avec term en BD / subjects insérés / subjects déjà présents (idempotent) / leaves orphelins |
| Liste orphelins | Pour chaque leaf sans term en BD, indiquer pourquoi (ex. `term` n'a pas encore été seedé). À régler avant import définitif. |
| Distribution par root | Compte de subjects insérés par catégorie racine (animals, fictional_characters, etc.) |
| Échantillon | 10 subjects insérés avec leur `id`, `term_id`, `name` |

### Tests

`tests/test_import_subjects_v0.py` (nouveau) :

- Smoke : sur un mini-fichier taxonomie test (3 leaves), script insère 3 subjects.
- Idempotence : 2e exécution → 0 nouveaux subjects, pas d'erreur.
- Dry-run : `--dry-run` n'écrit pas en BD.
- Leaves orphelins (term inexistant) : pas d'erreur fatale, listés dans le rapport.
- Schéma : subjects insérés ont les champs attendus (`source='skill_v0'`, `status='draft'`, `tags=[]`).
- Tests SQLite-portables (in-memory).

## Critères d'acceptation

- Script exécutable : `python scripts/import_subjects_v0_from_skill.py --dry-run` puis sans `--dry-run`.
- Idempotent : 2 exécutions consécutives → aucune insertion en double, aucune erreur.
- Rapport généré conforme à la spec ci-dessus.
- Tests pytest verts (≥ 5 nouveaux tests).
- Pas de breaking change.
- Sur la base actuelle (taxonomie 1376 leaves), import attendu : **318 subjects publishables** (cf. corpus MEP v0 mesuré) — mais le script importe **tous les leaves** sans filtrer ; le filtrage par tag/règle se fera en Vague 2 (annotation + filtre).
- Pas d'effet sur les 53 leafs ex-frieze : ils sont importés en tant que subjects normaux (`status='draft'`) mais ne passeront pas le filtre tags en aval (à régler côté config filtre).

## Hors scope

- Filtrage par tag à l'import (le filtrage se fait en aval via annotation + règles par term).
- Génération automatique du prompt à l'import (job `subject_prompt_generation` séparé, Vague 2).
- Import depuis le skill .skill packagé (utiliser le JSON canonique, le skill packagé est dérivé).
- Création/seed de la table `term` si vide (prérequis : `term` doit déjà être seedée — vérifier via `python scripts/seed_data.py` ou équivalent).

## Plan d'exécution suggéré (sous-agent unique)

```
Phase 1 — Audit data (~10 min)
  - Vérifier coloring_taxonomy_full.json structure (1376 leaves attendus)
  - Vérifier table term peuplée

Phase 2 — Script (~30 min)
  - Argparse/Typer
  - Aplatissement taxonomie
  - Insertion idempotente avec Session

Phase 3 — Tests (~15 min)
  - 5 tests sur mini-fichier

Phase 4 — Exécution réelle dry-run + run (~10 min)
  - Validation rapport
  - Distribution par root
```

## Reporting

`docs/reports/2026-05-10_import-subjects-v0-skill.md` (sortie du script + interprétation).

## Estimation

~45-60 min dev + tests + rapport + run réel.

## Dépendance

V1.2 (modèle `subject`) doit être livré avant — sinon insertion impossible. Si V1.2 et V1.3 sont lancés en parallèle, l'agent V1.3 peut préparer le script et attendre que V1.2 soit mergé pour exécuter le run réel.
