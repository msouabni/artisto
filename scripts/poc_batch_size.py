"""POC batch_size — soccer × batch=3 + sélection auto via QC vision.

Hypothèse : sur soccer (taux échec anatomy 70 % en seed-variance, scheduler
karras invalidé), générer **3 images par seed via batch_size=3** et sélectionner
la meilleure par QC vision automatique pourrait remonter le taux publishable
en prod sans payer 3× la latence (ComfyUI batch est plus rapide que 3 appels
séparés grâce au partage de l'inférence par étape).

Concept : soccer × 10 seeds (mêmes que `poc-seed-variance.json`).
Pour chaque seed : 1 appel ComfyUI avec node 13 `batch_size=3` ; ComfyUI
produit 3 PNGs (seed, seed+1, seed+2 en interne). On QC chacune et on
sélectionne la meilleure :
  priorité 1 : good ET pas d'issue
  priorité 2 : good avec issues mineures
  priorité 3 : poor avec confidence la plus haute (moindre mal)

Pas de rapport MD — annotation humaine ensuite via :
http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-batch-size

Usage :
    python scripts/poc_batch_size.py
"""
from __future__ import annotations

import base64
import copy
import io
import json
import shutil
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
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-batch-size"
INDEX_JSON = OUTPUT_DIR / "poc-batch-size.json"

BATCH_SIZE = 3

VISION_MODEL = "qwen3.5:9b"
VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete", "has_text"'
)
VISION_TIMEOUT = 240


def load_seeds_prompt_negative() -> tuple[list[int], str, str]:
    """Lit les 10 seeds soccer + prompt + négatif depuis l'index seed-variance."""
    if not VARIANCE_INDEX.is_file():
        raise FileNotFoundError(f"Index seed-variance introuvable : {VARIANCE_INDEX}")
    data = json.loads(VARIANCE_INDEX.read_text(encoding="utf-8"))
    seeds = data.get("seeds", {}).get("soccer")
    if not seeds or not isinstance(seeds, list) or len(seeds) != 10:
        raise RuntimeError("seeds.soccer manquant ou pas 10 entrées")
    prompt = data.get("prompts_used", {}).get("soccer")
    if not prompt:
        raise RuntimeError("prompts_used.soccer manquant")
    negative = (data.get("negatives_used") or {}).get("soccer", "")
    return [int(s) for s in seeds], prompt.strip(), negative.strip()


def load_workflow_raw() -> dict:
    data = json.loads(WORKFLOW_JSON.read_text(encoding="utf-8-sig"))
    data.pop("__meta__", None)
    return data


def make_workflow(*, base: dict, positive_prompt: str, negative_prompt: str, seed: int) -> dict:
    """Patch direct nodes 13 (batch_size) / 14 / 15 / 16."""
    wf = copy.deepcopy(base)
    wf["13"]["inputs"]["batch_size"] = BATCH_SIZE
    wf["14"]["inputs"]["text"] = positive_prompt
    wf["15"]["inputs"]["text"] = negative_prompt if negative_prompt else " "
    wf["16"]["inputs"]["seed"] = int(seed)
    wf["16"]["inputs"]["steps"] = 8
    wf["16"]["inputs"]["scheduler"] = "normal"
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


def select_best(batch: list[dict]) -> int:
    """Sélectionne l'index (1-based) de la meilleure image du batch.

    Priorité décroissante :
      1) good ET pas d'issue
      2) good avec issues mineures (privilégie absence de `has_text` et `not_line_art`)
      3) poor : la plus haute confidence (moindre mal)
    Tiebreak final : index 1 (priorité au premier rendu, choix arbitraire mais déterministe).
    """
    BAD_ISSUES = {"has_text", "not_line_art", "incomplete", "blurry"}

    def rank(item: dict) -> tuple:
        v = item.get("vision_qc") or {}
        if not v.get("json_ok"):
            return (3, 0, item["index"])  # JSON parse fail → bottom
        verdict = v.get("verdict")
        issues = set(v.get("issues") or [])
        conf = int(v.get("confidence") or 0)
        if verdict == "good" and not issues:
            return (0, -conf, item["index"])
        if verdict == "good" and not (issues & BAD_ISSUES):
            return (1, -conf, item["index"])
        if verdict == "good":
            return (1, -conf + 1000, item["index"])  # good mais avec un BAD_ISSUE
        # poor
        return (2, -conf, item["index"])

    sorted_batch = sorted(batch, key=rank)
    return sorted_batch[0]["index"]


def write_index(index: dict) -> None:
    INDEX_JSON.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    print("=" * 100, flush=True)
    print(f"POC batch_size — soccer × 10 seeds, batch={BATCH_SIZE} par seed (30 images au total)", flush=True)
    print("=" * 100, flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1

    seeds, prompt, negative = load_seeds_prompt_negative()
    base_workflow = load_workflow_raw()

    print(f"\nComfyUI : {client.base_url}", flush=True)
    print(f"Params : sampler=euler, steps=8, scheduler=normal, cfg=1.0, 1024×1024, denoise=1.0, batch_size={BATCH_SIZE}", flush=True)
    print(f"Source seeds + prompt + négatif : {VARIANCE_INDEX.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Output dir : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Index JSON : {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Seeds soccer (10) : {seeds}", flush=True)
    print(flush=True)

    # Plan des 10 seeds
    plan: list[dict] = []
    for i, seed in enumerate(seeds, 1):
        short = str(seed)[-6:]
        plan.append({
            "concept": "soccer",
            "var_index": i,
            "seed": int(seed),
            "seed_short": short,
        })

    index: dict = {
        "poc": "batch-size",
        "date": "2026-05-07",
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
            "batch_size": BATCH_SIZE,
        },
        "negative_used": negative,
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
        short = entry["seed_short"]

        wf = make_workflow(
            base=base_workflow,
            positive_prompt=prompt,
            negative_prompt=negative,
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
            images_meta = client.extract_output_images(history)
            comfy_dt = time.time() - t0
            if len(images_meta) != BATCH_SIZE:
                # Pas bloquant : on accepte ce qu'on récupère, mais on log
                print(
                    f"[soccer-batch var{i:02d}] ⚠ {len(images_meta)} images retournées (attendu {BATCH_SIZE})",
                    flush=True,
                )
            if not images_meta:
                raise RuntimeError("Aucune image dans l'historique ComfyUI")
            rec["comfy_latency_s"] = round(comfy_dt, 2)
            rec["comfy_prompt_id"] = prompt_id
        except Exception as exc:
            rec["status"] = "comfy_error"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[soccer-batch var{i:02d}] ❌ Comfy {rec['error']}", flush=True)
            write_index(index)
            continue

        # Téléchargement des N images du batch
        batch_records: list[dict] = []
        for j, img in enumerate(images_meta, 1):
            fname = f"soccer_var{i:02d}_s{short}_b{j}_08s_normal_euler_cfg10.png"
            out_path = OUTPUT_DIR / fname
            try:
                client.download_image(
                    filename=img["filename"],
                    dest=out_path,
                    subfolder=img.get("subfolder", ""),
                    folder_type=img.get("type", "output"),
                )
            except Exception as exc:
                print(f"[soccer-batch var{i:02d} b{j}] ❌ download {exc}", flush=True)
                batch_records.append({
                    "index": j,
                    "filename": fname,
                    "error_download": f"{type(exc).__name__}: {exc}",
                })
                continue

            # Histogram
            try:
                hist = histogram_check(out_path)
            except Exception as exc:
                hist = {"error": f"{type(exc).__name__}: {exc}"}

            # Vision QC
            v = call_vision_qc(out_path)

            cr = (hist or {}).get("color_ratio", 0.0)
            if v.get("error"):
                tag = "vision_err"
                verdict = None
            elif not v.get("json_ok"):
                tag = "json_fail"
                verdict = None
            else:
                verdict = v.get("verdict")
                tag = "good" if verdict == "good" and not v.get("issues") else (
                    "good_with_issues" if verdict == "good" else "poor"
                )

            batch_records.append({
                "index": j,
                "filename": fname,
                "image_path": str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "histogram": hist,
                "vision_qc": v,
                "verdict": verdict,
                "issues": v.get("issues") or [],
                "confidence": v.get("confidence"),
                "tag": tag,
            })

        rec["batch"] = batch_records

        # Sélection meilleure image
        best_idx = select_best(batch_records) if batch_records else None
        rec["best_index"] = best_idx
        rec["batch_success"] = any(
            (b.get("verdict") == "good" and not b.get("issues"))
            for b in batch_records
        )
        # Inclut aussi les "good_with_issues" comme partial success
        rec["batch_any_good"] = any(b.get("verdict") == "good" for b in batch_records)

        # Copie de la meilleure → fichier _best
        best_path = None
        if best_idx is not None:
            best_src = OUTPUT_DIR / batch_records[best_idx - 1]["filename"]
            best_path = OUTPUT_DIR / f"soccer_var{i:02d}_s{short}_best_08s_normal_euler_cfg10.png"
            if best_src.is_file():
                shutil.copy2(best_src, best_path)
                rec["best_image_path"] = str(best_path.relative_to(PROJECT_ROOT)).replace("\\", "/")

        # Console line
        verdicts = [b.get("verdict") or "?" for b in batch_records]
        n_good = sum(1 for b in batch_records if b.get("verdict") == "good")
        n_good_clean = sum(
            1 for b in batch_records
            if b.get("verdict") == "good" and not b.get("issues")
        )
        success_mark = "✅" if rec["batch_success"] else ("⚠" if rec["batch_any_good"] else "❌")
        print(
            f"[soccer-batch var{i:02d}] {success_mark} verdicts={verdicts}  "
            f"good_clean={n_good_clean}/3  any_good={n_good}/3  best=b{best_idx}  "
            f"comfy={rec.get('comfy_latency_s', 0):.1f}s",
            flush=True,
        )

        rec["status"] = "done"
        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_index(index)

    # ── Stats finales ──
    items = index["items"]
    n_seeds = len(items)
    n_done = sum(1 for it in items if it.get("status") == "done")
    n_err = sum(1 for it in items if it.get("status") == "comfy_error")

    # Batch success (≥1 image good_clean)
    n_batch_success = sum(1 for it in items if it.get("batch_success"))
    n_batch_any_good = sum(1 for it in items if it.get("batch_any_good"))

    # Distribution good_clean dans le batch (0/1/2/3)
    dist_good_clean: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
    for it in items:
        if it.get("status") != "done":
            continue
        n = sum(
            1 for b in (it.get("batch") or [])
            if b.get("verdict") == "good" and not b.get("issues")
        )
        dist_good_clean[n] = dist_good_clean.get(n, 0) + 1

    # Image-level totals
    total_imgs = sum(len(it.get("batch") or []) for it in items)
    n_img_good = sum(
        1 for it in items
        for b in (it.get("batch") or [])
        if b.get("verdict") == "good"
    )
    n_img_good_clean = sum(
        1 for it in items
        for b in (it.get("batch") or [])
        if b.get("verdict") == "good" and not b.get("issues")
    )

    summary = {
        "n_seeds": n_seeds,
        "n_done": n_done,
        "n_comfy_error": n_err,
        "n_batch_success_good_clean": n_batch_success,
        "n_batch_any_good": n_batch_any_good,
        "distribution_good_clean_per_batch": dist_good_clean,
        "image_level": {
            "total_images": total_imgs,
            "n_good": n_img_good,
            "n_good_clean": n_img_good_clean,
        },
    }
    index["summary"] = summary
    write_index(index)

    print(flush=True)
    print("─── Stats ─────────────────────────────────────────────────────────────────────", flush=True)
    print(f"Seeds done           : {n_done}/{n_seeds}  (erreurs Comfy : {n_err})", flush=True)
    print(f"Batch success ≥1 good_clean      : {n_batch_success}/{n_seeds}  ({n_batch_success*100//max(n_seeds,1)}%)", flush=True)
    print(f"Batch any good (avec ou sans issue): {n_batch_any_good}/{n_seeds}  ({n_batch_any_good*100//max(n_seeds,1)}%)", flush=True)
    print(f"Distribution good_clean / batch  : 0={dist_good_clean[0]} · 1={dist_good_clean[1]} · 2={dist_good_clean[2]} · 3={dist_good_clean[3]}", flush=True)
    print(f"Image-level                      : good_clean={n_img_good_clean}/{total_imgs}  any_good={n_img_good}/{total_imgs}  (rappel seed-variance baseline 30 % publishable)", flush=True)
    print(flush=True)
    print(f"Index JSON → {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print("Annotation humaine : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-batch-size", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
