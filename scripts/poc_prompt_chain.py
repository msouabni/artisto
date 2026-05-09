"""POC-3 — Chaîne planner → writer → validator sur 10 concepts variés.

Ancré sur la taxonomie universelle v0 (`data/taxonomy_universal_v0.yaml`) :
- 2 animaux (animaux_domestiques, animaux_sauvages)
- 2 outils (extension du domaine "metiers" / contexte atelier)
- 2 sports (extension du domaine "vie_quotidienne")
- 2 personnages fictifs (super_heros_originaux, fantasy)
- 2 corps humain / géométrie (educatif → formes + science)

La chaîne est exécutée en direct via Ollama (qwen3:8b sur les 3 templates
image_prompts.yaml : `prompt_planner`, `prompt_writer_ernie`, `validate_prompt_ernie`),
sans passer par l'API HTTP — le job-queue ne change rien à la mesure de
qualité/latence et évite la dépendance worker.

Critères de succès :
- ≥ 80 % des concepts obtiennent un score validator ≥ 75 au premier essai
- Latence totale par concept ≤ 45 s

Usage :
    python scripts/poc_prompt_chain.py
"""
from __future__ import annotations

import io
import json
import statistics
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

import yaml  # noqa: E402

from services.ollama_json import (  # noqa: E402
    apply_no_think_system,
    call_ollama_sync,
    parse_json_response,
)

REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain.json"
IMAGE_PROMPTS = PROJECT_ROOT / "prompts" / "image_prompts.yaml"

# Cible : score validator ≥ SCORE_THRESHOLD au premier essai pour ≥ SUCCESS_RATE des concepts
SCORE_THRESHOLD = 75
SUCCESS_RATE = 0.80
LATENCY_BUDGET_S = 45.0

PROFILE = "kids_coloring_lineart_v1"
WORKFLOW = "ernie-image-turbo-q8-api"   # défaut : pack ERNIE (writer/validator ernie)

# 10 concepts — anchored on universal_v0 themes ; respecte le pattern
# "Subject in/on/at <Location>" pour name_en (cf. generate_concepts rules).
CONCEPTS: list[dict] = [
    # ── Animaux ──
    {
        "category": "animaux",
        "taxonomy_anchor": "themes/animaux/animaux_domestiques",
        "name_en": "Cat in a Library",
        "keywords": "cat, library, books, bookshelves, reading",
        "tags_context": "Animaux, Animaux domestiques, Chat",
    },
    {
        "category": "animaux",
        "taxonomy_anchor": "themes/animaux/animaux_marins",
        "name_en": "Dolphin near a Coral Reef",
        "keywords": "dolphin, coral reef, ocean, fish, seaweed",
        "tags_context": "Animaux, Animaux marins, Dauphin",
    },
    # ── Outils (extension via metiers / contexte atelier) ──
    {
        "category": "outils",
        "taxonomy_anchor": "themes/personnages/metiers",
        "name_en": "Hammer on a Workbench",
        "keywords": "hammer, workbench, tools, nails, sawdust",
        "tags_context": "Personnages, Métiers, Menuisier, Outils",
    },
    {
        "category": "outils",
        "taxonomy_anchor": "themes/personnages/metiers",
        "name_en": "Paintbrush in an Art Studio",
        "keywords": "paintbrush, studio, easel, palette, canvas",
        "tags_context": "Personnages, Métiers, Artiste, Outils",
    },
    # ── Sports (extension via vie_quotidienne) ──
    {
        "category": "sports",
        "taxonomy_anchor": "themes/personnages/vie_quotidienne",
        "name_en": "Soccer Ball on a Field",
        "keywords": "soccer ball, field, goal, grass, stadium",
        "tags_context": "Personnages, Vie quotidienne, Sport, Football",
    },
    {
        "category": "sports",
        "taxonomy_anchor": "themes/personnages/vie_quotidienne",
        "name_en": "Skateboard in a Skate Park",
        "keywords": "skateboard, skate park, ramps, helmet, urban",
        "tags_context": "Personnages, Vie quotidienne, Sport, Skateboard",
    },
    # ── Personnages fictifs ──
    {
        "category": "personnages_fictifs",
        "taxonomy_anchor": "themes/personnages/super_heros_originaux",
        "name_en": "Superhero on a City Rooftop",
        "keywords": "superhero, cape, rooftop, skyline, mask",
        "tags_context": "Personnages, Super-héros originaux",
    },
    {
        "category": "personnages_fictifs",
        "taxonomy_anchor": "themes/personnages/fantasy",
        "name_en": "Wizard in a Magic Tower",
        "keywords": "wizard, tower, spellbook, crystal ball, robe",
        "tags_context": "Personnages, Fantasy, Magicien",
    },
    # ── Corps humain / géométrie ──
    {
        "category": "corps_humain_geometrie",
        "taxonomy_anchor": "themes/educatif/formes",
        "name_en": "Triangle on a School Blackboard",
        "keywords": "triangle, blackboard, classroom, chalk, geometry",
        "tags_context": "Éducatif, Formes, Géométrie",
    },
    {
        "category": "corps_humain_geometrie",
        "taxonomy_anchor": "themes/educatif/science",
        "name_en": "Skeleton in a Science Lab",
        "keywords": "skeleton, science lab, anatomy, microscope, beakers",
        "tags_context": "Éducatif, Science, Corps humain, Anatomie",
    },
]


def load_image_prompts() -> dict:
    return yaml.safe_load(IMAGE_PROMPTS.read_text(encoding="utf-8"))


def template(prompts_yaml: dict, key: str) -> dict:
    return prompts_yaml["prompts"][key]


def call_step(
    *,
    user: str,
    system: str,
    model: str,
    temperature: float,
    timeout: int,
) -> tuple[str, float]:
    """Appel Ollama sync avec mesure de latence (think-tags strippés en aval)."""
    sys_p = apply_no_think_system(model, system)
    t0 = time.time()
    raw = call_ollama_sync(user, sys_p, model=model, temperature=temperature, timeout=timeout)
    return raw, time.time() - t0


def run_chain(concept: dict, prompts_yaml: dict) -> dict:
    """Exécute planner → writer (ernie) → validator (ernie) sur un concept."""
    out: dict = {
        "concept": concept,
        "errors": [],
        "latencies": {},
    }

    # ── Étape 1 : planner ──
    planner_tpl = template(prompts_yaml, "prompt_planner")
    p_user = planner_tpl["user"].format(
        profile=PROFILE,
        keywords=concept["keywords"],
        title=concept["name_en"],
        tags_context=concept["tags_context"],
    )
    try:
        p_raw, p_dt = call_step(
            user=p_user,
            system=planner_tpl["system"],
            model=planner_tpl.get("model"),
            temperature=float(planner_tpl.get("temperature", 0.35)),
            timeout=int(planner_tpl.get("timeout", 180)),
        )
        plan = parse_json_response(p_raw)
        if not isinstance(plan, dict):
            raise ValueError(f"plan n'est pas un dict : {type(plan).__name__}")
        out["plan"] = plan
        out["plan_raw"] = p_raw
        out["plan_model"] = planner_tpl.get("model")
        out["latencies"]["planner_s"] = p_dt
    except Exception as exc:
        out["errors"].append(f"planner: {type(exc).__name__}: {exc}")
        return out

    # ── Étape 2 : writer ernie ──
    writer_tpl = template(prompts_yaml, "prompt_writer_ernie")
    w_user = writer_tpl["user"].format(plan_json=json.dumps(plan, ensure_ascii=False, indent=2))
    try:
        w_raw, w_dt = call_step(
            user=w_user,
            system=writer_tpl["system"],
            model=writer_tpl.get("model"),
            temperature=float(writer_tpl.get("temperature", 0.4)),
            timeout=int(writer_tpl.get("timeout", 180)),
        )
        parsed_w = parse_json_response(w_raw)
        if not isinstance(parsed_w, dict):
            raise ValueError(f"writer output pas un dict : {type(parsed_w).__name__}")
        final_prompt = (parsed_w.get("prompt") or "").strip()
        if not final_prompt:
            raise ValueError("writer n'a pas renvoyé de champ 'prompt'")
        out["final_prompt"] = final_prompt
        out["negative_prompt"] = (parsed_w.get("negative_prompt") or "").strip()
        out["writer_raw"] = w_raw
        out["writer_model"] = writer_tpl.get("model")
        out["latencies"]["writer_s"] = w_dt
    except Exception as exc:
        out["errors"].append(f"writer: {type(exc).__name__}: {exc}")
        return out

    # ── Étape 3 : validator ernie ──
    validator_tpl = template(prompts_yaml, "validate_prompt_ernie")
    v_user = validator_tpl["user"].format(profile=PROFILE, prompt=final_prompt)
    try:
        v_raw, v_dt = call_step(
            user=v_user,
            system=validator_tpl["system"],
            model=validator_tpl.get("model"),
            temperature=float(validator_tpl.get("temperature", 0.2)),
            timeout=int(validator_tpl.get("timeout", 120)),
        )
        validation = parse_json_response(v_raw)
        if not isinstance(validation, dict):
            raise ValueError(f"validator output pas un dict : {type(validation).__name__}")
        score = validation.get("score")
        if isinstance(score, bool):
            score = int(score)
        elif score is not None:
            try:
                score = int(score)
            except (TypeError, ValueError):
                score = None
        score = max(0, min(100, score if score is not None else 0))
        checks = validation.get("checks") if isinstance(validation.get("checks"), list) else []
        recs = validation.get("recommendations") if isinstance(validation.get("recommendations"), list) else []
        out["validator"] = {
            "score": score,
            "checks": checks,
            "recommendations": recs,
        }
        out["validator_raw"] = v_raw
        out["validator_model"] = validator_tpl.get("model")
        out["latencies"]["validator_s"] = v_dt
    except Exception as exc:
        out["errors"].append(f"validator: {type(exc).__name__}: {exc}")
        return out

    out["latencies"]["total_s"] = (
        out["latencies"]["planner_s"]
        + out["latencies"]["writer_s"]
        + out["latencies"]["validator_s"]
    )
    return out


def main() -> int:
    print("=" * 100)
    print(f"POC-3 — chaîne planner → writer → validator sur {len(CONCEPTS)} concepts variés")
    print("=" * 100)

    prompts_yaml = load_image_prompts()
    planner_model = prompts_yaml["prompts"]["prompt_planner"].get("model")
    writer_model = prompts_yaml["prompts"]["prompt_writer_ernie"].get("model")
    validator_model = prompts_yaml["prompts"]["validate_prompt_ernie"].get("model")
    print(f"Modèles : planner={planner_model} · writer={writer_model} · validator={validator_model}")
    print(f"Profile : {PROFILE} · workflow : {WORKFLOW}")
    print(f"Cible succès : ≥ {int(SUCCESS_RATE * 100)}% concepts avec score ≥ {SCORE_THRESHOLD} ; latence ≤ {LATENCY_BUDGET_S}s")
    print()

    results: list[dict] = []
    for i, concept in enumerate(CONCEPTS, 1):
        print(f"[{i:>2}/{len(CONCEPTS)}] {concept['category']:<25} {concept['name_en']}")
        t_start = time.time()
        res = run_chain(concept, prompts_yaml)
        wall = time.time() - t_start
        if res.get("errors"):
            print(f"        ❌ {' | '.join(res['errors'])}")
        else:
            score = res["validator"]["score"]
            checks = res["validator"]["checks"]
            n_pass = sum(1 for c in checks if isinstance(c, dict) and bool(c.get("pass")))
            n_total = len(checks)
            lat = res["latencies"]
            print(
                f"        score={score:>3}  checks={n_pass}/{n_total}  "
                f"P={lat['planner_s']:.1f}s W={lat['writer_s']:.1f}s V={lat['validator_s']:.1f}s "
                f"total={lat['total_s']:.1f}s (wall={wall:.1f}s)"
            )
        results.append(res)

    # ── Agrégats ──
    successful = [r for r in results if not r.get("errors")]
    scores = [r["validator"]["score"] for r in successful]
    totals = [r["latencies"]["total_s"] for r in successful]
    n_above_thresh = sum(1 for s in scores if s >= SCORE_THRESHOLD)
    rate_thresh = (n_above_thresh / len(CONCEPTS)) if CONCEPTS else 0.0
    n_under_budget = sum(1 for t in totals if t <= LATENCY_BUDGET_S)
    rate_budget = (n_under_budget / len(CONCEPTS)) if CONCEPTS else 0.0

    p50_total = statistics.median(totals) if totals else None
    p95_total = (sorted(totals)[max(0, int(round(0.95 * (len(totals) - 1))))] if totals else None)

    # Distribution checks (par id)
    check_pass: dict = {}
    check_total: dict = {}
    for r in successful:
        for c in r["validator"]["checks"]:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or "?")
            check_total[cid] = check_total.get(cid, 0) + 1
            if bool(c.get("pass")):
                check_pass[cid] = check_pass.get(cid, 0) + 1

    print()
    print("─── Agrégats ───────────────────────────────────────────────────────────────────")
    print(f"Erreurs chaîne : {len(CONCEPTS) - len(successful)}/{len(CONCEPTS)}")
    print(f"Concepts ≥ {SCORE_THRESHOLD} : {n_above_thresh}/{len(CONCEPTS)} ({rate_thresh*100:.0f}%)  [cible ≥ {int(SUCCESS_RATE*100)}%]")
    print(f"Concepts ≤ {LATENCY_BUDGET_S}s : {n_under_budget}/{len(CONCEPTS)} ({rate_budget*100:.0f}%)")
    if scores:
        print(f"Scores : min={min(scores)} median={statistics.median(scores):.0f} max={max(scores)}")
    if totals:
        print(f"Latence totale : p50={p50_total:.1f}s p95={p95_total:.1f}s mean={statistics.mean(totals):.1f}s")

    payload = {
        "poc": "prompt-chain",
        "date": "2026-05-05",
        "models": {"planner": planner_model, "writer": writer_model, "validator": validator_model},
        "profile": PROFILE,
        "workflow": WORKFLOW,
        "success_threshold_score": SCORE_THRESHOLD,
        "success_rate_target": SUCCESS_RATE,
        "latency_budget_s": LATENCY_BUDGET_S,
        "concepts": CONCEPTS,
        "results": results,
        "aggregates": {
            "n_concepts": len(CONCEPTS),
            "n_chain_errors": len(CONCEPTS) - len(successful),
            "n_above_threshold": n_above_thresh,
            "rate_threshold": rate_thresh,
            "n_under_budget": n_under_budget,
            "rate_budget": rate_budget,
            "score_min": min(scores) if scores else None,
            "score_median": statistics.median(scores) if scores else None,
            "score_max": max(scores) if scores else None,
            "latency_total_p50": p50_total,
            "latency_total_p95": p95_total,
            "latency_total_mean": statistics.mean(totals) if totals else None,
            "checks_pass": check_pass,
            "checks_total": check_total,
        },
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nJSON brut → {REPORT_JSON}")

    # ── Markdown ──
    success_ok = rate_thresh >= SUCCESS_RATE
    latency_ok = (p50_total is not None and p50_total <= LATENCY_BUDGET_S)

    md: list[str] = []
    md.append("# POC-3 — Chaîne planner → writer → validator")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append(
        f"Validation de la chaîne **planner → writer → validator** sur **{len(CONCEPTS)} concepts variés** "
        "issus de la taxonomie universelle v0 (`data/taxonomy_universal_v0.yaml`). "
        "Catégories couvertes : 2 animaux, 2 outils, 2 sports, 2 personnages fictifs, 2 corps humain / géométrie. "
        f"Modèles : planner=`{planner_model}` · writer=`{writer_model}` · validator=`{validator_model}` "
        f"(templates `prompt_planner` + `prompt_writer_ernie` + `validate_prompt_ernie`, profile `{PROFILE}`). "
        "Appels Ollama directs (sync) — l'API job-queue ne change ni la qualité ni la latence et ajoute "
        "une dépendance worker non requise pour ce POC."
    )
    md.append("")
    md.append("## Critères de succès")
    md.append(f"- ≥ **{int(SUCCESS_RATE * 100)} %** des concepts obtiennent un score validator ≥ **{SCORE_THRESHOLD}** au premier essai")
    md.append(f"- Latence totale par concept ≤ **{LATENCY_BUDGET_S} s**")
    md.append("")

    md.append("## Résultats par concept")
    md.append("")
    md.append("| # | Catégorie | name_en | Score | Checks pass | Planner | Writer | Validator | Total | Erreurs |")
    md.append("|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for i, r in enumerate(results, 1):
        c = r["concept"]
        if r.get("errors"):
            md.append(
                f"| {i} | {c['category']} | {c['name_en']} | — | — | — | — | — | — | "
                f"{' / '.join(r['errors'])} |"
            )
            continue
        s = r["validator"]["score"]
        ck = r["validator"]["checks"]
        npass = sum(1 for x in ck if isinstance(x, dict) and bool(x.get("pass")))
        ntot = len(ck)
        lat = r["latencies"]
        md.append(
            f"| {i} | {c['category']} | {c['name_en']} | **{s}** | {npass}/{ntot} | "
            f"{lat['planner_s']:.1f}s | {lat['writer_s']:.1f}s | {lat['validator_s']:.1f}s | "
            f"**{lat['total_s']:.1f}s** | — |"
        )
    md.append("")

    md.append("## Agrégats")
    md.append("")
    md.append(f"- Erreurs chaîne : **{len(CONCEPTS) - len(successful)}/{len(CONCEPTS)}**")
    md.append(
        f"- Concepts avec score ≥ {SCORE_THRESHOLD} : **{n_above_thresh}/{len(CONCEPTS)} "
        f"({rate_thresh*100:.0f} %)** — cible ≥ {int(SUCCESS_RATE*100)} % "
        f"→ {'✅' if success_ok else '❌'}"
    )
    md.append(
        f"- Concepts avec latence ≤ {LATENCY_BUDGET_S}s : **{n_under_budget}/{len(CONCEPTS)} "
        f"({rate_budget*100:.0f} %)**"
    )
    if scores:
        md.append(f"- Score : min={min(scores)} · médiane={statistics.median(scores):.0f} · max={max(scores)}")
    if totals:
        md.append(
            f"- Latence totale : p50=**{p50_total:.1f}s** "
            f"({'✅' if latency_ok else '❌'} cible ≤ {LATENCY_BUDGET_S}s) · "
            f"p95={p95_total:.1f}s · moyenne={statistics.mean(totals):.1f}s"
        )
    md.append("")

    md.append("### Distribution des checks validator")
    md.append("")
    md.append("| Check | Pass | Total | % |")
    md.append("|---|---:|---:|---:|")
    for cid in sorted(check_total.keys()):
        npass = check_pass.get(cid, 0)
        ntot = check_total[cid]
        pct = (npass / ntot * 100) if ntot else 0.0
        md.append(f"| {cid} | {npass} | {ntot} | {pct:.0f}% |")
    md.append("")

    # Top 3 / Bottom 3 (parmi les succès, sur score puis latence inverse)
    sorted_by_score = sorted(
        successful,
        key=lambda r: (r["validator"]["score"], -r["latencies"]["total_s"]),
        reverse=True,
    )
    top3 = sorted_by_score[:3]
    bot3 = list(reversed(sorted_by_score[-3:])) if len(sorted_by_score) >= 3 else []

    def _block(title: str, items: list[dict]) -> None:
        md.append(f"## {title}")
        md.append("")
        for r in items:
            c = r["concept"]
            v = r["validator"]
            md.append(f"### {c['category']} · {c['name_en']}")
            md.append(
                f"- Score : **{v['score']}** · Total : {r['latencies']['total_s']:.1f}s "
                f"(P {r['latencies']['planner_s']:.1f}s · W {r['latencies']['writer_s']:.1f}s · "
                f"V {r['latencies']['validator_s']:.1f}s)"
            )
            md.append("")
            md.append("**Prompt final (writer ernie) :**")
            md.append("")
            md.append("```")
            md.append(r.get("final_prompt", "").strip())
            md.append("```")
            md.append("")
            recs = v.get("recommendations") or []
            if recs:
                md.append("**Recommandations validator :**")
                for rec in recs:
                    md.append(f"- {rec}")
                md.append("")
            failed = [c for c in v.get("checks", []) if isinstance(c, dict) and not bool(c.get("pass"))]
            if failed:
                md.append("**Checks échoués :**")
                for fc in failed:
                    md.append(f"- `{fc.get('id', '?')}` : {fc.get('detail', '')}")
                md.append("")

    if top3:
        _block("Top 3 — meilleurs scores", top3)
    if bot3:
        _block("Bottom 3 — moins bons scores", bot3)

    md.append("## Verdict")
    md.append("")
    if success_ok and latency_ok:
        md.append(
            "✅ **Chaîne prête pour P2.** Les deux critères sont remplis : "
            f"{rate_thresh*100:.0f} % des concepts dépassent le score {SCORE_THRESHOLD} "
            f"(cible ≥ {int(SUCCESS_RATE*100)} %) et la latence p50 reste sous le budget de {LATENCY_BUDGET_S}s."
        )
    else:
        issues: list[str] = []
        if not success_ok:
            issues.append(
                f"taux de succès {rate_thresh*100:.0f} % < cible {int(SUCCESS_RATE*100)} % "
                f"(seuil score {SCORE_THRESHOLD})"
            )
        if not latency_ok and p50_total is not None:
            issues.append(f"latence p50 {p50_total:.1f}s > budget {LATENCY_BUDGET_S}s")
        md.append("⚠ **Ajustements nécessaires avant P2.** " + " ; ".join(issues) + ".")
        md.append("")
        md.append("Pistes d'arbitrage :")
        if not success_ok:
            md.append("- Renforcer le writer ernie sur la fidélité title (subject + setting littéraux dans le 1er paragraphe)")
            md.append("- Exiger un check explicite « scene fidelity » dans le validator (id supplémentaire)")
            md.append("- Examiner les recommandations récurrentes ci-dessus avant de tuner")
        if not latency_ok:
            md.append(f"- Tester un fallback writer plus rapide (qwen3.5:4b) sur la chaîne")
            md.append("- Paralléliser writer et validator si les heuristiques le permettent")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes : `2026-05-05_poc-prompt-chain.json` (concepts + plans + prompts + validations + raw responses)")
    md.append("- Script : `scripts/poc_prompt_chain.py`")
    md.append(f"- Templates : `prompts/image_prompts.yaml` (prompt_planner, prompt_writer_ernie, validate_prompt_ernie)")
    md.append(f"- Modèles testés : planner=`{planner_model}` · writer=`{writer_model}` · validator=`{validator_model}`")
    md.append("- Plan de POC : `docs/poc-plan.md` § POC-3")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
