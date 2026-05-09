"""POC negative prompt — enrichissement ciblé par type de sujet.

Hypothèse à tester : un negative prompt enrichi (au lieu du string vide actuel)
corrige les 3 problèmes du POC image quality (couleurs résiduelles sur fridge,
motion artifacts soccer, couleurs vivides dragon) sans toucher au prompt positif.

3 concepts × 3 variantes negative = 9 générations ComfyUI :
  - v2_no_negative      : negative = "" (reproduit le POC original avec seed contrôlé)
  - v3_baseline         : negative = BASELINE (commun à tous)
  - v4_baseline_additif : negative = BASELINE + additif spécifique au concept

La colonne "v1 original POC" du compare grid réutilise l'image existante
``docs/reports/poc-image-quality/<slug>.png`` (générée précédemment).

QC automatique : histogram (Pillow) + vision qwen3.5:9b sur chaque variante.

Réutilise ``ComfyClient`` + ``load_workflow_template`` du worker prod (cf.
``scripts/poc_image_quality.py``). Workflow ``ernie-image-turbo-q8-api``.

Usage :
    python scripts/poc_negative_prompt.py
"""
from __future__ import annotations

import base64
import io
import json
import os
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

import httpx  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    _supports_native_think_disable,
    parse_json_response,
)
from workers.comfy_client import (  # noqa: E402
    ComfyClient,
    workflows_json_dir,
)

CHAIN_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain-v2.json"
ORIGINAL_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-image-quality"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-negative-prompt"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-negative-prompt.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-negative-prompt.json"

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

# Sampler defaults : NON injectés par le script (parité 1:1 avec l'UI ComfyUI).
# Toutes les valeurs (steps, cfg, sampler_name, scheduler, denoise, width, height,
# batch_size) restent celles du JSON ernie-image-turbo-q8-api.json.

# Seed fixe par concept pour isoler l'effet du negative entre les 3 variantes.
# Le seed du POC original (image v1_original) est différent → la comparaison v1
# vs v2_no_negative montre la variance stochastique.
# 2026-05-06 : soccer aligné sur le seed UI ComfyUI (1038277875074319) pour
# permettre une comparaison pixel-perfect script ↔ UI.
SEED_PER_CONCEPT = {"soccer": 1038277875074319, "refrigerator": 42002, "dragon": 42003}


# ───────────────── Negatives ─────────────────
NEG_BASELINE = (
    "shading, gradients, color fills, shadows, gray tones, watercolor, painting, "
    "photo, realistic, 3D render, blurry, low quality, text, watermark, signature, logo"
)

NEG_ADDITIONAL = {
    # 2026-05-06 : aligné avec l'UI ComfyUI (test anatomie pure, sans préfixe
    # baseline) pour permettre la comparaison pixel-perfect script ↔ UI.
    "soccer": (
        "extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, "
        "wrong number of limbs, six fingers, deformed feet, no motion"
    ),
    "refrigerator": (
        "colorful, vivid colors, saturated colors, color fills, colored objects, "
        "ambient light, window glow, sunlight effect, warm lighting, colored lighting, "
        "golden light"
    ),
    "dragon": (
        "colorful, vivid colors, green scales, colored dragon, saturated, painted, "
        "fantasy colors, chromatic"
    ),
}


# Identification des 3 concepts cibles dans le JSON chain v2
TARGET_KEYWORDS = ["soccer", "refrigerator", "dragon"]
ORIGINAL_FILES = {
    "soccer": "sports-soccer-ball-on-a-field.png",
    "refrigerator": "electromenager-refrigerator-in-a-kitchen.png",
    "dragon": "fantasy-dragon-in-a-castle-courtyard.png",
}


def slug_from_target(target: str) -> str:
    return ORIGINAL_FILES[target].replace(".png", "")


def load_chain_concepts() -> dict[str, dict]:
    """Charge les 3 concepts cibles avec leurs prompts originaux (validator score 95)."""
    data = json.loads(CHAIN_JSON.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for r in data.get("results", []):
        name_en = (r.get("concept", {}).get("name_en") or "").lower()
        for t in TARGET_KEYWORDS:
            if t in name_en and t not in out:
                out[t] = {
                    "target": t,
                    "name_en": r["concept"].get("name_en"),
                    "category": r["concept"].get("category"),
                    "final_prompt": r.get("final_prompt") or "",
                    "validator_score": (r.get("validator") or {}).get("score"),
                }
                break
    missing = [t for t in TARGET_KEYWORDS if t not in out]
    if missing:
        raise RuntimeError(f"Concepts manquants dans chain JSON : {missing}")
    return out


# ───────────────── ComfyUI submission ─────────────────
def submit_to_comfy(client: ComfyClient, prompt_text: str, negative_text: str, seed: int) -> tuple[str, dict]:
    """Soumission ComfyUI direct — parité 1:1 avec l'UI.

    Charge le JSON brut, retire ``__meta__``, ne modifie QUE node 14 (positive),
    node 15 (negative — seulement si non vide, sinon laisse la valeur par
    défaut ``" "`` du JSON) et node 16 (seed). Tous les autres paramètres
    sampler (steps, cfg, sampler_name, scheduler, denoise, width, height,
    batch_size) restent strictement ceux du fichier JSON.
    """
    wf_path = workflows_json_dir() / f"{WORKFLOW_TEMPLATE}.json"
    workflow = json.loads(wf_path.read_text(encoding="utf-8"))
    workflow.pop("__meta__", None)

    workflow["14"]["inputs"]["text"] = prompt_text
    neg_clean = (negative_text or "").strip()
    if neg_clean:
        workflow["15"]["inputs"]["text"] = negative_text
    # else: laisse la valeur par défaut du JSON (typiquement " ")
    workflow["16"]["inputs"]["seed"] = int(seed)

    prompt_id = client.submit_prompt(workflow)
    ksampler_inputs = workflow["16"]["inputs"]
    return prompt_id, {
        "workflow_template": WORKFLOW_TEMPLATE,
        "seed": int(seed),
        "negative_applied": bool(neg_clean),
        "negative_text_used": workflow["15"]["inputs"]["text"],
        "steps": ksampler_inputs.get("steps"),
        "cfg": ksampler_inputs.get("cfg"),
        "sampler_name": ksampler_inputs.get("sampler_name"),
        "scheduler": ksampler_inputs.get("scheduler"),
        "denoise": ksampler_inputs.get("denoise"),
        "width": workflow["13"]["inputs"].get("width"),
        "height": workflow["13"]["inputs"].get("height"),
        "batch_size": workflow["13"]["inputs"].get("batch_size"),
    }


def generate_image(client: ComfyClient, prompt: str, negative: str, seed: int, out_path: Path) -> dict:
    t0 = time.time()
    try:
        prompt_id, gen_params = submit_to_comfy(client, prompt, negative, seed)
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
            "ok": True, "comfy_latency_s": round(time.time() - t0, 2),
            "comfy_prompt_id": prompt_id, "generation_params": gen_params,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "comfy_latency_s": round(time.time() - t0, 2)}


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
            "json_ok": True, "raw": raw, "parsed": parsed,
            "verdict": parsed.get("quality"),
            "issues": parsed.get("issues") or [],
            "confidence": parsed.get("confidence"),
            "latency_s": dt,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}


# ───────────────── Compare grid ─────────────────
def compose_grid(images: list[Image.Image], titles: list[str]) -> Image.Image:
    pad = 10
    title_h = 30
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    grid_w = cell_w * len(images) + pad * (len(images) + 1)
    grid_h = cell_h + title_h + pad * 2
    out = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, (im, title) in enumerate(zip(images, titles)):
        x = pad + i * (cell_w + pad)
        im_rgb = im if im.mode == "RGB" else im.convert("RGB")
        out.paste(im_rgb, (x, title_h + pad))
        if font is not None:
            draw.text((x + 4, 4), title, fill=(0, 0, 0), font=font)
    return out


# ───────────────── Per-concept pipeline ─────────────────
def process_concept(client: ComfyClient, target: str, concept: dict) -> dict:
    print(f"\n[{target}] {concept['name_en']} (validator score {concept['validator_score']})")
    prompt = concept["final_prompt"]
    seed = SEED_PER_CONCEPT[target]
    slug = slug_from_target(target)

    # Variantes
    # NB soccer : v4 envoie exactement NEG_ADDITIONAL["soccer"] (sans préfixe
    # baseline) pour matcher pixel-perfect le test UI ComfyUI (négatif anatomie
    # pure). Pour les autres concepts, v4 reste baseline + additif.
    if target == "soccer":
        v4_neg = NEG_ADDITIONAL[target]
    else:
        v4_neg = NEG_BASELINE + ", " + NEG_ADDITIONAL[target]
    variants_def = [
        ("v2_no_negative", ""),
        ("v3_baseline", NEG_BASELINE),
        ("v4_baseline_additif", v4_neg),
    ]

    rec_variants: list[dict] = []
    for code, negative in variants_def:
        out_path = OUTPUT_DIR / f"{slug}_{code}.png"
        print(f"  {code:<22} (neg chars={len(negative)})", flush=True)
        gen = generate_image(client, prompt, negative, seed, out_path)
        if not gen.get("ok"):
            print(f"    Comfy ❌ {gen.get('error')}", flush=True)
            rec_variants.append({"code": code, "negative": negative, **gen})
            continue
        print(f"    Comfy ✅ {gen['comfy_latency_s']}s", flush=True)
        hist = histogram_check(out_path)
        v = call_vision_qc(out_path)
        verdict = v.get("verdict") if v.get("json_ok") else None
        issues = v.get("issues") if v.get("json_ok") else None
        print(
            f"    hist {'OK' if hist['histogram_ok'] else 'KO'} color={hist['color_ratio']:.4f}  "
            f"vision verdict={verdict} issues={issues}",
            flush=True,
        )
        rec_variants.append({
            "code": code, "negative": negative,
            "image_path": str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "histogram": hist, "vision_qc": v, **gen,
        })

    # Compose le compare 4 colonnes
    try:
        # v1 = original POC (pré-existant)
        original_path = ORIGINAL_DIR / ORIGINAL_FILES[target]
        col_imgs: list[Image.Image] = [Image.open(original_path).convert("RGB")]
        col_titles: list[str] = ["v1 original POC"]
        for v in rec_variants:
            if v.get("ok"):
                col_imgs.append(Image.open(PROJECT_ROOT / v["image_path"]).convert("RGB"))
                col_titles.append(v["code"])
            else:
                # Placeholder rouge si génération KO
                ph = Image.new("RGB", col_imgs[0].size, (200, 100, 100))
                col_imgs.append(ph)
                col_titles.append(v["code"] + " (KO)")
        # Re-size all to the smallest dim
        target_size = col_imgs[0].size
        col_imgs = [im.resize(target_size) for im in col_imgs]
        grid = compose_grid(col_imgs, col_titles)
        grid_path = OUTPUT_DIR / f"{slug}_compare.png"
        grid.save(grid_path)
        print(f"  compare grid → {grid_path.name}")
    except Exception as exc:
        print(f"  ⚠ compare grid failed: {exc}")

    return {
        "target": target,
        "concept": concept,
        "seed": seed,
        "variants": rec_variants,
    }


# ───────────────── Main ─────────────────
def main() -> int:
    print("=" * 100)
    print("POC negative prompt — baseline vs additif spécifique")
    print("=" * 100)

    if not CHAIN_JSON.exists():
        print(f"❌ Chain JSON introuvable : {CHAIN_JSON}", file=sys.stderr)
        return 1
    concepts = load_chain_concepts()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"\nComfyUI OK : {client.base_url}")
    print(f"Workflow : {WORKFLOW_TEMPLATE} · Vision QC : {VISION_MODEL}")
    print(f"Seeds : {SEED_PER_CONCEPT}")
    print(f"Negatives :")
    print(f"  baseline = {NEG_BASELINE[:80]}…")
    for k, v in NEG_ADDITIONAL.items():
        print(f"  + {k}: {v[:80]}…")

    # Support --only <concept> pour ne traiter qu'un seul concept (debug / re-run ciblé)
    only = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        if idx + 1 < len(sys.argv):
            only = sys.argv[idx + 1].strip().lower()
            if only not in TARGET_KEYWORDS:
                print(f"❌ --only doit être dans {TARGET_KEYWORDS}, reçu '{only}'", file=sys.stderr)
                return 1

    targets_to_run = [only] if only else TARGET_KEYWORDS
    if only:
        print(f"\n→ Mode --only : exécution restreinte à '{only}'")

    all_results = []
    for target in targets_to_run:
        all_results.append(process_concept(client, target, concepts[target]))

    # ─── JSON ───
    if only:
        # Run partiel : ne pas écraser le rapport JSON validé du run complet.
        # Écrire un fichier daté + concept pour traçabilité.
        partial_json = REPORT_JSON.with_name(REPORT_JSON.stem + f"_only-{only}.json")
        payload = {
            "poc": "negative-prompt",
            "mode": f"only:{only}",
            "date": "2026-05-06",
            "workflow_template": WORKFLOW_TEMPLATE,
            "vision_model": VISION_MODEL,
            "seeds": {only: SEED_PER_CONCEPT[only]},
            "neg_baseline": NEG_BASELINE,
            "neg_additional": {only: NEG_ADDITIONAL[only]},
            "results": all_results,
        }
        partial_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nJSON partiel → {partial_json}")
        print(f"(rapport MD complet non régénéré — mode partiel)")
        return 0

    payload = {
        "poc": "negative-prompt",
        "date": "2026-05-06",
        "workflow_template": WORKFLOW_TEMPLATE,
        "vision_model": VISION_MODEL,
        "seeds": SEED_PER_CONCEPT,
        "neg_baseline": NEG_BASELINE,
        "neg_additional": NEG_ADDITIONAL,
        "results": all_results,
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # ─── MD ───
    md = []
    md.append("# POC negative prompt — enrichissement ciblé par type de sujet")
    md.append("Date : 2026-05-06")
    md.append("")
    md.append("## Contexte")
    md.append("Test de l'effet d'un **negative prompt enrichi** (au lieu du string vide actuel) sur les 3 problèmes du POC `image-quality` (couleurs résiduelles fridge / motion artifacts soccer / couleurs vivides dragon). **Prompts positifs strictement inchangés**, mêmes paramètres sampler, **seed fixe par concept** pour isoler l'effet du negative entre les 3 variantes.")
    md.append("")
    md.append("La colonne ``v1 original POC`` du compare grid réutilise les images existantes de ``docs/reports/poc-image-quality/`` (seed différent — montre la variance stochastique).")
    md.append("")
    md.append("## Negatives testés")
    md.append("")
    md.append("**Baseline (commun)** :")
    md.append("```")
    md.append(NEG_BASELINE)
    md.append("```")
    md.append("")
    md.append("**Additifs spécifiques** :")
    for t, neg in NEG_ADDITIONAL.items():
        md.append(f"")
        md.append(f"`{t}` (problème ciblé : "
                  f"{'motion artifacts → anatomie' if t == 'soccer' else ('couleurs + lighting' if t == 'refrigerator' else 'couleurs résiduelles')})")
        md.append("```")
        md.append(neg)
        md.append("```")
    md.append("")

    md.append("## Résultats par concept × variante")
    md.append("")
    md.append("Métriques :")
    md.append("- `color_ratio` : ratio pixels colorés (Pillow histogram, `build_technical_image_qc_v1`)")
    md.append("- `histogram_ok` : pas de flag `strong_color` / `noticeable_color`")
    md.append("- `vision verdict` : qwen3.5:9b QC, good / poor")
    md.append("- `issues` : liste retournée par le QC vision")
    md.append("")
    md.append("| Concept | Variante | color_ratio | hist | vision verdict | issues |")
    md.append("|---|---|---|---|---|---|")
    for r in all_results:
        target = r["target"]
        for v in r["variants"]:
            if not v.get("ok"):
                md.append(f"| {target} | {v['code']} | — | — | (gen KO) | {v.get('error', '')} |")
                continue
            hist = v.get("histogram") or {}
            visn = v.get("vision_qc") or {}
            verdict = visn.get("verdict") if visn.get("json_ok") else "?"
            issues = ", ".join(visn.get("issues") or []) or "—"
            md.append(
                f"| {target} | {v['code']} | {hist.get('color_ratio', 0):.4f} | "
                f"{'OK' if hist.get('histogram_ok') else 'KO'} | "
                f"{verdict} | {issues} |"
            )
    md.append("")

    md.append("## Outputs")
    md.append("")
    md.append("Tous les fichiers dans `docs/reports/poc-negative-prompt/` :")
    md.append("")
    md.append("```")
    for r in all_results:
        slug = slug_from_target(r["target"])
        md.append(f"  {slug}_v2_no_negative.png")
        md.append(f"  {slug}_v3_baseline.png")
        md.append(f"  {slug}_v4_baseline_additif.png")
        md.append(f"  {slug}_compare.png   ← grille 4 colonnes (v1 original | v2 no_neg | v3 baseline | v4 baseline+additif)")
    md.append("```")
    md.append("")

    md.append("## Verdict par couche")
    md.append("")
    md.append("> Évaluation à compléter par hamma après revue des `*_compare.png`.")
    md.append("")
    md.append("### Le baseline seul suffit-il ?")
    md.append("→ [à compléter après revue visuelle des 3 colonnes v3_baseline]")
    md.append("")
    md.append("### Les additifs spécifiques apportent-ils un gain mesurable ?")
    md.append("→ [à compléter après comparaison v3_baseline ↔ v4_baseline_additif sur chaque concept]")
    md.append("")
    md.append("### Effet collatéral du negative sur les zones blanches / contours ?")
    md.append("→ [à compléter — vérifier que le negative ne dégrade pas le line art réussi]")
    md.append("")

    md.append("## Si POC validé — actions de prod")
    md.append("")
    md.append("Si l'effet du baseline (et/ou des additifs) est confirmé sur ces 3 cas :")
    md.append("")
    md.append("1. **Mettre à jour `prompt_writer_ernie`** (cf. `prompts/image_prompts.yaml`) pour qu'il génère un `negative_prompt` structuré : baseline fixe + additifs sélectionnés selon les keywords du plan (subject/setting). Ne plus retourner `negative_prompt: \"\"`.")
    md.append("2. **Couche \"negative prompt enrichment\"** dans `src/services/ai_jobs_sync.py::_execute_writer_from_plan_v1_sync` : après le writer, parser le plan pour détecter les sujets sensibles (animaux→anatomie, électroménager→couleurs/lighting, créatures fantastiques→couleurs) et injecter l'additif correspondant. Logique simple : table `keyword → additif`.")
    md.append("3. **Tests** : `tests/test_negative_prompt_enrichment.py` avec 5 cas de keywords → vérifier que l'additif attendu est ajouté.")
    md.append("")

    md.append("## Points d'attention")
    md.append("")
    md.append("- **Seed fixe par concept** : v2/v3/v4 partagent le même seed → la diff visuelle est purement attribuable au negative. v1 (original POC) avait un seed aléatoire → différence stochastique normale.")
    md.append("- **Sampling 8 steps cfg=1.0** (Ernie defaults) : configuration prod, identique au POC image-quality.")
    md.append("- **Vision QC qwen3.5:9b** : 5/6 sur le POC vision-batch — taux d'erreur ~17 % sur \"has_color\". Considérer Pillow histogram comme arbitre primaire et vision comme contrôle secondaire.")
    md.append("- **Latence par génération** : ~10-20s ComfyUI + ~10s vision QC = ~30s par variante × 9 = ~5 min total pour ce POC.")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes : `2026-05-05_poc-negative-prompt.json`")
    md.append("- Script : `scripts/poc_negative_prompt.py`")
    md.append("- Prompts source : `docs/reports/2026-05-05_poc-prompt-chain-v2.json`")
    md.append("- Images originales POC : `docs/reports/poc-image-quality/`")
    md.append("- POC image-quality : `docs/reports/2026-05-05_poc-image-quality.md`")

    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
