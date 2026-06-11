"""Zooms : dog (visage, haut-gauche) + peacock (centre, detail) par style.
Compare crop original | blank | solution pour juger la finesse de la partition.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
STYLES = ["mosaic", "zellige", "mandala", "zentangle"]

# crops normalises (y0,y1,x0,x1) en fraction
CROPS = {
    "dog": (0.05, 0.45, 0.20, 0.65),       # tete / haut du corps
    "peacock": (0.30, 0.70, 0.30, 0.70),   # centre (corps + amorce queue)
}
TILE = 280
PAD = 6


def _put(img, text, x, y, color=(20, 20, 20)):
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def crop(path: Path, frac):
    im = cv2.imread(str(path))
    if im is None:
        return np.full((TILE, TILE, 3), 230, np.uint8)
    H, W = im.shape[:2]
    y0, y1, x0, x1 = frac
    c = im[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
    return cv2.resize(c, (TILE, TILE))


def main():
    for subj, frac in CROPS.items():
        cols = ["original", "blank", "solution"]
        gw = len(cols) * (TILE + PAD) + PAD
        gh = len(STYLES) * (TILE + 22 + PAD) + 30
        grid = np.full((gh, gw, 3), 250, np.uint8)
        _put(grid, f"ZOOM {subj} : original | blank | solution", PAD, 20)
        for r, style in enumerate(STYLES):
            y0 = 30 + r * (TILE + 22 + PAD)
            _put(grid, f"{style}_{subj}", PAD, y0 + 14, (90, 30, 30))
            yc = y0 + 22
            srcs = [CORPUS / f"{style}_{subj}.png",
                    HERE / f"{style}_{subj}_blank.png",
                    HERE / f"{style}_{subj}_solution.png"]
            for c_i, sp in enumerate(srcs):
                x0 = PAD + c_i * (TILE + PAD)
                grid[yc:yc + TILE, x0:x0 + TILE] = crop(sp, frac)
        out = HERE / f"zoom_{subj}.png"
        cv2.imwrite(str(out), grid)
        print("wrote", out.name, grid.shape)


if __name__ == "__main__":
    main()
