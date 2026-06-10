"""G0 - Planche contact des 10 originaux du corpus decoloriage gele.

Lit `poc/decoloriage/corpus.json`, charge les 10 PNG, et compose une planche
contact 5 colonnes x 2 lignes avec entete + libelle (slot, categorie, id).

Usage :
    python poc/decoloriage/make_contact_sheet_g0.py
    python poc/decoloriage/make_contact_sheet_g0.py --out poc/decoloriage/contact_sheet_g0.png

Sortie par defaut : poc/decoloriage/contact_sheet_g0.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_OUT = Path(__file__).parent / "contact_sheet_g0.png"

THUMB_SIZE = 480       # cote du carre vignette
COLS = 5
ROWS = 2
GAP = 18               # espace entre vignettes
PAD = 28               # padding general
LABEL_H = 70           # zone texte sous chaque vignette
HEADER_H = 90          # bandeau titre en haut
BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE_TEXT = (20, 20, 25)


def _font(size: int) -> ImageFont.ImageFont:
    """Charge une police TTF si possible, sinon fallback bitmap."""
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
    """Resize en preservant ratio + centre dans un carre blanc."""
    img = img.convert("RGB")
    w, h = img.size
    scale = side / max(w, h)
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    img = img.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGB", (side, side), CARD_BG)
    off = ((side - new_size[0]) // 2, (side - new_size[1]) // 2)
    canvas.paste(img, off)
    return canvas


def _draw_label(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, item: dict, fonts: dict) -> None:
    slot = item["slot"]
    category = item["category"]
    img_id = item["id"]

    line1 = f"#{slot:02d}  -  {category.upper()}"
    line2 = img_id

    draw.text((x + 8, y + 8), line1, fill=SUB, font=fonts["small"])
    draw.text((x + 8, y + 32), line2, fill=TEXT, font=fonts["mono"])


def build_contact_sheet(corpus_path: Path, out_path: Path) -> Path:
    data = json.loads(corpus_path.read_text(encoding="utf-8"))
    items = data["images"]
    if len(items) != COLS * ROWS:
        raise SystemExit(
            f"corpus.json doit contenir exactement {COLS * ROWS} images "
            f"(trouve : {len(items)})."
        )

    cell_w = THUMB_SIZE
    cell_h = THUMB_SIZE + LABEL_H
    sheet_w = PAD * 2 + COLS * cell_w + (COLS - 1) * GAP
    sheet_h = PAD * 2 + HEADER_H + ROWS * cell_h + (ROWS - 1) * GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)

    fonts = {
        "title": _font(34),
        "subtitle": _font(18),
        "small": _font(15),
        "mono": _font(20),
    }

    # Header
    title = "G0 - Decoloriage - Corpus gele (10 PNG ERNIE pastel)"
    subtitle = (
        f"Source : {data['source'][:90]}...   |   "
        f"Frozen : {data['frozen_at']}   |   "
        "Categories : 5 animaux + 2 scenes + 2 objets + 1 stress"
    )
    draw.text((PAD, PAD), title, fill=TITLE_TEXT, font=fonts["title"])
    draw.text((PAD, PAD + 44), subtitle, fill=SUB, font=fonts["subtitle"])

    # Grid
    grid_y0 = PAD + HEADER_H
    for idx, item in enumerate(items):
        col = idx % COLS
        row = idx // COLS
        x = PAD + col * (cell_w + GAP)
        y = grid_y0 + row * (cell_h + GAP)

        # Carte fond
        draw.rectangle(
            (x - 2, y - 2, x + cell_w + 2, y + cell_h + 2),
            fill=CARD_BG,
            outline=(220, 220, 225),
            width=1,
        )

        # Vignette
        img_path = (PROJECT_ROOT / item["path"]).resolve()
        if not img_path.exists():
            placeholder = Image.new("RGB", (cell_w, THUMB_SIZE), (255, 230, 230))
            ph_draw = ImageDraw.Draw(placeholder)
            ph_draw.text((10, 10), f"MISSING:\n{item['path']}", fill=(150, 30, 30), font=fonts["small"])
            sheet.paste(placeholder, (x, y))
        else:
            with Image.open(img_path) as im:
                thumb = _fit_thumb(im, THUMB_SIZE)
            sheet.paste(thumb, (x, y))

        # Label
        _draw_label(draw, x, y + THUMB_SIZE, cell_w, item, fonts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Planche contact G0 decoloriage")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="Chemin corpus.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="PNG de sortie")
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
