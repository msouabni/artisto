"""CLI vectorisation PNG -> SVG (post-ERNIE, moteur VTracer).

Deux sous-commandes :

    # Vectorise un dossier d'images en SVG de production.
    python scripts/vectorize_cli.py run <folder> --out data/svg/

    # Genere un rapport HTML auto-contenu (miniatures base64 + SVG inline).
    python scripts/vectorize_cli.py report <folder> --out report.html --max 30

Sélection du preset (default ``bw_default``) :
    --preset bw_default | bw_clean | bw_detail | bw_polygon

Overrides ponctuels (appliques par-dessus le preset) :
    --mode {spline,polygon,none}
    --filter-speckle <int>
    --corner-threshold <int>
    --splice-threshold <int>
    --path-precision <int>

Pre-clean OpenCV (opt-in — VTracer gere deja filter_speckle natif) :
    --pre-clean           active le pre-clean OpenCV
    --adaptive            seuillage adaptatif gaussian (sinon Otsu)
    --no-close            desactive la fermeture morpho
    --no-despeckle        desactive le median 3x3

Le dossier d'images est **externe au repo** (sortie ComfyUI, parfois sur une
autre machine via Tailscale). Le CLI prend donc un chemin arbitraire en
argument et ne suppose aucun emplacement par defaut cote images.
"""
from __future__ import annotations

import argparse
import base64
import html
import logging
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from services.vectorizer import (  # noqa: E402
    PRESETS,
    VectorizeParams,
    VectorizeResult,
    Vectorizer,
)

logger = logging.getLogger("vectorize_cli")


def _params_from_args(args: argparse.Namespace) -> VectorizeParams:
    """Construit les VectorizeParams en partant d'un preset + overrides CLI."""
    base = PRESETS[args.preset]
    overrides: dict = {}
    if args.mode is not None:
        overrides["mode"] = args.mode
    if args.filter_speckle is not None:
        overrides["filter_speckle"] = int(args.filter_speckle)
    if args.corner_threshold is not None:
        overrides["corner_threshold"] = int(args.corner_threshold)
    if args.splice_threshold is not None:
        overrides["splice_threshold"] = int(args.splice_threshold)
    if args.path_precision is not None:
        overrides["path_precision"] = int(args.path_precision)
    if args.pre_clean:
        overrides["pre_clean"] = True
    if args.adaptive:
        overrides["adaptive"] = True
    if args.no_close:
        overrides["close_gaps"] = False
    if args.no_despeckle:
        overrides["despeckle"] = False
    return replace(base, **overrides) if overrides else base


def _cmd_run(args: argparse.Namespace) -> int:
    src_dir = Path(args.folder).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    params = _params_from_args(args)
    vec = Vectorizer(params)
    total = 0
    ok = 0
    for res in vec.process_batch(src_dir, out_dir, limit=args.max, save_clean=False):
        total += 1
        ok += 1
        print(
            f"  {res.name}  {res.kb_in:6.1f} KB -> {res.kb_svg:6.1f} KB  "
            f"ratio={res.ratio:5.2f}  paths={res.n_paths} subpaths={res.n_subpaths}"
        )

    print(f"\n[run] {ok}/{total} vectorises vers {out_dir} (preset={args.preset}, mode={params.mode})")
    return 0 if total > 0 else 1


def _img_to_data_uri(path: Path, mime: str = "image/png") -> str:
    raw = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _svg_inline(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("<?xml"):
        text = text.split("?>", 1)[-1].lstrip()
    return text


def _render_html(cards: list[dict], src_dir: Path, params: VectorizeParams, preset_name: str) -> str:
    rows = []
    for card in cards:
        # Le bloc 'cleaned' n'apparait que si pre_clean a ete utilise.
        clean_col = ""
        if card.get("clean_data"):
            clean_col = f"""
            <figure>
              <figcaption>nettoye (pre-clean opencv)</figcaption>
              <img src="{card['clean_data']}" alt="image nettoyee" />
            </figure>
            """
        rows.append(
            f"""
        <article class="card">
          <h2>{html.escape(card['name'])}</h2>
          <div class="grid">
            <figure>
              <figcaption>raster source</figcaption>
              <img src="{card['src_data']}" alt="raster source" />
            </figure>
            {clean_col}
            <figure>
              <figcaption>SVG inline (rendu navigateur)</figcaption>
              <div class="svg-wrap">{card['svg_inline']}</div>
            </figure>
          </div>
          <table class="metrics">
            <tr><th>kb_in (PNG)</th><td>{card['kb_in']:.1f}</td></tr>
            <tr><th>kb_svg</th><td>{card['kb_svg']:.1f}</td></tr>
            <tr><th>ratio (svg/png)</th><td>{card['ratio']:.2f}</td></tr>
            <tr><th>paths</th><td>{card['n_paths']}</td></tr>
            <tr><th>subpaths (M)</th><td>{card['n_subpaths']}</td></tr>
          </table>
        </article>
        """
        )

    p = params
    params_dl = (
        f"preset={preset_name} - colormode={p.colormode} - mode={p.mode} - "
        f"filter_speckle={p.filter_speckle} - corner={p.corner_threshold} - "
        f"splice={p.splice_threshold} - path_precision={p.path_precision} "
        f"- pre_clean={p.pre_clean}"
    )

    style = """
    body{font-family:system-ui,sans-serif;background:#fafafa;color:#222;margin:1.5rem;}
    h1{margin-top:0;} header{margin-bottom:1.5rem;}
    .params{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.85rem;
            background:#fff;border:1px solid #ddd;padding:.5rem .75rem;border-radius:.4rem;}
    .card{background:#fff;border:1px solid #ddd;border-radius:.6rem;
          padding:1rem 1.25rem;margin-bottom:1.5rem;}
    .card h2{margin:0 0 .75rem 0;font-size:1.1rem;font-family:ui-monospace,Menlo,Consolas,monospace;}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;align-items:start;}
    figure{margin:0;display:flex;flex-direction:column;gap:.35rem;}
    figcaption{font-size:.75rem;color:#666;text-transform:uppercase;letter-spacing:.05em;}
    figure img,.svg-wrap{width:100%;height:auto;background:#fff;
                          border:1px solid #eee;border-radius:.3rem;display:block;}
    .svg-wrap svg{width:100%;height:auto;display:block;}
    .metrics{margin-top:.75rem;border-collapse:collapse;font-size:.85rem;}
    .metrics th{text-align:left;color:#666;font-weight:500;padding:.15rem .75rem .15rem 0;}
    .metrics td{font-family:ui-monospace,Menlo,Consolas,monospace;}
    """

    rows_html = "\n".join(rows) if rows else "<p>Aucune image vectorisee.</p>"
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<title>Rapport vectorisation - {html.escape(src_dir.name)}</title>
<style>{style}</style>
</head>
<body>
<header>
  <h1>Rapport vectorisation - {html.escape(str(src_dir))}</h1>
  <p>{len(cards)} image(s) traitee(s).</p>
  <p class="params">{html.escape(params_dl)}</p>
</header>
{rows_html}
</body>
</html>
"""


def _cmd_report(args: argparse.Namespace) -> int:
    src_dir = Path(args.folder).expanduser().resolve()
    out_html = Path(args.out).expanduser().resolve()
    out_html.parent.mkdir(parents=True, exist_ok=True)

    params = _params_from_args(args)
    vec = Vectorizer(params)

    tmp_dir = Path(tempfile.mkdtemp(prefix="vectorize_report_"))
    cards: list[dict] = []
    try:
        # save_clean=True n'a d'effet que si pre_clean est aussi True (sinon
        # aucun PNG nettoye n'est produit).
        for res in vec.process_batch(src_dir, tmp_dir, limit=args.max, save_clean=params.pre_clean):
            matches = [p for p in src_dir.iterdir() if p.stem == res.name and p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
            if not matches:
                continue
            src_png = matches[0]
            card = _build_card(res, src_png)
            cards.append(card)

        html_out = _render_html(cards, src_dir, params, args.preset)
        out_html.write_text(html_out, encoding="utf-8")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"[report] {len(cards)} image(s) -> {out_html} (preset={args.preset})")
    return 0 if cards else 1


def _build_card(res: VectorizeResult, src_png: Path) -> dict:
    card = {
        "name": res.name,
        "src_data": _img_to_data_uri(src_png),
        "svg_inline": _svg_inline(res.svg_path),
        "kb_in": res.kb_in,
        "kb_svg": res.kb_svg,
        "ratio": res.ratio,
        "n_paths": res.n_paths,
        "n_subpaths": res.n_subpaths,
        "clean_data": None,
    }
    if res.clean_path and res.clean_path.exists():
        card["clean_data"] = _img_to_data_uri(res.clean_path)
    return card


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Vectorisation PNG -> SVG via VTracer (line-art post-ERNIE).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def _add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("folder", help="Dossier source contenant les PNG/JPG.")
        sub.add_argument("--max", type=int, default=None, help="Limite de fichiers traites.")
        sub.add_argument(
            "--preset",
            choices=sorted(PRESETS.keys()),
            default="bw_default",
            help="Preset VTracer (def bw_default).",
        )
        sub.add_argument("--mode", choices=["spline", "polygon", "none"], default=None,
                         help="Mode de trace (override du preset).")
        sub.add_argument("--filter-speckle", type=int, default=None,
                         help="Seuil bruit VTracer (override du preset).")
        sub.add_argument("--corner-threshold", type=int, default=None,
                         help="Seuil de detection des coins (override).")
        sub.add_argument("--splice-threshold", type=int, default=None,
                         help="Seuil de splicing des segments (override).")
        sub.add_argument("--path-precision", type=int, default=None,
                         help="Precision des paths SVG (override).")
        sub.add_argument("--pre-clean", action="store_true",
                         help="Active le pre-clean OpenCV (Otsu / median / close).")
        sub.add_argument("--adaptive", action="store_true",
                         help="Pre-clean : seuillage adaptatif gaussien.")
        sub.add_argument("--no-close", action="store_true",
                         help="Pre-clean : desactive la fermeture morpho.")
        sub.add_argument("--no-despeckle", action="store_true",
                         help="Pre-clean : desactive le median 3x3.")

    p_run = subparsers.add_parser("run", help="Vectorise un dossier vers data/svg/.")
    _add_common(p_run)
    p_run.add_argument("--out", default="data/svg/", help="Dossier de sortie SVG.")
    p_run.set_defaults(func=_cmd_run)

    p_report = subparsers.add_parser("report", help="Rapport HTML auto-contenu.")
    _add_common(p_report)
    p_report.add_argument("--out", required=True, help="Chemin HTML de sortie.")
    p_report.set_defaults(func=_cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
