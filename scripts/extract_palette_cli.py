"""CLI : extraction palette + trait + coloriage interactif depuis PNG colorie.

Promu depuis ``_lab/extract-palette/coloriage.py`` le 2026-05-31.

Sous-commandes :

    # Extrait un PNG, sauvegarde un SVG de production.
    python scripts/extract_palette_cli.py run <png> --out output.svg

    # Genere le HTML coloriage interactif self-contained.
    python scripts/extract_palette_cli.py coloriage <png> --out coloriage.html

    # Bench sur un dossier (extrait tous les PNG et resume les stats).
    python scripts/extract_palette_cli.py bench <folder> --out bench.html

Le dossier d'entree est arbitraire (sortie ComfyUI, dossier externe via Tailscale,
etc.). Aucun emplacement par defaut code en dur.

Preset par defaut : ``iso_trait_v3_anomaly_split`` (PROD_PRESET).
Override : ``--preset <nom>`` (cf. PRESETS dans services/extract_palette.py).
Rollback : ``--preset iso_trait_v3_filled_no_gap_merged`` (ancien prod).
"""
from __future__ import annotations

import argparse
import base64
import html as html_escape
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from services.extract_palette import (  # noqa: E402
    PRESETS,
    PROD_PRESET,
    PaletteResult,
    _extract_svg_inner,
    _generate_auto_palette,
    _points_to_path_d,
    extract_palette,
    make_params,
    render_svg,
)

logger = logging.getLogger("extract_palette_cli")


DEFAULT_PALETTE = [
    "#e63946", "#f1a208", "#fcca46", "#a3c46d",
    "#52b788", "#06aed5", "#118ab2", "#7b68ee",
    "#9d4edd", "#ff6392", "#ff8fab", "#8b5a3c",
    "#5a4a3a", "#888888", "#bcbcbc", "#ffffff",
    "#000000",
]


# === Sous-commande "run" : SVG simple =========================================
def _cmd_run(args: argparse.Namespace) -> int:
    png_path = Path(args.png).expanduser().resolve()
    if not png_path.is_file():
        print(f"FAIL: PNG introuvable : {png_path}", file=sys.stderr)
        return 2

    overrides = {}
    if args.n_colors is not None:
        overrides["n_colors"] = int(args.n_colors)
    if args.merge_small is not None:
        overrides["merge_small_regions_px"] = int(args.merge_small)

    params = make_params(args.preset, **overrides)
    print(f"extract-palette {png_path.name} (preset={args.preset})")
    t0 = time.time()
    res = extract_palette(png_path, params)
    elapsed = time.time() - t0

    print(f"  regions   : {len(res.regions)}")
    print(f"  ink       : {res.ink_coverage_ratio * 100:.1f}%")
    print(f"  reg_cov   : {res.regions_coverage_ratio * 100:.1f}%")
    print(f"  extracted : {elapsed:.1f} s")

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    svg = render_svg(res, mode=args.mode)
    out_path.write_text(svg, encoding="utf-8")
    print(f"  -> SVG : {out_path} ({out_path.stat().st_size // 1024} KB)")
    return 0


# === Sous-commande "coloriage" : HTML interactif =============================
def _build_coloring_svg(res: PaletteResult, viewbox_w: int, viewbox_h: int) -> str:
    """SVG interactif : regions blanches cliquables + trait noir overlay."""
    parts = []
    parts.append(
        f'<rect x="0" y="0" width="{viewbox_w}" height="{viewbox_h}" fill="#ffffff"/>'
    )
    region_paths = []
    for idx, r in enumerate(res.regions, start=1):
        d = _points_to_path_d(r.points)
        r8, g8, b8 = r.color_rgb
        natural = f"rgb({r8},{g8},{b8})"
        bx, by, bw, bh = r.bbox
        cx, cy = bx + bw // 2, by + bh // 2
        region_paths.append(
            f'<path d="{d}" fill="#ffffff" stroke="#ffffff" stroke-width="1" '
            f'stroke-linejoin="round" stroke-linecap="round" '
            f'class="region" data-region-id="{r.color_id}-{r.area}" '
            f'data-idx="{idx}" data-cid="{r.color_id}" data-area="{r.area}" '
            f'data-cx="{cx}" data-cy="{cy}" '
            f'data-natural="{natural}"/>'
        )
    parts.append(f'<g class="regions">{"".join(region_paths)}</g>')
    if res.ink_svg_inline:
        inner = _extract_svg_inner(res.ink_svg_inline)
        parts.append(f'<g class="ink-layer" style="pointer-events:none;">{inner}</g>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {viewbox_w} {viewbox_h}" '
        f'preserveAspectRatio="xMidYMid meet" class="canvas-svg">\n'
        f'  {"".join(parts)}\n'
        f'</svg>'
    )


def _render_coloring_html(name: str, src_png: Path, svg_inline: str,
                          n_regions: int, ernie_palette: list, preset_name: str) -> str:
    palette_html = "".join(
        f'<button class="swatch" data-color="{c}" style="background:{c};" title="{c}"></button>'
        for c in DEFAULT_PALETTE
    )
    src_uri = f"data:image/png;base64,{base64.b64encode(src_png.read_bytes()).decode('ascii')}"
    auto_palettes = {
        "rainbow": [f"rgb({r},{g},{b})" for r, g, b in _generate_auto_palette(n_regions, "rainbow")],
        "pastel":  [f"rgb({r},{g},{b})" for r, g, b in _generate_auto_palette(n_regions, "pastel")],
        "vibrant": [f"rgb({r},{g},{b})" for r, g, b in _generate_auto_palette(n_regions, "vibrant")],
    }
    auto_palettes_json = json.dumps(auto_palettes)

    style = """
    *{box-sizing:border-box;} body{font-family:system-ui,sans-serif;background:#fafafa;color:#222;margin:0;padding:1rem;}
    h1{margin:0 0 .25rem 0;font-size:1.05rem;font-family:ui-monospace,Menlo,Consolas,monospace;}
    header{background:#fff;border:1px solid #ddd;border-radius:.5rem;padding:.75rem 1rem;margin-bottom:1rem;
           position:sticky;top:.5rem;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.04);}
    .controls{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;margin-top:.5rem;}
    .palette{display:flex;gap:.3rem;flex-wrap:wrap;margin-right:.5rem;}
    .palette label{font-size:.8rem;color:#666;margin-right:.4rem;}
    .swatch{width:34px;height:34px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #bbb;cursor:pointer;padding:0;transition:transform .05s;}
    .swatch:hover{transform:scale(1.1);} .swatch.active{box-shadow:0 0 0 3px #222;}
    .btn{background:#f0f0f0;border:1px solid #c8c8c8;border-radius:.4rem;padding:.4rem .7rem;font-size:.82rem;cursor:pointer;font-family:ui-monospace,Menlo,Consolas,monospace;}
    .btn:hover{background:#e5e5e5;} .btn.active{background:#222;color:#fff;border-color:#222;}
    main{background:#fff;border:1px solid #ddd;border-radius:.5rem;padding:1rem;max-width:920px;margin:0 auto;}
    .canvas{background:#fff;border:1px solid #eee;border-radius:.3rem;overflow:hidden;}
    .canvas-svg{width:100%;height:auto;display:block;}
    .region{cursor:pointer;transition:filter .12s,opacity .12s;}
    .region:hover{filter:brightness(.85);}
    body.solution .region{pointer-events:none;}
    body.show-zones .region{stroke:#999 !important;stroke-width:0.7 !important;}
    .meta{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.75rem;color:#666;margin-top:.5rem;}
    """
    script = f"""
    let currentColor = '#e63946';
    const swatches = document.querySelectorAll('.swatch');
    swatches.forEach(s => {{ s.addEventListener('click', () => {{
        currentColor = s.dataset.color;
        swatches.forEach(x => x.classList.remove('active'));
        s.classList.add('active');
    }}); }});
    if (swatches.length) swatches[0].classList.add('active');

    const regions = document.querySelectorAll('.region');
    function setRegionColor(r, color) {{
      r.setAttribute('fill', color);
      r.setAttribute('stroke', color);
      r.dataset.user = color;
    }}
    regions.forEach(r => {{ r.addEventListener('click', e => {{
        e.stopPropagation();
        setRegionColor(r, currentColor);
    }}); }});

    document.getElementById('btn-reset').addEventListener('click', () => {{
      regions.forEach(r => {{ setRegionColor(r, '#ffffff'); delete r.dataset.user; }});
      document.body.classList.remove('solution');
      document.getElementById('btn-solution').classList.remove('active');
    }});

    const btnSolution = document.getElementById('btn-solution');
    btnSolution.addEventListener('click', () => {{
      const showing = document.body.classList.toggle('solution');
      btnSolution.classList.toggle('active', showing);
      regions.forEach(r => {{
        if (showing) {{
          r.dataset.userBackup = r.getAttribute('fill');
          r.setAttribute('fill', r.dataset.natural);
          r.setAttribute('stroke', r.dataset.natural);
        }} else {{
          const backup = r.dataset.userBackup || '#ffffff';
          r.setAttribute('fill', backup);
          r.setAttribute('stroke', backup);
        }}
      }});
    }});

    const btnZones = document.getElementById('btn-zones');
    btnZones.addEventListener('click', () => {{
      const showing = document.body.classList.toggle('show-zones');
      btnZones.classList.toggle('active', showing);
    }});

    const AUTO_PALETTES = {auto_palettes_json};
    function applyAutoPalette(name) {{
      const pal = AUTO_PALETTES[name]; if (!pal) return;
      const groups = {{}};
      regions.forEach(r => {{
        const cid = r.dataset.regionId.split('-')[0];
        if (!groups[cid]) groups[cid] = [];
        groups[cid].push(r);
      }});
      const keys = Object.keys(groups).sort((a,b) => parseInt(a) - parseInt(b));
      keys.forEach((cid, idx) => {{
        const color = pal[idx % pal.length];
        groups[cid].forEach(r => setRegionColor(r, color));
      }});
    }}
    document.getElementById('btn-rainbow').addEventListener('click', () => applyAutoPalette('rainbow'));
    document.getElementById('btn-pastel').addEventListener('click', () => applyAutoPalette('pastel'));
    document.getElementById('btn-vibrant').addEventListener('click', () => applyAutoPalette('vibrant'));
    """
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"/><title>Coloriage — {html_escape.escape(name)}</title><style>{style}</style></head>
<body><header>
<h1>Coloriage : {html_escape.escape(name)}</h1>
<div class="meta">{n_regions} régions cliquables · preset : {html_escape.escape(preset_name)} · source : {html_escape.escape(src_png.name)}</div>
<div class="controls">
  <div class="palette"><label>couleur</label>{palette_html}</div>
  <button id="btn-reset" class="btn">tout effacer</button>
  <button id="btn-solution" class="btn">voir la solution</button>
  <button id="btn-zones" class="btn">afficher zones</button>
  <button id="btn-rainbow" class="btn">auto rainbow</button>
  <button id="btn-pastel" class="btn">auto pastel</button>
  <button id="btn-vibrant" class="btn">auto vibrant</button>
</div></header>
<main><div class="canvas">{svg_inline}</div></main>
<script>{script}</script>
</body></html>
"""


def _cmd_coloriage(args: argparse.Namespace) -> int:
    png_path = Path(args.png).expanduser().resolve()
    if not png_path.is_file():
        print(f"FAIL: PNG introuvable : {png_path}", file=sys.stderr)
        return 2
    print(f"extract-palette + coloriage : {png_path.name} (preset={args.preset})")
    overrides = {}
    if args.merge_small is not None:
        overrides["merge_small_regions_px"] = int(args.merge_small)
    params = make_params(args.preset, **overrides)
    t0 = time.time()
    res = extract_palette(png_path, params)
    elapsed = time.time() - t0
    print(f"  regions : {len(res.regions)} | ink {res.ink_coverage_ratio*100:.1f}% | "
          f"cov {res.regions_coverage_ratio*100:.1f}% | {elapsed:.1f} s")
    svg = _build_coloring_svg(res, res.width, res.height)
    html_str = _render_coloring_html(
        png_path.stem, png_path, svg, len(res.regions), res.palette, args.preset,
    )
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_str, encoding="utf-8")
    print(f"  -> HTML : {out_path} ({out_path.stat().st_size // 1024} KB)")
    return 0


# === Sous-commande "bench" : dossier complet ==================================
def _cmd_bench(args: argparse.Namespace) -> int:
    src_dir = Path(args.folder).expanduser().resolve()
    if not src_dir.is_dir():
        print(f"FAIL: dossier introuvable : {src_dir}", file=sys.stderr)
        return 2
    pngs = sorted(src_dir.glob("*.png"))
    if args.max:
        pngs = pngs[: args.max]
    if not pngs:
        print(f"Aucun PNG dans {src_dir}", file=sys.stderr)
        return 2
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    params = make_params(args.preset)
    print(f"== bench {len(pngs)} PNG (preset={args.preset}) ==")
    rows = []
    for png in pngs:
        try:
            t0 = time.time()
            res = extract_palette(png, params)
            elapsed = time.time() - t0
        except Exception as e:
            print(f"  [FAIL] {png.name}: {e}")
            continue
        row = (png.stem, len(res.regions), res.ink_coverage_ratio * 100,
               res.regions_coverage_ratio * 100, elapsed)
        rows.append(row)
        print(f"  [OK ] {png.name:<40}  reg={row[1]:<4} ink={row[2]:5.1f}%  "
              f"cov={row[3]:5.1f}%  {row[4]:.1f}s")

    # HTML resume
    body = "\n".join(
        f"<tr><td>{html_escape.escape(n)}</td><td>{r}</td>"
        f"<td>{i:.1f}%</td><td>{c:.1f}%</td><td>{e:.1f}s</td></tr>"
        for n, r, i, c, e in rows
    )
    out_path.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<title>bench extract-palette</title>
<style>body{{font-family:system-ui;margin:1rem;}}table{{border-collapse:collapse;}}
td,th{{padding:.3rem .5rem;border-bottom:1px solid #eee;}}</style></head>
<body><h1>bench extract-palette ({args.preset})</h1>
<p>{len(rows)} PNG traites sur {len(pngs)} candidats.</p>
<table><thead><tr><th>fichier</th><th>regions</th><th>ink</th><th>cov</th><th>ms</th></tr></thead>
<tbody>{body}</tbody></table></body></html>""", encoding="utf-8")
    print(f"\n-> bench HTML : {out_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extraction palette + coloriage interactif depuis PNG colorie ERNIE.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--preset", default=PROD_PRESET, choices=sorted(PRESETS.keys()),
                       help=f"Preset (def : {PROD_PRESET}). Rollback : iso_trait_v3_filled_no_gap_merged.")
        p.add_argument("--merge-small", type=int, default=None,
                       help="Override merge_small_regions_px (px).")

    p_run = sub.add_parser("run", help="Extrait + sauvegarde SVG.")
    p_run.add_argument("png", help="PNG colorie source.")
    p_run.add_argument("--out", required=True, help="Chemin SVG de sortie.")
    p_run.add_argument("--mode", default="full",
                       choices=["full", "regions", "line_only", "blank_outlined"],
                       help="Mode rendu SVG (def : full).")
    p_run.add_argument("--n-colors", type=int, default=None,
                       help="Override n_colors k-means.")
    _common(p_run)
    p_run.set_defaults(func=_cmd_run)

    p_col = sub.add_parser("coloriage", help="Genere HTML coloriage interactif.")
    p_col.add_argument("png", help="PNG colorie source.")
    p_col.add_argument("--out", required=True, help="Chemin HTML de sortie.")
    _common(p_col)
    p_col.set_defaults(func=_cmd_coloriage)

    p_b = sub.add_parser("bench", help="Bench un dossier de PNG.")
    p_b.add_argument("folder", help="Dossier source.")
    p_b.add_argument("--out", required=True, help="Chemin HTML bench resume.")
    p_b.add_argument("--max", type=int, default=None, help="Limite nb PNG.")
    _common(p_b)
    p_b.set_defaults(func=_cmd_bench)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
