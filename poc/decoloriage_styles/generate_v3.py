"""v3 "fidelite" - Regeneration ciblee low_poly + kawaii_bold (chromakey green).

Itération v3 du POC2. Repart des prompts v2 (fond chromakey green deja present)
en POUSSANT LE DETAIL pour la cible ADULTE :
  - tous styles : ajout "highly detailed, intricate" (max detail, pas de
    simplification).
  - low_poly : ajout "many small triangular facets" (facettes nombreuses).

Reutilise le client ComfyUI de generate_s0_adapted via import (aucune modif).
Params : seed=42, 1024x1024, defauts workflow turbo.

Usage :
    python poc/decoloriage_styles/generate_v3.py
    python poc/decoloriage_styles/generate_v3.py --only low_poly_dog
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "_lab" / "colored-fill-test"))
import run as comfy_client  # noqa: E402

WORKFLOW_PATH = PROJECT_ROOT / "data" / "workflows" / "ernie-image-turbo-q8-api.json"
CORPUS_DIR = HERE / "corpus_v3"

SEED = 42
WIDTH = 1024
HEIGHT = 1024
MAX_RETRIES = 2

NEGATIVE = (
    "blurry, low quality, watermark, text, signature, deformed, extra limbs, "
    "multiple subjects, photorealistic, thick heavy outlines"
)

# Prompts v3 = v2 (chromakey) + "highly detailed, intricate"
# + low_poly : "many small triangular facets".
POSITIVE = {
    "low_poly_dog": "low poly geometric art of a single dog sitting in profile, full body, triangulated polygonal facets, many small triangular facets, flat shaded triangles, sharp clean edges, vector geometric style, highly detailed, intricate, on a solid chroma key green background, centered",
    "low_poly_castle": "low poly geometric art of a single fairytale castle with towers, full view, triangulated polygonal facets, many small triangular facets, flat shaded triangles, sharp clean edges, vector geometric style, highly detailed, intricate, on a solid chroma key green background, centered",
    "low_poly_peacock": "low poly geometric art of a single peacock with tail feathers displayed, triangulated polygonal facets, many small triangular facets, flat shaded triangles, sharp clean edges, vector geometric style, highly detailed, intricate, on a solid chroma key green background, centered",
    "kawaii_bold_dog": "cute kawaii cartoon of a single dog sitting in profile, full body, fine thin clean black outlines, flat color fills, simple clean shapes, highly detailed, intricate, on a solid chroma key green background, centered",
    "kawaii_bold_castle": "cute kawaii cartoon of a single fairytale castle with towers, full view, fine thin clean black outlines, flat color fills, simple clean shapes, highly detailed, intricate, on a solid chroma key green background, centered",
    "kawaii_bold_peacock": "cute kawaii cartoon of a single peacock with tail feathers displayed, fine thin clean black outlines, flat color fills, simple clean shapes, highly detailed, intricate, on a solid chroma key green background, centered",
}

ORDER = [
    "low_poly_dog", "low_poly_castle", "low_poly_peacock",
    "kawaii_bold_dog", "kawaii_bold_castle", "kawaii_bold_peacock",
]


def generate_one(workflow_base: dict, img_id: str, n: int) -> bool:
    dst = CORPUS_DIR / f"{img_id}.png"
    for attempt in range(MAX_RETRIES + 1):
        try:
            wf = copy.deepcopy(workflow_base)
            wf["14"]["inputs"]["text"] = POSITIVE[img_id]
            wf["15"]["inputs"]["text"] = NEGATIVE
            wf["16"]["inputs"]["seed"] = SEED
            wf["13"]["inputs"]["width"] = WIDTH
            wf["13"]["inputs"]["height"] = HEIGHT
            tag = f"[{n}/6 {img_id}]" + (f" retry{attempt}" if attempt else "")
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
    print(f"== v3 fidelite/detail : {len(ids)} image(s), seed={SEED} ==")
    t_all = time.time()
    results = {}
    for n, img_id in enumerate(ids, 1):
        results[img_id] = generate_one(wf_base, img_id, n)
    n_ok = sum(results.values())
    print(f"\n{n_ok}/{len(ids)} images en {time.time()-t_all:.1f}s")
    fails = [k for k, v in results.items() if not v]
    if fails:
        print(f"echecs : {fails}")
    return 0 if n_ok == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
