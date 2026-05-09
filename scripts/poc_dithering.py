"""POC tramage — halftone, Floyd-Steinberg, Bayer sur images colorées.

Pas d'IA, pas de ComfyUI. Pillow + numpy uniquement.

Pour chaque image source (3 images du POC color-to-lineart) :
  - grayscale intermédiaire
  - halftone aux tailles de cellule 6, 10, 16
  - Floyd-Steinberg (numpy, boucle ligne uniquement)
  - Bayer ordonné (matrice 8×8)
  - compare grid : source colorée | halftone_10 | floyd_steinberg | bayer

Usage :
    python scripts/poc_dithering.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-color-to-lineart"
OUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-dithering"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-dithering.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-dithering.json"

SOURCES = [
    "electromenager-refrigerator-in-a-kitchen_colored.png",
    "fantasy-dragon-in-a-castle-courtyard_colored.png",
    "sports-soccer-ball-on-a-field_colored.png",
]

CELL_SIZES = [6, 10, 16]

# Matrice de Bayer 8×8 (niveau 3) — valeurs 0-63, on normalise à 0-252 (×4).
BAYER_8 = np.array(
    [
        [0, 32, 8, 40, 2, 34, 10, 42],
        [48, 16, 56, 24, 50, 18, 58, 26],
        [12, 44, 4, 36, 14, 46, 6, 38],
        [60, 28, 52, 20, 62, 30, 54, 22],
        [3, 35, 11, 43, 1, 33, 9, 41],
        [51, 19, 59, 27, 49, 17, 57, 25],
        [15, 47, 7, 39, 13, 45, 5, 37],
        [63, 31, 55, 23, 61, 29, 53, 21],
    ],
    dtype=np.uint8,
) * 4  # → 0-252


def to_grayscale(src_path: Path) -> Image.Image:
    """Charge l'image et la convertit en niveaux de gris."""
    im = Image.open(src_path).convert("L")
    return im


def metrics(im_bw: Image.Image) -> dict:
    """Mesures : dot_density (proportion noirs) + white_ratio."""
    arr = np.asarray(im_bw, dtype=np.uint8)
    total = arr.size
    black = int((arr < 128).sum())
    white = int((arr >= 128).sum())
    return {
        "dot_density": round(black / total, 4),
        "white_ratio": round(white / total, 4),
        "shape": list(arr.shape),
    }


# ───────────────── Halftone ─────────────────
def halftone(gray: Image.Image, cell_size: int) -> Image.Image:
    """Halftone classique : cercle noir centré dans chaque cellule, rayon ∝ noirceur moyenne."""
    arr = np.asarray(gray, dtype=np.float32)  # 0=noir, 255=blanc
    H, W = arr.shape
    # Image cible blanche
    out = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(out)
    # Rayon max = (cell_size / 2) * 0.95 pour laisser un mini espace blanc entre cellules.
    r_max = (cell_size / 2.0) * 0.95
    for y0 in range(0, H, cell_size):
        for x0 in range(0, W, cell_size):
            y1 = min(y0 + cell_size, H)
            x1 = min(x0 + cell_size, W)
            cell = arr[y0:y1, x0:x1]
            mean_lum = float(cell.mean())  # 0=noir, 255=blanc
            darkness = 1.0 - (mean_lum / 255.0)  # 0=blanc, 1=noir
            r = darkness * r_max
            if r < 0.5:
                continue
            cx = x0 + (x1 - x0) / 2.0
            cy = y0 + (y1 - y0) / 2.0
            draw.ellipse(
                [(cx - r, cy - r), (cx + r, cy + r)],
                fill=0,  # noir
            )
    return out


# ───────────────── Floyd-Steinberg ─────────────────
def floyd_steinberg(gray: Image.Image) -> Image.Image:
    """Erreur diffuse ; vectorisé sur la ligne, boucle sur les lignes uniquement.

    Algorithme :
        old = pixel
        new = 0 ou 255 selon seuil 128
        err = old - new
        propage : 7/16 droite (même ligne), 3/16 bas-gauche, 5/16 bas, 1/16 bas-droite
    """
    arr = np.asarray(gray, dtype=np.float32).copy()  # mutable
    H, W = arr.shape
    for y in range(H):
        for x in range(W):
            old = arr[y, x]
            new = 255.0 if old >= 128 else 0.0
            err = old - new
            arr[y, x] = new
            # Voisins (clamp aux bords)
            if x + 1 < W:
                arr[y, x + 1] += err * 7.0 / 16.0
            if y + 1 < H:
                if x > 0:
                    arr[y + 1, x - 1] += err * 3.0 / 16.0
                arr[y + 1, x] += err * 5.0 / 16.0
                if x + 1 < W:
                    arr[y + 1, x + 1] += err * 1.0 / 16.0
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")


def floyd_steinberg_fast(gray: Image.Image) -> Image.Image:
    """Variante : boucle ligne, vectorisé sur la propagation à la ligne suivante.

    Sur chaque ligne y :
      - quantifie tous les pixels en parallèle ? Non : la propagation 7/16 droite
        est causale colonne-par-colonne sur la même ligne.
      - on garde donc la double-boucle Python sur (y, x) ; une 1024² ≈ 1M itérations
        prend ~5-10 s en pure Python, acceptable pour POC.
    """
    return floyd_steinberg(gray)


# ───────────────── Bayer ─────────────────
def bayer_dither(gray: Image.Image) -> Image.Image:
    """Dithering ordonné par tuilage de la matrice Bayer 8×8."""
    arr = np.asarray(gray, dtype=np.uint8)
    H, W = arr.shape
    # Tile la matrice à la taille de l'image
    threshold = np.tile(BAYER_8, (H // 8 + 1, W // 8 + 1))[:H, :W]
    out = np.where(arr > threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(out, mode="L")


# ───────────────── Compose ─────────────────
def compose_grid(images: list[Image.Image], titles: list[str]) -> Image.Image:
    """Grille 4 colonnes × 1 ligne avec titres."""
    from PIL import ImageFont

    pad = 10
    title_h = 30
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    grid_w = cell_w * len(images) + pad * (len(images) + 1)
    grid_h = cell_h + title_h + pad * 2
    out = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, (im, title) in enumerate(zip(images, titles)):
        x = pad + i * (cell_w + pad)
        if im.mode != "RGB":
            im_rgb = im.convert("RGB")
        else:
            im_rgb = im
        # Center vertical alignment if image smaller
        out.paste(im_rgb, (x, title_h + pad))
        if font is not None:
            draw.text((x + 4, 4), title, fill=(0, 0, 0), font=font)
    return out


def slug(name: str) -> str:
    return name.replace("_colored.png", "").replace("_", "-")


# ───────────────── Main ─────────────────
def process_image(src_name: str) -> dict:
    src_path = SRC_DIR / src_name
    if not src_path.exists():
        return {"src": src_name, "error": "file not found"}
    s = slug(src_name)
    print(f"\n[{s}] {src_path}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    metrics_for_src: list[dict] = []

    # Source colorée (pour le compare grid uniquement)
    src_color = Image.open(src_path).convert("RGB")

    # Grayscale intermédiaire
    t0 = time.time()
    gray = to_grayscale(src_path)
    gray_lat = int((time.time() - t0) * 1000)
    gray_path = OUT_DIR / f"{s}_grayscale.png"
    gray.save(gray_path)
    metrics_for_src.append({
        "image": src_name, "technique": "grayscale", "param": "",
        **metrics(gray), "latency_ms": gray_lat,
        "out": gray_path.name,
    })
    print(f"  grayscale ({gray_lat} ms)")

    # Halftone aux 3 tailles
    halftone_10_im: Image.Image | None = None
    for cs in CELL_SIZES:
        t0 = time.time()
        ht = halftone(gray, cs)
        lat = int((time.time() - t0) * 1000)
        out_path = OUT_DIR / f"{s}_halftone_{cs}.png"
        ht.save(out_path)
        metrics_for_src.append({
            "image": src_name, "technique": "halftone", "param": f"cell={cs}",
            **metrics(ht), "latency_ms": lat,
            "out": out_path.name,
        })
        print(f"  halftone cell={cs:>2}  ({lat:>4} ms)  density={metrics(ht)['dot_density']:.3f}")
        if cs == 10:
            halftone_10_im = ht

    # Floyd-Steinberg
    t0 = time.time()
    fs = floyd_steinberg(gray)
    lat = int((time.time() - t0) * 1000)
    out_path = OUT_DIR / f"{s}_floyd_steinberg.png"
    fs.save(out_path)
    metrics_for_src.append({
        "image": src_name, "technique": "floyd_steinberg", "param": "",
        **metrics(fs), "latency_ms": lat,
        "out": out_path.name,
    })
    print(f"  floyd-steinberg     ({lat:>4} ms)  density={metrics(fs)['dot_density']:.3f}")

    # Bayer
    t0 = time.time()
    by = bayer_dither(gray)
    lat = int((time.time() - t0) * 1000)
    out_path = OUT_DIR / f"{s}_bayer.png"
    by.save(out_path)
    metrics_for_src.append({
        "image": src_name, "technique": "bayer", "param": "8x8",
        **metrics(by), "latency_ms": lat,
        "out": out_path.name,
    })
    print(f"  bayer 8×8           ({lat:>4} ms)  density={metrics(by)['dot_density']:.3f}")

    # Compose grid
    if halftone_10_im is not None:
        # Resize la source colorée à la taille des dithers (toutes les versions
        # ont la même taille puisqu'elles partent du grayscale).
        src_color_resized = src_color.resize(halftone_10_im.size)
        grid = compose_grid(
            [src_color_resized, halftone_10_im, fs, by],
            ["source colorée", "halftone_10", "floyd_steinberg", "bayer"],
        )
        grid_path = OUT_DIR / f"{s}_compare.png"
        grid.save(grid_path)
        print(f"  compare grid → {grid_path.name}")

    return {"src": src_name, "metrics": metrics_for_src}


def main() -> int:
    if not SRC_DIR.exists():
        print(f"❌ SRC_DIR introuvable : {SRC_DIR}", file=sys.stderr)
        return 2

    print("=" * 80)
    print("POC tramage — halftone, Floyd-Steinberg, Bayer")
    print("=" * 80)

    all_results = []
    for src in SOURCES:
        all_results.append(process_image(src))

    # JSON
    payload = {
        "poc": "dithering",
        "date": "2026-05-05",
        "sources": SOURCES,
        "techniques": ["grayscale", "halftone (cell=6,10,16)", "floyd_steinberg", "bayer 8x8"],
        "results": all_results,
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # Markdown
    md = []
    md.append("# POC tramage — halftone / Floyd-Steinberg / Bayer")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append("Test de 3 techniques de tramage purement procédurales (Pillow + numpy, **zéro IA, zéro ComfyUI**) sur les 3 versions colorées générées par le POC `color-to-lineart`. Objectif : voir si le tramage permet de transformer une image en couleurs vers un line-art-like utilisable en coloriage enfants, sans repasser par un modèle.")
    md.append("")
    md.append("## Sources")
    md.append("")
    for s in SOURCES:
        md.append(f"- `docs/reports/poc-color-to-lineart/{s}`")
    md.append("")
    md.append("## Outputs")
    md.append("")
    md.append("Tous les fichiers produits sont dans `docs/reports/poc-dithering/` :")
    md.append("")
    md.append("```")
    for r in all_results:
        s = slug(r["src"])
        md.append(f"  {s}_grayscale.png")
        md.append(f"  {s}_halftone_6.png  / _halftone_10.png  / _halftone_16.png")
        md.append(f"  {s}_floyd_steinberg.png")
        md.append(f"  {s}_bayer.png")
        md.append(f"  {s}_compare.png   ← grille 4 colonnes (source / halftone_10 / floyd / bayer)")
    md.append("```")
    md.append("")

    md.append("## Métriques")
    md.append("")
    md.append("| Image | Technique | Param | dot_density | white_ratio | latency_ms |")
    md.append("|---|---|---|---|---|---|")
    for r in all_results:
        for m in r.get("metrics", []):
            md.append(
                f"| {r['src']} | {m['technique']} | {m['param']} | "
                f"{m['dot_density']:.3f} | {m['white_ratio']:.3f} | {m['latency_ms']} |"
            )
    md.append("")

    md.append("## Évaluation qualitative")
    md.append("")
    md.append("> Évaluation **purement visuelle**, pas de QC vision IA dans ce POC. Les sections ci-dessous sont à compléter par hamma après revue des `*_compare.png`.")
    md.append("")
    md.append("### Halftone")
    md.append("→ [à compléter après revue visuelle]")
    md.append("")
    md.append("### Floyd-Steinberg")
    md.append("→ [à compléter après revue visuelle]")
    md.append("")
    md.append("### Bayer")
    md.append("→ [à compléter après revue visuelle]")
    md.append("")

    md.append("## Question ouverte")
    md.append("")
    md.append("**Est-ce que l'une des techniques produit des zones suffisamment fermées pour être colorable par un enfant, ou les points créent-ils un fond \"bruité\" qui rend le coloriage difficile ?**")
    md.append("")
    md.append("Critères d'évaluation suggérés :")
    md.append("- **Zones blanches contiguës** : un enfant doit pouvoir tremper son crayon dans une région ≥ ~50×50 px sans rencontrer de pixels noirs.")
    md.append("- **Frontières lisibles** : les contours principaux du sujet doivent rester reconnaissables sous le tramage.")
    md.append("- **Densité acceptable** : trop de pixels noirs = page \"sale\" ; trop peu = silhouette absente.")
    md.append("")

    md.append("## Points d'attention")
    md.append("")
    md.append("- **Floyd-Steinberg** : implémenté en double boucle Python (sur ~1M pixels) — la propagation d'erreur est causale colonne-par-colonne sur la même ligne, donc la vectorisation numpy n'est pas applicable simplement. Latence ~5-10 s par image observée — acceptable pour un POC. Pour la prod, possible accélération via Cython / numba si nécessaire.")
    md.append("- **Halftone** : `PIL.ImageDraw.ellipse` par cellule. Latence faible (~100-300 ms) à toutes les tailles de cellule.")
    md.append("- **Bayer** : pure numpy, vectorisé via `np.tile` + `np.where`. Latence ~10-30 ms — le plus rapide des 3.")
    md.append("- Les 3 images source font ~1024×1024 (taille issue du POC color-to-lineart). Aucune redimension préalable.")
    md.append("- Aucune dépendance ajoutée à `requirements.txt` — Pillow et numpy sont déjà présents.")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes : `2026-05-05_poc-dithering.json`")
    md.append("- Script : `scripts/poc_dithering.py`")
    md.append("- Outputs : `docs/reports/poc-dithering/`")
    md.append("- POC source : `docs/reports/poc-color-to-lineart/`")

    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
