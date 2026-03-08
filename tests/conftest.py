"""Fixtures pytest pour les tests API taxonomie."""
from __future__ import annotations

import duckdb
import pytest

from api.db import get_db


def _make_test_conn():
    """Connexion DuckDB en mémoire avec schéma minimal taxonomie."""
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE taxonomy (taxonomy_id TEXT PRIMARY KEY, label_i18n TEXT, languages TEXT)")
    conn.execute("INSERT INTO taxonomy (taxonomy_id, label_i18n, languages) VALUES ('universal_v0', '{}', '[\"fr\",\"en\",\"ar\"]')")
    conn.execute(
        "CREATE TABLE vocabulary (id TEXT PRIMARY KEY, taxonomy_id TEXT NOT NULL REFERENCES taxonomy(taxonomy_id), label_i18n TEXT)"
    )
    conn.execute("INSERT INTO vocabulary (id, taxonomy_id, label_i18n) VALUES ('themes', 'universal_v0', '{}')")
    conn.execute("""
        CREATE TABLE term (
            id TEXT NOT NULL,
            vocabulary_id TEXT NOT NULL REFERENCES vocabulary(id),
            parent_id TEXT,
            slug TEXT NOT NULL,
            slug_i18n TEXT,
            name_i18n TEXT,
            description_i18n TEXT,
            weight INTEGER,
            keywords TEXT,
            PRIMARY KEY (id, vocabulary_id)
        )
    """)
    return conn


@pytest.fixture
def test_conn():
    """Connexion DuckDB test (mémoire)."""
    conn = _make_test_conn()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def app_with_test_db(test_conn):
    """Application FastAPI avec get_db surchargé pour utiliser la DB test."""
    from api.main import app
    from api import db

    def override_get_db():
        yield test_conn

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_db, None)
