"""create subject table

Revision ID: 0007_subject_table
Revises: 0006_annotation_polymorphic
Create Date: 2026-05-10

Brief : 2026-05-10_brief-modele-subject.md (modèle ``subject`` éditorial,
sous-objet d'un ``term``). Permet de matérialiser un sujet concret (ex.
"lion mâle adulte sur rocher") rattaché à un term taxonomique. Utilisé
ultérieurement par le pipeline pour produire des prompts spécifiques.

Schéma :
- ``id`` : UUID/text, PK
- ``term_id`` + ``vocabulary_id`` : FK composite vers ``term`` (PK composée)
- ``name`` : libellé court éditorial (unique par term_id)
- ``status`` : whitelist {draft, annotated, validated, enriched, prompted,
  generated, qc_done, published, rejected}
- ``note`` : entier 0-6 (CHECK 0..6)
- ``tags`` : JSONB (liste de tags whitelisted)
- ``brief`` : texte libre (description éditoriale)
- ``metadata`` : JSONB libre
- ``created_at`` / ``updated_at`` : ISO text

Cible Postgres → JSONB explicite. Côté SQLite (tests via
``Base.metadata.create_all``), le modèle utilise ``sqlalchemy.JSON``
cross-dialect — cette migration n'est jamais exécutée en test.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_subject_table"
down_revision = "0006_annotation_polymorphic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crée la table ``subject`` avec ses contraintes et index."""
    op.create_table(
        "subject",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("term_id", sa.Text(), nullable=False),
        sa.Column("vocabulary_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("note", sa.Integer(), nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("subject_metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["term_id", "vocabulary_id"],
            ["term.id", "term.vocabulary_id"],
            name="fk_subject_term",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "term_id", "name", name="uq_subject_term_name",
        ),
        sa.CheckConstraint(
            "note IS NULL OR (note >= 0 AND note <= 6)",
            name="ck_subject_note_range",
        ),
        sa.CheckConstraint(
            "status IN ('draft','annotated','validated','enriched',"
            "'prompted','generated','qc_done','published','rejected')",
            name="ck_subject_status_whitelist",
        ),
    )
    op.create_index(
        "idx_subject_term",
        "subject",
        ["term_id", "vocabulary_id"],
    )
    op.create_index(
        "idx_subject_status",
        "subject",
        ["status"],
    )
    op.create_index(
        "idx_subject_updated",
        "subject",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_subject_updated", table_name="subject")
    op.drop_index("idx_subject_status", table_name="subject")
    op.drop_index("idx_subject_term", table_name="subject")
    op.drop_table("subject")
