#!/usr/bin/env python3
"""Active le type image_generation dans job_type_config (PostgreSQL)."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from api.db import get_db_sync

conn = get_db_sync()
try:
    conn.execute("UPDATE job_type_config SET enabled = ? WHERE type = ?", [True, "image_generation"])
    conn.session.commit()
    print("image_generation enabled")
finally:
    conn.close()
