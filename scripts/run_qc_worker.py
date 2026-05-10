#!/usr/bin/env python3
"""Worker qui consomme les jobs image_qc_auto (status=pending).

Calcule 5 tags déterministes (Pillow + NumPy, no LLM) sur les images
générées par le worker image_generation et les pose sur ``image_output.qc_tags``.

Trigger automatique : le worker image enqueue un job image_qc_auto en fin de
``save_result``. Ce script consomme ces jobs.

Usage : ``python scripts/run_qc_worker.py [--once]``

Brief : ``docs/architect/briefs/2026-05-10_brief-qc-auto-worker.md``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from artiste_logging import setup_logging

setup_logging("qc_worker")

from workers.qc_worker import QCWorker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once", action="store_true", help="Traiter un seul job puis quitter"
    )
    args = parser.parse_args()

    worker = QCWorker(db_path=None)
    worker.run_loop(once=args.once, poll_interval=2.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
