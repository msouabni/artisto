#!/usr/bin/env python3
"""
Initialise la base DuckDB avec le schéma complet.
Usage: python scripts/init_db.py [chemin_db]
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "artiste_coloriage.duckdb"
SCHEMA_PATH = DATA_DIR / "schema.sql"


def init_db(db_path: Path | None = None) -> None:
    db_path = db_path or DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema not found: {SCHEMA_PATH}")

    import duckdb

    conn = duckdb.connect(str(db_path))
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # Exécuter le schéma (DuckDB n'exécute qu'une seule instruction par execute)
    for stmt in schema_sql.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        stmt = "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--"))
        if not stmt.strip():
            continue
        try:
            conn.execute(stmt)
        except Exception as e:
            # Ignorer les erreurs "already exists" pour CREATE TABLE/INDEX
            if "already exists" not in str(e).lower():
                raise RuntimeError(f"Schema error: {stmt[:80]}...") from e

    conn.close()
    print(f"Base initialisée: {db_path}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    init_db(path)
