"""Galerie v2 - comparatif des 2 fixes (chromakey museau + trait kawaii fin).

Bloc A (preuve des fixes) : pour dog des 2 styles, v1 blank | v2 blank cote a
  cote. Montre que le museau est preserve (low_poly) et le trait kawaii plus fin.
Bloc B (rendu v2) : par style, les 3 sujets en v2 blank | solution.

Reutilise le style PIL de make_gallery_s3.py (helpers _font/_fit).
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
STATS_V2 = HERE / "s3_out_v2" / "v2_stats.json"
STATS_V1 = HERE / "s3_out" / "s3_stats.json"
V1_DIR = HERE / "s3_out"
V2_DIR = HERE / "s3_out_v2"
SHEET = V2_DIR / "gallery_v2.png"

BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE = (20, 20, 25)
OK = (40, 150, 80)

STYLE_COLORS = {"low_poly": (120, 170, 120), "kawaii_bold": (210, 95, 150)}
STYLES = ["low_poly", "kawaii_bold"]
SUBJECTS = ["dog", "castle", "peacock"]


def _font(size: int):
    for path in ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _fit(img: Image.Image, side: int) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    scale = side / max(w, h)
    new = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    img = img.resize(new, Image.LANCZOS)
    canvas = Image.new("RGB", (side, side), CARD_BG)
    canvas.paste(img, ((side - new[0]) // 2, (side - new[1]) // 2))
    return canvas


def main() -> int:
    v2 = json.loads(STATS_V2.read_text(encoding="utf-8"))
    v2_by_id = {r["id"]: r for r in v2["images"]}
    v1_by_id = {}
    if STATS_V1.exists():
        v1 = json.loads(STATS_V1.read_text(encoding="utf-8"))
        v1_by_id = {r["id"]: r for r in v1["images"]}

    THUMB = 300
    GAP = 12
    PAD = 28
    LABEL_W = 230
    HEADER_H = 120
    row_h = THUMB + 24

    # Bloc A : 2 lignes (low_poly_dog, kawaii_bold_dog), 2 col (v1 blank | v2 blank)
    # Bloc B : 6 lignes (2 styles x 3 sujets), 2 col (v2 blank | v2 solution)
    n_rows_A = 2
    n_rows_B = len(STYLES) * len(SUBJECTS)
    section_gap = 60

    sheet_w = PAD * 2 + LABEL_W + 2 * THUMB + GAP
    sheet_h = (PAD * 2 + HEADER_H
               + 30 + n_rows_A * (row_h + GAP)
               + section_gap
               + 30 + n_rows_B * (row_h + GAP))

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    f = {"title": _font(30), "sub": _font(16), "small": _font(13),
         "mono": _font(17), "stat": _font(13), "head": _font(19), "sec": _font(22)}

    draw.text((PAD, PAD), "v2 ciblee - low_poly + kawaii_bold : 2 fixes",
              fill=TITLE, font=f["title"])
    draw.text((PAD, PAD + 40),
              "FIX1 fond chromakey green -> region papier dediee (museau preserve). "
              "FIX2 trait kawaii fin (prompt + erosion masque encre, ink cap 2px).",
              fill=SUB, font=f["sub"])
    draw.text((PAD, PAD + 64),
              "POC1+POC2 reutilises par import. Verdict publiable/non = humain.",
              fill=SUB, font=f["small"])

    col_xs = [PAD + LABEL_W, PAD + LABEL_W + THUMB + GAP]
    y = PAD + HEADER_H

    # ---- Bloc A ----
    draw.text((PAD, y), "A - Preuve des fixes : dog v1 vs v2", fill=TITLE, font=f["sec"])
    y += 32
    for c, txt in enumerate(["v1 blank (defaut)", "v2 blank (fixe)"]):
        draw.text((col_xs[c] + 4, y - 22), txt, fill=TEXT, font=f["head"])
    for style in STYLES:
        rid = f"{style}_dog"
        scolor = STYLE_COLORS[style]
        r2 = v2_by_id.get(rid, {})
        r1 = v1_by_id.get(rid, {})
        draw.text((PAD, y + 6), style.upper(), fill=scolor, font=f["mono"])
        draw.text((PAD, y + 32), "dog", fill=TEXT, font=f["mono"])
        v1_ink = r1.get("ink_stroke_width", "?")
        v2_ink = r2.get("ink_stroke_px", "?")
        mus = r2.get("muzzle_preserved", {}).get("preserved")
        draw.text((PAD, y + 60), f"v1 ink_px : {v1_ink}", fill=SUB, font=f["stat"])
        draw.text((PAD, y + 80), f"v2 ink_px : {v2_ink}", fill=scolor, font=f["stat"])
        draw.text((PAD, y + 100), f"v1 cliquables : {r1.get('n_clickable','?')}", fill=SUB, font=f["stat"])
        draw.text((PAD, y + 120), f"v2 cliquables : {r2.get('n_clickable','?')}", fill=SUB, font=f["stat"])
        draw.text((PAD, y + 142), f"museau : {'PRESERVE' if mus else 'NON'}",
                  fill=OK if mus else (200, 60, 60), font=f["stat"])

        # v1 blank
        v1_blank = V1_DIR / f"{r1.get('slot', 0):02d}_{rid}_g5_blank.png"
        if v1_blank.exists():
            with Image.open(v1_blank) as im:
                sheet.paste(_fit(im, THUMB), (col_xs[0], y))
        # v2 blank
        v2_blank = V2_DIR / f"{rid}_blank.png"
        if v2_blank.exists():
            with Image.open(v2_blank) as im:
                sheet.paste(_fit(im, THUMB), (col_xs[1], y))
        y += row_h + GAP

    y += section_gap - GAP

    # ---- Bloc B ----
    draw.text((PAD, y), "B - Rendu v2 : 3 sujets par style (blank | solution)",
              fill=TITLE, font=f["sec"])
    y += 32
    for c, txt in enumerate(["v2 blank", "v2 solution (couleurs ERNIE)"]):
        draw.text((col_xs[c] + 4, y - 22), txt, fill=TEXT, font=f["head"])
    for style in STYLES:
        for subject in SUBJECTS:
            rid = f"{style}_{subject}"
            scolor = STYLE_COLORS[style]
            r2 = v2_by_id.get(rid, {})
            draw.text((PAD, y + 6), style.upper(), fill=scolor, font=f["mono"])
            draw.text((PAD, y + 32), subject, fill=TEXT, font=f["mono"])
            draw.text((PAD, y + 60), f"cliquables : {r2.get('n_clickable','?')}", fill=SUB, font=f["stat"])
            draw.text((PAD, y + 80), f"ink_px : {r2.get('ink_stroke_px','?')}", fill=scolor, font=f["stat"])
            draw.text((PAD, y + 100), f"src : {r2.get('ink_source','?')}", fill=SUB, font=f["stat"])
            draw.text((PAD, y + 120), f"dE med : {r2.get('delta_e_median','?')}", fill=SUB, font=f["stat"])
            mus = r2.get("muzzle_preserved", {}).get("preserved")
            draw.text((PAD, y + 140), f"sujet!=fond : {'OUI' if mus else 'NON'}",
                      fill=OK if mus else (200, 60, 60), font=f["stat"])
            blank = V2_DIR / f"{rid}_blank.png"
            sol = V2_DIR / f"{rid}_solution.png"
            if blank.exists():
                with Image.open(blank) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[0], y))
            if sol.exists():
                with Image.open(sol) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[1], y))
            y += row_h + GAP

    SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEET, "PNG", optimize=True)
    print(f"OK galerie v2 : {SHEET}  ({SHEET.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
