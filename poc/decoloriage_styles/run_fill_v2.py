"""Runner batch lineart-fill sur les 12 PNG natifs N&B.

Pour chaque image du corpus native_batch :
  - <id>_blank.png, <id>.svg, <id>.html, <id>_demo_filled.png
Puis :
  - gallery_fill.png : 12 lignes (blank | demo remplie), labellees style+sujet
  - fill_stats.json  : stats par image
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lineart_fill import process_image  # noqa: E402

CORPUS_JSON = HERE / "native_batch" / "corpus_native.json"
SRC_DIR = HERE / "native_batch" / "corpus"
OUT_DIR = HERE / "fill_v2"


def _label_strip(text: str, width: int, height: int = 34) -> np.ndarray:
    strip = np.full((height, width, 3), 30, dtype=np.uint8)
    cv2.putText(strip, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1, cv2.LINE_AA)
    return strip


def build_gallery(items: list[dict], stats_by_id: dict[str, dict],
                  out_path: Path, thumb: int = 300) -> None:
    """12 lignes x (blank | demo filled), label a gauche."""
    rows = []
    for it in items:
        rid = it["id"]
        st = stats_by_id.get(rid)
        if st is None:
            continue
        blank = cv2.imread(st["outputs"]["blank_png"])
        demo = cv2.imread(st["outputs"]["demo_filled_png"])
        blank = cv2.resize(blank, (thumb, thumb), interpolation=cv2.INTER_AREA)
        demo = cv2.resize(demo, (thumb, thumb), interpolation=cv2.INTER_AREA)
        pair = np.hstack([blank, np.full((thumb, 4, 3), 200, np.uint8), demo])
        label = f"{it['style']}/{it['subject']}  cells={st['n_cells']}  cov={st['coverage_pct']:.0f}%"
        strip = _label_strip(label, pair.shape[1])
        rows.append(np.vstack([strip, pair]))
        rows.append(np.full((6, pair.shape[1], 3), 245, np.uint8))
    gallery = np.vstack(rows)
    # Header global
    header = _label_strip("lineart-fill  |  GAUCHE = blank (encre)   DROITE = demo (1 couleur / cellule)",
                          gallery.shape[1], height=40)
    gallery = np.vstack([header, gallery])
    cv2.imwrite(str(out_path), gallery)


def main() -> int:
    corpus = json.loads(CORPUS_JSON.read_text(encoding="utf-8"))
    items = corpus["images"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_stats = []
    stats_by_id = {}
    t0 = time.time()
    for it in items:
        rid = it["id"]
        src = SRC_DIR / f"{rid}.png"
        if not src.exists():
            print(f"[SKIP] {rid} : source absente {src}", file=sys.stderr)
            continue
        print(f"[FILL] {rid} ({it['style']}/{it['subject']}) ...", flush=True)
        st = process_image(src, OUT_DIR, rid, style=it["style"], subject=it["subject"])
        all_stats.append(st)
        stats_by_id[rid] = st
        print(f"   -> {st['n_cells']:4d} cells, {st['n_paper']} paper, "
              f"cov={st['coverage_pct']:.1f}%, median_cell={st['median_cell_px']}px, "
              f"svg={st['svg_kb']}KB, t={st['timing_s']}s")

    elapsed = round(time.time() - t0, 2)

    # Gallery
    gallery_path = OUT_DIR / "gallery_fill.png"
    build_gallery(items, stats_by_id, gallery_path)

    # Aggregats par style
    by_style: dict[str, list[dict]] = {}
    for st in all_stats:
        by_style.setdefault(st["style"], []).append(st)
    style_summary = {}
    for style, lst in by_style.items():
        cells = [s["n_cells"] for s in lst]
        cov = [s["coverage_pct"] for s in lst]
        svg = [s["svg_kb"] for s in lst]
        style_summary[style] = {
            "n_images": len(lst),
            "n_cells_median": int(np.median(cells)),
            "n_cells_min": int(min(cells)),
            "n_cells_max": int(max(cells)),
            "coverage_pct_median": round(float(np.median(cov)), 2),
            "coverage_pct_min": round(float(min(cov)), 2),
            "svg_kb_median": round(float(np.median(svg)), 1),
        }

    out = {
        "gate": "POC2-lineart-fill",
        "n_images": len(all_stats),
        "timing_s_total": elapsed,
        "global": {
            "coverage_pct_median": round(float(np.median([s["coverage_pct"] for s in all_stats])), 2),
            "coverage_pct_min": round(float(min(s["coverage_pct"] for s in all_stats)), 2),
            "n_cells_median": int(np.median([s["n_cells"] for s in all_stats])),
        },
        "by_style": style_summary,
        "gallery": str(gallery_path),
        "images": all_stats,
    }
    stats_path = OUT_DIR / "fill_stats.json"
    stats_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[OK] {len(all_stats)} images en {elapsed}s")
    print(f"     coverage median = {out['global']['coverage_pct_median']}%  "
          f"(min {out['global']['coverage_pct_min']}%)")
    print(f"     cells median = {out['global']['n_cells_median']}")
    print(f"     gallery : {gallery_path}")
    print(f"     stats   : {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
