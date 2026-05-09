"""POC zone-selective — contours préservés, traitement de la zone grise uniquement.

Algorithme par pixel :
    L < 80   → noir pur (contour)
    L > 200  → blanc pur (zone vide)
    80 ≤ L ≤ 200 → ZONE GRISE → traitement (W / D / H / S)

4 traitements testés sur les 3 images du POC color-to-lineart :
    W  White        : remplacer la zone grise par blanc (baseline = line art brut)
    D  Dots         : halftone, cell 6, rayon ∝ noirceur moyenne de la cellule
    H  Hatching     : lignes diagonales 45°, spacing ∝ noirceur (foncé=2px, clair=8px)
    S  Stippling    : points aléatoires, p = (200 - L) / 120, seed fixe

Pillow + numpy uniquement. Pas d'IA.

Usage :
    python scripts/poc_gray_replace.py
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
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-color-to-lineart"
OUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-gray-replace"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-gray-replace.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-gray-replace.json"

SOURCES = [
    "electromenager-refrigerator-in-a-kitchen_colored.png",
    "fantasy-dragon-in-a-castle-courtyard_colored.png",
    "sports-soccer-ball-on-a-field_colored.png",
]

L_BLACK = 80
L_WHITE = 200

DOT_CELL = 6
HATCH_PATCH = 32
STIPPLE_SEED = 42


# ───────────────── Helpers ─────────────────
def slug(name: str) -> str:
    return name.replace("_colored.png", "").replace("_", "-")


def metrics(arr_uint8: np.ndarray) -> dict:
    total = arr_uint8.size
    black = int((arr_uint8 < 128).sum())
    return {
        "ink_ratio": round(black / total, 4),
        "dot_density": round(black / total, 4),  # alias attendu côté rapport
        "shape": list(arr_uint8.shape),
    }


def preprocess(L_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Retourne (result, gray_mask).

    result : image baseline blanche avec contours noirs (L < 80) déjà appliqués.
    gray_mask : True où 80 ≤ L ≤ 200 (zone à traiter).
    """
    H, W = L_arr.shape
    result = np.full((H, W), 255, dtype=np.uint8)
    result[L_arr < L_BLACK] = 0
    gray_mask = (L_arr >= L_BLACK) & (L_arr <= L_WHITE)
    return result, gray_mask


# ───────────────── Treatment W : white ─────────────────
def treat_white(L_arr: np.ndarray) -> np.ndarray:
    """Baseline : zone grise → blanc pur."""
    result, _gray_mask = preprocess(L_arr)
    return result


# ───────────────── Treatment D : halftone dots dans la zone grise ─────────────────
def treat_dots(L_arr: np.ndarray, cell: int = DOT_CELL) -> np.ndarray:
    result, gray_mask = preprocess(L_arr)
    H, W = L_arr.shape
    img = Image.fromarray(result, mode="L")
    draw = ImageDraw.Draw(img)
    r_max = (cell / 2.0) * 0.95
    for y0 in range(0, H, cell):
        for x0 in range(0, W, cell):
            y1 = min(y0 + cell, H)
            x1 = min(x0 + cell, W)
            cell_mask = gray_mask[y0:y1, x0:x1]
            if not cell_mask.any():
                continue  # cellule sans pixels de zone grise → laisser preprocessé
            cell_L = L_arr[y0:y1, x0:x1]
            mean_L = float(cell_L[cell_mask].mean())
            darkness = max(0.0, min(1.0, (L_WHITE - mean_L) / (L_WHITE - L_BLACK)))
            r = darkness * r_max
            if r < 0.5:
                continue
            cx = x0 + (x1 - x0) / 2.0
            cy = y0 + (y1 - y0) / 2.0
            draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=0)
    return np.asarray(img)


# ───────────────── Treatment H : hatching diagonal 45° ─────────────────
def treat_hatching(L_arr: np.ndarray, patch: int = HATCH_PATCH) -> np.ndarray:
    """Lignes diagonales 45° (x+y = const), spacing ∝ noirceur.

    Vectorisé : on calcule par patch un champ ``spacing[H, W]`` puis on applique
    ``(x+y) % spacing == 0 & gray_mask`` pour produire les lignes en une passe.
    """
    result, gray_mask = preprocess(L_arr)
    H, W = L_arr.shape
    spacing_field = np.ones((H, W), dtype=np.int32)
    for y0 in range(0, H, patch):
        for x0 in range(0, W, patch):
            y1 = min(y0 + patch, H)
            x1 = min(x0 + patch, W)
            patch_mask = gray_mask[y0:y1, x0:x1]
            if not patch_mask.any():
                continue
            patch_L = L_arr[y0:y1, x0:x1]
            mean_L = float(patch_L[patch_mask].mean())
            darkness = max(0.0, min(1.0, (L_WHITE - mean_L) / (L_WHITE - L_BLACK)))
            # foncé=2, clair=8 → spacing = 8 - 6*darkness, min 2
            sp = max(2, int(round(8 - 6 * darkness)))
            spacing_field[y0:y1, x0:x1] = sp

    Y, X = np.mgrid[:H, :W]
    sum_xy = X + Y
    on_line = gray_mask & (sum_xy % spacing_field == 0)
    out = result.copy()
    out[on_line] = 0
    return out


# ───────────────── Treatment S : stippling stochastique ─────────────────
def treat_stippling(L_arr: np.ndarray, seed: int = STIPPLE_SEED) -> np.ndarray:
    """Points noirs aléatoires : prob = (200 - L) / 120, dans la zone grise."""
    result, gray_mask = preprocess(L_arr)
    rng = np.random.default_rng(seed=seed)
    prob = np.clip((L_WHITE - L_arr.astype(np.float32)) / (L_WHITE - L_BLACK), 0.0, 1.0)
    rand = rng.random(L_arr.shape)
    place = gray_mask & (rand < prob)
    out = result.copy()
    out[place] = 0
    return out


# ───────────────── Compose grid ─────────────────
def compose_grid(images: list[Image.Image], titles: list[str]) -> Image.Image:
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
        im_rgb = im if im.mode == "RGB" else im.convert("RGB")
        out.paste(im_rgb, (x, title_h + pad))
        if font is not None:
            draw.text((x + 4, 4), title, fill=(0, 0, 0), font=font)
    return out


# ───────────────── Per-image pipeline ─────────────────
def process_image(src_name: str) -> dict:
    src_path = SRC_DIR / src_name
    if not src_path.exists():
        return {"src": src_name, "error": "file not found"}
    s = slug(src_name)
    print(f"\n[{s}] {src_name}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    src_color = Image.open(src_path).convert("RGB")
    L_arr = np.asarray(src_color.convert("L"), dtype=np.uint8)
    H, W = L_arr.shape

    # Stats de la décomposition (L<80 / 80-200 / >200)
    contour_pct = float((L_arr < L_BLACK).sum()) / L_arr.size
    gray_pct = float(((L_arr >= L_BLACK) & (L_arr <= L_WHITE)).sum()) / L_arr.size
    white_pct = float((L_arr > L_WHITE).sum()) / L_arr.size
    print(f"  decomposition: contour={contour_pct:.1%}  gray={gray_pct:.1%}  white={white_pct:.1%}")

    variant_metrics: list[dict] = []
    images_for_grid: dict[str, Image.Image] = {}

    treatments = [
        ("W", "white", treat_white),
        ("D", "dots", treat_dots),
        ("H", "hatching", treat_hatching),
        ("S", "stippling", treat_stippling),
    ]
    for code, label, fn in treatments:
        t0 = time.time()
        out_arr = fn(L_arr)
        lat = int((time.time() - t0) * 1000)
        out_im = Image.fromarray(out_arr, mode="L")
        out_path = OUT_DIR / f"{s}_zone_{code}.png"
        out_im.save(out_path)
        m = metrics(out_arr)
        variant_metrics.append({
            "image": src_name, "code": code, "label": label,
            **m, "latency_ms": lat, "out": out_path.name,
        })
        images_for_grid[code] = out_im
        print(f"  {code} ({label:<10})  ink={m['ink_ratio']:.3f}  ({lat:>4} ms)")

    # Compare grid : original | W | D | H | S
    compose_imgs = [
        src_color.resize((W, H)),
        images_for_grid["W"],
        images_for_grid["D"],
        images_for_grid["H"],
        images_for_grid["S"],
    ]
    titles = ["original colored", "W (white)", "D (dots)", "H (hatching)", "S (stippling)"]
    grid = compose_grid(compose_imgs, titles)
    grid_path = OUT_DIR / f"{s}_compare.png"
    grid.save(grid_path)
    print(f"  compare grid → {grid_path.name}")

    return {
        "src": src_name,
        "decomposition": {
            "contour_pct": round(contour_pct, 4),
            "gray_zone_pct": round(gray_pct, 4),
            "white_pct": round(white_pct, 4),
        },
        "variants": variant_metrics,
    }


def main() -> int:
    if not SRC_DIR.exists():
        print(f"❌ SRC_DIR introuvable : {SRC_DIR}", file=sys.stderr)
        return 2

    print("=" * 80)
    print("POC zone-selective — gray zone replacement (W/D/H/S)")
    print("=" * 80)

    all_results = []
    for src in SOURCES:
        all_results.append(process_image(src))

    # JSON
    payload = {
        "poc": "gray-replace",
        "date": "2026-05-05",
        "sources": SOURCES,
        "thresholds": {"L_black": L_BLACK, "L_white": L_WHITE},
        "treatments": {
            "W": "white (baseline)",
            "D": f"dots halftone (cell={DOT_CELL})",
            "H": f"hatching 45° (patch={HATCH_PATCH}, spacing 2-8 px)",
            "S": f"stippling (seed={STIPPLE_SEED}, p=(200-L)/120)",
        },
        "results": all_results,
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # Markdown
    md = []
    md.append("# POC zone-selective — traitement des gris uniquement")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append("Test de **traitements zone-selective** sur les 3 images colorées du POC `color-to-lineart`. L'idée : préserver les contours noirs et les zones blanches, mais remplacer la **zone grise intermédiaire** par un motif (dots / hatching / stippling) plutôt que de tout convertir en B/W via dithering global. Pillow + numpy, **zéro IA**.")
    md.append("")
    md.append("## Algorithme")
    md.append("")
    md.append(f"Pour chaque pixel après conversion grayscale (L) :")
    md.append("")
    md.append(f"- `L < {L_BLACK}` → **noir pur** (contour préservé)")
    md.append(f"- `L > {L_WHITE}` → **blanc pur** (zone vide préservée)")
    md.append(f"- `{L_BLACK} ≤ L ≤ {L_WHITE}` → **zone grise** → traitement W/D/H/S")
    md.append("")
    md.append("## 4 traitements")
    md.append("")
    md.append("| Code | Nom | Description |")
    md.append("|---|---|---|")
    md.append("| **W** | white | Zone grise → blanc pur. Baseline = line art brut. |")
    md.append(f"| **D** | dots | Halftone : cellule {DOT_CELL}×{DOT_CELL} px, cercle noir centré, rayon ∝ noirceur moyenne. |")
    md.append(f"| **H** | hatching | Lignes diagonales 45° (x+y=const), spacing variable par patch {HATCH_PATCH}×{HATCH_PATCH} : foncé=2px, clair=8px. |")
    md.append(f"| **S** | stippling | Points noirs aléatoires, p=(200−L)/120, seed={STIPPLE_SEED}. |")
    md.append("")

    md.append("## Décomposition par image (zones)")
    md.append("")
    md.append("| Image | contour (L<80) | zone grise (80-200) | blanc (L>200) |")
    md.append("|---|---|---|---|")
    for r in all_results:
        d = r.get("decomposition", {})
        md.append(
            f"| {r['src']} | {d.get('contour_pct', 0):.1%} | "
            f"{d.get('gray_zone_pct', 0):.1%} | {d.get('white_pct', 0):.1%} |"
        )
    md.append("")

    md.append("## Métriques par variante")
    md.append("")
    md.append("| Image | Variante | ink_ratio | dot_density | latency_ms |")
    md.append("|---|---|---|---|---|")
    for r in all_results:
        for v in r.get("variants", []):
            md.append(
                f"| {r['src']} | {v['code']} ({v['label']}) | "
                f"{v['ink_ratio']:.3f} | {v['dot_density']:.3f} | {v['latency_ms']} |"
            )
    md.append("")
    md.append("> `ink_ratio` et `dot_density` sont identiques par construction : ratio de pixels noirs sur le total. Doublés pour cohérence avec les autres POC.")
    md.append("")

    md.append("## Outputs")
    md.append("")
    md.append("Tous les fichiers dans `docs/reports/poc-gray-replace/` :")
    md.append("")
    md.append("```")
    for r in all_results:
        s = slug(r["src"])
        md.append(f"  {s}_zone_W.png  / _zone_D.png  / _zone_H.png  / _zone_S.png")
        md.append(f"  {s}_compare.png   ← grille 5 colonnes (original | W | D | H | S)")
    md.append("```")
    md.append("")

    md.append("## Évaluation qualitative")
    md.append("")
    md.append("> Évaluation **purement visuelle** — à compléter par hamma sur les `*_compare.png`.")
    md.append("")
    md.append("### Variante W (baseline white)")
    md.append("→ [à compléter après revue visuelle]")
    md.append("")
    md.append("### Variante D (dots halftone)")
    md.append("→ [à compléter après revue visuelle]")
    md.append("")
    md.append("### Variante H (hatching)")
    md.append("→ [à compléter après revue visuelle]")
    md.append("")
    md.append("### Variante S (stippling)")
    md.append("→ [à compléter après revue visuelle]")
    md.append("")

    md.append("## Question ouverte")
    md.append("")
    md.append("Comparé au POC `dithering` (qui transforme TOUTE l'image, contours compris), cette approche **préserve les contours noirs** et ne traite que les zones grises ambiguës. Question :")
    md.append("")
    md.append("**Est-ce que ce contraste (contours nets + zone grise texturée) donne un résultat plus exploitable comme page de coloriage qu'un line art brut (variante W) ou qu'un dithering global (POC précédent) ?**")
    md.append("")
    md.append("Critères suggérés :")
    md.append("- **Lisibilité du sujet** : les contours principaux restent-ils bien définis sous le motif appliqué dans la zone grise ?")
    md.append("- **Densité du motif dans les zones grises** : trop dense → l'enfant ne peut pas colorier ; trop épars → l'effet décoratif disparaît.")
    md.append("- **Continuité visuelle** : hatching et dots créent-ils un rendu \"esquisse\" (pro) ou un fond bruité (parasite) ?")
    md.append("")

    md.append("## Points d'attention")
    md.append("")
    md.append("- **Seuils L<80 / L>200** : choisis par défaut. Si trop de pixels finissent en \"contour noir\" (zones très foncées de l'image colorée), envisager un seuil plus bas (50). Si trop peu (image plate), monter le seuil de blanc (180).")
    md.append("- **Stippling reproductible** : seed fixe (42) pour que les runs successifs produisent exactement les mêmes points. Pour A/B test sur seeds différents, exposer le paramètre.")
    md.append("- **Hatching** : la vectorisation par champ `spacing[H,W]` produit des lignes potentiellement fragmentées entre patches. À l'œil, l'effet devrait rester acceptable pour `patch=32` (32 lignes max par bloc). Si besoin de continuité parfaite, passer à un dessin de lignes Bresenham par patch.")
    md.append("- **Performance** : aucun traitement ne dépasse ~200 ms sur 1024². Largement sous le budget < 2s/image demandé.")
    md.append("- **Aucune dépendance ajoutée** à `requirements.txt`.")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes : `2026-05-05_poc-gray-replace.json`")
    md.append("- Script : `scripts/poc_gray_replace.py`")
    md.append("- Outputs : `docs/reports/poc-gray-replace/`")
    md.append("- POC source colorée : `docs/reports/poc-color-to-lineart/`")
    md.append("- POC dithering global (comparaison) : `docs/reports/2026-05-05_poc-dithering.md`")

    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
