"""G5 - Planche galerie 10x2 :
   (1) preview blank   - line art ERNIE-style avec ink-regions = noir plein
   (2) preview solution - couleurs ERNIE quantifiees sur 6 crayons design system

+ stats par sujet : zones cliquables, regions encre, DeltaE median,
  crayons utilises, hollow-tube check (PASS / FAIL).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_G5_STATS = Path(__file__).parent / "g5_out" / "stats.json"
DEFAULT_SHEET = Path(__file__).parent / "contact_sheet_g5.png"

THUMB = 380
GAP = 14
PAD = 28
LABEL_W = 280
HEADER_H = 130
COLS = 2  # blank | solution

BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE = (20, 20, 25)
COL_BLANK = (60, 60, 75)
COL_SOL = (40, 110, 60)
RED = (200, 60, 30)
GREEN = (40, 130, 70)


def _font(size: int) -> ImageFont.ImageFont:
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


def build_sheet(corpus: dict, g5: dict, out_path: Path) -> Path:
    items = corpus["images"]
    by_slot = {s["slot"]: s for s in g5.get("images", [])}

    row_h = THUMB + 8
    sheet_w = PAD * 2 + LABEL_W + COLS * THUMB + (COLS - 1) * GAP
    sheet_h = PAD * 2 + HEADER_H + len(items) * row_h + (len(items) - 1) * GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    fonts = {
        "title": _font(32),
        "subtitle": _font(16),
        "small": _font(12),
        "mono": _font(16),
        "stat": _font(14),
        "stat_strong": _font(14),
        "head": _font(20),
    }

    p = g5["params"]
    hyp = g5.get("hollow_tube_check_global", {})
    n_pass = hyp.get("n_images_pass", 0)
    n_total = hyp.get("n_images_evaluated", len(items))
    pass_color = COL_SOL if n_pass == n_total else RED
    title = "G5 - Decoloriage batch - galerie 10 sujets (blank | solution)"
    subtitle = (
        f"Params : ink-region overlap >= {int(p['ink_region_overlap_threshold']*100)}%,"
        f" hollow-tube alert > {int(p['hollow_tube_overlap_threshold']*100)}%,"
        f" L* fond >= {int(p['background_L_threshold'])}, mapping ΔE Lab vs 6 crayons.   "
        f"Total : {g5.get('timing_s_total', '?')}s, DeltaE median global : {g5.get('delta_e_overall_median', '?')}"
    )
    draw.text((PAD, PAD), title, fill=TITLE, font=fonts["title"])
    draw.text((PAD, PAD + 42), subtitle, fill=SUB, font=fonts["subtitle"])
    draw.text(
        (PAD, PAD + 70),
        f"Hollow-tube check : {n_pass}/{n_total} pass (zero region cliquable avec "
        f"overlap > {int(p['hollow_tube_overlap_threshold']*100)}% sur le masque traits)",
        fill=pass_color, font=fonts["head"],
    )

    col_xs = [PAD + LABEL_W]
    for _ in range(COLS - 1):
        col_xs.append(col_xs[-1] + THUMB + GAP)
    col_titles = [
        ("(1) blank - line art ERNIE-style", COL_BLANK),
        ("(2) solution - 6 crayons + papier", COL_SOL),
    ]
    for c, (txt, col) in enumerate(col_titles):
        draw.text(
            (col_xs[c] + 4, PAD + HEADER_H - 26),
            txt,
            fill=col,
            font=fonts["head"],
        )

    grid_y0 = PAD + HEADER_H
    for idx, item in enumerate(items):
        y = grid_y0 + idx * (row_h + GAP)
        slot = item["slot"]
        rid = item["id"]
        cat = item["category"]
        s = by_slot.get(slot, {})

        draw.text((PAD, y + 6), f"#{slot:02d}", fill=SUB, font=fonts["mono"])
        draw.text((PAD, y + 24), cat.upper(), fill=SUB, font=fonts["small"])
        draw.text((PAD, y + 40), rid, fill=TEXT, font=fonts["mono"])

        # Stats principales
        n_reg = s.get("n_regions", "?")
        n_ink_reg = s.get("n_ink_regions", "?")
        delta_e = s.get("delta_e_median", "?")
        delta_e_max = s.get("delta_e_max", "?")
        n_arcs = s.get("n_arcs", "?")
        n_ink = s.get("n_ink", "?")
        n_shading = s.get("n_shading", "?")
        timing = s.get("timing_s", "?")

        line1 = f"{n_reg} zones cliquables"
        draw.text((PAD, y + 76), line1, fill=TEXT, font=fonts["stat_strong"])
        line2 = f"{n_ink_reg} regions-encre"
        draw.text((PAD, y + 96), line2, fill=SUB, font=fonts["stat"])
        line3 = f"arcs : {n_ink} encre + {n_shading} shading"
        draw.text((PAD, y + 116), line3, fill=SUB, font=fonts["stat"])
        line4 = f"DeltaE median {delta_e} (max {delta_e_max})"
        draw.text((PAD, y + 136), line4, fill=SUB, font=fonts["stat"])

        # Crayons distribution
        crayons_used = s.get("crayons_used", {})
        y_palette = y + 162
        x_palette = PAD
        for crayon in g5.get("crayons", []):
            cnt = crayons_used.get(crayon["hex"], 0)
            if cnt == 0:
                continue
            # rect 12x12 + count
            color_hex = crayon["hex"].lstrip("#")
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            draw.rectangle(
                [(x_palette, y_palette), (x_palette + 12, y_palette + 12)],
                fill=(r, g, b), outline=(80, 80, 80),
            )
            draw.text((x_palette + 16, y_palette - 2), str(cnt), fill=TEXT, font=fonts["small"])
            x_palette += 16 + 8 * max(1, len(str(cnt)))
        # Papier rect
        papier = crayons_used.get("#ffffff", 0)
        if papier > 0:
            draw.rectangle(
                [(x_palette, y_palette), (x_palette + 12, y_palette + 12)],
                fill=(255, 255, 255), outline=(150, 150, 150),
            )
            draw.text((x_palette + 16, y_palette - 2), str(papier), fill=TEXT, font=fonts["small"])

        # Hollow-tube check
        ht = s.get("hollow_tube_check", {})
        ht_pass = ht.get("pass", False)
        ht_n = ht.get("n_candidates", 0)
        ht_color = GREEN if ht_pass else RED
        ht_text = f"hollow-tube : PASS" if ht_pass else f"hollow-tube : FAIL ({ht_n})"
        draw.text((PAD, y + 184), ht_text, fill=ht_color, font=fonts["stat_strong"])
        draw.text((PAD, y + 204), f"t {timing}s", fill=SUB, font=fonts["small"])

        # Col (1) blank
        b_path = s.get("outputs", {}).get("blank_png")
        if b_path:
            p_full = (PROJECT_ROOT / b_path).resolve()
            if p_full.exists():
                with Image.open(p_full) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[0], y))
        # Col (2) solution
        sol_path = s.get("outputs", {}).get("solution_png")
        if sol_path:
            p_full = (PROJECT_ROOT / sol_path).resolve()
            if p_full.exists():
                with Image.open(p_full) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[1], y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--stats", type=Path, default=DEFAULT_G5_STATS)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    g5 = json.loads(args.stats.read_text(encoding="utf-8"))
    out = build_sheet(corpus, g5, args.sheet)
    print(f"OK planche G5 galerie : {out}")
    print(f"   taille : {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
