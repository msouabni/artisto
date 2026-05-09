"""POC-LLM : benchmark comparatif des modèles Ollama disponibles.

Étapes :
0. Inventaire des modèles via /api/tags (skip llava).
1. Tâche AR : Prompt A du POC-4 sur 10 paires (concept_en, term_ar, term_en).
2. Tâche concepts : prompt suggest_children sur 5 termes feuilles variés.
3. Synthèse + score composite + classement.

Usage :
    python scripts/poc_llm_benchmark.py
"""
from __future__ import annotations

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
import yaml  # noqa: E402

from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    call_ollama_sync,
    parse_json_response,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-llm-benchmark.json"
TAXONOMY_PROMPTS = PROJECT_ROOT / "prompts" / "taxonomy_prompts.yaml"

PAIRS_AR = [
    {"concept_en": "elephant in the savanna",       "term_id": "animaux_sauvages",
     "term_ar": "حيوانات برية",       "term_en": "Wild animals"},
    {"concept_en": "jumping dolphin",                "term_id": "animaux_marins",
     "term_ar": "حيوانات بحرية",      "term_en": "Sea animals"},
    {"concept_en": "cow grazing in the field",       "term_id": "animaux_ferme",
     "term_ar": "حيوانات المزرعة",    "term_en": "Farm animals"},
    {"concept_en": "kitten playing with a ball",     "term_id": "animaux_domestiques_cats_kittens",
     "term_ar": "القطط في اللعب",     "term_en": "Kittens Playtime"},
    {"concept_en": "decorated Christmas tree",        "term_id": "noel",
     "term_ar": "عيد الميلاد",        "term_en": "Christmas"},
    {"concept_en": "Easter eggs in a basket",         "term_id": "paques",
     "term_ar": "عيد الفصح",          "term_en": "Easter"},
    {"concept_en": "Halloween pumpkin with a smile",  "term_id": "halloween",
     "term_ar": "هالووين",            "term_en": "Halloween"},
    {"concept_en": "complex flower mandala",          "term_id": "mandalas_fleurs",
     "term_ar": "مندالات الزهور",     "term_en": "Flower mandalas"},
    {"concept_en": "snowy mountains scene",           "term_id": "hiver",
     "term_ar": "الشتاء",             "term_en": "Winter"},
    {"concept_en": "racing car on a track",           "term_id": "voitures",
     "term_ar": "السيارات",           "term_en": "Cars"},
]

PROMPT_A_TPL = """Le sujet de l'image est : "{concept_en}".
Le thème principal en arabe est : {term_ar} ({term_en}).

Génère le contenu éditorial en arabe standard (fusha/MSA) pour cette page de coloriage.

Règles strictes :
- Pas de harakat (signes diacritiques)
- Pas de caractères latins
- Arabe standard uniquement, pas de dialecte

Retourne UNIQUEMENT un JSON valide avec ces champs :
{{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "...", "...", "...", "..."]}}

Contraintes de longueur :
- title : 30 à 50 caractères
- title_card : 25 caractères maximum
- description : 55 à 90 caractères
- keywords : exactement 5 mots-clés"""

# Bornes ajustées pour benchmark (cf. recommandation POC-4 : élargir AR)
TITLE_MIN, TITLE_MAX = 25, 55
DESC_MIN, DESC_MAX = 40, 100

LEAF_TERMS = [
    {"id": "animaux_marins",   "name_fr": "Animaux marins",   "name_en": "Sea animals"},
    {"id": "noel",              "name_fr": "Noël",             "name_en": "Christmas"},
    {"id": "mandalas_fleurs",   "name_fr": "Mandalas fleurs",  "name_en": "Flower mandalas"},
    {"id": "voitures",          "name_fr": "Voitures",         "name_en": "Cars"},
    {"id": "science",           "name_fr": "Science",          "name_en": "Science"},
]

HARAKAT_RE = re.compile("[\u0610-\u061A\u064B-\u065F]")
LATIN_RE = re.compile(r"[a-zA-Z]")
AL_PREFIX_RE = re.compile(r"^(ال|وال|فال|بال|كال|لل)")


def _normalize_for_anchor(s: str) -> str:
    return HARAKAT_RE.sub("", (s or "").replace("ـ", "")).strip()


def _anchor_present(term_ar: str, *texts: str) -> dict:
    haystack = " ".join(_normalize_for_anchor(t) for t in texts if t)
    needle = _normalize_for_anchor(term_ar)
    if not needle or not haystack:
        return {"present": False, "match_kind": "no_data"}
    if needle in haystack:
        return {"present": True, "match_kind": "exact"}
    bare = AL_PREFIX_RE.sub("", needle).strip()
    if bare and bare in haystack:
        return {"present": True, "match_kind": "no_article"}
    for token in needle.split():
        token_bare = AL_PREFIX_RE.sub("", token).strip()
        if len(token_bare) >= 3 and token_bare in haystack:
            return {"present": True, "match_kind": "token_match"}
    if len(bare) >= 4 and bare[:4] in haystack:
        return {"present": True, "match_kind": "prefix_4"}
    return {"present": False, "match_kind": "absent"}


def _has_harakat(*texts: str) -> bool:
    return any(HARAKAT_RE.search(t or "") for t in texts)


def _has_latin(*texts: str) -> bool:
    return any(LATIN_RE.search(t or "") for t in texts)


def _evaluate_ar(parsed, term_ar: str) -> dict:
    if not isinstance(parsed, dict):
        return {"json_ok": False}
    title = (parsed.get("title") or "").strip()
    card = (parsed.get("title_card") or "").strip()
    desc = (parsed.get("description") or "").strip()
    kw = parsed.get("keywords") or []
    kw_strs = [k for k in kw if isinstance(k, str)] if isinstance(kw, list) else []
    anchor = _anchor_present(term_ar, title, desc)
    fields = [title, card, desc, *kw_strs]
    return {
        "json_ok": True,
        "title": title,
        "title_card": card,
        "description": desc,
        "keywords": kw_strs,
        "title_len": len(title),
        "title_in_bounds": TITLE_MIN <= len(title) <= TITLE_MAX,
        "title_card_len": len(card),
        "title_card_in_bounds": len(card) <= 25,
        "description_len": len(desc),
        "description_in_bounds": DESC_MIN <= len(desc) <= DESC_MAX,
        "keywords_count": len(kw_strs),
        "keywords_count_ok": len(kw_strs) == 5,
        "anchor_present": anchor["present"],
        "anchor_match_kind": anchor.get("match_kind"),
        "harakat_anywhere": _has_harakat(*fields),
        "latin_anywhere": _has_latin(*fields),
    }


def list_models() -> tuple[list[dict], list[dict]]:
    r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=15.0)
    r.raise_for_status()
    all_models = r.json().get("models", [])
    text = [m for m in all_models if "llava" not in (m.get("name") or "").lower()]
    return all_models, text


def benchmark_ar(model: str) -> list[dict]:
    print(f"\n  --- AR benchmark sur {model} ({len(PAIRS_AR)} paires) ---")
    out = []
    for idx, pair in enumerate(PAIRS_AR, 1):
        prompt = PROMPT_A_TPL.format(**pair)
        t0 = time.time()
        try:
            raw = call_ollama_sync(prompt, "", model=model, temperature=0.0, timeout=180)
        except Exception as exc:
            dt = time.time() - t0
            out.append({"pair": pair, "error": f"{type(exc).__name__}: {exc}", "latency_s": dt})
            print(f"    [{idx}] ❌ {pair['concept_en'][:25]:<25} {type(exc).__name__}")
            continue
        dt = time.time() - t0
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            out.append({"pair": pair, "raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt})
            print(f"    [{idx}] ⚠ {pair['concept_en'][:25]:<25} JSON KO ({dt:.1f}s)")
            continue
        ev = _evaluate_ar(parsed, pair["term_ar"])
        out.append({"pair": pair, "raw": raw, "parsed": parsed, "latency_s": dt, **ev})
        anchor_flag = "✓" if ev.get("anchor_present") else "✗"
        bounds_flag = "✓" if ev.get("title_in_bounds") and ev.get("description_in_bounds") else "✗"
        clean_flag = "✓" if not ev.get("harakat_anywhere") and not ev.get("latin_anywhere") else "✗"
        print(f"    [{idx}] {pair['concept_en'][:25]:<25} anchor={anchor_flag} bounds={bounds_flag} clean={clean_flag} {dt:.1f}s")
    return out


def aggregate_ar(results: list[dict], n_total: int) -> dict:
    valid = [r for r in results if r.get("json_ok")]
    if not valid:
        return {"json_ok": 0, "total": n_total}
    return {
        "total": n_total,
        "json_ok": len(valid),
        "anchor_present": sum(1 for r in valid if r["anchor_present"]),
        "title_in_bounds": sum(1 for r in valid if r["title_in_bounds"]),
        "title_card_in_bounds": sum(1 for r in valid if r["title_card_in_bounds"]),
        "description_in_bounds": sum(1 for r in valid if r["description_in_bounds"]),
        "keywords_count_ok": sum(1 for r in valid if r["keywords_count_ok"]),
        "harakat_clean": sum(1 for r in valid if not r["harakat_anywhere"]),
        "latin_clean": sum(1 for r in valid if not r["latin_anywhere"]),
        "avg_latency_s": round(sum(r["latency_s"] for r in valid) / len(valid), 2),
    }


def load_suggest_children_template() -> dict:
    data = yaml.safe_load(TAXONOMY_PROMPTS.read_text(encoding="utf-8"))
    return data["prompts"]["suggest_children"]


def benchmark_concepts(model: str, template: dict, leaves: list[dict]) -> list[dict]:
    print(f"\n  --- Concepts benchmark sur {model} ({len(leaves)} termes) ---")
    out = []
    for leaf in leaves:
        sys_prompt = template["system"]
        user_prompt = template["user"].format(
            parent_name_en=leaf["name_en"],
            parent_name_fr=leaf["name_fr"],
            parent_id=leaf["id"],
            vocabulary_id="themes",
            existing_context="No children exist yet for this parent. Feel free to generate the most relevant terms.",
            count=5,
        )
        t0 = time.time()
        try:
            raw = call_ollama_sync(user_prompt, sys_prompt, model=model, temperature=0.5, timeout=180)
        except Exception as exc:
            dt = time.time() - t0
            out.append({"leaf": leaf, "error": f"{type(exc).__name__}: {exc}", "latency_s": dt})
            print(f"    {leaf['id']:<22} ❌ {type(exc).__name__}")
            continue
        dt = time.time() - t0
        try:
            parsed = parse_json_response(raw)
            if isinstance(parsed, dict):
                # Sometimes wrapped — flatten
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
        except Exception as exc:
            out.append({"leaf": leaf, "raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt})
            print(f"    {leaf['id']:<22} ⚠ JSON KO ({dt:.1f}s)")
            continue
        children = parsed if isinstance(parsed, list) else []
        out.append({"leaf": leaf, "raw": raw, "json_ok": True, "children": children, "latency_s": dt})
        print(f"    {leaf['id']:<22} {len(children)} children  {dt:.1f}s")
    return out


def evaluate_concepts(results: list[dict], existing_terms: dict) -> list[dict]:
    """Add per-child evaluation : ar_present, cross_locale_flag, duplicate."""
    existing_fr = {t["name_fr"].lower() for t in existing_terms if t.get("name_fr")}
    existing_en = {t["name_en"].lower() for t in existing_terms if t.get("name_en")}
    existing_id = {t["id"] for t in existing_terms}
    for r in results:
        if not r.get("json_ok"):
            continue
        evs = []
        for c in r.get("children", []):
            if not isinstance(c, dict):
                continue
            ar = (c.get("name_ar") or "").strip()
            fr = (c.get("name_fr") or "").strip()
            en = (c.get("name_en") or "").strip()
            cid = str(c.get("id") or "").strip()
            ar_ok = bool(ar) and 1 <= len(ar.split()) <= 4
            # Cross-locale heuristic flag : suspect if word counts differ ≥3, or fr==en, or one missing
            wc_fr = len(fr.split())
            wc_en = len(en.split())
            same = (fr.lower() == en.lower() and fr != "")
            wc_diff = abs(wc_fr - wc_en) >= 3
            missing = not fr or not en
            cross_locale_flag = same or wc_diff or missing
            duplicate = (
                cid in existing_id
                or fr.lower() in existing_fr
                or (en.lower() in existing_en if en else False)
            )
            evs.append({
                "id": cid,
                "name_fr": fr,
                "name_en": en,
                "name_ar": ar,
                "ar_ok": ar_ok,
                "cross_locale_suspect": cross_locale_flag,
                "duplicate": duplicate,
            })
        r["children_evaluated"] = evs
    return results


def aggregate_concepts(results: list[dict], n_terms: int) -> dict:
    valid = [r for r in results if r.get("json_ok")]
    total_children = 0
    ar_ok = 0
    suspect = 0
    duplicates = 0
    for r in valid:
        evs = r.get("children_evaluated", [])
        total_children += len(evs)
        ar_ok += sum(1 for e in evs if e["ar_ok"])
        suspect += sum(1 for e in evs if e["cross_locale_suspect"])
        duplicates += sum(1 for e in evs if e["duplicate"])
    avg_lat = sum(r["latency_s"] for r in valid) / len(valid) if valid else 0
    return {
        "total_terms": n_terms,
        "json_ok": len(valid),
        "total_children_generated": total_children,
        "ar_present_and_short": ar_ok,
        "cross_locale_suspect": suspect,
        "duplicates_with_existing": duplicates,
        "avg_latency_s": round(avg_lat, 2),
    }


def composite_score(ar_agg: dict, concepts_agg: dict) -> float:
    """Score composite normalisé sur 100.

    Pondération (cf. brief) :
      - AR sémantique (anchor) ×3
      - JSON fiable ×2 (moyenne AR + concepts)
      - Latence ×2 (inversée — plus c'est rapide, mieux c'est)
      - AR bornes ×1 (title + description)
      - Cohérence FR/EN ×1
    Total max = 9 → ramené à 100.
    """
    n_ar = ar_agg.get("total", 1)
    n_kids = concepts_agg.get("total_children_generated", 0) or 1

    score_ar_anchor = (ar_agg.get("anchor_present", 0) / n_ar) * 3
    json_ar = ar_agg.get("json_ok", 0) / n_ar
    json_concepts = concepts_agg.get("json_ok", 0) / max(concepts_agg.get("total_terms", 1), 1)
    score_json = ((json_ar + json_concepts) / 2) * 2
    avg_lat = (ar_agg.get("avg_latency_s", 60) + concepts_agg.get("avg_latency_s", 60)) / 2
    # Latence : 0s = 1.0, 60s = 0.0 (linéaire borné).
    lat_norm = max(0.0, min(1.0, 1 - avg_lat / 60))
    score_lat = lat_norm * 2
    title_ok = ar_agg.get("title_in_bounds", 0) / n_ar
    desc_ok = ar_agg.get("description_in_bounds", 0) / n_ar
    score_bounds = ((title_ok + desc_ok) / 2) * 1
    suspect = concepts_agg.get("cross_locale_suspect", 0)
    coherence = 1 - (suspect / n_kids)
    score_coh = coherence * 1

    total = score_ar_anchor + score_json + score_lat + score_bounds + score_coh
    return round((total / 9) * 100, 1)


def fetch_existing_terms() -> list[dict]:
    """Snapshot des termes pour dédup detection."""
    from api.db import DBConnAdapter, SessionLocal
    from api.helpers import get_i18n
    session = SessionLocal()
    conn = DBConnAdapter(session)
    rows = conn.execute("SELECT id, name_i18n FROM term").fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else dict(zip(["id", "name_i18n"], r))
        out.append({
            "id": str(d["id"]),
            "name_fr": get_i18n(d["name_i18n"], "fr"),
            "name_en": get_i18n(d["name_i18n"], "en"),
        })
    conn.close()
    return out


def main() -> int:
    print("=" * 100)
    print("POC-LLM — Benchmark comparatif Ollama")
    print("=" * 100)

    print(f"\n[Étape 0] Inventaire modèles ({OLLAMA_BASE_URL})")
    try:
        all_models, text_models = list_models()
    except Exception as exc:
        print(f"  ❌ Impossible de lister les modèles : {exc}", file=sys.stderr)
        return 2
    print(f"  Total : {len(all_models)} modèles, dont {len(text_models)} non-LLaVA")
    for m in all_models:
        details = m.get("details") or {}
        marker = "✓" if "llava" not in (m.get("name") or "").lower() else "(skip LLaVA)"
        print(f"    {marker} {m.get('name'):<22} family={details.get('family'):<10} param_size={details.get('parameter_size'):<8} size={round(m.get('size', 0)/(1024**3), 2)} GB")

    if len(text_models) < 2:
        print(f"\n⚠ Moins de 2 modèles non-LLaVA disponibles ({len(text_models)}). Benchmark comparatif impossible.")
        return 3

    print(f"\n[Étape 1] AR anchored content sur {len(text_models)} modèles…")
    suggest_tpl = load_suggest_children_template()
    existing_terms = fetch_existing_terms()

    bench: dict = {}
    for m in text_models:
        name = m["name"]
        print(f"\n>>> Modèle : {name}")
        ar_results = benchmark_ar(name)
        ar_agg = aggregate_ar(ar_results, len(PAIRS_AR))
        concepts_results = benchmark_concepts(name, suggest_tpl, LEAF_TERMS)
        concepts_results = evaluate_concepts(concepts_results, existing_terms)
        concepts_agg = aggregate_concepts(concepts_results, len(LEAF_TERMS))
        score = composite_score(ar_agg, concepts_agg)
        bench[name] = {
            "model_info": m,
            "ar_results": ar_results,
            "ar_agg": ar_agg,
            "concepts_results": concepts_results,
            "concepts_agg": concepts_agg,
            "composite_score": score,
        }
        print(f"\n  Synthèse {name} :")
        print(f"    AR  : json={ar_agg['json_ok']}/{ar_agg['total']} anchor={ar_agg['anchor_present']}/{ar_agg['total']} "
              f"title_b={ar_agg['title_in_bounds']}/{ar_agg['total']} desc_b={ar_agg['description_in_bounds']}/{ar_agg['total']} "
              f"harakat_clean={ar_agg['harakat_clean']}/{ar_agg['total']} latin_clean={ar_agg['latin_clean']}/{ar_agg['total']} lat={ar_agg['avg_latency_s']}s")
        print(f"    Concepts : json={concepts_agg['json_ok']}/{concepts_agg['total_terms']} children={concepts_agg['total_children_generated']} "
              f"ar_ok={concepts_agg['ar_present_and_short']} suspect_loc={concepts_agg['cross_locale_suspect']} "
              f"dup={concepts_agg['duplicates_with_existing']} lat={concepts_agg['avg_latency_s']}s")
        print(f"    Score composite : {score} / 100")

    # Save JSON
    payload = {
        "poc": "llm-benchmark",
        "date": "2026-05-05",
        "ollama_base_url": OLLAMA_BASE_URL,
        "all_models_listed": [{"name": m.get("name"), "size_gb": round(m.get("size", 0)/(1024**3), 2),
                                "param_size": (m.get("details") or {}).get("parameter_size"),
                                "family": (m.get("details") or {}).get("family")} for m in all_models],
        "text_models_tested": [m["name"] for m in text_models],
        "ar_pairs_count": len(PAIRS_AR),
        "leaf_terms_concepts": LEAF_TERMS,
        "ar_bounds": {"title": [TITLE_MIN, TITLE_MAX], "description": [DESC_MIN, DESC_MAX]},
        "results_by_model": bench,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON brut → {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
