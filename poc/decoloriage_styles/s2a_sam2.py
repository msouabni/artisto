"""S2a - Segmentation SAM 2 sur le style manga (3 sujets : dog, castle, peacock).

1) SAM2AutomaticMaskGenerator sur chaque image manga -> liste de masques.
2) Partition : argmax/assignation pixel->masque (masque de plus grande
   confiance/score gagne en cas de chevauchement) + pixels non couverts assignes
   par plus proche region (bouchage) -> region_map dense sans trou.
3) Fusion des petites regions / regions similaires en REUTILISANT g2 par import :
   - smooth_merge_similar (niveau "enfant" POC 1, ΔE<12, protected immune=set())
   Pour rester comparable a la colonne k-means POC 1 (s1_out/manga_*_enfant.png),
   on applique le MEME niveau enfant.

Sortie : region_map SAM2 (npy) + rendu contours + n_regions. Compare cote a cote
dans la planche (s2a_planche.py).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from scipy import ndimage as ndi
from skimage.color import rgb2lab

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
POC1_DIR = PROJECT_ROOT / "poc" / "decoloriage"
sys.path.insert(0, str(POC1_DIR))

# Reuse POC 1 par import (aucune copie) :
from g1a_v3_compact import render_with_outline  # noqa: E402
from g2_partition import smooth_merge_similar  # noqa: E402

from sam2.build_sam import build_sam2  # noqa: E402
from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator  # noqa: E402

CORPUS = HERE / "corpus.json"
OUT_DIR = HERE / "s2_out"
RAW_DIR = OUT_DIR / "sam2_raw"

CKPT = HERE / "_models" / "sam2_ckpt" / "sam2.1_hiera_small.pt"
CFG = "configs/sam2.1/sam2.1_hiera_s.yaml"

# Niveau enfant POC 1 (verbatim) pour comparabilite directe avec k-means.
ENFANT_SMOOTH_THRESH = 12.0


def build_region_map_from_masks(masks: list[dict], h: int, w: int) -> np.ndarray:
    """argmax/assignation pixel->masque + bouchage de trous.

    SAM2 AMG retourne des masques potentiellement chevauchants, chacun avec un
    'predicted_iou' et 'stability_score'. Strategie : trier par aire CROISSANTE
    et peindre (les petits masques, plus specifiques, gagnent au-dessus des
    grands fonds). Pixels restants (non couverts) -> label 0, bouches ensuite par
    expansion du plus proche label (distance transform)."""
    region_map = np.zeros((h, w), dtype=np.int32)
    # Trier masques par aire decroissante : grands peints d'abord, petits ecrasent.
    order = sorted(range(len(masks)), key=lambda i: -int(masks[i]["area"]))
    for new_label, i in enumerate(order, start=1):
        seg = masks[i]["segmentation"]
        region_map[seg] = new_label

    # Bouchage des trous (pixels label 0) : plus proche region non-nulle.
    holes = region_map == 0
    if holes.any():
        # indices du plus proche pixel non-trou
        _, (iy, ix) = ndi.distance_transform_edt(
            holes, return_distances=True, return_indices=True
        )
        region_map[holes] = region_map[iy[holes], ix[holes]]

    # Recompacter les labels + s'assurer que chaque label = 1 composante connexe
    # (un masque SAM peut etre spatialement disjoint -> on re-split en CC).
    rm_cc = np.zeros((h, w), dtype=np.int32)
    next_id = 1
    struct = ndi.generate_binary_structure(2, 1)
    for lbl in np.unique(region_map):
        mask = region_map == lbl
        cc, n = ndi.label(mask, structure=struct)
        if n == 0:
            continue
        cc[cc > 0] += next_id - 1
        rm_cc[mask] = cc[mask]
        next_id += n
    return rm_cc


def main() -> int:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = [it for it in data["images"] if it["style"] == "manga"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[S2a] device={device}  ckpt={CKPT.name}", flush=True)
    sam2_model = build_sam2(CFG, str(CKPT), device=device, apply_postprocessing=False)
    # AMG params : grille modeste pour limiter le temps CPU, min_mask_region_area
    # nettoie les micro-masques (bouches ensuite par g2 de toute facon).
    amg = SAM2AutomaticMaskGenerator(
        sam2_model,
        points_per_side=32,
        pred_iou_thresh=0.7,
        stability_score_thresh=0.85,
        min_mask_region_area=100,
    )

    results: dict = {}
    for item in items:
        rid = item["id"]
        src = (HERE / item["path"]).resolve()
        rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        lab = rgb2lab(rgb).astype(np.float32)

        t0 = time.time()
        masks = amg.generate(rgb)
        t_sam = round(time.time() - t0, 2)
        n_masks = len(masks)

        rm = build_region_map_from_masks(masks, h, w)
        n_regions_sam_raw = int(len(np.unique(rm)))

        # Fusion niveau enfant POC 1 (reuse g2). protected vide : SAM ne fournit
        # pas de protected_ids ; on laisse smooth_merge gerer ΔE<12.
        t1 = time.time()
        rm_enfant, n_smooth = smooth_merge_similar(
            rm, lab, thresh=ENFANT_SMOOTH_THRESH, protected_ids=set()
        )
        t_merge = round(time.time() - t1, 2)
        n_regions_final = int(len(np.unique(rm_enfant)))

        render = render_with_outline(rm_enfant, seed=int(np.sum(rm_enfant) % 9973))
        sam_png = RAW_DIR / f"{rid}_sam2_enfant.png"
        sam_npy = RAW_DIR / f"{rid}_sam2_regionmap.npy"
        cv2.imwrite(str(sam_png), cv2.cvtColor(render, cv2.COLOR_RGB2BGR))
        np.save(sam_npy, rm_enfant.astype(np.int32))

        # Visualisation des masques SAM bruts (overlay colore).
        overlay = render_with_outline(
            build_region_map_from_masks(masks, h, w),
            seed=7,
        )
        cv2.imwrite(str(RAW_DIR / f"{rid}_sam2_masks_raw.png"),
                    cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))

        results[rid] = {
            "n_sam_masks": n_masks,
            "n_regions_sam_raw": n_regions_sam_raw,
            "n_regions_final": n_regions_final,
            "smooth_merges": n_smooth,
            "time_sam_s": t_sam,
            "time_merge_s": t_merge,
            "sam2_enfant_png": str(sam_png.relative_to(HERE)).replace("\\", "/"),
            "sam2_regionmap_npy": str(sam_npy.relative_to(HERE)).replace("\\", "/"),
        }
        print(f"[S2a] {rid:14s} masks={n_masks:4d} raw_reg={n_regions_sam_raw:4d} "
              f"-> final={n_regions_final:4d}  (sam {t_sam}s, merge {t_merge}s)",
              flush=True)

    out = {
        "branch": "S2a",
        "model": "SAM 2.1 hiera small (automatic mask generator)",
        "config": CFG,
        "device": device,
        "amg_params": {
            "points_per_side": 32, "pred_iou_thresh": 0.7,
            "stability_score_thresh": 0.85, "min_mask_region_area": 100,
        },
        "enfant_smooth_thresh": ENFANT_SMOOTH_THRESH,
        "poc1_reused": [
            "g1a_v3_compact.render_with_outline",
            "g2_partition.smooth_merge_similar (niveau enfant, ΔE<12)",
        ],
        "results": results,
    }
    (OUT_DIR / "s2a_sam2_stats.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nOK s2a_sam2_stats.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
