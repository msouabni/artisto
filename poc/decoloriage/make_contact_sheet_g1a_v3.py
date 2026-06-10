"""G1a v3 - Planche contact + recap 3 colonnes + 2 crops zoomes.

Sorties :
  - contact_sheet_g1a_v3.png : 5x2 (original | regions v3) + label 3 stats
  - zoom_crop_eye_v3.png : cat ou dog, zoom sur l'oeil/truffe
  - zoom_crop_gradient_v3.png : peacock ou lion, zoom sur degrade/plume
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_STATS = Path(__file__).parent / "g1a_out_v3" / "stats.json"
DEFAULT_OUT = Path(__file__).parent / "contact_sheet_g1a_v3.png"
DEFAULT_CROP_EYE = Path(__file__).parent / "zoom_crop_eye_v3.png"
DEFAULT_CROP_GRADIENT = Path(__file__).parent / "zoom_crop_gradient_v3.png"

THUMB = 380
COLS = 5
ROWS = 2
SEP = 8
CELL_GAP = 18
PAD = 28
LABEL_H = 108
HEADER_H = 110
BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE_TEXT = (20, 20, 25)
COL_BRUT = (130, 130, 140)
COL_PROT = (15, 90, 170)
COL_FINAL = (200, 60, 30)


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


def build_sheet(corpus: dict, stats: dict, out_path: Path) -> Path:
    items = corpus["images"]
    stats_by = {s["slot"]: s for s in stats["images"]}

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
        "stats": _font(16),
    }

    p = stats["params"]
    title = "G1a v3 - Decoloriage - pyrMeanShift + compacite 3x3 + protection ΔE"
    subtitle = (
        f"params : k={p['k']}, pyrMeanShift sp={p['meanshift_sp']}, sr={p['meanshift_sr']}, "
        f"merge<{p['merge_thresh']*100:.2f}%, protect ΔE76>={p['protect_contrast']:.0f}, "
        "sliver = region non-compacte (echec erosion 3x3) -> fusion forcee"
    )
    draw.text((PAD, PAD), title, fill=TITLE_TEXT, font=fonts["title"])
    draw.text((PAD, PAD + 44), subtitle, fill=SUB, font=fonts["subtitle"])
    legend = (
        "recap par cellule  ->  brut (CC bruts) | protegees legitimes (compactes + ΔE>=30) | final"
    )
    draw.text((PAD, PAD + 72), legend, fill=SUB, font=fonts["small"])

    grid_y0 = PAD + HEADER_H
    for idx, item in enumerate(items):
        col = idx % COLS
        row = idx // COLS
        x = PAD + col * (cell_w + CELL_GAP)
        y = grid_y0 + row * (cell_h + CELL_GAP)
        slot = item["slot"]
        rid = item["id"]
        cat = item["category"]
        s = stats_by.get(slot, {})

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

        reg_rel = s.get("out_png")
        if reg_rel:
            reg_path = (PROJECT_ROOT / reg_rel).resolve()
            if reg_path.exists():
                with Image.open(reg_path) as im:
                    sheet.paste(_fit(im, THUMB), (x + THUMB + SEP, y))

        line1 = f"#{slot:02d}  -  {cat.upper()}  -  {rid}"
        ly = y + THUMB + 6
        draw.text((x + 8, ly), line1, fill=TEXT, font=fonts["mono"])

        brut = s.get("regions_before_merge", "?")
        prot = s.get("protected_legitimate", "?")
        final = s.get("regions_final", "?")
        # Ligne 2 : 3 colonnes colorees
        ly2 = ly + 28
        x_text = x + 8
        seg_brut = f"brut  {brut}"
        seg_prot = f"   |   protegees  {prot}"
        seg_final = f"   |   final  {final}"
        draw.text((x_text, ly2), seg_brut, fill=COL_BRUT, font=fonts["stats"])
        w_brut = draw.textlength(seg_brut, font=fonts["stats"])
        draw.text((x_text + w_brut, ly2), seg_prot, fill=COL_PROT, font=fonts["stats"])
        w_prot = draw.textlength(seg_prot, font=fonts["stats"])
        draw.text((x_text + w_brut + w_prot, ly2), seg_final, fill=COL_FINAL, font=fonts["stats"])

        sliver = s.get("sliver_forced_merges", "?")
        non_sliver = s.get("non_sliver_merges", "?")
        total_t = s.get("timing_s", {}).get("total", "?")
        line3 = f"slivers forces : {sliver}  |  autres fusions : {non_sliver}  |  t v3 : {total_t}s"
        draw.text((x + 8, ly2 + 28), line3, fill=SUB, font=fonts["small"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def make_zoom_crop(
    orig_path: Path,
    regions_path: Path,
    bbox: tuple[int, int, int, int],
    out_path: Path,
    label_left: str,
    label_right: str,
    title: str,
) -> Path:
    """bbox = (left, top, width, height) en coordonnees du fichier source 1024x1024."""
    left, top, w, h = bbox
    box = (left, top, left + w, top + h)
    target_h = 640
    scale = target_h / h

    o = Image.open(orig_path).convert("RGB").crop(box).resize(
        (int(w * scale), target_h), Image.LANCZOS
    )
    r = Image.open(regions_path).convert("RGB").crop(box).resize(
        (int(w * scale), target_h), Image.LANCZOS
    )

    gap = 12
    pad = 16
    title_h = 40
    label_h = 30
    canvas_w = o.width * 2 + gap + 2 * pad
    canvas_h = target_h + title_h + label_h + 2 * pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(canvas)
    fonts = {
        "title": _font(22),
        "label": _font(16),
    }
    draw.text((pad, pad), title, fill=TITLE_TEXT, font=fonts["title"])
    img_y = pad + title_h
    canvas.paste(o, (pad, img_y))
    canvas.paste(r, (pad + o.width + gap, img_y))
    draw.text((pad, img_y + target_h + 4), label_left, fill=SUB, font=fonts["label"])
    draw.text((pad + o.width + gap, img_y + target_h + 4), label_right, fill=SUB, font=fonts["label"])
    canvas.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--crop-eye", type=Path, default=DEFAULT_CROP_EYE)
    parser.add_argument("--crop-gradient", type=Path, default=DEFAULT_CROP_GRADIENT)
    args = parser.parse_args()

    if not args.corpus.exists() or not args.stats.exists():
        print("ERREUR : corpus ou stats absent", file=sys.stderr)
        return 2

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    stats = json.loads(args.stats.read_text(encoding="utf-8"))

    out_sheet = build_sheet(corpus, stats, args.out)
    print(f"OK planche v3 : {out_sheet}")

    # ---- Crops zoomes ----
    items_by_id = {it["id"]: it for it in corpus["images"]}
    stats_by_id = {s["id"]: s for s in stats["images"]}

    # Crop oeil : pastel_cat (yeux visibles sur la tete) + zone face
    cat_item = items_by_id["pastel_cat"]
    cat_stat = stats_by_id["pastel_cat"]
    cat_orig = (PROJECT_ROOT / cat_item["path"]).resolve()
    cat_reg = (PROJECT_ROOT / cat_stat["out_png"]).resolve()
    # Tete du chat : approximativement (left=270, top=120, w=520, h=420) sur 1024
    make_zoom_crop(
        cat_orig, cat_reg, bbox=(270, 120, 520, 420),
        out_path=args.crop_eye,
        label_left="pastel_cat - original ERNIE",
        label_right=f"v3 (final={cat_stat['regions_final']}, protected={cat_stat['protected_legitimate']})",
        title="G1a v3 - Zoom oeil/face (pastel_cat) - validation preservation yeux/truffe/moustaches",
    )
    print(f"OK zoom oeil : {args.crop_eye}")

    # Crop degrade : pastel_peacock (plumes en eventail)
    peacock_item = items_by_id["pastel_peacock"]
    peacock_stat = stats_by_id["pastel_peacock"]
    peacock_orig = (PROJECT_ROOT / peacock_item["path"]).resolve()
    peacock_reg = (PROJECT_ROOT / peacock_stat["out_png"]).resolve()
    # Partie haute du paon avec plumes et ocelles : (left=80, top=80, w=860, h=480)
    make_zoom_crop(
        peacock_orig, peacock_reg, bbox=(80, 80, 860, 480),
        out_path=args.crop_gradient,
        label_left="pastel_peacock - original ERNIE (stress test)",
        label_right=f"v3 (final={peacock_stat['regions_final']}, protected={peacock_stat['protected_legitimate']})",
        title="G1a v3 - Zoom degrade/plumes (pastel_peacock) - validation ocelles preservees",
    )
    print(f"OK zoom degrade : {args.crop_gradient}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
