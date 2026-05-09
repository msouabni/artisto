"""POC vision batch — gemma4:26b sur 6 images de coloriage.

Compare 4 stratégies d'appel API Ollama :
  1. Appels unitaires (1 image / call) — baseline
  2. Batch 3 images / call (2 calls)
  3. Batch 5 images / call (1 call de 5 + 1 call de 1)
  4. Batch 6 images / call (1 call unique)

Pour chaque config : verdicts corrects vs ground truth, issues identifiées,
latence totale + par image. Recommandation taille batch optimale.

Usage :
    python scripts/poc_vision_batch.py
"""
from __future__ import annotations

import base64
import io
import json
import re
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

from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    parse_json_response,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-vision-batch.json"
MODEL = "gemma4:26b"
CALL_TIMEOUT = 600  # batch peut être plus long
SYSTEM_PROMPT = "You are a quality control assistant for children's coloring pages."

# Ground truth importée du POC-LLM-v2
VISION_IMAGES = [
    {"path": "data/outputs/animaux_chat_collier_job_gen_1773358396932.png",
     "ground_truth": "poor", "expected_issues": ["incomplete", "not_line_art"]},
    {"path": "data/outputs/adventure_in_scooby-doo-island_job_gen_1776469080378352300_4.png",
     "ground_truth": "poor", "expected_issues": ["has_color"]},
    {"path": "data/outputs/animals_bath_cat_job_gen_1776983831725453200_3.png",
     "ground_truth": "good", "expected_issues": []},
    {"path": "data/outputs/animals_party_decor_job_gen_1776469535491823500_6.png",
     "ground_truth": "good", "expected_issues": []},
    {"path": "data/outputs/animaux_chat_biblioth_que_job_gen_1773480548607.png",
     "ground_truth": "good", "expected_issues": []},
    {"path": "data/outputs/animals_fairy_cat_job_gen_1776986811626965500_5.png",
     "ground_truth": "good", "expected_issues": []},
]


def _img_b64(path: str) -> str:
    return base64.b64encode((PROJECT_ROOT / path).read_bytes()).decode("ascii")


def _build_user_prompt(n_images: int) -> str:
    if n_images == 1:
        return (
            "Evaluate this coloring page image quality for publication.\n"
            "Reply ONLY with a valid JSON array of 1 object, no explanation:\n"
            '[{"image_index": 1, "verdict": "good"|"poor", "confidence": 0-100, "issues": []}]\n'
            'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete"'
        )
    return (
        f"I will send you {n_images} images. For EACH image, evaluate its quality for publication.\n"
        f"Reply ONLY with a valid JSON array of {n_images} objects, in the same order as the images were sent.\n"
        "Each object format:\n"
        '{"image_index": N, "verdict": "good"|"poor", "confidence": 0-100, "issues": []}\n'
        f"image_index goes from 1 to {n_images} (1 = first image, etc.).\n"
        'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete"'
    )


def call_vision_batch(images: list[dict]) -> tuple[str, float, str | None]:
    """Appel /api/generate avec N images base64. Retourne (raw, latency_s, error)."""
    n = len(images)
    user_prompt = _build_user_prompt(n)
    payload = {
        "model": MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": user_prompt,
        "images": [_img_b64(img["path"]) for img in images],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=CALL_TIMEOUT) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
        dt = time.time() - t0
        if "error" in data and "response" not in data:
            return "", dt, f"ollama_error: {data['error']}"
        return data.get("response", ""), dt, None
    except Exception as exc:
        return "", time.time() - t0, f"{type(exc).__name__}: {exc}"


def evaluate_per_image(images: list[dict], verdicts_returned: list[dict]) -> list[dict]:
    """Aligne les verdicts retournés sur les images (par image_index 1-based)."""
    by_idx: dict[int, dict] = {}
    for v in verdicts_returned:
        if not isinstance(v, dict):
            continue
        idx = v.get("image_index")
        if isinstance(idx, int) and 1 <= idx <= len(images):
            by_idx[idx] = v
        elif isinstance(idx, str) and idx.isdigit() and 1 <= int(idx) <= len(images):
            by_idx[int(idx)] = v
    out = []
    for i, img in enumerate(images, 1):
        v = by_idx.get(i)
        if v is None:
            out.append({
                "image": img["path"], "ground_truth": img["ground_truth"],
                "expected_issues": img["expected_issues"],
                "verdict": None, "verdict_correct": None,
                "issues_returned": None, "issues_overlap_with_expected": None,
                "confidence": None, "missing_in_response": True,
            })
            continue
        verdict = v.get("verdict")
        confidence = v.get("confidence")
        issues = v.get("issues") or []
        issues_set = set(issues) if isinstance(issues, list) else set()
        expected_set = set(img["expected_issues"])
        if expected_set:
            overlap = len(issues_set & expected_set) / len(expected_set)
        else:
            overlap = 1.0 if not issues_set else 0.0  # good image : pas d'issues attendues
        out.append({
            "image": img["path"], "ground_truth": img["ground_truth"],
            "expected_issues": img["expected_issues"],
            "verdict": verdict,
            "verdict_correct": verdict == img["ground_truth"] if verdict in ("good", "poor") else False,
            "issues_returned": issues, "issues_overlap_with_expected": round(overlap, 2),
            "confidence": confidence, "missing_in_response": False,
        })
    return out


def chunked(lst: list, size: int) -> list[list]:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def run_config(label: str, batch_size: int) -> dict:
    print(f"\n{'=' * 80}\n>>> Config {label} (batch_size={batch_size})\n{'=' * 80}")
    chunks = chunked(VISION_IMAGES, batch_size)
    print(f"  {len(chunks)} batch call(s) — {[len(c) for c in chunks]} images per call")
    all_eval: list[dict] = []
    total_latency = 0.0
    call_records = []
    json_ok_count = 0
    for ci, chunk in enumerate(chunks, 1):
        print(f"  call {ci}/{len(chunks)} ({len(chunk)} images)…", end=" ", flush=True)
        raw, dt, err = call_vision_batch(chunk)
        total_latency += dt
        if err:
            print(f"ERR {err} ({dt:.1f}s)")
            call_records.append({"chunk_idx": ci, "n_images": len(chunk), "error": err, "latency_s": dt})
            for img in chunk:
                all_eval.append({
                    "image": img["path"], "ground_truth": img["ground_truth"],
                    "expected_issues": img["expected_issues"],
                    "error": err, "verdict": None, "verdict_correct": False,
                })
            continue
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            print(f"JSON⚠ {type(exc).__name__} ({dt:.1f}s)")
            call_records.append({
                "chunk_idx": ci, "n_images": len(chunk), "raw": raw,
                "json_ok": False, "json_error": str(exc), "latency_s": dt,
            })
            for img in chunk:
                all_eval.append({
                    "image": img["path"], "ground_truth": img["ground_truth"],
                    "expected_issues": img["expected_issues"],
                    "verdict": None, "verdict_correct": False, "json_ko": True,
                })
            continue
        json_ok_count += 1
        if isinstance(parsed, dict):
            # éventuellement : un dict avec une key array
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break
        verdicts = parsed if isinstance(parsed, list) else []
        ev_chunk = evaluate_per_image(chunk, verdicts)
        all_eval.extend(ev_chunk)
        ok = sum(1 for e in ev_chunk if e.get("verdict_correct"))
        miss = sum(1 for e in ev_chunk if e.get("missing_in_response"))
        print(f"OK {ok}/{len(chunk)} verdicts correct  ({dt:.1f}s)  miss={miss}")
        call_records.append({
            "chunk_idx": ci, "n_images": len(chunk), "raw": raw, "json_ok": True,
            "verdicts_returned": verdicts, "evaluations": ev_chunk, "latency_s": dt,
        })

    n_total = len(all_eval)
    correct = sum(1 for e in all_eval if e.get("verdict_correct"))
    overlap_avg = (
        sum(e.get("issues_overlap_with_expected") or 0 for e in all_eval if e.get("issues_overlap_with_expected") is not None)
        / max(1, sum(1 for e in all_eval if e.get("issues_overlap_with_expected") is not None))
    )
    missing = sum(1 for e in all_eval if e.get("missing_in_response"))
    json_kos = sum(1 for e in all_eval if e.get("json_ko"))
    summary = {
        "label": label,
        "batch_size": batch_size,
        "n_calls": len(chunks),
        "total_latency_s": round(total_latency, 2),
        "latency_per_image_s": round(total_latency / n_total, 2) if n_total else None,
        "verdicts_correct": correct,
        "n_images": n_total,
        "json_ok_calls": json_ok_count,
        "json_ko_calls": len(chunks) - json_ok_count,
        "missing_in_response": missing,
        "issues_overlap_avg": round(overlap_avg, 2),
    }
    print(f"\n  Synthèse {label}: {correct}/{n_total} verdicts correct, "
          f"{total_latency:.1f}s total, {summary['latency_per_image_s']}s/image, "
          f"json_ok {json_ok_count}/{len(chunks)}, miss={missing}, issues_overlap_avg={summary['issues_overlap_avg']}")
    return {"summary": summary, "call_records": call_records, "evaluations": all_eval}


def main() -> int:
    print("=" * 100)
    print("POC vision batch — gemma4:26b — 6 images, 4 configurations")
    print("=" * 100)
    # Vérif images existent
    missing = [img["path"] for img in VISION_IMAGES if not (PROJECT_ROOT / img["path"]).exists()]
    if missing:
        print(f"⚠ Images manquantes : {missing}", file=sys.stderr)
        return 2
    print(f"\n[Préparation] 6 images disponibles ({sum(1 for i in VISION_IMAGES if i['ground_truth']=='good')} good, "
          f"{sum(1 for i in VISION_IMAGES if i['ground_truth']=='poor')} poor)")

    bench: dict[str, dict] = {}
    bench["unit"] = run_config("unit (1×6)", batch_size=1)
    bench["batch3"] = run_config("batch 3", batch_size=3)
    bench["batch5"] = run_config("batch 5", batch_size=5)
    bench["batch6"] = run_config("batch 6 (all)", batch_size=6)

    payload = {
        "poc": "vision-batch",
        "date": "2026-05-05",
        "model": MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "n_images": len(VISION_IMAGES),
        "vision_images": VISION_IMAGES,
        "configs": bench,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # Comparatif
    print(f"\n{'=' * 80}\nCOMPARATIF FINAL\n{'=' * 80}")
    print(f"{'Config':<20} {'n_calls':<8} {'verdicts':<12} {'tot_lat':<10} {'/image':<10} {'json_ok':<8} {'miss':<6}")
    for k, b in bench.items():
        s = b["summary"]
        print(f"{s['label']:<20} {s['n_calls']:<8} {s['verdicts_correct']}/{s['n_images']:<10} "
              f"{s['total_latency_s']:>6}s  {str(s['latency_per_image_s']):>6}s  "
              f"{s['json_ok_calls']}/{s['n_calls']:<6} {s['missing_in_response']:<6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
