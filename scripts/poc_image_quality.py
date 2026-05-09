"""POC image quality — bouclage prompt → ComfyUI → QC vision.

Chaînon manquant entre le score validator (syntaxique) du POC-3 v2 et la
qualité visuelle réelle des images générées :

1. Sélectionne 8 concepts à score ≥ 95 dans
   ``docs/reports/2026-05-05_poc-prompt-chain-v2.json``, en couvrant 8 catégories
   distinctes (animaux, outils, sports, fantasy, professions, électroménager,
   géométrie, personnages fictifs).
2. Soumet chaque prompt à ComfyUI (workflow ``ernie-image-turbo-q8-api``,
   réutilise exactement ``ComfyClient`` + ``load_workflow_template`` du worker
   prod) et télécharge l'image finale dans
   ``docs/reports/poc-image-quality/<concept_slug>.png``.
3. Pré-check histogram via ``build_technical_image_qc_v1`` (Pillow + NumPy,
   < 10 ms/image — flags ``strong_color``, ``low_white_background``…).
4. QC vision avec ``qwen3.5:9b`` via Ollama, exactement le prompt validé
   en ``poc_qwen35_vision.py`` (verdict good/poor + issues + confidence).

Critères de succès :
- ≥ 6/8 images verdict ``good`` du QC vision
- 0 image avec texte visible
- ≤ 2 images avec couleurs parasites (histogram KO)

Usage :
    python scripts/poc_image_quality.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
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

import httpx  # noqa: E402

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    _supports_native_think_disable,
    parse_json_response,
)
from workers.comfy_client import (  # noqa: E402
    ComfyClient,
    apply_overrides,
    load_workflow_template,
    sanitize_public_workflow_inputs,
    workflows_json_dir,
)

V2_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain-v2.json"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-image-quality"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-image-quality.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-image-quality.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"
PROFILE = "kids_coloring_lineart_v1"

# Vision QC — repris à l'identique de poc_qwen35_vision.py (validé)
VISION_MODEL = "qwen3.5:9b"
VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete", "has_text"'
)
VISION_TIMEOUT = 240

# Sampler defaults (alignés sur ImageWorker._ERNIE_SAMPLER_DEFAULTS)
ERNIE_SAMPLER_DEFAULTS: dict = {
    "steps": 8,
    "cfg": 1.0,
    "width": 1024,
    "height": 1024,
    "batch_size": 1,
    "sampler_name": "euler",
    "scheduler": "normal",
    "denoise": 1.0,
}

# Critères POC
TARGET_GOOD = 6  # sur 8
MAX_HIST_KO = 2

# Sélection : 1 concept par catégorie pour couvrir 8 catégories distinctes.
SELECTED_CATEGORIES: list[str] = [
    "animaux",
    "outils",
    "sports",
    "personnages_fictifs",
    "electromenager",
    "geometrie",
    "professions",
    "fantasy",
]


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:60] or "concept"


def select_concepts(v2_data: dict) -> list[dict]:
    """Pioche 1 concept score ≥ 95 par catégorie ciblée. Si plusieurs candidats,
    prend le premier (ordre d'origine) pour avoir un sample reproductible."""
    by_cat: dict[str, list[dict]] = {}
    for r in v2_data.get("results", []):
        if r.get("errors"):
            continue
        v = r.get("validator") or {}
        if not isinstance(v, dict):
            continue
        if (v.get("score") or 0) < 95:
            continue
        cat = r["concept"].get("category", "?")
        by_cat.setdefault(cat, []).append(r)

    picked: list[dict] = []
    missing: list[str] = []
    for cat in SELECTED_CATEGORIES:
        items = by_cat.get(cat) or []
        if not items:
            missing.append(cat)
            continue
        picked.append(items[0])
    if missing:
        print(f"⚠ Catégories sans candidat ≥ 95 : {missing}")
    return picked


def submit_to_comfy(client: ComfyClient, prompt_text: str, negative_text: str) -> tuple[str, dict]:
    """Soumission ComfyUI ; retourne (prompt_id, generation_params)."""
    workflows_dir = workflows_json_dir()
    wf_base, public_inputs_map, contract = load_workflow_template(workflows_dir, WORKFLOW_TEMPLATE)
    candidate: dict = {
        "positive_prompt": prompt_text,
        "negative_prompt": negative_text or "",
        "seed": int.from_bytes(os.urandom(4), "big"),
    }
    for k, v in ERNIE_SAMPLER_DEFAULTS.items():
        candidate[k] = v
    overrides = sanitize_public_workflow_inputs(candidate, contract)
    workflow = apply_overrides(wf_base, public_inputs_map, overrides)
    prompt_id = client.submit_prompt(workflow)
    gen_params = {
        "workflow_template": WORKFLOW_TEMPLATE,
        "contract_version": contract.get("contract_version"),
        **{k: overrides.get(k, candidate.get(k)) for k in ERNIE_SAMPLER_DEFAULTS.keys()},
        "seed": overrides.get("seed", candidate["seed"]),
    }
    return prompt_id, gen_params


def call_vision_qc(image_path: Path) -> dict:
    """qwen3.5:9b vision QC (mêmes paramètres que poc_qwen35_vision.py)."""
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload: dict = {
        "model": VISION_MODEL,
        "system": VISION_SYSTEM,
        "prompt": VISION_USER_PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.0},
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
            "json_ok": True,
            "raw": raw,
            "parsed": parsed,
            "verdict": parsed.get("quality"),
            "issues": parsed.get("issues") or [],
            "confidence": parsed.get("confidence"),
            "latency_s": dt,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}


def histogram_check(image_path: Path) -> dict:
    """Pré-check Pillow ; flag les couleurs parasites avant le QC vision."""
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    flags = qc.get("flags") or []
    color_ratio = float(metrics.get("color_ratio", 0.0))
    white_ratio = float(metrics.get("white_ratio", 0.0))
    ink_ratio = float(metrics.get("ink_ratio", 0.0))
    has_color_issue = ("strong_color" in flags) or ("noticeable_color" in flags)
    return {
        "histogram_ok": not has_color_issue,
        "color_ratio": color_ratio,
        "white_ratio": white_ratio,
        "ink_ratio": ink_ratio,
        "flags": flags,
        "status": qc.get("status"),
    }


def main() -> int:
    print("=" * 100, flush=True)
    print("POC image quality — prompts POC-3 v2 → ComfyUI → QC vision qwen3.5:9b", flush=True)
    print("=" * 100, flush=True)

    if not V2_JSON.exists():
        print(f"❌ JSON v2 introuvable : {V2_JSON}", file=sys.stderr)
        return 1
    v2_data = json.loads(V2_JSON.read_text(encoding="utf-8"))
    selected = select_concepts(v2_data)
    print(f"\nConcepts sélectionnés : {len(selected)}", flush=True)
    for r in selected:
        print(f"  · [{r['concept']['category']:<25}] {r['concept']['name_en']} (score {r['validator']['score']})", flush=True)

    if not selected:
        print("❌ Aucun concept sélectionné", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"\nComfyUI OK : {client.base_url}", flush=True)
    print(f"Workflow : {WORKFLOW_TEMPLATE} · Vision QC : {VISION_MODEL}", flush=True)
    print(flush=True)

    results: list[dict] = []
    for i, r in enumerate(selected, 1):
        c = r["concept"]
        prompt_text = (r.get("final_prompt") or "").strip()
        neg = (r.get("negative_prompt") or "").strip()
        slug = f"{c['category']}-{slugify(c['name_en'])}"
        out_path = OUTPUT_DIR / f"{slug}.png"
        print(f"[{i}/{len(selected)}] {c['category']:<25} {c['name_en']}", flush=True)
        if not prompt_text:
            print("        ❌ prompt vide", flush=True)
            results.append({
                "concept": c, "prompt_score_validator": r["validator"]["score"],
                "error": "empty prompt",
            })
            continue

        # ── ComfyUI ──
        rec: dict = {
            "concept": c,
            "prompt": prompt_text,
            "negative_prompt": neg,
            "prompt_score_validator": r["validator"]["score"],
            "image_path": str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }
        try:
            t0 = time.time()
            prompt_id, gen_params = submit_to_comfy(client, prompt_text, neg)
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
            comfy_dt = time.time() - t0
            rec["comfy_latency_s"] = round(comfy_dt, 2)
            rec["comfy_prompt_id"] = prompt_id
            rec["generation_params"] = gen_params
            print(f"        Comfy ✅ {comfy_dt:.1f}s → {out_path.name}", flush=True)
        except Exception as exc:
            rec["error_comfy"] = f"{type(exc).__name__}: {exc}"
            print(f"        Comfy ❌ {rec['error_comfy']}", flush=True)
            results.append(rec)
            continue

        # ── Histogram pre-check ──
        try:
            hist = histogram_check(out_path)
            rec["histogram"] = hist
            tag = "OK" if hist["histogram_ok"] else "KO"
            print(
                f"        hist {tag} color={hist['color_ratio']:.4f} white={hist['white_ratio']:.4f} "
                f"ink={hist['ink_ratio']:.4f} flags={hist['flags']}",
                flush=True,
            )
        except Exception as exc:
            rec["error_histogram"] = f"{type(exc).__name__}: {exc}"
            print(f"        hist ❌ {rec['error_histogram']}", flush=True)

        # ── Vision QC ──
        try:
            v = call_vision_qc(out_path)
            rec["vision_qc"] = v
            if v.get("error"):
                print(f"        vision ❌ {v['error']} ({v.get('latency_s', 0):.1f}s)", flush=True)
            elif not v.get("json_ok"):
                print(f"        vision ⚠ JSON parse fail ({v.get('latency_s', 0):.1f}s)", flush=True)
            else:
                print(
                    f"        vision verdict={v.get('verdict')} "
                    f"issues={v.get('issues')} conf={v.get('confidence')} "
                    f"({v.get('latency_s', 0):.1f}s)",
                    flush=True,
                )
        except Exception as exc:
            rec["error_vision"] = f"{type(exc).__name__}: {exc}"
            print(f"        vision ❌ {rec['error_vision']}", flush=True)

        results.append(rec)

    # ── Agrégats ──
    n = len(results)
    n_image_ok = sum(1 for r in results if "error_comfy" not in r and "error" not in r and r.get("image_path"))
    n_good = sum(
        1 for r in results
        if isinstance(r.get("vision_qc"), dict) and r["vision_qc"].get("verdict") == "good"
    )
    n_poor = sum(
        1 for r in results
        if isinstance(r.get("vision_qc"), dict) and r["vision_qc"].get("verdict") == "poor"
    )
    has_text_count = sum(
        1 for r in results
        if isinstance(r.get("vision_qc"), dict)
        and "has_text" in (r["vision_qc"].get("issues") or [])
    )
    has_color_count = sum(
        1 for r in results
        if isinstance(r.get("vision_qc"), dict)
        and "has_color" in (r["vision_qc"].get("issues") or [])
    )
    n_hist_ko = sum(1 for r in results if isinstance(r.get("histogram"), dict) and not r["histogram"].get("histogram_ok"))
    comfy_lats = [r["comfy_latency_s"] for r in results if "comfy_latency_s" in r]
    vision_lats = [
        r["vision_qc"]["latency_s"] for r in results
        if isinstance(r.get("vision_qc"), dict) and r["vision_qc"].get("latency_s")
    ]

    print(flush=True)
    print("─── Agrégats ───────────────────────────────────────────────────────────────────", flush=True)
    print(f"Images générées   : {n_image_ok}/{n}", flush=True)
    print(f"Vision verdict good: {n_good}/{n}  [cible ≥ {TARGET_GOOD}]", flush=True)
    print(f"Vision verdict poor: {n_poor}/{n}", flush=True)
    print(f"has_text détecté  : {has_text_count}/{n}  [cible 0]", flush=True)
    print(f"has_color détecté : {has_color_count}/{n}", flush=True)
    print(f"Histogram KO      : {n_hist_ko}/{n}  [cible ≤ {MAX_HIST_KO}]", flush=True)
    if comfy_lats:
        print(f"Comfy latency     : min={min(comfy_lats):.1f}s mean={sum(comfy_lats)/len(comfy_lats):.1f}s max={max(comfy_lats):.1f}s", flush=True)
    if vision_lats:
        print(f"Vision latency    : min={min(vision_lats):.1f}s mean={sum(vision_lats)/len(vision_lats):.1f}s max={max(vision_lats):.1f}s", flush=True)

    aggregates = {
        "n_concepts": n,
        "n_image_generated": n_image_ok,
        "n_vision_good": n_good,
        "n_vision_poor": n_poor,
        "n_has_text": has_text_count,
        "n_has_color": has_color_count,
        "n_histogram_ko": n_hist_ko,
        "target_good": TARGET_GOOD,
        "target_max_hist_ko": MAX_HIST_KO,
        "comfy_latency_min_s": min(comfy_lats) if comfy_lats else None,
        "comfy_latency_max_s": max(comfy_lats) if comfy_lats else None,
        "comfy_latency_mean_s": (sum(comfy_lats) / len(comfy_lats)) if comfy_lats else None,
        "vision_latency_min_s": min(vision_lats) if vision_lats else None,
        "vision_latency_max_s": max(vision_lats) if vision_lats else None,
        "vision_latency_mean_s": (sum(vision_lats) / len(vision_lats)) if vision_lats else None,
    }

    payload = {
        "poc": "image-quality",
        "date": "2026-05-05",
        "workflow_template": WORKFLOW_TEMPLATE,
        "vision_model": VISION_MODEL,
        "comfy_url": client.base_url,
        "ollama_base_url": OLLAMA_BASE_URL,
        "selection": SELECTED_CATEGORIES,
        "results": results,
        "aggregates": aggregates,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nJSON brut → {REPORT_JSON}", flush=True)

    # ── Markdown ──
    success_good = n_good >= TARGET_GOOD
    success_text = has_text_count == 0
    success_hist = n_hist_ko <= MAX_HIST_KO
    overall_ok = success_good and success_text and success_hist

    md: list[str] = []
    md.append("# POC image quality — bouclage prompt → ComfyUI → QC vision")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append(
        f"Premier bouclage de la chaîne complète : on prend les **prompts produits par POC-3 v2** "
        f"(`{V2_JSON.name}`, score validator ≥ 95), on les génère réellement via **ComfyUI** "
        f"(workflow `{WORKFLOW_TEMPLATE}`), puis on évalue chaque image avec **{VISION_MODEL}** "
        "(le QC vision validé en `2026-05-05_poc-qwen35-vision.md`). C'est le chaînon manquant "
        "entre le score validator (syntaxique) et la qualité visuelle réelle."
    )
    md.append("")
    md.append("**Sélection** : 1 concept par catégorie sur les 8 catégories de POC-3 v2 (score ≥ 95).")
    md.append("")
    md.append("## Critères de succès")
    md.append(f"- ≥ **{TARGET_GOOD}/{len(SELECTED_CATEGORIES)}** images verdict ``good`` du QC vision")
    md.append("- **0** image avec `has_text` détecté")
    md.append(f"- ≤ **{MAX_HIST_KO}** images avec histogram KO (couleurs parasites)")
    md.append("")

    md.append("## Résultats par concept")
    md.append("")
    md.append("| # | Catégorie | Concept | Validator | Comfy s | Hist | Vision verdict | Issues | Conf | Image |")
    md.append("|---|---|---|---:|---:|:---:|:---:|---|---:|---|")
    for i, r in enumerate(results, 1):
        c = r["concept"]
        v = r.get("vision_qc") or {}
        h = r.get("histogram") or {}
        if r.get("error_comfy") or r.get("error"):
            md.append(
                f"| {i} | {c.get('category', '?')} | {c.get('name_en', '?')} | {r.get('prompt_score_validator', '—')} "
                f"| — | — | — | comfy: {r.get('error_comfy') or r.get('error')} | — | — |"
            )
            continue
        verdict = v.get("verdict") or "—"
        issues = ", ".join(v.get("issues") or []) or "—"
        conf = v.get("confidence") if v.get("confidence") is not None else "—"
        hist_tag = "✅" if h.get("histogram_ok") else "❌"
        comfy_s = f"{r.get('comfy_latency_s', 0):.1f}" if r.get("comfy_latency_s") else "—"
        md.append(
            f"| {i} | {c['category']} | {c['name_en']} | {r['prompt_score_validator']} "
            f"| {comfy_s} | {hist_tag} | **{verdict}** | {issues} | {conf} | "
            f"`{r.get('image_path', '—')}` |"
        )
    md.append("")

    md.append("## Agrégats")
    md.append("")
    md.append(f"- Images générées : **{n_image_ok}/{n}**")
    md.append(
        f"- Verdict ``good`` : **{n_good}/{n}** "
        f"({'✅' if success_good else '❌'} cible ≥ {TARGET_GOOD})"
    )
    md.append(f"- Verdict ``poor`` : **{n_poor}/{n}**")
    md.append(
        f"- ``has_text`` détecté : **{has_text_count}/{n}** "
        f"({'✅' if success_text else '❌'} cible 0)"
    )
    md.append(f"- ``has_color`` détecté : **{has_color_count}/{n}**")
    md.append(
        f"- Histogram KO : **{n_hist_ko}/{n}** "
        f"({'✅' if success_hist else '❌'} cible ≤ {MAX_HIST_KO})"
    )
    if comfy_lats:
        md.append(
            f"- Comfy latency : min={min(comfy_lats):.1f}s · "
            f"mean={sum(comfy_lats)/len(comfy_lats):.1f}s · max={max(comfy_lats):.1f}s"
        )
    if vision_lats:
        md.append(
            f"- Vision latency : min={min(vision_lats):.1f}s · "
            f"mean={sum(vision_lats)/len(vision_lats):.1f}s · max={max(vision_lats):.1f}s"
        )
    md.append("")

    # ── Détails par image (issues + recommandations) ──
    md.append("## Détail par image")
    md.append("")
    for r in results:
        if r.get("error_comfy") or r.get("error"):
            continue
        c = r["concept"]
        h = r.get("histogram") or {}
        v = r.get("vision_qc") or {}
        md.append(f"### [{c['category']}] {c['name_en']}")
        md.append(f"- Prompt validator score : {r['prompt_score_validator']}")
        md.append(f"- Comfy : {r.get('comfy_latency_s', '—')}s · seed={r.get('generation_params', {}).get('seed', '—')}")
        md.append(
            f"- Histogram : color_ratio={h.get('color_ratio', '—')} · "
            f"white_ratio={h.get('white_ratio', '—')} · ink_ratio={h.get('ink_ratio', '—')} · "
            f"flags={h.get('flags', [])}"
        )
        if v.get("json_ok"):
            md.append(
                f"- Vision : verdict=**{v.get('verdict')}** · issues={v.get('issues')} · "
                f"confidence={v.get('confidence')} · latency={v.get('latency_s', 0):.1f}s"
            )
        elif v.get("error"):
            md.append(f"- Vision : ❌ {v.get('error')}")
        else:
            md.append(f"- Vision : ⚠ JSON parse fail")
        md.append(f"- Image : `{r.get('image_path')}`")
        md.append("")

    md.append("## Verdict")
    md.append("")
    if overall_ok:
        md.append("✅ **Boucle prompt→image→QC validée.** Les 3 critères sont remplis : "
                  f"{n_good}/{n} images jugées ``good`` par le QC vision (cible ≥ {TARGET_GOOD}), "
                  f"{has_text_count} image avec texte (cible 0), "
                  f"{n_hist_ko} histogram KO (cible ≤ {MAX_HIST_KO}). "
                  "Les prompts du POC-3 v2 produisent effectivement des images de coloriage line art exploitables.")
    else:
        not_met: list[str] = []
        if not success_good:
            not_met.append(f"good seulement {n_good}/{n} (cible ≥ {TARGET_GOOD})")
        if not success_text:
            not_met.append(f"has_text détecté {has_text_count}× (cible 0)")
        if not success_hist:
            not_met.append(f"{n_hist_ko} histogram KO (cible ≤ {MAX_HIST_KO})")
        md.append("⚠ **Critères partiellement remplis : " + " ; ".join(not_met) + ".**")
        md.append("")
        md.append("Examiner le détail par image ci-dessus et la galerie `docs/reports/poc-image-quality/` "
                  "pour identifier les patterns d'échec visuels.")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Galerie images : `docs/reports/poc-image-quality/` (1 PNG par concept, naming `<categorie>-<slug>.png`)")
    md.append(f"- Données brutes : `2026-05-05_poc-image-quality.json`")
    md.append(f"- Source prompts : `2026-05-05_poc-prompt-chain-v2.json` (POC-3 v2)")
    md.append(f"- Script : `scripts/poc_image_quality.py`")
    md.append(f"- Workflow ComfyUI : `data/workflows/{WORKFLOW_TEMPLATE}.json` + `.overrides.json`")
    md.append(f"- QC vision : `{VISION_MODEL}` (mêmes paramètres que `scripts/poc_qwen35_vision.py`)")
    md.append(f"- QC technique : `src/services/image_qc_technical.py::build_technical_image_qc_v1`")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
