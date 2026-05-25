# Brief — Création des 7 catégories manquantes côté rimalab-v2

Date : 2026-05-14
Pour : claude-code d'exécution
Repo cible : **`D:\projets\rimalab-v2`** (PAS artiste-coloriage)

---

## Contexte

Le mapper `map_leaf_to_category()` côté `artiste-coloriage` (`scripts/alwanbooks_pipeline.py:506`) produit 9 categoryId distincts pour les 405 Posts MD générés et pushés sur `origin/content/export-mep-v0` (commit `55fcdc0`).

Côté `rimalab-v2`, seules **3 catégories existent** (`animals.md`, `animals_cats.md`, `animals_lions.md`). Le build Astro casse au validate Zod avec :

```
[validate] Post 'abeille-a-miel' references missing categoryId 'animals_wild'.
Known categories: [animals, animals_cats, animals_lions]
```

Il manque 7 catégories. Ce brief crée ces 7 .md selon le pattern des 3 existants, commit, push.

**Note** : une solution durable (registry partagé + test cross-repo qui empêche cette désync) sera planifiée pour le cycle suivant. Ce brief = fix tactique uniquement.

## Objectif

1. Créer 7 fichiers MD dans `D:\projets\rimalab-v2\src\content\categories\`
2. Commit sur la branche actuelle (`content/export-mep-v0`)
3. Push origin
4. Build Astro côté Naymar (`C:\Users\msoua\rimalab-v2`, après `git pull`) doit passer 0 erreur validate categoryId

## Branche cible

`content/export-mep-v0` (déjà existante côté origin, commit récent `55fcdc0`). Vérifier avec `git status` avant toute modif que le clone D:\projets\rimalab-v2 est bien sur cette branche et que working tree est propre. Si autre branche, `git checkout content/export-mep-v0` d'abord.

## Pattern Zod à respecter

Calque sur `D:\projets\rimalab-v2\src\content\categories\animals_lions.md`. Le frontmatter attend exactement :

```yaml
---
id: '<categoryId>'
slug_i18n:
  ar: '<slug ar>'
  fr: '<slug fr>'
  en: '<slug en>'
name_i18n:
  ar: '<name ar>'
  fr: '<name fr>'
  en: '<name en>'
description_i18n:
  ar: '<desc ar, ~80-120 chars>'
  fr: '<desc fr, ~120-150 chars>'
  en: '<desc en, ~120-150 chars>'
keywords_i18n:
  ar:
    - '<kw1 ar>'
    - '<kw2 ar>'
    - '<kw3 ar>'
  fr:
    - '<kw1 fr>'
    - '<kw2 fr>'
    - '<kw3 fr>'
  en:
    - '<kw1 en>'
    - '<kw2 en>'
    - '<kw3 en>'
parent_id: '<animals|null>'
weight: <int>
---

<une ligne de description corps en français>
```

**Strict** : ne pas ajouter de champs, ne pas en supprimer. Toujours `parent_id` (avec `null` si racine), toujours `weight` (entier). Toujours 3 keywords par locale.

## Contenu littéral des 7 fichiers (à copier intégralement)

### 1. `animals_birds.md`

```markdown
---
id: 'animals_birds'
slug_i18n:
  ar: 'tuyur'
  fr: 'oiseaux'
  en: 'birds'
name_i18n:
  ar: 'طيور'
  fr: 'Oiseaux'
  en: 'Birds'
description_i18n:
  ar: 'صفحات تلوين الطيور للأطفال — عصافير وطيور غريبة وطيور جارحة، رسومات ملهمة وسهلة التلوين.'
  fr: 'Coloriages d''oiseaux pour enfants — moineaux, oiseaux exotiques, rapaces, illustrations inspirantes et faciles à colorier.'
  en: 'Bird coloring pages for kids — sparrows, exotic birds, raptors, inspiring and easy line art to color.'
keywords_i18n:
  ar:
    - 'تلوين طيور'
    - 'صفحات عصافير'
    - 'طيور للأطفال'
  fr:
    - 'coloriage oiseau'
    - 'oiseau à imprimer'
    - 'coloriage oiseaux enfant'
  en:
    - 'bird coloring'
    - 'bird coloring page'
    - 'birds for kids'
parent_id: 'animals'
weight: 30
---

Sous-catégorie : oiseaux.
```

### 2. `animals_marine.md`

```markdown
---
id: 'animals_marine'
slug_i18n:
  ar: 'bahriyya'
  fr: 'marins'
  en: 'marine'
name_i18n:
  ar: 'حيوانات بحرية'
  fr: 'Animaux marins'
  en: 'Marine Animals'
description_i18n:
  ar: 'صفحات تلوين الحيوانات البحرية للأطفال — أسماك ودلافين وحيتان وسلاحف بحرية، رسومات بحرية ممتعة.'
  fr: 'Coloriages d''animaux marins pour enfants — poissons, dauphins, baleines, tortues marines, illustrations océaniques amusantes.'
  en: 'Marine animal coloring pages for kids — fish, dolphins, whales, sea turtles, fun ocean line art.'
keywords_i18n:
  ar:
    - 'تلوين حيوانات بحرية'
    - 'صفحات أسماك'
    - 'بحر للأطفال'
  fr:
    - 'coloriage animaux marins'
    - 'coloriage poisson'
    - 'coloriage océan'
  en:
    - 'marine animals coloring'
    - 'fish coloring page'
    - 'ocean coloring'
parent_id: 'animals'
weight: 40
---

Sous-catégorie : animaux marins.
```

### 3. `animals_pets.md`

```markdown
---
id: 'animals_pets'
slug_i18n:
  ar: 'aliifa'
  fr: 'compagnie'
  en: 'pets'
name_i18n:
  ar: 'حيوانات أليفة'
  fr: 'Animaux de compagnie'
  en: 'Pets'
description_i18n:
  ar: 'صفحات تلوين الحيوانات الأليفة للأطفال — كلاب وأرانب وقوارض وطيور أليفة، رفاق منزليين لطفاء للتلوين.'
  fr: 'Coloriages d''animaux de compagnie pour enfants — chiens, lapins, rongeurs, oiseaux domestiques, compagnons mignons à colorier.'
  en: 'Pet coloring pages for kids — dogs, rabbits, rodents, domestic birds, cute household companions to color.'
keywords_i18n:
  ar:
    - 'تلوين حيوانات أليفة'
    - 'صفحات كلاب'
    - 'حيوانات منزلية'
  fr:
    - 'coloriage animaux compagnie'
    - 'coloriage chien'
    - 'coloriage lapin'
  en:
    - 'pet coloring'
    - 'dog coloring page'
    - 'pets coloring'
parent_id: 'animals'
weight: 50
---

Sous-catégorie : animaux de compagnie.
```

### 4. `animals_wild.md`

```markdown
---
id: 'animals_wild'
slug_i18n:
  ar: 'bariyya'
  fr: 'sauvages'
  en: 'wild'
name_i18n:
  ar: 'حيوانات برية'
  fr: 'Animaux sauvages'
  en: 'Wild Animals'
description_i18n:
  ar: 'صفحات تلوين الحيوانات البرية للأطفال — فيلة وحمر وحشية وزرافات وحيوانات الغابة، رسومات قوية لمحبي الطبيعة.'
  fr: 'Coloriages d''animaux sauvages pour enfants — éléphants, zèbres, girafes, animaux de la forêt, illustrations puissantes pour amoureux de la nature.'
  en: 'Wild animal coloring pages for kids — elephants, zebras, giraffes, forest animals, powerful line art for nature lovers.'
keywords_i18n:
  ar:
    - 'تلوين حيوانات برية'
    - 'صفحات فيل'
    - 'حيوانات الغابة'
  fr:
    - 'coloriage animaux sauvages'
    - 'coloriage éléphant'
    - 'coloriage savane'
  en:
    - 'wild animals coloring'
    - 'elephant coloring page'
    - 'safari coloring'
parent_id: 'animals'
weight: 60
---

Sous-catégorie : animaux sauvages.
```

### 5. `general_humans.md`

```markdown
---
id: 'general_humans'
slug_i18n:
  ar: 'shakhsiyat'
  fr: 'personnages'
  en: 'characters'
name_i18n:
  ar: 'شخصيات'
  fr: 'Personnages'
  en: 'Characters'
description_i18n:
  ar: 'صفحات تلوين الشخصيات للأطفال — مهن وأبطال خارقين وحرف يومية، رسومات إنسانية ملهمة وممتعة.'
  fr: 'Coloriages de personnages pour enfants — métiers, super-héros, professions du quotidien, illustrations humaines inspirantes et amusantes.'
  en: 'Character coloring pages for kids — jobs, superheroes, everyday professions, inspiring and fun human line art.'
keywords_i18n:
  ar:
    - 'تلوين شخصيات'
    - 'صفحات مهن'
    - 'أبطال للأطفال'
  fr:
    - 'coloriage personnages'
    - 'coloriage métier'
    - 'coloriage super-héros'
  en:
    - 'character coloring'
    - 'jobs coloring page'
    - 'superhero coloring'
parent_id: null
weight: 100
---

Catégorie racine pour personnages humains, métiers et super-héros.
```

### 6. `objects_things.md`

```markdown
---
id: 'objects_things'
slug_i18n:
  ar: 'ashya'
  fr: 'objets'
  en: 'objects'
name_i18n:
  ar: 'أشياء'
  fr: 'Objets'
  en: 'Objects'
description_i18n:
  ar: 'صفحات تلوين الأشياء للأطفال — أدوات يومية وآلات وألعاب ومركبات، رسومات بسيطة لتعليم الأطفال محيطهم.'
  fr: 'Coloriages d''objets pour enfants — outils du quotidien, machines, jouets, véhicules, illustrations simples pour apprendre le monde qui les entoure.'
  en: 'Object coloring pages for kids — everyday tools, machines, toys, vehicles, simple line art to learn about their surroundings.'
keywords_i18n:
  ar:
    - 'تلوين أشياء'
    - 'صفحات أدوات'
    - 'مركبات للأطفال'
  fr:
    - 'coloriage objets'
    - 'coloriage véhicule'
    - 'coloriage outils'
  en:
    - 'object coloring'
    - 'vehicle coloring page'
    - 'tools coloring'
parent_id: null
weight: 200
---

Catégorie racine pour objets, outils, véhicules et choses du quotidien.
```

### 7. `letters_arabic.md`

```markdown
---
id: 'letters_arabic'
slug_i18n:
  ar: 'al-huruf-al-arabiyya'
  fr: 'alphabet-arabe'
  en: 'arabic-alphabet'
name_i18n:
  ar: 'الحروف العربية'
  fr: 'Alphabet arabe'
  en: 'Arabic Alphabet'
description_i18n:
  ar: 'صفحات تلوين الحروف العربية للأطفال — حرف بحرف مع كلمة مثال، رسومات تعليمية لتعلم القراءة بالعربية.'
  fr: 'Coloriages de l''alphabet arabe pour enfants — lettre par lettre avec mot illustré, illustrations pédagogiques pour apprendre à lire en arabe.'
  en: 'Arabic alphabet coloring pages for kids — letter by letter with example word, educational line art to learn reading in Arabic.'
keywords_i18n:
  ar:
    - 'تلوين الحروف العربية'
    - 'تعلم العربية'
    - 'أبجدية عربية'
  fr:
    - 'alphabet arabe coloriage'
    - 'apprendre arabe enfant'
    - 'lettres arabes'
  en:
    - 'arabic alphabet coloring'
    - 'learn arabic kids'
    - 'arabic letters'
parent_id: null
weight: 300
---

Catégorie racine pour l'alphabet arabe et l'apprentissage de la langue.
```

---

## Étapes d'exécution

```powershell
# 1. Vérifier l'état du clone rimalab-v2 Mardona
cd D:\projets\rimalab-v2
git status                            # working tree doit etre clean
git branch --show-current             # doit etre content/export-mep-v0
git log --oneline -1                  # doit etre 55fcdc0 ou plus recent

# 2. Créer les 7 fichiers dans src/content/categories/
#    Utiliser Set-Content -Encoding utf8 pour chaque fichier
#    Ne PAS utiliser New-Item -Force (risque de tronquer)
#    Encodage UTF-8 sans BOM (cohérent avec les 3 .md existants)

# 3. Vérifier
git status --short                    # doit montrer 7 fichiers untracked dans src/content/categories/
ls src/content/categories/            # doit lister 10 .md (3 existants + 7 nouveaux)

# 4. Sanity check 1 fichier (vérifier que le YAML est parsable)
Get-Content src/content/categories/animals_birds.md -TotalCount 5
# attendu : --- + id: 'animals_birds' + slug_i18n: + ar: 'tuyur' + fr: 'oiseaux'

# 5. Commit + push
git add src/content/categories/
git commit -m "feat(content): 7 nouvelles categories (animals_birds/marine/pets/wild + general_humans + objects_things + letters_arabic)

Debloque le build Astro qui validait categoryId contre les 3 categories
existantes seulement (animals, animals_cats, animals_lions).

Fix tactique. Solution durable (registry partage + test cross-repo) prevue
au cycle suivant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push origin content/export-mep-v0
```

## Critères d'acceptation

1. 7 nouveaux .md créés dans `D:\projets\rimalab-v2\src\content\categories\`
2. Encodage UTF-8 sans BOM (vérifier `[System.IO.File]::ReadAllBytes(...)[0..2]` ne commence pas par `239,187,191`)
3. Frontmatter YAML parsable (caractères AR rendus correctement, pas de remplacement par `?` ou `Ï`)
4. `git status` post-création : 7 untracked / 0 modified ailleurs
5. Commit + push réussis sur `origin/content/export-mep-v0`
6. PAS d'autre modification (pas de touch sur Posts MD existants, pas de tests, pas de doc additionnelle)

## Test final (humain, hors brief)

Côté Naymar `C:\Users\msoua\rimalab-v2` après push origin :

```powershell
cd C:\Users\msoua\rimalab-v2
git fetch origin
git checkout content/export-mep-v0
git pull
npm run build
```

Build attendu :
- 0 erreur validate categoryId
- ~400+ pages générées (405 Posts × locale-cible vs 60 ce matin)
- Les 5 duplicate id warnings (hamster, iron-man, labrador-retriever, scooby-doo, tintin-reporter) persistent — c'est un bug séparé, traité dans un brief distinct.

## Reporting

Créer `docs/reports/2026-05-14_phase-creation-categories-rimalab-v2.md` côté `D:\projets\artiste-coloriage` (PAS côté rimalab-v2) avec :

- Liste des 7 .md créés (path + id)
- Sortie `git log --oneline -2` post-push (commit hash)
- Statut "build Astro à valider côté Naymar par l'utilisateur"
- Tout point d'attention rencontré pendant l'exécution

## Hors-scope (à NE PAS faire)

- Toute modification de Posts MD existants (les 405 sont déjà OK avec le bon categoryId, juste qu'il manquait les categories)
- Toute modification du mapper `artiste-coloriage` (réservé brief niveau 1+2 cycle suivant)
- Toute investigation des 5 duplicate ids (bug B séparé)
- Toute création de Categories supplémentaires non listées (pas de granularité étendue tant que le mapper ne les produit pas)
- Toute modification de `src/content.config.ts` (le Zod schema doit déjà accepter ces categoryIds génériques)
