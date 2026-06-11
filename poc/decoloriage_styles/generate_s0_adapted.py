"""S0-pivot-adapted - Corpus croise styles coloriage-adaptes (decoloriage-styles).

Pivot du POC2 : au lieu de styles durs (manga/realiste/peinture/3d), on teste
4 styles concus pour etre coloriables PAR CONSTRUCTION : low_poly, stained_glass,
papercut, kawaii_bold. 3 sujets : dog, castle, peacock => 12 PNG.

Reutilise le client ComfyUI de generate_s0.py / _lab/colored-fill-test/run.py.
Parametres sampler = defauts du workflow turbo (euler/8/cfg1.0/1024), seed=42.
Le style vient UNIQUEMENT du prompt.

Usage :
    python poc/decoloriage_styles/generate_s0_adapted.py
    python poc/decoloriage_styles/generate_s0_adapted.py --only low_poly_dog kawaii_bold_castle
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

# Reutilise le client ComfyUI du POC1 (import, pas copier-coller).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "_lab" / "colored-fill-test"))
import run as comfy_client  # noqa: E402

WORKFLOW_PATH = PROJECT_ROOT / "data" / "workflows" / "ernie-image-turbo-q8-api.json"
OUT_DIR = Path(__file__).parent
CORPUS_DIR = OUT_DIR / "corpus_adapted"
DEFAULT_COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

SEED = 42
WIDTH = 1024
HEIGHT = 1024
FROZEN_AT = "2026-06-11"

SUBJECTS = ["dog", "castle", "peacock"]
STYLES = ["low_poly", "stained_glass", "papercut", "kawaii_bold"]

NEGATIVE = (
    "blurry, low quality, jpeg artifacts, watermark, text, signature, "
    "deformed, extra limbs, multiple subjects, photorealistic, photo"
)

# 12 prompts positifs (fournis tels quels par le brief S0-pivot-adapted).
POSITIVE = {
    "low_poly_dog": "low poly geometric art of a single dog sitting in profile, full body, triangulated polygonal facets, flat shaded triangles, sharp clean edges, vector geometric style, plain background, centered",
    "low_poly_castle": "low poly geometric art of a single fairytale castle with towers, full view, triangulated polygonal facets, flat shaded triangles, sharp clean edges, vector geometric style, plain background, centered",
    "low_poly_peacock": "low poly geometric art of a single peacock with tail feathers displayed, triangulated polygonal facets, flat shaded triangles, sharp clean edges, vector geometric style, plain background, centered",
    "stained_glass_dog": "stained glass window illustration of a single dog sitting in profile, full body, bold black leading outlines separating flat colored glass panes, mosaic, luminous, plain background, centered",
    "stained_glass_castle": "stained glass window illustration of a single fairytale castle with towers, full view, bold black leading outlines separating flat colored glass panes, mosaic, luminous, plain background, centered",
    "stained_glass_peacock": "stained glass window illustration of a single peacock with tail feathers displayed, bold black leading outlines separating flat colored glass panes, mosaic, luminous, plain background, centered",
    "papercut_dog": "papercut craft illustration of a single dog sitting in profile, full body, layered flat cut-paper shapes, clean crisp edges, paper collage style, plain background, centered",
    "papercut_castle": "papercut craft illustration of a single fairytale castle with towers, full view, layered flat cut-paper shapes, clean crisp edges, paper collage style, plain background, centered",
    "papercut_peacock": "papercut craft illustration of a single peacock with tail feathers displayed, layered flat cut-paper shapes, clean crisp edges, paper collage style, plain background, centered",
    "kawaii_bold_dog": "cute kawaii cartoon of a single dog sitting in profile, full body, bold thick black outlines, flat color fills, simple clean shapes, sticker style, plain background, centered",
    "kawaii_bold_castle": "cute kawaii cartoon of a single fairytale castle with towers, full view, bold thick black outlines, flat color fills, simple clean shapes, sticker style, plain background, centered",
    "kawaii_bold_peacock": "cute kawaii cartoon of a single peacock with tail feathers displayed, bold thick black outlines, flat color fills, simple clean shapes, sticker style, plain background, centered",
}

MAX_RETRIES = 2


def build_slots() -> list[dict]:
    """Construit les 12 slots ordonnes (style-major, sujet-minor)."""
    slots = []
    n = 0
    for style in STYLES:
        for subject in SUBJECTS:
            n += 1
            img_id = f"{style}_{subject}"
            slots.append({
                "slot": n,
                "subject": subject,
                "style": style,
                "id": img_id,
                "path": f"corpus_adapted/{img_id}.png",
                "prompt": POSITIVE[img_id],
                "negative": NEGATIVE,
            })
    return slots


def generate_one(workflow_base: dict, slot: dict) -> bool:
    """Genere une image avec retry <=2. Retourne True si PNG sauve."""
    img_id = slot["id"]
    dst = CORPUS_DIR / f"{img_id}.png"
    for attempt in range(MAX_RETRIES + 1):
        try:
            wf = copy.deepcopy(workflow_base)
            wf["14"]["inputs"]["text"] = slot["prompt"]
            wf["15"]["inputs"]["text"] = slot["negative"]
            wf["16"]["inputs"]["seed"] = SEED
            wf["13"]["inputs"]["width"] = WIDTH
            wf["13"]["inputs"]["height"] = HEIGHT

            tag = f"[{slot['slot']:02d}/12 {img_id}]" + (f" retry{attempt}" if attempt else "")
            print(f"{tag} submit...")
            t0 = time.time()
            pid = comfy_client.submit_workflow(wf)
            hist = comfy_client.wait_for_completion(pid, timeout=240)
            saved = comfy_client.download_output_image(hist, dst)
            elapsed = time.time() - t0
            if saved:
                print(f"  -> {dst.name} ({elapsed:.1f} s)")
                return True
            print(f"  WARN: pas de PNG (pid={pid})")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL attempt {attempt}] {img_id}: {e}")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S0-pivot-adapted corpus croise 3x4 via ERNIE.")
    parser.add_argument("--only", nargs="+", default=None,
                        help="Sous-ensemble d'ids (ex: low_poly_dog kawaii_bold_castle).")
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    args = parser.parse_args(argv)

    comfy_client.COMFY_URL = args.comfy_url.rstrip("/")
    print(f"ComfyUI URL : {comfy_client.COMFY_URL}")
    if not comfy_client.check_comfy():
        print("FAIL: ComfyUI ne repond pas.", file=sys.stderr)
        return 2

    workflow_base = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    workflow_base.pop("__meta__", None)

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    slots = build_slots()
    if args.only:
        slots = [s for s in slots if s["id"] in set(args.only)]

    print(f"== S0-pivot-adapted : {len(slots)} image(s), seed={SEED} ==")
    t_all = time.time()
    results: dict[str, bool] = {}
    for slot in slots:
        results[slot["id"]] = generate_one(workflow_base, slot)
    total_elapsed = time.time() - t_all

    # corpus_adapted.json gele (tous les 12 slots, path=null si echec).
    all_slots = build_slots()
    images = []
    for s in all_slots:
        ok = results.get(s["id"], None)
        entry = dict(s)
        if ok is False:
            entry["path"] = None
        images.append(entry)

    corpus = {
        "version": 1,
        "frozen_at": FROZEN_AT,
        "gate": "S0-pivot-adapted",
        "source": "ComfyUI ERNIE turbo q8 (generation POC2 decoloriage-styles, pivot styles adaptes)",
        "ernie_workflow": "data/workflows/ernie-image-turbo-q8-api.json",
        "sampler_defaults": "euler / steps=8 / cfg=1.0 / scheduler=normal / 1024x1024 (defauts workflow turbo, non retunes)",
        "styles": STYLES,
        "subjects": SUBJECTS,
        "no_flat_colors": False,
        "pivot_note": "styles coloriage-adaptes par construction (low_poly/stained_glass/papercut/kawaii_bold) au lieu de styles durs",
        "seed_policy": f"seed fixe={SEED} pour les 12 images (reproductible)",
        "images": images,
    }
    corpus_path = OUT_DIR / "corpus_adapted.json"
    corpus_path.write_text(json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")

    n_ok = sum(1 for v in results.values() if v)
    fails = [k for k, v in results.items() if not v]
    print(f"\n{n_ok}/{len(slots)} images generees en {total_elapsed:.1f} s")
    if fails:
        print(f"echecs : {fails}")
    print(f"corpus_adapted.json : {corpus_path}")
    return 0 if n_ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
