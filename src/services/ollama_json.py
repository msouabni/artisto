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
    """Supprime les blocs <think>...</think> des modèles thinking."""
    return re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()


def parse_json_response(raw: str) -> Any:
    """Parse la réponse JSON d'Ollama. Gère think-tags et blocs ```json."""
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
    raise ValueError(f"Réponse Ollama non parsable en JSON. Extrait : {clean[:300]}")


def apply_no_think_system(model: str | None, system: str) -> str:
    """Réduit le mode thinking sur Qwen3 (aligné api.routes.ai._apply_no_think_system)."""
    m = (model or OLLAMA_MODEL or "").lower()
    if "qwen3" in m:
        return "/no_think\n" + (system or "")
    return system


def call_ollama_sync(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    timeout: int | None = None,
) -> str:
    """Appelle Ollama /api/generate de façon synchrone."""
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
                raise RuntimeError(f"Ollama erreur modèle : {data['error']}")
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
            f"Ollama timeout après {timeout or OLLAMA_TIMEOUT}s sur {model or OLLAMA_MODEL}"
        ) from exc
