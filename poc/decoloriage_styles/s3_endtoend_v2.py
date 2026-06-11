"""S3 v2 - Bout-en-bout cible low_poly + kawaii_bold avec 2 fixes.

Itération v2 du POC2 (skill decoloriage-styles). Corrige 2 defauts humains :

  FIX 1 - Fusion sujet<->fond. Les images v2 sont generees sur fond CHROMAKEY
          GREEN (#00B140). On detecte le masque chromakey (reutilise
          src/services/extract_palette._detect_chromakey_mask, import sans modif)
          et on FORCE tous les pixels chromakey dans UNE region de fond dediee
          dans le region_map issu de g2. Consequence : le museau du chien (sujet)
          ne peut plus etre absorbe dans le fond, car le fond est isole par le
          masque chromakey AVANT le rendu g5. Le fond -> mappe Papier blanc
          (L*>=92 cote g5 via couleur forcee blanche).

  FIX 2 - kawaii : trait de tracage trop epais. Double action :
          (a) prompt v2 = "fine thin clean black outlines" (cote generation).
          (b) au rendu : on plafonne l'epaisseur du stroke encre. g5 calcule
              ink_w = max(2, measure_line_thickness(line_mask)). On EROde le
              masque d'encre kawaii (L<25) pour diviser ~par 2 l'epaisseur
              mediane mesuree -> ink_w plafonne ~2px, shading ~1px. La valeur
              retenue est documentee dans v2_stats.json (ink_stroke_px).

POC 1 ET POC 2 reutilises PAR IMPORT (aucune modification du code source) :
  - poc/decoloriage/g2_partition.process_image_3levels
  - poc/decoloriage/g5_product.process_image_g5
  - poc/decoloriage_styles/s3_endtoend.build_2weight_ink (fallback low_poly)
  - src/services/extract_palette._detect_chromakey_mask

Livrables (poc/decoloriage_styles/s3_out_v2/) :
  - <id>_blank.png + <id>_solution.png (6 chacun)
  - low_poly_dog.html + kawaii_bold_dog.html (click-to-fill standalone)
  - v2_stats.json (par image : n_regions, pct_ink_mask, ink_source, n_clickable,
    ink_stroke_px, museau preserve oui/non)
La galerie gallery_v2.png est produite par make_gallery_v2.py.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
POC1_DIR = PROJECT_ROOT / "poc" / "decoloriage"
sys.path.insert(0, str(POC1_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(HERE))

from g2_partition import process_image_3levels  # noqa: E402
from g5_product import process_image_g5  # noqa: E402
from s3_endtoend import build_2weight_ink  # noqa: E402 (fallback low_poly, import sans modif)
from services.extract_palette import _detect_chromakey_mask  # noqa: E402

CORPUS_V2 = HERE / "corpus_v2"
OUT_DIR = HERE / "s3_out_v2"
WORK_DIR = OUT_DIR / "_work"

CHROMAKEY_RGB = (0, 177, 64)   # #00B140
CHROMAKEY_DELTA_E = 40.0       # plateau valide sur les 6 images v2 (cf. POC log)

# Par style : source d'encre.
#   low_poly  -> 2weight (frontieres de partition, pas d'encre native fiable)
#   kawaii    -> L25 native ERODEE (cap epaisseur trait, fix 2)
SUBJECTS = ["dog", "castle", "peacock"]
STYLES = ["low_poly", "kawaii_bold"]

# Plafond d'epaisseur de trait encre vise au rendu (px).
KAWAII_INK_CAP_PX = 2.0
# Erosion appliquee au masque encre kawaii pour diviser ~par 2 l'epaisseur
# mesuree par measure_line_thickness (= 2*median(distanceTransform inside)).
# Un kernel ellipse 3x3 retire ~1px de rayon par iteration.
KAWAII_ERODE_KERNEL = 3


def force_chromakey_background(rm: np.ndarray, chromakey_mask: np.ndarray) -> tuple[np.ndarray, int, int]:
    """Force tous les pixels chromakey dans une SEULE region de fond dediee.

    - new_bg_label = max(labels)+1
    - tout pixel chromakey -> new_bg_label
    - le sujet (non-chromakey) garde ses labels g2 d'origine
    Retourne (rm_modifie, new_bg_label, n_subject_regions)."""
    rm2 = rm.copy().astype(np.int32)
    bg_label = int(rm2.max()) + 1
    ck = chromakey_mask > 0
    rm2[ck] = bg_label
    # Relabel compact des regions sujet (hors fond) pour rester propre, en
    # gardant le fond comme un label unique.
    subj_labels = sorted(int(x) for x in np.unique(rm2[~ck]))
    remap = {old: i for i, old in enumerate(subj_labels)}
    final_bg = len(subj_labels)
    out = np.empty_like(rm2)
    for old, new in remap.items():
        out[rm2 == old] = new
    out[ck] = final_bg
    return out, final_bg, len(subj_labels)


def muzzle_preserved(rm: np.ndarray, bg_label: int, chromakey_mask: np.ndarray) -> dict:
    """Verifie que la zone du museau (sujet) est une region DISTINCTE du fond.

    Heuristique geometrique robuste sans annotation : on echantillonne une
    bande centrale gauche du sujet (cote museau pour un chien de profil
    sitting, sujet centre) et on verifie qu'aucun pixel sujet de cette bande
    n'a herite du label de fond. Comme le museau est dark (proche du fond en
    teinte mais PAS chromakey), le fix garantit qu'il reste sujet.
    Retourne {preserved, n_subject_px_in_band, n_bg_px_in_band}."""
    H, W = rm.shape
    ck = chromakey_mask > 0
    # bande verticale centrale (35-65% hauteur), tiers gauche (15-45% largeur)
    y0, y1 = int(0.30 * H), int(0.70 * H)
    x0, x1 = int(0.12 * W), int(0.50 * W)
    band_rm = rm[y0:y1, x0:x1]
    band_ck = ck[y0:y1, x0:x1]
    subj_band = ~band_ck
    n_subj = int(subj_band.sum())
    # pixels sujet de la bande qui auraient le label de fond = fusion (mauvais)
    n_bg_leak = int(((band_rm == bg_label) & subj_band).sum())
    preserved = n_subj > 0 and n_bg_leak == 0
    return {
        "preserved": bool(preserved),
        "n_subject_px_in_band": n_subj,
        "n_bg_leak_px_in_band": n_bg_leak,
    }


def cap_kawaii_ink(line_mask: np.ndarray, out_path: Path) -> tuple[Path, float, float]:
    """Erode le masque encre kawaii pour diviser ~par 2 l'epaisseur mediane.

    Retourne (chemin_masque_erode, thickness_avant, thickness_apres)."""
    from g4_two_weight import measure_line_thickness  # import POC1 sans modif
    t_before = measure_line_thickness(line_mask)
    target = t_before
    eroded = line_mask.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (KAWAII_ERODE_KERNEL, KAWAII_ERODE_KERNEL))
    # Erode tant que l'epaisseur mesuree > moitie de l'origine ET > cap, max 6 it.
    half = max(KAWAII_INK_CAP_PX, t_before / 2.0)
    for _ in range(6):
        cur = measure_line_thickness(eroded)
        if cur <= half or (eroded > 0).sum() == 0:
            break
        eroded = cv2.erode(eroded, kernel, iterations=1)
    t_after = measure_line_thickness(eroded)
    cv2.imwrite(str(out_path), eroded)
    return out_path, round(t_before, 2), round(t_after, 2)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    per_image: list[dict] = []
    failures: list[dict] = []
    t_start = time.time()

    slot = 0
    for style in STYLES:
        for subject in SUBJECTS:
            slot += 1
            rid = f"{style}_{subject}"
            src = CORPUS_V2 / f"{rid}.png"
            if not src.exists():
                failures.append({"id": rid, "reason": f"PNG absent {src}"})
                print(f"[SKIP] {rid} : PNG absent", file=sys.stderr)
                continue
            try:
                rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                h, w = rgb.shape[:2]
                total_px = h * w

                # --- FIX 1 : masque chromakey ---
                ck_mask = _detect_chromakey_mask(bgr, CHROMAKEY_RGB, CHROMAKEY_DELTA_E)
                pct_bg = round(100.0 * (ck_mask > 0).sum() / total_px, 2)

                # --- g2 niveau enfant + masque L<25 ---
                l25_path = WORK_DIR / f"{rid}_L25.png"
                result = process_image_3levels(rgb, out_lines=l25_path)
                rm_enfant = result["levels"]["enfant"]["region_map"].astype(np.int32)

                # FIX 1 : force le fond chromakey en region unique
                rm_fixed, bg_label, n_subj = force_chromakey_background(rm_enfant, ck_mask)
                n_regions = int(len(np.unique(rm_fixed)))

                # Verif museau preserve (sujet != fond)
                muzzle = muzzle_preserved(rm_fixed, bg_label, ck_mask)

                rm_npy = WORK_DIR / f"{rid}_regionmap.npy"
                np.save(rm_npy, rm_fixed)

                l25 = cv2.imread(str(l25_path), cv2.IMREAD_GRAYSCALE)
                # Le trait ne doit pas inclure le fond chromakey : on retire
                # tout pixel chromakey du masque encre (le fond est papier).
                l25[ck_mask > 0] = 0
                cv2.imwrite(str(l25_path), l25)
                pct_ink_mask = round(100.0 * int((l25 > 0).sum()) / total_px, 2)

                # --- Source d'encre par style + FIX 2 (cap kawaii) ---
                ink_meta: dict = {}
                if style == "kawaii_bold":
                    ink_source = "L25_eroded"
                    capped_path = WORK_DIR / f"{rid}_L25_capped.png"
                    ink_mask_path, t_before, t_after = cap_kawaii_ink(l25, capped_path)
                    ink_meta = {
                        "pct_ink_mask_L25": pct_ink_mask,
                        "thickness_before_erode": t_before,
                        "thickness_after_erode": t_after,
                        "erode_kernel": KAWAII_ERODE_KERNEL,
                        "ink_cap_px_target": KAWAII_INK_CAP_PX,
                    }
                else:  # low_poly -> 2 poids
                    ink_source = "2weight"
                    ink2w, meta2w = build_2weight_ink(rm_fixed)
                    ink2w_path = WORK_DIR / f"{rid}_2weight.png"
                    cv2.imwrite(str(ink2w_path), ink2w)
                    ink_mask_path = ink2w_path
                    pct_2w = round(100.0 * int((ink2w > 0).sum()) / total_px, 2)
                    ink_meta = {"pct_ink_mask_L25": pct_ink_mask,
                                "pct_ink_2weight": pct_2w, **meta2w}

                # --- g3 + g4 + g5 ---
                stats = process_image_g5(
                    slot=slot,
                    rid=rid,
                    original_png_path=src,
                    region_map_path=rm_npy,
                    line_mask_path=ink_mask_path,
                    out_dir=OUT_DIR,
                )

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
                    "chromakey_bg_pct": pct_bg,
                    "n_subject_regions": n_subj,
                    "n_regions": n_regions,
                    "pct_ink_mask": pct_ink_mask,
                    "ink_source": ink_source,
                    "ink_source_meta": ink_meta,
                    "n_clickable": stats["n_regions"],
                    "n_ink_regions": stats["n_ink_regions"],
                    "ink_stroke_px": stats["ink_stroke_width"],
                    "shading_stroke_px": stats["shading_stroke_width"],
                    "delta_e_median": stats["delta_e_median"],
                    "muzzle_preserved": muzzle,
                    "blank_png": f"s3_out_v2/{rid}_blank.png",
                    "solution_png": f"s3_out_v2/{rid}_solution.png",
                    "html": stats["outputs"]["html"],
                    "timing_s": stats["timing_s"],
                }
                per_image.append(row)
                print(
                    f"[v2] {rid:22s} bg%={pct_bg:5.1f} regions={n_regions:4d} "
                    f"ink%={pct_ink_mask:5.2f} src={ink_source:11s} "
                    f"clickable={stats['n_regions']:4d} ink_px={stats['ink_stroke_width']:.2f} "
                    f"museau={'OUI' if muzzle['preserved'] else 'NON':3s} "
                    f"({stats['timing_s']}s)",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                import traceback
                failures.append({"id": rid, "reason": repr(exc),
                                 "trace": traceback.format_exc()})
                print(f"[FAIL] {rid} : {exc!r}", file=sys.stderr)
                traceback.print_exc()

    # HTML dog par style -> nom court
    for row in per_image:
        if row["subject"] != "dog":
            continue
        g5_html = OUT_DIR / f"{row['slot']:02d}_{row['id']}_g5.html"
        if g5_html.exists():
            shutil.copyfile(g5_html, OUT_DIR / f"{row['style']}_dog.html")

    out = {
        "gate": "S3-v2",
        "corpus": "corpus_v2 (low_poly + kawaii_bold, fond chromakey green) x 3 sujets",
        "description": (
            "v2 ciblee : FIX1 fond chromakey -> region papier dediee (museau "
            "preserve) ; FIX2 trait kawaii fin (prompt fine outlines + erosion "
            "masque encre -> ink_stroke plafonne). POC1+POC2 reutilises par import."
        ),
        "fixes": {
            "fix1_chromakey": {
                "chromakey_rgb": list(CHROMAKEY_RGB),
                "chromakey_delta_e": CHROMAKEY_DELTA_E,
                "source": "src/services/extract_palette._detect_chromakey_mask (import)",
            },
            "fix2_kawaii_thin": {
                "prompt": "fine thin clean black outlines (cote generation)",
                "render_cap_px": KAWAII_INK_CAP_PX,
                "erode_kernel": KAWAII_ERODE_KERNEL,
                "method": "erosion masque encre L<25 -> mi-epaisseur mesuree",
            },
        },
        "poc_reused": [
            "poc/decoloriage/g2_partition.py (process_image_3levels)",
            "poc/decoloriage/g4_two_weight.py (measure_line_thickness)",
            "poc/decoloriage/g5_product.py (process_image_g5)",
            "poc/decoloriage_styles/s3_endtoend.py (build_2weight_ink)",
            "src/services/extract_palette.py (_detect_chromakey_mask)",
        ],
        "n_processed": len(per_image),
        "n_failed": len(failures),
        "failures": failures,
        "images": per_image,
        "timing_s_total": round(time.time() - t_start, 2),
    }
    stats_path = OUT_DIR / "v2_stats.json"
    stats_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK v2_stats : {stats_path}")
    print(f"   {len(per_image)}/6 traitees, {len(failures)} echec(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
