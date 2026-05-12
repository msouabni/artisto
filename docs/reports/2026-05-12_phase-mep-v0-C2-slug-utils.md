# Phase MEP-v0/C2 — Helpers slugs (R2 + Post par locale)

Date : 2026-05-12
Brief : `docs/architect/briefs/2026-05-12_brief-mep-v0-C2-slug-utils.md`
Branche : `feat/mep-v0-C2-slug-utils`

## Contexte

Implémenter `r2_slug()` et `post_slug()` dans `src/services/slug_utils.py` pour le contrat Alwan Books (`docs/xchange/PIPELINE-CONTRACT.md` §3 — R2 slug ASCII kebab strict, et §5 — Post slug par locale, regex Zod `^[a-z0-9]+(-[a-z0-9]+)*$`). Aucune dépendance pip nouvelle, stdlib uniquement. La translittération AR s'appuie sur `docs/xchange/ar_slug_corpus.csv` (30 entrées de référence) en priorité, avec fallback table char-par-char.

## Résultats

### Fichiers livrés (whitelist respectée)

| Fichier | Type | LOC |
|---|---|---|
| `src/services/slug_utils.py` | NEW | ~280 |
| `tests/test_slug_utils.py` | NEW | ~210 |
| `docs/reports/2026-05-12_phase-mep-v0-C2-slug-utils.md` | NEW | ce fichier |

Aucune zone gelée touchée (vérifié : `src/services/prompt_generator.py`, `src/services/content_generator.py`, `src/api/*`, `data/prompt_generator/*`, `docs/xchange/PIPELINE-CONTRACT.md` inchangés).

### API publique

```python
from services.slug_utils import r2_slug, post_slug, ASCII_KEBAB_RE

r2_slug("Lion in Savanna")              # → "lion-in-savanna"
r2_slug("Éid al-Adha Sheep")            # → "eid-al-adha-sheep"
r2_slug("42 Apples")                    # → ValueError (commence par chiffre)

post_slug("Lion in Savanna", "en")      # → "lion-in-savanna"
post_slug("Chat à la bibliothèque", "fr")  # → "chat-a-la-bibliotheque"
post_slug("أسد في الغابة", "ar")        # → "asad-fi-al-ghaba"
```

### Algo translit AR (priorité décroissante)

1. **Phrase complète** présente dans `ar_slug_corpus.csv` → réutilise le slug exact (cas du brief §3)
2. **Mot par mot** : pour chaque token AR, lookup dans la `word_map` extraite du corpus (alignement automatique gérant `ال` → `al-` et longueurs variables)
3. **Fallback char-par-char** : table inline 30 caractères AR → ASCII (incl. variants hamza, alif maksura, ta marbuta, harakat strippés, tatweel supprimé, `ع` → silencieux conformément au corpus)

### Tests pytest

```
$ python -m pytest tests/test_slug_utils.py -v
=== 52 passed in 0.06s ===
```

Catégories de tests :

| Catégorie | Cas | Couverture |
|---|---|---|
| `r2_slug` valid inputs | 14 | accents (Éid, café, naïve, œuf), ponctuation, underscores, espaces multiples, esperluette, parenthèses, apostrophe |
| `r2_slug` ValueError | 8 | `"42 Apples"`, vide, whitespace, `"!!!"`, `"a"` (trop court), `"1"`, `"---"`, `None` |
| `r2_slug` idempotence | 1 | `r2_slug(r2_slug(x)) == r2_slug(x)` |
| `post_slug` FR/EN | 10 | 5 EN + 5 FR avec accents et caractères latins étendus |
| `post_slug` AR corpus | 10 | ancres réelles du corpus + alignement `ال`/`al-` |
| `post_slug` AR strip harakat | 1 | `"أَسَدٌ فِي الْغَابَةِ"` → `"asad-fi-al-ghaba"` |
| `post_slug` AR strip tatweel | 1 | `"أســـد في الغابة"` → `"asad-fi-al-ghaba"` |
| `post_slug` AR fallback char | 1 | `"كتاب"` (hors corpus) → `"ktab"` via table |
| `post_slug` AR word-by-word | 1 | `"فيل ملون"` (phrase nouvelle, mots connus) → `"fil-mulawwan"` |
| `post_slug` déterminisme | 1 | 3× même call, même résultat |
| `post_slug` erreurs | 3 | locale invalide, input vide, `None` |
| Regex Zod mirror | 1 | sanity check pattern `^[a-z0-9]+(-[a-z0-9]+)*$` |

Suite globale : 240 passed, 5 failed dans le worktree — **les 5 échecs sont préexistants** (test_bulk_generation_jobs ernie negative_prompt, test_workflow_template_sidecar) et identiques avant/après l'introduction de `slug_utils.py` (vérifié par stash + re-test). Le `test_content_generator.py` est aussi cassé en collection (import manquant `HARAKAT_RE` de `ollama_json`), préexistant et hors scope C2.

### Échantillons de slugs générés

| Locale | Input | Slug |
|---|---|---|
| en | `Lion in Savanna` | `lion-in-savanna` |
| en | `Cat in Library` | `cat-in-library` |
| en | `Birthday Cake with Candles` | `birthday-cake-with-candles` |
| fr | `Chat à la bibliothèque` | `chat-a-la-bibliotheque` |
| fr | `Lion dans la Savane` | `lion-dans-la-savane` |
| fr | `Forêt enchantée` | `foret-enchantee` |
| fr | `Père Noël en hiver` | `pere-noel-en-hiver` |
| ar | `أسد في الغابة` | `asad-fi-al-ghaba` |
| ar | `قط في المكتبة` | `qitt-fi-al-maktaba` |
| ar | `فراشة ملونة` | `farasha-mulawwana` |
| ar | `حصان يركض` | `hisan-yarkud` |
| ar | `سمكة في البحر` | `samaka-fi-al-bahr` |

r2_slug (depuis `name_en`) : `Lion in Savanna` → `lion-in-savanna`, `Cat in Library` → `cat-in-library`, `Birthday Cake with Candles` → `birthday-cake-with-candles`, `Forest Enchanted` → `forest-enchanted`, `Santa Claus in Winter` → `santa-claus-in-winter`.

## Points d'attention

1. **Translittération AR fallback char-par-char** : pour les mots AR absents du corpus (ex. `"كتاب"` → `"ktab"`), la table char-par-char **n'insère pas les voyelles courtes** (harakat absents → translit consonantique). Le slug reste valide regex Zod mais peut paraître peu lisible (`mdrsa` au lieu de `madrasa` pour مدرسة). C'est conforme à la spec brief ("déterministe + ASCII + kebab + lisible" — la lisibilité est meilleure quand le corpus a le mot). **Action recommandée** : enrichir `ar_slug_corpus.csv` au fil de la taxonomie (chaque nouveau terme AR ajouté à la taxonomie devrait être ajouté au corpus pour bénéficier d'une translit avec voyelles).

2. **Caractère `ع` silencieux** : aligné avec le corpus (`عصفور` → `usfur`, `ضفدع` → `dafda`, `مع` → `maa`). Le brief proposait `ع → '` (apostrophe puis stripping), j'ai choisi `ع → ""` direct pour cohérence avec les exemples concrets du corpus. Le rendu final reste ASCII kebab. À ré-évaluer si une ancre éditoriale demande l'apostrophe.

3. **Pré-existant hors scope** : `tests/test_content_generator.py` casse en collection (`HARAKAT_RE` et `strip_harakat` importés de `services.ollama_json` mais non définis là — ils existent dans plusieurs scripts POC). Vraie source : le wiring `content_generator → ollama_json` est incomplet sur la branche worktree. À traiter par le brief MEP-v0/B (i18n-batch) ou un patch séparé.

4. **`r2_slug` strict** : la décision archi est de **rejeter** les inputs qui commencent par un chiffre (`"42 Apples"` → `ValueError`). Cohérent avec la regex interne `^[a-z][a-z0-9-]*[a-z0-9]$` plus stricte que la Zod publique. Si l'appelant a un cas légitime (ex. import legacy avec nom contenant chiffres en tête), il peut soit corriger le `name_en` source, soit utiliser `post_slug(name_en, 'en')` qui applique la regex Zod moins stricte (chiffres autorisés en tête).

5. **Aucune dépendance externe ajoutée** : `requirements.txt` inchangé, stdlib uniquement (`csv`, `re`, `unicodedata`, `pathlib`). Compatible avec le contrat "lib slug AR libre" du brief.

## Décision / Action suivante

**Critères d'acceptation : ✅ tous validés.**

- [x] `r2_slug` couvre ≥ 10 cas tests (14 + 8 ValueError + 1 idempotence = 23)
- [x] `post_slug` couvre ≥ 10 cas tests (10 FR/EN + 10 AR corpus + 4 spécifiques + 3 erreurs = 27)
- [x] AR translittéré ASCII kebab, sans harakat, sans latin résiduel
- [x] `ar_slug_corpus.csv` utilisé prioritairement
- [x] Déterminisme vérifié
- [x] Aucune zone gelée touchée
- [x] Aucune dépendance pip nouvelle
- [x] Tests pytest verts (`52 passed` sur `test_slug_utils.py`)
- [x] Aucune régression suite globale (5 échecs préexistants confirmés)

**Action suivante** : Brief C3 (export `data/export/`) peut maintenant consommer `r2_slug` + `post_slug` pour générer les noms de fichiers PNG/WebP/PDF (via `r2_slug`) et les frontmatter Posts MD par locale (via `post_slug`). Brief C1 (migration annotations DB) reste orthogonal.

Si le PMO valide, MAJ MEMORY post-merge avec entrée KB : "slugs MEP v0 = `services.slug_utils.r2_slug/post_slug`, corpus AR éditable dans `docs/xchange/ar_slug_corpus.csv`".
