# Audit contrat pipeline → rimalab-v2 — v2 (post-arbitrages)
Date : 2026-05-12
Auteur : claude-code (`artiste-coloriage`)
Précédent : `docs/reports/2026-05-12_audit-contrat-rimalab-v2.md`

## Contexte

Suite aux 6 arbitrages reçus de `rimalab-v2` le 2026-05-12, patches appliqués au pipeline `alwanbooks_pipeline.py`. Re-run mock complet effectué : 135 leaves, 0 violation HARD caps, 0 résidu metadata, 4 catégories utilisées.

## Arbitrages reçus et application

| # | Arbitrage `rimalab-v2` | Application pipeline | Statut |
|---|---|---|---|
| Q1 regex slug | `^[a-z0-9]+(-[a-z0-9]+)*$` (digit start OK) | déjà conforme | ✅ |
| Q2 `.passthrough()` | accepte tout, mais on retire `_pipeline`/`r2_slug` pour cleanliness | implémenté (whitelist `_FRONTMATTER_ORDER`) | ✅ |
| Q3 categoryId existants | `animals_cats`, `letters_arabic` | mapping leaf→cat implémenté + 2 categories à créer signalées | ✅ |
| Q4 fallback | `animals_cats` (pas `uncategorized`) | utilisé comme `_CATEGORY_DEFAULT` | ✅ |
| Q5 push | PR obligatoire, jamais main direct | branche dédiée `content/export-mep-v0` | ✅ |
| Q6 r2Url | basename ASCII kebab, pas de query string | déjà conforme | ✅ |
| Q7 `themeIds` | reste `[]` car aucun Theme | défaut `[]` | ✅ |

## Répartition `categoryId` sur les 405 MDs générés

| categoryId | Nb MDs | Statut côté rimalab-v2 | Action |
|---|---:|---|---|
| `animals_cats` | 153 | ✅ existe | fallback générique (51 leaves animaux non-chats sémantiquement faux) |
| `general_humans` | 129 | ⚠️ **à créer** | 43 leaves humains/personnages/professions |
| `objects_things` | 117 | ⚠️ **à créer** | 39 leaves objets/véhicules/motifs |
| `letters_arabic` | 6 | ✅ existe | 2 leaves (×3 locales) |

**135 leaves × 3 locales = 405 MDs total. Toutes les catégories utilisées sont déclarées dans le contrat ou demandées à `rimalab-v2`.**

## Faille de mapping détectée (sémantique)

51 leaves animaux non-chats tombent en `animals_cats` faute de Category `animals_generic`. Sémantiquement faux mais débloque le build. Exemples :

- `african_elephant`, `asian_elephant` (éléphants)
- `arctic_fox`, `gray_wolf` (canidés sauvages)
- `alpaca`, `armadillo`, `chimpanzee`, `dairy_cow` (mammifères divers)
- `bengal_tiger`, `snow_leopard`, `spotted_leopard` (félins non-chats domestiques)
- `monarch_butterfly`, `honey_bee`, `garden_snail` (insectes/invertébrés)
- `polar_bear_on_ice`, `grizzly_bear` (ours)
- `peacock_with_open_tail`, `snowy_owl`, `turkey_bird` (oiseaux)
- `crab_on_the_beach`, `great_white_shark`, `sea_turtle_swimming`, `swimming_seahorse`, `starfish_on_seabed` (faune marine)

**Demande explicite à `rimalab-v2`** : créer `animals_generic` (ou plusieurs categories `animals_birds`, `animals_marine`, `animals_wild`, etc. selon granularité voulue). Pipeline livrera un patch mapping en 10 min après confirmation.

## Conformité finale (mesurée sur 405 MDs)

| Exigence contrat | Résultat |
|---|---|
| Slug regex `^[a-z0-9]+(-[a-z0-9]+)*$` | 405/405 ✅ |
| Slug ≤50 chars | 405/405 ✅ (max observé : 34) |
| Title [5,100] | 405/405 ✅ |
| Title_card [5,40] | 405/405 ✅ |
| Description [20,200] | 405/405 ✅ |
| Keywords [2-30 chars items, 1-8 items] | 405/405 ✅ (filtre auto applique) |
| `categoryId` non vide | 405/405 ✅ |
| `themeIds` array (peut être vide) | 405/405 ✅ |
| `status` ∈ {approved, published} | 405/405 ✅ (tous `approved`) |
| `ageMin ≤ ageMax` | 405/405 ✅ (4 ≤ 10) |
| `niveauDifficulte` ∈ {easy, medium, hard} | 405/405 ✅ (tous `easy`) |
| URLs R2 basename ASCII kebab | 405/405 ✅ |
| AR slugs 100% ASCII | 405/405 ✅ |
| `_pipeline` / `r2_slug` retirés du MD | 405/405 ✅ |

## Sample concret post-patches — Pompier (FR)

`data/export/rimalab_simulated/src/content/posts/fr/pompier-super-heros.md` :

```yaml
---
locale: 'fr'
slug: 'pompier-super-heros'
title: 'Pompier Super-Héros : Coloriage pour enfants'
title_card: 'Pompier Super-Héros'
description: 'Colorie ce pompier super-héros courageux prêt à sauver les jours et à protéger la ville avec son équipement spécial.'
keywords:
  - 'pompier'
  - 'super-héros'
  - 'courageux'
  - 'sauveur'
  - 'ville'
categoryId: 'general_humans'
themeIds: []
ageMin: 4
ageMax: 10
niveauDifficulte: 'easy'
imageSource: 'https://assets.alwanbooks.com/coloriages/png/firefighter-superhero.png'
imageWeb: 'https://assets.alwanbooks.com/coloriages/webp/firefighter-superhero.webp'
imageThumb: 'https://assets.alwanbooks.com/coloriages/thumbs/firefighter-superhero.webp'
imagePdf: 'https://assets.alwanbooks.com/coloriages/pdf/firefighter-superhero.pdf'
status: 'approved'
datePublication: 2026-05-12
featured: false
---

## Pompier Super-Héros : Coloriage pour enfants

Colorie ce pompier super-héros courageux prêt à sauver les jours et à protéger la ville avec son équipement spécial.
```

## État pipeline

- 608 tests pytest verts (590 + 18 alwanbooks_pipeline avec 4 nouveaux tests sur mapping leaf→cat, filtre keywords, fallback None).
- Mock run complet : 135 leaves OK, 540 variants R2 simulés, 405 MDs.
- Branche dédiée prévue côté rimalab-v2 : `content/export-mep-v0` (jamais main direct).
- Git push automatique côté pipeline désactivé tant que l'utilisateur n'a pas explicitement validé.

## Points d'attention

- `categoryId='animals_cats'` pour 51 leaves animaux non-chats (sémantique imparfaite). Bloquera la review humaine côté rimalab-v2 si scrutiny stricte. Préconisation : créer ≥1 Category `animals_generic` côté plateforme.
- Body MD reste un placeholder simple (`## title` + description). Pas de section "Conseils pédagogiques". À enrichir dans un brief content-writing post-D si désiré.
- Aucun PNG master n'a encore été uploadé sur R2 réel. Les URLs `imageSource/Web/Thumb/Pdf` sont prédites — il faut configurer les creds R2 (`docs/cloudflare-r2-setup.md`) et lancer un smoke test prod pour les rendre 200 OK.
- 15 leaves bloqués upstream par HARD caps Zod (descriptions trop longues). Brief B (i18n) doit re-générer ces 15 leaves pour les ramener dans le corpus exportable.

## Décision / Action suivante

- ✅ Pipeline 100% conforme contrat sur les 405 MDs (post-patches).
- ➡️ `rimalab-v2` : créer Categories `general_humans` + `objects_things` (+ idéalement `animals_generic`). Une fois fait, smoke test prod 1 leaf en réel.
- ➡️ `artiste-coloriage` : (utilisateur) configurer creds Cloudflare R2 + lancer smoke test sur 1 leaf en réel.
- ⏳ Output visible sur `alwanbooks.com` : **15-30 min** une fois Categories créées + creds R2 livrés.
