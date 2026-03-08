# Scripts Artiste Coloriage

## Base DuckDB

### Initialiser la base

```bash
python scripts/init_db.py
```

Crée `data/artiste_coloriage.duckdb` avec le schéma complet.

### Importer la taxonomie JSON

```bash
python scripts/import_taxonomy_json_to_db.py [chemin_json] [chemin_db]
```

Par défaut : `data/taxonomy_universal_v0.json` → `data/artiste_coloriage.duckdb`.

## API FastAPI

```bash
cd src && python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

- Éditeur taxonomie : http://127.0.0.1:8000/data/taxonomy_editor.html
- API docs : http://127.0.0.1:8000/docs

En cas de 500 : voir le corps de la réponse (DevTools → Network → Response) ou les logs du terminal serveur ; détail dans `tests/README.md`.
