"""add qc_tags column on image_output

Revision ID: 0008_image_output_qc_tags
Revises: 0006_annotation_polymorphic
Create Date: 2026-05-10

Brief : 2026-05-10_brief-qc-auto-worker.md (worker QC déterministe sur
``image_output`` qui pose 5 tags après chaque génération réussie).

La colonne ``qc_tags`` stocke la liste des tags QC posés par le worker
``image_qc_auto`` (par ex. ``["qc_color_residual", "qc_low_contrast"]``
ou ``["qc_ok"]``). Type JSONB côté Postgres pour requêtes futures
(filtrage par tag) ; côté SQLite (tests) le modèle SQLAlchemy utilise
``JSON`` cross-dialect — cette migration n'est pas exécutée en test
(conftest reconstruit le schéma depuis le modèle).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_image_output_qc_tags"
down_revision = "0007_subject_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "image_output",
        sa.Column("qc_tags", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("image_output", "qc_tags")
