"""seed image_generate_prompts, image_prompt_suggest, image_prompts_bulk

Revision ID: 0004_seed_new_job_types
Revises: 0003_job_duration_ms
Create Date: 2026-04-24
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

revision = "0004_seed_new_job_types"
down_revision = "0003_job_duration_ms"
branch_labels = None
depends_on = None

NEW_TYPES = (
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
)


def upgrade() -> None:
    conn = op.get_bind()
    for spec in NEW_TYPES:
        conn.exec_driver_sql(
            """
            INSERT INTO job_type_config (type, label, enabled, max_concurrent, description, category, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (type) DO NOTHING
            """,
            (
                spec["type"],
                spec["label"],
                spec["enabled"],
                spec["max_concurrent"],
                spec["description"],
                spec["category"],
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    types = tuple(spec["type"] for spec in NEW_TYPES)
    conn.exec_driver_sql(
        "DELETE FROM job_type_config WHERE type IN (%s, %s, %s)",
        types,
    )
