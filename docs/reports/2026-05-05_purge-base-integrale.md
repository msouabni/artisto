# Migration — Purge intégrale base PostgreSQL
Date : 2026-05-05

## Contexte
Préparation à l'intégration d'une nouvelle taxonomie complète. Sauvegarde complète de la base PostgreSQL `artiste_coloriage` puis purge intégrale des données opérationnelles, **schéma préservé** (les migrations Alembic ne sont pas touchées). La table `job_type_config` (configuration des types de jobs) est également préservée car elle est seedée à chaque démarrage API et son intégrité conditionne le bon fonctionnement des workers.

## Résultats — comptages avant / après

| Table | Avant | Après | Δ | Action |
|---|---|---|---|---|
| `ai_prompt_template` | 0 | 0 | 0 | déjà vide |
| `alembic_version` | 1 | 1 | 0 | **PRESERVÉ** (état migrations) |
| `collection` | 0 | 0 | 0 | déjà vide |
| `collection_image` | 0 | 0 | 0 | déjà vide |
| `coverage_stats` | 0 | 0 | 0 | déjà vide |
| `export` | 0 | 0 | 0 | déjà vide |
| `image` | **74** | **0** | -74 | purgé |
| `image_output` | **71** | **0** | -71 | purgé |
| `image_taxonomy_tag` | **18** | **0** | -18 | purgé |
| `job` | **94** | **0** | -94 | purgé |
| `job_type_config` | 14 | 14 | 0 | **PRESERVÉ** (config workers) |
| `locale` | 0 | 0 | 0 | déjà vide |
| `site` | 0 | 0 | 0 | déjà vide |
| `site_publication` | 0 | 0 | 0 | déjà vide |
| `site_taxonomy` | 0 | 0 | 0 | déjà vide |
| `taxonomy` | **1** | **0** | -1 | purgé |
| `term` | **88** | **0** | -88 | purgé |
| `vocabulary` | **1** | **0** | -1 | purgé |
| **Total lignes** | **362** | **15** | **-347** | |

**Validation finale** : tables purgées toutes à 0 ✓ · tables préservées intactes ✓.

## Sauvegardes produites

| Fichier | Taille | Usage |
|---|---|---|
| `backups/2026-05-05_backup-pre-purge.sql` | 408.5 KB | Restauration complète via `psql` (schéma + données + données seed) |
| `backups/2026-05-05_backup-pre-purge.json` | 546.6 KB | Inspection humaine (`ensure_ascii=False`), 9 tables non vides, 362 lignes |

Les deux formats sont **complémentaires** : le SQL pour restauration totale, le JSON pour relecture éditoriale (taxonomie, descriptions, prompts, etc.).

### Restauration complète (rollback)

Pour restaurer **l'intégralité** de la base à l'état avant purge :

```bash
# 1. Stopper les workers et l'API
python start.py --stop  # ou kill manuels

# 2. Restaurer le dump dans le container postgres
docker exec -i artiste-postgres psql -U artiste -d artiste_coloriage < backups/2026-05-05_backup-pre-purge.sql

# 3. Vérifier
docker exec artiste-postgres psql -U artiste -d artiste_coloriage -c "SELECT COUNT(*) FROM term;"
# → doit retourner 88
```

Le dump a été produit avec `--clean --if-exists` : il commence par `DROP TABLE IF EXISTS` puis recrée tout. Pas besoin de purger préalablement la base actuelle ; la restauration écrase et reconstruit.

### Inspection JSON (lecture humaine)

```bash
# tables non vides présentes dans le JSON
python -c "import json; d=json.load(open('backups/2026-05-05_backup-pre-purge.json',encoding='utf-8')); print(list(d['tables'].keys()))"

# parcourir les termes de la taxonomie
python -c "import json; d=json.load(open('backups/2026-05-05_backup-pre-purge.json',encoding='utf-8')); [print(t['id']) for t in d['tables']['term']]"
```

## Procédure de rechargement (nouvelle taxonomie partielle)

La purge laisse la base **vide mais structurellement intacte**. Pour recharger un nouveau jeu de données partiel (typiquement : nouvelle taxonomie sans réinjecter les images / jobs historiques), utiliser le script template :

```bash
python scripts/db_reload.py path/to/new_taxonomy.json
```

`scripts/db_reload.py` est un **squelette documenté** non fonctionnel en l'état. À adapter selon le format exact du fichier source. Il documente :
- l'**ordre d'import inverse** de la purge : `taxonomy → vocabulary → term`
- le **tri topologique** requis sur `term.parent_id` (racines avant feuilles)
- la **validation amont** (cohérence FK source) avant tout INSERT
- la **vérification aval** (comptages attendus vs réels)

**Convention** : pas de réimport de `job_type_config` (préservée), pas de réimport de `alembic_version` (intacte).

## Avertissements

### Ce qui est PERDU (non récupérable sans restaurer le dump)

- **74 images générées** (records `image`) avec leurs prompts, statuts éditoriaux, tags taxonomiques.
- **71 outputs image** (`image_output`) — les fichiers PNG dans `data/outputs/` sont **conservés sur disque** (pas touchés par la purge DB) mais leur lien avec un record image en base est perdu.
- **94 jobs historiques** (générations passées, jobs en `awaiting_validation`, etc.).
- **88 termes taxonomiques** + 1 vocabulaire + 1 taxonomie. C'est la cible de cette purge — sera remplacé par la nouvelle taxonomie.
- **18 image_taxonomy_tag** (associations image ↔ term).

### Ce qui est CONSERVÉ

- **Schéma SQL complet** : toutes les tables, contraintes, indexes, types ENUM intacts. Aucune altération structurelle.
- **`alembic_version`** : l'état des migrations est préservé. `alembic upgrade head` ne fera rien (on est déjà à la dernière révision).
- **`job_type_config`** (14 lignes) : la configuration des types de jobs (image_generation, taxonomy_*, image_*, etc.) est préservée. Ne pas la réinitialiser ni la purger — l'API la re-seede au démarrage si elle est vide, mais on évite ce cycle inutile en la conservant.
- **Fichiers PNG sur disque** dans `data/outputs/` : la purge DB ne touche pas le filesystem. Si on veut nettoyer aussi les fichiers, c'est une opération séparée (`rm data/outputs/*.png`).
- **`backups/2026-05-05_backup-pre-purge.{sql,json}`** : seul filet de récupération si rollback nécessaire.

### Ce qui doit être recréé manuellement après le rechargement

- Les **images** ne seront pas restaurées par le rechargement de la nouvelle taxonomie. Si on veut conserver l'historique des générations, il faut :
  - Soit restaurer le dump complet (rollback total — perte de la nouvelle taxonomie).
  - Soit re-générer les images depuis la nouvelle taxonomie avec ComfyUI.
  - Soit faire un import partiel ciblé des records image depuis le JSON backup, avec ré-association vers les nouveaux term_id (complexe, à éviter sauf nécessité).

## Notes techniques

### Ordre de purge utilisé (corrigé vs brief utilisateur)

L'ordre fourni dans le brief avait une inversion FK sur `term`/`vocabulary` (term FK→vocabulary donc term doit être supprimé AVANT vocabulary, pas APRÈS). Ordre effectif appliqué :

```
1. image_taxonomy_tag    (FK → term, FK → image)
2. coverage_stats        (FK → taxonomy)         — déjà vide
3. site_taxonomy         (FK → site, FK → taxonomy) — déjà vide
4. collection_image      (FK → collection, FK → image) — déjà vide
5. export                (FK → collection)       — déjà vide
6. image_output          (FK → image, FK → job)  ← ajouté (non listé dans brief)
7. job
8. image
9. term                  (FK → vocabulary, FK auto-réf parent_id)
10. vocabulary           (FK → taxonomy)
11. taxonomy
12. site                                          — déjà vide
```

Tables non listées par le brief mais touchées : `image_output` (71 lignes ; sinon FK violée par la suppression de `image` ou `job`).

### `DELETE` vs `TRUNCATE CASCADE`

Choix : `DELETE FROM "table"` table par table en respectant l'ordre FK. Plus verbeux mais permet de logger précisément combien de lignes sont supprimées par table. `TRUNCATE CASCADE` aurait été plus rapide mais (a) plus risqué (pas de contrôle fin) et (b) saute trivialement les contraintes que je veux justement valider.

Toute la purge est dans une **transaction unique** (`engine.begin()`) — si une étape échoue, rollback complet, base intacte.

## Décision / Action suivante

✅ Base purgée et prête à recevoir une nouvelle taxonomie.

Étapes attendues côté caller :
1. Préparer le fichier source (JSON taxonomie, format à figer).
2. Adapter `scripts/db_reload.py` aux champs effectifs de la nouvelle taxonomie.
3. Exécuter `python scripts/db_reload.py path/to/new_taxonomy.json`.
4. Vérifier comptages post-import + sanity check (au moins 1 langue par term).
5. Redémarrer l'API — les workers re-seederont rien (job_type_config intact).

## Annexes

- Backup SQL : `backups/2026-05-05_backup-pre-purge.sql`
- Backup JSON : `backups/2026-05-05_backup-pre-purge.json`
- Script backup : `scripts/db_backup.py`
- Script purge : `scripts/db_purge.py`
- Template rechargement : `scripts/db_reload.py` (à compléter)
- Récap purge JSON : `scripts/_purge_summary.json`
