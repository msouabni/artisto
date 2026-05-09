"""POC benchmark image-generation sur les 204 sujets de la taxonomie.

Lit ``data/taxonomy_subjects_with_prompts.json`` (produit par
``scripts/generate_taxonomy_prompts.py``) et genere une image par sujet en
utilisant les ``generation_params`` propres a chaque sujet (tier-specific :
1024x1024 batch=3 pour anatomy, 768x768 pour simple_*, 512x512 pour educational,
etc.) et son couple positive/negative_prompt.

Naming : {NN:03d}_{slug(name_en)}_{seed}.png ou seed = 50000 + index (deterministe).
Le prefixe NN evite les collisions de slug (ex. plusieurs sujets nommes "Cat"
dans des leaves differents). Le slug est en lowercase + non-alphanum -> '_' pour
le matching cote annotator (exact filename match via subjects-index.json).

Output :
  docs/reports/poc-taxonomy-subjects/
    {NN:03d}_{slug}_{seed}.png    (204 images)
    poc-taxonomy-subjects.json    (metriques QC indexees par filename)
    subjects-index.json           (copie de taxonomy_subjects_with_prompts.json
                                   avec filename ajoute par sujet -> permet a
                                   l'annotator d'afficher title/prompt/negative
                                   via exact match dans le schema 'subjects')

Resume : skip si le filename existe deja dans la cle 'results' du JSON metriques
avec ok=True ET le PNG est sur disque.

Usage :
    python scripts/poc_taxonomy_subjects_benchmark.py
    python scripts/poc_taxonomy_subjects_benchmark.py --only-tier anatomy
    python scripts/poc_taxonomy_subjects_benchmark.py --limit 10
"""
from __future__ import annotations

import base64
import json
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

import httpx  # noqa: E402

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    _supports_native_think_disable,
    parse_json_response,
)
from workers.comfy_client import ComfyClient, workflows_json_dir  # noqa: E402

# ───────────────── Paths ─────────────────
SUBJECTS_FILE = PROJECT_ROOT / "data" / "taxonomy_subjects_with_prompts.json"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-taxonomy-subjects"
METRICS_JSON = OUTPUT_DIR / "poc-taxonomy-subjects.json"
SUBJECTS_INDEX_JSON = OUTPUT_DIR / "subjects-index.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"
VISION_MODEL = "qwen3.5:9b"
VISION_TIMEOUT = 240
VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete", "has_text"'
)

SEED_BASE = 50_000  # seed = SEED_BASE + index (deterministe, ne collisionne pas avec 42xxx/43xxx)


# ───────────────── Helpers ─────────────────
_SLUG_KEEP = re.compile(r"[^a-z0-9_]+")


def slugify(name: str) -> str:
    s = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    s = _SLUG_KEEP.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "untitled"


def build_filename(idx: int, name_en: str, seed: int) -> str:
    return f"{idx:03d}_{slugify(name_en)}_{seed}.png"


def load_subjects() -> list[dict]:
    data = json.loads(SUBJECTS_FILE.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        subjects = data.get("subjects") or []
    elif isinstance(data, list):
        subjects = data
    else:
        raise RuntimeError(f"Format inattendu : {SUBJECTS_FILE}")
    if len(subjects) != 204:
        print(f"warning: attendu 204 sujets, trouve {len(subjects)}", file=sys.stderr)
    return subjects


# ───────────────── ComfyUI submission ─────────────────
def submit_to_comfy(
    client: ComfyClient,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    params: dict,
) -> str:
    """Soumission ComfyUI direct -- parite 1:1 avec l'UI.

    Modifie node 13 (width/height/batch_size), 14 (positive),
    15 (negative ou ' ' si vide), 16 (seed/steps/cfg/scheduler/sampler_name/denoise).
    Tous les autres champs restent ceux du JSON workflow.
    """
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    workflow = json.loads(wf_path.read_text(encoding="utf-8"))
    workflow.pop("__meta__", None)

    workflow["13"]["inputs"]["width"] = int(params.get("width", 1024))
    workflow["13"]["inputs"]["height"] = int(params.get("height", 1024))
    workflow["13"]["inputs"]["batch_size"] = int(params.get("batch_size", 1))
    workflow["14"]["inputs"]["text"] = positive_prompt
    neg_clean = (negative_prompt or "").strip()
    if neg_clean:
        workflow["15"]["inputs"]["text"] = negative_prompt
    workflow["16"]["inputs"]["seed"] = int(seed)
    workflow["16"]["inputs"]["steps"] = int(params.get("steps", 8))
    workflow["16"]["inputs"]["cfg"] = float(params.get("cfg", 1.0))
    workflow["16"]["inputs"]["scheduler"] = params.get("scheduler", "normal")
    workflow["16"]["inputs"]["sampler_name"] = params.get("sampler_name", "euler")
    workflow["16"]["inputs"]["denoise"] = float(params.get("denoise", 1.0))

    return client.submit_prompt(workflow)


def generate_image(
    client: ComfyClient,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    params: dict,
    out_path: Path,
) -> dict:
    t0 = time.time()
    try:
        prompt_id = submit_to_comfy(client, positive_prompt, negative_prompt, seed, params)
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
            "n_outputs_generated": len(images),  # info pour batch_size > 1 (1ere seule sauvegardee)
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "comfy_latency_s": round(time.time() - t0, 2)}


# ───────────────── QC ─────────────────
def histogram_check(image_path: Path) -> dict:
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    flags = qc.get("flags") or []
    return {
        "histogram_ok": not (("strong_color" in flags) or ("noticeable_color" in flags)),
        "color_ratio": float(metrics.get("color_ratio", 0.0)),
        "white_ratio": float(metrics.get("white_ratio", 0.0)),
        "ink_ratio": float(metrics.get("ink_ratio", 0.0)),
        "flags": flags,
    }


def call_vision_qc(image_path: Path) -> dict:
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload: dict = {
        "model": VISION_MODEL, "system": VISION_SYSTEM,
        "prompt": VISION_USER_PROMPT, "images": [img_b64],
        "stream": False, "options": {"temperature": 0.0},
    }
    if _supports_native_think_disable(VISION_MODEL):
        payload["think"] = False
    t0 = time.time()
    try:
        with httpx.Client(timeout=VISION_TIMEOUT) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
        dt = round(time.time() - t0, 2)
        if "error" in data and "response" not in data:
            return {"json_ok": False, "error": data["error"], "latency_s": dt}
        raw = data.get("response", "")
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            return {"json_ok": False, "raw": raw, "json_error": str(exc), "latency_s": dt}
        if not isinstance(parsed, dict):
            return {"json_ok": False, "raw": raw, "json_error": "not a dict", "latency_s": dt}
        return {
            "json_ok": True,
            "verdict": parsed.get("quality"),
            "issues": parsed.get("issues") or [],
            "confidence": parsed.get("confidence"),
            "latency_s": dt,
        }
    except Exception as exc:
        return {"json_ok": False, "error": f"{type(exc).__name__}: {exc}",
                "latency_s": round(time.time() - t0, 2)}


# ───────────────── Metrics IO ─────────────────
def load_metrics() -> dict:
    if METRICS_JSON.exists():
        try:
            return json.loads(METRICS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "poc": "taxonomy-subjects",
        "workflow_template": WORKFLOW_TEMPLATE,
        "vision_model": VISION_MODEL,
        "subjects_file": str(SUBJECTS_FILE.relative_to(PROJECT_ROOT)),
        "seed_base": SEED_BASE,
        "results": {},
    }


def save_metrics(metrics: dict) -> None:
    METRICS_JSON.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def write_subjects_index(subjects_with_filename: list[dict]) -> None:
    """Ecrit subjects-index.json (lu par l'annotator pour le mapping prompt/title/negative/tier)."""
    payload = {
        "source": str(SUBJECTS_FILE.relative_to(PROJECT_ROOT)),
        "seed_base": SEED_BASE,
        "subjects": subjects_with_filename,
    }
    SUBJECTS_INDEX_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ───────────────── Pipeline une image ─────────────────
def run_one(
    client: ComfyClient,
    metrics: dict,
    label: str,
    fname: str,
    subject: dict,
    seed: int,
) -> None:
    out_path = OUTPUT_DIR / fname
    prev = (metrics.get("results") or {}).get(fname)
    if prev and prev.get("ok") and out_path.is_file():
        print(f"  {label} skip (deja OK)", flush=True)
        return
    print(f"  {label} -> {fname}", flush=True)

    params = subject.get("generation_params") or {}
    positive = subject.get("positive_prompt") or ""
    negative = subject.get("negative_prompt") or ""

    gen = generate_image(client, positive, negative, seed, params, out_path)
    base_meta = {
        "name_en": subject.get("name_en"),
        "leaf_id": subject.get("leaf_id"),
        "leaf_name_en": subject.get("leaf_name_en"),
        "parent_name_en": subject.get("parent_name_en"),
        "tier": subject.get("tier"),
        "seed": seed,
        "params": params,
        "positive_chars": len(positive),
        "negative_chars": len(negative),
    }
    if not gen.get("ok"):
        print(f"  {label} X Comfy: {gen.get('error')} ({gen['comfy_latency_s']}s)", flush=True)
        metrics["results"][fname] = {**base_meta, **gen}
        save_metrics(metrics)
        return

    hist = histogram_check(out_path)
    vqc = call_vision_qc(out_path)
    verdict = vqc.get("verdict") if vqc.get("json_ok") else "?"
    print(
        f"  {label} OK {fname} - color_ratio={hist['color_ratio']:.3f} vision={verdict} "
        f"(gen {gen['comfy_latency_s']}s)",
        flush=True,
    )
    metrics["results"][fname] = {
        **base_meta,
        "ok": True,
        "comfy_latency_s": gen["comfy_latency_s"],
        "comfy_prompt_id": gen.get("comfy_prompt_id"),
        "n_outputs_generated": gen.get("n_outputs_generated"),
        "histogram": hist,
        "vision_qc": vqc,
    }
    save_metrics(metrics)


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC benchmark taxonomy subjects - 204 sujets x prompts par tier")
    print("=" * 100)

    if not SUBJECTS_FILE.exists():
        print(f"X Subjects file introuvable : {SUBJECTS_FILE}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    only_tier = None
    if "--only-tier" in sys.argv:
        idx = sys.argv.index("--only-tier")
        if idx + 1 < len(sys.argv):
            only_tier = sys.argv[idx + 1].strip().lower()

    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[idx + 1])
            except ValueError:
                print("X --limit doit etre un entier", file=sys.stderr)
                return 1

    subjects = load_subjects()

    # Pre-compute filename + seed pour chaque sujet (deterministique sur l'index)
    enriched: list[tuple[int, dict, str, int]] = []
    for i, s in enumerate(subjects):
        seed = SEED_BASE + i
        fname = build_filename(i + 1, s.get("name_en", ""), seed)
        enriched.append((i, s, fname, seed))

    # Filtrage --only-tier / --limit
    targets = enriched
    if only_tier:
        targets = [t for t in targets if (t[1].get("tier") or "").lower() == only_tier]
    if limit:
        targets = targets[:limit]

    # Ecrit subjects-index.json (toutes les 204 entrees, meme si run partiel,
    # pour que l'annotator ait le mapping complet en exact match).
    subjects_with_fname = []
    for i, s, fname, seed in enriched:
        copy = dict(s)
        copy["filename"] = fname
        copy["seed"] = seed
        subjects_with_fname.append(copy)
    write_subjects_index(subjects_with_fname)

    client = ComfyClient()
    if not client.is_available():
        print(f"X ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1

    n_total = len(targets)
    print(f"\nComfyUI OK     : {client.base_url}")
    print(f"Workflow       : {WORKFLOW_TEMPLATE}  ·  Vision QC : {VISION_MODEL}")
    print(f"Subjects total : {len(subjects)}  ·  a generer : {n_total}"
          + (f" (only-tier={only_tier})" if only_tier else "")
          + (f" (limit={limit})" if limit else ""))
    print(f"Seed base      : {SEED_BASE}  ·  output dir : {OUTPUT_DIR.relative_to(PROJECT_ROOT)}")

    metrics = load_metrics()
    n_done = 0
    for i, s, fname, seed in targets:
        n_done += 1
        tier = s.get("tier") or "?"
        leaf = s.get("leaf_name_en") or "?"
        name = s.get("name_en") or "?"
        label = f"[{n_done:03d}/{n_total}] [{tier:<18} · {leaf} / {name}]"
        run_one(client, metrics, label, fname, s, seed)

    print(f"\nDone -> {METRICS_JSON.relative_to(PROJECT_ROOT)}")
    print(f"     -> {SUBJECTS_INDEX_JSON.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
