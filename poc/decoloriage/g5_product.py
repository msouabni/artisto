"""G5 - Bout en bout produit : SVG bicouche click-to-fill + 6 crayons.

Cible : une seule image (pastel_dog par defaut), SVG bicouche :
  - couche fills : un <path> par region, fill initial blanc, data-color = crayon
    le plus proche en distance Lab (parmi les 6 crayons design system),
    data-original = couleur moyenne du PNG original
  - couche strokes : arcs topologiques G4 (encre + shading, 2 poids,
    chaque frontiere dessinee UNE fois)

+ HTML standalone embarquant le SVG inline avec :
  - palette 6 crayons (Cerise, Mandarine, Citron, Menthe, Ocean, Prune)
  - click sur region -> fill avec la couleur selectionnee
  - bouton "Solution" -> applique data-color a toutes les regions
  - bouton "Reset" -> retour au blanc
  - mini vignette ERNIE d'origine en reference

Critere pass G5 :
  1. tap -> fill correct sur 100 % des zones (chaque <path> reagit au click)
  2. mode "solution" ressemble a l'image ERNIE d'origine (vignette cote a cote)
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from skimage.color import rgb2lab

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from g3_vectorize import extract_region_polygons, _signed_area  # noqa: E402
from g4_two_weight import (  # noqa: E402
    extract_topological_arcs,
    classify_arc_into_ink_or_shading,
    measure_line_thickness,
    smooth_open_arc,
    INK_OVERLAP_THRESHOLD,
    LINE_MASK_DILATE_PX,
    DP_TOLERANCE,
    CHAIKIN_ITERS_ARC,
    CHAIKIN_ITERS_REGION,
    SHADING_RATIO,
)

DEFAULT_CORPUS = Path(__file__).parent / "corpus.json"
DEFAULT_G2_STATS = Path(__file__).parent / "g2_out" / "stats.json"
DEFAULT_OUT_DIR = Path(__file__).parent / "g5_out"
DEFAULT_SLOT = 1  # pastel_dog
DEFAULT_LEVEL = "enfant"

# Pivot G5 2026-06-10 : seuil au-dessus duquel une region est consideree comme
# region-encre (= partie du trait ERNIE segmente en region par k-means). On
# mesure le ratio des pixels de la region qui tombent dans le masque G2
# dilate. Les regions encre sont remplies #111111 plein, non cliquables,
# exclues du compteur de zones.
INK_REGION_OVERLAP_THRESHOLD = 0.50
INK_REGION_FILL = "#111111"

# Crayons du design system Alwan Books (skill spec G5)
CRAYONS = [
    {"name": "Cerise",    "hex": "#FF2E63"},
    {"name": "Mandarine", "hex": "#FF8A2B"},
    {"name": "Citron",    "hex": "#FFD60A"},
    {"name": "Menthe",    "hex": "#06D6A0"},
    {"name": "Ocean",     "hex": "#118AB2"},
    {"name": "Prune",     "hex": "#8B5CF6"},
]

# Au-dessus de ce L*, on considere la region comme "papier" et on garde blanc
# en mode solution (sinon le fond du dog se peindrait en pale crayon).
BACKGROUND_L_THRESHOLD = 92.0


# ----------------------------------------------------------------------------
# Mapping couleur -> crayon le plus proche (Lab distance)
# ----------------------------------------------------------------------------
def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_lab_single(rgb: tuple[int, int, int]) -> np.ndarray:
    arr = np.array([[list(rgb)]], dtype=np.uint8)
    lab = rgb2lab(arr / 255.0)
    return lab[0, 0]  # (L, a, b)


def build_crayons_lab() -> list[dict]:
    out = []
    for c in CRAYONS:
        lab = _rgb_to_lab_single(_hex_to_rgb(c["hex"]))
        out.append({**c, "lab": tuple(float(v) for v in lab)})
    return out


def nearest_crayon(region_lab: tuple[float, float, float],
                   crayons_lab: list[dict]) -> dict:
    """Retourne le crayon le plus proche en distance Lab Euclidienne (DeltaE76)."""
    rl = np.array(region_lab, dtype=np.float64)
    best = None
    best_d = float("inf")
    for c in crayons_lab:
        cl = np.array(c["lab"], dtype=np.float64)
        d = float(np.linalg.norm(rl - cl))
        if d < best_d:
            best_d = d
            best = c
    return {**best, "delta_e": round(best_d, 2)}


# ----------------------------------------------------------------------------
# SVG bicouche click-to-fill
# ----------------------------------------------------------------------------
def compute_ink_regions(
    region_map: np.ndarray,
    line_mask_dilated: np.ndarray,
    threshold: float = INK_REGION_OVERLAP_THRESHOLD,
) -> tuple[set[int], dict[int, float]]:
    """Pour chaque region : ratio des pixels qui tombent dans le masque de
    traits G2 dilate. Si >= threshold, la region est consideree comme
    "region-encre" (= partie du trait ERNIE segmentee en region par k-means).
    Retourne (set des rid, dict rid -> ratio)."""
    H, W = region_map.shape
    ink_mask = line_mask_dilated > 0
    ids = np.unique(region_map).tolist()
    ratios: dict[int, float] = {}
    ink_ids: set[int] = set()
    for rid in ids:
        mask = region_map == rid
        n_pix = int(mask.sum())
        if n_pix == 0:
            continue
        n_overlap = int((mask & ink_mask).sum())
        ratio = n_overlap / n_pix
        ratios[int(rid)] = round(ratio, 3)
        if ratio >= threshold:
            ink_ids.add(int(rid))
    return ink_ids, ratios


def build_g5_svg(
    region_polys: list[tuple[int, list[np.ndarray]]],
    region_data: dict[int, dict],  # rid -> {hex_original, lab, crayon_hex, crayon_name, delta_e, is_background}
    arcs_classified: list[dict],
    ink_w: float,
    shading_w: float,
    H: int,
    W: int,
    ink_region_ids: set[int] | None = None,
) -> str:
    """Genere un SVG bicouche click-to-fill.

    Pivot 2026-06-10 :
    - Les regions identifiees comme "encre" (overlap avec masque G2 dilate) =
      fill #111111 plein, pointer-events:none, pas de data-color, exclues du
      compteur de zones cliquables. Resoud le bug "trait creux coloriable".
    - Les arcs "shading" portent class="arc-shading". CSS leur applique
      stroke:none par defaut, sauf si la SVG/wrapper porte la classe
      .show-guides (toggle "Guides" du HTML).
    - Les arcs "ink" sont inchanges (stroke noir epais).
    """
    if ink_region_ids is None:
        ink_region_ids = set()
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'shape-rendering="geometricPrecision">'
    ]
    lines.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

    # ---- Fill layer : un path par region (toutes les sous-polylines fusionnees
    # avec fill-rule:evenodd via d composite, pour qu'un seul click cible toute
    # la region) ----
    lines.append('<g id="fills" stroke="none" fill-rule="evenodd">')

    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))

    for rid, polys in sorted_polys:
        # Construire le `d` composite (une seule path pour toutes les sous-poly)
        d_parts: list[str] = []
        for poly in polys:
            d_parts.append(f"M{poly[0][1]:.2f},{poly[0][0]:.2f}")
            for p in poly[1:]:
                d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
            d_parts.append("Z")
        d_attr = " ".join(d_parts)

        if rid in ink_region_ids:
            # Region-encre : noir plein, non cliquable, pas de data-color.
            lines.append(
                f'<path class="ink-region" '
                f'data-region-id="{rid}" '
                f'fill="{INK_REGION_FILL}" '
                f'pointer-events="none" '
                f'd="{d_attr}"/>'
            )
            continue

        data = region_data.get(rid)
        if data is None:
            continue
        bg_class = " region-bg" if data["is_background"] else ""
        lines.append(
            f'<path class="region{bg_class}" '
            f'data-region-id="{rid}" '
            f'data-color="{data["crayon_hex"]}" '
            f'data-original="{data["hex_original"]}" '
            f'data-crayon-name="{data["crayon_name"]}" '
            f'data-delta-e="{data["delta_e"]}" '
            f'fill="#ffffff" '
            f'd="{d_attr}"/>'
        )
    lines.append("</g>")

    # ---- Stroke layer ----
    # Ink arcs : noir epais, toujours visibles. Shading arcs : class="arc-shading"
    # pour permettre au CSS de les masquer par defaut + les reveler via
    # .show-guides .arc-shading.
    lines.append(
        f'<g id="strokes" fill="none" stroke="#15151B" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'pointer-events="none">'
    )
    for arc in arcs_classified:
        poly = arc["smoothed"]
        if len(poly) < 2:
            continue
        cls = arc["class"]
        sw = ink_w if cls == "ink" else shading_w
        d_parts = [f"M{poly[0][1]:.2f},{poly[0][0]:.2f}"]
        for p in poly[1:]:
            d_parts.append(f"L{p[1]:.2f},{p[0]:.2f}")
        cls_attr = ' class="arc-ink"' if cls == "ink" else ' class="arc-shading"'
        lines.append(
            f'<path{cls_attr} d="{" ".join(d_parts)}" stroke-width="{sw:.2f}"/>'
        )
    lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# HTML standalone (palette + JS click-to-fill + solution + reset)
# ----------------------------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>G5 - Decoloriage click-to-fill - {title}</title>
<style>
  :root {{
    --bg: #fdfbf6;
    --paper: #ffffff;
    --ink: #15151b;
    --muted: #6b6b78;
    --shadow: 0 6px 24px rgba(0,0,0,0.08);
    --gap: 14px;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: var(--ink);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  header {{
    padding: 18px 24px;
    border-bottom: 1px solid #ece8df;
    background: #fff;
  }}
  header h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
  header p {{ margin: 4px 0 0; color: var(--muted); font-size: 13px; }}
  main {{
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 280px;
    gap: 18px;
    padding: 18px 24px;
    max-width: 1400px;
    margin: 0 auto;
    width: 100%;
  }}
  .canvas-wrap {{
    background: var(--paper);
    border-radius: 16px;
    padding: 18px;
    box-shadow: var(--shadow);
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 600px;
  }}
  .canvas-wrap svg {{
    width: 100%;
    height: auto;
    max-height: 80vh;
    display: block;
  }}
  .region {{ cursor: pointer; transition: fill 0.08s ease; }}
  .region:hover {{ filter: brightness(0.97); }}
  .region.region-bg {{ cursor: pointer; }}
  /* Pivot G5 2026-06-10 : shading arcs masques par defaut, reveles
     via le toggle "Guides" (.show-guides sur le canvas). */
  .arc-shading {{ stroke: none; }}
  .show-guides .arc-shading {{ stroke: #DDDDDD; stroke-width: 1; }}
  aside {{
    display: flex;
    flex-direction: column;
    gap: var(--gap);
  }}
  .card {{
    background: var(--paper);
    border-radius: 12px;
    padding: 14px;
    box-shadow: var(--shadow);
  }}
  .card h2 {{ margin: 0 0 10px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
  .palette {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
  .crayon {{
    aspect-ratio: 1.6 / 1;
    border-radius: 10px;
    border: 3px solid transparent;
    cursor: pointer;
    position: relative;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    padding-bottom: 6px;
    font-size: 11px;
    font-weight: 600;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.35);
    transition: transform 0.1s ease;
  }}
  .crayon[aria-pressed="true"] {{ border-color: var(--ink); transform: translateY(-2px); }}
  .crayon:hover {{ transform: translateY(-2px); }}
  .actions {{ display: flex; flex-direction: column; gap: 8px; }}
  button.action {{
    appearance: none;
    border: 1.5px solid var(--ink);
    background: #fff;
    color: var(--ink);
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }}
  button.action:hover {{ background: #f5f1e6; }}
  button.action.primary {{ background: var(--ink); color: #fff; }}
  button.action.primary:hover {{ background: #2a2a35; }}
  .ref-wrap {{ display: flex; align-items: center; gap: 10px; }}
  .ref-wrap img {{ width: 100%; max-width: 240px; border-radius: 8px; border: 1px solid #ece8df; }}
  .stats {{ font-size: 12px; color: var(--muted); line-height: 1.55; }}
  .stats strong {{ color: var(--ink); }}
  footer {{ padding: 12px 24px; color: var(--muted); font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>Decoloriage POC G5 - <em>{title}</em></h1>
  <p>Cible : tap pour remplir, palette 6 crayons design system, mode solution = couleurs ERNIE quantifiees.</p>
</header>
<main>
  <section class="canvas-wrap" aria-label="Zone de coloriage">
    {svg_inline}
  </section>
  <aside>
    <div class="card">
      <h2>Palette - 6 crayons</h2>
      <div class="palette" role="radiogroup" aria-label="Choix de la couleur">
        {palette_html}
      </div>
    </div>
    <div class="card actions">
      <h2>Actions</h2>
      <button class="action primary" id="btn-solution">Solution (couleurs ERNIE quantifiees)</button>
      <button class="action" id="btn-reset">Tout effacer</button>
      <button class="action" id="btn-guides" aria-pressed="false">Guides shading : OFF</button>
    </div>
    <div class="card">
      <h2>Reference ERNIE</h2>
      <div class="ref-wrap">
        <img src="data:image/png;base64,{ref_b64}" alt="Image ERNIE pastel d'origine">
      </div>
    </div>
    <div class="card stats">
      <strong>{n_regions}</strong> zones cliquables ({n_ink_regions} regions-encre exclues)<br>
      <strong>{n_arcs}</strong> arcs frontieres ({n_ink} encre visibles, {n_shading} shading masques)<br>
      Stroke encre {ink_w:.1f} px / shading {shading_w:.1f} px (toggle Guides)<br>
      Distribution crayons (mode solution) :<br>
      {crayon_distribution}
    </div>
  </aside>
</main>
<footer>POC decoloriage G5 - 2026-06-10 - {title}</footer>
<script>
(() => {{
  let selected = '#FF2E63';
  const crayons = document.querySelectorAll('.crayon');
  crayons.forEach(btn => {{
    btn.addEventListener('click', () => {{
      crayons.forEach(b => b.setAttribute('aria-pressed', 'false'));
      btn.setAttribute('aria-pressed', 'true');
      selected = btn.dataset.color;
    }});
  }});
  document.querySelectorAll('.region').forEach(p => {{
    p.addEventListener('click', () => {{
      p.setAttribute('fill', selected);
    }});
  }});
  document.getElementById('btn-solution').addEventListener('click', () => {{
    document.querySelectorAll('.region').forEach(p => {{
      const target = p.dataset.color || '#ffffff';
      p.setAttribute('fill', target);
    }});
  }});
  document.getElementById('btn-reset').addEventListener('click', () => {{
    document.querySelectorAll('.region').forEach(p => {{
      p.setAttribute('fill', '#ffffff');
    }});
  }});
  // Toggle Guides shading
  const guides = document.getElementById('btn-guides');
  guides.addEventListener('click', () => {{
    const wrap = document.querySelector('.canvas-wrap');
    const on = wrap.classList.toggle('show-guides');
    guides.setAttribute('aria-pressed', on ? 'true' : 'false');
    guides.textContent = on ? 'Guides shading : ON' : 'Guides shading : OFF';
  }});
}})();
</script>
</body>
</html>
"""


def build_html(
    svg_inline: str,
    crayons_used: dict[str, int],
    ref_png_path: Path,
    title: str,
    n_regions: int,
    n_arcs: int,
    n_ink: int,
    n_shading: int,
    ink_w: float,
    shading_w: float,
    n_ink_regions: int = 0,
) -> str:
    palette_html_parts = []
    for c in CRAYONS:
        palette_html_parts.append(
            f'<button class="crayon" role="radio" '
            f'aria-pressed="{"true" if c["hex"] == "#FF2E63" else "false"}" '
            f'data-color="{c["hex"]}" '
            f'style="background:{c["hex"]}" '
            f'title="{c["name"]}">{c["name"]}</button>'
        )
    palette_html = "\n        ".join(palette_html_parts)

    # Crayon distribution lines
    distr_lines = []
    for c in CRAYONS:
        cnt = crayons_used.get(c["hex"], 0)
        distr_lines.append(
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
            f'background:{c["hex"]};margin-right:4px;vertical-align:middle"></span>'
            f'{c["name"]} : {cnt}'
        )
    # background regions
    distr_lines.append(
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
        f'background:#ffffff;border:1px solid #ccc;margin-right:4px;vertical-align:middle"></span>'
        f'Papier (fond) : {crayons_used.get("#ffffff", 0)}'
    )
    crayon_distribution = "<br>".join(distr_lines)

    ref_bytes = ref_png_path.read_bytes()
    ref_b64 = base64.b64encode(ref_bytes).decode("ascii")

    return HTML_TEMPLATE.format(
        title=title,
        svg_inline=svg_inline,
        palette_html=palette_html,
        ref_b64=ref_b64,
        n_regions=n_regions,
        n_arcs=n_arcs,
        n_ink=n_ink,
        n_shading=n_shading,
        ink_w=ink_w,
        shading_w=shading_w,
        n_ink_regions=n_ink_regions,
        crayon_distribution=crayon_distribution,
    )


# ----------------------------------------------------------------------------
# Per-region original color extraction (depuis le PNG ERNIE)
# Reimplemente ici pour ne pas dependre du module G2 directement.
# ----------------------------------------------------------------------------
def compute_region_colors_from_original(
    original_rgb: np.ndarray, region_map: np.ndarray,
) -> dict[int, dict]:
    """Pour chaque region, calcule la couleur moyenne (Lab + hex) sur le PNG
    original. Retourne {rid : {lab, hex}}."""
    H, W = region_map.shape
    out: dict[int, dict] = {}
    ids = np.unique(region_map).tolist()
    rgb_norm = original_rgb.astype(np.float64) / 255.0
    lab_full = rgb2lab(rgb_norm)
    for rid in ids:
        mask = region_map == rid
        if not mask.any():
            continue
        lab_mean = lab_full[mask].mean(axis=0)
        # Reconvert Lab -> RGB pour hex
        lab_arr = np.array([[list(lab_mean)]], dtype=np.float64)
        from skimage.color import lab2rgb
        rgb_back = lab2rgb(lab_arr)
        r, g, b = (np.clip(rgb_back[0, 0] * 255.0, 0, 255)).astype(np.uint8).tolist()
        hex_str = f"#{r:02X}{g:02X}{b:02X}"
        out[int(rid)] = {
            "lab": tuple(float(v) for v in lab_mean),
            "hex": hex_str,
        }
    return out


# ----------------------------------------------------------------------------
# Pipeline G5 par image (single shot)
# ----------------------------------------------------------------------------
def process_image_g5(
    slot: int,
    rid: str,
    original_png_path: Path,
    region_map_path: Path,
    line_mask_path: Path,
    out_dir: Path,
    dp_tol: float = DP_TOLERANCE,
    chaikin_iters_arc: int = CHAIKIN_ITERS_ARC,
    chaikin_iters_region: int = CHAIKIN_ITERS_REGION,
) -> dict:
    t_total = time.time()

    rm = np.load(region_map_path).astype(np.int32)
    H, W = rm.shape

    # Charger l'original (BGR par cv2)
    orig_bgr = cv2.imread(str(original_png_path), cv2.IMREAD_COLOR)
    if orig_bgr is None:
        raise FileNotFoundError(f"Original PNG missing : {original_png_path}")
    orig_rgb = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2RGB)
    if orig_rgb.shape[:2] != (H, W):
        orig_rgb = cv2.resize(orig_rgb, (W, H), interpolation=cv2.INTER_AREA)

    # Couleurs originales par region
    print(f"    > computing per-region colors from original...", flush=True)
    region_colors = compute_region_colors_from_original(orig_rgb, rm)

    # Mapping vers crayons
    print(f"    > mapping {len(region_colors)} regions to 6 crayons...", flush=True)
    crayons_lab = build_crayons_lab()
    region_data: dict[int, dict] = {}
    crayons_used: dict[str, int] = {}
    for rid_int, c in region_colors.items():
        is_bg = c["lab"][0] >= BACKGROUND_L_THRESHOLD
        if is_bg:
            crayon_hex = "#ffffff"
            crayon_name = "Papier"
            delta_e = 0.0
        else:
            crayon = nearest_crayon(c["lab"], crayons_lab)
            crayon_hex = crayon["hex"]
            crayon_name = crayon["name"]
            delta_e = crayon["delta_e"]
        region_data[rid_int] = {
            "hex_original": c["hex"],
            "lab": c["lab"],
            "crayon_hex": crayon_hex,
            "crayon_name": crayon_name,
            "delta_e": delta_e,
            "is_background": is_bg,
        }
        crayons_used[crayon_hex] = crayons_used.get(crayon_hex, 0) + 1

    # Line mask + epaisseur trait
    line_mask = cv2.imread(str(line_mask_path), cv2.IMREAD_GRAYSCALE)
    if line_mask is None:
        raise FileNotFoundError(f"Line mask missing : {line_mask_path}")
    print(f"    > measuring line thickness + dilating mask...", flush=True)
    median_thickness = measure_line_thickness(line_mask)
    ink_w = max(2.0, median_thickness)
    shading_w = max(1.0, ink_w * SHADING_RATIO)
    kernel = np.ones((LINE_MASK_DILATE_PX, LINE_MASK_DILATE_PX), np.uint8)
    line_mask_dilated = cv2.dilate(line_mask, kernel, iterations=1)

    # Arcs topologiques (G4)
    print(f"    > extracting topological arcs...", flush=True)
    arcs, arc_stats = extract_topological_arcs(rm)
    print(f"    > classifying {len(arcs)} arcs ink/shading + smoothing...", flush=True)
    n_ink = 0
    n_shading = 0
    arcs_classified: list[dict] = []
    for arc in arcs:
        cls, ratio = classify_arc_into_ink_or_shading(arc["points"], line_mask_dilated)
        smoothed = smooth_open_arc(arc["points"], dp_tol, chaikin_iters_arc, H, W)
        arcs_classified.append({**arc, "class": cls, "smoothed": smoothed})
        if cls == "ink":
            n_ink += 1
        else:
            n_shading += 1

    # Detection regions-encre (= trait ERNIE segmente en region)
    print(f"    > detecting ink regions (overlap >= "
          f"{int(INK_REGION_OVERLAP_THRESHOLD*100)}% with dilated trait mask)...",
          flush=True)
    ink_region_ids, ink_overlap_ratios = compute_ink_regions(
        rm, line_mask_dilated, INK_REGION_OVERLAP_THRESHOLD,
    )
    # Exclure les regions-encre du compteur de zones cliquables et du
    # decompte crayons (elles seront rendues noir plein).
    for rid_int in ink_region_ids:
        if rid_int in region_data:
            data = region_data[rid_int]
            crayons_used[data["crayon_hex"]] = max(
                0, crayons_used.get(data["crayon_hex"], 0) - 1,
            )

    # Fill polygons (G3)
    print(f"    > extracting fill polygons...", flush=True)
    region_polys = extract_region_polygons(rm, dp_tol, chaikin_iters_region)

    # SVG G5
    print(f"    > building SVG (ink regions: {len(ink_region_ids)}, "
          f"clickable regions: {len(region_data) - len(ink_region_ids)})...",
          flush=True)
    svg_text = build_g5_svg(
        region_polys, region_data, arcs_classified, ink_w, shading_w, H, W,
        ink_region_ids=ink_region_ids,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / f"{slot:02d}_{rid}_g5.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    n_clickable_regions = len(region_data) - len(ink_region_ids)

    # HTML standalone
    print(f"    > building HTML standalone...", flush=True)
    title = rid.replace("_", " ").replace("pastel ", "").title()
    html_text = build_html(
        svg_inline=svg_text,
        crayons_used=crayons_used,
        ref_png_path=original_png_path,
        title=title,
        n_regions=n_clickable_regions,
        n_arcs=len(arcs),
        n_ink=n_ink,
        n_shading=n_shading,
        ink_w=ink_w,
        shading_w=shading_w,
        n_ink_regions=len(ink_region_ids),
    )
    html_path = out_dir / f"{slot:02d}_{rid}_g5.html"
    html_path.write_text(html_text, encoding="utf-8")

    # Helpers couleur
    def hex_to_bgr(hex_str: str) -> tuple[int, int, int]:
        h = hex_str.lstrip("#")
        return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))

    ink_region_bgr = hex_to_bgr(INK_REGION_FILL)
    ink_region_bgr_arr = np.array(ink_region_bgr, dtype=np.uint8)
    ink_int = max(1, int(round(ink_w)))
    stroke_bgr = (27, 21, 21)

    # Masque pixel-perfect des ink-regions (pour rasterisation correcte).
    # On NE peut pas s'appuyer sur cv2.fillPoly par sous-poly : il ne respecte
    # pas le fill-rule even-odd, donc les trous (regions colorees vues depuis
    # la region-trait annulaire) se remplissent aussi en noir. Le SVG est
    # correct (fill-rule="evenodd" sur <g id="fills">), mais le PNG preview
    # doit utiliser le masque pixel directement.
    ink_pixel_mask = np.zeros((H, W), dtype=bool)
    for rid_int in ink_region_ids:
        ink_pixel_mask |= (rm == rid_int)

    # Solution rasterisee (preview du mode solution)
    # - regions normales -> fill crayon mappe (par polygones smoothed)
    # - ink-regions -> ecrasees au masque pixel-perfect (= silhouette du trait)
    # - arcs ink -> stroke noir epais (par-dessus, lisse les bords du masque)
    # - arcs shading -> NE PAS rendre (alignement avec defaut HTML)
    sol_rendered = np.full((H, W, 3), 255, dtype=np.uint8)
    def total_area(polys):
        return sum(abs(_signed_area(p)) for p in polys)
    sorted_polys = sorted(region_polys, key=lambda x: -total_area(x[1]))
    for rid_int, polys in sorted_polys:
        if rid_int in ink_region_ids:
            continue  # gere apres via masque pixel
        data = region_data.get(rid_int)
        if data is None:
            continue
        bgr = hex_to_bgr(data["crayon_hex"])
        for poly in polys:
            pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(sol_rendered, [pts], bgr)
    # Ink-regions par-dessus, masque pixel-perfect (annulaire si trait fin)
    sol_rendered[ink_pixel_mask] = ink_region_bgr_arr
    # Arcs ink en stroke noir, lisse les bords du masque
    for arc in arcs_classified:
        if arc["class"] != "ink":
            continue
        poly = arc["smoothed"]
        if len(poly) < 2:
            continue
        pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(sol_rendered, [pts], False, stroke_bgr, ink_int, lineType=cv2.LINE_AA)
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_g5_solution.png"), sol_rendered)

    # Blank rasterise (preview du depart) - pivot G5 :
    # - tout blanc, puis ink-regions = noir au masque pixel-perfect
    # - arcs ink = noir epais (par-dessus, lisse les bords)
    # - arcs shading = NE PAS rendre (alignement avec defaut HTML)
    blank_rendered = np.full((H, W, 3), 255, dtype=np.uint8)
    blank_rendered[ink_pixel_mask] = ink_region_bgr_arr
    for arc in arcs_classified:
        if arc["class"] != "ink":
            continue
        poly = arc["smoothed"]
        if len(poly) < 2:
            continue
        pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(blank_rendered, [pts], False, stroke_bgr, ink_int, lineType=cv2.LINE_AA)
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_g5_blank.png"), blank_rendered)

    # Variante "print" (backlog b8) : blank + guides shading reactives en clair
    # (utile pour impression papier coloriage adulte).
    print_rendered = blank_rendered.copy()
    guides_bgr = (221, 221, 221)
    for arc in arcs_classified:
        if arc["class"] != "shading":
            continue
        poly = arc["smoothed"]
        if len(poly) < 2:
            continue
        pts = poly[:, [1, 0]].astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(print_rendered, [pts], False, guides_bgr, 1, lineType=cv2.LINE_AA)
    cv2.imwrite(str(out_dir / f"{slot:02d}_{rid}_g5_print.png"), print_rendered)

    elapsed = time.time() - t_total

    return {
        "slot": slot,
        "id": rid,
        "image_size": [int(W), int(H)],
        "n_regions_total": len(region_data),
        "n_regions": n_clickable_regions,
        "n_ink_regions": len(ink_region_ids),
        "ink_region_ids": sorted(int(r) for r in ink_region_ids),
        "n_arcs": len(arcs),
        "n_ink": n_ink,
        "n_shading": n_shading,
        "ink_stroke_width": round(ink_w, 2),
        "shading_stroke_width": round(shading_w, 2),
        "crayons_used": crayons_used,
        "outputs": {
            "svg": str(svg_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "html": str(html_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "solution_png": str((out_dir / f"{slot:02d}_{rid}_g5_solution.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "blank_png": str((out_dir / f"{slot:02d}_{rid}_g5_blank.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "print_png": str((out_dir / f"{slot:02d}_{rid}_g5_print.png").relative_to(PROJECT_ROOT)).replace("\\", "/"),
        },
        "regions_detail": [
            {
                "id": rid_int,
                "hex_original": d["hex_original"],
                "lab": [round(v, 2) for v in d["lab"]],
                "crayon_name": d["crayon_name"],
                "crayon_hex": d["crayon_hex"],
                "delta_e": d["delta_e"],
                "is_background": d["is_background"],
                "is_ink_region": rid_int in ink_region_ids,
                "ink_overlap_ratio": ink_overlap_ratios.get(rid_int, 0.0),
            }
            for rid_int, d in sorted(region_data.items())
        ],
        "timing_s": round(elapsed, 2),
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--g2-stats", type=Path, default=DEFAULT_G2_STATS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--slot", type=int, default=DEFAULT_SLOT,
                        help="Slot du corpus (defaut 1 = pastel_dog)")
    parser.add_argument("--level", type=str, default=DEFAULT_LEVEL,
                        choices=["tout_petit", "enfant", "adulte"])
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    g2 = json.loads(args.g2_stats.read_text(encoding="utf-8"))

    # Trouver l'image cible dans le corpus
    item = next((i for i in corpus["images"] if i["slot"] == args.slot), None)
    if item is None:
        print(f"[ERR] slot {args.slot} introuvable dans le corpus", file=sys.stderr)
        return 1
    rid = item["id"]
    original_path = (PROJECT_ROOT / item["path"]).resolve()
    if not original_path.exists():
        print(f"[ERR] PNG original absent : {original_path}", file=sys.stderr)
        return 1

    # G2 region_map pour le niveau choisi
    g2_entry = next(
        (s for s in g2["images"]
         if s["slot"] == args.slot and s["level"] == args.level),
        None,
    )
    if g2_entry is None:
        print(f"[ERR] G2 entry manquante slot={args.slot} level={args.level}", file=sys.stderr)
        return 1
    rm_npy = (PROJECT_ROOT / g2_entry["out_npy"]).resolve()
    if not rm_npy.exists():
        print(f"[ERR] region_map.npy absent : {rm_npy}", file=sys.stderr)
        return 1

    # Line mask
    line_entry = g2.get("lines", {}).get(rid)
    if line_entry is None:
        print(f"[ERR] line mask manquant pour {rid}", file=sys.stderr)
        return 1
    line_mask_path = (PROJECT_ROOT / line_entry["path"]).resolve()
    if not line_mask_path.exists():
        print(f"[ERR] line mask absent : {line_mask_path}", file=sys.stderr)
        return 1

    print(f"[G5] #{args.slot:02d} {rid} (niveau {args.level})", flush=True)
    print(f"     original   : {original_path}", flush=True)
    print(f"     region_map : {rm_npy}", flush=True)
    print(f"     line mask  : {line_mask_path}", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    stats = process_image_g5(
        slot=args.slot,
        rid=rid,
        original_png_path=original_path,
        region_map_path=rm_npy,
        line_mask_path=line_mask_path,
        out_dir=args.out,
    )
    stats["category"] = item["category"]
    stats["level"] = args.level

    # Stats consolidees
    out_stats = {
        "params": {
            "background_L_threshold": BACKGROUND_L_THRESHOLD,
            "ink_overlap_threshold": INK_OVERLAP_THRESHOLD,
            "line_mask_dilate_px": LINE_MASK_DILATE_PX,
            "dp_tolerance": DP_TOLERANCE,
            "chaikin_iters_arc": CHAIKIN_ITERS_ARC,
            "chaikin_iters_region": CHAIKIN_ITERS_REGION,
            "shading_ratio_of_ink": SHADING_RATIO,
        },
        "crayons": [{"name": c["name"], "hex": c["hex"]} for c in CRAYONS],
        "image": stats,
    }
    stats_path = args.out / "stats.json"
    stats_path.write_text(json.dumps(out_stats, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[G5 OK] {stats['n_regions']} zones cliquables, {stats['n_arcs']} arcs "
          f"({stats['n_ink']} encre / {stats['n_shading']} shading)")
    print(f"        Stroke encre {stats['ink_stroke_width']} px / shading "
          f"{stats['shading_stroke_width']} px")
    print(f"        Crayons utilises (solution mode) :")
    for hex_str, cnt in sorted(stats["crayons_used"].items(),
                                key=lambda x: -x[1]):
        name = next(
            (c["name"] for c in CRAYONS if c["hex"] == hex_str),
            "Papier" if hex_str == "#ffffff" else hex_str,
        )
        print(f"          - {name:12s} ({hex_str}) : {cnt}")
    print(f"\n[G5 LIVRABLES]")
    print(f"        SVG    : {stats['outputs']['svg']}")
    print(f"        HTML   : {stats['outputs']['html']}  <-- ouvrir dans un navigateur")
    print(f"        PNG    : solution {stats['outputs']['solution_png']}")
    print(f"                  blank    {stats['outputs']['blank_png']}")
    print(f"        Stats  : {stats_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
