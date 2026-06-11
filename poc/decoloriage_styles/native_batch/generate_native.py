"""POC2 EXPLORATION - sujets NATIFS - 4 styles ornementaux x 3 sujets = 12 images.

Principe : on ne force AUCUN sujet figuratif arbitraire (pas dog/castle/peacock).
Chaque style est genere dans sa nature, en line-art a CONTOURS NOIRS sur FOND
BLANC (= page de coloriage par construction). N&B, pas de chromakey.

Reutilise le client ComfyUI de _lab/colored-fill-test/run.py par import (sans
modif). Params : seed=42, 1024x1024, defauts workflow turbo.

Usage :
    python poc/decoloriage_styles/native_batch/generate_native.py
    python poc/decoloriage_styles/native_batch/generate_native.py --only zellige_star
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "_lab" / "colored-fill-test"))
import run as comfy_client  # noqa: E402

WORKFLOW_PATH = PROJECT_ROOT / "data" / "workflows" / "ernie-image-turbo-q8-api.json"
CORPUS_DIR = HERE / "corpus"

SEED = 42
WIDTH = 1024
HEIGHT = 1024
MAX_RETRIES = 2

NEGATIVE = (
    "color, colored, grayscale shading, gradient, photo, photorealistic, blurry, "
    "watermark, text, signature, low quality, deformed"
)

# 12 prompts NATIFS (positif). Negatif commun ci-dessus.
PROMPTS = {
    # ZELLIGE (geometrique islamique pur)
    "zellige_star": (
        "intricate islamic geometric zellige pattern, eight-pointed star tessellation, "
        "interlacing arabesque lines, perfectly symmetric, coloring book line art, "
        "bold clean black outlines, white background, centered"
    ),
    "zellige_medallion": (
        "ornate arabesque medallion, islamic geometric rosette, symmetric floral "
        "arabesque, coloring book line art, bold clean black outlines, white "
        "background, centered"
    ),
    "zellige_panel": (
        "moroccan zellige tile pattern panel, interlacing geometric tessellation, "
        "coloring book line art, bold clean black outlines, white background, centered"
    ),
    # MANDALA
    "mandala_floral": (
        "intricate floral mandala, symmetric radial flower petals, coloring book line "
        "art, bold clean black outlines, white background, centered"
    ),
    "mandala_geometric": (
        "intricate geometric mandala, symmetric radial pattern, coloring book line art, "
        "bold clean black outlines, white background, centered"
    ),
    "mandala_lotus": (
        "lotus mandala, symmetric radial lotus petals and ornaments, coloring book line "
        "art, bold clean black outlines, white background, centered"
    ),
    # ZENTANGLE (forme iconique remplie de tangles)
    "zentangle_owl": (
        "a stylized owl filled with intricate zentangle tangle patterns, coloring book "
        "line art, bold black outlines, white background, centered"
    ),
    "zentangle_feather": (
        "a large feather filled with intricate zentangle doodle patterns, coloring book "
        "line art, bold black outlines, white background, centered"
    ),
    "zentangle_butterfly": (
        "a symmetric butterfly filled with intricate zentangle tangle patterns, "
        "coloring book line art, bold black outlines, white background, centered"
    ),
    # MOSAIQUE (sujet natif romain/byzantin)
    "mosaic_fish": (
        "a fish in ancient roman mosaic style, tesserae tile grid, coloring book line "
        "art of mosaic tiles, bold black outlines, white background, centered"
    ),
    "mosaic_medallion": (
        "a geometric byzantine mosaic medallion, concentric tesserae tile rings, "
        "coloring book line art, bold black outlines, white background, centered"
    ),
    "mosaic_bird": (
        "a bird in byzantine mosaic style, tesserae tiles, coloring book line art, "
        "bold black outlines, white background, centered"
    ),
}

STYLES = ["zellige", "mandala", "zentangle", "mosaic"]
# ordre d'apparition stable par style
ORDER = [
    "zellige_star", "zellige_medallion", "zellige_panel",
    "mandala_floral", "mandala_geometric", "mandala_lotus",
    "zentangle_owl", "zentangle_feather", "zentangle_butterfly",
    "mosaic_fish", "mosaic_medallion", "mosaic_bird",
]


def generate_one(workflow_base: dict, img_id: str, n: int, total: int) -> bool:
    dst = CORPUS_DIR / f"{img_id}.png"
    pos = PROMPTS[img_id]
    for attempt in range(MAX_RETRIES + 1):
        try:
            wf = copy.deepcopy(workflow_base)
            wf["14"]["inputs"]["text"] = pos
            wf["15"]["inputs"]["text"] = NEGATIVE
            wf["16"]["inputs"]["seed"] = SEED
            wf["13"]["inputs"]["width"] = WIDTH
            wf["13"]["inputs"]["height"] = HEIGHT
            tag = f"[{n}/{total} {img_id}]" + (f" retry{attempt}" if attempt else "")
            print(f"{tag} submit...", flush=True)
            t0 = time.time()
            pid = comfy_client.submit_workflow(wf)
            hist = comfy_client.wait_for_completion(pid, timeout=240)
            saved = comfy_client.download_output_image(hist, dst)
            if saved:
                print(f"  -> {dst.name} ({time.time()-t0:.1f}s)", flush=True)
                return True
            print(f"  WARN pas de PNG (pid={pid})")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL attempt {attempt}] {img_id}: {e}")
    return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="+", default=None)
    p.add_argument("--comfy-url", default=comfy_client.DEFAULT_COMFY_URL)
    args = p.parse_args(argv)

    comfy_client.COMFY_URL = args.comfy_url.rstrip("/")
    print(f"ComfyUI URL : {comfy_client.COMFY_URL}")
    if not comfy_client.check_comfy():
        print("FAIL: ComfyUI ne repond pas.", file=sys.stderr)
        return 2

    wf_base = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    wf_base.pop("__meta__", None)
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    ids = [i for i in ORDER if (not args.only or i in set(args.only))]
    print(f"== EXPLORATION sujets natifs : {len(ids)} image(s), seed={SEED} ==")
    t_all = time.time()
    results = {}
    for n, img_id in enumerate(ids, 1):
        results[img_id] = generate_one(wf_base, img_id, n, len(ids))
    n_ok = sum(results.values())
    print(f"\n{n_ok}/{len(ids)} images en {time.time()-t_all:.1f}s")
    fails = [k for k, v in results.items() if not v]
    if fails:
        print(f"echecs : {fails}")

    # corpus_native.json
    corpus = {
        "gate": "POC2-exploration-native-subjects",
        "frozen_at": "2026-06-12",
        "seed": SEED,
        "resolution": [WIDTH, HEIGHT],
        "principle": (
            "sujets natifs adaptes au style, line-art contours noirs sur fond blanc, "
            "N&B, pas de chromakey"
        ),
        "styles": STYLES,
        "negative": NEGATIVE,
        "images": [],
    }
    for img_id in ORDER:
        style = img_id.split("_", 1)[0]
        subject = img_id.split("_", 1)[1]
        corpus["images"].append({
            "id": img_id, "style": style, "subject": subject,
            "positive": PROMPTS[img_id], "negative": NEGATIVE,
            "generated": bool(results.get(img_id, (CORPUS_DIR / f"{img_id}.png").exists())),
        })
    (HERE / "corpus_native.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"corpus_native.json ecrit ({len(ORDER)} entrees)")
    return 0 if n_ok == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
