"""Routes API pour l'enrichissement IA via Ollama."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import to_json_safe, transaction
from api.routes.taxonomy import _get_terms_flat, _term_to_response, _ensure_vocabulary_exists
from services.ai_jobs_sync import run_generate_concepts_sync

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_FILE = PROJECT_ROOT / "prompts" / "taxonomy_prompts.yaml"
IMAGE_PROMPTS_FILE = PROJECT_ROOT / "prompts" / "image_prompts.yaml"

router = APIRouter(prefix="/api/ai", tags=["ai"])

PROMPT_KEYS = ("enrich_term", "enrich_terms_batch", "suggest_children", "generate_vocabulary", "enrich_keywords")
IMAGE_PROMPT_KEYS = (
    "generate_concepts",
    "generate_prompts",
    "suggest_prompt",
    "prompt_planner",
    "prompt_planner_batch",
    "prompt_writer_zimage",
    "prompt_writer_ernie",
    "improve_prompt_zimage",
    "improve_prompt_ernie",
    "validate_prompt_zimage",
    "validate_prompt_ernie",
)


def resolve_image_prompt_template_keys(workflow_template: str | None) -> dict[str, str]:
    """Mappe un workflow Comfy cible vers les clés YAML writer/validate/improve (planner commun).

    Défaut opérationnel : pack **Ernie** (absent, vide, inconnu, ou ``ernie-image-turbo-q8-api``).
    Pack **Z-Image** uniquement si ``workflow_template == z_image_turbo_v1``.
    """
    wt = (workflow_template or "").strip()
    if wt == "z_image_turbo_v1":
        return {
            "planner": "prompt_planner",
            "planner_batch": "prompt_planner_batch",
            "writer": "prompt_writer_zimage",
            "validate": "validate_prompt_zimage",
            "improve": "improve_prompt_zimage",
        }
    return {
        "planner": "prompt_planner",
        "planner_batch": "prompt_planner_batch",
        "writer": "prompt_writer_ernie",
        "validate": "validate_prompt_ernie",
        "improve": "improve_prompt_ernie",
    }


# ─── Configuration Ollama (surchargeable via variables d'environnement) ───────

class _OllamaConfig:
    @property
    def base_url(self) -> str:
        return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    @property
    def default_model(self) -> str:
        return os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

    @property
    def default_timeout(self) -> int:
        return int(os.environ.get("OLLAMA_TIMEOUT", "60"))


OLLAMA = _OllamaConfig()

# Client HTTP réutilisé pour POST /api/generate (timeouts par requête sur post()).
_ollama_http_client: httpx.AsyncClient | None = None

# Concurrence max pour writers / validations en create-prompts-bulk (évite de saturer Ollama).
BULK_OLLAMA_CONCURRENCY = 3

# Repli métier (line art) si le writer LLM ne renvoie pas de ``negative_prompt`` exploitable.
DEFAULT_LINEART_NEGATIVE_V1 = (
    "shading, gradients, gray tones, shadows, color fills, watercolor, painting, photo, "
    "realistic, 3D render, blurry, low quality, text, watermark, signature"
)


def _default_negative_prompt_for_profile(profile: str) -> str:
    p = (profile or "").strip()
    if p == "kids_coloring_lineart_v1" or p.startswith("kids_coloring_lineart"):
        return DEFAULT_LINEART_NEGATIVE_V1
    return ""


def _get_ollama_http_client() -> httpx.AsyncClient:
    global _ollama_http_client
    if _ollama_http_client is None or _ollama_http_client.is_closed:
        _ollama_http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=20),
        )
    return _ollama_http_client


def _apply_no_think_system(model: str, system: str) -> str:
    """Préfixe /no_think pour qwen3:* strict (le tag n'opère pas sur qwen3.5+).

    Pour qwen3.5 et ultérieurs, utiliser ``"think": false`` natif Ollama dans le
    body (cf. ``_native_think_disable`` ci-dessous).
    """
    m = (model or "").lower()
    if "qwen3:" in m and "qwen3." not in m:
        return "/no_think\n" + (system or "")
    return system


def _native_think_disable(model: str) -> bool:
    """qwen3.5+ : Ollama accepte le paramètre natif ``"think": false`` dans le body."""
    return "qwen3." in (model or "").lower()


# ─── Modèles de requêtes ──────────────────────────────────────────────────────

class EnrichTermRequest(BaseModel):
    term_id: str
    vocabulary_id: str
    fields: list[str] = []
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class GenerateContentRequest(BaseModel):
    concept_name_en: str
    concept_name_fr: str
    term_name_ar: str
    model: str | None = None
    max_retries: int | None = None


class PromptChainRequest(BaseModel):
    image_id: str | None = None
    concept_name_en: str | None = None
    title: str | None = None
    keywords: str | None = None
    tags_context: str | None = None
    profile: str | None = None
    workflow_template: str | None = None
    model: str | None = None
    temperature: float | None = None


class SuggestChildrenRequest(BaseModel):
    term_id: str
    vocabulary_id: str
    count: int = 5
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class GenerateVocabularyRequest(BaseModel):
    theme: str
    root_count: int = 5
    children_per_root: int = 3
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class EnrichKeywordsRequest(BaseModel):
    term_id: str
    vocabulary_id: str
    min_keywords: int = 5
    max_keywords: int = 15
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class EnrichTermsBatchRequest(BaseModel):
    term_ids: list[str]
    vocabulary_id: str
    fields: list[str] = []
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class GenerateConceptsRequest(BaseModel):
    """Génère des concepts à partir d'un thème. Optionnel : term_id+vocabulary_id pour ancrer dans la taxonomie."""
    theme: str
    term_id: str | None = None
    vocabulary_id: str | None = None
    count: int = 5
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class GeneratePromptsRequest(BaseModel):
    """Concepts à transformer en prompts line art. Soit concepts, soit term_id+vocabulary_id (ou taxonomy_id)."""
    concepts: list[dict[str, Any]] = []
    term_id: str | None = None
    vocabulary_id: str | None = None
    taxonomy_id: str | None = None  # alternative à vocabulary_id, résolu côté backend
    count: int = 3
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class SuggestPromptRequest(BaseModel):
    """Suggère un prompt amélioré. Soit image_id, soit title+prompt+tags."""
    image_id: str | None = None
    title: str = ""
    prompt: str = ""
    tags_context: str = ""
    count: int = 2
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class CreatePromptRequest(BaseModel):
    """Pipeline v1 : mots-clés / titre / tags → plan LLM → prompt structuré (défaut Ernie ; opt-in Z-Image)."""
    keywords: str = ""
    title: str = ""
    tags_context: str = ""
    profile: str = "kids_coloring_lineart_v1"
    workflow_template: str | None = Field(
        default=None,
        description="Workflow Comfy cible pour choisir writer/validate (ex. ernie-image-turbo-q8-api). Optionnel.",
    )
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class ImprovePromptRequest(BaseModel):
    """Améliore un prompt existant (variantes) — template improve_prompt_zimage."""
    prompt: str = ""
    title: str = ""
    tags_context: str = ""
    image_id: str | None = None
    count: int = 2
    workflow_template: str | None = Field(
        default=None,
        description="Workflow Comfy cible pour le template d'amélioration (ex. ernie-image-turbo-q8-api). Optionnel.",
    )
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class ValidatePromptRequest(BaseModel):
    """Validation heuristique du prompt (score + checks)."""
    prompt: str
    profile: str = "kids_coloring_lineart_v1"
    workflow_template: str | None = Field(
        default=None,
        description="Workflow Comfy cible pour le validateur (ex. ernie-image-turbo-q8-api). Optionnel.",
    )
    model: str | None = None
    temperature: float | None = None
    custom_system: str | None = None
    custom_prompt: str | None = None


class CreatePromptBulkItem(BaseModel):
    """Un concept image pour génération bulk v1 (même pipeline que create-prompt)."""
    image_id: str = ""
    keywords: str = ""
    title: str = ""
    tags_context: str = ""
    profile: str | None = None


class CreatePromptsBulkRequest(BaseModel):
    """Bulk : planner → writer par item ; validation optionnelle."""
    items: list[CreatePromptBulkItem]
    validate_prompts: bool = False
    workflow_template: str | None = Field(
        default=None,
        description="Workflow Comfy cible commun à tous les items bulk (ex. ernie-image-turbo-q8-api). Optionnel.",
    )
    model: str | None = None
    temperature: float | None = None


class PromptUpdateRequest(BaseModel):
    system_text: str
    user_text: str
    model: str | None = None
    temperature: float | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_yaml_prompts() -> dict:
    """Charge les templates de prompts depuis taxonomy_prompts.yaml (source de vérité)."""
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or {}
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Fichier de prompts introuvable : {PROMPTS_FILE}",
        )
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur parsing YAML prompts : {exc}",
        )


def _load_prompts(conn: DBConnAdapter | None = None) -> dict:
    """
    Charge les templates de prompts.
    Priorité : DB (ai_prompt_template) > taxonomy_prompts.yaml.
    Si une clé est manquante en DB, elle est complétée par le YAML.
    """
    yaml_data = _load_yaml_prompts()
    yaml_prompts = yaml_data.get("prompts", {})

    if conn is None:
        return yaml_data

    try:
        rows = conn.execute(
            "SELECT key, system_text, user_text, model, temperature FROM ai_prompt_template"
        ).fetchall()
    except Exception:
        return yaml_data

    if not rows:
        return yaml_data

    # Merge : DB overrides YAML for keys present in DB
    merged_prompts = dict(yaml_prompts)
    for row in rows:
        key, system_text, user_text, model, temperature = row
        base = dict(yaml_prompts.get(key, {}))
        base["system"] = system_text
        base["user"] = user_text
        if model:
            base["model"] = model
        if temperature is not None:
            base["temperature"] = temperature
        merged_prompts[key] = base

    result = dict(yaml_data)
    result["prompts"] = merged_prompts
    return result


def _get_prompt_template(prompts_data: dict, name: str) -> dict:
    """Retourne le template d'un prompt par nom."""
    tpl = prompts_data.get("prompts", {}).get(name)
    if not tpl:
        raise HTTPException(
            status_code=500,
            detail=f"Template de prompt '{name}' introuvable dans {PROMPTS_FILE}",
        )
    return tpl


def _load_image_prompts() -> dict:
    """Charge les templates depuis image_prompts.yaml."""
    try:
        with open(IMAGE_PROMPTS_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or {}
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Fichier de prompts introuvable : {IMAGE_PROMPTS_FILE}",
        )
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur parsing YAML image prompts : {exc}",
        )


def _get_image_prompt_template(name: str) -> dict:
    """Retourne le template d'un prompt image par nom."""
    data = _load_image_prompts()
    tpl = data.get("prompts", {}).get(name)
    if not tpl:
        raise HTTPException(
            status_code=500,
            detail=f"Template de prompt '{name}' introuvable dans {IMAGE_PROMPTS_FILE}",
        )
    return tpl


def _get_term(
    conn: DBConnAdapter, vocabulary_id: str, term_id: str
) -> dict[str, Any]:
    """Récupère un terme depuis la DB et le retourne au format API."""
    _ensure_vocabulary_exists(conn, vocabulary_id)
    rows = _get_terms_flat(conn, vocabulary_id)
    term_row = next((r for r in rows if r["id"] == term_id), None)
    if not term_row:
        raise HTTPException(
            status_code=404,
            detail=f"Terme '{term_id}' non trouvé dans le vocabulaire '{vocabulary_id}'",
        )
    out = _term_to_response(term_row)
    out["vocabulary_id"] = vocabulary_id
    return out


def _get_term_children(
    conn: DBConnAdapter, vocabulary_id: str, term_id: str
) -> list[dict[str, Any]]:
    """Retourne les enfants directs d'un terme."""
    _ensure_vocabulary_exists(conn, vocabulary_id)
    rows = _get_terms_flat(conn, vocabulary_id)
    children = [r for r in rows if r.get("parent_id") == term_id]
    return [_term_to_response(r) for r in children]


async def _call_ollama(
    prompt: str,
    system: str,
    model: str,
    temperature: float,
    timeout: int,
) -> str:
    """Appelle l'API Ollama /api/generate et retourne le texte brut de la réponse."""
    url = f"{OLLAMA.base_url}/api/generate"
    # Note : on N'utilise PAS "format": "json" car les modèles de type "thinking"
    # (Qwen3, DeepSeek-R1…) émettent d'abord des blocs <think>…</think> avant
    # le JSON, ce qui rend la sortie invalide pour la validation d'Ollama.
    # Notre _parse_json_response() gère déjà les think-tags et extrait le JSON.
    system = _apply_no_think_system(model, system)
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if _native_think_disable(model):
        payload["think"] = False
    logger.debug("Ollama → %s model=%s temp=%s", url, model, temperature)
    try:
        client = _get_ollama_http_client()
        res = await client.post(url, json=payload, timeout=float(timeout))
        res.raise_for_status()
        data = res.json()
        # Ollama peut retourner {"error": "..."} au niveau racine si le modèle échoue
        if "error" in data and "response" not in data:
            raise HTTPException(
                status_code=502,
                detail=f"Ollama erreur modèle : {data['error']}",
            )
        raw = data.get("response", "")
        logger.debug("Ollama ← %d chars : %s", len(raw), raw[:200])
        return raw
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama non disponible sur {OLLAMA.base_url}. "
                   "Assurez-vous qu'Ollama est démarré (`ollama serve`).",
        )
    except httpx.TimeoutException:
        logger.warning(
            "Ollama timeout model=%s timeout=%ss url=%s prompt_chars=%d",
            model,
            timeout,
            url,
            len(prompt),
        )
        raise HTTPException(
            status_code=504,
            detail=f"Ollama timeout après {timeout}s. Essayez un prompt plus court ou augmentez OLLAMA_TIMEOUT.",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur Ollama HTTP {exc.response.status_code} : {exc.response.text[:300]}",
        )


def _strip_think_tags(raw: str) -> str:
    """
    Qwen3 (et autres modèles 'thinking') insèrent des blocs <think>...</think>
    avant le JSON même quand format='json' est demandé.
    Cette fonction les supprime proprement.
    """
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE)
    return cleaned.strip()


def _repair_json_llm_typos(text: str) -> str:
    """
    Corrige des fautes fréquentes dans le JSON généré par les LLM (sans parseur JSON complet).
    Ex. clé avec guillemet doublé : , ""weight": -> , "weight":
    Contexte produit : docs/ai-model-strategy.md (« Réponses JSON des LLM : correction nécessaire »).
    """
    return re.sub(r',(\s*)""(\w+)"(\s*:)', r', \1"\2"\3', text)


def _parse_json_response(raw: str) -> Any:
    """
    Parse la réponse JSON d'Ollama après normalisation (_repair_json_llm_typos, _strip_think_tags).
    Les sorties LLM ne sont pas du JSON strict : voir docs/ai-model-strategy.md (« Réponses JSON des LLM »).
    Gère :
      - les blocs <think>...</think> de Qwen3 et autres modèles 'thinking'
      - les blocs ```json ... ``` ou ``` ... ```
      - le texte libre autour du JSON
    """
    raw = raw.strip()
    logger.debug("Ollama raw response (first 500): %s", raw[:500])

    # 1. Think-tags + typos fréquentes LLM (ex. ""clé" au lieu de "clé")
    clean = _repair_json_llm_typos(_strip_think_tags(raw))

    # 2. Tentative directe sur la réponse nettoyée
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # 3. Extraction depuis un bloc ```json ... ``` ou ``` ... ```
    for candidate in (clean, raw):
        match = re.search(r"```(?:json)?\s*([\[{][\s\S]*?[\]}])\s*```", candidate)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

    # 4. Extraction du premier objet ou tableau JSON valide
    for candidate in (clean, raw):
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = candidate.find(start_char)
            if start < 0:
                continue
            # Chercher la fermeture correspondante en comptant les niveaux
            depth = 0
            close_char = end_char
            for i, ch in enumerate(candidate[start:], start):
                if ch == start_char:
                    depth += 1
                elif ch == close_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(candidate[start : i + 1])
                        except json.JSONDecodeError:
                            break

    logger.error("Could not parse Ollama response as JSON. Raw: %s", raw[:600])
    raise HTTPException(
        status_code=422,
        detail=f"Réponse Ollama non parsable en JSON. Extrait : {clean[:300]}",
    )


def _detect_missing_fields(term: dict[str, Any], requested: list[str]) -> list[str]:
    """
    Si requested est vide, retourne tous les champs textuels vides.
    Sinon retourne la liste demandée telle quelle.
    """
    text_fields = [
        "name_fr", "name_en", "name_ar",
        "description_fr", "description_en", "description_ar",
    ]
    if requested:
        return requested
    return [f for f in text_fields if not term.get(f)]


def _resolve_model_temp(
    tpl: dict, req_model: str | None, req_temp: float | None
) -> tuple[str, float]:
    model = req_model or tpl.get("model") or OLLAMA.default_model
    temperature = req_temp if req_temp is not None else float(tpl.get("temperature", 0.3))
    return model, temperature


def _image_prompt_timeout(tpl: dict) -> int:
    """Timeout HTTP pour un template image (tpl.timeout > defaults.timeout > OLLAMA)."""
    try:
        data = _load_image_prompts()
    except HTTPException:
        return int(OLLAMA.default_timeout)
    return int(
        tpl.get("timeout")
        or data.get("defaults", {}).get("timeout", OLLAMA.default_timeout)
    )


# Negative prompt standard line-art (aligné sur templates YAML legacy / suggest)
Z_IMAGE_LINEART_NEGATIVE_PROMPT = (
    "shading, gradients, gray tones, shadows, color fills, watercolor, painting, photo, "
    "realistic, 3D render, blurry, low quality, text, watermark, signature"
)

# Limite lot bulk create-prompt v1 (évite timeouts navigateur / surcharge Ollama)
BULK_CREATE_PROMPTS_MAX_ITEMS = 10


def _http_exception_detail(exc: HTTPException) -> str:
    d = exc.detail
    if isinstance(d, str):
        return d
    return str(d)


def _fetch_image_title_tags_context(
    conn: DBConnAdapter, image_id: str
) -> tuple[str, str]:
    """Titre + tags (noms FR) pour enrichir le planner bulk."""
    title = ""
    tags_context = ""
    try:
        row = conn.execute("SELECT title FROM image WHERE id = ?", [image_id]).fetchone()
        if row:
            title = str(row[0] or "").strip()
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
            tags_context = ", ".join(n for n in names if n)
    except Exception:
        pass
    return title, tags_context


def _normalize_batch_planner_plans(parsed: Any, expected_n: int) -> list[dict[str, Any]]:
    """Extrait une liste de N objets plan depuis la réponse JSON du planner batch."""
    if isinstance(parsed, dict):
        for key in ("plans", "items", "results", "data"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break
        else:
            parsed = []
    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=422,
            detail="Batch planner : la réponse n'est pas un tableau JSON.",
        )
    if len(parsed) != expected_n:
        raise HTTPException(
            status_code=422,
            detail=f"Batch planner : attendu {expected_n} plan(s), reçu {len(parsed)}.",
        )
    out: list[dict[str, Any]] = []
    for i, p in enumerate(parsed):
        if not isinstance(p, dict):
            raise HTTPException(
                status_code=422,
                detail=f"Batch planner : l'élément {i} n'est pas un objet JSON.",
            )
        out.append(p)
    return out


async def _execute_batch_planner_v1(
    batch_items: list[dict[str, str]],
    *,
    model: str | None,
    temperature: float | None,
) -> tuple[list[dict[str, Any]], str, float, str]:
    """Un seul appel Ollama planner pour N items (même schéma de plan que l'item unique)."""
    planner_tpl = _get_image_prompt_template("prompt_planner_batch")
    p_model, p_temp = _resolve_model_temp(planner_tpl, model, temperature)
    p_timeout = _image_prompt_timeout(planner_tpl)
    items_json = json.dumps(
        [
            {
                "index": i,
                "profile": b["profile"],
                "keywords": b["keywords"],
                "title": b["title"],
                "tags_context": b["tags_context"],
            }
            for i, b in enumerate(batch_items)
        ],
        ensure_ascii=False,
        indent=2,
    )
    user = planner_tpl["user"].format(
        items_json=items_json,
        count=len(batch_items),
    )
    system = planner_tpl["system"]
    raw = await _call_ollama(user, system, p_model, p_temp, p_timeout)
    parsed = _parse_json_response(raw)
    plans = _normalize_batch_planner_plans(parsed, len(batch_items))
    return plans, p_model, p_temp, raw


async def _execute_writer_from_plan_v1(
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
    """Étape writer seule à partir d'un plan JSON (pipeline v1)."""
    tpl_keys = resolve_image_prompt_template_keys(workflow_template)
    writer_tpl = _get_image_prompt_template(tpl_keys["writer"])
    w_model, w_temp = _resolve_model_temp(writer_tpl, model, temperature)
    w_timeout = _image_prompt_timeout(writer_tpl)
    plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
    writer_user = writer_tpl["user"].format(plan_json=plan_json)
    writer_system = writer_tpl["system"]
    raw_out = await _call_ollama(writer_user, writer_system, w_model, w_temp, w_timeout)
    parsed_out = _parse_json_response(raw_out)
    final_prompt = ""
    final_negative = ""
    if isinstance(parsed_out, dict):
        final_prompt = str(parsed_out.get("prompt") or "").strip()
        final_negative = str(parsed_out.get("negative_prompt") or "").strip()
    if not final_prompt:
        raise HTTPException(
            status_code=422,
            detail="Le writer n'a pas renvoyé de champ 'prompt' exploitable.",
        )
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


async def _execute_create_prompt_v1(
    *,
    keywords: str,
    title: str,
    tags_context: str,
    profile: str,
    model: str | None,
    temperature: float | None,
    custom_system: str | None,
    custom_prompt: str | None,
    workflow_template: str | None = None,
) -> dict[str, Any]:
    """Pipeline v1 planner → writer (réutilisable par create-prompt et create-prompts-bulk)."""
    kw = (keywords or "").strip()
    title = (title or "").strip()
    tags = (tags_context or "").strip()
    if not kw and not title:
        raise HTTPException(
            status_code=400,
            detail="Fournir au moins `keywords` ou `title` pour créer un prompt.",
        )

    planner_tpl = _get_image_prompt_template("prompt_planner")
    p_model, p_temp = _resolve_model_temp(planner_tpl, model, temperature)
    p_timeout = _image_prompt_timeout(planner_tpl)

    profile = (profile or "kids_coloring_lineart_v1").strip()
    if custom_prompt is not None:
        planner_user = custom_prompt
    else:
        planner_user = planner_tpl["user"].format(
            profile=profile or "(default)",
            keywords=kw or "(none)",
            title=title or "(none)",
            tags_context=tags or "(none)",
        )
    planner_system = custom_system if custom_system is not None else planner_tpl["system"]

    raw_plan = await _call_ollama(planner_user, planner_system, p_model, p_temp, p_timeout)
    plan = _parse_json_response(raw_plan)
    if not isinstance(plan, dict):
        raise HTTPException(
            status_code=422,
            detail="Le planificateur n'a pas renvoyé un objet JSON attendu.",
        )

    return await _execute_writer_from_plan_v1(
        plan,
        profile=profile,
        model=model,
        temperature=temperature,
        model_planner=p_model,
        temperature_planner=p_temp,
        raw_plan=raw_plan,
        workflow_template=workflow_template,
    )


async def _execute_validate_prompt_v1(
    *,
    prompt: str,
    profile: str,
    model: str | None,
    temperature: float | None,
    custom_system: str | None,
    custom_prompt: str | None,
    workflow_template: str | None = None,
) -> dict[str, Any]:
    """Validation score + checks (réutilisable par validate-prompt et bulk)."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Le champ `prompt` est requis.")

    tpl_keys = resolve_image_prompt_template_keys(workflow_template)
    tpl = _get_image_prompt_template(tpl_keys["validate"])
    mdl, temp = _resolve_model_temp(tpl, model, temperature)
    timeout = _image_prompt_timeout(tpl)
    prof = (profile or "kids_coloring_lineart_v1").strip()

    if custom_prompt is not None:
        user_prompt = custom_prompt
    else:
        user_prompt = tpl["user"].format(profile=prof, prompt=prompt)
    system = custom_system if custom_system is not None else tpl["system"]

    raw = await _call_ollama(user_prompt, system, mdl, temp, timeout)
    data = _parse_json_response(raw)

    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="La validation n'a pas renvoyé un objet JSON.")

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


def _resolve_prompt_system(tpl: dict, custom_prompt: str | None, custom_system: str | None) -> tuple[str, str]:
    """Retourne (prompt_user, system) en tenant compte des surcharges custom."""
    system = custom_system if custom_system is not None else tpl["system"]
    prompt = custom_prompt if custom_prompt is not None else None
    return prompt, system



def _ai_enqueue(
    job_type: str,
    config: dict[str, Any],
    entity_type: str = "term",
    entity_id: str = "",
    conn: Any = None,
) -> dict[str, Any]:
    """Crée un job pending et renvoie {job_id, status, job_type}.

    Si ``conn`` est fourni (connexion de la route), l'utilise directement.
    Sinon ouvre une connexion write propre (ex. appel hors route).
    Lève HTTPException si le type est désactivé ou inconnu.
    """
    import random
    import time as _time
    from datetime import datetime, timezone

    own_conn = None
    if conn is None:
        from api.db import get_db_sync
        own_conn = get_db_sync(read_only=False)
        conn = own_conn

    try:
        row = conn.execute(
            "SELECT enabled FROM job_type_config WHERE type = ?",
            [job_type],
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=400,
                detail=f"Type de job '{job_type}' inconnu dans job_type_config.",
            )
        if not bool(row[0]):
            raise HTTPException(
                status_code=400,
                detail=f"Le type de job '{job_type}' est désactivé.",
            )

        job_id = f"job_ai_{_time.time_ns()}_{random.randint(1000, 9999)}"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        config_json = json.dumps(config, ensure_ascii=False)

        conn.execute(
            """
            INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, priority)
            VALUES (?, ?, 'pending', ?, ?, ?, ?, 5)
            """,
            [job_id, job_type, config_json, now, entity_type, entity_id or None],
        )
        conn.session.commit()
    finally:
        if own_conn is not None:
            own_conn.close()

    return {"job_id": job_id, "status": "pending", "job_type": job_type}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/enrich-term")
async def enrich_term(
    body: EnrichTermRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Enrichit les champs manquants d'un terme. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "vocabulary_id": body.vocabulary_id,
        "term_id": body.term_id,
        "fields": body.fields,
    }
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue("taxonomy_enrich_term", config, "term", body.term_id, conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/enrich-terms-batch")
async def enrich_terms_batch(
    body: EnrichTermsBatchRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Enrichit plusieurs termes en lot. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "vocabulary_id": body.vocabulary_id,
        "term_ids": body.term_ids,
        "fields": body.fields,
    }
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue(
        "taxonomy_enrich_terms_batch", config, "taxonomy_batch", body.vocabulary_id, conn=conn
    )
    return JSONResponse(content=result, status_code=202)


@router.post("/prompt-chain")
async def prompt_chain_endpoint(
    body: PromptChainRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Exécute la chaîne planner→writer→validator en une passe (P2 ⑥a — POC-3 v2).

    Synchrone (pas de queue). Retourne le prompt line-art final + score validator
    + latences par étape. Pour appel async batch via worker, utiliser le job type
    ``image_prompt_chain`` (cf. POST /api/jobs/enqueue).
    """
    from services.ai_jobs_sync import run_image_prompt_chain_sync
    config: dict[str, Any] = {}
    for f in (
        "image_id", "concept_name_en", "title", "keywords", "tags_context",
        "profile", "workflow_template", "model", "temperature",
    ):
        v = getattr(body, f, None)
        if v is not None and v != "":
            config[f] = v
    try:
        result = run_image_prompt_chain_sync(conn, config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"prompt-chain failed: {type(exc).__name__}: {exc}",
        ) from exc
    # Pas de raw_* dans la réponse HTTP par défaut (lourd).
    public = {k: v for k, v in result.items() if not k.startswith("raw_")}
    return public


@router.post("/generate-content")
async def generate_content_endpoint(body: GenerateContentRequest) -> dict[str, Any]:
    """Génère le contenu éditorial i18n EN+FR+AR pour un concept (P2 ⑥b).

    Synchrone : retourne le ContentResult sérialisé en JSON. Latence typique
    ~10-30 s (3 appels LLM séquentiels + jusqu'à `max_retries` retries AR).
    """
    from services.content_generator import (
        content_result_to_dict,
        generate_content,
    )
    kwargs: dict[str, Any] = {
        "concept_name_en": body.concept_name_en,
        "concept_name_fr": body.concept_name_fr,
        "term_name_ar": body.term_name_ar,
    }
    if body.model is not None:
        kwargs["model"] = body.model
    if body.max_retries is not None:
        kwargs["max_retries"] = body.max_retries
    try:
        result = generate_content(**kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"generate_content failed: {type(exc).__name__}: {exc}") from exc
    return content_result_to_dict(result)


@router.post("/suggest-children")
async def suggest_children(
    body: SuggestChildrenRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Suggère des termes enfants. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "vocabulary_id": body.vocabulary_id,
        "term_id": body.term_id,
        "count": body.count,
    }
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue(
        "taxonomy_suggest_children", config, "term", body.term_id, conn=conn
    )
    return JSONResponse(content=result, status_code=202)


@router.post("/generate-vocabulary")
async def generate_vocabulary(
    body: GenerateVocabularyRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Génère un vocabulaire complet. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "theme": body.theme,
        "root_count": body.root_count,
        "children_per_root": body.children_per_root,
        "target_vocabulary_id": getattr(body, "target_vocabulary_id", None) or "",
    }
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue("taxonomy_generate_vocabulary", config, "vocabulary", "", conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/enrich-keywords")
async def enrich_keywords(
    body: EnrichKeywordsRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Génère des mots-clés SEO. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "vocabulary_id": body.vocabulary_id,
        "term_id": body.term_id,
        "min_keywords": body.min_keywords,
        "max_keywords": body.max_keywords,
    }
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue(
        "taxonomy_enrich_keywords", config, "term", body.term_id, conn=conn
    )
    return JSONResponse(content=result, status_code=202)


# ─── Endpoints : prompts images (line art) ─────────────────────────────────────

@router.post("/generate-concepts")
async def generate_concepts(
    body: GenerateConceptsRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Génère des concepts image. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "theme": body.theme,
        "count": body.count,
    }
    if body.term_id:
        config["term_id"] = body.term_id
    if body.vocabulary_id:
        config["vocabulary_id"] = body.vocabulary_id
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue("image_generate_concepts", config, "concept_batch", "", conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/generate-prompts")
async def generate_prompts(
    body: GeneratePromptsRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """
    Génère des prompts line art à partir de concepts ou d'un terme taxonomique.
    En mode async (défaut) : renvoie {job_id, status} HTTP 202.
    """
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {"count": body.count, "concepts": list(body.concepts)}
    if body.term_id:
        config["term_id"] = body.term_id
    if body.vocabulary_id:
        config["vocabulary_id"] = body.vocabulary_id
    if body.taxonomy_id:
        config["taxonomy_id"] = body.taxonomy_id
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue("image_generate_prompts", config, "image", "", conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/suggest-prompt")
async def suggest_prompt(
    body: SuggestPromptRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Suggère un prompt amélioré. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "title": body.title or "",
        "prompt": body.prompt or "",
        "tags_context": body.tags_context or "",
        "count": body.count,
    }
    if body.image_id:
        config["image_id"] = body.image_id
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    entity_id = body.image_id or ""
    result = _ai_enqueue("image_prompt_suggest", config, "image", entity_id, conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/create-prompt")
async def create_prompt(
    body: CreatePromptRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Pipeline v1 planner→writer. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "keywords": body.keywords or "",
        "title": body.title or "",
        "tags_context": body.tags_context or "",
        "profile": (body.profile or "kids_coloring_lineart_v1").strip(),
    }
    if body.workflow_template:
        config["workflow_template"] = body.workflow_template
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue("image_prompt_create", config, "image", "", conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/create-prompts-bulk")
async def create_prompts_bulk(
    body: CreatePromptsBulkRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """
    Génère des prompts v1 (planner → writer) pour plusieurs concepts.
    Renvoie {job_id, status} HTTP 202 (job image_prompts_bulk).
    """
    from fastapi.responses import JSONResponse
    items_config = [
        {
            "image_id": item.image_id or "",
            "keywords": item.keywords or "",
            "title": item.title or "",
            "tags_context": item.tags_context or "",
            "profile": item.profile or "kids_coloring_lineart_v1",
        }
        for item in body.items
    ]
    config: dict[str, Any] = {
        "items": items_config,
        "validate_prompts": body.validate_prompts,
    }
    if body.workflow_template:
        config["workflow_template"] = body.workflow_template
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    result = _ai_enqueue("image_prompts_bulk", config, "image", "", conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/improve-prompt")
async def improve_prompt(
    body: ImprovePromptRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Améliore un prompt (variantes). Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "prompt": body.prompt or "",
        "title": body.title or "",
        "tags_context": body.tags_context or "",
        "count": body.count,
    }
    if body.image_id:
        config["image_id"] = body.image_id
    if body.workflow_template:
        config["workflow_template"] = body.workflow_template
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    entity_id = body.image_id or ""
    result = _ai_enqueue("image_prompt_improve", config, "image", entity_id, conn=conn)
    return JSONResponse(content=result, status_code=202)


@router.post("/validate-prompt")
async def validate_prompt(
    body: ValidatePromptRequest,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Contrôle qualité heuristique. Renvoie {job_id, status} HTTP 202."""
    from fastapi.responses import JSONResponse
    config: dict[str, Any] = {
        "prompt": body.prompt,
        "profile": (body.profile or "kids_coloring_lineart_v1").strip(),
    }
    if body.workflow_template:
        config["workflow_template"] = body.workflow_template
    if body.model is not None:
        config["model"] = body.model
    if body.temperature is not None:
        config["temperature"] = body.temperature
    if body.custom_prompt is not None:
        config["custom_prompt"] = body.custom_prompt
    if body.custom_system is not None:
        config["custom_system"] = body.custom_system
    result = _ai_enqueue("image_prompt_validate", config, "image", "", conn=conn)
    return JSONResponse(content=result, status_code=202)


# ─── Endpoints : gestion des prompts ─────────────────────────────────────────

@router.get("/prompts")
async def list_prompts(
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """
    Retourne les 4 templates de prompts (DB en priorité, YAML en fallback).
    Chaque entrée indique si elle est surchargée en DB ou non.
    """
    prompts_data = _load_prompts(conn)
    yaml_data = _load_yaml_prompts()
    yaml_prompts = yaml_data.get("prompts", {})

    # Récupérer les clés présentes en DB
    try:
        db_keys = {r[0] for r in conn.execute("SELECT key FROM ai_prompt_template").fetchall()}
    except Exception:
        db_keys = set()

    result = {}
    for key in PROMPT_KEYS:
        tpl = prompts_data.get("prompts", {}).get(key, {})
        yaml_tpl = yaml_prompts.get(key, {})
        result[key] = {
            "key": key,
            "description": yaml_tpl.get("description", ""),
            "system_text": tpl.get("system", ""),
            "user_text": tpl.get("user", ""),
            "model": tpl.get("model") or OLLAMA.default_model,
            "temperature": float(tpl.get("temperature", 0.3)),
            "overridden_in_db": key in db_keys,
        }
    return result


@router.get("/prompts/{key}")
async def get_prompt(
    key: str,
    conn: DBConnAdapter = Depends(get_db_read),
) -> dict[str, Any]:
    """Retourne un template de prompt par clé (taxonomie ou image)."""
    if key in IMAGE_PROMPT_KEYS:
        tpl = _get_image_prompt_template(key)
        return {
            "key": key,
            "description": tpl.get("description", ""),
            "system_text": tpl.get("system", ""),
            "user_text": tpl.get("user", ""),
            "model": tpl.get("model") or OLLAMA.default_model,
            "temperature": float(tpl.get("temperature", 0.3)),
            "overridden_in_db": False,
        }
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Clé de prompt inconnue : '{key}'")

    prompts_data = _load_prompts(conn)
    yaml_data = _load_yaml_prompts()
    yaml_tpl = yaml_data.get("prompts", {}).get(key, {})
    tpl = prompts_data.get("prompts", {}).get(key, {})

    try:
        db_keys = {r[0] for r in conn.execute("SELECT key FROM ai_prompt_template WHERE key = ?", [key]).fetchall()}
    except Exception:
        db_keys = set()

    return {
        "key": key,
        "description": yaml_tpl.get("description", ""),
        "system_text": tpl.get("system", ""),
        "user_text": tpl.get("user", ""),
        "model": tpl.get("model") or OLLAMA.default_model,
        "temperature": float(tpl.get("temperature", 0.3)),
        "overridden_in_db": key in db_keys,
    }


@router.put("/prompts/{key}")
async def update_prompt(
    key: str,
    body: PromptUpdateRequest,
    conn: DBConnAdapter = Depends(get_db_write),
) -> dict[str, Any]:
    """
    Sauvegarde un template de prompt en DB (upsert).
    Prend le dessus sur le YAML pour cette clé.
    """
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Clé de prompt inconnue : '{key}'. Valeurs : {PROMPT_KEYS}")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO ai_prompt_template (key, system_text, user_text, model, temperature, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (key) DO UPDATE SET
            system_text = excluded.system_text,
            user_text = excluded.user_text,
            model = excluded.model,
            temperature = excluded.temperature,
            updated_at = excluded.updated_at
        """,
        [key, body.system_text, body.user_text, body.model, body.temperature, now],
    )
    return {"key": key, "updated": True, "updated_at": now}


@router.post("/prompts/{key}/reset")
async def reset_prompt(
    key: str,
    conn: DBConnAdapter = Depends(get_db_write),
) -> dict[str, Any]:
    """
    Supprime la surcharge DB pour une clé de prompt.
    La clé retombe sur le fallback YAML.
    """
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Clé de prompt inconnue : '{key}'. Valeurs : {PROMPT_KEYS}")

    conn.execute("DELETE FROM ai_prompt_template WHERE key = ?", [key])
    return {"key": key, "reset": True, "source": "yaml"}


# ─── Endpoint utilitaire : vérification de la disponibilité d'Ollama ─────────

@router.get("/status")
async def ollama_status() -> dict[str, Any]:
    """Vérifie que l'API Ollama est accessible et retourne les modèles disponibles."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{OLLAMA.base_url}/api/tags")
            res.raise_for_status()
            data = res.json()
            models = [m.get("name") for m in data.get("models", [])]
            return {
                "available": True,
                "base_url": OLLAMA.base_url,
                "configured_model": OLLAMA.default_model,
                "models": models,
            }
    except Exception as exc:
        return {
            "available": False,
            "base_url": OLLAMA.base_url,
            "configured_model": OLLAMA.default_model,
            "error": str(exc),
        }


class PlaygroundRequest(BaseModel):
    """Payload pour `POST /api/ai/playground` (UI de test prompts Ollama).

    - ``think`` : par défaut auto (None) — applique la logique projet
      (qwen3:* strict → ``/no_think`` system tag ; qwen3.5+ → ``"think": false``
      natif). Si ``think`` est explicitement ``True``, on laisse think actif
      (utile pour comparer). Si ``False`` explicite, on force désactivation.
    """

    prompt: str
    model: str | None = None
    system: str = ""
    temperature: float = 0.0
    think: bool | None = None  # None = auto (désactivé par convention projet)
    timeout: int | None = None


@router.post("/playground")
async def ollama_playground(payload: PlaygroundRequest) -> dict[str, Any]:
    """Endpoint simple pour tester un prompt sur Ollama (UI playground).

    Pas de persistance, pas de JSON parsing — texte brut renvoyé.
    Gère automatiquement `/no_think` (qwen3:* strict) et `think: false`
    (qwen3.5+) selon le modèle. Désactivable explicitement via `think=True`.
    """
    import time

    model = (payload.model or OLLAMA.default_model).strip()
    system = payload.system or ""
    timeout = int(payload.timeout) if payload.timeout else OLLAMA.default_timeout

    # Logique think : None (auto) = désactivé selon convention projet.
    # True explicite = laisser actif. False explicite = désactivé.
    disable_think = payload.think is not True  # auto-désactivé sauf si think=True

    think_handling = {"strategy": "default-active"}
    if disable_think:
        system = _apply_no_think_system(model, system)
        think_handling = {
            "strategy": "qwen3-strict-/no_think"
            if system.startswith("/no_think")
            else "qwen3.5-native"
            if _native_think_disable(model)
            else "no-disable-needed",
            "system_prefixed": system.startswith("/no_think"),
            "native_think_false": _native_think_disable(model),
        }

    body: dict = {
        "model": model,
        "prompt": payload.prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": float(payload.temperature)},
    }
    if disable_think and _native_think_disable(model):
        body["think"] = False

    url = f"{OLLAMA.base_url}/api/generate"
    t0 = time.perf_counter()
    try:
        client = _get_ollama_http_client()
        res = await client.post(url, json=body, timeout=float(timeout))
        res.raise_for_status()
        data = res.json()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if "error" in data and "response" not in data:
            return {
                "ok": False,
                "error": data["error"],
                "latency_ms": latency_ms,
                "model": model,
                "think_handling": think_handling,
            }
        return {
            "ok": True,
            "response": data.get("response", ""),
            "model": model,
            "latency_ms": latency_ms,
            "think_handling": think_handling,
            "total_duration_ns": data.get("total_duration"),
            "eval_count": data.get("eval_count"),
            "prompt_eval_count": data.get("prompt_eval_count"),
        }
    except httpx.ConnectError:
        return {
            "ok": False,
            "error": f"Ollama non disponible sur {OLLAMA.base_url} — démarre `ollama serve`",
            "model": model,
            "think_handling": think_handling,
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "error": f"Timeout après {timeout}s",
            "model": model,
            "think_handling": think_handling,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "model": model,
            "think_handling": think_handling,
        }
