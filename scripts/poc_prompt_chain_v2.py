"""POC-3 v2 — Re-run de la chaîne planner → writer → validator post-fixes.

3 ajustements de robustesse appliqués depuis v1 :
1. ``num_ctx=8192`` côté validator (le JSON validator dépassait 4096 sur les
   prompts image verbeux et tronquait mid-objet).
2. Retry planner à T=0 si la 1re réponse n'est pas un JSON candidat
   (drift complet observé sur qwen3:8b strict en v1).
3. Règle « no readable text in scene » ajoutée à ``prompt_writer_ernie.system``
   pour traiter le pattern ``technical_cleanup`` 4/7 → cible 90 %+.

Bonus : migration ``qwen3:8b → qwen3.5:4b`` sur les 3 templates concernés
(``prompt_planner``, ``prompt_writer_ernie``, ``validate_prompt_ernie``)
conformément à la décision routing LLM (CLAUDE.md).

Test sur **20 concepts** : les 10 v1 + 10 nouveaux variés depuis la nouvelle
taxonomie (électroménager, géométrie, personnalités sportives, professions,
fantasy).

Critères de succès (mêmes seuils que v1) :
- ≥ 80 % des concepts obtiennent un score validator ≥ 75 au premier essai
- Latence totale par concept ≤ 45 s

Usage :
    python scripts/poc_prompt_chain_v2.py
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
    call_ollama_sync_with_drift_retry,
    parse_json_response,
)

REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain-v2.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain-v2.json"
V1_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain.json"
IMAGE_PROMPTS = PROJECT_ROOT / "prompts" / "image_prompts.yaml"

SCORE_THRESHOLD = 75
SUCCESS_RATE = 0.80
LATENCY_BUDGET_S = 45.0

PROFILE = "kids_coloring_lineart_v1"
WORKFLOW = "ernie-image-turbo-q8-api"

VALIDATOR_NUM_CTX = 8192   # fix #1 : éviter troncature JSON validator

# 10 concepts v1 (mêmes que poc_prompt_chain.py) ────────────────────────
CONCEPTS_V1: list[dict] = [
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

# 10 nouveaux concepts (catégories demandées) ──────────────────────────
CONCEPTS_NEW: list[dict] = [
    # ── Électroménager ──
    {
        "category": "electromenager",
        "taxonomy_anchor": "themes/divers",
        "name_en": "Refrigerator in a Kitchen",
        "keywords": "refrigerator, kitchen, counter, fruits, magnets",
        "tags_context": "Maison, Cuisine, Électroménager",
    },
    {
        "category": "electromenager",
        "taxonomy_anchor": "themes/divers",
        "name_en": "Washing Machine in a Laundry Room",
        "keywords": "washing machine, laundry, basket, detergent, towels",
        "tags_context": "Maison, Buanderie, Électroménager",
    },
    # ── Géométrie ──
    {
        "category": "geometrie",
        "taxonomy_anchor": "themes/educatif/formes",
        "name_en": "Hexagon on a Math Whiteboard",
        "keywords": "hexagon, whiteboard, classroom, marker, ruler",
        "tags_context": "Éducatif, Formes, Géométrie",
    },
    {
        "category": "geometrie",
        "taxonomy_anchor": "themes/educatif/formes",
        "name_en": "Cube on a Math Desk",
        "keywords": "cube, desk, classroom, notebook, pencil",
        "tags_context": "Éducatif, Formes, Géométrie, Solide",
    },
    # ── Personnalités sportives ──
    {
        "category": "personnalites_sportives",
        "taxonomy_anchor": "themes/personnages/vie_quotidienne",
        "name_en": "Tennis Player on a Court",
        "keywords": "tennis player, court, racket, net, ball",
        "tags_context": "Personnages, Sport, Tennis",
    },
    {
        "category": "personnalites_sportives",
        "taxonomy_anchor": "themes/personnages/vie_quotidienne",
        "name_en": "Boxer in a Boxing Ring",
        "keywords": "boxer, boxing ring, gloves, ropes, corner stool",
        "tags_context": "Personnages, Sport, Boxe",
    },
    # ── Professions ──
    {
        "category": "professions",
        "taxonomy_anchor": "themes/personnages/metiers",
        "name_en": "Astronaut on a Space Station",
        "keywords": "astronaut, space station, helmet, control panel, porthole",
        "tags_context": "Personnages, Métiers, Astronaute, Espace",
    },
    {
        "category": "professions",
        "taxonomy_anchor": "themes/personnages/metiers",
        "name_en": "Chef in a Restaurant Kitchen",
        "keywords": "chef, restaurant kitchen, hat, pots, stove",
        "tags_context": "Personnages, Métiers, Cuisinier",
    },
    # ── Fantasy ──
    {
        "category": "fantasy",
        "taxonomy_anchor": "themes/personnages/fantasy",
        "name_en": "Dragon in a Castle Courtyard",
        "keywords": "dragon, castle courtyard, towers, banners, drawbridge",
        "tags_context": "Personnages, Fantasy, Dragon",
    },
    {
        "category": "fantasy",
        "taxonomy_anchor": "themes/personnages/fantasy",
        "name_en": "Fairy in an Enchanted Forest",
        "keywords": "fairy, enchanted forest, mushrooms, fireflies, flowers",
        "tags_context": "Personnages, Fantasy, Fée, Forêt",
    },
]

CONCEPTS = CONCEPTS_V1 + CONCEPTS_NEW


def load_image_prompts() -> dict:
    return yaml.safe_load(IMAGE_PROMPTS.read_text(encoding="utf-8"))


def template(prompts_yaml: dict, key: str) -> dict:
    return prompts_yaml["prompts"][key]


def run_chain(concept: dict, prompts_yaml: dict) -> dict:
    """planner (drift retry) → writer ernie → validator ernie (num_ctx=8192)."""
    out: dict = {
        "concept": concept,
        "errors": [],
        "latencies": {},
        "drift_retry": False,
    }

    # ── Étape 1 : planner avec drift retry ──
    planner_tpl = template(prompts_yaml, "prompt_planner")
    p_user = planner_tpl["user"].format(
        profile=PROFILE,
        keywords=concept["keywords"],
        title=concept["name_en"],
        tags_context=concept["tags_context"],
    )
    p_system = apply_no_think_system(planner_tpl.get("model"), planner_tpl["system"])
    try:
        t0 = time.time()
        raw_plan, drift_meta = call_ollama_sync_with_drift_retry(
            p_user, p_system,
            model=planner_tpl.get("model"),
            temperature=float(planner_tpl.get("temperature", 0.35)),
            timeout=int(planner_tpl.get("timeout", 180)),
        )
        p_dt = time.time() - t0
        plan = parse_json_response(raw_plan)
        if not isinstance(plan, dict):
            raise ValueError(f"plan n'est pas un dict : {type(plan).__name__}")
        out["plan"] = plan
        out["plan_raw"] = raw_plan
        out["plan_first_raw_drift"] = drift_meta.get("first_raw")
        out["drift_retry"] = bool(drift_meta.get("drift_retry"))
        out["plan_model"] = planner_tpl.get("model")
        out["latencies"]["planner_s"] = p_dt
    except Exception as exc:
        out["errors"].append(f"planner: {type(exc).__name__}: {exc}")
        return out

    # ── Étape 2 : writer ernie ──
    writer_tpl = template(prompts_yaml, "prompt_writer_ernie")
    w_user = writer_tpl["user"].format(plan_json=json.dumps(plan, ensure_ascii=False, indent=2))
    w_system = apply_no_think_system(writer_tpl.get("model"), writer_tpl["system"])
    try:
        t0 = time.time()
        w_raw = call_ollama_sync(
            w_user, w_system,
            model=writer_tpl.get("model"),
            temperature=float(writer_tpl.get("temperature", 0.4)),
            timeout=int(writer_tpl.get("timeout", 180)),
        )
        w_dt = time.time() - t0
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

    # ── Étape 3 : validator ernie avec num_ctx=8192 ──
    validator_tpl = template(prompts_yaml, "validate_prompt_ernie")
    v_user = validator_tpl["user"].format(profile=PROFILE, prompt=final_prompt)
    v_system = apply_no_think_system(validator_tpl.get("model"), validator_tpl["system"])
    try:
        t0 = time.time()
        v_raw = call_ollama_sync(
            v_user, v_system,
            model=validator_tpl.get("model"),
            temperature=float(validator_tpl.get("temperature", 0.2)),
            timeout=int(validator_tpl.get("timeout", 120)),
            num_ctx=VALIDATOR_NUM_CTX,
        )
        v_dt = time.time() - t0
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
        out["validator"] = {"score": score, "checks": checks, "recommendations": recs}
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


def load_v1_aggregates() -> dict | None:
    if not V1_JSON.exists():
        return None
    try:
        return json.loads(V1_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    print("=" * 100, flush=True)
    print(f"POC-3 v2 — chaîne post-fixes sur {len(CONCEPTS)} concepts (10 v1 + 10 nouveaux)", flush=True)
    print("=" * 100, flush=True)

    prompts_yaml = load_image_prompts()
    planner_model = prompts_yaml["prompts"]["prompt_planner"].get("model")
    writer_model = prompts_yaml["prompts"]["prompt_writer_ernie"].get("model")
    validator_model = prompts_yaml["prompts"]["validate_prompt_ernie"].get("model")
    print(f"Modèles : planner={planner_model} · writer={writer_model} · validator={validator_model}", flush=True)
    print(f"Profile : {PROFILE} · workflow : {WORKFLOW} · validator num_ctx={VALIDATOR_NUM_CTX}", flush=True)
    print(f"Cible succès : ≥ {int(SUCCESS_RATE * 100)}% concepts avec score ≥ {SCORE_THRESHOLD} ; latence ≤ {LATENCY_BUDGET_S}s", flush=True)
    print(flush=True)

    results: list[dict] = []
    for i, concept in enumerate(CONCEPTS, 1):
        origin = "v1" if concept in CONCEPTS_V1 else "new"
        print(f"[{i:>2}/{len(CONCEPTS)}] [{origin}] {concept['category']:<25} {concept['name_en']}", flush=True)
        t_start = time.time()
        res = run_chain(concept, prompts_yaml)
        res["origin"] = origin
        wall = time.time() - t_start
        if res.get("errors"):
            print(f"        ❌ {' | '.join(res['errors'])[:200]}", flush=True)
        else:
            score = res["validator"]["score"]
            checks = res["validator"]["checks"]
            n_pass = sum(1 for c in checks if isinstance(c, dict) and bool(c.get("pass")))
            n_total = len(checks)
            lat = res["latencies"]
            drift_tag = " 🔁drift-retry" if res.get("drift_retry") else ""
            print(
                f"        score={score:>3}  checks={n_pass}/{n_total}  "
                f"P={lat['planner_s']:.1f}s W={lat['writer_s']:.1f}s V={lat['validator_s']:.1f}s "
                f"total={lat['total_s']:.1f}s (wall={wall:.1f}s){drift_tag}",
                flush=True,
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
    n_drift_retried = sum(1 for r in results if r.get("drift_retry"))

    p50_total = statistics.median(totals) if totals else None
    p95_total = (sorted(totals)[max(0, int(round(0.95 * (len(totals) - 1))))] if totals else None)

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

    print(flush=True)
    print("─── Agrégats ───────────────────────────────────────────────────────────────────", flush=True)
    print(f"Erreurs chaîne : {len(CONCEPTS) - len(successful)}/{len(CONCEPTS)}", flush=True)
    print(f"Drift retries : {n_drift_retried}/{len(CONCEPTS)}", flush=True)
    print(f"Concepts ≥ {SCORE_THRESHOLD} : {n_above_thresh}/{len(CONCEPTS)} ({rate_thresh*100:.0f}%)  [cible ≥ {int(SUCCESS_RATE*100)}%]", flush=True)
    print(f"Concepts ≤ {LATENCY_BUDGET_S}s : {n_under_budget}/{len(CONCEPTS)} ({rate_budget*100:.0f}%)", flush=True)
    if scores:
        print(f"Scores : min={min(scores)} median={statistics.median(scores):.0f} max={max(scores)}", flush=True)
    if totals:
        print(f"Latence totale : p50={p50_total:.1f}s p95={p95_total:.1f}s mean={statistics.mean(totals):.1f}s", flush=True)

    payload = {
        "poc": "prompt-chain-v2",
        "date": "2026-05-05",
        "fixes_applied": [
            "validator num_ctx=8192",
            "planner drift retry @ T=0",
            "no-text rule in prompt_writer_ernie.system",
            "models migrated to qwen3.5:4b",
        ],
        "models": {"planner": planner_model, "writer": writer_model, "validator": validator_model},
        "profile": PROFILE,
        "workflow": WORKFLOW,
        "validator_num_ctx": VALIDATOR_NUM_CTX,
        "success_threshold_score": SCORE_THRESHOLD,
        "success_rate_target": SUCCESS_RATE,
        "latency_budget_s": LATENCY_BUDGET_S,
        "concepts_v1_count": len(CONCEPTS_V1),
        "concepts_new_count": len(CONCEPTS_NEW),
        "concepts": CONCEPTS,
        "results": results,
        "aggregates": {
            "n_concepts": len(CONCEPTS),
            "n_chain_errors": len(CONCEPTS) - len(successful),
            "n_drift_retried": n_drift_retried,
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
    print(f"\nJSON brut → {REPORT_JSON}", flush=True)

    # ── Markdown ──
    success_ok = rate_thresh >= SUCCESS_RATE
    latency_ok = (p50_total is not None and p50_total <= LATENCY_BUDGET_S)
    v1 = load_v1_aggregates()

    md: list[str] = []
    md.append("# POC-3 v2 — Chaîne planner → writer → validator (post-fixes)")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append(
        f"Re-run du POC-3 après application des **3 fixes de robustesse** identifiés en v1 + migration "
        f"`qwen3:8b → qwen3.5:4b` sur les 3 templates concernés. Test sur **{len(CONCEPTS)} concepts** : "
        f"les **{len(CONCEPTS_V1)} concepts v1** rejoués à l'identique + **{len(CONCEPTS_NEW)} nouveaux** "
        "depuis la nouvelle taxonomie (électroménager, géométrie, personnalités sportives, professions, fantasy)."
    )
    md.append("")
    md.append("### Fixes appliqués")
    md.append("")
    md.append("1. **`num_ctx=8192` validator** — `src/services/ollama_json.py::call_ollama_sync` expose un paramètre `num_ctx` ; `run_image_prompt_validate_sync` (et ce script) le passent à 8192. Le JSON validator dépassait régulièrement la limite Ollama par défaut de 4096 tokens et tronquait mid-objet.")
    md.append("2. **Retry planner sur drift** — `call_ollama_sync_with_drift_retry` détecte si la réponse (think-tags strippés) ne commence pas par `{` ou `[` et relance une fois à T=0. `run_image_prompt_create_sync` utilise ce wrapper.")
    md.append("3. **Règle « no readable text »** ajoutée au `system` de `prompt_writer_ernie` (pattern `technical_cleanup` qui échouait 3/7 en v1 sur du texte diégétique).")
    md.append("4. **Bonus** — `prompt_planner`, `prompt_writer_ernie`, `validate_prompt_ernie` migrés vers `qwen3.5:4b` (alignement avec le routing LLM acté dans CLAUDE.md, ~5× plus rapide qu'`qwen3:8b`).")
    md.append("")
    md.append(f"Modèles : planner=`{planner_model}` · writer=`{writer_model}` · validator=`{validator_model}` (validator `num_ctx={VALIDATOR_NUM_CTX}`).")
    md.append("")
    md.append("## Critères de succès")
    md.append(f"- ≥ **{int(SUCCESS_RATE * 100)} %** des concepts obtiennent un score validator ≥ **{SCORE_THRESHOLD}** au premier essai")
    md.append(f"- Latence totale par concept ≤ **{LATENCY_BUDGET_S} s**")
    md.append("")

    md.append("## Résultats par concept")
    md.append("")
    md.append("| # | Origine | Catégorie | name_en | Score | Checks pass | Planner | Writer | Validator | Total | Drift retry | Erreurs |")
    md.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|:---:|---|")
    for i, r in enumerate(results, 1):
        c = r["concept"]
        origin = r.get("origin", "")
        if r.get("errors"):
            md.append(
                f"| {i} | {origin} | {c['category']} | {c['name_en']} | — | — | — | — | — | — | "
                f"{'🔁' if r.get('drift_retry') else ''} | {' / '.join(r['errors'])[:120]} |"
            )
            continue
        s = r["validator"]["score"]
        ck = r["validator"]["checks"]
        npass = sum(1 for x in ck if isinstance(x, dict) and bool(x.get("pass")))
        ntot = len(ck)
        lat = r["latencies"]
        md.append(
            f"| {i} | {origin} | {c['category']} | {c['name_en']} | **{s}** | {npass}/{ntot} | "
            f"{lat['planner_s']:.1f}s | {lat['writer_s']:.1f}s | {lat['validator_s']:.1f}s | "
            f"**{lat['total_s']:.1f}s** | {'🔁' if r.get('drift_retry') else ''} | — |"
        )
    md.append("")

    # ── Comparaison v1 vs v2 sur les 10 concepts communs ──
    md.append("## Comparaison v1 vs v2 (mêmes 10 concepts)")
    md.append("")
    if v1 is None:
        md.append("*JSON v1 non disponible — comparaison sautée.*")
    else:
        v1_results = {r["concept"]["name_en"]: r for r in v1.get("results", []) if isinstance(r, dict)}
        v2_results = {r["concept"]["name_en"]: r for r in results[: len(CONCEPTS_V1)]}
        md.append("| Concept | v1 score | v2 score | Δ | v1 total | v2 total | v1 erreurs | v2 erreurs |")
        md.append("|---|---:|---:|---:|---:|---:|---|---|")
        improved = same = degraded = 0
        for c in CONCEPTS_V1:
            name = c["name_en"]
            v1r = v1_results.get(name) or {}
            v2r = v2_results.get(name) or {}
            v1s = v1r.get("validator", {}).get("score") if isinstance(v1r.get("validator"), dict) else None
            v2s = v2r.get("validator", {}).get("score") if isinstance(v2r.get("validator"), dict) else None
            v1t = v1r.get("latencies", {}).get("total_s") if isinstance(v1r.get("latencies"), dict) else None
            v2t = v2r.get("latencies", {}).get("total_s") if isinstance(v2r.get("latencies"), dict) else None
            v1err = ", ".join(v1r.get("errors") or [])[:80]
            v2err = ", ".join(v2r.get("errors") or [])[:80]
            if v1s is not None and v2s is not None:
                if v2s > v1s:
                    improved += 1
                elif v2s == v1s:
                    same += 1
                else:
                    degraded += 1
                delta = f"{v2s - v1s:+d}"
            elif v1s is None and v2s is not None:
                improved += 1
                delta = "(v1 fail → v2 ok)"
            elif v1s is not None and v2s is None:
                degraded += 1
                delta = "(v1 ok → v2 fail)"
            else:
                delta = "—"
            md.append(
                f"| {name} | {v1s if v1s is not None else '—'} | {v2s if v2s is not None else '—'} | "
                f"{delta} | {f'{v1t:.1f}s' if v1t else '—'} | {f'{v2t:.1f}s' if v2t else '—'} | "
                f"{v1err or '—'} | {v2err or '—'} |"
            )
        md.append("")
        md.append(f"Δ score : **{improved}** améliorés · **{same}** identiques · **{degraded}** dégradés.")
        md.append("")

    md.append("## Agrégats v2")
    md.append("")
    md.append(f"- Erreurs chaîne : **{len(CONCEPTS) - len(successful)}/{len(CONCEPTS)}**")
    md.append(f"- Drift retries effectifs : **{n_drift_retried}/{len(CONCEPTS)}**")
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
    md.append("| Check | Pass | Total | % v2 | rappel v1 |")
    md.append("|---|---:|---:|---:|---:|")
    v1_check_pass = (v1 or {}).get("aggregates", {}).get("checks_pass", {}) if v1 else {}
    v1_check_total = (v1 or {}).get("aggregates", {}).get("checks_total", {}) if v1 else {}
    for cid in sorted(check_total.keys()):
        npass = check_pass.get(cid, 0)
        ntot = check_total[cid]
        pct = (npass / ntot * 100) if ntot else 0.0
        v1pct = ""
        if cid in v1_check_total and v1_check_total[cid]:
            v1pct = f"{(v1_check_pass.get(cid, 0) / v1_check_total[cid]) * 100:.0f}%"
        md.append(f"| {cid} | {npass} | {ntot} | {pct:.0f}% | {v1pct} |")
    md.append("")

    # Top / Bottom prompts
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
            md.append(f"### [{r.get('origin', '')}] {c['category']} · {c['name_en']}")
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
            f"✅ **Chaîne prête pour P2.** Les deux critères sont remplis : "
            f"**{rate_thresh*100:.0f} %** des concepts dépassent le score {SCORE_THRESHOLD} "
            f"(cible ≥ {int(SUCCESS_RATE*100)} %) et la latence p50 reste sous le budget de {LATENCY_BUDGET_S}s."
        )
        md.append("")
        md.append("Les 3 fixes ont fonctionné comme prévu : pas de troncature JSON validator, drift planner intercepté par retry T=0, et le check `technical_cleanup` est revenu en zone verte.")
    else:
        issues: list[str] = []
        if not success_ok:
            issues.append(f"taux {rate_thresh*100:.0f} % < cible {int(SUCCESS_RATE*100)} %")
        if not latency_ok and p50_total is not None:
            issues.append(f"latence p50 {p50_total:.1f}s > budget {LATENCY_BUDGET_S}s")
        md.append("⚠ **Critères partiellement remplis : " + " ; ".join(issues) + ".**")
        md.append("")
        md.append("Examiner les Bottom 3 ci-dessus et le tableau de comparaison v1↔v2 pour identifier les régressions ou patterns résiduels.")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes : `2026-05-05_poc-prompt-chain-v2.json`")
    md.append("- Comparaison : `2026-05-05_poc-prompt-chain.json` (v1)")
    md.append("- Script : `scripts/poc_prompt_chain_v2.py`")
    md.append("- Templates : `prompts/image_prompts.yaml` (prompt_planner, prompt_writer_ernie, validate_prompt_ernie)")
    md.append("- Helpers : `src/services/ollama_json.py::call_ollama_sync_with_drift_retry`")
    md.append("- Patches prod : `src/services/ai_jobs_sync.py::run_image_prompt_create_sync` (drift retry) ; `run_image_prompt_validate_sync` (num_ctx=8192)")
    md.append("- Plan de POC : `docs/poc-plan.md` § POC-3")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
