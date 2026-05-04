"""Helpers partages pour tous les routers FastAPI."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Generator

from fastapi import HTTPException
from fastapi.responses import Response


def to_json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "item"):
        return obj.item()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    return str(obj)


def json_response(data: Any) -> Response:
    body = json.dumps(to_json_safe(data), ensure_ascii=False).encode("utf-8")
    return Response(content=body, media_type="application/json; charset=utf-8")


def get_i18n(val: str | None, key: str) -> str:
    if not val:
        return ""
    try:
        data = json.loads(val) if isinstance(val, str) else val
        out = data.get(key, "") or ""
        return str(out) if out is not None else ""
    except (json.JSONDecodeError, TypeError):
        return ""


def to_i18n(**locales: str) -> str:
    d = {k: v for k, v in locales.items() if v}
    return json.dumps(d, ensure_ascii=False) if d else "{}"


@contextmanager
def transaction(conn: Any) -> Generator[Any, None, None]:
    try:
        tx = conn.session.begin_nested() if conn.session.in_transaction() else conn.session.begin()
        with tx:
            yield conn
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


async def extract_error_detail(res: Any) -> str:
    try:
        body = await res.json() if hasattr(res, "json") else {}
    except Exception:
        body = {}
    detail = body.get("detail", "")
    if isinstance(detail, str):
        return detail
    return json.dumps(detail, ensure_ascii=False)
