"""POC scale-benchmark -- couverture des classes non couvertes (confidence Haute).

Identifie les ``workflow_class`` du PromptGenerator non encore traitees par
``poc_scale_benchmark_humans/nature/objects`` et ayant ``confidence == 'Haute'``
(strict). Pour chaque classe, echantillonne max 10 leaves (seed 2027) et genere
les images via ERNIE direct.

Output : docs/reports/poc-scale-benchmark/
  - {leaf_id}_{w}x{h}_euler8s.png    (image canonique)
  - index-<slug_class>.json          (subjects schema, 1 par classe)
  - poc-scale-benchmark.json         (metriques fusionnees, mises a jour incrementalement)

Le multi-index fusion (cf. fix benchmark.py 2026-05-09) permet a l'annotateur
de retrouver titre/prompt/badges via tous les ``index-*.json`` du dossier.

Seed : 9000 + idx_global * 7 (sans collision avec runs precedents 4xxx-7xxx).

Usage :
    PYTHONPATH=src python scripts/poc_scale_benchmark_uncovered.py
    PYTHONPATH=src python scripts/poc_scale_benchmark_uncovered.py --only-class "Scene paysage"
    PYTHONPATH=src python scripts/poc_scale_benchmark_uncovered.py --limit-classes 5
"""
from __future__ import annotations

import json
import random
import re
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
METRICS_JSON = OUTPUT_DIR / "poc-scale-benchmark.json"
WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

# ───────────────── Coverage ─────────────────
# Classes deja couvertes par les runs precedents (humans + nature + objects)
# et par la liste fournie par l'utilisateur.
COVERED_CLASSES: set[str] = {
    "Solo animal", "Solo insect", "Solo fish", "Solo bird",
    "Solo humain en action", "Solo humain + accessoires",
    "Solo objet", "Solo objet (véhicule)",
    "Lettre + objet", "Variable",
    "Solo humain (personnalité)",
    "Solo humain (générique)",
    "Solo humain pose active",
    "Solo humain (personnalité) + action figée",
    "Solo humain/animal cartoon",
    "Solo personnage ou créature",
    "Humain + entité",
}

# ───────────────── ComfyUI fixed ─────────────────
FIXED_STEPS = 8
FIXED_SAMPLER = "euler"
FIXED_SCHEDULER = "normal"
FIXED_CFG = 1.0
SEED_BASE = 9000
SEED_STRIDE = 7
SAMPLE_PER_CLASS = 10
SAMPLE_SEED = 2027
CONFIDENCE_FILTER = "Haute"  # strict


# ───────────────── Helpers ─────────────────
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_class(name: str) -> str:
    s = (name or "").lower()
    # remove diacritics roughly
    s = (
        s.replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
         .replace("à", "a").replace("â", "a").replace("ä", "a")
         .replace("î", "i").replace("ï", "i")
         .replace("ô", "o").replace("ö", "o")
         .replace("û", "u").replace("ü", "u").replace("ù", "u")
         .replace("ç", "c").replace("œ", "oe").replace("ñ", "n")
    )
    s = _SLUG_RE.sub("_", s).strip("_")
    return s or "untitled"


def discover_uncovered_classes(gen: PromptGenerator) -> list[tuple[str, list[tuple[str, dict]]]]:
    """Pour chaque classe non couverte avec confidence stricte 'Haute',
    retourne [(class_name, [(leaf_id, build_prompt_result), ...])] echantillonne.
    """
    by_class: dict[str, list[tuple[str, dict]]] = {}
    for lid in sorted(gen.leaf_index.keys()):
        try:
            r = gen.build_prompt(lid)
        except Exception:
            continue
        cls = r.get("workflow_class") or ""
        conf = r.get("confidence") or ""
        if not cls or cls in COVERED_CLASSES:
            continue
        if conf != CONFIDENCE_FILTER:
            continue
        by_class.setdefault(cls, []).append((lid, r))
    # Echantillonne 10 par classe (deterministe seed=2027)
    rng = random.Random(SAMPLE_SEED)
    out: list[tuple[str, list[tuple[str, dict]]]] = []
    for cls in sorted(by_class):
        pool = by_class[cls]
        # Tri pre-sample pour reproductibilite
        pool.sort(key=lambda t: t[0])
        n = min(SAMPLE_PER_CLASS, len(pool))
        # Sample local independant pour eviter la dependance d'ordre entre classes
        local_rng = random.Random(SAMPLE_SEED + hash(cls) % 100000)
        sample = local_rng.sample(pool, n)
        out.append((cls, sample))
    return out


def index_path_for_class(cls: str) -> Path:
    return OUTPUT_DIR / f"index-{slugify_class(cls)}.json"


# ───────────────── Index IO ─────────────────
def load_metrics() -> dict:
    if METRICS_JSON.exists():
        try:
            return json.loads(METRICS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "poc": "scale-benchmark",
        "workflow_template": WORKFLOW_TEMPLATE,
        "fixed": {"steps": FIXED_STEPS, "sampler_name": FIXED_SAMPLER,
                  "scheduler": FIXED_SCHEDULER, "cfg": FIXED_CFG},
        "results": {},
    }


def save_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def append_subject_to_class_index(cls: str, subject: dict) -> None:
    """Ajoute (ou remplace par filename) un subject dans index-<slug>.json."""
    p = index_path_for_class(cls)
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = None
    else:
        data = None
    if not isinstance(data, dict):
        data = {
            "source": f"workflow_class={cls!r} | confidence=Haute | sample seed={SAMPLE_SEED}",
            "workflow_class": cls,
            "subjects": [],
        }
    subjects = data.setdefault("subjects", [])
    # Replace by filename if already present
    fname = subject.get("filename")
    subjects = [s for s in subjects if not (isinstance(s, dict) and s.get("filename") == fname)]
    subjects.append(subject)
    data["subjects"] = subjects
    save_atomic(p, data)


# ───────────────── ComfyUI ─────────────────
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


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC scale-benchmark uncovered classes (confidence=Haute, max=10/class)")
    print("=" * 100)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # CLI options
    only_class = None
    limit = None
    if "--only-class" in sys.argv:
        i = sys.argv.index("--only-class")
        if i + 1 < len(sys.argv):
            only_class = sys.argv[i + 1].strip()
    if "--limit-classes" in sys.argv:
        i = sys.argv.index("--limit-classes")
        if i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                pass

    gen = PromptGenerator()
    print(f"PromptGenerator initialise. Total leaves : {len(gen.leaf_index)}")

    plan = discover_uncovered_classes(gen)
    if only_class:
        plan = [t for t in plan if t[0] == only_class]
    if limit is not None:
        plan = plan[:limit]

    n_classes = len(plan)
    n_total = sum(len(s) for _, s in plan)
    print(f"Classes a traiter : {n_classes}  ({CONFIDENCE_FILTER}, hors deja couvertes)")
    print(f"Images a generer  : {n_total}  (max {SAMPLE_PER_CLASS}/classe)")
    for cls, sample in plan:
        print(f"  - {cls:<55} {len(sample)} leaves")
    print()

    if n_total == 0:
        print("Rien a generer.")
        return 0

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"ComfyUI OK : {client.base_url}")
    print()

    metrics = load_metrics()
    n_ok = 0
    n_ko = 0
    n_skip = 0
    idx_global = 0

    for cls, sample in plan:
        slug = slugify_class(cls)
        for leaf_id, result in sample:
            seed = SEED_BASE + idx_global * SEED_STRIDE
            idx_global += 1
            positive = result.get("positive") or ""
            negative = result.get("negative") or ""
            reso = result.get("resolution") or (1024, 1024)
            if isinstance(reso, list):
                reso = tuple(reso)
            width, height = int(reso[0]), int(reso[1])
            leaf_name_en = result.get("leaf_name_en") or leaf_id
            fname = f"{leaf_id}_{width}x{height}_euler8s.png"
            out_path = OUTPUT_DIR / fname

            label = f"[{idx_global:03d}/{n_total}] [{cls[:30]}] {leaf_id}"

            # Skip si deja sur disque + dans metrics
            prev = metrics["results"].get(fname)
            if prev and prev.get("status") == "ok" and out_path.is_file():
                print(f"  {label}  skip (deja OK)")
                n_skip += 1
                # Veille a ce que le subject soit aussi dans index-<slug>.json
                subject = {
                    "filename": fname, "name_en": leaf_name_en, "leaf_id": leaf_id,
                    "tier": cls, "workflow_class": cls,
                    "technique": result.get("technique"), "pipeline": result.get("pipeline"),
                    "confidence": result.get("confidence"),
                    "pitfalls": result.get("pitfalls"),
                    "positive_prompt": positive, "negative_prompt": negative,
                    "resolution": [width, height],
                    "seed": prev.get("seed", seed),
                }
                append_subject_to_class_index(cls, subject)
                continue

            print(f"  {label}  {width}x{height} seed={seed}", flush=True)
            gen_res = generate_image(client, positive, negative, width, height, seed, out_path)
            if not gen_res.get("ok"):
                print(f"     X {gen_res.get('error')}")
                metrics["results"][fname] = {
                    "leaf_id": leaf_id, "leaf_name_en": leaf_name_en,
                    "workflow_class": cls,
                    "resolution": [width, height], "seed": seed,
                    "status": "comfy_error", "error": gen_res.get("error"),
                    "comfy_latency_s": gen_res.get("comfy_latency_s"),
                }
                save_atomic(METRICS_JSON, metrics)
                n_ko += 1
                continue

            hist = histogram_check(out_path)
            print(f"     OK {gen_res['comfy_latency_s']}s color_ratio={hist['color_ratio']:.4f} hist_ok={hist['histogram_ok']}")

            metrics["results"][fname] = {
                "leaf_id": leaf_id, "leaf_name_en": leaf_name_en,
                "workflow_class": cls, "technique": result.get("technique"),
                "pipeline": result.get("pipeline"), "confidence": result.get("confidence"),
                "pitfalls": result.get("pitfalls"),
                "resolution": [width, height], "seed": seed,
                "filename": fname,
                "status": "ok",
                "comfy_latency_s": gen_res["comfy_latency_s"],
                "comfy_prompt_id": gen_res.get("comfy_prompt_id"),
                "color_ratio": hist["color_ratio"],
                "ink_ratio": hist["ink_ratio"],
                "white_ratio": hist["white_ratio"],
                "histogram_ok": hist["histogram_ok"],
                "flags": hist["flags"],
            }
            save_atomic(METRICS_JSON, metrics)

            subject = {
                "filename": fname, "name_en": leaf_name_en, "leaf_id": leaf_id,
                "tier": cls, "workflow_class": cls,
                "technique": result.get("technique"), "pipeline": result.get("pipeline"),
                "confidence": result.get("confidence"),
                "pitfalls": result.get("pitfalls"),
                "positive_prompt": positive, "negative_prompt": negative,
                "resolution": [width, height], "seed": seed,
            }
            append_subject_to_class_index(cls, subject)
            n_ok += 1

    print()
    print(f"Resume : {n_ok} OK / {n_skip} SKIP / {n_ko} KO  -> {METRICS_JSON.relative_to(PROJECT_ROOT)}")
    print(f"Indexes: {OUTPUT_DIR.relative_to(PROJECT_ROOT)}/index-*.json (1 par classe)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
