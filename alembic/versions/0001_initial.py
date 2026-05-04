"""initial schema via SQLAlchemy metadata

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-16
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

# Project code lives under `src/` (imports like `api.models`).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
