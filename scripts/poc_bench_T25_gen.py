"""POC bench T25 - generation des 20 images post-pivot pour mesure garde-fou.

Genere 20 images post-pivot des templates `template_frieze_1xN` et
`template_grid_3x3_imagier` (refactores 2026-05-10 en BEFORE/AFTER ou
SPOT-THE-DIFFERENCE) afin de mesurer le taux de defauts composition
`image_pas_coherente` + `image_incomprehensible` vs baseline pre-pivot.

Specifications (cf. brief 2026-05-10_brief-bench-gardefou-T25.md) :
- 10 leaves sur frise (8 frise narrative + 2 multi-sujets frise)
- 10 leaves sur grille (5 imagier differencie 3x3 + 5 multi-sujets via grille)
- Seed offset = 800 (different des reruns precedents qui utilisent 100)
- Parametres image figes CLAUDE.md : sampler=euler, steps=8, cfg=1.0,
  scheduler=normal. Resolution selon workflow_class (cartographie adaptative).
- Output : docs/reports/poc-bench-T25-postPivot/
- Index : index-bench-T25.json (schema subjects standard)
- annotations.json cree vide (a remplir via annotateur v2 mode `?dir=...`)

Usage :
    PYTHONPATH=src python scripts/poc_bench_T25_gen.py
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

from services.prompt_generator import PromptGenerator  # noqa: E402
from workers.comfy_client import ComfyClient, workflows_json_dir  # noqa: E402

# ───────────────── Paths ─────────────────
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-bench-T25-postPivot"
INDEX_FILE = OUTPUT_DIR / "index-bench-T25.json"
ANNOTATIONS_FILE = OUTPUT_DIR / "annotations.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"
SEED_OFFSET = 800

# ───────────────── Image params figes (CLAUDE.md) ─────────────────
SAMPLER = "euler"
STEPS = 8
CFG = 1.0
SCHEDULER = "normal"

# ───────────────── Selection 10+10 leaves ─────────────────
# Source : annotations pre-pivot poc-scale-benchmark/annotations.json + index-*.json
# Privilegier les leaves avec defauts image_pas_coherente / image_incomprehensible

FRISE_LEAVES: list[tuple[str, int]] = [
    # Frise narrative 1xN (pattern X2) - 8 leaves dont 6 avec defauts
    ("teenager_with_backpack", 9070),
    ("child_at_school_age", 9077),
    ("life_cycle_full_poster", 9084),
    ("toddler_learning_to_walk", 9091),
    ("parent_with_child", 9098),
    ("baby_first_year", 9105),
    ("grandparent_with_grandchild", 9112),
    ("young_adult_at_work", 9119),
    # Multi-sujets (frise) - 2 leaves additionnelles (pivot template_frieze_1xN aussi)
    ("classroom_with_teacher", 9200),
    ("school_bus_with_kids", 9207),
]

GRID_LEAVES: list[tuple[str, int]] = [
    # Imagier differencie 3x3 - 5 leaves dont 4 avec defauts
    ("ice_cream_and_sorbets", 9511),
    ("dairy_products_milk", 9525),
    ("vegetables_basket", 9532),
    ("fruits_basket", 9539),
    ("bread_and_pastries", 9490),
    # Multi-sujets via grille (meta-pattern §2) - 5 leaves dont 1 avec defauts explicites
    ("decorative_number_ten_fingers", 9623),
    ("number_zero_with_eggs", 9595),
    ("number_three_with_birds", 9602),
    ("number_one_with_apple", 9637),
    ("number_nine_with_cars", 9616),
]

ALL_LEAVES: list[tuple[str, int, str]] = [
    *((lid, seed, "frise") for lid, seed in FRISE_LEAVES),
    *((lid, seed, "grid") for lid, seed in GRID_LEAVES),
]


# ───────────────── Helpers ─────────────────
def submit_to_comfy(
    client: ComfyClient,
    positive: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
) -> str:
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
    wf["16"]["inputs"]["steps"] = int(STEPS)
    wf["16"]["inputs"]["sampler_name"] = SAMPLER
    wf["16"]["inputs"]["scheduler"] = SCHEDULER
    wf["16"]["inputs"]["cfg"] = float(CFG)
    return client.submit_prompt(wf)


def generate_one(
    client: ComfyClient,
    positive: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    out_path: Path,
) -> dict:
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
        return {
            "ok": True,
            "comfy_latency_s": round(time.time() - t0, 2),
            "comfy_prompt_id": prompt_id,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "comfy_latency_s": round(time.time() - t0, 2),
        }


def save_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def make_filename(leaf_id: str, width: int, height: int) -> str:
    return f"{leaf_id}_{width}x{height}_T25_{SAMPLER}{STEPS}s.png"


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC bench T25 - generation 20 images post-pivot (10 frise + 10 grid)")
    print("=" * 100)
    print(f"Output dir : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}")
    print(f"Seed offset : +{SEED_OFFSET}")
    print(
        f"Image params : sampler={SAMPLER} steps={STEPS} cfg={CFG} scheduler={SCHEDULER}"
    )
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ComfyUI sanity check (echec fort, pas de fallback silencieux)
    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI INDISPONIBLE sur {client.base_url}", file=sys.stderr)
        print(
            "  Le brief impose un echec fort. Demarrer ComfyUI avant de relancer.",
            file=sys.stderr,
        )
        return 2
    print(f"ComfyUI OK : {client.base_url}")

    gen = PromptGenerator()
    print(f"PromptGenerator initialise. Total leaves dispo : {len(gen.leaf_index)}")
    print()

    # Build subjects (schema standard)
    subjects: list[dict] = []
    n_ok = 0
    n_ko = 0

    for idx, (leaf_id, seed_orig, group) in enumerate(ALL_LEAVES):
        progress = f"[{idx+1:02d}/{len(ALL_LEAVES)}]"

        # Build prompt post-pivot
        try:
            r = gen.build_prompt(leaf_id)
        except Exception as exc:
            print(f"  {progress} SKIP {leaf_id} : build_prompt error: {exc}")
            subjects.append(
                {
                    "leaf_id": leaf_id,
                    "group": group,
                    "status": "build_prompt_error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "seed": int(seed_orig) + SEED_OFFSET,
                }
            )
            n_ko += 1
            continue

        positive = r.get("positive") or ""
        negative = r.get("negative") or ""
        reso = r.get("resolution") or (1024, 1024)
        if isinstance(reso, list):
            reso = tuple(reso)
        width = int(reso[0]) if reso[0] is not None else 1024
        height = int(reso[1]) if reso[1] is not None else 1024
        workflow_class = r.get("workflow_class") or ""
        technique = r.get("technique") or ""
        confidence = r.get("confidence") or ""
        pipeline = r.get("pipeline") or ""

        seed = int(seed_orig) + SEED_OFFSET
        filename = make_filename(leaf_id, width, height)
        out_path = OUTPUT_DIR / filename

        print(
            f"  {progress} {leaf_id:<35} seed={seed} reso={width}x{height} group={group}"
        )

        # Generate
        gen_res = generate_one(
            client, positive, negative, width, height, seed, out_path
        )
        if not gen_res.get("ok"):
            print(f"     X {gen_res.get('error')}")
            subjects.append(
                {
                    "filename": filename,
                    "output_file": filename,
                    "leaf_id": leaf_id,
                    "name_en": r.get("leaf_name_en") or "",
                    "group": group,
                    "tier": workflow_class,
                    "workflow_class": workflow_class,
                    "technique": technique,
                    "pipeline": pipeline,
                    "confidence": confidence,
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                    "resolution": [width, height],
                    "seed": seed,
                    "seed_original": int(seed_orig),
                    "seed_offset": SEED_OFFSET,
                    "sampler": SAMPLER,
                    "steps": STEPS,
                    "cfg": CFG,
                    "scheduler": SCHEDULER,
                    "status": "comfy_error",
                    "error": gen_res.get("error"),
                    "comfy_latency_s": gen_res.get("comfy_latency_s"),
                }
            )
            n_ko += 1
            # Save partial index immediately so we don't lose state on crash
            save_atomic(
                INDEX_FILE,
                {
                    "source": "POC bench T25 post-pivot (brief 2026-05-10)",
                    "seed_offset": SEED_OFFSET,
                    "image_params": {
                        "sampler": SAMPLER,
                        "steps": STEPS,
                        "cfg": CFG,
                        "scheduler": SCHEDULER,
                    },
                    "subjects": subjects,
                },
            )
            continue

        latency = gen_res.get("comfy_latency_s")
        print(f"     OK {latency}s")

        subjects.append(
            {
                "filename": filename,
                "output_file": filename,
                "leaf_id": leaf_id,
                "name_en": r.get("leaf_name_en") or "",
                "group": group,
                "tier": workflow_class,
                "workflow_class": workflow_class,
                "technique": technique,
                "pipeline": pipeline,
                "confidence": confidence,
                "positive_prompt": positive,
                "negative_prompt": negative,
                "resolution": [width, height],
                "seed": seed,
                "seed_original": int(seed_orig),
                "seed_offset": SEED_OFFSET,
                "sampler": SAMPLER,
                "steps": STEPS,
                "cfg": CFG,
                "scheduler": SCHEDULER,
                "status": "ok",
                "comfy_latency_s": latency,
                "comfy_prompt_id": gen_res.get("comfy_prompt_id"),
            }
        )
        n_ok += 1
        save_atomic(
            INDEX_FILE,
            {
                "source": "POC bench T25 post-pivot (brief 2026-05-10)",
                "seed_offset": SEED_OFFSET,
                "image_params": {
                    "sampler": SAMPLER,
                    "steps": STEPS,
                    "cfg": CFG,
                    "scheduler": SCHEDULER,
                },
                "subjects": subjects,
            },
        )

    # Final index
    save_atomic(
        INDEX_FILE,
        {
            "source": "POC bench T25 post-pivot (brief 2026-05-10)",
            "seed_offset": SEED_OFFSET,
            "image_params": {
                "sampler": SAMPLER,
                "steps": STEPS,
                "cfg": CFG,
                "scheduler": SCHEDULER,
            },
            "subjects": subjects,
        },
    )

    # annotations.json vide (annotateur v2)
    if not ANNOTATIONS_FILE.is_file():
        save_atomic(
            ANNOTATIONS_FILE,
            {
                "dir": "poc-bench-T25-postPivot",
                "annotations": {},
            },
        )
        print()
        print(f"annotations.json cree (vide) : {ANNOTATIONS_FILE.relative_to(PROJECT_ROOT)}")
    else:
        print()
        print(
            f"annotations.json deja present, conserve : {ANNOTATIONS_FILE.relative_to(PROJECT_ROOT)}"
        )

    print()
    print(f"Resume : {n_ok} OK / {n_ko} KO sur {len(ALL_LEAVES)}")
    print(f"Index   : {INDEX_FILE.relative_to(PROJECT_ROOT)}")
    print(
        "Annotateur :"
        " http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-bench-T25-postPivot"
    )
    return 0 if n_ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
