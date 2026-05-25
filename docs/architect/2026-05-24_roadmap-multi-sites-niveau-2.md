# Roadmap multi-sites — Niveau 2

Date : 2026-05-24
Statut : préparation (pas de livraison maintenant — à déclencher quand un 2e site destinataire arrive concrètement)
Document parent : `docs/architect/2026-05-24_workflow-pipeline-multi-sites.md`

## Quand déclencher

Niveau 2 = "industrialisation multi-sites". À déclencher si **au moins un** des signaux suivants apparaît :

1. **Un 2e site destinataire est planifié** avec une date d'activation concrète (ex: 2e marque éditoriale, site partenaire, dérivé thématique).
2. **L'édition manuelle de `destination_sites.json`** devient fréquente (>3 modifications/mois) ou cause des erreurs (oubli de clone, branche oubliée, etc.).
3. **L'utilisateur demande explicitement** de pouvoir piloter les sites via CLI (sans toucher au JSON à la main).

Tant qu'aucun de ces signaux n'apparaît : **rester en Niveau 1**. YAGNI strict — l'archi Niveau 1 supporte sans douleur 1-2 sites édités à la main.

## Commandes CLI à ajouter

### `pipeline sites add`

```bash
pipeline sites add --id <site_id> \
                   --repo <git_url> \
                   --branch <default_branch> \
                   [--name "Display name"] \
                   [--posts-dir src/content/posts] \
                   [--categories-dir src/content/categories] \
                   [--themes-dir src/content/themes] \
                   [--locales ar,fr,en] \
                   [--bot-name artiste-pipeline] \
                   [--bot-email bot@artiste-coloriage.local]
```

Effets :
1. Valide que `<site_id>` n'existe pas déjà dans `destination_sites.json`.
2. Valide la regex `<site_id>` : `^[a-z][a-z0-9_-]{1,40}$`.
3. Calcule `clone_path = data/sites/<site_id>/`.
4. `git clone <repo> <clone_path>` (échec → rollback : ne pas ajouter au registry).
5. Ajoute l'entrée au registry avec valeurs par défaut pour les champs optionnels.
6. Écrit `destination_sites.json` avec indent 2 + LF.
7. Crée un commit côté `artiste-coloriage` : `chore(sites): add <site_id>`.

### `pipeline sites list`

```bash
pipeline sites list
```

Sortie tabulaire :

```
ID            NAME              ENABLED  BRANCH  CLONE_PATH                       LAST_PUSH
alwanbooks    Alwan Books V2    ✓        main    data/sites/alwanbooks            2026-05-24 bot/lot-2026-05-24
example2      Example 2         ✗        main    data/sites/example2              (jamais)
```

`LAST_PUSH` lu depuis `git log -1 --format="%cs %D" --grep="^feat(content)"` côté clone, parsing rapide. Si erreur → "?".

### `pipeline sites remove <site_id>`

```bash
pipeline sites remove <site_id> [--keep-clone]
```

Effets :
1. Refuse si la branche bot la plus récente du site n'a pas été mergée côté origin (warning, mais peut être bypass avec `--force`).
2. Retire l'entrée du registry.
3. Supprime le clone `data/sites/<site_id>/` (sauf si `--keep-clone`).
4. Commit côté artiste : `chore(sites): remove <site_id>`.

### `pipeline sites enable <id>` / `pipeline sites disable <id>`

Modifient le champ `enabled` du registry. `disable` n'exclut le site que des opérations `--all-sites` (les commandes ciblées `--site <id>` continuent à fonctionner sauf si garde-fou explicite).

### `pipeline sites pull --site <id>`

```bash
pipeline sites pull --site alwanbooks
pipeline sites pull --all-sites
```

Effets :
1. `git fetch origin` côté clone.
2. Vérifie que la working copy est clean (sinon refuse).
3. Si on est sur la branche par défaut : `git pull`. Sinon : warning ("not on default branch, skipping pull").
4. Met à jour le clone pour qu'il reflète l'état origin (utile avant un push pour éviter les conflits de branche bot avec des branches existantes).

### `pipeline push --all-sites`

```bash
pipeline push --all-sites [--regen <slug>...] [--no-git-push]
```

Effets :
1. Boucle sur tous les sites avec `enabled=true` dans le registry.
2. Pour chacun : `pull` (cf. `pipeline sites pull`), puis `push --site <id>` avec les mêmes options.
3. Si un site échoue : continuer les autres, accumuler les erreurs, reporter en fin de boucle.
4. Récap deployment global en sortie (somme par site).

### `pipeline sync-categories --all-sites` / `pipeline sync-themes --all-sites`

Idem pattern `--all-sites`.

### `pipeline cutover --all-sites`

À utiliser si plusieurs sites passent en prod simultanément. Boucle sur tous les sites enabled, applique `cutover` à chacun.

## Hooks pre/post sync (option)

Si besoin émerge : permettre des hooks Python custom par site :

```json
{
  "id": "example2",
  "hooks": {
    "pre_push": "scripts/hooks/example2_pre_push.py",
    "post_push": "scripts/hooks/example2_post_push.py"
  }
}
```

Cas d'usage potentiel :
- Notifier Slack après push.
- Lancer un build smoke côté CI du site.
- Adapter le frontmatter selon les conventions spécifiques du site.

**Anti-pattern à éviter** : ne pas mettre de logique métier dans les hooks. Si le site a un schéma de frontmatter différent, créer un transformer dédié (`structure.frontmatter_transformer: scripts/transformers/example2.py`) plutôt qu'un hook.

## Changements de schéma `destination_sites.json` Niveau 2

Aucun changement breaking. Ajouts optionnels :

```json
{
  "id": "example2",
  "...": "...",
  "hooks": { ... },                        // optionnel, ajouté Niveau 2
  "structure": {
    "...": "...",
    "frontmatter_transformer": "..."       // optionnel, ajouté Niveau 2
  },
  "metrics": {                             // optionnel, ajouté Niveau 2
    "last_push_at": "2026-05-24T10:30:00Z",
    "last_push_branch": "bot/lot-2026-05-24",
    "total_posts_pushed": 411,
    "total_themes_pushed": 5
  }
}
```

Les nouveaux champs sont **uniquement écrits par le pipeline** (l'utilisateur ne les touche pas à la main). Niveau 1 ignore ces champs s'ils sont absents (rétrocompat).

## Tests à ajouter

| Fichier | Tests à ajouter |
|---|---|
| `tests/test_sites_cli.py` | `test_sites_add_clones_and_registers` (mocker `git clone`) · `test_sites_add_refuses_duplicate_id` · `test_sites_add_validates_id_regex` · `test_sites_list_format` · `test_sites_remove_deletes_clone_unless_keep` · `test_sites_remove_refuses_unmerged_branch_without_force` · `test_sites_enable_disable_toggles_field` |
| `tests/test_pipeline_all_sites.py` | `test_push_all_sites_loops_enabled_only` · `test_push_all_sites_continues_on_failure` · `test_sync_categories_all_sites` · `test_pull_all_sites` |
| `tests/test_hooks.py` (si hooks livrés) | `test_pre_push_hook_called_before_git_push` · `test_post_push_hook_failure_logged_but_not_blocking` |

## Estimation effort

| Lot | Estimation |
|---|---|
| Commandes `sites add/list/remove/enable/disable` | ~2-3h |
| Commande `sites pull` + `--all-sites` pattern | ~1-2h |
| Métriques optionnelles (`last_push_at`, etc.) | ~1h |
| Hooks pre/post (si livrés) | ~2-3h |
| Tests + doc | ~2h |
| **Total Niveau 2 sans hooks** | **~6-8h** |
| **Total Niveau 2 avec hooks** | **~8-11h** |

## Anti-patterns à éviter en Niveau 2

1. **Hardcoder un site spécifique** dans le code générique (ex: `if site_id == "alwanbooks":`). Tout comportement spécifique doit passer par le registry (`structure.*` ou `hooks.*`).
2. **Ajouter des creds Git par site** dans `destination_sites.json`. Les creds restent globales (SSH key système). Si un site spécifique demande des creds différentes : passer par config SSH (`~/.ssh/config` avec `Host alwanbooks.github`, `IdentityFile ...`) — invisible pour le pipeline.
3. **Mélanger les responsabilités sites vs registries** (categories/themes). Le registry de sites = "où pousser". Les registries categories/themes = "quoi pousser". Pas de cross-dépendance.
4. **CLI interactive** (`pipeline sites add --interactive`). Tout doit être scriptable, args explicites uniquement.
5. **Permettre `--force` sans confirmation** sur les opérations destructives (remove, push --force jamais). `--force` doit demander une confirmation sauf si `--yes` est aussi passé.

## Évolution Niveau 3+ (envisagée, pas spec)

- **Niveau 3** : skill `artiste-pipeline-skill` qui wrap les commandes CLI les plus fréquentes en prompts naturels (cf. doc workflow §Évolution future).
- **Niveau 4** : GUI web locale hébergée par `start.py` pour les mêmes opérations (backlog).
- **Niveau 5 (très futur)** : delta-driven sync (au lieu de ADD-ONLY simple, calcul d'un 3-way merge entre état pipeline / état clone / état origin).

Ces niveaux sont mentionnés pour mémoire ; aucune spec à ce jour.
