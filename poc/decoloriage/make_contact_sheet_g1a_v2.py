"""G1a v2 - Planche contact 5x2 : original | regions v2 protegees.

Label de chaque cellule :
  - ligne 1 : #slot - CATEGORIE - id
  - ligne 2 : avant pivot (v1, 0.3% sans prot.)  vs  apres pivot (v2, 0.05% + ΔE>=30)
  - ligne 3 : protected v2, fusion v2, temps v2

Usage : python poc/decoloriage/make_contact_sheet_g1a_v2.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_STATS_V1 = Path(__file__).parent / "g1a_out" / "stats.json"
DEFAULT_STATS_V2 = Path(__file__).parent / "g1a_out_v2" / "stats.json"
DEFAULT_OUT = Path(__file__).parent / "contact_sheet_g1a_v2.png"

THUMB = 380
COLS = 5
ROWS = 2
SEP = 8
CELL_GAP = 18
PAD = 28
LABEL_H = 102
HEADER_H = 110
BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE_TEXT = (20, 20, 25)
ACCENT_OLD = (110, 110, 120)
ACCENT_NEW = (200, 60, 30)
ACCENT_PROT = (15, 90, 170)


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


def build_sheet(corpus_path: Path, stats_v1: Path, stats_v2: Path, out_path: Path) -> Path:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    v1 = json.loads(stats_v1.read_text(encoding="utf-8"))
    v2 = json.loads(stats_v2.read_text(encoding="utf-8"))
    items = corpus["images"]
    v1_by = {s["slot"]: s for s in v1["images"]}
    v2_by = {s["slot"]: s for s in v2["images"]}

    cell_w = THUMB * 2 + SEP
    cell_h = THUMB + LABEL_H
    sheet_w = PAD * 2 + COLS * cell_w + (COLS - 1) * CELL_GAP
    sheet_h = PAD * 2 + HEADER_H + ROWS * cell_h + (ROWS - 1) * CELL_GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    fonts = {
        "title": _font(34),
        "subtitle": _font(17),
        "small": _font(14),
        "mono": _font(18),
        "stats": _font(15),
    }

    params_v1 = v1["params"]
    params_v2 = v2["params"]
    title = "G1a v2 (pivot) - Decoloriage - Quantification couleur + protection contraste"
    subtitle = (
        f"v1 : k={params_v1['k']}, merge<{params_v1['merge_thresh']*100:.2f}%, sans protection   |   "
        f"v2 : k={params_v2['k']}, merge<{params_v2['merge_thresh']*100:.2f}%, "
        f"protect deltaE76>={params_v2['protect_contrast']:.0f}   |   "
        "droite = regions v2 (couleurs aleatoires + contour 1 px)"
    )
    draw.text((PAD, PAD), title, fill=TITLE_TEXT, font=fonts["title"])
    draw.text((PAD, PAD + 44), subtitle, fill=SUB, font=fonts["subtitle"])
    legend = (
        "regions  avant v1 (gris) > apres v2 (rouge) | "
        "protected v2 (bleu) = regions epargnees par la regle de contraste"
    )
    draw.text((PAD, PAD + 70), legend, fill=SUB, font=fonts["small"])

    grid_y0 = PAD + HEADER_H
    for idx, item in enumerate(items):
        col = idx % COLS
        row = idx // COLS
        x = PAD + col * (cell_w + CELL_GAP)
        y = grid_y0 + row * (cell_h + CELL_GAP)
        slot = item["slot"]
        rid = item["id"]
        cat = item["category"]
        s1 = v1_by.get(slot, {})
        s2 = v2_by.get(slot, {})

        draw.rectangle(
            (x - 2, y - 2, x + cell_w + 2, y + cell_h + 2),
            fill=CARD_BG,
            outline=(220, 220, 225),
            width=1,
        )

        orig_path = (PROJECT_ROOT / item["path"]).resolve()
        if orig_path.exists():
            with Image.open(orig_path) as im:
                sheet.paste(_fit(im, THUMB), (x, y))

        reg_rel = s2.get("out_png")
        if reg_rel:
            reg_path = (PROJECT_ROOT / reg_rel).resolve()
            if reg_path.exists():
                with Image.open(reg_path) as im:
                    sheet.paste(_fit(im, THUMB), (x + THUMB + SEP, y))

        v1_count = s1.get("regions_after_merge", "?")
        v2_count = s2.get("regions_after_merge", "?")
        v2_prot = s2.get("protected_regions", "?")
        v2_merg = s2.get("merged_regions", "?")
        v2_total_t = s2.get("timing_s", {}).get("total", "?")

        line1 = f"#{slot:02d}  -  {cat.upper()}  -  {rid}"
        ly = y + THUMB + 6
        draw.text((x + 8, ly), line1, fill=TEXT, font=fonts["mono"])

        # Avant / apres en deux segments colores
        prefix = "regions  "
        draw.text((x + 8, ly + 28), prefix, fill=TEXT, font=fonts["stats"])
        prefix_w = draw.textlength(prefix, font=fonts["stats"])
        av_txt = f"avant v1 : {v1_count}"
        draw.text((x + 8 + prefix_w, ly + 28), av_txt, fill=ACCENT_OLD, font=fonts["stats"])
        av_w = draw.textlength(av_txt + "   ->   ", font=fonts["stats"])
        draw.text((x + 8 + prefix_w + draw.textlength(av_txt, font=fonts["stats"]),
                   ly + 28), "   ->   ", fill=TEXT, font=fonts["stats"])
        after_x = x + 8 + prefix_w + draw.textlength(av_txt + "   ->   ", font=fonts["stats"])
        ap_txt = f"apres v2 : {v2_count}"
        draw.text((after_x, ly + 28), ap_txt, fill=ACCENT_NEW, font=fonts["stats"])

        line3 = (
            f"v2 : protected {v2_prot}  |  fusion {v2_merg}  |  total {v2_total_t}s"
        )
        draw.text((x + 8, ly + 56), line3, fill=ACCENT_PROT, font=fonts["small"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--stats-v1", type=Path, default=DEFAULT_STATS_V1)
    parser.add_argument("--stats-v2", type=Path, default=DEFAULT_STATS_V2)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    for p, name in [(args.corpus, "corpus"), (args.stats_v1, "stats v1"), (args.stats_v2, "stats v2")]:
        if not p.exists():
            print(f"ERREUR : {name} absent : {p}", file=sys.stderr)
            return 2
    out = build_sheet(args.corpus, args.stats_v1, args.stats_v2, args.out)
    print(f"OK contact sheet G1a v2 : {out}")
    print(f"   taille : {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
