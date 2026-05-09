"""POC sampler benchmark v3 -- CFG x resolution x 6 nouveaux concepts.

Trois axes independants :

  Axe 1 -- CFG : 4 concepts (hammer/cat/soccer/dragon) x cfg in {1.0, 1.5, 2.0, 3.0}
                 = 16 images. Steps=8, scheduler=normal, sampler=euler, denoise=1.0,
                 1024x1024.

  Axe 2 -- Resolution : 3 concepts (cat/soccer/dragon) x reso in
                        {512, 768, 1024}^2 = 9 images. cfg=1.0, autres params idem.

  Axe 3 -- 6 nouveaux concepts (flower/fish/castle/train/lion/house) avec
           prompts ecrits dans le script. cfg=1.0, 1024x1024, autres params idem.
           = 6 images.

Total : 31 images. ETA ~14-17 min sur RTX (~22s gen + ~6s vision QC).

Naming :
  - axe 1 (CFG) : {concept}_08s_normal_euler_cfg{int(cfg*10):02d}_{seed_short}.png
                  (cfg=1.5 -> cfg15, cfg=3.0 -> cfg30)
  - axe 2 (reso): {concept}_08s_normal_euler_cfg10_{w}x{h}_{seed_short}.png
  - axe 3 (new) : {concept}_08s_normal_euler_cfg10_{seed_short}.png

Injection JSON brut : modifie node 14 (positive), 15 (negative ou " "), 13 (width/height),
16 (seed/steps/cfg/scheduler/sampler_name). Tous les autres champs (denoise, batch_size)
restent ceux du JSON.

Output : docs/reports/poc-sampler-benchmark-v3/
  - <filename>.png
  - poc-sampler-benchmark-v3.json (metriques par filename)

Usage :
    python scripts/poc_sampler_benchmark_v3.py
    python scripts/poc_sampler_benchmark_v3.py --only-axis cfg
    python scripts/poc_sampler_benchmark_v3.py --only-axis resolution
    python scripts/poc_sampler_benchmark_v3.py --only-axis new
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import httpx  # noqa: E402

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    _supports_native_think_disable,
    parse_json_response,
)
from workers.comfy_client import ComfyClient, workflows_json_dir  # noqa: E402

# ───────────────── Paths ─────────────────
CHAIN_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain-v2.json"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-sampler-benchmark-v3"
METRICS_JSON = OUTPUT_DIR / "poc-sampler-benchmark-v3.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"
VISION_MODEL = "qwen3.5:9b"
VISION_TIMEOUT = 240
VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete", "has_text"'
)

# ───────────────── Negatives ─────────────────
NEG_BASELINE = (
    "shading, gradients, color fills, shadows, gray tones, watercolor, painting, "
    "photo, realistic, 3D render, blurry, low quality, text, watermark, signature, logo"
)

NEG_SOCCER_ANATOMY = (
    "extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, "
    "wrong number of limbs, six fingers, deformed feet, no motion"
)

# ───────────────── Concepts (chain v2) ─────────────────
CONCEPTS_FROM_CHAIN: dict[str, dict] = {
    "soccer": {"seed": 1038277875074319, "negative": NEG_SOCCER_ANATOMY, "match_keyword": "soccer ball on a field"},
    "dragon": {"seed": 42003,            "negative": NEG_BASELINE,        "match_keyword": "dragon in a castle"},
    "cat":    {"seed": 42004,            "negative": NEG_BASELINE,        "match_keyword": "cat in a library"},
    "hammer": {"seed": 42005,            "negative": NEG_BASELINE,        "match_keyword": "hammer on a workbench"},
}

# ───────────────── Concepts inline (axe 3) ─────────────────
# Pattern stricte du chain v2 : "[shot] centered on [subject] [setting], capturing a
# [mood] mood. The scene features [details], all depicted as simple shapes suitable
# for children. Style: Black-and-white line art only [...]. Technical cleanup: No text [...]"
_STYLE_TAIL = (
    "Style: Black-and-white line art only, monochrome coloring book style with thick black "
    "outlines on a pure white background, no shading, no gradients, no color fills, no filled "
    "areas. Technical cleanup: No text, no letters, no numbers, no words, no signs, no labels, "
    "no watermarks, no logos, no signatures, no written characters anywhere in the image, clean "
    "layout with clear lines for easy coloring."
)

CONCEPTS_INLINE: dict[str, dict] = {
    "flower": {
        "seed": 43001, "negative": NEG_BASELINE, "category": "nature",
        "prompt": (
            "A close-up centered on a single rose flower with stem and leaves, capturing a calm "
            "and elegant mood. The scene features a rose with layered petals at the top, a slender "
            "stem with a few thorns, two leaves on either side of the stem, and a small patch of "
            "ground at the base, all depicted as simple shapes suitable for children. " + _STYLE_TAIL
        ),
    },
    "fish": {
        "seed": 43002, "negative": NEG_BASELINE, "category": "animaux",
        "prompt": (
            "A side view centered on a tropical fish swimming in calm water, capturing a peaceful "
            "and curious mood. The scene features a fish with a rounded body, detailed scale "
            "patterns covering the entire body, large dorsal and ventral fins, a flowing tail with "
            "wavy stripes, one round eye with a clear pupil, gills near the head, and small "
            "bubbles rising around it, all depicted as simple shapes suitable for children. "
            + _STYLE_TAIL
        ),
    },
    "castle": {
        "seed": 43003, "negative": NEG_BASELINE, "category": "architecture",
        "prompt": (
            "A frontal view centered on a medieval castle with towers and battlements, capturing a "
            "majestic and adventurous mood. The scene features a large central keep, two side "
            "towers with conical roofs, crenelated stone walls, a wooden drawbridge over a moat, a "
            "portcullis gate, narrow arched windows, triangular flags on top of the towers, a "
            "stone path leading to the entrance, and a few simple clouds in the sky, all depicted "
            "as simple shapes suitable for children. " + _STYLE_TAIL
        ),
    },
    "train": {
        "seed": 43004, "negative": NEG_BASELINE, "category": "vehicule",
        "prompt": (
            "A side view centered on a steam locomotive on rails, capturing a nostalgic and "
            "energetic mood. The scene features a steam locomotive with a tall smokestack, a "
            "cylindrical boiler, large driving wheels with spokes, smaller wheels at the front, a "
            "cabin with rectangular windows for the driver, a coal tender attached behind, puffs "
            "of smoke rising from the chimney, straight railroad tracks under the train, and a few "
            "rounded hills in the background, all depicted as simple shapes suitable for children. "
            + _STYLE_TAIL
        ),
    },
    "lion": {
        "seed": 43005, "negative": NEG_BASELINE, "category": "animaux",
        "prompt": (
            "A frontal view centered on a lion sitting upright, capturing a calm and noble mood. "
            "The scene features a lion with a detailed flowing mane forming locks around its head, "
            "two large round eyes, a triangular nose, a closed muzzle with whiskers, two upright "
            "ears, two front paws resting on the ground, a tail curled to one side with a tuft of "
            "fur at the tip, and a simple straight ground line under it, all depicted as simple "
            "shapes suitable for children. " + _STYLE_TAIL
        ),
    },
    "house": {
        "seed": 43006, "negative": NEG_BASELINE, "category": "architecture",
        "prompt": (
            "A slight three-quarter perspective view centered on a single-family house with a "
            "garden, capturing a cheerful and welcoming mood. The scene features a house with a "
            "sloped pitched roof, a brick chimney with curling smoke, a wooden front door with a "
            "round knob, two windows with shutters and curtains, a small porch with two steps, a "
            "low picket fence around the front yard, a tall tree on one side, several flowers "
            "growing in the yard, a paved path leading to the door, and a smiling sun with rays "
            "in the upper sky, all depicted as simple shapes suitable for children. " + _STYLE_TAIL
        ),
    },
}

# ───────────────── Axe 1 -- CFG ─────────────────
CFG_AXIS_CONCEPTS = ["hammer", "cat", "soccer", "dragon"]
CFG_VALUES = [1.0, 1.5, 2.0, 3.0]
CFG_AXIS_FIXED = {"steps": 8, "scheduler": "normal", "sampler_name": "euler", "width": 1024, "height": 1024}

# ───────────────── Axe 2 -- Resolution ─────────────────
RESO_AXIS_CONCEPTS = ["cat", "soccer", "dragon"]
RESO_VALUES = [(512, 512), (768, 768), (1024, 1024)]
RESO_AXIS_FIXED = {"steps": 8, "scheduler": "normal", "sampler_name": "euler", "cfg": 1.0}

# ───────────────── Axe 3 -- Nouveaux concepts ─────────────────
NEW_AXIS_FIXED = {"steps": 8, "scheduler": "normal", "sampler_name": "euler",
                  "cfg": 1.0, "width": 1024, "height": 1024}


# ───────────────── Helpers ─────────────────
def load_chain_positives() -> dict[str, str]:
    """Charge les positive prompts pour les concepts venant de chain v2."""
    data = json.loads(CHAIN_JSON.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for r in data.get("results", []):
        name_en = (r.get("concept", {}).get("name_en") or "").lower()
        for key, conf in CONCEPTS_FROM_CHAIN.items():
            if conf["match_keyword"].lower() in name_en and key not in out:
                out[key] = r.get("final_prompt") or ""
                break
    missing = [k for k in CONCEPTS_FROM_CHAIN if k not in out]
    if missing:
        raise RuntimeError(f"Concepts manquants dans chain JSON : {missing}")
    return out


def seed_short(seed: int) -> str:
    return str(seed)[-6:]


def fname_cfg(concept: str, cfg: float, seed: int) -> str:
    return f"{concept}_08s_normal_euler_cfg{int(cfg * 10):02d}_{seed_short(seed)}.png"


def fname_reso(concept: str, w: int, h: int, seed: int) -> str:
    return f"{concept}_08s_normal_euler_cfg10_{w}x{h}_{seed_short(seed)}.png"


def fname_new(concept: str, seed: int) -> str:
    return f"{concept}_08s_normal_euler_cfg10_{seed_short(seed)}.png"


# ───────────────── ComfyUI submission ─────────────────
def submit_to_comfy(
    client: ComfyClient,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    steps: int,
    scheduler: str,
    sampler_name: str,
    cfg: float,
    width: int,
    height: int,
) -> str:
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    workflow = json.loads(wf_path.read_text(encoding="utf-8"))
    workflow.pop("__meta__", None)

    workflow["13"]["inputs"]["width"] = int(width)
    workflow["13"]["inputs"]["height"] = int(height)
    workflow["14"]["inputs"]["text"] = positive_prompt
    neg_clean = (negative_prompt or "").strip()
    if neg_clean:
        workflow["15"]["inputs"]["text"] = negative_prompt
    workflow["16"]["inputs"]["seed"] = int(seed)
    workflow["16"]["inputs"]["steps"] = int(steps)
    workflow["16"]["inputs"]["cfg"] = float(cfg)
    workflow["16"]["inputs"]["scheduler"] = scheduler
    workflow["16"]["inputs"]["sampler_name"] = sampler_name

    return client.submit_prompt(workflow)


def generate_image(
    client: ComfyClient,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    steps: int,
    scheduler: str,
    sampler_name: str,
    cfg: float,
    width: int,
    height: int,
    out_path: Path,
) -> dict:
    t0 = time.time()
    try:
        prompt_id = submit_to_comfy(
            client, positive_prompt, negative_prompt, seed, steps, scheduler, sampler_name,
            cfg, width, height,
        )
        history = client.poll_until_done(prompt_id)
        images = client.extract_output_images(history)
        if not images:
            raise RuntimeError("Aucune image dans l'historique ComfyUI")
        first = images[0]
        client.download_image(
            filename=first["filename"],
            dest=out_path,
            subfolder=first.get("subfolder", ""),
            folder_type=first.get("type", "output"),
        )
        return {"ok": True, "comfy_latency_s": round(time.time() - t0, 2),
                "comfy_prompt_id": prompt_id}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "comfy_latency_s": round(time.time() - t0, 2)}


# ───────────────── QC ─────────────────
def histogram_check(image_path: Path) -> dict:
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    flags = qc.get("flags") or []
    return {
        "histogram_ok": not (("strong_color" in flags) or ("noticeable_color" in flags)),
        "color_ratio": float(metrics.get("color_ratio", 0.0)),
        "white_ratio": float(metrics.get("white_ratio", 0.0)),
        "ink_ratio": float(metrics.get("ink_ratio", 0.0)),
        "flags": flags,
    }


def call_vision_qc(image_path: Path) -> dict:
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload: dict = {
        "model": VISION_MODEL, "system": VISION_SYSTEM,
        "prompt": VISION_USER_PROMPT, "images": [img_b64],
        "stream": False, "options": {"temperature": 0.0},
    }
    if _supports_native_think_disable(VISION_MODEL):
        payload["think"] = False
    t0 = time.time()
    try:
        with httpx.Client(timeout=VISION_TIMEOUT) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
        dt = round(time.time() - t0, 2)
        if "error" in data and "response" not in data:
            return {"json_ok": False, "error": data["error"], "latency_s": dt}
        raw = data.get("response", "")
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            return {"json_ok": False, "raw": raw, "json_error": str(exc), "latency_s": dt}
        if not isinstance(parsed, dict):
            return {"json_ok": False, "raw": raw, "json_error": "not a dict", "latency_s": dt}
        return {
            "json_ok": True,
            "verdict": parsed.get("quality"),
            "issues": parsed.get("issues") or [],
            "confidence": parsed.get("confidence"),
            "latency_s": dt,
        }
    except Exception as exc:
        return {"json_ok": False, "error": f"{type(exc).__name__}: {exc}",
                "latency_s": round(time.time() - t0, 2)}


# ───────────────── Metrics IO ─────────────────
def load_metrics() -> dict:
    if METRICS_JSON.exists():
        try:
            return json.loads(METRICS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    concepts_meta: dict[str, dict] = {}
    for k, v in CONCEPTS_FROM_CHAIN.items():
        concepts_meta[k] = {"seed": v["seed"], "source": "chain_v2",
                            "match_keyword": v["match_keyword"], "negative": "anatomy" if k == "soccer" else "baseline"}
    for k, v in CONCEPTS_INLINE.items():
        concepts_meta[k] = {"seed": v["seed"], "source": "inline",
                            "category": v.get("category"), "negative": "baseline"}
    return {
        "poc": "sampler-benchmark-v3",
        "workflow_template": WORKFLOW_TEMPLATE,
        "vision_model": VISION_MODEL,
        "axes": {
            "cfg": {"concepts": CFG_AXIS_CONCEPTS, "cfg_values": CFG_VALUES, "fixed": CFG_AXIS_FIXED},
            "resolution": {"concepts": RESO_AXIS_CONCEPTS, "values": RESO_VALUES, "fixed": RESO_AXIS_FIXED},
            "new_concepts": {"concepts": list(CONCEPTS_INLINE), "fixed": NEW_AXIS_FIXED},
        },
        "concepts": concepts_meta,
        "results": {},
    }


def save_metrics(metrics: dict) -> None:
    METRICS_JSON.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ───────────────── Pipeline une image ─────────────────
def run_one(
    client: ComfyClient,
    metrics: dict,
    label: str,
    fname: str,
    positive: str,
    negative: str,
    seed: int,
    steps: int,
    scheduler: str,
    sampler_name: str,
    cfg: float,
    width: int,
    height: int,
    extra_meta: dict | None = None,
) -> None:
    out_path = OUTPUT_DIR / fname
    prev = (metrics.get("results") or {}).get(fname)
    if prev and prev.get("ok") and out_path.is_file():
        print(f"  {label} skip (deja OK)", flush=True)
        return
    print(f"  {label} -> {fname}", flush=True)

    gen = generate_image(
        client, positive, negative, seed, steps, scheduler, sampler_name,
        cfg, width, height, out_path,
    )
    base_meta = {
        "concept_key": (extra_meta or {}).get("concept_key"),
        "axis": (extra_meta or {}).get("axis"),
        "steps": steps, "scheduler": scheduler, "sampler_name": sampler_name,
        "cfg": cfg, "width": width, "height": height,
        "seed": seed, "negative_chars": len(negative),
        **(extra_meta or {}),
    }
    if not gen.get("ok"):
        print(f"  {label} X Comfy: {gen.get('error')} ({gen['comfy_latency_s']}s)", flush=True)
        metrics["results"][fname] = {**base_meta, **gen}
        save_metrics(metrics)
        return

    hist = histogram_check(out_path)
    vqc = call_vision_qc(out_path)
    verdict = vqc.get("verdict") if vqc.get("json_ok") else "?"
    print(
        f"  {label} OK {fname} - color_ratio={hist['color_ratio']:.3f} vision={verdict} "
        f"(gen {gen['comfy_latency_s']}s)",
        flush=True,
    )
    metrics["results"][fname] = {
        **base_meta, "ok": True,
        "comfy_latency_s": gen["comfy_latency_s"],
        "comfy_prompt_id": gen.get("comfy_prompt_id"),
        "histogram": hist,
        "vision_qc": vqc,
    }
    save_metrics(metrics)


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC sampler benchmark v3 - CFG x resolution x new concepts")
    print("=" * 100)

    if not CHAIN_JSON.exists():
        print(f"X Chain JSON introuvable : {CHAIN_JSON}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    only_axis = None
    if "--only-axis" in sys.argv:
        idx = sys.argv.index("--only-axis")
        if idx + 1 < len(sys.argv):
            only_axis = sys.argv[idx + 1].strip().lower()
            if only_axis not in {"cfg", "resolution", "new"}:
                print(f"X --only-axis doit etre dans cfg/resolution/new, recu '{only_axis}'", file=sys.stderr)
                return 1

    chain_positives = load_chain_positives()
    all_positives: dict[str, str] = dict(chain_positives)
    for k, v in CONCEPTS_INLINE.items():
        all_positives[k] = v["prompt"]

    all_concepts: dict[str, dict] = {}
    for k, v in CONCEPTS_FROM_CHAIN.items():
        all_concepts[k] = {"seed": v["seed"], "negative": v["negative"]}
    for k, v in CONCEPTS_INLINE.items():
        all_concepts[k] = {"seed": v["seed"], "negative": v["negative"]}

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1

    n_cfg = len(CFG_AXIS_CONCEPTS) * len(CFG_VALUES)
    n_reso = len(RESO_AXIS_CONCEPTS) * len(RESO_VALUES)
    n_new = len(CONCEPTS_INLINE)
    if only_axis == "cfg":   n_total = n_cfg
    elif only_axis == "resolution": n_total = n_reso
    elif only_axis == "new": n_total = n_new
    else:                    n_total = n_cfg + n_reso + n_new

    print(f"\nComfyUI OK  : {client.base_url}")
    print(f"Workflow    : {WORKFLOW_TEMPLATE}  ·  Vision QC : {VISION_MODEL}")
    print(f"Axe CFG     : {CFG_AXIS_CONCEPTS} x cfg in {CFG_VALUES} = {n_cfg}")
    print(f"Axe reso    : {RESO_AXIS_CONCEPTS} x reso in {RESO_VALUES} = {n_reso}")
    print(f"Axe new     : {list(CONCEPTS_INLINE)} = {n_new}")
    print(f"Plan        : {n_total} images" + (f" (only-axis={only_axis})" if only_axis else ""))

    metrics = load_metrics()
    n_done = 0

    # ── Axe 1 : CFG ───────────────────────────────────────────────────────────
    if only_axis in (None, "cfg"):
        for concept in CFG_AXIS_CONCEPTS:
            conf = all_concepts[concept]
            for cfg in CFG_VALUES:
                n_done += 1
                fname = fname_cfg(concept, cfg, conf["seed"])
                label = f"[{n_done:02d}/{n_total}] [cfg axis · {concept} cfg={cfg}]"
                run_one(
                    client, metrics, label, fname,
                    positive=all_positives[concept], negative=conf["negative"],
                    seed=conf["seed"],
                    steps=CFG_AXIS_FIXED["steps"], scheduler=CFG_AXIS_FIXED["scheduler"],
                    sampler_name=CFG_AXIS_FIXED["sampler_name"],
                    cfg=cfg,
                    width=CFG_AXIS_FIXED["width"], height=CFG_AXIS_FIXED["height"],
                    extra_meta={"concept_key": concept, "axis": "cfg"},
                )

    # ── Axe 2 : Resolution ────────────────────────────────────────────────────
    if only_axis in (None, "resolution"):
        for concept in RESO_AXIS_CONCEPTS:
            conf = all_concepts[concept]
            for (w, h) in RESO_VALUES:
                n_done += 1
                fname = fname_reso(concept, w, h, conf["seed"])
                label = f"[{n_done:02d}/{n_total}] [reso axis · {concept} {w}x{h}]"
                run_one(
                    client, metrics, label, fname,
                    positive=all_positives[concept], negative=conf["negative"],
                    seed=conf["seed"],
                    steps=RESO_AXIS_FIXED["steps"], scheduler=RESO_AXIS_FIXED["scheduler"],
                    sampler_name=RESO_AXIS_FIXED["sampler_name"],
                    cfg=RESO_AXIS_FIXED["cfg"],
                    width=w, height=h,
                    extra_meta={"concept_key": concept, "axis": "resolution"},
                )

    # ── Axe 3 : Nouveaux concepts ─────────────────────────────────────────────
    if only_axis in (None, "new"):
        for concept in CONCEPTS_INLINE:
            conf = all_concepts[concept]
            n_done += 1
            fname = fname_new(concept, conf["seed"])
            label = f"[{n_done:02d}/{n_total}] [new axis · {concept}]"
            run_one(
                client, metrics, label, fname,
                positive=all_positives[concept], negative=conf["negative"],
                seed=conf["seed"],
                steps=NEW_AXIS_FIXED["steps"], scheduler=NEW_AXIS_FIXED["scheduler"],
                sampler_name=NEW_AXIS_FIXED["sampler_name"],
                cfg=NEW_AXIS_FIXED["cfg"],
                width=NEW_AXIS_FIXED["width"], height=NEW_AXIS_FIXED["height"],
                extra_meta={"concept_key": concept, "axis": "new"},
            )

    print(f"\nDone -> {METRICS_JSON.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
