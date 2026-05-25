# Workflow pipeline → sites destinataires — Référence d'architecture

Date : 2026-05-24
Statut : référence (lecture obligatoire avant tout brief touchant `scripts/alwanbooks_pipeline.py` ou un repo de site destinataire)
Audience : architecte humain, claude-code `artiste-coloriage`, claude-code des sites destinataires (`rimalab-v2`, futurs)

## Vision

Le projet `artiste-coloriage` génère des coloriages line-art et les publie sur **N sites destinataires** (1 actuellement = `alwanbooks.com` via `rimalab-v2`, conçu pour N à terme).

Architecture retenue : **git-as-CMS**. Les sites destinataires sont des repos Astro (statiques, frontmatter Zod) qui consomment les artefacts produits par le pipeline. Pas de CMS headless, pas d'API runtime — juste des fichiers MD versionnés par git, livrés sur des branches dédiées et mergés en main par le site destinataire.

**Principe directeur** : la pipeline **produit** du contenu sans jamais **détruire** ce que l'humain a édité à la main. Le contenu existant côté site destinataire est traité comme inviolable par défaut. Toute modification destructive demande un verbe explicite.

## Types de contenu et leurs régimes

Trois types de contenu circulent entre `artiste-coloriage` et les sites destinataires. Chaque type a son régime propre.

### 1. Posts (coloriages individuels)

- **Stockage côté site** : `src/content/posts/{ar,fr,en}/<slug>.md` (1 fichier par locale)
- **Source côté pipeline** : taxonomy + PromptGenerator + DB annotations → `data/export/posts/`
- **Régime** : **ADD-ONLY** (Modèle A)

### 2. Categories (taxonomie de rangement)

- **Stockage côté site** : `src/content/categories/<id>.md` (1 fichier par category, i18n inline)
- **Source côté pipeline** : `data/categories_registry.json` (source unique de vérité)
- **Régime** : **sync strict** (overwrite byte-identique depuis registry)

### 3. Themes (regroupements transverses)

- **Stockage côté site** : `src/content/themes/<id>.md` (1 fichier par theme, i18n inline)
- **Source côté pipeline** : `data/themes_registry.json` (source unique + mapping leaves → themes)
- **Régime** : **ADD-ONLY** (Modèle A) — comme les posts, pas comme les categories

## Modèle A — ADD-ONLY + blocklist + regen explicite

Appliqué aux **posts** et aux **themes**. Garantit la coexistence pipeline / édition manuelle.

### Règles

1. La pipeline ne touche **jamais** un fichier qui existe déjà côté site destinataire.
2. Pour créer un fichier qui existe : c'est un no-op (silencieux, idempotent).
3. Pour overwriter un fichier existant : verbe **`--regen <slug>`** ou **`--regen-theme <id>`** explicite uniquement.
4. Pour empêcher la (re-)création d'un fichier : ajout à la **blocklist** par type (`data/pipeline_blocklist.json` pour posts, `data/pipeline_themes_blocklist.json` pour themes).

### Conséquences

- **Édition manuelle** d'un MD côté site : protégée. Aucun futur `push` ne l'écrasera.
- **Suppression manuelle** d'un MD côté site : doit être complétée par un ajout à la blocklist, sinon le prochain `push` recréera le fichier.
- **Création manuelle** d'un MD côté site (sans passer par pipeline) : vit sa vie, pipeline l'ignore.
- **Mise à jour pilotée par pipeline** (ex: amélioration i18n, refonte template) : nécessite `--regen <slug>` annoncé. Pas d'écrasement par accident.
- **Revert à une ancienne version** : `git checkout <sha> -- <file>` côté site. La pipeline ne le voit pas.

## Sync strict (categories uniquement)

Régime appliqué aux **categories** seulement. Justification : 10 entrées stables, structure du site, pas un sujet d'édition fréquente.

### Règles

1. `data/categories_registry.json` côté `artiste-coloriage` = source unique.
2. `pipeline --sync-categories` régénère **tous** les `categories/<id>.md` côté site en overwrite byte-identique depuis le registry.
3. Aucune édition manuelle des `categories/<id>.md` côté site n'est tolérée : elle sera systématiquement écrasée au prochain sync.
4. Pour modifier une category : PR sur `data/categories_registry.json` côté `artiste-coloriage` → `--sync-categories` → push.

### Conséquence

- Si quelqu'un édite une category à la main côté site, c'est une **erreur de workflow** : la modif sera perdue. Le contrat est documenté côté site dans `PIPELINE-NOTES.md`.
- Pour ajouter une nouvelle category : édition directe de `data/categories_registry.json` (JSON simple, 10-15 entrées max prévues à terme).

## Verbes pipeline (CLI)

Niveau 1 (livré dans le brief `2026-05-24_brief-niveau-1-multi-sites-add-only.md`) :

| Verbe | Effet | Régime |
|---|---|---|
| `pipeline push --site <id>` (défaut) | Crée les posts absents côté site, ADD-ONLY. Auto-tag `themeIds` selon registry themes. Push auto sur branche bot. | Posts ADD-ONLY + Themes auto-tag |
| `pipeline push --site <id> --regen <slug>...` | Overwrite explicite de slugs ciblés (post). Push sur branche bot. | Posts overwrite ciblé |
| `pipeline push --site <id> --regen-file <txt>` | Idem mais lit la liste de slugs depuis un fichier (utile pour batchs). | Posts overwrite batch |
| `pipeline sync-categories --site <id>` | Régénère `categories/*.md` byte-identique depuis registry. Push sur branche bot. | Categories sync strict |
| `pipeline sync-themes --site <id>` | Crée les themes absents (ADD-ONLY). Push sur branche bot. | Themes ADD-ONLY |
| `pipeline sync-themes --site <id> --regen-theme <id>` | Overwrite explicite d'un theme ciblé. | Themes overwrite ciblé |
| `pipeline upload --site <id>` | Upload R2 uniquement (variants images), sans toucher au git du site. | R2 only |
| `pipeline blocklist add-post <slug> --site <id>` | Ajoute slug à `data/pipeline_blocklist.json`. | Blocklist posts |
| `pipeline blocklist add-theme <id> --site <id>` | Ajoute theme_id à `data/pipeline_themes_blocklist.json`. | Blocklist themes |
| `pipeline cutover --site <id>` | Réécrit tous les `approved` éligibles en `published`. Commit massif + push. À utiliser une fois (au cutover J+30). | Bump statut éditorial |

Niveau 2 (préparé en roadmap, pas livré Niveau 1) :

| Verbe | Effet |
|---|---|
| `pipeline sites add --id <> --repo <> --branch <>` | Clone + enregistre un nouveau site destinataire. |
| `pipeline sites list/remove <id>/enable <id>/disable <id>` | CRUD sites destinataires. |
| `pipeline sites pull --site <id>` | Fetch+pull du clone local avant un push (sync avec origin). |
| `pipeline push --all-sites` | Boucle sur tous les sites enabled. |

## Conventions techniques

### Emplacement des clones

Les repos des sites destinataires sont clonés sous `data/sites/<site_id>/` dans le repo `artiste-coloriage` (gitignored). Le clone est créé à `pipeline sites add` (Niveau 2) ou manuellement en Niveau 1.

Exemple :
```
artiste-coloriage/
├── data/
│   └── sites/
│       └── alwanbooks/        ← clone de git@github.com:msouabni/rimalab-v2.git
│           ├── .git/
│           └── src/content/...
```

Override possible via env var `SITES_ROOT` (réservé Niveau 2).

### Identité git du bot

Commits pipeline attribués à : `artiste-pipeline <bot@artiste-coloriage.local>`.

Séparation claire dans `git log` côté site entre commits humains et commits pipeline. Le bot n'a pas de compte GitHub (apparaît en avatar par défaut).

### Convention nom de branche

Format : `bot/lot-{YYYY-MM-DD}` (date du push, time machine locale).

Si une branche du même nom existe déjà ce jour-là : suffixe auto `-2`, `-3`, etc. Ex : `bot/lot-2026-05-24-2`.

La branche est créée systématiquement (jamais de push direct sur `main` côté site). C'est au site destinataire de merger via PR ou directement.

### Creds Git

SSH key système (déjà configurée localement). `repo_url` dans `destination_sites.json` au format SSH : `git@github.com:msouabni/rimalab-v2.git`.

Aucun secret Git stocké côté `artiste-coloriage` (pas de token dans `.env`, pas de bot account).

### Creds R2

Stockés dans `.env` côté `artiste-coloriage` : `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, etc. Doc setup : `docs/cloudflare-r2-setup.md`. Les creds R2 ne quittent jamais la machine pipeline.

## Lifecycle d'un MD post

Diagramme des transitions possibles pour un post `<slug>.md` :

```
        [absent côté site]
              │
              │ pipeline push (ADD-ONLY)
              ▼
       [créé par pipeline]
              │
              ├─── édition humaine ────► [édité humain] ──► futur push : skip
              │                                         ──► futur regen : overwrite
              │
              ├─── pipeline regen ────► [regénéré pipeline] (overwrite contrôlé)
              │
              └─── git rm + blocklist add ──► [supprimé] ──► futur push : skip définitif

       [créé manuellement par humain]
              │
              │ (pipeline l'ignore complètement, jamais touché)
              ▼
       [vit sa vie hors-pipeline]
```

## Récap deployment imprimé

Chaque `pipeline push --site <id>` imprime en fin de run un récap structuré que l'humain peut copier-coller en commit message ou en notif :

```
=== artiste-pipeline — push lot 2026-05-24 vers site=alwanbooks ===
Mode posts        : ADD-ONLY (--regen=<aucun>)
Posts créés       : 12 (nouveaux)
Posts ignorés     : 399 (déjà présents)
Blocklist posts   : 3 entrées
Categories sync   : 0 modifs (registry inchangé)
Themes sync       : 1 créé (noel_2026)
themeIds auto-tag : 47 posts impactés (lecture themes_registry)
R2 variants       : 48 uploadés / 24 skipped (etag match)

Branche push      : bot/lot-2026-05-24
Commits           : 2 (feat: 12 posts, feat: 1 theme noel_2026)
URL PR/branche    : https://github.com/msouabni/rimalab-v2/tree/bot/lot-2026-05-24

À faire côté site destinataire (humain / claude site) :
  1. git fetch origin
  2. git checkout bot/lot-2026-05-24
  3. npm run build  (vérifier 0 erreur Zod)
  4. Ouvrir PR + review + merge sur main
```

## Matrice responsabilités

| Action | Qui décide | Qui exécute | Qui valide |
|---|---|---|---|
| Ajouter un coloriage au catalogue | archi/humain | claude-code artiste (génération) → pipeline push | claude site (build) |
| Modifier i18n d'un coloriage existant | archi/humain | pipeline `--regen <slug>` | claude site (build) |
| Retirer un coloriage du site | humain | humain (`git rm` côté site + blocklist add) | claude site (build) |
| Éditer ponctuellement la description d'un coloriage (correction typo) | humain | humain (édition directe MD côté site) | claude site (build) |
| Ajouter / renommer une category | archi/humain | archi (PR registry) → pipeline `--sync-categories` | claude site (build) |
| Ajouter un theme | archi/humain | archi (PR registry themes) → pipeline `--sync-themes` | claude site (build) |
| Modifier les leaves attachés à un theme existant | archi/humain | archi (PR registry themes) → pipeline `--regen-theme` + `--regen <posts>` impactés | claude site (build) |
| Cutover preview → public (prod) | humain | pipeline `cutover` + claude site (flip `PUBLIC_SITE_STATE=public`) | claude site (build prod) |
| Régénération de masse (refonte template) | archi | pipeline `--regen-file <txt>` | claude site (build + smoke) |
| Revert un coloriage à une version antérieure | humain | humain (`git checkout <sha> -- <file>` côté site + commit) | claude site (build) |
| Ajouter un nouveau site destinataire | humain | Niveau 2 : `pipeline sites add` ; Niveau 1 : édition directe `destination_sites.json` + `git clone` manuel | archi |

## Évolution future (Niveau 2 et au-delà)

Documenté dans `docs/architect/2026-05-24_roadmap-multi-sites-niveau-2.md`. Résumé :

- **Niveau 2** : commandes CLI sites add/remove/list, push --all-sites, hooks pre/post sync. À déclencher quand un 2e site destinataire est planifié concrètement.
- **Niveau 3 envisagé** : skill `artiste-pipeline-skill` qui encode les 4 verbes humains les plus fréquents (retirer un coloriage, ajouter un theme, regen un post, lancer un lot). Permet à un humain non-technique de piloter via prompt naturel.
- **Niveau 4 envisagé** : GUI web légère pour les mêmes verbes, hébergée localement par `start.py`. Backlog.

## Références

- Décision modèle A acquise : `docs/architect/MEMORY.md` (à jour via `/architect-save` 2026-05-24)
- Décision multi-sites Niveau 1 : ce document + roadmap Niveau 2
- Contrat pipeline → rimalab-v2 : `docs/xchange/PIPELINE-CONTRACT.md`
- Setup R2 : `docs/cloudflare-r2-setup.md`
- Registry catégories (livré 2026-05-15) : `data/categories_registry.json` + tests dédiés
