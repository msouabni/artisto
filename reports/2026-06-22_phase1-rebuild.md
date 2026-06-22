# Phase 1 — Rebuild (cockpit, prio 3)
Date : 2026-06-22

## Contexte

Track cockpit git-autoritaire, **priorité 3** (décision 4 de
`DIRECTION-PHASE-2026-06-22.md`) : le site est **statique** (Astro →
Cloudflare). Une page à `publishDate` future ne devient *live* que si un build
tourne **après** la date. Le cockpit doit donc piloter le rebuild : **à la
demande** (publication immédiate), par **cron horaire** (programmations échues),
et exposer un **signal « rebuild dû »**. Postgres uniquement.

## Résultats

| Livrable | Fichier | État |
|---|---|---|
| Table `schedule` (publish_date miroir + last_build_at ; rebuild_due dérivé) | `src/api/cockpit_models.py` | ✅ |
| `compute_rebuild_due(publish_date, last_build_at, now)` (fonction pure) | `src/services/rebuild.py` | ✅ |
| `trigger_rebuild()` configurable (hook / cmd / mock) | `src/services/rebuild.py` | ✅ |
| `rebuild_due_run(conn, now)` (cron) + `sync_schedule_from_git`, `fetch_due_schedules` | `src/services/rebuild.py` | ✅ |
| `POST /api/cockpit/rebuild` (à la demande) | `src/api/routes/cockpit_git.py` | ✅ |
| `POST /api/cockpit/rebuild/run-due` (cron) + `GET /api/cockpit/rebuild/due` | `src/api/routes/cockpit_git.py` | ✅ |
| Signal « rebuild dû » : `GET /api/cockpit/next-action` + kanban (`totals.rebuild_due` + badge carte) | `src/api/routes/cockpit_git.py` | ✅ |
| Tests Postgres éphémère (16) | `tests/cockpit/test_rebuild.py` | ✅ |

### Règle métier

```
rebuild_due = (publish_date <= now)
              ET (last_build_at IS NULL OU last_build_at < publish_date)
```

Une page **programmée arrivée à échéance mais pas encore rebuildée** est due.
`now` injectable. `publish_date = None` → jamais due (publiée à la date de
commit). Comparaison homogène : `date` nue promue à minuit UTC.

### Déclencheur (configurable, mocké)

`trigger_rebuild()` choisit par env, dans l'ordre : `REBUILD_HOOK_URL` (POST
deploy hook) → `REBUILD_CMD` (shell local) → **mock no-op loggué** (défaut).
`last_build_at = now` posé au succès. **Aucun deploy réel** sans env configuré.

### Les 3 options de déclencheur du cron horaire

`rebuild_due_run` / `POST .../rebuild/run-due` sont appelables par (au choix) :
1. **Cloudflare Cron Trigger** (Worker horaire → `fetch` run-due) — recommandé prod.
2. **Cron CI** (GitHub Actions `schedule:` → `curl` run-due).
3. **Le cockpit** (job type `rebuild` du framework worker, ou bouton UI).

Aucun cron système n'est installé dans cet incrément (fonction + endpoint).

### Tests

```
docker compose up -d postgres
python -m pytest tests/cockpit/ -q
→ 62 passed in 6.45s
```

dont `tests/cockpit/test_rebuild.py` : **16 passed**. Couvre :
- `compute_rebuild_due` : avant date = non due / échue sans build = due / build
  antérieur à publishDate = due / build postérieur = non due / no publishDate =
  non due / échéance pile = due.
- `trigger_rebuild` mock (triggered=True, mode=mock, pas d'erreur).
- `rebuild_due_run` : déclenche le mock, pose `last_build_at`, `due_after=0`,
  idempotent, no-op quand rien n'est dû.
- Endpoints à la demande + run-due (mock) + `GET /rebuild/due`.
- `next-action` surface le rebuild dû (priorité haute) et passe **avant** le
  drift ; `kind=none` quand tout est à jour.

### Démo

work_item programmé (`publish_date` = 2026-06-01, passée ; `last_build_at`
NULL) → `next-action`/`fetch_due_schedules` = « 1 page DUE (baleine) » →
`rebuild_due_run` (mode mock) pose `last_build_at` sur 1 schedule →
`fetch_due_schedules` = 0 (plus due). Reproduit par les tests
`test_rebuild_due_run_triggers_mock_and_clears_due` et
`test_endpoint_run_due_mock`.

## Points d'attention

- **Aucun déploiement prod déclenché** : sans `REBUILD_HOOK_URL` /`REBUILD_CMD`,
  `trigger_rebuild` reste un no-op loggué (mode mock). Conforme à la consigne
  « pas de hook réel déclenché ».
- `rebuild_due` n'est **jamais persisté** (dérivé à la lecture) — cap « pas de
  seconde vérité ».
- `POST /rebuild` (à la demande) stampe **toutes** les pages du repo (un build
  couvre tout le site statique) ; `run-due` ne stampe que les pages dues.
- 5 erreurs de collecte **préexistantes** hors cockpit
  (`ModuleNotFoundError: services.extract_palette`, WIP non commité sur la
  branche) — sans rapport avec cet incrément. Le modèle `Schedule` compile sous
  le `create_all` SQLite global (vérifié) → ne casse pas le conftest global.

## Décision / Action suivante

Incrément **livré**. Réserve : le **câblage Cloudflare réel** (deploy hook
effectif, Pages build, propagation CDN) appartient au **track Hamma** — ici
seul le contrat `trigger_rebuild` configurable + le mode mock sont fournis.
Choix d'orchestrateur cron (Cloudflare Cron Trigger / cron CI / cockpit) à
trancher avec l'exploitation.
