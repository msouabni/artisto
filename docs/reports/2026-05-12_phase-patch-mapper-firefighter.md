# Phase — Patch mapper categoryId + génération 3 MDs firefighter_superhero
Date : 2026-05-12

## Résultats (5 lignes max)

- Patch `map_leaf_to_category()` reécrit selon brief : 8 règles ordonnées (lions / birds / marine / pets / wild / humans / letters / fallback objects_things). `lion_in_the_savanna` → `animals_lions` (OK), big cats exclus de `animals_pets`, fallback final passe d'`animals_cats` à `objects_things`.
- `_ensure_post_complete` injecte désormais `dateModification` (= `datePublication` au premier export) — bloqueur Zod V2 B3 acté par dev rimalab.
- Tests mapper : 23/23 verts (`tests/test_alwanbooks_pipeline.py`). Couverture étendue à 80+ cas leaf → category (toutes catégories rimalab + filtre big_cats). Suite globale : 613/613 verts, 0 régression (`pytest --ignore=tests/test_content_generator.py`).
- Pipeline exécutée en `--leaf-id firefighter_superhero --no-git-push --mock` : 4 variants R2 simulés + 3 MDs écrits dans `D:/projets/rimalab-v2/src/content/posts/{fr,en,ar}/`. Pas de commit côté rimalab-v2 (zone gelée respectée).
- Les 3 MDs contiennent `categoryId: 'general_humans'` et `dateModification: 2026-05-12` (= `datePublication`) — prêts pour build Astro + validation Zod côté naymar.

## Annexe — 3 MDs raw firefighter_superhero

### MD FR (path: src/content/posts/fr/pompier-super-heros.md)

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
dateModification: 2026-05-12
featured: false
---

## Pompier Super-Héros : Coloriage pour enfants

Colorie ce pompier super-héros courageux prêt à sauver les jours et à protéger la ville avec son équipement spécial.
```

### MD EN (path: src/content/posts/en/firefighter-superhero.md)

```yaml
---
locale: 'en'
slug: 'firefighter-superhero'
title: 'Brave Firefighter Superhero Coloring Page'
title_card: 'Firefighter Hero'
description: 'Color this brave firefighter superhero who saves the day with a giant hose and a bright red helmet for kids to enjoy.'
keywords:
  - 'firefighter'
  - 'superhero'
  - 'coloring'
  - 'kids'
  - 'hero'
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
dateModification: 2026-05-12
featured: false
---

## Brave Firefighter Superhero Coloring Page

Color this brave firefighter superhero who saves the day with a giant hose and a bright red helmet for kids to enjoy.
```

### MD AR (path: src/content/posts/ar/itfayy-btl-kharq.md)

```yaml
---
locale: 'ar'
slug: 'itfayy-btl-kharq'
title: 'إطفائي بطل خارق: صفحة تلوين للأطفال'
title_card: 'إطفائي بطل خارق'
description: 'استمتع بتلوين صورة الإطفائي البطل الخارق في هذه الصفحة التعليمية الممتعة والمثالية للأطفال.'
keywords:
  - 'إطفائي'
  - 'بطل'
  - 'خارق'
  - 'تلوين'
  - 'أطفال'
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
dateModification: 2026-05-12
featured: false
---

## إطفائي بطل خارق: صفحة تلوين للأطفال

استمتع بتلوين صورة الإطفائي البطل الخارق في هذه الصفحة التعليمية الممتعة والمثالية للأطفال.
```
