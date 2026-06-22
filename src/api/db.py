"""SQLAlchemy DB layer + adapter for legacy SQL call sites."""
from __future__ import annotations

import os
import re
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://artiste:artiste@127.0.0.1:5432/artiste_coloriage",
)

ENGINE = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)

DEFAULT_JOB_TYPES = (
    {
        "type": "image_generation",
        "label": "Generation image (ComfyUI)",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Generation d'images via diffusion",
        "category": "image",
    },
    {
        "type": "text_enrichment",
        "label": "Enrichissement texte (Ollama)",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Enrichissement taxonomies, images, etc.",
        "category": "text",
    },
    {
        "type": "taxonomy_enrich_term",
        "label": "Taxonomie : enrichir un terme",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Suggestions de champs pour un terme (revue)",
        "category": "text",
    },
    {
        "type": "taxonomy_enrich_terms_batch",
        "label": "Taxonomie : enrichir plusieurs termes",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Lot de termes (revue)",
        "category": "text",
    },
    {
        "type": "taxonomy_enrich_keywords",
        "label": "Taxonomie : mots-cles",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Mots-cles SEO pour un terme",
        "category": "text",
    },
    {
        "type": "taxonomy_suggest_children",
        "label": "Taxonomie : suggerer des enfants",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Nouveaux termes enfants (import)",
        "category": "text",
    },
    {
        "type": "taxonomy_generate_vocabulary",
        "label": "Taxonomie : generer un vocabulaire",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Arborescence proposee (import)",
        "category": "text",
    },
    {
        "type": "image_prompt_create",
        "label": "Prompt image : creation (planner+writer)",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Pipeline Z-Image pour une image",
        "category": "text",
    },
    {
        "type": "image_prompt_improve",
        "label": "Prompt image : amelioration",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Variantes de prompt",
        "category": "text",
    },
    {
        "type": "image_prompt_validate",
        "label": "Prompt image : validation score",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Score et checks",
        "category": "text",
    },
    {
        "type": "image_prompt_chain",
        "label": "Prompt image : chaine complete (planner->writer->validator)",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Genere et valide un prompt line-art en une seule passe (POC-3 v2)",
        "category": "text",
    },
    {
        "type": "image_generate_concepts",
        "label": "Concepts image (themes / sous-themes)",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Generation de concepts line-art ; revue puis creation en base",
        "category": "text",
    },
    {
        "type": "image_generate_prompts",
        "label": "Prompts image : generation depuis concepts",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Genere des prompts line-art a partir d'une liste de concepts ou d'un terme taxonomique",
        "category": "text",
    },
    {
        "type": "image_prompt_suggest",
        "label": "Prompt image : suggestion",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Suggere un nouveau prompt pour une image (contexte image_id ou titre/tags direct)",
        "category": "text",
    },
    {
        "type": "image_prompts_bulk",
        "label": "Prompts image : generation bulk (planner+writer)",
        "enabled": False,
        "max_concurrent": 1,
        "description": "Pipeline planner->writer pour plusieurs concepts ; validation optionnelle",
        "category": "text",
    },
    {
        "type": "image_qc_auto",
        "label": "QC auto image (deterministe)",
        "enabled": False,
        "max_concurrent": 1,
        "description": "5 regles deterministes (couleur/contraste/complexite/saturation) -> qc_tags sur image_output",
        "category": "image",
    },
    {
        "type": "image_post_processing",
        "label": "Post-traitement coloriage (vectorisation + coloriage interactif)",
        "enabled": True,
        "max_concurrent": 2,
        "description": "Genere SVG vectoriel print et SVG coloriage interactif depuis le PNG raw.",
        "category": "image",
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SqlResult:
    def __init__(self, result: Result[Any]) -> None:
        self._r = result

    def fetchall(self):
        return self._r.fetchall()

    def fetchone(self):
        return self._r.fetchone()


def _qmark_to_named(sql: str, params: list[Any] | tuple[Any, ...] | None) -> tuple[str, dict[str, Any]]:
    if not params:
        return sql, {}
    idx = 0

    def repl(_: re.Match[str]) -> str:
        nonlocal idx
        token = f"p{idx}"
        idx += 1
        return f":{token}"

    converted = re.sub(r"\?", repl, sql)
    bind = {f"p{i}": v for i, v in enumerate(params)}
    return converted, bind


class DBConnAdapter:
    """Adapter wrapping a SQLAlchemy Session with a duckdb-compatible execute/fetchall interface."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> SqlResult:
        converted, bind = _qmark_to_named(sql, params)
        res = self.session.execute(text(converted), bind)
        return SqlResult(res)

    def close(self) -> None:
        self.session.close()


def get_db_read() -> Generator[DBConnAdapter, None, None]:
    session = SessionLocal()
    try:
        yield DBConnAdapter(session)
    finally:
        session.close()


def get_db_write() -> Generator[DBConnAdapter, None, None]:
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


def get_db() -> Generator[DBConnAdapter, None, None]:
    yield from get_db_write()


def get_db_sync(read_only: bool = False, db_path: Path | None = None) -> DBConnAdapter:
    _ = read_only
    _ = db_path
    return DBConnAdapter(SessionLocal())


def ensure_default_job_types(session: Session) -> None:
    """Seed idempotent des types de jobs requis par l'UI et les workers."""
    from api.models import JobTypeConfig

    existing_rows = session.query(JobTypeConfig).all()
    existing = {row.type: row for row in existing_rows}
    now = _now()
    changed = False

    for spec in DEFAULT_JOB_TYPES:
        if spec["type"] in existing:
            row = existing[spec["type"]]
            row.label = row.label or spec["label"]
            row.max_concurrent = row.max_concurrent or spec["max_concurrent"]
            row.description = row.description or spec["description"]
            row.category = row.category or spec["category"]
            if not row.updated_at:
                row.updated_at = now
            continue

        session.add(JobTypeConfig(updated_at=now, **spec))
        changed = True

    if changed:
        session.flush()


def init_db(path: Path | None = None) -> None:
    _ = path
    from api.models import Base
    # Enregistre les tables du cockpit git-autoritaire (work_item / git_index)
    # sur Base.metadata avant create_all (sinon non créées hors tests).
    from api import cockpit_models  # noqa: F401

    Base.metadata.create_all(bind=ENGINE)
    session = SessionLocal()
    try:
        ensure_default_job_types(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
