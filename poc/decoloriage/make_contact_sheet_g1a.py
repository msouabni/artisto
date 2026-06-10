"""G1a - Planche contact 5x2 cellules : original | regions colorees.

Pour chaque image du corpus, juxtapose :
  - l'original (gauche)
  - la sortie regions colorees aleatoires + contour noir (droite)
Disposition : 5 colonnes x 2 lignes (meme grille que G0).

Usage :
    python poc/decoloriage/make_contact_sheet_g1a.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_STATS = Path(__file__).parent / "g1a_out" / "stats.json"
DEFAULT_OUT = Path(__file__).parent / "contact_sheet_g1a.png"

THUMB = 380               # cote vignette (un peu plus petit qu'en G0 car 2 vignettes par cellule)
COLS = 5
ROWS = 2
SEP = 8                   # separateur entre orig et regions
CELL_GAP = 18             # gap entre cellules
PAD = 28
LABEL_H = 86              # texte sous chaque cellule
HEADER_H = 100
BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE_TEXT = (20, 20, 25)
ACCENT = (15, 90, 170)


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


def build_sheet(corpus_path: Path, stats_path: Path, out_path: Path) -> Path:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    items = corpus["images"]
    stats_by_slot = {s["slot"]: s for s in stats["images"]}

    cell_w = THUMB * 2 + SEP
    cell_h = THUMB + LABEL_H
    sheet_w = PAD * 2 + COLS * cell_w + (COLS - 1) * CELL_GAP
    sheet_h = PAD * 2 + HEADER_H + ROWS * cell_h + (ROWS - 1) * CELL_GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    fonts = {
        "title": _font(36),
        "subtitle": _font(18),
        "small": _font(14),
        "mono": _font(18),
        "stats": _font(15),
    }

    title = "G1a - Decoloriage - Quantification couleur (Lab + k-means k=12, fusion < 0.3% aire)"
    subtitle = (
        f"Corpus gele G0   |   params : k={stats['params']['k']}, "
        f"merge_thresh={stats['params']['merge_thresh']}   |   "
        "gauche = original ERNIE pastel, droite = regions (couleurs aleatoires + contour 1px)"
    )
    draw.text((PAD, PAD), title, fill=TITLE_TEXT, font=fonts["title"])
    draw.text((PAD, PAD + 46), subtitle, fill=SUB, font=fonts["subtitle"])

    grid_y0 = PAD + HEADER_H
    for idx, item in enumerate(items):
        col = idx % COLS
        row = idx // COLS
        x = PAD + col * (cell_w + CELL_GAP)
        y = grid_y0 + row * (cell_h + CELL_GAP)
        slot = item["slot"]
        rid = item["id"]
        cat = item["category"]
        s = stats_by_slot.get(slot, {})

        draw.rectangle(
            (x - 2, y - 2, x + cell_w + 2, y + cell_h + 2),
            fill=CARD_BG,
            outline=(220, 220, 225),
            width=1,
        )

        # Original (gauche)
        orig_path = (PROJECT_ROOT / item["path"]).resolve()
        if orig_path.exists():
            with Image.open(orig_path) as im:
                sheet.paste(_fit(im, THUMB), (x, y))
        else:
            draw.rectangle((x, y, x + THUMB, y + THUMB), fill=(255, 230, 230))

        # Regions (droite)
        reg_rel = s.get("out_png")
        if reg_rel:
            reg_path = (PROJECT_ROOT / reg_rel).resolve()
            if reg_path.exists():
                with Image.open(reg_path) as im:
                    sheet.paste(_fit(im, THUMB), (x + THUMB + SEP, y))
            else:
                draw.rectangle(
                    (x + THUMB + SEP, y, x + 2 * THUMB + SEP, y + THUMB),
                    fill=(255, 230, 230),
                )

        # Label (sous la cellule, sur 2 colonnes textuelles)
        line1 = f"#{slot:02d}  -  {cat.upper()}  -  {rid}"
        regs_before = s.get("regions_before_merge", "?")
        regs_after = s.get("regions_after_merge", "?")
        merged = s.get("merged_regions", "?")
        timing = s.get("timing_s", {}).get("total", "?")
        line2 = f"regions  CC bruts : {regs_before}    apres fusion : {regs_after}    fusion : {merged}"
        line3 = f"temps total : {timing}s    k=12    seuil fusion = 0.3% de l'aire"

        ly = y + THUMB + 6
        draw.text((x + 8, ly), line1, fill=TEXT, font=fonts["mono"])
        draw.text((x + 8, ly + 26), line2, fill=ACCENT, font=fonts["stats"])
        draw.text((x + 8, ly + 48), line3, fill=SUB, font=fonts["small"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not args.corpus.exists() or not args.stats.exists():
        print("ERREUR : corpus.json ou stats.json absent", file=sys.stderr)
        return 2
    out = build_sheet(args.corpus, args.stats, args.out)
    print(f"OK contact sheet G1a : {out}")
    print(f"   taille : {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
