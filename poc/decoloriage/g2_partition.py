"""G2 (pivot v2 2026-06-10) - Partition propre 3 cadrans avec tout-petit
"familles de couleurs" + extraction colors + line masks.

Architecture :
  - base v3 unique (= G1a v3 finalise) -> rm_v3 + protected_ids canoniques.
  - adulte    : rm_v3 (smooth_merge_thresh = 0).
  - enfant    : smooth_merge_similar(rm_v3, thresh=12, protected immune).
  - tout-petit:
      1) k-means k=5 sur les CENTROIDES Lab des regions de rm_v3
         -> chaque region recoit une "famille" 0..4.
      2) Fusion iterative (union-find) des paires adjacentes de meme famille,
         protected immunes.
      3) Fallback : si > 10 non-protegees restantes, fusion greedy ΔE
         croissant jusqu'a 10.

Extractions livrees a G3/G5 :
  - stats.json : pour chaque region de chaque niveau, couleur moyenne
    issue du PNG ORIGINAL (Lab + hex). Sera le data-color + mapping
    6 crayons en G5.
  - g2_out/lines/<slot>_<id>_lines.png : masque traits noirs binaire
    (seuil L < 25 sur image lissee, ferme 3x3). Entree directe G3/G4.
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
sys.path.insert(0, str(Path(__file__).parent))

from g1a_v3_compact import (  # noqa: E402
    preprocess_meanshift,
    kmeans_lab,
    connected_regions,
    merge_v3,
    render_with_outline,
    vectorized_adjacency,
)

DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_OUT_DIR = Path(__file__).parent / "g2_out"


BASE_V3 = {
    "k": 12,
    "sp": 12,
    "sr": 24,
    "merge_thresh": 0.0005,
    "contrast_thresh": 30.0,
}

LEVELS = {
    "tout_petit": {
        "label": "tout-petit",
        "mode": "family",
        "k_families": 5,
        "fallback_target_non_protected": 10,
    },
    "enfant": {
        "label": "enfant",
        "mode": "smooth",
        "smooth_merge_thresh": 12.0,
    },
    "adulte": {
        "label": "adulte",
        "mode": "v3",
        "smooth_merge_thresh": 0.0,
    },
}

LINES_L_THRESHOLD = 25.0


# ============================================================================
# Helpers de fusion (union-find generique)
# ============================================================================
def _make_state(rm: np.ndarray, lab_image: np.ndarray):
    """Etat initial pour fusion : ids, areas, means, adj, parent + find()."""
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


# ============================================================================
# Enfant : smooth_merge_similar (ΔE < seuil, greedy)
# ============================================================================
def smooth_merge_similar(
    region_map: np.ndarray,
    lab_image: np.ndarray,
    thresh: float,
    max_passes: int = 8,
    protected_ids: set[int] | None = None,
) -> tuple[np.ndarray, int]:
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


# ============================================================================
# Tout-petit : family merge + fallback greedy
# ============================================================================
def family_merge_tout_petit(
    region_map: np.ndarray,
    lab_image: np.ndarray,
    protected_ids: set[int] | None = None,
    k_families: int = 5,
    fallback_target: int = 10,
    max_passes_family: int = 20,
    max_fallback_iters: int = 500,
) -> tuple[np.ndarray, dict]:
    """Pipeline tout-petit :
    1) k-means sur centroides Lab des regions -> familles 0..k-1.
    2) Fusion iterative des paires adjacentes de meme famille (skip protected).
    3) Fallback : si non-protegees > target, fusion greedy ΔE jusqu'a target.
    """
    if protected_ids is None:
        protected_ids = set()

    rm = region_map.copy()
    ids_list, areas, means, adj, parent, find = _make_state(rm, lab_image)
    n_regions = len(ids_list)
    if n_regions < 2:
        return rm, {
            "k_families_used": 0,
            "family_merges": 0,
            "fallback_merges": 0,
            "n_non_protected_initial": 0,
            "n_non_protected_final": 0,
        }

    # --- 1) k-means sur centroides Lab des regions ---
    centroids = np.zeros((n_regions, 3), dtype=np.float32)
    for i, rid in enumerate(ids_list):
        centroids[i] = means[int(rid)]
    k_actual = min(k_families, n_regions)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    cv2.setRNGSeed(42)
    _compact, family_labels, _centers = cv2.kmeans(
        centroids, k_actual, None, criteria, 6, cv2.KMEANS_PP_CENTERS
    )
    family_labels = family_labels.ravel()  # cv2 retourne shape (N, 1)
    family: dict[int, int] = {
        int(rid): int(family_labels[i]) for i, rid in enumerate(ids_list)
    }

    n_non_protected_initial = sum(1 for rid in ids_list if int(rid) not in protected_ids)

    # --- 2) Fusion iterative des paires adjacentes de meme famille ---
    family_merges = 0
    for _ in range(max_passes_family):
        # Construire paires de meme famille, non-protegees, par aire decroissante
        seen = set()
        pairs: list[tuple[int, int, int]] = []
        for rid in list(adj.keys()):
            if find(rid) != rid:
                continue
            if rid in protected_ids:
                continue
            for nb in adj[rid]:
                nb_root = find(nb)
                if nb_root == rid or nb_root in protected_ids:
                    continue
                if family[rid] != family[nb_root]:
                    continue
                key = (min(rid, nb_root), max(rid, nb_root))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((areas[rid] + areas[nb_root], rid, nb_root))
        if not pairs:
            break
        pairs.sort(key=lambda x: -x[0])
        changed = False
        for _pa, a, b in pairs:
            a_root = find(a)
            b_root = find(b)
            if a_root == b_root or a_root in protected_ids or b_root in protected_ids:
                continue
            if family[a_root] != family[b_root]:
                continue
            small, large = (
                (a_root, b_root) if areas[a_root] < areas[b_root] else (b_root, a_root)
            )
            _merge_into(small, large, areas, means, adj, parent, find)
            # La famille du large est conservee (par convention).
            family_merges += 1
            changed = True
        if not changed:
            break

    # --- 3) Fallback greedy ΔE croissant ---
    def count_non_protected() -> int:
        return sum(
            1
            for rid in adj.keys()
            if find(rid) == rid and rid not in protected_ids
        )

    fallback_merges = 0
    n_np = count_non_protected()
    for _ in range(max_fallback_iters):
        if n_np <= fallback_target:
            break
        # Trouver paire non-protegee de plus petit ΔE
        best: tuple[float, int, int] | None = None
        seen = set()
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
                if best is None or de < best[0]:
                    best = (de, rid, nb_root)
        if best is None:
            break
        de, a, b = best
        a_root = find(a)
        b_root = find(b)
        small, large = (
            (a_root, b_root) if areas[a_root] < areas[b_root] else (b_root, a_root)
        )
        _merge_into(small, large, areas, means, adj, parent, find)
        fallback_merges += 1
        n_np -= 1

    new_rm = _relabel(rm, parent, find)
    return new_rm, {
        "k_families_used": k_actual,
        "family_merges": family_merges,
        "fallback_merges": fallback_merges,
        "n_non_protected_initial": n_non_protected_initial,
        "n_non_protected_final": count_non_protected(),
    }


# ============================================================================
# Extractions G3/G5
# ============================================================================
def compute_region_colors_from_original(
    region_map: np.ndarray,
    rgb_original: np.ndarray,
) -> list[dict]:
    """Pour chaque region, calcule (Lab + hex sRGB) depuis l'image ORIGINALE."""
    ids_list = np.unique(region_map).tolist()
    if not ids_list:
        return []
    lab_orig = rgb2lab(rgb_original).astype(np.float32)
    r = rgb_original[..., 0].astype(np.float32)
    g = rgb_original[..., 1].astype(np.float32)
    b = rgb_original[..., 2].astype(np.float32)

    L_means = ndi.mean(lab_orig[..., 0], region_map, ids_list)
    a_means = ndi.mean(lab_orig[..., 1], region_map, ids_list)
    b_means_lab = ndi.mean(lab_orig[..., 2], region_map, ids_list)
    r_means = ndi.mean(r, region_map, ids_list)
    g_means = ndi.mean(g, region_map, ids_list)
    blue_means = ndi.mean(b, region_map, ids_list)
    areas = np.bincount(region_map.ravel())

    out = []
    for i, rid in enumerate(ids_list):
        rid_int = int(rid)
        rr = int(round(max(0.0, min(255.0, r_means[i]))))
        gg = int(round(max(0.0, min(255.0, g_means[i]))))
        bb = int(round(max(0.0, min(255.0, blue_means[i]))))
        out.append({
            "id": rid_int,
            "area_px": int(areas[rid_int]),
            "lab": [round(float(L_means[i]), 2),
                    round(float(a_means[i]), 2),
                    round(float(b_means_lab[i]), 2)],
            "hex": "#{:02X}{:02X}{:02X}".format(rr, gg, bb),
        })
    return out


def build_line_mask(rgb_smoothed: np.ndarray, L_threshold: float = 25.0) -> np.ndarray:
    """Masque binaire des traits noirs : L < seuil sur image lissee,
    avec close 3x3 pour boucher micro-trous. Retourne uint8 0/255."""
    lab = rgb2lab(rgb_smoothed).astype(np.float32)
    mask = (lab[..., 0] < L_threshold).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return (mask * 255).astype(np.uint8)


# ============================================================================
# Orchestration par image
# ============================================================================
def process_image_3levels(rgb: np.ndarray, out_lines: Path | None = None) -> dict:
    """Produit les 3 partitions + extractions G3/G5."""
    t0 = time.time()
    rgb_s = preprocess_meanshift(rgb, sp=BASE_V3["sp"], sr=BASE_V3["sr"])
    t_meanshift = time.time() - t0
    t0 = time.time()
    cl, lab = kmeans_lab(rgb_s, k=BASE_V3["k"])
    t_kmeans = time.time() - t0
    t0 = time.time()
    rm = connected_regions(cl)
    n_before_cc = int(len(np.unique(rm)))
    t_cc = time.time() - t0
    t0 = time.time()
    rm_v3, v3_stats = merge_v3(
        rm, lab,
        min_area_ratio=BASE_V3["merge_thresh"],
        contrast_thresh=BASE_V3["contrast_thresh"],
    )
    n_v3 = int(len(np.unique(rm_v3)))
    t_v3 = time.time() - t0

    protected_ids: set[int] = set(v3_stats.get("protected_final_ids", []))

    # --- Line mask (sur image lissee) ---
    line_mask = build_line_mask(rgb_s, L_threshold=LINES_L_THRESHOLD)
    line_mask_path = None
    if out_lines is not None:
        out_lines.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_lines), line_mask)
        line_mask_path = str(out_lines)

    n_line_px = int((line_mask > 0).sum())

    results: dict[str, dict] = {}
    # ----- adulte (= v3) -----
    ts = time.time()
    rm_a = rm_v3.copy()
    t_adulte = time.time() - ts
    # ----- enfant -----
    ts = time.time()
    rm_e, n_smooth = smooth_merge_similar(
        rm_v3, lab,
        thresh=LEVELS["enfant"]["smooth_merge_thresh"],
        protected_ids=protected_ids,
    )
    t_enfant = time.time() - ts
    # ----- tout-petit -----
    ts = time.time()
    rm_tp, tp_stats = family_merge_tout_petit(
        rm_v3, lab,
        protected_ids=protected_ids,
        k_families=LEVELS["tout_petit"]["k_families"],
        fallback_target=LEVELS["tout_petit"]["fallback_target_non_protected"],
    )
    t_toutpetit = time.time() - ts

    # Pour chaque niveau : render + per-region colors (depuis ORIGINAL rgb)
    for lvl_key, rm_lvl, level_timing, level_extra in [
        ("tout_petit", rm_tp, t_toutpetit, tp_stats),
        ("enfant", rm_e, t_enfant, {"smooth_merges": n_smooth}),
        ("adulte", rm_a, t_adulte, {}),
    ]:
        render = render_with_outline(rm_lvl, seed=int(np.sum(rm_lvl) % 9973))
        n_orphans = int((rm_lvl == 0).sum())
        n_final = int(len(np.unique(rm_lvl)))
        region_colors = compute_region_colors_from_original(rm_lvl, rgb)
        # Marquer protected dans la liste
        prot_set = protected_ids
        for r in region_colors:
            r["protected"] = bool(r["id"] in prot_set)

        results[lvl_key] = {
            "region_map": rm_lvl,
            "render": render,
            "stats": {
                "params": {**BASE_V3, **LEVELS[lvl_key]},
                "regions_before_merge": n_before_cc,
                "regions_after_v3": n_v3,
                "regions_final": n_final,
                "protected_immune": len(protected_ids),
                "orphan_pixels": n_orphans,
                "regions": region_colors,
                **level_extra,
                "timing_s": {
                    "meanshift": round(t_meanshift, 2),
                    "kmeans": round(t_kmeans, 2),
                    "cc": round(t_cc, 2),
                    "merge_v3": round(t_v3, 2),
                    "level_step": round(level_timing, 2),
                    "total": round(
                        t_meanshift + t_kmeans + t_cc + t_v3 + level_timing, 2
                    ),
                },
            },
        }

    return {
        "levels": results,
        "line_mask_path": line_mask_path,
        "line_pixel_count": n_line_px,
    }


# ============================================================================
# Main
# ============================================================================
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    data = json.loads(args.corpus.read_text(encoding="utf-8"))
    items = data["images"]

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "lines").mkdir(parents=True, exist_ok=True)
    for lvl_key in LEVELS.keys():
        (args.out / lvl_key).mkdir(parents=True, exist_ok=True)

    all_stats: dict = {
        "base_v3": BASE_V3,
        "levels": LEVELS,
        "lines_L_threshold": LINES_L_THRESHOLD,
        "design": (
            "Base v3 unique -> protected_ids canoniques. "
            "tout-petit = family-merge k=5 + fallback greedy ΔE jusqu'a 10 non-protegees. "
            "enfant = smooth_merge_thresh 12 (inchange). adulte = v3 brut."
        ),
        "images": [],
        "lines": {},
    }
    orphan_violations = []

    for item in items:
        src = (PROJECT_ROOT / item["path"]).resolve()
        slot = item["slot"]
        rid = item["id"]
        if not src.exists():
            print(f"[SKIP] #{slot} {rid}", file=sys.stderr)
            continue
        rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        out_lines = args.out / "lines" / f"{slot:02d}_{rid}_lines.png"
        print(f"[G2 v2] #{slot:02d} {rid}", flush=True)
        result = process_image_3levels(rgb, out_lines=out_lines)
        all_stats["lines"][rid] = {
            "path": str(out_lines.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "line_pixel_count": result["line_pixel_count"],
            "ratio": round(result["line_pixel_count"] / (rgb.shape[0] * rgb.shape[1]), 4),
        }
        for lvl_key, lvl in result["levels"].items():
            out_png = args.out / lvl_key / f"{slot:02d}_{rid}_regions.png"
            out_npy = args.out / lvl_key / f"{slot:02d}_{rid}_regionmap.npy"
            cv2.imwrite(str(out_png), cv2.cvtColor(lvl["render"], cv2.COLOR_RGB2BGR))
            np.save(out_npy, lvl["region_map"].astype(np.int32))
            s = lvl["stats"]
            s["slot"] = slot
            s["id"] = rid
            s["category"] = item["category"]
            s["level"] = lvl_key
            s["out_png"] = str(out_png.relative_to(PROJECT_ROOT)).replace("\\", "/")
            s["out_npy"] = str(out_npy.relative_to(PROJECT_ROOT)).replace("\\", "/")
            all_stats["images"].append(s)
            extra = ""
            if lvl_key == "tout_petit":
                extra = (
                    f"fam_merges {s.get('family_merges', 0):3d}, "
                    f"fallback {s.get('fallback_merges', 0):3d}, "
                    f"non_protected {s.get('n_non_protected_final', 0):3d}"
                )
            elif lvl_key == "enfant":
                extra = f"smooth {s.get('smooth_merges', 0):3d}"
            print(
                f"    [{lvl_key:10s}] regions {s['regions_final']:4d}  "
                f"(immune {s['protected_immune']:3d}, {extra}, "
                f"orphans {s['orphan_pixels']})"
            )
            if s["orphan_pixels"] > 0:
                orphan_violations.append((slot, lvl_key, s["orphan_pixels"]))

    all_stats["orphan_violations"] = orphan_violations
    all_stats["orphan_check"] = (
        "OK 0 orphelin" if not orphan_violations else f"FAIL {len(orphan_violations)} cas"
    )

    # Decision produit (2026-06-10) : tout-petit est conditionnel.
    # publishable_tp = (non-protegees tp <= 12) ET (protected <= 15).
    # Heuristique simple, raffinage hors POC.
    publishable_summary = []
    by_slot = {}
    for s in all_stats["images"]:
        by_slot.setdefault(s["slot"], {})[s["level"]] = s
    for slot, lvls in sorted(by_slot.items()):
        tp = lvls.get("tout_petit", {})
        non_prot = tp.get("n_non_protected_final", None)
        protected = tp.get("protected_immune", None)
        publishable_tp = bool(
            non_prot is not None
            and protected is not None
            and non_prot <= 12
            and protected <= 15
        )
        tp["publishable_tp"] = publishable_tp
        tp["publishable_tp_rule"] = "(non_protected_final <= 12) AND (protected_immune <= 15)"
        publishable_summary.append({
            "slot": slot,
            "id": tp.get("id", "?"),
            "category": tp.get("category", "?"),
            "non_protected_final": non_prot,
            "protected_immune": protected,
            "publishable_tp": publishable_tp,
        })
    all_stats["publishable_tp_summary"] = publishable_summary
    all_stats["publishable_tp_count"] = sum(1 for x in publishable_summary if x["publishable_tp"])

    stats_path = args.out / "stats.json"
    stats_path.write_text(json.dumps(all_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK stats : {stats_path}")
    print(f"Orphan check : {all_stats['orphan_check']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
