"""G1a v3 - Pivot 2 : pretraitement pyrMeanShift + compacite 3x3.

Pipeline par image :
  1. cv2.pyrMeanShiftFiltering(sp=12, sr=24) sur le RGB d'origine
     -> aplatit AA et degrades, frontieres preservees.
  2. K-means k=12 en Lab sur l'image LISSEE.
  3. CC 4-connexite -> region_map brut.
  4. Compacite : pour chaque region, calcul d'un masque "interieur" via
     comparaison 3x3 vectorisee. Une region SANS pixel interieur (sliver
     1-2 px de large, point isole < 9 px) = sliver -> fusion forcee dans
     le voisin dominant, sans regarder le contraste.
  5. Sinon : si aire < min_area :
        - si DeltaE76 moyen aux voisins >= 30 -> protegee legitime
        - sinon -> fusion dans le voisin de plus grande aire
  6. Relabel final.

Cible (utilisateur) : 30-150 regions/image apres nettoyage.
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
DEFAULT_OUT_DIR = Path(__file__).parent / "g1a_out_v3"


# ----------------------------------------------------------------------------
# 1) Pretraitement edge-preserving
# ----------------------------------------------------------------------------
def preprocess_meanshift(rgb: np.ndarray, sp: int = 12, sr: int = 24) -> np.ndarray:
    """cv2.pyrMeanShiftFiltering attend BGR 8-bit. Retourne RGB 8-bit lisse."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    shifted = cv2.pyrMeanShiftFiltering(bgr, sp=sp, sr=sr)
    return cv2.cvtColor(shifted, cv2.COLOR_BGR2RGB)


# ----------------------------------------------------------------------------
# 2) k-means Lab (identique v2)
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# 3) CC (identique)
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# 4) Compacite : un pixel est "interieur" si ses 8 voisins 3x3 ont le meme label.
#    Une region est compacte si >= 1 pixel interieur (= survit a une erosion 3x3).
# ----------------------------------------------------------------------------
def interior_mask_8(rm: np.ndarray) -> np.ndarray:
    """Retourne un masque booleen (H, W) : True = pixel survivant erosion 3x3."""
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


# ----------------------------------------------------------------------------
# 5) Adjacence + fusion v3
# ----------------------------------------------------------------------------
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


def merge_v3(
    region_map: np.ndarray,
    lab_image: np.ndarray,
    min_area_ratio: float,
    contrast_thresh: float,
    max_passes: int = 20,
) -> tuple[np.ndarray, dict]:
    """Pipeline fusion v3 avec compacite + ΔE."""
    h, w = region_map.shape
    total_px = h * w
    min_area = max(1, int(round(min_area_ratio * total_px)))

    rm = region_map.copy()
    ids_arr = np.unique(rm)
    ids_list = ids_arr.tolist()

    # Aires initiales
    areas_arr = np.bincount(rm.ravel())
    areas: dict[int, int] = {int(rid): int(areas_arr[rid]) for rid in ids_list}

    # Means Lab par region
    L_means = ndi.mean(lab_image[..., 0], rm, ids_list)
    a_means = ndi.mean(lab_image[..., 1], rm, ids_list)
    b_means = ndi.mean(lab_image[..., 2], rm, ids_list)
    means: dict[int, np.ndarray] = {
        int(rid): np.array([L_means[i], a_means[i], b_means[i]], dtype=np.float64)
        for i, rid in enumerate(ids_list)
    }

    # Compacite (1 calcul global)
    int_mask = interior_mask_8(rm)
    interior_counts = ndi.sum(int_mask, rm, ids_list)
    is_compact: dict[int, bool] = {
        int(rid): bool(interior_counts[i] > 0) for i, rid in enumerate(ids_list)
    }
    n_slivers_initial = sum(1 for v in is_compact.values() if not v)

    # Adjacence
    adj = vectorized_adjacency(rm)
    for rid in ids_list:
        adj.setdefault(int(rid), set())

    # Union-find
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
                # une region grande mais 1-px-wide doit aussi etre traitee si non-compacte
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

            # Region large ET compacte -> rien a faire (passe son tour)
            if not small and compact:
                continue

            neighbor_roots: set[int] = set()
            for nb in list(adj[rid]):
                root = find(nb)
                if root != rid:
                    neighbor_roots.add(root)
            if not neighbor_roots:
                continue

            # Sliver (non compact) -> fusion forcee dans voisin de plus grande aire
            if not compact:
                best_n = max(neighbor_roots, key=lambda n: areas[n])
                _do_merge(rid, best_n, neighbor_roots, areas, means, adj, parent)
                sliver_forced_merges += 1
                merged_count += 1
                changed = True
                continue

            # Compact + petit -> evaluer ΔE
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

    # protected_ids = labels finaux des regions protegees v3. Comme une region
    # protegee n'est jamais fusionnee, son id v3 (avant relabel) == son id final.
    protected_final_ids = sorted(int(rid) for rid in protected)

    return new_rm, {
        "merged_count": merged_count,
        "sliver_forced_merges": sliver_forced_merges,
        "non_sliver_merges": merged_count - sliver_forced_merges,
        "protected_count": len(protected),
        "protected_final_ids": protected_final_ids,
        "slivers_initial": n_slivers_initial,
        "regions_final": n_final,
        "min_area_px": min_area,
        "min_area_ratio": min_area_ratio,
        "contrast_threshold": contrast_thresh,
        "mean_deltaE_protected": (
            round(deltae_protected_sum / deltae_protected_n, 2) if deltae_protected_n else 0.0
        ),
        "passes_used": pass_idx + 1,
    }


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


# ----------------------------------------------------------------------------
# Render
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
    sp: int,
    sr: int,
    merge_thresh: float,
    contrast_thresh: float,
) -> tuple[np.ndarray, dict]:
    rgb = cv2.cvtColor(cv2.imread(str(img_path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape

    t0 = time.time()
    rgb_smoothed = preprocess_meanshift(rgb, sp=sp, sr=sr)
    t1 = time.time()
    cl, lab = kmeans_lab(rgb_smoothed, k=k)
    t2 = time.time()
    rm = connected_regions(cl)
    n_before_cc = int(len(np.unique(rm)))
    t3 = time.time()
    rm_merged, merge_stats = merge_v3(
        rm, lab, min_area_ratio=merge_thresh, contrast_thresh=contrast_thresh
    )
    t4 = time.time()
    render = render_with_outline(rm_merged, seed=int(np.sum(rm_merged) % 9973))
    t5 = time.time()

    stats = {
        "image_size": [int(w), int(h)],
        "k": k,
        "meanshift_sp": sp,
        "meanshift_sr": sr,
        "merge_thresh_ratio": merge_thresh,
        "contrast_threshold": contrast_thresh,
        "regions_before_merge": n_before_cc,
        "regions_final": merge_stats["regions_final"],
        "protected_legitimate": merge_stats["protected_count"],
        "sliver_forced_merges": merge_stats["sliver_forced_merges"],
        "non_sliver_merges": merge_stats["non_sliver_merges"],
        "slivers_initial": merge_stats["slivers_initial"],
        "mean_deltaE_protected": merge_stats["mean_deltaE_protected"],
        "passes_used": merge_stats["passes_used"],
        "timing_s": {
            "meanshift": round(t1 - t0, 2),
            "kmeans": round(t2 - t1, 2),
            "cc": round(t3 - t2, 2),
            "merge": round(t4 - t3, 2),
            "render": round(t5 - t4, 2),
            "total": round(t5 - t0, 2),
        },
    }
    return render, stats


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="G1a v3 pivot : pyrMeanShift + compacite + ΔE")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--k", type=int, default=12)
    parser.add_argument("--sp", type=int, default=12)
    parser.add_argument("--sr", type=int, default=24)
    parser.add_argument("--merge-thresh", type=float, default=0.0005)
    parser.add_argument("--protect-contrast", type=float, default=30.0)
    args = parser.parse_args()

    data = json.loads(args.corpus.read_text(encoding="utf-8"))
    items = data["images"]

    args.out.mkdir(parents=True, exist_ok=True)
    all_stats = {
        "params": {
            "k": args.k,
            "meanshift_sp": args.sp,
            "meanshift_sr": args.sr,
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
        print(f"[G1a v3] #{slot:02d} {rid} ...", flush=True)
        render, stats = process_image(
            src,
            k=args.k,
            sp=args.sp,
            sr=args.sr,
            merge_thresh=args.merge_thresh,
            contrast_thresh=args.protect_contrast,
        )
        out_png = args.out / f"{slot:02d}_{rid}_regions_v3.png"
        cv2.imwrite(str(out_png), cv2.cvtColor(render, cv2.COLOR_RGB2BGR))
        stats["slot"] = slot
        stats["id"] = rid
        stats["category"] = item["category"]
        stats["out_png"] = str(out_png.relative_to(PROJECT_ROOT)).replace("\\", "/")
        all_stats["images"].append(stats)
        print(
            f"       brut: {stats['regions_before_merge']}  ->  "
            f"final: {stats['regions_final']}  |  "
            f"protected legit: {stats['protected_legitimate']}  |  "
            f"slivers force: {stats['sliver_forced_merges']}  |  "
            f"t {stats['timing_s']['total']}s"
        )

    stats_path = args.out / "stats.json"
    stats_path.write_text(json.dumps(all_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK stats : {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
