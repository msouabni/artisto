"""gallery_explore.png : 4 styles x 3 sujets, blank|solution, labellise.
+ zooms (dog visage + peacock detail) par style.

Lit les PNG blank/solution produits par s_explore_endtoend.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
STYLES = ["mosaic", "zellige", "mandala", "zentangle"]
SUBJECTS = ["dog", "castle", "peacock"]
CELL = 300
PAD = 6
LABEL_H = 26
HDR_H = 30


def _put(img, text, x, y, scale=0.5, color=(20, 20, 20)):
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def load_cell(path: Path) -> np.ndarray:
    im = cv2.imread(str(path))
    if im is None:
        im = np.full((CELL, CELL, 3), 230, np.uint8)
        _put(im, "MISSING", 90, CELL // 2, 0.7, (0, 0, 255))
        return im
    return cv2.resize(im, (CELL, CELL))


def main():
    stats = json.loads((HERE / "explore_stats.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in stats["images"]}

    # layout : pour chaque style une ligne ; chaque sujet = 2 colonnes (blank|solution)
    pair_w = 2 * CELL + PAD
    n_cols = len(SUBJECTS)
    grid_w = n_cols * (pair_w + PAD) + PAD
    row_h = HDR_H + LABEL_H + CELL + PAD
    grid_h = len(STYLES) * row_h + 40
    grid = np.full((grid_h, grid_w, 3), 250, np.uint8)

    _put(grid, "POC2 EXPLORATION ornemental - 4 styles x 3 sujets - blank | solution",
         PAD, 24, 0.6, (0, 0, 0))

    for r, style in enumerate(STYLES):
        y0 = 40 + r * row_h
        sample = by_id.get(f"{style}_dog", {})
        hdr = (f"{style.upper()}  bg={sample.get('bg','?')} "
               f"color={sample.get('color_mode','?')} ink={sample.get('ink_source','?')} "
               f"stroke={sample.get('stroke_px','?')}px merge_de={sample.get('merge_de','?')}")
        _put(grid, hdr, PAD, y0 + 18, 0.5, (90, 30, 30))
        for c, subj in enumerate(SUBJECTS):
            rid = f"{style}_{subj}"
            x0 = PAD + c * (pair_w + PAD)
            yl = y0 + HDR_H
            n = by_id.get(rid, {}).get("n_clickable", "?")
            _put(grid, f"{subj} (n={n})", x0, yl + 16, 0.45, (40, 40, 40))
            yc = yl + LABEL_H
            blank = load_cell(HERE / f"{rid}_blank.png")
            sol = load_cell(HERE / f"{rid}_solution.png")
            grid[yc:yc + CELL, x0:x0 + CELL] = blank
            grid[yc:yc + CELL, x0 + CELL + PAD:x0 + 2 * CELL + PAD] = sol

    out = HERE / "gallery_explore.png"
    cv2.imwrite(str(out), grid)
    print("gallery_explore.png", grid.shape)


if __name__ == "__main__":
    main()
