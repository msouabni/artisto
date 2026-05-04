#!/usr/bin/env python3
"""Exécute la migration v7 Job Queue.
Usage: python scripts/run_migration_v7.py [--db-path PATH]
Arrêtez uvicorn avant d'exécuter (DuckDB verrouille le fichier).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb


def get_existing_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    """Retourne les noms des colonnes existantes."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()
    return {r[0] for r in rows} if rows else set()


def get_existing_tables(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """Retourne les noms des tables existantes."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {r[0] for r in rows} if rows else set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "artiste_coloriage.duckdb",
        help="Chemin vers la base DuckDB",
    )
    args = parser.parse_args()  # noqa: F841

    db_path = args.db_path
    if not db_path.exists():
        print(f"Erreur: base non trouvée: {db_path}")
        return 1

    conn = duckdb.connect(str(db_path), read_only=False)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    job_cols = get_existing_columns(conn, "job")

    new_columns = [
        ("priority", "INTEGER DEFAULT 5"),
        ("retry_count", "INTEGER DEFAULT 0"),
        ("max_retries", "INTEGER DEFAULT 3"),
        ("scheduled_at", "TEXT"),
        ("entity_type", "TEXT"),
        ("entity_id", "TEXT"),
        ("result", "TEXT"),
        ("external_ref_id", "TEXT"),
        ("progress", "INTEGER DEFAULT 0"),
        ("progress_message", "TEXT"),
        ("worker_id", "TEXT"),
        ("last_heartbeat_at", "TEXT"),
    ]

    for col_name, col_def in new_columns:
        if col_name not in job_cols:
            conn.execute(f"ALTER TABLE job ADD COLUMN {col_name} {col_def}")
            print(f"  job.{col_name} ajouté.")
        else:
            print(f"  job.{col_name} existe déjà.")

    # Migration données : entity_type + entity_id depuis image_id
    conn.execute("""
        UPDATE job SET entity_type = 'image', entity_id = image_id
        WHERE image_id IS NOT NULL AND (entity_type IS NULL OR entity_id IS NULL)
    """)
    print("  Migration entity_type/entity_id effectuée.")

    # Table job_type_config
    tables = get_existing_tables(conn)
    if "job_type_config" not in tables:
        conn.execute("""
            CREATE TABLE job_type_config (
                type TEXT PRIMARY KEY,
                label TEXT,
                enabled INTEGER DEFAULT 0,
                max_concurrent INTEGER DEFAULT 1,
                description TEXT,
                category TEXT,
                updated_at TEXT
            )
        """)
        print("  Table job_type_config créée.")

        conn.execute(
            """
            INSERT INTO job_type_config (type, label, enabled, max_concurrent, description, category, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ["image_generation", "Génération image (ComfyUI)", 0, 1, "Génération d'images via diffusion", "image", now],
        )
        conn.execute(
            """
            INSERT INTO job_type_config (type, label, enabled, max_concurrent, description, category, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ["text_enrichment", "Enrichissement texte (Ollama)", 0, 1, "Enrichissement taxonomies, images, etc.", "text", now],
        )
        print("  job_type_config : seed image_generation, text_enrichment.")
    else:
        print("  Table job_type_config existe déjà.")

    conn.close()
    print("Migration v7 terminée avec succès.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
