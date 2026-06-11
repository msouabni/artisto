"""S3 v3 "fidelite" - Bout-en-bout low_poly + kawaii_bold, cible ADULTE.

Itération v3 du POC2 (skill decoloriage-styles). Implemente les 4 demandes
humaines (cible ADULTE = max detail, aucune simplification, fidelite couleurs) :

  1. Chromakey dans le prompt : conserve (deja v2/v3, "solid chroma key green
     background"). RAS.

  2. Max detail / pas de simplification : on utilise la partition niveau
     ADULTE (= rm_v3 brut de g2, SANS smooth_merge enfant). Toutes les regions
     preservees. n_regions documente vs enfant.

  3. low_poly PAS de trace noir : aucune couche d'encre noire ni region-encre.
     Les frontieres de facettes sont rendues en traits fins gris clair
     (#999999, 1px) uniquement (guides). Le blank = facettes a fins contours
     gris, coloriables.

  4. kawaii fidelite couleurs : mode solution FIDELE -> data-color = couleur
     MOYENNE D'ORIGINE de chaque region (hex ERNIE reel), PAS le nearest-crayon.
     Trait noir FIN (~2px, comme v2) conserve comme outline.
     (low_poly aussi : solution en couleurs d'origine fideles.)

POC 1 ET POC 2 reutilises PAR IMPORT (aucune modification du code source) :
  - poc/decoloriage/g2_partition.process_image_3levels  (niveau "adulte")
  - poc/decoloriage/g3_vectorize.extract_region_polygons / _signed_area
  - poc/decoloriage/g4_two_weight.* (arcs topologiques, classify, smooth,
    measure_line_thickness)
  - poc/decoloriage/g5_product.* (compute_region_colors_from_original,
    compute_ink_regions, build_crayons_lab/nearest_crayon pour stats only)
  - src/services/extract_palette._detect_chromakey_mask

Le rendu SVG/HTML/preview est REIMPLEMENTE ici (pas une modif de g5_product)
pour porter le mode "fidele" (data-color = hex original) et le rendu par style
(low_poly = strokes gris fins sans noir ; kawaii = strokes noirs fins).

Livrables (poc/decoloriage_styles/s3_out_v3/) :
  - <id>_blank.png + <id>_solution.png (6 chacun, solution = tons fideles)
  - <id>_zoom.png (dog visage/museau + peacock queue, 2 styles -> 4 crops x2)
  - low_poly_dog.html + kawaii_bold_dog.html (click-to-fill, vectoriel, fidele)
  - v3_stats.json
La galerie gallery_v3.png est produite par make_gallery_v3.py.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
POC1_DIR = PROJECT_ROOT / "poc" / "decoloriage"
sys.path.insert(0, str(POC1_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(HERE))

from g2_partition import process_image_3levels  # noqa: E402
from g3_vectorize import extract_region_polygons, _signed_area  # noqa: E402
from g4_two_weight import (  # noqa: E402
    extract_topological_arcs,
    classify_arc_into_ink_or_shading,
    measure_line_thickness,
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

CORPUS_V3 = HERE / "corpus_v3"
OUT_DIR = HERE / "s3_out_v3"
WORK_DIR = OUT_DIR / "_work"

CHROMAKEY_RGB = (0, 177, 64)   # #00B140
CHROMAKEY_DELTA_E = 40.0       # plateau valide v2

SUBJECTS = ["dog", "castle", "peacock"]
STYLES = ["low_poly", "kawaii_bold"]

# Cible ADULTE -> niveau de partition g2.
PARTITION_LEVEL = "adulte"

# Rendu par style.
LOWPOLY_STROKE_HEX = "#999999"   # gris clair, guides facettes
LOWPOLY_STROKE_PX = 1.0
KAWAII_INK_PX = 2.0              # outline noir fin (comme v2)
KAWAII_SHADING_PX = 1.0
KAWAII_INK_HEX = "#15151B"


# ----------------------------------------------------------------------------
# FIX 1 chromakey (reutilise la logique v2)
# ----------------------------------------------------------------------------
def force_chromakey_background(rm: np.ndarray, chromakey_mask: np.ndarray):
    """Force tous les pixels chromakey dans UNE seule region de fond dediee.
    Retourne (rm_modifie, final_bg_label, n_subject_regions)."""
    rm2 = rm.copy().astype(np.int32)
    ck = chromakey_mask > 0
    subj_labels = sorted(int(x) for x in np.unique(rm2[~ck]))
    remap = {old: i for i, old in enumerate(subj_labels)}
    final_bg = len(subj_labels)
    out = np.empty_like(rm2)
    for old, new in remap.items():
        out[rm2 == old] = new
    out[ck] = final_bg
    return out, final_bg, len(subj_labels)


def muzzle_preserved(rm: np.ndarray, bg_label: int, chromakey_mask: np.ndarray) -> dict:
    """Verifie que la bande centrale-gauche du sujet n'a pas fuite dans le fond."""
    H, W = rm.shape
    ck = chromakey_mask > 0
    y0, y1 = int(0.30 * H), int(0.70 * H)
    x0, x1 = int(0.12 * W), int(0.50 * W)
    band_rm = rm[y0:y1, x0:x1]
    band_ck = ck[y0:y1, x0:x1]
    subj_band = ~band_ck
    n_subj = int(subj_band.sum())
    n_bg_leak = int(((band_rm == bg_label) & subj_band).sum())
    preserved = n_subj > 0 and n_bg_leak == 0
    return {
        "preserved": bool(preserved),
        "n_subject_px_in_band": n_subj,
        "n_bg_leak_px_in_band": n_bg_leak,
    }


# ----------------------------------------------------------------------------
# Rendu SVG bicouche FIDELE (data-color = hex original) par style
# ----------------------------------------------------------------------------
def build_faithful_svg(
    region_polys,
    region_data: dict[int, dict],   # rid -> {hex_original, lab, is_background}
    arcs_classified: list[dict],
    style: str,
    H: int,
    W: int,
    ink_region_ids: set[int] | None = None,
) -> str:
    """SVG bicouche click-to-fill, mode fidele.

    - Fill layer : un <path> par region, fill blanc au depart, data-color =
      hex MOYEN D'ORIGINE (fidele). data-original conserve pour reference.
    - low_poly : aucune region-encre, strokes = arcs en gris clair fin (#999,
      1px) class="arc-guide" (frontieres de facettes, coloriables).
    - kawaii  : region-encre eventuelles (overlap >= seuil) noir plein non
      cliquable ; arcs ink = noir fin (~2px) class="arc-ink", shading masque.
    """
    if ink_region_ids is None:
        ink_region_ids = set()
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'shape-rendering="geometricPrecision">'
    ]
    lines.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
    lines.append('<g id="fills" stroke="none" fill-rule="evenodd">')

    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))

    for rid, polys in sorted_polys:
        d_parts: list[str] = []
        for poly in polys:
            d_parts.append(f"M{poly[0][1]:.2f},{poly[0][0]:.2f}")
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            d_parts.append("Z")
        d_attr = " ".join(d_parts)

        if rid in ink_region_ids:
            lines.append(
                f'<path class="ink-region" data-region-id="{rid}" '
                f'fill="{KAWAII_INK_HEX}" pointer-events="none" d="{d_attr}"/>'
            )
            continue

        data = region_data.get(rid)
        if data is None:
            continue
        # MODE FIDELE : data-color = hex original (tons ERNIE reels).
        bg_class = " region-bg" if data["is_background"] else ""
        target = "#ffffff" if data["is_background"] else data["hex_original"]
        lines.append(
            f'<path class="region{bg_class}" data-region-id="{rid}" '
            f'data-color="{target}" '
            f'data-original="{data["hex_original"]}" '
            f'fill="#ffffff" d="{d_attr}"/>'
        )
    lines.append("</g>")

    # ---- Stroke layer (par style) ----
    if style == "low_poly":
        # Guides gris fins UNIQUEMENT, aucune couche noire.
        lines.append(
            f'<g id="strokes" fill="none" stroke="{LOWPOLY_STROKE_HEX}" '
            f'stroke-width="{LOWPOLY_STROKE_PX:.2f}" '
            f'stroke-linejoin="round" stroke-linecap="round" '
            f'pointer-events="none">'
        )
        for arc in arcs_classified:
            poly = arc["smoothed"]
            if len(poly) < 2:
                continue
            d_parts = [f"M{poly[0][1]:.2f},{poly[0][0]:.2f}"]
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            lines.append(f'<path class="arc-guide" d="{" ".join(d_parts)}"/>')
        lines.append("</g>")
    else:  # kawaii : noir fin, shading masque par defaut
        lines.append(
            f'<g id="strokes" fill="none" stroke="{KAWAII_INK_HEX}" '
            f'stroke-linejoin="round" stroke-linecap="round" '
            f'pointer-events="none">'
        )
        for arc in arcs_classified:
            poly = arc["smoothed"]
            if len(poly) < 2:
                continue
            cls = arc["class"]
            sw = KAWAII_INK_PX if cls == "ink" else KAWAII_SHADING_PX
            cls_attr = ' class="arc-ink"' if cls == "ink" else ' class="arc-shading"'
            d_parts = [f"M{poly[0][1]:.2f},{poly[0][0]:.2f}"]
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            lines.append(
                f'<path{cls_attr} d="{" ".join(d_parts)}" stroke-width="{sw:.2f}"/>'
            )
        lines.append("</g>")

    lines.append("</svg>")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# HTML standalone (palette libre + solution fidele)
# ----------------------------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>v3 fidelite - {title}</title>
<style>
  :root {{ --bg:#fdfbf6; --paper:#fff; --ink:#15151b; --muted:#6b6b78;
    --shadow:0 6px 24px rgba(0,0,0,.08); }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    color:var(--ink); min-height:100vh; display:flex; flex-direction:column; }}
  header {{ padding:18px 24px; border-bottom:1px solid #ece8df; background:#fff; }}
  header h1 {{ margin:0; font-size:18px; font-weight:600; }}
  header p {{ margin:4px 0 0; color:var(--muted); font-size:13px; }}
  main {{ flex:1; display:grid; grid-template-columns:1fr 300px; gap:18px;
    padding:18px 24px; max-width:1500px; margin:0 auto; width:100%; }}
  .canvas-wrap {{ background:var(--paper); border-radius:16px; padding:18px;
    box-shadow:var(--shadow); display:flex; align-items:center; justify-content:center; min-height:600px; }}
  .canvas-wrap svg {{ width:100%; height:auto; max-height:84vh; display:block; }}
  .region {{ cursor:pointer; transition:fill .08s ease; }}
  .region:hover {{ filter:brightness(.95); }}
  /* low_poly : guides gris fins (toujours visibles, fins). kawaii : shading masque. */
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
  button.action {{ appearance:none; border:1.5px solid var(--ink); background:#fff; color:var(--ink);
    border-radius:10px; padding:10px 12px; font-size:14px; font-weight:600; cursor:pointer; }}
  button.action:hover {{ background:#f5f1e6; }}
  button.action.primary {{ background:var(--ink); color:#fff; }}
  .ref-wrap img {{ width:100%; max-width:260px; border-radius:8px; border:1px solid #ece8df; }}
  .stats {{ font-size:12px; color:var(--muted); line-height:1.55; }}
  .stats strong {{ color:var(--ink); }}
  footer {{ padding:12px 24px; color:var(--muted); font-size:12px; text-align:center; }}
</style>
</head>
<body>
<header>
  <h1>Decoloriage v3 fidelite - <em>{title}</em></h1>
  <p>Cible ADULTE : max detail (partition adulte), solution = tons ERNIE d'origine (fidele). {style_note}</p>
</header>
<main>
  <section class="canvas-wrap" aria-label="Zone de coloriage">
    {svg_inline}
  </section>
  <aside>
    <div class="card">
      <h2>Palette libre</h2>
      <div class="palette" role="radiogroup">
        {palette_html}
      </div>
      <div class="picker-row">
        <label>Couleur libre</label>
        <input type="color" id="picker" value="#FF2E63">
      </div>
    </div>
    <div class="card actions">
      <h2>Actions</h2>
      <button class="action primary" id="btn-solution">Solution (tons d'origine fideles)</button>
      <button class="action" id="btn-reset">Tout effacer</button>
      <button class="action" id="btn-guides" aria-pressed="false">Guides : OFF</button>
    </div>
    <div class="card">
      <h2>Reference ERNIE</h2>
      <div class="ref-wrap">
        <img src="data:image/png;base64,{ref_b64}" alt="Image ERNIE d'origine">
      </div>
    </div>
    <div class="card stats">
      <strong>{n_regions}</strong> zones cliquables ({n_ink_regions} regions-encre)<br>
      <strong>{n_arcs}</strong> arcs frontieres ({n_ink} encre, {n_shading} fins)<br>
      Style : <strong>{style}</strong> &middot; strokes : {stroke_desc}<br>
      Mode couleur : <strong>fidele (hex d'origine)</strong>
    </div>
  </aside>
</main>
<footer>POC decoloriage v3 fidelite - {title}</footer>
<script>
(() => {{
  let selected = '#FF2E63';
  const swatches = document.querySelectorAll('.swatch');
  const picker = document.getElementById('picker');
  swatches.forEach(btn => {{
    btn.addEventListener('click', () => {{
      swatches.forEach(b => b.setAttribute('aria-pressed','false'));
      btn.setAttribute('aria-pressed','true');
      selected = btn.dataset.color;
      picker.value = selected;
    }});
  }});
  picker.addEventListener('input', () => {{
    selected = picker.value;
    swatches.forEach(b => b.setAttribute('aria-pressed','false'));
  }});
  document.querySelectorAll('.region').forEach(p => {{
    p.addEventListener('click', () => p.setAttribute('fill', selected));
  }});
  document.getElementById('btn-solution').addEventListener('click', () => {{
    document.querySelectorAll('.region').forEach(p => {{
      p.setAttribute('fill', p.dataset.color || '#ffffff');
    }});
  }});
  document.getElementById('btn-reset').addEventListener('click', () => {{
    document.querySelectorAll('.region').forEach(p => p.setAttribute('fill','#ffffff'));
  }});
  const guides = document.getElementById('btn-guides');
  guides.addEventListener('click', () => {{
    const wrap = document.querySelector('.canvas-wrap');
    const on = wrap.classList.toggle('show-guides');
    guides.setAttribute('aria-pressed', on ? 'true':'false');
    guides.textContent = on ? 'Guides : ON' : 'Guides : OFF';
  }});
}})();
</script>
</body>
</html>
"""

PALETTE_FREE = ["#FF2E63", "#FF8A2B", "#FFD60A", "#06D6A0",
                "#118AB2", "#8B5CF6", "#9B5E3C", "#222222"]


def build_html_v3(svg_inline, ref_png_path, title, style, n_regions, n_arcs,
                  n_ink, n_shading, n_ink_regions, stroke_desc, style_note):
    import base64
    palette_parts = []
    for i, hexc in enumerate(PALETTE_FREE):
        palette_parts.append(
            f'<button class="swatch" role="radio" '
            f'aria-pressed="{"true" if i == 0 else "false"}" '
            f'data-color="{hexc}" style="background:{hexc}" title="{hexc}"></button>'
        )
    palette_html = "\n        ".join(palette_parts)
    ref_b64 = base64.b64encode(ref_png_path.read_bytes()).decode("ascii")
    return HTML_TEMPLATE.format(
        title=title, svg_inline=svg_inline, palette_html=palette_html,
        ref_b64=ref_b64, n_regions=n_regions, n_arcs=n_arcs, n_ink=n_ink,
        n_shading=n_shading, n_ink_regions=n_ink_regions, style=style,
        stroke_desc=stroke_desc, style_note=style_note,
    )


# ----------------------------------------------------------------------------
# Rasterisation preview (blank + solution fidele) par style
# ----------------------------------------------------------------------------
def _hex_to_bgr(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


def process_one(style: str, subject: str, slot: int) -> dict:
    rid = f"{style}_{subject}"
    src = CORPUS_V3 / f"{rid}.png"
    rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    H, W = rgb.shape[:2]
    total_px = H * W
    t0 = time.time()

    # --- chromakey ---
    ck_mask = _detect_chromakey_mask(bgr, CHROMAKEY_RGB, CHROMAKEY_DELTA_E)
    pct_bg = round(100.0 * (ck_mask > 0).sum() / total_px, 2)

    # --- g2 : niveau ADULTE + enfant (pour comparaison n_regions) ---
    l25_path = WORK_DIR / f"{rid}_L25.png"
    result = process_image_3levels(rgb, out_lines=l25_path)
    rm_adulte = result["levels"]["adulte"]["region_map"].astype(np.int32)
    rm_enfant = result["levels"]["enfant"]["region_map"].astype(np.int32)
    n_regions_enfant_raw = int(len(np.unique(rm_enfant)))
    n_regions_adulte_raw = int(len(np.unique(rm_adulte)))

    # FIX 1 : fond chromakey -> region unique (museau preserve)
    rm_fixed, bg_label, n_subj = force_chromakey_background(rm_adulte, ck_mask)
    n_regions = int(len(np.unique(rm_fixed)))
    muzzle = muzzle_preserved(rm_fixed, bg_label, ck_mask)

    # line mask sans chromakey
    l25 = cv2.imread(str(l25_path), cv2.IMREAD_GRAYSCALE)
    l25[ck_mask > 0] = 0
    pct_ink_mask = round(100.0 * int((l25 > 0).sum()) / total_px, 2)

    # --- couleurs originales par region (depuis le PNG ERNIE) ---
    region_colors = compute_region_colors_from_original(rgb, rm_fixed)
    region_data: dict[int, dict] = {}
    for rid_int, c in region_colors.items():
        is_bg = (rid_int == bg_label)
        region_data[rid_int] = {
            "hex_original": c["hex"],
            "lab": c["lab"],
            "is_background": is_bg,
        }

    # --- masque encre dilate (pour ink-regions kawaii + classif arcs) ---
    kernel = np.ones((LINE_MASK_DILATE_PX, LINE_MASK_DILATE_PX), np.uint8)
    line_mask_dilated = cv2.dilate(l25, kernel, iterations=1)

    # ink-regions : SEULEMENT pour kawaii (low_poly = AUCUN noir)
    if style == "kawaii_bold":
        ink_region_ids, _ratios = compute_ink_regions(
            rm_fixed, line_mask_dilated, INK_REGION_OVERLAP_THRESHOLD,
        )
        # le fond ne doit jamais etre une region-encre
        ink_region_ids.discard(int(bg_label))
    else:
        ink_region_ids = set()

    # --- arcs topologiques + classif + smoothing ---
    arcs, _arc_stats = extract_topological_arcs(rm_fixed)
    n_ink = 0
    n_shading = 0
    arcs_classified: list[dict] = []
    for arc in arcs:
        if style == "low_poly":
            cls = "guide"  # tout en gris fin
        else:
            cls, _ratio = classify_arc_into_ink_or_shading(arc["points"], line_mask_dilated)
        smoothed = smooth_open_arc(arc["points"], DP_TOLERANCE, CHAIKIN_ITERS_ARC, H, W)
        arcs_classified.append({**arc, "class": cls, "smoothed": smoothed})
        if cls == "ink":
            n_ink += 1
        elif cls == "shading":
            n_shading += 1

    # --- fill polygons (G3) ---
    region_polys = extract_region_polygons(rm_fixed, DP_TOLERANCE, CHAIKIN_ITERS_REGION)

    # --- SVG fidele ---
    svg_text = build_faithful_svg(
        region_polys, region_data, arcs_classified, style, H, W,
        ink_region_ids=ink_region_ids,
    )
    svg_path = OUT_DIR / f"{slot:02d}_{rid}_g5.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    n_clickable = sum(
        1 for rid_int, d in region_data.items()
        if rid_int not in ink_region_ids and not d["is_background"]
    )

    # --- previews (blank + solution fidele) ---
    # ink pixel mask exact (kawaii)
    ink_pixel_mask = np.zeros((H, W), dtype=bool)
    for rid_int in ink_region_ids:
        ink_pixel_mask |= (rm_fixed == rid_int)

    blank_path = OUT_DIR / f"{slot:02d}_{rid}_g5_blank.png"
    sol_path = OUT_DIR / f"{slot:02d}_{rid}_g5_solution.png"
    _rasterize(region_polys, region_data, arcs_classified, style, H, W,
               ink_region_ids, ink_pixel_mask, blank_path, sol_path)

    import shutil
    shutil.copyfile(blank_path, OUT_DIR / f"{rid}_blank.png")
    shutil.copyfile(sol_path, OUT_DIR / f"{rid}_solution.png")

    # --- HTML ---
    if style == "low_poly":
        stroke_desc = f"guides gris {LOWPOLY_STROKE_HEX} {LOWPOLY_STROKE_PX:.0f}px (aucun noir)"
        style_note = "low_poly = facettes a contours gris fins, aucun trace noir."
        stroke_style = "gray1px"
    else:
        stroke_desc = f"noir {KAWAII_INK_HEX} {KAWAII_INK_PX:.0f}px (outline fin)"
        style_note = "kawaii = outline noir fin (~2px)."
        stroke_style = "black2px"

    html_text = build_html_v3(
        svg_inline=svg_text, ref_png_path=src,
        title=rid.replace("_", " ").title(), style=style,
        n_regions=n_clickable, n_arcs=len(arcs), n_ink=n_ink,
        n_shading=n_shading, n_ink_regions=len(ink_region_ids),
        stroke_desc=stroke_desc, style_note=style_note,
    )
    html_path = OUT_DIR / f"{slot:02d}_{rid}_g5.html"
    html_path.write_text(html_text, encoding="utf-8")

    elapsed = round(time.time() - t0, 2)
    print(
        f"[v3] {rid:22s} bg%={pct_bg:5.1f} adulte={n_regions_adulte_raw:4d} "
        f"enfant={n_regions_enfant_raw:4d} final={n_regions:4d} "
        f"clickable={n_clickable:4d} ink_reg={len(ink_region_ids):3d} "
        f"stroke={stroke_style:8s} museau={'OUI' if muzzle['preserved'] else 'NON'} "
        f"({elapsed}s)", flush=True,
    )

    return {
        "id": rid, "slot": slot, "style": style, "subject": subject,
        "image_size": [int(W), int(H)],
        "partition_level": PARTITION_LEVEL,
        "chromakey_bg_pct": pct_bg,
        "n_regions_adulte_raw": n_regions_adulte_raw,
        "n_regions_enfant_raw": n_regions_enfant_raw,
        "detail_gain_adulte_vs_enfant": n_regions_adulte_raw - n_regions_enfant_raw,
        "n_subject_regions": n_subj,
        "n_regions": n_regions,
        "n_clickable": n_clickable,
        "n_ink_regions": len(ink_region_ids),
        "n_arcs": len(arcs),
        "n_ink": n_ink,
        "n_shading": n_shading,
        "color_mode": "faithful",
        "stroke_style": stroke_style,
        "stroke_desc": stroke_desc,
        "pct_ink_mask": pct_ink_mask,
        "muzzle_preserved": muzzle,
        "blank_png": f"s3_out_v3/{rid}_blank.png",
        "solution_png": f"s3_out_v3/{rid}_solution.png",
        "svg": f"s3_out_v3/{slot:02d}_{rid}_g5.svg",
        "html": f"s3_out_v3/{slot:02d}_{rid}_g5.html",
        "timing_s": elapsed,
    }


def _rasterize(region_polys, region_data, arcs_classified, style, H, W,
               ink_region_ids, ink_pixel_mask, blank_path, sol_path):
    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))
    guide_bgr = _hex_to_bgr(LOWPOLY_STROKE_HEX)
    ink_bgr = _hex_to_bgr(KAWAII_INK_HEX)
    ink_region_bgr = np.array(_hex_to_bgr(KAWAII_INK_HEX), dtype=np.uint8)
    ink_int = max(1, int(round(KAWAII_INK_PX)))
    guide_int = max(1, int(round(LOWPOLY_STROKE_PX)))

    def draw_strokes(canvas):
        if style == "low_poly":
            for arc in arcs_classified:
                poly = arc["smoothed"]
                if len(poly) < 2:
                    continue
                pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
                cv2.polylines(canvas, [pts], False, guide_bgr, guide_int, lineType=cv2.LINE_AA)
        else:
            canvas[ink_pixel_mask] = ink_region_bgr
            for arc in arcs_classified:
                if arc["class"] != "ink":
                    continue
                poly = arc["smoothed"]
                if len(poly) < 2:
                    continue
                pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
                cv2.polylines(canvas, [pts], False, ink_bgr, ink_int, lineType=cv2.LINE_AA)

    # solution fidele
    sol = np.full((H, W, 3), 255, dtype=np.uint8)
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


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    per_image: list[dict] = []
    failures: list[dict] = []
    t_start = time.time()

    slot = 0
    for style in STYLES:
        for subject in SUBJECTS:
            slot += 1
            rid = f"{style}_{subject}"
            if not (CORPUS_V3 / f"{rid}.png").exists():
                failures.append({"id": rid, "reason": "PNG absent"})
                continue
            # retry <=2/image
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

    # HTML dog raccourci par style
    import shutil
    for row in per_image:
        if row["subject"] != "dog":
            continue
        g5_html = OUT_DIR / f"{row['slot']:02d}_{row['id']}_g5.html"
        if g5_html.exists():
            shutil.copyfile(g5_html, OUT_DIR / f"{row['style']}_dog.html")

    out = {
        "gate": "S3-v3-fidelite",
        "corpus": "corpus_v3 (low_poly + kawaii_bold, chromakey green, detail+) x 3 sujets",
        "target": "ADULTE : max detail, aucune simplification, fidelite couleurs",
        "design": {
            "partition_level": PARTITION_LEVEL,
            "color_mode": "faithful (data-color = hex moyen d'origine ERNIE)",
            "low_poly_stroke": f"{LOWPOLY_STROKE_HEX} {LOWPOLY_STROKE_PX}px, AUCUN noir, aucune region-encre",
            "kawaii_stroke": f"noir {KAWAII_INK_HEX} {KAWAII_INK_PX}px outline fin",
            "chromakey": {"rgb": list(CHROMAKEY_RGB), "delta_e": CHROMAKEY_DELTA_E},
        },
        "poc_reused": [
            "poc/decoloriage/g2_partition.py (process_image_3levels, niveau adulte)",
            "poc/decoloriage/g3_vectorize.py (extract_region_polygons, _signed_area)",
            "poc/decoloriage/g4_two_weight.py (arcs, classify, smooth, thickness)",
            "poc/decoloriage/g5_product.py (compute_region_colors_from_original, compute_ink_regions)",
            "src/services/extract_palette.py (_detect_chromakey_mask)",
        ],
        "n_processed": len(per_image),
        "n_failed": len(failures),
        "failures": failures,
        "images": per_image,
        "timing_s_total": round(time.time() - t_start, 2),
    }
    stats_path = OUT_DIR / "v3_stats.json"
    stats_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK v3_stats : {stats_path}")
    print(f"   {len(per_image)}/6 traitees, {len(failures)} echec(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
