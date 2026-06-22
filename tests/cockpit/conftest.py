"""Conftest DÉDIÉ Postgres pour les tests du cockpit git-autoritaire.

Cap : PostgreSQL unique. SQLite est INTERDIT, y compris pour les tests (le
dialecte diverge → faux verts). Ces tests tournent sur une **Postgres
éphémère** : un schéma jetable créé sur la Postgres docker
(``docker compose up -d postgres``), ``create_all``, puis teardown (DROP SCHEMA
CASCADE).

Ce conftest est isolé sous ``tests/cockpit/`` et ne touche PAS le conftest
SQLite global (``tests/conftest.py``). Il N'IMPORTE PAS ce dernier et force
``DATABASE_URL`` Postgres avant tout import de ``api.db``.

URL configurable via ``COCKPIT_TEST_DATABASE_URL`` (défaut = la Postgres docker
du projet). Si la base est injoignable, les tests sont SKIPPÉS (pas de faux
vert, pas de bascule SQLite).
"""
from __future__ import annotations

import os
import uuid

# Empêche l'écriture de logs fichier en test.
os.environ["ARTISTE_LOG_TO_FILE"] = "0"

# URL Postgres de test (jamais SQLite). Doit être posée AVANT d'importer api.db.
_PG_URL = os.environ.get(
    "COCKPIT_TEST_DATABASE_URL",
    "postgresql+psycopg://artiste:artiste@127.0.0.1:5432/artiste_coloriage",
)
os.environ["DATABASE_URL"] = _PG_URL

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

# Importe les modèles cockpit pour qu'ils s'enregistrent sur Base.metadata.
from api import cockpit_models  # noqa: F401
from api.db import DBConnAdapter
from api.models import Base


def _pg_reachable(url: str) -> bool:
    try:
        eng = create_engine(url, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except OperationalError:
        return False
    except Exception:
        return False


# Tables du cockpit créées/droppées dans le schéma éphémère (ne touche pas le
# schéma public de prod).
_COCKPIT_TABLES = [
    cockpit_models.WorkItem.__table__,
    cockpit_models.GitIndex.__table__,
    cockpit_models.Opportunity.__table__,
    cockpit_models.Schedule.__table__,
    cockpit_models.IndexStatus.__table__,
]


@pytest.fixture(scope="session")
def pg_engine():
    """Engine Postgres + schéma éphémère jetable. Skip si Postgres injoignable."""
    if not _pg_reachable(_PG_URL):
        pytest.skip(
            "Postgres injoignable — lance `docker compose up -d postgres`. "
            "SQLite est interdit pour ces tests (faux verts)."
        )

    schema = f"cockpit_test_{uuid.uuid4().hex[:12]}"
    # search_path pointé sur le schéma éphémère pour toutes les connexions.
    engine = create_engine(
        _PG_URL,
        future=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    # Crée le schéma (sur une connexion sans le search_path encore appliqué au
    # DDL de schéma — CREATE SCHEMA est qualifié explicitement).
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    # create_all des SEULES tables cockpit dans le schéma éphémère.
    Base.metadata.create_all(bind=engine, tables=_COCKPIT_TABLES)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture(autouse=True)
def _truncate_between_tests(pg_engine):
    """Isolation : tables cockpit vierges avant CHAQUE test (toutes fixtures).

    autouse → s'applique aussi aux tests n'utilisant que ``client`` (qui ne
    passe pas par ``pg_session``), évitant l'accumulation de lignes commitées
    entre tests.
    """
    with pg_engine.begin() as c:
        c.execute(text("TRUNCATE work_item, git_index, opportunity, schedule, index_status"))
    yield


@pytest.fixture
def pg_session(pg_engine):
    """Session SQLAlchemy sur la Postgres éphémère."""
    SessionLocal = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def conn(pg_session):
    """``DBConnAdapter`` (interface ``execute(sql, [params])`` placeholders ``?``)."""
    adapter = DBConnAdapter(pg_session)
    yield adapter


@pytest.fixture
def client(pg_engine):
    """TestClient FastAPI avec dépendances DB overridées vers la Postgres éphémère."""
    from fastapi.testclient import TestClient

    from api.db import get_db_read, get_db_write
    from api.main import app

    SessionLocal = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, future=True)

    def _override_read():
        session = SessionLocal()
        try:
            yield DBConnAdapter(session)
        finally:
            session.close()

    def _override_write():
        session = SessionLocal()
        try:
            adapter = DBConnAdapter(session)
            yield adapter
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db_read] = _override_read
    app.dependency_overrides[get_db_write] = _override_write
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_read, None)
        app.dependency_overrides.pop(get_db_write, None)
