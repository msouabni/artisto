"""S1 - Planche contact 12x2 : original | partition enfant.

12 lignes (3 sujets x 4 styles), groupees et labellees par style+sujet.
Reutilise le style PIL de poc/decoloriage/make_contact_sheet_g2.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus.json"
STATS = HERE / "s1_out" / "s1_stats.json"
SHEET = HERE / "s1_out" / "contact_sheet_s1.png"

BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE = (20, 20, 25)

STYLE_COLORS = {
    "manga": (127, 188, 210),
    "realiste": (205, 80, 84),
    "peinture": (243, 169, 83),
    "3d": (120, 170, 120),
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
    # Ordre : groupe par style (manga, realiste, peinture, 3d), sujets dans l'ordre corpus.
    style_order = corpus["styles"]
    items = sorted(
        corpus["images"],
        key=lambda it: (style_order.index(it["style"]), it["slot"]),
    )

    THUMB = 300
    GAP = 12
    PAD = 28
    LABEL_W = 230
    HEADER_H = 96
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
        "mono": _font(16),
        "stat": _font(14),
        "head": _font(20),
    }

    p = stats["params_verbatim_poc1"]
    draw.text((PAD, PAD), "S1 - Baseline brute : POC 1 INCHANGE sur 12 styles (diagnostic)", fill=TITLE, font=fonts["title"])
    draw.text(
        (PAD, PAD + 42),
        f"g1a_v3 (meanshift sp={p['meanshift_sp']}/sr={p['meanshift_sr']} + kmeans Lab k={p['kmeans_k']} "
        f"+ merge_v3) -> g2 niveau enfant (smooth ΔE<{p['enfant_smooth_merge_thresh']}) "
        f"| masque traits L<{p['lines_L_threshold']} + close 3x3",
        fill=SUB,
        font=fonts["subtitle"],
    )
    draw.text(
        (PAD, PAD + 66),
        "Aucune adaptation. Colonnes : original ERNIE | partition enfant (contours). Verdict pass/kill par style = humain.",
        fill=SUB,
        font=fonts["small"],
    )

    grid_y0 = PAD + HEADER_H
    col_xs = [PAD + LABEL_W, PAD + LABEL_W + THUMB + GAP]
    for c, txt in enumerate(["original ERNIE", "partition enfant"]):
        draw.text((col_xs[c] + 4, grid_y0 - 26), txt, fill=TEXT, font=fonts["head"])

    for idx, item in enumerate(items):
        y = grid_y0 + idx * (row_h + GAP)
        rid = item["id"]
        style = item["style"]
        subject = item["subject"]
        scolor = STYLE_COLORS.get(style, SUB)
        r = by_id.get(rid, {})

        # Label gauche : style (couleur) + sujet + metriques
        draw.text((PAD, y + 6), style.upper(), fill=scolor, font=fonts["mono"])
        draw.text((PAD, y + 28), subject, fill=TEXT, font=fonts["mono"])
        draw.text((PAD, y + 56), f"regions : {r.get('n_regions_final', '?')}", fill=SUB, font=fonts["stat"])
        draw.text((PAD, y + 76), f"ink% : {r.get('pct_ink_mask', '?')}", fill=SUB, font=fonts["stat"])
        draw.text((PAD, y + 96), f"sliver : {r.get('sliver_ratio', '?')}", fill=SUB, font=fonts["stat"])

        # Original
        orig = (HERE / item["path"]).resolve()
        if orig.exists():
            with Image.open(orig) as im:
                sheet.paste(_fit(im, THUMB), (col_xs[0], y))

        # Partition enfant
        ep = r.get("enfant_png")
        if ep:
            epp = (HERE / ep).resolve()
            if epp.exists():
                with Image.open(epp) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[1], y))

    SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEET, "PNG", optimize=True)
    print(f"OK planche : {SHEET}  ({SHEET.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
