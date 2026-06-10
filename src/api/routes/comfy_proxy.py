"""Proxy minimal vers ComfyUI pour contourner CORS depuis le browser.

Le navigateur ne peut pas appeler directement http://127.0.0.1:8188 depuis
http://127.0.0.1:8000/data/...html (CORS refuse). Ce proxy expose les
endpoints ComfyUI necessaires au playground avec la meme origin que l'API.

Endpoints :
    POST /api/comfy/submit              -> POST {COMFY_URL}/prompt
    GET  /api/comfy/history/{prompt_id} -> GET  {COMFY_URL}/history/{prompt_id}
    GET  /api/comfy/view                -> GET  {COMFY_URL}/view?filename=...&...
                                            (stream binaire de l'image)

L'URL ComfyUI est configurable via env COMFY_URL (default http://127.0.0.1:8188).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
PROXY_TIMEOUT = 30.0

router = APIRouter(prefix="/api/comfy", tags=["comfy-proxy"])


@router.post("/submit")
async def submit_workflow(request: Request) -> dict:
    """Forwarde un POST /prompt vers ComfyUI."""
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            r = await client.post(f"{COMFY_URL}/prompt", json=body)
    except httpx.RequestError as e:
        logger.warning("Proxy ComfyUI submit echoue : %s", e)
        raise HTTPException(502, f"ComfyUI inaccessible : {e}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@router.get("/history/{prompt_id}")
async def get_history(prompt_id: str) -> dict:
    """Forwarde un GET /history/{prompt_id} vers ComfyUI."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            r = await client.get(f"{COMFY_URL}/history/{prompt_id}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"ComfyUI inaccessible : {e}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@router.get("/view")
async def view_image(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
) -> Response:
    """Forwarde un GET /view?filename=...&subfolder=...&type=... vers ComfyUI.

    Stream le contenu binaire de l'image (PNG).
    """
    params = {"filename": filename, "subfolder": subfolder, "type": type}
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            r = await client.get(f"{COMFY_URL}/view", params=params)
    except httpx.RequestError as e:
        raise HTTPException(502, f"ComfyUI inaccessible : {e}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return Response(
        content=r.content,
        media_type=r.headers.get("content-type", "image/png"),
    )
