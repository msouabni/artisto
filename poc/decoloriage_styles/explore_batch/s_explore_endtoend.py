"""EXPLORATION end-to-end - 4 styles ornementaux, cible ADULTE.

Distinction structurelle (determine le calibrage) :

  TUILES (mosaic, zellige) : tuiles colorees + joints sombres.
    - fond            : chromakey green -> Papier (region fond unique)
    - source d'encre  : joints L<25 ; fallback = frontieres de partition (arcs)
    - color_mode      : FAITHFUL (hex moyen d'origine de la tuile)
    - stroke          : noir fin (joints)
    - merge           : smooth_merge ΔE pour ramener n_regions dans la zone usable

  LINE-ART NATIF (mandala, zentangle) : noir sur blanc, deja une page de
  coloriage.
    - fond            : blanc (PAS de chromakey) -> Papier via L*>=92
    - source d'encre  : traits noirs natifs L<25
    - color_mode      : BLANK (white-fillable ; pas de couleur d'origine, source N&B)
    - stroke          : noir fin
    - regions         : cellules blanches encloses (partition g2 + merge leger)

Reutilise PAR IMPORT (aucune modif) :
  - poc/decoloriage/g2_partition (process_image_3levels, smooth_merge_similar)
  - poc/decoloriage/g3_vectorize (extract_region_polygons, _signed_area)
  - poc/decoloriage/g4_two_weight (arcs, classify, smooth, thickness)
  - poc/decoloriage/g5_product (compute_region_colors_from_original, compute_ink_regions)
  - src/services/extract_palette (_detect_chromakey_mask)

Le rendu SVG/HTML/preview est parametre par STYLE_CONFIG (fond, encre,
color_mode, stroke, merge). Aucune modif des modules POC1/POC2.
"""
from __future__ import annotations

import base64
import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent.parent
POC1_DIR = PROJECT_ROOT / "poc" / "decoloriage"
sys.path.insert(0, str(POC1_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from g2_partition import process_image_3levels, smooth_merge_similar  # noqa: E402
from g3_vectorize import extract_region_polygons, _signed_area  # noqa: E402
from g4_two_weight import (  # noqa: E402
    extract_topological_arcs,
    classify_arc_into_ink_or_shading,
    smooth_open_arc,
    LINE_MASK_DILATE_PX,
    DP_TOLERANCE,
    CHAIKIN_ITERS_ARC,
    CHAIKIN_ITERS_REGION,
)
from g5_product import (  # noqa: E402
    compute_region_colors_from_original,
    compute_ink_regions,
    INK_REGION_OVERLAP_THRESHOLD,
)
from services.extract_palette import _detect_chromakey_mask  # noqa: E402

CORPUS = HERE / "corpus"
OUT_DIR = HERE  # livrables directement sous explore_batch/
WORK_DIR = HERE / "_work"

CHROMAKEY_RGB = (0, 177, 64)
CHROMAKEY_DELTA_E = 40.0
INK_HEX = "#15151B"
INK_PX = 2.0
SHADING_PX = 1.0
WHITE_L_THRESH = 92.0   # L*>=92 -> Papier (fond blanc line-art)

STYLES = ["mosaic", "zellige", "mandala", "zentangle"]
SUBJECTS = ["dog", "castle", "peacock"]

# Calibrage par style (itere ci-dessous ; voir CALIBRATION.md).
#   bg        : "chromakey" | "white"
#   color_mode: "faithful" | "blank"
#   ink_source: "joints" (L<25 + ink-regions kawaii-like) | "lineart" (L<25, arcs ink)
#   merge_de  : seuil smooth_merge ΔE (0 = aucun) pour reduire n_regions
# ink_mode :
#   "joints"  -> tuiles : regions a fort overlap avec joints dilates = encre
#                (compute_ink_regions). color regions = tuiles.
#   "dark"    -> line-art : regions sombres (L_mean < INK_L_MEAN) = encre noire
#                non cliquable ; toutes les cellules claires restent cliquables.
#                (evite que compute_ink_regions n'avale toutes les cellules.)
# merge_de : seuil smooth_merge ΔE (0 = aucun).
INK_L_MEAN = 28.0   # line-art : region encre si L moyen < 28 (vrai noir seulement,
                    # pas les gris moyens -> evite d'empater le fond ornemental)
STYLE_CONFIG = {
    "mosaic":    {"bg": "chromakey", "color_mode": "faithful", "ink_source": "joints",  "ink_mode": "joints", "merge_de": 16.0, "ink_px": 2.0},
    "zellige":   {"bg": "chromakey", "color_mode": "faithful", "ink_source": "joints",  "ink_mode": "joints", "merge_de": 14.0, "ink_px": 2.0},
    "mandala":   {"bg": "white",     "color_mode": "blank",    "ink_source": "lineart", "ink_mode": "dark",   "merge_de": 6.0,  "ink_px": 1.5},
    "zentangle": {"bg": "white",     "color_mode": "blank",    "ink_source": "lineart", "ink_mode": "dark",   "merge_de": 6.0,  "ink_px": 1.5},
}


def _hex_to_bgr(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


def force_single_bg(rm: np.ndarray, bg_mask: np.ndarray):
    """Fusionne tous les pixels bg_mask dans UNE region de fond. -> (rm, bg_label, n_subj)."""
    rm2 = rm.copy().astype(np.int32)
    bm = bg_mask > 0
    subj_labels = sorted(int(x) for x in np.unique(rm2[~bm])) if (~bm).any() else []
    remap = {old: i for i, old in enumerate(subj_labels)}
    final_bg = len(subj_labels)
    out = np.empty_like(rm2)
    for old, new in remap.items():
        out[rm2 == old] = new
    out[bm] = final_bg
    return out, final_bg, len(subj_labels)


PALETTE_FREE = ["#FF2E63", "#FF8A2B", "#FFD60A", "#06D6A0",
                "#118AB2", "#8B5CF6", "#9B5E3C", "#222222"]


# ----------------------------------------------------------------------------
# SVG bicouche parametre (faithful ou blank)
# ----------------------------------------------------------------------------
def build_svg(region_polys, region_data, arcs_classified, cfg, H, W, ink_region_ids):
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" shape-rendering="geometricPrecision">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        '<g id="fills" stroke="none" fill-rule="evenodd">',
    ]

    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))

    for rid, polys in sorted_polys:
        d_parts = []
        for poly in polys:
            d_parts.append(f"M{poly[0][1]:.2f},{poly[0][0]:.2f}")
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            d_parts.append("Z")
        d_attr = " ".join(d_parts)
        if rid in ink_region_ids:
            lines.append(
                f'<path class="ink-region" data-region-id="{rid}" '
                f'fill="{INK_HEX}" pointer-events="none" d="{d_attr}"/>')
            continue
        data = region_data.get(rid)
        if data is None:
            continue
        bg_class = " region-bg" if data["is_background"] else ""
        if data["is_background"]:
            target = "#ffffff"
        elif cfg["color_mode"] == "faithful":
            target = data["hex_original"]
        else:  # blank
            target = "#ffffff"
        lines.append(
            f'<path class="region{bg_class}" data-region-id="{rid}" '
            f'data-color="{target}" data-original="{data["hex_original"]}" '
            f'fill="#ffffff" d="{d_attr}"/>')
    lines.append("</g>")

    ink_px = cfg["ink_px"]
    lines.append(
        f'<g id="strokes" fill="none" stroke="{INK_HEX}" stroke-linejoin="round" '
        f'stroke-linecap="round" pointer-events="none">')
    for arc in arcs_classified:
        poly = arc["smoothed"]
        if len(poly) < 2:
            continue
        cls = arc["class"]
        sw = ink_px if cls == "ink" else SHADING_PX
        cls_attr = ' class="arc-ink"' if cls == "ink" else ' class="arc-shading"'
        d_parts = [f"M{poly[0][1]:.2f},{poly[0][0]:.2f}"]
        for p in poly[1:]:
            d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
        lines.append(f'<path{cls_attr} d="{" ".join(d_parts)}" stroke-width="{sw:.2f}"/>')
    lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Exploration ornemental - {title}</title>
<style>
  :root {{ --bg:#fdfbf6; --paper:#fff; --ink:#15151b; --muted:#6b6b78; --shadow:0 6px 24px rgba(0,0,0,.08); }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:var(--ink); min-height:100vh; display:flex; flex-direction:column; }}
  header {{ padding:18px 24px; border-bottom:1px solid #ece8df; background:#fff; }}
  header h1 {{ margin:0; font-size:18px; font-weight:600; }}
  header p {{ margin:4px 0 0; color:var(--muted); font-size:13px; }}
  main {{ flex:1; display:grid; grid-template-columns:1fr 300px; gap:18px; padding:18px 24px; max-width:1500px; margin:0 auto; width:100%; }}
  .canvas-wrap {{ background:var(--paper); border-radius:16px; padding:18px; box-shadow:var(--shadow); display:flex; align-items:center; justify-content:center; min-height:600px; }}
  .canvas-wrap svg {{ width:100%; height:auto; max-height:84vh; display:block; }}
  .region {{ cursor:pointer; transition:fill .08s ease; }}
  .region:hover {{ filter:brightness(.95); }}
  .arc-shading {{ stroke:none; }}
  .show-guides .arc-shading {{ stroke:#DDD; stroke-width:1; }}
  aside {{ display:flex; flex-direction:column; gap:14px; }}
  .card {{ background:var(--paper); border-radius:12px; padding:14px; box-shadow:var(--shadow); }}
  .card h2 {{ margin:0 0 10px; font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }}
  .palette {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }}
  .swatch {{ aspect-ratio:1; border-radius:8px; border:3px solid transparent; cursor:pointer; }}
  .swatch[aria-pressed="true"] {{ border-color:var(--ink); transform:scale(1.06); }}
  .picker-row {{ display:flex; align-items:center; gap:8px; margin-top:10px; }}
  .picker-row input[type=color] {{ width:42px; height:32px; border:none; background:none; cursor:pointer; }}
  .actions {{ display:flex; flex-direction:column; gap:8px; }}
  button.action {{ appearance:none; border:1.5px solid var(--ink); background:#fff; color:var(--ink); border-radius:10px; padding:10px 12px; font-size:14px; font-weight:600; cursor:pointer; }}
  button.action:hover {{ background:#f5f1e6; }}
  button.action.primary {{ background:var(--ink); color:#fff; }}
  .ref-wrap img {{ width:100%; max-width:260px; border-radius:8px; border:1px solid #ece8df; }}
  .stats {{ font-size:12px; color:var(--muted); line-height:1.55; }}
  .stats strong {{ color:var(--ink); }}
  footer {{ padding:12px 24px; color:var(--muted); font-size:12px; text-align:center; }}
</style></head>
<body>
<header><h1>Exploration ornemental - <em>{title}</em></h1>
<p>Style <strong>{style}</strong> &middot; cible ADULTE &middot; {style_note}</p></header>
<main>
  <section class="canvas-wrap" aria-label="Zone de coloriage">{svg_inline}</section>
  <aside>
    <div class="card"><h2>Palette libre</h2><div class="palette" role="radiogroup">{palette_html}</div>
      <div class="picker-row"><label>Couleur libre</label><input type="color" id="picker" value="#FF2E63"></div></div>
    <div class="card actions"><h2>Actions</h2>
      <button class="action primary" id="btn-solution">{sol_label}</button>
      <button class="action" id="btn-reset">Tout effacer</button>
      <button class="action" id="btn-guides" aria-pressed="false">Guides : OFF</button></div>
    <div class="card"><h2>Reference ERNIE</h2><div class="ref-wrap">
      <img src="data:image/png;base64,{ref_b64}" alt="Image ERNIE d'origine"></div></div>
    <div class="card stats"><strong>{n_regions}</strong> zones cliquables ({n_ink_regions} regions-encre)<br>
      <strong>{n_arcs}</strong> arcs frontieres ({n_ink} encre, {n_shading} fins)<br>
      Mode couleur : <strong>{color_mode}</strong> &middot; encre : {ink_source}</div>
  </aside>
</main>
<footer>POC2 exploration ornemental - {title}</footer>
<script>
(() => {{
  let selected = '#FF2E63';
  const swatches = document.querySelectorAll('.swatch');
  const picker = document.getElementById('picker');
  swatches.forEach(btn => {{ btn.addEventListener('click', () => {{
    swatches.forEach(b => b.setAttribute('aria-pressed','false'));
    btn.setAttribute('aria-pressed','true'); selected = btn.dataset.color; picker.value = selected; }}); }});
  picker.addEventListener('input', () => {{ selected = picker.value; swatches.forEach(b => b.setAttribute('aria-pressed','false')); }});
  document.querySelectorAll('.region').forEach(p => p.addEventListener('click', () => p.setAttribute('fill', selected)));
  document.getElementById('btn-solution').addEventListener('click', () => {{
    document.querySelectorAll('.region').forEach(p => p.setAttribute('fill', p.dataset.color || '#ffffff')); }});
  document.getElementById('btn-reset').addEventListener('click', () => {{
    document.querySelectorAll('.region').forEach(p => p.setAttribute('fill','#ffffff')); }});
  const guides = document.getElementById('btn-guides');
  guides.addEventListener('click', () => {{ const wrap = document.querySelector('.canvas-wrap');
    const on = wrap.classList.toggle('show-guides'); guides.setAttribute('aria-pressed', on?'true':'false');
    guides.textContent = on ? 'Guides : ON' : 'Guides : OFF'; }});
}})();
</script></body></html>
"""


def build_html(svg_inline, ref_png, title, style, cfg, n_regions, n_arcs,
               n_ink, n_shading, n_ink_regions, style_note):
    parts = []
    for i, hexc in enumerate(PALETTE_FREE):
        parts.append(
            f'<button class="swatch" role="radio" aria-pressed="{"true" if i==0 else "false"}" '
            f'data-color="{hexc}" style="background:{hexc}" title="{hexc}"></button>')
    sol_label = "Solution (tons d'origine)" if cfg["color_mode"] == "faithful" else "Tout effacer (pas de solution N&B)"
    ref_b64 = base64.b64encode(ref_png.read_bytes()).decode("ascii")
    return HTML_TEMPLATE.format(
        title=title, svg_inline=svg_inline, palette_html="\n".join(parts),
        ref_b64=ref_b64, n_regions=n_regions, n_arcs=n_arcs, n_ink=n_ink,
        n_shading=n_shading, n_ink_regions=n_ink_regions, style=style,
        color_mode=cfg["color_mode"], ink_source=cfg["ink_source"],
        style_note=style_note, sol_label=sol_label)


def _rasterize(region_polys, region_data, arcs_classified, cfg, H, W,
               ink_region_ids, ink_pixel_mask, blank_path, sol_path):
    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))
    ink_bgr = _hex_to_bgr(INK_HEX)
    ink_region_bgr = np.array(ink_bgr, dtype=np.uint8)
    ink_int = max(1, int(round(cfg["ink_px"])))

    def draw_strokes(canvas):
        if ink_pixel_mask is not None and ink_pixel_mask.any():
            canvas[ink_pixel_mask] = ink_region_bgr
        if cfg["ink_mode"] == "dark":
            # line-art : le trait = uniquement le masque natif fin (deja pose
            # ci-dessus). On NE redessine PAS les 30k+ arcs (qui empateraient le
            # preview). Le SVG, lui, porte les arcs en vectoriel zoomable.
            return
        for arc in arcs_classified:
            if arc["class"] != "ink":
                continue
            poly = arc["smoothed"]
            if len(poly) < 2:
                continue
            pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(canvas, [pts], False, ink_bgr, ink_int, lineType=cv2.LINE_AA)

    # solution
    sol = np.full((H, W, 3), 255, dtype=np.uint8)
    if cfg["color_mode"] == "faithful":
        for rid_int, polys in sorted_polys:
            if rid_int in ink_region_ids:
                continue
            data = region_data.get(rid_int)
            if data is None or data["is_background"]:
                continue
            bgr = _hex_to_bgr(data["hex_original"])
            for poly in polys:
                pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
                cv2.fillPoly(sol, [pts], bgr)
    draw_strokes(sol)
    cv2.imwrite(str(sol_path), sol)

    # blank
    blank = np.full((H, W, 3), 255, dtype=np.uint8)
    draw_strokes(blank)
    cv2.imwrite(str(blank_path), blank)


def process_one(style, subject, slot):
    rid = f"{style}_{subject}"
    cfg = STYLE_CONFIG[style]
    src = CORPUS / f"{rid}.png"
    rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    H, W = rgb.shape[:2]
    total_px = H * W
    t0 = time.time()
    lab_full = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab_full[:, :, 0] * 100.0 / 255.0

    # --- background mask ---
    if cfg["bg"] == "chromakey":
        bg_mask = _detect_chromakey_mask(bgr, CHROMAKEY_RGB, CHROMAKEY_DELTA_E)
    else:  # white line-art : L*>=92
        bg_mask = (L >= WHITE_L_THRESH).astype(np.uint8) * 255
    pct_bg = round(100.0 * (bg_mask > 0).sum() / total_px, 2)

    # --- ink mask L<25 (sans bg) ---
    ink_l25 = (L < 25).astype(np.uint8) * 255
    ink_l25[bg_mask > 0] = 0
    pct_ink_mask = round(100.0 * int((ink_l25 > 0).sum()) / total_px, 2)

    # --- partition g2 niveau adulte ---
    l25_path = WORK_DIR / f"{rid}_lines.png"
    result = process_image_3levels(rgb, out_lines=l25_path)
    rm_adulte = result["levels"]["adulte"]["region_map"].astype(np.int32)
    rm_enfant = result["levels"]["enfant"]["region_map"].astype(np.int32)
    n_adulte_raw = int(len(np.unique(rm_adulte)))
    n_enfant_raw = int(len(np.unique(rm_enfant)))

    # --- merge leger par style (reduit n_regions vers zone usable) ---
    if cfg["merge_de"] > 0:
        rm_merged, n_merges = smooth_merge_similar(rm_adulte, lab_full, cfg["merge_de"])
        rm_merged = rm_merged.astype(np.int32)
    else:
        rm_merged, n_merges = rm_adulte, 0
    n_after_merge = int(len(np.unique(rm_merged)))

    # --- fond -> region unique ---
    rm_fixed, bg_label, n_subj = force_single_bg(rm_merged, bg_mask)
    n_regions = int(len(np.unique(rm_fixed)))

    # --- couleurs originales par region ---
    region_colors = compute_region_colors_from_original(rgb, rm_fixed)
    region_data = {}
    for rid_int, c in region_colors.items():
        region_data[rid_int] = {
            "hex_original": c["hex"], "lab": c["lab"],
            "is_background": (rid_int == bg_label),
        }

    # --- ink-regions selon le mode ---
    kernel = np.ones((LINE_MASK_DILATE_PX, LINE_MASK_DILATE_PX), np.uint8)
    line_mask_dilated = cv2.dilate(ink_l25, kernel, iterations=1)
    if cfg["ink_mode"] == "joints":
        # tuiles : regions a fort overlap avec joints dilates = encre.
        ink_region_ids, _ratios = compute_ink_regions(
            rm_fixed, line_mask_dilated, INK_REGION_OVERLAP_THRESHOLD)
    else:  # "dark" : line-art -> region encre si L moyen < INK_L_MEAN.
        # (compute_ink_regions avalerait toutes les cellules en line-art dense.)
        ink_region_ids = {
            rid_int for rid_int, d in region_data.items()
            if d["lab"][0] < INK_L_MEAN
        }
    ink_region_ids.discard(int(bg_label))

    # --- arcs topologiques + classif ink/shading ---
    arcs, _ = extract_topological_arcs(rm_fixed)
    arcs_classified = []
    n_ink = n_shading = 0
    for arc in arcs:
        cls, _r = classify_arc_into_ink_or_shading(arc["points"], line_mask_dilated)
        smoothed = smooth_open_arc(arc["points"], DP_TOLERANCE, CHAIKIN_ITERS_ARC, H, W)
        arcs_classified.append({**arc, "class": cls, "smoothed": smoothed})
        if cls == "ink":
            n_ink += 1
        elif cls == "shading":
            n_shading += 1

    # --- region polygons ---
    region_polys = extract_region_polygons(rm_fixed, DP_TOLERANCE, CHAIKIN_ITERS_REGION)

    # --- SVG ---
    svg_text = build_svg(region_polys, region_data, arcs_classified, cfg, H, W, ink_region_ids)
    (OUT_DIR / f"{rid}.svg").write_text(svg_text, encoding="utf-8")

    n_clickable = sum(
        1 for rid_int, d in region_data.items()
        if rid_int not in ink_region_ids and not d["is_background"])

    # --- previews ---
    if cfg["ink_mode"] == "dark":
        # line-art : l'encre du blank = UNIQUEMENT le trait noir natif fin (L<25
        # sur l'original), pas les regions sombres k-means (qui empateraient la
        # page en masses noires). Les regions sombres restent hors-clickable via
        # ink_region_ids (non coloriees), mais ne sont PAS peintes en noir plein.
        ink_pixel_mask = (ink_l25 > 0)
    else:
        # tuiles : joints = regions encre (remplies) -> blank = tuiles blanches
        # separees par joints sombres.
        ink_pixel_mask = np.zeros((H, W), dtype=bool)
        for rid_int in ink_region_ids:
            ink_pixel_mask |= (rm_fixed == rid_int)
    blank_path = OUT_DIR / f"{rid}_blank.png"
    sol_path = OUT_DIR / f"{rid}_solution.png"
    _rasterize(region_polys, region_data, arcs_classified, cfg, H, W,
               ink_region_ids, ink_pixel_mask, blank_path, sol_path)

    # --- HTML (dog only -> raccourci ; on genere pour tous, copie dog plus tard) ---
    note = {
        "mosaic": "tuiles fideles + joints noirs ; fond chromakey -> papier.",
        "zellige": "tuiles geometriques fideles + contours noirs ; fond chromakey -> papier.",
        "mandala": "line-art natif ; cellules blanches a colorier, encre noire native.",
        "zentangle": "line-art natif dense ; cellules blanches a colorier, encre noire native.",
    }[style]
    html_text = build_html(
        svg_text, src, rid.replace("_", " ").title(), style, cfg,
        n_clickable, len(arcs), n_ink, n_shading, len(ink_region_ids), note)
    (OUT_DIR / f"{rid}.html").write_text(html_text, encoding="utf-8")

    elapsed = round(time.time() - t0, 2)
    print(
        f"[{style:9s} {subject:7s}] bg%={pct_bg:5.1f} ink%={pct_ink_mask:5.1f} "
        f"adulte={n_adulte_raw:4d} merge_de={cfg['merge_de']:.0f}->{n_after_merge:4d} "
        f"final={n_regions:4d} clickable={n_clickable:4d} ink_reg={len(ink_region_ids):3d} "
        f"arcs={len(arcs):4d}(ink={n_ink}) ({elapsed}s)", flush=True)

    return {
        "id": rid, "slot": slot, "style": style, "subject": subject,
        "image_size": [int(W), int(H)],
        "bg": cfg["bg"], "color_mode": cfg["color_mode"],
        "ink_source": cfg["ink_source"], "merge_de": cfg["merge_de"],
        "stroke_px": cfg["ink_px"], "stroke_hex": INK_HEX,
        "bg_pct": pct_bg, "pct_ink_mask": pct_ink_mask,
        "n_regions_adulte_raw": n_adulte_raw,
        "n_regions_enfant_raw": n_enfant_raw,
        "n_merges": n_merges, "n_after_merge": n_after_merge,
        "n_subject_regions": n_subj,
        "n_regions": n_regions, "n_clickable": n_clickable,
        "n_ink_regions": len(ink_region_ids),
        "n_arcs": len(arcs), "n_ink": n_ink, "n_shading": n_shading,
        "blank_png": f"{rid}_blank.png", "solution_png": f"{rid}_solution.png",
        "svg": f"{rid}.svg", "html": f"{rid}.html",
        "timing_s": elapsed,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--styles", nargs="+", default=None,
                    help="ne traiter que ces styles (defaut : tous)")
    args = ap.parse_args()
    sel_styles = args.styles or STYLES

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    per_image = []
    failures = []
    # reprise incrementale : repartir des images deja faites dans explore_stats.json
    prev_path = OUT_DIR / "explore_stats.json"
    prev_by_id = {}
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            prev_by_id = {r["id"]: r for r in prev.get("images", [])}
        except Exception:  # noqa: BLE001
            prev_by_id = {}
    t_start = time.time()
    slot = 0
    for style in STYLES:
        for subject in SUBJECTS:
            slot += 1
            rid = f"{style}_{subject}"
            if style not in sel_styles:
                if rid in prev_by_id:
                    per_image.append(prev_by_id[rid])  # conserve l'ancien resultat
                continue
            if not (CORPUS / f"{rid}.png").exists():
                failures.append({"id": rid, "reason": "PNG absent"})
                continue
            last_exc = None
            for attempt in range(3):
                try:
                    per_image.append(process_one(style, subject, slot))
                    last_exc = None
                    break
                except Exception as exc:  # noqa: BLE001
                    import traceback
                    last_exc = exc
                    print(f"[retry {attempt}] {rid}: {exc!r}", file=sys.stderr)
                    if attempt == 2:
                        traceback.print_exc()
            if last_exc is not None:
                failures.append({"id": rid, "reason": repr(last_exc)})

    # Livrable <style>_dog.html = directement {style}_dog.html (deja ecrit par
    # process_one sous le nom {rid}.html). rid == f"{style}_dog" -> meme fichier,
    # aucune copie necessaire.

    out = {
        "gate": "POC2-exploration-ornamental",
        "frozen_at": "2026-06-11",
        "target": "ADULTE : coloriable par construction, calibrage par style",
        "style_config": STYLE_CONFIG,
        "poc_reused": [
            "poc/decoloriage/g2_partition.py (process_image_3levels, smooth_merge_similar)",
            "poc/decoloriage/g3_vectorize.py (extract_region_polygons, _signed_area)",
            "poc/decoloriage/g4_two_weight.py (arcs, classify, smooth)",
            "poc/decoloriage/g5_product.py (compute_region_colors_from_original, compute_ink_regions)",
            "src/services/extract_palette.py (_detect_chromakey_mask)",
        ],
        "n_processed": len(per_image), "n_failed": len(failures),
        "failures": failures, "images": per_image,
        "timing_s_total": round(time.time() - t_start, 2),
    }
    (OUT_DIR / "explore_stats.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK explore_stats.json -> {len(per_image)}/12 traitees, {len(failures)} echec(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
