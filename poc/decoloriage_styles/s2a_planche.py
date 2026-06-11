"""S2a - Planche comparaison manga : original | k-means POC1 | SAM 2.

3 sujets (dog, castle, peacock) x 3 colonnes. n_regions affiche par methode.
  - col 1 : original (corpus/manga_*.png)
  - col 2 : partition k-means POC 1 = s1_out/manga_*_enfant.png
            (n_regions lu dans s1_out/s1_stats.json)
  - col 3 : partition SAM 2 = s2_out/sam2_raw/manga_*_sam2_enfant.png
            (n_regions lu dans s2_out/s2a_sam2_stats.json)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus.json"
OUT_DIR = HERE / "s2_out"
RAW_DIR = OUT_DIR / "sam2_raw"
S1_OUT = HERE / "s1_out"

SUBJECTS = ["dog", "castle", "peacock"]
CELL = 380


def label_cell(img: np.ndarray, title: str, sub: str) -> np.ndarray:
    h, w = img.shape[:2]
    bar = np.full((70, w, 3), 245, dtype=np.uint8)
    cv2.putText(bar, title, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(bar, sub, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def prep(path: Path, title: str, sub: str) -> np.ndarray:
    img = cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    r = cv2.resize(img, (CELL, CELL), interpolation=cv2.INTER_AREA)
    return label_cell(r, title, sub)


def main() -> int:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = {it["subject"]: it for it in data["images"] if it["style"] == "manga"}

    s1 = json.loads((S1_OUT / "s1_stats.json").read_text(encoding="utf-8"))
    kmeans_nreg = {r["id"]: r["n_regions_final"] for r in s1["images"]}

    sam_stats = json.loads((OUT_DIR / "s2a_sam2_stats.json").read_text(encoding="utf-8"))
    sam_res = sam_stats["results"]

    rows = []
    for subj in SUBJECTS:
        item = items[subj]
        rid = item["id"]
        orig = (HERE / item["path"]).resolve()
        c1 = prep(orig, "original", f"manga_{subj}")
        c2 = prep(S1_OUT / f"{rid}_enfant.png", "k-means POC1",
                  f"n_regions = {kmeans_nreg[rid]}")
        c3 = prep(RAW_DIR / f"{rid}_sam2_enfant.png", "SAM 2",
                  f"n_regions = {sam_res[rid]['n_regions_final']}  "
                  f"(masks {sam_res[rid]['n_sam_masks']})")
        rowimg = np.hstack([c1, c2, c3])
        lbl = np.full((rowimg.shape[0], 150, 3), 230, dtype=np.uint8)
        cv2.putText(lbl, f"manga_{subj}", (10, rowimg.shape[0] // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2, cv2.LINE_AA)
        rows.append(np.hstack([lbl, rowimg]))

    planche = np.vstack(rows)
    title = np.full((60, planche.shape[1], 3), 255, dtype=np.uint8)
    cv2.putText(title, "S2a - manga : original | partition k-means POC1 | partition SAM 2",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (10, 10, 10), 2, cv2.LINE_AA)
    planche = np.vstack([title, planche])
    out_png = OUT_DIR / "planche_s2a_manga.png"
    cv2.imwrite(str(out_png), cv2.cvtColor(planche, cv2.COLOR_RGB2BGR))
    print(f"OK planche : {out_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
