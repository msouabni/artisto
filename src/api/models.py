from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


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
