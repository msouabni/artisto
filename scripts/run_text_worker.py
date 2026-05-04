#!/usr/bin/env python3
"""Worker qui consomme les jobs text_enrichment (status=pending).

Usage: python scripts/run_text_worker.py [--once]
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

setup_logging("text_worker")

from workers.ai_pipeline_worker import AiPipelineWorker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Traiter un seul job puis quitter")
    args = parser.parse_args()

    worker = AiPipelineWorker(db_path=None)
    worker.run_loop(once=args.once, poll_interval=2.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
