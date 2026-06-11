"""S1 - Baseline brute : POC 1 INCHANGE applique aux 12 images du corpus S0.

Diagnostic ("ne peut pas fail") : on lance le pipeline POC 1 verbatim
(g1a_v3 + g2 niveau enfant + masque de traits L<25) sur les 3 sujets x 4
styles, et on cartographie ce qui casse PAR STYLE.

POC 1 est REUTILISE PAR IMPORT depuis poc/decoloriage/ :
  - g2_partition.process_image_3levels  (orchestration g1a_v3 -> niveaux)
  - g2_partition.build_line_mask         (masque L<25 + close 3x3)
Aucun fichier POC 1 n'est modifie. Aucune adaptation de pipeline.

On n'utilise QUE le niveau "enfant" (smooth_merge ΔE<12, protected immune),
conformement au brief S1.

Metriques par image :
  - n_regions_final : nb de regions du region_map ENFANT.
  - pct_ink_mask    : % de pixels couverts par le masque de traits L<25.
  - sliver_ratio    : voir SLIVER_RATIO_DEFINITION ci-dessous.

Sorties (poc/decoloriage_styles/s1_out/) :
  - <id>_enfant.png    : rendu partition enfant (contours visibles).
  - <id>_linemask.png  : masque L<25.
  - s1_stats.json      : tableau par image + agregats medians par style.
La planche contact_sheet_s1.png est produite par make_contact_sheet_s1.py.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
POC1_DIR = PROJECT_ROOT / "poc" / "decoloriage"

# --- Import POC 1 PAR IMPORT (aucune copie, aucune modification) ---
sys.path.insert(0, str(POC1_DIR))
from g2_partition import process_image_3levels  # noqa: E402

CORPUS = HERE / "corpus.json"
OUT_DIR = HERE / "s1_out"

SLIVER_RATIO_DEFINITION = (
    "sliver_ratio = proxy des 'slivers forces' de G3. Sur le squelette des "
    "frontieres inter-regions du region_map enfant (pixels ou un voisin 4-conn "
    "porte un label different), fraction de ces pixels-frontiere qui NE sont PAS "
    "couverts par le masque de traits L<25 dilate de 1px. Interpretation : une "
    "frontiere de region sans encre native dessous est invisible sur la planche "
    "finale ; G3 doit y forcer un stroke artificiel (sliver). sliver_ratio eleve "
    "= beaucoup de frontieres de segmentation sans support d'encre = traits "
    "fabriques. 0 = toute frontiere de region tombe sur de l'encre reelle."
)


def boundary_pixels(region_map: np.ndarray) -> np.ndarray:
    """Masque booleen des pixels-frontiere inter-regions (4-connexite)."""
    rm = region_map
    b = np.zeros(rm.shape, dtype=bool)
    b[:, :-1] |= rm[:, :-1] != rm[:, 1:]
    b[:, 1:] |= rm[:, :-1] != rm[:, 1:]
    b[:-1, :] |= rm[:-1, :] != rm[1:, :]
    b[1:, :] |= rm[:-1, :] != rm[1:, :]
    return b


def compute_sliver_ratio(region_map: np.ndarray, line_mask: np.ndarray) -> dict:
    """Voir SLIVER_RATIO_DEFINITION."""
    bnd = boundary_pixels(region_map)
    n_bnd = int(bnd.sum())
    if n_bnd == 0:
        return {"sliver_ratio": 0.0, "n_boundary_px": 0, "n_boundary_uncovered_px": 0}
    ink = line_mask > 0
    ink_dil = ndi.binary_dilation(ink, iterations=1)
    uncovered = bnd & ~ink_dil
    n_unc = int(uncovered.sum())
    return {
        "sliver_ratio": round(n_unc / n_bnd, 4),
        "n_boundary_px": n_bnd,
        "n_boundary_uncovered_px": n_unc,
    }


def main() -> int:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = data["images"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    per_image: list[dict] = []
    for item in items:
        rid = item["id"]
        style = item["style"]
        subject = item["subject"]
        src = (HERE / item["path"]).resolve()
        if not src.exists():
            print(f"[SKIP] {rid} (introuvable)", file=sys.stderr)
            continue

        rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        total_px = h * w

        # Masque de traits ecrit a part (chemin S1) ET niveaux POC 1.
        line_out = OUT_DIR / f"{rid}_linemask.png"
        t0 = time.time()
        result = process_image_3levels(rgb, out_lines=line_out)
        dt = round(time.time() - t0, 2)

        enfant = result["levels"]["enfant"]
        rm_enfant = enfant["region_map"]
        render = enfant["render"]
        n_regions_final = int(len(np.unique(rm_enfant)))

        # Relire le masque ecrit par POC 1 (build_line_mask, L<25 + close 3x3).
        line_mask = cv2.imread(str(line_out), cv2.IMREAD_GRAYSCALE)
        n_ink = int((line_mask > 0).sum())
        pct_ink_mask = round(100.0 * n_ink / total_px, 2)

        sliver = compute_sliver_ratio(rm_enfant, line_mask)

        # Rendu partition enfant (contours visibles) chemin S1.
        enfant_png = OUT_DIR / f"{rid}_enfant.png"
        cv2.imwrite(str(enfant_png), cv2.cvtColor(render, cv2.COLOR_RGB2BGR))

        row = {
            "id": rid,
            "style": style,
            "subject": subject,
            "image_size": [int(w), int(h)],
            "n_regions_final": n_regions_final,
            "pct_ink_mask": pct_ink_mask,
            "sliver_ratio": sliver["sliver_ratio"],
            "n_boundary_px": sliver["n_boundary_px"],
            "n_boundary_uncovered_px": sliver["n_boundary_uncovered_px"],
            "protected_immune": enfant["stats"]["protected_immune"],
            "enfant_png": f"s1_out/{rid}_enfant.png",
            "linemask_png": f"s1_out/{rid}_linemask.png",
            "time_s": dt,
        }
        per_image.append(row)
        print(
            f"[S1] {rid:18s} style={style:9s}  regions={n_regions_final:4d}  "
            f"ink%={pct_ink_mask:6.2f}  sliver={sliver['sliver_ratio']:.3f}  ({dt}s)",
            flush=True,
        )

    # --- Agregats medians par style ---
    by_style: dict[str, list[dict]] = {}
    for r in per_image:
        by_style.setdefault(r["style"], []).append(r)

    aggregates = {}
    for style, rows in by_style.items():
        aggregates[style] = {
            "n_images": len(rows),
            "median_n_regions_final": round(statistics.median(r["n_regions_final"] for r in rows), 1),
            "median_pct_ink_mask": round(statistics.median(r["pct_ink_mask"] for r in rows), 2),
            "median_sliver_ratio": round(statistics.median(r["sliver_ratio"] for r in rows), 4),
            "min_n_regions_final": min(r["n_regions_final"] for r in rows),
            "max_n_regions_final": max(r["n_regions_final"] for r in rows),
            "min_pct_ink_mask": min(r["pct_ink_mask"] for r in rows),
            "max_pct_ink_mask": max(r["pct_ink_mask"] for r in rows),
        }

    out = {
        "gate": "S1",
        "description": (
            "Baseline brute POC 1 INCHANGE (g1a_v3 + g2 niveau enfant + masque "
            "traits L<25) applique aux 12 images du corpus S0. Aucune adaptation. "
            "Diagnostic de ce qui casse par style. Verdict pass/kill = humain."
        ),
        "poc1_reused": [
            "poc/decoloriage/g1a_v3_compact.py (process_image / preprocess_meanshift / kmeans_lab / connected_regions / merge_v3)",
            "poc/decoloriage/g2_partition.py (process_image_3levels, niveau enfant, build_line_mask L<25 + close 3x3)",
        ],
        "params_verbatim_poc1": {
            "meanshift_sp": 12, "meanshift_sr": 24, "kmeans_k": 12,
            "merge_thresh": 0.0005, "contrast_thresh": 30.0,
            "enfant_smooth_merge_thresh": 12.0, "lines_L_threshold": 25.0,
            "line_mask_close": "MORPH_CLOSE 3x3 iter=1",
        },
        "sliver_ratio_definition": SLIVER_RATIO_DEFINITION,
        "images": per_image,
        "aggregates_by_style_median": aggregates,
    }
    stats_path = OUT_DIR / "s1_stats.json"
    stats_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK s1_stats : {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
