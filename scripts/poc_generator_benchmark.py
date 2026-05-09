"""POC benchmark PromptGenerator -- valider les prompts template ERNIE.

Selectionne ~30 feuilles representatives par classe (Solo animal / humain action /
humain personnalite / cartoon / vehicule / objet) et genere une image par feuille
via le pipeline ERNIE direct, en lisant positive/negative/resolution depuis
``services.prompt_generator.PromptGenerator``.

Pas de vision QC -- annotation humaine via :
    http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-generator-benchmark

Pour chaque feuille :
  1. result = gen.build_prompt(leaf_id)        (ValueError -> SKIP loggue)
  2. workflow = data/workflows/ernie-image-turbo-q8-api.json (JSON brut, no contract)
  3. Modifie : node 13 width/height, 14 positive, 15 negative,
               16 seed/steps/sampler_name/scheduler/cfg
  4. QC histogram (color_ratio, ink_ratio)
  5. Sauvegarde PNG + entree atomique dans l'index JSON

Naming : {leaf_id}_{w}x{h}_euler8s.png
Output : docs/reports/poc-generator-benchmark/

Usage :
    PYTHONPATH=src python scripts/poc_generator_benchmark.py
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
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-generator-benchmark"
INDEX_JSON = OUTPUT_DIR / "poc-generator-benchmark.json"
WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

# Fixed sampler params (les seuls champs non touches par le PromptGenerator).
FIXED_STEPS = 8
FIXED_SAMPLER = "euler"
FIXED_SCHEDULER = "normal"
FIXED_CFG = 1.0
SEED_BASE = 4242
SEED_STRIDE = 7

# ───────────────── Selection des feuilles (par classe) ─────────────────
# IDs verifies contre PromptGenerator.leaf_index (1376 leaves dispo).
# 27/30 resolvent ; 3 SKIP attendus signales par le script.
LEAVES_BY_CLASS: dict[str, list[str]] = {
    "Solo animal - mammiferes": [
        "lion_in_savanna", "african_elephant", "farm_horse",
        "pet_turtle", "sea_turtle_swimming",
    ],
    "Solo insect": [
        "monarch_butterfly", "garden_spider", "honeybee_on_flower",
    ],
    "Solo fish / marine": [
        "nowruz_goldfish_in_bowl", "playful_dolphin", "clownfish_in_anemone",
    ],
    "Solo bird": [
        "soaring_eagle", "peacock_with_open_tail", "emperor_penguin",
    ],
    "Solo humain en action": [
        "firefighter_with_hose", "baker_with_bread", "doctor_with_stethoscope",
        "ballet_dancer_pose", "astronaut_floating_in_space",
    ],
    "Solo humain (personnalite)": [
        "princess_in_tower", "knight_in_shining_armor",
        "wizard_with_staff", "pirate_ship_captain",
    ],
    "Solo objet vehicule": [
        "sailing_boat", "hot_air_balloon",
        "first_steam_engine_train", "vintage_car_convertible",
    ],
    "Solo objet": [
        "birthday_cake_with_candles", "musician_with_guitar",
        "medieval_castle_with_moat",
    ],
}


# ───────────────── Index IO (atomic) ─────────────────
def load_index() -> dict:
    if INDEX_JSON.exists():
        try:
            return json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "poc": "generator-benchmark",
        "workflow_template": WORKFLOW_TEMPLATE,
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


# ───────────────── Pipeline ─────────────────
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
    print("POC generator-benchmark - PromptGenerator x ERNIE direct")
    print("=" * 100)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Aplatit la liste avec un compteur global pour le seed
    flat: list[tuple[int, str, str]] = []  # (idx, workflow_class, leaf_id)
    for cls, leaves in LEAVES_BY_CLASS.items():
        for lid in leaves:
            flat.append((len(flat), cls, lid))

    n_planned = len(flat)
    print(f"Plan : {n_planned} feuilles ({len(LEAVES_BY_CLASS)} classes)")
    print(f"Output : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}")

    gen = PromptGenerator()
    print(f"PromptGenerator initialise. Total leaves dispo : {len(gen.leaf_index)}")

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"ComfyUI OK : {client.base_url}")
    print()

    index = load_index()
    n_ok = 0
    n_skip = 0
    n_ko = 0

    for idx, cls, lid in flat:
        progress = f"[{idx + 1:02d}/{n_planned}]"

        # 1) Resolve via PromptGenerator
        try:
            result = gen.build_prompt(lid)
        except ValueError as exc:
            print(f"  {progress} SKIP {lid} - introuvable")
            index["results"][lid] = {
                "leaf_id": lid, "workflow_class": cls,
                "status": "skip_unknown_leaf", "error": str(exc),
            }
            save_index_atomic(index)
            n_skip += 1
            continue
        except Exception as exc:
            print(f"  {progress} ERR {lid} - {type(exc).__name__}: {exc}")
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

        # 2) Skip si deja OK sur disque
        prev = index["results"].get(lid)
        if prev and prev.get("status") == "ok" and out_path.is_file():
            print(f"  {progress} {lid} {width}x{height} - skip (deja OK)")
            n_ok += 1
            continue

        # 3) Generer
        gen_res = generate_image(client, positive, negative, width, height, seed, out_path)
        if not gen_res.get("ok"):
            print(f"  {progress} {lid} {width}x{height} - X Comfy: {gen_res.get('error')}")
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

        # 4) QC histogram
        hist = histogram_check(out_path)
        latency = gen_res.get("comfy_latency_s")
        print(f"  {progress} {lid} {width}x{height} - {latency}s "
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

    # ─── Resume ───
    print()
    print(f"Resume : {n_ok} OK / {n_skip} SKIP (introuvables) / {n_ko} KO")
    print(f"Index   : {INDEX_JSON.relative_to(PROJECT_ROOT)}")
    print()
    print(f"Annoter : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-generator-benchmark")
    return 0


if __name__ == "__main__":
    sys.exit(main())
