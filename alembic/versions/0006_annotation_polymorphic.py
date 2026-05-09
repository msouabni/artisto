"""create annotation table (polymorphic)

Revision ID: 0006_annotation_polymorphic
Revises: 0005_term_metadata_jsonb
Create Date: 2026-05-09

Brief : 2026-05-09_brief-greffon-prod.md (table polymorphe d'annotation
humaine, attachable à n'importe quel objet pipeline via target_type +
target_id, initialement ``image_output``).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_annotation_polymorphic"
down_revision = "0005_term_metadata_jsonb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crée la table ``annotation`` polymorphe avec ses index.

    Cible Postgres → JSONB explicite pour ``image_tags`` / ``prompt_tags`` /
    ``custom_tags``. Côté SQLite (tests via ``Base.metadata.create_all``),
    le modèle utilise ``sqlalchemy.JSON`` cross-dialect — cette migration
    n'est jamais exécutée en test (conftest reconstruit le schéma depuis
    le modèle).
    """
    op.create_table(
        "annotation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("image_tags", postgresql.JSONB, nullable=True),
        sa.Column("prompt_tags", postgresql.JSONB, nullable=True),
        sa.Column("custom_tags", postgresql.JSONB, nullable=True),
        sa.Column(
            "pattern",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("pattern_note", sa.Text(), nullable=True),
        sa.Column(
            "sample",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "publishable",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "target_type", "target_id", name="uq_annotation_target",
        ),
    )
    op.create_index(
        "idx_annotation_target",
        "annotation",
        ["target_type", "target_id"],
    )
    op.create_index(
        "idx_annotation_updated",
        "annotation",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_annotation_updated", table_name="annotation")
    op.drop_index("idx_annotation_target", table_name="annotation")
    op.drop_table("annotation")
