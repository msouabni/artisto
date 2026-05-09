"""POC-1 : Audit couverture AR taxonomie + qualité suggest_children.

Partie A : statistiques de couverture name_ar dans la table term.
Partie B : test du endpoint /api/ai/suggest-children sur 2 termes feuilles
            choisis comme bonnes ancres AR.

Usage :
    python scripts/poc_taxonomy_ar_coverage.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from api.db import DBConnAdapter, SessionLocal  # noqa: E402
from api.helpers import get_i18n  # noqa: E402

import httpx  # noqa: E402

API_BASE = os.environ.get("ARTISTE_API_BASE", "http://127.0.0.1:8000")
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-taxonomy-ar-coverage.json"


def _row_to_dict(row, keys: list[str]) -> dict:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(zip(keys, row))


def part_a() -> dict:
    session = SessionLocal()
    conn = DBConnAdapter(session)
    try:
        rows = conn.execute(
            "SELECT id, parent_id, vocabulary_id, name_i18n FROM term"
        ).fetchall()
    except Exception as exc:
        conn.close()
        raise RuntimeError(f"Lecture table term : {exc}") from exc

    keys = ["id", "parent_id", "vocabulary_id", "name_i18n"]
    terms: list[dict] = []
    for row in rows:
        d = _row_to_dict(row, keys)
        terms.append(
            {
                "id": str(d["id"]),
                "parent_id": str(d["parent_id"]) if d["parent_id"] else None,
                "vocabulary_id": str(d["vocabulary_id"]) if d["vocabulary_id"] else None,
                "name_fr": get_i18n(d["name_i18n"], "fr"),
                "name_en": get_i18n(d["name_i18n"], "en"),
                "name_ar": get_i18n(d["name_i18n"], "ar"),
            }
        )
    conn.close()

    children_set = {t["parent_id"] for t in terms if t["parent_id"]}
    for t in terms:
        t["is_leaf"] = t["id"] not in children_set

    leaves = [t for t in terms if t["is_leaf"]]
    total = len(terms)
    with_ar = [t for t in terms if t["name_ar"]]
    leaves_with_ar = [t for t in leaves if t["name_ar"]]

    by_vocab: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "with_ar": 0, "leaves": 0, "leaves_with_ar": 0}
    )
    for t in terms:
        v = t["vocabulary_id"] or "<null>"
        by_vocab[v]["total"] += 1
        if t["name_ar"]:
            by_vocab[v]["with_ar"] += 1
        if t["is_leaf"]:
            by_vocab[v]["leaves"] += 1
            if t["name_ar"]:
                by_vocab[v]["leaves_with_ar"] += 1

    def _score(t: dict) -> int:
        words_ar = len((t["name_ar"] or "").split())
        s = 0
        if 1 <= words_ar <= 3:
            s += 10
        if words_ar == 1:
            s += 5
        if t["parent_id"]:
            s += 2
        if t["name_fr"]:
            s += 2
        if t["name_en"]:
            s += 2
        return s

    candidates = [t for t in leaves if t["name_ar"]]
    top_leaves = sorted(candidates, key=lambda t: (-_score(t), t["id"]))[:10]

    return {
        "total_terms": total,
        "terms_with_name_ar": len(with_ar),
        "pct_with_name_ar": round(100 * len(with_ar) / total, 1) if total else 0.0,
        "leaves_total": len(leaves),
        "leaves_with_name_ar": len(leaves_with_ar),
        "pct_leaves_with_name_ar": round(100 * len(leaves_with_ar) / len(leaves), 1)
        if leaves
        else 0.0,
        "by_vocabulary": dict(by_vocab),
        "top_10_leaves": top_leaves,
        "all_terms": terms,
    }


def _extract_suggestions(payload) -> list:
    """Trouve la liste de suggestions dans le résultat du job.

    Format observé pour taxonomy_suggest_children :
        {"artifact_type": "taxonomy_import_ops",
         "proposal": {"operations": [{"op": "add", "value": {...term...}}, ...]}}
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return []
    if not isinstance(payload, dict):
        return []
    proposal = payload.get("proposal")
    if isinstance(proposal, dict):
        ops = proposal.get("operations")
        if isinstance(ops, list):
            return [
                op["value"]
                for op in ops
                if isinstance(op, dict) and op.get("op") == "add" and isinstance(op.get("value"), dict)
            ]
    keys = ("suggestions", "children", "items", "proposed", "data", "results", "new_children", "new_terms")
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list):
            return v
    art = payload.get("artifact")
    if isinstance(art, dict):
        for k in keys:
            v = art.get(k)
            if isinstance(v, list):
                return v
    for v in payload.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and ("name_ar" in v[0] or "name_fr" in v[0]):
            return v
    return []


def part_b(top_leaves: list[dict], existing_terms: list[dict]) -> list[dict]:
    chosen = top_leaves[:2]
    if len(chosen) < 2:
        print(f"  ⚠ seulement {len(chosen)} feuille(s) candidate(s) — partie B partielle")
    existing_fr = {t["name_fr"].lower() for t in existing_terms if t["name_fr"]}
    existing_en = {t["name_en"].lower() for t in existing_terms if t["name_en"]}

    results = []
    for leaf in chosen:
        print(
            f"\n[suggest_children] term_id={leaf['id']!r}  "
            f"vocab={leaf['vocabulary_id']!r}  name_fr={leaf['name_fr']!r}  name_ar={leaf['name_ar']!r}"
        )
        try:
            r = httpx.post(
                f"{API_BASE}/api/ai/suggest-children",
                json={
                    "term_id": leaf["id"],
                    "vocabulary_id": leaf["vocabulary_id"],
                    "count": 5,
                },
                timeout=30.0,
            )
        except Exception as exc:
            results.append({"leaf": leaf, "error": f"POST exception: {type(exc).__name__}: {exc}"})
            continue
        if r.status_code != 202:
            results.append({"leaf": leaf, "error": f"POST {r.status_code}: {r.text[:300]}"})
            continue
        job_data = r.json()
        job_id = job_data.get("job_id") or job_data.get("id")
        print(f"  job_id={job_id} — polling…")

        max_wait = 240
        t0 = time.time()
        result_payload = None
        last_status = None
        while time.time() - t0 < max_wait:
            time.sleep(3)
            try:
                jr = httpx.get(f"{API_BASE}/api/jobs/{job_id}", timeout=10.0)
            except Exception:
                continue
            if jr.status_code != 200:
                continue
            job = jr.json()
            last_status = job.get("status")
            if last_status in ("awaiting_validation", "completed", "succeeded", "done"):
                result_payload = job.get("result")
                break
            if last_status in ("failed", "error", "cancelled", "canceled"):
                results.append(
                    {
                        "leaf": leaf,
                        "job_id": job_id,
                        "error": f"job status={last_status}",
                        "error_message": job.get("error_message"),
                    }
                )
                result_payload = "FAILED"
                break

        if result_payload is None:
            results.append(
                {
                    "leaf": leaf,
                    "job_id": job_id,
                    "error": f"polling timeout {max_wait}s, last_status={last_status}",
                }
            )
            continue
        if result_payload == "FAILED":
            continue

        suggestions = _extract_suggestions(result_payload)
        evals = []
        for s in suggestions:
            if not isinstance(s, dict):
                continue
            ar = (s.get("name_ar") or "").strip()
            fr = (s.get("name_fr") or "").strip()
            en = (s.get("name_en") or "").strip()
            words = ar.split()
            duplicate = (fr.lower() in existing_fr) or (en.lower() in existing_en if en else False)
            evals.append(
                {
                    "id": s.get("id", ""),
                    "name_fr": fr,
                    "name_en": en,
                    "name_ar": ar,
                    "ar_present": bool(ar),
                    "ar_word_count": len(words),
                    "ar_in_1_4_words": 1 <= len(words) <= 4,
                    "duplicate_with_existing": duplicate,
                }
            )
        results.append(
            {
                "leaf": leaf,
                "job_id": job_id,
                "status": last_status,
                "suggestions_count": len(suggestions),
                "suggestions_evaluated": evals,
                "raw_result": result_payload,
            }
        )
        for ev in evals:
            print(
                f"    {ev['id']!r:<28} fr={ev['name_fr']!r:<22} ar={ev['name_ar']!r:<28} "
                f"1-4_mots={ev['ar_in_1_4_words']}  dup={ev['duplicate_with_existing']}"
            )
    return results


def main() -> int:
    print("=" * 90)
    print("POC-1 — Audit couverture AR taxonomie + qualité suggest_children")
    print("=" * 90)

    print("\n[A] Audit taxonomie…")
    a_data = part_a()
    print(f"  total_terms              : {a_data['total_terms']}")
    print(f"  avec name_ar             : {a_data['terms_with_name_ar']} ({a_data['pct_with_name_ar']}%)")
    print(f"  leaves total             : {a_data['leaves_total']}")
    print(f"  leaves avec name_ar      : {a_data['leaves_with_name_ar']} ({a_data['pct_leaves_with_name_ar']}%)")
    print()
    print("Par vocabulaire :")
    for v, stats in sorted(a_data["by_vocabulary"].items(), key=lambda kv: -kv[1]["total"]):
        ar_pct = round(100 * stats["with_ar"] / stats["total"], 1) if stats["total"] else 0
        leaf_ar_pct = round(100 * stats["leaves_with_ar"] / stats["leaves"], 1) if stats["leaves"] else 0
        print(
            f"  {v:<35} total={stats['total']:>4}  ar={stats['with_ar']:>4} ({ar_pct:>5}%)  "
            f"leaves={stats['leaves']:>4} leaves_ar={stats['leaves_with_ar']:>4} ({leaf_ar_pct:>5}%)"
        )
    print()
    print(f"Top {len(a_data['top_10_leaves'])} leaves candidates (ancres AR) :")
    for t in a_data["top_10_leaves"]:
        print(f"  {t['id']:<30} vocab={t['vocabulary_id']:<18} fr={t['name_fr']!r:<22} ar={t['name_ar']!r}")

    print("\n[B] Test suggest_children sur 2 leaves…")
    b_results = part_b(a_data["top_10_leaves"], a_data["all_terms"])

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "poc": "taxonomy-ar-coverage",
        "date": "2026-05-05",
        "api_base": API_BASE,
        "part_a": {
            "total_terms": a_data["total_terms"],
            "terms_with_name_ar": a_data["terms_with_name_ar"],
            "pct_with_name_ar": a_data["pct_with_name_ar"],
            "leaves_total": a_data["leaves_total"],
            "leaves_with_name_ar": a_data["leaves_with_name_ar"],
            "pct_leaves_with_name_ar": a_data["pct_leaves_with_name_ar"],
            "by_vocabulary": a_data["by_vocabulary"],
            "top_10_leaves": a_data["top_10_leaves"],
        },
        "part_b": {
            "tested_count": len(b_results),
            "results": b_results,
        },
    }
    with REPORT_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON brut → {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
