"""POC-2 : generate_concepts sur la nouvelle taxonomie avec qwen3.5:4b.

15 termes feuilles variés × 5 concepts = 75 concepts.

Catégories :
- 3 animaux (pet / farm / african wild)
- 2 outils (hand / gardening)
- 2 professions (health / security_emergency)
- 2 sports (team / individual)
- 2 personnages fictifs (disney / marvel)
- 2 géométrie/alphabet (basic_shapes / english_alphabet)
- 2 corps humain (external_anatomy / internal_organs)

Usage :
    python scripts/poc_generate_concepts.py
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import yaml  # noqa: E402

from sqlalchemy import text  # noqa: E402

from api.db import ENGINE  # noqa: E402
from api.helpers import get_i18n  # noqa: E402
from services.ollama_json import (  # noqa: E402
    apply_no_think_system,
    call_ollama_sync,
    parse_json_response,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-generate-concepts.json"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-generate-concepts.md"
IMAGE_PROMPTS = PROJECT_ROOT / "prompts" / "image_prompts.yaml"

MODEL = "qwen3.5:4b"
COUNT_PER_LEAF = 5

# Sélection : 1 feuille pour chaque sous-thème listé (= 1ʳᵉ feuille trouvée
# par sous-thème). Mappés sur la spec utilisateur (3+2+2+2+2+2+2 = 15).
SUBTOPICS = [
    ("animals/pet_animals", "pet_animals", "Animaux"),
    ("animals/farm_animals", "farm_animals", "Animaux"),
    ("animals/african_wild_animals", "african_wild_animals", "Animaux"),
    ("tools/hand_tools", "hand_tools", "Outils"),
    ("tools/gardening_tools", "gardening_tools", "Outils"),
    ("professions/health_professions", "health_professions", "Professions"),
    ("professions/security_and_emergency", "security_and_emergency", "Professions"),
    ("sports/team_sports", "team_sports", "Sports"),
    ("sports/individual_sports", "individual_sports", "Sports"),
    ("characters/disney_universe", "disney_universe", "Personnages fictifs"),
    ("characters/marvel_universe", "marvel_universe", "Personnages fictifs"),
    ("geometry/basic_shapes", "basic_shapes", "Géométrie / Alphabet"),
    ("alphabet/english_alphabet_illustrated", "english_alphabet_illustrated", "Géométrie / Alphabet"),
    ("body/external_anatomy", "external_anatomy", "Corps humain"),
    ("body/internal_organs_educational", "internal_organs_educational", "Corps humain"),
]

# Codepoints explicites — RTL trap résolu
HARAKAT_RE = re.compile("[\u0610-\u061A\u064B-\u065F]")
SETTING_MARKERS = re.compile(r"\b(in|on|at|under|inside|near|with|by|under|over|beside|through|across|during|from|to)\b", re.IGNORECASE)


def has_harakat(s: str) -> bool:
    return bool(HARAKAT_RE.search(s or ""))


def has_setting_marker(s: str) -> bool:
    return bool(SETTING_MARKERS.search(s or ""))


def fetch_leaf_for_subtopic(parent_id: str) -> dict | None:
    """1ʳᵉ feuille (level 2) sous le sous-thème donné."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, name_i18n, parent_id
                FROM term
                WHERE parent_id = :pid
                ORDER BY weight, id
                LIMIT 1
            """),
            {"pid": parent_id},
        ).fetchall()
    if not rows:
        return None
    d = dict(rows[0]._mapping)
    return {
        "id": d["id"],
        "parent_id": d["parent_id"],
        "name_en": get_i18n(d["name_i18n"], "en"),
        "name_fr": get_i18n(d["name_i18n"], "fr"),
        "name_ar": get_i18n(d["name_i18n"], "ar"),
    }


def load_template() -> dict:
    return yaml.safe_load(IMAGE_PROMPTS.read_text(encoding="utf-8"))["prompts"]["generate_concepts"]


def call_generate_concepts(leaf: dict, template: dict) -> dict:
    """Appelle Ollama generate_concepts pour ce leaf, count=COUNT_PER_LEAF."""
    sys_prompt = apply_no_think_system(MODEL, template["system"])
    user_prompt = template["user"].format(
        theme=leaf["name_en"],
        theme_name_ar=leaf["name_ar"] or "(no AR anchor)",
        taxonomy_context=f"Taxonomy parent: {leaf['parent_id']} → leaf: {leaf['id']}",
        count=COUNT_PER_LEAF,
    )
    t0 = time.time()
    try:
        raw = call_ollama_sync(user_prompt, sys_prompt, model=MODEL, temperature=0.5, timeout=180)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}
    dt = time.time() - t0
    try:
        parsed = parse_json_response(raw)
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break
    except Exception as exc:
        return {"raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt}
    concepts = parsed if isinstance(parsed, list) else []
    return {"raw": raw, "json_ok": True, "concepts": concepts, "latency_s": dt}


def evaluate_concepts(concepts: list, leaf: dict) -> list[dict]:
    """Métriques par concept."""
    out = []
    for c in concepts:
        if not isinstance(c, dict):
            continue
        nen = (c.get("name_en") or "").strip()
        nfr = (c.get("name_fr") or "").strip()
        nar = (c.get("name_ar") or "").strip()
        # name_ar 1-4 words
        ar_words = nar.split()
        # name_en : Subject+Setting pattern (≥3 words AND contains a setting preposition)
        word_count = len(nen.split())
        out.append({
            "id": c.get("id"),
            "name_en": nen,
            "name_fr": nfr,
            "name_ar": nar,
            "name_en_word_count": word_count,
            "name_en_has_setting": has_setting_marker(nen),
            "name_en_subject_setting_ok": word_count >= 3 and has_setting_marker(nen),
            "name_ar_word_count": len(ar_words),
            "name_ar_in_1_4_words": 1 <= len(ar_words) <= 4 if nar else False,
            "name_ar_has_harakat": has_harakat(nar),
            "name_ar_present": bool(nar),
            "raw": c,
        })
    return out


def main() -> int:
    print("=" * 100)
    print(f"POC-2 — generate_concepts on {MODEL}")
    print("=" * 100)

    template = load_template()

    # Charger les 15 leaves
    print(f"\n[1] Sélection de 15 feuilles ({len(SUBTOPICS)} sous-thèmes ciblés)")
    leaves = []
    for label, parent_id, category in SUBTOPICS:
        leaf = fetch_leaf_for_subtopic(parent_id)
        if leaf is None:
            print(f"  ⚠ {label} — aucune feuille trouvée pour parent_id={parent_id}")
            continue
        leaves.append({**leaf, "_label": label, "_category": category})
        print(f"  ✓ {label:<55} → {leaf['id']:<35} [{leaf['name_en']}] / [{leaf['name_ar']}]")

    if len(leaves) < 15:
        print(f"  ⚠ Seulement {len(leaves)}/15 feuilles trouvées — POC partiel")

    # Lancer 15 appels generate_concepts
    print(f"\n[2] generate_concepts ({COUNT_PER_LEAF} concepts par feuille, total visé {COUNT_PER_LEAF*len(leaves)})")
    results = []
    for i, leaf in enumerate(leaves, 1):
        print(f"  [{i:>2}/{len(leaves)}] {leaf['_category']:<22} {leaf['id']:<35} ", end="", flush=True)
        res = call_generate_concepts(leaf, template)
        if res.get("error"):
            print(f"ERR {res['error']}")
            results.append({"leaf": leaf, **res})
            continue
        if not res.get("json_ok"):
            print(f"JSON⚠ ({res['latency_s']:.1f}s)")
            results.append({"leaf": leaf, **res})
            continue
        concepts = res["concepts"]
        evals = evaluate_concepts(concepts, leaf)
        n = len(concepts)
        ok_subset = sum(1 for e in evals if e["name_en_subject_setting_ok"])
        ar_ok = sum(1 for e in evals if e["name_ar_present"] and e["name_ar_in_1_4_words"] and not e["name_ar_has_harakat"])
        print(f"{n} concepts  S+S={ok_subset}/{n}  AR={ar_ok}/{n}  ({res['latency_s']:.1f}s)")
        results.append({"leaf": leaf, **res, "evaluations": evals})

    # Agrégation
    valid = [r for r in results if r.get("json_ok")]
    total_concepts = sum(len(r.get("concepts") or []) for r in valid)
    total_evals = []
    for r in valid:
        total_evals.extend(r.get("evaluations") or [])

    n_concepts = len(total_evals)
    n_ss = sum(1 for e in total_evals if e["name_en_subject_setting_ok"])
    n_ar_present = sum(1 for e in total_evals if e["name_ar_present"])
    n_ar_words_ok = sum(1 for e in total_evals if e["name_ar_in_1_4_words"])
    n_ar_no_harakat = sum(1 for e in total_evals if not e["name_ar_has_harakat"])
    avg_lat = sum(r["latency_s"] for r in valid) / max(1, len(valid))

    summary = {
        "leaves_targeted": len(SUBTOPICS),
        "leaves_actual": len(leaves),
        "calls_total": len(results),
        "calls_json_ok": len(valid),
        "concepts_total": n_concepts,
        "name_en_subject_setting_ok": f"{n_ss}/{n_concepts}",
        "name_ar_present": f"{n_ar_present}/{n_concepts}",
        "name_ar_in_1_4_words": f"{n_ar_words_ok}/{n_concepts}",
        "name_ar_no_harakat": f"{n_ar_no_harakat}/{n_concepts}",
        "avg_latency_s": round(avg_lat, 2),
    }

    print(f"\n=== Synthèse ===")
    for k, v in summary.items():
        print(f"  {k:<32} {v}")

    # Sauvegarder JSON brut
    payload = {
        "poc": "generate-concepts",
        "date": "2026-05-05",
        "model": MODEL,
        "count_per_leaf": COUNT_PER_LEAF,
        "subtopics": SUBTOPICS,
        "leaves": leaves,
        "results": results,
        "summary": summary,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # Rapport markdown lisible humain
    md = []
    md.append("# POC-2 — `generate_concepts` sur la nouvelle taxonomie")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append(f"Test du prompt `generate_concepts` (modifié pour inclure `name_ar` + ancrage `theme_name_ar`) sur **{len(leaves)} feuilles variées** de la nouvelle taxonomie. Modèle : **{MODEL}** (T=0.5). {COUNT_PER_LEAF} concepts par feuille → {n_concepts} concepts au total. **Aucun jugement automatique de qualité linguistique** — la lisibilité est laissée à l'humain.")
    md.append("")
    md.append("## Synthèse")
    md.append("")
    md.append("| Métrique | Valeur |")
    md.append("|---|---|")
    md.append(f"| Feuilles ciblées / réelles | {summary['leaves_targeted']} / {summary['leaves_actual']} |")
    md.append(f"| Appels JSON valides | {summary['calls_json_ok']} / {summary['calls_total']} |")
    md.append(f"| Concepts générés | {n_concepts} |")
    md.append(f"| `name_en` Subject + Setting (≥3 mots + préposition) | {summary['name_en_subject_setting_ok']} |")
    md.append(f"| `name_ar` présent | {summary['name_ar_present']} |")
    md.append(f"| `name_ar` 1–4 mots | {summary['name_ar_in_1_4_words']} |")
    md.append(f"| `name_ar` sans harakat | {summary['name_ar_no_harakat']} |")
    md.append(f"| Latence moyenne / appel | {summary['avg_latency_s']} s |")
    md.append("")

    md.append("## Concepts générés (lecture humaine)")
    md.append("")

    # Grouper par catégorie
    by_cat: dict[str, list] = {}
    for r in results:
        leaf = r["leaf"]
        by_cat.setdefault(leaf["_category"], []).append(r)

    for cat, recs in by_cat.items():
        md.append(f"### {cat}")
        md.append("")
        for r in recs:
            leaf = r["leaf"]
            md.append(f"#### Feuille `{leaf['id']}` (parent: `{leaf['parent_id']}`)")
            md.append(f"- name_en : **{leaf['name_en']}**")
            md.append(f"- name_fr : **{leaf['name_fr']}**")
            md.append(f"- name_ar : **{leaf['name_ar']}** (ancre)")
            md.append("")
            if r.get("error"):
                md.append(f"❌ ERR : {r['error']}")
                md.append("")
                continue
            if not r.get("json_ok"):
                md.append(f"⚠ JSON KO : {r.get('json_error')}")
                md.append("")
                continue
            md.append("| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |")
            md.append("|---|---|---|---|")
            for i, ev in enumerate(r["evaluations"], 1):
                ss_flag = "✓" if ev["name_en_subject_setting_ok"] else "✗"
                ar_flag = ""
                if ev["name_ar_has_harakat"]:
                    ar_flag = " ⚠harakat"
                if ev["name_ar"] and not ev["name_ar_in_1_4_words"]:
                    ar_flag += " ⚠wc"
                md.append(
                    f"| {i} | `{ev['name_en']}` ({ss_flag}, {ev['name_en_word_count']}w) | `{ev['name_fr']}` | `{ev['name_ar']}` ({ev['name_ar_word_count']}w{ar_flag}) |"
                )
            md.append("")

    md.append("## Points d'attention")
    md.append("")
    md.append("- Métrique « Subject + Setting » heuristique : présence d'une préposition (`in/on/at/under/with/...`) et ≥ 3 mots dans `name_en`. Cela peut produire des faux positifs (préposition non-locative) mais détecte la majorité des titres concrets.")
    md.append("- Le caractère « 5 concepts par feuille » dépend du modèle : si le modèle renvoie moins (4) ou plus (6+), pas d'erreur.")
    md.append("- L'**ancre AR** (`theme_name_ar` passée dans le prompt) est censée orienter le LLM vers le bon mot racine arabe pour le sujet. Évaluer humainement si les `name_ar` retournés réutilisent cet ancrage ou divergent.")
    md.append("- **Aucun jugement automatique de cohérence cross-locale** dans ce rapport ; la table ci-dessus permet la revue côte à côte FR/EN/AR.")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes : `2026-05-05_poc-generate-concepts.json`")
    md.append("- Script : `scripts/poc_generate_concepts.py`")
    md.append("- Template modifié : `prompts/image_prompts.yaml::generate_concepts` (ajout `name_ar` + placeholder `theme_name_ar`)")
    md.append("- Caller modifié : `src/services/ai_jobs_sync.py` (extraction `theme_name_ar` depuis le term)")

    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
