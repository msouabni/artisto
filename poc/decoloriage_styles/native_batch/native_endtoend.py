"""POC2 EXPLORATION sujets natifs - end-to-end LINE-ART (les 12).

Tous les sujets natifs sont generes en line-art contours noirs sur fond blanc :
c'est deja une page de coloriage. On reutilise SANS MODIF le mode line-art cale
au batch precedent (explore_batch/s_explore_endtoend.py, config mandala/zentangle) :

  - fond        : blanc (PAS de chromakey) -> Papier via L*>=92
  - source encre: trait natif L<25 (mince), mode "dark" (region encre si L_moy<28)
  - color_mode  : BLANK (blanc-remplissable ; pas de couleur d'origine, source N&B)
  - stroke      : noir fin 1.5px ; regions = cellules blanches encloses
  - partition   : adulte (max detail) + smooth_merge leger ΔE=6

Si une partition explose (>~800 cliquables), on monte merge_de pour ce style et on
le documente (partition adaptee pour rester lisible adulte).

Reutilise PAR IMPORT (aucune modif) :
  - explore_batch/s_explore_endtoend : build_svg, build_html, _rasterize,
    force_single_bg, INK_HEX, WHITE_L_THRESH, INK_L_MEAN
  - poc/decoloriage/g2_partition, g3_vectorize, g4_two_weight, g5_product

Usage :
    python poc/decoloriage_styles/native_batch/native_endtoend.py
    python poc/decoloriage_styles/native_batch/native_endtoend.py --only zellige_star
    python poc/decoloriage_styles/native_batch/native_endtoend.py --merge-de zellige=10
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent.parent
POC1_DIR = PROJECT_ROOT / "poc" / "decoloriage"
EXPLORE_DIR = HERE.parent / "explore_batch"
sys.path.insert(0, str(POC1_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(EXPLORE_DIR))

# --- import du mode line-art cale au batch precedent (SANS MODIF) ---
import s_explore_endtoend as base  # noqa: E402
from s_explore_endtoend import (  # noqa: E402
    build_svg, build_html, _rasterize, force_single_bg,
    INK_HEX, WHITE_L_THRESH, INK_L_MEAN,
)
# --- modules POC1 (import only) ---
from g2_partition import process_image_3levels, smooth_merge_similar  # noqa: E402
from g3_vectorize import extract_region_polygons  # noqa: E402
from g4_two_weight import (  # noqa: E402
    extract_topological_arcs,
    classify_arc_into_ink_or_shading,
    smooth_open_arc,
    LINE_MASK_DILATE_PX,
    DP_TOLERANCE,
    CHAIKIN_ITERS_ARC,
    CHAIKIN_ITERS_REGION,
)
from g5_product import compute_region_colors_from_original  # noqa: E402

CORPUS = HERE / "corpus"
OUT_DIR = HERE
WORK_DIR = HERE / "_work"

# Tous les sujets natifs sont en line-art : on reutilise la config mandala/zentangle.
LINEART_CFG_BASE = {
    "bg": "white", "color_mode": "blank", "ink_source": "lineart",
    "ink_mode": "dark", "merge_de": 6.0, "ink_px": 1.5,
}

ORDER = [
    "zellige_star", "zellige_medallion", "zellige_panel",
    "mandala_floral", "mandala_geometric", "mandala_lotus",
    "zentangle_owl", "zentangle_feather", "zentangle_butterfly",
    "mosaic_fish", "mosaic_medallion", "mosaic_bird",
]

# seuil de charge adulte : au-dela on applique un smooth_merge plus fort.
CLICKABLE_TARGET = 800
SMOOTH_MERGE_STEP = 4.0   # +ΔE par escalade
SMOOTH_MERGE_MAX = 18.0

STYLE_NOTE = {
    "zellige": "line-art geometrique islamique natif ; cellules blanches a colorier.",
    "mandala": "line-art mandala natif ; cellules blanches a colorier, encre noire native.",
    "zentangle": "line-art zentangle natif dense ; cellules blanches a colorier.",
    "mosaic": "line-art de tuiles mosaique natif ; cellules blanches a colorier.",
}


def _partition_with_merge(rgb, rid, merge_de, lab_full):
    """Partition adulte + smooth_merge ΔE. Retourne (rm_merged, n_after, n_merges)."""
    l25_path = WORK_DIR / f"{rid}_lines.png"
    result = process_image_3levels(rgb, out_lines=l25_path)
    rm_adulte = result["levels"]["adulte"]["region_map"].astype(np.int32)
    n_adulte_raw = int(len(np.unique(rm_adulte)))
    if merge_de > 0:
        rm_merged, n_merges = smooth_merge_similar(rm_adulte, lab_full, merge_de)
        rm_merged = rm_merged.astype(np.int32)
    else:
        rm_merged, n_merges = rm_adulte, 0
    return rm_merged, int(len(np.unique(rm_merged))), n_merges, n_adulte_raw


def process_one(img_id, slot, merge_de_override=None):
    style, subject = img_id.split("_", 1)
    cfg = dict(LINEART_CFG_BASE)
    if merge_de_override is not None:
        cfg["merge_de"] = merge_de_override
    src = CORPUS / f"{img_id}.png"
    rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    H, W = rgb.shape[:2]
    total_px = H * W
    t0 = time.time()
    lab_full = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab_full[:, :, 0] * 100.0 / 255.0

    # --- background = blanc L*>=92 ---
    bg_mask = (L >= WHITE_L_THRESH).astype(np.uint8) * 255
    pct_bg = round(100.0 * (bg_mask > 0).sum() / total_px, 2)

    # --- ink mask L<25 (sans bg) ---
    ink_l25 = (L < 25).astype(np.uint8) * 255
    ink_l25[bg_mask > 0] = 0
    pct_ink_mask = round(100.0 * int((ink_l25 > 0).sum()) / total_px, 2)

    # --- partition adulte + merge (escalade si surcharge) ---
    merge_de = cfg["merge_de"]
    rm_merged, n_after_merge, n_merges, n_adulte_raw = _partition_with_merge(
        rgb, img_id, merge_de, lab_full)
    rm_fixed, bg_label, n_subj = force_single_bg(rm_merged, bg_mask)

    region_colors = compute_region_colors_from_original(rgb, rm_fixed)
    region_data = {
        rid_int: {"hex_original": c["hex"], "lab": c["lab"],
                  "is_background": (rid_int == bg_label)}
        for rid_int, c in region_colors.items()
    }
    ink_region_ids = {
        rid_int for rid_int, d in region_data.items() if d["lab"][0] < INK_L_MEAN
    }
    ink_region_ids.discard(int(bg_label))
    n_clickable = sum(
        1 for rid_int, d in region_data.items()
        if rid_int not in ink_region_ids and not d["is_background"])

    escalations = []
    # --- escalade smooth_merge si surcharge adulte ---
    while n_clickable > CLICKABLE_TARGET and merge_de < SMOOTH_MERGE_MAX:
        merge_de = min(SMOOTH_MERGE_MAX, merge_de + SMOOTH_MERGE_STEP)
        escalations.append(merge_de)
        rm_merged, n_after_merge, n_merges, _ = _partition_with_merge(
            rgb, img_id, merge_de, lab_full)
        rm_fixed, bg_label, n_subj = force_single_bg(rm_merged, bg_mask)
        region_colors = compute_region_colors_from_original(rgb, rm_fixed)
        region_data = {
            rid_int: {"hex_original": c["hex"], "lab": c["lab"],
                      "is_background": (rid_int == bg_label)}
            for rid_int, c in region_colors.items()
        }
        ink_region_ids = {
            rid_int for rid_int, d in region_data.items() if d["lab"][0] < INK_L_MEAN
        }
        ink_region_ids.discard(int(bg_label))
        n_clickable = sum(
            1 for rid_int, d in region_data.items()
            if rid_int not in ink_region_ids and not d["is_background"])

    cfg["merge_de"] = merge_de
    n_regions = int(len(np.unique(rm_fixed)))

    # --- arcs topologiques + classif ---
    kernel = np.ones((LINE_MASK_DILATE_PX, LINE_MASK_DILATE_PX), np.uint8)
    line_mask_dilated = cv2.dilate(ink_l25, kernel, iterations=1)
    arcs, _ = extract_topological_arcs(rm_fixed)
    arcs_classified = []
    n_ink = n_shading = 0
    for arc in arcs:
        cls, _r = classify_arc_into_ink_or_shading(arc["points"], line_mask_dilated)
        smoothed = smooth_open_arc(arc["points"], DP_TOLERANCE, CHAIKIN_ITERS_ARC, H, W)
        arcs_classified.append({**arc, "class": cls, "smoothed": smoothed})
        if cls == "ink":
            n_ink += 1
        elif cls == "shading":
            n_shading += 1

    region_polys = extract_region_polygons(rm_fixed, DP_TOLERANCE, CHAIKIN_ITERS_REGION)

    # --- SVG ---
    svg_text = build_svg(region_polys, region_data, arcs_classified, cfg, H, W, ink_region_ids)
    svg_path = OUT_DIR / f"{img_id}_svg.svg"
    svg_path.write_text(svg_text, encoding="utf-8")
    svg_mb = round(svg_path.stat().st_size / (1024 * 1024), 3)

    # --- previews (line-art : encre blank = masque natif fin uniquement) ---
    ink_pixel_mask = (ink_l25 > 0)
    blank_path = OUT_DIR / f"{img_id}_blank.png"
    sol_path = WORK_DIR / f"{img_id}_solution.png"  # N&B : solution = blank, on garde au work
    _rasterize(region_polys, region_data, arcs_classified, cfg, H, W,
               ink_region_ids, ink_pixel_mask, blank_path, sol_path)

    # --- HTML interactif (1 par style : le 1er sujet du style) ---
    note = STYLE_NOTE[style]
    html_text = build_html(
        svg_text, src, img_id.replace("_", " ").title(), style, cfg,
        n_clickable, len(arcs), n_ink, n_shading, len(ink_region_ids), note)
    # ecrit toujours le HTML par image (utile pour debug), le sample par style est copie ensuite
    (OUT_DIR / f"{img_id}.html").write_text(html_text, encoding="utf-8")

    elapsed = round(time.time() - t0, 2)
    print(
        f"[{img_id:22s}] bg%={pct_bg:5.1f} ink%={pct_ink_mask:5.1f} "
        f"adulte={n_adulte_raw:4d} merge_de={merge_de:.0f}->{n_after_merge:4d} "
        f"final={n_regions:4d} clickable={n_clickable:4d} ink_reg={len(ink_region_ids):3d} "
        f"arcs={len(arcs):4d}(ink={n_ink}) svg={svg_mb}Mo ({elapsed}s)"
        + (f" ESCALADE merge->{escalations}" if escalations else ""), flush=True)

    notes = note
    if escalations:
        notes += f" [partition adaptee : smooth_merge escalade ΔE->{merge_de:.0f} (surcharge >{CLICKABLE_TARGET})]"

    return {
        "id": img_id, "slot": slot, "style": style, "subject": subject,
        "image_size": [int(W), int(H)],
        "bg": cfg["bg"], "color_mode": cfg["color_mode"],
        "ink_source": cfg["ink_source"], "ink_mode": cfg["ink_mode"],
        "merge_de": merge_de, "merge_escalations": escalations,
        "stroke_px": cfg["ink_px"], "stroke_hex": INK_HEX,
        "bg_pct": pct_bg, "pct_ink_mask": pct_ink_mask,
        "n_regions_adulte_raw": n_adulte_raw,
        "n_merges": n_merges, "n_after_merge": n_after_merge,
        "n_subject_regions": n_subj,
        "n_regions": n_regions, "n_clickable": n_clickable,
        "n_ink_regions": len(ink_region_ids),
        "n_arcs": len(arcs), "n_ink": n_ink, "n_shading": n_shading,
        "svg_mb": svg_mb,
        "blank_png": f"{img_id}_blank.png",
        "svg": f"{img_id}_svg.svg", "html": f"{img_id}.html",
        "timing_s": elapsed, "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", default=None)
    ap.add_argument("--merge-de", action="append", default=[],
                    help="override style=val, ex: zellige=10")
    args = ap.parse_args()

    merge_overrides = {}
    for kv in args.merge_de:
        k, v = kv.split("=")
        merge_overrides[k] = float(v)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    ids = [i for i in ORDER if (not args.only or i in set(args.only))]
    per_image, failures = [], []
    t_start = time.time()
    for slot, img_id in enumerate(ids, 1):
        if not (CORPUS / f"{img_id}.png").exists():
            failures.append({"id": img_id, "reason": "PNG absent"})
            continue
        style = img_id.split("_", 1)[0]
        ov = merge_overrides.get(style)
        last_exc = None
        for attempt in range(3):  # retry <=2
            try:
                per_image.append(process_one(img_id, slot, ov))
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                import traceback
                last_exc = exc
                print(f"[retry {attempt}] {img_id}: {exc!r}", file=sys.stderr)
                if attempt == 2:
                    traceback.print_exc()
        if last_exc is not None:
            failures.append({"id": img_id, "reason": repr(last_exc)})

    # --- sample HTML par style (1er sujet du style) ---
    style_first = {}
    for r in per_image:
        style_first.setdefault(r["style"], r["id"])
    import shutil
    samples = {}
    for style, first_id in style_first.items():
        src_html = OUT_DIR / f"{first_id}.html"
        dst_html = OUT_DIR / f"{style}_sample.html"
        if src_html.exists():
            shutil.copyfile(src_html, dst_html)
            samples[style] = {"sample_id": first_id, "file": dst_html.name}

    out = {
        "gate": "POC2-exploration-native-subjects",
        "frozen_at": "2026-06-12",
        "mode": "line-art (les 12) : fond blanc L*>=92 -> Papier, encre trait natif "
                "L<25 mode dark, regions = cellules blanches, color_mode blank",
        "lineart_cfg_base": LINEART_CFG_BASE,
        "clickable_target_adulte": CLICKABLE_TARGET,
        "poc_reused": [
            "explore_batch/s_explore_endtoend.py (build_svg, build_html, _rasterize, "
            "force_single_bg, INK_HEX, WHITE_L_THRESH, INK_L_MEAN) - SANS MODIF",
            "poc/decoloriage/g2_partition.py (process_image_3levels, smooth_merge_similar)",
            "poc/decoloriage/g3_vectorize.py (extract_region_polygons)",
            "poc/decoloriage/g4_two_weight.py (arcs, classify, smooth)",
            "poc/decoloriage/g5_product.py (compute_region_colors_from_original)",
        ],
        "style_samples_html": samples,
        "n_processed": len(per_image), "n_failed": len(failures),
        "failures": failures, "images": per_image,
        "timing_s_total": round(time.time() - t_start, 2),
    }
    (OUT_DIR / "native_stats.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK native_stats.json -> {len(per_image)}/12 traitees, {len(failures)} echec(s)")
    print(f"samples HTML par style : {list(samples.values())}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
