"""POC sampler benchmark — exploration steps × scheduler.

Pour chaque concept (soccer / refrigerator / dragon), explore la grille :
  steps in {4, 8, 12, 20} x scheduler in {normal, karras}
cfg=1.0, sampler=euler, denoise=1.0 fixes (defaults Ernie Turbo Q8).

3 concepts x 4 steps x 2 schedulers = 24 images. Chaque image :
  - sauvegardee sur disque immediatement apres generation ComfyUI
  - QC Pillow histogram + vision qwen3.5:9b
  - entree JSON metriques mise a jour incrementalement (resilience crash)

Naming :
  {concept}_{steps:02d}s_{scheduler}_{sampler_name}_cfg{cfg_int}_{seed_short}.png
ex. soccer_08s_normal_euler_cfg10_074319.png

Injection : JSON brut, modifie UNIQUEMENT node 14 (positive), node 15 (negative
ou " " si vide), node 16 (seed/steps/scheduler). Tous les autres champs
(cfg, sampler_name, denoise, width, height, batch_size) restent ceux du JSON
data/workflows/ernie-image-turbo-q8-api.json (parite 1:1 avec l'UI).

Output :
  - docs/reports/poc-sampler-benchmark/<filename>.png
  - docs/reports/poc-sampler-benchmark/poc-sampler-benchmark.json (metriques par filename)

Pas de grille auto, pas de rapport MD auto. Les agregats et la decision se font
apres en fonction des observations.

Usage :
    python scripts/poc_sampler_benchmark.py
    python scripts/poc_sampler_benchmark.py --only soccer
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
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-sampler-benchmark"
METRICS_JSON = OUTPUT_DIR / "poc-sampler-benchmark.json"

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

# ───────────────── Grille parametres ─────────────────
STEPS_GRID = [4, 8, 12, 20]
SCHEDULER_GRID = ["normal", "karras"]
CFG = 1.0
SAMPLER_NAME = "euler"
DENOISE = 1.0

# ───────────────── Negatives ─────────────────
NEG_BASELINE = (
    "shading, gradients, color fills, shadows, gray tones, watercolor, painting, "
    "photo, realistic, 3D render, blurry, low quality, text, watermark, signature, logo"
)

NEG_SOCCER_ANATOMY = (
    "extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, "
    "wrong number of limbs, six fingers, deformed feet, no motion"
)

# ───────────────── Concepts ─────────────────
# match_keyword : substring dans concept.name_en (lowercase) du chain JSON
CONCEPTS: dict[str, dict] = {
    "soccer":       {"seed": 1038277875074319, "negative": NEG_SOCCER_ANATOMY, "match_keyword": "soccer"},
    "refrigerator": {"seed": 42002,            "negative": NEG_BASELINE,        "match_keyword": "refrigerator"},
    "dragon":       {"seed": 42003,            "negative": NEG_BASELINE,        "match_keyword": "dragon"},
}


# ───────────────── Helpers ─────────────────
def load_chain_positives() -> dict[str, str]:
    """Charge les positive prompts (final_prompt) pour les 3 concepts cibles."""
    data = json.loads(CHAIN_JSON.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for r in data.get("results", []):
        name_en = (r.get("concept", {}).get("name_en") or "").lower()
        for key, conf in CONCEPTS.items():
            if conf["match_keyword"] in name_en and key not in out:
                out[key] = r.get("final_prompt") or ""
                break
    missing = [k for k in CONCEPTS if k not in out]
    if missing:
        raise RuntimeError(f"Concepts manquants dans chain JSON : {missing}")
    return out


def build_filename(concept: str, steps: int, scheduler: str, cfg: float, seed: int) -> str:
    cfg_int = int(cfg * 10)
    seed_short = str(seed)[-6:]
    return f"{concept}_{steps:02d}s_{scheduler}_{SAMPLER_NAME}_cfg{cfg_int}_{seed_short}.png"


# ───────────────── ComfyUI submission ─────────────────
def submit_to_comfy(
    client: ComfyClient,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    steps: int,
    scheduler: str,
) -> str:
    """Soumission ComfyUI direct -- parite 1:1 avec l'UI.

    Charge le JSON brut, retire __meta__, ne modifie QUE :
      - node 14 inputs.text  = positive_prompt
      - node 15 inputs.text  = negative_prompt (ou laisse " " du JSON si vide)
      - node 16 inputs.seed  = seed
      - node 16 inputs.steps = steps
      - node 16 inputs.scheduler = scheduler
    Tous les autres champs (cfg, sampler_name, denoise, width, height, batch_size)
    restent strictement ceux du fichier JSON.
    """
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    workflow = json.loads(wf_path.read_text(encoding="utf-8"))
    workflow.pop("__meta__", None)

    workflow["14"]["inputs"]["text"] = positive_prompt
    neg_clean = (negative_prompt or "").strip()
    if neg_clean:
        workflow["15"]["inputs"]["text"] = negative_prompt
    workflow["16"]["inputs"]["seed"] = int(seed)
    workflow["16"]["inputs"]["steps"] = int(steps)
    workflow["16"]["inputs"]["scheduler"] = scheduler

    return client.submit_prompt(workflow)


def generate_image(
    client: ComfyClient,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    steps: int,
    scheduler: str,
    out_path: Path,
) -> dict:
    t0 = time.time()
    try:
        prompt_id = submit_to_comfy(client, positive_prompt, negative_prompt, seed, steps, scheduler)
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
        return {
            "ok": True,
            "comfy_latency_s": round(time.time() - t0, 2),
            "comfy_prompt_id": prompt_id,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "comfy_latency_s": round(time.time() - t0, 2),
        }


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
        return {"json_ok": False, "error": f"{type(exc).__name__}: {exc}", "latency_s": round(time.time() - t0, 2)}


# ───────────────── Metrics IO ─────────────────
def load_metrics() -> dict:
    if METRICS_JSON.exists():
        try:
            return json.loads(METRICS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "poc": "sampler-benchmark",
        "workflow_template": WORKFLOW_TEMPLATE,
        "vision_model": VISION_MODEL,
        "fixed_params": {"cfg": CFG, "sampler_name": SAMPLER_NAME, "denoise": DENOISE},
        "grid": {"steps": STEPS_GRID, "scheduler": SCHEDULER_GRID},
        "concepts": {k: {"seed": v["seed"], "negative_chars": len(v["negative"])} for k, v in CONCEPTS.items()},
        "results": {},  # indexed by filename
    }


def save_metrics(metrics: dict) -> None:
    METRICS_JSON.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC sampler benchmark - steps x scheduler grid")
    print("=" * 100)

    if not CHAIN_JSON.exists():
        print(f"X Chain JSON introuvable : {CHAIN_JSON}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --only <concept> pour run cible
    only = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        if idx + 1 < len(sys.argv):
            only = sys.argv[idx + 1].strip().lower()
            if only not in CONCEPTS:
                print(f"X --only doit etre dans {list(CONCEPTS)}, recu '{only}'", file=sys.stderr)
                return 1

    targets = [only] if only else list(CONCEPTS)
    if only:
        print(f"\n-> Mode --only : {only}")

    positives = load_chain_positives()

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"\nComfyUI OK : {client.base_url}")
    print(f"Workflow   : {WORKFLOW_TEMPLATE}  ·  Vision QC : {VISION_MODEL}")
    print(f"Fixed      : cfg={CFG} sampler={SAMPLER_NAME} denoise={DENOISE}")
    print(f"Grid       : steps={STEPS_GRID} x scheduler={SCHEDULER_GRID}")
    n_total = len(targets) * len(STEPS_GRID) * len(SCHEDULER_GRID)
    print(f"Total runs : {len(targets)} concepts x {len(STEPS_GRID)} x {len(SCHEDULER_GRID)} = {n_total} images")

    metrics = load_metrics()

    n_done = 0
    for concept in targets:
        conf = CONCEPTS[concept]
        seed = conf["seed"]
        negative = conf["negative"]
        positive = positives[concept]
        for steps in STEPS_GRID:
            for scheduler in SCHEDULER_GRID:
                n_done += 1
                fname = build_filename(concept, steps, scheduler, CFG, seed)
                out_path = OUTPUT_DIR / fname
                tag = f"[{concept} {steps:02d}s/{scheduler}]"
                print(f"\n[{n_done:02d}/{n_total}] {tag} -> {fname}", flush=True)

                gen = generate_image(client, positive, negative, seed, steps, scheduler, out_path)
                if not gen.get("ok"):
                    print(f"  {tag} X Comfy: {gen.get('error')} ({gen['comfy_latency_s']}s)", flush=True)
                    metrics["results"][fname] = {
                        "concept": concept, "steps": steps, "scheduler": scheduler,
                        "cfg": CFG, "sampler_name": SAMPLER_NAME, "denoise": DENOISE,
                        "seed": seed, "negative_chars": len(negative),
                        **gen,
                    }
                    save_metrics(metrics)
                    continue

                hist = histogram_check(out_path)
                vqc = call_vision_qc(out_path)
                verdict = vqc.get("verdict") if vqc.get("json_ok") else "?"
                color = hist["color_ratio"]
                print(
                    f"  {tag} OK {fname} - color_ratio={color:.3f} vision={verdict} "
                    f"(gen {gen['comfy_latency_s']}s)",
                    flush=True,
                )

                metrics["results"][fname] = {
                    "concept": concept,
                    "steps": steps,
                    "scheduler": scheduler,
                    "cfg": CFG,
                    "sampler_name": SAMPLER_NAME,
                    "denoise": DENOISE,
                    "seed": seed,
                    "negative_chars": len(negative),
                    "ok": True,
                    "comfy_latency_s": gen["comfy_latency_s"],
                    "comfy_prompt_id": gen.get("comfy_prompt_id"),
                    "histogram": hist,
                    "vision_qc": vqc,
                }
                save_metrics(metrics)

    print(f"\nDone -> {METRICS_JSON.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
