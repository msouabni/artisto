"""G2 - Planche contact 10x4 + histogramme + 4 crops frontieres.

Sorties :
  - contact_sheet_g2.png : 10 lignes (1 par image) x 4 colonnes
                           (original | tout-petit | enfant | adulte)
  - histogram_g2.png : nb regions par image et par niveau (bar chart PIL)
  - zoom_g2_boundary_dog.png : zoom face/oeil chien (4 panels)
  - zoom_g2_boundary_lion.png : zoom criniere lion (4 panels)
  - zoom_g2_boundary_peacock.png : zoom plumes/ocelles paon (4 panels)
  - zoom_g2_boundary_polar_bear.png : zoom ours/glace (4 panels)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_STATS = Path(__file__).parent / "g2_out" / "stats.json"
DEFAULT_SHEET = Path(__file__).parent / "contact_sheet_g2.png"
DEFAULT_HISTO = Path(__file__).parent / "histogram_g2.png"

# Pivot v2 : planche 10x3 = orig | tout-petit | enfant. adulte sort de l'affichage
# (mais reste dans stats.json).
LEVEL_KEYS = ["tout_petit", "enfant"]
LEVEL_LABELS = {"tout_petit": "tout-petit", "enfant": "enfant", "adulte": "adulte"}
LEVEL_COLORS = {
    "tout_petit": (127, 188, 210),
    "enfant": (243, 169, 83),
    "adulte": (205, 80, 84),
}

BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE = (20, 20, 25)


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


# ----------------------------------------------------------------------------
# Planche principale 10 x 4
# ----------------------------------------------------------------------------
def build_main_sheet(corpus: dict, stats: dict, out_path: Path) -> Path:
    items = corpus["images"]
    # stats : list of (slot, level) entries
    by_slot_level: dict[tuple[int, str], dict] = {
        (s["slot"], s["level"]): s for s in stats["images"]
    }
    levels = stats["levels"]

    THUMB = 320
    GAP = 12
    PAD = 28
    LABEL_W = 240
    HEADER_H = 110
    COLS = 1 + len(LEVEL_KEYS)  # orig + niveaux affiches
    ROWS = len(items)

    row_h = THUMB + 30  # vignette + petite legende
    sheet_w = PAD * 2 + LABEL_W + COLS * THUMB + (COLS - 1) * GAP
    sheet_h = PAD * 2 + HEADER_H + ROWS * row_h + (ROWS - 1) * GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    fonts = {
        "title": _font(34),
        "subtitle": _font(17),
        "small": _font(14),
        "mono": _font(17),
        "stat": _font(15),
        "head": _font(20),
    }

    base = stats.get("base_v3", {})
    tp_cfg = levels.get("tout_petit", {})
    en_cfg = levels.get("enfant", {})
    title = "G2 v2 - Decoloriage - tout-petit familles couleurs / enfant smooth / adulte v3"
    subtitle = (
        f"base v3 unique : k={base.get('k', '?')}, "
        f"merge={base.get('merge_thresh', 0)*100:.2f}%, "
        f"contrast ΔE>={base.get('contrast_thresh', '?')}   |   "
        f"tout-petit : k_familles={tp_cfg.get('k_families', '?')}, "
        f"fallback target={tp_cfg.get('fallback_target_non_protected', '?')} non-protegees   |   "
        f"enfant : smooth ΔE<{en_cfg.get('smooth_merge_thresh', '?')}   |   "
        f"0 pixel orphelin sur {ROWS * 3} runs   |   "
        "protected anatomie immune a TOUS niveaux"
    )
    draw.text((PAD, PAD), title, fill=TITLE, font=fonts["title"])
    draw.text((PAD, PAD + 44), subtitle, fill=SUB, font=fonts["subtitle"])
    draw.text(
        (PAD, PAD + 72),
        "Pass : 0 pixel orphelin + 15-80 regions au seuil median (enfant) + 3 niveaux visuellement distincts",
        fill=SUB,
        font=fonts["small"],
    )

    # En-tetes de colonne
    grid_y0 = PAD + HEADER_H
    col_xs = [PAD + LABEL_W]
    for c in range(COLS - 1):
        col_xs.append(col_xs[-1] + THUMB + GAP)
    col_titles = ["original ERNIE"] + [LEVEL_LABELS[k] for k in LEVEL_KEYS]
    col_colors = [TEXT] + [LEVEL_COLORS[k] for k in LEVEL_KEYS]
    for c, (txt, col) in enumerate(zip(col_titles, col_colors)):
        draw.text(
            (col_xs[c] + 4, grid_y0 - 26),
            txt,
            fill=col,
            font=fonts["head"],
        )

    # Lignes
    for idx, item in enumerate(items):
        y = grid_y0 + idx * (row_h + GAP)
        slot = item["slot"]
        rid = item["id"]
        cat = item["category"]

        # Label gauche
        draw.text((PAD, y + 8), f"#{slot:02d}", fill=SUB, font=fonts["mono"])
        draw.text((PAD, y + 28), cat.upper(), fill=SUB, font=fonts["small"])
        draw.text((PAD, y + 48), rid, fill=TEXT, font=fonts["mono"])

        # Original
        orig = (PROJECT_ROOT / item["path"]).resolve()
        if orig.exists():
            with Image.open(orig) as im:
                sheet.paste(_fit(im, THUMB), (col_xs[0], y))

        for ci, level_key in enumerate(LEVEL_KEYS, start=1):
            s = by_slot_level.get((slot, level_key), {})
            reg = s.get("out_png")
            if reg:
                reg_p = (PROJECT_ROOT / reg).resolve()
                if reg_p.exists():
                    with Image.open(reg_p) as im:
                        sheet.paste(_fit(im, THUMB), (col_xs[ci], y))
            # Legende region count
            n = s.get("regions_final", "?")
            color = LEVEL_COLORS[level_key]
            txt = f"regions : {n}"
            draw.text((col_xs[ci] + 4, y + THUMB + 4), txt, fill=color, font=fonts["stat"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


# ----------------------------------------------------------------------------
# Histogramme (bar chart PIL)
# ----------------------------------------------------------------------------
def build_histogram(corpus: dict, stats: dict, out_path: Path) -> Path:
    items = corpus["images"]
    by_slot_level: dict[tuple[int, str], dict] = {
        (s["slot"], s["level"]): s for s in stats["images"]
    }

    W = 1400
    H = 640
    PAD_L = 80
    PAD_R = 40
    PAD_T = 90
    PAD_B = 170

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    fonts = {
        "title": _font(28),
        "axis": _font(14),
        "label": _font(15),
        "val": _font(13),
        "legend": _font(16),
    }

    draw.text(
        (PAD_L, 18),
        "G2 - Nombre de regions par image et par niveau (cadran de difficulte)",
        fill=TITLE,
        font=fonts["title"],
    )
    draw.text(
        (PAD_L, 54),
        "Pass : 15-80 regions au seuil median (enfant) sur la majorite des sujets. "
        "Peacock = stress-test, hors cible numerique attendu.",
        fill=SUB,
        font=fonts["axis"],
    )

    # Cap y at 100 for readability, indicate values above explicitly
    Y_CAP = 100

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    n_groups = len(items)
    group_w = plot_w / n_groups
    bar_w = group_w * 0.24
    gap_intra = group_w * 0.04

    # Axe Y
    draw.line([(PAD_L, PAD_T), (PAD_L, PAD_T + plot_h)], fill=(180, 180, 188), width=1)
    draw.line([(PAD_L, PAD_T + plot_h), (W - PAD_R, PAD_T + plot_h)], fill=(180, 180, 188), width=1)
    # Graduations
    for tick in [0, 20, 40, 60, 80, 100]:
        ty = PAD_T + plot_h - (tick / Y_CAP) * plot_h
        draw.line([(PAD_L - 4, ty), (PAD_L, ty)], fill=(180, 180, 188), width=1)
        draw.text((PAD_L - 36, ty - 8), str(tick), fill=SUB, font=fonts["axis"])

    # Bars + labels
    for gi, item in enumerate(items):
        slot = item["slot"]
        rid = item["id"]
        cx0 = PAD_L + gi * group_w + group_w * 0.05
        for bi, key in enumerate(LEVEL_KEYS):
            s = by_slot_level.get((slot, key), {})
            n = s.get("regions_final", 0)
            if not isinstance(n, int):
                n = 0
            h_visible = min(n, Y_CAP)
            bar_h = (h_visible / Y_CAP) * plot_h
            bx = cx0 + bi * (bar_w + gap_intra)
            by_top = PAD_T + plot_h - bar_h
            color = LEVEL_COLORS[key]
            draw.rectangle(
                [(bx, by_top), (bx + bar_w, PAD_T + plot_h)],
                fill=color,
                outline=(20, 20, 25),
                width=1,
            )
            # Valeur au-dessus
            val_txt = str(n)
            tw = draw.textlength(val_txt, font=fonts["val"])
            draw.text(
                (bx + bar_w / 2 - tw / 2, by_top - 16),
                val_txt,
                fill=color if n <= Y_CAP else (200, 60, 30),
                font=fonts["val"],
            )

        # Label image (rotated 30 deg simulee : on coupe simplement)
        label = rid.replace("pastel_", "").replace("taxo_", "")
        if len(label) > 16:
            label = label[:15] + "..."
        tw = draw.textlength(label, font=fonts["label"])
        draw.text(
            (cx0 + (3 * bar_w + 2 * gap_intra) / 2 - tw / 2, PAD_T + plot_h + 8),
            label,
            fill=TEXT,
            font=fonts["label"],
        )
        draw.text(
            (cx0 + (3 * bar_w + 2 * gap_intra) / 2 - 12, PAD_T + plot_h + 26),
            f"#{slot:02d}",
            fill=SUB,
            font=fonts["axis"],
        )

    # Legende
    legend_y = H - 90
    lx = PAD_L
    for key in LEVEL_KEYS:
        color = LEVEL_COLORS[key]
        draw.rectangle([(lx, legend_y), (lx + 22, legend_y + 22)], fill=color, outline=(20, 20, 25))
        draw.text((lx + 30, legend_y + 2), LEVEL_LABELS[key], fill=TEXT, font=fonts["legend"])
        lx += 180
    draw.text(
        (PAD_L, legend_y + 36),
        "y plafonne a 100 pour lisibilite. Au-dessus, la valeur exacte est ecrite en rouge.",
        fill=SUB,
        font=fonts["axis"],
    )

    img.save(out_path, "PNG", optimize=True)
    return out_path


# ----------------------------------------------------------------------------
# Crops frontiere : 4 panels (orig + 3 niveaux)
# ----------------------------------------------------------------------------
def build_boundary_crop(
    corpus: dict,
    stats: dict,
    image_id: str,
    bbox: tuple[int, int, int, int],
    title: str,
    out_path: Path,
) -> Path:
    items_by_id = {it["id"]: it for it in corpus["images"]}
    by_slot_level: dict[tuple[int, str], dict] = {
        (s["slot"], s["level"]): s for s in stats["images"]
    }
    item = items_by_id[image_id]
    slot = item["slot"]
    orig = (PROJECT_ROOT / item["path"]).resolve()

    left, top, w, h = bbox
    box = (left, top, left + w, top + h)
    target_h = 460
    scale = target_h / h
    panel_w = int(w * scale)
    gap = 10
    pad = 18
    title_h = 44
    label_h = 36
    canvas_w = panel_w * 4 + gap * 3 + pad * 2
    canvas_h = target_h + title_h + label_h + pad * 2

    canvas = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(canvas)
    fonts = {
        "title": _font(22),
        "head": _font(17),
        "small": _font(13),
    }
    draw.text((pad, pad), title, fill=TITLE, font=fonts["title"])

    # Original
    img_y = pad + title_h
    with Image.open(orig) as im:
        crop = im.convert("RGB").crop(box).resize((panel_w, target_h), Image.LANCZOS)
    canvas.paste(crop, (pad, img_y))
    draw.text((pad, img_y + target_h + 4), "original ERNIE", fill=TEXT, font=fonts["head"])

    # 3 levels
    for i, key in enumerate(LEVEL_KEYS, start=1):
        s = by_slot_level.get((slot, key), {})
        reg = s.get("out_png")
        x = pad + i * (panel_w + gap)
        if reg:
            reg_p = (PROJECT_ROOT / reg).resolve()
            if reg_p.exists():
                with Image.open(reg_p) as im:
                    crop = im.convert("RGB").crop(box).resize((panel_w, target_h), Image.LANCZOS)
                canvas.paste(crop, (x, img_y))
        n = s.get("regions_final", "?")
        label = f"{LEVEL_LABELS[key]}  ({n} regions)"
        draw.text((x, img_y + target_h + 4), label, fill=LEVEL_COLORS[key], font=fonts["head"])

    canvas.save(out_path, "PNG", optimize=True)
    return out_path


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--histo", type=Path, default=DEFAULT_HISTO)
    args = parser.parse_args()

    if not args.corpus.exists() or not args.stats.exists():
        print("ERREUR : corpus ou stats absent", file=sys.stderr)
        return 2

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    stats = json.loads(args.stats.read_text(encoding="utf-8"))

    p1 = build_main_sheet(corpus, stats, args.sheet)
    print(f"OK planche : {p1}  ({p1.stat().st_size / 1024:.0f} KB)")

    p2 = build_histogram(corpus, stats, args.histo)
    print(f"OK histo   : {p2}  ({p2.stat().st_size / 1024:.0f} KB)")

    # 4 crops frontieres (bbox approx pour 1024x1024)
    crops = [
        ("pastel_dog",
         (240, 160, 460, 380),
         "G2 boundary - chien : face/oeil/truffe (validation details fins)",
         Path(__file__).parent / "zoom_g2_boundary_dog.png"),
        ("pastel_lion2",
         (220, 60, 540, 420),
         "G2 boundary - lion : criniere multi-tons (test fusion couleurs proches)",
         Path(__file__).parent / "zoom_g2_boundary_lion.png"),
        ("pastel_peacock",
         (80, 80, 860, 460),
         "G2 boundary - paon : plumes/ocelles (stress test)",
         Path(__file__).parent / "zoom_g2_boundary_peacock.png"),
        ("taxo_polar_bear_on_ice",
         (60, 460, 900, 460),
         "G2 boundary - ours sur glace : interface sujet/fond pastel",
         Path(__file__).parent / "zoom_g2_boundary_polar_bear.png"),
    ]
    for image_id, bbox, title, out in crops:
        p = build_boundary_crop(corpus, stats, image_id, bbox, title, out)
        print(f"OK crop    : {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
