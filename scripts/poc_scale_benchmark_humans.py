"""POC scale benchmark -- selection humains via PromptGenerator workflow_class.

Filtre toutes les feuilles dont ``workflow_class`` est dans HUMAN_CLASSES,
echantillonne max 50 (seed=2027 deterministe), puis genere une image par
feuille. Pour les classes a risque anatomy (``Solo humain en action`` et
``Solo humain pose active``) : ``batch_size=3`` -> 3 images sauvegardees
avec suffixes _b1/_b2/_b3, plus une copie sans suffixe (b1 par defaut).

Output : docs/reports/poc-scale-benchmark/
  - {leaf_id}_{w}x{h}_euler8s.png         (image "best" = copie de b1 si batch=3)
  - {leaf_id}_{w}x{h}_b{j}_euler8s.png    (images batch j=1..3, uniquement si batch=3)
  - poc-scale-benchmark.json              (metriques par filename, lues par annotator)
  - index-humans.json                     (subjects schema -> prompt/title/badges annotator)

Seed : 6000 + idx * 7 (pas de collision avec runs precedents).

Usage :
    PYTHONPATH=src python scripts/poc_scale_benchmark_humans.py
"""
from __future__ import annotations

import json
import random
import shutil
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
METRICS_JSON = OUTPUT_DIR / "poc-scale-benchmark.json"  # consommé par /api/benchmark/images (clé `results`)
SUBJECTS_INDEX_JSON = OUTPUT_DIR / "index-humans.json"  # consommé par _find_prompt_index (clé `subjects`)
WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

# ───────────────── Selection / batching ─────────────────
HUMAN_CLASSES: set[str] = {
    "Solo humain en action",
    "Solo humain + accessoires",
    "Solo humain (personnalité)",
    "Solo humain (générique)",
    "Solo humain pose active",
    "Solo humain (personnalité) + action figée",
    "Solo humain/animal cartoon",
    "Solo personnage ou créature",
    "Humain + entité",
}
RISK_ANATOMY_CLASSES: set[str] = {
    "Solo humain en action",
    "Solo humain pose active",
}
SAMPLE_SIZE = 50
SAMPLE_SEED = 2027

# ───────────────── ComfyUI fixed ─────────────────
FIXED_STEPS = 8
FIXED_SAMPLER = "euler"
FIXED_SCHEDULER = "normal"
FIXED_CFG = 1.0
SEED_BASE = 6000
SEED_STRIDE = 7


# ───────────────── Index IO ─────────────────
def load_metrics() -> dict:
    if METRICS_JSON.exists():
        try:
            return json.loads(METRICS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "poc": "scale-benchmark-humans",
        "workflow_template": WORKFLOW_TEMPLATE,
        "fixed": {
            "steps": FIXED_STEPS, "sampler_name": FIXED_SAMPLER,
            "scheduler": FIXED_SCHEDULER, "cfg": FIXED_CFG,
            "seed_base": SEED_BASE, "seed_stride": SEED_STRIDE,
        },
        "selection": {
            "human_classes": sorted(HUMAN_CLASSES),
            "risk_anatomy_classes": sorted(RISK_ANATOMY_CLASSES),
            "sample_size": SAMPLE_SIZE,
            "sample_seed": SAMPLE_SEED,
        },
        "results": {},
    }


def save_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


# ───────────────── ComfyUI submission ─────────────────
def submit_to_comfy(
    client: ComfyClient,
    positive: str, negative: str,
    width: int, height: int, batch_size: int,
    seed: int,
) -> str:
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    wf.pop("__meta__", None)

    wf["13"]["inputs"]["width"] = int(width)
    wf["13"]["inputs"]["height"] = int(height)
    wf["13"]["inputs"]["batch_size"] = int(batch_size)
    wf["14"]["inputs"]["text"] = positive
    if negative and negative.strip():
        wf["15"]["inputs"]["text"] = negative
    wf["16"]["inputs"]["seed"] = int(seed)
    wf["16"]["inputs"]["steps"] = int(FIXED_STEPS)
    wf["16"]["inputs"]["sampler_name"] = FIXED_SAMPLER
    wf["16"]["inputs"]["scheduler"] = FIXED_SCHEDULER
    wf["16"]["inputs"]["cfg"] = float(FIXED_CFG)

    return client.submit_prompt(wf)


def generate_batch(
    client: ComfyClient,
    positive: str, negative: str,
    width: int, height: int, batch_size: int,
    seed: int, leaf_id: str,
) -> dict:
    """Genere `batch_size` images, sauvegarde toutes les sorties.

    Pour batch_size=1 : ecrit ``{leaf_id}_{w}x{h}_euler8s.png``.
    Pour batch_size=3 : ecrit b1/b2/b3 + copie b1 sans suffixe.
    """
    t0 = time.time()
    try:
        prompt_id = submit_to_comfy(client, positive, negative, width, height, batch_size, seed)
        history = client.poll_until_done(prompt_id)
        images = client.extract_output_images(history)
        if not images:
            raise RuntimeError("Aucune image dans l'historique ComfyUI")

        canonical_name = f"{leaf_id}_{width}x{height}_euler8s.png"
        canonical_path = OUTPUT_DIR / canonical_name

        batch_filenames: list[str] = []
        if batch_size == 1:
            client.download_image(
                filename=images[0]["filename"], dest=canonical_path,
                subfolder=images[0].get("subfolder", ""),
                folder_type=images[0].get("type", "output"),
            )
            batch_filenames = [canonical_name]
        else:
            # On genere autant de _b{j}.png que de sorties Comfy (max batch_size)
            n = min(len(images), batch_size)
            for j in range(n):
                fname = f"{leaf_id}_{width}x{height}_b{j+1}_euler8s.png"
                fpath = OUTPUT_DIR / fname
                client.download_image(
                    filename=images[j]["filename"], dest=fpath,
                    subfolder=images[j].get("subfolder", ""),
                    folder_type=images[j].get("type", "output"),
                )
                batch_filenames.append(fname)
            # Copie b1 vers le filename sans suffixe (best par defaut)
            if batch_filenames:
                shutil.copyfile(OUTPUT_DIR / batch_filenames[0], canonical_path)

        return {
            "ok": True,
            "comfy_latency_s": round(time.time() - t0, 2),
            "comfy_prompt_id": prompt_id,
            "n_outputs_generated": len(images),
            "canonical_filename": canonical_name,
            "batch_filenames": batch_filenames,
        }
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


# ───────────────── Selection ─────────────────
def select_human_leaves(gen: PromptGenerator) -> list[tuple[str, dict]]:
    """Filtre + echantillonne 50 leaves humaines deterministe (seed=2027).

    Retourne liste de tuples (leaf_id, build_prompt_result) dans l'ordre
    determinist du sample.
    """
    pool: list[tuple[str, dict]] = []
    for lid in sorted(gen.leaf_index.keys()):  # tri pour reproductibilite
        try:
            r = gen.build_prompt(lid)
        except Exception:
            continue
        if (r.get("workflow_class") or "") in HUMAN_CLASSES:
            pool.append((lid, r))
    rng = random.Random(SAMPLE_SEED)
    n = min(SAMPLE_SIZE, len(pool))
    sample = rng.sample(pool, n)
    return sample


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC scale-benchmark humains - PromptGenerator x ERNIE direct")
    print("=" * 100)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    gen = PromptGenerator()
    print(f"PromptGenerator initialise. Total leaves dispo : {len(gen.leaf_index)}")

    sample = select_human_leaves(gen)
    n_total = len(sample)
    print(f"Selection humaine : {n_total} feuilles (sample seed={SAMPLE_SEED}, max={SAMPLE_SIZE})")

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"ComfyUI OK : {client.base_url}")
    print()

    metrics = load_metrics()

    # subjects index (pour annotator)
    subjects_index: dict = {
        "source": "PromptGenerator workflow_class filter -> sample(seed=2027)",
        "human_classes": sorted(HUMAN_CLASSES),
        "subjects": [],
    }

    n_ok = 0
    n_ko = 0

    for idx, (leaf_id, result) in enumerate(sample):
        cls = result.get("workflow_class") or "?"
        risk = cls in RISK_ANATOMY_CLASSES
        batch_size = 3 if risk else 1
        positive = result.get("positive") or ""
        negative = result.get("negative") or ""
        reso = result.get("resolution") or (1024, 1024)
        if isinstance(reso, list):
            reso = tuple(reso)
        width, height = int(reso[0]), int(reso[1])
        leaf_name_en = result.get("leaf_name_en") or leaf_id
        seed = SEED_BASE + idx * SEED_STRIDE
        canonical_name = f"{leaf_id}_{width}x{height}_euler8s.png"
        canonical_path = OUTPUT_DIR / canonical_name

        progress = f"[{idx+1:02d}/{n_total}]"
        risk_tag = "ANATOMY×3" if risk else "x1"
        print(f"  {progress} {leaf_id:<40} {cls:<40} {width}x{height} {risk_tag}", flush=True)

        # Skip si deja OK
        prev = metrics["results"].get(canonical_name)
        if prev and prev.get("status") == "ok" and canonical_path.is_file():
            print(f"     skip (deja OK)")
            n_ok += 1
            continue

        gen_res = generate_batch(client, positive, negative, width, height, batch_size, seed, leaf_id)
        if not gen_res.get("ok"):
            print(f"     X {gen_res.get('error')}")
            metrics["results"][canonical_name] = {
                "leaf_id": leaf_id, "leaf_name_en": leaf_name_en,
                "workflow_class": cls,
                "resolution": [width, height], "seed": seed,
                "batch_size": batch_size, "risk_anatomy": risk,
                "status": "comfy_error", "error": gen_res.get("error"),
                "comfy_latency_s": gen_res.get("comfy_latency_s"),
            }
            save_atomic(METRICS_JSON, metrics)
            n_ko += 1
            continue

        hist = histogram_check(canonical_path)
        latency = gen_res.get("comfy_latency_s")
        print(f"     OK {latency}s color_ratio={hist['color_ratio']:.4f} ink_ratio={hist['ink_ratio']:.3f}"
              + (f"  batch={len(gen_res['batch_filenames'])}" if risk else ""))

        # Metrics entry
        metrics["results"][canonical_name] = {
            "leaf_id": leaf_id, "leaf_name_en": leaf_name_en,
            "workflow_class": cls, "technique": result.get("technique"),
            "pipeline": result.get("pipeline"), "confidence": result.get("confidence"),
            "pitfalls": result.get("pitfalls"),
            "resolution": [width, height], "seed": seed,
            "batch_size": batch_size, "risk_anatomy": risk,
            "filename": canonical_name,
            "batch_filenames": gen_res.get("batch_filenames", []),
            "status": "ok",
            "comfy_latency_s": latency,
            "comfy_prompt_id": gen_res.get("comfy_prompt_id"),
            "color_ratio": hist["color_ratio"],
            "ink_ratio": hist["ink_ratio"],
            "white_ratio": hist["white_ratio"],
            "histogram_ok": hist["histogram_ok"],
            "flags": hist["flags"],
        }
        save_atomic(METRICS_JSON, metrics)

        # Subjects index entry (filename = canonical, batch_filenames stocké)
        subjects_index["subjects"].append({
            "filename": canonical_name,
            "name_en": leaf_name_en,
            "leaf_id": leaf_id,
            "tier": cls,  # affiché comme tier dans l'annotator
            "workflow_class": cls,
            "technique": result.get("technique"),
            "pipeline": result.get("pipeline"),
            "confidence": result.get("confidence"),
            "pitfalls": result.get("pitfalls"),
            "positive_prompt": positive,
            "negative_prompt": negative,
            "resolution": [width, height],
            "batch_size": batch_size,
            "risk_anatomy": risk,
            "batch_filenames": gen_res.get("batch_filenames", []),
            "seed": seed,
        })
        save_atomic(SUBJECTS_INDEX_JSON, subjects_index)
        n_ok += 1

    print()
    print(f"Resume : {n_ok} OK / {n_ko} KO  -> {METRICS_JSON.relative_to(PROJECT_ROOT)}")
    print(f"        subjects-index -> {SUBJECTS_INDEX_JSON.relative_to(PROJECT_ROOT)}")
    print()
    print(f"Annoter : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark")
    return 0


if __name__ == "__main__":
    sys.exit(main())
