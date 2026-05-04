#!/usr/bin/env python3
"""
Bootstrap complet : init DB + import taxonomie + seed données démo.

Usage:
  python scripts/bootstrap_demo.py [--reset]
  python scripts/bootstrap_demo.py --reset   # reset seed uniquement (conserve taxonomie)
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_JSON = DATA_DIR / "taxonomy_universal_v0.json"


def main() -> None:
    reset = "--reset" in sys.argv
    sys.path.insert(0, str(PROJECT_ROOT))

    if not reset:
        print("1/3 Initialisation du schéma…")
        from scripts.init_db import init_db
        init_db(None)

        print("2/3 Import de la taxonomie…")
        from scripts.import_taxonomy_json_to_db import import_json
        import_json(DEFAULT_JSON, None)
    else:
        print("Mode --reset : skip init et import (conserve taxonomie)")

    print("3/3 Seed des données démo…")
    from scripts.seed_data import seed
    seed(Path("unused"), reset=reset)

    print("\nBootstrap termine. Demarrez l'API puis ouvrez :")
    print("   http://127.0.0.1:8000/data/images_editor.html")
    print("   http://127.0.0.1:8000/data/admin.html")


if __name__ == "__main__":
    main()
