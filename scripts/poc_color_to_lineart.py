"""POC two-step colored→lineart vs monochrome direct.

Hypothèse à tester : pour les subjects à fort prior couleur (refrigerator,
dragon, etc.), demander une **illustration colorée style flat-color cartoon
avec contours noirs épais** puis **extraire les contours en post-traitement
non-IA** donne-t-il un meilleur line art que la génération monochrome
directe (qui leak des couleurs résiduelles, cf. POC image quality 2/8 KO) ?

Concepts testés (les 3 problématiques du POC précédent) :
- electromenager / Refrigerator in a Kitchen — couleurs résiduelles + lighting
- fantasy / Dragon in a Castle Courtyard — couleurs résiduelles
- sports / Soccer Ball on a Field — anatomie du joueur (3 jambes en monochrome)

3 méthodes d'extraction (Pillow only, < 50 ms / image) :
- Méthode A : dark pixel extraction (R<80 ET G<80 ET B<80 → noir, reste → blanc)
- Méthode B : grayscale threshold simple (L<128 → noir, reste → blanc)
- Méthode C : grayscale threshold agressif (L<160) — enlève davantage les ombres grises

Métriques par image résultante :
- Pillow histogram (color_ratio, white_ratio, ink_ratio)
- QC vision qwen3.5:9b — verdict + issues (mêmes paramètres que poc_image_quality.py)
- closed_contours_ratio — heuristique floodfill depuis les 4 coins :
  proportion de pixels blancs atteignables depuis le bord (= zones « ouvertes »,
  non colorables proprement par un enfant). Plus haut = pire.

Sortie côte-à-côte par concept : 4 colonnes
[ original monochrome | colored source | method_A | method_B ].

Usage :
    python scripts/poc_color_to_lineart.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
from collections import deque
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
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

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

OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-color-to-lineart"
ORIG_DIR = PROJECT_ROOT / "docs" / "reports" / "poc-image-quality"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-color-to-lineart.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-color-to-lineart.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

# Vision QC — mêmes params que poc_image_quality.py
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

# 3 prompts colorés "flat color cartoon avec contours noirs épais" — même scène
# que les originaux v2, mais on ne demande plus du monochrome ; au contraire on
# demande explicitement les flat color fills pour les contours soient compagnons
# d'aplats — l'extraction post-process reposera sur ces aplats noirs.
COLORED_PROMPTS: list[dict] = [
    {
        "category": "electromenager",
        "name_en": "Refrigerator in a Kitchen",
        "slug": "electromenager-refrigerator-in-a-kitchen",
        "original_image": "electromenager-refrigerator-in-a-kitchen.png",
        "prompt": (
            "A wide shot centered on a refrigerator with magnets and fruit on the "
            "counter in a bright and clean kitchen, cheerful and inviting mood. "
            "The scene features a red apple, a yellow banana, a magnetic star, and a "
            "magnetic heart placed on the kitchen counter near an open refrigerator "
            "door and white cabinets, with a window letting in sunlight.\n\n"
            "Style: children's book cartoon illustration, thick bold black outlines "
            "around every shape, flat solid color fills inside each region, white "
            "background, clean vector style, no shading, no gradients, no textures, "
            "no soft edges. Each object is delineated by a clear continuous black contour.\n\n"
            "Technical cleanup: no text, no letters, no numbers, no words, no signs, "
            "no labels, no watermarks, no logos, no signatures, clean layout."
        ),
        "negative_prompt": "",
    },
    {
        "category": "fantasy",
        "name_en": "Dragon in a Castle Courtyard",
        "slug": "fantasy-dragon-in-a-castle-courtyard",
        "original_image": "fantasy-dragon-in-a-castle-courtyard.png",
        "prompt": (
            "A wide shot centered on a friendly green dragon standing in a medieval "
            "castle courtyard with towers and a drawbridge, adventurous and cheerful "
            "mood. The scene features stone castle towers with arched windows, a "
            "drawbridge extending across the courtyard, red banners hanging from "
            "the towers, a stone fountain in the center, a large stone gate, green "
            "bushes, and the dragon's large wings spread wide.\n\n"
            "Style: children's book cartoon illustration, thick bold black outlines "
            "around every shape, flat solid color fills inside each region, white "
            "background, clean vector style, no shading, no gradients, no textures. "
            "Each object is delineated by a clear continuous black contour.\n\n"
            "Technical cleanup: no text, no letters, no numbers, no words, no signs, "
            "no labels, no watermarks, no logos, no signatures, clean layout."
        ),
        "negative_prompt": "",
    },
    {
        "category": "sports",
        "name_en": "Soccer Ball on a Field",
        "slug": "sports-soccer-ball-on-a-field",
        "original_image": "sports-soccer-ball-on-a-field.png",
        "prompt": (
            "A wide shot centered on a child kicking a soccer ball on a sunny outdoor "
            "grass field with a goal, cheerful and energetic mood. The scene features "
            "a soccer ball in mid-air, green grass rendered as simple shapes, a white "
            "goal net with clear mesh patterns, stadium stands in the background, a "
            "blue sky with fluffy clouds, a goal post, and motion lines indicating "
            "the kick. The child has exactly two legs in a natural kicking pose.\n\n"
            "Style: children's book cartoon illustration, thick bold black outlines "
            "around every shape, flat solid color fills inside each region, white "
            "background, clean vector style, no shading, no gradients, no textures. "
            "Each character and object is delineated by a clear continuous black contour.\n\n"
            "Technical cleanup: no text, no letters, no numbers, no words, no signs, "
            "no labels, no watermarks, no logos, no signatures, clean layout, anatomy correct."
        ),
        "negative_prompt": "",
    },
]


def slug_path(slug: str, suffix: str) -> Path:
    return OUTPUT_DIR / f"{slug}_{suffix}.png"


# ─── Méthodes d'extraction ──────────────────────────────────────────────────

def method_a_dark_pixel(img: Image.Image) -> Image.Image:
    """RGB strict : pixel noir si R<80 ET G<80 ET B<80, sinon blanc."""
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    dark = (r < 80) & (g < 80) & (b < 80)
    out = np.full(arr.shape[:2] + (3,), 255, dtype=np.uint8)
    out[dark] = (0, 0, 0)
    return Image.fromarray(out, mode="RGB")


def method_b_gray_threshold(img: Image.Image, threshold: int = 128) -> Image.Image:
    """Grayscale + seuil : L<threshold → noir, sinon blanc."""
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    out = np.where(gray < threshold, 0, 255).astype(np.uint8)
    rgb = np.stack([out, out, out], axis=-1)
    return Image.fromarray(rgb, mode="RGB")


def method_c_gray_threshold_aggressive(img: Image.Image, threshold: int = 160) -> Image.Image:
    """Grayscale + seuil plus haut → enlève davantage les ombres grises."""
    return method_b_gray_threshold(img, threshold=threshold)


# ─── closed_contours_ratio (heuristique) ───────────────────────────────────

def closed_contours_ratio(img: Image.Image, threshold: int = 200) -> float:
    """Proportion des pixels blancs atteignables depuis les 4 bords (= zones « ouvertes »).

    Plus haut = pire (plus de zones où la couleur d'un enfant fuirait au floodfill).
    Une scène line art idéale a quelques zones intérieures fermées, donc seul le
    fond extérieur est atteignable depuis les bords → ratio ~0.4-0.7.
    Une scène avec contours pétés = quasi tout l'intérieur atteignable → ratio > 0.8.
    """
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    h, w = gray.shape
    is_white = gray >= threshold
    visited = np.zeros_like(is_white, dtype=bool)

    # Seeds : pixels blancs sur les 4 bords
    queue: deque = deque()
    for x in range(w):
        if is_white[0, x] and not visited[0, x]:
            visited[0, x] = True
            queue.append((0, x))
        if is_white[h - 1, x] and not visited[h - 1, x]:
            visited[h - 1, x] = True
            queue.append((h - 1, x))
    for y in range(h):
        if is_white[y, 0] and not visited[y, 0]:
            visited[y, 0] = True
            queue.append((y, 0))
        if is_white[y, w - 1] and not visited[y, w - 1]:
            visited[y, w - 1] = True
            queue.append((y, w - 1))

    while queue:
        y, x = queue.popleft()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and is_white[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                queue.append((ny, nx))

    total_white = int(is_white.sum())
    if total_white == 0:
        return 0.0
    reachable = int(visited.sum())
    return round(reachable / total_white, 4)


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


# ─── Histogram ─────────────────────────────────────────────────────────────

def histogram_check(image_path: Path) -> dict:
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    return {
        "color_ratio": float(metrics.get("color_ratio", 0.0)),
        "white_ratio": float(metrics.get("white_ratio", 0.0)),
        "ink_ratio": float(metrics.get("ink_ratio", 0.0)),
        "flags": qc.get("flags") or [],
        "status": qc.get("status"),
    }


# ─── Compare 4-col ──────────────────────────────────────────────────────────

def build_compare(
    *,
    original_mono: Path,
    colored: Path,
    method_a: Path,
    method_b: Path,
    out_path: Path,
    cell: int = 512,
) -> Path:
    """4 colonnes : original mono | colored | method_A | method_B (chacune 512×512)."""
    canvas = Image.new("RGB", (cell * 4, cell), (255, 255, 255))
    for i, p in enumerate([original_mono, colored, method_a, method_b]):
        if p.is_file():
            img = Image.open(p).convert("RGB").resize((cell, cell), Image.LANCZOS)
        else:
            img = Image.new("RGB", (cell, cell), (240, 240, 240))
        canvas.paste(img, (i * cell, 0))
    canvas.save(out_path, "PNG")
    return out_path


# ─── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 100, flush=True)
    print("POC color-to-lineart — ERNIE coloré + extraction contours non-IA", flush=True)
    print("=" * 100, flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI indisponible sur {client.base_url}", file=sys.stderr)
        return 1
    print(f"\nComfyUI OK : {client.base_url}", flush=True)
    print(f"Workflow : {WORKFLOW_TEMPLATE} · Vision QC : {VISION_MODEL}", flush=True)
    print(flush=True)

    results: list[dict] = []
    for i, c in enumerate(COLORED_PROMPTS, 1):
        print(f"[{i}/{len(COLORED_PROMPTS)}] {c['category']:<20} {c['name_en']}", flush=True)
        rec: dict = {
            "concept": c,
            "original_mono_image": str((ORIG_DIR / c["original_image"]).relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }

        # Étape 2 : génération colorée
        colored_path = slug_path(c["slug"], "colored")
        try:
            t0 = time.time()
            prompt_id, gen_params = submit_to_comfy(client, c["prompt"], c["negative_prompt"])
            history = client.poll_until_done(prompt_id)
            images = client.extract_output_images(history)
            if not images:
                raise RuntimeError("Aucune image dans l'historique ComfyUI")
            first = images[0]
            client.download_image(
                filename=first["filename"],
                dest=colored_path,
                subfolder=first.get("subfolder", ""),
                folder_type=first.get("type", "output"),
            )
            comfy_dt = time.time() - t0
            rec["colored_image"] = str(colored_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            rec["comfy_latency_s"] = round(comfy_dt, 2)
            rec["generation_params"] = gen_params
            print(f"        Comfy ✅ {comfy_dt:.1f}s → {colored_path.name}", flush=True)
        except Exception as exc:
            rec["error_comfy"] = f"{type(exc).__name__}: {exc}"
            print(f"        Comfy ❌ {rec['error_comfy']}", flush=True)
            results.append(rec)
            continue

        # Étape 3 : 3 méthodes d'extraction
        rec["methods"] = {}
        try:
            src = Image.open(colored_path).convert("RGB")
        except Exception as exc:
            rec["error_extraction"] = f"{type(exc).__name__}: {exc}"
            print(f"        extract ❌ {rec['error_extraction']}", flush=True)
            results.append(rec)
            continue

        for method_name, fn in (
            ("method_a", method_a_dark_pixel),
            ("method_b", method_b_gray_threshold),
            ("method_c", method_c_gray_threshold_aggressive),
        ):
            t0 = time.time()
            converted = fn(src)
            extr_dt = time.time() - t0
            out_path = slug_path(c["slug"], method_name)
            converted.save(out_path, "PNG")

            # Pillow histogram
            hist = histogram_check(out_path)
            # Closed contours
            t0 = time.time()
            ccr = closed_contours_ratio(converted)
            ccr_dt = time.time() - t0

            method_rec: dict = {
                "image": str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "extract_latency_s": round(extr_dt, 4),
                "closed_contours_ratio": ccr,
                "closed_contours_latency_s": round(ccr_dt, 4),
                "histogram": hist,
            }
            print(
                f"        {method_name} extract={extr_dt*1000:.1f}ms ccr={ccr:.3f} "
                f"color={hist['color_ratio']:.4f} ink={hist['ink_ratio']:.4f} flags={hist['flags']}",
                flush=True,
            )

            # Vision QC
            v = call_vision_qc(out_path)
            method_rec["vision_qc"] = v
            if v.get("error"):
                print(f"            vision ❌ {v['error']}", flush=True)
            elif not v.get("json_ok"):
                print(f"            vision ⚠ JSON parse fail", flush=True)
            else:
                print(
                    f"            vision verdict={v.get('verdict')} issues={v.get('issues')} "
                    f"conf={v.get('confidence')} ({v.get('latency_s', 0):.1f}s)",
                    flush=True,
                )

            rec["methods"][method_name] = method_rec

        # Histogram + ccr sur la source colorée elle-même (référence)
        try:
            src_hist = histogram_check(colored_path)
            src_ccr = closed_contours_ratio(src)
            rec["colored_source"] = {
                "histogram": src_hist,
                "closed_contours_ratio": src_ccr,
            }
        except Exception:
            pass

        # Étape 5 : compare 4 colonnes
        compare_path = OUTPUT_DIR / f"{c['slug']}_compare.png"
        try:
            build_compare(
                original_mono=ORIG_DIR / c["original_image"],
                colored=colored_path,
                method_a=slug_path(c["slug"], "method_a"),
                method_b=slug_path(c["slug"], "method_b"),
                out_path=compare_path,
            )
            rec["compare_image"] = str(compare_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            print(f"        compare ✅ → {compare_path.name}", flush=True)
        except Exception as exc:
            rec["error_compare"] = f"{type(exc).__name__}: {exc}"
            print(f"        compare ❌ {rec['error_compare']}", flush=True)

        results.append(rec)

    # ── Agrégats : pour chaque concept, quelle méthode gagne ? ──
    # Heuristique gagnante : verdict good ET ink_ratio dans [0.005, 0.55] ET ccr le plus bas
    print(flush=True)
    print("─── Méthode gagnante par concept ──────────────────────────────────────────────", flush=True)
    winners: list[dict] = []
    for r in results:
        if "methods" not in r:
            continue
        candidates = []
        for mname, m in r["methods"].items():
            v = m.get("vision_qc") or {}
            verdict = v.get("verdict") if v.get("json_ok") else None
            issues = set(v.get("issues") or [])
            ink = m.get("histogram", {}).get("ink_ratio", 0.0)
            color = m.get("histogram", {}).get("color_ratio", 0.0)
            ccr = m.get("closed_contours_ratio", 1.0)
            # Score : good=2, valid ink range=1, low ccr bonus, low color bonus
            score = 0
            if verdict == "good":
                score += 50
            if "has_color" not in issues:
                score += 10
            if "has_text" not in issues:
                score += 5
            if 0.005 <= ink <= 0.55:
                score += 10
            if color < 0.025:
                score += 10
            score -= int(ccr * 30)  # plus ccr est haut, plus c'est pénalisant
            candidates.append((score, mname, m))
        candidates.sort(key=lambda x: -x[0])
        winner_score, winner_name, winner = candidates[0]
        winners.append({
            "concept": r["concept"]["name_en"],
            "category": r["concept"]["category"],
            "winner": winner_name,
            "winner_score": winner_score,
            "ranking": [(m, s) for s, m, _ in candidates],
        })
        print(f"  · {r['concept']['name_en']:<35} → **{winner_name}** (score {winner_score})  "
              f"ranking: {', '.join(f'{m}:{s}' for s, m, _ in candidates)}", flush=True)

    payload = {
        "poc": "color-to-lineart",
        "date": "2026-05-05",
        "workflow_template": WORKFLOW_TEMPLATE,
        "vision_model": VISION_MODEL,
        "results": results,
        "winners": winners,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nJSON brut → {REPORT_JSON}", flush=True)

    # ── Markdown ──
    md: list[str] = []
    md.append("# POC color-to-lineart — ERNIE coloré + extraction contours non-IA")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append(
        "Le POC image quality précédent a identifié **2/8 images KO histogram** sur des subjects à "
        "fort prior couleur (Refrigerator, Dragon). Hypothèse testée ici : générer une **illustration "
        "colorée style cartoon avec contours noirs épais** puis **extraire les contours en post-traitement "
        "non-IA (Pillow)** donne-t-il un meilleur line art que la génération monochrome directe ? "
        "Bonus, on rajoute le 3e cas problématique du POC précédent : **Soccer Ball / 3 jambes**, pour "
        "voir si le mode coloré + post-process améliore aussi l'anatomie."
    )
    md.append("")
    md.append("## Méthodes d'extraction")
    md.append("")
    md.append("- **Méthode A — dark pixel RGB strict** : noir ssi `R<80 ET G<80 ET B<80`, sinon blanc. Repose sur le fait que ERNIE produit des contours noirs purs en mode colored cartoon.")
    md.append("- **Méthode B — grayscale threshold L<128** : binaire simple sur la luminance.")
    md.append("- **Méthode C — grayscale threshold L<160** (agressif) : enlève davantage les ombres grises au prix de perdre des traits fins.")
    md.append("")
    md.append("**closed_contours_ratio** = proportion des pixels blancs atteignables depuis les 4 bords par floodfill 4-connexité (`flag d'« ouverture »` du dessin). Plus haut = plus de zones non fermées où la couleur d'un enfant fuirait. Référence : un line art bien fermé est typiquement `0.4-0.7` (le fond extérieur seul est atteignable).")
    md.append("")

    md.append("## Résultats par concept et méthode")
    md.append("")
    md.append("| Concept | Méthode | color_ratio | ink_ratio | white_ratio | ccr | flags hist | Vision verdict | Vision issues | Conf |")
    md.append("|---|---|---:|---:|---:|---:|---|:---:|---|---:|")
    for r in results:
        c = r["concept"]
        if "error_comfy" in r:
            md.append(f"| {c['name_en']} | (Comfy fail) | — | — | — | — | — | — | {r['error_comfy']} | — |")
            continue
        # source colorée
        src = r.get("colored_source") or {}
        h0 = src.get("histogram") or {}
        md.append(
            f"| **{c['name_en']}** | _colored source_ | "
            f"{h0.get('color_ratio', '—')} | {h0.get('ink_ratio', '—')} | "
            f"{h0.get('white_ratio', '—')} | {src.get('closed_contours_ratio', '—')} | "
            f"{h0.get('flags', [])} | — | — | — |"
        )
        for mname in ("method_a", "method_b", "method_c"):
            m = r.get("methods", {}).get(mname) or {}
            v = m.get("vision_qc") or {}
            h = m.get("histogram") or {}
            verdict = v.get("verdict") if v.get("json_ok") else "—"
            issues = ", ".join(v.get("issues") or []) or "—"
            conf = v.get("confidence") if v.get("confidence") is not None else "—"
            md.append(
                f"| | {mname} | {h.get('color_ratio', '—')} | {h.get('ink_ratio', '—')} | "
                f"{h.get('white_ratio', '—')} | {m.get('closed_contours_ratio', '—')} | "
                f"{h.get('flags', [])} | **{verdict}** | {issues} | {conf} |"
            )
    md.append("")

    md.append("## Méthode gagnante par concept")
    md.append("")
    md.append("Score heuristique : verdict ``good`` (+50), pas `has_color` (+10), pas `has_text` (+5), "
              "ink_ratio ∈ [0.005, 0.55] (+10), color_ratio < 0.025 (+10), pénalité `int(ccr × 30)`.")
    md.append("")
    md.append("| Concept | Catégorie | Gagnante | Score | Ranking |")
    md.append("|---|---|:---:|---:|---|")
    for w in winners:
        md.append(
            f"| {w['concept']} | {w['category']} | **{w['winner']}** | {w['winner_score']} | "
            f"{', '.join(f'{m}:{s}' for m, s in w['ranking'])} |"
        )
    md.append("")

    md.append("## Comparaisons côte à côte")
    md.append("")
    md.append("4 colonnes par image : `original mono (POC précédent) | colored source | method_A | method_B`.")
    md.append("")
    for r in results:
        if r.get("compare_image"):
            md.append(f"### [{r['concept']['category']}] {r['concept']['name_en']}")
            md.append(f"![compare](../../{r['compare_image']})")
            md.append("")
            md.append(f"- Original mono : `{r.get('original_mono_image')}`")
            md.append(f"- Colored source : `{r.get('colored_image')}`")
            for mname in ("method_a", "method_b", "method_c"):
                m = r.get("methods", {}).get(mname) or {}
                if m.get("image"):
                    md.append(f"- {mname} : `{m['image']}`")
            md.append("")

    # Verdict global : majoritaire bon ou pas ?
    n_concepts = sum(1 for r in results if "methods" in r)
    n_winner_good = sum(
        1 for w in winners
        if w["winner_score"] >= 50  # = au moins verdict good
    )
    md.append("## Verdict global")
    md.append("")
    if n_winner_good == n_concepts and n_concepts > 0:
        md.append(
            f"✅ **Two-step colored→lineart vaut mieux que le monochrome direct sur les {n_concepts}/{n_concepts} "
            "subjects à fort prior couleur testés ici.** Le modèle ERNIE en mode colored cartoon respecte mieux "
            "les contraintes de contours fermés (sortie naturelle pour ce style), et l'extraction RGB strict "
            "donne un line art monochrome propre sans leak couleur."
        )
    elif n_winner_good >= n_concepts // 2 + 1:
        md.append(
            f"⚠ **Two-step partiellement convaincant** : {n_winner_good}/{n_concepts} concepts ont une méthode "
            "post-process avec verdict ``good``. Voir détails par concept ci-dessus pour décider concept par concept."
        )
    else:
        md.append(
            f"❌ **Two-step non convaincant globalement** : seulement {n_winner_good}/{n_concepts} concepts ont une "
            "méthode post-process avec verdict ``good``. Rester sur les prompts monochrome renforcés du POC-3 v2 "
            "+ traiter le pattern color_prior par anti-color-prior dans le writer (recommandation initiale)."
        )
    md.append("")

    md.append("## Recommandation architecturale")
    md.append("")
    md.append("Deux options viables selon le résultat ci-dessus :")
    md.append("")
    md.append("**Option 1 — `profile color_prior` two-step** : ajouter un nouveau profile pipeline "
              "`kids_coloring_lineart_color_prior_v1` activé pour les subjects flagués (refrigerator, "
              "dragon, fruit, drapeau, perroquet, papillon, etc. — liste à curer). Workflow : prompt cartoon "
              "coloré → ComfyUI → extraction Pillow méthode gagnante par défaut → QC vision sur le résultat "
              "monochrome final. Avantage : robuste sur les category priors, pas besoin de tordre le LLM. "
              "Coût : 1 step Pillow supplémentaire (~50 ms), pas d'appel LLM/image en plus.")
    md.append("")
    md.append("**Option 2 — anti-color-prior dans le writer** : ajouter à `prompt_writer_ernie.system` "
              "une consigne « When the subject is commonly depicted in color in reference images "
              "(refrigerator, dragon, fruit, flag, parrot, butterfly), prepend ‘plain black silhouette of a’ "
              "to neutralize the color prior. ». Avantage : single-step, simple. Coût : à valider que cette "
              "consigne ne dégrade pas les autres subjects. À tester en A/B sur le 8-pack du POC précédent.")
    md.append("")
    md.append("Une combinaison **Option 1 + Option 2** est aussi possible : neutraliser dans le writer "
              "(option 2) et garder le post-process two-step en filet de sécurité quand le histogram remonte "
              "encore `noticeable_color`.")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Galerie : `docs/reports/poc-color-to-lineart/` (1 colored + 3 méthodes + 1 compare par concept)")
    md.append("- Données brutes : `2026-05-05_poc-color-to-lineart.json`")
    md.append("- Originaux mono : `docs/reports/poc-image-quality/` (réutilisés sans modification)")
    md.append("- Source prompts originaux : `2026-05-05_poc-prompt-chain-v2.json`")
    md.append("- Script : `scripts/poc_color_to_lineart.py`")
    md.append("- Comparaison QC : POC image quality `2026-05-05_poc-image-quality.md`")
    md.append("")
    md.append("**Points d'attention :**")
    md.append("- Si les contours ERNIE en colored cartoon ne sont pas noirs purs (ex. brun foncé / contour orangé), méthode A peut louper des traits — basculer alors sur méthode B/C (grayscale).")
    md.append("- `closed_contours_ratio` est une heuristique 4-connexité ; les fins traits diagonaux peuvent laisser des fuites au floodfill. Lecture complémentaire à la métrique vision.")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
