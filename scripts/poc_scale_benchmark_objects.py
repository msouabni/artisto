"""POC scale-benchmark — passe à l'échelle sur les classes "objet".

Sélectionne jusqu'à 50 feuilles dont le ``workflow_class`` (issu de
``taxonomy_production_cartography.json``) appartient à l'ensemble
``OBJECT_CLASSES`` ci-dessous, puis génère une image par feuille via
ERNIE direct (mêmes paramètres que ``poc_generator_benchmark`` :
steps=8, sampler=euler, scheduler=normal, cfg=1.0).

Différences notables vs. ``poc_generator_benchmark`` :
- Sélection randomisée des feuilles (``random.seed(2028)``) — limite à 50
  même quand l'univers candidat est plus large.
- Seed ComfyUI : ``7000 + idx*7`` (et non 4242+idx*7).
- Index nommé ``index-objects.json`` (pas ``<dir>/<dir>.json``) — le
  préfixe ``index-`` permet d'avoir plusieurs index spécialisés dans le
  même dossier (objects / animals / humans, etc.).

Usage :
    PYTHONPATH=src python scripts/poc_scale_benchmark_objects.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from services.prompt_generator import PromptGenerator  # noqa: E402
from workers.comfy_client import ComfyClient, workflows_json_dir  # noqa: E402

# ───────────────── Paths ─────────────────
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-scale-benchmark"
INDEX_JSON = OUTPUT_DIR / "index-objects.json"
WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

# Fixed sampler params (alignés sur poc-generator-benchmark).
FIXED_STEPS = 8
FIXED_SAMPLER = "euler"
FIXED_SCHEDULER = "normal"
FIXED_CFG = 1.0
SEED_BASE = 7000
SEED_STRIDE = 7

# Sélection des feuilles : workflow_class dans cet ensemble.
OBJECT_CLASSES = {
    "Solo objet",
    "Solo objet véhicule",
    "Solo objet historique",
    "Solo objet en vol OU au sol",
    "Mandala",
    "Éducatif",
    "Lettre + objet",
    "Variable",
    "Variable (solo objet ou frise)",
    "Solo objet (véhicule)",
}

SELECTION_SEED = 2028
SELECTION_LIMIT = 50


# ───────────────── Index IO (atomic) ─────────────────
def load_index() -> dict:
    if INDEX_JSON.exists():
        try:
            return json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "poc": "scale-benchmark-objects",
        "workflow_template": WORKFLOW_TEMPLATE,
        "selection": {
            "classes": sorted(OBJECT_CLASSES),
            "seed": SELECTION_SEED,
            "limit": SELECTION_LIMIT,
        },
        "fixed": {
            "steps": FIXED_STEPS, "sampler_name": FIXED_SAMPLER,
            "scheduler": FIXED_SCHEDULER, "cfg": FIXED_CFG,
            "seed_base": SEED_BASE, "seed_stride": SEED_STRIDE,
        },
        "results": {},
    }


def save_index_atomic(index: dict) -> None:
    tmp = INDEX_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(INDEX_JSON)


# ───────────────── Sélection des feuilles ─────────────────
def collect_object_leaves(gen: PromptGenerator) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Retourne (candidats, comptes_par_classe) pour les classes ``OBJECT_CLASSES``.

    Chaque candidat est ``(leaf_id, workflow_class)``. Itération déterministe
    (ordre du ``leaf_index``).
    """
    per_class: dict[str, int] = {}
    candidates: list[tuple[str, str]] = []
    for leaf_id, (_root, sub, _leaf) in gen.leaf_index.items():
        strat = gen.strategy_index.get(sub["id"])
        if not strat:
            continue
        cls = strat["class"]
        if cls in OBJECT_CLASSES:
            candidates.append((leaf_id, cls))
            per_class[cls] = per_class.get(cls, 0) + 1
    return candidates, per_class


def sample_leaves(candidates: list[tuple[str, str]],
                  limit: int, seed: int) -> list[tuple[str, str]]:
    """Échantillonne aléatoirement ``limit`` éléments avec ``seed`` fixe.

    Si ``len(candidates) <= limit`` : retourne tout (trié pour stabilité).
    """
    if len(candidates) <= limit:
        return sorted(candidates, key=lambda t: t[0])
    rng = random.Random(seed)
    return sorted(rng.sample(candidates, limit), key=lambda t: t[0])


# ───────────────── Pipeline (copié sur poc_generator_benchmark) ─────────────────
def submit_to_comfy(client: ComfyClient, positive: str, negative: str,
                    width: int, height: int, seed: int) -> str:
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    wf.pop("__meta__", None)

    wf["13"]["inputs"]["width"] = int(width)
    wf["13"]["inputs"]["height"] = int(height)
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


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC scale-benchmark objects — PromptGenerator x ERNIE direct (seed sample)")
    print("=" * 100)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    gen = PromptGenerator()
    print(f"PromptGenerator initialisé. Total leaves dispo : {len(gen.leaf_index)}")

    candidates, per_class = collect_object_leaves(gen)
    print(f"Candidats objets : {len(candidates)}")
    for cls in sorted(OBJECT_CLASSES):
        n = per_class.get(cls, 0)
        marker = "✓" if n > 0 else "·"
        print(f"  {marker} {n:3d}  {cls}")

    selected = sample_leaves(candidates, SELECTION_LIMIT, SELECTION_SEED)
    print(f"Sélectionnés : {len(selected)} (seed={SELECTION_SEED}, limit={SELECTION_LIMIT})")
    print(f"Output : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}")
    print(f"Index  : {INDEX_JSON.relative_to(PROJECT_ROOT)}")
    print()

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"ComfyUI OK : {client.base_url}")
    print()

    index = load_index()
    # Mémorise la sélection complète dans l'index (utile pour reproduire / annoter).
    index["selection"]["per_class_counts"] = dict(sorted(per_class.items()))
    index["selection"]["selected_leaves"] = [
        {"leaf_id": lid, "workflow_class": cls} for lid, cls in selected
    ]

    n_ok = 0
    n_skip = 0
    n_ko = 0

    for idx, (lid, cls) in enumerate(selected):
        progress = f"[{idx + 1:02d}/{len(selected)}]"

        try:
            result = gen.build_prompt(lid)
        except ValueError as exc:
            print(f"  {progress} SKIP {lid} — introuvable")
            index["results"][lid] = {
                "leaf_id": lid, "workflow_class": cls,
                "status": "skip_unknown_leaf", "error": str(exc),
            }
            save_index_atomic(index)
            n_skip += 1
            continue
        except Exception as exc:
            print(f"  {progress} ERR {lid} — {type(exc).__name__}: {exc}")
            index["results"][lid] = {
                "leaf_id": lid, "workflow_class": cls,
                "status": "build_prompt_error", "error": f"{type(exc).__name__}: {exc}",
            }
            save_index_atomic(index)
            n_ko += 1
            continue

        positive = result.get("positive") or ""
        negative = result.get("negative") or ""
        reso = result.get("resolution") or (1024, 1024)
        if isinstance(reso, list):
            reso = tuple(reso)
        width, height = int(reso[0]), int(reso[1])
        leaf_name_en = result.get("leaf_name_en") or lid

        seed = SEED_BASE + idx * SEED_STRIDE
        fname = f"{lid}_{width}x{height}_euler8s.png"
        out_path = OUTPUT_DIR / fname

        prev = index["results"].get(lid)
        if prev and prev.get("status") == "ok" and out_path.is_file():
            print(f"  {progress} {lid} {width}x{height} — skip (déjà OK)")
            n_ok += 1
            continue

        gen_res = generate_image(client, positive, negative, width, height, seed, out_path)
        if not gen_res.get("ok"):
            print(f"  {progress} {lid} {width}x{height} — X Comfy: {gen_res.get('error')}")
            index["results"][lid] = {
                "leaf_id": lid, "leaf_name_en": leaf_name_en,
                "workflow_class": result.get("workflow_class") or cls,
                "technique": result.get("technique"), "pipeline": result.get("pipeline"),
                "confidence": result.get("confidence"),
                "resolution": [width, height],
                "positive": positive, "negative": negative,
                "pitfalls": result.get("pitfalls"),
                "filename": fname, "seed": seed,
                "status": "comfy_error", "error": gen_res.get("error"),
                "comfy_latency_s": gen_res.get("comfy_latency_s"),
            }
            save_index_atomic(index)
            n_ko += 1
            continue

        hist = histogram_check(out_path)
        latency = gen_res.get("comfy_latency_s")
        print(f"  {progress} {lid} {width}x{height} — {latency}s "
              f"color_ratio={hist['color_ratio']:.3f} ink_ratio={hist['ink_ratio']:.3f}")

        index["results"][lid] = {
            "leaf_id": lid, "leaf_name_en": leaf_name_en,
            "workflow_class": result.get("workflow_class") or cls,
            "technique": result.get("technique"), "pipeline": result.get("pipeline"),
            "confidence": result.get("confidence"),
            "resolution": [width, height],
            "positive": positive, "negative": negative,
            "pitfalls": result.get("pitfalls"),
            "filename": fname, "seed": seed,
            "status": "ok",
            "comfy_latency_s": latency,
            "comfy_prompt_id": gen_res.get("comfy_prompt_id"),
            "color_ratio": hist["color_ratio"],
            "ink_ratio": hist["ink_ratio"],
            "white_ratio": hist["white_ratio"],
            "histogram_ok": hist["histogram_ok"],
            "flags": hist["flags"],
        }
        save_index_atomic(index)
        n_ok += 1

    print()
    print(f"Résumé : {n_ok} OK / {n_skip} SKIP (introuvables) / {n_ko} KO")
    print(f"Index  : {INDEX_JSON.relative_to(PROJECT_ROOT)}")
    print()
    print("Annoter : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark")
    return 0


if __name__ == "__main__":
    sys.exit(main())
