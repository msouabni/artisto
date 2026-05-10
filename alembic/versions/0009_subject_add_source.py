"""add source column to subject

Revision ID: 0009_subject_add_source
Revises: 0008_image_output_qc_tags
Create Date: 2026-05-10

Ajout post-livraison V1.2 : colonne ``source`` sur ``subject``.

Le brief V1.2 demandait ``source TEXT NOT NULL`` mais la migration 0007
initiale a été livrée sans (omission). V1.3 (import skill v0) utilise
``source='skill_v0'`` comme critère d'idempotence — donc la colonne
doit exister comme colonne SQL directe (pas via JSON metadata).

Cette migration ajoute ``source`` avec ``server_default='manual'`` pour
ne pas casser les rows existants (qui prennent 'manual' par défaut).
Côté Python, le modèle SQLAlchemy a aussi ``default='manual'``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_subject_add_source"
down_revision = "0008_image_output_qc_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subject",
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.create_index("idx_subject_source", "subject", ["source"])


def downgrade() -> None:
    op.drop_index("idx_subject_source", table_name="subject")
    op.drop_column("subject", "source")
