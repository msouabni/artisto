#!/usr/bin/env python3
"""Exécute la migration v3 Image/Job refonte.
Usage: python scripts/run_migration_v3.py
Arrêtez uvicorn avant d'exécuter (DuckDB verrouille le fichier).
"""
from __future__ import annotations

import sys
from pathlib import Path

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


def main() -> int:
    if not DB_PATH.exists():
        print(f"Erreur: base non trouvée: {DB_PATH}")
        return 1

    conn = duckdb.connect(str(DB_PATH), read_only=False)

    # 1. job : ajouter image_id (DuckDB ne supporte pas ADD COLUMN avec REFERENCES)
    job_cols = get_existing_columns(conn, "job")
    if "image_id" not in job_cols:
        conn.execute("ALTER TABLE job ADD COLUMN image_id TEXT")
        print("  job.image_id ajouté.")
    else:
        print("  job.image_id existe déjà.")

    # 2. Index idx_job_image
    try:
        conn.execute("CREATE INDEX idx_job_image ON job(image_id)")
        print("  Index idx_job_image créé.")
    except duckdb.Error as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            print("  Index idx_job_image existe déjà.")
        else:
            raise

    # 3. image_output : ajouter text_content
    io_cols = get_existing_columns(conn, "image_output")
    if "text_content" not in io_cols:
        conn.execute("ALTER TABLE image_output ADD COLUMN text_content TEXT")
        print("  image_output.text_content ajouté.")
    else:
        print("  image_output.text_content existe déjà.")

    # 4. file_path reste NOT NULL (DuckDB bloque ALTER à cause des contraintes).
    # Pour outputs texte-only, utiliser file_path='' et text_content rempli.
    # Nettoyer file_path_tmp si présent (résidu d'une migration partielle)
    if "file_path_tmp" in get_existing_columns(conn, "image_output"):
        try:
            conn.execute("ALTER TABLE image_output DROP COLUMN file_path_tmp")
            print("  image_output.file_path_tmp supprimé (nettoyage).")
        except duckdb.Error:
            print("  image_output.file_path_tmp non supprimable (ignoré).")

    # 5. Migration données : job.image_id depuis image_output (pour image_generation)
    try:
        conn.execute("""
            UPDATE job SET image_id = (
                SELECT io.image_id FROM image_output io
                WHERE io.job_id = job.id
                LIMIT 1
            )
            WHERE job.image_id IS NULL
              AND job.type = 'image_generation'
              AND EXISTS (SELECT 1 FROM image_output io WHERE io.job_id = job.id)
        """)
        print("  job.image_id peuplé depuis image_output.")
    except duckdb.Error as e:
        print(f"  Note migration job.image_id (image_output): {e}")

    # 6. Pour les jobs image_generation sans output, prendre image_id depuis image.job_id
    try:
        conn.execute("""
            UPDATE job SET image_id = (
                SELECT i.id FROM image i WHERE i.job_id = job.id LIMIT 1
            )
            WHERE job.image_id IS NULL
              AND job.type = 'image_generation'
              AND EXISTS (SELECT 1 FROM image i WHERE i.job_id = job.id)
        """)
        print("  job.image_id peuplé depuis image.job_id (legacy).")
    except duckdb.Error as e:
        print(f"  Note migration job.image_id (legacy): {e}")

    # 7. image.job_id : DuckDB ne permet pas DROP COLUMN avec FK. On garde la colonne
    #    (dépréciée) ; la relation principale est désormais job.image_id.
    img_cols = get_existing_columns(conn, "image")
    if "job_id" in img_cols:
        print("  image.job_id conservé (DuckDB bloque DROP avec FK). Déprécié : utiliser job.image_id.")

    conn.close()
    print("Migration v3 terminée avec succès.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
