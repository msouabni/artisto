"""Compatibility shim to keep legacy imports while migrating off DuckDB."""
from __future__ import annotations

from typing import Any


class Error(Exception):
    pass


class DuckDBPyConnection:
    pass


def connect(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("duckdb shim in use: direct duckdb.connect is no longer supported")
