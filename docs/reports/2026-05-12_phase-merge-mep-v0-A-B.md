# Phase — Merge MEP-v0/A + MEP-v0/B sur main
Date : 2026-05-12

## Contexte

Les briefs MEP-v0/A (`feat/mep-v0-A-modele-publication`, commit `185f744`) et
MEP-v0/B (`feat/mep-v0-B-i18n-batch`, 4 commits) ont été livrés en parallèle
de la Vague 1 user. Ils sont sémantiquement orthogonaux à la Vague 1 mais la
branche A portait une migration Alembic numérotée `0007_image_publication`
qui entrait en conflit avec la `0007_subject_table` livrée sur main par la
Vague 1.

État Alembic sur main avant ce merge :
- 0001 → 0006 (pré-Vague 1)
- 0007_subject_table, 0008_image_output_qc_tags, 0009_subject_add_source (Vague 1)

Objectif :
1. Renuméroter la 0007 de la branche A en 0010
2. Squash-merger A puis B sur main
3. Garantir `alembic upgrade head` + suite pytest globale verte
4. Nettoyer worktrees + branches

## Modifications

| Fichier | Type | LOC | Origine |
|---|---|---|---|
| `alembic/versions/0010_image_publication.py` | NEW | 84 | A (renommé depuis `0007_image_publication.py`, `down_revision` repointé sur `0009_subject_add_source`) |
| `src/api/models.py` | M | +47 | A (ajout pur de la classe `ImagePublication`, pas de modif des modèles existants) |
| `src/api/image_publication.py` | NEW | 239 | A (helpers `create_for_image`, `get_for_image`, `mark_status`) |
| `tests/test_image_publication.py` | NEW | 482 | A (24 tests SQLite in-memory) |
| `docs/reports/2026-05-10_phase-mep-v0-A-modele-publication.md` | NEW | 157 | A (rapport de phase A, repris tel quel — référence à l'ancienne mig `0007` conservée par fidélité historique) |
| `scripts/poc_generate_i18n.py` | NEW | 853 | B (script batch i18n des leaves publishable) |
| `tests/test_i18n_batch.py` | NEW | 712 | B (35 tests : 27 i18n + 8 think:false natif qwen3.5+) |
| `data/export/_i18n_batch.json` | NEW | ~ | B (output partiel, 16 leaves complétées) |
| `data/export/_i18n_batch_progress.json` | NEW | ~ | B (état du batch en cours) |
| `data/export/_i18n_batch_progress.qwen3_8b.archive.json` | NEW | ~ | B (checkpoint qwen3:8b pré-bascule qwen3.5:4b) |
| `docs/reports/2026-05-10_phase-mep-v0-B-i18n-batch.md` | NEW | 378 | B (rapport de phase B) |
| `docs/reports/2026-05-12_phase-merge-mep-v0-A-B.md` | NEW | — | ce rapport |

**Total** : 12 fichiers ajoutés/modifiés, 1009 LOC (A) + 23873 LOC (B incluant le JSON batch sérialisé) = ~24882 lignes nettes ajoutées.

Aucune modification sur les fichiers Vague 1 (`0007_subject_table.py`,
`0008_image_output_qc_tags.py`, `0009_subject_add_source.py`).
Aucun fichier hors whitelist touché.

## Commits

| Hash | Titre | Branche |
|---|---|---|
| `aeddf6a` | `chore(MEP-v0/A): renumérotation Alembic 0007 → 0010 (après Vague 1)` | `feat/mep-v0-A-modele-publication` (supprimée) |
| `f2e6ca6` | `feat(MEP-v0/A): modèle DB publication + transitions statuts (mig 0010)` | `main` |
| `85948a4` | `feat(MEP-v0/B): batch i18n + patch think:false qwen3.5+ (script + 35 tests + output)` | `main` |

Le commit `aeddf6a` n'existe plus dans le graphe (branche A supprimée après
squash-merge). Son contenu (renommage + down_revision) est intégré dans
`f2e6ca6`. C'est conforme à l'objectif squash-merge du brief.

## Stratégie technique de merge — note importante

Les branches A et B avaient pour base le commit `89e3d08` (avant Vague 1).
Entre cette base et le HEAD de main, la Vague 1 a supprimé ~27 000 LOC
(refactor majeur : `prompt_generator.py`, `prompt_filters.py`, `qc_worker.py`,
`routes/subjects.py`, etc.). Un `git merge --squash` direct depuis main aurait
réintroduit ce code supprimé (effet de `merge --squash` qui prend le delta
total `main..branche` et non `base..branche`).

Solution adoptée : extraction du **delta net** `base..branche` puis application
restreinte :
- `git diff 89e3d08..feat/mep-v0-A-modele-publication -- src/api/models.py | git apply --3way` (fusion propre avec les modifs Vague 1 sur `models.py`)
- `git checkout feat/mep-v0-A-modele-publication -- <fichiers nouveaux>` pour les fichiers strictement ajoutés
- Idem pour B (uniquement des ajouts, pas de modifs sur fichiers existants)
- `cp` manuel pour les 3 fichiers `data/export/` non-trackés dans la worktree B (le brief les inclut explicitement dans la whitelist)

Aucun conflit textuel n'est apparu. Le `git apply --3way` sur `models.py` a
appliqué cleanement l'ajout d'`ImagePublication` (la zone autour de
`AiPromptTemplate` n'avait pas été touchée par la Vague 1).

## Tests

### Pytest baseline (main avant merge)

```
PYTHONPATH=src pytest --ignore=tests/test_content_generator.py
452 passed in 7.59s
```

Pas de tests Ernie sidecar KO observés dans la baseline actuelle (la dette
mentionnée par le brief — "5 tests Ernie sidecar pré-existants peuvent
rester KO" — n'est plus visible sur le HEAD main `94b8f37`).

### Pytest après merge A

```
476 passed in 3.81s
```

+24 tests = exactement le compte annoncé pour A. Aucune régression.

### Pytest après merge B (final)

```
511 passed in 4.11s
```

+35 tests vs après-A = exactement le compte annoncé pour B.
+59 tests vs baseline = 24 (A) + 35 (B). Suite 100 % verte.

### Alembic

État après merge A + upgrade :

```
$ alembic history
0009_subject_add_source -> 0010_image_publication (head), create image_publication table (publication layer i18n)
0008_image_output_qc_tags -> 0009_subject_add_source, add source column to subject
0007_subject_table -> 0008_image_output_qc_tags, add qc_tags column on image_output
0006_annotation_polymorphic -> 0007_subject_table, create subject table
0005_term_metadata_jsonb -> 0006_annotation_polymorphic, ...
0004_seed_new_job_types -> 0005_term_metadata_jsonb, ...
0003_job_duration_ms -> 0004_seed_new_job_types, ...
0002_seed_job_type_config -> 0003_job_duration_ms, ...
0001_initial -> 0002_seed_job_type_config, ...
<base> -> 0001_initial, initial schema via SQLAlchemy metadata

$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 0009_subject_add_source -> 0010_image_publication, create image_publication table (publication layer i18n)

$ alembic current
0010_image_publication (head)
```

Chaîne 0001 → 0010 monotone, un seul head, table `image_publication` créée
sur Postgres sans erreur. La migration 0010 ne touche aucune table existante,
elle crée la table publication + 2 index + 1 contrainte UNIQUE + 1 FK CASCADE.

## Nettoyage worktrees + branches

| Élément | État |
|---|---|
| Worktree `agent-a73a97f8d140020f0` (B) | ✅ Supprimée (Git + disque) |
| Worktree `agent-aaed0f266ab4b0a45` (A) | ✅ Désenregistrée côté Git ; le répertoire physique reste sur disque car l'agent qui exécute ce merge a son CWD dans cette worktree (Windows refuse `rm` d'un répertoire ouvert par un autre processus). À nettoyer manuellement après fin de session ou via redémarrage. |
| Branche `feat/mep-v0-A-modele-publication` | ✅ Supprimée |
| Branche `feat/mep-v0-B-i18n-batch` | ✅ Supprimée |
| Branche `worktree-agent-aaed0f266ab4b0a45` | ✅ Supprimée |
| Branche `worktree-agent-a73a97f8d140020f0` | ✅ Supprimée |

`git worktree list` :
```
D:/projets/artiste-coloriage                                         85948a4 [main]
D:/projets/artiste-coloriage/.claude/worktrees/serene-hodgkin-26db43 74f279e [claude/serene-hodgkin-26db43]
```

(la worktree `serene-hodgkin-26db43` n'est pas dans le périmètre de ce brief.)

## Points d'attention

1. **Stratégie de merge non-triviale**. Les branches A/B avaient une base
   antérieure à la Vague 1. Un `git merge --squash` direct aurait régressé
   ~27 KLOC supprimées par la Vague 1. L'application a été faite par delta
   net `base..branche`. À garder en tête si d'autres branches longues sont
   à merger plus tard.

2. **Worktree A physiquement présente**. Le répertoire
   `.claude/worktrees/agent-aaed0f266ab4b0a45` reste sur disque (Git ne le
   track plus). Sans impact fonctionnel mais à supprimer manuellement.

3. **Fichiers `data/export/` non-trackés dans la worktree B**. Le brief les
   listait dans la whitelist, ils ont été inclus dans le commit B. Si ces
   fichiers étaient intentionnellement laissés hors versionnement (batch
   reproductible à la demande), ils peuvent être ajoutés à `.gitignore`
   en follow-up.

4. **Rapport de phase A référence l'ancienne migration `0007_image_publication.py`**.
   Conservé tel quel par fidélité historique (convention reporting :
   les rapports sont immuables). La trace de la renumérotation est dans
   ce rapport-ci.

5. **Suite Ernie sidecar**. Le brief évoquait "5 tests Ernie sidecar
   pré-existants peuvent rester KO". Ils ne sont pas observés dans la
   baseline actuelle (452 passed, 0 failed). Aucune régression à signaler.

## Décision / Action suivante

- ✅ Tous les critères d'acceptation du brief sont remplis.
- ✅ **Bloqueur n°1 MEMORY levé** : la chaîne Alembic est propre, prête pour
  les briefs suivants (notamment Brief C — export final consommant le modèle A
  + le batch B).
- 🟡 **Brief C peut maintenant être dispatché** : il consommera
  `ImagePublication` (A) + le batch `data/export/_i18n_batch.json` (B) pour
  produire l'export final vers la plateforme Alwan.
- 🟡 **Follow-up post-v0** : le patch propre `ollama_json.py` (brief B
  "patch-think-false") mentionne déjà l'implémentation côté main — vérifier
  cohérence avec la documentation du rapport B (déjà conforme au CLAUDE.md
  qui décrit `_supports_native_think_disable`).
- 🟡 **Nettoyage manuel** : supprimer le répertoire physique
  `.claude/worktrees/agent-aaed0f266ab4b0a45` après la fin de cette session
  d'agent.
