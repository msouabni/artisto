"""Backup complet de la base PostgreSQL avant purge.

Produit deux fichiers :
1. backups/2026-05-05_backup-pre-purge.sql — pg_dump complet (restauration via psql)
2. backups/2026-05-05_backup-pre-purge.json — export JSON des tables non vides
   (inspection humaine, ensure_ascii=False)

pg_dump est exécuté via `docker exec artiste-postgres pg_dump …` car le binaire
n'est pas dans le PATH local.

Usage :
    python scripts/db_backup.py
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import inspect, text  # noqa: E402

from api.db import ENGINE  # noqa: E402

DATE_TAG = "2026-05-05"
BACKUP_DIR = PROJECT_ROOT / "backups"
SQL_PATH = BACKUP_DIR / f"{DATE_TAG}_backup-pre-purge.sql"
JSON_PATH = BACKUP_DIR / f"{DATE_TAG}_backup-pre-purge.json"

DB_NAME = "artiste_coloriage"
DB_USER = "artiste"
CONTAINER = "artiste-postgres"


def pg_dump_via_docker() -> dict:
    """pg_dump complet via docker exec ; écrit le SQL dans SQL_PATH."""
    cmd = [
        "docker", "exec", CONTAINER,
        "pg_dump", "-U", DB_USER, "-d", DB_NAME,
        "--clean", "--if-exists", "--no-owner", "--no-privileges",
    ]
    print(f"  Running: {' '.join(cmd)}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(cmd, capture_output=True, text=False)
    if res.returncode != 0:
        return {"ok": False, "returncode": res.returncode, "stderr": res.stderr.decode("utf-8", errors="replace")[:500]}
    SQL_PATH.write_bytes(res.stdout)
    return {
        "ok": True,
        "path": str(SQL_PATH.relative_to(PROJECT_ROOT)),
        "size_bytes": SQL_PATH.stat().st_size,
        "size_kb": round(SQL_PATH.stat().st_size / 1024, 1),
    }


def export_json() -> dict:
    """Export JSON de toutes les tables non vides."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    insp = inspect(ENGINE)
    all_tables = sorted(insp.get_table_names())

    export: dict[str, list] = {}
    counts: dict[str, int] = {}
    with ENGINE.connect() as conn:
        for t in all_tables:
            res = conn.execute(text(f'SELECT * FROM "{t}"'))
            rows = res.fetchall()
            counts[t] = len(rows)
            if not rows:
                continue
            cols = list(res.keys())
            data = []
            for row in rows:
                row_dict = {}
                for k, v in zip(cols, row):
                    # Convertir types non-JSON-serializable
                    if hasattr(v, "isoformat"):
                        row_dict[k] = v.isoformat()
                    elif isinstance(v, (bytes, bytearray)):
                        row_dict[k] = v.decode("utf-8", errors="replace")
                    else:
                        row_dict[k] = v
                data.append(row_dict)
            export[t] = data
            print(f"  {t:<35} {len(rows)} rows")

    payload = {
        "backup_date": DATE_TAG,
        "database": DB_NAME,
        "table_counts": counts,
        "tables": export,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "path": str(JSON_PATH.relative_to(PROJECT_ROOT)),
        "size_bytes": JSON_PATH.stat().st_size,
        "size_kb": round(JSON_PATH.stat().st_size / 1024, 1),
        "non_empty_tables": sum(1 for v in counts.values() if v > 0),
        "total_rows": sum(counts.values()),
    }


def main() -> int:
    print("=" * 80)
    print("BACKUP pré-purge — pg_dump SQL + export JSON")
    print("=" * 80)

    print("\n[1] pg_dump SQL via docker exec")
    sql_info = pg_dump_via_docker()
    if not sql_info["ok"]:
        print(f"  ❌ pg_dump FAILED (rc={sql_info['returncode']})")
        print(f"     stderr: {sql_info['stderr']}")
        return 2
    print(f"  ✓ {sql_info['path']}  ({sql_info['size_kb']} KB)")

    print("\n[2] Export JSON tables non vides")
    json_info = export_json()
    print(f"\n  ✓ {json_info['path']}  ({json_info['size_kb']} KB)")
    print(f"    {json_info['non_empty_tables']} tables non vides, {json_info['total_rows']} lignes")

    print("\nBackup complet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
