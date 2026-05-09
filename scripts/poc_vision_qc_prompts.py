"""POC vision QC prompts — calibration du prompt qwen3.5:9b pour détecter
le défaut anatomy (3_jambes, 2_objets) sur soccer.

Le prompt baseline (utilisé jusqu'ici dans poc_image_quality / poc_seed_variance /
poc_batch_size) marque toutes les images soccer "good" même quand l'annotation
humaine voit 3 jambes — taux détection 0 %. Ce POC compare 5 variantes de
prompts pour trouver lequel rappelle le plus de défauts anatomy sans trop
de faux positifs.

Source images : `docs/reports/poc-batch-size/*.png` (exclure `*_best*`)
Ground truth  : `docs/reports/poc-batch-size/annotations.json`

Métriques par prompt vs ground truth `3_jambes` :
  TP : image avec 3_jambes détectée comme defect
  FP : image sans 3_jambes détectée comme defect (fausse alarme)
  FN : image avec 3_jambes ratée
  TN : image sans 3_jambes correctement non flaguée
  Precision = TP / (TP + FP)
  Recall    = TP / (TP + FN)
  F1        = 2 * P * R / (P + R)

Usage :
    python scripts/poc_vision_qc_prompts.py
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
    _supports_native_think_disable,
    parse_json_response,
)

BATCH_SIZE_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-batch-size"
ANNOTATIONS_JSON = BATCH_SIZE_DIR / "annotations.json"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-vision-qc-prompts"
INDEX_JSON = OUTPUT_DIR / "poc-vision-qc-prompts.json"

VISION_MODEL = "qwen3.5:9b"
VISION_TIMEOUT = 120

# Détection « défaut anatomy » à partir de la réponse parsée — fonction unifiée
# qui regarde tous les signaux possibles selon le schéma de chaque prompt.
DEFECT_ISSUE_TOKENS = {
    "extra_leg", "extra_legs", "3_jambes", "three_legs", "third_leg",
    "multiple_balls", "multiple_figures", "duplicate_limbs",
}


def detect_defect(parsed: dict) -> tuple[bool, str]:
    """Retourne (detected, reason). Looks at all possible fields produced
    by any of the 5 prompts (verdict, issues, anatomy_ok, anatomy_defect, leg_count)."""
    if not isinstance(parsed, dict):
        return False, "not_a_dict"

    quality = parsed.get("quality")
    issues_raw = parsed.get("issues") or []
    issues = {str(x).strip().lower() for x in issues_raw if isinstance(x, str)}
    anatomy_ok = parsed.get("anatomy_ok")
    anatomy_defect = parsed.get("anatomy_defect")
    leg_count = parsed.get("leg_count")

    if quality == "poor":
        return True, "quality=poor"
    if anatomy_ok is False:
        return True, "anatomy_ok=false"
    if anatomy_defect is True:
        return True, "anatomy_defect=true"
    try:
        if leg_count is not None and int(leg_count) >= 3:
            return True, f"leg_count={leg_count}"
    except (TypeError, ValueError):
        pass
    matched = issues & {t.lower() for t in DEFECT_ISSUE_TOKENS}
    if matched:
        return True, f"issues={sorted(matched)}"
    return False, "clean"


# ─── 5 prompts à tester ─────────────────────────────────────────────────────

PROMPTS: dict[str, dict] = {
    "A": {
        "label": "current (baseline)",
        "system": "You are a quality control assistant for children's coloring pages.",
        "user": (
            "Evaluate this coloring page image quality for publication.\n"
            "Reply ONLY with valid JSON, no explanation:\n"
            '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
            'Possible issues: "has_color", "blurry", "noisy", "artifacts", '
            '"not_line_art", "incomplete", "has_text"'
        ),
    },
    "B": {
        "label": "anatomy-aware",
        "system": "You are a strict quality control inspector for children's coloring book pages.",
        "user": (
            "Inspect this coloring page carefully for anatomy defects.\n"
            "Count the number of legs on any human or animal figure.\n"
            "A normal person has EXACTLY 2 legs. 3 or more legs = defect.\n"
            "Reply ONLY with valid JSON:\n"
            '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
            'Possible issues: "extra_leg" (3+ legs visible), "missing_leg", '
            '"multiple_figures", "has_color", "not_line_art", "incomplete"'
        ),
    },
    "C": {
        "label": "soccer-specific explicit",
        "system": "You are a quality control assistant for children's coloring pages.",
        "user": (
            "This coloring page shows a soccer scene. Inspect it carefully:\n"
            "1. Count the legs of the soccer player. Normal = 2 legs. "
            "If you see 3 or more legs, that is a critical defect.\n"
            "2. Count soccer balls. Normal = 1 ball.\n"
            "3. Is it black-and-white line art only?\n"
            "Reply ONLY with valid JSON:\n"
            '{"quality": "good"|"poor", "leg_count": <integer>, "ball_count": <integer>, '
            '"issues": [], "confidence": 0-100}\n'
            'Possible issues: "extra_leg", "multiple_balls", "has_color", '
            '"not_line_art", "incomplete"'
        ),
    },
    "D": {
        "label": "binary anatomy check",
        "system": "You are a precise visual inspector.",
        "user": (
            "Look at this image very carefully.\n"
            "Focus ONLY on this question: does any figure in the image have an "
            "abnormal number of limbs?\n"
            "- A human soccer player should have EXACTLY 2 legs and 2 arms.\n"
            "- If you see 3 legs, fused legs, or extra limbs anywhere: anatomy_ok = false.\n"
            "Reply ONLY with valid JSON:\n"
            '{"quality": "good"|"poor", "anatomy_ok": true, "issues": [], "confidence": 0-100}\n'
            "Set quality to poor if anatomy_ok is false."
        ),
    },
    "E": {
        "label": "chain-of-thought forced",
        "system": "You are a quality control assistant for children's coloring pages.",
        "user": (
            "Examine this coloring page step by step:\n"
            "Step 1: Is there a human figure? If yes, count their legs carefully.\n"
            "Step 2: Are there any anatomy defects (extra limbs, fused limbs, "
            "wrong number of legs)?\n"
            "Step 3: Is it proper black-and-white line art (no color fills)?\n"
            "Step 4: Final verdict.\n"
            "Reply ONLY with valid JSON (no text outside JSON):\n"
            '{"leg_count": <integer or null>, "anatomy_defect": true|false, '
            '"has_color": true|false, "quality": "good"|"poor", "issues": [], '
            '"confidence": 0-100}'
        ),
    },
}


def call_vision(prompt_id: str, image_path: Path) -> dict:
    """Appelle qwen3.5:9b avec le prompt {prompt_id} et l'image."""
    cfg = PROMPTS[prompt_id]
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload: dict = {
        "model": VISION_MODEL,
        "system": cfg["system"],
        "prompt": cfg["user"],
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
            return {"status": "ollama_error", "error": data["error"], "latency_s": dt}
        raw = data.get("response", "")
        try:
            parsed = parse_json_response(raw)
        except ValueError as exc:
            return {"status": "no_parse", "raw": raw, "json_error": str(exc), "latency_s": dt}
        if not isinstance(parsed, dict):
            return {"status": "not_dict", "raw": raw, "parsed_type": type(parsed).__name__, "latency_s": dt}
        return {"status": "ok", "raw": raw, "parsed": parsed, "latency_s": dt}
    except Exception as exc:
        return {"status": "http_error", "error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}


def load_ground_truth() -> tuple[list[Path], dict[str, dict]]:
    """Retourne (liste images non-_best triées, dict filename → annotation)."""
    ann_data = json.loads(ANNOTATIONS_JSON.read_text(encoding="utf-8"))
    ann = ann_data.get("annotations") or {}
    images: list[Path] = sorted(
        p for p in BATCH_SIZE_DIR.glob("*.png") if "_best" not in p.name
    )
    if not images:
        raise RuntimeError(f"Aucune image non-_best dans {BATCH_SIZE_DIR}")
    return images, ann


def compute_metrics(per_image: dict[str, dict], gt_3jambes: dict[str, bool]) -> dict:
    TP = FP = FN = TN = 0
    no_parse = 0
    no_parse_files: list[str] = []
    for fname, gt in gt_3jambes.items():
        rec = per_image.get(fname) or {}
        if rec.get("status") != "ok":
            no_parse += 1
            no_parse_files.append(fname)
            continue
        detected = bool(rec.get("detected_defect"))
        if gt and detected:
            TP += 1
        elif gt and not detected:
            FN += 1
        elif (not gt) and detected:
            FP += 1
        else:
            TN += 1
    p = TP / (TP + FP) if (TP + FP) else 0.0
    r = TP / (TP + FN) if (TP + FN) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {
        "TP": TP, "FP": FP, "FN": FN, "TN": TN,
        "no_parse": no_parse,
        "no_parse_files": no_parse_files,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "F1": round(f1, 4),
    }


def main() -> int:
    print("=" * 100, flush=True)
    print("POC vision QC prompts — 5 prompts × 30 images soccer (ground truth = annotations humaines)", flush=True)
    print("=" * 100, flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    images, ann = load_ground_truth()
    print(f"\nImages testées : {len(images)} (de {BATCH_SIZE_DIR.relative_to(PROJECT_ROOT)}, hors _best)", flush=True)
    print(f"Ground truth   : {ANNOTATIONS_JSON.relative_to(PROJECT_ROOT)}", flush=True)

    # Ground truth filtré : uniquement les images qui ont une entrée d'annotation
    gt_3jambes: dict[str, bool] = {}
    missing_ann = []
    for img in images:
        a = ann.get(img.name)
        if a is None:
            missing_ann.append(img.name)
            continue
        gt_3jambes[img.name] = "3_jambes" in (a.get("defects") or [])
    if missing_ann:
        print(f"⚠ {len(missing_ann)} images sans entrée d'annotation, ignorées : {missing_ann[:3]}…", flush=True)

    n_3jambes = sum(1 for v in gt_3jambes.values() if v)
    n_no_3jambes = sum(1 for v in gt_3jambes.values() if not v)
    print(f"Ground truth : 3_jambes = {n_3jambes}/{len(gt_3jambes)}, "
          f"sans 3_jambes = {n_no_3jambes}/{len(gt_3jambes)}", flush=True)
    print(flush=True)

    # Index pré-rempli
    index: dict = {
        "poc": "vision-qc-prompts",
        "date": "2026-05-07",
        "vision_model": VISION_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "source_dir": str(BATCH_SIZE_DIR.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "annotations_file": str(ANNOTATIONS_JSON.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "n_images": len(gt_3jambes),
        "ground_truth_3jambes_count": n_3jambes,
        "prompts_tested": list(PROMPTS.keys()),
        "prompts_text": {k: {"label": v["label"], "system": v["system"], "user": v["user"]}
                          for k, v in PROMPTS.items()},
        "results": {},
    }
    INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    sorted_filenames = sorted(gt_3jambes.keys())
    for prompt_id in PROMPTS:
        print(f"─── Prompt {prompt_id} ({PROMPTS[prompt_id]['label']}) ─────────────────────────────────", flush=True)
        per_image: dict[str, dict] = {}
        for i, fname in enumerate(sorted_filenames, 1):
            img_path = BATCH_SIZE_DIR / fname
            res = call_vision(prompt_id, img_path)
            entry: dict = {
                "filename": fname,
                "status": res.get("status"),
                "latency_s": round(res.get("latency_s") or 0.0, 2),
                "ground_truth_3jambes": gt_3jambes[fname],
            }
            if res.get("status") == "ok":
                parsed = res.get("parsed") or {}
                detected, reason = detect_defect(parsed)
                entry.update({
                    "raw_response": res.get("raw"),
                    "parsed": parsed,
                    "detected_defect": detected,
                    "detection_reason": reason,
                })
            else:
                # Erreur / pas de parse — on garde le brut pour debug
                if "raw" in res:
                    entry["raw_response"] = res.get("raw")
                if "error" in res:
                    entry["error"] = res.get("error")
                if "json_error" in res:
                    entry["json_error"] = res.get("json_error")
                entry["detected_defect"] = False
                entry["detection_reason"] = res.get("status")

            per_image[fname] = entry
            mark = "✓" if entry.get("detected_defect") == gt_3jambes[fname] else "✗"
            tag = "ok" if res.get("status") == "ok" else f"⚠{res.get('status')}"
            gt_tag = "3J" if gt_3jambes[fname] else "  "
            det_tag = "DETECT" if entry.get("detected_defect") else "      "
            print(
                f"  Prompt {prompt_id} — image {i:>2}/{len(sorted_filenames)} {tag:<10}  "
                f"gt={gt_tag} det={det_tag} {mark} ({entry['latency_s']}s) — {fname[-40:]}",
                flush=True,
            )

        metrics = compute_metrics(per_image, gt_3jambes)
        index["results"][prompt_id] = {
            "label": PROMPTS[prompt_id]["label"],
            "per_image": per_image,
            "metrics": metrics,
        }
        # Persist après chaque prompt complet
        INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        m = metrics
        print(f"  → Prompt {prompt_id} metrics : "
              f"TP={m['TP']} FP={m['FP']} FN={m['FN']} TN={m['TN']} "
              f"P={m['precision']} R={m['recall']} F1={m['F1']} "
              f"(no_parse={m['no_parse']})", flush=True)
        print(flush=True)

    # ── Tableau comparatif final ──
    print("=" * 100, flush=True)
    print("Tableau comparatif (vs ground truth 3_jambes)", flush=True)
    print("=" * 100, flush=True)
    print(f"{'Prompt':<8} {'Label':<30} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3} "
          f"{'Precision':>9} {'Recall':>7} {'F1':>6} {'no_parse':>9}", flush=True)
    print("-" * 100, flush=True)
    for prompt_id in PROMPTS:
        m = index["results"][prompt_id]["metrics"]
        print(f"{prompt_id:<8} {PROMPTS[prompt_id]['label']:<30} "
              f"{m['TP']:>3} {m['FP']:>3} {m['FN']:>3} {m['TN']:>3} "
              f"{m['precision']:>9.3f} {m['recall']:>7.3f} {m['F1']:>6.3f} "
              f"{m['no_parse']:>9}", flush=True)
    print(flush=True)

    # Best F1
    best = max(PROMPTS.keys(), key=lambda k: index["results"][k]["metrics"]["F1"])
    bm = index["results"][best]["metrics"]
    print(f"Best F1 : Prompt {best} ({PROMPTS[best]['label']}) → F1={bm['F1']} "
          f"(P={bm['precision']} R={bm['recall']})", flush=True)

    print(f"\nIndex JSON → {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
