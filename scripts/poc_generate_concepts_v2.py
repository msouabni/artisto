"""POC-2 v2 — generate_concepts après affinage du prompt.

Tests ciblés sur les 4 termes problématiques de la v1 :
- claw_hammer            (outil — risque setting implausible "hammer in kitchen")
- firefighter_with_hose  (profession — risque sur-traduction FR)
- elsa_from_frozen       (personnage — S+S 2/5 en v1)
- letter_a_with_apple    (alphabet — S+S 4/5 en v1)

Compare v1 (résultats sauvés) vs v2 (prompt révisé) sur les mêmes 4 leaves,
mêmes hyper-paramètres (T=0.5, qwen3.5:4b).

Usage :
    python scripts/poc_generate_concepts_v2.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

# Réutilise utils du v1
from poc_generate_concepts import (  # noqa: E402
    HARAKAT_RE,  # noqa: F401
    SETTING_MARKERS,  # noqa: F401
    has_harakat, has_setting_marker,
    fetch_leaf_for_subtopic,
    load_template,
    call_generate_concepts,
    evaluate_concepts,
    MODEL, COUNT_PER_LEAF,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-generate-concepts-v2.json"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-generate-concepts-v2.md"
V1_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-generate-concepts.json"

# Les 4 termes problématiques identifiés en v1 (par parent_id du sous-thème).
TARGETS = [
    ("hand_tools",                    "Outils",          "Setting plausibility"),
    ("security_and_emergency",        "Professions",     "FR translation quality"),
    ("disney_universe",               "Personnages",     "Subject+Setting strict"),
    ("english_alphabet_illustrated",  "Alphabet",        "Subject+Setting strict"),
]


def fetch_specific_leaf(parent_id: str, target_id: str) -> dict | None:
    """Cherche le leaf exact (pour reproduire la même feuille qu'en v1)."""
    from sqlalchemy import text
    from api.db import ENGINE
    from api.helpers import get_i18n
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name_i18n, parent_id FROM term WHERE id = :id"),
            {"id": target_id},
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


def load_v1_for_leaf(leaf_id: str) -> dict | None:
    if not V1_JSON.exists():
        return None
    data = json.loads(V1_JSON.read_text(encoding="utf-8"))
    for r in data.get("results", []):
        if r.get("leaf", {}).get("id") == leaf_id:
            return r
    return None


def main() -> int:
    print("=" * 100)
    print(f"POC-2 v2 — generate_concepts (prompt affiné) on {MODEL}")
    print("=" * 100)

    template = load_template()

    # Map sub-topic → leaf id testé en v1
    target_leaf_ids = {
        "hand_tools": "claw_hammer",
        "security_and_emergency": "firefighter_with_hose",
        "disney_universe": "elsa_from_frozen",
        "english_alphabet_illustrated": "letter_a_with_apple",
    }

    print("\n[1] Re-fetch des 4 feuilles ciblées")
    leaves: list[dict] = []
    for parent_id, category, focus in TARGETS:
        leaf_id = target_leaf_ids[parent_id]
        leaf = fetch_specific_leaf(parent_id, leaf_id)
        if leaf is None:
            print(f"  ⚠ {leaf_id} introuvable")
            continue
        leaves.append({**leaf, "_category": category, "_focus": focus})
        print(f"  ✓ {category:<14} | {focus:<32} → {leaf['id']}  [{leaf['name_en']}] / [{leaf['name_ar']}]")

    print(f"\n[2] generate_concepts v2 ({COUNT_PER_LEAF} concepts × {len(leaves)} leaves)")
    results_v2 = []
    for i, leaf in enumerate(leaves, 1):
        print(f"  [{i}/{len(leaves)}] {leaf['id']:<35} ", end="", flush=True)
        res = call_generate_concepts(leaf, template)
        if res.get("error"):
            print(f"ERR {res['error']}")
            results_v2.append({"leaf": leaf, **res})
            continue
        if not res.get("json_ok"):
            print(f"JSON⚠")
            results_v2.append({"leaf": leaf, **res})
            continue
        evals = evaluate_concepts(res["concepts"], leaf)
        n = len(res["concepts"])
        ss = sum(1 for e in evals if e["name_en_subject_setting_ok"])
        ar_ok = sum(1 for e in evals if e["name_ar_present"] and e["name_ar_in_1_4_words"] and not e["name_ar_has_harakat"])
        ar3 = sum(1 for e in evals if 1 <= e["name_ar_word_count"] <= 3)
        print(f"{n} concepts  S+S={ss}/{n}  AR_ok={ar_ok}/{n}  AR≤3w={ar3}/{n}  ({res['latency_s']:.1f}s)")
        results_v2.append({"leaf": leaf, **res, "evaluations": evals})

    # Charger les résultats v1 pour ces 4 mêmes leaves
    print("\n[3] Comparaison v1 ↔ v2")
    comparison = []
    for r2 in results_v2:
        leaf_id = r2["leaf"]["id"]
        r1 = load_v1_for_leaf(leaf_id)
        comparison.append({"leaf_id": leaf_id, "v1": r1, "v2": r2})

    payload = {
        "poc": "generate-concepts-v2",
        "date": "2026-05-05",
        "model": MODEL,
        "count_per_leaf": COUNT_PER_LEAF,
        "targets": TARGETS,
        "leaves": leaves,
        "results_v2": results_v2,
        "comparison": comparison,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # ─── MD ─── lecture humaine côte à côte
    md = []
    md.append("# POC-2 v2 — `generate_concepts` après affinage du prompt")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append("Affinage du prompt `generate_concepts` pour adresser 4 défauts identifiés en v1 (cf. `2026-05-05_poc-generate-concepts.md`) :")
    md.append("")
    md.append("1. **Setting plausible** — interdire les lieux non naturels pour le sujet (ex. `Hammer in a Kitchen`).")
    md.append("2. **Format Subject+Setting strict** — `<Subject> <preposition> a <Location>` ; verbes d'action exclus du `name_en` (vont dans `description_en`).")
    md.append("3. **`name_ar` 1-3 mots** (resserré de 1-4) pour les sujets complexes.")
    md.append("4. **Qualité FR** — exemple négatif explicite contre les sur-traductions (firefighter → pompier, pas \"infirmier de pompier\").")
    md.append("")
    md.append("Test sur les 4 termes problématiques de la v1 :")
    md.append(f"- `claw_hammer` (focus : setting plausibility)")
    md.append(f"- `firefighter_with_hose` (focus : FR translation quality)")
    md.append(f"- `elsa_from_frozen` (focus : Subject+Setting strict — 2/5 en v1)")
    md.append(f"- `letter_a_with_apple` (focus : Subject+Setting strict — 4/5 en v1)")
    md.append("")

    md.append("## Synthèse v1 vs v2")
    md.append("")
    md.append("| Feuille | Focus | v1 S+S | v2 S+S | v1 AR≤4w | v2 AR≤3w | v1 latence | v2 latence |")
    md.append("|---|---|---|---|---|---|---|---|")
    for c in comparison:
        leaf_id = c["leaf_id"]
        r1 = c["v1"] or {}
        r2 = c["v2"]
        focus = next((t[2] for t in TARGETS if target_leaf_ids[t[0]] == leaf_id), "")

        def _stats(r):
            if not r or not r.get("json_ok"):
                return ("—", "—", "—")
            evs = r.get("evaluations") or []
            n = len(evs)
            ss = sum(1 for e in evs if e.get("name_en_subject_setting_ok"))
            ar = sum(1 for e in evs if e.get("name_ar_in_1_4_words"))
            return (f"{ss}/{n}", f"{ar}/{n}", f"{r.get('latency_s', 0):.1f}s")

        ss1, ar1, lat1 = _stats(r1)
        # Pour v2 on calcule AR≤3 mots
        evs2 = r2.get("evaluations") or []
        n2 = len(evs2)
        ss2 = f"{sum(1 for e in evs2 if e.get('name_en_subject_setting_ok'))}/{n2}" if evs2 else "—"
        ar3 = f"{sum(1 for e in evs2 if 1 <= e.get('name_ar_word_count', 0) <= 3)}/{n2}" if evs2 else "—"
        lat2 = f"{r2.get('latency_s', 0):.1f}s" if r2.get("json_ok") else "—"
        md.append(f"| `{leaf_id}` | {focus} | {ss1} | {ss2} | {ar1} | {ar3} | {lat1} | {lat2} |")
    md.append("")

    # Détail par feuille avec comparaison côte à côte
    md.append("## Comparaison détaillée v1 ↔ v2")
    md.append("")
    for c in comparison:
        leaf_id = c["leaf_id"]
        r2 = c["v2"]
        r1 = c["v1"] or {}
        leaf = r2["leaf"]
        md.append(f"### `{leaf_id}` — {leaf['name_en']} / {leaf['name_fr']} / {leaf['name_ar']}")
        md.append("")
        md.append("Focus : **" + next((t[2] for t in TARGETS if target_leaf_ids[t[0]] == leaf_id), "") + "**")
        md.append("")

        md.append("**v1 (prompt initial)**")
        md.append("")
        if not r1.get("json_ok"):
            md.append("_(v1 absent ou KO)_")
        else:
            md.append("| # | name_en | name_fr | name_ar |")
            md.append("|---|---|---|---|")
            for i, ev in enumerate(r1.get("evaluations") or [], 1):
                md.append(f"| {i} | `{ev['name_en']}` | `{ev['name_fr']}` | `{ev['name_ar']}` ({ev['name_ar_word_count']}w) |")
        md.append("")

        md.append("**v2 (prompt affiné)**")
        md.append("")
        if r2.get("error"):
            md.append(f"❌ ERR : {r2['error']}")
        elif not r2.get("json_ok"):
            md.append(f"⚠ JSON KO : {r2.get('json_error')}")
        else:
            md.append("| # | name_en (S+S?) | name_fr | name_ar (mots / harakat) |")
            md.append("|---|---|---|---|")
            for i, ev in enumerate(r2.get("evaluations") or [], 1):
                ss_flag = "✓" if ev["name_en_subject_setting_ok"] else "✗"
                ar_flag = ""
                if ev["name_ar_has_harakat"]:
                    ar_flag = " ⚠harakat"
                ar_wc = ev["name_ar_word_count"]
                wc_flag = "✓" if 1 <= ar_wc <= 3 else " ⚠>3w"
                md.append(
                    f"| {i} | `{ev['name_en']}` ({ss_flag}, {ev['name_en_word_count']}w) | `{ev['name_fr']}` | `{ev['name_ar']}` ({ar_wc}w {wc_flag}{ar_flag}) |"
                )
        md.append("")

    md.append("## Points d'attention")
    md.append("")
    md.append("- **Métrique S+S** : présence d'une préposition locative (`in/on/at/under/inside/near/by/over/beside/with/...`) et ≥3 mots dans `name_en`. Une préposition légitime non-locative peut produire un faux positif. Évaluation humaine recommandée pour la cohérence sémantique.")
    md.append("- **`name_ar` 1-3 mots** : nouvelle contrainte — le modèle peut continuer à produire 4-6 mots sur des sujets complexes (ex. \"Spider-Man dans un combat\"). Si le taux d'échec dépasse 30 %, ajouter un post-process de troncature ou imposer une regen.")
    md.append("- **Pas de jugement automatique de qualité linguistique FR/AR** dans ce rapport. Lire les tableaux côte à côte ci-dessus pour vérifier la cohérence.")
    md.append("- T=0.5 (non déterministe) : les résultats v1 et v2 ne sont pas strictement comparables sur le même seed, mais les **patterns** (S+S, longueurs, etc.) sont mesurables sur 5 concepts × 4 leaves = 20 items.")
    md.append("")
    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes v2 : `2026-05-05_poc-generate-concepts-v2.json`")
    md.append("- Données brutes v1 : `2026-05-05_poc-generate-concepts.json` (15 leaves, 75 concepts)")
    md.append("- Script v2 : `scripts/poc_generate_concepts_v2.py`")
    md.append("- Template modifié : `prompts/image_prompts.yaml::generate_concepts`")
    md.append("- Rapport v1 : `docs/reports/2026-05-05_poc-generate-concepts.md`")

    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
