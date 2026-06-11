"""Runner batch lineart-fill v2 (PRODUCTION) sur les 12 PNG natifs N&B.

Pour chaque image du corpus native_batch :
  - <id>_blank.png, <id>.svg, <id>.html, <id>_demo_filled.png, <id>_zoom.png
Puis :
  - gallery_fill_v3.png : 12 x (demo remplie | zoom), labellee style+sujet
  - fill_v3_stats.json  : stats par image + comparaison vs fill_v2

Sortie : poc/decoloriage_styles/fill_v3/
Reutilise lineart_fill_v2.process_image (qui importe g3 + Vectorizer + Voronoi).
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
from lineart_fill_v2 import process_image  # noqa: E402

CORPUS_JSON = HERE / "native_batch" / "corpus_native.json"
SRC_DIR = HERE / "native_batch" / "corpus"
OUT_DIR = HERE / "fill_v3"
FILL_V2_STATS = HERE / "fill_v2" / "fill_stats.json"


def _label_strip(text: str, width: int, height: int = 34) -> np.ndarray:
    strip = np.full((height, width, 3), 30, dtype=np.uint8)
    cv2.putText(strip, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1, cv2.LINE_AA)
    return strip


def build_gallery(items: list[dict], stats_by_id: dict[str, dict],
                  out_path: Path, thumb: int = 320) -> None:
    """12 lignes x (demo filled | zoom AVANT/APRES), label a gauche."""
    rows = []
    for it in items:
        rid = it["id"]
        st = stats_by_id.get(rid)
        if st is None:
            continue
        demo = cv2.imread(st["outputs"]["demo_filled_png"])
        zoom = cv2.imread(st["outputs"]["zoom_png"])
        demo = cv2.resize(demo, (thumb, thumb), interpolation=cv2.INTER_AREA)
        # zoom est ~2x large (avant|apres) -> on garde son ratio
        zr = thumb / zoom.shape[0]
        zoom = cv2.resize(zoom, (int(zoom.shape[1] * zr), thumb),
                          interpolation=cv2.INTER_AREA)
        pair = np.hstack([demo, np.full((thumb, 4, 3), 200, np.uint8), zoom])
        label = (f"{it['style']}/{it['subject']}  cells={st['n_cells']}  "
                 f"cov {st['coverage_before_pct']:.0f}%->{st['coverage_after_pct']:.0f}%  "
                 f"svg={st['svg_kb']:.0f}KB")
        strip = _label_strip(label, pair.shape[1])
        rows.append(np.vstack([strip, pair]))
        rows.append(np.full((6, pair.shape[1], 3), 245, np.uint8))
    # align rows to max width
    maxw = max(r.shape[1] for r in rows)
    rows = [r if r.shape[1] == maxw else
            np.hstack([r, np.full((r.shape[0], maxw - r.shape[1], 3), 245, np.uint8)])
            for r in rows]
    gallery = np.vstack(rows)
    header = _label_strip(
        "lineart-fill v2 (prod)  |  GAUCHE = demo remplie (1 couleur/cellule, halo supprime)   "
        "DROITE = zoom AVANT(halo+crenelage) / APRES(zero halo + encre lisse)",
        gallery.shape[1], height=40)
    gallery = np.vstack([header, gallery])
    cv2.imwrite(str(out_path), gallery)


def main() -> int:
    corpus = json.loads(CORPUS_JSON.read_text(encoding="utf-8"))
    items = corpus["images"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # fill_v2 pour comparaison
    v2_by_id = {}
    if FILL_V2_STATS.exists():
        v2 = json.loads(FILL_V2_STATS.read_text(encoding="utf-8"))
        for s in v2.get("images", []):
            v2_by_id[s["id"]] = s

    all_stats = []
    stats_by_id = {}
    t0 = time.time()
    for it in items:
        rid = it["id"]
        src = SRC_DIR / f"{rid}.png"
        if not src.exists():
            print(f"[SKIP] {rid} : source absente {src}", file=sys.stderr)
            continue
        print(f"[FILL v2] {rid} ({it['style']}/{it['subject']}) ...", flush=True)
        st = process_image(src, OUT_DIR, rid, style=it["style"], subject=it["subject"])

        # comparaison vs fill_v2
        v2s = v2_by_id.get(rid)
        if v2s is not None:
            st["vs_fill_v2"] = {
                "v2_coverage_pct_vs_white": v2s.get("coverage_pct"),
                "v2_svg_kb": v2s.get("svg_kb"),
                "v2_ink_layer": "raster_base64",
                "v3_ink_layer": "vector_vtracer",
                "v3_coverage_pct_vs_canvas": st["coverage_after_pct"],
                "svg_kb_delta": round(st["svg_kb"] - v2s.get("svg_kb", 0.0), 1),
            }
        all_stats.append(st)
        stats_by_id[rid] = st
        print(f"   -> {st['n_cells']:4d} cells, {st['n_paper']} paper, "
              f"cov {st['coverage_before_pct']:.1f}%->{st['coverage_after_pct']:.1f}%, "
              f"ink_paths={st['n_ink_paths']}, svg={st['svg_kb']}KB "
              f"(dont encre vec {st['ink_svg_kb']}KB), t={st['timing_s']}s")

    elapsed = round(time.time() - t0, 2)

    gallery_path = OUT_DIR / "gallery_fill_v3.png"
    build_gallery(items, stats_by_id, gallery_path)

    by_style: dict[str, list[dict]] = {}
    for st in all_stats:
        by_style.setdefault(st["style"], []).append(st)
    style_summary = {}
    for style, lst in by_style.items():
        cov_a = [s["coverage_after_pct"] for s in lst]
        cov_b = [s["coverage_before_pct"] for s in lst]
        svg = [s["svg_kb"] for s in lst]
        style_summary[style] = {
            "n_images": len(lst),
            "coverage_before_pct_median": round(float(np.median(cov_b)), 2),
            "coverage_after_pct_median": round(float(np.median(cov_a)), 2),
            "coverage_after_pct_min": round(float(min(cov_a)), 2),
            "svg_kb_median": round(float(np.median(svg)), 1),
        }

    out = {
        "gate": "POC2-lineart-fill-v2-production",
        "module": "lineart_fill_v2.py",
        "fixes": {
            "fix1_halo": "expansion Voronoi (distance_transform_edt return_indices) "
                         "des cellules sous le trait -> couverture canvas ~100%",
            "fix2_smooth": "encre vectorisee via src/services/vectorizer.Vectorizer "
                           "(VTracer bw_default spline) au lieu de raster base64",
        },
        "n_images": len(all_stats),
        "timing_s_total": elapsed,
        "global": {
            "coverage_before_pct_median": round(
                float(np.median([s["coverage_before_pct"] for s in all_stats])), 2),
            "coverage_after_pct_median": round(
                float(np.median([s["coverage_after_pct"] for s in all_stats])), 2),
            "coverage_after_pct_min": round(
                float(min(s["coverage_after_pct"] for s in all_stats)), 2),
            "n_cells_median": int(np.median([s["n_cells"] for s in all_stats])),
            "svg_kb_median": round(
                float(np.median([s["svg_kb"] for s in all_stats])), 1),
        },
        "note_metrique": (
            "fill_v2 mesurait coverage_pct vs surface BLANCHE (le halo etait "
            "exclu du denominateur -> ~99.5% trompeur). v3 mesure vs CANVAS "
            "complet (H*W) : coverage_before = ancien comportement v1 reel (halo "
            "non assigne), coverage_after = apres expansion Voronoi (~100%)."
        ),
        "by_style": style_summary,
        "gallery": str(gallery_path),
        "images": all_stats,
    }
    stats_path = OUT_DIR / "fill_v3_stats.json"
    stats_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[OK] {len(all_stats)} images en {elapsed}s")
    print(f"     coverage AVANT median = {out['global']['coverage_before_pct_median']}%  "
          f"-> APRES median = {out['global']['coverage_after_pct_median']}% "
          f"(min {out['global']['coverage_after_pct_min']}%)")
    print(f"     svg median = {out['global']['svg_kb_median']}KB")
    print(f"     gallery : {gallery_path}")
    print(f"     stats   : {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
