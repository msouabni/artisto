"""
Framework de test A/B pour les prompts Ollama.

Usage :
  python scripts/test_prompts.py                        # teste tous les prompts
  python scripts/test_prompts.py --prompt generate_prompts
  python scripts/test_prompts.py --prompt enrich_term --runs 3
  python scripts/test_prompts.py --output results/test_prompts.json

Chaque test envoie le prompt à Ollama et évalue la réponse selon plusieurs métriques :
  - json_valid       : la réponse est parsable en JSON
  - fields_complete  : tous les champs attendus sont présents
  - descriptions_length : les descriptions respectent les contraintes de longueur
  - no_think_bleed   : pas de balises <think> dans la réponse finale
  - language_balance : répartition linguistique pour les mots-clés (enrich_keywords)
  - sd_structure     : le prompt SD suit l'ordre attendu (generate_prompts)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "90"))


# ─── Cas de test ──────────────────────────────────────────────────────────────

TEST_CASES: dict[str, dict[str, Any]] = {
    "enrich_term": {
        "description": "Enrichir un terme taxonomique simple",
        "variables": {
            "term_json": json.dumps({
                "id": "animaux_grenouille",
                "slug": "frog",
                "name_fr": "Grenouille",
                "name_en": "",
                "name_ar": "",
                "description_fr": "",
                "description_en": "",
                "description_ar": "",
            }, ensure_ascii=False, indent=2),
            "missing_fields": json.dumps(["name_en", "name_ar", "description_fr", "description_en", "description_ar"]),
        },
        "expected_fields": ["name_en", "name_ar", "description_fr", "description_en", "description_ar"],
        "metrics": ["json_valid", "fields_complete", "descriptions_length", "no_think_bleed"],
        "description_min_words": 15,
        "description_max_words": 40,
    },
    "enrich_terms_batch": {
        "description": "Enrichir plusieurs termes en un appel",
        "variables": {
            "terms_json": json.dumps({
                "vehicules_velo": {"id": "vehicules_velo", "slug": "bicycle", "name_fr": "Vélo", "name_en": "", "name_ar": "", "description_fr": "", "description_en": ""},
                "vehicules_moto": {"id": "vehicules_moto", "slug": "motorcycle", "name_fr": "Moto", "name_en": "", "name_ar": "", "description_fr": "", "description_en": ""},
            }, ensure_ascii=False, indent=2),
            "missing_fields": json.dumps(["name_en", "name_ar", "description_fr"]),
        },
        "expected_keys": ["vehicules_velo", "vehicules_moto"],
        "expected_fields_per_key": ["name_en", "name_ar", "description_fr"],
        "metrics": ["json_valid", "batch_keys_present", "no_think_bleed"],
    },
    "suggest_children": {
        "description": "Proposer des sous-catégories pour 'animaux'",
        "variables": {
            "parent_name_fr": "Animaux",
            "parent_name_en": "Animals",
            "parent_id": "animaux",
            "vocabulary_id": "universal_v0",
            "existing_context": "Aucun terme enfant n'existe encore pour ce parent. Tu es libre de générer les termes les plus pertinents.",
            "count": "5",
        },
        "expected_fields": ["id", "slug", "name_fr", "name_en", "name_ar", "description_fr", "description_en"],
        "metrics": ["json_valid", "is_array", "fields_complete", "id_convention", "no_think_bleed"],
        "id_prefix": "animaux_",
    },
    "generate_vocabulary": {
        "description": "Générer un vocabulaire sur le thème Noël",
        "variables": {
            "theme": "Noël et fêtes de fin d'année",
            "root_count": "3",
            "children_per_root": "2",
        },
        "metrics": ["json_valid", "has_terms_key", "no_think_bleed"],
    },
    "enrich_keywords": {
        "description": "Générer des mots-clés SEO pour 'animaux de la forêt'",
        "variables": {
            "term_json": json.dumps({
                "id": "animaux_foret",
                "name_fr": "Animaux de la forêt",
                "name_en": "Forest Animals",
                "name_ar": "حيوانات الغابة",
                "description_fr": "Coloriages d'animaux de la forêt pour enfants.",
            }, ensure_ascii=False, indent=2),
            "min_keywords": "10",
            "max_keywords": "20",
        },
        "metrics": ["json_valid", "has_keywords_key", "keywords_length", "language_balance", "no_think_bleed"],
        "min_keywords": 10,
        "max_keywords": 20,
    },
    "generate_concepts": {
        "description": "Générer des concepts sur le thème 'Dinosaures'",
        "variables": {
            "theme": "Dinosaures",
            "taxonomy_context": "Aucun ancrage taxonomique fourni.",
            "count": "5",
        },
        "expected_fields": ["id", "slug", "name_fr", "name_en", "description_fr", "description_en"],
        "metrics": ["json_valid", "is_array", "fields_complete", "no_think_bleed"],
    },
    "generate_prompts": {
        "description": "Générer des prompts SD — test fidélité au titre du concept",
        "variables": {
            "concepts_json": json.dumps([
                {"id": "animaux_chat_bibliotheque", "name_fr": "Chat en bibliothèque", "name_en": "Cat in a Library"},
                {"id": "fetes_sorciere_halloween", "name_fr": "Sorcière d'Halloween", "name_en": "Halloween Witch"},
            ], ensure_ascii=False, indent=2),
            "count": "1",
        },
        "expected_fields": ["concept_id", "prompt", "negative_prompt"],
        "metrics": ["json_valid", "is_array", "fields_complete", "sd_structure", "sd_scene_richness", "negative_prompt_quality", "no_think_bleed"],
    },
    "suggest_prompt": {
        "description": "Améliorer un prompt générique pour 'Chat en bibliothèque'",
        "variables": {
            "title": "Chat en bibliothèque",
            "prompt": "black and white cat, coloring page",
            "tags_context": "animaux, chat, bibliothèque, lecture",
            "count": "2",
        },
        "expected_fields": ["prompt", "negative_prompt"],
        "metrics": ["json_valid", "is_array", "fields_complete", "sd_structure", "sd_scene_richness", "no_think_bleed"],
        "scene_keywords": ["library", "book", "shelf", "shelves", "reading", "desk", "glasses"],
    },
}


# ─── Helpers Ollama ───────────────────────────────────────────────────────────

def _strip_think_tags(raw: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()


def _parse_json(raw: str) -> Any:
    clean = _strip_think_tags(raw)
    for candidate in (clean, raw):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*([\[{][\s\S]*?[\]}])\s*```", candidate)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        for start_char in ("[", "{"):
            start = candidate.find(start_char)
            if start < 0:
                continue
            depth = 0
            close = "]" if start_char == "[" else "}"
            for i, ch in enumerate(candidate[start:], start):
                if ch == start_char:
                    depth += 1
                elif ch == close:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(candidate[start:i + 1])
                        except json.JSONDecodeError:
                            break
    return None


def call_ollama(system: str, user: str, model: str, temperature: float) -> tuple[str, float]:
    """Appelle Ollama et retourne (réponse brute, durée en secondes)."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": user,
        "system": system,
        "stream": False,
        "options": {"temperature": temperature},
    }
    t0 = time.time()
    with httpx.Client(timeout=float(OLLAMA_TIMEOUT)) as client:
        res = client.post(url, json=payload)
        res.raise_for_status()
        data = res.json()
    elapsed = time.time() - t0
    if "error" in data and "response" not in data:
        raise RuntimeError(f"Ollama error: {data['error']}")
    return data.get("response", ""), elapsed


# ─── Métriques ────────────────────────────────────────────────────────────────

@dataclass
class MetricResult:
    name: str
    passed: bool
    score: float  # 0.0 à 1.0
    detail: str = ""


def _count_words(text: str) -> int:
    return len(text.split())


def _detect_language(text: str) -> str:
    """Détecte grossièrement la langue d'un keyword."""
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
    if arabic_chars > len(text) * 0.3:
        return "ar"
    common_fr = re.compile(r"\b(coloriage|colorier|les|des|pour|avec|dans|une|enfant|page|de|du|la|le|en)\b", re.I)
    common_en = re.compile(r"\b(coloring|color|for|kids|children|the|and|page|free|with|in|of|a)\b", re.I)
    fr_count = len(common_fr.findall(text))
    en_count = len(common_en.findall(text))
    if fr_count > en_count:
        return "fr"
    if en_count > fr_count:
        return "en"
    return "unknown"


def evaluate_response(
    raw: str,
    parsed: Any,
    test_case: dict[str, Any],
    prompt_key: str,
) -> list[MetricResult]:
    metrics = test_case.get("metrics", [])
    results: list[MetricResult] = []

    for metric in metrics:

        if metric == "json_valid":
            passed = parsed is not None
            results.append(MetricResult("json_valid", passed, 1.0 if passed else 0.0,
                                        "JSON parsé" if passed else f"Échec parsing, extrait: {raw[:150]}"))

        elif metric == "no_think_bleed":
            has_think = bool(re.search(r"<think>", raw, re.IGNORECASE))
            clean = _strip_think_tags(raw)
            has_bleed = bool(re.search(r"<think>", clean, re.IGNORECASE))
            passed = not has_bleed
            results.append(MetricResult("no_think_bleed", passed, 1.0 if passed else 0.0,
                                        "OK" if not has_think else ("Think-tags supprimés" if passed else "Think-tags PERSISTENT dans la réponse finale")))

        elif metric == "is_array":
            passed = isinstance(parsed, list)
            results.append(MetricResult("is_array", passed, 1.0 if passed else 0.0,
                                        f"Type: {type(parsed).__name__}"))

        elif metric == "fields_complete":
            if parsed is None:
                results.append(MetricResult("fields_complete", False, 0.0, "JSON non parsable"))
                continue
            expected = test_case.get("expected_fields", [])
            items = parsed if isinstance(parsed, list) else [parsed]
            if not items:
                results.append(MetricResult("fields_complete", False, 0.0, "Liste vide"))
                continue
            total_checks = len(items) * len(expected)
            passed_checks = 0
            missing_details = []
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                for f in expected:
                    val = item.get(f, "")
                    if val and str(val).strip():
                        passed_checks += 1
                    else:
                        missing_details.append(f"item[{idx}].{f}")
            score = passed_checks / max(total_checks, 1)
            passed = score >= 0.9
            detail = f"{passed_checks}/{total_checks} champs remplis"
            if missing_details:
                detail += f" | Manquants: {missing_details[:5]}"
            results.append(MetricResult("fields_complete", passed, score, detail))

        elif metric == "descriptions_length":
            if parsed is None:
                results.append(MetricResult("descriptions_length", False, 0.0, "JSON non parsable"))
                continue
            min_w = test_case.get("description_min_words", 10)
            max_w = test_case.get("description_max_words", 50)
            desc_fields = [k for k in (parsed.keys() if isinstance(parsed, dict) else []) if "description" in k]
            if not desc_fields and isinstance(parsed, list):
                all_items = parsed
                desc_fields = ["description_fr", "description_en", "description_ar"]
            else:
                all_items = [parsed]
            checks, passes = 0, 0
            details = []
            for item in all_items:
                if not isinstance(item, dict):
                    continue
                for f in desc_fields:
                    val = str(item.get(f, "") or "")
                    if not val.strip():
                        continue
                    wc = _count_words(val)
                    checks += 1
                    if min_w <= wc <= max_w:
                        passes += 1
                    else:
                        details.append(f"{f}: {wc} mots (attendu {min_w}-{max_w})")
            if checks == 0:
                results.append(MetricResult("descriptions_length", True, 1.0, "Aucune description à vérifier"))
            else:
                score = passes / checks
                results.append(MetricResult("descriptions_length", score >= 0.8, score,
                                            f"{passes}/{checks} dans la plage" + (f" | Hors plage: {details[:3]}" if details else "")))

        elif metric == "batch_keys_present":
            if not isinstance(parsed, dict):
                results.append(MetricResult("batch_keys_present", False, 0.0, f"Attendu dict, got {type(parsed).__name__}"))
                continue
            expected_keys = test_case.get("expected_keys", [])
            present = [k for k in expected_keys if k in parsed]
            score = len(present) / max(len(expected_keys), 1)
            passed = score == 1.0
            results.append(MetricResult("batch_keys_present", passed, score,
                                        f"{len(present)}/{len(expected_keys)} clés présentes" +
                                        (f" | Manquantes: {[k for k in expected_keys if k not in parsed]}" if not passed else "")))

        elif metric == "id_convention":
            prefix = test_case.get("id_prefix", "")
            if not isinstance(parsed, list) or not prefix:
                results.append(MetricResult("id_convention", True, 1.0, "Non applicable"))
                continue
            checks = [item for item in parsed if isinstance(item, dict) and item.get("id")]
            conforming = [item for item in checks if str(item.get("id", "")).startswith(prefix)]
            score = len(conforming) / max(len(checks), 1)
            results.append(MetricResult("id_convention", score >= 0.8, score,
                                        f"{len(conforming)}/{len(checks)} IDs avec préfixe '{prefix}'"))

        elif metric == "has_terms_key":
            passed = isinstance(parsed, dict) and "terms" in parsed and isinstance(parsed["terms"], list)
            results.append(MetricResult("has_terms_key", passed, 1.0 if passed else 0.0,
                                        f"Clé 'terms' présente et liste" if passed else f"Structure: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__}"))

        elif metric == "has_keywords_key":
            passed = isinstance(parsed, dict) and "keywords" in parsed and isinstance(parsed["keywords"], list)
            results.append(MetricResult("has_keywords_key", passed, 1.0 if passed else 0.0,
                                        f"{len(parsed.get('keywords', []))} keywords" if passed else "Clé 'keywords' manquante"))

        elif metric == "keywords_length":
            if not isinstance(parsed, dict) or "keywords" not in parsed:
                results.append(MetricResult("keywords_length", False, 0.0, "Pas de keywords"))
                continue
            kws = parsed["keywords"]
            min_k = test_case.get("min_keywords", 5)
            max_k = test_case.get("max_keywords", 20)
            count = len(kws)
            passed = min_k <= count <= max_k
            # Vérifier aussi la longueur de chaque keyword (1-5 mots)
            too_long = [k for k in kws if _count_words(str(k)) > 5]
            score = 1.0 if (passed and not too_long) else (0.5 if passed else 0.0)
            detail = f"{count} keywords (attendu {min_k}-{max_k})"
            if too_long:
                detail += f" | {len(too_long)} keywords trop longs: {too_long[:3]}"
            results.append(MetricResult("keywords_length", score >= 0.8, score, detail))

        elif metric == "language_balance":
            if not isinstance(parsed, dict) or "keywords" not in parsed:
                results.append(MetricResult("language_balance", False, 0.0, "Pas de keywords"))
                continue
            kws = [str(k) for k in parsed["keywords"]]
            if not kws:
                results.append(MetricResult("language_balance", False, 0.0, "Liste vide"))
                continue
            langs = [_detect_language(k) for k in kws]
            fr_pct = langs.count("fr") / len(langs)
            en_pct = langs.count("en") / len(langs)
            ar_pct = langs.count("ar") / len(langs)
            passed = fr_pct >= 0.25 and en_pct >= 0.25 and ar_pct >= 0.15
            score = min(fr_pct / 0.30, 1.0) * 0.35 + min(en_pct / 0.30, 1.0) * 0.35 + min(ar_pct / 0.20, 1.0) * 0.30
            results.append(MetricResult("language_balance", passed, round(score, 2),
                                        f"FR={fr_pct:.0%} EN={en_pct:.0%} AR={ar_pct:.0%} (cible: FR≥30% EN≥30% AR≥20%)"))

        elif metric == "sd_structure":
            items = parsed if isinstance(parsed, list) else [parsed]
            checks, passes = 0, 0
            details = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                p = str(item.get("prompt", ""))
                if not p:
                    continue
                checks += 1
                has_style = bool(re.search(r"coloring book|line art|black and white", p, re.I))
                has_technique = bool(re.search(r"outline|no shading|bold lines|clean lines|white background", p, re.I))
                if has_style and has_technique:
                    passes += 1
                else:
                    missing = []
                    if not has_style:
                        missing.append("style (coloring book/line art)")
                    if not has_technique:
                        missing.append("technique (outlines/no shading)")
                    details.append(f"Manque: {missing}")
            score = passes / max(checks, 1)
            results.append(MetricResult("sd_structure", score >= 0.8, score,
                                        f"{passes}/{checks} prompts bien structurés" + (f" | {details[:2]}" if details else "")))

        elif metric == "sd_scene_richness":
            # Vérifie que le prompt décrit une scène riche (props, environnement) plutôt que de simples tags
            items = parsed if isinstance(parsed, list) else [parsed]
            checks, passes = 0, 0
            details = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                p = str(item.get("prompt", ""))
                if not p:
                    continue
                checks += 1
                # Indicateurs d'une scène riche : mots de lieu, d'action, de props
                scene_indicators = re.findall(
                    r"\b(sitting|standing|flying|reading|wearing|holding|surrounded|with|in the|on top|near|next to|"
                    r"desk|table|shelf|shelves|floor|wall|window|door|background|foreground|library|forest|kitchen|"
                    r"bedroom|garden|street|castle|ocean|mountain|book|hat|glasses|wand|sword|flower|tree|cloud|"
                    r"candle|lantern|basket|ladder|globe|pot|plant|stone|bridge|boat)\b",
                    p, re.I
                )
                # Indicateurs de richesse : >= 5 éléments de scène différents
                unique_indicators = len(set(m.lower() for m in scene_indicators))
                # Vérifier aussi que ce n'est pas que des tags (présence de verbes/prépositions de scène)
                has_action_or_place = bool(re.search(
                    r"\b(sitting|standing|flying|reading|wearing|holding|climbing|looking|playing|surrounded by|in the|on top of|next to)\b",
                    p, re.I
                ))
                # Vérifier fidélité au concept via les keywords spécifiques du test
                scene_kw = test_case.get("scene_keywords", [])
                kw_found = sum(1 for k in scene_kw if k.lower() in p.lower()) if scene_kw else None

                is_rich = unique_indicators >= 4 and has_action_or_place
                if is_rich:
                    passes += 1
                    detail_item = f"OK ({unique_indicators} éléments de scène)"
                else:
                    detail_item = f"Trop générique ({unique_indicators} éléments, action={'oui' if has_action_or_place else 'non'})"
                if kw_found is not None:
                    detail_item += f", fidélité titre: {kw_found}/{len(scene_kw)} mots-clés"
                details.append(detail_item)

            score = passes / max(checks, 1)
            results.append(MetricResult("sd_scene_richness", score >= 0.7, score,
                                        f"{passes}/{checks} prompts riches | {' | '.join(details[:3])}"))

        elif metric == "negative_prompt_quality":
            items = parsed if isinstance(parsed, list) else [parsed]
            checks, passes = 0, 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                np = str(item.get("negative_prompt", ""))
                if not np:
                    continue
                checks += 1
                required_terms = ["shading", "gray", "watercolor", "realistic"]
                present = sum(1 for t in required_terms if t.lower() in np.lower())
                if present >= 3:
                    passes += 1
            score = passes / max(checks, 1)
            results.append(MetricResult("negative_prompt_quality", score >= 0.8, score,
                                        f"{passes}/{checks} negative prompts avec termes requis (shading, gray, watercolor, realistic)"))

    return results


# ─── Runner principal ──────────────────────────────────────────────────────────

@dataclass
class TestRun:
    prompt_key: str
    run_index: int
    model: str
    temperature: float
    elapsed_seconds: float
    raw_response: str
    parsed: Any
    metrics: list[MetricResult]
    overall_score: float = 0.0
    passed: bool = False
    error: str = ""

    def summary(self) -> str:
        status = "✓" if self.passed else "✗"
        score_pct = f"{self.overall_score:.0%}"
        lines = [f"  [{status}] Run #{self.run_index + 1} — score {score_pct} — {self.elapsed_seconds:.1f}s"]
        for m in self.metrics:
            icon = "✓" if m.passed else "✗"
            lines.append(f"    {icon} {m.name}: {m.detail}")
        return "\n".join(lines)


def run_prompt_test(
    prompt_key: str,
    test_case: dict[str, Any],
    prompts_data: dict,
    runs: int = 1,
) -> list[TestRun]:
    tpl = prompts_data.get("prompts", {}).get(prompt_key)
    if not tpl:
        print(f"  ⚠ Prompt '{prompt_key}' non trouvé dans le YAML")
        return []

    model = tpl.get("model", "qwen2.5:7b")
    temperature = float(tpl.get("temperature", 0.3))
    system = tpl.get("system", "")
    user_template = tpl.get("user", "")
    variables = test_case.get("variables", {})

    try:
        user = user_template.format(**variables)
    except KeyError as e:
        print(f"  ⚠ Variable manquante dans le template : {e}")
        return []

    results: list[TestRun] = []
    for i in range(runs):
        print(f"  → Run #{i + 1}/{runs} (model={model}, temp={temperature})...")
        error = ""
        raw = ""
        parsed = None
        elapsed = 0.0
        try:
            raw, elapsed = call_ollama(system, user, model, temperature)
            parsed = _parse_json(raw)
        except Exception as exc:
            error = str(exc)
            print(f"    ⚠ Erreur Ollama : {error}")

        metric_results = evaluate_response(raw, parsed, test_case, prompt_key) if not error else []
        overall_score = (
            sum(m.score for m in metric_results) / len(metric_results)
            if metric_results else 0.0
        )
        passed = overall_score >= 0.8 and not error

        run = TestRun(
            prompt_key=prompt_key,
            run_index=i,
            model=model,
            temperature=temperature,
            elapsed_seconds=round(elapsed, 2),
            raw_response=raw[:1000],
            parsed=parsed,
            metrics=metric_results,
            overall_score=round(overall_score, 3),
            passed=passed,
            error=error,
        )
        results.append(run)
        print(run.summary())

    return results


def run_all_tests(
    prompt_filter: str | None = None,
    runs: int = 1,
    output_path: Path | None = None,
) -> None:
    # Charger les deux fichiers YAML
    taxonomy_yaml = PROJECT_ROOT / "prompts" / "taxonomy_prompts.yaml"
    image_yaml = PROJECT_ROOT / "prompts" / "image_prompts.yaml"

    with open(taxonomy_yaml, encoding="utf-8") as f:
        taxonomy_data = yaml.safe_load(f) or {}
    with open(image_yaml, encoding="utf-8") as f:
        image_data = yaml.safe_load(f) or {}

    # Fusionner
    all_prompts: dict[str, Any] = {"prompts": {}}
    all_prompts["prompts"].update(taxonomy_data.get("prompts", {}))
    all_prompts["prompts"].update(image_data.get("prompts", {}))

    keys_to_test = [prompt_filter] if prompt_filter else list(TEST_CASES.keys())
    unknown = [k for k in keys_to_test if k not in TEST_CASES]
    if unknown:
        print(f"⚠ Clés inconnues : {unknown}")
        print(f"Clés disponibles : {list(TEST_CASES.keys())}")
        return

    print(f"\n{'=' * 60}")
    print(f"TEST DES PROMPTS OLLAMA")
    print(f"Date : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Prompts testés : {keys_to_test}")
    print(f"Runs par prompt : {runs}")
    print(f"{'=' * 60}\n")

    all_runs: list[TestRun] = []
    summary_rows: list[dict] = []

    for key in keys_to_test:
        test_case = TEST_CASES[key]
        print(f"\n{'─' * 50}")
        print(f"▶ {key} — {test_case['description']}")
        runs_result = run_prompt_test(key, test_case, all_prompts, runs=runs)
        all_runs.extend(runs_result)

        if runs_result:
            avg_score = sum(r.overall_score for r in runs_result) / len(runs_result)
            pass_rate = sum(1 for r in runs_result if r.passed) / len(runs_result)
            avg_time = sum(r.elapsed_seconds for r in runs_result) / len(runs_result)
            summary_rows.append({
                "key": key,
                "avg_score": round(avg_score, 3),
                "pass_rate": round(pass_rate, 2),
                "avg_time_s": round(avg_time, 1),
                "runs": len(runs_result),
            })

    # Résumé
    print(f"\n{'=' * 60}")
    print("RÉSUMÉ")
    print(f"{'=' * 60}")
    print(f"{'Prompt':<25} {'Score moy':>10} {'Taux réussite':>15} {'Temps moy':>10}")
    print(f"{'─' * 65}")
    for row in summary_rows:
        score_bar = "█" * int(row["avg_score"] * 10) + "░" * (10 - int(row["avg_score"] * 10))
        print(f"{row['key']:<25} {row['avg_score']:>9.1%} {row['pass_rate']:>14.0%} {row['avg_time_s']:>8.1f}s")
    print()

    # Export JSON
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        export = {
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary_rows,
            "runs": [
                {
                    **{k: v for k, v in asdict(run).items() if k not in ("raw_response", "parsed")},
                    "metrics": [asdict(m) for m in run.metrics],
                    "raw_response_preview": run.raw_response[:500],
                }
                for run in all_runs
            ],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        print(f"📄 Résultats exportés : {output_path}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test A/B des prompts Ollama")
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help=f"Clé du prompt à tester. Options: {list(TEST_CASES.keys())}",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Nombre de runs par prompt (pour mesurer la variabilité)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Chemin du fichier JSON de résultats (ex: results/test_prompts.json)",
    )
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else PROJECT_ROOT / "data" / "outputs" / "test_prompts_results.json"

    run_all_tests(
        prompt_filter=args.prompt,
        runs=args.runs,
        output_path=output_path,
    )
