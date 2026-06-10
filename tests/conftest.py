"""Pytest fixtures for API tests with SQLAlchemy (SQLite memory)."""
from __future__ import annotations

import os

os.environ["ARTISTE_LOG_TO_FILE"] = "0"
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
# Tests legacy supposent le mode lineart historique (passage en pastel
# 2026-05-31 est une transition prod, mais les tests restent ancres sur
# le mode lineart). Tests dedies pastel : tests/test_prompt_generator_pastel.py.
os.environ["ARTISTE_PROMPT_STYLE"] = "lineart"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.db import DBConnAdapter, ensure_default_job_types, get_db_read, get_db_write
from api.models import Base


def _make_test_conn() -> DBConnAdapter:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    conn = DBConnAdapter(session)
    conn.execute(
        "INSERT INTO taxonomy (taxonomy_id, label_i18n, languages) VALUES (?, ?, ?)",
        ["universal_v0", "{}", '["fr","en","ar"]'],
    )
    conn.execute(
        "INSERT INTO vocabulary (id, taxonomy_id, label_i18n) VALUES (?, ?, ?)",
        ["themes", "universal_v0", "{}"],
    )
    ensure_default_job_types(session)
    conn.execute(
        "UPDATE job_type_config SET enabled = 1 WHERE type = 'text_enrichment'",
    )
    session.commit()
    return conn


@pytest.fixture
def test_conn():
    conn = _make_test_conn()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def app_with_test_db(test_conn):
    from api.main import app

    def override_get_db_read():
        yield test_conn

    def override_get_db_write():
        yield test_conn

    app.dependency_overrides[get_db_read] = override_get_db_read
    app.dependency_overrides[get_db_write] = override_get_db_write
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_db_read, None)
        app.dependency_overrides.pop(get_db_write, None)