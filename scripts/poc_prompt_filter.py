"""POC prompt filter — validation empirique des règles de réécriture.

Objectif : vérifier que des règles de sanitisation appliquées AVANT ComfyUI
améliorent la qualité visuelle sur les 3 concepts problématiques du POC
image quality (mono direct). Pas d'intégration dans le pipeline — juste un
script autonome qui :

1. Lit les prompts originaux dans 2026-05-05_poc-prompt-chain-v2.json
2. Applique 4 règles de réécriture inline (anatomy / lighting / color nouns /
   colorful adjectives) en loggant chaque match
3. Affiche / sauvegarde le diff prompt avant ↔ après
4. Génère l'image filtrée via ComfyUI (workflow ernie-image-turbo-q8-api)
5. QC : Pillow histogram + qwen3.5:9b vision QC
6. Comparaison côte-à-côte 3 colonnes (original | filtered | diff_prompt PNG)

Usage :
    python scripts/poc_prompt_filter.py
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
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

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
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-prompt-filter"
ORIG_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-image-quality"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-filter.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-filter.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

VISION_MODEL = "qwen3.5:9b"
VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER_PROMPT = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete", "has_text"'
)
VISION_TIMEOUT = 240

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

# Concepts cibles (3 problématiques du POC image quality)
TARGETS: list[dict] = [
    {
        "name_en": "Soccer Ball on a Field",
        "category": "sports",
        "slug": "sports-soccer-ball-on-a-field",
        "issue": "anatomie (3 jambes en mode action kicking)",
        "original_image": "sports-soccer-ball-on-a-field.png",
    },
    {
        "name_en": "Refrigerator in a Kitchen",
        "category": "electromenager",
        "slug": "electromenager-refrigerator-in-a-kitchen",
        "issue": "couleurs résiduelles + lighting (sunlight + colorful + couleurs nommées)",
        "original_image": "electromenager-refrigerator-in-a-kitchen.png",
    },
    {
        "name_en": "Dragon in a Castle Courtyard",
        "category": "fantasy",
        "slug": "fantasy-dragon-in-a-castle-courtyard",
        "issue": "couleurs résiduelles (green dragon, red banners)",
        "original_image": "fantasy-dragon-in-a-castle-courtyard.png",
    },
]

# ─── Règles de réécriture ───────────────────────────────────────────────────

RULES: list[dict] = [
    {
        "id": "anatomy_static_pose",
        "type": "trigger_append",
        # Si l'un de ces patterns est détecté → append une consigne anatomie static.
        "patterns": [
            "kicking", "running", "jumping", "throwing", "diving",
            "mid-air", "sprinting", "leaping", "flying through",
        ],
        "append": (
            " Note: simple static pose, character standing or sitting calmly, "
            "no motion blur, no action lines, anatomically correct with exactly "
            "two legs and two arms visible."
        ),
    },
    {
        "id": "no_light_sources",
        "type": "phrase_replace",
        "replacements": {
            # Phrases longues d'abord pour éviter qu'une plus courte mange la plus longue
            "with a window letting in warm sunlight": "with a window",
            "with a window letting in sunlight": "with a window",
            "letting in warm sunlight": "",
            "letting in sunlight": "",
            "warm sunlight": "",
            "golden light": "",
            "ambient light": "",
            "warm light": "",
            "window light": "window",
            "candlelight": "",
            "glowing": "",
            "sunlight": "",
        },
    },
    {
        "id": "strip_color_nouns",
        "type": "regex_replace",
        "pattern": r"\b(red|blue|green|yellow|orange|purple|pink|brown|golden|grey|gray|white|black)\s+(\w+)",
        "replacement": r"\2",  # garder le nom, virer la couleur
        # Exception : si le mot suivant est "background", "outlines", "outline" ou "line" on garde
        # (ex. "white background", "black outlines" sont des consignes line-art)
        "skip_if_next_in": {"background", "outlines", "outline", "line", "lines", "art"},
    },
    {
        "id": "no_colorful_adjectives",
        "type": "phrase_replace",
        "replacements": {
            "multicolored": "varied",
            "colorful": "cheerful",
            "vibrant": "lively",
            "bright": "inviting",
            "vivid": "clear",
        },
    },
]


def apply_rules(prompt: str) -> tuple[str, list[dict]]:
    """Applique les 4 règles séquentiellement et retourne (prompt_filtré, log).

    Le log est une liste d'événements ``{rule_id, before, after, action}`` dans
    l'ordre d'application. Une règle peut produire 0 à N événements selon le
    nombre de matches.
    """
    log: list[dict] = []
    p = prompt

    for rule in RULES:
        rid = rule["id"]
        rtype = rule["type"]

        if rtype == "trigger_append":
            triggered_by = next((pat for pat in rule["patterns"] if pat.lower() in p.lower()), None)
            if triggered_by:
                before_len = len(p)
                p = p.rstrip() + rule["append"]
                log.append({
                    "rule_id": rid,
                    "action": "append",
                    "triggered_by": triggered_by,
                    "before_len": before_len,
                    "after_len": len(p),
                })

        elif rtype == "phrase_replace":
            for needle, replacement in rule["replacements"].items():
                # Case-insensitive search via re
                pattern = re.compile(re.escape(needle), flags=re.IGNORECASE)
                matches = list(pattern.finditer(p))
                if matches:
                    new_p = pattern.sub(replacement, p)
                    log.append({
                        "rule_id": rid,
                        "action": "replace",
                        "needle": needle,
                        "replacement": replacement,
                        "n_matches": len(matches),
                    })
                    p = new_p

        elif rtype == "regex_replace":
            pattern = re.compile(rule["pattern"], flags=re.IGNORECASE)
            skip_set = {w.lower() for w in (rule.get("skip_if_next_in") or set())}
            matches: list[re.Match] = []

            def _replace_with_skip(m: re.Match) -> str:
                # Si le 2e groupe est dans skip_set, on garde tel quel
                noun = m.group(2).lower()
                if noun in skip_set:
                    return m.group(0)
                matches.append(m)
                # Substituer via expand
                return m.expand(rule["replacement"])

            new_p = pattern.sub(_replace_with_skip, p)
            if matches:
                log.append({
                    "rule_id": rid,
                    "action": "regex",
                    "pattern": rule["pattern"],
                    "n_matches": len(matches),
                    "examples": [m.group(0) for m in matches[:6]],
                })
                p = new_p

    # Nettoyer les espaces multiples / virgules orphelines créées par les replacements vides
    p = re.sub(r"\s+,", ",", p)
    p = re.sub(r"\s{2,}", " ", p)
    p = re.sub(r",\s*,", ",", p)
    return p.strip(), log


# ─── ComfyUI submit ─────────────────────────────────────────────────────────

def submit_to_comfy(client: ComfyClient, prompt_text: str, negative_text: str) -> tuple[str, dict]:
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
    gen_params = {k: overrides.get(k, candidate.get(k)) for k in ERNIE_SAMPLER_DEFAULTS.keys()}
    gen_params["seed"] = overrides.get("seed", candidate["seed"])
    return prompt_id, gen_params


# ─── Vision QC ──────────────────────────────────────────────────────────────

def call_vision_qc(image_path: Path) -> dict:
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
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    return {
        "color_ratio": float(metrics.get("color_ratio", 0.0)),
        "white_ratio": float(metrics.get("white_ratio", 0.0)),
        "ink_ratio": float(metrics.get("ink_ratio", 0.0)),
        "flags": qc.get("flags") or [],
    }


# ─── Diff prompt rendu en image (Pillow) ────────────────────────────────────

def render_prompt_diff_image(
    *,
    title: str,
    original: str,
    filtered: str,
    rules_log: list[dict],
    out_path: Path,
    width: int = 512,
    height: int = 512,
) -> Path:
    """Rend un PNG 512×512 avec original / filtered / règles déclenchées en texte."""
    img = Image.new("RGB", (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    try:
        font_h = ImageFont.truetype("arial.ttf", 12)
        font_t = ImageFont.truetype("arialbd.ttf", 13)
    except Exception:
        font_h = ImageFont.load_default()
        font_t = ImageFont.load_default()

    def wrap(text: str, max_chars: int) -> list[str]:
        words = text.split()
        out: list[str] = []
        line = ""
        for w in words:
            if len(line) + 1 + len(w) <= max_chars:
                line = (line + " " + w).strip()
            else:
                if line:
                    out.append(line)
                line = w
        if line:
            out.append(line)
        return out

    y = 6
    draw.text((6, y), title, fill=(0, 0, 0), font=font_t); y += 18

    draw.text((6, y), "ORIGINAL:", fill=(120, 0, 0), font=font_t); y += 16
    for ln in wrap(original, 70)[:8]:
        draw.text((6, y), ln, fill=(40, 40, 40), font=font_h); y += 14
    y += 6

    draw.text((6, y), "FILTERED:", fill=(0, 100, 0), font=font_t); y += 16
    for ln in wrap(filtered, 70)[:8]:
        draw.text((6, y), ln, fill=(40, 40, 40), font=font_h); y += 14
    y += 6

    draw.text((6, y), "RULES TRIGGERED:", fill=(0, 0, 120), font=font_t); y += 16
    if not rules_log:
        draw.text((6, y), "(none)", fill=(80, 80, 80), font=font_h); y += 14
    else:
        for ev in rules_log[:8]:
            line = f"- {ev['rule_id']} : {ev.get('action', '')}"
            if "needle" in ev:
                line += f" '{ev['needle']}' → '{ev['replacement']}' ×{ev['n_matches']}"
            elif "examples" in ev:
                line += f" ×{ev['n_matches']} (e.g. {', '.join(ev['examples'][:3])})"
            elif "triggered_by" in ev:
                line += f" trig='{ev['triggered_by']}'"
            for ln in wrap(line, 70)[:2]:
                draw.text((6, y), ln, fill=(30, 30, 30), font=font_h); y += 14
    img.save(out_path, "PNG")
    return out_path


def build_compare(*, original: Path, filtered: Path, diff_prompt: Path, out_path: Path, cell: int = 512) -> Path:
    canvas = Image.new("RGB", (cell * 3, cell), (255, 255, 255))
    for i, p in enumerate([original, filtered, diff_prompt]):
        if p.is_file():
            im = Image.open(p).convert("RGB").resize((cell, cell), Image.LANCZOS)
        else:
            im = Image.new("RGB", (cell, cell), (240, 240, 240))
        canvas.paste(im, (i * cell, 0))
    canvas.save(out_path, "PNG")
    return out_path


# ─── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 100, flush=True)
    print("POC prompt filter — règles de réécriture sur 3 concepts problématiques", flush=True)
    print("=" * 100, flush=True)

    if not V2_JSON.exists():
        print(f"❌ JSON v2 introuvable : {V2_JSON}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    v2_data = json.loads(V2_JSON.read_text(encoding="utf-8"))
    by_name = {r["concept"]["name_en"]: r for r in v2_data.get("results", []) if isinstance(r, dict)}

    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"\nComfyUI OK : {client.base_url}", flush=True)
    print(f"Workflow : {WORKFLOW_TEMPLATE} · Vision QC : {VISION_MODEL}", flush=True)
    print(flush=True)

    results: list[dict] = []
    for i, t in enumerate(TARGETS, 1):
        print(f"[{i}/{len(TARGETS)}] {t['category']:<20} {t['name_en']}", flush=True)
        v2 = by_name.get(t["name_en"])
        if not v2:
            print(f"        ❌ concept introuvable dans v2 JSON", flush=True)
            results.append({"concept": t, "error": "not in v2 JSON"})
            continue
        original_prompt = (v2.get("final_prompt") or "").strip()
        if not original_prompt:
            print(f"        ❌ prompt original vide", flush=True)
            results.append({"concept": t, "error": "empty original prompt"})
            continue

        # Étape 2 : appliquer les règles
        filtered_prompt, log = apply_rules(original_prompt)
        print(f"        Règles déclenchées : {len(log)}", flush=True)
        for ev in log:
            extras = []
            if "needle" in ev:
                extras.append(f"'{ev['needle']}' → '{ev['replacement']}' ×{ev['n_matches']}")
            elif "triggered_by" in ev:
                extras.append(f"trig={ev['triggered_by']!r}")
            elif "examples" in ev:
                extras.append(f"×{ev['n_matches']} ({', '.join(ev['examples'][:3])})")
            print(f"          · {ev['rule_id']} {ev.get('action', '')} {' '.join(extras)}", flush=True)

        # Étape 3 : sauvegarder le diff txt
        diff_txt_path = OUTPUT_DIR / f"{t['slug']}_prompt_diff.txt"
        diff_txt_path.write_text(
            f"# {t['name_en']}\n# Issue: {t['issue']}\n\n"
            f"## ORIGINAL PROMPT\n{original_prompt}\n\n"
            f"## FILTERED PROMPT\n{filtered_prompt}\n\n"
            f"## RULES TRIGGERED ({len(log)})\n"
            + "\n".join(f"- {json.dumps(ev, ensure_ascii=False)}" for ev in log)
            + "\n",
            encoding="utf-8",
        )

        # Étape 4 : génération filtrée via ComfyUI
        filtered_image_path = OUTPUT_DIR / f"{t['slug']}_filtered.png"
        rec: dict = {
            "concept": t,
            "original_prompt": original_prompt,
            "filtered_prompt": filtered_prompt,
            "rules_log": log,
            "n_rules_triggered": len(log),
            "original_image": str((ORIG_DIR / t["original_image"]).relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "filtered_image": str(filtered_image_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "prompt_diff_txt": str(diff_txt_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }
        try:
            t0 = time.time()
            prompt_id, gen_params = submit_to_comfy(client, filtered_prompt, "")
            history = client.poll_until_done(prompt_id)
            images = client.extract_output_images(history)
            if not images:
                raise RuntimeError("Aucune image dans l'historique ComfyUI")
            first = images[0]
            client.download_image(
                filename=first["filename"],
                dest=filtered_image_path,
                subfolder=first.get("subfolder", ""),
                folder_type=first.get("type", "output"),
            )
            comfy_dt = time.time() - t0
            rec["comfy_latency_s"] = round(comfy_dt, 2)
            rec["generation_params"] = gen_params
            print(f"        Comfy ✅ {comfy_dt:.1f}s → {filtered_image_path.name}", flush=True)
        except Exception as exc:
            rec["error_comfy"] = f"{type(exc).__name__}: {exc}"
            print(f"        Comfy ❌ {rec['error_comfy']}", flush=True)
            results.append(rec)
            continue

        # Étape 5a : histogram filtered + original
        try:
            rec["histogram_filtered"] = histogram_check(filtered_image_path)
            print(
                f"        hist filtered: color={rec['histogram_filtered']['color_ratio']:.4f} "
                f"ink={rec['histogram_filtered']['ink_ratio']:.4f} flags={rec['histogram_filtered']['flags']}",
                flush=True,
            )
        except Exception as exc:
            rec["error_hist_filtered"] = f"{type(exc).__name__}: {exc}"
        try:
            rec["histogram_original"] = histogram_check(ORIG_DIR / t["original_image"])
        except Exception as exc:
            rec["error_hist_original"] = f"{type(exc).__name__}: {exc}"

        # Étape 5b : vision QC filtered
        v_filtered = call_vision_qc(filtered_image_path)
        rec["vision_filtered"] = v_filtered
        if v_filtered.get("error"):
            print(f"        vision filtered ❌ {v_filtered['error']}", flush=True)
        elif v_filtered.get("json_ok"):
            print(
                f"        vision filtered: verdict={v_filtered.get('verdict')} "
                f"issues={v_filtered.get('issues')} conf={v_filtered.get('confidence')} "
                f"({v_filtered.get('latency_s', 0):.1f}s)",
                flush=True,
            )

        # Vision QC original (référence) — l'image existe déjà du POC précédent
        v_original = call_vision_qc(ORIG_DIR / t["original_image"])
        rec["vision_original"] = v_original
        if v_original.get("json_ok"):
            print(
                f"        vision original: verdict={v_original.get('verdict')} "
                f"issues={v_original.get('issues')} conf={v_original.get('confidence')}",
                flush=True,
            )

        # Étape 6 : diff prompt PNG + compare 3 colonnes
        try:
            diff_png = OUTPUT_DIR / f"{t['slug']}_diff_prompt.png"
            render_prompt_diff_image(
                title=f"{t['category']} · {t['name_en']}",
                original=original_prompt,
                filtered=filtered_prompt,
                rules_log=log,
                out_path=diff_png,
            )
            compare_path = OUTPUT_DIR / f"{t['slug']}_compare.png"
            build_compare(
                original=ORIG_DIR / t["original_image"],
                filtered=filtered_image_path,
                diff_prompt=diff_png,
                out_path=compare_path,
            )
            rec["compare_image"] = str(compare_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            rec["diff_prompt_image"] = str(diff_png.relative_to(PROJECT_ROOT)).replace("\\", "/")
            print(f"        compare ✅ → {compare_path.name}", flush=True)
        except Exception as exc:
            rec["error_compare"] = f"{type(exc).__name__}: {exc}"
            print(f"        compare ❌ {rec['error_compare']}", flush=True)

        results.append(rec)

    # ── Agrégats par règle (a-t-elle été déclenchée et a-t-elle eu un effet ?) ──
    rule_stats: dict[str, dict] = {r["id"]: {"triggered_on": [], "n_total_matches": 0} for r in RULES}
    for r in results:
        if r.get("error") or r.get("error_comfy"):
            continue
        for ev in r.get("rules_log") or []:
            rid = ev["rule_id"]
            rule_stats[rid]["triggered_on"].append(r["concept"]["name_en"])
            n_matches = ev.get("n_matches") or (1 if "triggered_by" in ev else 0)
            rule_stats[rid]["n_total_matches"] += n_matches

    print(flush=True)
    print("─── Agrégats par règle ────────────────────────────────────────────────────────", flush=True)
    for rid, s in rule_stats.items():
        triggered = sorted(set(s["triggered_on"]))
        print(f"  · {rid:<25} déclenchée sur {len(triggered)}/{len(TARGETS)} concepts "
              f"({s['n_total_matches']} match(es)) : {triggered}", flush=True)

    payload = {
        "poc": "prompt-filter",
        "date": "2026-05-05",
        "workflow_template": WORKFLOW_TEMPLATE,
        "vision_model": VISION_MODEL,
        "rules": [{"id": r["id"], "type": r["type"]} for r in RULES],
        "results": results,
        "rule_stats": rule_stats,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}", flush=True)

    # ── Markdown ──
    md: list[str] = []
    md.append("# POC prompt filter — validation empirique des règles de réécriture")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append(
        "Test isolé (pas d'intégration pipeline) de **4 règles de sanitisation appliquées avant ComfyUI** "
        "sur les 3 concepts problématiques du POC image quality :"
    )
    md.append("")
    for t in TARGETS:
        md.append(f"- `{t['slug']}` — {t['issue']}")
    md.append("")
    md.append("## Règles testées")
    md.append("")
    md.append("| ID | Type | Description |")
    md.append("|---|---|---|")
    md.append("| `anatomy_static_pose` | trigger_append | Si verbe d'action détecté (kicking, running, mid-air, …), append « simple static pose, exactly two legs and two arms ». |")
    md.append("| `no_light_sources` | phrase_replace | Strip des sources lumineuses (sunlight, golden light, glowing, …) qui poussent ERNIE à ajouter un rendu ombré/coloré. |")
    md.append("| `strip_color_nouns` | regex_replace | `\\b(red|blue|green|...)\\s+(\\w+)` → ne garde que le nom, sauf si suivi de `background`/`outlines`/`line` (mots-clés line-art à préserver). |")
    md.append("| `no_colorful_adjectives` | phrase_replace | `colorful → cheerful`, `vibrant → lively`, `bright → inviting`, `multicolored → varied`, `vivid → clear`. |")
    md.append("")

    md.append("## Tableau résumé par concept")
    md.append("")
    md.append("| Concept | Règles décl. | color_ratio orig→filt | ink_ratio orig→filt | Vision orig (issues) | Vision filt (issues) | Anatomie OK ? |")
    md.append("|---|---:|---:|---:|---|---|:---:|")
    for r in results:
        if r.get("error") or r.get("error_comfy"):
            err = r.get("error") or r.get("error_comfy")
            md.append(f"| {r['concept']['name_en']} | — | — | — | — | — | err: {err} |")
            continue
        c = r["concept"]
        ho = r.get("histogram_original", {})
        hf = r.get("histogram_filtered", {})
        vo = r.get("vision_original", {})
        vf = r.get("vision_filtered", {})
        oc = ho.get("color_ratio", 0.0)
        fc = hf.get("color_ratio", 0.0)
        oi = ho.get("ink_ratio", 0.0)
        fi = hf.get("ink_ratio", 0.0)
        vo_iss = ", ".join(vo.get("issues") or []) if vo.get("json_ok") else "?"
        vf_iss = ", ".join(vf.get("issues") or []) if vf.get("json_ok") else "?"
        vo_v = vo.get("verdict") if vo.get("json_ok") else "?"
        vf_v = vf.get("verdict") if vf.get("json_ok") else "?"
        # Anatomie : on la juge "OK" si la règle anatomy_static_pose a été déclenchée
        # ET qu'aucun issue blurry/incomplete/anatomy n'apparaît côté vision filtered.
        anat_rule = any(ev["rule_id"] == "anatomy_static_pose" for ev in r.get("rules_log") or [])
        bad_anat = any(
            i in (vf.get("issues") or [])
            for i in ("incomplete", "blurry", "noisy", "artifacts", "not_line_art")
        )
        anat_ok = "✅" if anat_rule and not bad_anat else ("n/a" if not anat_rule else "⚠")
        md.append(
            f"| {c['name_en']} | {r['n_rules_triggered']} "
            f"| {oc:.4f} → **{fc:.4f}** "
            f"| {oi:.4f} → {fi:.4f} "
            f"| **{vo_v}** ({vo_iss or '—'}) "
            f"| **{vf_v}** ({vf_iss or '—'}) "
            f"| {anat_ok} |"
        )
    md.append("")

    md.append("## Détail des règles déclenchées par concept")
    md.append("")
    for r in results:
        if r.get("error") or r.get("error_comfy"):
            continue
        c = r["concept"]
        md.append(f"### [{c['category']}] {c['name_en']}")
        md.append(f"- Issue ciblée : {c['issue']}")
        log = r.get("rules_log") or []
        if not log:
            md.append("- **Aucune règle déclenchée** — les patterns n'ont rien matché. Possible que le writer ait déjà neutralisé ces tournures, ou que les règles soient mal calibrées sur ce concept.")
        else:
            md.append(f"- {len(log)} événement(s) :")
            for ev in log:
                if "needle" in ev:
                    md.append(f"  - `{ev['rule_id']}` — `'{ev['needle']}' → '{ev['replacement']}'` ×{ev['n_matches']}")
                elif "examples" in ev:
                    md.append(f"  - `{ev['rule_id']}` — regex ×{ev['n_matches']} (ex. {', '.join(ev['examples'][:6])})")
                elif "triggered_by" in ev:
                    md.append(f"  - `{ev['rule_id']}` — trigger `'{ev['triggered_by']}'` → append +{ev.get('after_len', 0) - ev.get('before_len', 0)} chars")
        md.append("")
        md.append(f"**Image filtrée :** `{r.get('filtered_image')}` · **Compare 3-col :** `{r.get('compare_image')}` · **Diff prompt txt :** `{r.get('prompt_diff_txt')}`")
        md.append("")

    md.append("## Comparaisons côte à côte")
    md.append("")
    md.append("3 colonnes par concept : `original POC mono | filtered (ce POC) | diff_prompt rendu PNG`.")
    md.append("")
    for r in results:
        if r.get("compare_image"):
            md.append(f"### [{r['concept']['category']}] {r['concept']['name_en']}")
            md.append(f"![compare](../../{r['compare_image']})")
            md.append("")

    md.append("## Verdict par règle")
    md.append("")
    md.append("| Règle | Déclenchée sur | Effet observé | Effets de bord |")
    md.append("|---|---|---|---|")
    for rid, s in rule_stats.items():
        triggered = sorted(set(s["triggered_on"]))
        n = len(triggered)
        # Heuristique d'effet : pour chaque concept où elle s'est déclenchée, regarder si
        # le verdict s'est amélioré (issues réduites) ou pas
        effect = "—"
        side: list[str] = []
        if rid == "strip_color_nouns" or rid == "no_colorful_adjectives" or rid == "no_light_sources":
            # Mesurer Δ color_ratio sur les concepts où elle s'est déclenchée
            deltas = []
            for r in results:
                if r.get("error") or r.get("error_comfy"):
                    continue
                if r["concept"]["name_en"] not in triggered:
                    continue
                orig_c = (r.get("histogram_original") or {}).get("color_ratio", 0.0)
                filt_c = (r.get("histogram_filtered") or {}).get("color_ratio", 0.0)
                deltas.append((r["concept"]["name_en"], orig_c, filt_c))
            if deltas:
                effect = "Δ color_ratio : " + " ; ".join(
                    f"{name} {oc:.4f}→{fc:.4f}" for name, oc, fc in deltas
                )
        elif rid == "anatomy_static_pose":
            for r in results:
                if r.get("error") or r.get("error_comfy"):
                    continue
                if r["concept"]["name_en"] not in triggered:
                    continue
                vf = r.get("vision_filtered") or {}
                vo = r.get("vision_original") or {}
                effect = (
                    f"Vision filtered: verdict={vf.get('verdict', '?')} issues={vf.get('issues') or []} ; "
                    f"original: verdict={vo.get('verdict', '?')} issues={vo.get('issues') or []}"
                )
        md.append(f"| `{rid}` | {n}/{len(TARGETS)} ({', '.join(triggered) or '—'}) | {effect} | {' ; '.join(side) or '—'} |")
    md.append("")

    md.append("## Verdict global")
    md.append("")
    n_color_improved = 0
    n_color_same_or_worse = 0
    for r in results:
        if r.get("error") or r.get("error_comfy"):
            continue
        oc = (r.get("histogram_original") or {}).get("color_ratio", 0.0)
        fc = (r.get("histogram_filtered") or {}).get("color_ratio", 0.0)
        if fc < oc - 0.005:
            n_color_improved += 1
        elif fc > oc + 0.005:
            n_color_same_or_worse += 1
        # else: identique
    n_ok = sum(1 for r in results if isinstance(r.get("vision_filtered"), dict) and r["vision_filtered"].get("verdict") == "good")
    md.append(f"- Images avec verdict ``good`` après filtre : **{n_ok}/{len(results)}**")
    md.append(f"- Δ color_ratio improved (>0.005) : **{n_color_improved}/{len(results)}**")
    md.append(f"- Δ color_ratio dégradé (>0.005) : **{n_color_same_or_worse}/{len(results)}**")
    md.append("")
    md.append("**Question : intégrer le filtre dans le pipeline ou ajuster les règles d'abord ?**")
    md.append("")
    md.append("→ Lecture humaine du tableau ci-dessus + revue visuelle des 3 PNG `_compare.png` "
              "permet de trancher concept par concept. Le filtre est **complémentaire** au two-step "
              "colored→lineart (POC précédent) : le filtre traite le prompt en upstream (léger, "
              "transparent), le two-step traite le rendu en downstream (robuste face aux color priors "
              "que le filtre ne peut pas neutraliser purement par texte).")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Galerie : `docs/reports/poc-prompt-filter/` (1 filtered + 1 diff_prompt + 1 compare + 1 diff txt par concept)")
    md.append("- Données brutes : `2026-05-05_poc-prompt-filter.json` (prompts orig/filtered + log règles + histogram + vision)")
    md.append("- Source prompts originaux : `2026-05-05_poc-prompt-chain-v2.json`")
    md.append("- Originaux mono : `docs/reports/poc-image-quality/`")
    md.append("- Script : `scripts/poc_prompt_filter.py`")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
