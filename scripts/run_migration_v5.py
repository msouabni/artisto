#!/usr/bin/env python3
"""Exécute la migration v5 : suppression des index sur image (workaround bug DuckDB FK).
Usage: python scripts/run_migration_v5.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

DB_PATH = PROJECT_ROOT / "data" / "artiste_coloriage.duckdb"
MIGRATION_SQL = PROJECT_ROOT / "data" / "migration_v5_drop_image_indexes.sql"


def main() -> int:
    if not DB_PATH.exists():
        print(f"Erreur: base non trouvée: {DB_PATH}")
        return 1
    if not MIGRATION_SQL.exists():
        print(f"Erreur: migration non trouvée: {MIGRATION_SQL}")
        return 1

    conn = duckdb.connect(str(DB_PATH), read_only=False)
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    # Supprimer les lignes de commentaire pour éviter que le 1er DROP soit fusionné avec -- et ignoré
    lines = [l for l in sql.split("\n") if not l.strip().startswith("--")]
    sql_clean = "\n".join(lines)
    for stmt in sql_clean.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
            print(f"  Exécuté: {stmt[:60]}...")
        except duckdb.Error as e:
            if "does not exist" in str(e).lower():
                print(f"  Ignoré (index absent): {stmt[:50]}...")
            else:
                raise
    conn.close()
    print("Migration v5 terminée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
