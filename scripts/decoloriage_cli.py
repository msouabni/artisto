"""CLI minimal : décoloriage d'un PNG colorié pastel → SVG bicouche click-to-fill.

Phase 1 (spike) du plan de migration décoloriage prod.
Source du cœur métier : ``src/services/decoloriage.py`` (porté du POC
`decoloriage-validation`, scripts g1a→g5).

Usage :

    python scripts/decoloriage_cli.py run <png_path> --out <svg_path> --level enfant

Niveau ``enfant`` uniquement en v1 (D5). Le PNG d'entrée est arbitraire
(sortie ERNIE pastel, dossier externe, etc.). Aucun chemin par défaut.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows : la console cp1252 ne sait pas encoder les accents/ΔE. Forcer UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from services.decoloriage import decolorize  # noqa: E402


def cmd_run(args: argparse.Namespace) -> int:
    png_path = Path(args.png).resolve()
    out_path = Path(args.out).resolve()

    if not png_path.exists():
        print(f"[ERR] PNG introuvable : {png_path}", file=sys.stderr)
        return 1

    print(f"[décoloriage] {png_path.name} (niveau {args.level}) ...", flush=True)
    result = decolorize(png_path, level=args.level)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.svg, encoding="utf-8")

    # Distribution crayons lisible
    distr = ", ".join(
        f"{hex_str}:{cnt}" for hex_str, cnt in sorted(
            result.crayon_distribution.items(), key=lambda x: -x[1]
        ) if cnt > 0
    )

    print(f"  SVG          : {out_path}")
    print(f"  image        : {result.image_size[0]}x{result.image_size[1]}")
    print(f"  cliquables   : {result.n_clickable}")
    print(f"  régions-encre: {result.n_ink_regions}")
    print(f"  arcs         : {result.n_arcs} ({result.n_ink_arcs} encre / "
          f"{result.n_shading_arcs} shading)")
    print(f"  stroke       : encre {result.ink_stroke_width}px / "
          f"shading {result.shading_stroke_width}px")
    print(f"  deltaE median: {result.delta_e_median}")
    print(f"  publishable_tp: {result.publishable_tp}")
    print(f"  distribution : {distr}")
    if result.hollow_tube_candidates:
        print(f"  hollow-tube  : {len(result.hollow_tube_candidates)} candidat(s) "
              f"(revue humaine)")
    print(f"  temps        : {result.timing_s}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Décoloriage PNG colorié → SVG bicouche click-to-fill."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Décolorie un PNG en SVG bicouche.")
    p_run.add_argument("png", type=str, help="Chemin du PNG colorié (pastel).")
    p_run.add_argument("--out", type=str, required=True, help="Chemin du SVG de sortie.")
    p_run.add_argument("--level", type=str, default="enfant", choices=["enfant"],
                       help="Niveau de partition (v1 : enfant uniquement).")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
