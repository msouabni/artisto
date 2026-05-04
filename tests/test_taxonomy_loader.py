"""Tests du loader CLI de taxonomie (sans accès direct duckdb.connect)."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import taxonomy as taxonomy_module


def test_load_taxonomy_from_db_uses_current_db_adapter(test_conn, monkeypatch):
    monkeypatch.setattr("api.db.get_db_sync", lambda read_only=True: test_conn)

    tx = taxonomy_module.load_taxonomy_from_db()

    assert tx.taxonomy_id == "universal_v0"
    assert any(v.id == "themes" for v in tx.vocabularies)


def test_get_taxonomy_falls_back_to_json_when_db_unavailable(monkeypatch):
    sentinel = object()

    def _boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(taxonomy_module, "load_taxonomy_from_db", _boom)
    monkeypatch.setattr(taxonomy_module, "load_taxonomy", lambda path=taxonomy_module.DEFAULT_TAXONOMY_PATH: sentinel)

    assert taxonomy_module.get_taxonomy() is sentinel
