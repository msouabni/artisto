#!/usr/bin/env python3
"""Liste tous les index de la base DuckDB."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

DB_PATH = PROJECT_ROOT / "data" / "artiste_coloriage.duckdb"
conn = duckdb.connect(str(DB_PATH), read_only=True)
try:
    rows = conn.execute("SELECT * FROM duckdb_indexes()").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM duckdb_indexes()").description]
    print("Colonnes:", cols)
    for r in rows:
        print(r)
finally:
    conn.close()
