# Protocole de clôture Vague 1 MEP v0

Date : 2026-05-10
Source : `docs/architect/2026-05-10_spec-mep-v0.md` + 4 rapports `docs/reports/2026-05-10_{simplification-worker-image,modele-subject,import-subjects-v0,qc-auto-worker}.md`.

## Objectif

Merger les 4 worktrees Vague 1 dans `main`, appliquer la migration Postgres, valider en prod, fermer la dette sidecar, classer la Vague 1 en livrée. Sans introduire de régression.

## Pré-requis

- Notification de completion reçue pour les 4 agents (V1.1, V1.2, V1.3, V1.4) — ✅ acquise 2026-05-10.
- Branche `main` à jour, working tree propre.
- Postgres dev accessible (`docker compose up -d postgres`).
- ComfyUI accessible pour smoke E2E post-merge.

## Séquence — 13 étapes

### 1. État des worktrees

```bash
git worktree list
# Doit afficher 4 worktrees : agent-a2b1fb942398d9ce7 (V1.1),
# agent-a14038c22bcfae2e5 (V1.2), agent-a81013a5b0b458730 (V1.3),
# agent-adfb8ecda905b9d36 (V1.4)
```

Pour chaque worktree, vérifier diff vs `main` :

```bash
git -C .claude/worktrees/agent-a2b1fb942398d9ce7 diff main --stat
git -C .claude/worktrees/agent-a14038c22bcfae2e5 diff main --stat
git -C .claude/worktrees/agent-a81013a5b0b458730 diff main --stat
git -C .claude/worktrees/agent-adfb8ecda905b9d36 diff main --stat
```

Confirmer périmètre conforme aux briefs (fichiers attendus, pas de fichier inattendu).

### 2. Merge V1.1 — Simplification worker image

V1.1 est autonome, pas de dépendance. Merger en premier pour clôturer la dette sidecar.

```bash
# Depuis main
git merge worktree-agent-a2b1fb942398d9ce7
pytest --ignore=tests/test_content_generator.py
# Attendu : 190 passed
```

**Checkpoint** : suite globale doit être verte (sauf `test_content_generator.py` dette legacy). Si rouge, identifier la régression avant de continuer.

### 3. Merge V1.2 — Modèle `subject`

V1.2 est autonome côté code. Migration 0007 indépendante de 0008 (V1.4).

```bash
git merge worktree-agent-a14038c22bcfae2e5
pytest --ignore=tests/test_content_generator.py tests/test_subjects_api.py
# Attendu : 25 passed
pytest --ignore=tests/test_content_generator.py
# Attendu : ~215 passed (190 + 25)
```

### 4. Appliquer migration 0007 sur Postgres dev

```bash
alembic upgrade head
# Vérifier la table 'subject' créée
psql $DATABASE_URL -c "\d subject"
```

**Checkpoint** : table `subject` présente avec 11 colonnes, 2 CHECK, FK composite vers `term`.

### 5. Rebase migration 0008 (V1.4) sur 0007

V1.4 a `down_revision = '0006_annotation_polymorphic'`. Doit pointer vers `0007_subject_table` après merge V1.2.

```bash
# Dans le worktree V1.4
cd .claude/worktrees/agent-adfb8ecda905b9d36

# Éditer alembic/versions/0008_image_output_qc_tags.py :
#   down_revision = '0007_subject_table'   # au lieu de '0006_annotation_polymorphic'

# Vérifier la chaîne Alembic
alembic history
# Attendu : 0006 → 0007 → 0008 linéaire

# Commit le fix (worktree V1.4)
git add alembic/versions/0008_image_output_qc_tags.py
git commit -m "fix: rebase 0008 on 0007_subject_table"

cd ../../..
```

### 6. Merge V1.4 — qc_worker

```bash
git merge worktree-agent-adfb8ecda905b9d36
pytest --ignore=tests/test_content_generator.py tests/test_qc_worker.py
# Attendu : 21 passed
pytest --ignore=tests/test_content_generator.py
# Attendu : ~236 passed (215 + 21)
```

### 7. Appliquer migration 0008 sur Postgres dev

```bash
alembic upgrade head
# Vérifier la colonne 'qc_tags' sur image_output
psql $DATABASE_URL -c "\d image_output" | grep qc_tags
# Attendu : qc_tags | jsonb |
```

### 8. Merge V1.3 — Import subjects v0

V1.3 contient une injection `Subject` minimale qui se court-circuite après merge V1.2 (via `hasattr`).

```bash
git merge worktree-agent-a81013a5b0b458730
pytest --ignore=tests/test_content_generator.py tests/test_import_subjects_v0.py
# Attendu : 17 passed
pytest --ignore=tests/test_content_generator.py
# Attendu : ~253 passed (236 + 17)
```

### 9. Run réel import V1.3

```bash
python scripts/import_subjects_v0_from_skill.py --dry-run
# Vérifier : 1376 leaves attendus, 0 orphelins, distribution par root attendue

python scripts/import_subjects_v0_from_skill.py
# Insertion réelle : 1376 subjects créés, source='skill_v0', status='draft'

# Vérifier en base
psql $DATABASE_URL -c "SELECT COUNT(*) FROM subject;"
# Attendu : 1376

psql $DATABASE_URL -c "SELECT source, status, COUNT(*) FROM subject GROUP BY source, status;"
# Attendu : skill_v0 | draft | 1376
```

### 10. Activer job type `image_qc_auto`

Le job type est seedé `enabled=False` par défaut.

```bash
# Soit via API
curl -X PUT http://127.0.0.1:8000/api/jobs/types/image_qc_auto \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Soit via Jobs editor UI : http://127.0.0.1:8000/data/jobs_editor.html
```

### 11. Créer `scripts/run_qc_worker.py`

Hors brief V1.4 mais nécessaire pour démarrer le worker QC. Analogue à `scripts/run_image_worker.py`.

```python
# scripts/run_qc_worker.py
"""Démarre le worker QC auto (déterministe, no LLM)."""
import argparse
from workers.qc_worker import QCWorker

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Traite un seul job puis exit")
    args = parser.parse_args()
    worker = QCWorker()
    if args.once:
        worker.run_once()
    else:
        worker.run_loop()

if __name__ == "__main__":
    main()
```

**Brief mini** : 1 sous-agent ~15 min, ou fait à la main par l'archi.

### 12. Smoke E2E post-merge

Vérifier que la chaîne complète fonctionne en bout-en-bout :

```bash
# Démarrer la stack
python start.py --no-reload

# Dans un autre terminal : créer 1 job image via API
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "type": "image_generation",
    "entity_type": "image",
    "entity_id": "<image_id_existante_status_scheduled>",
    "config": {
      "positive_prompt": "a cute cat sitting on grass",
      "workflow_template": "ernie-image-turbo-q8-api",
      "seed": 42
    }
  }'

# Attendre completion
# Vérifier image_output créé
# Vérifier job image_qc_auto créé automatiquement (trigger)
# Vérifier qc_tags posés après ~1s
psql $DATABASE_URL -c "SELECT qc_tags FROM image_output ORDER BY created_at DESC LIMIT 1;"
# Attendu : ["qc_ok"] ou liste de tags
```

**Checkpoint final** : pipeline `image_generation → image_output → image_qc_auto → qc_tags` opérationnel.

### 13. Cleanup worktrees + MAJ MEMORY

```bash
# Supprimer les 4 worktrees
git worktree remove .claude/worktrees/agent-a2b1fb942398d9ce7
git worktree remove .claude/worktrees/agent-a14038c22bcfae2e5
git worktree remove .claude/worktrees/agent-a81013a5b0b458730
git worktree remove .claude/worktrees/agent-adfb8ecda905b9d36

# Supprimer les branches worktree
git branch -D worktree-agent-a2b1fb942398d9ce7
git branch -D worktree-agent-a14038c22bcfae2e5
git branch -D worktree-agent-a81013a5b0b458730
git branch -D worktree-agent-adfb8ecda905b9d36
```

MAJ MEMORY :
- Passer la ligne `Vague 1 MEP v0 lancée — 4 sous-agents background worktree` de `lancé` à `fait 2026-05-10`.
- Acter la chaîne complète subject → image → QC opérationnelle.
- Mettre à jour la dette technique : 5 tests préexistants ERNIE clôturés.

MAJ démarche `docs/architect/2026-05-10_demarche-transferts-skill.md` + `docs/architect/2026-05-10_spec-mep-v0.md` : marquer Vague 1 livrée, ouvrir Vague 2.

## Critères de sortie de la Vague 1

- ✅ Suite pytest verte : ~253 passed (hors `test_content_generator.py` dette legacy).
- ✅ Migrations 0007 + 0008 appliquées sur Postgres dev.
- ✅ 1376 subjects insérés (status='draft', source='skill_v0').
- ✅ Job type `image_qc_auto` enabled.
- ✅ Smoke E2E : 1 image générée → qc_tags posés automatiquement.
- ✅ 4 worktrees supprimés.
- ✅ MEMORY + démarche + spec MEP v0 à jour.

## Risques + rollback

| Risque | Mitigation | Rollback |
|---|---|---|
| Conflit merge V1.2 vs V1.4 sur `src/api/models.py` | Zones disjointes (`Subject` vs `ImageOutput.qc_tags`), merge linéaire attendu | Si conflit imprévu : merge manuel à 3-way ; tests pour valider |
| Conflit merge V1.1 vs V1.4 sur `src/workers/image_worker.py` | V1.1 refactor `process()`, V1.4 ajoute `_enqueue_qc_job` dans `save_result` (non touché par V1.1) | Si conflit : conserver les deux modifs (zones distinctes) |
| Migration 0008 plante en prod | SQL upgrade simple `ADD COLUMN qc_tags JSONB` (idempotent rare avec `IF NOT EXISTS` à ajouter au besoin) | `alembic downgrade 0007` (downgrade validé offline) |
| Import V1.3 timeout sur 1376 leaves | Batch d'insertion via `Session` (rapide), pas d'appel externe | `python scripts/import_subjects_v0_from_skill.py --limit 100` pour tester |
| qc_worker fait du bruit en prod (50% `qc_color_residual` sur calibration) | Recalibration seuil à 0.005-0.01 si tag posé trop souvent | Modifier `QC_COLOR_RESIDUAL_THRESHOLD` dans `qc_worker.py` + rerun |
| Smoke E2E échoue | ComfyUI ou worker non démarré | Vérifier `python start.py` logs, `tail logs/api.log logs/image_worker.log` |

## Estimation

- Étapes 1-2 (état + merge V1.1) : ~10 min
- Étapes 3-4 (merge V1.2 + migration 0007) : ~10 min
- Étapes 5-7 (rebase 0008 + merge V1.4 + migration 0008) : ~15 min
- Étapes 8-9 (merge V1.3 + run import) : ~10 min
- Étapes 10-11 (activer job type + script run_qc_worker) : ~15 min
- Étape 12 (smoke E2E) : ~10 min
- Étape 13 (cleanup + MEMORY) : ~10 min

**Total Vague 1 clôturée en ~1h20.**

## Action suivante (post-clôture)

Une fois Vague 1 fermée :

1. **Cadrage MEP v0** (bloqueur n°1) : périmètre fonctionnel + critères de sortie + date cible.
2. **Vague 2 MEP v0** rédigée : 4 briefs (V2.1 annotateur subject mode, V2.2 filtre tags + règles par term, V2.3 ai_pipeline_worker enrichissement i18n, V2.4 wrapper job prompt_generation).
3. **Vague 3** (publication plateforme Alwan Books) : à cadrer en parallèle.
