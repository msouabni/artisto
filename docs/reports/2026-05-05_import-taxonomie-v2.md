# Migration — Import taxonomie v2 (coloring_taxonomy_seo.json)
Date : 2026-05-05

## Contexte
Suite à la purge intégrale (cf. `2026-05-05_purge-base-integrale.md`), import de la nouvelle taxonomie depuis `docs/xchange/coloring_taxonomy_seo.json`. Source : 18 racines, 145 sous-thèmes, 1376 feuilles = **1539 nœuds**.

## Mapping appliqué

| Source | Cible DB |
|---|---|
| 18 racines + 145 sous-thèmes + 1376 feuilles | 1539 lignes `term` |
| (synthétique) | 1 ligne `taxonomy` (id=`coloring_themes`) |
| (synthétique) | 1 ligne `vocabulary` (id=`themes`, taxonomy_id=`coloring_themes`) |
| `id` | `term.id` ET `term.slug` (le slug source est déjà conforme kebab/snake) |
| `name_en`, `name_fr`, `name_ar` | `term.name_i18n` (JSON `{"en": …, "fr": …, "ar": …}`) |
| (parent dans la hiérarchie) | `term.parent_id` (`NULL` pour les racines) |
| index dans le parent | `term.weight` |
| `seo` (objet) | **ignoré** — pas de colonne `metadata` dans le schéma |

`level` calculé pour les stats (0/1/2) mais **non persisté** : aucune colonne dédiée. Il se retrouve par `parent_id IS NULL` (racine), `parent_id` pointant sur racine (sous-thème), sinon feuille.

## Comptages avant / après

| Table | Après purge (avant import) | Après import | Δ |
|---|---|---|---|
| `taxonomy` | 0 | **1** | +1 |
| `vocabulary` | 0 | **1** | +1 |
| `term` | 0 | **1539** | +1539 |
| `term` racines (`parent_id IS NULL`) | 0 | 18 | +18 |
| `term` sous-thèmes (parent = racine) | 0 | 145 | +145 |
| `term` feuilles (parent = sous-thème) | 0 | 1376 | +1376 |
| `alembic_version` | 1 | 1 | 0 (préservé) |
| `job_type_config` | 14 | 14 | 0 (préservé) |

## Vérifications post-import

| Vérification | Attendu | Réel | Statut |
|---|---|---|---|
| `taxonomy` count | 1 | 1 | ✓ |
| `vocabulary` count | 1 | 1 | ✓ |
| `term` count global | 1539 | 1539 | ✓ |
| `term` racines (level 0) | 18 | 18 | ✓ |
| `term` sous-thèmes (level 1) | 145 | 145 | ✓ |
| `term` feuilles (level 2) | 1376 | 1376 | ✓ |
| FK orphelins (`parent_id` invalide) | 0 | 0 | ✓ |
| Couverture `name_ar` non vide | 1539 | 1539 (**100 %**) | ✓ |

### Sanity check sur 5 feuilles aléatoires (PostgreSQL `ORDER BY RANDOM()`)

| Feuille | `name_ar` |
|---|---|
| `train_conductor` | `سائق القطار` |
| `dentist_at_work` | `طبيب الأسنان` |
| `kitchen_strainer` | `المصفاة` |
| `server_room_with_racks` | `غرفة خوادم مع رفوف` |
| `steampunk_pocket_watch_open` | `ساعة جيب ستيمبانك مفتوحة` |

Toutes présentes et non vides. Pas de translittération phonétique douteuse type "بوديل" (le seed précédent en avait sur les chiens, fini avec cette nouvelle taxonomie).

## Points d'attention

- **0 erreur, 0 warning** sur la passe d'import. Tous les checks structurels passent.
- **Champ `seo` ignoré** : 1539 nœuds avaient un objet SEO riche (search_volume_bucket, seo_priority, seasonality, peak_months, lead_time_weeks, tags). Données utiles éditorialement, perdues à l'import car aucune colonne cible. Si on veut les exploiter en P2/P3, il faut :
  - soit ajouter une colonne `metadata` (TEXT JSON) sur `term` via une migration Alembic ;
  - soit créer une table d'extension `term_seo (term_id, payload JSON)`.
  Le fichier source `docs/xchange/coloring_taxonomy_seo.json` reste consultable pour récupérer ces données plus tard sans re-générer la taxonomie.
- **Couverture AR 100 %** vs 100 % aussi sur l'ancienne taxonomie (88 nœuds), mais sur **17.5× plus de termes** (1539 vs 88), avec une qualité lexicale visiblement supérieure (pas de translittération phonétique douteuse sur les chiens, vrais termes arabes).
- Les **fichiers PNG sur disque** dans `data/outputs/` (orphelins depuis la purge des records `image`) ne sont pas affectés par cet import. À nettoyer séparément si désiré : `rm data/outputs/*.png`.

## Décision / Action suivante

✅ Taxonomie v2 en place et validée. Pipeline opérationnel pour P2 :
- `qwen3.5:4b` peut maintenant ancrer le contenu i18n sur les 1376 feuilles disponibles.
- `suggest_children` peut étendre le périmètre si besoin sur cette base.

À adresser plus tard :
- Si les métadonnées SEO doivent être exploitées (filtrage par seasonality, priorisation par search_volume_bucket) : prévoir migration Alembic ajoutant une colonne `metadata JSON` sur `term`, puis re-run d'un script qui croise le JSON source et complète chaque term.
- L'éditeur web `/data/taxonomy_editor.html` doit pouvoir afficher 1539 termes — vérifier que la pagination/recherche tient sur ce volume avant de l'ouvrir aux utilisateurs.

## Annexes

- Source : `docs/xchange/coloring_taxonomy_seo.json` (1019 KB)
- Script (adapté du template post-purge) : `scripts/db_reload.py`
- Récap import JSON : `scripts/_reload_summary.json`
- Backup pré-purge (rollback possible) : `backups/2026-05-05_backup-pre-purge.{sql,json}`
- Rapport purge : `docs/reports/2026-05-05_purge-base-integrale.md`
