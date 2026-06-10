#!/usr/bin/env python3
"""Worker qui consomme les jobs image_post_processing (status=pending).

Applique le post-traitement (extract_palette + vectorizer) sur les
``image_output`` fraichement generes par ``image_generation``.

Usage: python scripts/run_image_post_processing_worker.py [--once]
  --once : traite un seul job puis quitte (sinon boucle infinie).

Connexion : utilise DATABASE_URL (PostgreSQL).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from artiste_logging import setup_logging

setup_logging("image_post_processing_worker")

from workers.image_post_processing_worker import ImagePostProcessingWorker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Traiter un seul job puis quitter",
    )
    args = parser.parse_args()

    worker = ImagePostProcessingWorker(db_path=None)
    worker.run_loop(once=args.once, poll_interval=2.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
