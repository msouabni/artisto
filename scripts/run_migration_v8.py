#!/usr/bin/env python3
"""Exécute la migration v8 batch_ref.
Usage: python scripts/run_migration_v8.py [--db-path PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb


def get_existing_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()
    return {r[0] for r in rows} if rows else set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=PROJECT_ROOT / "data" / "artiste_coloriage.duckdb")
    args = parser.parse_args()

    if not args.db_path.exists():
        print(f"Erreur: base non trouvée: {args.db_path}")
        return 1

    conn = duckdb.connect(str(args.db_path), read_only=False)
    job_cols = get_existing_columns(conn, "job")

    if "batch_ref" not in job_cols:
        conn.execute("ALTER TABLE job ADD COLUMN batch_ref TEXT")
        print("  job.batch_ref ajouté.")
    else:
        print("  job.batch_ref existe déjà.")

    conn.close()
    print("Migration v8 terminée avec succès.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
