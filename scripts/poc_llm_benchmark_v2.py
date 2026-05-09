"""POC-LLM-v2 : benchmark étendu sur 6 modèles + tâche vision.

Étapes :
0. Inventaire des modèles attendus (qwen2.5:7b, qwen3:8b, qwen3.5:9b, qwen3.5:4b,
   gemma4:26b, aya-expanse:8b).
1. Tâche AR : Prompt A POC-4 sur 10 paires (concept_en, term_ar, term_en).
2. Tâche concepts : prompt suggest_children sur 5 termes feuilles.
3. Tâche vision : 6 images (4 bonnes, 2 mauvaises) sur gemma4:26b + qwen3.5:9b.
4. Synthèse + score composite + classement.

Usage :
    python scripts/poc_llm_benchmark_v2.py
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
import yaml  # noqa: E402

from services.ollama_json import (  # noqa: E402
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT,
    apply_no_think_system,
    call_ollama_sync,
    parse_json_response,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-llm-benchmark-v2.json"
TAXONOMY_PROMPTS = PROJECT_ROOT / "prompts" / "taxonomy_prompts.yaml"

EXPECTED_MODELS = [
    "qwen2.5:7b",
    "qwen3:8b",
    "qwen3.5:9b",
    "qwen3.5:4b",
    "gemma4:26b",
    "aya-expanse:8b",
]
VISION_MODELS = ["gemma4:26b", "qwen3.5:9b"]

# ─────────────── PAIRS AR (identique POC-LLM v1) ───────────────
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

TITLE_MIN, TITLE_MAX = 25, 55
DESC_MIN, DESC_MAX = 40, 100

LEAF_TERMS = [
    {"id": "animaux_marins",   "name_fr": "Animaux marins",   "name_en": "Sea animals"},
    {"id": "noel",              "name_fr": "Noël",             "name_en": "Christmas"},
    {"id": "mandalas_fleurs",   "name_fr": "Mandalas fleurs",  "name_en": "Flower mandalas"},
    {"id": "voitures",          "name_fr": "Voitures",         "name_en": "Cars"},
    {"id": "science",           "name_fr": "Science",          "name_en": "Science"},
]

# Codepoints explicites pour éviter le RTL trap au copier-coller
HARAKAT_RE = re.compile("[\u0610-\u061A\u064B-\u065F]")
LATIN_RE = re.compile(r"[a-zA-Z]")
AL_PREFIX_RE = re.compile(r"^(ال|وال|فال|بال|كال|لل)")

# Images vision : ground truth manuelle
VISION_IMAGES = [
    {"path": "data/outputs/animaux_chat_collier_job_gen_1773358396932.png",
     "ground_truth": "poor", "expected_issues": ["incomplete", "not_line_art"],
     "note": "image vide avec juste texte du prompt"},
    {"path": "data/outputs/adventure_in_scooby-doo-island_job_gen_1776469080378352300_4.png",
     "ground_truth": "poor", "expected_issues": ["has_color"],
     "note": "soleil jaune + gradients gris, pas du line art pur"},
    {"path": "data/outputs/animals_bath_cat_job_gen_1776983831725453200_3.png",
     "ground_truth": "good", "expected_issues": [],
     "note": "line art propre"},
    {"path": "data/outputs/animals_party_decor_job_gen_1776469535491823500_6.png",
     "ground_truth": "good", "expected_issues": [],
     "note": "line art propre"},
    {"path": "data/outputs/animaux_chat_biblioth_que_job_gen_1773480548607.png",
     "ground_truth": "good", "expected_issues": [],
     "note": "line art simple, propre"},
    {"path": "data/outputs/animals_fairy_cat_job_gen_1776986811626965500_5.png",
     "ground_truth": "good", "expected_issues": [],
     "note": "line art détaillé propre"},
]

VISION_SYSTEM = "You are a quality control assistant for children's coloring pages."
VISION_USER = (
    "Evaluate this coloring page image quality for publication.\n"
    "Reply ONLY with valid JSON, no explanation:\n"
    '{"quality": "good"|"poor", "issues": [], "confidence": 0-100}\n'
    'Possible issues: "has_color", "blurry", "noisy", "artifacts", "not_line_art", "incomplete"'
)


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
        "title": title, "title_card": card, "description": desc, "keywords": kw_strs,
        "title_len": len(title), "title_in_bounds": TITLE_MIN <= len(title) <= TITLE_MAX,
        "title_card_len": len(card), "title_card_in_bounds": len(card) <= 25,
        "description_len": len(desc), "description_in_bounds": DESC_MIN <= len(desc) <= DESC_MAX,
        "keywords_count": len(kw_strs), "keywords_count_ok": len(kw_strs) == 5,
        "anchor_present": anchor["present"], "anchor_match_kind": anchor.get("match_kind"),
        "harakat_anywhere": _has_harakat(*fields),
        "latin_anywhere": _has_latin(*fields),
    }


def list_models() -> list[dict]:
    r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=15.0)
    r.raise_for_status()
    return r.json().get("models", [])


CALL_TIMEOUT = 120  # secondes par call (réduit de 300 pour limiter pertes sur modèles lents)
PING_TIMEOUT = 30


def ping_model(model: str) -> tuple[bool, float]:
    """Pre-flight : modèle répond en <30s à un prompt minimal ?"""
    payload = {
        "model": model,
        "prompt": "Reply with the single word: pong",
        "system": apply_no_think_system(model, ""),
        "stream": False,
        "options": {"temperature": 0.0},
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=PING_TIMEOUT) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            r.raise_for_status()
        return True, time.time() - t0
    except Exception:
        return False, time.time() - t0


def benchmark_ar(model: str) -> list[dict]:
    print(f"\n  --- AR benchmark on {model} ---")
    out = []
    for idx, pair in enumerate(PAIRS_AR, 1):
        prompt = PROMPT_A_TPL.format(**pair)
        # Force /no_think pour qwen3* (apply_no_think_system détecte qwen3 dans name)
        sys_prompt = apply_no_think_system(model, "")
        t0 = time.time()
        try:
            raw = call_ollama_sync(prompt, sys_prompt, model=model, temperature=0.0, timeout=CALL_TIMEOUT)
        except Exception as exc:
            dt = time.time() - t0
            out.append({"pair": pair, "error": f"{type(exc).__name__}: {exc}", "latency_s": dt})
            print(f"    [{idx:>2}] ERR  {pair['concept_en'][:30]:<30} {type(exc).__name__}")
            continue
        dt = time.time() - t0
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            out.append({"pair": pair, "raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt})
            print(f"    [{idx:>2}] JSON⚠ {pair['concept_en'][:30]:<30} ({dt:.1f}s)")
            continue
        ev = _evaluate_ar(parsed, pair["term_ar"])
        out.append({"pair": pair, "raw": raw, "parsed": parsed, "latency_s": dt, **ev})
        anchor = "✓" if ev.get("anchor_present") else "✗"
        bounds = "✓" if ev.get("title_in_bounds") and ev.get("description_in_bounds") else "✗"
        clean = "✓" if not ev.get("harakat_anywhere") and not ev.get("latin_anywhere") else "✗"
        print(f"    [{idx:>2}] {pair['concept_en'][:30]:<30} a={anchor} b={bounds} c={clean} {dt:.1f}s")
    return out


def aggregate_ar(results: list[dict], n_total: int) -> dict:
    valid = [r for r in results if r.get("json_ok")]
    if not valid:
        return {"json_ok": 0, "total": n_total, "errors": len(results) - len(valid)}
    return {
        "total": n_total, "json_ok": len(valid),
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
    return yaml.safe_load(TAXONOMY_PROMPTS.read_text(encoding="utf-8"))["prompts"]["suggest_children"]


def benchmark_concepts(model: str, template: dict) -> list[dict]:
    print(f"\n  --- Concepts benchmark on {model} ---")
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
            print(f"    {leaf['id']:<22} ERR  {type(exc).__name__}")
            continue
        dt = time.time() - t0
        try:
            parsed = parse_json_response(raw)
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
        except Exception as exc:
            out.append({"leaf": leaf, "raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt})
            print(f"    {leaf['id']:<22} JSON⚠ ({dt:.1f}s)")
            continue
        children = parsed if isinstance(parsed, list) else []
        out.append({"leaf": leaf, "raw": raw, "json_ok": True, "children": children, "latency_s": dt})
        print(f"    {leaf['id']:<22} {len(children)} children  {dt:.1f}s")
    return out


def evaluate_concepts(results: list[dict], existing_terms: list[dict]) -> list[dict]:
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
            wc_fr, wc_en = len(fr.split()), len(en.split())
            same = (fr.lower() == en.lower() and fr != "")
            wc_diff = abs(wc_fr - wc_en) >= 3
            missing = not fr or not en
            cross_locale_flag = same or wc_diff or missing
            duplicate = (cid in existing_id) or (fr.lower() in existing_fr) or (en.lower() in existing_en if en else False)
            evs.append({
                "id": cid, "name_fr": fr, "name_en": en, "name_ar": ar,
                "ar_ok": ar_ok, "cross_locale_suspect": cross_locale_flag, "duplicate": duplicate,
            })
        r["children_evaluated"] = evs
    return results


def aggregate_concepts(results: list[dict], n_terms: int) -> dict:
    valid = [r for r in results if r.get("json_ok")]
    total_children = ar_ok = suspect = dup = 0
    for r in valid:
        evs = r.get("children_evaluated", [])
        total_children += len(evs)
        ar_ok += sum(1 for e in evs if e["ar_ok"])
        suspect += sum(1 for e in evs if e["cross_locale_suspect"])
        dup += sum(1 for e in evs if e["duplicate"])
    avg_lat = sum(r["latency_s"] for r in valid) / len(valid) if valid else 0
    return {
        "total_terms": n_terms, "json_ok": len(valid),
        "total_children_generated": total_children,
        "ar_present_and_short": ar_ok,
        "cross_locale_suspect": suspect,
        "duplicates_with_existing": dup,
        "avg_latency_s": round(avg_lat, 2),
    }


def fetch_existing_terms() -> list[dict]:
    from api.db import DBConnAdapter, SessionLocal
    from api.helpers import get_i18n
    session = SessionLocal()
    conn = DBConnAdapter(session)
    rows = conn.execute("SELECT id, name_i18n FROM term").fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping)
        out.append({"id": str(d["id"]),
                    "name_fr": get_i18n(d["name_i18n"], "fr"),
                    "name_en": get_i18n(d["name_i18n"], "en")})
    conn.close()
    return out


def call_ollama_vision(model: str, prompt: str, system: str, image_path: Path, timeout: int = 300) -> str:
    """Appel /api/generate avec image base64."""
    img_bytes = image_path.read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode("ascii")
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
        r.raise_for_status()
        return r.json().get("response", "")


def benchmark_vision(model: str) -> list[dict]:
    print(f"\n  --- Vision benchmark on {model} ---")
    out = []
    for img in VISION_IMAGES:
        path = PROJECT_ROOT / img["path"]
        if not path.exists():
            out.append({"image": img["path"], "error": "file not found"})
            print(f"    {Path(img['path']).name[:40]:<40} ERR  file not found")
            continue
        sys_prompt = apply_no_think_system(model, VISION_SYSTEM)
        t0 = time.time()
        try:
            raw = call_ollama_vision(model, VISION_USER, sys_prompt, path, timeout=CALL_TIMEOUT)
        except Exception as exc:
            dt = time.time() - t0
            out.append({"image": img["path"], "ground_truth": img["ground_truth"],
                        "error": f"{type(exc).__name__}: {exc}", "latency_s": dt})
            print(f"    {Path(img['path']).name[:40]:<40} ERR  {type(exc).__name__} ({dt:.1f}s)")
            continue
        dt = time.time() - t0
        try:
            parsed = parse_json_response(raw)
            json_ok = isinstance(parsed, dict)
        except Exception as exc:
            out.append({"image": img["path"], "ground_truth": img["ground_truth"],
                        "raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt})
            print(f"    {Path(img['path']).name[:40]:<40} JSON⚠ ({dt:.1f}s)")
            continue
        verdict = parsed.get("quality") if json_ok else None
        verdict_correct = (verdict == img["ground_truth"]) if verdict in ("good", "poor") else None
        out.append({
            "image": img["path"], "ground_truth": img["ground_truth"],
            "expected_issues": img["expected_issues"], "raw": raw, "parsed": parsed,
            "json_ok": json_ok, "verdict": verdict, "verdict_correct": verdict_correct,
            "issues_returned": parsed.get("issues") if json_ok else None,
            "confidence": parsed.get("confidence") if json_ok else None,
            "latency_s": dt,
        })
        flag = "✓" if verdict_correct else ("✗" if verdict_correct is False else "?")
        print(f"    {Path(img['path']).name[:40]:<40} v={verdict} (gt={img['ground_truth']}) {flag} {dt:.1f}s")
    return out


def aggregate_vision(results: list[dict]) -> dict:
    if not results:
        return {}
    valid = [r for r in results if r.get("json_ok")]
    correct = sum(1 for r in valid if r.get("verdict_correct"))
    avg_lat = sum(r.get("latency_s", 0) for r in valid) / len(valid) if valid else 0
    return {
        "total": len(results),
        "json_ok": len(valid),
        "verdict_correct": correct,
        "avg_latency_s": round(avg_lat, 2),
    }


def composite_score(ar_agg: dict, concepts_agg: dict) -> float:
    n_ar = ar_agg.get("total", 1)
    n_kids = concepts_agg.get("total_children_generated", 0) or 1
    score_ar_anchor = (ar_agg.get("anchor_present", 0) / n_ar) * 3
    json_ar = ar_agg.get("json_ok", 0) / n_ar
    json_concepts = concepts_agg.get("json_ok", 0) / max(concepts_agg.get("total_terms", 1), 1)
    score_json = ((json_ar + json_concepts) / 2) * 2
    avg_lat = (ar_agg.get("avg_latency_s", 60) + concepts_agg.get("avg_latency_s", 60)) / 2
    lat_norm = max(0.0, min(1.0, 1 - avg_lat / 60))
    score_lat = lat_norm * 2
    title_ok = ar_agg.get("title_in_bounds", 0) / n_ar
    desc_ok = ar_agg.get("description_in_bounds", 0) / n_ar
    score_bounds = ((title_ok + desc_ok) / 2) * 2
    suspect = concepts_agg.get("cross_locale_suspect", 0)
    coherence = 1 - (suspect / n_kids)
    score_coh = coherence * 1
    total = score_ar_anchor + score_json + score_lat + score_bounds + score_coh
    return round((total / 10) * 100, 1)


def main() -> int:
    print("=" * 100)
    print("POC-LLM-v2 — Benchmark étendu 6 modèles + vision")
    print("=" * 100)

    print(f"\n[Étape 0] Inventaire ({OLLAMA_BASE_URL})")
    available = list_models()
    available_names = {m["name"] for m in available}
    confirmed = [name for name in EXPECTED_MODELS if name in available_names]
    missing = [name for name in EXPECTED_MODELS if name not in available_names]
    print(f"  Listés sur server : {confirmed}")
    if missing:
        print(f"  ⚠ Manquants : {missing}")

    # Pre-flight : vérifier que chaque modèle répond < 30s à un prompt minimal
    print(f"\n[Pre-flight ping {PING_TIMEOUT}s]")
    responsive: list[str] = []
    skipped: list[str] = []
    for name in confirmed:
        ok, dt = ping_model(name)
        if ok:
            responsive.append(name)
            print(f"  ✓ {name:<22} {dt:.1f}s")
        else:
            skipped.append(name)
            print(f"  ✗ {name:<22} TIMEOUT/ERROR ({dt:.1f}s) — skip benchmark")

    print(f"\n  Modèles benchmarkés : {responsive}")
    print(f"  Vision testée sur : {[v for v in VISION_MODELS if v in responsive]}")

    print("\n[Préparation]")
    suggest_tpl = load_suggest_children_template()
    existing_terms = fetch_existing_terms()
    print(f"  {len(existing_terms)} termes existants chargés (dédup detection)")

    bench: dict = {}

    def _save_partial(extra: dict | None = None) -> None:
        payload = {
            "poc": "llm-benchmark-v2",
            "date": "2026-05-05",
            "ollama_base_url": OLLAMA_BASE_URL,
            "expected_models": EXPECTED_MODELS,
            "confirmed_listed": confirmed,
            "missing_models": missing,
            "responsive_models": responsive,
            "skipped_models_preflight": skipped,
            "ar_pairs": PAIRS_AR,
            "leaf_terms": LEAF_TERMS,
            "vision_images": VISION_IMAGES,
            "ar_bounds": {"title": [TITLE_MIN, TITLE_MAX], "description": [DESC_MIN, DESC_MAX]},
            "results_by_model": bench,
            **(extra or {}),
        }
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        with REPORT_JSON.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    for model_name in responsive:
        print(f"\n>>> Modèle : {model_name}")
        ar_results = benchmark_ar(model_name)
        ar_agg = aggregate_ar(ar_results, len(PAIRS_AR))
        concepts_results = benchmark_concepts(model_name, suggest_tpl)
        concepts_results = evaluate_concepts(concepts_results, existing_terms)
        concepts_agg = aggregate_concepts(concepts_results, len(LEAF_TERMS))
        score = composite_score(ar_agg, concepts_agg)
        bench[model_name] = {
            "ar_results": ar_results, "ar_agg": ar_agg,
            "concepts_results": concepts_results, "concepts_agg": concepts_agg,
            "composite_score": score,
        }
        print(f"\n  Synthèse {model_name} :")
        print(f"    AR  : json={ar_agg.get('json_ok',0)}/{ar_agg.get('total',0)} anchor={ar_agg.get('anchor_present',0)}/{ar_agg.get('total',0)} "
              f"title_b={ar_agg.get('title_in_bounds',0)}/{ar_agg.get('total',0)} desc_b={ar_agg.get('description_in_bounds',0)}/{ar_agg.get('total',0)} "
              f"harakat={ar_agg.get('harakat_clean',0)}/{ar_agg.get('total',0)} latin={ar_agg.get('latin_clean',0)}/{ar_agg.get('total',0)} lat={ar_agg.get('avg_latency_s','?')}s")
        print(f"    Concepts : json={concepts_agg.get('json_ok',0)}/{concepts_agg.get('total_terms',0)} children={concepts_agg.get('total_children_generated',0)} "
              f"ar_ok={concepts_agg.get('ar_present_and_short',0)} suspect={concepts_agg.get('cross_locale_suspect',0)} "
              f"dup={concepts_agg.get('duplicates_with_existing',0)} lat={concepts_agg.get('avg_latency_s','?')}s")
        print(f"    Score composite : {score} / 100")
        _save_partial()  # save incrémental après chaque modèle

    # Étape 3 — vision (uniquement modèles responsive)
    print("\n[Étape 3] Vision QC")
    vision_models_available = [v for v in VISION_MODELS if v in responsive]
    vision_bench: dict = {}
    if not VISION_IMAGES or not all((PROJECT_ROOT / img["path"]).exists() for img in VISION_IMAGES):
        print(f"  ⚠ Toutes les images attendues ne sont pas présentes — partiel")
    for vm in vision_models_available:
        print(f"\n>>> Vision {vm}")
        vr = benchmark_vision(vm)
        va = aggregate_vision(vr)
        vision_bench[vm] = {"results": vr, "agg": va}
        print(f"  Synthèse vision {vm} : json={va.get('json_ok',0)}/{va.get('total',0)} correct={va.get('verdict_correct',0)}/{va.get('json_ok',0)} lat={va.get('avg_latency_s','?')}s")

    # Save JSON final (avec vision)
    _save_partial({"vision_results_by_model": vision_bench, "vision_models_tested": vision_models_available})
    print(f"\nJSON brut → {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
