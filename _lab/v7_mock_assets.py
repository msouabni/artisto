"""V7 — Génère des assets MOCK par planche à la convention verrouillée.

Convention (verrouillée) :
    {slug-planche}/{id-style}.png   ← source / affichage (~800px)
    {slug-planche}/{id-style}.svg   ← impression (mock)

Règles de distribution des styles (cf. brief V7 + seed styles rimalab-v2) :
  - ``classique`` : OBLIGATOIRE + en premier, sur les 10 planches.
  - ``briques``   : profils [enfant, ado, adulte] → posé partout SAUF profil:'facile'.
  - ``zentangle`` : profils [ado, adulte] → SEULEMENT sur planches ado/adulte,
                    JAMAIS facile/enfant.

Les visuels RÉELS sont du track Hamma : ici on émet de simples plaques mock
(rectangle + label) en PNG + un SVG d'impression mock. Aucun réseau, aucun LLM.

Usage :
    PYTHONPATH=src python _lab/v7_mock_assets.py --out _lab/v7_assets
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

# Profil par planche (défaut 'enfant' ; 'facile' pour la planche tout-petit ;
# 'ado' pour démontrer zentangle). Couvre les 3 cas de distribution.
PLANCHES: dict[str, str] = {
    "baleine": "enfant",
    "poisson-facile": "facile",     # jeunes enfants → zentangle/briques interdits
    "tortue-de-mer": "enfant",
    "hippocampe": "enfant",
    "crabe": "enfant",
    "poisson-rouge": "enfant",
    "pieuvre": "enfant",
    "baleine-bleue": "ado",         # ado → zentangle autorisé
    "meduse": "ado",                # ado → zentangle autorisé
    "poisson-rigolo": "enfant",
}

# Couleur d'accent par style (pour distinguer visuellement les plaques mock).
STYLE_ACCENT = {
    "classique": (40, 40, 40),
    "briques": (180, 90, 50),
    "zentangle": (60, 60, 120),
}


def styles_for_profil(profil: str) -> list[str]:
    """Styles admissibles pour un profil de planche (classique en premier)."""
    styles = ["classique"]
    if profil != "facile":          # briques : enfant/ado/adulte (pas facile)
        styles.append("briques")
    if profil in ("ado", "adulte"):  # zentangle : ado/adulte seulement
        styles.append("zentangle")
    return styles


def _mock_png(path: Path, slug: str, style: str, size: int = 800) -> None:
    accent = STYLE_ACCENT.get(style, (90, 90, 90))
    img = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    # Cadre + diagonale + sujet stylisé : juste un repère visuel mock.
    d.rectangle([20, 20, size - 20, size - 20], outline=accent, width=8)
    d.ellipse([size * 0.25, size * 0.25, size * 0.75, size * 0.75], outline=accent, width=6)
    if style == "briques":
        for y in range(120, size - 120, 60):
            for x in range(120, size - 120, 100):
                d.rectangle([x, y, x + 80, y + 40], outline=accent, width=3)
    elif style == "zentangle":
        for r in range(40, 320, 28):
            d.ellipse([size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r],
                      outline=accent, width=2)
    d.text((40, size - 60), f"MOCK {slug} / {style}", fill=accent)
    img.save(path, "PNG")


def _mock_svg(path: Path, slug: str, style: str) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" '
        'width="800" height="800">'
        '<rect x="20" y="20" width="760" height="760" fill="none" '
        'stroke="#222" stroke-width="6"/>'
        '<circle cx="400" cy="400" r="200" fill="none" stroke="#222" stroke-width="4"/>'
        f'<text x="40" y="760" font-size="24" fill="#222">MOCK PRINT {slug} / {style}</text>'
        '</svg>'
    )
    path.write_text(svg, encoding="utf-8")


def generate(out_root: Path) -> dict[str, list[str]]:
    out_root.mkdir(parents=True, exist_ok=True)
    summary: dict[str, list[str]] = {}
    for slug, profil in PLANCHES.items():
        styles = styles_for_profil(profil)
        d = out_root / slug
        d.mkdir(parents=True, exist_ok=True)
        for style in styles:
            _mock_png(d / f"{style}.png", slug, style)
            _mock_svg(d / f"{style}.svg", slug, style)
        summary[slug] = styles
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_lab/v7_assets", help="dossier racine des assets mock")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    summary = generate(out)
    print(f"Assets mock générés sous {out}")
    for slug, styles in summary.items():
        print(f"  {slug:16s} [{PLANCHES[slug]:7s}] -> {styles}")
    print(f"\nTotal : {len(summary)} planches, "
          f"{sum(len(s) for s in summary.values())} variantes (png+svg).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
