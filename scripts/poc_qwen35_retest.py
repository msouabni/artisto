"""POC qwen3.5 retest — vérifier que le fix `think: false` natif Ollama débloque
les modèles qwen3.5:9b et qwen3.5:4b qui timeoutent en POC-LLM-v2.

Réutilise les 10 paires AR (Prompt A POC-4) + 5 termes feuilles (suggest_children)
du POC-LLM-v2 pour comparaison directe. Logge la sortie brute pour détecter
d'éventuelles balises <think>…</think> résiduelles.

Usage :
    python scripts/poc_qwen35_retest.py
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
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import httpx  # noqa: E402

from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    apply_no_think_system,
    _supports_native_think_disable,
    call_ollama_sync,
    parse_json_response,
)
from poc_llm_benchmark_v2 import (  # noqa: E402
    PAIRS_AR,
    PROMPT_A_TPL,
    LEAF_TERMS,
    TITLE_MIN, TITLE_MAX, DESC_MIN, DESC_MAX,
    HARAKAT_RE, LATIN_RE,
    _evaluate_ar,
    aggregate_ar, aggregate_concepts,
    evaluate_concepts, fetch_existing_terms,
    load_suggest_children_template,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-qwen35-retest.json"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-qwen35-retest.md"

MODELS_RETEST = ["qwen3.5:9b", "qwen3.5:4b"]
CALL_TIMEOUT = 180  # marge supplémentaire vs v2 (120s)

THINK_TAG_RE = re.compile(r"<think\b[^>]*>([\s\S]*?)</think>", re.IGNORECASE)


def _has_think_tag(raw: str) -> tuple[bool, int]:
    """Détecte balises <think>...</think> et compte les caractères inclus."""
    matches = THINK_TAG_RE.findall(raw or "")
    if not matches:
        return False, 0
    return True, sum(len(m) for m in matches)


def benchmark_ar(model: str) -> list[dict]:
    print(f"\n--- AR benchmark on {model} ({len(PAIRS_AR)} paires, timeout {CALL_TIMEOUT}s) ---")
    out = []
    for idx, pair in enumerate(PAIRS_AR, 1):
        prompt = PROMPT_A_TPL.format(**pair)
        sys_prompt = apply_no_think_system(model, "")
        t0 = time.time()
        try:
            raw = call_ollama_sync(prompt, sys_prompt, model=model, temperature=0.0, timeout=CALL_TIMEOUT)
        except Exception as exc:
            dt = time.time() - t0
            out.append({"pair": pair, "error": f"{type(exc).__name__}: {exc}", "latency_s": dt})
            print(f"  [{idx:>2}] ERR  {pair['concept_en'][:30]:<30} {type(exc).__name__} ({dt:.1f}s)")
            continue
        dt = time.time() - t0
        has_think, think_chars = _has_think_tag(raw)
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            out.append({
                "pair": pair, "raw": raw, "json_ok": False, "json_error": str(exc),
                "latency_s": dt, "has_think_tag": has_think, "think_tag_chars": think_chars,
            })
            print(f"  [{idx:>2}] JSON⚠ {pair['concept_en'][:30]:<30} ({dt:.1f}s)  think={has_think}")
            continue
        ev = _evaluate_ar(parsed, pair["term_ar"])
        out.append({
            "pair": pair, "raw": raw, "parsed": parsed, "latency_s": dt,
            "has_think_tag": has_think, "think_tag_chars": think_chars, **ev,
        })
        anchor = "✓" if ev.get("anchor_present") else "✗"
        bounds = "✓" if ev.get("title_in_bounds") and ev.get("description_in_bounds") else "✗"
        clean = "✓" if not ev.get("harakat_anywhere") and not ev.get("latin_anywhere") else "✗"
        think_flag = "T" if has_think else "·"
        print(f"  [{idx:>2}] {pair['concept_en'][:30]:<30} a={anchor} b={bounds} c={clean} [{think_flag}] {dt:.1f}s")
    return out


def benchmark_concepts(model: str, template: dict) -> list[dict]:
    print(f"\n--- Concepts benchmark on {model} ({len(LEAF_TERMS)} termes) ---")
    out = []
    for leaf in LEAF_TERMS:
        sys_prompt = apply_no_think_system(model, template["system"])
        user_prompt = template["user"].format(
            parent_name_en=leaf["name_en"], parent_name_fr=leaf["name_fr"],
            parent_id=leaf["id"], vocabulary_id="themes",
            existing_context="No children exist yet for this parent. Feel free to generate the most relevant terms.",
            count=5,
        )
        t0 = time.time()
        try:
            raw = call_ollama_sync(user_prompt, sys_prompt, model=model, temperature=0.5, timeout=CALL_TIMEOUT)
        except Exception as exc:
            dt = time.time() - t0
            out.append({"leaf": leaf, "error": f"{type(exc).__name__}: {exc}", "latency_s": dt})
            print(f"  {leaf['id']:<22} ERR  {type(exc).__name__} ({dt:.1f}s)")
            continue
        dt = time.time() - t0
        has_think, think_chars = _has_think_tag(raw)
        try:
            parsed = parse_json_response(raw)
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
        except Exception as exc:
            out.append({
                "leaf": leaf, "raw": raw, "json_ok": False, "json_error": str(exc),
                "latency_s": dt, "has_think_tag": has_think, "think_tag_chars": think_chars,
            })
            print(f"  {leaf['id']:<22} JSON⚠ ({dt:.1f}s)  think={has_think}")
            continue
        children = parsed if isinstance(parsed, list) else []
        out.append({
            "leaf": leaf, "raw": raw, "json_ok": True, "children": children,
            "latency_s": dt, "has_think_tag": has_think, "think_tag_chars": think_chars,
        })
        think_flag = "T" if has_think else "·"
        print(f"  {leaf['id']:<22} {len(children)} children [{think_flag}]  {dt:.1f}s")
    return out


def think_summary(results: list[dict]) -> dict:
    n_total = len(results)
    n_with_think = sum(1 for r in results if r.get("has_think_tag"))
    chars = [r.get("think_tag_chars", 0) for r in results if r.get("has_think_tag")]
    return {
        "calls_total": n_total,
        "calls_with_think_tag": n_with_think,
        "avg_think_tag_chars": round(sum(chars) / len(chars), 1) if chars else 0,
        "max_think_tag_chars": max(chars) if chars else 0,
    }


def main() -> int:
    print("=" * 100)
    print("POC qwen3.5 retest — fix `think: false` natif Ollama")
    print("=" * 100)

    # Vérifier que les 2 modèles répondent à un ping rapide
    print(f"\n[Pre-flight ping 30s]")
    payload_ping = {"prompt": "Reply with the single word: pong", "stream": False, "options": {"temperature": 0.0}}
    for m in MODELS_RETEST:
        sys_p = apply_no_think_system(m, "")
        body = {"model": m, "system": sys_p, **payload_ping}
        if _supports_native_think_disable(m):
            body["think"] = False
        t0 = time.time()
        try:
            with httpx.Client(timeout=30.0) as c:
                r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=body)
                r.raise_for_status()
            dt = time.time() - t0
            resp = (r.json().get("response") or "")[:60].replace("\n", " ")
            print(f"  ✓ {m:<22} {dt:.1f}s  → {resp!r}")
        except Exception as exc:
            dt = time.time() - t0
            print(f"  ✗ {m:<22} {dt:.1f}s  {type(exc).__name__}: {exc}")

    suggest_tpl = load_suggest_children_template()
    existing_terms = fetch_existing_terms()
    print(f"\n  {len(existing_terms)} termes existants chargés (dédup)")

    bench: dict = {}

    def _save() -> None:
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "poc": "qwen35-retest",
            "date": "2026-05-05",
            "models_tested": MODELS_RETEST,
            "ollama_base_url": OLLAMA_BASE_URL,
            "fix_applied": "src/services/ollama_json.py: apply_no_think_system limité à qwen3: strict ; payload['think']=False ajouté pour qwen3.5+",
            "ar_pairs": PAIRS_AR,
            "leaf_terms": LEAF_TERMS,
            "ar_bounds": {"title": [TITLE_MIN, TITLE_MAX], "description": [DESC_MIN, DESC_MAX]},
            "call_timeout_s": CALL_TIMEOUT,
            "results_by_model": bench,
        }
        REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    for model_name in MODELS_RETEST:
        print(f"\n{'=' * 100}\n>>> {model_name}\n{'=' * 100}")
        ar_results = benchmark_ar(model_name)
        ar_agg = aggregate_ar(ar_results, len(PAIRS_AR))
        concepts_results = benchmark_concepts(model_name, suggest_tpl)
        concepts_results = evaluate_concepts(concepts_results, existing_terms)
        concepts_agg = aggregate_concepts(concepts_results, len(LEAF_TERMS))
        ar_think = think_summary(ar_results)
        concepts_think = think_summary(concepts_results)
        bench[model_name] = {
            "ar_results": ar_results, "ar_agg": ar_agg,
            "concepts_results": concepts_results, "concepts_agg": concepts_agg,
            "ar_think": ar_think, "concepts_think": concepts_think,
        }
        print(f"\n  Synthèse {model_name} :")
        print(f"    AR     : json={ar_agg.get('json_ok',0)}/{ar_agg.get('total',0)} "
              f"anchor={ar_agg.get('anchor_present',0)}/{ar_agg.get('total',0)} "
              f"title_b={ar_agg.get('title_in_bounds',0)}/{ar_agg.get('total',0)} "
              f"desc_b={ar_agg.get('description_in_bounds',0)}/{ar_agg.get('total',0)} "
              f"harakat={ar_agg.get('harakat_clean',0)}/{ar_agg.get('total',0)} "
              f"latin={ar_agg.get('latin_clean',0)}/{ar_agg.get('total',0)} "
              f"lat={ar_agg.get('avg_latency_s','?')}s")
        print(f"    Concepts: json={concepts_agg.get('json_ok',0)}/{concepts_agg.get('total_terms',0)} "
              f"children={concepts_agg.get('total_children_generated',0)} "
              f"ar_ok={concepts_agg.get('ar_present_and_short',0)} "
              f"suspect={concepts_agg.get('cross_locale_suspect',0)} "
              f"dup={concepts_agg.get('duplicates_with_existing',0)} "
              f"lat={concepts_agg.get('avg_latency_s','?')}s")
        print(f"    Think  : AR {ar_think['calls_with_think_tag']}/{ar_think['calls_total']} balises "
              f"({ar_think['avg_think_tag_chars']:.0f} chars avg)  "
              f"Concepts {concepts_think['calls_with_think_tag']}/{concepts_think['calls_total']} balises")
        _save()

    print(f"\nJSON brut → {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
