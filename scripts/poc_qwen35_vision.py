"""POC qwen3.5:9b vision — capacité multimodale + benchmark QC sur 6 images.

Phase 1 : sonde si qwen3.5:9b sur cette instance Ollama est réellement multimodal
          (POST /api/generate avec images: [b64]). Si non, arrête et documente.
Phase 2 : si phase 1 OK, exécute le QC sur les 6 images du POC vision-batch et
          compare aux verdicts gemma4:26b déjà mesurés.

Usage :
    python scripts/poc_qwen35_vision.py
"""
from __future__ import annotations

import base64
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

from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    apply_no_think_system,
    _supports_native_think_disable,
    parse_json_response,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-qwen35-vision.json"
MODEL = "qwen3.5:9b"
GEMMA_REF = "gemma4:26b"
SYSTEM_PROMPT = "You are a quality control assistant for children's coloring pages."
QC_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete"'
)
PHASE1_PROBE_PROMPT = (
    "Describe what you see in this image in 1 short sentence. "
    "If you cannot see any image, reply with: NO_IMAGE_SEEN."
)
CALL_TIMEOUT = 240


def _img_b64(path: str) -> str:
    return base64.b64encode((PROJECT_ROOT / path).read_bytes()).decode("ascii")


def call_vision(model: str, prompt: str, system: str, image_path: str, timeout: int = CALL_TIMEOUT) -> dict:
    payload: dict = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "images": [_img_b64(image_path)],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    if _supports_native_think_disable(model):
        payload["think"] = False
    t0 = time.time()
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
        dt = time.time() - t0
        if "error" in data and "response" not in data:
            return {"error": data["error"], "latency_s": dt}
        return {"raw": data.get("response", ""), "latency_s": dt}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}


def load_images_from_v2() -> list[dict]:
    p = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-vision-batch.json"
    if not p.exists():
        # fallback : prendre le v2 benchmark
        p = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-llm-benchmark-v2.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("vision_images") or []


def gemma_results_from_v2() -> dict[str, dict]:
    """Index par chemin → record gemma4 verdict du POC-LLM-v2."""
    p = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-llm-benchmark-v2.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    vis = (data.get("vision_results_by_model") or {}).get(GEMMA_REF, {})
    out = {}
    for r in vis.get("results", []):
        out[r["image"]] = r
    return out


def evaluate_qc(parsed, gt_record: dict) -> dict:
    if not isinstance(parsed, dict):
        return {"json_ok": False}
    verdict = parsed.get("quality")
    confidence = parsed.get("confidence")
    issues = parsed.get("issues") or []
    expected = set(gt_record.get("expected_issues") or [])
    issues_set = set(issues) if isinstance(issues, list) else set()
    if expected:
        overlap = len(expected & issues_set) / len(expected)
    else:
        overlap = 1.0 if not issues_set else 0.0
    return {
        "json_ok": True,
        "verdict": verdict,
        "verdict_correct": verdict == gt_record["ground_truth"] if verdict in ("good", "poor") else False,
        "issues_returned": issues,
        "expected_issues": gt_record.get("expected_issues"),
        "issues_overlap": round(overlap, 2),
        "confidence": confidence,
    }


def phase1_probe(images: list[dict]) -> dict:
    """Sonde rapide : envoie l'image vide-texte + prompt 'décris ce que tu vois'.

    Critères de validation multimodale :
    - Pas d'erreur API.
    - Réponse non vide.
    - La réponse fait référence à une image (mots-clés "image", "see", "shows",
      "drawing", "art", "coloring", etc.) OU décrit du contenu visuel cohérent
      avec l'image probe (texte écrit sur fond blanc).
    """
    probe_image = next((i for i in images if i.get("ground_truth") == "poor"
                        and "incomplete" in (i.get("expected_issues") or [])), images[0] if images else None)
    if probe_image is None:
        return {"capability_detected": False, "error": "no probe image found"}

    print(f"\n[Phase 1] Probe sur {Path(probe_image['path']).name} (ground_truth=poor, image vide-texte)")
    print(f"  Prompt: {PHASE1_PROBE_PROMPT!r}")
    res = call_vision(MODEL, PHASE1_PROBE_PROMPT, "", probe_image["path"])
    if "error" in res:
        print(f"  ❌ ERROR: {res['error']}")
        return {
            "capability_detected": False,
            "probe_image": probe_image["path"],
            "error": res["error"],
            "latency_s": res["latency_s"],
        }

    raw = (res["raw"] or "").strip()
    print(f"  Latence : {res['latency_s']:.1f}s")
    print(f"  Réponse brute : {raw[:300]!r}")

    if not raw:
        return {
            "capability_detected": False, "probe_image": probe_image["path"],
            "raw": raw, "reason": "empty response", "latency_s": res["latency_s"],
        }
    if "NO_IMAGE_SEEN" in raw.upper():
        return {
            "capability_detected": False, "probe_image": probe_image["path"],
            "raw": raw, "reason": "model declared NO_IMAGE_SEEN", "latency_s": res["latency_s"],
        }
    # Heuristique : la réponse mentionne-t-elle un contenu visuel plausible ?
    visual_kw = ("image", "see", "shows", "depict", "drawing", "art", "page", "coloring", "blank",
                 "white", "text", "background", "picture", "photo", "void", "empty")
    raw_lc = raw.lower()
    has_visual = any(kw in raw_lc for kw in visual_kw)

    return {
        "capability_detected": has_visual,
        "probe_image": probe_image["path"],
        "raw": raw,
        "reason": "visual_keywords detected" if has_visual else "no visual content references found",
        "latency_s": res["latency_s"],
    }


def phase2_benchmark(images: list[dict]) -> list[dict]:
    print(f"\n[Phase 2] QC benchmark sur {len(images)} images (1 image / call)")
    out = []
    for idx, img in enumerate(images, 1):
        print(f"  [{idx}/{len(images)}] {Path(img['path']).name[:55]:<55} (gt={img['ground_truth']})  …", end=" ", flush=True)
        res = call_vision(MODEL, QC_USER_PROMPT, SYSTEM_PROMPT, img["path"])
        if "error" in res:
            print(f"ERR {res['error']} ({res['latency_s']:.1f}s)")
            out.append({"image": img["path"], "ground_truth": img["ground_truth"],
                        "expected_issues": img["expected_issues"],
                        "error": res["error"], "latency_s": res["latency_s"]})
            continue
        try:
            parsed = parse_json_response(res["raw"])
        except Exception as exc:
            print(f"JSON⚠ {type(exc).__name__} ({res['latency_s']:.1f}s)")
            out.append({"image": img["path"], "ground_truth": img["ground_truth"],
                        "expected_issues": img["expected_issues"],
                        "raw": res["raw"], "json_ok": False, "json_error": str(exc),
                        "latency_s": res["latency_s"]})
            continue
        ev = evaluate_qc(parsed, img)
        ok = "✓" if ev.get("verdict_correct") else "✗"
        print(f"v={ev.get('verdict')} {ok} ({res['latency_s']:.1f}s)  issues={ev.get('issues_returned')}")
        out.append({"image": img["path"], "ground_truth": img["ground_truth"],
                    "expected_issues": img["expected_issues"],
                    "raw": res["raw"], "parsed": parsed,
                    "latency_s": res["latency_s"], **ev})
    return out


def main() -> int:
    print("=" * 100)
    print(f"POC qwen3.5:9b vision — capability probe + QC benchmark")
    print("=" * 100)

    images = load_images_from_v2()
    print(f"\nImages : {len(images)} ({sum(1 for i in images if i['ground_truth']=='good')} good, "
          f"{sum(1 for i in images if i['ground_truth']=='poor')} poor)")
    if len(images) < 6:
        print("⚠ Moins de 6 images disponibles — bench partiel", file=sys.stderr)

    probe = phase1_probe(images)
    print(f"\n  → capability_detected = {probe['capability_detected']}  ({probe.get('reason', '?')})")

    benchmark_results: list[dict] = []
    summary: dict = {}
    if probe["capability_detected"]:
        benchmark_results = phase2_benchmark(images)
        valid = [r for r in benchmark_results if r.get("json_ok")]
        n = len(valid)
        correct = sum(1 for r in valid if r.get("verdict_correct"))
        avg_lat = round(sum(r["latency_s"] for r in valid) / n, 2) if n else 0
        avg_overlap = round(sum(r.get("issues_overlap", 0) or 0 for r in valid) / n, 2) if n else 0
        summary = {
            "n_images": len(benchmark_results),
            "json_ok": n,
            "verdict_correct": correct,
            "avg_latency_s": avg_lat,
            "avg_issues_overlap": avg_overlap,
        }
        print(f"\n=== Synthèse phase 2 ===")
        print(f"  JSON OK         : {n}/{len(benchmark_results)}")
        print(f"  Verdicts OK     : {correct}/{n}")
        print(f"  Avg latency     : {avg_lat}s")
        print(f"  Avg issues overlap : {avg_overlap}")
    else:
        print("\nPhase 2 SKIPPED — qwen3.5:9b n'est pas multimodal sur cette instance Ollama.")

    # Comparatif vs gemma4
    gemma = gemma_results_from_v2()
    comparison = []
    print(f"\n=== Comparatif vs {GEMMA_REF} ===")
    for r in benchmark_results:
        path = r["image"]
        gt = r["ground_truth"]
        qwen_v = r.get("verdict", "—")
        gemma_v = (gemma.get(path) or {}).get("verdict", "—")
        match_qwen = "✓" if qwen_v == gt else "✗"
        match_gemma = "✓" if gemma_v == gt else "✗"
        agreement = "=" if qwen_v == gemma_v else "≠"
        comparison.append({
            "image": path, "ground_truth": gt,
            "verdict_qwen35_9b": qwen_v, "verdict_gemma4_26b": gemma_v,
            "qwen_correct": qwen_v == gt, "gemma_correct": gemma_v == gt,
            "agree": qwen_v == gemma_v,
        })
        print(f"  {Path(path).name[:50]:<50} gt={gt:<5} qwen={qwen_v!s:<5} {match_qwen}  gemma={gemma_v!s:<5} {match_gemma}  {agreement}")

    payload = {
        "poc": "qwen35-vision",
        "date": "2026-05-05",
        "model": MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "phase1_probe": probe,
        "phase2_results": benchmark_results,
        "phase2_summary": summary,
        "comparison_vs_gemma4": comparison,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
