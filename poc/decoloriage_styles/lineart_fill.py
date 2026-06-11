"""lineart_fill - post-traitement dedie "interactive coloring book fill" pour
line-art N&B (contours noirs sur fond blanc).

PROBLEME resolu : le pipeline decoloriage POC1/POC2 (k-means sur couleur) est le
mauvais outil sur du line-art N&B. Il segmente la STRUCTURE DES TRAITS au lieu
d'isoler les CELLULES BLANCHES delimitees par les traits. Les pages sont belles
mais pas coloriables.

CE MODULE est un NOUVEAU chemin (!= decoloriage k-means). Algorithme classique
"interactive coloring book fill" :

  1. Charger le PNG line-art (contours noirs / fond blanc).
  2. Binariser l'encre : seuil sur niveau de gris (pixels < INK_THRESHOLD = encre).
     L'anti-aliasing est absorbe par le seuil + la fermeture morpho.
  3. Fermeture morpho legere (MORPH_CLOSE kernel ~3px) pour souder les micro-trous
     de trait (evite la fuite inter-cellules par un trait discontinu).
  4. Composantes connexes du NON-encre (blanc), connectivite 4 ; l'encre = barriere.
     Chaque composante = une CELLULE coloriable.
  5. Fond = Papier : composantes blanches touchant le bord image -> region papier
     (cliquable mais marquee fond, fill blanc par defaut). Fusion des composantes
     < MIN_CELL_PX (bruit) dans aucun voisin (juste reaffectees a l'encre/ignorees).
  6. Vectoriser chaque cellule en path SVG : REUTILISE
     g3_vectorize.extract_region_polygons (marching squares + DP + Chaikin) sur le
     label-map des cellules.
  7. SVG bicouche : <g id="fills"> = 1 path cliquable par cellule (class="region",
     data-region-id, fill #ffffff) ; <g id="strokes"> = couche encre = masque
     binarise des traits noirs rasterise en image base64 par-dessus, non cliquable
     (pointer-events:none).
  8. HTML click-to-fill standalone (porte de g5) : palette 6 crayons + custom,
     bouton "Demo" = remplit chaque cellule d'une couleur aleatoire.

PREUVE DE COLORABILITE : <id>_demo_filled.png = chaque cellule remplie d'une
couleur distincte (rasterise depuis le label-map des cellules, l'encre par-dessus).
Prouve que les cellules sont des unites independantes couvrant toute la zone blanche
(pas de region geante, pas de fuite inter-cellules).

Reutilise g3 par IMPORT (aucune modif des sources POC). Pas de re-generation ComfyUI.
"""
from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi

# --- Import du code POC sans le modifier ---
POC1_DIR = Path(__file__).resolve().parents[1] / "decoloriage"
sys.path.insert(0, str(POC1_DIR))
from g3_vectorize import extract_region_polygons, _signed_area  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------------
# Parametres figes (calibres sur 12 PNG natifs 1024x1024, ink% 12-28)
# ----------------------------------------------------------------------------
INK_THRESHOLD = 110         # px gris < seuil = encre/trait noir
MORPH_CLOSE_KERNEL = 3      # px : soude les micro-trous de trait discontinu
MIN_CELL_PX = 24            # cellules < N px = bruit (fusionnees dans l'encre)
CONNECTIVITY = 1            # 1 = 4-connexite (l'encre fait barriere)
DP_TOLERANCE = 1.0
CHAIKIN_ITERS = 2

# Crayons du design system Alwan Books (identiques a g5)
CRAYONS = [
    {"name": "Cerise",    "hex": "#FF2E63"},
    {"name": "Mandarine", "hex": "#FF8A2B"},
    {"name": "Citron",    "hex": "#FFD60A"},
    {"name": "Menthe",    "hex": "#06D6A0"},
    {"name": "Ocean",     "hex": "#118AB2"},
    {"name": "Prune",     "hex": "#8B5CF6"},
]

# Palette de demo (rasterisation de la preuve de colorabilite). 24 teintes bien
# espacees pour que les cellules adjacentes contrastent visuellement.
_DEMO_PALETTE = np.array([
    [255, 89, 94], [255, 146, 76], [255, 202, 58], [138, 201, 38],
    [25, 130, 196], [106, 76, 147], [255, 122, 162], [67, 170, 139],
    [87, 117, 144], [242, 132, 130], [144, 190, 109], [249, 199, 79],
    [248, 150, 30], [77, 144, 142], [157, 2, 8], [232, 93, 117],
    [45, 197, 244], [181, 23, 158], [114, 9, 183], [76, 201, 240],
    [0, 187, 249], [0, 245, 212], [254, 228, 64], [155, 93, 229],
], dtype=np.uint8)


# ----------------------------------------------------------------------------
# Etapes 2-5 : binarisation encre + cellules blanches connexes
# ----------------------------------------------------------------------------
def binarize_ink(gray: np.ndarray, threshold: int = INK_THRESHOLD,
                 close_kernel: int = MORPH_CLOSE_KERNEL) -> np.ndarray:
    """Retourne un masque uint8 de l'encre (255 = trait noir, 0 = blanc).
    Seuil + MORPH_CLOSE leger pour souder les micro-trous (anti-aliasing /
    trait discontinu)."""
    ink = (gray < threshold).astype(np.uint8) * 255
    if close_kernel and close_kernel > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel, close_kernel))
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k)
    return ink


def label_cells(ink_mask: np.ndarray, min_cell_px: int = MIN_CELL_PX,
                connectivity: int = CONNECTIVITY,
                ) -> tuple[np.ndarray, set[int], dict[int, int]]:
    """Composantes connexes du NON-encre (blanc). L'encre fait barriere.

    Retourne :
      - region_map : int32 (H, W). 0 = encre (non-cellule). >=1 = id de cellule.
      - paper_ids  : set des ids de cellules touchant le bord image (= papier/fond).
      - cell_sizes : dict id -> nb pixels.

    Les cellules < min_cell_px sont reaffectees a l'encre (0) : bruit / slivers de
    trait residuels qui n'apporteraient aucune zone coloriable utile.
    """
    white = (ink_mask == 0)
    struct = ndi.generate_binary_structure(2, connectivity)
    lab, n = ndi.label(white, structure=struct)
    lab = lab.astype(np.int32)

    H, W = lab.shape
    # Tailles
    sizes = np.bincount(lab.ravel())
    # Cellules trop petites -> encre (0)
    small_ids = np.where(sizes < min_cell_px)[0]
    small_ids = small_ids[small_ids != 0]
    if len(small_ids):
        small_set = set(int(s) for s in small_ids)
        remove = np.isin(lab, list(small_set))
        lab[remove] = 0

    # Ids restants + relabel compact 1..K
    remaining = np.unique(lab)
    remaining = remaining[remaining != 0]
    remap = np.zeros(int(lab.max()) + 1, dtype=np.int32)
    for new_id, old_id in enumerate(remaining, start=1):
        remap[old_id] = new_id
    region_map = remap[lab]

    # Detection papier : cellules touchant le bord
    border_ids = set()
    for edge in (region_map[0, :], region_map[-1, :],
                 region_map[:, 0], region_map[:, -1]):
        border_ids.update(int(v) for v in np.unique(edge) if v != 0)

    cell_sizes = {}
    if region_map.max() > 0:
        cs = np.bincount(region_map.ravel())
        for cid in range(1, len(cs)):
            cell_sizes[int(cid)] = int(cs[cid])

    return region_map, border_ids, cell_sizes


# ----------------------------------------------------------------------------
# Etape 7 : couche encre rasterisee pixel-perfect en PNG base64 (overlay SVG)
# ----------------------------------------------------------------------------
def ink_mask_to_png_b64(ink_mask: np.ndarray) -> str:
    """Rend la couche encre en PNG RGBA : trait noir opaque, reste transparent.
    Encode en base64 pour embarquer dans le SVG (<image>) et le HTML."""
    H, W = ink_mask.shape
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    is_ink = ink_mask > 0
    rgba[is_ink, 3] = 255  # alpha
    # RGB reste (0,0,0) -> noir
    ok, buf = cv2.imencode(".png", rgba)
    if not ok:
        raise RuntimeError("encode PNG ink layer failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ----------------------------------------------------------------------------
# Etape 7 : assemblage SVG bicouche
# ----------------------------------------------------------------------------
def build_fill_svg(
    region_polys: list[tuple[int, list[np.ndarray]]],
    paper_ids: set[int],
    ink_png_b64: str,
    H: int,
    W: int,
) -> str:
    """SVG bicouche.

    <g id="fills"> : un <path> composite par cellule (toutes les sous-polylines
        fusionnees, fill-rule:evenodd pour qu'un trou interieur ne se remplisse
        pas). class="region" + data-region-id. Les cellules papier portent en plus
        class="region region-paper". fill #ffffff par defaut.
    <g id="strokes"> : couche encre = masque binarise rasterise pixel-perfect,
        embarque en <image> base64, pointer-events:none (non cliquable).
    """
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'shape-rendering="geometricPrecision">'
    ]
    lines.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

    # --- Fill layer ---
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
        cls = "region region-paper" if rid in paper_ids else "region"
        lines.append(
            f'<path class="{cls}" data-region-id="{rid}" '
            f'fill="#ffffff" d="{d_attr}"/>'
        )
    lines.append("</g>")

    # --- Stroke layer = couche encre rasterisee (pixel-perfect), non cliquable ---
    lines.append('<g id="strokes" pointer-events="none">')
    lines.append(
        f'<image x="0" y="0" width="{W}" height="{H}" '
        f'image-rendering="pixelated" '
        f'href="data:image/png;base64,{ink_png_b64}" '
        f'xlink:href="data:image/png;base64,{ink_png_b64}"/>'
    )
    lines.append("</g>")

    lines.append("</svg>")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Etape 8 : HTML click-to-fill standalone (porte de g5 + bouton Demo)
# ----------------------------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lineart-fill - {title}</title>
<style>
  :root {{
    --bg: #fdfbf6; --paper: #ffffff; --ink: #15151b; --muted: #6b6b78;
    --shadow: 0 6px 24px rgba(0,0,0,0.08); --gap: 14px;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: var(--ink); min-height: 100vh; display: flex; flex-direction: column; }}
  header {{ padding: 18px 24px; border-bottom: 1px solid #ece8df; background: #fff; }}
  header h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
  header p {{ margin: 4px 0 0; color: var(--muted); font-size: 13px; }}
  main {{ flex: 1; display: grid; grid-template-columns: 1fr 280px; gap: 18px;
    padding: 18px 24px; max-width: 1400px; margin: 0 auto; width: 100%; }}
  .canvas-wrap {{ background: var(--paper); border-radius: 16px; padding: 18px;
    box-shadow: var(--shadow); display: flex; align-items: center;
    justify-content: center; min-height: 600px; }}
  .canvas-wrap svg {{ width: 100%; height: auto; max-height: 84vh; display: block; }}
  .region {{ cursor: pointer; transition: fill 0.08s ease; }}
  .region:hover {{ filter: brightness(0.95); }}
  aside {{ display: flex; flex-direction: column; gap: var(--gap); }}
  .card {{ background: var(--paper); border-radius: 12px; padding: 14px; box-shadow: var(--shadow); }}
  .card h2 {{ margin: 0 0 10px; font-size: 13px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); }}
  .palette {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
  .crayon {{ aspect-ratio: 1.6 / 1; border-radius: 10px; border: 3px solid transparent;
    cursor: pointer; display: flex; align-items: flex-end; justify-content: center;
    padding-bottom: 6px; font-size: 11px; font-weight: 600; color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.35); transition: transform 0.1s ease; }}
  .crayon[aria-pressed="true"] {{ border-color: var(--ink); transform: translateY(-2px); }}
  .crayon:hover {{ transform: translateY(-2px); }}
  .custom-row {{ display: flex; align-items: center; gap: 8px; margin-top: 10px; }}
  .custom-row input[type=color] {{ width: 44px; height: 34px; border: none;
    background: none; cursor: pointer; }}
  .actions {{ display: flex; flex-direction: column; gap: 8px; }}
  button.action {{ appearance: none; border: 1.5px solid var(--ink); background: #fff;
    color: var(--ink); border-radius: 10px; padding: 10px 12px; font-size: 14px;
    font-weight: 600; cursor: pointer; }}
  button.action:hover {{ background: #f5f1e6; }}
  button.action.primary {{ background: var(--ink); color: #fff; }}
  button.action.primary:hover {{ background: #2a2a35; }}
  .stats {{ font-size: 12px; color: var(--muted); line-height: 1.55; }}
  .stats strong {{ color: var(--ink); }}
  footer {{ padding: 12px 24px; color: var(--muted); font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>Lineart-fill - <em>{title}</em></h1>
  <p>Style : {style} - sujet : {subject}. Clic sur une cellule -> remplit. Cellules blanches isolees par les traits noirs (couche encre non cliquable).</p>
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
      <div class="custom-row">
        <input type="color" id="custom-color" value="#3aa0ff" title="Couleur libre">
        <span style="font-size:12px;color:var(--muted)">Couleur libre</span>
      </div>
    </div>
    <div class="card actions">
      <h2>Actions</h2>
      <button class="action primary" id="btn-demo">Demo : colorier aleatoirement</button>
      <button class="action" id="btn-reset">Tout effacer</button>
    </div>
    <div class="card stats">
      <strong>{n_cells}</strong> cellules cliquables<br>
      <strong>{n_paper}</strong> cellule(s) papier (fond)<br>
      Couverture cellules : <strong>{coverage_pct:.1f}%</strong> de la zone blanche<br>
      Seuil encre &lt; {ink_threshold} - close {morph_close}px - min cell {min_cell_px}px
    </div>
  </aside>
</main>
<footer>POC2 lineart-fill - {title}</footer>
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
  const custom = document.getElementById('custom-color');
  custom.addEventListener('input', () => {{
    crayons.forEach(b => b.setAttribute('aria-pressed', 'false'));
    selected = custom.value;
  }});
  const regions = document.querySelectorAll('.region');
  regions.forEach(p => {{
    p.addEventListener('click', () => {{ p.setAttribute('fill', selected); }});
  }});
  document.getElementById('btn-demo').addEventListener('click', () => {{
    const hues = ['#FF595E','#FF924C','#FFCA3A','#8AC926','#1982C4','#6A4C93',
                  '#FF7AA2','#43AA8B','#577590','#F94144','#90BE6D','#9B5DE5'];
    regions.forEach(p => {{
      const c = hues[Math.floor(Math.random()*hues.length)];
      p.setAttribute('fill', c);
    }});
  }});
  document.getElementById('btn-reset').addEventListener('click', () => {{
    regions.forEach(p => {{ p.setAttribute('fill', '#ffffff'); }});
  }});
}})();
</script>
</body>
</html>
"""


def build_html(svg_inline: str, title: str, style: str, subject: str,
               n_cells: int, n_paper: int, coverage_pct: float) -> str:
    palette_parts = []
    for c in CRAYONS:
        palette_parts.append(
            f'<button class="crayon" role="radio" '
            f'aria-pressed="{"true" if c["hex"] == "#FF2E63" else "false"}" '
            f'data-color="{c["hex"]}" style="background:{c["hex"]}" '
            f'title="{c["name"]}">{c["name"]}</button>'
        )
    return HTML_TEMPLATE.format(
        title=title, style=style, subject=subject,
        svg_inline=svg_inline,
        palette_html="\n        ".join(palette_parts),
        n_cells=n_cells, n_paper=n_paper, coverage_pct=coverage_pct,
        ink_threshold=INK_THRESHOLD, morph_close=MORPH_CLOSE_KERNEL,
        min_cell_px=MIN_CELL_PX,
    )


# ----------------------------------------------------------------------------
# Preuve de colorabilite : rasterisation demo (1 couleur distincte par cellule)
# ----------------------------------------------------------------------------
def render_demo_filled(region_map: np.ndarray, ink_mask: np.ndarray,
                       seed: int = 42) -> np.ndarray:
    """Rasterise chaque cellule avec une couleur distincte (cycle palette demo
    + jitter par id pour eviter deux voisines identiques), l'encre par-dessus en
    noir. Prouve que les cellules sont des unites independantes couvrant toute la
    zone blanche. Retourne une image BGR uint8."""
    H, W = region_map.shape
    rng = np.random.default_rng(seed)
    max_id = int(region_map.max())
    # Table de couleurs : 1 par id. Cycle de la palette + permutation aleatoire
    # pour disperser les teintes, evitant que des ids consecutifs (souvent
    # spatialement proches) partagent une teinte.
    order = rng.permutation(max_id) if max_id > 0 else np.array([], dtype=int)
    lut = np.zeros((max_id + 1, 3), dtype=np.uint8)  # RGB
    for rank, cid in enumerate(order):
        lut[cid + 1] = _DEMO_PALETTE[rank % len(_DEMO_PALETTE)]
    # id 0 = encre/non-cellule -> blanc (sera ecrase par l'encre noire ensuite)
    lut[0] = (255, 255, 255)
    rgb = lut[region_map]               # (H, W, 3) RGB
    bgr = rgb[:, :, ::-1].copy()
    # Encre par-dessus en noir pur (pixel-perfect)
    bgr[ink_mask > 0] = (0, 0, 0)
    return bgr


# ----------------------------------------------------------------------------
# Pipeline complet par image
# ----------------------------------------------------------------------------
def process_image(
    src_png: Path,
    out_dir: Path,
    image_id: str,
    style: str = "",
    subject: str = "",
    ink_threshold: int = INK_THRESHOLD,
    morph_close: int = MORPH_CLOSE_KERNEL,
    min_cell_px: int = MIN_CELL_PX,
    dp_tol: float = DP_TOLERANCE,
    chaikin_iters: int = CHAIKIN_ITERS,
) -> dict:
    t0 = time.time()
    gray = cv2.imread(str(src_png), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"PNG illisible : {src_png}")
    H, W = gray.shape

    # 2-3. Binarisation encre + fermeture morpho
    ink_mask = binarize_ink(gray, ink_threshold, morph_close)

    # 4-5. Cellules blanches connexes + papier
    region_map, paper_ids, cell_sizes = label_cells(
        ink_mask, min_cell_px, CONNECTIVITY,
    )
    n_total_cells = int(region_map.max())
    n_paper = len(paper_ids)
    n_clickable = n_total_cells  # papier reste cliquable (marque)

    # Couverture : surface des cellules vs surface blanche d'origine (pre-close)
    white_px_orig = int((gray >= ink_threshold).sum())
    cells_px = int((region_map > 0).sum())
    coverage_pct = (cells_px / white_px_orig * 100) if white_px_orig else 0.0

    # 6. Vectorisation des cellules (REUTILISE g3)
    region_polys = extract_region_polygons(region_map, dp_tol, chaikin_iters)
    # extract_region_polygons inclut l'id 0 (encre) ; on le retire de la couche
    # fills (l'encre est rendue separement en raster).
    region_polys = [(rid, polys) for rid, polys in region_polys if rid != 0]
    n_polys = sum(len(p) for _, p in region_polys)

    # 7. Couche encre rasterisee + SVG bicouche
    ink_b64 = ink_mask_to_png_b64(ink_mask)
    svg_text = build_fill_svg(region_polys, paper_ids, ink_b64, H, W)
    svg_path = out_dir / f"{image_id}.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    # 8. HTML standalone
    title = image_id.replace("_", " ").title()
    html_text = build_html(
        svg_text, title, style, subject, n_clickable, n_paper, coverage_pct,
    )
    html_path = out_dir / f"{image_id}.html"
    html_path.write_text(html_text, encoding="utf-8")

    # Blank PNG (couche encre seule, inchangee vs source mais propre N&B)
    blank = np.full((H, W, 3), 255, dtype=np.uint8)
    blank[ink_mask > 0] = (0, 0, 0)
    blank_path = out_dir / f"{image_id}_blank.png"
    cv2.imwrite(str(blank_path), blank)

    # Preuve : demo filled
    demo = render_demo_filled(region_map, ink_mask)
    demo_path = out_dir / f"{image_id}_demo_filled.png"
    cv2.imwrite(str(demo_path), demo)

    svg_kb = round(svg_path.stat().st_size / 1024, 1)
    cell_size_list = sorted(cell_sizes.values())
    median_cell_px = int(np.median(cell_size_list)) if cell_size_list else 0

    elapsed = round(time.time() - t0, 2)
    return {
        "id": image_id,
        "style": style,
        "subject": subject,
        "image_size": [int(W), int(H)],
        "n_cells": n_clickable,
        "n_paper": n_paper,
        "n_polylines": n_polys,
        "cells_px": cells_px,
        "white_px_orig": white_px_orig,
        "coverage_pct": round(coverage_pct, 2),
        "median_cell_px": median_cell_px,
        "svg_kb": svg_kb,
        "params": {
            "ink_threshold": ink_threshold,
            "morph_close": morph_close,
            "min_cell_px": min_cell_px,
            "connectivity": CONNECTIVITY,
            "dp_tolerance": dp_tol,
            "chaikin_iters": chaikin_iters,
        },
        "outputs": {
            "blank_png": str(blank_path),
            "svg": str(svg_path),
            "html": str(html_path),
            "demo_filled_png": str(demo_path),
        },
        "timing_s": elapsed,
    }
