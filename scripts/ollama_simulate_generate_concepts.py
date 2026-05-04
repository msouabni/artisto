"""Simule /api/generate comme generate_concepts (affiche réponse brute)."""
import json
import os
import sys
import time

import httpx

BASE = os.environ.get("OLLAMA_BASE_URL", "http://100.65.24.35:11434").rstrip("/")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

SYSTEM = """You are a content expert for children's coloring websites.
Your role: produce a list of CONCEPTS (sub-themes, precise image ideas) from a general theme.
These concepts will be used to generate Z-Image-Turbo prompts later.
Criteria for a good concept:
- Visual and concrete: must be drawable in line art (simple outlines)
- Popular with children (known characters, animals, nature, holidays, etc.)
- Age-appropriate (avoid violence, adult content)
- Distinct from other concepts in the list (no near-duplicates)
- SEO: short English slug, natural descriptions that include the word "coloring"
Z-IMAGE ALIGNMENT (MANDATORY):
- name_en MUST be a SCENE TITLE that contains BOTH a clear SUBJECT and a clear SETTING.
- Prefer the pattern: "<Subject> in <Setting>" (or on/at/under/inside/near).
- Avoid vague titles without a setting (e.g. "Cute Cat").
Examples of GOOD scene titles: "Cat in a Library", "Dinosaur in a Jungle", "Tractor on a Farm"
Examples of BAD titles: "Cute Cat", "Freedom", "Joy", "Nature Philosophy"
IMPORTANT: Reply ONLY with the requested JSON. No thinking, no markdown. Raw JSON only."""

TAXONOMY = """Taxonomy context (anchor) — parent term and existing children:
[
  {"id": "cartoons_disney", "name_en": "Disney Characters", "name_fr": "Personnages Disney"}
]"""

USER = f"""Theme: Disney Characters
{TAXONOMY}

Generate exactly 10 concepts (precise, drawable image ideas) for this theme.
For each concept, provide:
- id : snake_case unique identifier (e.g. animals_sitting_cat, vehicles_farm_tractor)
- slug : kebab-case URL slug in English, short (2-4 words)
- name_en : English SCENE TITLE that explicitly includes SUBJECT + SETTING (prefer "X in Y"), 3-8 words
- name_fr : French name, short (2-5 words), natural
- description_en : 15-25 words, SEO-friendly, mention "coloring"
- description_fr : 15-25 words, SEO-friendly, mention "coloriage" or "colorier"
- weight : display order (0, 1, 2...)

Expected JSON array format:
[
  {{"id": "animals_sitting_cat", "slug": "sitting-cat", "name_en": "Cute Sitting Cat", "name_fr": "Chat assis mignon",
    "description_en": "Cute sitting cat coloring page, ideal for young children to color.", "description_fr": "Coloriage d'un chat assis souriant, parfait pour les enfants.", "weight": 0}},
  ...
]"""


def main() -> None:
    payload = {
        "model": MODEL,
        "prompt": USER,
        "system": SYSTEM,
        "stream": False,
        "options": {"temperature": 0.5},
    }
    print(f"POST {BASE}/api/generate model={MODEL}", flush=True)
    t0 = time.perf_counter()
    r = httpx.post(f"{BASE}/api/generate", json=payload, timeout=400.0)
    dt = time.perf_counter() - t0
    print(f"HTTP {r.status_code} elapsed_s={dt:.2f}\n", flush=True)
    data = r.json()
    if data.get("error"):
        print("OLLAMA ERROR:", data["error"], flush=True)
        return
    raw = data.get("response", "")
    print("=== TEXTE BRUT (response) ===", flush=True)
    print(raw, flush=True)
    print("\n=== TENTATIVE JSON pretty ===", flush=True)
    text = raw.strip()
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: -3].strip()
    try:
        parsed = json.loads(text)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        print("Parse JSON échoué:", e, flush=True)


if __name__ == "__main__":
    main()
