"""S0 - Planche contact 4 lignes (styles) x 3 colonnes (sujets).

Lit poc/decoloriage_styles/corpus.json (12 entrees), charge les PNG, et compose
une planche 3 colonnes (dog/castle/peacock) x 4 lignes (manga/realiste/peinture/3d),
chaque vignette labellee (style + sujet), avec un titre en tete.

Reutilise/adapte le code PIL des contact sheets POC1
(poc/decoloriage/make_contact_sheet_g0.py).

Usage :
    python poc/decoloriage_styles/make_contact_sheet_s0.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_OUT = Path(__file__).parent / "contact_sheet_s0.png"

THUMB_SIZE = 460
GAP = 18
PAD = 28
LABEL_H = 62
HEADER_H = 90
ROW_LABEL_W = 110  # bandeau gauche avec le nom du style
BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE_TEXT = (20, 20, 25)
ROW_BAND = (235, 236, 240)

STYLES = ["manga", "realiste", "peinture", "3d"]
SUBJECTS = ["dog", "castle", "peacock"]


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _fit_thumb(img: Image.Image, side: int) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    scale = side / max(w, h)
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    img = img.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGB", (side, side), CARD_BG)
    off = ((side - new_size[0]) // 2, (side - new_size[1]) // 2)
    canvas.paste(img, off)
    return canvas


def build_contact_sheet(corpus_path: Path, out_path: Path) -> Path:
    data = json.loads(corpus_path.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in data["images"]}

    cols = len(SUBJECTS)
    rows = len(STYLES)
    cell_w = THUMB_SIZE
    cell_h = THUMB_SIZE + LABEL_H
    sheet_w = PAD * 2 + ROW_LABEL_W + cols * cell_w + (cols - 1) * GAP
    sheet_h = PAD * 2 + HEADER_H + rows * cell_h + (rows - 1) * GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    fonts = {
        "title": _font(34),
        "subtitle": _font(18),
        "small": _font(15),
        "mono": _font(19),
        "row": _font(22),
        "colhead": _font(22),
    }

    # Header
    title = "S0 - Decoloriage-styles - Corpus croise 3 sujets x 4 styles (12 PNG ERNIE)"
    subtitle = (
        f"Source : {data['source']}   |   Frozen : {data['frozen_at']}   |   "
        f"seed={42} fixe   |   sans 'flat colors' (images stylistiques riches)"
    )
    draw.text((PAD, PAD), title, fill=TITLE_TEXT, font=fonts["title"])
    draw.text((PAD, PAD + 44), subtitle, fill=SUB, font=fonts["subtitle"])

    grid_x0 = PAD + ROW_LABEL_W
    grid_y0 = PAD + HEADER_H

    # En-tetes de colonnes (sujets)
    for c, subj in enumerate(SUBJECTS):
        x = grid_x0 + c * (cell_w + GAP)
        draw.text((x + 8, grid_y0 - 28), subj.upper(), fill=TEXT, font=fonts["colhead"])

    for r, style in enumerate(STYLES):
        y = grid_y0 + r * (cell_h + GAP)
        # Bandeau gauche du style (vertical-ish : on ecrit horizontalement, place a gauche)
        draw.rectangle(
            (PAD - 2, y - 2, PAD + ROW_LABEL_W - GAP, y + cell_h + 2),
            fill=ROW_BAND, outline=(220, 220, 225), width=1,
        )
        draw.text((PAD + 8, y + cell_h // 2 - 12), style.upper(), fill=TEXT, font=fonts["row"])

        for c, subj in enumerate(SUBJECTS):
            img_id = f"{style}_{subj}"
            item = by_id.get(img_id)
            x = grid_x0 + c * (cell_w + GAP)

            draw.rectangle(
                (x - 2, y - 2, x + cell_w + 2, y + cell_h + 2),
                fill=CARD_BG, outline=(220, 220, 225), width=1,
            )

            path = item.get("path") if item else None
            img_path = (PROJECT_ROOT / "poc" / "decoloriage_styles" / path).resolve() if path else None
            if not img_path or not img_path.exists():
                ph = Image.new("RGB", (cell_w, THUMB_SIZE), (255, 230, 230))
                ImageDraw.Draw(ph).text((10, 10), f"MISSING:\n{img_id}", fill=(150, 30, 30), font=fonts["small"])
                sheet.paste(ph, (x, y))
            else:
                with Image.open(img_path) as im:
                    sheet.paste(_fit_thumb(im, THUMB_SIZE), (x, y))

            # Label sous la vignette
            draw.text((x + 8, y + THUMB_SIZE + 8), f"{style} / {subj}", fill=SUB, font=fonts["small"])
            draw.text((x + 8, y + THUMB_SIZE + 30), img_id, fill=TEXT, font=fonts["mono"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Planche contact S0 (4x3)")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not args.corpus.exists():
        print(f"ERREUR : corpus introuvable : {args.corpus}", file=sys.stderr)
        return 2
    out = build_contact_sheet(args.corpus, args.out)
    print(f"OK contact sheet : {out}")
    print(f"   taille : {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
