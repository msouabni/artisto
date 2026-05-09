"""add metadata jsonb to term

Revision ID: 0005_term_metadata_jsonb
Revises: 0004_seed_new_job_types
Create Date: 2026-05-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_term_metadata_jsonb"
down_revision = "0004_seed_new_job_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ajoute la colonne metadata JSONB nullable sur term.

    Cible Postgres → JSONB explicite. Côté SQLite (tests via Base.metadata.create_all),
    l'attribut Python `Term.node_metadata` est défini avec sa.JSON dans le modèle, ce
    qui produira un type JSON portable. Cette migration n'est jamais exécutée en
    test (conftest reconstruit le schéma depuis le modèle).
    """
    op.add_column(
        "term",
        sa.Column("metadata", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("term", "metadata")
