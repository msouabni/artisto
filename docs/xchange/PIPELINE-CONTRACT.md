# Contrat pipeline — Alwan Books V2

> Source of truth pour l'équipe `alwanbooks-pipeline` (Python + Pillow +
> boto3). Ce document décrit ce que la pipeline doit produire pour que
> `rimalab-v2` accepte le contenu et que Cloudflare puisse déployer.
>
> Cohérent avec ADR Révision 2.4 (cf. `docs/ADR.md` §§ 1.6, 1.12, 1.13,
> 1.14) et `src/content.config.ts` (schémas Zod).

## 1. Pourquoi ce document

**Audience** : développeurs qui maintiennent `alwanbooks-pipeline`
(repo séparé). Vous adaptez le pipeline pour produire du contenu
trilingue conforme V2.

**Objectif** : vous donner tout pour (a) comprendre où votre pipeline
s'insère, (b) connaître exactement le format attendu, (c) valider votre
output localement avant push, (d) travailler efficacement avec Cursor
sur ce code.

**Scope du contrat** :

- ✅ **Posts** (coloriages, mono-locale) : un fichier MD par Post × locale dans `src/content/posts/{ar,fr,en}/<slug>.md`
- ✅ **R2 assets** (4 variants par master image) sur `assets.alwanbooks.com`

**Hors scope (ce que la pipeline ne fait PAS)** :

- ❌ **Categories** (`src/content/categories/*.md`) — saisie manuelle V1, ~50 entrées
- ❌ **Themes** (`src/content/themes/*.md`) — saisie manuelle V1, 10 hubs avec contenu éditorial long
- ❌ **Templates Astro, helpers, CSS, build config** — gérés dans `rimalab-v2`

**Versioning** : ce doc évolue avec le schéma. Voir § 15 Changelog.

## 2. Architecture — où la pipeline s'insère

```
┌─────────────────────────┐
│ alwanbooks-pipeline     │ Python + Pillow + boto3 + lib slug AR
│ (repo séparé)           │
│  - Génère 4 variants    │
│  - Génère MD Posts      │
└──────────┬──────────────┘
           │
           ├──── Upload R2 (atomique 4-ou-0, idempotent par hash)
           │     → assets.alwanbooks.com/coloriages/{png,webp,thumbs,pdf}/<slug>.<ext>
           │
           └──── git commit + push origin/main
                 → src/content/posts/{ar,fr,en}/<slug>.md
                                 │
                                 ▼
                  ┌──────────────────────────┐
                  │ GitHub webhook           │
                  └──────────┬───────────────┘
                             │
                             ▼
                  ┌──────────────────────────┐
                  │ Cloudflare Workers       │ Build Astro (~30-60 s)
                  │ Static Assets            │ npm run build → dist/
                  └──────────┬───────────────┘
                             │
                             ▼
                  ┌──────────────────────────┐
                  │ alwanbooks.com (cutover) │ Site statique servi
                  │ rimalab-v2.workers.dev   │ via Workers
                  └──────────────────────────┘
```

**Limites de responsabilité** :

| Concern | Pipeline | rimalab-v2 |
|---|:---:|:---:|
| Génération images (4 variants) | ✅ | — |
| Upload R2 | ✅ | — |
| Translittération slugs AR → ASCII | ✅ | — |
| Filtrage drafts (`status` vs `approved/published`) | ✅ | — |
| Génération frontmatter Posts | ✅ | — |
| Validation Zod build-time | — | ✅ |
| Templates / dispatcher / SEO / sitemap | — | ✅ |
| Saisie Categories / Themes | — | ✅ (manuelle V1) |

## 3. Contrat R2 — 4 variants par coloriage

**Bucket** : `alwanbooks-assets`
**Custom domain** : `assets.alwanbooks.com`
**Auth pipeline** : Cloudflare API token scopé bucket en lecture+écriture (env vars `R2_ACCESS_KEY_ID` + `R2_SECRET_ACCESS_KEY` côté pipeline)

### Variants exigés (atomicité 4-ou-0)

| Variant | Path R2 | Format | Specs |
|---|---|---|---|
| Master | `coloriages/png/<slug>.png` | PNG | Source haute-résolution, transparence préservée si présente, **pas de redimensionnement** |
| Web | `coloriages/webp/<slug>.webp` | WebP | Pillow `quality=85`, `method=6`, même résolution que master |
| Thumb | `coloriages/thumbs/<slug>.webp` | WebP | `PIL.Image.thumbnail((400, 400))`, ratio préservé, Lanczos resampling, `quality=80` |
| PDF | `coloriages/pdf/<slug>.pdf` | PDF | A4 portrait 595×842 pt, image fitted via `img2pdf.FitMode.into`, marges 10 mm, `auto_orient=False` |

### Workflow par master image

1. **Validation basename** ASCII kebab strict (mirror du Zod regex côté Astro, cf. § 5) — échec immédiat si non-conforme
2. **Génération locale** des 4 variants en `/tmp` depuis le PNG master
3. **Upload atomique** des 4 variants vers R2 — si une étape échoue, **rollback** des variants déjà uploadés du même slug
4. **Idempotence par hash** : skip si `sha256(master)` inchangé ET tous les variants présents dans R2
5. **Logging par slug** : timestamp, tailles produites, succès/échec

### CORS

`AllowedOrigins: ["*"]` — décidé 2026-04-30 (assets publics read-only,
aucun risque, cf. ADR §1.14 et `docs/CUTOVER.md`). La pipeline n'a
pas à se soucier de la config CORS.

### URLs frontmatter (consommées par rimalab-v2)

```
imageSource: https://assets.alwanbooks.com/coloriages/png/<slug>.png
imageWeb:    https://assets.alwanbooks.com/coloriages/webp/<slug>.webp
imageThumb:  https://assets.alwanbooks.com/coloriages/thumbs/<slug>.webp
imagePdf:    https://assets.alwanbooks.com/coloriages/pdf/<slug>.pdf
```

### R2 slug ≠ Post slug (subtilité importante)

Le **R2 slug** est l'identifiant canonique du master image, choisi au
moment de l'upload. Contraintes hard :

- **ASCII kebab strict** (regex § 5)
- **Stable** : ne change jamais après upload — c'est l'identité de l'image
- **Unique** dans le bucket

**Recommandation (pas obligatoire)** : utiliser le slug EN du Post si EN
existe, sinon le slug FR, sinon la translittération AR. C'est ce que
montrent les fixtures actuelles (`lion-savanna`, `cat-library`) et ça
rend les URLs R2 prévisibles depuis n'importe quelle URL Post EN. Mais
la pipeline reste libre d'utiliser un autre schéma (UUID, hash, etc.)
tant que les contraintes hard sont respectées.

La pipeline **DOIT** toutefois utiliser le MÊME R2 slug pour les 4
variants d'un même master (PNG/WebP/Thumb/PDF) — atomicité 4-ou-0 +
cohérence.

**Conséquence pratique** : 3 Posts (AR/FR/EN) qui partagent la même
image référencent les MÊMES 4 URLs R2 dans leurs 4 champs `imageSource/
Web/Thumb/Pdf`. Exemple réel :

| Post | Locale | Post slug (URL) | R2 slug (assets) |
|---|---|---|---|
| Lion savane (FR) | fr | `lion-savane` | `lion-savanna` |
| Lion in savanna (EN) | en | `lion-in-savanna` | `lion-savanna` |
| Asad fi al-ghaba (AR) | ar | `asad-fi-al-ghaba` | `lion-savanna` |

## 4. Schéma Post — frontmatter complet

Source autoritative : `src/content.config.ts` (Posts collection). Tableau
récapitulatif :

| Champ | Type | Min-Max | Sweet spot | Optionnel ? | Notes |
|---|---|---|---|:---:|---|
| `locale` | enum `'ar'\|'fr'\|'en'` | — | — | non | Doit matcher le dossier (ex: `posts/fr/` → `locale: 'fr'`) |
| `slug` | string | regex + max 50 | 15-25 chars | non | ASCII kebab strict, cf. § 5. Pré-translittéré pipeline. |
| `title` | string | 5-100 | 40-60 chars | non | H1 Post page + `<title>` SEO |
| `title_card` | string | 5-40 | 25-35 chars | **oui** | PostCard 1 ligne. Si absent, fallback `title.slice(0, 40)`. **Fournir explicitement si `title.length > 40`** |
| `description` | string | 20-200 | 80-130 chars | non | 1-3 phrases prose pure (pas de markdown) |
| `keywords` | array of string | 1-8 items, items 2-30 chars | 3-5 items | non | Mots-clés SEO. **Pas `keywords_i18n`** (Posts mono-locale) |
| `categoryId` | string | min 1 | — | non | Référence `id` d'une Category existante (snake_case, ex: `animals_cats`) |
| `themeIds` | array of string | — | — | oui (default `[]`) | Références `id` de Themes existants (kebab-case, ex: `arabic-alphabet`) |
| `ageMin` | int | 0-99 | — | non | Borne d'âge inférieure. Validé `ageMin ≤ ageMax` |
| `ageMax` | int | 0-99 | — | non | Borne d'âge supérieure |
| `niveauDifficulte` | enum `'easy'\|'medium'\|'hard'` | — | — | non | Enum technique anglais (l'affichage est localisé via i18n) |
| `imageSource` | URL | basename ASCII kebab | — | non | URL R2 PNG master (cf. § 3) |
| `imageWeb` | URL | basename ASCII kebab | — | non | URL R2 WebP full |
| `imageThumb` | URL | basename ASCII kebab | — | non | URL R2 WebP 400×400 |
| `imagePdf` | URL | basename ASCII kebab | — | non | URL R2 PDF A4 |
| `status` | enum `'approved'\|'published'` | — | — | non | Drafts filtrés pipeline-side, jamais reçus |
| `datePublication` | date (YAML) | — | — | non | `2026-04-25` (ISO) ou Date object |
| `dateModification` | date (YAML) | — | — | non | Idem |
| `featured` | boolean | — | — | oui (default `false`) | Met le Post en avant côté UI |

**Tolérance extras** : le schéma utilise `.passthrough()` — vous pouvez
inclure des champs metadata pipeline (`model_name`, `prompt`,
`negative_prompt`, `quality_score`, etc.) sans casser le build. Ils ne
seront simplement pas consommés.

**Conventions de casing** :

- `categoryId`, `themeIds`, `parent_id` (Categories) : **snake_case partout**, aligné avec les `id` des fichiers Category. Note : `CLAUDE.md` mentionne historiquement "camelCase côté Posts" — c'est obsolète, le code et les fixtures sont la source of truth (snake_case).
- Champs frontmatter eux-mêmes : `camelCase` (`categoryId`, `ageMin`, `niveauDifficulte`, `imageSource`, etc.) — convention YAML/JS.

## 5. Règle slugs — ASCII kebab strict

Source : ADR §1.12.

**Regex** : `/^[a-z0-9]+(-[a-z0-9]+)*$/`

**Bornes** :

- Posts `slug` : max **50** chars (sweet spot 15-25)
- Categories/Themes `slug_i18n.{ar,fr,en}` : max **40** chars

**Caractères autorisés** : `a-z`, `0-9`, `-` (tiret unique entre groupes alphanumériques)

**Pré-translittération** : la pipeline s'occupe de la translittération
arabe → latin. **Le repo Astro ne contient AUCUNE logique de
translittération**. Choix de lib **libre** — `python-slugify`, table
ad-hoc, ou autre. Seule contrainte : l'output doit respecter le regex
ci-dessus.

### Exemples corrects ✅

```
lion-savane
chat-bibliotheque
oiseau-foret-tropicale
asad-fi-al-ghaba          (translittération AR de "أسد في الغابة")
qitt-fi-al-maktaba        (translittération AR de "قط في المكتبة")
ramadan-2026
alif-pomme
```

### Anti-patterns ❌

```
Lion-Savane               → uppercase interdit
lion_savane               → underscore interdit
lion savane               → espace interdit
lion-à-savane             → diacritique interdit
لوحة-أسد                  → UTF-8 non-ASCII interdit
lion--savane              → double tiret interdit
-lion-savane              → tiret en début interdit
lion-savane-              → tiret en fin interdit
lion.savane               → point interdit
lion/savane               → slash interdit
```

### Stratégie de déduplication (responsabilité pipeline)

Si deux titres arabes différents produisent le même slug latin
translittéré, dédupliquer côté DB pipeline avec un suffixe numérique
(ex: `qitt-fi-al-maktaba` puis `qitt-fi-al-maktaba-2`). Cohérent avec
ADR §1.12.

## 6. Mono-locale — un Post = une entité

**Principe** : 3 langues partageant la même image = **3 fichiers MD
distincts**, indépendants.

```
src/content/posts/
├── ar/
│   ├── asad-fi-al-ghaba.md       (locale: 'ar')
│   └── qitt-fi-al-maktaba.md
├── fr/
│   ├── lion-savane.md            (locale: 'fr')
│   └── chat-bibliotheque.md
└── en/
    ├── lion-in-savanna.md        (locale: 'en')
    └── cat-in-library.md
```

**Le slug peut différer par locale** — c'est même attendu. La
translittération AR ne ressemble pas au slug FR ou EN. Mais les 3 Posts
référencent les **mêmes URLs R2** (cf. § 3, R2 slug ≠ Post slug).

**Synchronisation non atomique** : un Post peut être en FR le mardi et
en EN le vendredi. Aucune URL EN n'est générée tant que le fichier EN
n'existe pas — pas de 404, juste l'absence de l'URL côté EN.

**Build cassé volontairement** si `title`/`description`/`keywords`
manquent ou violent les bornes pour publication d'un Post EN (Zod
strict). Pas de fallback automatique depuis FR. Cohérent avec ADR
§1.6 et §1.7.

## 7. Locale-specific guidance

### AR (arabe)

- **RTL** géré 100 % côté Astro (`<html dir="rtl">`, CSS logical
  properties). La pipeline n'a rien à faire pour RTL.
- **Densité lexicale** ~50 % inférieure à FR/EN à concept équivalent —
  viser la borne basse des sweet spots (titre 30-40 chars souvent
  suffisant pour la même idée que 50-60 chars en FR).
- **Slugs** en translittération latine ASCII (jamais d'arabe dans les
  URLs, cf. § 5).
- **Chiffres dans le contenu** : occidentaux (`0123456789`) **partout**, y
  compris en AR. Décision design 2026-04-29 — chiffres arabo-indiens
  écartés pour cohérence cross-locale et alignement avec le web arabe
  moderne (Aljazeera, BBC Arabic).

### FR (français)

- Locale par défaut éditoriale.
- Sweet spots calibrés sur le français (titres 40-60 chars).

### EN (anglais)

- Densité comparable à FR.
- `title`/`description`/`keywords` **obligatoires** si publication EN —
  pas de fallback depuis FR. Le pipeline doit avoir les 3 traductions
  prêtes avant de pousser une locale donnée.

## 8. Quality gates — qu'est-ce qui casse le build ?

### Build fail (Zod refuse)

- Toute borne `min/max` violée (titre 4 ou 101 chars, slug 51 chars, description hors 20-200…)
- Slug regex non respecté (cf. § 5)
- `categoryId` qui ne référence pas une Category existante (validé Phase 3 dans le dispatcher)
- URL R2 dont le **basename** n'est pas ASCII kebab (regex `r2Url`)
- `ageMin > ageMax`
- `status` autre que `approved`/`published`
- Champ obligatoire absent

### Build pass mais image cassée côté visiteur

- URL R2 valide syntaxiquement mais 404 (variant pas uploadé) → la page Post se charge mais l'image est un broken-link icon. **À vérifier dans la pipeline avant push** (curl HEAD sur les 4 URLs).
- Slug Post collision avec un Post existant dans la même locale (idem build pass — l'un écrasera l'autre côté Astro). Vérification pipeline-side.

### Drafts

`status ∈ {'draft', 'pending', 'rejected', …}` ne devraient **jamais
arriver** côté Astro. Filtrage côté pipeline = règle dure.

## 9. Workflow content — pipeline → site déployé

1. **Pipeline** génère 4 variants R2 + 1 fichier MD par locale publiée
2. **Upload R2** atomique (4-ou-0, idempotent par hash)
3. **Commit + push** sur `rimalab-v2/main` (HTTPS via PAT ou SSH key)
4. **GitHub webhook** déclenche le build Cloudflare Workers
5. **Build Astro** (~30-60 s pour 1000 Posts) → `dist/`
6. **Site déployé** — URL canonique : `/<locale>/<categoriesRoot[locale]>/<categorySlug>/<postSlug>` (sans trailing slash)

**Mapping `categoriesRoot`** (depuis `src/lib/i18n/paths.ts`) :

| Locale | categoriesRoot |
|:---:|:---:|
| `ar` | `talween` |
| `fr` | `coloriages` |
| `en` | `coloring` |

Exemples d'URLs canoniques générées :

```
/ar/talween/hayawanat/usud/asad-fi-al-ghaba
/fr/coloriages/animaux/lions/lion-savane
/en/coloring/animals/lions/lion-in-savanna
```

## 10. Validation locale avant push

Le pipeline peut (et devrait) valider son output localement avant push :

```bash
# 1. Cloner / pull rimalab-v2
git clone git@github.com:msouabni/rimalab-v2.git
cd rimalab-v2

# 2. Activer Node 22 (lu depuis .nvmrc)
nvm use

# 3. Installer deps (npm ci si lockfile à jour, npm install sinon)
npm ci

# 4. Build complet — échoue si schéma violé
npm run build
```

- **Build PASS** → safe à pusher
- **Build FAIL** → lire l'erreur Zod (chemin du champ + message), corriger frontmatter, retry

Astuce : Astro affiche un message d'erreur Zod par champ violé, avec le
chemin (`posts/fr/<slug>.md` → `title`) et le message custom de la
borne. Tous les messages référencent `ADR §1.13` ou `§1.12` pour
clarifier la règle.

## 11. Examples annotés

### 11.1 Post FR complet (`src/content/posts/fr/chat-bibliotheque.md`)

```yaml
---
locale: 'fr'                          # ← § 4 : doit matcher le dossier posts/fr/
slug: 'chat-bibliotheque'             # ← § 5 : ASCII kebab, max 50
title: 'Chat dans une bibliothèque'   # ← § 4 : 5-100 chars (28 ici, sweet spot)
title_card: 'Chat à la bibliothèque'  # ← § 4 : optionnel, max 40 (22 ici)
description: 'Coloriage d''un petit chat assis entre des étagères de livres — illustration mignonne et amusante, adaptée aux enfants de 4 à 8 ans.'
                                       # ← § 4 : 20-200 chars (140 ici, sweet spot)
keywords:
  - 'coloriage chat'                  # ← § 4 : 1-8 items, items 2-30 chars
  - 'chat à imprimer'
  - 'chat et livres'
categoryId: 'animals_cats'            # ← § 4 : référence Category existante (snake_case)
themeIds: ['arabic-alphabet']         # ← § 4 : références Theme(s) existant(s)
ageMin: 4                             # ← § 4 : 0-99, ageMin ≤ ageMax
ageMax: 8
niveauDifficulte: 'easy'              # ← § 4 : enum technique anglais
imageSource: 'https://assets.alwanbooks.com/coloriages/png/cat-library.png'
                                       # ← § 3 : R2 slug = 'cat-library' (basename ASCII kebab)
imageWeb: 'https://assets.alwanbooks.com/coloriages/webp/cat-library.webp'
imageThumb: 'https://assets.alwanbooks.com/coloriages/thumbs/cat-library.webp'
imagePdf: 'https://assets.alwanbooks.com/coloriages/pdf/cat-library.pdf'
status: 'approved'                    # ← § 4 : approved | published (jamais draft)
datePublication: 2026-04-25
dateModification: 2026-04-25
featured: true                        # ← § 4 : optionnel, default false
---

## À propos de ce coloriage

Un petit chat qui explore les étagères d'une bibliothèque — illustration simple aux traits clairs, parfaite pour les enfants qui apprennent à colorier sans dépasser les bords. Le dessin invite l'enfant à remarquer les petits détails comme les livres et les coussins.

## Conseils pédagogiques

Propose à ton enfant des couleurs différentes pour le chat à chaque fois qu'il colorie la page : gris, orange, blanc et noir. Ça renouvelle l'activité et stimule la créativité.
```

### 11.2 Post EN équivalent (`src/content/posts/en/cat-in-library.md`)

Mêmes 4 URLs R2 (le master `cat-library.{png|webp|pdf}` est partagé),
slug et titre différents, contenu prose traduit/adapté. Frontmatter
identique sur `categoryId`/`themeIds`/`ageMin`/`ageMax`/`niveauDifficulte`/`featured`.

### 11.3 Post AR équivalent (`src/content/posts/ar/qitt-fi-al-maktaba.md`)

```yaml
---
locale: 'ar'
slug: 'qitt-fi-al-maktaba'            # translittération de "قط في المكتبة"
title: 'قط في المكتبة'                # arabe natif dans le titre
description: '...'                    # description AR
keywords: ['تلوين قط', 'قطة للأطفال', '...']
categoryId: 'animals_cats'            # même Category référencée (multilingue côté Categories)
themeIds: ['arabic-alphabet']
ageMin: 4
ageMax: 8
niveauDifficulte: 'easy'
imageSource: 'https://assets.alwanbooks.com/coloriages/png/cat-library.png'
                                       # mêmes URLs R2 que les Posts FR/EN
imageWeb: 'https://assets.alwanbooks.com/coloriages/webp/cat-library.webp'
imageThumb: 'https://assets.alwanbooks.com/coloriages/thumbs/cat-library.webp'
imagePdf: 'https://assets.alwanbooks.com/coloriages/pdf/cat-library.pdf'
status: 'approved'
datePublication: 2026-04-25
dateModification: 2026-04-25
---
```

### 11.4 Cas edge — `title_card` distinct du `title`

Pour un Post avec `title.length > 40`, fournir explicitement `title_card`
court :

```yaml
title: 'Coloriage chat dans une bibliothèque pour enfants 4-8 ans à imprimer gratuit'
                                       # 80 chars — long-tail SEO H1
title_card: 'Chat à la bibliothèque'   # 22 chars — PostCard 1 ligne
```

PostCard rend `title_card`, PostTemplate rend `title` (long, H1 + SEO).
Cf. ADR §1.13.

### 11.5 Cas edge — Post mono-locale (FR seul)

```
src/content/posts/
└── fr/
    └── nouveau-coloriage.md     ← FR publié maintenant
```

Pas de fichier `en/` ou `ar/`. C'est OK. Aucune URL EN/AR ne sera
générée pour ce Post tant que les fichiers correspondants n'existent
pas. Ajouter `en/nouveau-coloriage.md` dans un push ultérieur fera
apparaître l'URL EN sans toucher à FR.

## 12. Anti-patterns courants

| Anti-pattern | Symptôme | Fix |
|---|---|---|
| Slug avec diacritique (`lion-à-savane`) | Build fail (regex Zod) | Translittérer |
| `title` > 100 chars | Build fail (Zod max) | Raccourcir, ou utiliser `title_card` court + garder `title` long si SEO le justifie |
| `description` avec markdown formatting (gras, liens) | Affichage moche dans `<meta>` et hub display | Prose pure, pas de syntaxe markdown |
| `keywords` en phrase complète | Dilue le signal SEO, dépasse souvent les 30 chars/item | Termes courts (2-30 chars), 3-5 items |
| URL R2 avec query string (`?v=1`) ou fragment (`#x`) | Build fail (regex `r2Url` valide le basename strict) | URL nue, sans paramètres |
| `ageMin > ageMax` | Build fail (refine) | Inverser les valeurs |
| `datePublication` futur | Toléré, pas bloquant | Réfléchir si voulu (publish embargo manuel) |
| `keywords_i18n` dans frontmatter Post | Build fail (champ inconnu, mais `.passthrough()` ignore — pourtant Zod n'attend pas ce champ ici) | `keywords_i18n` est pour Categories/Themes uniquement. Posts utilisent `keywords` (flat array). |
| `status: 'draft'` | Build fail (enum strict) | Filtrer côté pipeline avant export |
| Slug pas ASCII kebab (uppercase, underscore, espace) | Build fail (regex) | Voir § 5 |
| `categoryId` qui ne matche aucune Category existante | Build fail (cross-validation Phase 3) | Vérifier `src/content/categories/` avant push |
| 4 URLs R2 référençant 4 R2 slugs différents | Incohérence visible côté visiteur (différentes images affichées) | UTILISER LE MÊME R2 slug pour les 4 variants — atomicité (cf. § 3) |
| Post slug en collision avec un Post existant dans la même locale | Build pass (Astro overwrite silencieux) | Vérifier unicité côté pipeline avant push |

## 13. Pre-push checklist (pipeline)

À automatiser dans le script pipeline (`pre_push_check.py` recommandé) :

- [ ] Tous les Posts du batch passent `npm run build` local sur un clone propre
- [ ] Toutes les URLs R2 du batch retournent 200 (`curl -I` HEAD sur les 4 variants par Post)
- [ ] Aucun slug en collision avec un Post existant (même locale) — `glob src/content/posts/<locale>/<slug>.md`, doit être unique
- [ ] `categoryId` de chaque Post existe dans `src/content/categories/<id>.md`
- [ ] `themeIds[]` (si non vide) référencent des Themes existants dans `src/content/themes/<id>.md`
- [ ] Branche pipeline mergée sur `main` (ou PR review si workflow PR avec branch protection)

## 14. Travailler avec Cursor sur cette pipeline

### 14.1 System prompt suggéré

À coller dans Cursor → Settings → Rules (ou équivalent récent) :

```
Tu travailles sur alwanbooks-pipeline qui produit du contenu pour
rimalab-v2 (Astro 6 SSG, trilingue AR/FR/EN). Le contrat est dans
docs/PIPELINE-CONTRACT.md du repo rimalab-v2.

Règles strictes :
- Slugs ASCII kebab `/^[a-z0-9]+(-[a-z0-9]+)*$/`, max 50 chars (Posts)
- Posts mono-locale : 3 fichiers MD pour 3 langues, peut être désynchronisé
- Frontmatter Zod-validé strict — bornes hard, build cassé hors bornes
- Pre-translittérer slugs AR avant de les écrire (jamais d'arabe en URL)
- Chiffres occidentaux (0-9) partout dans le contenu, y compris AR
- 4 variants R2 atomiques par coloriage (PNG master, WebP web, WebP
  thumb 400×400, PDF A4) — même R2 slug pour les 4 variants
- R2 slug ≠ Post slug : R2 slug est canonique pour le master image,
  partagé entre les Posts AR/FR/EN qui pointent vers la même image
- Categories et Themes ne sont PAS gérés par la pipeline (saisie manuelle
  V1 dans rimalab-v2)
- Drafts filtrés pipeline-side : status ∈ {approved, published} only

Avant de proposer du code qui génère du frontmatter ou translittère
des slugs, vérifie ton output contre la regex et les bornes Zod du § 4
de docs/PIPELINE-CONTRACT.md.
```

### 14.2 Prompts-templates utiles

```
"Génère un Post FR pour <description image> avec frontmatter conforme
au schéma docs/PIPELINE-CONTRACT.md §4. Référence categoryId='<id>'
qui existe dans src/content/categories/."

"Translittère ce titre AR en slug ASCII kebab respectant la regex de
docs/PIPELINE-CONTRACT.md §5 : <titre arabe>"

"Vérifie que ce frontmatter passe la validation Zod docs/PIPELINE-
CONTRACT.md §8 : <bloc YAML>"

"Liste les variants R2 attendus pour le master <slug> selon
docs/PIPELINE-CONTRACT.md §3, format tableau."
```

### 14.3 Anti-patterns AI à surveiller

- **Hallucination de champs** : l'AI peut inventer des champs frontmatter inexistants (`author`, `tags`, `excerpt`). Toujours croiser avec § 4. Le `.passthrough()` du schéma ignore les extras → l'erreur ne pète pas au build mais le champ ne sert à rien.
- **Slugs avec diacritiques** : l'AI est tentée de produire `lion-à-savane` ou `qıtt-fi-al-maktaba`. Vérifier regex § 5 systématiquement.
- **Markdown dans `description`** : l'AI ajoute spontanément du gras/liens. Garder prose pure (cf. § 12).
- **`keywords_i18n` sur Posts** : confusion fréquente avec Categories/Themes. Posts = `keywords` flat array.
- **Translittération AR incohérente** : l'AI peut produire des variantes différentes pour le même mot (`maktabah`/`maktaba`/`maktabat`). Imposer une stratégie déterministe pipeline-side, ne pas laisser l'AI improviser à chaque appel.

## 15. Changelog

- **2026-05-01** — Version initiale, calée sur ADR Révision 2.4 et schémas `src/content.config.ts` au commit `1238da1`.
- À mettre à jour à chaque évolution majeure du schema. PR pipeline-side recommandée pour signaler aux deux équipes lors d'un changement de contrat.

---

_Pour toute question ou clarification : ouvrir une issue sur
`msouabni/rimalab-v2` ou contacter directement le mainteneur du repo._
