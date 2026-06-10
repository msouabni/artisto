"""G1a v2 - Pivot : seuil fusion 0.05 % + protection ΔE Lab.

Different de v1 :
  - min_area_ratio = 0.0005 (0.05 %, contre 0.003 = 0.3 % en v1)
  - Regle de protection : ne JAMAIS fusionner une region dont le contraste
    Lab moyen avec ses voisines depasse un seuil (default ΔE76 = 30).
    Protege les yeux, truffes, ocelles, motifs sombres internes.
  - Adjacence vectorisee (np.unique sur paires de pixels frontieres) + union-find,
    pour passer de 80s/image (v1, dilation par region) a ~few seconds/image.

Usage :
    python poc/decoloriage/g1a_v2_protected.py
    python poc/decoloriage/g1a_v2_protected.py --k 12 --merge-thresh 0.0005 --protect-contrast 30
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.color import rgb2lab


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_OUT_DIR = Path(__file__).parent / "g1a_out_v2"


# ----------------------------------------------------------------------------
# k-means + connected components (identique a v1)
# ----------------------------------------------------------------------------
def kmeans_lab(rgb: np.ndarray, k: int, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Retourne (cluster_labels_HxW, lab_image_HxWx3)."""
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
    struct = ndi.generate_binary_structure(2, 1)  # 4-connexite
    for c in np.unique(cluster_labels):
        mask = cluster_labels == c
        cc, n = ndi.label(mask, structure=struct)
        if n == 0:
            continue
        cc[cc > 0] += next_id - 1
        region_map[mask] = cc[mask]
        next_id += n
    return region_map


# ----------------------------------------------------------------------------
# Adjacence vectorisee
# ----------------------------------------------------------------------------
def vectorized_adjacency(region_map: np.ndarray) -> dict[int, set[int]]:
    """Build {label: set(neighbor labels)} from a 4-connexite graph."""
    rm = region_map
    # Paires horizontales
    a = rm[:, :-1].ravel()
    b = rm[:, 1:].ravel()
    mask = a != b
    pairs_h = np.column_stack([a[mask], b[mask]])
    # Paires verticales
    a = rm[:-1, :].ravel()
    b = rm[1:, :].ravel()
    mask = a != b
    pairs_v = np.column_stack([a[mask], b[mask]])
    pairs = np.vstack([pairs_h, pairs_v])
    if len(pairs) == 0:
        return {}
    # Canoniser (min, max) puis unique
    pairs = np.sort(pairs, axis=1)
    pairs = np.unique(pairs, axis=0)

    adj: dict[int, set[int]] = {}
    for row in pairs:
        a_id, b_id = int(row[0]), int(row[1])
        adj.setdefault(a_id, set()).add(b_id)
        adj.setdefault(b_id, set()).add(a_id)
    return adj


# ----------------------------------------------------------------------------
# Fusion avec protection ΔE
# ----------------------------------------------------------------------------
def merge_protected(
    region_map: np.ndarray,
    lab_image: np.ndarray,
    min_area_ratio: float,
    contrast_thresh: float,
    max_passes: int = 20,
) -> tuple[np.ndarray, dict]:
    """Fusionne les petites regions sauf si ΔE76 moyen avec voisines >= seuil.

    Retourne (new_region_map, stats).
    """
    h, w = region_map.shape
    total_px = h * w
    min_area = max(1, int(round(min_area_ratio * total_px)))

    rm = region_map.copy()
    ids_arr = np.unique(rm)
    ids_list = ids_arr.tolist()

    # Aires initiales (bincount = O(N))
    areas_arr = np.bincount(rm.ravel())  # size = max_id + 1
    areas: dict[int, int] = {int(rid): int(areas_arr[rid]) for rid in ids_list}

    # Means Lab par region (vectorise via scipy.ndimage.mean)
    L_means = ndi.mean(lab_image[..., 0], rm, ids_list)
    a_means = ndi.mean(lab_image[..., 1], rm, ids_list)
    b_means = ndi.mean(lab_image[..., 2], rm, ids_list)
    means: dict[int, np.ndarray] = {
        int(rid): np.array([L_means[i], a_means[i], b_means[i]], dtype=np.float64)
        for i, rid in enumerate(ids_list)
    }

    adj = vectorized_adjacency(rm)
    for rid in ids_list:
        adj.setdefault(int(rid), set())

    # Union-find
    parent: dict[int, int] = {int(rid): int(rid) for rid in ids_list}

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        # path compression
        while parent[x] != root:
            nxt = parent[x]
            parent[x] = root
            x = nxt
        return root

    protected: set[int] = set()
    merged_count = 0
    deltaE_sum = 0.0
    deltaE_n = 0
    pass_idx = 0

    for pass_idx in range(max_passes):
        candidates = [
            rid for rid in adj.keys()
            if find(rid) == rid
            and rid not in protected
            and areas[rid] < min_area
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
            if areas[rid] >= min_area:
                continue
            # Voisins courants (deduplique via find)
            neighbor_roots: set[int] = set()
            for nb in list(adj[rid]):
                root = find(nb)
                if root != rid:
                    neighbor_roots.add(root)
            if not neighbor_roots:
                continue
            # ΔE76 moyen
            my_lab = means[rid]
            deltaEs = [float(np.linalg.norm(my_lab - means[n])) for n in neighbor_roots]
            mean_de = sum(deltaEs) / len(deltaEs)
            deltaE_sum += mean_de
            deltaE_n += 1
            if mean_de >= contrast_thresh:
                protected.add(rid)
                continue
            # Fusion dans le voisin de plus grande aire
            best_n = max(neighbor_roots, key=lambda n: areas[n])
            new_area = areas[best_n] + areas[rid]
            means[best_n] = (means[best_n] * areas[best_n] + means[rid] * areas[rid]) / new_area
            areas[best_n] = new_area
            adj[best_n].update(neighbor_roots - {best_n})
            for nb in list(adj[rid]):
                root = find(nb)
                if root in adj:
                    adj[root].discard(rid)
                    if root != best_n:
                        adj[root].add(best_n)
            parent[rid] = best_n
            merged_count += 1
            changed = True
        if not changed:
            break

    # Relabel final via translation array
    max_id = max(parent.keys()) if parent else 0
    translate = np.arange(max_id + 1, dtype=np.int32)
    for rid in parent.keys():
        translate[rid] = find(rid)
    new_rm = translate[rm]

    return new_rm, {
        "merged_count": merged_count,
        "protected_count": len(protected),
        "min_area_px": min_area,
        "min_area_ratio": min_area_ratio,
        "contrast_threshold": contrast_thresh,
        "mean_deltaE_observed": round(deltaE_sum / max(1, deltaE_n), 2),
        "passes_used": pass_idx + 1,
    }


# ----------------------------------------------------------------------------
# Rendu (identique a v1)
# ----------------------------------------------------------------------------
def render_with_outline(region_map: np.ndarray, seed: int = 0, outline: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    max_id = int(region_map.max())
    palette = rng.integers(40, 240, size=(max_id + 2, 3), dtype=np.uint8)
    base = palette[region_map]
    rm = region_map
    dx = np.zeros_like(rm, dtype=bool)
    dy = np.zeros_like(rm, dtype=bool)
    dx[:, :-1] = rm[:, :-1] != rm[:, 1:]
    dy[:-1, :] = rm[:-1, :] != rm[1:, :]
    edges = dx | dy
    if outline > 1:
        edges = ndi.binary_dilation(edges, iterations=outline - 1)
    base[edges] = [10, 10, 15]
    return base


# ----------------------------------------------------------------------------
# Pipeline par image
# ----------------------------------------------------------------------------
def process_image(
    img_path: Path,
    k: int,
    merge_thresh: float,
    contrast_thresh: float,
) -> tuple[np.ndarray, dict]:
    rgb = cv2.cvtColor(cv2.imread(str(img_path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape

    t0 = time.time()
    cl, lab = kmeans_lab(rgb, k=k)
    t1 = time.time()
    rm = connected_regions(cl)
    n_before_cc = int(len(np.unique(rm)))
    t2 = time.time()
    rm_merged, merge_stats = merge_protected(
        rm, lab, min_area_ratio=merge_thresh, contrast_thresh=contrast_thresh
    )
    n_after = int(len(np.unique(rm_merged)))
    t3 = time.time()
    render = render_with_outline(rm_merged, seed=int(np.sum(rm_merged) % 9973))
    t4 = time.time()

    stats = {
        "image_size": [int(w), int(h)],
        "k": k,
        "merge_thresh_ratio": merge_thresh,
        "contrast_threshold": contrast_thresh,
        "regions_before_merge": n_before_cc,
        "regions_after_merge": n_after,
        "merged_regions": merge_stats["merged_count"],
        "protected_regions": merge_stats["protected_count"],
        "min_area_px": merge_stats["min_area_px"],
        "mean_deltaE_observed": merge_stats["mean_deltaE_observed"],
        "passes_used": merge_stats["passes_used"],
        "timing_s": {
            "kmeans": round(t1 - t0, 2),
            "cc": round(t2 - t1, 2),
            "merge": round(t3 - t2, 2),
            "render": round(t4 - t3, 2),
            "total": round(t4 - t0, 2),
        },
    }
    return render, stats


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="G1a v2 pivot : seuil 0.05% + protection ΔE")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--k", type=int, default=12)
    parser.add_argument("--merge-thresh", type=float, default=0.0005,
                        help="Fusion regions < ratio (default 0.0005 = 0.05%%)")
    parser.add_argument("--protect-contrast", type=float, default=30.0,
                        help="ΔE76 moyen >= seuil => region protegee (default 30)")
    args = parser.parse_args()

    data = json.loads(args.corpus.read_text(encoding="utf-8"))
    items = data["images"]

    args.out.mkdir(parents=True, exist_ok=True)
    all_stats = {
        "params": {
            "k": args.k,
            "merge_thresh": args.merge_thresh,
            "protect_contrast": args.protect_contrast,
        },
        "images": [],
    }

    for item in items:
        src = (PROJECT_ROOT / item["path"]).resolve()
        slot = item["slot"]
        rid = item["id"]
        if not src.exists():
            print(f"[SKIP] #{slot} {rid}", file=sys.stderr)
            continue
        print(f"[G1a v2] #{slot:02d} {rid} ...", flush=True)
        render, stats = process_image(src, k=args.k, merge_thresh=args.merge_thresh,
                                      contrast_thresh=args.protect_contrast)
        out_png = args.out / f"{slot:02d}_{rid}_regions_v2.png"
        cv2.imwrite(str(out_png), cv2.cvtColor(render, cv2.COLOR_RGB2BGR))
        stats["slot"] = slot
        stats["id"] = rid
        stats["category"] = item["category"]
        stats["out_png"] = str(out_png.relative_to(PROJECT_ROOT)).replace("\\", "/")
        all_stats["images"].append(stats)
        print(
            f"       regions: {stats['regions_before_merge']} -> "
            f"{stats['regions_after_merge']} (fusion {stats['merged_regions']}, "
            f"protected {stats['protected_regions']}) | "
            f"total {stats['timing_s']['total']}s"
        )

    stats_path = args.out / "stats.json"
    stats_path.write_text(json.dumps(all_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK stats : {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
