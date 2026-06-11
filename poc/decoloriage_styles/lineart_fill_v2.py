"""lineart_fill_v2 - version PRODUCTION du fill line-art N&B.

Corrige les 2 defauts production identifies par l'humain sur fill_v2 :

  DEFAUT 1 - traces blanches (halo) autour des traits :
    Dans v1, les pixels d'encre (et anti-aliases) n'etaient assignes a AUCUNE
    cellule -> au remplissage, un halo blanc subsistait le long des traits.
    FIX : apres les composantes connexes du blanc, on ETEND chaque cellule
    jusque SOUS le trait via une transformee de distance / Voronoi
    (scipy.ndimage.distance_transform_edt avec return_indices=True). Le label-map
    des cellules couvre alors 100 % du canvas (zero pixel non assigne). La couche
    encre est dessinee PAR-DESSUS -> en remplissant, la couleur passe sous la
    ligne, zero halo blanc.

  DEFAUT 2 - traits pas lisses (crenelage) :
    Dans v1, la couche encre etait une image raster base64 (pixelisee).
    FIX : on VECTORISE le masque d'encre via src/services/vectorizer.py
    (Vectorizer.from_preset("bw_default"), VTracer spline) -> paths SVG noirs
    lisses pour <g id="strokes"> (pointer-events:none).

Les cellules (<g id="fills">) restent vectorisees via g3.extract_region_polygons
(deja lisse, Chaikin) MAIS desormais ETENDUES (fix 1) -> leurs bords passent sous
l'encre vectorisee.

Reutilise par IMPORT, AUCUNE modif des sources :
  - poc/decoloriage/g3_vectorize.extract_region_polygons (+ _signed_area)
  - src/services/vectorizer.Vectorizer (VTracer, preset bw_default)
  - principe Voronoi de src/services/extract_palette._expand_regions_to_ink
    (re-implemente ici a l'identique pour ne pas tirer toute la dependance
    extract_palette ; meme appel distance_transform_edt(return_indices=True)).

Pas de re-generation ComfyUI.
"""
from __future__ import annotations

import re
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi
from scipy.ndimage import distance_transform_edt

# --- Import du code POC + service prod sans les modifier ---
HERE = Path(__file__).resolve().parent
POC1_DIR = HERE.parent / "decoloriage"
PROJECT_ROOT = HERE.parents[1]
SRC_DIR = PROJECT_ROOT / "src"
for _p in (str(POC1_DIR), str(SRC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from g3_vectorize import extract_region_polygons, _signed_area  # noqa: E402
from services.vectorizer import Vectorizer  # noqa: E402


# ----------------------------------------------------------------------------
# Parametres figes (memes qu'en v1, calibres sur 12 PNG natifs 1024x1024)
# ----------------------------------------------------------------------------
INK_THRESHOLD = 110         # px gris < seuil = encre/trait noir
MORPH_CLOSE_KERNEL = 3      # px : soude les micro-trous de trait discontinu
MIN_CELL_PX = 24            # cellules < N px = bruit (fusionnees dans l'encre)
CONNECTIVITY = 1            # 1 = 4-connexite (l'encre fait barriere)
DP_TOLERANCE = 1.0
CHAIKIN_ITERS = 2
INK_VECTOR_PRESET = "bw_default"   # VTracer spline = traits lisses

# Crayons du design system Alwan Books (identiques a g5/v1)
CRAYONS = [
    {"name": "Cerise",    "hex": "#FF2E63"},
    {"name": "Mandarine", "hex": "#FF8A2B"},
    {"name": "Citron",    "hex": "#FFD60A"},
    {"name": "Menthe",    "hex": "#06D6A0"},
    {"name": "Ocean",     "hex": "#118AB2"},
    {"name": "Prune",     "hex": "#8B5CF6"},
]

# Palette de demo (24 teintes bien espacees pour contraste inter-cellules).
_DEMO_PALETTE = np.array([
    [255, 89, 94], [255, 146, 76], [255, 202, 58], [138, 201, 38],
    [25, 130, 196], [106, 76, 147], [255, 122, 162], [67, 170, 139],
    [87, 117, 144], [242, 132, 130], [144, 190, 109], [249, 199, 79],
    [248, 150, 30], [77, 144, 142], [157, 2, 8], [232, 93, 117],
    [45, 197, 244], [181, 23, 158], [114, 9, 183], [76, 201, 240],
    [0, 187, 249], [0, 245, 212], [254, 228, 64], [155, 93, 229],
], dtype=np.uint8)


# ----------------------------------------------------------------------------
# Etape 2-3 : binarisation encre (identique v1)
# ----------------------------------------------------------------------------
def binarize_ink(gray: np.ndarray, threshold: int = INK_THRESHOLD,
                 close_kernel: int = MORPH_CLOSE_KERNEL) -> np.ndarray:
    """Masque uint8 de l'encre (255 = trait noir, 0 = blanc). Seuil + MORPH_CLOSE
    leger pour souder les micro-trous (anti-aliasing / trait discontinu)."""
    ink = (gray < threshold).astype(np.uint8) * 255
    if close_kernel and close_kernel > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel, close_kernel))
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k)
    return ink


# ----------------------------------------------------------------------------
# Etape 4-5 : cellules blanches connexes (identique v1)
# ----------------------------------------------------------------------------
def label_cells(ink_mask: np.ndarray, min_cell_px: int = MIN_CELL_PX,
                connectivity: int = CONNECTIVITY,
                ) -> tuple[np.ndarray, set[int], dict[int, int]]:
    """Composantes connexes du NON-encre (blanc). L'encre fait barriere.

    Retourne (region_map int32 [0=encre, >=1=cellule], paper_ids, cell_sizes).
    Les cellules < min_cell_px sont reaffectees a l'encre (0).
    """
    white = (ink_mask == 0)
    struct = ndi.generate_binary_structure(2, connectivity)
    lab, _n = ndi.label(white, structure=struct)
    lab = lab.astype(np.int32)

    sizes = np.bincount(lab.ravel())
    small_ids = np.where(sizes < min_cell_px)[0]
    small_ids = small_ids[small_ids != 0]
    if len(small_ids):
        remove = np.isin(lab, list(int(s) for s in small_ids))
        lab[remove] = 0

    remaining = np.unique(lab)
    remaining = remaining[remaining != 0]
    remap = np.zeros(int(lab.max()) + 1, dtype=np.int32)
    for new_id, old_id in enumerate(remaining, start=1):
        remap[old_id] = new_id
    region_map = remap[lab]

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
# FIX 1 : expansion Voronoi des cellules SOUS le trait (couverture 100 %)
# ----------------------------------------------------------------------------
def expand_cells_to_ink(region_map: np.ndarray) -> np.ndarray:
    """Etend chaque cellule jusque sous l'encre via nearest-cell (Voronoi).

    Meme principe que extract_palette._expand_regions_to_ink : pour chaque pixel
    d'encre (region_map == 0), trouve la cellule (>=1) la plus proche en distance
    euclidienne et lui attribue son id. Resultat : le label-map couvre 100 % du
    canvas (plus aucun pixel a 0), chaque cellule s'etend jusqu'au centre du trait.

    L'encre noire est ensuite dessinee PAR-DESSUS au rendu -> zero halo blanc.
    """
    cell_mask = region_map > 0
    if cell_mask.all() or not cell_mask.any():
        return region_map.copy()

    # distance_transform_edt(~cell_mask) : pour chaque pixel d'encre, indices du
    # pixel-cellule le plus proche.
    _distance, indices = distance_transform_edt(
        ~cell_mask, return_indices=True,
    )
    nearest_y, nearest_x = indices

    out = region_map.copy()
    ink_pixels = ~cell_mask
    out[ink_pixels] = region_map[nearest_y[ink_pixels], nearest_x[ink_pixels]]
    return out


# ----------------------------------------------------------------------------
# FIX 2 : vectorisation du masque d'encre -> paths SVG lisses (VTracer)
# ----------------------------------------------------------------------------
# VTracer emet un <path> par forme : d="..." puis fill + transform="translate(tx,ty)".
# Les coords de d sont RELATIVES a ce translate -> on doit le capturer.
_D_RE = re.compile(r'\bd="([^"]+)"')
_TRANSLATE_RE = re.compile(r'translate\(\s*(-?\d*\.?\d+)\s*,\s*(-?\d*\.?\d+)\s*\)')


def vectorize_ink_paths(ink_mask: np.ndarray, preset: str = INK_VECTOR_PRESET,
                        ) -> tuple[list[tuple[str, float, float]], int]:
    """Vectorise le masque d'encre en paths SVG noirs lisses via VTracer.

    Construit un PNG binaire (encre noire sur fond blanc), le passe au service
    prod Vectorizer (preset bw_default, spline). Retourne
    (liste de (d_string, tx, ty), taille SVG VTracer en octets) ou (tx, ty) est
    le translate du <path> (les coords de d y sont relatives).
    """
    H, W = ink_mask.shape
    binary = np.full((H, W), 255, dtype=np.uint8)
    binary[ink_mask > 0] = 0

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        in_png = td_path / "ink.png"
        cv2.imwrite(str(in_png), binary)
        vec = Vectorizer.from_preset(preset)
        result = vec.process(in_png, td_path)
        svg_text = result.svg_path.read_text(encoding="utf-8")
        svg_bytes = result.svg_path.stat().st_size

    paths: list[tuple[str, float, float]] = []
    # Decoupe par element <path ...> pour associer correctement d <-> transform.
    for chunk in svg_text.split("<path")[1:]:
        elem = chunk.split(">", 1)[0]  # attributs jusqu'au premier '>'
        dm = _D_RE.search(elem)
        if not dm:
            continue
        tm = _TRANSLATE_RE.search(elem)
        tx, ty = (float(tm.group(1)), float(tm.group(2))) if tm else (0.0, 0.0)
        paths.append((dm.group(1), tx, ty))
    return paths, int(svg_bytes)


# ----------------------------------------------------------------------------
# Etape 7 : assemblage SVG bicouche (fills vectorises etendus + encre vectorisee)
# ----------------------------------------------------------------------------
def build_fill_svg(
    region_polys: list[tuple[int, list[np.ndarray]]],
    paper_ids: set[int],
    ink_paths: list[tuple[str, float, float]],
    H: int,
    W: int,
) -> str:
    """SVG bicouche, 100 % vectoriel.

    <g id="fills"> : un <path> composite par cellule ETENDUE (bords passant sous
        l'encre). class="region"/"region region-paper", data-region-id, fill #fff.
    <g id="strokes"> : encre VECTORISEE (paths VTracer spline lisses), fill noir,
        pointer-events:none (non cliquable). Plus de raster base64 -> plus de
        crenelage.
    """
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'shape-rendering="geometricPrecision">'
    ]
    lines.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

    # --- Fill layer (cellules etendues) ---
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

    # --- Stroke layer = encre VECTORISEE (lisse), non cliquable ---
    lines.append('<g id="strokes" pointer-events="none" fill="#15151b" '
                 'stroke="none" fill-rule="evenodd">')
    for d, tx, ty in ink_paths:
        if tx or ty:
            lines.append(f'<path d="{d}" transform="translate({tx},{ty})"/>')
        else:
            lines.append(f'<path d="{d}"/>')
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
<title>Lineart-fill v2 - {title}</title>
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
  <h1>Lineart-fill v2 - <em>{title}</em></h1>
  <p>Style : {style} - sujet : {subject}. Clic sur une cellule -> remplit. Cellules etendues sous le trait (zero halo) + encre vectorisee (traits lisses).</p>
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
      Couverture cellules : <strong>{coverage_pct:.1f}%</strong> du canvas (halo supprime)<br>
      Encre vectorisee (VTracer spline) - traits lisses
    </div>
  </aside>
</main>
<footer>POC2 lineart-fill v2 (production) - {title}</footer>
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
    )


# ----------------------------------------------------------------------------
# Preuve : demo filled (1 couleur distincte / cellule ETENDUE, encre par-dessus)
# ----------------------------------------------------------------------------
def render_demo_filled(region_map_expanded: np.ndarray, ink_mask: np.ndarray,
                       seed: int = 42) -> np.ndarray:
    """Rasterise chaque cellule ETENDUE avec une couleur distincte, l'encre
    par-dessus en noir. Comme region_map est etendu sous le trait, la couleur
    touche le trait : zero halo blanc visible. Retourne une image BGR uint8."""
    rng = np.random.default_rng(seed)
    max_id = int(region_map_expanded.max())
    order = rng.permutation(max_id) if max_id > 0 else np.array([], dtype=int)
    lut = np.zeros((max_id + 1, 3), dtype=np.uint8)  # RGB
    for rank, cid in enumerate(order):
        lut[cid + 1] = _DEMO_PALETTE[rank % len(_DEMO_PALETTE)]
    lut[0] = (255, 255, 255)  # ne devrait plus exister (couverture 100%)
    rgb = lut[region_map_expanded]
    bgr = rgb[:, :, ::-1].copy()
    bgr[ink_mask > 0] = (0, 0, 0)
    return bgr


def render_demo_no_ink(region_map_expanded: np.ndarray, seed: int = 42) -> np.ndarray:
    """Variante SANS encre par-dessus : montre que les cellules etendues
    couvrent 100 % du canvas (preuve directe du fix halo)."""
    rng = np.random.default_rng(seed)
    max_id = int(region_map_expanded.max())
    order = rng.permutation(max_id) if max_id > 0 else np.array([], dtype=int)
    lut = np.zeros((max_id + 1, 3), dtype=np.uint8)
    for rank, cid in enumerate(order):
        lut[cid + 1] = _DEMO_PALETTE[rank % len(_DEMO_PALETTE)]
    lut[0] = (255, 255, 255)
    rgb = lut[region_map_expanded]
    return rgb[:, :, ::-1].copy()


# ----------------------------------------------------------------------------
# Zoom : crop fort grossissement sur une zone de traits (preuve halo + lissage)
# ----------------------------------------------------------------------------
def _flatten_bezier(p0, p1, p2, p3, n: int = 16) -> list[tuple[float, float]]:
    """Echantillonne une cubic Bezier (4 points de controle) en n+1 points."""
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = (mt ** 3) * p0[0] + 3 * (mt ** 2) * t * p1[0] \
            + 3 * mt * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        y = (mt ** 3) * p0[1] + 3 * (mt ** 2) * t * p1[1] \
            + 3 * mt * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        pts.append((x, y))
    return pts


_TOKEN_RE = re.compile(r"([MmCcLlZzHhVv])|(-?\d*\.?\d+(?:e-?\d+)?)")


def flatten_svg_path(d: str, scale: float = 1.0, bez_steps: int = 18,
                     ) -> list[list[tuple[float, float]]]:
    """Convertit un attribut SVG 'd' (M/C/L/Z absolus, comme VTracer) en une
    liste de sous-polylignes (flatten des cubic Beziers). Coordonnees * scale.

    Suffisant pour les paths VTracer (M, C, Z absolus). Gere aussi L/H/V/Z par
    securite. Sous-chemins separes par M -> evenodd pour les trous."""
    tokens = _TOKEN_RE.findall(d)
    nums = []
    cmds = []  # (cmd, start_index_in_nums)
    for cmd, num in tokens:
        if cmd:
            cmds.append((cmd, len(nums)))
        else:
            nums.append(float(num))

    subpaths: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    pos = (0.0, 0.0)
    start = (0.0, 0.0)

    i = 0
    while i < len(cmds):
        cmd, idx = cmds[i]
        nxt = cmds[i + 1][1] if i + 1 < len(cmds) else len(nums)
        args = nums[idx:nxt]
        if cmd in ("M", "m"):
            if cur:
                subpaths.append(cur)
            x, y = args[0], args[1]
            if cmd == "m":
                x += pos[0]; y += pos[1]
            pos = (x, y); start = pos
            cur = [pos]
            # extra coord pairs after M are implicit L
            j = 2
            while j + 1 < len(args):
                lx, ly = args[j], args[j + 1]
                if cmd == "m":
                    lx += pos[0]; ly += pos[1]
                pos = (lx, ly); cur.append(pos); j += 2
        elif cmd in ("C", "c"):
            j = 0
            while j + 5 < len(args):
                c1 = (args[j], args[j + 1]); c2 = (args[j + 2], args[j + 3])
                end = (args[j + 4], args[j + 5])
                if cmd == "c":
                    c1 = (c1[0] + pos[0], c1[1] + pos[1])
                    c2 = (c2[0] + pos[0], c2[1] + pos[1])
                    end = (end[0] + pos[0], end[1] + pos[1])
                cur.extend(_flatten_bezier(pos, c1, c2, end, bez_steps)[1:])
                pos = end; j += 6
        elif cmd in ("L", "l"):
            j = 0
            while j + 1 < len(args):
                lx, ly = args[j], args[j + 1]
                if cmd == "l":
                    lx += pos[0]; ly += pos[1]
                pos = (lx, ly); cur.append(pos); j += 2
        elif cmd in ("H", "h"):
            for v in args:
                x = v + (pos[0] if cmd == "h" else 0.0)
                pos = (x, pos[1]); cur.append(pos)
        elif cmd in ("V", "v"):
            for v in args:
                y = v + (pos[1] if cmd == "v" else 0.0)
                pos = (pos[0], y); cur.append(pos)
        elif cmd in ("Z", "z"):
            if cur:
                cur.append(start)
                subpaths.append(cur)
                cur = []
            pos = start
        i += 1
    if cur:
        subpaths.append(cur)

    if scale != 1.0:
        subpaths = [[(x * scale, y * scale) for (x, y) in sp] for sp in subpaths]
    return subpaths


def rasterize_vector_ink(ink_paths: list[tuple[str, float, float]], H: int, W: int,
                         scale: float = 1.0) -> np.ndarray:
    """Rasterise les paths d'encre VECTORISES (smooth) en un masque uint8 a la
    resolution (H*scale, W*scale). 255 = encre. Prouve le lissage : a fort
    upscale via scale, les bords restent courbes (issus des Beziers flattenes),
    pas crenele comme le raster source.

    Chaque path porte son translate (tx, ty) ; on l'applique puis on multiplie
    par scale. fill-rule evenodd : chaque sous-chemin XORe -> trous respectes."""
    Hs, Ws = int(round(H * scale)), int(round(W * scale))
    canvas = np.zeros((Hs, Ws), dtype=np.uint8)
    bez = max(10, int(round(2 * scale)))
    for d, tx, ty in ink_paths:
        # Un <path> VTracer = une forme noire avec ses trous internes encodes
        # comme sous-chemins supplementaires (fill-rule evenodd PAR path). On XOR
        # les sous-chemins de CE path entre eux, puis on OR le resultat dans le
        # canvas global (les paths sont peints les uns sur les autres = stacked).
        path_acc = np.zeros((Hs, Ws), dtype=np.uint8)
        for sp in flatten_svg_path(d, scale=1.0, bez_steps=bez):
            if len(sp) < 3:
                continue
            arr = (np.array(sp) + np.array([tx, ty])) * scale
            poly = np.round(arr).astype(np.int32)
            tmp = np.zeros((Hs, Ws), dtype=np.uint8)
            cv2.fillPoly(tmp, [poly], 1, lineType=cv2.LINE_8)
            path_acc ^= tmp
        canvas |= path_acc
    return canvas * 255


def _render_svg_zoom(
    region_map_exp: np.ndarray,
    ink_paths: list[tuple[str, float, float]],
    H: int, W: int,
    y: int, x: int, win: int, scale: float,
) -> np.ndarray:
    """Rend une fenetre [y:y+win, x:x+win] du SVG reel a fort upscale (scale) :
    fills = cellules etendues (couleur), encre = paths VECTORISES (lisses).

    C'est la preuve combinee : (a) la couleur des cellules etendues touche le
    trait (zero halo), (b) l'encre est vectorisee -> bords lisses meme grossis."""
    # Fills : upscale du label-map etendu (NEAREST garde les frontieres nettes,
    # mais comme les cellules sont etendues sous le trait, la couleur va jusqu'au
    # trait vectoriel).
    rng = np.random.default_rng(42)
    max_id = int(region_map_exp.max())
    order = rng.permutation(max_id) if max_id > 0 else np.array([], dtype=int)
    lut = np.zeros((max_id + 1, 3), dtype=np.uint8)
    for rank, cid in enumerate(order):
        lut[cid + 1] = _DEMO_PALETTE[rank % len(_DEMO_PALETTE)]
    lut[0] = (255, 255, 255)
    fills_rgb = lut[region_map_exp]
    fills_bgr = fills_rgb[:, :, ::-1].copy()

    crop_fills = fills_bgr[y:y + win, x:x + win]
    crop_up = cv2.resize(crop_fills, (int(win * scale), int(win * scale)),
                         interpolation=cv2.INTER_NEAREST)

    # Encre vectorisee rasterisee a fort upscale sur la fenetre :
    # on rasterise toute l'image a scale puis on crop (simple et robuste).
    ink_hi = rasterize_vector_ink(ink_paths, H, W, scale=scale)
    ys, xs = int(y * scale), int(x * scale)
    we = int(win * scale)
    ink_crop = ink_hi[ys:ys + we, xs:xs + we]
    # composite : encre noire (avec antialias du fillPoly LINE_AA) par-dessus
    if ink_crop.shape[:2] != crop_up.shape[:2]:
        ink_crop = cv2.resize(ink_crop, (crop_up.shape[1], crop_up.shape[0]),
                              interpolation=cv2.INTER_AREA)
    alpha = (ink_crop.astype(np.float32) / 255.0)[:, :, None]
    black = np.zeros_like(crop_up)
    out = (crop_up.astype(np.float32) * (1 - alpha)
           + black.astype(np.float32) * alpha).astype(np.uint8)
    return out


def _pick_ink_dense_window(ink_mask: np.ndarray, win: int) -> tuple[int, int]:
    """Trouve le coin (y, x) d'une fenetre win x win a forte densite de trait
    (zone interessante pour montrer halo + lissage)."""
    H, W = ink_mask.shape
    win = min(win, H, W)
    # densite locale via integral image
    ink = (ink_mask > 0).astype(np.float32)
    integral = cv2.integral(ink)  # (H+1, W+1)
    best, best_yx = -1.0, (H // 2 - win // 2, W // 2 - win // 2)
    step = max(8, win // 4)
    for y in range(0, H - win + 1, step):
        for x in range(0, W - win + 1, step):
            s = (integral[y + win, x + win] - integral[y, x + win]
                 - integral[y + win, x] + integral[y, x])
            frac = s / (win * win)
            # on veut du trait mais pas un bloc noir : cible ~15-45 % de trait
            score = -abs(frac - 0.28)
            if score > best:
                best, best_yx = score, (y, x)
    return best_yx


def build_zoom(
    region_map_exp: np.ndarray,
    ink_paths: list[tuple[str, float, float]],
    ink_mask: np.ndarray,
    win: int = 110,
    scale: float = 7.0,
) -> np.ndarray:
    """Crop fort grossissement sur une zone de traits, montrant cote a cote :
      - GAUCHE = ancien rendu (raster) : encre crenelee + halo blanc le long du
        trait (cellules non etendues : on simule via le masque source pixelise).
      - DROITE = nouveau rendu : cellules etendues (couleur jusqu'au trait, zero
        halo) + encre VECTORISEE (bords lisses).
    Une bande separatrice + labels."""
    H, W = ink_mask.shape
    y, x = _pick_ink_dense_window(ink_mask, win)

    right = _render_svg_zoom(region_map_exp, ink_paths, H, W, y, x, win, scale)

    # GAUCHE (comparaison "avant") : raster encre source pixelise sans expansion
    # -> halo blanc autour du trait + crenelage. On colorie les cellules NON
    # etendues (region 0 = encre/halo reste blanc) puis encre raster par-dessus.
    rng = np.random.default_rng(42)
    max_id = int(region_map_exp.max())
    order = rng.permutation(max_id) if max_id > 0 else np.array([], dtype=int)
    lut = np.zeros((max_id + 1, 3), dtype=np.uint8)
    for rank, cid in enumerate(order):
        lut[cid + 1] = _DEMO_PALETTE[rank % len(_DEMO_PALETTE)]
    lut[0] = (255, 255, 255)
    # NOTE : on n'a pas conserve le region_map pre-expansion ici ; le halo "avant"
    # se materialise en mettant a blanc tout pixel d'encre source (ink_mask>0) sur
    # le rendu couleur. Ca reproduit fidelement le defaut v1 (encre + AA = blanc).
    crop_ink = ink_mask[y:y + win, x:x + win]

    # On reconstruit "avant" depuis le rendu droite-fills sans expansion :
    # plus simple = prendre les fills etendus puis re-blanchir sous le trait.
    fills_rgb = lut[region_map_exp]
    fills_bgr = fills_rgb[:, :, ::-1].copy()
    before = fills_bgr.copy()
    before[ink_mask > 0] = (255, 255, 255)  # halo blanc v1
    before[ink_mask > 0] = (255, 255, 255)
    crop_before = before[y:y + win, x:x + win].copy()
    # encre raster pixelisee (NEAREST) par-dessus en noir
    left = cv2.resize(crop_before, (int(win * scale), int(win * scale)),
                      interpolation=cv2.INTER_NEAREST)
    ink_up = cv2.resize(crop_ink, (int(win * scale), int(win * scale)),
                        interpolation=cv2.INTER_NEAREST)
    left[ink_up > 0] = (0, 0, 0)

    # assemblage cote a cote + labels
    sep = np.full((left.shape[0], 4, 3), 200, np.uint8)
    pair = np.hstack([left, sep, right])
    lab_h = 30
    lab = np.full((lab_h, pair.shape[1], 3), 30, np.uint8)
    cv2.putText(lab, "AVANT (v1): halo + crenelage", (8, 21),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 160, 255), 1, cv2.LINE_AA)
    cv2.putText(lab, "APRES (v2): zero halo + lisse",
                (left.shape[1] + 12, 21),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 255, 160), 1, cv2.LINE_AA)
    return np.vstack([lab, pair])


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

    # 2-3. Binarisation encre
    ink_mask = binarize_ink(gray, ink_threshold, morph_close)

    # 4-5. Cellules blanches connexes (avant expansion)
    region_map, paper_ids, cell_sizes = label_cells(
        ink_mask, min_cell_px, CONNECTIVITY,
    )
    n_total_cells = int(region_map.max())
    n_paper = len(paper_ids)
    n_clickable = n_total_cells

    # Couverture AVANT expansion (= ancien comportement v1 : halo non assigne)
    canvas_px = H * W
    cells_px_before = int((region_map > 0).sum())
    coverage_before = (cells_px_before / canvas_px * 100) if canvas_px else 0.0

    # FIX 1 : expansion Voronoi des cellules sous le trait -> couverture 100 %
    region_map_exp = expand_cells_to_ink(region_map)
    cells_px_after = int((region_map_exp > 0).sum())
    coverage_after = (cells_px_after / canvas_px * 100) if canvas_px else 0.0

    # 6. Vectorisation des cellules ETENDUES (REUTILISE g3)
    region_polys = extract_region_polygons(region_map_exp, dp_tol, chaikin_iters)
    region_polys = [(rid, polys) for rid, polys in region_polys if rid != 0]
    n_polys = sum(len(p) for _, p in region_polys)

    # FIX 2 : vectorisation de l'encre (REUTILISE Vectorizer / VTracer)
    ink_paths, ink_svg_bytes = vectorize_ink_paths(ink_mask)
    n_ink_paths = len(ink_paths)

    # 7. SVG bicouche 100 % vectoriel
    svg_text = build_fill_svg(region_polys, paper_ids, ink_paths, H, W)
    svg_path = out_dir / f"{image_id}.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    # 8. HTML standalone
    title = image_id.replace("_", " ").title()
    html_text = build_html(
        svg_text, title, style, subject, n_clickable, n_paper, coverage_after,
    )
    html_path = out_dir / f"{image_id}.html"
    html_path.write_text(html_text, encoding="utf-8")

    # Blank PNG (couche encre seule)
    blank = np.full((H, W, 3), 255, dtype=np.uint8)
    blank[ink_mask > 0] = (0, 0, 0)
    blank_path = out_dir / f"{image_id}_blank.png"
    cv2.imwrite(str(blank_path), blank)

    # Preuve : demo filled (cellules etendues + encre)
    demo = render_demo_filled(region_map_exp, ink_mask)
    demo_path = out_dir / f"{image_id}_demo_filled.png"
    cv2.imwrite(str(demo_path), demo)

    # Zoom : crop fort grossissement, comparaison AVANT (halo+crenelage) /
    # APRES (cellules etendues + encre vectorisee lisse).
    zoom = build_zoom(region_map_exp, ink_paths, ink_mask)
    zoom_path = out_dir / f"{image_id}_zoom.png"
    cv2.imwrite(str(zoom_path), zoom)
    zoom_source = "vector_ink_render"

    svg_kb = round(svg_path.stat().st_size / 1024, 1)
    ink_svg_kb = round(ink_svg_bytes / 1024, 1)
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
        "n_ink_paths": n_ink_paths,
        "coverage_before_pct": round(coverage_before, 2),
        "coverage_after_pct": round(coverage_after, 2),
        "svg_kb": svg_kb,
        "ink_svg_kb": ink_svg_kb,
        "median_cell_px": median_cell_px,
        "zoom_source": zoom_source,
        "params": {
            "ink_threshold": ink_threshold,
            "morph_close": morph_close,
            "min_cell_px": min_cell_px,
            "connectivity": CONNECTIVITY,
            "dp_tolerance": dp_tol,
            "chaikin_iters": chaikin_iters,
            "ink_vector_preset": INK_VECTOR_PRESET,
        },
        "outputs": {
            "blank_png": str(blank_path),
            "svg": str(svg_path),
            "html": str(html_path),
            "demo_filled_png": str(demo_path),
            "zoom_png": str(zoom_path),
        },
        "timing_s": elapsed,
    }
