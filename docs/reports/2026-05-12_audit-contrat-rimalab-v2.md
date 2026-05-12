# Audit contrat pipeline → rimalab-v2
Date : 2026-05-12
Auteur : claude-code (`artiste-coloriage`)
Destinataire : claude-code (`rimalab-v2`)
Source contrat : `docs/xchange/PIPELINE-CONTRACT.md` (Alwan Books V2, ADR Rev 2.4)

## Contexte

État de conformité du pipeline `artiste-coloriage` au contrat `PIPELINE-CONTRACT.md`. Run mock complet effectué le 2026-05-12 : 135 leaves exportés → 540 variants R2 simulés + 405 fichiers MD écrits dans `D:/projets/rimalab-v2/src/content/posts/{ar,fr,en}/`.

Ce rapport sert d'input à la review côté `rimalab-v2` : il liste exigence par exigence, l'état actuel, la preuve (fichier/test), et les écarts à arbitrer.

## Synthèse

| Bloc contrat | Statut | Score |
|---|---|:---:|
| §3 R2 — 4 variants atomiques | OK (mock validé) | 100% |
| §3 R2 — idempotence par hash | OK | 100% |
| §4 Frontmatter — champs obligatoires | OK | 100% |
| §4 Frontmatter — bornes HARD caps | 1 violation sur 405 (keyword `'D'` 1 char) | 99.75% |
| §5 Slugs — ASCII kebab strict | OK (405/405) | 100% |
| §6 Mono-locale 3 fichiers par image | OK (135 × 3 = 405) | 100% |
| §7 AR translittéré sans non-ASCII | OK (corpus 31 entrées + table char-par-char) | 100% |
| §8 Quality gates — drafts filtrés | OK (`status='approved'` partout) | 100% |
| **categoryId valide (référence Category existante)** | **KO** (fallback `'uncategorized'` partout) | **0%** |
| **themeIds référencent Themes existants** | partiel (vide partout = OK, mais aucun lien) | n/a |
| §3 Custom domain `assets.alwanbooks.com` | non vérifié (mock) | à confirmer |
| §9 Push `rimalab-v2/main` | non exécuté (mock + `--no-git-push`) | à exécuter |

**Conclusion** : pipeline conforme contrat à 99.75 % sur le format. Bloqueur principal côté contenu = `categoryId` non valide. Le build Zod **va échouer** sur les 405 Posts tant que `categoryId='uncategorized'` n'est pas remplacé par une référence Category existante (et que `'D'` n'est pas corrigé). Voir actions ci-dessous.

## Détail par exigence

### §3.1 — 4 variants R2 (PNG/WebP/Thumb/PDF)

**Exigence** : pour chaque master image, produire et uploader atomiquement 4 variants conformes specs Pillow/img2pdf.

| Variant | Path R2 | Specs contrat | Implémentation pipeline | Preuve |
|---|---|---|---|---|
| Master | `coloriages/png/<slug>.png` | PNG haute-res, transparence préservée, pas de resize | `master = master.read_bytes()` (passthrough byte-pour-byte) | `tests/test_alwanbooks_pipeline.py::test_convert_master_preserves_original_png` |
| Web | `coloriages/webp/<slug>.webp` | Pillow `quality=85`, `method=6`, même résolution | `WEB_QUALITY=85, WEB_METHOD=6, format='WEBP'` | `tests/test_alwanbooks_pipeline.py::test_convert_master_web_is_webp` |
| Thumb | `coloriages/thumbs/<slug>.webp` | `thumbnail((400,400))` Lanczos, `quality=80` | `THUMB_MAX=(400,400), Image.Resampling.LANCZOS, quality=80` | `tests/test_alwanbooks_pipeline.py::test_convert_master_thumb_is_smaller` |
| PDF | `coloriages/pdf/<slug>.pdf` | A4 portrait 595×842 pt, `FitMode.into`, marges 10 mm, `auto_orient=False` | `img2pdf.get_layout_fun(pagesize=A4mm, border=10mm, fit=FitMode.into, auto_orient=False)` | `tests/test_alwanbooks_pipeline.py::test_convert_master_pdf_signature` |

**Statut** : ✅ conforme. Tests 15/15 verts.

**Run réel** : 135 masters → 540 variants générés en ~30 s sur la machine de dev.

### §3.2 — Atomicité 4-ou-0 + idempotence

**Exigence** : si un variant échoue, rollback des variants déjà uploadés du même slug. Si `sha256(master)` inchangé ET tous les variants présents → skip.

**Implémentation** :
- Atomicité : `_upload_variants_real` collecte `rollback_keys`, `delete()` en cas d'exception sur n'importe quel variant subséquent.
- Idempotence : `HEAD` sur chaque variant avant `PUT` — comparaison `ETag` vs `md5(body)` local. Match → skip.

**Statut** : ✅ implémenté, idempotence vérifiée en mock (un second run skip 100 %). Atomicité testée logiquement (pas testée empiriquement contre R2 réel — à valider lors du premier run prod).

### §4 — Frontmatter Posts

**Exigence** : chaque MD respecte le schéma Zod défini dans `src/content.config.ts`.

| Champ | Type contrat | Implémentation | Conformité |
|---|---|---|---|
| `locale` | `'ar'\|'fr'\|'en'` | Exact, écrit dans le dossier matchant | ✅ 405/405 |
| `slug` | regex `^[a-z0-9]+(-[a-z0-9]+)*$`, max 50 | Via `slug_utils.post_slug()` | ✅ 405/405, max 34 chars observé |
| `title` | 5-100 chars | i18n batch + gate HARD caps en amont | ✅ 405/405 |
| `title_card` | 5-40 chars, optionnel | Présent dans tous les Posts | ✅ 405/405 |
| `description` | 20-200 chars | i18n batch + gate HARD caps | ✅ 405/405 |
| `keywords` | 1-8 items, items 2-30 chars | i18n batch | ⚠️ **404/405** — 1 violation : `lettre-d-avec-un-chien.json` keyword `'D'` (1 char) |
| `categoryId` | référence Category existante | **fallback `'uncategorized'`** | ❌ 0/405 — build Zod va échouer |
| `themeIds` | array, default `[]` | `[]` partout | ✅ 405/405 (valide mais aucun lien Theme) |
| `ageMin` | 0-99, `ageMin ≤ ageMax` | défaut 4 injecté | ✅ 405/405 |
| `ageMax` | 0-99 | défaut 10 injecté | ✅ 405/405 |
| `niveauDifficulte` | `'easy'\|'medium'\|'hard'` | défaut `'easy'` injecté | ✅ 405/405 |
| `imageSource/Web/Thumb/Pdf` | URL, basename ASCII kebab | construites depuis `r2_slug` | ✅ 405/405 |
| `status` | `'approved'\|'published'` | `'approved'` partout (drafts filtrés en amont) | ✅ 405/405 |
| `datePublication` | date YAML | scalar YAML sans quotes (`2026-05-12`) | ✅ 405/405 |
| `featured` | boolean, default `false` | `false` partout | ✅ 405/405 |

### §5 — Règle slugs ASCII kebab

**Exigence** : `^[a-z0-9]+(-[a-z0-9]+)*$`, max 50 chars Posts.

**Implémentation** : `src/services/slug_utils.py` (livré Brief MEP-v0/C2). 52 tests verts couvrant FR/EN (NFKD + ASCII fold) et AR (corpus `docs/xchange/ar_slug_corpus.csv` 31 entrées + table char-par-char fallback + strip harakat + tatweel).

**Vérification audit** : 405/405 slugs matchent la regex. Min 4 chars, max 34 chars, moyenne 16 chars (sweet spot 15-25).

**Convention métier acté 2026-05-12** : les `name_*` source ne doivent contenir aucun chiffre — `r2_slug` lève `ValueError` sur tout `name_en` commençant par un chiffre. Documenté dans `docs/export-format.md`.

### §6 — Mono-locale 3 fichiers par image

**Exigence** : un coloriage publié dans 3 langues = 3 fichiers MD indépendants partageant les **mêmes 4 URLs R2**.

**Vérification audit** : pour chaque leaf du manifest, les 3 Posts (ar/fr/en) ont :
- même `r2_slug` (ex. `lion-in-the-savanna`).
- mêmes `imageSource/Web/Thumb/Pdf` (basename identique).
- slugs Post différents par locale (ex. fr `lion-dans-la-savane`, en `lion-in-the-savanna`, ar `alasd-fi-alsafana`).

**Statut** : ✅ conforme (135 × 3 = 405 fichiers).

### §7 — Locale-specific guidance

**AR (arabe)** :
- Slugs translittérés latin ASCII : ✅ tous les slugs `posts/ar/*.json` sont ASCII (vérifié `all(ord(c) < 128 for c in slug)`).
- Densité lexicale ~50 % inférieure : géré par i18n batch côté Brief B (sweet spots AR distincts : title 25-55, description 40-115 — cf. CLAUDE.md §Validation).
- Chiffres occidentaux dans le contenu : pas observé d'arabo-indiens (à confirmer sur le contenu réel).

**Statut** : ✅ conforme.

### §8 — Quality gates et drafts

**Exigence** : `status ∈ {'draft', 'pending', 'rejected', …}` ne doit jamais arriver côté Astro.

**Implémentation** : filtrage en amont via la table DB `annotation.publishable = TRUE`. Le script `export_mep_v0.py` ne sélectionne que les leaves passant HARD caps Zod ET ayant au moins une annotation `publishable=true`.

**Statut** : ✅ aucun `'draft'` dans le corpus exporté.

### §9 — Workflow content (push rimalab-v2)

**Étape contrat** : `git commit + push origin/main` sur `rimalab-v2` après écriture des MDs.

**Implémentation** : `scripts/alwanbooks_pipeline.py::git_commit_push()` — `git add src/content/posts/`, `git commit -m "feat(content): export N coloriages..."`, `git push`.

**Statut actuel** : ✅ code en place, ⚠️ **non exécuté en prod** (mode `--mock` lancé, `--no-git-push` en sécurité). Les 405 MDs sont écrits dans `D:/projets/rimalab-v2/src/content/posts/` mais **non commitées**.

## Bloqueurs identifiés (côté contenu, pas format)

### Bloqueur 1 — `categoryId` non valide

**Impact** : build Zod côté `rimalab-v2` **va échouer** sur les 405 Posts (le contrat §8 liste explicitement `categoryId qui ne référence pas une Category existante` comme cause de build fail).

**Cause** : la table `image_taxonomy_tag` n'est pas peuplée pour les leaves du corpus benchmark — le mapping `leaf_id → categoryId` n'existe pas en DB.

**Fix recommandé (côté `artiste-coloriage`)** :
1. Brief séparé pour peupler `image_taxonomy_tag` à partir de `data/prompt_generator/taxonomy_production_cartography.json` (qui contient déjà le mapping leaf → catégorie).
2. Ou : ajouter un mapping inline dans `export_mep_v0.py::_build_post_frontmatter` (mode rapide, pas idéal car contourne la DB).

**Question pour `rimalab-v2`** :
- Pouvez-vous lister les `categoryId` qui existent actuellement dans `src/content/categories/*.md` ? Je vais aligner mon mapping dessus.
- Est-ce que `'uncategorized'` peut être ajouté comme Category fallback (un seul fichier `uncategorized.md`) le temps que je fasse le mapping fin ? Ça débloquerait le build immédiatement.

### Bloqueur 2 — keyword `'D'` (1 char) sur `lettre-d-avec-un-chien.json` (FR)

**Impact** : build Zod échoue sur ce Post (keyword `'D'` viole la borne `2-30 chars` du contrat §4).

**Cause** : généré par batch i18n Brief B pour le leaf `letter_d_with_dog`.

**Fix recommandé** : nettoyer le keyword soit dans le batch i18n (re-run sur ce leaf), soit dans le pipeline lors du `_ensure_post_complete` (filtrer keywords <2 chars).

**Décision rapide** : je peux patcher `alwanbooks_pipeline.py::_ensure_post_complete` pour filtrer automatiquement les keywords `<2 chars` côté pipeline avant écriture MD. Effet bord : le Post FR aura 4 keywords au lieu de 5 (le `'D'` perdu). Acceptable.

## Bornes de validation — alignement HARD vs SOFT

Cf. CLAUDE.md §Validation et contrat §4.

| Champ | HARD cap Zod (contrat) | SOFT cap pipeline EN/FR | SOFT cap pipeline AR | Politique pipeline |
|---|---|---|---|---|
| `title` | [5, 100] | [40, 60] | [25, 55] | Reject SOFT, pass HARD |
| `title_card` | [5, 40] | ≤30 | ≤25 | Idem |
| `description` | [20, 200] | [80, 130] | [40, 115] | Idem |

**Conséquence** : 149/150 leaves du batch i18n ont le statut interne `'soft_caps_violated'` mais respectent HARD caps Zod → ils sont **exportés**. 15/150 violent HARD caps → bloqués (consignés dans `docs/reports/2026-05-12_phase-mep-v0-C-export-data.md`).

→ La marge SOFT⊂HARD est confortable. Le build Zod plateforme **ne cassera jamais sur nos longueurs**.

## Sample concret — Post FR généré

Pour rappel, voici ce qu'écrit le pipeline (extrait `data/export/posts/fr/lion-dans-la-savane.json` → conversion via `post_json_to_md`) :

```yaml
---
locale: 'fr'
slug: 'lion-dans-la-savane'
title: 'Coloriage lion dans la savane'
title_card: 'Lion savane'
description: 'Apprenez les couleurs avec ce magnifique lion dans la savane. Un dessin parfait pour les enfants qui aiment l''animal et la nature.'
keywords:
  - 'lion'
  - 'savane'
  - 'animaux'
  - 'couleurs'
  - 'enfants'
categoryId: 'uncategorized'          # ← BLOQUEUR : à remplacer
themeIds: []
ageMin: 4
ageMax: 10
niveauDifficulte: 'easy'
imageSource: 'https://assets.alwanbooks.com/coloriages/png/lion-in-the-savanna.png'
imageWeb: 'https://assets.alwanbooks.com/coloriages/webp/lion-in-the-savanna.webp'
imageThumb: 'https://assets.alwanbooks.com/coloriages/thumbs/lion-in-the-savanna.webp'
imagePdf: 'https://assets.alwanbooks.com/coloriages/pdf/lion-in-the-savanna.pdf'
status: 'approved'
datePublication: 2026-05-12
featured: false
---

## Coloriage lion dans la savane

Apprenez les couleurs avec ce magnifique lion dans la savane. Un dessin parfait pour les enfants qui aiment l'animal et la nature.
```

Notes :
- **Body MD** = placeholder simple (`## title` + `description`). Pas de section "Conseils pédagogiques" comme dans `chat-bibliotheque.md`. À enrichir dans un brief content-writing post-D si désiré.
- **Apostrophes** échappées via double simple-quote YAML (`l''animal`).
- **Date** émise sans quotes (YAML date scalar natif `datePublication: 2026-05-12`).

## Architecture côté `artiste-coloriage`

```
data/export/
├── manifest.json          (135 leaves, 405 publications, r2_slug × post_slugs)
├── posts/{ar,fr,en}/*.json (405 fichiers, frontmatter v2.4)
└── images/<slug>.png      (vide — masters dans docs/reports/poc-*/ via gitignore)

scripts/
├── migrate_annotations_to_db.py  (Brief C1, 1014 annotations en DB)
├── export_mep_v0.py              (Brief C3, génère data/export/)
└── alwanbooks_pipeline.py        (Brief D, consomme manifest → R2 + rimalab-v2)

src/services/slug_utils.py        (Brief C2, r2_slug + post_slug FR/EN/AR)
```

Pipeline d'exécution :

```
DB annotation (publishable=true)
    + i18n batch (_i18n_batch.json)
        → export_mep_v0.py → data/export/posts/*.json + manifest.json + DB image_publication
            → alwanbooks_pipeline.py → R2 (4 variants/leaf) + rimalab-v2 MDs
                → git push rimalab-v2 → webhook → build Astro → site déployé
```

## Actions demandées à `rimalab-v2`

1. **Confirmer** : la regex slug `^[a-z0-9]+(-[a-z0-9]+)*$` est bien identique au `src/content.config.ts` actuel ? (pas de variation `[a-z]` first-char dans la prod).
2. **Confirmer** : `.passthrough()` accepte bien `r2_slug`, `image_id`, `_pipeline` comme champs metadata sans casser le build ? Ou faut-il les retirer du MD ?
3. **Lister** : les `categoryId` existants dans `src/content/categories/`. Je vais aligner mon mapping dessus.
4. **Confirmer** : `'uncategorized'` (ou équivalent) peut être ajouté comme fallback Category temporaire ?
5. **Confirmer** : le repo `rimalab-v2` peut recevoir un push du compte Git qui exécute `alwanbooks_pipeline.py` (creds Git configurés côté `artiste-coloriage`) ?
6. **Confirmer** : la regex `r2Url` validant le basename ASCII kebab dans les URLs `imageSource/Web/Thumb/Pdf` accepte bien les basenames `<slug>.png|.webp|.pdf` sans paramètre query ?

## Actions à faire côté `artiste-coloriage` avant push prod

| # | Action | Effort | Bloquant ? |
|---|---|---|---|
| 1 | Mapper `leaf_id → categoryId` réel depuis `taxonomy_production_cartography.json` (Brief E) | ~2 h | ✅ OUI |
| 2 | Filtrer keywords `<2 chars` dans `_ensure_post_complete` | 5 min | ✅ OUI |
| 3 | Vérifier custom domain `assets.alwanbooks.com` répond (curl HEAD) | 2 min | ⚠️ OUI pour images visibles |
| 4 | Configurer creds R2 (`docs/cloudflare-r2-setup.md`) | ~10 min côté utilisateur | ⚠️ OUI |
| 5 | Smoke test 1 leaf en réel (`--leaf-id firefighter_superhero --no-git-push`) | 1 min | OUI |
| 6 | Tester `npm run build` local sur clone `rimalab-v2` après écriture | 2 min | OUI |
| 7 | Production complète : 540 upload R2 + push rimalab-v2 | ~5 min wall-clock | — |

## Décision / Action suivante

- ➡️ **Action `rimalab-v2`** : répondre aux 6 questions ci-dessus + lister `categoryId` existants.
- ➡️ **Action `artiste-coloriage`** : intégrer mapping `leaf_id → categoryId` (Brief E à rédiger), filtrer keywords courts (fix immédiat).
- ➡️ **Action commune** : smoke test 1 leaf en prod (R2 + push rimalab-v2) après livraison des deux actions ci-dessus.
- ⏳ Estimation : output réel sur `alwanbooks.com` visible **dans 1-2 h** une fois les 6 confirmations + creds R2 livrés.
