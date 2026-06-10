"""G3 - Vectorisation du label_map enfant comme une carte.

Pipeline par image :
  1. Load enfant region_map (.npy) + per-region hex depuis stats.json
  2. Per region : find_contours -> approximate_polygon (Douglas-Peucker)
                  -> chaikin smooth fermee
  3. Build SVG : un <path> par contour avec fill = hex region et stroke noir
     epais (pivot anti-sliver pre-autorise). Tri par aire decroissante pour
     que les details (petite aire) restent au-dessus.
  4. Rasterize les polygones (cv2.fillPoly + polylines stroke) -> coverage mask
  5. Diff : red la ou rien n'est couvert vs masque attendu (= tout sauf 0).
  6. Detecte les jonctions triples (corners ou >= 3 labels coexistent).

Livrables :
  - g3_out/<slot>_<id>_enfant.svg
  - g3_out/<slot>_<id>_svg_render.png (rasterisation des polygones)
  - g3_out/<slot>_<id>_diff.png (rouge sur pixels non couverts)
  - g3_out/<slot>_<id>_junctions_overlay.png (jonctions en cyan sur SVG)
  - g3_out/stats.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from skimage.measure import approximate_polygon, find_contours


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_G2_STATS = Path(__file__).parent / "g2_out" / "stats.json"
DEFAULT_OUT_DIR = Path(__file__).parent / "g3_out"

DP_TOLERANCE = 1.0       # px (Douglas-Peucker)
CHAIKIN_ITERS = 2        # 2 iter = courbes lisses sans trop de points
STROKE_COLOR = (20, 20, 25)  # noir doux RGB
STROKE_WIDTH = 2         # px (pivot anti-sliver)


# ----------------------------------------------------------------------------
# Helpers : DP + Chaikin
# ----------------------------------------------------------------------------
def chaikin_closed(points: np.ndarray, iterations: int = 1) -> np.ndarray:
    """Chaikin corner-cutting pour polyligne FERMEE.
    points : (N, 2) array.
    Retourne (~2^iter * N, 2) array."""
    if len(points) < 3:
        return points
    pts = np.asarray(points, dtype=np.float64)
    # Strip closing duplicate if present
    if len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    for _ in range(iterations):
        n = len(pts)
        if n < 3:
            break
        next_pts = np.roll(pts, -1, axis=0)
        q = 0.75 * pts + 0.25 * next_pts
        r = 0.25 * pts + 0.75 * next_pts
        new = np.empty((2 * n, 2), dtype=np.float64)
        new[0::2] = q
        new[1::2] = r
        pts = new
    return pts


def simplify_and_smooth(
    contour: np.ndarray, dp_tol: float, chaikin_iters: int,
    H: int | None = None, W: int | None = None, edge_eps: float = 3.0,
) -> np.ndarray:
    """contour : (N, 2) array de skimage.find_contours en (row, col) demi-pixels.
    Retourne polyline (M, 2) simplifiee + lissee, FERMEE (premier == dernier).

    Si la polyline touche les bords de l'image (vertex a moins de edge_eps de
    -0.5 row/col ou H/W-0.5), on SKIP Chaikin pour preserver les angles droits
    aux coins de l'image. Les contours interieurs (= les bords entre regions)
    sont lisses normalement."""
    simp = approximate_polygon(contour, tolerance=dp_tol)
    if len(simp) < 3:
        return simp
    touches_edge = False
    if H is not None and W is not None:
        touches_edge = bool(
            (simp[:, 0] < edge_eps).any()
            or (simp[:, 0] > H - 1 - edge_eps).any()
            or (simp[:, 1] < edge_eps).any()
            or (simp[:, 1] > W - 1 - edge_eps).any()
        )
    if touches_edge or chaikin_iters <= 0:
        smooth = simp
    else:
        smooth = chaikin_closed(simp, iterations=chaikin_iters)
    return np.vstack([smooth, smooth[:1]])


def snap_polygon_to_edges(poly: np.ndarray, H: int, W: int, eps: float = 3.0) -> np.ndarray:
    """Pour les regions touchant le bord, snap les points proches des bords
    a l'exterieur exact de l'image pour eviter les coins arrondis non
    couverts par Chaikin. (row, col) format."""
    poly = poly.copy().astype(np.float64)
    poly[poly[:, 0] < eps, 0] = -1.0
    poly[poly[:, 0] > H - 1 - eps, 0] = float(H)
    poly[poly[:, 1] < eps, 1] = -1.0
    poly[poly[:, 1] > W - 1 - eps, 1] = float(W)
    return poly


# ----------------------------------------------------------------------------
# Extraction des contours par region
# ----------------------------------------------------------------------------
def extract_region_polygons(
    region_map: np.ndarray, dp_tol: float, chaikin_iters: int,
) -> list[tuple[int, list[np.ndarray]]]:
    """Pour chaque region, retourne (region_id, [polylines fermes (M, 2)]).
    On PADDE avec un label hors-domaine (-1) pour que les regions touchant
    le bord de l'image soient tracees integralement par find_contours."""
    H, W = region_map.shape
    sentinel = int(region_map.max()) + 1
    padded = np.full((H + 2, W + 2), sentinel, dtype=region_map.dtype)
    padded[1:-1, 1:-1] = region_map

    out = []
    ids = np.unique(region_map).tolist()
    for rid in ids:
        rid_int = int(rid)
        mask = (padded == rid).astype(np.uint8)
        contours = find_contours(mask, level=0.5, fully_connected="high")
        # Decaler de -1 (pad) pour revenir dans le repere image
        contours = [c - 1.0 for c in contours]
        polys = []
        for c in contours:
            poly = simplify_and_smooth(c, dp_tol, chaikin_iters, H=H, W=W)
            poly = snap_polygon_to_edges(poly, H, W)
            if len(poly) >= 4:
                polys.append(poly)
        if polys:
            out.append((rid_int, polys))
    return out


# ----------------------------------------------------------------------------
# Construction SVG (texte)
# ----------------------------------------------------------------------------
def polygons_to_svg(
    region_polys: list[tuple[int, list[np.ndarray]]],
    region_hex: dict[int, str],
    width: int,
    height: int,
    stroke_hex: str = "#15151B",
    stroke_width: int = STROKE_WIDTH,
    sort_desc_by_area: bool = True,
) -> str:
    """Genere une chaine SVG. Tri par aire decroissante : background dessine
    d'abord, details au-dessus."""
    if sort_desc_by_area:
        def total_area(polys):
            return sum(abs(_signed_area(p)) for p in polys)
        region_polys = sorted(
            region_polys, key=lambda x: -total_area(x[1])
        )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'shape-rendering="geometricPrecision">'
    ]
    # Fond blanc pour eviter transparence apparente
    lines.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    for rid, polys in region_polys:
        fill = region_hex.get(rid, "#dddddd")
        for poly in polys:
            d_parts = []
            d_parts.append(f"M{poly[0][1]:.2f},{poly[0][0]:.2f}")
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            d_parts.append("Z")
            lines.append(
                f'<path d="{" ".join(d_parts)}" '
                f'fill="{fill}" stroke="{stroke_hex}" stroke-width="{stroke_width}" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )
    lines.append("</svg>")
    return "\n".join(lines)


def _signed_area(poly: np.ndarray) -> float:
    """Aire signee d'une polyligne fermee (shoelace), en pixels."""
    if len(poly) < 3:
        return 0.0
    x = poly[:, 1]
    y = poly[:, 0]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


# ----------------------------------------------------------------------------
# Rasterisation pour controle de couverture + diff
# ----------------------------------------------------------------------------
def rasterize(
    region_polys: list[tuple[int, list[np.ndarray]]],
    region_hex: dict[int, str],
    width: int,
    height: int,
    stroke_color_bgr: tuple[int, int, int] = (25, 20, 20),
    stroke_width: int = STROKE_WIDTH,
) -> tuple[np.ndarray, np.ndarray]:
    """Rasterise polygones (fill + stroke) et retourne (rendered_bgr, coverage_u8)."""
    rendered = np.full((height, width, 3), 255, dtype=np.uint8)
    coverage = np.zeros((height, width), dtype=np.uint8)
    # Tri par aire decroissante
    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))

    # Fill pass
    for rid, polys in sorted_polys:
        hex_color = region_hex.get(rid, "#dddddd").lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        bgr = (b, g, r)
        for poly in polys:
            pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(rendered, [pts], bgr)
            cv2.fillPoly(coverage, [pts], 255)
    # Stroke pass (au-dessus)
    for rid, polys in sorted_polys:
        for poly in polys:
            pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(
                rendered, [pts], isClosed=True, color=stroke_color_bgr,
                thickness=stroke_width, lineType=cv2.LINE_AA,
            )
            cv2.polylines(
                coverage, [pts], isClosed=True, color=255,
                thickness=stroke_width, lineType=cv2.LINE_8,
            )
    return rendered, coverage


def make_diff(coverage_u8: np.ndarray, rendered_bgr: np.ndarray) -> tuple[np.ndarray, int]:
    """Visualise les pixels non couverts en rouge sur le rendu."""
    diff = rendered_bgr.copy()
    not_covered = coverage_u8 == 0
    diff[not_covered] = (40, 40, 230)  # rouge BGR
    return diff, int(not_covered.sum())


# ----------------------------------------------------------------------------
# Detection des jonctions triples
# ----------------------------------------------------------------------------
def detect_junctions(region_map: np.ndarray) -> np.ndarray:
    """Retourne un masque (H+1, W+1) bool des coins ou >= 3 labels distincts
    se rejoignent parmi les 4 pixels adjacents."""
    H, W = region_map.shape
    A = region_map[:-1, :-1]
    B = region_map[:-1, 1:]
    C = region_map[1:, :-1]
    D = region_map[1:, 1:]
    stack = np.stack([A, B, C, D], axis=-1)
    sorted_st = np.sort(stack, axis=-1)
    diffs = sorted_st[..., 1:] != sorted_st[..., :-1]
    distinct_count = 1 + diffs.sum(axis=-1)
    interior_mask = distinct_count >= 3  # (H-1, W-1)
    # Inserer dans une grille (H, W) qui place les corners interieurs en (1..H-1, 1..W-1)
    mask = np.zeros((H, W), dtype=bool)
    mask[1:, 1:] = interior_mask
    return mask


def junction_score(region_map: np.ndarray, r: int, c: int) -> int:
    """Nombre de labels distincts autour du corner (r, c). 3 ou 4."""
    H, W = region_map.shape
    rs = [r - 1, r - 1, r, r]
    cs = [c - 1, c, c - 1, c]
    labels = []
    for rr, cc in zip(rs, cs):
        if 0 <= rr < H and 0 <= cc < W:
            labels.append(int(region_map[rr, cc]))
    return len(set(labels))


# ----------------------------------------------------------------------------
# Pipeline par image
# ----------------------------------------------------------------------------
def process_image(
    region_map_path: Path,
    region_hex: dict[int, str],
    out_dir: Path,
    slot: int,
    rid: str,
    dp_tol: float = DP_TOLERANCE,
    chaikin_iters: int = CHAIKIN_ITERS,
) -> dict:
    rm = np.load(region_map_path).astype(np.int32)
    H, W = rm.shape

    t0 = time.time()
    region_polys = extract_region_polygons(rm, dp_tol, chaikin_iters)
    t_extract = time.time() - t0

    # Stats vectorisation
    n_regions = len(region_polys)
    n_polys = sum(len(p) for _, p in region_polys)
    n_points_total = sum(len(poly) for _, polys in region_polys for poly in polys)

    # SVG
    t0 = time.time()
    svg_text = polygons_to_svg(region_polys, region_hex, W, H)
    svg_path = out_dir / f"{slot:02d}_{rid}_enfant.svg"
    svg_path.write_text(svg_text, encoding="utf-8")
    t_svg = time.time() - t0

    # Rasterisation + diff
    t0 = time.time()
    rendered, coverage = rasterize(region_polys, region_hex, W, H)
    diff, n_non_covered = make_diff(coverage, rendered)
    t_raster = time.time() - t0
    non_covered_pct = n_non_covered / (H * W) * 100

    # Sauvegarde renderings
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_svg_render.png"), rendered)
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_diff.png"), diff)

    # Detection jonctions triples
    t0 = time.time()
    junc_mask = detect_junctions(rm)
    junc_rcs = np.argwhere(junc_mask)
    # Score chaque jonction = nb labels distincts (3 ou 4)
    junc_scored = [
        (int(r), int(c), junction_score(rm, int(r), int(c)))
        for r, c in junc_rcs
    ]
    n_junc_3 = sum(1 for _, _, s in junc_scored if s == 3)
    n_junc_4plus = sum(1 for _, _, s in junc_scored if s >= 4)
    t_junc = time.time() - t0

    # Overlay : jonctions en cyan sur le rendu SVG
    overlay = rendered.copy()
    for r, c, score in junc_scored:
        color = (255, 230, 0) if score >= 4 else (255, 150, 0)  # BGR (cyan / orange)
        cv2.circle(overlay, (c, r), radius=3, color=color, thickness=-1)
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_junctions_overlay.png"), overlay)

    return {
        "slot": slot,
        "id": rid,
        "image_size": [int(W), int(H)],
        "n_regions": n_regions,
        "n_polylines": n_polys,
        "n_points_total": n_points_total,
        "non_covered_pixels": n_non_covered,
        "non_covered_pct": round(non_covered_pct, 4),
        "junctions_3": n_junc_3,
        "junctions_4plus": n_junc_4plus,
        "junctions_total": n_junc_3 + n_junc_4plus,
        "params": {
            "dp_tolerance": dp_tol,
            "chaikin_iters": chaikin_iters,
            "stroke_width": STROKE_WIDTH,
        },
        "timing_s": {
            "extract": round(t_extract, 2),
            "svg": round(t_svg, 2),
            "raster": round(t_raster, 2),
            "junctions": round(t_junc, 2),
            "total": round(t_extract + t_svg + t_raster + t_junc, 2),
        },
        "outputs": {
            "svg": str((out_dir / f"{slot:02d}_{rid}_enfant.svg").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "svg_render_png": str((out_dir / f"{slot:02d}_{rid}_svg_render.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "diff_png": str((out_dir / f"{slot:02d}_{rid}_diff.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "junctions_overlay_png": str((out_dir / f"{slot:02d}_{rid}_junctions_overlay.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
        },
        "best_junctions": [
            {"row": r, "col": c, "labels_around": s}
            for r, c, s in sorted(junc_scored, key=lambda x: -x[2])[:5]
        ],
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--g2-stats", type=Path, default=DEFAULT_G2_STATS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--level", default="enfant")
    parser.add_argument("--dp-tol", type=float, default=DP_TOLERANCE)
    parser.add_argument("--chaikin-iters", type=int, default=CHAIKIN_ITERS)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    g2 = json.loads(args.g2_stats.read_text(encoding="utf-8"))

    args.out.mkdir(parents=True, exist_ok=True)

    # Build (slot, level) -> stats for hex lookup
    g2_by_slot_level = {
        (s["slot"], s["level"]): s for s in g2["images"]
    }

    all_stats = {
        "level_used": args.level,
        "params": {
            "dp_tolerance": args.dp_tol,
            "chaikin_iters": args.chaikin_iters,
            "stroke_width": STROKE_WIDTH,
        },
        "images": [],
    }

    for item in corpus["images"]:
        slot = item["slot"]
        rid = item["id"]
        g2_entry = g2_by_slot_level.get((slot, args.level))
        if not g2_entry:
            print(f"[SKIP] #{slot} {rid}: pas de stats g2 {args.level}", file=sys.stderr)
            continue
        rm_npy = (PROJECT_ROOT / g2_entry["out_npy"]).resolve()
        if not rm_npy.exists():
            print(f"[SKIP] #{slot} {rid}: {rm_npy} absent", file=sys.stderr)
            continue
        region_hex: dict[int, str] = {
            r["id"]: r["hex"] for r in g2_entry.get("regions", [])
        }
        print(f"[G3] #{slot:02d} {rid} : {len(region_hex)} regions ...", flush=True)
        stats = process_image(
            rm_npy, region_hex, args.out, slot, rid,
            dp_tol=args.dp_tol, chaikin_iters=args.chaikin_iters,
        )
        all_stats["images"].append(stats)
        print(
            f"        n_polys {stats['n_polylines']:4d}  "
            f"pts {stats['n_points_total']:5d}  "
            f"non_covered {stats['non_covered_pct']:.3f}%  "
            f"junctions {stats['junctions_3']:3d}x3 / {stats['junctions_4plus']:3d}x4+  "
            f"t {stats['timing_s']['total']}s"
        )

    stats_path = args.out / "stats.json"
    stats_path.write_text(json.dumps(all_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK stats : {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
