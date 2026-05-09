"""POC seed variance — stabilité de qualité d'ERNIE sur seeds aléatoires.

En prod les seeds ne sont pas fixes : il faut connaître la variance pour calibrer
le retry automatique. Ce POC mesure la dispersion qualité concept par concept
sur des seeds reproductibles.

Concepts × #seeds :
- soccer × 10 (anatomie, le plus sensible — 3 jambes)
- dragon × 10 (couleurs résiduelles)
- cat × 5 (tier intermédiaire)
- hammer × 5 (contrôle, doit être stable)

Total : 30 images. Params figés : euler 8s normal cfg=1.0 1024×1024 denoise=1.0.
Négatifs : soccer = anatomy validé ; autres = baseline (vide).
Prompts : v2 JSON pour soccer/dragon/cat/hammer.

Injection : workflow JSON brut (data/workflows/ernie-image-turbo-q8-api.json),
suppression __meta__, modifications uniquement node 14 text / node 15 text /
node 16 seed. Pas d'overrides_map ni de sanitize_public_workflow_inputs —
ce POC vise la stabilité du backend, pas la mécanique du contrat.

Output : docs/reports/poc-seed-variance/ — images au fil de l'eau + index
poc-seed-variance.json mis à jour après chaque image (color_ratio, ink_ratio,
vision verdict). Pas de rapport MD : annotation humaine ensuite via
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-seed-variance.

Usage :
    python scripts/poc_seed_variance.py
"""
from __future__ import annotations

import base64
import copy
import io
import json
import random
import sys
import time
import uuid
import urllib.parse
import urllib.request
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

V2_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain-v2.json"
WORKFLOW_JSON = PROJECT_ROOT / "data" / "workflows" / "ernie-image-turbo-q8-api.json"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-seed-variance"
INDEX_JSON = OUTPUT_DIR / "poc-seed-variance.json"

# Seeds reproductibles : random.Random(2026) dans cet ordre exact, pour que ce
# POC soit ré-exécutable bit-pour-bit (modulo la non-déterminisme ComfyUI/cuda).
rng = random.Random(2026)
SEEDS: dict[str, list[int]] = {
    "soccer": [rng.randint(0, 2**32 - 1) for _ in range(10)],
    "dragon": [rng.randint(0, 2**32 - 1) for _ in range(10)],
    "cat":    [rng.randint(0, 2**32 - 1) for _ in range(5)],
    "hammer": [rng.randint(0, 2**32 - 1) for _ in range(5)],
}

# Mapping concept → name_en dans v2 JSON
V2_NAMES = {
    "soccer": "Soccer Ball on a Field",
    "dragon": "Dragon in a Castle Courtyard",
    "cat":    "Cat in a Library",
    "hammer": "Hammer on a Workbench",
}

# Négatif anatomy validé (soccer uniquement)
NEG_ANATOMY = (
    "extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, "
    "wrong number of limbs, six fingers, deformed feet, no motion"
)
NEG_BASELINE = ""   # baseline vide pour dragon/cat/hammer

NEGATIVES = {
    "soccer": NEG_ANATOMY,
    "dragon": NEG_BASELINE,
    "cat":    NEG_BASELINE,
    "hammer": NEG_BASELINE,
}

# Vision QC — mêmes paramètres que les POCs précédents
VISION_MODEL = "qwen3.5:9b"
VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete", "has_text"'
)
VISION_TIMEOUT = 240


def load_prompts_from_v2() -> dict[str, str]:
    """Récupère les prompts depuis v2 JSON pour les 4 concepts."""
    v2 = json.loads(V2_JSON.read_text(encoding="utf-8"))
    by_name = {r["concept"].get("name_en"): r.get("final_prompt", "")
               for r in v2.get("results", []) if isinstance(r, dict)}
    out: dict[str, str] = {}
    for concept, name_en in V2_NAMES.items():
        prompt = by_name.get(name_en)
        if not prompt:
            raise RuntimeError(f"Prompt v2 introuvable pour {concept!r} (name_en={name_en!r})")
        out[concept] = prompt.strip()
    return out


def load_workflow_raw() -> dict:
    """Charge le workflow JSON brut, supprime __meta__. Pas d'overrides_map."""
    data = json.loads(WORKFLOW_JSON.read_text(encoding="utf-8-sig"))
    data.pop("__meta__", None)
    return data


def make_workflow(*, base: dict, positive_prompt: str, negative_prompt: str, seed: int) -> dict:
    """Copie le workflow et patche uniquement node 14 text / node 15 text / node 16 seed."""
    wf = copy.deepcopy(base)
    wf["14"]["inputs"]["text"] = positive_prompt
    wf["15"]["inputs"]["text"] = negative_prompt if negative_prompt else " "
    wf["16"]["inputs"]["seed"] = int(seed)
    return wf


def submit_and_poll(client: ComfyClient, workflow: dict) -> dict:
    """Soumet et attend la fin. Retourne l'entrée d'historique."""
    prompt_id = client.submit_prompt(workflow)
    history = client.poll_until_done(prompt_id)
    return {"prompt_id": prompt_id, "history": history}


def download_first_image(client: ComfyClient, history: dict, dest: Path) -> dict:
    """Télécharge la première image de l'historique vers dest."""
    images = client.extract_output_images(history)
    if not images:
        raise RuntimeError("Aucune image dans l'historique ComfyUI")
    first = images[0]
    client.download_image(
        filename=first["filename"],
        dest=dest,
        subfolder=first.get("subfolder", ""),
        folder_type=first.get("type", "output"),
    )
    return first


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
    print("POC seed variance — soccer×10, dragon×10, cat×5, hammer×5 (30 images)", flush=True)
    print("=" * 100, flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1

    prompts = load_prompts_from_v2()
    base_workflow = load_workflow_raw()

    print(f"\nComfyUI : {client.base_url}", flush=True)
    print("Params fixes : euler 8s normal cfg=1.0 1024×1024 denoise=1.0 (déjà dans le workflow JSON)", flush=True)
    print(f"Output dir   : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Index JSON   : {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print(flush=True)
    print("Seeds générés (random.Random(2026)) :", flush=True)
    for c, seeds in SEEDS.items():
        print(f"  {c:<8} ({len(seeds)} seeds) : {seeds}", flush=True)
    print(flush=True)

    # Index pré-rempli, mis à jour après chaque image
    plan = []
    for concept, seeds in SEEDS.items():
        for i, seed in enumerate(seeds, 1):
            short = str(seed)[-6:]
            fname = f"{concept}_var{i:02d}_s{short}_08s_normal_euler_cfg10.png"
            plan.append({
                "concept": concept,
                "var_index": i,
                "seed": int(seed),
                "seed_short": short,
                "filename": fname,
            })
    index: dict = {
        "poc": "seed-variance",
        "date": "2026-05-06",
        "comfy_url": client.base_url,
        "ollama_base_url": OLLAMA_BASE_URL,
        "vision_model": VISION_MODEL,
        "params_fixes": {
            "sampler_name": "euler",
            "steps": 8,
            "scheduler": "normal",
            "cfg": 1.0,
            "width": 1024,
            "height": 1024,
            "denoise": 1.0,
        },
        "negatives_used": NEGATIVES,
        "seeds_recipe": "random.Random(2026); soccer:10, dragon:10, cat:5, hammer:5 (in this order)",
        "seeds": SEEDS,
        "prompts_used": {c: prompts[c] for c in V2_NAMES.keys()},
        "items_total": len(plan),
        "items": [],
    }
    # Slot vide dans l'index pour chaque image planifiée
    for entry in plan:
        index["items"].append({**entry, "status": "pending"})
    write_index(index)

    for idx_pos, entry in enumerate(plan):
        concept = entry["concept"]
        i = entry["var_index"]
        seed = entry["seed"]
        fname = entry["filename"]
        out_path = OUTPUT_DIR / fname

        positive = prompts[concept]
        negative = NEGATIVES[concept]

        wf = make_workflow(
            base=base_workflow,
            positive_prompt=positive,
            negative_prompt=negative,
            seed=seed,
        )

        rec = index["items"][idx_pos]
        rec["status"] = "running"
        rec["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_index(index)

        try:
            t0 = time.time()
            r = submit_and_poll(client, wf)
            first = download_first_image(client, r["history"], out_path)
            comfy_dt = time.time() - t0
            rec["comfy_latency_s"] = round(comfy_dt, 2)
            rec["comfy_prompt_id"] = r["prompt_id"]
            rec["image_path"] = str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            rec["comfy_filename_returned"] = first.get("filename")
        except Exception as exc:
            rec["status"] = "comfy_error"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[{concept} var{i:02d}] ❌ Comfy {rec['error']}", flush=True)
            write_index(index)
            continue

        # Histogram pre-check
        try:
            hist = histogram_check(out_path)
            rec["histogram"] = hist
        except Exception as exc:
            rec["error_histogram"] = f"{type(exc).__name__}: {exc}"

        # Vision QC
        v = call_vision_qc(out_path)
        rec["vision_qc"] = v

        # Console line — format demandé : [soccer var03] ✅ score vision=good color_ratio=0.002
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
            f"[{concept} var{i:02d}] {mark} {verdict} color_ratio={cr:.4f} "
            f"comfy={rec.get('comfy_latency_s', 0):.1f}s",
            flush=True,
        )

        rec["status"] = "done"
        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_index(index)

    # Petit résumé console final
    n_done = sum(1 for it in index["items"] if it.get("status") == "done")
    n_err = sum(1 for it in index["items"] if it.get("status") == "comfy_error")
    n_good = sum(
        1 for it in index["items"]
        if isinstance(it.get("vision_qc"), dict) and it["vision_qc"].get("verdict") == "good"
    )
    n_poor = sum(
        1 for it in index["items"]
        if isinstance(it.get("vision_qc"), dict) and it["vision_qc"].get("verdict") == "poor"
    )
    print(flush=True)
    print(f"Total : {n_done}/{len(plan)} générées · {n_err} erreurs · "
          f"vision good={n_good} · vision poor={n_poor}", flush=True)
    print(f"\nIndex JSON → {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Annotation humaine : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-seed-variance", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
