"""create image_publication table (publication layer i18n)

Revision ID: 0010_image_publication
Revises: 0009_subject_add_source
Create Date: 2026-05-10

Brief : 2026-05-10_brief-mep-v0-A-modele-publication.md

Ajoute la couche publication : 1 image × 3 locales = 3 lignes. Porte les champs
i18n (``title`` / ``description``), les slugs (R2 partagé, Post par locale) et
le statut publication (``pending`` → ``ready_for_export`` → ``published_alwan``).

PK composite ``(image_id, locale)`` ; FK ``image_id`` → ``image.id`` avec
``ON DELETE CASCADE`` ; index sur ``status`` et ``r2_slug`` ; unicité
``(locale, post_slug)``.

Cette migration cible Postgres. Côté SQLite (tests), le schéma est reconstruit
depuis le modèle SQLAlchemy via ``Base.metadata.create_all`` — la migration
n'est jamais exécutée en test.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_image_publication"
down_revision = "0009_subject_add_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crée la table ``image_publication`` avec ses index et contraintes."""
    op.create_table(
        "image_publication",
        sa.Column("image_id", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("post_slug", sa.Text(), nullable=True),
        sa.Column("r2_slug", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=True,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "image_id", "locale", name="pk_image_publication",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["image.id"],
            name="fk_image_publication_image_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "locale", "post_slug", name="uq_image_publication_post_slug",
        ),
    )
    op.create_index(
        "idx_image_publication_status",
        "image_publication",
        ["status"],
    )
    op.create_index(
        "idx_image_publication_r2_slug",
        "image_publication",
        ["r2_slug"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_image_publication_r2_slug", table_name="image_publication",
    )
    op.drop_index(
        "idx_image_publication_status", table_name="image_publication",
    )
    op.drop_table("image_publication")
