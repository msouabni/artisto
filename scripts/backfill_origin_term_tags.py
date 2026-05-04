#!/usr/bin/env python3
"""Backfill : pour chaque image avec origin_term_id non null, insère le tag
image_taxonomy_tag manquant. Idempotent — peut être exécuté plusieurs fois.

Usage:
    python scripts/backfill_origin_term_tags.py

Arrêtez uvicorn avant d'exécuter (DuckDB verrouille le fichier).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

DB_PATH = PROJECT_ROOT / "data" / "artiste_coloriage.duckdb"


def main() -> int:
    if not DB_PATH.exists():
        print(f"Erreur: base non trouvée: {DB_PATH}")
        return 1

    conn = duckdb.connect(str(DB_PATH), read_only=False)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = conn.execute(
        """
        SELECT id, origin_term_id, origin_taxonomy_id
        FROM image
        WHERE origin_term_id IS NOT NULL
          AND origin_taxonomy_id IS NOT NULL
          AND origin_term_id != ''
          AND origin_taxonomy_id != ''
        """
    ).fetchall()

    examined = 0
    inserted = 0
    already_present = 0

    for image_id, term_id, taxonomy_id in rows:
        examined += 1
        existing = conn.execute(
            "SELECT 1 FROM image_taxonomy_tag WHERE image_id=? AND taxonomy_id=? AND term_id=?",
            [image_id, taxonomy_id, term_id],
        ).fetchone()
        if existing:
            already_present += 1
        else:
            conn.execute(
                "INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at) VALUES (?, ?, ?, ?)",
                [image_id, taxonomy_id, term_id, now],
            )
            inserted += 1

    conn.close()
    print(f"Backfill terminé — examined={examined}, inserted={inserted}, already_present={already_present}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
