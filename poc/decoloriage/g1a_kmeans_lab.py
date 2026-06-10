"""G1a - Quantification couleur voie pauvre (OpenCV pur).

Pour chaque image du corpus :
  1. Convertit RGB -> Lab (skimage)
  2. K-means k=12 sur les pixels Lab
  3. Connected components (4-connexite) par cluster
  4. Fusion des regions d'aire < 0.3 % de l'image vers le voisin
     dominant (plus grand voisin direct)
  5. Re-label final + couleurs aleatoires par region

Sortie : un PNG par image dans poc/decoloriage/g1a_out/<id>_regions.png
+ un JSON de stats poc/decoloriage/g1a_out/stats.json.

Usage :
    python poc/decoloriage/g1a_kmeans_lab.py
    python poc/decoloriage/g1a_kmeans_lab.py --k 12 --merge-thresh 0.003
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
DEFAULT_OUT_DIR = Path(__file__).parent / "g1a_out"


# ----------------------------------------------------------------------------
# Etape 1+2 : Lab + k-means
# ----------------------------------------------------------------------------
def kmeans_lab(rgb: np.ndarray, k: int, seed: int = 42) -> np.ndarray:
    """Retourne un label map (H, W) int32 avec k clusters."""
    lab = rgb2lab(rgb).astype(np.float32)  # L in [0,100], a/b in [-128,127]
    h, w, _ = lab.shape
    flat = lab.reshape(-1, 3)
    # OpenCV kmeans : criteria, attempts, flags
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    # rng deterministe via cv2.setRNGSeed
    cv2.setRNGSeed(seed)
    _compact, labels, _centers = cv2.kmeans(
        flat, k, None, criteria, attempts=4, flags=cv2.KMEANS_PP_CENTERS
    )
    return labels.reshape(h, w).astype(np.int32)


# ----------------------------------------------------------------------------
# Etape 3 : connected components par cluster
# ----------------------------------------------------------------------------
def connected_regions(cluster_labels: np.ndarray) -> np.ndarray:
    """Pour chaque cluster, decoupe en composantes connexes 4-connexite.

    Retourne un label map global (H, W) ou chaque region a un id unique
    (>= 1, 0 reserve pour "vide" mais on n'a pas de vide ici donc 0 absent).
    """
    h, w = cluster_labels.shape
    region_map = np.zeros((h, w), dtype=np.int32)
    next_id = 1
    struct = ndi.generate_binary_structure(2, 1)  # 4-connexite
    for c in np.unique(cluster_labels):
        mask = cluster_labels == c
        cc, n = ndi.label(mask, structure=struct)
        if n == 0:
            continue
        # decaler les ids pour rester globalement uniques
        cc[cc > 0] += next_id - 1
        region_map[mask] = cc[mask]
        next_id += n
    return region_map


# ----------------------------------------------------------------------------
# Etape 4 : fusion des petites regions
# ----------------------------------------------------------------------------
def _neighbors_4(region_map: np.ndarray, region_id: int) -> dict[int, int]:
    """Retourne {voisin_id: nb_pixels_frontiere_partages} pour un region_id."""
    mask = region_map == region_id
    # Dilate de 1 px puis XOR pour obtenir la "bordure exterieure"
    struct = ndi.generate_binary_structure(2, 1)
    dilated = ndi.binary_dilation(mask, structure=struct, iterations=1)
    border = dilated & ~mask
    neigh_ids, counts = np.unique(region_map[border], return_counts=True)
    out = {}
    for nid, cnt in zip(neigh_ids.tolist(), counts.tolist()):
        if nid != 0 and nid != region_id:
            out[nid] = cnt
    return out


def merge_small_regions(
    region_map: np.ndarray,
    min_area_ratio: float,
    max_passes: int = 6,
) -> tuple[np.ndarray, dict[str, int]]:
    """Fusionne iterativement les regions < min_area_ratio dans leur plus
    grand voisin direct. Retourne (new_region_map, stats)."""
    h, w = region_map.shape
    total_px = h * w
    min_area = max(1, int(round(min_area_ratio * total_px)))

    rm = region_map.copy()
    merged_count = 0

    for _pass in range(max_passes):
        ids, counts = np.unique(rm, return_counts=True)
        small = [
            (rid, cnt)
            for rid, cnt in zip(ids.tolist(), counts.tolist())
            if cnt < min_area
        ]
        if not small:
            break
        # Trier du plus petit au plus grand pour stabilite
        small.sort(key=lambda x: x[1])
        changed = False
        for rid, _cnt in small:
            if (rm == rid).sum() == 0:
                continue  # deja absorbe
            neighbors = _neighbors_4(rm, rid)
            if not neighbors:
                continue
            # Choisir le voisin avec la plus grande aire totale (pas seulement la plus grande frontiere)
            best_nid = max(
                neighbors.keys(),
                key=lambda nid: int((rm == nid).sum()),
            )
            rm[rm == rid] = best_nid
            merged_count += 1
            changed = True
        if not changed:
            break

    return rm, {
        "merged_count": merged_count,
        "min_area_px": min_area,
        "min_area_ratio": min_area_ratio,
    }


# ----------------------------------------------------------------------------
# Render : couleurs aleatoires par region
# ----------------------------------------------------------------------------
def render_random_colors(region_map: np.ndarray, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ids = np.unique(region_map)
    palette = rng.integers(40, 240, size=(int(ids.max()) + 2, 3), dtype=np.uint8)
    out = palette[region_map]
    return out  # (H, W, 3) RGB uint8


def render_with_outline(region_map: np.ndarray, seed: int = 0, outline: int = 1) -> np.ndarray:
    """Render couleurs aleatoires + contour noir 1 px sur frontieres entre regions."""
    base = render_random_colors(region_map, seed=seed)
    # frontieres
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
) -> tuple[np.ndarray, dict]:
    rgb = cv2.cvtColor(cv2.imread(str(img_path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape

    t0 = time.time()
    cl = kmeans_lab(rgb, k=k)
    t1 = time.time()
    rm = connected_regions(cl)
    n_before = len(np.unique(rm))
    t2 = time.time()
    rm_merged, merge_stats = merge_small_regions(rm, min_area_ratio=merge_thresh)
    n_after = len(np.unique(rm_merged))
    t3 = time.time()
    render = render_with_outline(rm_merged, seed=int(np.sum(rm_merged) % 9973))
    t4 = time.time()

    stats = {
        "image_size": [int(w), int(h)],
        "k": k,
        "merge_thresh_ratio": merge_thresh,
        "regions_before_merge": int(n_before),
        "regions_after_merge": int(n_after),
        "merged_regions": merge_stats["merged_count"],
        "min_area_px": merge_stats["min_area_px"],
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
    parser = argparse.ArgumentParser(description="G1a kmeans Lab pipeline")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--k", type=int, default=12, help="K clusters (10..14)")
    parser.add_argument("--merge-thresh", type=float, default=0.003,
                        help="Fusion regions < ratio * area (default 0.003 = 0.3%%)")
    args = parser.parse_args()

    data = json.loads(args.corpus.read_text(encoding="utf-8"))
    items = data["images"]

    args.out.mkdir(parents=True, exist_ok=True)
    all_stats = {"params": {"k": args.k, "merge_thresh": args.merge_thresh}, "images": []}

    for item in items:
        src = (PROJECT_ROOT / item["path"]).resolve()
        slot = item["slot"]
        rid = item["id"]
        if not src.exists():
            print(f"[SKIP] #{slot} {rid} : fichier absent {src}", file=sys.stderr)
            continue
        print(f"[G1a] #{slot:02d} {rid} ...", flush=True)
        render, stats = process_image(src, k=args.k, merge_thresh=args.merge_thresh)
        out_png = args.out / f"{slot:02d}_{rid}_regions.png"
        cv2.imwrite(str(out_png), cv2.cvtColor(render, cv2.COLOR_RGB2BGR))
        stats["slot"] = slot
        stats["id"] = rid
        stats["category"] = item["category"]
        stats["out_png"] = str(out_png.relative_to(PROJECT_ROOT)).replace("\\", "/")
        all_stats["images"].append(stats)
        print(
            f"       regions: {stats['regions_before_merge']} -> "
            f"{stats['regions_after_merge']} (fusion {stats['merged_regions']}) | "
            f"total {stats['timing_s']['total']}s"
        )

    stats_path = args.out / "stats.json"
    stats_path.write_text(json.dumps(all_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK stats : {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
