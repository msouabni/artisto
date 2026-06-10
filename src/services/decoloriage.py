"""Décoloriage — cœur POC (G1a→G5) productionisé en service.

Phase 1 (spike) : porte le cœur réutilisable du POC `decoloriage-validation`
(scripts `poc/decoloriage/g1a_v3_compact.py`, `g2_partition.py`,
`g3_vectorize.py`, `g4_two_weight.py`, `g5_product.py`) dans un module unique
sans dépendance au harness contact-sheet.

Pipeline (niveau ``enfant`` uniquement en v1) :

    PNG colorié pastel
      → G1a v3 : pyrMeanShift(sp=12,sr=24) + k-means Lab k=12 + CC 4-conn
                 + merge_v3 (min_area_ratio=0.0005, contrast_thresh=30, compacité 3×3)
      → G2 enfant : smooth_merge_similar(thresh=12) avec immunité protected_ids
                    + masque de traits (L<25 + close 3×3)
      → G3 : extract_region_polygons (find_contours padding sentinel + DP tol 1
             + Chaikin closed 2 iter + snap-to-edges)
      → G4 : extract_topological_arcs + classify ink/shading (overlap ≥ 60 %
             masque dilaté 3 px) + measure_line_thickness + smooth_open_arc
      → G5 : compute_ink_regions (overlap ≥ 50 % → région-encre #111111
             pointer-events:none, exclue du compteur) + nearest_crayon
             (ΔE76 Lab vers 6 crayons) + exception Papier #ffffff si L*≥92
      → SVG bicouche <g id="fills" fill-rule="evenodd"> + <g id="strokes">

Tous les presets/constantes sont recopiés **verbatim** depuis le POC (D7,
méthodo POC immutables). Le service ne touche **aucune** base de données.

Façade publique : ``decolorize(png_path, level="enfant") -> DecoloriageResult``.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.color import rgb2lab
from skimage.measure import approximate_polygon, find_contours

logger = logging.getLogger(__name__)


class DecoloriageError(RuntimeError):
    """Erreur métier explicite du moteur décoloriage.

    Levée quand l'image est illisible, la segmentation ne produit aucune
    région, ou le masque de traits est vide — au lieu de crasher silencieusement
    plus loin dans le pipeline. Sous-classe de ``RuntimeError`` pour que les
    appelants puissent l'attraper sans dépendre du module.
    """

# ============================================================================
# Presets / constantes — RECOPIÉS VERBATIM DU POC (immutables, D7)
# ============================================================================

# --- G1a v3 (g1a_v3_compact.py / BASE_V3 de g2_partition.py) ---
G1A_K = 12
G1A_SP = 12
G1A_SR = 24
G1A_MERGE_THRESH = 0.0005
G1A_CONTRAST_THRESH = 30.0

# --- G2 enfant (g2_partition.py / LEVELS["enfant"]) ---
ENFANT_SMOOTH_MERGE_THRESH = 12.0
LINES_L_THRESHOLD = 25.0  # masque de traits : L < 25 sur image lissée

# --- G4 (g4_two_weight.py) ---
INK_OVERLAP_THRESHOLD = 0.60
LINE_MASK_DILATE_PX = 3
DP_TOLERANCE = 1.0
CHAIKIN_ITERS_ARC = 2
CHAIKIN_ITERS_REGION = 2
SHADING_RATIO = 1.0 / 3.0

# --- G5 (g5_product.py) ---
INK_REGION_OVERLAP_THRESHOLD = 0.50
INK_REGION_FILL = "#111111"
HOLLOW_TUBE_OVERLAP_THRESHOLD = 0.30
BACKGROUND_L_THRESHOLD = 92.0

# Crayons du design system Alwan Books (skill spec G5) — VERBATIM
CRAYONS = [
    {"name": "Cerise",    "hex": "#FF2E63"},
    {"name": "Mandarine", "hex": "#FF8A2B"},
    {"name": "Citron",    "hex": "#FFD60A"},
    {"name": "Menthe",    "hex": "#06D6A0"},
    {"name": "Ocean",     "hex": "#118AB2"},
    {"name": "Prune",     "hex": "#8B5CF6"},
]

# Palette autorisée pour les régions cliquables (crayons + Papier).
ALLOWED_FILL_HEXES = {c["hex"] for c in CRAYONS} | {"#ffffff"}

# Identifiant du moteur coloriage (clé ``coloring_engine`` de model_config).
COLORING_ENGINE = "decoloriage"


# ============================================================================
# G1a v3 — segmentation couleur (verbatim g1a_v3_compact.py)
# ============================================================================
def preprocess_meanshift(rgb: np.ndarray, sp: int = G1A_SP, sr: int = G1A_SR) -> np.ndarray:
    """cv2.pyrMeanShiftFiltering attend BGR 8-bit. Retourne RGB 8-bit lissé."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    shifted = cv2.pyrMeanShiftFiltering(bgr, sp=sp, sr=sr)
    return cv2.cvtColor(shifted, cv2.COLOR_BGR2RGB)


def kmeans_lab(rgb: np.ndarray, k: int, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    lab = rgb2lab(rgb).astype(np.float32)
    h, w, _ = lab.shape
    flat = lab.reshape(-1, 3)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    cv2.setRNGSeed(seed)
    _compact, labels, _centers = cv2.kmeans(
        flat, k, None, criteria, attempts=4, flags=cv2.KMEANS_PP_CENTERS
    )
    return labels.reshape(h, w).astype(np.int32), lab


def connected_regions(cluster_labels: np.ndarray) -> np.ndarray:
    h, w = cluster_labels.shape
    region_map = np.zeros((h, w), dtype=np.int32)
    next_id = 1
    struct = ndi.generate_binary_structure(2, 1)
    for c in np.unique(cluster_labels):
        mask = cluster_labels == c
        cc, n = ndi.label(mask, structure=struct)
        if n == 0:
            continue
        cc[cc > 0] += next_id - 1
        region_map[mask] = cc[mask]
        next_id += n
    return region_map


def interior_mask_8(rm: np.ndarray) -> np.ndarray:
    """Masque booléen (H, W) : True = pixel survivant à l'érosion 3×3."""
    h, w = rm.shape
    interior = np.zeros((h, w), dtype=bool)
    c = rm[1:-1, 1:-1]
    inner = (
        (c == rm[:-2, :-2])
        & (c == rm[:-2, 1:-1])
        & (c == rm[:-2, 2:])
        & (c == rm[1:-1, :-2])
        & (c == rm[1:-1, 2:])
        & (c == rm[2:, :-2])
        & (c == rm[2:, 1:-1])
        & (c == rm[2:, 2:])
    )
    interior[1:-1, 1:-1] = inner
    return interior


def vectorized_adjacency(region_map: np.ndarray) -> dict[int, set[int]]:
    rm = region_map
    a = rm[:, :-1].ravel(); b = rm[:, 1:].ravel()
    mh = a != b
    pairs_h = np.column_stack([a[mh], b[mh]])
    a = rm[:-1, :].ravel(); b = rm[1:, :].ravel()
    mv = a != b
    pairs_v = np.column_stack([a[mv], b[mv]])
    pairs = np.vstack([pairs_h, pairs_v])
    if len(pairs) == 0:
        return {}
    pairs = np.sort(pairs, axis=1)
    pairs = np.unique(pairs, axis=0)
    adj: dict[int, set[int]] = {}
    for row in pairs:
        a_id, b_id = int(row[0]), int(row[1])
        adj.setdefault(a_id, set()).add(b_id)
        adj.setdefault(b_id, set()).add(a_id)
    return adj


def _do_merge(rid, best_n, neighbor_roots, areas, means, adj, parent):
    new_area = areas[best_n] + areas[rid]
    means[best_n] = (means[best_n] * areas[best_n] + means[rid] * areas[rid]) / new_area
    areas[best_n] = new_area
    adj[best_n].update(neighbor_roots - {best_n})
    for nb in list(adj[rid]):
        root = nb
        while parent[root] != root:
            root = parent[root]
        if root in adj:
            adj[root].discard(rid)
            if root != best_n:
                adj[root].add(best_n)
    parent[rid] = best_n


def merge_v3(
    region_map: np.ndarray,
    lab_image: np.ndarray,
    min_area_ratio: float,
    contrast_thresh: float,
    max_passes: int = 20,
) -> tuple[np.ndarray, dict]:
    """Pipeline fusion v3 avec compacité + ΔE (verbatim g1a_v3_compact.py)."""
    h, w = region_map.shape
    total_px = h * w
    min_area = max(1, int(round(min_area_ratio * total_px)))

    rm = region_map.copy()
    ids_arr = np.unique(rm)
    ids_list = ids_arr.tolist()

    areas_arr = np.bincount(rm.ravel())
    areas: dict[int, int] = {int(rid): int(areas_arr[rid]) for rid in ids_list}

    L_means = ndi.mean(lab_image[..., 0], rm, ids_list)
    a_means = ndi.mean(lab_image[..., 1], rm, ids_list)
    b_means = ndi.mean(lab_image[..., 2], rm, ids_list)
    means: dict[int, np.ndarray] = {
        int(rid): np.array([L_means[i], a_means[i], b_means[i]], dtype=np.float64)
        for i, rid in enumerate(ids_list)
    }

    int_mask = interior_mask_8(rm)
    interior_counts = ndi.sum(int_mask, rm, ids_list)
    is_compact: dict[int, bool] = {
        int(rid): bool(interior_counts[i] > 0) for i, rid in enumerate(ids_list)
    }
    n_slivers_initial = sum(1 for v in is_compact.values() if not v)

    adj = vectorized_adjacency(rm)
    for rid in ids_list:
        adj.setdefault(int(rid), set())

    parent: dict[int, int] = {int(rid): int(rid) for rid in ids_list}

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            nxt = parent[x]
            parent[x] = root
            x = nxt
        return root

    protected: set[int] = set()
    merged_count = 0
    sliver_forced_merges = 0
    deltae_protected_sum = 0.0
    deltae_protected_n = 0
    pass_idx = 0

    for pass_idx in range(max_passes):
        candidates = [
            rid for rid in adj.keys()
            if find(rid) == rid
            and rid not in protected
            and (
                areas[rid] < min_area
                or (areas[rid] >= min_area and not is_compact.get(rid, True))
            )
        ]
        if not candidates:
            break
        candidates.sort(key=lambda x: areas[x])
        changed = False

        for rid in candidates:
            if find(rid) != rid:
                continue
            if rid in protected:
                continue

            small = areas[rid] < min_area
            compact = is_compact.get(rid, True)

            if not small and compact:
                continue

            neighbor_roots: set[int] = set()
            for nb in list(adj[rid]):
                root = find(nb)
                if root != rid:
                    neighbor_roots.add(root)
            if not neighbor_roots:
                continue

            if not compact:
                best_n = max(neighbor_roots, key=lambda n: areas[n])
                _do_merge(rid, best_n, neighbor_roots, areas, means, adj, parent)
                sliver_forced_merges += 1
                merged_count += 1
                changed = True
                continue

            my_lab = means[rid]
            deltaEs = [float(np.linalg.norm(my_lab - means[n])) for n in neighbor_roots]
            mean_de = sum(deltaEs) / len(deltaEs)

            if mean_de >= contrast_thresh:
                protected.add(rid)
                deltae_protected_sum += mean_de
                deltae_protected_n += 1
                continue

            best_n = max(neighbor_roots, key=lambda n: areas[n])
            _do_merge(rid, best_n, neighbor_roots, areas, means, adj, parent)
            merged_count += 1
            changed = True

        if not changed:
            break

    max_id = max(parent.keys()) if parent else 0
    translate = np.arange(max_id + 1, dtype=np.int32)
    for rid in parent.keys():
        translate[rid] = find(rid)
    new_rm = translate[rm]

    n_final = int(len(np.unique(new_rm)))
    protected_final_ids = sorted(int(rid) for rid in protected)

    return new_rm, {
        "merged_count": merged_count,
        "sliver_forced_merges": sliver_forced_merges,
        "protected_count": len(protected),
        "protected_final_ids": protected_final_ids,
        "slivers_initial": n_slivers_initial,
        "regions_final": n_final,
        "min_area_px": min_area,
        "passes_used": pass_idx + 1,
    }


# ============================================================================
# G2 enfant — smooth_merge_similar + masque de traits (verbatim g2_partition.py)
# ============================================================================
def _make_state(rm: np.ndarray, lab_image: np.ndarray):
    ids_arr = np.unique(rm)
    ids_list = ids_arr.tolist()
    areas_arr = np.bincount(rm.ravel())
    areas = {int(rid): int(areas_arr[rid]) for rid in ids_list}

    L_means = ndi.mean(lab_image[..., 0], rm, ids_list)
    a_means = ndi.mean(lab_image[..., 1], rm, ids_list)
    b_means = ndi.mean(lab_image[..., 2], rm, ids_list)
    means = {
        int(rid): np.array([L_means[i], a_means[i], b_means[i]], dtype=np.float64)
        for i, rid in enumerate(ids_list)
    }

    adj = vectorized_adjacency(rm)
    for rid in ids_list:
        adj.setdefault(int(rid), set())

    parent = {int(rid): int(rid) for rid in ids_list}

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            nxt = parent[x]
            parent[x] = root
            x = nxt
        return root

    return ids_list, areas, means, adj, parent, find


def _merge_into(small: int, large: int, areas, means, adj, parent, find_fn):
    new_area = areas[large] + areas[small]
    means[large] = (means[large] * areas[large] + means[small] * areas[small]) / new_area
    areas[large] = new_area
    for n in list(adj[small]):
        root = find_fn(n)
        if root == large or root == small:
            continue
        adj[large].add(root)
        if root in adj:
            adj[root].discard(small)
            adj[root].add(large)
    parent[small] = large


def _relabel(rm: np.ndarray, parent: dict[int, int], find_fn) -> np.ndarray:
    if not parent:
        return rm
    max_id = max(parent.keys())
    translate = np.arange(max_id + 1, dtype=np.int32)
    for rid in parent.keys():
        translate[rid] = find_fn(rid)
    return translate[rm]


def smooth_merge_similar(
    region_map: np.ndarray,
    lab_image: np.ndarray,
    thresh: float,
    max_passes: int = 8,
    protected_ids: set[int] | None = None,
) -> tuple[np.ndarray, int]:
    """Fusion greedy des régions adjacentes de ΔE < seuil (niveau enfant).
    Verbatim g2_partition.py — immunité ``protected_ids``."""
    if thresh <= 0:
        return region_map, 0
    if protected_ids is None:
        protected_ids = set()

    rm = region_map.copy()
    ids_list, areas, means, adj, parent, find = _make_state(rm, lab_image)

    merged_count = 0
    for _ in range(max_passes):
        seen = set()
        pairs: list[tuple[float, int, int]] = []
        for rid in list(adj.keys()):
            if find(rid) != rid:
                continue
            if rid in protected_ids:
                continue
            for nb in adj[rid]:
                nb_root = find(nb)
                if nb_root == rid or nb_root in protected_ids:
                    continue
                key = (min(rid, nb_root), max(rid, nb_root))
                if key in seen:
                    continue
                seen.add(key)
                de = float(np.linalg.norm(means[rid] - means[nb_root]))
                if de < thresh:
                    pairs.append((de, rid, nb_root))
        if not pairs:
            break
        pairs.sort(key=lambda x: x[0])
        changed = False
        for de, a, b in pairs:
            a_root = find(a)
            b_root = find(b)
            if a_root == b_root or a_root in protected_ids or b_root in protected_ids:
                continue
            small, large = (
                (a_root, b_root) if areas[a_root] < areas[b_root] else (b_root, a_root)
            )
            _merge_into(small, large, areas, means, adj, parent, find)
            merged_count += 1
            changed = True
        if not changed:
            break

    return _relabel(rm, parent, find), merged_count


def build_line_mask(rgb_smoothed: np.ndarray, L_threshold: float = LINES_L_THRESHOLD) -> np.ndarray:
    """Masque binaire des traits noirs : L < seuil sur image lissée, close 3×3.
    Retourne uint8 0/255. Verbatim g2_partition.py."""
    lab = rgb2lab(rgb_smoothed).astype(np.float32)
    mask = (lab[..., 0] < L_threshold).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return (mask * 255).astype(np.uint8)


def compute_region_colors_from_original(
    original_rgb: np.ndarray, region_map: np.ndarray,
) -> dict[int, dict]:
    """Couleur moyenne (Lab + hex) par région, depuis le PNG original.
    Verbatim g5_product.py (calcul Lab moyen puis reconversion sRGB)."""
    from skimage.color import lab2rgb

    out: dict[int, dict] = {}
    ids = np.unique(region_map).tolist()
    rgb_norm = original_rgb.astype(np.float64) / 255.0
    lab_full = rgb2lab(rgb_norm)
    for rid in ids:
        mask = region_map == rid
        if not mask.any():
            continue
        lab_mean = lab_full[mask].mean(axis=0)
        lab_arr = np.array([[list(lab_mean)]], dtype=np.float64)
        rgb_back = lab2rgb(lab_arr)
        r, g, b = (np.clip(rgb_back[0, 0] * 255.0, 0, 255)).astype(np.uint8).tolist()
        hex_str = f"#{r:02X}{g:02X}{b:02X}"
        out[int(rid)] = {
            "lab": tuple(float(v) for v in lab_mean),
            "hex": hex_str,
        }
    return out


# ============================================================================
# G3 — vectorisation des polygones de régions (verbatim g3_vectorize.py)
# ============================================================================
def chaikin_closed(points: np.ndarray, iterations: int = 1) -> np.ndarray:
    if len(points) < 3:
        return points
    pts = np.asarray(points, dtype=np.float64)
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
    poly = poly.copy().astype(np.float64)
    poly[poly[:, 0] < eps, 0] = -1.0
    poly[poly[:, 0] > H - 1 - eps, 0] = float(H)
    poly[poly[:, 1] < eps, 1] = -1.0
    poly[poly[:, 1] > W - 1 - eps, 1] = float(W)
    return poly


def extract_region_polygons(
    region_map: np.ndarray, dp_tol: float, chaikin_iters: int,
) -> list[tuple[int, list[np.ndarray]]]:
    """Pour chaque région : (id, [polylines fermées (M,2)]). Padding sentinel
    pour tracer les régions de bord intégralement. Verbatim g3_vectorize.py."""
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


def _signed_area(poly: np.ndarray) -> float:
    if len(poly) < 3:
        return 0.0
    x = poly[:, 1]
    y = poly[:, 0]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


# ============================================================================
# G4 — arcs topologiques + classification ink/shading (verbatim g4_two_weight.py)
# ============================================================================
def extract_topological_arcs(label_map: np.ndarray) -> tuple[list[dict], dict]:
    """Graphe des frontières partagées : chaque arc tracé UNE fois.
    Verbatim g4_two_weight.py."""
    H, W = label_map.shape
    sentinel = int(label_map.max()) + 1
    padded = np.full((H + 2, W + 2), sentinel, dtype=label_map.dtype)
    padded[1:-1, 1:-1] = label_map

    left = padded[:, :-1]
    right = padded[:, 1:]
    vmask = left != right
    vrows, vcols = np.where(vmask)

    top = padded[:-1, :]
    bot = padded[1:, :]
    hmask = top != bot
    hrows, hcols = np.where(hmask)

    corner_neighbors: dict[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]]] = (
        defaultdict(list)
    )

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

    junctions: set[tuple[int, int]] = set()
    for corner, nbrs in corner_neighbors.items():
        if len(nbrs) > 2:
            junctions.add(corner)

    arcs: list[dict] = []
    visited: set[frozenset[tuple[int, int]]] = set()

    def make_crack_id(a, b):
        return frozenset({a, b})

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


def classify_arc_into_ink_or_shading(
    arc_points: list[tuple[float, float]],
    dilated_line_mask: np.ndarray,
    threshold: float = INK_OVERLAP_THRESHOLD,
) -> tuple[str, float]:
    """Rasterise l'arc en ligne 1px et mesure son overlap avec le masque dilaté.
    Verbatim g4_two_weight.py."""
    H, W = dilated_line_mask.shape
    canvas = np.zeros((H, W), dtype=np.uint8)
    pts = np.array(arc_points, dtype=np.float64)
    if len(pts) < 2:
        return "shading", 0.0
    pts_int = np.round(pts).astype(np.int32)
    pts_int[:, 0] = np.clip(pts_int[:, 0], 0, H - 1)
    pts_int[:, 1] = np.clip(pts_int[:, 1], 0, W - 1)
    pts_xy = pts_int[:, [1, 0]].reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts_xy], isClosed=False, color=255, thickness=1, lineType=cv2.LINE_8)
    arc_mask = canvas > 0
    total = int(arc_mask.sum())
    if total == 0:
        return "shading", 0.0
    overlap = int((arc_mask & (dilated_line_mask > 0)).sum())
    ratio = overlap / total
    return ("ink" if ratio >= threshold else "shading"), ratio


def measure_line_thickness(line_mask: np.ndarray) -> float:
    """Épaisseur médiane = 2 × median(distance transform). Verbatim g4_two_weight.py."""
    line_bin = (line_mask > 127).astype(np.uint8)
    if line_bin.sum() == 0:
        return 3.0
    dist = cv2.distanceTransform(line_bin, cv2.DIST_L2, 5)
    inside = dist[line_bin > 0]
    return float(2.0 * np.median(inside))


def smooth_open_arc(
    arc_points: list[tuple[float, float]],
    dp_tol: float,
    chaikin_iters: int,
    H: int,
    W: int,
    edge_eps: float = 3.0,
) -> np.ndarray:
    """DP + Chaikin OUVERT (pas de fermeture), skip Chaikin si touche bord.
    Verbatim g4_two_weight.py."""
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
# G5 — produit : régions-encre + mapping crayon + SVG bicouche
# ============================================================================
def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_lab_single(rgb: tuple[int, int, int]) -> np.ndarray:
    arr = np.array([[list(rgb)]], dtype=np.uint8)
    lab = rgb2lab(arr / 255.0)
    return lab[0, 0]


def build_crayons_lab() -> list[dict]:
    out = []
    for c in CRAYONS:
        lab = _rgb_to_lab_single(_hex_to_rgb(c["hex"]))
        out.append({**c, "lab": tuple(float(v) for v in lab)})
    return out


def nearest_crayon(region_lab: tuple[float, float, float],
                   crayons_lab: list[dict]) -> dict:
    """Crayon le plus proche en distance Lab Euclidienne (ΔE76). Verbatim g5_product.py."""
    rl = np.array(region_lab, dtype=np.float64)
    best = None
    best_d = float("inf")
    for c in crayons_lab:
        cl = np.array(c["lab"], dtype=np.float64)
        d = float(np.linalg.norm(rl - cl))
        if d < best_d:
            best_d = d
            best = c
    return {**best, "delta_e": round(best_d, 2)}


def compute_ink_regions(
    region_map: np.ndarray,
    line_mask_dilated: np.ndarray,
    threshold: float = INK_REGION_OVERLAP_THRESHOLD,
) -> tuple[set[int], dict[int, float]]:
    """Régions dont l'overlap avec le masque de traits dilaté ≥ seuil =
    régions-encre. Verbatim g5_product.py."""
    ink_mask = line_mask_dilated > 0
    ids = np.unique(region_map).tolist()
    ratios: dict[int, float] = {}
    ink_ids: set[int] = set()
    for rid in ids:
        mask = region_map == rid
        n_pix = int(mask.sum())
        if n_pix == 0:
            continue
        n_overlap = int((mask & ink_mask).sum())
        ratio = n_overlap / n_pix
        ratios[int(rid)] = round(ratio, 3)
        if ratio >= threshold:
            ink_ids.add(int(rid))
    return ink_ids, ratios


def build_decoloriage_svg(
    region_polys: list[tuple[int, list[np.ndarray]]],
    region_data: dict[int, dict],
    arcs_classified: list[dict],
    ink_w: float,
    shading_w: float,
    H: int,
    W: int,
    ink_region_ids: set[int] | None = None,
) -> str:
    """SVG bicouche click-to-fill. Verbatim build_g5_svg de g5_product.py.

    - <g id="fills" fill-rule="evenodd"> : un <path> par région cliquable
      (data-region-id / data-color / data-original / data-crayon-name /
      data-delta-e). Régions-encre = #111111 plein, pointer-events:none.
    - <g id="strokes" pointer-events="none"> : arcs ink (visibles) + arcs
      shading (class="arc-shading", masqués par CSS sauf .show-guides).
    """
    if ink_region_ids is None:
        ink_region_ids = set()
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'shape-rendering="geometricPrecision">'
    ]
    lines.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

    lines.append('<g id="fills" stroke="none" fill-rule="evenodd">')

    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))

    for rid, polys in sorted_polys:
        d_parts: list[str] = []
        for poly in polys:
            d_parts.append(f"M{poly[0][1]:.2f},{poly[0][0]:.2f}")
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            d_parts.append("Z")
        d_attr = " ".join(d_parts)

        if rid in ink_region_ids:
            lines.append(
                f'<path class="ink-region" '
                f'data-region-id="{rid}" '
                f'fill="{INK_REGION_FILL}" '
                f'pointer-events="none" '
                f'd="{d_attr}"/>'
            )
            continue

        data = region_data.get(rid)
        if data is None:
            continue
        bg_class = " region-bg" if data["is_background"] else ""
        lines.append(
            f'<path class="region{bg_class}" '
            f'data-region-id="{rid}" '
            f'data-color="{data["crayon_hex"]}" '
            f'data-original="{data["hex_original"]}" '
            f'data-crayon-name="{data["crayon_name"]}" '
            f'data-delta-e="{data["delta_e"]}" '
            f'fill="#ffffff" '
            f'd="{d_attr}"/>'
        )
    lines.append("</g>")

    lines.append(
        f'<g id="strokes" fill="none" stroke="#15151B" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'pointer-events="none">'
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
        cls_attr = ' class="arc-ink"' if cls == "ink" else ' class="arc-shading"'
        lines.append(
            f'<path{cls_attr} d="{" ".join(d_parts)}" stroke-width="{sw:.2f}"/>'
        )
    lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines)


# ============================================================================
# Façade
# ============================================================================
@dataclass
class RegionMeta:
    """Métadonnée d'une région du SVG bicouche."""
    id: int
    crayon_name: str | None
    crayon_hex: str | None
    original_hex: str | None
    is_ink: bool
    delta_e: float


@dataclass
class DecoloriageResult:
    """Résultat de ``decolorize`` : SVG bicouche + métadonnées de régions."""
    svg: str
    regions: list[RegionMeta]
    n_clickable: int
    publishable_tp: bool
    crayon_distribution: dict[str, int]
    delta_e_median: float
    # Métadonnées additionnelles (non contractuelles mais utiles au rapport)
    level: str = "enfant"
    image_size: tuple[int, int] = (0, 0)
    n_ink_regions: int = 0
    n_arcs: int = 0
    n_ink_arcs: int = 0
    n_shading_arcs: int = 0
    ink_stroke_width: float = 0.0
    shading_stroke_width: float = 0.0
    timing_s: float = 0.0
    hollow_tube_candidates: list[dict] = field(default_factory=list)

    def to_metadata(self) -> dict:
        """Sérialise les métadonnées pour ``ImageOutput.model_config`` (JSON-safe).

        Toutes les valeurs sont des types Python natifs (``str``/``int``/
        ``float``/``bool``/``dict``) — aucun ``numpy.*`` — de sorte que
        ``json.dumps`` ne lève jamais. NULL-safe sur les numériques.

        Clés (contrat Phase 2) :
            - ``coloring_engine`` : ``"decoloriage"``
            - ``level`` : niveau de partition (``"enfant"`` en v1)
            - ``n_clickable`` : nombre de régions cliquables
            - ``n_ink_regions`` : nombre de régions-encre (non cliquables)
            - ``publishable_tp`` : éligibilité tout-petit (info, D5)
            - ``crayon_distribution`` : ``{hex: count}`` des crayons utilisés
            - ``delta_e_median`` : ΔE médian des régions cliquables non-fond
            - ``processing_s`` : temps de traitement (s)
        """
        distribution = {
            str(hex_str): int(cnt) if cnt is not None else 0
            for hex_str, cnt in (self.crayon_distribution or {}).items()
        }
        return {
            "coloring_engine": COLORING_ENGINE,
            "level": str(self.level),
            "n_clickable": int(self.n_clickable) if self.n_clickable is not None else 0,
            "n_ink_regions": int(self.n_ink_regions) if self.n_ink_regions is not None else 0,
            "publishable_tp": bool(self.publishable_tp),
            "crayon_distribution": distribution,
            "delta_e_median": (
                float(self.delta_e_median) if self.delta_e_median is not None else 0.0
            ),
            "processing_s": float(self.timing_s) if self.timing_s is not None else 0.0,
        }


def decolorize(png_path: Path | str, level: str = "enfant") -> DecoloriageResult:
    """Décolorie un PNG colorié pastel en SVG bicouche click-to-fill.

    Chaîne complète G1a v3 → G2 enfant → G3 → G4 → G5 portée verbatim du POC.
    Niveau ``enfant`` uniquement en v1 (D5). Ne touche aucune base de données.

    Args:
        png_path: chemin du PNG colorié (sortie ERNIE pastel).
        level: niveau de partition. Seul ``enfant`` est supporté en Phase 1.

    Returns:
        DecoloriageResult (svg bicouche, régions, métriques).
    """
    if level != "enfant":
        raise ValueError(
            f"Seul le niveau 'enfant' est supporté en v1 (D5), reçu {level!r}."
        )

    png_path = Path(png_path)
    if not png_path.exists():
        raise FileNotFoundError(f"PNG introuvable : {png_path}")

    t_total = time.time()
    logger.info("decoloriage start png=%s level=%s", png_path.name, level)

    # --- Charger l'original (BGR par cv2) ---
    orig_bgr = cv2.imread(str(png_path), cv2.IMREAD_COLOR)
    if orig_bgr is None:
        raise DecoloriageError(
            f"Image illisible (cv2.imread a renvoyé None) : {png_path}"
        )
    orig_rgb = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2RGB)
    H, W = orig_rgb.shape[:2]
    if H == 0 or W == 0:
        raise DecoloriageError(
            f"Image de dimension nulle ({W}x{H}) : {png_path}"
        )

    # --- G1a v3 : meanshift + k-means Lab + CC + merge_v3 ---
    rgb_smoothed = preprocess_meanshift(orig_rgb, sp=G1A_SP, sr=G1A_SR)
    cl, lab = kmeans_lab(rgb_smoothed, k=G1A_K)
    rm = connected_regions(cl)
    rm_v3, v3_stats = merge_v3(
        rm, lab,
        min_area_ratio=G1A_MERGE_THRESH,
        contrast_thresh=G1A_CONTRAST_THRESH,
    )
    protected_ids: set[int] = set(v3_stats.get("protected_final_ids", []))

    # --- G2 enfant : smooth_merge_similar (thresh=12, protected immunes) ---
    rm_enfant, _n_smooth = smooth_merge_similar(
        rm_v3, lab,
        thresh=ENFANT_SMOOTH_MERGE_THRESH,
        protected_ids=protected_ids,
    )

    n_regions_enfant = int(len(np.unique(rm_enfant)))
    if n_regions_enfant == 0:
        raise DecoloriageError(f"Segmentation vide (0 région) : {png_path}")

    # --- Masque de traits (L<25 + close 3×3) ---
    line_mask = build_line_mask(rgb_smoothed, L_threshold=LINES_L_THRESHOLD)
    if int((line_mask > 0).sum()) == 0:
        raise DecoloriageError(
            f"Masque de traits vide (aucun pixel L<{LINES_L_THRESHOLD}) : {png_path}"
        )

    # publishable_tp : règle G2 (decoloriage-tout-petit-conditional).
    # Calculée pour info (D5) : on évalue la partition tout-petit serait-elle
    # publiable. En v1 on n'expose pas tout-petit ; on calcule la métrique sur
    # la partition enfant non-protégée vs protégée comme proxy documenté.
    n_protected = len(protected_ids)
    n_non_protected = n_regions_enfant - n_protected
    publishable_tp = bool(n_non_protected <= 12 and n_protected <= 15)

    # --- Couleurs originales par région + mapping crayon (G5) ---
    region_colors = compute_region_colors_from_original(orig_rgb, rm_enfant)
    crayons_lab = build_crayons_lab()
    region_data: dict[int, dict] = {}
    crayons_used: dict[str, int] = {}
    for rid_int, c in region_colors.items():
        is_bg = c["lab"][0] >= BACKGROUND_L_THRESHOLD
        if is_bg:
            crayon_hex = "#ffffff"
            crayon_name = "Papier"
            delta_e = 0.0
        else:
            crayon = nearest_crayon(c["lab"], crayons_lab)
            crayon_hex = crayon["hex"]
            crayon_name = crayon["name"]
            delta_e = crayon["delta_e"]
        region_data[rid_int] = {
            "hex_original": c["hex"],
            "lab": c["lab"],
            "crayon_hex": crayon_hex,
            "crayon_name": crayon_name,
            "delta_e": delta_e,
            "is_background": is_bg,
        }
        crayons_used[crayon_hex] = crayons_used.get(crayon_hex, 0) + 1

    # --- Épaisseur trait + dilatation masque (G4) ---
    median_thickness = measure_line_thickness(line_mask)
    ink_w = max(2.0, median_thickness)
    shading_w = max(1.0, ink_w * SHADING_RATIO)
    kernel = np.ones((LINE_MASK_DILATE_PX, LINE_MASK_DILATE_PX), np.uint8)
    line_mask_dilated = cv2.dilate(line_mask, kernel, iterations=1)

    # --- Arcs topologiques + classification (G4) ---
    arcs, _arc_stats = extract_topological_arcs(rm_enfant)
    n_ink = 0
    n_shading = 0
    arcs_classified: list[dict] = []
    for arc in arcs:
        cls, ratio = classify_arc_into_ink_or_shading(arc["points"], line_mask_dilated)
        smoothed = smooth_open_arc(arc["points"], DP_TOLERANCE, CHAIKIN_ITERS_ARC, H, W)
        arcs_classified.append({**arc, "class": cls, "smoothed": smoothed})
        if cls == "ink":
            n_ink += 1
        else:
            n_shading += 1

    # --- Régions-encre (G5, overlap ≥ 50 %) ---
    ink_region_ids, ink_overlap_ratios = compute_ink_regions(
        rm_enfant, line_mask_dilated, INK_REGION_OVERLAP_THRESHOLD,
    )
    for rid_int in ink_region_ids:
        if rid_int in region_data:
            data = region_data[rid_int]
            crayons_used[data["crayon_hex"]] = max(
                0, crayons_used.get(data["crayon_hex"], 0) - 1,
            )

    # --- Polygones de fill (G3) ---
    region_polys = extract_region_polygons(rm_enfant, DP_TOLERANCE, CHAIKIN_ITERS_REGION)

    # --- SVG bicouche (G5) ---
    svg_text = build_decoloriage_svg(
        region_polys, region_data, arcs_classified, ink_w, shading_w, H, W,
        ink_region_ids=ink_region_ids,
    )

    # --- Métriques ---
    n_clickable = len(region_data) - len(ink_region_ids)

    delta_es = [
        data["delta_e"]
        for rid_int, data in region_data.items()
        if rid_int not in ink_region_ids and not data["is_background"]
    ]
    delta_e_median = float(np.median(delta_es)) if delta_es else 0.0

    hollow_tube_candidates: list[dict] = []
    for rid_int, data in region_data.items():
        if rid_int in ink_region_ids or data["is_background"]:
            continue
        ratio = ink_overlap_ratios.get(rid_int, 0.0)
        if ratio > HOLLOW_TUBE_OVERLAP_THRESHOLD:
            hollow_tube_candidates.append({
                "id": rid_int,
                "overlap_ratio": round(ratio, 3),
                "crayon_name": data["crayon_name"],
                "delta_e": data["delta_e"],
            })

    # --- RegionMeta list (NULL-safe, types JSON natifs) ---
    regions_meta: list[RegionMeta] = []
    for rid_int, data in sorted(region_data.items()):
        is_ink = rid_int in ink_region_ids
        if is_ink:
            regions_meta.append(RegionMeta(
                id=int(rid_int),
                crayon_name=None,
                crayon_hex=INK_REGION_FILL,
                original_hex=data["hex_original"],
                is_ink=True,
                delta_e=0.0,
            ))
        else:
            regions_meta.append(RegionMeta(
                id=int(rid_int),
                crayon_name=data["crayon_name"],
                crayon_hex=data["crayon_hex"],
                original_hex=data["hex_original"],
                is_ink=False,
                delta_e=float(data["delta_e"]) if data["delta_e"] is not None else 0.0,
            ))

    elapsed = time.time() - t_total

    logger.info(
        "decoloriage done png=%s clickable=%d ink_regions=%d "
        "delta_e_median=%.2f publishable_tp=%s %.2fs",
        png_path.name, int(n_clickable), len(ink_region_ids),
        round(delta_e_median, 2), publishable_tp, elapsed,
    )

    return DecoloriageResult(
        svg=svg_text,
        regions=regions_meta,
        n_clickable=int(n_clickable),
        publishable_tp=publishable_tp,
        crayon_distribution={k: int(v) for k, v in crayons_used.items()},
        delta_e_median=round(delta_e_median, 2),
        level=level,
        image_size=(int(W), int(H)),
        n_ink_regions=len(ink_region_ids),
        n_arcs=len(arcs),
        n_ink_arcs=n_ink,
        n_shading_arcs=n_shading,
        ink_stroke_width=round(ink_w, 2),
        shading_stroke_width=round(shading_w, 2),
        timing_s=round(elapsed, 2),
        hollow_tube_candidates=hollow_tube_candidates,
    )


__all__ = [
    "decolorize",
    "DecoloriageResult",
    "RegionMeta",
    "DecoloriageError",
    "COLORING_ENGINE",
    "ALLOWED_FILL_HEXES",
    "INK_REGION_FILL",
    "CRAYONS",
]
