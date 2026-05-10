"""POC bench gate ERNIE — 2026-05-10.

Lance la génération ComfyUI ciblée pour les 3 transferts à risque pivot du gate
ERNIE (T2T3T23 / T25 before-after / Pivot T25 frieze+grid). Optionnel : 4
transferts non-garde-fou bonus (T9 / ISO élargi / ANAT / METEO).

Brief source : ``docs/architect/briefs/2026-05-10_brief-bench-gate-ernie.md``.

Architecture (cf. brief §27-31) :
- Dossier parent ``docs/reports/poc-bench-gate-ernie-2026-05-10/`` reçoit
  l'index global + le rapport markdown.
- 3 sous-dossiers ``poc-bench-gate-ernie-{T2T3T23|T25|pivot}`` au niveau
  ``docs/reports/`` reçoivent les PNG (annotables séparément via
  ``benchmark-annotator.html``).
- Chaque sous-dossier contient son propre ``<dir>.json`` (métriques par
  filename, schema legacy poc-generator) + un ``index-bench-gate.json``
  (subjects schema pour l'annotateur).

Usage :
    PYTHONPATH=src python scripts/poc_bench_gate_ernie.py
    PYTHONPATH=src python scripts/poc_bench_gate_ernie.py --transferts T2T3T23,T25,pivot
    PYTHONPATH=src python scripts/poc_bench_gate_ernie.py --transferts T2T3T23

Seeds (cf. brief §22-25) :
    T2T3T23 → seed_base = 300
    T25     → seed_base = 400
    pivot   → seed_base = 1000
    (bonus T9 = 200, ISO élargi = 500, ANAT = 600, METEO = 800)
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

# Désactive les warnings PromptGenerator (canonical_poses missing, etc.) — bruit
# inutile pour ce POC. On garde les errors.
logging.getLogger("services.prompt_generator").setLevel(logging.ERROR)

from services.prompt_generator import PromptGenerator  # noqa: E402
from workers.comfy_client import ComfyClient, workflows_json_dir  # noqa: E402

# ───────────────── Constantes globales ─────────────────
WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"
FIXED_STEPS = 8
FIXED_SAMPLER = "euler"
FIXED_SCHEDULER = "normal"
FIXED_CFG = 1.0

# Dossier parent (rapport + index global)
PARENT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-bench-gate-ernie-2026-05-10"
GLOBAL_INDEX_PATH = PARENT_DIR / "index-bench-gate.json"


# ───────────────── Spec de chaque transfert ─────────────────
# Chaque transfert : leafs ciblés + seed_base (offset depuis 0).
# Cf. brief §22-25.
TRANSFERTS: dict[str, dict] = {
    "T2T3T23": {
        "label": "T2T3T23 grille / imagier annoté",
        "dir": "poc-bench-gate-ernie-T2T3T23",
        "seed_base": 300,
        "stride": 7,
        "leafs": [
            "fruit_imagier_with_names",
            "vegetable_imagier_with_names",
            "weather_imagier_with_names",
            "balanced_lunch_plate",
            "healthy_breakfast_plate",
            "proud_child_face",
            "sad_child_crying",
            "fruits_basket",
            "vegetables_basket",
            "bread_and_pastries",
        ],
    },
    "T25": {
        "label": "T25 before/after (Comparatif)",
        "dir": "poc-bench-gate-ernie-T25",
        "seed_base": 400,
        "stride": 7,
        # Source : data/prompt_generator/before_after_states.json (18 leafs)
        "leafs": [
            "rainwater_collection_barrel",
            "kid_recycling_bin_sorting",
            "beach_cleanup_volunteers",
            "compost_bin_in_garden",
            "earth_with_protective_hands",
            "solar_panels_on_roof",
            "polar_bear_on_melting_ice",
            "wind_turbines_on_hill",
            "kid_planting_a_tree",
            "deforestation_before_after",
            "vegetable_garden_at_home",
            "electric_car_charging",
            "reusable_shopping_tote_bag",
            "eco_friendly_house_with_panels",
            "zero_waste_kitchen",
            "bike_to_work_commute",
            "kids_picking_up_litter",
            "reusable_water_bottle",
        ],
    },
    "pivot": {
        "label": "Pivot T25 (frieze + grid imagier)",
        "dir": "poc-bench-gate-ernie-pivot",
        "seed_base": 1000,
        "stride": 7,
        # Sélection 8-10 leafs sur 4 méta-patterns (≥2 par classe).
        # Cf. brief §23. Choix qui ne chevauchent pas la liste T2T3T23.
        # - Frise narrative 1×N : life_cycle_and_aging + four_seasons
        # - Imagier différencié 3×3 : food_categories
        # - Multi-sujets via grille : illustrated_numbers
        # - Imagier différencié OU Solo : healthy_eating
        "leafs": [
            "baby_first_year",                # Frise narrative 1×N (pattern X2)
            "spring_blooming_meadow",         # Frise narrative 1×4
            "summer_beach_day",               # Frise narrative 1×4
            "winter_snowman_in_garden",       # Frise narrative 1×4
            "cakes_and_desserts",             # Imagier différencié 3×3
            "candy_shop_display",             # Imagier différencié 3×3
            "food_pyramid_for_kids",          # Imagier différencié OU Solo
            "rainbow_fruit_plate",            # Imagier différencié OU Solo
            "number_zero_with_eggs",          # Multi-sujets via grille
            "number_one_with_apple",          # Multi-sujets via grille
        ],
    },
    # ── Bonus optionnels (Phase 3 brief §54-59) ───────────────────────────
    "T9": {
        "label": "T9 (orientation directionnelle, Solo animal résiduels)",
        "dir": "poc-bench-gate-ernie-T9",
        "seed_base": 200,
        "stride": 7,
        "leafs": [
            "lion_in_savanna",
            "elephant_in_jungle",
            "tiger_in_forest",
            "giraffe_in_savanna",
            "zebra_in_savanna",
            "wolf_in_forest",
        ],
    },
    "ISO": {
        "label": "ISO élargi (anti-multi-humains/objets)",
        "dir": "poc-bench-gate-ernie-ISO",
        "seed_base": 500,
        "stride": 7,
        "leafs": [
            "single_apple_red_fruit",
            "single_pear_yellow_fruit",
            "single_banana_yellow_fruit",
            "child_holding_balloon",
            "boy_jumping_with_joy",
            "girl_dancing_ballet",
            "scientist_with_microscope",
            "construction_worker_with_helmet",
        ],
    },
    "ANAT": {
        "label": "ANAT (overrides anatomiques five_senses + élargis)",
        "dir": "poc-bench-gate-ernie-ANAT",
        "seed_base": 600,
        "stride": 7,
        # five_senses + élargi (12 leafs si dispo)
        "leafs": [
            "human_eye_anatomy",
            "human_ear_anatomy",
            "human_nose_anatomy",
            "human_tongue_anatomy",
            "human_hand_anatomy",
            "human_skeleton_full_body",
            "human_heart_anatomy",
            "human_brain_anatomy",
            "human_lungs_anatomy",
            "human_digestive_system",
            "human_muscle_arm",
            "human_skull_diagram",
        ],
    },
    "METEO": {
        "label": "METEO (scènes atmosphériques landscape three-quarter)",
        "dir": "poc-bench-gate-ernie-METEO",
        "seed_base": 800,
        "stride": 7,
        "leafs": [
            "sunny_day_with_sun",
            "rainy_day_with_umbrella",
            "thunderstorm_with_lightning",
            "foggy_morning_landscape",
            "snowy_winter_day",
            "windy_day_with_kite",
            "rainbow_after_rain",
        ],
    },
}


# ───────────────── Helpers ─────────────────
def save_atomic(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_json_or(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


# ───────────────── ComfyUI submission ─────────────────
def submit_to_comfy(client: ComfyClient, positive: str, negative: str,
                    width: int, height: int, seed: int) -> str:
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
    wf["16"]["inputs"]["steps"] = int(FIXED_STEPS)
    wf["16"]["inputs"]["sampler_name"] = FIXED_SAMPLER
    wf["16"]["inputs"]["scheduler"] = FIXED_SCHEDULER
    wf["16"]["inputs"]["cfg"] = float(FIXED_CFG)
    return client.submit_prompt(wf)


def generate_one(client: ComfyClient, positive: str, negative: str,
                 width: int, height: int, seed: int,
                 dest_path: Path) -> dict:
    t0 = time.time()
    try:
        prompt_id = submit_to_comfy(client, positive, negative, width, height, seed)
        history = client.poll_until_done(prompt_id)
        images = client.extract_output_images(history)
        if not images:
            raise RuntimeError("Aucune image dans l'historique ComfyUI")
        img = images[0]
        client.download_image(
            filename=img["filename"], dest=dest_path,
            subfolder=img.get("subfolder", ""),
            folder_type=img.get("type", "output"),
        )
        return {
            "ok": True,
            "comfy_latency_s": round(time.time() - t0, 2),
            "comfy_prompt_id": prompt_id,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "comfy_latency_s": round(time.time() - t0, 2),
        }


# ───────────────── Run d'un transfert ─────────────────
def run_transfert(transfert_id: str, gen: PromptGenerator,
                  client: ComfyClient, global_index: dict) -> dict:
    spec = TRANSFERTS[transfert_id]
    out_dir = PROJECT_ROOT / "docs" / "reports" / spec["dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Métriques canoniques (consommées par /api/benchmark/images via results dict)
    metrics_path = out_dir / f"{spec['dir']}.json"
    metrics = load_json_or(metrics_path, {
        "poc": "bench-gate-ernie",
        "transfert": transfert_id,
        "label": spec["label"],
        "workflow_template": WORKFLOW_TEMPLATE,
        "fixed": {
            "steps": FIXED_STEPS, "sampler_name": FIXED_SAMPLER,
            "scheduler": FIXED_SCHEDULER, "cfg": FIXED_CFG,
            "seed_base": spec["seed_base"], "seed_stride": spec["stride"],
        },
        "results": {},
    })

    # Subjects index pour l'annotateur (consommé par _find_prompt_index)
    subjects_path = out_dir / "index-bench-gate.json"
    subjects_idx = load_json_or(subjects_path, {
        "transfert": transfert_id,
        "label": spec["label"],
        "subjects": [],
    })
    # On rebuild la liste pour ne pas dédoubler en cas de relance
    seen_filenames = {s.get("filename") for s in subjects_idx.get("subjects", [])
                      if isinstance(s, dict)}

    n_ok = 0
    n_ko = 0
    n_skip = 0

    for idx, leaf_id in enumerate(spec["leafs"]):
        if leaf_id not in gen.leaf_index:
            print(f"  X leaf inconnu : {leaf_id}")
            n_ko += 1
            continue

        try:
            r = gen.build_prompt(leaf_id)
        except Exception as exc:  # noqa: BLE001
            print(f"  X build_prompt({leaf_id}) : {type(exc).__name__}: {exc}")
            n_ko += 1
            continue

        positive = r.get("positive") or ""
        negative = r.get("negative") or ""
        cls = r.get("workflow_class") or "?"
        reso = r.get("resolution") or (1024, 1024)
        if isinstance(reso, list):
            reso = tuple(reso)
        width, height = int(reso[0]), int(reso[1])
        seed = int(spec["seed_base"]) + idx * int(spec["stride"])
        leaf_name_en = r.get("leaf_name_en") or leaf_id

        canonical_name = f"{leaf_id}_{width}x{height}_euler8s.png"
        canonical_path = out_dir / canonical_name

        progress = f"[{idx+1:02d}/{len(spec['leafs'])}]"
        print(f"  {progress} {leaf_id:<40} {cls[:40]:<40} {width}x{height} seed={seed}",
              flush=True)

        # Skip si déjà OK
        prev = metrics["results"].get(canonical_name)
        if prev and prev.get("status") == "ok" and canonical_path.is_file():
            print("     skip (déjà OK)")
            n_skip += 1
            # S'assure que l'entrée subjects existe
            if canonical_name not in seen_filenames:
                subjects_idx["subjects"].append({
                    "filename": canonical_name,
                    "name_en": leaf_name_en,
                    "leaf_id": leaf_id,
                    "tier": cls,
                    "workflow_class": cls,
                    "technique": r.get("technique"),
                    "pipeline": r.get("pipeline"),
                    "confidence": r.get("confidence"),
                    "pitfalls": r.get("pitfalls"),
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                    "resolution": [width, height],
                    "seed": seed,
                    "transfert": transfert_id,
                })
                seen_filenames.add(canonical_name)
                save_atomic(subjects_path, subjects_idx)
            # Update global index entry
            global_index[canonical_name] = {
                "filename": canonical_name,
                "leaf_id": leaf_id,
                "workflow_class": cls,
                "transfert": transfert_id,
                "seed": seed,
                "subdir": spec["dir"],
            }
            continue

        gen_res = generate_one(client, positive, negative, width, height, seed,
                               canonical_path)
        if not gen_res.get("ok"):
            print(f"     X {gen_res.get('error')}")
            metrics["results"][canonical_name] = {
                "leaf_id": leaf_id, "leaf_name_en": leaf_name_en,
                "workflow_class": cls,
                "resolution": [width, height], "seed": seed,
                "transfert": transfert_id,
                "status": "comfy_error", "error": gen_res.get("error"),
                "comfy_latency_s": gen_res.get("comfy_latency_s"),
            }
            save_atomic(metrics_path, metrics)
            n_ko += 1
            continue

        latency = gen_res.get("comfy_latency_s")
        print(f"     OK {latency}s  ({canonical_name})")

        metrics["results"][canonical_name] = {
            "leaf_id": leaf_id,
            "leaf_name_en": leaf_name_en,
            "workflow_class": cls,
            "technique": r.get("technique"),
            "pipeline": r.get("pipeline"),
            "confidence": r.get("confidence"),
            "pitfalls": r.get("pitfalls"),
            "resolution": [width, height],
            "seed": seed,
            "transfert": transfert_id,
            "filename": canonical_name,
            "positive": positive,
            "negative": negative,
            "status": "ok",
            "comfy_latency_s": latency,
            "comfy_prompt_id": gen_res.get("comfy_prompt_id"),
        }
        save_atomic(metrics_path, metrics)

        if canonical_name not in seen_filenames:
            subjects_idx["subjects"].append({
                "filename": canonical_name,
                "name_en": leaf_name_en,
                "leaf_id": leaf_id,
                "tier": cls,
                "workflow_class": cls,
                "technique": r.get("technique"),
                "pipeline": r.get("pipeline"),
                "confidence": r.get("confidence"),
                "pitfalls": r.get("pitfalls"),
                "positive_prompt": positive,
                "negative_prompt": negative,
                "resolution": [width, height],
                "seed": seed,
                "transfert": transfert_id,
            })
            seen_filenames.add(canonical_name)
            save_atomic(subjects_path, subjects_idx)

        global_index[canonical_name] = {
            "filename": canonical_name,
            "leaf_id": leaf_id,
            "workflow_class": cls,
            "transfert": transfert_id,
            "seed": seed,
            "subdir": spec["dir"],
        }
        save_atomic(GLOBAL_INDEX_PATH, global_index)
        n_ok += 1

    return {"n_ok": n_ok, "n_ko": n_ko, "n_skip": n_skip,
            "out_dir": str(out_dir.relative_to(PROJECT_ROOT))}


# ───────────────── Main ─────────────────
def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "--transferts", default="T2T3T23,T25,pivot",
        help=("Liste de transferts à générer, séparée par virgules. "
              f"Choix : {','.join(TRANSFERTS.keys())}. Défaut : T2T3T23,T25,pivot."),
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Liste les transferts dispos et quitte (pas de génération).",
    )
    return parser.parse_args(list(argv) if argv else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        for tid, spec in TRANSFERTS.items():
            print(f"{tid:10}  {spec['label']:50}  {len(spec['leafs'])} leafs"
                  f"  seed_base={spec['seed_base']}")
        return 0

    selected = [t.strip() for t in args.transferts.split(",") if t.strip()]
    unknown = [t for t in selected if t not in TRANSFERTS]
    if unknown:
        print(f"Transferts inconnus : {unknown}", file=sys.stderr)
        return 2
    if not selected:
        print("Aucun transfert sélectionné.", file=sys.stderr)
        return 2

    print("=" * 100)
    print(f"POC bench gate ERNIE — transferts {selected}")
    print("=" * 100)

    PARENT_DIR.mkdir(parents=True, exist_ok=True)
    global_index = load_json_or(GLOBAL_INDEX_PATH, {})

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"ComfyUI OK : {client.base_url}")

    gen = PromptGenerator()
    print(f"PromptGenerator OK : {len(gen.leaf_index)} feuilles dispo")
    print()

    summary: dict[str, dict] = {}
    for tid in selected:
        spec = TRANSFERTS[tid]
        print(f"--- {tid} ({spec['label']}) ---")
        result = run_transfert(tid, gen, client, global_index)
        summary[tid] = result
        print(f"  → OK={result['n_ok']} KO={result['n_ko']} "
              f"SKIP={result['n_skip']}  ({result['out_dir']})")
        print()

    save_atomic(GLOBAL_INDEX_PATH, global_index)

    print("=" * 100)
    print("RÉSUMÉ")
    print("=" * 100)
    for tid, res in summary.items():
        print(f"  {tid:10}  OK={res['n_ok']:3}  KO={res['n_ko']:3}  "
              f"SKIP={res['n_skip']:3}  → {res['out_dir']}")
    print()
    print(f"Index global : {GLOBAL_INDEX_PATH.relative_to(PROJECT_ROOT)}")
    print()
    print("Annotation (par transfert) :")
    for tid in selected:
        d = TRANSFERTS[tid]["dir"]
        print(f"  http://127.0.0.1:8000/data/benchmark-annotator.html?dir={d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
