"""POC qwen3.5:4b volume — bench AR sur 50 paires variées pour valider la stabilité
avant promotion comme modèle par défaut prod.

Stratégie :
- Pioche les termes feuilles avec name_ar non vide depuis la base (88 termes au total).
- Sélectionne 50 paires variées en évitant le sur-échantillonnage de chiens
  (cap 3 max par catégorie de prefix).
- concept_en = leaf.name_en (le concept et l'ancre sont identiques — test plus facile
  qu'en POC-4 mais représentatif d'un cas typique en prod).
- Lance qwen3.5:4b avec Prompt A POC-4 (bornes SOFT title [25, 55], desc [40, 100]).

Usage :
    python scripts/poc_qwen35_volume.py
"""
from __future__ import annotations

import io
import json
import statistics
import sys
import time
from collections import Counter
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

from services.ollama_json import (  # noqa: E402
    apply_no_think_system,
    call_ollama_sync,
    parse_json_response,
)
from poc_llm_benchmark_v2 import (  # noqa: E402
    PROMPT_A_TPL,
    TITLE_MIN, TITLE_MAX, DESC_MIN, DESC_MAX,
    _evaluate_ar,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-qwen35-volume.json"
MODEL = "qwen3.5:4b"
TARGET_PAIRS = 50
CALL_TIMEOUT = 180
PER_CATEGORY_CAP = 3


def fetch_leaves_with_ar() -> list[dict]:
    """Tous les termes feuilles avec name_ar non vide."""
    from api.db import DBConnAdapter, SessionLocal
    from api.helpers import get_i18n
    session = SessionLocal()
    conn = DBConnAdapter(session)
    rows = conn.execute("SELECT id, parent_id, name_i18n FROM term").fetchall()
    terms = []
    for r in rows:
        d = dict(r._mapping)
        terms.append({
            "id": str(d["id"]),
            "parent_id": str(d["parent_id"]) if d["parent_id"] else None,
            "name_fr": get_i18n(d["name_i18n"], "fr"),
            "name_en": get_i18n(d["name_i18n"], "en"),
            "name_ar": get_i18n(d["name_i18n"], "ar"),
        })
    conn.close()
    children_set = {t["parent_id"] for t in terms if t["parent_id"]}
    leaves = [t for t in terms if t["id"] not in children_set and t["name_ar"]]
    return leaves


def pick_diverse_pairs(leaves: list[dict], n: int, cap_per_category: int) -> list[dict]:
    """Sélectionne n paires variées en limitant les chiens / catégories sur-représentées."""
    by_cat: dict[str, list[dict]] = {}
    for t in leaves:
        cat = t["id"].split("_")[0]
        # Pour les chiens (cluster sur-représenté), grouper plus fin
        if t["id"].startswith("animaux_domestiques_dogs_"):
            cat = "animaux_domestiques_dogs"
        by_cat.setdefault(cat, []).append(t)

    # Round-robin avec cap par catégorie
    selected: list[dict] = []
    cat_counts: Counter[str] = Counter()
    cats = list(by_cat.keys())
    while len(selected) < n:
        progressed = False
        for cat in cats:
            if cat_counts[cat] >= cap_per_category:
                continue
            pool = by_cat[cat]
            if cat_counts[cat] >= len(pool):
                continue
            selected.append(pool[cat_counts[cat]])
            cat_counts[cat] += 1
            progressed = True
            if len(selected) >= n:
                break
        if not progressed:
            break

    pairs = []
    for t in selected:
        # concept_en = name_en si dispo, sinon fr, sinon id
        concept_en = t["name_en"] or t["name_fr"] or t["id"]
        pairs.append({
            "concept_en": concept_en,
            "term_id": t["id"],
            "term_ar": t["name_ar"],
            "term_en": t["name_en"] or t["name_fr"] or t["id"],
        })
    return pairs


def run_pair(pair: dict, idx: int, total: int) -> dict:
    prompt = PROMPT_A_TPL.format(**pair)
    sys_prompt = apply_no_think_system(MODEL, "")
    t0 = time.time()
    try:
        raw = call_ollama_sync(prompt, sys_prompt, model=MODEL, temperature=0.0, timeout=CALL_TIMEOUT)
    except Exception as exc:
        dt = time.time() - t0
        print(f"  [{idx:>2}/{total}] ERR  {pair['concept_en'][:30]:<30} {type(exc).__name__} ({dt:.1f}s)")
        return {"pair": pair, "error": f"{type(exc).__name__}: {exc}", "latency_s": dt}
    dt = time.time() - t0
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        print(f"  [{idx:>2}/{total}] JSON⚠ {pair['concept_en'][:30]:<30} ({dt:.1f}s)")
        return {"pair": pair, "raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt}
    ev = _evaluate_ar(parsed, pair["term_ar"])
    record = {"pair": pair, "raw": raw, "parsed": parsed, "latency_s": dt, **ev}
    a = "✓" if ev.get("anchor_present") else "✗"
    b = "✓" if ev.get("title_in_bounds") and ev.get("description_in_bounds") else "✗"
    c = "✓" if not ev.get("harakat_anywhere") and not ev.get("latin_anywhere") else "✗"
    print(f"  [{idx:>2}/{total}] {pair['concept_en'][:30]:<30} a={a} b={b} c={c} {dt:.1f}s  title={ev.get('title_len','?')} desc={ev.get('description_len','?')}")
    return record


def aggregate(results: list[dict]) -> dict:
    valid = [r for r in results if r.get("json_ok")]
    n = len(valid)
    if n == 0:
        return {"json_ok": 0, "total": len(results)}
    title_lens = [r["title_len"] for r in valid]
    desc_lens = [r["description_len"] for r in valid]
    card_lens = [r["title_card_len"] for r in valid]
    return {
        "total": len(results),
        "json_ok": n,
        "anchor_present": sum(1 for r in valid if r["anchor_present"]),
        "title_in_bounds": sum(1 for r in valid if r["title_in_bounds"]),
        "title_card_in_bounds": sum(1 for r in valid if r["title_card_in_bounds"]),
        "description_in_bounds": sum(1 for r in valid if r["description_in_bounds"]),
        "keywords_count_ok": sum(1 for r in valid if r["keywords_count_ok"]),
        "harakat_clean": sum(1 for r in valid if not r["harakat_anywhere"]),
        "latin_clean": sum(1 for r in valid if not r["latin_anywhere"]),
        "title_min": min(title_lens),
        "title_max": max(title_lens),
        "title_avg": round(statistics.mean(title_lens), 1),
        "title_median": round(statistics.median(title_lens), 1),
        "description_min": min(desc_lens),
        "description_max": max(desc_lens),
        "description_avg": round(statistics.mean(desc_lens), 1),
        "description_median": round(statistics.median(desc_lens), 1),
        "title_card_min": min(card_lens),
        "title_card_max": max(card_lens),
        "title_card_avg": round(statistics.mean(card_lens), 1),
        "latency_min_s": round(min(r["latency_s"] for r in valid), 2),
        "latency_max_s": round(max(r["latency_s"] for r in valid), 2),
        "latency_avg_s": round(statistics.mean(r["latency_s"] for r in valid), 2),
        "latency_median_s": round(statistics.median(r["latency_s"] for r in valid), 2),
    }


def main() -> int:
    print("=" * 100)
    print(f"POC volume — qwen3.5:4b sur {TARGET_PAIRS} paires AR")
    print("=" * 100)

    print("\n[Préparation paires]")
    leaves = fetch_leaves_with_ar()
    print(f"  Termes feuilles avec name_ar : {len(leaves)}")
    pairs = pick_diverse_pairs(leaves, TARGET_PAIRS, PER_CATEGORY_CAP)
    print(f"  Paires sélectionnées : {len(pairs)} (cap {PER_CATEGORY_CAP}/catégorie)")
    cat_counts = Counter(p["term_id"].split("_")[0] for p in pairs)
    print(f"  Distribution par catégorie : {dict(cat_counts)}")

    print(f"\n[Bench {MODEL} — Prompt A POC-4 — bornes SOFT title [{TITLE_MIN},{TITLE_MAX}] desc [{DESC_MIN},{DESC_MAX}]]")
    results = []
    for i, pair in enumerate(pairs, 1):
        results.append(run_pair(pair, i, len(pairs)))
        # save partial every 10
        if i % 10 == 0:
            agg = aggregate(results)
            print(f"\n  [partial @ {i}] anchor={agg.get('anchor_present',0)}/{agg.get('json_ok',0)} "
                  f"title_b={agg.get('title_in_bounds',0)}/{agg.get('json_ok',0)} "
                  f"desc_b={agg.get('description_in_bounds',0)}/{agg.get('json_ok',0)} "
                  f"clean_har={agg.get('harakat_clean',0)}/{agg.get('json_ok',0)} "
                  f"clean_lat={agg.get('latin_clean',0)}/{agg.get('json_ok',0)}\n")

    agg = aggregate(results)
    print("\n=== Synthèse ===")
    print(f"  JSON parsable        : {agg['json_ok']}/{agg['total']}")
    print(f"  Anchor présent       : {agg['anchor_present']}/{agg['json_ok']}")
    print(f"  title in [{TITLE_MIN},{TITLE_MAX}]   : {agg['title_in_bounds']}/{agg['json_ok']}")
    print(f"  title_card ≤ 25      : {agg['title_card_in_bounds']}/{agg['json_ok']}")
    print(f"  desc  in [{DESC_MIN},{DESC_MAX}]    : {agg['description_in_bounds']}/{agg['json_ok']}")
    print(f"  keywords = 5         : {agg['keywords_count_ok']}/{agg['json_ok']}")
    print(f"  Harakat clean        : {agg['harakat_clean']}/{agg['json_ok']}")
    print(f"  Latin clean          : {agg['latin_clean']}/{agg['json_ok']}")
    print(f"  Latence min/avg/max  : {agg['latency_min_s']} / {agg['latency_avg_s']} / {agg['latency_max_s']} s")
    print(f"  Title len min/avg/median/max : {agg['title_min']} / {agg['title_avg']} / {agg['title_median']} / {agg['title_max']}")
    print(f"  Desc  len min/avg/median/max : {agg['description_min']} / {agg['description_avg']} / {agg['description_median']} / {agg['description_max']}")

    payload = {
        "poc": "qwen35-volume",
        "date": "2026-05-05",
        "model": MODEL,
        "target_pairs": TARGET_PAIRS,
        "actual_pairs": len(pairs),
        "ar_bounds": {"title": [TITLE_MIN, TITLE_MAX], "description": [DESC_MIN, DESC_MAX]},
        "category_distribution": dict(cat_counts),
        "pairs": pairs,
        "results": results,
        "summary": agg,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
