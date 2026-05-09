"""Re-run cible des cas annotes ``2_objets`` avec score <= 2.

Lit ``docs/reports/poc-scale-benchmark/annotations.json``, filtre les filenames
ayant le defaut ``2_objets`` et un score <= 2 (hors cas intentionnels
``letter_z_with_zebre`` et ``animal_superhero``), puis regenere chaque image
via ``PromptGenerator`` (templates corriges) + ComfyUI.

Particularites :
- Seed : seed_original + 100 (distinguer du run original)
- Suffix filename : ``_v2`` avant ``.png``
  ex. ``bactrian_camel_1024x1024_euler8s.png`` -> ``bactrian_camel_1024x1024_euler8s_v2.png``
- Output : meme dossier ``docs/reports/poc-scale-benchmark/``
- Index resultats : ``docs/reports/poc-scale-benchmark/rerun-2objets.json``

Usage :
    PYTHONPATH=src python scripts/poc_rerun_2objets.py
"""
from __future__ import annotations

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

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from services.prompt_generator import PromptGenerator  # noqa: E402
from workers.comfy_client import ComfyClient, workflows_json_dir  # noqa: E402

# ───────────────── Paths ─────────────────
SCALE_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-scale-benchmark"
ANNOTATIONS_FILE = SCALE_DIR / "annotations.json"
METRICS_FILE = SCALE_DIR / "poc-scale-benchmark.json"
OUTPUT_INDEX = SCALE_DIR / "rerun-2objets.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"
EXCLUDE_LEAVES = {"letter_z_with_zebre", "animal_superhero"}
SEED_OFFSET = 100  # added to original seed to distinguish from v1


# ───────────────── Helpers ─────────────────
def load_critical_filenames() -> list[str]:
    """Liste filenames avec defects=2_objets et score<=2, hors exclus."""
    data = json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    annotations = data.get("annotations") or {}
    out: list[str] = []
    for fname, ann in annotations.items():
        score = ann.get("score")
        defects = ann.get("defects") or []
        if score is None or score > 2:
            continue
        if "2_objets" not in defects:
            continue
        # Exclure cas intentionnels
        base = fname.removesuffix(".png").lower()
        if any(excl in base for excl in EXCLUDE_LEAVES):
            continue
        out.append(fname)
    return sorted(out)


def find_metrics_entry(filename: str) -> dict | None:
    """Cherche l'entree pour ce filename dans tous les index JSON du dossier.

    Le dossier ``poc-scale-benchmark/`` peut contenir plusieurs fichiers
    d'index (poc-scale-benchmark.json pour humains, index-nature.json,
    index-objects.json...) avec des schemas differents :
    - clef = filename (legacy / humains)
    - clef = leaf_id, ``filename`` dans la valeur (nature / objects)

    Retourne la 1re entree dont le filename matche.
    """
    for json_path in sorted(SCALE_DIR.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        results = (data.get("results") if isinstance(data, dict) else None) or {}
        if not isinstance(results, dict):
            continue
        # Schema 1 : clef = filename
        if filename in results and isinstance(results[filename], dict):
            return results[filename]
        # Schema 2 : clef = leaf_id, filename dans la valeur
        for entry in results.values():
            if isinstance(entry, dict) and entry.get("filename") == filename:
                return entry
    return None


def submit_to_comfy(client: ComfyClient, positive: str, negative: str,
                     width: int, height: int, seed: int,
                     steps: int = 8, sampler: str = "euler",
                     scheduler: str = "normal", cfg: float = 1.0) -> str:
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    wf.pop("__meta__", None)
    wf["13"]["inputs"]["width"] = int(width)
    wf["13"]["inputs"]["height"] = int(height)
    wf["13"]["inputs"]["batch_size"] = 1
    wf["14"]["inputs"]["text"] = positive
    if negative and negative.strip():
        wf["15"]["inputs"]["text"] = negative
    wf["16"]["inputs"]["seed"] = int(seed)
    wf["16"]["inputs"]["steps"] = int(steps)
    wf["16"]["inputs"]["sampler_name"] = sampler
    wf["16"]["inputs"]["scheduler"] = scheduler
    wf["16"]["inputs"]["cfg"] = float(cfg)
    return client.submit_prompt(wf)


def generate_v2(client: ComfyClient, positive: str, negative: str,
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
            filename=first["filename"], dest=out_path,
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


def save_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC re-run 2_objets - regen avec templates corriges")
    print("=" * 100)

    if not ANNOTATIONS_FILE.is_file():
        print(f"X annotations.json introuvable : {ANNOTATIONS_FILE}", file=sys.stderr)
        return 1

    critical = load_critical_filenames()
    print(f"Cas critiques eligibles : {len(critical)}")
    for f in critical:
        print(f"  - {f}")
    print()

    if not critical:
        print("Rien a regenerer.")
        return 0

    gen = PromptGenerator()
    print(f"PromptGenerator initialise. Total leaves dispo : {len(gen.leaf_index)}")

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"ComfyUI OK : {client.base_url}")
    print()

    output: dict = {
        "poc": "rerun-2objets",
        "seed_offset": SEED_OFFSET,
        "n_eligible": len(critical),
        "exclude": sorted(EXCLUDE_LEAVES),
        "results": {},  # key = filename_v2
    }

    n_ok, n_ko, n_skip = 0, 0, 0
    for idx, fname in enumerate(critical):
        progress = f"[{idx+1:02d}/{len(critical)}]"
        # Recupere l'entree metrics pour le leaf_id et seed original
        metrics_entry = find_metrics_entry(fname)
        if not metrics_entry:
            print(f"  {progress} SKIP {fname} : pas dans poc-scale-benchmark.json::results")
            n_skip += 1
            continue
        leaf_id = metrics_entry.get("leaf_id")
        if not leaf_id:
            print(f"  {progress} SKIP {fname} : pas de leaf_id dans metrics")
            n_skip += 1
            continue

        # Re-build prompt avec les templates corriges
        try:
            r = gen.build_prompt(leaf_id)
        except Exception as exc:
            print(f"  {progress} SKIP {leaf_id} : {type(exc).__name__}: {exc}")
            output["results"][fname] = {
                "leaf_id": leaf_id, "filename_original": fname,
                "status": "build_prompt_error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            save_atomic(OUTPUT_INDEX, output)
            n_skip += 1
            continue

        positive_v2 = r.get("positive") or ""
        negative_v2 = r.get("negative") or ""
        reso = r.get("resolution") or (1024, 1024)
        if isinstance(reso, list):
            reso = tuple(reso)
        width, height = int(reso[0]), int(reso[1])

        seed_orig = int(metrics_entry.get("seed") or 0)
        seed_v2 = seed_orig + SEED_OFFSET
        positive_v1 = metrics_entry.get("positive") or metrics_entry.get("positive_prompt") or ""

        # Filename v2 (suffixe avant .png)
        fname_v2 = fname.replace(".png", "_v2.png")
        out_path = SCALE_DIR / fname_v2

        print(f"  {progress} {leaf_id:<32} seed {seed_orig}->{seed_v2} reso={width}x{height}")

        gen_res = generate_v2(client, positive_v2, negative_v2, width, height, seed_v2, out_path)
        if not gen_res.get("ok"):
            print(f"     X {gen_res.get('error')}")
            output["results"][fname] = {
                "leaf_id": leaf_id,
                "filename_original": fname,
                "filename_v2": fname_v2,
                "seed_original": seed_orig,
                "seed_v2": seed_v2,
                "resolution": [width, height],
                "positive_v1_chars": len(positive_v1),
                "positive_v2": positive_v2,
                "positive_diff": positive_v1 != positive_v2,
                "negative_v2": negative_v2,
                "status": "comfy_error",
                "error": gen_res.get("error"),
                "comfy_latency_s": gen_res.get("comfy_latency_s"),
            }
            save_atomic(OUTPUT_INDEX, output)
            n_ko += 1
            continue

        hist = histogram_check(out_path)
        latency = gen_res.get("comfy_latency_s")
        diff_marker = " (PROMPT INCHANGE)" if positive_v1 == positive_v2 else " (prompt v2 != v1)"
        print(f"     OK {latency}s color_ratio={hist['color_ratio']:.4f} hist_ok={hist['histogram_ok']}{diff_marker}")

        output["results"][fname] = {
            "leaf_id": leaf_id,
            "leaf_name_en": r.get("leaf_name_en"),
            "workflow_class": r.get("workflow_class"),
            "filename_original": fname,
            "filename_v2": fname_v2,
            "seed_original": seed_orig,
            "seed_v2": seed_v2,
            "resolution": [width, height],
            "positive_v1_chars": len(positive_v1),
            "positive_v2": positive_v2,
            "positive_diff": positive_v1 != positive_v2,
            "negative_v2": negative_v2,
            "status": "ok",
            "comfy_latency_s": latency,
            "comfy_prompt_id": gen_res.get("comfy_prompt_id"),
            "color_ratio": hist["color_ratio"],
            "ink_ratio": hist["ink_ratio"],
            "white_ratio": hist["white_ratio"],
            "histogram_ok": hist["histogram_ok"],
            "flags": hist["flags"],
        }
        save_atomic(OUTPUT_INDEX, output)
        n_ok += 1

    print()
    print(f"Resume : {n_ok} OK / {n_ko} KO / {n_skip} SKIP")
    print(f"Index  : {OUTPUT_INDEX.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
