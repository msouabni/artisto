"""S2b - Extraction de traits par modele appris (informative-drawings) sur le
style 3D (3 sujets : dog, castle, peacock).

Lance informative-drawings (carolineec) en CPU pour 2 styles : anime_style et
contour_style. Le repo officiel test.py est cuda-only ; on importe son
Generator (model.py) et on l'execute en CPU, weights pretrained extraits du zip
Google Drive officiel.

Sortie informative-drawings = image 1 canal, ~1.0 = papier (blanc), valeurs
basses = traits. On binarise (seuil) -> couche encre 0/255 (255 = encre).

Compare aussi au fallback POC 1 (frontieres de la partition enfant en 2 poids),
mais ca c'est dans s2b_compare.py. Ici on ne produit que les couches infodraw.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torchvision.transforms as transforms
from PIL import Image

HERE = Path(__file__).resolve().parent
INFODRAW_DIR = HERE / "_models" / "informative-drawings"
sys.path.insert(0, str(INFODRAW_DIR))
from model import Generator  # noqa: E402

CKPT_DIR = INFODRAW_DIR / "checkpoints" / "model"
CORPUS = HERE / "corpus.json"
OUT_DIR = HERE / "s2_out"
RAW_DIR = OUT_DIR / "infodraw_raw"

# Tailles : informative-drawings entraine en 256, mais full-conv -> on peut
# inferer en plus grand. On garde 1024 (taille corpus) pour rester aligne avec
# le masque L<25 POC 1 (1024x1024). Resize bicubic.
INFER_SIZE = 1024

# Seuil de binarisation de la sortie infodraw (canal ~[0,1], 1=papier).
# encre = pixels SOUS le seuil. 0.5 = milieu ; on documente la couverture.
BIN_THRESHOLD = 0.5


def load_generator(style: str) -> Generator:
    net_G = Generator(3, 1, 3)
    ckpt = CKPT_DIR / style / "netG_A_latest.pth"
    state = torch.load(str(ckpt), map_location="cpu")
    net_G.load_state_dict(state)
    net_G.eval()
    return net_G


def run_style(net_G: Generator, rgb: np.ndarray) -> np.ndarray:
    """Retourne la sortie brute infodraw en float32 [0,1], shape (H, W)."""
    pil = Image.fromarray(rgb)
    tf = transforms.Compose([
        transforms.Resize(INFER_SIZE, Image.BICUBIC),
        transforms.ToTensor(),
    ])
    x = tf(pil).unsqueeze(0)  # (1,3,H,W)
    with torch.no_grad():
        out = net_G(x)  # (1,1,H,W) in [0,1]
    arr = out.squeeze().cpu().numpy().astype(np.float32)
    return arr


def binarize_ink(raw01: np.ndarray, thresh: float, target_hw: tuple[int, int]) -> np.ndarray:
    """raw01 : sortie infodraw [0,1] (1=papier). Retourne masque encre uint8
    0/255 (255 = encre) a la taille target_hw, nettoye (close+open 3x3)."""
    # encre = sous le seuil
    ink = (raw01 < thresh).astype(np.uint8)
    # Resize au format cible (nearest pour rester binaire)
    h, w = target_hw
    if ink.shape != (h, w):
        ink = cv2.resize(ink, (w, h), interpolation=cv2.INTER_NEAREST)
    k = np.ones((3, 3), np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k, iterations=1)
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, k, iterations=1)
    return (ink * 255).astype(np.uint8)


def ink_metrics(ink: np.ndarray) -> dict:
    """Mesures de couverture/proprete de la couche encre."""
    h, w = ink.shape
    total = h * w
    n_ink = int((ink > 0).sum())
    # Continuite : nb de composantes connexes de l'encre (moins = plus continu)
    n_cc, _ = cv2.connectedComponents((ink > 0).astype(np.uint8), connectivity=8)
    n_cc = int(n_cc - 1)  # retirer le fond
    return {
        "pct_ink": round(100.0 * n_ink / total, 2),
        "n_ink_px": n_ink,
        "n_ink_components": n_cc,
    }


def main() -> int:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = [it for it in data["images"] if it["style"] == "3d"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    styles = ["anime_style", "contour_style"]
    nets = {s: load_generator(s) for s in styles}
    print(f"[S2b] Generators charges (CPU) : {styles}", flush=True)

    results: dict = {}
    for item in items:
        rid = item["id"]
        src = (HERE / item["path"]).resolve()
        rgb = cv2.cvtColor(cv2.imread(str(src), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        results[rid] = {}
        for style in styles:
            t0 = time.time()
            raw01 = run_style(nets[style], rgb)
            ink = binarize_ink(raw01, BIN_THRESHOLD, (h, w))
            dt = round(time.time() - t0, 2)

            # Sauvegarde sortie brute (visuelle) + masque encre binaire.
            raw_u8 = (np.clip(raw01, 0, 1) * 255).astype(np.uint8)
            raw_u8 = cv2.resize(raw_u8, (w, h), interpolation=cv2.INTER_CUBIC)
            raw_path = RAW_DIR / f"{rid}_{style}_raw.png"
            ink_path = RAW_DIR / f"{rid}_{style}_ink.png"
            cv2.imwrite(str(raw_path), raw_u8)
            cv2.imwrite(str(ink_path), ink)

            m = ink_metrics(ink)
            m["time_s"] = dt
            m["raw_png"] = str(raw_path.relative_to(HERE)).replace("\\", "/")
            m["ink_png"] = str(ink_path.relative_to(HERE)).replace("\\", "/")
            results[rid][style] = m
            print(f"[S2b] {rid:12s} {style:14s} ink%={m['pct_ink']:6.2f} "
                  f"cc={m['n_ink_components']:5d} ({dt}s)", flush=True)

    out = {
        "branch": "S2b",
        "model": "informative-drawings (carolineec) anime_style + contour_style",
        "infer_size": INFER_SIZE,
        "bin_threshold": BIN_THRESHOLD,
        "device": "cpu",
        "results": results,
    }
    (OUT_DIR / "s2b_infodraw_stats.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nOK s2b_infodraw_stats.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
