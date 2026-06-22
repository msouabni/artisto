# PLAN-PHASE1 — Cockpit git-autoritaire

Cadre : `DIRECTION-PHASE-2026-06-22.md` (repo `alwanbooks-docs`). Cap non
négociable : **git = vérité du contenu**. Le cockpit est un miroir + une couche
d'orchestration ; il ne sert jamais de contenu autoritaire. **PostgreSQL
unique** (SQLite interdit, y compris en test → faux verts).

## Track cockpit / git-indexer

| Prio | Tâche | État | Fichiers clés |
|---|---|---|---|
| 1 | Indexeur git + schéma `work_item`/`git_index` + kanban dérivé + drift + score de demande | ✅ | `src/services/git_indexer.py`, `git_states.py`, `src/api/routes/cockpit_git.py`, `src/api/cockpit_models.py` |
| 2 | Commit bot cockpit→git (seule porte d'entrée) + marqueur `launchSet` | ✅ | `src/services/cockpit_git_publish.py` |
| 3 | **Rebuild : à la demande + cron horaire + signal « rebuild dû »** | ✅ | `src/services/rebuild.py`, `src/api/cockpit_models.py` (table `schedule`), `src/api/routes/cockpit_git.py` |

## Prio 3 — Rebuild (décision 4 DIRECTION-2026-06-22) ✅

Le site est **statique** (Astro → Cloudflare) : une page à `publishDate` future
ne devient *live* que si un build tourne **après** la date. Le cockpit pilote
donc le rebuild.

### Modèle de données

Table **`schedule`** (`src/api/cockpit_models.py`) :
- `work_item_id` — référence souple vers `work_item.id` ;
- `publish_date` — **miroir** de `git_index.publish_date` (seule vérité de
  planification) ;
- `last_build_at` — timestamp ISO du dernier build *déployé* couvrant la page
  (seule donnée propre à la table : git ne sait rien des builds déployés) ;
- `rebuild_due` — **dérivé, jamais stocké** (cf. règle ci-dessous).

### Règle métier (fonction pure)

`compute_rebuild_due(publish_date, last_build_at, now)` dans
`src/services/rebuild.py` :

```
rebuild_due = (publish_date <= now)
              ET (last_build_at IS NULL OU last_build_at < publish_date)
```

→ une page **programmée arrivée à échéance mais pas encore rebuildée** est due.
`now` est injectable (testée avant date = non due / après date sans build = due
/ après build = non due).

### Déclencheur configurable (mocké)

`trigger_rebuild()` choisit le backend par environnement, dans l'ordre :
1. `REBUILD_HOOK_URL` → POST sur un deploy hook (Cloudflare / staging) ;
2. `REBUILD_CMD` → commande shell locale (dev, ex. `npm run build`) ;
3. aucun → **no-op loggué** (mode **mock**, défaut).

Au succès, `last_build_at = now` est posé. **Aucun deploy réel** tant qu'aucune
variable d'env n'est configurée. Le câblage Cloudflare effectif relève du
**track Hamma**.

### Déclenchement « à la demande » vs « cron »

- **À la demande** (publication immédiate) : `POST /api/cockpit/rebuild` →
  `trigger_rebuild()`, stampe `last_build_at` sur toutes les pages du repo
  (un build couvre tout le site). Renvoie `{triggered, mode, built_at}`.
- **Cron horaire** : `rebuild_due_run(conn, now)` (fonction) +
  `POST /api/cockpit/rebuild/run-due`. Ne déclenche **un** build que si des
  pages sont dues (`compute_rebuild_due`), pose `last_build_at`, vérifie que
  plus aucune n'est due. No-op si rien n'est dû (pas de build inutile).
  Idempotent.

### Les 3 options de déclencheur du cron horaire

Le cron n'installe **aucun planificateur système** : c'est une fonction +
endpoint appelables par l'un des trois orchestrateurs suivants (au choix de
l'exploitation) :

1. **Cloudflare Cron Trigger** (Worker `*/60 * * * *` → `fetch` sur
   `POST /api/cockpit/rebuild/run-due`). Recommandé en prod (colocalisé avec le
   deploy hook ; pas d'infra cron à maintenir).
2. **Cron CI** (GitHub Actions `schedule:` horaire → `curl -XPOST .../run-due`,
   ou exécution directe de `rebuild_due_run`). Utile si le pipeline de build est
   déjà en CI.
3. **Le cockpit lui-même** (tâche de fond / job type `rebuild` du framework
   worker générique, ou bouton « vérifier les programmations » dans l'UI).
   Pratique en dev / self-hosted.

### Signal « rebuild dû » (next-action + kanban)

- `GET /api/cockpit/next-action` (« Reprends ici ») : **priorité haute** au
  rebuild dû — « N page(s) programmée(s) en attente de rebuild » → action =
  `POST /api/cockpit/rebuild/run-due`. À défaut, signale le drift (priorité
  moyenne), sinon « tout est à jour ».
- `GET /api/cockpit/kanban` : `totals.rebuild_due` + badge `rebuild_due` par
  carte concernée.
- `GET /api/cockpit/rebuild/due` : liste détaillée des pages actuellement dues.

### Tests

`tests/cockpit/test_rebuild.py` (Postgres éphémère, 16 tests) : règle pure,
`rebuild_due_run` (mock pose `last_build_at` → repasse non-due, idempotent,
no-op si rien dû), endpoints à la demande + run-due (mock), next-action surface
le rebuild dû (et passe avant le drift). **Aucun deploy réel, hook mocké.**

### Réserves

- Câblage **Cloudflare réel** (deploy hook effectif, Pages build, propagation) =
  **track Hamma**. Ici uniquement le contrat (`trigger_rebuild` configurable) +
  le mode mock.
- Pas de planificateur système installé : les 3 options ci-dessus sont
  documentées, leur mise en place opérationnelle est hors incrément.
