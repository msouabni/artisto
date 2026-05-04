"""seed default job types

Revision ID: 0002_seed_job_type_config
Revises: 0001_initial
Create Date: 2026-04-16
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.db import DEFAULT_JOB_TYPES

revision = "0002_seed_job_type_config"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    for spec in DEFAULT_JOB_TYPES:
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
    conn.exec_driver_sql(
        "DELETE FROM job_type_config WHERE type IN (%s, %s)",
        tuple(spec["type"] for spec in DEFAULT_JOB_TYPES),
    )
