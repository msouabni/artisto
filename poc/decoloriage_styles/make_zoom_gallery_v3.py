"""v3 - zoom crops (finesse detail adulte) + gallery_v3.png.

Zooms (4) : dog visage/museau + peacock queue, pour les 2 styles.
Chaque <id>_zoom.png = crop blank | crop solution cote a cote (finesse a
l'echelle adulte).

gallery_v3.png : blank|solution des 3 sujets x 2 styles + une ligne de zooms.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "s3_out_v3"

SUBJECTS = ["dog", "castle", "peacock"]
STYLES = ["low_poly", "kawaii_bold"]

# Crop normalise (x0,y0,x1,y1 en fraction) par sujet de zoom.
ZOOM_CROP = {
    "dog": (0.18, 0.05, 0.62, 0.55),       # visage / museau
    "peacock": (0.18, 0.02, 0.82, 0.55),   # eventail de queue (haut)
}
ZOOM_TARGETS = [("low_poly", "dog"), ("kawaii_bold", "dog"),
                ("low_poly", "peacock"), ("kawaii_bold", "peacock")]


def _load(p: Path) -> np.ndarray:
    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(p)
    return img


def _label(img: np.ndarray, text: str) -> np.ndarray:
    bar = np.full((34, img.shape[1], 3), 245, dtype=np.uint8)
    cv2.putText(bar, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 35), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def _crop_frac(img: np.ndarray, frac) -> np.ndarray:
    H, W = img.shape[:2]
    x0, y0, x1, y1 = frac
    return img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)].copy()


def _resize_w(img: np.ndarray, w: int) -> np.ndarray:
    h = int(img.shape[0] * w / img.shape[1])
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def make_zooms() -> list[Path]:
    paths = []
    for style, subject in ZOOM_TARGETS:
        rid = f"{style}_{subject}"
        blank = _load(OUT / f"{rid}_blank.png")
        sol = _load(OUT / f"{rid}_solution.png")
        frac = ZOOM_CROP[subject]
        cb = _resize_w(_crop_frac(blank, frac), 420)
        cs = _resize_w(_crop_frac(sol, frac), 420)
        h = max(cb.shape[0], cs.shape[0])
        cb = cv2.copyMakeBorder(cb, 0, h - cb.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cs = cv2.copyMakeBorder(cs, 0, h - cs.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cb = _label(cb, f"{rid} blank")
        cs = _label(cs, f"{rid} solution")
        gap = np.full((cb.shape[0], 12, 3), 255, dtype=np.uint8)
        combo = np.hstack([cb, gap, cs])
        outp = OUT / f"{rid}_zoom.png"
        cv2.imwrite(str(outp), combo)
        paths.append(outp)
        print(f"zoom -> {outp.name}")
    return paths


def make_gallery(zoom_paths: list[Path]) -> Path:
    cell_w = 240
    rows = []
    for style in STYLES:
        for subject in SUBJECTS:
            rid = f"{style}_{subject}"
            blank = _resize_w(_load(OUT / f"{rid}_blank.png"), cell_w)
            sol = _resize_w(_load(OUT / f"{rid}_solution.png"), cell_w)
            h = max(blank.shape[0], sol.shape[0])
            blank = cv2.copyMakeBorder(blank, 0, h - blank.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            sol = cv2.copyMakeBorder(sol, 0, h - sol.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            pair = np.hstack([blank, np.full((h, 6, 3), 230, dtype=np.uint8), sol])
            pair = _label(pair, f"{rid}  (blank | solution)")
            rows.append(pair)
    # 3 paires par ligne -> 2 lignes par style ; on empile simplement par 3
    grid_rows = []
    for i in range(0, len(rows), 3):
        chunk = rows[i:i + 3]
        maxh = max(c.shape[0] for c in chunk)
        chunk = [cv2.copyMakeBorder(c, 0, maxh - c.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for c in chunk]
        sep = np.full((maxh, 10, 3), 255, dtype=np.uint8)
        line = chunk[0]
        for c in chunk[1:]:
            line = np.hstack([line, sep, c])
        grid_rows.append(line)
    maxw = max(r.shape[1] for r in grid_rows)
    grid_rows = [cv2.copyMakeBorder(r, 0, 0, 0, maxw - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for r in grid_rows]
    top = np.vstack([np.full((10, maxw, 3), 255, dtype=np.uint8)] +
                    [v for r in grid_rows for v in (r, np.full((10, maxw, 3), 255, dtype=np.uint8))])

    # ligne de zooms en bas
    zooms = [_resize_w(_load(p), 300) for p in zoom_paths]
    zh = max(z.shape[0] for z in zooms)
    zooms = [cv2.copyMakeBorder(z, 0, zh - z.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for z in zooms]
    sep = np.full((zh, 8, 3), 255, dtype=np.uint8)
    zline = zooms[0]
    for z in zooms[1:]:
        zline = np.hstack([zline, sep, z])
    zline = _label(zline, "ZOOMS finesse adulte (dog museau + peacock queue) x 2 styles")
    if zline.shape[1] < maxw:
        zline = cv2.copyMakeBorder(zline, 0, 0, 0, maxw - zline.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))
    elif zline.shape[1] > maxw:
        top = cv2.copyMakeBorder(top, 0, 0, 0, zline.shape[1] - maxw, cv2.BORDER_CONSTANT, value=(255, 255, 255))

    final = np.vstack([top, np.full((14, top.shape[1], 3), 200, dtype=np.uint8), zline])
    outp = OUT / "gallery_v3.png"
    cv2.imwrite(str(outp), final)
    print(f"gallery -> {outp}")
    return outp


if __name__ == "__main__":
    zp = make_zooms()
    make_gallery(zp)
