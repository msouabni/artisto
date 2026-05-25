# Brief Niveau 1 — Pipeline multi-sites + ADD-ONLY + push auto + Themes

Date : 2026-05-24
Destinataire : claude-code (`artiste-coloriage`, exécution)
Estimation : 3-4 h dev
Documents de référence :
- `docs/architect/2026-05-24_workflow-pipeline-multi-sites.md` (référence d'architecture — lecture obligatoire avant de commencer)
- `data/themes_registry.json` (seed déjà livré 2026-05-24)
- `data/categories_registry.json` (pattern à imiter)

## Contexte

Le pipeline `scripts/alwanbooks_pipeline.py` est aujourd'hui couplé à `rimalab-v2` (path hardcodé, sync destructif sur les posts, push manuel). On passe en architecture multi-sites Niveau 1 : refactor du couplage + bascule en ADD-ONLY pour les posts + push automatique sur branche bot + industrialisation des Themes (parallèle exact des Categories déjà livrées 2026-05-15).

Modèle complet documenté dans `docs/architect/2026-05-24_workflow-pipeline-multi-sites.md`. **Ne pas commencer le code sans avoir lu ce document.**

## Objectif

Livrer un pipeline qui :
1. Pilote N sites destinataires via `data/destination_sites.json` (1 entrée `alwanbooks` au démarrage).
2. N'écrase **jamais** un post existant côté site (Modèle A — ADD-ONLY + blocklist + `--regen` explicite).
3. Industrialise les Themes (sync ADD-ONLY, auto-tag `themeIds` à la création des posts).
4. Push automatiquement sur branche `bot/lot-{YYYY-MM-DD}[-N]` avec identité bot dédiée.
5. Imprime un récap deployment lisible en fin de chaque run.
6. Fournit un verbe `cutover` pour le bump massif `approved → published` à J+30.

Le pipeline reste **rétrocompatible** au sens où une exécution standard sur `alwanbooks` produit le même résultat fonctionnel qu'aujourd'hui (mêmes posts, mêmes categories, mêmes variants R2), mais en ADD-ONLY au lieu de full sync.

## Périmètre détaillé

### 1. `data/destination_sites.json` (nouveau)

Schéma :

```json
{
  "version": 1,
  "sites": [
    {
      "id": "alwanbooks",
      "name": "Alwan Books V2",
      "repo_url": "git@github.com:msouabni/rimalab-v2.git",
      "default_branch": "main",
      "import_branch_pattern": "bot/lot-{date}",
      "clone_path": "data/sites/alwanbooks",
      "enabled": true,
      "structure": {
        "posts_dir": "src/content/posts",
        "categories_dir": "src/content/categories",
        "themes_dir": "src/content/themes",
        "locales": ["ar", "fr", "en"]
      },
      "bot": {
        "name": "artiste-pipeline",
        "email": "bot@artiste-coloriage.local"
      }
    }
  ]
}
```

Charger ce fichier au boot du module `alwanbooks_pipeline.py`. Exposer une fonction `get_site(site_id: str) -> dict` qui lève une exception claire si l'id n'existe pas ou est `enabled=false`.

**Préparer le terrain Niveau 2** : structurer le code pour que l'ajout futur de `pipeline sites add/list/remove` (Niveau 2) ne demande qu'à wrapper cette fonction. Pas de CLI sites pour Niveau 1.

### 2. `.gitignore` (modifier)

Ajouter :
```
# Clones des sites destinataires (Niveau 1 multi-sites)
data/sites/
```

### 3. Migration `data/sites/alwanbooks/` (geste manuel hors-pipeline)

L'utilisateur (ou ce brief en setup) doit cloner manuellement :
```powershell
git clone git@github.com:msouabni/rimalab-v2.git D:\projets\artiste-coloriage\data\sites\alwanbooks
```

Le pipeline lit ensuite ce clone via `clone_path` du registry. Le path historique `D:\projets\rimalab-v2` n'est **plus utilisé par le pipeline** après cette migration. Tu peux le laisser intact (utile pour humain), il sera ignoré.

Documente la commande de clone dans le rapport final.

### 4. Refactor `scripts/alwanbooks_pipeline.py` — mode posts ADD-ONLY

**Comportement actuel** : sync destructif (overwrite tous les MDs côté rimalab). À changer :

**Comportement cible** :
- Par défaut (`pipeline push --site alwanbooks`) : pour chaque leaf à traiter, vérifier si le post `<locale>/<slug>.md` existe déjà côté site. Si oui → skip (incrémenter compteur `posts_skipped_addonly`). Si non → écrire le MD (incrémenter `posts_created`).
- Avec `--regen <slug>` (multiple OK) : overwrite explicite des slugs ciblés, même s'ils existent.
- Avec `--regen-file <path.txt>` : lire les slugs depuis un fichier (1 slug par ligne, ignorer commentaires `#`).
- Avec `--regen-all` : overwrite full (mode legacy actuel, exposé pour cas de migration / refonte template). Doit être annoncé clairement en sortie (`⚠️  Mode --regen-all : tous les posts seront écrasés`).

**Lecture blocklist** :
- Créer `data/pipeline_blocklist.json` (vide au début) avec schéma :
  ```json
  {
    "version": 1,
    "blocked_posts": {
      "alwanbooks": ["slug1", "slug2"]
    }
  }
  ```
- Au moment de push un post, vérifier `blocklist[site_id]`. Si le slug y est → skip (incrémenter `posts_blocklisted`).
- Verbe CLI `pipeline blocklist add-post <slug> --site <id>` qui édite ce fichier.

### 5. Push automatique sur branche bot

À la fin d'un `push` (sauf si `--no-git-push` ou si 0 écriture) :

1. Calculer le nom de branche : `bot/lot-{YYYY-MM-DD}` (date locale).
2. Si la branche existe déjà côté origin du site : essayer `bot/lot-{YYYY-MM-DD}-2`, `-3`, etc., jusqu'à trouver un nom libre.
3. Côté clone local (`data/sites/<id>/`) : `git checkout -b <branche>`, `git add src/content/...`, `git commit -m "<msg>"` avec identité bot temporaire (`-c user.name="..." -c user.email="..."`), `git push -u origin <branche>`.

**Format commit message** :
```
feat(content): lot {YYYY-MM-DD} (+{N_posts}p +{N_themes}t)

Posts créés      : {N_posts}
Themes créés     : {N_themes}
Categories sync  : {N_cat_modified}
R2 variants      : {N_r2_uploaded} uploadés / {N_r2_skipped} skipped
```

**Plusieurs commits dans le même push** : si à la fois posts + themes sont impactés, créer 2 commits distincts (`feat(content): posts lot ...` et `feat(content): themes lot ...`) avant push, pour la lisibilité git.

**Flag `--no-git-push`** : à conserver. Skip uniquement le push (l'écriture locale est faite normalement).

### 6. Industrialisation Themes

Nouveau registry `data/themes_registry.json` : **déjà livré 2026-05-24 + patché 2026-05-25** par l'archi (**4 themes seed** : noel + ramadan + saison-hiver + saison-ete + 32 leaves attachées). Schéma documenté dans le fichier lui-même (`schema_note`).

**Note patch 2026-05-25** : le 5e theme `arabic-alphabet` initialement présent dans le seed a été retiré (doublon sémantique avec la category `letters_arabic` signalé par claude rimalab). L'éditorial i18n riche (5 paragraphes × 3 locales) a été migré dans `data/categories_registry.json` sur l'entrée `letters_arabic` via un nouveau champ optionnel `editorial_body_i18n` (parallèle aux themes). **Ce champ est documentaire pour le brief Niveau 1** : le code `--sync-categories` actuel ne sait pas l'écrire dans le `.md` (mini-brief séparé à venir pour étendre le code sync-categories). Niveau 1 ne touche pas à cette extension categories — focus uniquement sur les Themes.

Différences avec `categories_registry.json` :
- Champ supplémentaire `editorial_body_i18n` (texte long multi-paragraphes par locale, séparateur `\n\n`).
- Champ supplémentaire `leaves` (array de leaf_ids → themes auto-tagging).
- Pas de hiérarchie obligatoire (`parent_id: null` partout dans le seed, mais le schéma le supporte).

**Verbes à implémenter** :

| Verbe | Effet |
|---|---|
| `pipeline sync-themes --site <id>` | Pour chaque theme du registry : si `themes/<id>.md` n'existe pas côté site → écrire. Si existe → skip (ADD-ONLY). Push branche bot. |
| `pipeline sync-themes --site <id> --regen-theme <id>` | Overwrite explicite ciblé. Multiple OK. |
| `pipeline blocklist add-theme <id> --site <id>` | Ajoute à `data/pipeline_themes_blocklist.json` (créer si absent, schéma parallèle à blocklist posts). |

**Conversion JSON → MD theme** : format YAML frontmatter + body markdown. Reproduire exactement le format de `data/sites/alwanbooks/src/content/themes/arabic-alphabet.md` (= le placeholder côté rimalab qui sert de référence de format, mais qui sera supprimé au prochain --sync-themes une fois le theme retiré du registry et un mécanisme de drop ajouté — pour Niveau 1 ne pas implémenter le drop, juste écrire les 4 themes du registry). Spécificité : `editorial_body_i18n` en YAML literal block scalar (`|`) avec préservation des paragraphes (séparateur `\n\n`).

**Encodage** : UTF-8 sans BOM, LF universel (cohérent avec `--sync-categories` livré 2026-05-15).

**Idempotence byte-identique** : 2e run de `--sync-themes` sans changement → 0 écriture. Comparer bytes (pas mtime).

### 7. Auto-tagging `themeIds` à la création des posts

À la création d'un nouveau post (étape 4 — mode ADD-ONLY) :
1. Récupérer le `leaf_id` du leaf source.
2. Parcourir `themes_registry.json`, identifier les themes contenant ce `leaf_id` dans leur tableau `leaves`.
3. Écrire `themeIds: [<theme_id1>, <theme_id2>, ...]` dans le frontmatter du post.

**Préservation lors de regen** : si `pipeline --regen <slug>` overwrite un post, recalculer `themeIds` depuis le registry à ce moment-là (= valeur fraîche).

**Cas vide** : si aucun theme ne contient le leaf, écrire `themeIds: []` (champ obligatoire selon schéma actuel).

**Cohérence avec édition manuelle** : si l'humain édite `themeIds` à la main dans un post existant, c'est protégé par ADD-ONLY (pas regen → pas écrasé).

### 8. Récap deployment imprimé

À la fin de **chaque** run, imprimer un bloc structuré sur stdout :

```
=== artiste-pipeline — push lot 2026-05-24 vers site=alwanbooks ===
Mode posts        : ADD-ONLY (--regen=<aucun>)
Posts créés       : 12
Posts ignorés     : 399 (déjà présents)
Posts blocklist   : 0
Categories sync   : 0 (registry inchangé)
Themes sync       : 1 créé (noel) / 4 existants ignorés
themeIds auto-tag : 47 posts impactés (lecture themes_registry)
R2 variants       : 48 uploadés / 24 skipped (etag match) / 0 failed

Branche push      : bot/lot-2026-05-24
Commits           : 2 (feat: 12 posts, feat: 1 theme noel)
URL branche       : https://github.com/msouabni/rimalab-v2/tree/bot/lot-2026-05-24

À faire côté site destinataire (humain / claude site) :
  1. git fetch origin
  2. git checkout bot/lot-2026-05-24
  3. npm run build  (vérifier 0 erreur Zod)
  4. Ouvrir PR + review + merge sur main
```

Le récap doit être copy-pastable. Si `--no-git-push`, remplacer le bloc "Branche push / Commits / URL / À faire" par "⚠️  Mode --no-git-push : écriture locale uniquement, pas de push".

### 9. Verbe `pipeline cutover --site <id>`

À utiliser une seule fois au cutover J+30. Effet :
1. Lire tous les `posts/{ar,fr,en}/*.md` côté site.
2. Pour chaque post avec `status: 'approved'` : remplacer par `status: 'published'`. Pas toucher au reste du frontmatter ni au body.
3. Préserver bytes identiques sur tous les autres champs (regex ciblée sur la ligne `status:`, pas re-parse YAML).
4. Commit unique massif sur branche `bot/cutover-{YYYY-MM-DD}`, message : `chore(content): cutover preview→public ({N_modified} posts approved→published)`.
5. Push.
6. Récap : nombre de posts modifiés / nombre de posts déjà `published` / nombre de posts en autre statut (warning).

**Garde-fou** : refuser de tourner si le clone local n'est pas sur `main` ou si `git status` n'est pas clean.

**Convention naming `PUBLIC_SITE_STATE`** (confirmation patch 2026-05-25 après retour claude rimalab) : la var d'env côté Astro vaut `='public'` (pas `'production'`) en mode prod, cohérent avec `robots.txt.ts` et `BaseLayout.astro` côté rimalab. Le verbe `cutover` ne touche pas à cette var d'env (c'est claude rimalab qui la flippe le jour J), mais les commit messages et la doc doivent dire "preview→public" pour rester cohérents avec l'écosystème rimalab. **NE PAS introduire le terme "production" dans le code/doc de ce verbe.**

### 10. Tests à ajouter

Sous `tests/` (suite globale doit passer sans régression — actuellement 631 tests verts via `pytest --ignore=tests/test_content_generator.py`).

| Fichier | Tests à ajouter |
|---|---|
| `tests/test_destination_sites.py` (nouveau) | `test_load_sites_registry_ok` · `test_get_site_unknown_raises` · `test_get_site_disabled_raises` · `test_sites_registry_schema_valid` |
| `tests/test_pipeline_addonly.py` (nouveau) | `test_push_skips_existing_post` · `test_push_creates_missing_post` · `test_regen_overwrites_existing` · `test_regen_file_reads_list` · `test_blocklist_skips_post` · `test_blocklist_add_post_writes_file` |
| `tests/test_themes_registry.py` (nouveau, calqué sur `test_categories_registry.py`) | `test_registry_is_valid_json` · `test_registry_has_required_schema` · `test_registry_ids_are_unique` · `test_registry_ids_match_regex` · `test_registry_i18n_has_three_locales` · `test_registry_keywords_count` (entre 1 et 8 — schéma plus souple que categories qui sont à 3) · `test_registry_editorial_body_has_three_locales` · `test_registry_leaves_are_unique_within_theme` · `test_registry_leaves_resolve_to_taxonomy` (warning si leaf inexistant dans coloring_taxonomy_full.json — ne pas faire échouer car certains leaves peuvent venir d'extensions futures, juste logger) |
| `tests/test_sync_themes.py` (nouveau, calqué sur `test_sync_categories.py`) | `test_sync_themes_writes_md_files` · `test_sync_themes_md_content_structure` · `test_sync_themes_skips_existing_md_addonly` · `test_sync_themes_regen_theme_overwrites` · `test_sync_themes_editorial_body_preserves_paragraphs` (vérifier que `\n\n` du registry → blocs vides en YAML literal block) · `test_sync_themes_no_utf8_bom` · `test_sync_themes_lf_line_endings` · `test_sync_themes_scope_note_never_in_md` |
| `tests/test_pipeline_autotag_themes.py` (nouveau) | `test_post_gets_themeIds_from_registry` · `test_post_with_no_matching_theme_gets_empty_themeIds` · `test_regen_recomputes_themeIds_from_current_registry` |
| `tests/test_pipeline_push_branch.py` (nouveau) | `test_branch_name_uses_today_date` · `test_branch_name_increments_suffix_on_collision` (mocker `git ls-remote`) · `test_commit_uses_bot_identity` · `test_no_git_push_skips_push` (mocker `subprocess.run`) |
| `tests/test_pipeline_cutover.py` (nouveau) | `test_cutover_bumps_approved_to_published` · `test_cutover_preserves_other_fields_bytewise` · `test_cutover_refuses_dirty_working_tree` (mocker `git status`) · `test_cutover_skips_already_published` |

Estimation : 30-40 tests nouveaux. Couvrir les chemins critiques, pas chercher l'exhaustivité.

### 11. Documentation à mettre à jour

- `CLAUDE.md` : ajouter section "Workflow pipeline → sites destinataires" qui résume les 4 verbes humains + lien vers `docs/architect/2026-05-24_workflow-pipeline-multi-sites.md`. Mentionner explicitement que `--sync-categories` reste destructif (registry-driven) alors que `push` est ADD-ONLY (Modèle A).
- `data/categories_registry.json` : pas de modif (laisser tel quel).
- `data/themes_registry.json` : pas de modif (livré tel quel par archi).
- Créer `data/sites/.gitkeep` (pour que le dossier vide soit traçable).

## Critères d'acceptation

1. **Tests** : suite globale verte (`pytest --ignore=tests/test_content_generator.py`) après ajout des nouveaux tests. Compteur attendu : ~660-670 tests verts (vs 631 actuels).
2. **Smoke run réel sur alwanbooks** :
   - `pipeline push --site alwanbooks --no-git-push` (mode sécurité) → résultat attendu : `posts_created = 0` (les 411 posts existent déjà côté site), `posts_skipped_addonly = 411`, `themes_created = 5` (les 5 du registry), récap imprimé proprement.
   - `pipeline sync-themes --site alwanbooks --no-git-push` → résultat attendu : `themes_created = 0` ou `4` selon si le step précédent a déjà créé les themes. Tester l'idempotence (2e run = 0 écriture).
3. **Vérification visuelle** : ouvrir un theme généré (ex `data/sites/alwanbooks/src/content/themes/noel.md`) et confirmer que le format est identique au pattern `arabic-alphabet.md` (référence de format côté rimalab) : YAML frontmatter avec `editorial_body_i18n` en literal block scalar `|`, body markdown final, encoding UTF-8 sans BOM, LF.
4. **Récap deployment** : confirmer visuellement que le bloc imprimé est lisible, copy-pastable, contient toutes les sections.
5. **`git status` côté `data/sites/alwanbooks/`** après smoke : seuls les 4 themes nouveaux (noel, ramadan, saison-hiver, saison-ete) en untracked, rien de modifié. `arabic-alphabet.md` reste présent (placeholder rimalab existant, sera supprimé plus tard via un mini-brief drop). Si modification inattendue sur des posts existants → bug ADD-ONLY à corriger.
6. **Aucun push automatique** durant la phase test (utiliser `--no-git-push` partout pendant le dev pour éviter de spammer rimalab).

## Reporting

Produire `docs/reports/2026-05-24_phase-niveau-1-multi-sites-add-only.md` :

- **Contexte** : 1-2 phrases
- **Livrables** : liste des fichiers créés/modifiés (paths)
- **Tests** : `pytest` final count, nb nouveaux tests, 0 régression
- **Smoke runs** : output récap deployment des 2 commandes smoke (copier-coller)
- **Points d'attention** : décisions design non triviales prises pendant l'implémentation, edge cases identifiés
- **Décision / Action suivante** : "Niveau 1 livré, prêt pour utilisation en routine. Niveau 2 backlog (cf. roadmap)."

## Hors-scope explicitement

- **Commandes CLI `pipeline sites add/list/remove/etc.`** (Niveau 2 — roadmap dédiée).
- **Push automatique au moment de `--sync-categories`** (laisser le comportement actuel du flag inchangé).
- **Renommage de `alwanbooks_pipeline.py` en `pipeline.py`** : pas obligatoire pour Niveau 1 (peut induire des conflits import). Garder le nom actuel.
- **Documentation côté rimalab (`PIPELINE-NOTES.md`)** : sera produite séparément par claude rimalab après livraison Niveau 1.
- **Skill ou GUI** : explicitement reporté (cf. doc workflow, Niveau 3/4).
- **Pre-commit hook côté rimalab** : reporté backlog.
- **Migration des creds R2** : déjà en `.env`, pas à toucher.

## Sécurité

- Aucun secret (creds R2, tokens) ne doit apparaître dans les rapports ni dans aucun log committé.
- Les commits bot ne doivent jamais skip les hooks (`--no-verify` interdit sauf si l'utilisateur le demande explicitement).
- Le push automatique cible **uniquement** la branche bot (jamais `main` directement, jamais `--force`).

## Ordre d'implémentation recommandé

1. Lire `docs/architect/2026-05-24_workflow-pipeline-multi-sites.md` en entier.
2. Créer `data/destination_sites.json` + tests `test_destination_sites.py`.
3. Refactor lecture path rimalab dans `alwanbooks_pipeline.py` (utiliser registry au lieu de hardcode).
4. Cloner manuellement rimalab-v2 dans `data/sites/alwanbooks/`.
5. Implémenter mode ADD-ONLY + blocklist posts + tests.
6. Implémenter sync-themes + auto-tag themeIds + tests.
7. Implémenter push auto branche bot + tests (mocker subprocess).
8. Implémenter récap deployment (cosmetic, à la fin).
9. Implémenter verbe cutover + tests.
10. Smoke runs réels en `--no-git-push`.
11. Mettre à jour CLAUDE.md.
12. Rédiger rapport phase.

Ne pas tout faire en parallèle. Chaque étape doit être verte (tests) avant de passer à la suivante.
