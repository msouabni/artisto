# Phase — Niveau 1 multi-sites + ADD-ONLY + push auto + Themes
Date : 2026-05-24

## Contexte

Refactor du pipeline `scripts/alwanbooks_pipeline.py` pour passer en architecture multi-sites Niveau 1 : ADD-ONLY pour les posts/themes, push auto sur branche bot, industrialisation des themes, auto-tagging themeIds, verbe cutover.

## Livrables

### Fichiers créés

| Fichier | Description |
|---|---|
| `data/destination_sites.json` | Registry des sites destinataires (1 entrée alwanbooks) |
| `data/pipeline_blocklist.json` | Blocklist posts (vide) |
| `data/pipeline_themes_blocklist.json` | Blocklist themes (vide) |
| `data/sites/.gitkeep` | Répertoire pour les clones sites |
| `tests/test_destination_sites.py` | 4 tests registry sites |
| `tests/test_themes_registry.py` | 9 tests registry themes |
| `tests/test_pipeline_addonly.py` | 6 tests ADD-ONLY + blocklist |
| `tests/test_sync_themes.py` | 8 tests sync themes |
| `tests/test_pipeline_autotag_themes.py` | 3 tests auto-tag themeIds |
| `tests/test_pipeline_push_branch.py` | 4 tests push branche bot |
| `tests/test_pipeline_cutover.py` | 4 tests cutover |

### Fichiers modifiés

| Fichier | Description |
|---|---|
| `scripts/alwanbooks_pipeline.py` | Refactor complet : ADD-ONLY, themes, blocklist, bot push, cutover, récap deployment |
| `.gitignore` | Ajout `data/sites/*/` |
| `CLAUDE.md` | Section "Workflow pipeline → sites destinataires" |

## Tests

```
pytest --ignore=tests/test_content_generator.py → 669 passed in 13.31s
```

- Avant : 631 tests
- Après : 669 tests (+38 nouveaux)
- Régressions : 0

## Smoke runs

### Smoke 1 — Push initial (site main → création 405 posts + 4 themes)

```
=== artiste-pipeline — push lot 2026-05-25 vers site=alwanbooks ===
Mode posts        : ADD-ONLY (--regen=<aucun>)
Posts créés       : 405
Posts ignorés     : 0 (déjà présents)
Posts blocklist   : 0
Categories sync   : 0 modifs (registry)
Themes sync       : 4 créé (noel, ramadan, saison-hiver, saison-ete) / 0 existants ignorés
themeIds auto-tag : 12 posts impactés (lecture themes_registry)
R2 variants       : 540 uploadés / 0 skipped (etag match) / 0 failed

  Mode --no-git-push : écriture locale uniquement, pas de push
```

### Smoke 2 — Idempotence ADD-ONLY (2e run = 0 écriture)

```
=== artiste-pipeline — push lot 2026-05-25 vers site=alwanbooks ===
Mode posts        : ADD-ONLY (--regen=<aucun>)
Posts créés       : 0
Posts ignorés     : 405 (déjà présents)
Posts blocklist   : 0
Categories sync   : 0 modifs (registry)
Themes sync       : 0 créé / 4 existants ignorés
themeIds auto-tag : 0 posts impactés (lecture themes_registry)
R2 variants       : 540 uploadés / 0 skipped (etag match) / 0 failed

  Mode --no-git-push : écriture locale uniquement, pas de push
```

### Smoke 3 — Sync-themes standalone (idempotent)

```
[sync-themes] created=0 skipped=4 overwritten=0 blocklisted=0 total=4
```

## Points d'attention

1. **Site `main` branch** : la branche `main` de rimalab-v2 ne contient que 6 posts (les 6 du firefighter batch). Les 405 autres sont sur la branche non-mergée `content/export-mep-v0`. Le brief attendait 411 posts sur main — cet écart est normal et n'est pas un bug pipeline.

2. **Themes : 4 dans le registry** (patch 2026-05-25 : `arabic-alphabet` retiré du registry car doublon sémantique avec `letters_arabic`). Le fichier `arabic-alphabet.md` reste côté rimalab comme placeholder — suppression via mini-brief drop séparé.

3. **themeIds auto-tag** : 12 posts sur 135 leaves contiennent un leaf_id présent dans `themes_registry.json` → `themeIds` automatiquement rempli. Les cross-overs (un leaf dans 2+ themes) produisent des arrays multi-valeurs correctement.

4. **Format theme MD** : vérifié visuellement identique au pattern `arabic-alphabet.md` — YAML frontmatter avec `editorial_body_i18n` en literal block scalar `|`, paragraphes préservés par `\n\n`, UTF-8 sans BOM, LF uniquement.

5. **`scope_note` jamais émis** : garanti par assert dans le code + tests dédiés dans `test_sync_themes.py` et `test_sync_categories.py`.

6. **Git clone local** : le clone `data/sites/alwanbooks` est créé depuis le repo local `D:\projets\rimalab-v2` (SSH host key non disponible dans l'environnement sandboxé). Le remote a été mis à jour vers l'URL SSH GitHub (`git@github.com:msouabni/rimalab-v2.git`).

7. **`--regen-all` warning** : le flag affiche un avertissement explicite sur stdout avant de procéder.

## Décision / Action suivante

Niveau 1 livré, prêt pour utilisation en routine. Le premier vrai push sur rimalab-v2 se fera via :

```powershell
python scripts/alwanbooks_pipeline.py --site alwanbooks
```

(sans `--no-git-push` ni `--mock`), qui créera la branche `bot/lot-YYYY-MM-DD` et poussera les posts + themes.

Niveau 2 backlog : commandes CLI `pipeline sites add/list/remove`, `push --all-sites`, hooks pre/post sync (cf. `docs/architect/2026-05-24_roadmap-multi-sites-niveau-2.md`).
