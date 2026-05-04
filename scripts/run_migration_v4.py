#!/usr/bin/env python3
"""Exécute la migration v4 : current_job_id sur image.
Usage: python scripts/run_migration_v4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

DB_PATH = PROJECT_ROOT / "data" / "artiste_coloriage.duckdb"


def get_existing_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()
    return {r[0] for r in rows} if rows else set()


def main() -> int:
    if not DB_PATH.exists():
        print(f"Erreur: base non trouvée: {DB_PATH}")
        return 1

    conn = duckdb.connect(str(DB_PATH), read_only=False)
    img_cols = get_existing_columns(conn, "image")

    if "current_job_id" not in img_cols:
        conn.execute("ALTER TABLE image ADD COLUMN current_job_id TEXT")
        print("  image.current_job_id ajouté.")
    else:
        print("  image.current_job_id existe déjà.")

    conn.close()
    print("Migration v4 terminée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
