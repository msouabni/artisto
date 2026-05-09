# Brief projet — Artiste Coloriage

> Fichier maintenu par Claude Desktop. À transmettre en début de session pour donner le contexte.  
> Dernière mise à jour : 2026-05-04

---

## Rôle attendu de Claude Desktop

Tu m'aides à encadrer une instance de Claude Code qui travaille en local sur le repo `D:\projets\artiste-coloriage`. Tu ne vois pas le code. Ton job : formuler des prompts précis à copier-coller pour Claude Code, anticiper les problèmes d'usabilité et de volume, challenger les choix, valider les résultats. Claude Code fait l'implémentation, les tests, et le débogage.

**Vision permanente à garder en tête** : pipeline quasi-autonome, produire beaucoup avec maximum de qualité et minimum d'effort humain. L'admin gère une file d'exceptions, pas une revue exhaustive.

---

## Ce que fait le projet

Pipeline Python qui produit des images de coloriage (line art noir/blanc) prêtes à publier sur Alwan Books (alwanbooks.com), à partir d'une taxonomie universelle de thèmes FR/EN/AR.

```
Taxonomie (FR/EN/AR)
  → LLM concepts (Ollama)
  → LLM prompts line-art (planner → writer → validator)
  → Génération image (ComfyUI)
  → QC vision IA (LLaVA — line art propre ?)
  → Post-traitement : 4 variants (PNG master, WebP, WebP thumb, PDF A4)
  → Génération contenu i18n (title/description/keywords × 3 locales)
  → Validation contenu IA (LLM — bornes, prose pure, cohérence cross-locale)
  → Score de confiance → auto-approve ou file d'exceptions
  → Publication : R2 upload + MD frontmatter + git push → rimalab-v2
```

Utilisateur : administrateur unique (hamma). Single-user, pas d'auth, pas de scalabilité.

---

## Glossaire

- **Taxonomie** : structure globale + vocabulaires + termes (arbre FR/EN/AR).
- **Image** (= concept image) : idée d'image à produire (titre, prompt, statut, tags).
- **ImageVariant** : un des 4 fichiers produits par image (master/web/thumb/pdf).
- **ImageLocaleContent** : métadonnées éditoriales par locale (title_card, description, keywords, slug).
- **Job** : tâche asynchrone dans la queue (génération, enrichissement, publication…).
- **Publication Adapter** : interface abstraite — une implémentation par plateforme cible.
- **R2 slug** : identifiant stable du master image (ASCII kebab, jamais modifié après upload).
- **Post slug** : slug de l'URL du post sur la plateforme (peut différer du R2 slug, 1 par locale).

---

## Pile technique

- **Backend** : Python 3.11+, FastAPI + Uvicorn, SQLAlchemy 2.0
- **DB** : PostgreSQL 16 (Docker), migrations Alembic. `data/artiste_coloriage.duckdb` = legacy, ignorer.
- **LLM** : Ollama distant (qwen2.5:7b), appels HTTP directs. LLaVA pour QC vision.
- **Génération image** : ComfyUI local (workflow JSON + contrats sidecars `.overrides.json`)
- **UI** : HTML statique + Tabulator.js, servi par FastAPI sur `/data/`
- **Tests** : pytest + SQLite in-memory (jamais Postgres dans les tests)
- **CLI** : Typer (`python -m cli`), client HTTP vers l'API

---

## Architecture clé

**DBConnAdapter** : enveloppe SQLAlchemy, expose `execute(sql, [params])` avec `?` placeholders → `:p0…`. Toujours utiliser `?`.

**Queue de jobs** (`base_worker.py`) : heartbeat 30s, recovery stale >5min, retry `[60, 300, 900]`s, désactivation auto sur erreur dure.

**State machine image** (étendue) :
```
draft → prompt_ready → scheduled → generating → awaiting_validation
  → pending_qc → auto_approved ──────────────→ publishing → published
              → needs_review  → approved ──→ publishing → published
                              → rejected
```

**Contrat de revue de jobs** : `job_review_artifact.py` (forme du diff) + `job_review_apply.py` (logique apply). Étendre les deux pour tout nouveau type reviewable.

**Publication Adapter** : interface abstraite. `AlwanBooksAdapter` = R2 atomique 4-ou-0 + MD frontmatter + git PR auto-merge vers rimalab-v2.

**Conventions critiques** :
- NULL-safe : jamais `dict.get("weight", 0)` comme clé de tri → `int(w) if w is not None else 0`
- Tests SQLite-portables : pas de `RETURNING`, pas de `JSONB` operators, `Column(JSON)` pas `JSONB`
- `keywords` = `Column(JSON)`, `external_theme_ids` = `Column(JSON)` (compatibilité SQLite)
- `r2_slug` : stable après premier upload, modification = **interdit**

---

## Plan de production — état actuel

### Décisions architecturales actées

| Décision | Valeur |
|---|---|
| Stack | Conservée (FastAPI + SQLAlchemy + PostgreSQL + workers) |
| Mapping plateforme | `platform_term_mapping(platform_id, term_id, external_category_id, external_theme_ids JSON)` |
| Variants image | Table `image_variant` dédiée (pas réutiliser `image_output`) |
| Contenu i18n | Table `image_locale_content`, status par locale indépendant |
| Génération i18n | EN first → traduction FR → traduction AR |
| Translittération AR | Table custom DIN 31635 + fold ASCII (ḥ→h, ṣ→s, ṭ→t, ġ→gh, ḫ→kh, ḍ→d, ẓ→z, ʿ/ʾ→supprimés, ā/ū/ī→a/u/i) |
| Git publisher | Branche dédiée + PR auto-merge (pas push direct main) |
| Idempotence R2 | Via `image_variant.uploaded_at` en DB (pas ListObjects) |
| Validation pre-push | Python pur (port des regex Zod) + nightly anti-drift |
| LangGraph | Non pour l'instant |
| UX paradigme | Exception-driven : file d'exceptions + spot check, pas revue exhaustive |

### Phases

| Phase | Statut | Contenu |
|---|---|---|
| **P0** | 🔄 En cours | Questions rimalab-v2 (voir ci-dessous) + POC A translittération AR + POC B R2 (bloqué credentials) |
| **P1** | ✅ Prête à lancer | Schéma DB : migration Alembic, 3 nouvelles tables, champs étendus sur `image` |
| **P2** | ⏳ Après P1 | Génération i18n + revue IA contenu (LLM validation, score confiance) |
| **P3** | ⏳ Après P1, parallèle P2 | 4 variants image + QC vision LLaVA |
| **P4** | ⏳ Après P1+P2+P3 + réponses P0 | Publication Adapter AlwanBooks, validator Python, rollback plan |
| **P5** | ⏳ Après P4 | UX exception-driven : file exceptions, spot check, dry-run, unpublish, republish forcé |

### P0 — Questions en attente (rimalab-v2)

1. Branch protection sur `main` — PR ou push direct ?
2. Cadence push — 1 commit/Post ou batché ? (coût Cloudflare builds)
3. Scope token R2 — read+write ou delete aussi ? (stratégie rollback)
4. R2 staging — bucket séparé ou préfixe `staging/` dans prod avec token scopé ?
5. Categories/Themes manifest — URL stable ou clone repo nécessaire pour validation ?
6. Credentials staging rimalab pour smoke tests P4
7. `categoryId` snake_case vs `themeIds` kebab-case — volontaire ou coquille ?
8. `approved` vs `published` — sémantique éditoriale ?

### P0 — POC A (translittération AR)

Corpus ground-truth à remplir : `docs/xchange/ar_slug_corpus.csv` (30-50 paires titre AR → slug attendu). Ce corpus devient la suite de tests unitaires. **À faire avant de lancer le code du POC.**

### Rollback plan (acté)

- CI rimalab casse après push → revert PR git
- Upload R2 partiel → job de rollback DELETE les variants du batch
- Slug modifié post-publication → interdit techniquement (contrainte applicative)

### Observabilité (à implémenter en P4)

Métriques en DB : `images_published_per_day`, taux d'échec par étape (LLM / image / R2 / git). Visible dans dashboard admin.

### Use cases retirés/redéfinis

- ~~Export collection PDF~~ → variant PDF A4 par image (P3)
- ~~Dérivation taxonomie site~~ → table `platform_term_mapping` (P1)
- ~~Initialisation nouveau site~~ → configurer un Publication Adapter (P4)

---

## Secrets à documenter dans CLAUDE.md (à faire en P1)

`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `RIMALAB_GIT_TOKEN`

---

## Documentation de référence

- `docs/document-fonctionnel.md` — vision produit, glossaire, parcours, règles métier
- `docs/xchange/PIPELINE-CONTRACT.md` — contrat v2.4 avec Alwan Books (source de vérité format publication)
- `docs/xchange/ar_slug_corpus.csv` — corpus de test translittération AR
- `CLAUDE.md` — conventions techniques, architecture, pièges (première lecture pour Claude Code)

---

## Façon de travailler

- Projet en français, code et commits inclus.
- Claude Desktop fournit les prompts complets à copier-coller pour Claude Code.
- Claude Desktop anticipe proactivement les problèmes d'usabilité et de volume (vision "produire beaucoup avec minimum d'effort").
- Proposer l'usage de l'IA partout où elle peut remplacer une revue humaine.
- Pas d'écriture de fichiers sauf `docs/brief-claude-desktop.md` et `docs/xchange/ar_slug_corpus.csv`, et si explicitement demandé pour le reste.
- Plans avant implémentation pour les use cases non-triviaux.

## Convention rapports — échange Claude Code ↔ Claude Desktop

Tout output significatif de Claude Code va dans `docs/reports/`. Claude Desktop lit ces fichiers directement (outil Read) — pas de copier-coller.

**Types de rapports et nommage :**

| Type | Nom fichier | Contenu |
|---|---|---|
| POC | `YYYY-MM-DD_poc-<nom>.md` + `.json` | Résultats bruts + verdict + décision prise |
| Phase complétée | `YYYY-MM-DD_phase-<N>-<nom>.md` | Ce qui a été fait, fichiers touchés, critères de sortie atteints, points d'attention |
| Tests | `YYYY-MM-DD_tests-<nom>.md` | Résultat pytest (nb passed/failed), régressions éventuelles, couverture |
| Migration | `YYYY-MM-DD_migration-<nom>.md` | Tables créées/modifiées, upgrade/downgrade OK, état schéma final |
| Analyse / arbitrage | `YYYY-MM-DD_analyse-<nom>.md` | Diagnostic, options, recommandation, décision attendue |

**Règles :**
- Données avec texte non-ASCII (arabe, etc.) → toujours JSON avec `ensure_ascii=False`
- Chaque rapport `.md` inclut une section `## Décision / Action suivante`
- Claude Code écrit le rapport **avant** de terminer sa réponse, sans attendre une demande explicite
- L'historique est conservé — ne jamais écraser un rapport existant
