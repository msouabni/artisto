"""G4 - Planche verdict 10x3 :
   (a) line art ERNIE direct (= masque traits G2)
   (b) pipeline actuel binarisation+potrace (simulation)
   (c) decoloriage 2 poids (G4)

+ tableau : nombre de zones fermees (a) vs (c) par image
+ hypothese pre-enregistree regions(c) >= 2 x regions(a) sur les 5 animaux.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_G4_STATS = Path(__file__).parent / "g4_out" / "stats.json"
DEFAULT_SHEET = Path(__file__).parent / "contact_sheet_g4.png"

THUMB = 360
GAP = 12
PAD = 28
LABEL_W = 240
HEADER_H = 130
COLS = 3  # (a) | (b) | (c)

BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE = (20, 20, 25)
COL_A = (100, 100, 120)
COL_B = (180, 130, 60)
COL_C = (40, 110, 60)


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


def build_sheet(corpus: dict, g4: dict, out_path: Path) -> Path:
    items = corpus["images"]
    by_id = {s["id"]: s for s in g4["images"]}

    row_h = THUMB + 32
    sheet_w = PAD * 2 + LABEL_W + COLS * THUMB + (COLS - 1) * GAP
    sheet_h = PAD * 2 + HEADER_H + len(items) * row_h + (len(items) - 1) * GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    fonts = {
        "title": _font(34),
        "subtitle": _font(17),
        "small": _font(13),
        "mono": _font(17),
        "stat": _font(15),
        "head": _font(20),
    }

    p = g4["params"]
    hyp = g4.get("hypothesis_check", {})
    n_pass = hyp.get("n_animals_pass", 0)
    n_animals = hyp.get("n_animals_evaluated", 5)
    pass_color = COL_C if n_pass == n_animals else (200, 60, 30)
    title = "G4 - Decoloriage - Verdict 2 poids vs line art ERNIE vs binarisation+potrace"
    subtitle = (
        f"Params : seuil ink={int(p['ink_overlap_threshold']*100)}%, dilate trait {p['line_mask_dilate_px']}px,"
        f" DP tol {p['dp_tolerance']}px, Chaikin arcs {p['chaikin_iters_arc']}/regions {p['chaikin_iters_region']} iter   |   "
        "Stroke widths : encre = epaisseur mediane trait ERNIE / shading = ~1/3"
    )
    draw.text((PAD, PAD), title, fill=TITLE, font=fonts["title"])
    draw.text((PAD, PAD + 44), subtitle, fill=SUB, font=fonts["subtitle"])
    draw.text(
        (PAD, PAD + 72),
        f"Hypothese pre-enregistree regions(c) >= 2 x regions(a) sur 5 animaux : "
        f"{n_pass}/{n_animals} satisfont.",
        fill=pass_color, font=fonts["head"],
    )

    col_xs = [PAD + LABEL_W]
    for _ in range(COLS - 1):
        col_xs.append(col_xs[-1] + THUMB + GAP)
    col_titles = [
        ("(a) line art ERNIE direct", COL_A),
        ("(b) binarisation+potrace (baseline)", COL_B),
        ("(c) decoloriage 2 poids (G4)", COL_C),
    ]
    for c, (txt, col) in enumerate(col_titles):
        draw.text(
            (col_xs[c] + 4, PAD + HEADER_H - 28),
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
        s = by_id.get(rid, {})

        draw.text((PAD, y + 8), f"#{slot:02d}", fill=SUB, font=fonts["mono"])
        draw.text((PAD, y + 28), cat.upper(), fill=SUB, font=fonts["small"])
        draw.text((PAD, y + 46), rid, fill=TEXT, font=fonts["mono"])

        regs = s.get("regions", {})
        a = regs.get("a_line_art_zones", "?")
        c_val = regs.get("c_decoloriage_regions", "?")
        ratio = regs.get("ratio_c_over_a", "?")
        is_animal = cat == "animal"
        ratio_pass = (
            isinstance(ratio, (int, float)) and ratio >= 2.0
        ) if is_animal else None

        line_a = f"a = {a}  |  c = {c_val}"
        draw.text((PAD, y + 80), line_a, fill=TEXT, font=fonts["stat"])
        ratio_color = (
            COL_C if ratio_pass else (200, 60, 30) if is_animal else SUB
        )
        line_b = f"ratio c/a = {ratio}{'   PASS >= 2x' if ratio_pass else ('   FAIL < 2x' if is_animal and not ratio_pass else '')}"
        draw.text((PAD, y + 102), line_b, fill=ratio_color, font=fonts["stat"])

        arcs = s.get("arcs", {})
        line_c = (
            f"arcs : encre {arcs.get('n_ink', '?')} + shading {arcs.get('n_shading', '?')}"
        )
        draw.text((PAD, y + 124), line_c, fill=SUB, font=fonts["small"])
        thick = s.get("line_thickness", {})
        line_d = f"stroke : encre {thick.get('ink_stroke_width', '?')}px / sha {thick.get('shading_stroke_width', '?')}px"
        draw.text((PAD, y + 142), line_d, fill=SUB, font=fonts["small"])

        # Col (a) line art
        a_path = s.get("outputs", {}).get("a_line_art")
        if a_path:
            p_full = (PROJECT_ROOT / a_path).resolve()
            if p_full.exists():
                with Image.open(p_full) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[0], y))
        # Col (b) binarize+potrace
        b_path = s.get("outputs", {}).get("b_binarize_potrace")
        if b_path:
            p_full = (PROJECT_ROOT / b_path).resolve()
            if p_full.exists():
                with Image.open(p_full) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[1], y))
        # Col (c) g4 render
        c_path = s.get("outputs", {}).get("g4_render")
        if c_path:
            p_full = (PROJECT_ROOT / c_path).resolve()
            if p_full.exists():
                with Image.open(p_full) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[2], y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--stats", type=Path, default=DEFAULT_G4_STATS)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    g4 = json.loads(args.stats.read_text(encoding="utf-8"))
    out = build_sheet(corpus, g4, args.sheet)
    print(f"OK planche G4 verdict : {out}")
    print(f"   taille : {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
