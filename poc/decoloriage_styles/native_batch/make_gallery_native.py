"""Galerie native_batch : 4 styles x 3 sujets natifs, page BLANK en grand,
labellee par style+sujet."""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

STYLE_ROWS = ["zellige", "mandala", "zentangle", "mosaic"]
SUBJECTS = {
    "zellige": ["star", "medallion", "panel"],
    "mandala": ["floral", "geometric", "lotus"],
    "zentangle": ["owl", "feather", "butterfly"],
    "mosaic": ["fish", "medallion", "bird"],
}

CELL = 460
PAD = 16
LABEL_H = 34
HEADER_H = 60


def _font(sz):
    for name in ("arialbd.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, sz)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def main():
    f_lbl = _font(20)
    f_hdr = _font(30)
    ncol, nrow = 3, len(STYLE_ROWS)
    grid_w = ncol * CELL + (ncol + 1) * PAD
    grid_h = HEADER_H + nrow * (CELL + LABEL_H) + (nrow + 1) * PAD
    canvas = Image.new("RGB", (grid_w, grid_h), "#f4f1ea")
    d = ImageDraw.Draw(canvas)
    d.text((PAD, 16), "POC2 exploration - sujets NATIFS (blank / page de coloriage)",
           font=f_hdr, fill="#15151b")

    for r, style in enumerate(STYLE_ROWS):
        for c, subj in enumerate(SUBJECTS[style]):
            img_id = f"{style}_{subj}"
            x = PAD + c * (CELL + PAD)
            y = HEADER_H + PAD + r * (CELL + LABEL_H + PAD)
            blank = HERE / f"{img_id}_blank.png"
            if blank.exists():
                im = Image.open(blank).convert("RGB")
                im.thumbnail((CELL, CELL), Image.LANCZOS)
                ox = x + (CELL - im.width) // 2
                oy = y + (CELL - im.height) // 2
                canvas.paste(im, (ox, oy))
                d.rectangle([x, y, x + CELL, y + CELL], outline="#ccc", width=1)
            else:
                d.rectangle([x, y, x + CELL, y + CELL], fill="#eee", outline="#ccc")
                d.text((x + 10, y + 10), "MISSING", font=f_lbl, fill="#c00")
            d.text((x, y + CELL + 6), f"{style} - {subj}", font=f_lbl, fill="#15151b")

    out = HERE / "gallery_native.png"
    canvas.save(out)
    print(f"OK {out} ({canvas.width}x{canvas.height})")


if __name__ == "__main__":
    main()
