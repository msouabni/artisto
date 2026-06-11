"""S3 - Bout-en-bout par style (POC 2 decoloriage-styles, corpus adapte).

Pour chacune des 12 images (4 styles x 3 sujets) :
  1. g2 (process_image_3levels) -> region_map ENFANT + masque traits L<25
     + pct_ink_mask.
  2. Choix de la SOURCE D'ENCRE, par style, documente :
       - encre native dense (pct_ink_mask >= INK_DENSE_THRESHOLD) -> masque L<25.
       - sinon (peu d'encre native) -> fallback frontieres de partition en
         2 poids (g4 extract_topological_arcs : frontieres sujet/fond epaisses,
         internes fines).
     La couche encre retenue est ecrite comme line_mask, qui est l'entree de g5.
  3. g3 (vectorisation) + g4 (2 poids ink/shading) + g5 (SVG bicouche
     click-to-fill) via g5_product.process_image_g5 (POC 1, reutilise par import).

POC 1 reutilise PAR IMPORT (aucune modification) :
  - g2_partition.process_image_3levels
  - g4_two_weight.extract_topological_arcs
  - g5_product.process_image_g5 + nearest_crayon + assemblage SVG/HTML

Livrables (poc/decoloriage_styles/s3_out/) :
  - <id>_blank.png + <id>_solution.png (rendus g5, copies normalisees).
  - <style>_dog.html (1 HTML interactif click-to-fill par style).
  - s3_stats.json (par image + agregats par style).
La galerie gallery_s3.png est produite par make_gallery_s3.py.
"""
from __future__ import annotations

import json
import shutil
import statistics
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
from g5_product import process_image_g5  # noqa: E402

CORPUS = HERE / "corpus_adapted.json"
OUT_DIR = HERE / "s3_out"
WORK_DIR = OUT_DIR / "_work"  # region_map.npy + line_mask intermediaires

# Seuil au-dessus duquel on considere l'encre native dense (-> masque L<25).
# En dessous : fallback frontieres de partition 2 poids.
# Calibre a partir des densites mesurees : kawaii_bold/stained_glass attendus
# denses, low_poly/papercut attendus pauvres en encre native.
INK_DENSE_THRESHOLD = 6.0  # % pixels couverts par L<25

# Fallback 2 poids (px). Epais = frontieres touchant le label de fond.
THICK_W = 4
THIN_W = 1


def build_2weight_ink(rm: np.ndarray) -> tuple[np.ndarray, dict]:
    """Frontieres de partition en 2 poids -> masque encre uint8 0/255.
    Epais = arcs touchant le label de fond (silhouette sujet/fond), fin =
    internes. Reutilise g4 extract_topological_arcs (label_pair par arc)."""
    H, W = rm.shape
    border = np.concatenate([rm[0, :], rm[-1, :], rm[:, 0], rm[:, -1]])
    bg_label = int(np.bincount(border).argmax())

    arcs, _stats = extract_topological_arcs(rm)
    canvas = np.zeros((H, W), dtype=np.uint8)
    n_thick = 0
    n_thin = 0
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
            n_thick += 1
        else:
            n_thin += 1
    return canvas, {
        "bg_label": bg_label,
        "n_arcs": len(arcs),
        "n_thick_arcs": n_thick,
        "n_thin_arcs": n_thin,
        "thick_w": THICK_W,
        "thin_w": THIN_W,
    }


def choose_ink_source(style: str, pct_ink_mask: float) -> str:
    """Politique par style documentee dans le brief :
      - kawaii_bold, stained_glass : encre native dense -> 'L25'.
      - low_poly, papercut : peu/pas d'encre native -> '2weight'.
    On confirme via pct_ink_mask : si dense (>= seuil) -> L25, sinon 2weight.
    Le style oriente l'attente ; la mesure tranche le cas limite."""
    if pct_ink_mask >= INK_DENSE_THRESHOLD:
        return "L25"
    return "2weight"


def main() -> int:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = data["images"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    per_image: list[dict] = []
    failures: list[dict] = []
    t_start = time.time()

    for item in items:
        rid = item["id"]
        slot = item["slot"]
        style = item["style"]
        subject = item["subject"]
        src = (HERE / item["path"]).resolve()
        if not src.exists():
            failures.append({"id": rid, "reason": f"PNG absent {src}"})
            print(f"[SKIP] {rid} : PNG absent", file=sys.stderr)
            continue

        try:
            rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            total_px = h * w

            # --- 1) g2 niveau enfant + masque L<25 ---
            l25_path = WORK_DIR / f"{rid}_L25.png"
            result = process_image_3levels(rgb, out_lines=l25_path)
            rm_enfant = result["levels"]["enfant"]["region_map"].astype(np.int32)
            n_regions = int(len(np.unique(rm_enfant)))

            l25 = cv2.imread(str(l25_path), cv2.IMREAD_GRAYSCALE)
            n_ink = int((l25 > 0).sum())
            pct_ink_mask = round(100.0 * n_ink / total_px, 2)

            # region_map.npy pour g5
            rm_npy = WORK_DIR / f"{rid}_regionmap.npy"
            np.save(rm_npy, rm_enfant)

            # --- 2) Choix source d'encre ---
            ink_source = choose_ink_source(style, pct_ink_mask)
            if ink_source == "L25":
                ink_mask_path = l25_path
                ink_meta = {"pct_ink_mask_L25": pct_ink_mask}
            else:
                ink2w, meta2w = build_2weight_ink(rm_enfant)
                ink2w_path = WORK_DIR / f"{rid}_2weight.png"
                cv2.imwrite(str(ink2w_path), ink2w)
                ink_mask_path = ink2w_path
                pct_2w = round(100.0 * int((ink2w > 0).sum()) / total_px, 2)
                ink_meta = {"pct_ink_mask_L25": pct_ink_mask,
                            "pct_ink_2weight": pct_2w, **meta2w}

            # --- 3) g3 + g4 + g5 (process_image_g5) ---
            stats = process_image_g5(
                slot=slot,
                rid=rid,
                original_png_path=src,
                region_map_path=rm_npy,
                line_mask_path=ink_mask_path,
                out_dir=OUT_DIR,
            )

            # Copies normalisees blank / solution (noms attendus par le brief)
            g5_blank = OUT_DIR / f"{slot:02d}_{rid}_g5_blank.png"
            g5_sol = OUT_DIR / f"{slot:02d}_{rid}_g5_solution.png"
            shutil.copyfile(g5_blank, OUT_DIR / f"{rid}_blank.png")
            shutil.copyfile(g5_sol, OUT_DIR / f"{rid}_solution.png")

            row = {
                "id": rid,
                "slot": slot,
                "style": style,
                "subject": subject,
                "image_size": [int(w), int(h)],
                "n_regions": n_regions,
                "pct_ink_mask": pct_ink_mask,
                "ink_source_chosen": ink_source,
                "ink_source_meta": ink_meta,
                "n_clickable": stats["n_regions"],
                "n_ink_regions": stats["n_ink_regions"],
                "delta_e_median": stats["delta_e_median"],
                "n_arcs": stats["n_arcs"],
                "n_ink_arcs": stats["n_ink"],
                "n_shading_arcs": stats["n_shading"],
                "ink_stroke_width": stats["ink_stroke_width"],
                "blank_png": f"s3_out/{rid}_blank.png",
                "solution_png": f"s3_out/{rid}_solution.png",
                "html": stats["outputs"]["html"],
                "timing_s": stats["timing_s"],
            }
            per_image.append(row)
            print(
                f"[S3] {rid:22s} style={style:13s} regions={n_regions:4d} "
                f"ink%={pct_ink_mask:6.2f} src={ink_source:8s} "
                f"clickable={stats['n_regions']:4d} ink_reg={stats['n_ink_regions']:3d} "
                f"dE={stats['delta_e_median']:5.1f} ({stats['timing_s']}s)",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            import traceback
            failures.append({"id": rid, "reason": repr(exc),
                             "trace": traceback.format_exc()})
            print(f"[FAIL] {rid} : {exc!r}", file=sys.stderr)
            traceback.print_exc()

    # --- HTML dog par style : copie depuis g5 HTML produit, renomme ---
    html_dog_paths: dict[str, str] = {}
    for row in per_image:
        if row["subject"] != "dog":
            continue
        style = row["style"]
        slot = row["slot"]
        rid = row["id"]
        g5_html = OUT_DIR / f"{slot:02d}_{rid}_g5.html"
        if g5_html.exists():
            dest = OUT_DIR / f"{style}_dog.html"
            shutil.copyfile(g5_html, dest)
            html_dog_paths[style] = f"s3_out/{style}_dog.html"

    # --- Agregats par style ---
    by_style: dict[str, list[dict]] = {}
    for r in per_image:
        by_style.setdefault(r["style"], []).append(r)

    aggregates = {}
    for style, rows in by_style.items():
        sources = {r["ink_source_chosen"] for r in rows}
        aggregates[style] = {
            "n_images": len(rows),
            "median_n_regions": round(statistics.median(r["n_regions"] for r in rows), 1),
            "median_pct_ink_mask": round(statistics.median(r["pct_ink_mask"] for r in rows), 2),
            "median_n_clickable": round(statistics.median(r["n_clickable"] for r in rows), 1),
            "median_n_ink_regions": round(statistics.median(r["n_ink_regions"] for r in rows), 1),
            "median_delta_e": round(statistics.median(r["delta_e_median"] for r in rows), 2),
            "ink_source_chosen": sorted(sources),
        }

    out = {
        "gate": "S3",
        "corpus": "corpus_adapted.json (4 styles adaptes x 3 sujets)",
        "description": (
            "Bout-en-bout par style : g2 enfant + choix source d'encre "
            "(L<25 si dense, fallback frontieres partition 2 poids sinon) + "
            "g3/g4/g5 SVG bicouche click-to-fill. POC 1 reutilise par import. "
            "Verdict publiable/non = humain, par style."
        ),
        "params": {
            "ink_dense_threshold_pct": INK_DENSE_THRESHOLD,
            "fallback_2weight_thick_w": THICK_W,
            "fallback_2weight_thin_w": THIN_W,
            "ink_source_policy": (
                "kawaii_bold/stained_glass attendus denses -> L<25 ; "
                "low_poly/papercut attendus pauvres -> 2weight ; "
                "tranche par pct_ink_mask >= seuil."
            ),
        },
        "poc1_reused": [
            "poc/decoloriage/g2_partition.py (process_image_3levels)",
            "poc/decoloriage/g4_two_weight.py (extract_topological_arcs)",
            "poc/decoloriage/g5_product.py (process_image_g5 + nearest_crayon + SVG/HTML)",
        ],
        "n_processed": len(per_image),
        "n_failed": len(failures),
        "failures": failures,
        "html_dog_by_style": html_dog_paths,
        "images": per_image,
        "aggregates_by_style": aggregates,
        "timing_s_total": round(time.time() - t_start, 2),
    }
    stats_path = OUT_DIR / "s3_stats.json"
    stats_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK s3_stats : {stats_path}")
    print(f"   {len(per_image)}/12 traitees, {len(failures)} echec(s)")
    print(f"   HTML dog par style : {sorted(html_dog_paths.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
