"""S3 - Galerie 4 styles x 3 sujets, chaque cellule = blank | solution.

12 lignes (groupees par style, sujets dans l'ordre corpus), 2 colonnes
(blank | solution). Panneau de gauche : style + sujet + metriques + source
d'encre retenue. Reutilise le style PIL de make_contact_sheet_s1.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus_adapted.json"
STATS = HERE / "s3_out" / "s3_stats.json"
SHEET = HERE / "s3_out" / "gallery_s3.png"

BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE = (20, 20, 25)

STYLE_COLORS = {
    "low_poly": (120, 170, 120),
    "stained_glass": (127, 130, 210),
    "papercut": (243, 140, 83),
    "kawaii_bold": (210, 95, 150),
}


def _font(size: int):
    for path in [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
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
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    stats = json.loads(STATS.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in stats["images"]}
    style_order = corpus["styles"]
    items = sorted(
        corpus["images"],
        key=lambda it: (style_order.index(it["style"]), it["slot"]),
    )

    THUMB = 320
    GAP = 12
    PAD = 28
    LABEL_W = 250
    HEADER_H = 110
    COLS = 2
    ROWS = len(items)
    row_h = THUMB + 26

    sheet_w = PAD * 2 + LABEL_W + COLS * THUMB + (COLS - 1) * GAP
    sheet_h = PAD * 2 + HEADER_H + ROWS * row_h + (ROWS - 1) * GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    fonts = {
        "title": _font(32),
        "subtitle": _font(16),
        "small": _font(13),
        "mono": _font(17),
        "stat": _font(14),
        "head": _font(20),
    }

    draw.text((PAD, PAD), "S3 - Bout-en-bout decoloriage : 4 styles x 3 sujets (blank | solution)",
              fill=TITLE, font=fonts["title"])
    draw.text(
        (PAD, PAD + 42),
        "g2 enfant + source d'encre par style (L<25 si encre native dense, "
        "frontieres partition 2 poids sinon) -> g3/g4/g5 SVG bicouche click-to-fill.",
        fill=SUB, font=fonts["subtitle"],
    )
    draw.text(
        (PAD, PAD + 68),
        "Encre = fill noir non cliquable. Solution = couleurs ERNIE quantifiees 6 crayons (DeltaE Lab). "
        "Verdict publiable/non = humain, PAR STYLE.",
        fill=SUB, font=fonts["small"],
    )

    grid_y0 = PAD + HEADER_H
    col_xs = [PAD + LABEL_W, PAD + LABEL_W + THUMB + GAP]
    for c, txt in enumerate(["blank (depart coloriage)", "solution (couleurs ERNIE)"]):
        draw.text((col_xs[c] + 4, grid_y0 - 26), txt, fill=TEXT, font=fonts["head"])

    for idx, item in enumerate(items):
        y = grid_y0 + idx * (row_h + GAP)
        rid = item["id"]
        style = item["style"]
        subject = item["subject"]
        scolor = STYLE_COLORS.get(style, SUB)
        r = by_id.get(rid, {})

        draw.text((PAD, y + 6), style.upper(), fill=scolor, font=fonts["mono"])
        draw.text((PAD, y + 30), subject, fill=TEXT, font=fonts["mono"])
        draw.text((PAD, y + 58), f"regions : {r.get('n_regions', '?')}", fill=SUB, font=fonts["stat"])
        draw.text((PAD, y + 78), f"cliquables : {r.get('n_clickable', '?')}", fill=SUB, font=fonts["stat"])
        draw.text((PAD, y + 98), f"ink% : {r.get('pct_ink_mask', '?')}", fill=SUB, font=fonts["stat"])
        draw.text((PAD, y + 118), f"encre : {r.get('ink_source_chosen', '?')}", fill=scolor, font=fonts["stat"])
        draw.text((PAD, y + 138), f"dE med : {r.get('delta_e_median', '?')}", fill=SUB, font=fonts["stat"])

        blank = (HERE / r.get("blank_png", "")).resolve() if r.get("blank_png") else None
        sol = (HERE / r.get("solution_png", "")).resolve() if r.get("solution_png") else None
        if blank and blank.exists():
            with Image.open(blank) as im:
                sheet.paste(_fit(im, THUMB), (col_xs[0], y))
        if sol and sol.exists():
            with Image.open(sol) as im:
                sheet.paste(_fit(im, THUMB), (col_xs[1], y))

    SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEET, "PNG", optimize=True)
    print(f"OK galerie : {SHEET}  ({SHEET.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
