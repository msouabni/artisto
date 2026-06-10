"""G3 - Planche contact 10x3 + 4 zooms jonctions triples + HTML test SVG.

Sorties :
  - contact_sheet_g3.png : 10 lignes x 3 (orig | SVG rendu | diff)
  - zoom_g3_junction_<sujet>.png : 4 zooms 200x200 sur jonctions triples
  - g3_browser_test.html : page HTML qui charge les SVG inline pour
    verification "ouvrable dans le navigateur"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_G3_STATS = Path(__file__).parent / "g3_out" / "stats.json"
DEFAULT_SHEET = Path(__file__).parent / "contact_sheet_g3.png"
DEFAULT_HTML = Path(__file__).parent / "g3_browser_test.html"

THUMB = 360
GAP = 12
PAD = 28
LABEL_W = 220
HEADER_H = 110
COLS = 3  # orig | svg | diff

BG = (245, 245, 247)
CARD_BG = (255, 255, 255)
TEXT = (30, 30, 35)
SUB = (110, 110, 120)
TITLE = (20, 20, 25)
COL_OK = (40, 130, 60)
COL_BAD = (200, 60, 30)


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


def build_main_sheet(corpus: dict, g3_stats: dict, out_path: Path) -> Path:
    items = corpus["images"]
    by_id = {s["id"]: s for s in g3_stats["images"]}

    row_h = THUMB + 28
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

    p = g3_stats["params"]
    title = "G3 - Decoloriage - Vectorisation niveau ENFANT (DP + Chaikin + stroke anti-sliver)"
    subtitle = (
        f"params : DP tol={p['dp_tolerance']} px, "
        f"Chaikin {p['chaikin_iters']} iter, stroke noir {p['stroke_width']} px   |   "
        f"snap-to-edges sur polygones touchant les bords (preserve coins images)   |   "
        f"cible pass : < 0,5 % non couvert"
    )
    draw.text((PAD, PAD), title, fill=TITLE, font=fonts["title"])
    draw.text((PAD, PAD + 44), subtitle, fill=SUB, font=fonts["subtitle"])
    draw.text(
        (PAD, PAD + 72),
        "colonnes : original ERNIE  |  rendu SVG rasterise (fill + stroke)  |  diff "
        "(rouge la ou aucun polygone ne couvre)",
        fill=SUB, font=fonts["small"],
    )

    col_xs = [PAD + LABEL_W]
    for _ in range(COLS - 1):
        col_xs.append(col_xs[-1] + THUMB + GAP)
    col_titles = ["original ERNIE", "SVG rendu", "diff (non couvert = rouge)"]
    for c, t in enumerate(col_titles):
        draw.text((col_xs[c] + 4, PAD + HEADER_H - 26), t, fill=TEXT, font=fonts["head"])

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

        # Stats sous le label
        nc = s.get("non_covered_pct", 0)
        nc_color = COL_OK if nc < 0.5 else COL_BAD
        nj3 = s.get("junctions_3", "?")
        nj4 = s.get("junctions_4plus", "?")
        np_ = s.get("n_polylines", "?")
        pts = s.get("n_points_total", "?")
        draw.text((PAD, y + 82), f"non_cov : {nc:.3f}%", fill=nc_color, font=fonts["stat"])
        draw.text((PAD, y + 104), f"junctions 3/4+ : {nj3}/{nj4}", fill=TEXT, font=fonts["stat"])
        draw.text((PAD, y + 124), f"polylines : {np_}  pts : {pts}", fill=SUB, font=fonts["small"])

        # Col 0 : original
        orig = (PROJECT_ROOT / item["path"]).resolve()
        if orig.exists():
            with Image.open(orig) as im:
                sheet.paste(_fit(im, THUMB), (col_xs[0], y))

        # Col 1 : SVG render
        svg_rend = s.get("outputs", {}).get("svg_render_png")
        if svg_rend:
            p = (PROJECT_ROOT / svg_rend).resolve()
            if p.exists():
                with Image.open(p) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[1], y))

        # Col 2 : diff
        diff = s.get("outputs", {}).get("diff_png")
        if diff:
            p = (PROJECT_ROOT / diff).resolve()
            if p.exists():
                with Image.open(p) as im:
                    sheet.paste(_fit(im, THUMB), (col_xs[2], y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def build_junction_zoom(
    corpus: dict,
    g3_stats: dict,
    image_id: str,
    junction_idx: int,
    out_path: Path,
    zoom_radius: int = 80,
    upscale: int = 4,
) -> Path:
    items_by_id = {it["id"]: it for it in corpus["images"]}
    by_id = {s["id"]: s for s in g3_stats["images"]}
    item = items_by_id[image_id]
    s = by_id[image_id]
    best = s["best_junctions"]
    if junction_idx >= len(best):
        junction_idx = 0
    junc = best[junction_idx]
    r, c, n_labels = junc["row"], junc["col"], junc["labels_around"]

    # Source images
    orig = (PROJECT_ROOT / item["path"]).resolve()
    svg_rend = (PROJECT_ROOT / s["outputs"]["svg_render_png"]).resolve()
    overlay = (PROJECT_ROOT / s["outputs"]["junctions_overlay_png"]).resolve()

    # Box
    left = max(0, c - zoom_radius)
    top = max(0, r - zoom_radius)
    right = left + 2 * zoom_radius
    bottom = top + 2 * zoom_radius
    box = (left, top, right, bottom)
    target_side = (2 * zoom_radius) * upscale
    panels = []
    for src in [orig, svg_rend, overlay]:
        with Image.open(src) as im:
            crop = im.convert("RGB").crop(box).resize(
                (target_side, target_side), Image.NEAREST
            )
        panels.append(crop)

    gap = 12
    pad = 16
    title_h = 44
    label_h = 28
    canvas_w = target_side * 3 + gap * 2 + pad * 2
    canvas_h = target_side + title_h + label_h + pad * 2

    canvas = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(canvas)
    fonts = {
        "title": _font(20),
        "head": _font(16),
    }
    title = (
        f"G3 jonction triple - {image_id} - corner ({r}, {c}) avec "
        f"{n_labels} labels alentour - zoom x{upscale}"
    )
    draw.text((pad, pad), title, fill=TITLE, font=fonts["title"])

    img_y = pad + title_h
    for i, (p, lab) in enumerate(zip(panels, ["original", "SVG rendu", "jonctions (orange)"])):
        x = pad + i * (target_side + gap)
        canvas.paste(p, (x, img_y))
        draw.text((x, img_y + target_side + 4), lab, fill=TEXT, font=fonts["head"])

    canvas.save(out_path, "PNG", optimize=True)
    return out_path


def build_browser_html(g3_stats: dict, out_path: Path) -> Path:
    items = g3_stats["images"]
    parts = ["""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>G3 Decoloriage - SVG browseable</title>
<style>
  body { font-family: -apple-system, Segoe UI, system-ui, sans-serif; background:#f5f5f7; color:#222; padding:24px; }
  h1 { margin-top:0; }
  .grid { display:grid; grid-template-columns: repeat(2, 1fr); gap:18px; margin-top:16px; }
  .card { background:#fff; border:1px solid #ddd; border-radius:8px; padding:12px; }
  .card h2 { font-size: 15px; margin: 0 0 8px; color:#444; }
  .card .stat { font-size: 12px; color:#666; margin-bottom:8px; }
  .card img { display:block; width: 100%; height: auto; image-rendering: -webkit-optimize-contrast; }
  .pass { color: #2e7d32; font-weight: 600; }
  .fail { color: #c62828; font-weight: 600; }
</style>
</head>
<body>
<h1>G3 Decoloriage - SVG ouvrables dans le navigateur</h1>
<p>Chaque carte ci-dessous charge un SVG en tag &lt;img&gt;. Si le navigateur sait afficher
le SVG vectoriel, il l'affiche tel quel. Critere pass : 0 marche d'escalier visible
a zoom 200 % (zoom navigateur).</p>
<div class="grid">"""]
    for s in items:
        svg_rel = Path(s["outputs"]["svg"]).name
        nc = s["non_covered_pct"]
        css = "pass" if nc < 0.5 else "fail"
        parts.append(f"""<div class="card">
  <h2>#{s['slot']:02d} {s['id']}</h2>
  <div class="stat">polylines: {s['n_polylines']} | pts: {s['n_points_total']} |
    non couvert: <span class="{css}">{nc:.3f} %</span> |
    jonctions triples: {s['junctions_3']} | 4+: {s['junctions_4plus']}</div>
  <img src="g3_out/{svg_rel}" alt="{s['id']}">
</div>""")
    parts.append("</div></body></html>")
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--stats", type=Path, default=DEFAULT_G3_STATS)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    args = parser.parse_args()

    if not args.corpus.exists() or not args.stats.exists():
        print("ERREUR : corpus ou stats absent", file=sys.stderr)
        return 2

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    g3 = json.loads(args.stats.read_text(encoding="utf-8"))

    sheet_path = build_main_sheet(corpus, g3, args.sheet)
    print(f"OK planche : {sheet_path}")

    # 4 zooms : choisir des images avec triple junctions sur des zones variees
    zoom_specs = [
        ("pastel_dog", 0, Path(__file__).parent / "zoom_g3_junction_dog.png"),
        ("pastel_lion2", 0, Path(__file__).parent / "zoom_g3_junction_lion.png"),
        ("taxo_polar_bear_on_ice", 0,
         Path(__file__).parent / "zoom_g3_junction_polar_bear.png"),
        ("pastel_peacock", 0, Path(__file__).parent / "zoom_g3_junction_peacock.png"),
    ]
    for image_id, jidx, out in zoom_specs:
        p = build_junction_zoom(corpus, g3, image_id, jidx, out)
        print(f"OK zoom    : {p}")

    html = build_browser_html(g3, args.html)
    print(f"OK HTML    : {html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
