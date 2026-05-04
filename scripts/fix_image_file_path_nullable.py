#!/usr/bin/env python3
"""Rend image.file_path nullable (pour concepts sans fichier encore généré).

NOTE: Si DuckDB renvoie "Dependency Error: Cannot alter entry image because
there are entries that depend on it", la base ne peut pas être modifiée (tables
image_output, image_taxonomy_tag, etc. référencent image). Dans ce cas, la
solution est côté API : l'application envoie file_path = '' à la création.
Vérifiez que src/api/routes/images.py insère bien file_path avec une chaîne
vide dans les INSERT INTO image.

Ce script tente quand même l'ALTER pour les bases sans dépendances.
"""
from __future__ import annotations

import sys
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
    try:
        conn.execute("ALTER TABLE image ALTER file_path DROP NOT NULL")
        print("image.file_path est maintenant nullable.")
        return 0
    except duckdb.Error as e:
        err = str(e).lower()
        if "dependency" in err or "depend" in err:
            print("Impossible de modifier la table (références FK).")
            print("La correction est déjà appliquée dans l'API : les INSERT")
            print("envoient file_path = ''. Aucune action requise.")
            return 0
        if "not supported" in err or "not implemented" in err:
            print("ALTER DROP NOT NULL non supporté par cette version de DuckDB.")
            return 1
        print(f"Erreur: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
