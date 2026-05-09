"""POC scale-benchmark nature — toutes les feuilles haute confiance des
classes nature passées au pipeline ERNIE direct (génération PromptGenerator
+ ComfyUI), capé à 60 images via échantillon reproductible.

Classes nature couvertes (sortie du PromptGenerator post-audit 2026-05-09) :
- Solo animal             (mammifères 4 pattes, fantasy_animals)
- Solo insect             (insects_and_minibeasts)
- Solo fish               (marine_animals)
- Solo bird               (birds — exclu du high-conf actuellement, confiance Moyenne)
- Solo reptile            (réservé pour futur, aucune sub n'utilise actuellement)
- Solo animal (mammifère marin)  (réservé)

Note : `birds` est en confiance Moyenne dans la cartographie, donc absent
de `list_high_confidence_leaves()`. À la date de ce POC, le sample sortira
uniquement des classes Solo animal / Solo fish / Solo insect (110 leaves
disponibles, capés à 60). À élargir si la confidence `birds` passe à Haute.

Pipeline : pattern identique à `poc_generator_benchmark.py` — workflow JSON
brut, modifications uniquement nodes 13/14/15/16, batch_size=1.

Output : docs/reports/poc-scale-benchmark/
Index  : docs/reports/poc-scale-benchmark/index-nature.json (atomique)
Naming : {leaf_id}_{w}x{h}_euler8s.png

Annotation humaine :
    http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark

Usage :
    PYTHONPATH=src python scripts/poc_scale_benchmark_nature.py
"""
from __future__ import annotations

import io
import json
import random
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

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from services.prompt_generator import PromptGenerator  # noqa: E402
from workers.comfy_client import ComfyClient, workflows_json_dir  # noqa: E402

# ───────── Config ─────────
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-scale-benchmark"
INDEX_JSON = OUTPUT_DIR / "index-nature.json"
WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

NATURE_CLASSES = {
    "Solo animal",
    "Solo insect",
    "Solo fish",
    "Solo bird",
    "Solo animal (mammifère marin)",
    "Solo reptile",
}

MAX_LEAVES = 60
SAMPLE_SEED = 2026

FIXED_STEPS = 8
FIXED_SAMPLER = "euler"
FIXED_SCHEDULER = "normal"
FIXED_CFG = 1.0
FIXED_BATCH_SIZE = 1
SEED_BASE = 5000
SEED_STRIDE = 7


# ───────── Index IO ─────────
def load_index() -> dict:
    if INDEX_JSON.exists():
        try:
            return json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "poc": "scale-benchmark-nature",
        "date": "2026-05-09",
        "workflow_template": WORKFLOW_TEMPLATE,
        "nature_classes": sorted(NATURE_CLASSES),
        "max_leaves": MAX_LEAVES,
        "sample_seed": SAMPLE_SEED,
        "fixed": {
            "steps": FIXED_STEPS, "sampler_name": FIXED_SAMPLER,
            "scheduler": FIXED_SCHEDULER, "cfg": FIXED_CFG,
            "batch_size": FIXED_BATCH_SIZE,
            "seed_base": SEED_BASE, "seed_stride": SEED_STRIDE,
        },
        "results": {},
    }


def save_index_atomic(index: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(INDEX_JSON)


# ───────── Pipeline ─────────
def submit_to_comfy(client: ComfyClient, positive: str, negative: str,
                    width: int, height: int, seed: int) -> str:
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    wf.pop("__meta__", None)

    wf["13"]["inputs"]["width"] = int(width)
    wf["13"]["inputs"]["height"] = int(height)
    wf["13"]["inputs"]["batch_size"] = int(FIXED_BATCH_SIZE)
    wf["14"]["inputs"]["text"] = positive
    if negative and negative.strip():
        wf["15"]["inputs"]["text"] = negative
    wf["16"]["inputs"]["seed"] = int(seed)
    wf["16"]["inputs"]["steps"] = int(FIXED_STEPS)
    wf["16"]["inputs"]["sampler_name"] = FIXED_SAMPLER
    wf["16"]["inputs"]["scheduler"] = FIXED_SCHEDULER
    wf["16"]["inputs"]["cfg"] = float(FIXED_CFG)

    return client.submit_prompt(wf)


def generate_image(client: ComfyClient, positive: str, negative: str,
                   width: int, height: int, seed: int, out_path: Path) -> dict:
    t0 = time.time()
    try:
        prompt_id = submit_to_comfy(client, positive, negative, width, height, seed)
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


def histogram_check(image_path: Path) -> dict:
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    flags = qc.get("flags") or []
    return {
        "histogram_ok": not (("strong_color" in flags) or ("noticeable_color" in flags)),
        "color_ratio": float(metrics.get("color_ratio", 0.0)),
        "ink_ratio": float(metrics.get("ink_ratio", 0.0)),
        "white_ratio": float(metrics.get("white_ratio", 0.0)),
        "flags": flags,
    }


# ───────── Sélection feuilles nature ─────────
def select_nature_leaves(gen: PromptGenerator) -> list[tuple[str, str, dict]]:
    """Retourne [(leaf_id, workflow_class, build_prompt_result), ...] capé à MAX_LEAVES."""
    all_leaves = gen.list_high_confidence_leaves()
    nature: list[tuple[str, str, dict]] = []
    for lid in all_leaves:
        try:
            r = gen.build_prompt(lid)
        except Exception:
            continue
        cls = r.get("workflow_class")
        if cls in NATURE_CLASSES:
            nature.append((lid, cls, r))

    # Sample reproductible si > MAX_LEAVES
    if len(nature) > MAX_LEAVES:
        rng = random.Random(SAMPLE_SEED)
        nature = rng.sample(nature, MAX_LEAVES)
        # Tri stable post-sample : par classe puis leaf_id pour lisibilité console + idx déterministe
        nature.sort(key=lambda t: (t[1], t[0]))
    return nature


# ───────── Main ─────────
def main() -> int:
    print("=" * 100, flush=True)
    print("POC scale-benchmark NATURE — toutes les feuilles haute confiance des classes nature", flush=True)
    print("=" * 100, flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    gen = PromptGenerator()
    total = len(gen.leaf_index)
    print(f"\nPromptGenerator chargé : {total} leaves au total", flush=True)
    print(f"Classes nature ciblées : {sorted(NATURE_CLASSES)}", flush=True)

    selection = select_nature_leaves(gen)
    n_planned = len(selection)
    print(f"Sample : {n_planned} feuilles (cap {MAX_LEAVES}, seed={SAMPLE_SEED})", flush=True)

    by_class: dict[str, int] = {}
    for _, cls, _ in selection:
        by_class[cls] = by_class.get(cls, 0) + 1
    for cls, n in sorted(by_class.items(), key=lambda x: -x[1]):
        print(f"  {cls:<35} {n}", flush=True)
    print(f"Output : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Index  : {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print()

    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"ComfyUI OK : {client.base_url}", flush=True)
    print()

    index = load_index()
    index["selection_count"] = n_planned
    index["selection_by_class"] = by_class
    save_index_atomic(index)

    n_ok = 0
    n_ko = 0
    for idx, (lid, cls, r) in enumerate(selection, 1):
        w, h = r["resolution"]
        seed = SEED_BASE + idx * SEED_STRIDE
        fname = f"{lid}_{w}x{h}_euler8s.png"
        out_path = OUTPUT_DIR / fname

        gen_meta = generate_image(
            client,
            positive=r["positive"],
            negative=r["negative"],
            width=w, height=h, seed=seed,
            out_path=out_path,
        )

        rec: dict = {
            "leaf_id": lid,
            "leaf_name_en": r.get("leaf_name_en"),
            "workflow_class": cls,
            "subcategory_id": r.get("subcategory_id"),
            "subcategory_name": r.get("subcategory_name"),
            "category_root": r.get("category_root"),
            "resolution": [w, h],
            "positive": r["positive"],
            "negative": r["negative"],
            "filename": fname,
            "seed": seed,
            "comfy_latency_s": gen_meta.get("comfy_latency_s"),
            "comfy_prompt_id": gen_meta.get("comfy_prompt_id"),
            "status": "done" if gen_meta.get("ok") else "comfy_error",
        }
        if not gen_meta.get("ok"):
            rec["error"] = gen_meta.get("error")
            n_ko += 1
            print(f"[{idx:>2}/{n_planned}] {lid} {cls} {w}×{h} — ❌ {gen_meta.get('error')}", flush=True)
        else:
            try:
                hist = histogram_check(out_path)
                rec.update(hist)
            except Exception as exc:
                rec["histogram_error"] = f"{type(exc).__name__}: {exc}"
            n_ok += 1
            cr = rec.get("color_ratio", 0.0)
            ir = rec.get("ink_ratio", 0.0)
            flags = rec.get("flags") or []
            tag = "✅" if rec.get("histogram_ok", True) else "⚠"
            flags_str = f" flags={flags}" if flags else ""
            print(
                f"[{idx:>2}/{n_planned}] {lid} {cls} {w}×{h} — "
                f"{rec['comfy_latency_s']:.1f}s {tag} color={cr:.4f} ink={ir:.4f}{flags_str}",
                flush=True,
            )

        index["results"][lid] = rec
        save_index_atomic(index)

    # ── Stats finales par classe ──
    print(flush=True)
    print("─── Stats finales ─────────────────────────────────────────────────────────────", flush=True)
    print(f"Total : {n_ok}/{n_planned} générées · erreurs Comfy : {n_ko}", flush=True)
    print()

    by_cls_stats: dict[str, dict] = {}
    for rec in index["results"].values():
        cls = rec.get("workflow_class") or "?"
        s = by_cls_stats.setdefault(cls, {
            "n": 0, "n_ok": 0, "n_hist_ok": 0,
            "color_ratios": [], "color_max": 0.0,
            "color_violators": [],
        })
        s["n"] += 1
        if rec.get("status") == "done":
            s["n_ok"] += 1
            cr = float(rec.get("color_ratio") or 0.0)
            s["color_ratios"].append(cr)
            if cr > s["color_max"]:
                s["color_max"] = cr
            if rec.get("histogram_ok", True):
                s["n_hist_ok"] += 1
            if cr > 0.025:
                s["color_violators"].append((rec.get("leaf_id"), cr))

    print(f"{'Classe':<28} {'n':>3} {'ok':>3} {'hist_ok':>8} {'color_avg':>10} {'color_max':>10} {'violators(>0.025)':>20}", flush=True)
    print("-" * 100, flush=True)
    for cls in sorted(by_cls_stats):
        s = by_cls_stats[cls]
        avg = (sum(s["color_ratios"]) / len(s["color_ratios"])) if s["color_ratios"] else 0.0
        print(
            f"{cls:<28} {s['n']:>3} {s['n_ok']:>3} {s['n_hist_ok']:>8} "
            f"{avg:>10.5f} {s['color_max']:>10.5f} {len(s['color_violators']):>20}",
            flush=True,
        )

    # Persist stats dans index
    index["stats_by_class"] = {
        cls: {
            "n": s["n"], "n_ok": s["n_ok"], "n_histogram_ok": s["n_hist_ok"],
            "color_ratio_avg": round(
                (sum(s["color_ratios"]) / len(s["color_ratios"])) if s["color_ratios"] else 0.0, 5
            ),
            "color_ratio_max": round(s["color_max"], 5),
            "color_violators_count": len(s["color_violators"]),
            "color_violators": [{"leaf_id": lid, "color_ratio": round(cr, 5)}
                                for lid, cr in s["color_violators"]],
        }
        for cls, s in by_cls_stats.items()
    }
    save_index_atomic(index)

    print(flush=True)
    print(f"Index JSON → {INDEX_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"Annotation humaine : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark", flush=True)
    return 0 if n_ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
