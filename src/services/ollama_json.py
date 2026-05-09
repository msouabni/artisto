"""Parsing JSON Ollama et appels HTTP synchrones (partagé worker / scripts / services)."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "60"))


def strip_think_tags(raw: str) -> str:
    """Supprime les blocs <think>...</think> des modeles thinking."""
    return re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()


def parse_json_response(raw: str) -> Any:
    """Parse la reponse JSON d'Ollama. Gere think-tags et blocs ```json."""
    raw = raw.strip()
    clean = strip_think_tags(raw)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*([\[{][\s\S]*?[\]}])\s*```", clean)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start = clean.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(clean[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(clean[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"Reponse Ollama non parsable en JSON. Extrait : {clean[:300]}")


def _supports_native_think_disable(model: str | None) -> bool:
    """Retourne True si le modele supporte le parametre natif Ollama think=false.

    qwen3.5+ supporte "think": false dans le body de la requete.
    qwen3: strict (sans .5) necessite le tag /no_think dans le system prompt.
    """
    m = (model or OLLAMA_MODEL or "").lower()
    return bool(re.search(r"qwen3\.5", m))


def apply_no_think_system(model: str | None, system: str) -> str:
    """Injecte /no_think uniquement pour qwen3: strict (pas qwen3.5+).

    Pour qwen3.5+ utiliser le parametre natif "think": false dans le body Ollama
    (cf. _supports_native_think_disable).
    Aligne avec api.routes.ai._apply_no_think_system.
    """
    m = (model or OLLAMA_MODEL or "").lower()
    # qwen3: strict uniquement -- exclure qwen3.5 qui supporte native think disable
    if re.search(r"qwen3(?!\.5)", m):
        return "/no_think\n" + (system or "")
    return system


def call_ollama_sync(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    timeout: int | None = None,
) -> str:
    """Appelle Ollama /api/generate de facon synchrone."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    m = model or OLLAMA_MODEL
    system = apply_no_think_system(m, system)
    payload = {
        "model": m,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        with httpx.Client(timeout=float(timeout or OLLAMA_TIMEOUT)) as client:
            res = client.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            if "error" in data and "response" not in data:
                raise RuntimeError(f"Ollama erreur modele : {data['error']}")
            return data.get("response", "")
    except httpx.TimeoutException as exc:
        logger.warning(
            "Ollama timeout (sync) model=%s timeout=%ss url=%s prompt_chars=%d",
            model or OLLAMA_MODEL,
            timeout or OLLAMA_TIMEOUT,
            url,
            len(prompt),
        )
        raise RuntimeError(
            f"Ollama timeout apres {timeout or OLLAMA_TIMEOUT}s sur {model or OLLAMA_MODEL}"
        ) from exc


def call_ollama_sync_with_drift_retry(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    timeout: int | None = None,
) -> tuple[str, dict]:
    """Stub de compat : appelle ``call_ollama_sync`` sans logique drift-retry.

    Restauration minimale apres suppression de la fonction d'origine -- les
    callers (``services/ai_jobs_sync.py``) attendent ``(raw, drift_meta)``.
    Si le drift-retry est necessaire, il faudra le reimplementer ici.
    """
    raw = call_ollama_sync(prompt, system, model=model, temperature=temperature, timeout=timeout)
    return raw, {"drift_retry": False}
