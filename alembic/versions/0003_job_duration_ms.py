"""add duration_ms to job table

Revision ID: 0003_job_duration_ms
Revises: 0002_seed_job_type_config
Create Date: 2026-04-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_job_duration_ms"
down_revision = "0002_seed_job_type_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job", sa.Column("duration_ms", sa.Integer(), nullable=True))
    # Back-fill computed duration for already-finished jobs
    op.execute(
        """
        UPDATE job
        SET duration_ms = EXTRACT(EPOCH FROM (
            CAST(finished_at AS TIMESTAMPTZ) - CAST(started_at AS TIMESTAMPTZ)
        )) * 1000
        WHERE finished_at IS NOT NULL AND started_at IS NOT NULL
          AND duration_ms IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("job", "duration_ms")
