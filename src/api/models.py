from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Locale(Base):
    __tablename__ = "locale"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool | None] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int | None] = mapped_column(Integer, default=0)


class Taxonomy(Base):
    __tablename__ = "taxonomy"
    taxonomy_id: Mapped[str] = mapped_column(String, primary_key=True)
    label_i18n: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Vocabulary(Base):
    __tablename__ = "vocabulary"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    taxonomy_id: Mapped[str] = mapped_column(ForeignKey("taxonomy.taxonomy_id"), nullable=False)
    label_i18n: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Term(Base):
    __tablename__ = "term"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    vocabulary_id: Mapped[str] = mapped_column(ForeignKey("vocabulary.id"), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    slug_i18n: Mapped[str | None] = mapped_column(Text)
    name_i18n: Mapped[str | None] = mapped_column(Text)
    description_i18n: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[int | None] = mapped_column(Integer, default=0)
    keywords: Mapped[str | None] = mapped_column(Text)
    # Colonne `metadata` (JSONB côté Postgres, JSON côté SQLite via JSON type
    # cross-dialect). Attribut Python renommé `node_metadata` pour éviter le
    # conflit avec `Base.metadata` (réservé SQLAlchemy).
    node_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)

    # Relation vers ``subject`` (sous-objets éditoriaux d'un term). FK
    # composite (term_id, vocabulary_id) → (term.id, term.vocabulary_id).
    # ``passive_deletes=True`` pour laisser Postgres faire le ON DELETE CASCADE
    # côté SQL ; côté SQLite tests, l'enforcement FK est désactivé par défaut.
    subjects: Mapped[list["Subject"]] = relationship(
        "Subject",
        back_populates="term",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Site(Base):
    __tablename__ = "site"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name_i18n: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    default_locale: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str | None] = mapped_column(Text)
    taxonomy_config_path: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class SiteTaxonomy(Base):
    __tablename__ = "site_taxonomy"
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id"), primary_key=True)
    source_taxonomy_id: Mapped[str | None] = mapped_column(ForeignKey("taxonomy.taxonomy_id"))
    config_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "job"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    image_id: Mapped[str | None] = mapped_column(String)
    config: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int | None] = mapped_column(Integer, default=5)
    retry_count: Mapped[int | None] = mapped_column(Integer, default=0)
    max_retries: Mapped[int | None] = mapped_column(Integer, default=3)
    scheduled_at: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String)
    result: Mapped[str | None] = mapped_column(Text)
    external_ref_id: Mapped[str | None] = mapped_column(String)
    progress: Mapped[int | None] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String)
    last_heartbeat_at: Mapped[str | None] = mapped_column(Text)
    batch_ref: Mapped[str | None] = mapped_column(String)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class JobTypeConfig(Base):
    __tablename__ = "job_type_config"
    type: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool | None] = mapped_column(Boolean, default=False)
    max_concurrent: Mapped[int | None] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Image(Base):
    __tablename__ = "image"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String, default="draft")
    selected_output_id: Mapped[str | None] = mapped_column(String)
    current_job_id: Mapped[str | None] = mapped_column(String)
    origin_type: Mapped[str | None] = mapped_column(String, default="manual")
    origin_batch_id: Mapped[str | None] = mapped_column(String)
    origin_term_id: Mapped[str | None] = mapped_column(String)
    origin_taxonomy_id: Mapped[str | None] = mapped_column(String)
    file_path: Mapped[str | None] = mapped_column(Text)
    file_format: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Float)
    prompt_used: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class ImageOutput(Base):
    __tablename__ = "image_output"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    image_id: Mapped[str] = mapped_column(ForeignKey("image.id"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("job.id"))
    file_path: Mapped[str] = mapped_column(Text, default="")
    text_content: Mapped[str | None] = mapped_column(Text)
    file_format: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Float)
    model_name: Mapped[str | None] = mapped_column(Text)
    model_config: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    # Tags QC déterministes posés par le worker `image_qc_auto` (brief
    # 2026-05-10). JSON cross-dialect : liste de strings sur SQLite,
    # JSONB côté Postgres via la migration 0008.
    qc_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)


class ImageTaxonomyTag(Base):
    __tablename__ = "image_taxonomy_tag"
    image_id: Mapped[str] = mapped_column(ForeignKey("image.id"), primary_key=True)
    taxonomy_id: Mapped[str] = mapped_column(ForeignKey("taxonomy.taxonomy_id"), primary_key=True)
    term_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str | None] = mapped_column(Text)


class CoverageStats(Base):
    __tablename__ = "coverage_stats"
    term_id: Mapped[str] = mapped_column(String, primary_key=True)
    taxonomy_id: Mapped[str] = mapped_column(ForeignKey("taxonomy.taxonomy_id"), primary_key=True)
    image_count: Mapped[int | None] = mapped_column(Integer, default=0)
    collection_count: Mapped[int | None] = mapped_column(Integer, default=0)
    computed_at: Mapped[str | None] = mapped_column(Text)


class Collection(Base):
    __tablename__ = "collection"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True)
    name_i18n: Mapped[str | None] = mapped_column(Text)
    term_id: Mapped[str | None] = mapped_column(String)
    taxonomy_id: Mapped[str | None] = mapped_column(ForeignKey("taxonomy.taxonomy_id"))
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class CollectionImage(Base):
    __tablename__ = "collection_image"
    collection_id: Mapped[str] = mapped_column(ForeignKey("collection.id"), primary_key=True)
    image_id: Mapped[str] = mapped_column(ForeignKey("image.id"), primary_key=True)
    sort_order: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[str | None] = mapped_column(Text)


class Export(Base):
    __tablename__ = "export"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    collection_id: Mapped[str | None] = mapped_column(ForeignKey("collection.id"))
    site_id: Mapped[str | None] = mapped_column(ForeignKey("site.id"))
    output_path: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("job.id"))
    status: Mapped[str | None] = mapped_column(String, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[str | None] = mapped_column(Text)


class SitePublication(Base):
    __tablename__ = "site_publication"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id"), nullable=False)
    image_id: Mapped[str] = mapped_column(ForeignKey("image.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String, default="pending")
    created_at: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(Text)


class AiPromptTemplate(Base):
    __tablename__ = "ai_prompt_template"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    system_text: Mapped[str | None] = mapped_column(Text)
    user_text: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String)
    temperature: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Annotation(Base):
    """Table polymorphe d'annotation humaine (greffon prod, brief 2026-05-09).

    Une seule table qui peut s'attacher à n'importe quel objet de la pipeline
    (initialement ``image_output`` côté prod ; ``image``, ``term``, etc. en
    extension future). Pas de FK explicite : l'intégrité polymorphe est gérée
    applicativement (whitelist côté API, vérification light d'existence du
    ``target_id`` selon le ``target_type``).

    Les colonnes JSON utilisent ``sqlalchemy.JSON`` cross-dialect (TEXT côté
    SQLite, JSONB côté Postgres via la migration). Le code applicatif ne doit
    **pas** s'appuyer sur des opérateurs JSON Postgres-only — sérialiser /
    désérialiser explicitement.
    """

    __tablename__ = "annotation"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", name="uq_annotation_target"),
        Index("idx_annotation_target", "target_type", "target_id"),
        Index("idx_annotation_updated", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prompt_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    custom_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    pattern: Mapped[bool | None] = mapped_column(Boolean, default=False)
    pattern_note: Mapped[str | None] = mapped_column(Text)
    sample: Mapped[bool | None] = mapped_column(Boolean, default=False)
    publishable: Mapped[bool | None] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class Subject(Base):
    """Sous-objet éditorial d'un ``term`` (brief 2026-05-10).

    Un ``subject`` matérialise un sujet concret rattaché à un term taxonomique
    (ex. term=``lion`` → subjects=``lion mâle adulte sur rocher``,
    ``lionceau jouant``). Il porte le statut éditorial, une note humaine 0-6,
    une liste de tags whitelisted, un brief textuel et un bloc metadata libre.

    FK composite vers ``term`` (PK = ``id`` + ``vocabulary_id``). La colonne
    physique pour le bloc metadata est ``subject_metadata`` côté SQL pour
    éviter le conflit avec ``Base.metadata`` (réservé SQLAlchemy) — l'attribut
    Python ``subject_metadata`` reflète directement ce nom (pas d'alias).

    Côté Postgres (migration 0007) : ``tags`` et ``subject_metadata`` en JSONB,
    contraintes CHECK natives sur ``status`` et ``note``. Côté SQLite (tests),
    l'``status`` est enforced uniquement via Pydantic ; les CheckConstraint sont
    bien créés mais SQLite enforce les CHECK depuis 3.3+ — on garde la double
    barrière (Pydantic + DB).
    """

    __tablename__ = "subject"
    __table_args__ = (
        ForeignKeyConstraint(
            ["term_id", "vocabulary_id"],
            ["term.id", "term.vocabulary_id"],
            name="fk_subject_term",
            ondelete="CASCADE",
        ),
        UniqueConstraint("term_id", "name", name="uq_subject_term_name"),
        CheckConstraint(
            "note IS NULL OR (note >= 0 AND note <= 6)",
            name="ck_subject_note_range",
        ),
        CheckConstraint(
            "status IN ('draft','annotated','validated','enriched',"
            "'prompted','generated','qc_done','published','rejected')",
            name="ck_subject_status_whitelist",
        ),
        Index("idx_subject_term", "term_id", "vocabulary_id"),
        Index("idx_subject_status", "status"),
        Index("idx_subject_updated", "updated_at"),
        Index("idx_subject_source", "source"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    term_id: Mapped[str] = mapped_column(Text, nullable=False)
    vocabulary_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    note: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_metadata: Mapped[dict | None] = mapped_column(
        "subject_metadata", JSON, nullable=True
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    term: Mapped["Term"] = relationship("Term", back_populates="subjects")
