"""POC soccer karras — variance de seeds soccer × scheduler karras.

Hypothèse : le scheduler `karras` peut réduire le taux de `3_jambes` observé
sur soccer en `normal` (7/10 seeds en échec dans `2026-05-06_poc-seed-variance.md`).
Seul facteur changé : `scheduler="karras"` (vs `"normal"` dans le POC précédent).
Tout le reste est strictement identique : même prompt, même négatif anatomy,
mêmes 10 seeds, mêmes paramètres euler 8s cfg=1.0 1024×1024 denoise=1.0.

Source seeds + prompt : `docs/reports/poc-seed-variance/poc-seed-variance.json`
(lecture directe pour éviter toute dérive RNG).

Pas de rapport MD ici — l'analyse sera faite après annotation humaine via
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-soccer-karras

Usage :
    python scripts/poc_soccer_karras.py
"""
from __future__ import annotations

import base64
import copy
import io
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

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
from workers.comfy_client import ComfyClient  # noqa: E402

VARIANCE_INDEX = PROJECT_ROOT / "docs" / "reports" / "poc-seed-variance" / "poc-seed-variance.json"
WORKFLOW_JSON = PROJECT_ROOT / "data" / "workflows" / "ernie-image-turbo-q8-api.json"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-soccer-karras"
INDEX_JSON = OUTPUT_DIR / "poc-soccer-karras.json"

# Vision QC — mêmes paramètres que poc_seed_variance.py
VISION_MODEL = "qwen3.5:9b"
VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete", "has_text"'
)
VISION_TIMEOUT = 240

# Négatif anatomy soccer (validé) — repris à l'identique de poc_seed_variance.py
NEG_ANATOMY = (
    "extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, "
    "wrong number of limbs, six fingers, deformed feet, no motion"
)


def load_seeds_and_prompt() -> tuple[list[int], str]:
    """Lit les 10 seeds soccer + le prompt depuis l'index seed-variance."""
    if not VARIANCE_INDEX.is_file():
        raise FileNotFoundError(f"Index seed-variance introuvable : {VARIANCE_INDEX}")
    data = json.loads(VARIANCE_INDEX.read_text(encoding="utf-8"))
    seeds = data.get("seeds", {}).get("soccer")
    if not seeds or not isinstance(seeds, list) or len(seeds) != 10:
        raise RuntimeError("Clé 'seeds.soccer' manquante ou pas une liste de 10")
    prompt = data.get("prompts_used", {}).get("soccer")
    if not prompt:
        raise RuntimeError("Clé 'prompts_used.soccer' manquante")
    return [int(s) for s in seeds], prompt.strip()


def load_workflow_raw() -> dict:
    data = json.loads(WORKFLOW_JSON.read_text(encoding="utf-8-sig"))
    data.pop("__meta__", None)
    return data


def make_workflow(*, base: dict, positive_prompt: str, negative_prompt: str, seed: int) -> dict:
    """Patch direct nodes 14/15/16 avec scheduler='karras'."""
    wf = copy.deepcopy(base)
    wf["14"]["inputs"]["text"] = positive_prompt
    wf["15"]["inputs"]["text"] = negative_prompt if negative_prompt else " "
    wf["16"]["inputs"]["seed"] = int(seed)
    wf["16"]["inputs"]["steps"] = 8
    wf["16"]["inputs"]["scheduler"] = "karras"   # ← seule différence vs seed-variance
    wf["16"]["inputs"]["sampler_name"] = "euler"
    wf["16"]["inputs"]["cfg"] = 1.0
    wf["16"]["inputs"]["denoise"] = 1.0
    return wf


def histogram_check(image_path: Path) -> dict:
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    return {
        "color_ratio": float(metrics.get("color_ratio", 0.0)),
        "white_ratio": float(metrics.get("white_ratio", 0.0)),
        "ink_ratio": float(metrics.get("ink_ratio", 0.0)),
        "flags": qc.get("flags") or [],
    }


def call_vision_qc(image_path: Path) -> dict:
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload: dict = {
        "model": VISION_MODEL,
        "system": VISION_SYSTEM,
        "prompt": VISION_USER_PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    if _supports_native_think_disable(VISION_MODEL):
        payload["think"] = False
    t0 = time.time()
    try:
        with httpx.Client(timeout=VISION_TIMEOUT) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
        dt = time.time() - t0
        if "error" in data and "response" not in data:
            return {"error": data["error"], "latency_s": dt}
        raw = data.get("response", "")
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            return {"raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt}
        if not isinstance(parsed, dict):
            return {"raw": raw, "json_ok": False, "json_error": "not a dict", "latency_s": dt}
        return {
            "json_ok": True,
            "verdict": parsed.get("quality"),
            "issues": parsed.get("issues") or [],
            "confidence": parsed.get("confidence"),
            "latency_s": dt,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}


def write_index(index: dict) -> None:
    INDEX_JSON.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    print("=" * 100, flush=True)
    print("POC soccer karras — 10 seeds soccer × scheduler=karras (vs normal du seed-variance)", flush=True)
    print("=" * 100, flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1

    seeds, prompt = load_seeds_and_prompt()
    base_workflow = load_workflow_raw()

    print(f"\nComfyUI : {client.base_url}", flush=True)
    print("Params : sampler=euler, steps=8, scheduler=karras, cfg=1.0, 1024×1024, denoise=1.0", flush=True)
    print(f"Source seeds + prompt : {VARIANCE_INDEX.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Output dir : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Index JSON : {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Seeds soccer (10) : {seeds}", flush=True)
    print(flush=True)

    # Index pré-rempli, mis à jour après chaque image
    plan: list[dict] = []
    for i, seed in enumerate(seeds, 1):
        short = str(seed)[-6:]
        fname = f"soccer_var{i:02d}_s{short}_08s_karras_euler_cfg10.png"
        plan.append({
            "concept": "soccer",
            "var_index": i,
            "seed": int(seed),
            "seed_short": short,
            "filename": fname,
        })

    index: dict = {
        "poc": "soccer-karras",
        "date": "2026-05-07",
        "comfy_url": client.base_url,
        "ollama_base_url": OLLAMA_BASE_URL,
        "vision_model": VISION_MODEL,
        "params_fixes": {
            "sampler_name": "euler",
            "steps": 8,
            "scheduler": "karras",
            "cfg": 1.0,
            "width": 1024,
            "height": 1024,
            "denoise": 1.0,
        },
        "negative_used": NEG_ANATOMY,
        "source_index": str(VARIANCE_INDEX.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "seeds": {"soccer": seeds},
        "prompt_used": prompt,
        "items_total": len(plan),
        "items": [{**p, "status": "pending"} for p in plan],
    }
    write_index(index)

    for idx_pos, entry in enumerate(plan):
        i = entry["var_index"]
        seed = entry["seed"]
        fname = entry["filename"]
        out_path = OUTPUT_DIR / fname

        wf = make_workflow(
            base=base_workflow,
            positive_prompt=prompt,
            negative_prompt=NEG_ANATOMY,
            seed=seed,
        )

        rec = index["items"][idx_pos]
        rec["status"] = "running"
        rec["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_index(index)

        try:
            t0 = time.time()
            prompt_id = client.submit_prompt(wf)
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
            comfy_dt = time.time() - t0
            rec["comfy_latency_s"] = round(comfy_dt, 2)
            rec["comfy_prompt_id"] = prompt_id
            rec["image_path"] = str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            rec["comfy_filename_returned"] = first.get("filename")
        except Exception as exc:
            rec["status"] = "comfy_error"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[soccer-karras var{i:02d}] ❌ Comfy {rec['error']}", flush=True)
            write_index(index)
            continue

        # Histogram
        try:
            rec["histogram"] = histogram_check(out_path)
        except Exception as exc:
            rec["error_histogram"] = f"{type(exc).__name__}: {exc}"

        # Vision QC
        v = call_vision_qc(out_path)
        rec["vision_qc"] = v

        cr = (rec.get("histogram") or {}).get("color_ratio", 0.0)
        if v.get("error"):
            mark = "⚠"
            verdict = f"vision_err={v['error'][:40]}"
        elif not v.get("json_ok"):
            mark = "⚠"
            verdict = "vision_json_fail"
        else:
            mark = "✅" if v.get("verdict") == "good" else "⚠"
            issues = v.get("issues") or []
            issues_str = f" issues={issues}" if issues else ""
            verdict = f"vision={v.get('verdict')}{issues_str}"
        print(
            f"[soccer-karras var{i:02d}] {mark} {verdict} color_ratio={cr:.4f} "
            f"comfy={rec.get('comfy_latency_s', 0):.1f}s",
            flush=True,
        )

        rec["status"] = "done"
        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_index(index)

    n_done = sum(1 for it in index["items"] if it.get("status") == "done")
    n_err = sum(1 for it in index["items"] if it.get("status") == "comfy_error")
    n_good = sum(
        1 for it in index["items"]
        if isinstance(it.get("vision_qc"), dict) and it["vision_qc"].get("verdict") == "good"
    )
    print(flush=True)
    print(f"Total : {n_done}/{len(plan)} générées · {n_err} erreurs · vision good={n_good}", flush=True)
    print(f"\nIndex JSON → {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Annotation humaine : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-soccer-karras", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
