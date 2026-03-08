"""Connexion DuckDB et helpers.

Architecture : connexion unique partagée (thread-safe via DuckDB).
DuckDB gère en interne les lectures concurrentes.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Generator

import duckdb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "artiste_coloriage.duckdb"

# Connexion partagée : DuckDB supporte les connexions multiples sur le même fichier.
# On utilise un lock threading pour sérialiser les écritures concurrentes.
_db_lock = threading.Lock()
_shared_conn: duckdb.DuckDBPyConnection | None = None


def _get_shared_conn() -> duckdb.DuckDBPyConnection:
    global _shared_conn
    if _shared_conn is None:
        logger.info("Opening DuckDB connection: %s", DB_PATH)
        _shared_conn = duckdb.connect(str(DB_PATH), read_only=False)
    return _shared_conn


def get_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Dependency FastAPI : connexion DuckDB partagée avec lock."""
    with _db_lock:
        conn = _get_shared_conn()
        try:
            yield conn
        except Exception:
            # Si la connexion est corrompue, la réinitialiser
            global _shared_conn
            try:
                conn.close()
            except Exception:
                pass
            _shared_conn = None
            raise


def get_db_sync() -> duckdb.DuckDBPyConnection:
    """Connexion synchrone (hors FastAPI)."""
    return duckdb.connect(str(DB_PATH), read_only=False)


def init_db(path: Path | None = None) -> None:
    """Initialise la base avec le schéma."""
    path = path or DB_PATH
    schema_path = DATA_DIR / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")

    conn = duckdb.connect(str(path))
    schema_sql = schema_path.read_text(encoding="utf-8")
    for stmt in schema_sql.split(";"):
        stmt = stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue
        try:
            conn.execute(stmt)
        except duckdb.Error as e:
            if "already exists" not in str(e).lower():
                raise
    conn.close()
