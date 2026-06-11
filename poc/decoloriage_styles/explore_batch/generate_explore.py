"""EXPLORATION batch POC2 - 4 styles ornementaux x 3 sujets = 12 images.

Styles : mosaic, zellige (tuiles colorees + joints) ; mandala, zentangle
(line-art N&B natif). Cible ADULTE, coloriables par construction.

Reutilise le client ComfyUI de _lab/colored-fill-test/run.py par import (sans
modif). Params : seed=42, 1024x1024, defauts workflow turbo.

Usage :
    python poc/decoloriage_styles/explore_batch/generate_explore.py
    python poc/decoloriage_styles/explore_batch/generate_explore.py --only mosaic_dog
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

SUBJECT_DESC = {
    "dog": "dog sitting in profile, full body",
    "castle": "fairytale castle with towers, full view",
    "peacock": "peacock with tail feathers displayed",
}

NEG_TILES = (
    "blurry, low quality, watermark, text, deformed, multiple subjects, photorealistic"
)
NEG_LINEART = NEG_TILES + ", color, colored, grayscale gradient shading"

# (template, negatif) par style. {subj} = SUBJECT_DESC.
STYLE_PROMPTS = {
    "mosaic": (
        "mosaic artwork of a single {subj}, made of small colored ceramic tesserae "
        "tiles separated by dark grout lines, byzantine mosaic style, flat tile colors, "
        "highly detailed, on a solid chroma key green background, centered",
        NEG_TILES,
    ),
    "zellige": (
        "a single {subj} rendered in islamic geometric zellige style, tessellated "
        "geometric colored tiles with dark outlines, arabesque ornamental, flat tile "
        "colors, highly detailed, on a solid chroma key green background, centered",
        NEG_TILES,
    ),
    "mandala": (
        "ornamental mandala-style line art of a single {subj}, intricate symmetric "
        "decorative black linework, coloring book line art, black and white, highly "
        "detailed, white background, centered",
        NEG_LINEART,
    ),
    "zentangle": (
        "zentangle doodle line art of a single {subj}, intricate black and white tangle "
        "patterns filling the shape, coloring book line art, highly detailed, white "
        "background, centered",
        NEG_LINEART,
    ),
}

STYLES = ["mosaic", "zellige", "mandala", "zentangle"]
SUBJECTS = ["dog", "castle", "peacock"]
ORDER = [f"{s}_{subj}" for s in STYLES for subj in SUBJECTS]


def prompts_for(img_id: str) -> tuple[str, str]:
    style, subject = img_id.split("_", 1)
    tmpl, neg = STYLE_PROMPTS[style]
    return tmpl.format(subj=SUBJECT_DESC[subject]), neg


def generate_one(workflow_base: dict, img_id: str, n: int, total: int) -> bool:
    dst = CORPUS_DIR / f"{img_id}.png"
    pos, neg = prompts_for(img_id)
    for attempt in range(MAX_RETRIES + 1):
        try:
            wf = copy.deepcopy(workflow_base)
            wf["14"]["inputs"]["text"] = pos
            wf["15"]["inputs"]["text"] = neg
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
    print(f"== EXPLORATION 4 styles ornementaux : {len(ids)} image(s), seed={SEED} ==")
    t_all = time.time()
    results = {}
    for n, img_id in enumerate(ids, 1):
        results[img_id] = generate_one(wf_base, img_id, n, len(ids))
    n_ok = sum(results.values())
    print(f"\n{n_ok}/{len(ids)} images en {time.time()-t_all:.1f}s")
    fails = [k for k, v in results.items() if not v]
    if fails:
        print(f"echecs : {fails}")

    # corpus_explore.json
    corpus = {
        "gate": "POC2-exploration-ornamental",
        "frozen_at": "2026-06-11",
        "seed": SEED,
        "resolution": [WIDTH, HEIGHT],
        "styles": STYLES,
        "subjects": SUBJECTS,
        "negatives": {"tiles": NEG_TILES, "lineart": NEG_LINEART},
        "images": [],
    }
    for img_id in ORDER:
        pos, neg = prompts_for(img_id)
        style, subject = img_id.split("_", 1)
        corpus["images"].append({
            "id": img_id, "style": style, "subject": subject,
            "positive": pos, "negative": neg,
            "generated": bool(results.get(img_id, (CORPUS_DIR / f"{img_id}.png").exists())),
        })
    (HERE / "corpus_explore.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"corpus_explore.json ecrit ({len(ORDER)} entrees)")
    return 0 if n_ok == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
