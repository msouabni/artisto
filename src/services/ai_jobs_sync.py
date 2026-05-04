"""Exécution synchrone des pipelines IA (Ollama) pour les workers — alignée sur api.routes.ai."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException

from services.ollama_json import OLLAMA_MODEL, OLLAMA_TIMEOUT, call_ollama_sync

logger = logging.getLogger(__name__)


def _parse_json_ai(raw: str) -> Any:
    from api.routes.ai import _parse_json_response

    try:
        return _parse_json_response(raw)
    except HTTPException as e:
        d = e.detail
        raise ValueError(d if isinstance(d, str) else str(d)) from e


def _ollama_timeout_from_prompts(prompts_data: dict) -> int:
    from api.routes.ai import OLLAMA

    return int(prompts_data.get("defaults", {}).get("timeout", OLLAMA.default_timeout))


def run_text_enrichment_sync(config: dict[str, Any]) -> dict[str, Any]:
    prompt = config.get("prompt", "")
    system = config.get("system", "")
    model = config.get("model") or OLLAMA_MODEL
    temperature = float(config.get("temperature", 0.3))
    timeout = int(config.get("timeout") or OLLAMA_TIMEOUT)
    if not str(prompt).strip():
        raise ValueError("config.prompt requis")
    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    return {"result": _parse_json_ai(raw), "raw_response": raw}


def run_taxonomy_enrich_term_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    from api.routes import ai as ai_mod

    vocabulary_id = str(config.get("vocabulary_id") or "").strip()
    term_id = str(config.get("term_id") or "").strip()
    if not vocabulary_id or not term_id:
        raise ValueError("config.vocabulary_id et config.term_id requis")
    fields = config.get("fields") or []
    if not isinstance(fields, list):
        fields = []

    prompts_data = ai_mod._load_prompts(conn)
    tpl = ai_mod._get_prompt_template(prompts_data, "enrich_term")
    term = ai_mod._get_term(conn, vocabulary_id, term_id)
    req_fields = ai_mod._detect_missing_fields(term, fields)
    if not req_fields and config.get("custom_prompt") is None:
        return {
            "term_id": term_id,
            "vocabulary_id": vocabulary_id,
            "suggestions": {},
            "fields_requested": [],
            "skipped": True,
            "message": "Tous les champs textuels sont déjà renseignés.",
        }

    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    term_json = json.dumps(
        {k: v for k, v in term.items() if k not in ("vocabulary_id",)},
        ensure_ascii=False,
        indent=2,
    )
    if config.get("custom_prompt") is not None:
        prompt = config["custom_prompt"]
    else:
        prompt = tpl["user"].format(
            term_json=term_json,
            missing_fields=json.dumps(req_fields, ensure_ascii=False),
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    timeout = _ollama_timeout_from_prompts(prompts_data)
    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    suggestions = _parse_json_ai(raw)
    if isinstance(suggestions, dict):
        suggestions = {
            k: str(v).strip()
            for k, v in suggestions.items()
            if k in req_fields and v
        }
    else:
        suggestions = {}
    return {
        "term_id": term_id,
        "vocabulary_id": vocabulary_id,
        "suggestions": suggestions,
        "fields_requested": req_fields,
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def run_taxonomy_enrich_terms_batch_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    from api.routes import ai as ai_mod
    from api.routes.taxonomy import _ensure_vocabulary_exists, _get_terms_flat, _term_to_response

    vocabulary_id = str(config.get("vocabulary_id") or "").strip()
    term_ids = config.get("term_ids") or []
    if not vocabulary_id:
        raise ValueError("config.vocabulary_id requis")
    if not isinstance(term_ids, list) or not term_ids:
        raise ValueError("config.term_ids (liste non vide) requis")

    _ensure_vocabulary_exists(conn, vocabulary_id)
    rows = _get_terms_flat(conn, vocabulary_id)
    term_ids_set = {str(x) for x in term_ids}
    terms_by_id: dict[str, dict] = {}
    for r in rows:
        tid = r.get("id")
        if tid and str(tid) in term_ids_set:
            terms_by_id[str(tid)] = _term_to_response(r)

    text_fields = ("name_fr", "name_en", "name_ar", "description_fr", "description_en", "description_ar")
    missing: set[str] = set()
    terms_data: dict[str, dict] = {}
    body_fields = config.get("fields") or []
    if not isinstance(body_fields, list):
        body_fields = []
    for tid in term_ids:
        ts = str(tid)
        if ts not in terms_by_id:
            raise ValueError(f"Terme '{ts}' introuvable dans '{vocabulary_id}'")
        term = terms_by_id[ts]
        if body_fields:
            for f in body_fields:
                if f in text_fields:
                    missing.add(f)
        else:
            for f in ai_mod._detect_missing_fields(term, []):
                missing.add(f)
        terms_data[ts] = {k: v for k, v in term.items() if k != "vocabulary_id"}

    if not missing and config.get("custom_prompt") is None:
        return {
            "suggestions": {},
            "fields_requested": [],
            "term_ids": [str(x) for x in term_ids],
            "skipped": True,
            "message": "Rien à enrichir.",
        }

    fields_list = sorted(missing)
    prompts_data = ai_mod._load_prompts(conn)
    tpl = ai_mod._get_prompt_template(prompts_data, "enrich_terms_batch")
    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    terms_json = json.dumps(terms_data, ensure_ascii=False, indent=2)
    if config.get("custom_prompt") is not None:
        prompt = config["custom_prompt"]
    else:
        prompt = tpl["user"].format(
            terms_json=terms_json,
            missing_fields=json.dumps(fields_list, ensure_ascii=False),
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    timeout = _ollama_timeout_from_prompts(prompts_data)
    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    parsed = _parse_json_ai(raw)
    suggestions: dict[str, dict[str, str]] = {}
    if isinstance(parsed, dict):
        for tid in term_ids:
            ts = str(tid)
            val = parsed.get(ts)
            if isinstance(val, dict):
                suggestions[ts] = {
                    k: str(v).strip()
                    for k, v in val.items()
                    if k in fields_list and v
                }
    return {
        "suggestions": suggestions,
        "fields_requested": fields_list,
        "term_ids": [str(x) for x in term_ids],
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def run_taxonomy_enrich_keywords_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    from api.routes import ai as ai_mod

    vocabulary_id = str(config.get("vocabulary_id") or "").strip()
    term_id = str(config.get("term_id") or "").strip()
    if not vocabulary_id or not term_id:
        raise ValueError("config.vocabulary_id et config.term_id requis")
    min_kw = int(config.get("min_keywords", 5))
    max_kw = int(config.get("max_keywords", 15))

    prompts_data = ai_mod._load_prompts(conn)
    tpl = ai_mod._get_prompt_template(prompts_data, "enrich_keywords")
    term = ai_mod._get_term(conn, vocabulary_id, term_id)
    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    timeout = _ollama_timeout_from_prompts(prompts_data)
    term_json = json.dumps(
        {k: v for k, v in term.items() if k not in ("vocabulary_id",)},
        ensure_ascii=False,
        indent=2,
    )
    if config.get("custom_prompt") is not None:
        prompt = config["custom_prompt"]
    else:
        prompt = tpl["user"].format(
            term_json=term_json,
            min_keywords=min_kw,
            max_keywords=max_kw,
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    suggestions = _parse_json_ai(raw)
    keywords: list[str] = []
    if isinstance(suggestions, dict):
        KW_KEYS = ("keywords", "mots_cles", "mots-cles", "tags", "terms", "items")
        for key in KW_KEYS:
            if key in suggestions and isinstance(suggestions[key], list):
                keywords = suggestions[key]
                break
        else:
            for v in suggestions.values():
                if isinstance(v, list):
                    keywords = v
                    break
    elif isinstance(suggestions, list):
        keywords = suggestions
    keywords = [str(k).strip() for k in keywords if k and str(k).strip()]
    return {
        "term_id": term_id,
        "vocabulary_id": vocabulary_id,
        "suggestions_keywords": keywords,
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def run_taxonomy_suggest_children_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    from api.routes import ai as ai_mod

    vocabulary_id = str(config.get("vocabulary_id") or "").strip()
    term_id = str(config.get("term_id") or "").strip()
    count = int(config.get("count", 5))
    if not vocabulary_id or not term_id:
        raise ValueError("config.vocabulary_id et config.term_id requis")

    prompts_data = ai_mod._load_prompts(conn)
    tpl = ai_mod._get_prompt_template(prompts_data, "suggest_children")
    term = ai_mod._get_term(conn, vocabulary_id, term_id)
    existing = ai_mod._get_term_children(conn, vocabulary_id, term_id)
    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    timeout = _ollama_timeout_from_prompts(prompts_data)

    if existing:
        existing_context = (
            "Existing children — do NOT duplicate:\n"
            + json.dumps(
                [{"id": c["id"], "name_en": c.get("name_en") or c.get("name_fr", ""), "name_fr": c.get("name_fr", "")}
                 for c in existing],
                ensure_ascii=False,
            )
        )
    else:
        existing_context = "No children exist yet for this parent. Feel free to generate the most relevant terms."

    if config.get("custom_prompt") is not None:
        prompt = config["custom_prompt"]
    else:
        prompt = tpl["user"].format(
            parent_name_en=term.get("name_en") or term.get("name_fr") or term["id"],
            parent_name_fr=term.get("name_fr") or term.get("name_en") or term["id"],
            parent_id=term["id"],
            vocabulary_id=vocabulary_id,
            existing_context=existing_context,
            count=count,
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    suggestions = _parse_json_ai(raw)

    if isinstance(suggestions, dict):
        ARRAY_KEYS = (
            "children", "terms", "items", "results", "suggestions",
            "suggested_children", "new_children", "new_terms",
        )
        extracted = None
        for key in ARRAY_KEYS:
            if key in suggestions and isinstance(suggestions[key], list):
                extracted = suggestions[key]
                break
        if extracted is None:
            for v in suggestions.values():
                if isinstance(v, list):
                    extracted = v
                    break
        suggestions = extracted if extracted is not None else []
    if not isinstance(suggestions, list):
        suggestions = []

    cleaned = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        name_fr = str(item.get("name_fr") or "").strip()
        name_en = str(item.get("name_en") or "").strip()
        slug = str(item.get("slug") or item_id).strip() or item_id
        cleaned.append({
            "id": item_id,
            "slug": slug,
            "name_fr": name_fr,
            "name_en": name_en,
            "name_ar": str(item.get("name_ar") or "").strip(),
            "description_fr": str(item.get("description_fr") or "").strip(),
            "description_en": str(item.get("description_en") or "").strip(),
            "weight": int(item.get("weight") or (len(existing) + len(cleaned))),
            "parent_id": term_id,
        })

    return {
        "term_id": term_id,
        "vocabulary_id": vocabulary_id,
        "suggestions": cleaned,
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def _flatten_vocab_terms(nodes: Any, parent_id: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(nodes, list):
        return out
    for item in nodes:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            continue
        slug = str(item.get("slug") or cid).strip() or cid
        entry = {
            "id": cid,
            "slug": slug,
            "name_fr": str(item.get("name_fr") or "").strip(),
            "name_en": str(item.get("name_en") or "").strip(),
            "name_ar": str(item.get("name_ar") or "").strip(),
            "description_fr": str(item.get("description_fr") or "").strip(),
            "description_en": str(item.get("description_en") or "").strip(),
            "description_ar": str(item.get("description_ar") or "").strip(),
            "weight": int(item.get("weight") or len(out)),
            "parent_id": parent_id,
        }
        out.append(entry)
        ch = item.get("children")
        if isinstance(ch, list) and ch:
            out.extend(_flatten_vocab_terms(ch, cid))
    return out


def run_taxonomy_generate_vocabulary_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    from api.routes import ai as ai_mod

    theme = str(config.get("theme") or "").strip()
    if not theme:
        raise ValueError("config.theme requis")
    root_count = int(config.get("root_count", 5))
    children_per_root = int(config.get("children_per_root", 3))

    prompts_data = ai_mod._load_prompts(conn)
    tpl = ai_mod._get_prompt_template(prompts_data, "generate_vocabulary")
    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    timeout = _ollama_timeout_from_prompts(prompts_data)

    if config.get("custom_prompt") is not None:
        prompt = config["custom_prompt"]
    else:
        prompt = tpl["user"].format(
            theme=theme,
            root_count=root_count,
            children_per_root=children_per_root,
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    suggestions = _parse_json_ai(raw)

    if isinstance(suggestions, dict):
        ARRAY_KEYS = ("terms", "children", "items", "results", "vocabulary", "topics")
        terms = []
        for key in ARRAY_KEYS:
            if key in suggestions and isinstance(suggestions[key], list):
                terms = suggestions[key]
                break
        else:
            for v in suggestions.values():
                if isinstance(v, list):
                    terms = v
                    break
    elif isinstance(suggestions, list):
        terms = suggestions
    else:
        terms = []

    flat = _flatten_vocab_terms(terms, None)
    return {
        "theme": theme,
        "suggestions_flat": flat,
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def run_generate_concepts_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Aligné sur POST /api/ai/generate-concepts : thème + concepts image (sous-thèmes)."""
    from fastapi import HTTPException

    from api.routes import ai as ai_mod

    theme = str(config.get("theme") or "").strip()
    if not theme:
        raise ValueError("config.theme requis")
    term_id = (config.get("term_id") or "").strip() or None
    vocabulary_id = (config.get("vocabulary_id") or "").strip() or None

    taxonomy_context = ""
    if term_id and vocabulary_id:
        try:
            term = ai_mod._get_term(conn, vocabulary_id, term_id)
            children = ai_mod._get_term_children(conn, vocabulary_id, term_id)
            branch = [term] + children
            taxonomy_context = (
                "Taxonomy context (anchor) — parent term and existing children:\n"
                + json.dumps(
                    [{"id": t.get("id"), "name_en": t.get("name_en") or t.get("name_fr"), "name_fr": t.get("name_fr")} for t in branch],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        except HTTPException:
            pass

    tpl = ai_mod._get_image_prompt_template("generate_concepts")
    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    image_data = ai_mod._load_image_prompts()
    timeout = int(
        tpl.get("timeout")
        or image_data.get("defaults", {}).get("timeout")
        or ai_mod.OLLAMA.default_timeout
    )
    count = min(max(1, int(config.get("count", 5))), 15)

    if config.get("custom_prompt") is not None:
        prompt = config["custom_prompt"]
    else:
        prompt = tpl["user"].format(
            theme=theme,
            taxonomy_context=taxonomy_context or "No taxonomy anchor provided.",
            count=count,
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    parsed = _parse_json_ai(raw)

    if isinstance(parsed, dict):
        _concept_wrap_keys = ("concepts", "suggestions", "results", "items", "terms")
        if not any(k in parsed for k in _concept_wrap_keys) and str(parsed.get("id") or "").strip():
            parsed = [parsed]

    suggestions: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        suggestions = parsed
    elif isinstance(parsed, dict):
        for key in ("concepts", "suggestions", "results", "items", "terms"):
            if key in parsed and isinstance(parsed[key], list):
                suggestions = parsed[key]
                break
        else:
            for v in parsed.values():
                if isinstance(v, list):
                    suggestions = v
                    break

    cleaned: list[dict[str, Any]] = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            continue
        slug = str(item.get("slug") or cid).strip() or cid
        name_fr = str(item.get("name_fr") or "").strip()
        name_en = str(item.get("name_en") or "").strip()
        cleaned.append({
            "id": cid,
            "slug": slug,
            "title": name_en or name_fr or cid,
            "name_fr": name_fr,
            "name_en": name_en,
            "name_ar": str(item.get("name_ar") or "").strip(),
            "description_fr": str(item.get("description_fr") or "").strip(),
            "description_en": str(item.get("description_en") or "").strip(),
            "weight": int(item.get("weight") or len(cleaned)),
        })

    return {
        "suggestions": cleaned,
        "theme": theme,
        "prompt_used": prompt,
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def _image_timeout(tpl: dict) -> int:
    from api.routes.ai import _image_prompt_timeout

    return _image_prompt_timeout(tpl)


def _execute_writer_from_plan_v1_sync(
    plan: dict[str, Any],
    *,
    profile: str,
    model: str | None,
    temperature: float | None,
    model_planner: str,
    temperature_planner: float,
    raw_plan: str,
    workflow_template: str | None = None,
) -> dict[str, Any]:
    from api.routes.ai import (
        _default_negative_prompt_for_profile,
        _get_image_prompt_template,
        _resolve_model_temp,
        resolve_image_prompt_template_keys,
    )

    tpl_keys = resolve_image_prompt_template_keys(workflow_template)
    writer_tpl = _get_image_prompt_template(tpl_keys["writer"])
    w_model, w_temp = _resolve_model_temp(writer_tpl, model, temperature)
    w_timeout = _image_timeout(writer_tpl)
    plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
    writer_user = writer_tpl["user"].format(plan_json=plan_json)
    writer_system = writer_tpl["system"]
    raw_out = call_ollama_sync(writer_user, writer_system, w_model, w_temp, w_timeout)
    parsed_out = _parse_json_ai(raw_out)
    final_prompt = ""
    final_negative = ""
    if isinstance(parsed_out, dict):
        final_prompt = str(parsed_out.get("prompt") or "").strip()
        final_negative = str(parsed_out.get("negative_prompt") or "").strip()
    if not final_prompt:
        raise ValueError("Le writer n'a pas renvoyé de champ 'prompt' exploitable.")
    if not final_negative:
        final_negative = _default_negative_prompt_for_profile(profile)

    return {
        "prompt": final_prompt,
        "negative_prompt": final_negative,
        "plan": plan,
        "profile": profile,
        "model_planner": model_planner,
        "model_writer": w_model,
        "temperature_planner": temperature_planner,
        "temperature_writer": w_temp,
        "raw_plan": raw_plan,
        "raw_writer": raw_out,
    }


def run_image_prompt_create_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    _ = conn
    from api.routes.ai import _get_image_prompt_template, _resolve_model_temp

    keywords = str(config.get("keywords") or "").strip()
    title = str(config.get("title") or "").strip()
    tags_context = str(config.get("tags_context") or "").strip()
    profile = str(config.get("profile") or "kids_coloring_lineart_v1").strip()
    if not keywords and not title:
        raise ValueError("Fournir au moins config.keywords ou config.title")

    planner_tpl = _get_image_prompt_template("prompt_planner")
    p_model, p_temp = _resolve_model_temp(planner_tpl, config.get("model"), config.get("temperature"))
    p_timeout = _image_timeout(planner_tpl)

    if config.get("custom_prompt") is not None:
        planner_user = config["custom_prompt"]
    else:
        planner_user = planner_tpl["user"].format(
            profile=profile or "(default)",
            keywords=keywords or "(none)",
            title=title or "(none)",
            tags_context=tags_context or "(none)",
        )
    planner_system = config["custom_system"] if config.get("custom_system") is not None else planner_tpl["system"]
    raw_plan = call_ollama_sync(planner_user, planner_system, p_model, p_temp, p_timeout)
    plan = _parse_json_ai(raw_plan)
    if not isinstance(plan, dict):
        raise ValueError("Le planificateur n'a pas renvoyé un objet JSON attendu.")

    wf_tpl = str(config.get("workflow_template") or "").strip() or None
    return _execute_writer_from_plan_v1_sync(
        plan,
        profile=profile,
        model=config.get("model"),
        temperature=config.get("temperature"),
        model_planner=p_model,
        temperature_planner=p_temp,
        raw_plan=raw_plan,
        workflow_template=wf_tpl,
    )


def run_image_prompt_improve_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    from api.routes.ai import _get_image_prompt_template, _resolve_model_temp
    from api.routes import ai as ai_mod

    title = str(config.get("title") or "").strip()
    prompt = str(config.get("prompt") or "").strip()
    tags_context = str(config.get("tags_context") or "").strip()
    image_id = (config.get("image_id") or "").strip()

    if image_id:
        try:
            rows = conn.execute(
                "SELECT title, prompt FROM image WHERE id = ?",
                [image_id],
            ).fetchall()
            if rows:
                if not title:
                    title = str(rows[0][0] or "")
                if not prompt:
                    prompt = str(rows[0][1] or "")
            tag_rows = conn.execute(
                """
                SELECT t.name_i18n FROM image_taxonomy_tag it
                JOIN vocabulary v ON v.taxonomy_id = it.taxonomy_id
                JOIN term t ON t.id = it.term_id AND t.vocabulary_id = v.id
                WHERE it.image_id = ?
                """,
                [image_id],
            ).fetchall()
            if tag_rows:
                from api.helpers import get_i18n

                names = [get_i18n(r[0], "fr") or "" for r in tag_rows if r[0]]
                joined = ", ".join(n for n in names if n)
                if joined:
                    tags_context = tags_context or joined
        except Exception:
            pass

    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Fournir config.prompt ou config.image_id avec prompt en base.")

    from api.routes.ai import resolve_image_prompt_template_keys

    tpl_keys = resolve_image_prompt_template_keys(str(config.get("workflow_template") or "").strip() or None)
    tpl = _get_image_prompt_template(tpl_keys["improve"])
    model, temperature = _resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    timeout = ai_mod._image_prompt_timeout(tpl)
    count = min(max(1, int(config.get("count", 2))), 5)

    display_title = title or "(no title)"
    if image_id and title:
        try:
            en_row = conn.execute(
                "SELECT title_en FROM image WHERE id = ?", [image_id]
            ).fetchone()
            if en_row and en_row[0]:
                display_title = str(en_row[0])
        except Exception:
            pass

    if config.get("custom_prompt") is not None:
        user_prompt = config["custom_prompt"]
    else:
        user_prompt = tpl["user"].format(
            title=display_title,
            prompt=prompt,
            tags_context=tags_context or "(none)",
            count=count,
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    raw = call_ollama_sync(user_prompt, system, model, temperature, timeout)
    parsed = _parse_json_ai(raw)

    suggestions: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        suggestions = parsed
    elif isinstance(parsed, dict):
        for key in ("suggestions", "prompts", "results", "items"):
            if key in parsed and isinstance(parsed[key], list):
                suggestions = parsed[key]
                break
        else:
            for v in parsed.values():
                if isinstance(v, list):
                    suggestions = v
                    break

    cleaned: list[dict[str, Any]] = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        p = str(item.get("prompt") or "").strip()
        np = str(item.get("negative_prompt") or "").strip()
        if p:
            cleaned.append({"prompt": p, "negative_prompt": np})

    return {
        "suggestions": cleaned,
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def run_generate_prompts_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Génère des prompts line art à partir de concepts (liste) ou d'un terme taxonomique.

    Config attendue :
    - ``concepts`` : liste de dicts {id, name_en, name_fr, ...} (optionnel si term_id fourni)
    - ``term_id`` / ``vocabulary_id`` : ancrage taxonomique (optionnel si concepts fourni)
    - ``count`` : nombre de suggestions (1-10, défaut 3)
    - ``model``, ``temperature``, ``custom_prompt``, ``custom_system``
    """
    from api.routes import ai as ai_mod

    concepts: list[dict[str, Any]] = config.get("concepts") or []
    term_id = (config.get("term_id") or "").strip() or None
    vocabulary_id = (config.get("vocabulary_id") or "").strip() or None

    if term_id and vocabulary_id:
        try:
            term = ai_mod._get_term(conn, vocabulary_id, term_id)
            children = ai_mod._get_term_children(conn, vocabulary_id, term_id)
            concepts = [term] + children
        except Exception:
            pass

    if not concepts:
        raise ValueError(
            "Fournir soit config.concepts, soit config.term_id + config.vocabulary_id"
        )

    tpl = ai_mod._get_image_prompt_template("generate_prompts")
    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    image_data = ai_mod._load_image_prompts()
    timeout = int(image_data.get("defaults", {}).get("timeout", ai_mod.OLLAMA.default_timeout))

    def _slim(c: dict[str, Any]) -> dict[str, Any]:
        name_en = str(c.get("name_en") or "").strip()
        name_fr = str(c.get("name_fr") or "").strip()
        return {"id": c.get("id", ""), "title": name_en or name_fr}

    count = min(max(1, int(config.get("count", 3))), 10)
    concepts_json = json.dumps([_slim(c) for c in concepts[:10]], ensure_ascii=False, indent=2)

    if config.get("custom_prompt") is not None:
        prompt = config["custom_prompt"]
    else:
        prompt = tpl["user"].format(concepts_json=concepts_json, count=count)
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]

    raw = call_ollama_sync(prompt, system, model, temperature, timeout)
    parsed = _parse_json_ai(raw)

    suggestions: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        suggestions = parsed
    elif isinstance(parsed, dict):
        for key in ("prompts", "suggestions", "results", "items"):
            if key in parsed and isinstance(parsed[key], list):
                suggestions = parsed[key]
                break
        else:
            for v in parsed.values():
                if isinstance(v, list):
                    suggestions = v
                    break

    cleaned = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("concept_id") or "").strip()
        p = str(item.get("prompt") or "").strip()
        np = str(item.get("negative_prompt") or "").strip()
        if p:
            cleaned.append({"concept_id": cid or "unknown", "prompt": p, "negative_prompt": np})

    return {
        "suggestions": cleaned,
        "concepts_count": len(concepts),
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def run_suggest_prompt_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Suggère un prompt amélioré pour une image (nouvelle suggestion, pas une amélioration).

    Config attendue :
    - ``image_id`` : charge titre/prompt/tags depuis la DB (optionnel)
    - ``title``, ``prompt``, ``tags_context`` : surcharge directe
    - ``count`` : nombre de suggestions (1-5, défaut 2)
    - ``model``, ``temperature``, ``custom_prompt``, ``custom_system``
    """
    from api.routes import ai as ai_mod

    title = str(config.get("title") or "").strip()
    prompt = str(config.get("prompt") or "").strip()
    tags_context = str(config.get("tags_context") or "").strip()
    image_id = (config.get("image_id") or "").strip() or None

    if image_id:
        try:
            rows = conn.execute(
                "SELECT title, prompt FROM image WHERE id = ?", [image_id]
            ).fetchall()
            if rows:
                if not title:
                    title = str(rows[0][0] or "")
                if not prompt:
                    prompt = str(rows[0][1] or "")
            tag_rows = conn.execute(
                """
                SELECT t.name_i18n FROM image_taxonomy_tag it
                JOIN vocabulary v ON v.taxonomy_id = it.taxonomy_id
                JOIN term t ON t.id = it.term_id AND t.vocabulary_id = v.id
                WHERE it.image_id = ?
                """,
                [image_id],
            ).fetchall()
            if tag_rows:
                from api.helpers import get_i18n
                names = [get_i18n(r[0], "fr") or "" for r in tag_rows if r[0]]
                joined = ", ".join(n for n in names if n)
                if joined:
                    tags_context = tags_context or joined
        except Exception:
            pass

    tpl = ai_mod._get_image_prompt_template("suggest_prompt")
    model, temperature = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    image_data = ai_mod._load_image_prompts()
    timeout = int(image_data.get("defaults", {}).get("timeout", ai_mod.OLLAMA.default_timeout))
    count = min(max(1, int(config.get("count", 2))), 5)

    display_title = title or "(no title)"

    if config.get("custom_prompt") is not None:
        user_prompt = config["custom_prompt"]
    else:
        user_prompt = tpl["user"].format(
            title=display_title,
            prompt=prompt or "(none)",
            tags_context=tags_context or "(none)",
            count=count,
        )
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]

    raw = call_ollama_sync(user_prompt, system, model, temperature, timeout)
    parsed = _parse_json_ai(raw)

    suggestions: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        suggestions = parsed
    elif isinstance(parsed, dict):
        for key in ("suggestions", "prompts", "results", "items"):
            if key in parsed and isinstance(parsed[key], list):
                suggestions = parsed[key]
                break
        else:
            for v in parsed.values():
                if isinstance(v, list):
                    suggestions = v
                    break

    cleaned = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        p = str(item.get("prompt") or "").strip()
        np = str(item.get("negative_prompt") or "").strip()
        if p:
            cleaned.append({"prompt": p, "negative_prompt": np})

    return {
        "suggestions": cleaned,
        "model": model,
        "temperature": temperature,
        "raw_response": raw,
    }


def run_prompts_bulk_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Pipeline bulk : planner → writer pour plusieurs concepts.

    Config attendue :
    - ``items`` : liste de {image_id?, keywords?, title?, tags_context?, profile?}
    - ``validate_prompts`` : bool (défaut False)
    - ``workflow_template``, ``model``, ``temperature``
    """
    items_raw = config.get("items") or []
    if not items_raw:
        raise ValueError("config.items (liste non vide) requis")
    if len(items_raw) > 10:
        raise ValueError("Maximum 10 items par job image_prompts_bulk")

    validate_prompts = bool(config.get("validate_prompts", False))
    workflow_template = (config.get("workflow_template") or "").strip() or None
    model = config.get("model")
    temperature = config.get("temperature")

    n = len(items_raw)
    results: list[dict[str, Any]] = []
    success = 0
    failed = 0

    for item in items_raw:
        image_id = (item.get("image_id") or "").strip() or None
        kw = (item.get("keywords") or "").strip()
        title = (item.get("title") or "").strip()
        tags = (item.get("tags_context") or "").strip()
        profile = (item.get("profile") or "kids_coloring_lineart_v1").strip()

        if image_id:
            try:
                rows = conn.execute(
                    "SELECT title, prompt FROM image WHERE id = ?", [image_id]
                ).fetchall()
                if rows:
                    if not title:
                        title = str(rows[0][0] or "")
                tag_rows = conn.execute(
                    """
                    SELECT t.name_i18n FROM image_taxonomy_tag it
                    JOIN vocabulary v ON v.taxonomy_id = it.taxonomy_id
                    JOIN term t ON t.id = it.term_id AND t.vocabulary_id = v.id
                    WHERE it.image_id = ?
                    """,
                    [image_id],
                ).fetchall()
                if tag_rows:
                    from api.helpers import get_i18n
                    names = [get_i18n(r[0], "fr") or "" for r in tag_rows if r[0]]
                    joined = ", ".join(n for n in names if n)
                    if joined:
                        tags = tags or joined
            except Exception:
                pass

        if not kw and not title:
            failed += 1
            results.append({
                "image_id": image_id,
                "ok": False,
                "error": "Fournir au moins keywords ou title (ou image_id avec titre en base).",
            })
            continue

        try:
            item_config = {
                "keywords": kw,
                "title": title,
                "tags_context": tags,
                "profile": profile,
                "workflow_template": workflow_template,
                "model": model,
                "temperature": temperature,
            }
            out = run_image_prompt_create_sync(conn, item_config)
            row: dict[str, Any] = {
                "image_id": image_id,
                "title": title,
                "ok": True,
                "prompt": out["prompt"],
                "negative_prompt": out.get("negative_prompt", ""),
                "plan": out.get("plan"),
                "profile": out.get("profile"),
                "model_planner": out.get("model_planner"),
                "model_writer": out.get("model_writer"),
            }
            if validate_prompts:
                try:
                    val_config = {
                        "prompt": out["prompt"],
                        "profile": profile,
                        "workflow_template": workflow_template,
                        "model": model,
                        "temperature": temperature,
                    }
                    val = run_image_prompt_validate_sync(conn, val_config)
                    row["validation"] = {
                        "score": val["score"],
                        "checks": val["checks"],
                        "recommendations": val["recommendations"],
                        "model": val.get("model"),
                    }
                except Exception as ve:
                    row["validation"] = {"error": str(ve)}
            success += 1
            results.append(row)
        except Exception as exc:
            failed += 1
            results.append({
                "image_id": image_id,
                "title": title,
                "ok": False,
                "error": str(exc),
            })

    return {
        "results": results,
        "summary": {"total": n, "success": success, "failed": failed},
    }


def run_image_prompt_validate_sync(conn: Any, config: dict[str, Any]) -> dict[str, Any]:
    _ = conn
    from api.routes import ai as ai_mod

    prompt = str(config.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("config.prompt requis")
    profile = str(config.get("profile") or "kids_coloring_lineart_v1").strip()

    tpl_keys = ai_mod.resolve_image_prompt_template_keys(str(config.get("workflow_template") or "").strip() or None)
    tpl = ai_mod._get_image_prompt_template(tpl_keys["validate"])
    mdl, temp = ai_mod._resolve_model_temp(tpl, config.get("model"), config.get("temperature"))
    timeout = ai_mod._image_prompt_timeout(tpl)

    if config.get("custom_prompt") is not None:
        user_prompt = config["custom_prompt"]
    else:
        user_prompt = tpl["user"].format(profile=profile, prompt=prompt)
    system = config["custom_system"] if config.get("custom_system") is not None else tpl["system"]
    raw = call_ollama_sync(user_prompt, system, mdl, temp, timeout)
    data = _parse_json_ai(raw)
    if not isinstance(data, dict):
        raise ValueError("La validation n'a pas renvoyé un objet JSON.")

    score = data.get("score")
    if isinstance(score, bool):
        score = int(score)
    elif score is not None:
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = None
    if score is None:
        score = 0
    score = max(0, min(100, score))

    checks = data.get("checks")
    if not isinstance(checks, list):
        checks = []
    rec = data.get("recommendations")
    if not isinstance(rec, list):
        rec = []

    return {
        "score": score,
        "checks": checks,
        "recommendations": rec,
        "model": mdl,
        "temperature": temp,
        "raw_response": raw,
    }
