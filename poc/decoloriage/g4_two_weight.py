"""G4 - Decoloriage : hierarchie de traits a 2 poids (ink / shading).

Architecture :
  1. Extraction TOPOLOGIQUE des arcs du graphe de frontieres partagees :
     - Cracks (segments inter-pixels ou les labels different)
     - Corners en jonction = ou >= 3 labels se rencontrent
     - Arcs = chemins de jonction-a-jonction (chaque frontiere tracee UNE fois)
  2. Classification des arcs : "encre" si >= 60 % de ses pixels tombent dans
     le masque de traits G2 dilate 3 px, sinon "shading".
  3. Calibrage stroke : epaisseur "encre" = mediane de l'epaisseur du trait ERNIE
     (2 x median(distance transform) sur le masque). "shading" = ~1/3.
  4. SVG en DEUX couches :
     - Fill layer : polygones par region (avec snap-edges + Chaikin G3),
       sans stroke
     - Stroke layer : arcs topologiques, chaque arc dessine UNE fois,
       stroke-linejoin/linecap round, 2 poids selon classe
  5. Comptage zones fermees (a) line art ERNIE direct = CC inversion du masque
     de traits.

Cible G4 : hypothese pre-enregistree
    regions(c) >= 2 x regions(a) sur les 5 animaux
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from skimage.measure import approximate_polygon

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))

# Reuse G3 helpers
from g3_vectorize import (  # noqa: E402
    extract_region_polygons,
    snap_polygon_to_edges,
    _signed_area,
)

DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_G2_STATS = Path(__file__).parent / "g2_out" / "stats.json"
DEFAULT_OUT_DIR = Path(__file__).parent / "g4_out"

INK_OVERLAP_THRESHOLD = 0.60
LINE_MASK_DILATE_PX = 3
DP_TOLERANCE = 1.0
CHAIKIN_ITERS_ARC = 2
CHAIKIN_ITERS_REGION = 2  # for fill polygons
SHADING_RATIO = 1.0 / 3.0  # shading_w = ink_w * ratio


# ============================================================================
# 1) Extraction des arcs topologiques
# ============================================================================
def extract_topological_arcs(label_map: np.ndarray) -> tuple[list[dict], dict]:
    """Retourne (arcs, stats). Chaque arc : {points, label_pair, endpoints,
    closed_loop}. points en (row, col) flottants dans l'image originale
    (apres shift du padding)."""
    H, W = label_map.shape
    sentinel = int(label_map.max()) + 1
    padded = np.full((H + 2, W + 2), sentinel, dtype=label_map.dtype)
    padded[1:-1, 1:-1] = label_map

    # Vectorise les cracks
    # Vertical cracks : entre pixels horizontalement adjacents
    left = padded[:, :-1]
    right = padded[:, 1:]
    vmask = left != right
    vrows, vcols = np.where(vmask)

    # Horizontal cracks
    top = padded[:-1, :]
    bot = padded[1:, :]
    hmask = top != bot
    hrows, hcols = np.where(hmask)

    # Construire l'adjacence des corners
    # corner = (r, c) en coord padded ; on shiftera de -1 a la fin
    corner_neighbors: dict[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]]] = (
        defaultdict(list)
    )

    # Vertical crack en (r, c+1) <-> (r+1, c+1)
    left_vals = left[vrows, vcols]
    right_vals = right[vrows, vcols]
    for i in range(len(vrows)):
        r = int(vrows[i]); c = int(vcols[i])
        a = int(left_vals[i]); b = int(right_vals[i])
        pair = (min(a, b), max(a, b))
        c1 = (r, c + 1)
        c2 = (r + 1, c + 1)
        corner_neighbors[c1].append((c2, pair))
        corner_neighbors[c2].append((c1, pair))

    top_vals = top[hrows, hcols]
    bot_vals = bot[hrows, hcols]
    for i in range(len(hrows)):
        r = int(hrows[i]); c = int(hcols[i])
        a = int(top_vals[i]); b = int(bot_vals[i])
        pair = (min(a, b), max(a, b))
        c1 = (r + 1, c)
        c2 = (r + 1, c + 1)
        corner_neighbors[c1].append((c2, pair))
        corner_neighbors[c2].append((c1, pair))

    # Jonctions : corners avec > 2 cracks
    junctions: set[tuple[int, int]] = set()
    for corner, nbrs in corner_neighbors.items():
        if len(nbrs) > 2:
            junctions.add(corner)

    arcs: list[dict] = []
    visited: set[frozenset[tuple[int, int]]] = set()

    def make_crack_id(a, b):
        return frozenset({a, b})

    # Tracer arcs depuis chaque jonction
    for jct in list(junctions):
        for (nbr, pair) in list(corner_neighbors[jct]):
            cid = make_crack_id(jct, nbr)
            if cid in visited:
                continue
            visited.add(cid)
            arc_pts: list[tuple[int, int]] = [jct, nbr]
            arc_pair = pair
            current = nbr
            prev = jct
            while current not in junctions:
                nbrs = corner_neighbors[current]
                if len(nbrs) != 2:
                    break
                # Prendre le voisin qui n'est pas prev
                next_corner = None
                for (n_corner, n_pair) in nbrs:
                    if n_corner != prev:
                        next_corner = n_corner
                        break
                if next_corner is None:
                    break
                cid_next = make_crack_id(current, next_corner)
                if cid_next in visited:
                    break
                visited.add(cid_next)
                arc_pts.append(next_corner)
                prev = current
                current = next_corner
            arcs.append({
                "points": arc_pts,
                "label_pair": arc_pair,
                "endpoints": (jct, current),
                "closed_loop": False,
            })

    # Tracer les boucles fermees (sans jonction)
    all_cracks_count = (len(vrows) + len(hrows))
    for corner, nbrs in list(corner_neighbors.items()):
        for (nbr, pair) in nbrs:
            cid = make_crack_id(corner, nbr)
            if cid in visited:
                continue
            visited.add(cid)
            arc_pts = [corner, nbr]
            arc_pair = pair
            current = nbr
            prev = corner
            while True:
                nbrs2 = corner_neighbors[current]
                if len(nbrs2) != 2:
                    break
                next_corner = None
                for (n_corner, n_pair) in nbrs2:
                    if n_corner != prev:
                        next_corner = n_corner
                        break
                if next_corner is None:
                    break
                cid_next = make_crack_id(current, next_corner)
                if cid_next in visited:
                    arc_pts.append(next_corner)
                    break
                visited.add(cid_next)
                arc_pts.append(next_corner)
                prev = current
                current = next_corner
            arcs.append({
                "points": arc_pts,
                "label_pair": arc_pair,
                "endpoints": (corner, current),
                "closed_loop": True,
            })

    # Shift back to image coords : padded -1
    for arc in arcs:
        arc["points"] = [(float(r - 1), float(c - 1)) for (r, c) in arc["points"]]
        e1, e2 = arc["endpoints"]
        arc["endpoints"] = ((e1[0] - 1, e1[1] - 1), (e2[0] - 1, e2[1] - 1))

    stats = {
        "n_cracks": all_cracks_count,
        "n_junctions": len(junctions),
        "n_arcs": len(arcs),
    }
    return arcs, stats


# ============================================================================
# 2) Classification ink / shading
# ============================================================================
def classify_arc_into_ink_or_shading(
    arc_points: list[tuple[float, float]],
    dilated_line_mask: np.ndarray,
    threshold: float = INK_OVERLAP_THRESHOLD,
) -> tuple[str, float]:
    """Rasterise l'arc en 1-px line et mesure son overlap avec line_mask dilate."""
    H, W = dilated_line_mask.shape
    canvas = np.zeros((H, W), dtype=np.uint8)
    # Points en (row, col) -> cv2 needs (x, y) = (col, row)
    pts = np.array(arc_points, dtype=np.float64)
    if len(pts) < 2:
        return "shading", 0.0
    pts_int = np.round(pts).astype(np.int32)
    # Clamp dans l'image (les arcs de bord peuvent etre a -1)
    pts_int[:, 0] = np.clip(pts_int[:, 0], 0, H - 1)
    pts_int[:, 1] = np.clip(pts_int[:, 1], 0, W - 1)
    # Convert to (x, y) format
    pts_xy = pts_int[:, [1, 0]].reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts_xy], isClosed=False, color=255, thickness=1, lineType=cv2.LINE_8)
    arc_mask = canvas > 0
    total = int(arc_mask.sum())
    if total == 0:
        return "shading", 0.0
    overlap = int((arc_mask & (dilated_line_mask > 0)).sum())
    ratio = overlap / total
    return ("ink" if ratio >= threshold else "shading"), ratio


# ============================================================================
# 3) Calibrage de l'epaisseur du trait ERNIE
# ============================================================================
def measure_line_thickness(line_mask: np.ndarray) -> float:
    """Estimation de l'epaisseur mediane = 2 x median(distance transform)
    sur les pixels INSIDE the mask."""
    line_bin = (line_mask > 127).astype(np.uint8)
    if line_bin.sum() == 0:
        return 3.0
    dist = cv2.distanceTransform(line_bin, cv2.DIST_L2, 5)
    inside = dist[line_bin > 0]
    return float(2.0 * np.median(inside))


# ============================================================================
# 4) Lissage des arcs (DP + Chaikin) en preservant les bords
# ============================================================================
def smooth_open_arc(
    arc_points: list[tuple[float, float]],
    dp_tol: float,
    chaikin_iters: int,
    H: int,
    W: int,
    edge_eps: float = 3.0,
) -> np.ndarray:
    """DP + Chaikin OUVERT (pas de fermeture). Skip Chaikin si touche bord."""
    if len(arc_points) < 2:
        return np.array(arc_points, dtype=np.float64)
    arr = np.array(arc_points, dtype=np.float64)
    simp = approximate_polygon(arr, tolerance=dp_tol)
    if len(simp) < 2:
        return simp
    touches_edge = bool(
        (simp[:, 0] < edge_eps).any()
        or (simp[:, 0] > H - 1 - edge_eps).any()
        or (simp[:, 1] < edge_eps).any()
        or (simp[:, 1] > W - 1 - edge_eps).any()
    )
    if touches_edge or chaikin_iters <= 0:
        return simp
    # Open-curve Chaikin (Q et R par segment, ne pas wrap)
    for _ in range(chaikin_iters):
        if len(simp) < 2:
            break
        new_pts: list[np.ndarray] = [simp[0]]
        for i in range(len(simp) - 1):
            p1 = simp[i]
            p2 = simp[i + 1]
            q = 0.75 * p1 + 0.25 * p2
            r = 0.25 * p1 + 0.75 * p2
            new_pts.append(q)
            new_pts.append(r)
        new_pts.append(simp[-1])
        simp = np.array(new_pts)
    return simp


# ============================================================================
# 5) Build SVG (fill layer + stroke layer)
# ============================================================================
def build_g4_svg(
    region_polys: list[tuple[int, list[np.ndarray]]],
    region_hex: dict[int, str],
    arcs_classified: list[dict],
    ink_w: float,
    shading_w: float,
    H: int,
    W: int,
) -> str:
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'shape-rendering="geometricPrecision">'
    ]
    lines.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

    # ---- Fill layer ----
    lines.append('<g id="fills" stroke="none">')

    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))
    for rid, polys in sorted_polys:
        fill = region_hex.get(rid, "#dddddd")
        for poly in polys:
            d_parts = [f"M{poly[0][1]:.2f},{poly[0][0]:.2f}"]
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            d_parts.append("Z")
            lines.append(f'<path d="{" ".join(d_parts)}" fill="{fill}"/>')
    lines.append("</g>")

    # ---- Stroke layer ----
    lines.append(
        f'<g id="strokes" fill="none" stroke="#15151B" '
        f'stroke-linejoin="round" stroke-linecap="round">'
    )
    for arc in arcs_classified:
        poly = arc["smoothed"]
        if len(poly) < 2:
            continue
        cls = arc["class"]
        sw = ink_w if cls == "ink" else shading_w
        d_parts = [f"M{poly[0][1]:.2f},{poly[0][0]:.2f}"]
        for p in poly[1:]:
            d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
        lines.append(
            f'<path d="{" ".join(d_parts)}" stroke-width="{sw:.2f}"/>'
        )
    lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines)


# ============================================================================
# 6) Rasterisation pour controle visuel + (a) line art count
# ============================================================================
def rasterize_g4(
    region_polys, region_hex, arcs_classified, ink_w, shading_w, H, W
) -> np.ndarray:
    """Rasterise dans l'ordre du SVG : fond blanc, fills tries par aire dec,
    puis strokes."""
    canvas = np.full((H, W, 3), 255, dtype=np.uint8)
    # Fill pass
    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))
    for rid, polys in sorted_polys:
        hex_color = region_hex.get(rid, "#dddddd").lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        bgr = (b, g, r)
        for poly in polys:
            pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(canvas, [pts], bgr)
    # Stroke pass (2 poids)
    ink_int = max(1, int(round(ink_w)))
    sha_int = max(1, int(round(shading_w)))
    stroke_bgr = (27, 21, 21)  # #15151B en BGR
    for arc in arcs_classified:
        poly = arc["smoothed"]
        if len(poly) < 2:
            continue
        cls = arc["class"]
        thickness = ink_int if cls == "ink" else sha_int
        pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [pts], False, stroke_bgr, thickness, lineType=cv2.LINE_AA)
    return canvas


def count_regions_in_line_art(line_mask_path: Path) -> tuple[int, np.ndarray, np.ndarray]:
    """Charge le masque de traits, le binarise, et compte les composantes
    connexes du COMPLEMENT (= zones fermees coloriables).
    Retourne (n_zones, line_mask_u8, vis_rgb)."""
    line = cv2.imread(str(line_mask_path), cv2.IMREAD_GRAYSCALE)
    line_bin = (line > 127).astype(np.uint8)
    fill = 1 - line_bin
    n_labels, labels = cv2.connectedComponents(fill, connectivity=4)
    # n_labels inclut le label 0 (= les traits). n_zones = n_labels - 1.
    n_zones = max(0, n_labels - 1)

    # Visualisation : zones en couleurs aleatoires + traits noirs
    rng = np.random.default_rng(0)
    palette = rng.integers(80, 220, size=(n_labels + 1, 3), dtype=np.uint8)
    palette[0] = [15, 15, 15]  # traits noirs
    vis = palette[labels]
    return n_zones, line_bin, vis


# ============================================================================
# 7) "Pipeline actuel binarisation+potrace" (simule)
# ============================================================================
def simulate_binarize_potrace(line_mask_u8: np.ndarray) -> np.ndarray:
    """Vectorisation naive du masque de traits : findContours -> polylines.
    Le rendu est un line-art noir/blanc, sans remplissage colore.
    Sert de baseline (b) pour la planche verdict."""
    H, W = line_mask_u8.shape
    canvas = np.full((H, W, 3), 255, dtype=np.uint8)
    # Simplifier le masque puis tracer
    contours, _ = cv2.findContours(line_mask_u8, cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)
    # Tracer
    cv2.drawContours(canvas, contours, -1, (20, 20, 25), thickness=2, lineType=cv2.LINE_AA)
    return canvas


# ============================================================================
# 8) Pipeline G4 par image
# ============================================================================
def process_image(
    region_map_path: Path,
    line_mask_path: Path,
    region_hex: dict[int, str],
    out_dir: Path,
    slot: int,
    rid: str,
    dp_tol: float = DP_TOLERANCE,
    chaikin_iters_arc: int = CHAIKIN_ITERS_ARC,
    chaikin_iters_region: int = CHAIKIN_ITERS_REGION,
) -> dict:
    rm = np.load(region_map_path).astype(np.int32)
    H, W = rm.shape
    line_mask = cv2.imread(str(line_mask_path), cv2.IMREAD_GRAYSCALE)
    if line_mask is None:
        raise FileNotFoundError(f"Line mask missing : {line_mask_path}")

    # Mesurer epaisseur trait ERNIE
    t0 = time.time()
    median_thickness = measure_line_thickness(line_mask)
    ink_w = max(2.0, median_thickness)  # garde-fou
    shading_w = max(1.0, ink_w * SHADING_RATIO)
    t_thickness = time.time() - t0

    # Dilatation du masque de traits pour la classification
    t0 = time.time()
    kernel = np.ones((LINE_MASK_DILATE_PX, LINE_MASK_DILATE_PX), np.uint8)
    line_mask_dilated = cv2.dilate(line_mask, kernel, iterations=1)
    t_dilate = time.time() - t0

    # Extraction des arcs topologiques
    t0 = time.time()
    arcs, arc_stats = extract_topological_arcs(rm)
    t_arcs = time.time() - t0

    # Classification ink / shading
    t0 = time.time()
    n_ink = 0
    n_shading = 0
    arcs_classified: list[dict] = []
    for arc in arcs:
        cls, ratio = classify_arc_into_ink_or_shading(arc["points"], line_mask_dilated)
        smoothed = smooth_open_arc(arc["points"], dp_tol, chaikin_iters_arc, H, W)
        arcs_classified.append({
            **arc,
            "class": cls,
            "ink_ratio": round(ratio, 3),
            "smoothed": smoothed,
        })
        if cls == "ink":
            n_ink += 1
        else:
            n_shading += 1
    t_classify = time.time() - t0

    # Fill polygons (G3 approach with Chaikin smoothing)
    t0 = time.time()
    region_polys = extract_region_polygons(rm, dp_tol, chaikin_iters_region)
    t_fills = time.time() - t0

    # SVG
    t0 = time.time()
    svg_text = build_g4_svg(region_polys, region_hex, arcs_classified, ink_w, shading_w, H, W)
    svg_path = out_dir / f"{slot:02d}_{rid}_g4.svg"
    svg_path.write_text(svg_text, encoding="utf-8")
    t_svg = time.time() - t0

    # Rasterisation
    t0 = time.time()
    rendered = rasterize_g4(region_polys, region_hex, arcs_classified, ink_w, shading_w, H, W)
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_g4_render.png"), rendered)
    t_render = time.time() - t0

    # (a) compte zones fermees du line art ERNIE direct
    n_zones_a, line_bin, line_art_vis = count_regions_in_line_art(line_mask_path)
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_a_line_art.png"),
                cv2.cvtColor(line_art_vis, cv2.COLOR_RGB2BGR))

    # (b) baseline binarize + potrace simule
    sim_b = simulate_binarize_potrace((line_bin * 255).astype(np.uint8))
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_b_binarize_potrace.png"), sim_b)

    n_zones_c = int(len(np.unique(rm)))

    return {
        "slot": slot,
        "id": rid,
        "image_size": [int(W), int(H)],
        "params": {
            "ink_overlap_threshold": INK_OVERLAP_THRESHOLD,
            "line_mask_dilate_px": LINE_MASK_DILATE_PX,
            "dp_tolerance": dp_tol,
            "chaikin_iters_arc": chaikin_iters_arc,
            "chaikin_iters_region": chaikin_iters_region,
        },
        "line_thickness": {
            "median_measured": round(median_thickness, 2),
            "ink_stroke_width": round(ink_w, 2),
            "shading_stroke_width": round(shading_w, 2),
        },
        "arcs": {
            **arc_stats,
            "n_ink": n_ink,
            "n_shading": n_shading,
        },
        "regions": {
            "a_line_art_zones": n_zones_a,
            "c_decoloriage_regions": n_zones_c,
            "ratio_c_over_a": round(n_zones_c / max(1, n_zones_a), 2),
        },
        "outputs": {
            "svg": str((out_dir / f"{slot:02d}_{rid}_g4.svg").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "g4_render": str((out_dir / f"{slot:02d}_{rid}_g4_render.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "a_line_art": str((out_dir / f"{slot:02d}_{rid}_a_line_art.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "b_binarize_potrace": str((out_dir / f"{slot:02d}_{rid}_b_binarize_potrace.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
        },
        "timing_s": {
            "thickness": round(t_thickness, 2),
            "dilate": round(t_dilate, 2),
            "arcs": round(t_arcs, 2),
            "classify": round(t_classify, 2),
            "fills": round(t_fills, 2),
            "svg": round(t_svg, 2),
            "render": round(t_render, 2),
            "total": round(
                t_thickness + t_dilate + t_arcs + t_classify + t_fills + t_svg + t_render, 2
            ),
        },
    }


# ============================================================================
# 9) Main
# ============================================================================
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--g2-stats", type=Path, default=DEFAULT_G2_STATS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    g2 = json.loads(args.g2_stats.read_text(encoding="utf-8"))

    args.out.mkdir(parents=True, exist_ok=True)

    g2_by_slot_level = {(s["slot"], s["level"]): s for s in g2["images"]}
    g2_lines = g2.get("lines", {})

    all_stats = {
        "params": {
            "ink_overlap_threshold": INK_OVERLAP_THRESHOLD,
            "line_mask_dilate_px": LINE_MASK_DILATE_PX,
            "dp_tolerance": DP_TOLERANCE,
            "chaikin_iters_arc": CHAIKIN_ITERS_ARC,
            "chaikin_iters_region": CHAIKIN_ITERS_REGION,
            "shading_ratio_of_ink": SHADING_RATIO,
        },
        "hypothesis_pre_recorded": "regions(c) >= 2 x regions(a) sur les 5 animaux",
        "images": [],
    }

    for item in corpus["images"]:
        slot = item["slot"]
        rid = item["id"]
        g2_entry = g2_by_slot_level.get((slot, "enfant"))
        line_entry = g2_lines.get(rid)
        if not g2_entry or not line_entry:
            print(f"[SKIP] #{slot} {rid}: stats manquantes", file=sys.stderr)
            continue
        rm_npy = (PROJECT_ROOT / g2_entry["out_npy"]).resolve()
        line_mask_path = (PROJECT_ROOT / line_entry["path"]).resolve()
        if not rm_npy.exists() or not line_mask_path.exists():
            print(f"[SKIP] #{slot} {rid}: fichier absent", file=sys.stderr)
            continue
        region_hex: dict[int, str] = {r["id"]: r["hex"] for r in g2_entry.get("regions", [])}
        print(f"[G4] #{slot:02d} {rid} ...", flush=True)
        stats = process_image(rm_npy, line_mask_path, region_hex, args.out, slot, rid)
        stats["category"] = item["category"]
        all_stats["images"].append(stats)
        print(
            f"     ink {stats['arcs']['n_ink']:4d}  shading {stats['arcs']['n_shading']:4d}  "
            f"thickness ink={stats['line_thickness']['ink_stroke_width']:.1f}px / "
            f"sha={stats['line_thickness']['shading_stroke_width']:.1f}px  |  "
            f"a={stats['regions']['a_line_art_zones']}  c={stats['regions']['c_decoloriage_regions']}  "
            f"ratio c/a={stats['regions']['ratio_c_over_a']}  |  "
            f"t {stats['timing_s']['total']}s"
        )

    # Resume hypothese sur animaux
    animals = [s for s in all_stats["images"] if s["category"] == "animal"]
    n_pass = sum(1 for s in animals if s["regions"]["ratio_c_over_a"] >= 2.0)
    all_stats["hypothesis_check"] = {
        "n_animals_evaluated": len(animals),
        "n_animals_pass": n_pass,
        "details": [
            {
                "slot": s["slot"],
                "id": s["id"],
                "a": s["regions"]["a_line_art_zones"],
                "c": s["regions"]["c_decoloriage_regions"],
                "ratio": s["regions"]["ratio_c_over_a"],
                "pass_2x": s["regions"]["ratio_c_over_a"] >= 2.0,
            }
            for s in animals
        ],
    }

    stats_path = args.out / "stats.json"
    stats_path.write_text(json.dumps(all_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK stats : {stats_path}")
    print(
        f"Hypothese animaux : {n_pass}/{len(animals)} satisfont regions(c) >= 2 x regions(a)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
