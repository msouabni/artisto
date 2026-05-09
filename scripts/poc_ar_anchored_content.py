"""POC-4 : Génération de contenu AR ancré sur term.name_ar.

Stratégie : injecter le label AR validé d'un terme feuille de la taxonomie comme
ancre explicite dans le prompt qwen2.5:7b, pour réduire les erreurs sémantiques
(taux baseline 30-40 % en génération directe FR/EN→AR).

Usage :
    python scripts/poc_ar_anchored_content.py
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

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-ar-anchored-content.json"

# 10 paires variées — termes feuilles avec name_ar propre (pas de translittération
# phonétique douteuse type "بوديل" pour Poodle).
PAIRS = [
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

# Variant B : force term_ar en début de titre.
PROMPT_B_TPL = """Le sujet de l'image est : "{concept_en}".
Le thème principal en arabe est : {term_ar} ({term_en}).

Génère le contenu éditorial en arabe standard (fusha/MSA) pour cette page de coloriage.

Règles strictes :
- Le title DOIT commencer par les mots : {term_ar}
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

HARAKAT_RE = re.compile(r"[ؐ-ًؚ-ٟ]")
LATIN_RE = re.compile(r"[a-zA-Z]")
AL_PREFIX_RE = re.compile(r"^(ال|وال|فال|بال|كال|لل)")


def _normalize_for_anchor(s: str) -> str:
    """Normalise pour matching anchor : enlève harakat éventuels, tatweel."""
    return HARAKAT_RE.sub("", s.replace("ـ", "")).strip()


def _anchor_present(term_ar: str, *texts: str) -> dict:
    """Vérifie si le terme arabe (ou variante morphologique) apparaît dans un des textes."""
    haystack = " ".join(_normalize_for_anchor(t) for t in texts if t)
    needle = _normalize_for_anchor(term_ar)
    if not needle or not haystack:
        return {"present": False, "match_kind": "no_data"}
    if needle in haystack:
        return {"present": True, "match_kind": "exact"}
    # Sans préfixe d'article
    bare = AL_PREFIX_RE.sub("", needle).strip()
    if bare and bare in haystack:
        return {"present": True, "match_kind": "no_article"}
    # Match au moins un mot du term_ar (≥3 chars)
    for token in needle.split():
        token_bare = AL_PREFIX_RE.sub("", token).strip()
        if len(token_bare) >= 3 and token_bare in haystack:
            return {"present": True, "match_kind": "token_match", "token": token_bare}
    # Préfixe de 4+ chars
    if len(bare) >= 4 and bare[:4] in haystack:
        return {"present": True, "match_kind": "prefix_4"}
    return {"present": False, "match_kind": "absent"}


def _has_harakat(*texts: str) -> bool:
    return any(HARAKAT_RE.search(t or "") for t in texts)


def _has_latin(*texts: str) -> bool:
    return any(LATIN_RE.search(t or "") for t in texts)


def _evaluate(parsed, term_ar: str) -> dict:
    if not isinstance(parsed, dict):
        return {"json_ok": False}
    title = (parsed.get("title") or "").strip()
    card = (parsed.get("title_card") or "").strip()
    desc = (parsed.get("description") or "").strip()
    kw = parsed.get("keywords") or []
    kw_strs = [k for k in kw if isinstance(k, str)] if isinstance(kw, list) else []
    anchor = _anchor_present(term_ar, title, desc)
    all_text_fields = [title, card, desc, *kw_strs]
    return {
        "json_ok": True,
        "title": title,
        "title_card": card,
        "description": desc,
        "keywords": kw_strs,
        "title_len": len(title),
        "title_in_bounds": 30 <= len(title) <= 50,
        "title_card_len": len(card),
        "title_card_in_bounds": len(card) <= 25,
        "description_len": len(desc),
        "description_in_bounds": 55 <= len(desc) <= 90,
        "keywords_count": len(kw_strs),
        "keywords_count_ok": len(kw_strs) == 5,
        "anchor_present": anchor["present"],
        "anchor_match_kind": anchor.get("match_kind"),
        "harakat_anywhere": _has_harakat(*all_text_fields),
        "latin_anywhere": _has_latin(*all_text_fields),
    }


def run_one(prompt_tpl: str, pair: dict) -> dict:
    prompt = prompt_tpl.format(**pair)
    t0 = time.time()
    try:
        raw = call_ollama_sync(prompt, "", temperature=0.0)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}
    dt = time.time() - t0
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {"raw": raw, "json_ok": False, "json_error": f"{type(exc).__name__}: {exc}", "latency_s": dt}
    ev = _evaluate(parsed, pair["term_ar"])
    return {"raw": raw, "parsed": parsed if isinstance(parsed, dict) else None, "latency_s": dt, **ev}


def aggregate(results: list[dict]) -> dict:
    valid = [r for r in results if r.get("json_ok")]
    n = len(valid)
    if n == 0:
        return {"json_ok": 0, "total": len(results)}
    return {
        "json_ok": n,
        "total": len(results),
        "title_in_bounds": sum(1 for r in valid if r["title_in_bounds"]),
        "title_card_in_bounds": sum(1 for r in valid if r["title_card_in_bounds"]),
        "description_in_bounds": sum(1 for r in valid if r["description_in_bounds"]),
        "keywords_count_ok": sum(1 for r in valid if r["keywords_count_ok"]),
        "anchor_present": sum(1 for r in valid if r["anchor_present"]),
        "harakat_present": sum(1 for r in valid if r["harakat_anywhere"]),
        "latin_present": sum(1 for r in valid if r["latin_anywhere"]),
        "avg_latency_s": round(sum(r["latency_s"] for r in valid) / n, 2),
    }


def print_summary(label: str, agg: dict, n: int) -> None:
    print(f"\n=== Synthèse {label} ===")
    print(f"  JSON parsable           : {agg.get('json_ok', 0)}/{n}")
    if agg.get("json_ok"):
        print(f"  Anchor présent          : {agg['anchor_present']}/{agg['json_ok']}")
        print(f"  title in [30,50]        : {agg['title_in_bounds']}/{agg['json_ok']}")
        print(f"  title_card ≤ 25         : {agg['title_card_in_bounds']}/{agg['json_ok']}")
        print(f"  description in [55,90]  : {agg['description_in_bounds']}/{agg['json_ok']}")
        print(f"  keywords = 5            : {agg['keywords_count_ok']}/{agg['json_ok']}")
        print(f"  harakat absents         : {agg['json_ok'] - agg['harakat_present']}/{agg['json_ok']}")
        print(f"  latin absents           : {agg['json_ok'] - agg['latin_present']}/{agg['json_ok']}")
        print(f"  avg latency             : {agg['avg_latency_s']}s")


def main() -> int:
    print(f"Modèle : {OLLAMA_MODEL}  ·  T=0  ·  {len(PAIRS)} paires\n")

    print("=" * 100)
    print("PROMPT A — anchored")
    print("=" * 100)
    results_a = []
    for idx, pair in enumerate(PAIRS, 1):
        print(f"\n[{idx}/{len(PAIRS)}] concept={pair['concept_en']!r}  term_ar={pair['term_ar']!r}")
        r = run_one(PROMPT_A_TPL, pair)
        r["pair"] = pair
        results_a.append(r)
        if r.get("error"):
            print(f"  ERREUR : {r['error']}")
        elif not r.get("json_ok"):
            print(f"  JSON KO : {r.get('json_error')}")
        else:
            print(f"  title       : {r['title']}  ({r['title_len']}c, in_bounds={r['title_in_bounds']})")
            print(f"  title_card  : {r['title_card']}  ({r['title_card_len']}c, in_bounds={r['title_card_in_bounds']})")
            print(f"  description : {r['description']}  ({r['description_len']}c, in_bounds={r['description_in_bounds']})")
            print(f"  keywords    : {r['keywords']}  ({r['keywords_count']}, ok={r['keywords_count_ok']})")
            print(f"  flags       : anchor={r['anchor_present']}({r.get('anchor_match_kind')})  harakat={r['harakat_anywhere']}  latin={r['latin_anywhere']}  lat={r['latency_s']:.1f}s")

    agg_a = aggregate(results_a)
    print_summary("PROMPT A", agg_a, len(PAIRS))

    # Trigger variant B if anchor error rate > 10 %
    json_ok_a = agg_a.get("json_ok", 0)
    anchor_a = agg_a.get("anchor_present", 0)
    error_rate_a = (json_ok_a - anchor_a) / json_ok_a if json_ok_a else 1.0
    print(f"\nAnchor error rate prompt A : {error_rate_a:.1%}")

    results_b: list[dict] = []
    agg_b: dict = {}
    if error_rate_a > 0.10:
        print(f"\n>10 % erreurs sémantiques → run variant B (forcer term_ar en début de titre)")
        print("=" * 100)
        print("PROMPT B — anchored + force term_ar prefix in title")
        print("=" * 100)
        for idx, pair in enumerate(PAIRS, 1):
            print(f"\n[{idx}/{len(PAIRS)}] concept={pair['concept_en']!r}  term_ar={pair['term_ar']!r}")
            r = run_one(PROMPT_B_TPL, pair)
            r["pair"] = pair
            results_b.append(r)
            if r.get("error"):
                print(f"  ERREUR : {r['error']}")
            elif not r.get("json_ok"):
                print(f"  JSON KO : {r.get('json_error')}")
            else:
                print(f"  title       : {r['title']}  ({r['title_len']}c)")
                print(f"  flags       : anchor={r['anchor_present']}({r.get('anchor_match_kind')})  harakat={r['harakat_anywhere']}  latin={r['latin_anywhere']}")
        agg_b = aggregate(results_b)
        print_summary("PROMPT B", agg_b, len(PAIRS))
    else:
        print(f"\nAnchor error rate ≤ 10 % → variant B non déclenchée.")

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "poc": "ar-anchored-content",
        "date": "2026-05-05",
        "model": OLLAMA_MODEL,
        "temperature": 0.0,
        "pairs_count": len(PAIRS),
        "pairs": PAIRS,
        "prompt_a_template": PROMPT_A_TPL,
        "prompt_b_template": PROMPT_B_TPL,
        "summary_a": agg_a,
        "summary_b": agg_b if agg_b else None,
        "variant_b_triggered": bool(agg_b),
        "results_a": results_a,
        "results_b": results_b if results_b else None,
        "baseline_error_rate_no_anchor": "30-40% (cf. POC ar-content-quality 2026-05-05)",
    }
    with REPORT_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON brut → {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
