# Phase 1 — Intégration indexation (cache `index_status`) · prêt-à-brancher

Date : 2026-06-22
Branche : `feat/cockpit-git-indexer`
Cadre : `DIRECTION-PHASE-2026-06-22.md` (track cockpit, prio 4) + ADR
`2026-06-22_DOSSIER-cockpit-plan-controle-git-verite.md` (table `index_status`).

## Contexte

Le cockpit doit afficher, par page, son **état d'indexation** côté Google
(Search Console URL Inspection) et Bing (Webmaster). Les creds GSC/Bing relèvent
du **track Hamma** (non disponibles à ce stade). On livre donc le **cache +
l'affichage + l'état dérivé**, avec un **provider mock actif** maintenant et les
**deux providers réels implémentés mais gatés sur env** — brancher = poser les
variables d'environnement, **aucun changement de code**.

**Périmètre strict** : URL Inspection / **couverture** uniquement. La
performance (Search Analytics : impressions/clics/position) est **Phase 2** —
explicitement hors scope.

## Résultats

| Livrable | État | Fichier |
|---|---|---|
| Table `index_status` (`url`·`engine`·`coverage_state`·`last_crawl`·`fetched_at`, unique `(engine,url)`) | ✅ | `src/api/cockpit_models.py` |
| Interface `IndexProvider` (protocole) | ✅ | `src/services/index_providers.py` |
| `GscUrlInspectionProvider` (réel, gated `GSC_*`, quota+back-off, non-200→`unknown`) | ✅ implémenté, **inactif sans creds** | `src/services/index_providers.py` |
| `BingWebmasterProvider` (réel, gated `BING_WEBMASTER_API_KEY`) | ✅ implémenté, **inactif sans creds** | `src/services/index_providers.py` |
| `MockIndexProvider` (déterministe, hors-ligne) | ✅ **actif (défaut)** | `src/services/index_providers.py` |
| Sélection auto (creds → réel, sinon mock) | ✅ | `select_provider()` |
| Sync `POST /api/cockpit/index-status/sync` + upsert | ✅ | `src/services/index_sync.py`, `src/api/routes/cockpit_git.py` |
| Lecture `GET /api/cockpit/index-status` | ✅ | `src/api/routes/cockpit_git.py` |
| Enrichissement kanban + work-items (`coverage_state`, `coverage`, `indexed`, `url`) | ✅ | `src/api/routes/cockpit_git.py` |
| État dérivé `indexé` (`coverage_state == indexed`, jamais stocké) | ✅ | `derive_index_state()` |
| Badge couleur + bouton « Sync indexation » | ✅ | `data/cockpit_kanban.html` |
| Signal next-action « publiées non indexées » (prio basse) | ✅ | `src/api/routes/cockpit_git.py` |
| Tests Postgres éphémère (21) | ✅ | `tests/cockpit/test_index_status.py` |

### Tests

```
docker compose up -d postgres
pytest tests/cockpit/
→ 83 passed (dont 21 nouveaux index_status, 0 régression)
pytest tests/cockpit/test_index_status.py
→ 21 passed
```

Couverture des tests : upsert/lecture sur clé `(engine, url)` (insert puis update
idempotent), agrégat multi-moteur (couverture la plus favorable), sélection
provider (mock par défaut ; **réel sélectionné si env GSC/Bing simulées mais
`inspect` monkeypatché → zéro réseau**), sync mock sur les 10 URLs marines (cache
peuplé, idempotent), kanban/work-items exposent `coverage_state` + `indexed`,
page sans cache → `unknown`/`indexed=False` (pas de crash), next-action
« publiées non indexées ». **Aucun SQLite, aucun réseau.**

### Démo (mock, 10 URLs marines)

Schéma Postgres éphémère, 10 work_items marins, sync `engine=gsc` en mock :

```
provider live (gsc)? False
SYNC REPORT (mock): {"engine":"gsc","provider":"mock","requested":10,"inserted":10,
                     "updated":0,"indexed":8,"by_state":{"indexed":8,"crawled_not_indexed":2}}
CACHE index_status (10 URLs):
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/baleine/
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/poisson-facile/
  crawled_not_indexed  indexe=False  https://alwanbooks.com/fr/colorier/tortue-de-mer/
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/hippocampe/
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/crabe/
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/poisson-rouge/
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/pieuvre/
  crawled_not_indexed  indexe=False  https://alwanbooks.com/fr/colorier/baleine-bleue/
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/meduse/
  indexed              indexe=True   https://alwanbooks.com/fr/colorier/poisson-rigolo/
```

→ cache peuplé, état `indexé` dérivé (8 vrais), 2 cas non triviaux
`crawled_not_indexed` (= « publié non indexé »), `provider=mock` (creds absentes).

## Points d'attention

- **`index_status` = cache lecture**, jamais une vérité de contenu (vérité =
  API moteur ; git = vérité du contenu). L'état `indexé` est **dérivé** (fonction
  pure `derive_index_state`), **jamais persisté** — cohérent avec `git_states`.
- **URL dérivée** de `(locale, slug)` via `work_item_url` =
  `{COCKPIT_SITE_BASE}/{locale}/colorier/{slug}/` (convention prompt-generator).
  La clé du cache est interne et **cohérente entre sync et affichage** ; l'URL
  publique exacte (le registry réel utilise `/coloriages/animaux-marins/<slug>`)
  sera arbitrée au branchement des creds — surchargeable par `COCKPIT_SITE_BASE`.
- **Aucun appel réseau sans creds** : `select_provider` retombe sur le mock ;
  les providers réels ne sont jamais *appelés* (défense en profondeur : leur
  `inspect` re-vérifie `available()`).
- Table créée par `create_all` (scan `Base.metadata`), pas de migration Alembic
  dédiée — cohérent avec `work_item`/`git_index`/`schedule`.

## Décision / Action suivante

Incrément **prêt-à-brancher**. Ce qui reste :

1. **Creds GSC/Bing = track Hamma** : poser `GSC_SERVICE_ACCOUNT_JSON` +
   `GSC_PROPERTY` (et/ou `BING_WEBMASTER_API_KEY` + `BING_SITE_URL`) + installer
   `google-api-python-client` côté déploiement → le provider réel s'active
   **automatiquement** (mock retombe sans creds). Confirmer la convention d'URL
   publique réelle au passage (override `COCKPIT_SITE_BASE` si besoin).
2. **Search Analytics (performance) = Phase 2** : table `perf_metric`,
   impressions/clics/position, tendance par cluster — hors de cet incrément.
