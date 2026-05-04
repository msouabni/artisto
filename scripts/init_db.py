#!/usr/bin/env python3
"""Initialise le schéma PostgreSQL via SQLAlchemy ORM."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def init_db(db_path: Path | None = None) -> None:
    _ = db_path
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from api.db import init_db as init_db_runtime

    init_db_runtime()
    print("Schema PostgreSQL initialisé.")


if __name__ == "__main__":
    init_db(None)
