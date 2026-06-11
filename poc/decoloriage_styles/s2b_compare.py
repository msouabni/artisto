"""S2b - Comparaison 4 sources d'encre sur le style 3D + planche + stats.

Pour chaque sujet 3D (dog, castle, peacock), 4 colonnes :
  1. L<25 POC 1            : reprend s1_out/3d_*_linemask.png (masque de traits).
  2. infodraw anime_style  : s2_out/infodraw_raw/3d_*_anime_style_ink.png
  3. infodraw contour_style: s2_out/infodraw_raw/3d_*_contour_style_ink.png
  4. fallback partition 2-poids : frontieres de la partition ENFANT POC 1 en
     2 poids (epais = frontiere sujet/fond, fin = internes). REUTILISE g4
     extract_topological_arcs par import + g2 process_image_3levels par import.

La planche est rendue en "encre noire sur blanc" pour les 4 sources (memes
conventions), labellee, avec % pixels encre par cellule.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
POC1_DIR = PROJECT_ROOT / "poc" / "decoloriage"
sys.path.insert(0, str(POC1_DIR))

from g2_partition import process_image_3levels  # noqa: E402
from g4_two_weight import extract_topological_arcs  # noqa: E402

CORPUS = HERE / "corpus.json"
OUT_DIR = HERE / "s2_out"
RAW_DIR = OUT_DIR / "infodraw_raw"
S1_OUT = HERE / "s1_out"

SUBJECTS = ["dog", "castle", "peacock"]

# Epaisseurs de trait pour le fallback 2-poids (px).
THICK_W = 4
THIN_W = 1
BG_LABEL = None  # determine dynamiquement = label de plus grande aire au bord


def build_2weight_ink(rm: np.ndarray) -> tuple[np.ndarray, dict]:
    """Frontieres de partition en 2 poids -> image encre noir/blanc (uint8,
    255=encre). Epais = arcs touchant le label de fond (sujet/fond), fin =
    internes. Reutilise g4 extract_topological_arcs (arcs topologiques + label_pair)."""
    H, W = rm.shape
    # Label de fond = label majoritaire sur la bordure de l'image.
    border = np.concatenate([rm[0, :], rm[-1, :], rm[:, 0], rm[:, -1]])
    bg_label = int(np.bincount(border).argmax())

    arcs, _stats = extract_topological_arcs(rm)
    canvas = np.zeros((H, W), dtype=np.uint8)  # 0 = papier
    n_thick_arcs = 0
    n_thin_arcs = 0
    for arc in arcs:
        a, b = arc["label_pair"]
        is_subject_bg = (a == bg_label) or (b == bg_label)
        w = THICK_W if is_subject_bg else THIN_W
        pts = np.array(arc["points"], dtype=np.float64)
        if len(pts) < 2:
            continue
        pts_int = np.round(pts).astype(np.int32)
        pts_int[:, 0] = np.clip(pts_int[:, 0], 0, H - 1)
        pts_int[:, 1] = np.clip(pts_int[:, 1], 0, W - 1)
        pts_xy = pts_int[:, [1, 0]].reshape(-1, 1, 2)
        cv2.polylines(canvas, [pts_xy], False, 255, thickness=w, lineType=cv2.LINE_8)
        if is_subject_bg:
            n_thick_arcs += 1
        else:
            n_thin_arcs += 1
    return canvas, {
        "bg_label": bg_label,
        "n_arcs": len(arcs),
        "n_thick_arcs": n_thick_arcs,
        "n_thin_arcs": n_thin_arcs,
        "thick_w": THICK_W,
        "thin_w": THIN_W,
    }


def ink_metrics(ink: np.ndarray) -> dict:
    h, w = ink.shape
    n = int((ink > 0).sum())
    n_cc, _ = cv2.connectedComponents((ink > 0).astype(np.uint8), connectivity=8)
    return {
        "pct_ink": round(100.0 * n / (h * w), 2),
        "n_ink_components": int(n_cc - 1),
    }


def to_black_on_white(ink_mask: np.ndarray) -> np.ndarray:
    """ink_mask uint8 (255=encre) -> RGB encre noire sur fond blanc."""
    out = np.full((*ink_mask.shape, 3), 255, dtype=np.uint8)
    out[ink_mask > 0] = (20, 20, 25)
    return out


def label_cell(img: np.ndarray, text: str, sub: str) -> np.ndarray:
    h, w = img.shape[:2]
    bar = np.full((70, w, 3), 245, dtype=np.uint8)
    cv2.putText(bar, text, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(bar, sub, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def main() -> int:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = {it["subject"]: it for it in data["images"] if it["style"] == "3d"}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    infodraw_stats = json.loads((OUT_DIR / "s2b_infodraw_stats.json").read_text(encoding="utf-8"))

    cell = 360  # taille d'affichage par cellule
    rows = []
    per_subject_stats = {}
    for subj in SUBJECTS:
        item = items[subj]
        rid = item["id"]
        src = (HERE / item["path"]).resolve()
        rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]

        # --- Source 1 : L<25 POC 1 (relire s1_out) ---
        l25 = cv2.imread(str(S1_OUT / f"{rid}_linemask.png"), cv2.IMREAD_GRAYSCALE)
        m_l25 = ink_metrics(l25)
        col1 = to_black_on_white(l25)

        # --- Source 2 & 3 : infodraw ---
        anime = cv2.imread(str(RAW_DIR / f"{rid}_anime_style_ink.png"), cv2.IMREAD_GRAYSCALE)
        contour = cv2.imread(str(RAW_DIR / f"{rid}_contour_style_ink.png"), cv2.IMREAD_GRAYSCALE)
        m_anime = ink_metrics(anime)
        m_contour = ink_metrics(contour)
        col2 = to_black_on_white(anime)
        col3 = to_black_on_white(contour)

        # --- Source 4 : fallback partition 2-poids (reuse g2 + g4) ---
        t0 = time.time()
        result = process_image_3levels(rgb, out_lines=None)
        rm_enfant = result["levels"]["enfant"]["region_map"]
        ink2w, meta2w = build_2weight_ink(rm_enfant)
        t_2w = round(time.time() - t0, 2)
        m_2w = ink_metrics(ink2w)
        cv2.imwrite(str(RAW_DIR / f"{rid}_fallback_2weight_ink.png"), ink2w)
        col4 = to_black_on_white(ink2w)

        # Resize cells + label
        def prep(img, title, sub):
            r = cv2.resize(img, (cell, cell), interpolation=cv2.INTER_AREA)
            return label_cell(r, title, sub)

        c1 = prep(col1, "L<25 POC1", f"ink {m_l25['pct_ink']}%  cc {m_l25['n_ink_components']}")
        c2 = prep(col2, "infodraw anime", f"ink {m_anime['pct_ink']}%  cc {m_anime['n_ink_components']}")
        c3 = prep(col3, "infodraw contour", f"ink {m_contour['pct_ink']}%  cc {m_contour['n_ink_components']}")
        c4 = prep(col4, "fallback 2-poids", f"ink {m_2w['pct_ink']}%  cc {m_2w['n_ink_components']}")

        # Label de ligne (sujet) a gauche
        rowimg = np.hstack([c1, c2, c3, c4])
        lbl = np.full((rowimg.shape[0], 150, 3), 230, dtype=np.uint8)
        cv2.putText(lbl, f"3d_{subj}", (10, rowimg.shape[0] // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2, cv2.LINE_AA)
        rows.append(np.hstack([lbl, rowimg]))

        per_subject_stats[rid] = {
            "L25_poc1": m_l25,
            "infodraw_anime": m_anime,
            "infodraw_contour": m_contour,
            "fallback_2weight": {**m_2w, **meta2w, "time_s": t_2w},
        }
        print(f"[S2b-cmp] {rid:12s} L25={m_l25['pct_ink']:5.2f}% "
              f"anime={m_anime['pct_ink']:5.2f}% contour={m_contour['pct_ink']:5.2f}% "
              f"2w={m_2w['pct_ink']:5.2f}%", flush=True)

    planche = np.vstack(rows)
    # Bandeau titre
    title = np.full((60, planche.shape[1], 3), 255, dtype=np.uint8)
    cv2.putText(title, "S2b - 3D : 4 sources d'encre (L<25 | infodraw anime | infodraw contour | fallback 2-poids)",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 2, cv2.LINE_AA)
    planche = np.vstack([title, planche])
    out_png = OUT_DIR / "planche_s2b_3d.png"
    cv2.imwrite(str(out_png), cv2.cvtColor(planche, cv2.COLOR_RGB2BGR))
    print(f"\nOK planche : {out_png}")

    (OUT_DIR / "s2b_compare_stats.json").write_text(
        json.dumps({"branch": "S2b", "per_subject": per_subject_stats},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
