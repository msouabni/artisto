# Phase — Registry partagé categoryId + sync MDs cross-repo

Date : 2026-05-15
Branche : `feat/categories-registry-cross-repo`
Brief : `docs/architect/briefs/2026-05-15_brief-categories-registry-cross-repo.md`

## Contexte

Bug A (2026-05-14) : `map_leaf_to_category()` côté artiste-coloriage produisait des `categoryId` sans valider qu'ils existent côté rimalab-v2 → build Astro cassait au validate Zod. Fix tactique 2026-05-14 = 7 MDs créés à la main côté rimalab, mais entre-temps claude rimalab a créé 6 catégories sur main avec des wordings différents → divergence.

Solution durable livrée ici : 1 registry JSON côté artiste-coloriage = source unique de vérité, mapper consulte fail-fast, pipeline régénère les MDs côté rimalab depuis le registry (idempotent byte-identique).

## Livrables

### 1. `data/categories_registry.json` (10 catégories, ~280 LOC JSON)

- 3 historiques recopiées byte-byte depuis `D:\projets\rimalab-v2\src\content\categories\animals{,_cats,_lions}.md` (commit rimalab `6889870`, branche `content/export-mep-v0`)
- 7 nouvelles recopiées byte-byte depuis le brief tactique `docs/architect/briefs/2026-05-14_brief-creation-categories-rimalab-v2.md`
- Champ `scope_note` (interne, jamais propagé dans MDs) ajouté selon valeurs explicites du brief 2026-05-15 :
  - `animals_pets` : élargi (compagnie + ferme, pas d'animals_farm)
  - `animals_wild` : élargi (sauvage + fantastique animal, pas d'animals_fantastic)
  - `general_humans` : humanoïdes inclus (fairy, yeti, princess…)
  - `objects_things` : fallback ultime
  - 6 autres : scope_note court 1 ligne
- Format : `ensure_ascii=False`, indent 2 espaces, JSON valide

### 2. Refactor `map_leaf_to_category()` (`scripts/alwanbooks_pipeline.py`)

- Chargement registry au boot module (cache module-level `CATEGORIES_REGISTRY`)
- `KNOWN_CATEGORY_IDS = frozenset(...)` exposé
- Toutes les branches du mapper refactorées pour passer par une variable `result` ; `assert result in KNOWN_CATEGORY_IDS` avant le return
- 0 changement de logique métier (8 règles identiques, mêmes priorités, mêmes regex)

### 3. `tests/test_categories_registry.py` (10 tests, ~180 LOC)

| Test | Vérifie |
|---|---|
| `test_registry_is_valid_json` | JSON parse OK, `version` + `categories` présents |
| `test_registry_has_required_schema` | Champs requis présents et de bon type |
| `test_registry_ids_are_unique` | Pas de doublon d'id |
| `test_registry_ids_match_regex` | `^[a-z][a-z0-9_]*$` |
| `test_registry_parent_ids_resolve` | Tout `parent_id` non-null pointe vers un id existant |
| `test_registry_i18n_has_three_locales` | AR/FR/EN strict sur slug/name/description/keywords |
| `test_registry_keywords_count` | Exactement 3 keywords par locale |
| `test_mapper_only_emits_known_categories` | 130+ leaves de `coloring_taxonomy_full.json` → IDs tous dans registry |
| `test_mapper_known_category_ids_constant_matches_registry` | `KNOWN_CATEGORY_IDS == set(registry ids)` |
| `test_mapper_handles_edge_cases` | None / "" / unknown leaf → fallback registry-valid |

### 4. `tests/test_sync_categories.py` (8 tests, ~190 LOC)

| Test | Vérifie |
|---|---|
| `test_sync_categories_writes_md_files` | 2 catégories → 2 MDs créés |
| `test_sync_categories_md_content_structure` | Frontmatter YAML correct (delimiters, champs, i18n, body, AR préservé) |
| `test_sync_categories_scope_note_never_in_md` | `scope_note` jamais dans le .md généré |
| `test_sync_categories_idempotent_byte_identical` | Re-run sur contenu inchangé = 0 écriture, bytes + mtime identiques |
| `test_sync_categories_detects_change_and_rewrites` | Modification du registry → 1 réécriture ciblée |
| `test_sync_categories_no_utf8_bom` | Pas de BOM UTF-8 en first bytes |
| `test_sync_categories_yaml_field_order` | Ordre id → slug → name → description → keywords → parent_id → weight |
| `test_sync_categories_lf_line_endings` | LF universel (pas de CRLF) |

### 5. Flag CLI `--sync-categories` (`scripts/alwanbooks_pipeline.py`)

- `--sync-categories [--no-git-push]` : régénère uniquement `src/content/categories/*.md` côté rimalab, ignore manifest/posts/R2
- Idempotence byte-identique via `_write_if_changed()` (compare bytes, pas mtime)
- Ordre déterministe des champs : id → slug_i18n → name_i18n → description_i18n → keywords_i18n → parent_id → weight
- Locales toujours dans l'ordre ar → fr → en
- Encodage UTF-8 sans BOM, LF universel
- `scope_note` filtré (`assert "scope_note" not in md` filet de sécurité)
- Aide CLI mise à jour, sortie console `wrote=X skipped=Y total=Z` + détail par fichier

## Résultats tests

### Tests dédiés

```
tests/test_categories_registry.py ........ 10 passed in 0.07s
tests/test_sync_categories.py ........     8 passed in 0.11s
```

### Suite globale

```
pytest --ignore=tests/test_content_generator.py
631 passed in 13.05s
```

**0 régression sur les 613 tests préexistants**.

## Sanity manuel `--sync-categories --no-git-push`

### Run 1 (post-livraison initiale)

```
[sync-categories] wrote=3 skipped=7 total=10
  wrote   src\content\categories\animals.md
  wrote   src\content\categories\animals_cats.md
  wrote   src\content\categories\animals_lions.md
  skipped src\content\categories\animals_birds.md
  skipped src\content\categories\animals_marine.md
  skipped src\content\categories\animals_pets.md
  skipped src\content\categories\animals_wild.md
  skipped src\content\categories\general_humans.md
  skipped src\content\categories\objects_things.md
  skipped src\content\categories\letters_arabic.md
```

Diagnostic : les 3 MDs historiques (`animals`, `animals_cats`, `animals_lions`) étaient stockés en **CRLF** côté rimalab (probablement issus d'un checkout Windows initial). Le pipeline les normalise en **LF universel**.

Vérification `git diff` côté rimalab après sync :

```
git diff --numstat src/content/categories/animals.md       → vide (0+/0-)
git diff --numstat src/content/categories/animals_cats.md  → vide (0+/0-)
git diff --numstat src/content/categories/animals_lions.md → vide (0+/0-)
```

**Aucune ligne de contenu modifiée** — seul changement = line endings CRLF → LF. Git montre un warning `LF will be replaced by CRLF` (autocrlf actif côté rimalab sans `.gitattributes`).

### Run 2 (idempotence)

```
[sync-categories] wrote=0 skipped=10 total=10
```

**100% idempotent byte-identique** au 2e run. État rimalab restauré (`git checkout --`) en fin de sanity pour ne pas polluer le repo.

## Décisions / Points d'attention

### A. Line endings : LF universel choisi (vs CRLF des historiques)

Le pipeline écrit en **LF universel** (`open("wb")`, pas de traduction OS). Justification :

- Les 7 MDs créés au brief tactique 2026-05-14 (commit rimalab `6889870`) sont déjà en LF
- LF est cohérent avec la majorité des MDs `src/content/posts/` (écrits par `write_post_md` via `write_text` UTF-8)
- LF est plus déterministe (pas de variation cross-OS)
- Le 1er sync va normaliser les 3 historiques CRLF → LF (1 fois), puis 100% idempotent
- Pas de `.gitattributes` côté rimalab → autocrlf reste la responsabilité du dev local

**Si rimalab veut imposer CRLF** : ajouter un `.gitattributes` (`*.md text eol=lf`) ou changer la stratégie pipeline. Hors-scope ici, à discuter post-livraison.

### B. `scope_note` filtré par double garde

1. `category_to_md()` n'émet jamais `scope_note` (whitelist de champs `_CATEGORY_FRONTMATTER_ORDER`)
2. `sync_categories()` assert filet de sécurité : `"scope_note" not in md`

Si quelqu'un nomme une catégorie `scope_note_xxx` à l'avenir, cet assert pourrait faire faux positif — à reconsidérer si ça arrive (improbable).

### C. Fail-fast assert dans `map_leaf_to_category`

Le `assert result in KNOWN_CATEGORY_IDS` casse en local si quelqu'un ajoute une 9e règle qui retourne un id non registry. Le test `test_mapper_only_emits_known_categories` l'attrapera aussi. Double garde voulue.

**Note** : `assert` est désactivé par `python -O`. Le pipeline prod ne tourne pas avec `-O` (cf. start.py / lancement direct), c'est OK.

### D. Branche locale, pas de push origin

Comme demandé par le brief : commits propres sur `feat/categories-registry-cross-repo` côté artiste-coloriage, **pas de push origin** (archi valide avant push).

Côté rimalab-v2 : 0 modification persistante (changements de sanity restaurés via `git checkout --`).

## Commits créés (côté artiste-coloriage)

À voir après les commits via `git log --oneline -3`.

## Workflow post-livraison

```powershell
# Modifier une catégorie
notepad data/categories_registry.json

# Tests
pytest tests/test_categories_registry.py tests/test_sync_categories.py -v

# Régénérer côté rimalab
python scripts/alwanbooks_pipeline.py --sync-categories --no-git-push

# Si diff côté rimalab → commit + push manuel
cd D:\projets\rimalab-v2
git add src/content/categories/
git commit -m "sync(categories): regen depuis registry artiste-coloriage v1"
git push origin <branche>
```

## Décision / Action suivante

- Archi valide la branche `feat/categories-registry-cross-repo` (côté artiste-coloriage)
- Une fois validé : push origin + merge sur main / feat/mep-v0-D-alwanbooks-pipeline
- Notifier claude rimalab : wordings retenus = wordings brief tactique 2026-05-14 ; pour modifier, PR sur `data/categories_registry.json` côté artiste-coloriage (jamais sur `src/content/categories/*.md` directement)
- Hors-scope mais à planifier : pre-commit hook côté rimalab qui appelle `--sync-categories` avant chaque commit sur main (sécurité bidirectionnelle)
- Bug B (5 slugs FR=EN identiques) : brief séparé
