"""POC v2 jetable : compare 2 prompts (A=structure stricte, B=few-shot example)
pour la génération de contenu AR sur 10 concepts EN.

Usage :
    python scripts/poc_ar_content_prompts_v2.py
"""
from __future__ import annotations

import io
import json
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

from services.ollama_json import (  # noqa: E402
    OLLAMA_MODEL,
    call_ollama_sync,
    parse_json_response,
)

CONCEPTS = [
    "lion in the savanna",
    "cat in a library",
    "colorful butterfly",
    "elephant with its babies",
    "fish in the ocean",
    "fox in the forest",
    "white rabbit",
    "bird on a branch",
    "turtle on a rock",
    "jumping dolphin",
]

PROMPT_A = """You generate editorial content in Arabic for a children's coloring website (ages 4-10).
Target audience: young children. Use simple, clear, modern Arabic. No vowel diacritics. No Latin characters.

Concept: "{concept}"

Generate JSON only:
{{
  "title": "Arabic title between 40 and 60 characters",
  "title_card": "Short Arabic title, maximum 30 characters",
  "description": "Arabic description in plain prose, between 80 and 130 characters, no markdown",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}}"""

PROMPT_B = """You generate Arabic content for a children's coloring website. Simple Arabic for ages 4-10. No diacritics. No Latin.

Example for "lion in the savanna":
{{
  "title": "استمتع برسم أسد يمشي في السافانا الجميلة مع أشجارها",
  "title_card": "الأسد في السافانا",
  "description": "أسد قوي يتجول في السافانا بين الأشجار الطويلة تحت الشمس الدافئة، رائع للتلوين",
  "keywords": ["تلوين أسد", "حيوانات أفريقيا", "السافانا"]
}}

Now generate for: "{concept}\""""

HARAKAT = set("ًٌٍَُِّْٰ")
LATIN_RE = re.compile(r"[A-Za-z]")


def _has_harakat(text: str) -> bool:
    return any(c in HARAKAT for c in text or "")


def _has_latin(text: str) -> bool:
    return bool(LATIN_RE.search(text or ""))


def _measure(parsed) -> dict:
    if not isinstance(parsed, dict):
        return {}
    title = parsed.get("title", "") or ""
    card = parsed.get("title_card", "") or ""
    desc = parsed.get("description", "") or ""
    kw = parsed.get("keywords", []) or []
    kw_strs = [k for k in kw if isinstance(k, str)] if isinstance(kw, list) else []
    return {
        "title_len": len(title),
        "title_in_bounds": 40 <= len(title) <= 60,
        "title_card_len": len(card),
        "title_card_in_bounds": len(card) <= 30,
        "description_len": len(desc),
        "description_in_bounds": 80 <= len(desc) <= 130,
        "keywords_count": len(kw_strs),
        "harakat_anywhere": (_has_harakat(title) or _has_harakat(card)
                             or _has_harakat(desc) or any(_has_harakat(k) for k in kw_strs)),
        "latin_anywhere": (_has_latin(title) or _has_latin(card)
                           or _has_latin(desc) or any(_has_latin(k) for k in kw_strs)),
    }


def run_one(prompt_template: str, concept: str) -> dict:
    prompt = prompt_template.format(concept=concept)
    t0 = time.time()
    try:
        raw = call_ollama_sync(prompt=prompt, system="", temperature=0.0)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}
    dt = time.time() - t0
    try:
        parsed = parse_json_response(raw)
        json_ok = isinstance(parsed, dict)
    except Exception as exc:
        return {"raw": raw, "json_ok": False, "json_error": f"{type(exc).__name__}: {exc}", "latency_s": dt}
    measures = _measure(parsed) if json_ok else {}
    return {"raw": raw, "parsed": parsed if json_ok else None, "json_ok": json_ok, "latency_s": dt, **measures}


def main() -> int:
    print(f"Modèle : {OLLAMA_MODEL}  ·  T=0  ·  {len(CONCEPTS)} concepts × 2 prompts\n")

    all_results: list[dict] = []
    for idx, concept in enumerate(CONCEPTS, 1):
        print(f"\n{'=' * 100}")
        print(f"[{idx}/{len(CONCEPTS)}] CONCEPT : {concept}")
        print("=" * 100)

        record: dict = {"concept": concept, "id": idx}
        for label, prompt in [("A", PROMPT_A), ("B", PROMPT_B)]:
            print(f"\n--- Prompt {label} ---")
            result = run_one(prompt, concept)
            record[f"prompt_{label.lower()}"] = result
            if "error" in result:
                print(f"  ERREUR : {result['error']}")
                continue
            if not result.get("json_ok"):
                print(f"  JSON KO : {result.get('json_error')}")
                print(f"  RAW (300 chars) : {(result.get('raw') or '')[:300]}")
                continue
            p = result["parsed"]
            print(f"  title       ({result['title_len']:>3} chars, in_bounds={result['title_in_bounds']}) : {p.get('title')}")
            print(f"  title_card  ({result['title_card_len']:>3} chars, in_bounds={result['title_card_in_bounds']}) : {p.get('title_card')}")
            print(f"  description ({result['description_len']:>3} chars, in_bounds={result['description_in_bounds']}) : {p.get('description')}")
            print(f"  keywords    ({result['keywords_count']} items) : {p.get('keywords')}")
            print(f"  flags       : harakat={result['harakat_anywhere']}  latin={result['latin_anywhere']}  latency={result['latency_s']:.1f}s")
        all_results.append(record)

    # Synthèse
    print(f"\n{'=' * 100}\nSYNTHÈSE\n{'=' * 100}")
    summaries: dict = {}
    for label in ("A", "B"):
        key = f"prompt_{label.lower()}"
        valid = [r[key] for r in all_results if r.get(key, {}).get("json_ok")]
        n = len(valid)
        title_ok = sum(1 for r in valid if r["title_in_bounds"])
        card_ok = sum(1 for r in valid if r["title_card_in_bounds"])
        desc_ok = sum(1 for r in valid if r["description_in_bounds"])
        harakat = sum(1 for r in valid if r["harakat_anywhere"])
        latin = sum(1 for r in valid if r["latin_anywhere"])
        latencies = [r["latency_s"] for r in valid]
        avg_lat = sum(latencies) / n if n else 0
        summaries[label] = {
            "json_ok": n,
            "title_in_bounds": title_ok,
            "title_card_in_bounds": card_ok,
            "description_in_bounds": desc_ok,
            "harakat": harakat,
            "latin": latin,
            "avg_latency_s": round(avg_lat, 2),
        }
        print(f"\nPrompt {label} : {n}/{len(CONCEPTS)} JSON parsable")
        print(f"  title in [40,60]        : {title_ok}/{n}")
        print(f"  title_card ≤ 30         : {card_ok}/{n}")
        print(f"  description in [80,130] : {desc_ok}/{n}")
        print(f"  harakat présent         : {harakat}/{n}")
        print(f"  latin présent           : {latin}/{n}")
        print(f"  avg latency             : {avg_lat:.1f}s")

    # Export raw JSON pour rapport
    out_path = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-ar-content-prompts-v2.json"
    payload = {
        "poc": "ar-content-prompts-v2",
        "date": "2026-05-05",
        "model": OLLAMA_MODEL,
        "temperature": 0.0,
        "concepts_count": len(CONCEPTS),
        "concepts": CONCEPTS,
        "prompt_a": PROMPT_A,
        "prompt_b": PROMPT_B,
        "summary": summaries,
        "results": all_results,
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nJSON brut → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
