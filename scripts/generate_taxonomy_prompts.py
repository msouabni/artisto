"""Génération de prompts image par sujet via qwen3.5:4b avec routage par tier.

Lit `data/taxonomy_subjects.json` (204 sujets, sortie de
`generate_taxonomy_subjects.py`), dispatche chaque sujet vers un système prompt
+ user prompt spécifique au tier, puis appelle qwen3.5:4b (think=false natif)
pour produire le `positive_prompt`. Ajoute le `negative_prompt` et les
`generation_params` figés par tier.

Output : `data/taxonomy_subjects_with_prompts.json` (atomique, incrémental).

Note d'implémentation : la version actuelle de `services.ollama_json.call_ollama_sync`
n'active pas `think: false` pour qwen3.5+ (cf. POC `generate_taxonomy_subjects`,
2026-05-07 — premier sujet a passé 60 s en mode thinking et n'a rien produit).
On bypasse donc avec un appel HTTP direct exactement comme dans
`generate_taxonomy_subjects.py`.

Usage :
    python scripts/generate_taxonomy_prompts.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import datetime, timezone
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

from services.ollama_json import strip_think_tags  # noqa: E402

INPUT_JSON = PROJECT_ROOT / "data" / "taxonomy_subjects.json"
OUTPUT_JSON = PROJECT_ROOT / "data" / "taxonomy_subjects_with_prompts.json"
OUTPUT_TMP = OUTPUT_JSON.with_suffix(".json.tmp")

MODEL = "qwen3.5:4b"
TEMPERATURE = 0.4
TIMEOUT = 180
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

WARN_MAX_CHARS = 500   # > 500 chars → warning mais on stocke quand même

# ─── Paramètres de génération par tier ──────────────────────────────────────

NEG_ANATOMY = (
    "extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, "
    "wrong number of limbs, six fingers, deformed feet"
)

COMMON_GEN_PARAMS = {
    "steps": 8,
    "sampler_name": "euler",
    "scheduler": "normal",
    "cfg": 1.0,
    "denoise": 1.0,
}

GEN_PARAMS_BY_TIER: dict[str, dict] = {
    "simple_inanimate": {"width": 768, "height": 768, "batch_size": 1, "negative_prompt": ""},
    "simple_animated":  {"width": 768, "height": 768, "batch_size": 1, "negative_prompt": ""},
    "anatomy":          {"width": 1024, "height": 1024, "batch_size": 3, "negative_prompt": NEG_ANATOMY},
    "mandala":          {"width": 768, "height": 768, "batch_size": 1, "negative_prompt": ""},
    "educational":      {"width": 512, "height": 512, "batch_size": 1, "negative_prompt": ""},
}

# ─── System prompts par tier ────────────────────────────────────────────────

SYSTEMS: dict[str, str] = {
    "simple_inanimate": (
        "You are a prompt engineer for a children's coloring book image generator. "
        "Write concise, visual image prompts."
    ),
    "simple_animated": (
        "You are a prompt engineer for a children's coloring book image generator. "
        "Write prompts for cute animal/creature illustrations."
    ),
    "anatomy": (
        "You are a prompt engineer for a children's coloring book image generator. "
        "Write prompts for human character scenes.\n"
        "IMPORTANT: always specify static pose, avoid motion words that cause "
        "anatomy defects."
    ),
    "mandala": (
        "You are a prompt engineer for a children's coloring book image generator "
        "specializing in mandala patterns."
    ),
    "educational": (
        "You are a prompt engineer for a children's coloring book image generator "
        "specializing in educational content for young children."
    ),
}

# ─── User templates par tier ────────────────────────────────────────────────

USER_TEMPLATE_INANIMATE_OR_ANIMATED = (
    "Subject: {name_en}\n"
    "Description: {description}\n"
    "Category: {leaf_name_en}\n\n"
    "Write a single image generation prompt for a children's coloring page.\n"
    "Requirements:\n"
    "- Centered composition, single clear subject\n"
    "- \"Style: Black-and-white line art only, thick black outlines on pure "
    "white background, no shading, no gradients, no color fills\"\n"
    "- \"Technical cleanup: No text, no watermarks, clean layout\"\n"
    "- 2-3 sentences max, concrete visual details only\n"
    "Reply with ONLY the prompt text, no explanation, no quotes."
)

USER_TEMPLATE_ANATOMY = (
    "Subject: {name_en}\n"
    "Description: {description}\n"
    "Category: {leaf_name_en}\n\n"
    "Write an image generation prompt for a children's coloring page.\n"
    "Requirements:\n"
    "- STATIC POSE (standing, sitting — no jumping, running, kicking)\n"
    "- Single figure, centered, clear anatomy\n"
    "- \"Style: Black-and-white line art only, thick black outlines on pure "
    "white background, no shading, no gradients, no color fills\"\n"
    "- \"Technical cleanup: No text, no watermarks, clean layout\"\n"
    "- 2-3 sentences max\n"
    "Reply with ONLY the prompt text, no explanation, no quotes."
)

USER_TEMPLATE_MANDALA = (
    "Subject: {name_en}\n"
    "Description: {description}\n\n"
    "Write an image generation prompt for a children's coloring mandala.\n"
    "Requirements:\n"
    "- Perfectly symmetrical, radiating from center\n"
    "- Intricate but child-friendly geometric pattern\n"
    "- \"Style: Black-and-white line art only, perfectly symmetrical mandala, "
    "thick outlines on pure white background, no color fills\"\n"
    "- 2 sentences max\n"
    "Reply with ONLY the prompt text, no explanation, no quotes."
)

USER_TEMPLATE_EDUCATIONAL = (
    "Subject: {name_en}\n"
    "Description: {description}\n"
    "Category: {leaf_name_en}\n\n"
    "Write an image generation prompt for a children's educational coloring page.\n"
    "Requirements:\n"
    "- Large clear central element (letter, number, shape)\n"
    "- Simple decorative elements around it\n"
    "- \"Style: Black-and-white line art only, very clean simple outlines, "
    "no shading, no color fills, suitable for tracing\"\n"
    "- 2 sentences max\n"
    "Reply with ONLY the prompt text, no explanation, no quotes."
)


def build_user_prompt(subject: dict) -> str:
    tier = subject["tier"]
    args = {
        "name_en": subject["name_en"],
        "description": subject.get("description", ""),
        "leaf_name_en": subject.get("leaf_name_en", ""),
    }
    if tier == "anatomy":
        return USER_TEMPLATE_ANATOMY.format(**args)
    if tier == "mandala":
        return USER_TEMPLATE_MANDALA.format(**args)
    if tier == "educational":
        return USER_TEMPLATE_EDUCATIONAL.format(**args)
    # simple_inanimate / simple_animated (et fallback)
    return USER_TEMPLATE_INANIMATE_OR_ANIMATED.format(**args)


def call_qwen35_direct(user: str, system: str) -> str:
    """Appel HTTP direct à Ollama avec think=false natif (qwen3.5+)."""
    payload = {
        "model": MODEL,
        "system": system,
        "prompt": user,
        "stream": False,
        "options": {"temperature": TEMPERATURE},
        "think": False,
    }
    with httpx.Client(timeout=float(TIMEOUT)) as c:
        r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    if "error" in data and "response" not in data:
        raise RuntimeError(f"Ollama erreur modèle : {data['error']}")
    return data.get("response", "")


def clean_prompt_text(raw: str) -> str:
    """Strip think-tags puis cleanup léger : enlève fences/backticks et guillemets enveloppants."""
    text = strip_think_tags(raw or "").strip()
    # Enlever d'éventuels fences markdown
    if text.startswith("```"):
        text = text.lstrip("`").lstrip()
        # virer le mot "text"/"prompt" si présent en première ligne
        first_nl = text.find("\n")
        if first_nl >= 0 and len(text[:first_nl].split()) <= 2 and text[:first_nl].isalpha():
            text = text[first_nl + 1:].strip()
    if text.endswith("```"):
        text = text.rstrip("`").rstrip()
    # Enlever guillemets enveloppants
    if len(text) >= 2 and text[0] in {'"', "'"} and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text


def atomic_write(path: Path, tmp: Path, data: dict) -> None:
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    print("=" * 100, flush=True)
    print(f"Génération prompts taxonomie — modèle {MODEL} (T={TEMPERATURE}, think=false)", flush=True)
    print("=" * 100, flush=True)

    if not INPUT_JSON.is_file():
        print(f"❌ Source introuvable : {INPUT_JSON}", file=sys.stderr)
        return 1
    src = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    subjects: list[dict] = src.get("subjects") or []
    if not subjects:
        print("❌ Aucun sujet dans la source", file=sys.stderr)
        return 1

    print(f"\nSujets en entrée : {len(subjects)} (depuis {INPUT_JSON.relative_to(PROJECT_ROOT)})", flush=True)
    print(f"Output cible     : {OUTPUT_JSON.relative_to(PROJECT_ROOT)} (atomique via .tmp)", flush=True)
    print(flush=True)

    out_subjects: list[dict] = []
    failures: list[dict] = []
    warnings_count = 0
    started_at = datetime.now(timezone.utc).isoformat()

    for i, s in enumerate(subjects, 1):
        tier = s.get("tier") or "simple_inanimate"
        if tier not in GEN_PARAMS_BY_TIER:
            tier = "simple_inanimate"
            s["tier"] = tier  # normaliser

        leaf = s.get("leaf_name_en", "?")
        name = s.get("name_en", "?")
        print(f"[{i:>3}/{len(subjects)}] {leaf} / {name} — {tier}", flush=True, end=" ")

        system = SYSTEMS[tier]
        user = build_user_prompt(s)

        t0 = time.time()
        try:
            raw = call_qwen35_direct(user, system)
        except Exception as exc:
            dt = time.time() - t0
            print(f"❌ ollama: {type(exc).__name__}: {exc} ({dt:.1f}s)", flush=True)
            failures.append({"subject": s, "error": f"{type(exc).__name__}: {exc}"})
            continue
        dt = time.time() - t0

        positive = clean_prompt_text(raw)
        warn_flag = ""
        if not positive:
            warnings_count += 1
            warn_flag = " ⚠ empty"
        elif len(positive) > WARN_MAX_CHARS:
            warnings_count += 1
            warn_flag = f" ⚠ {len(positive)}c"

        gen = GEN_PARAMS_BY_TIER[tier]
        out_entry = {
            "leaf_id": s.get("leaf_id"),
            "leaf_name_en": s.get("leaf_name_en"),
            "parent_name_en": s.get("parent_name_en"),
            "name_en": s.get("name_en"),
            "tier": tier,
            "description": s.get("description", ""),
            "positive_prompt": positive,
            "negative_prompt": gen["negative_prompt"],
            "generation_params": {
                "width": gen["width"],
                "height": gen["height"],
                "batch_size": gen["batch_size"],
                **COMMON_GEN_PARAMS,
            },
        }
        out_subjects.append(out_entry)

        print(f"✅ {len(positive)}c {dt:.1f}s{warn_flag}", flush=True)

        # Persist incrémental après chaque sujet
        partial = {
            "generated_at": started_at,
            "model": MODEL,
            "temperature": TEMPERATURE,
            "total": len(subjects),
            "produced": len(out_subjects),
            "failures_count": len(failures),
            "warnings_count": warnings_count,
            "subjects": out_subjects,
            "failures": failures,
        }
        atomic_write(OUTPUT_JSON, OUTPUT_TMP, partial)

    # ── Résumé final ──
    final = {
        "generated_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "temperature": TEMPERATURE,
        "total": len(subjects),
        "produced": len(out_subjects),
        "failures_count": len(failures),
        "warnings_count": warnings_count,
        "subjects": out_subjects,
        "failures": failures,
    }
    atomic_write(OUTPUT_JSON, OUTPUT_TMP, final)

    by_tier_counts: dict[str, int] = {}
    for s in out_subjects:
        by_tier_counts[s["tier"]] = by_tier_counts.get(s["tier"], 0) + 1

    print(flush=True)
    print("─── Résumé ────────────────────────────────────────────────────────────────────", flush=True)
    print(f"Sujets produits  : {len(out_subjects)}/{len(subjects)}  (échecs : {len(failures)}, warnings : {warnings_count})", flush=True)
    print("Distribution par tier :", flush=True)
    for tier in sorted(by_tier_counts, key=lambda t: -by_tier_counts[t]):
        gen = GEN_PARAMS_BY_TIER[tier]
        print(f"  {tier:<22} : {by_tier_counts[tier]:>3}  "
              f"({gen['width']}×{gen['height']}, batch={gen['batch_size']}, "
              f"neg={'anatomy' if gen['negative_prompt'] else 'none'})", flush=True)
    if failures:
        print(flush=True)
        print("Échecs :", flush=True)
        for f in failures:
            s = f["subject"]
            print(f"  - {s.get('leaf_name_en', '?'):<25} {s.get('name_en', '?'):<30} {s.get('tier', '?'):<18} → {f['error']}", flush=True)
    print(flush=True)
    print(f"Output : {OUTPUT_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
