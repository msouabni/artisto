# Migration — `term.metadata` JSONB
Date : 2026-05-05

## Contexte
Suite à l'import de la taxonomie v2 (`docs/reports/2026-05-05_import-taxonomie-v2.md`), le rapport notait que les 1539 nœuds source contenaient un objet `seo` riche (search_volume_bucket, seo_priority, seasonality, peak_months, lead_time_weeks, tags) **non importé** car aucune colonne cible. Demande utilisateur : ajouter `term.metadata` JSONB nullable, mapper `seo → metadata` à l'import, **rétroactivement remplir les 1376 feuilles déjà importées**.

## Modifications

### 1. Modèle ORM (`src/api/models.py`)

Ajout d'une `Mapped[dict | None]` sur la classe `Term` :

```python
# Attribut Python `node_metadata` (la colonne SQL s'appelle bien `metadata`),
# renommé pour éviter le conflit avec `Base.metadata` (réservé SQLAlchemy).
node_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
```

Type SQLAlchemy `JSON` — cross-dialect : Postgres stocke en JSON, mais la migration ci-dessous force `JSONB` côté Postgres ; SQLite (tests via `Base.metadata.create_all`) stocke en JSON natif (pas de JSONB en SQLite — tests inchangés et toujours portables).

### 2. Migration Alembic — `0005_term_metadata_jsonb`

Le template `alembic/script.py.mako` est manquant dans le repo, donc `alembic revision --autogenerate` échoue à la création du fichier. Migration **écrite à la main** en suivant le pattern des révisions 0001-0004 :

```python
revision = "0005_term_metadata_jsonb"
down_revision = "0004_seed_new_job_types"

def upgrade():
    op.add_column("term", sa.Column("metadata", postgresql.JSONB, nullable=True))

def downgrade():
    op.drop_column("term", "metadata")
```

Appliquée via `alembic upgrade head` :

```
INFO  [alembic.runtime.migration] Running upgrade 0004_seed_new_job_types -> 0005_term_metadata_jsonb, add metadata jsonb to term
```

État schéma `term` confirmé après upgrade :

```
metadata                  JSONB    (NULL)
```

### 3. `scripts/db_reload.py`

Mapping `seo → metadata` ajouté dans la fonction `_insert_node` :

```python
seo = node.get("seo")
meta_json = json.dumps(seo, ensure_ascii=False) if isinstance(seo, dict) else None
INSERT INTO term (..., metadata, ...) VALUES (..., CAST(:meta AS jsonb), ...)
```

Note : on cast explicitement `CAST(:meta AS jsonb)` pour que SQLAlchemy passe la string JSON et que Postgres la convertisse côté serveur. Le cast est nécessaire avec un placeholder paramétré (sinon Postgres voit un text et refuse).

### 4. Backfill rétroactif des 1539 lignes existantes

Au lieu de purger+réimporter, j'ai fait un `UPDATE` ciblé : walker le source JSON, faire un `UPDATE term SET metadata = CAST(:meta AS jsonb) WHERE id = :id` pour chaque nœud avec un objet `seo`.

Résultats :

| Métrique | Valeur |
|---|---|
| Nœuds source avec objet `seo` | 1376 (uniquement les feuilles ; racines et sous-thèmes n'en ont pas) |
| Nœuds sans `seo` dans le source | 163 (= 18 racines + 145 sous-thèmes) |
| `UPDATE` réussis | **1376** |
| `UPDATE` non trouvés (id manquant en DB) | 0 ✅ |
| `term` total en DB | 1539 |
| `term` avec `metadata` non NULL | **1376 / 1539** ✅ |
| `term` avec `metadata` NULL | 163 (cohérent avec source) |

### 5. Sanity check sur 1 feuille (`train_conductor`)

```json
{
  "tags": ["professions", "transport-and-logistics"],
  "peak_months": [],
  "seasonality": "evergreen",
  "seo_priority": {"ar": "secondary", "en": "secondary", "fr": "secondary"},
  "lead_time_weeks": 0,
  "search_volume_real": null,
  "search_volume_bucket": "low"
}
```

Le JSONB est correctement parsé, types préservés (objet imbriqué `seo_priority`, array `tags`, null pour `search_volume_real`).

## Points d'attention

- **`Base.metadata` réservé** : SQLAlchemy interdit l'usage du nom `metadata` comme attribut Python sur une classe ORM (conflit avec le `MetaData` du registre). Solution adoptée : attribut `node_metadata` côté Python, colonne SQL `metadata` via le 1er argument de `mapped_column`. Aucun consommateur de la base ne lit `metadata` aujourd'hui via l'ORM ; quand ce sera le cas, accéder via `term.node_metadata`.
- **Tests SQLite portables** : la migration `0005` cible Postgres uniquement (JSONB explicite). Les tests reconstruisent le schéma depuis le modèle ORM (`Base.metadata.create_all`), donc utilisent `JSON` côté SQLite. Cohérent avec la convention CLAUDE.md « `Column(JSON)` pas `JSONB` ».
- **Template Alembic manquant** : `alembic/script.py.mako` absent du repo. À créer pour rendre `alembic revision --autogenerate` fonctionnel à l'avenir. Contournement actuel : écriture manuelle des migrations en suivant le pattern `0001-0005`.
- **Si on veut requêter le JSONB** : Postgres natif supporte les opérateurs `->`, `->>`, `@>`, `#>>`, etc. Mais **CLAUDE.md interdit ces opérateurs dans la couche générique** (cassent les tests SQLite). Si on veut filtrer par `seasonality` ou `seo_priority`, faire le filtrage en Python après lecture, ou créer une fonction utilitaire dialect-aware.
- **Racines/sous-thèmes sans metadata** : c'est cohérent avec le source (le seo n'existe que sur les feuilles). Si on veut un metadata aussi sur les niveaux supérieurs, il faut soit l'agréger côté Python (somme de tags des feuilles), soit modifier le source.

## Décision / Action suivante

✅ Colonne `term.metadata` JSONB en place, alimentée à 1376/1376 feuilles avec leurs métadonnées SEO. Disponible pour la suite du pipeline (filtrage saisonnier, priorisation par search volume, etc.).

Action restante (mineure) :
- Créer `alembic/script.py.mako` quand on aura besoin de prochaines migrations autogénérées (ou continuer à écrire à la main, marche très bien sur ce projet).

## Annexes

- Migration : `alembic/versions/0005_term_metadata_jsonb.py`
- Modèle modifié : `src/api/models.py` → classe `Term`
- Script d'import (avec mapping seo→metadata) : `scripts/db_reload.py`
- Source : `docs/xchange/coloring_taxonomy_seo.json`
- Rapport import : `docs/reports/2026-05-05_import-taxonomie-v2.md`
- Rapport purge préalable : `docs/reports/2026-05-05_purge-base-integrale.md`
