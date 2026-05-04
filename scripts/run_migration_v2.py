#!/usr/bin/env python3
"""Exécute la migration v2 Image Concept Pipeline.
Usage: python scripts/run_migration_v2.py
Arrêtez uvicorn avant d'exécuter (DuckDB verrouille le fichier).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ajouter le projet au path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

DB_PATH = PROJECT_ROOT / "data" / "artiste_coloriage.duckdb"


def get_existing_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    """Retourne les noms des colonnes existantes."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()
    return {r[0] for r in rows} if rows else set()


def _recreate_image_table_file_path_nullable(conn: duckdb.DuckDBPyConnection) -> None:
    """Workaround si ALTER DROP NOT NULL non supporté : colonne temporaire puis swap."""
    print("  Workaround: colonne temporaire pour file_path nullable...")
    conn.execute("ALTER TABLE image ADD COLUMN file_path_tmp TEXT")
    conn.execute("UPDATE image SET file_path_tmp = file_path")
    conn.execute("ALTER TABLE image DROP COLUMN file_path")
    conn.execute("ALTER TABLE image RENAME COLUMN file_path_tmp TO file_path")
    print("  image.file_path rendu nullable (workaround).")


def main() -> int:
    if not DB_PATH.exists():
        print(f"Erreur: base non trouvée: {DB_PATH}")
        return 1

    conn = duckdb.connect(str(DB_PATH), read_only=False)
    existing = get_existing_columns(conn, "image")
    cols_to_add = [
        ("title", "TEXT"),
        ("prompt", "TEXT"),
        ("selected_output_id", "TEXT"),
        ("origin_type", "TEXT DEFAULT 'manual'"),
        ("origin_batch_id", "TEXT"),
        ("origin_term_id", "TEXT"),
        ("origin_taxonomy_id", "TEXT"),
    ]

    for col_name, col_def in cols_to_add:
        if col_name in existing:
            print(f"  Colonne {col_name} existe déjà, ignorée.")
            continue
        sql = f"ALTER TABLE image ADD COLUMN {col_name} {col_def}"
        print(f"  {sql}")
        conn.execute(sql)
        existing.add(col_name)

    # Créer image_output si absent
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'image_output'"
    ).fetchall()
    if not tables:
        conn.execute("""
            CREATE TABLE image_output (
              id TEXT PRIMARY KEY,
              image_id TEXT NOT NULL REFERENCES image(id),
              job_id TEXT REFERENCES job(id),
              file_path TEXT NOT NULL,
              file_format TEXT,
              width INTEGER,
              height INTEGER,
              quality_score REAL,
              model_name TEXT,
              model_config TEXT,
              created_at TEXT
            )
        """)
        conn.execute("CREATE INDEX idx_image_output_image ON image_output(image_id)")
        conn.execute("CREATE INDEX idx_image_output_job ON image_output(job_id)")
        print("  Table image_output créée.")
    else:
        print("  Table image_output existe déjà.")

    # Migrer les images existantes vers image_output
    try:
        conn.execute("""
            INSERT INTO image_output (
              id, image_id, job_id, file_path, file_format,
              width, height, quality_score, model_name, created_at
            )
            SELECT
              'out_' || id, id, job_id, file_path, file_format,
              width, height, quality_score, model_name,
              COALESCE(created_at, strftime(cast(now() AS TIMESTAMP), '%Y-%m-%dT%H:%M:%SZ'))
            FROM image
            WHERE file_path IS NOT NULL AND file_path != ''
              AND NOT EXISTS (SELECT 1 FROM image_output WHERE image_output.id = 'out_' || image.id)
        """)
        print("  Images migrées vers image_output.")
    except duckdb.Error as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            print(f"  Note migration outputs: {e}")

    # Mettre à jour les colonnes concept
    conn.execute("""
        UPDATE image SET
          selected_output_id = CASE
            WHEN file_path IS NOT NULL AND file_path != ''
            THEN 'out_' || id ELSE NULL END,
          title = CASE WHEN title IS NULL OR title = ''
            THEN COALESCE(NULLIF(TRIM(prompt_used), ''), id) ELSE title END,
          prompt = CASE WHEN prompt IS NULL OR prompt = ''
            THEN prompt_used ELSE prompt END,
          status = CASE status
            WHEN 'raw' THEN 'generated'
            WHEN 'reviewed' THEN 'generated'
            WHEN 'approved' THEN 'approved'
            WHEN 'rejected' THEN 'rejected'
            ELSE COALESCE(status, 'draft') END,
          origin_type = COALESCE(origin_type, 'manual')
    """)
    print("  Colonnes concept mises à jour.")

    # Rendre image.file_path nullable si possible (sinon l'API envoie file_path='')
    try:
        conn.execute("ALTER TABLE image ALTER file_path DROP NOT NULL")
        print("  image.file_path rendu nullable.")
    except duckdb.Error as e:
        err = str(e).lower()
        if "dependency" in err or "depend" in err:
            print("  image.file_path non modifiable (FK). L'API envoie file_path='' à la création.")
        elif "not supported" in err or "not implemented" in err:
            try:
                _recreate_image_table_file_path_nullable(conn)
            except duckdb.Error:
                print("  image.file_path inchangé. L'API envoie file_path='' à la création.")
        else:
            raise

    conn.close()
    print("Migration v2 terminée avec succès.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
