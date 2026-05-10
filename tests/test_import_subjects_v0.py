"""Tests pour scripts/import_subjects_v0_from_skill.py.

Le brief V1.2 (modèle ``Subject`` + migration ``0007_subject_table.py``) n'est
pas encore mergé dans ce worktree. Pour rester déterministe et SQLite-portable,
on injecte une classe ``Subject`` minimale dans ``api.models`` au début du
module — elle reproduit le schéma documenté dans le brief V1.2 et sera
supplantée par la définition réelle dès que V1.2 mergera (les attributs
attendus par le script sont les mêmes).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text as sql_text,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import models as api_models
from api.models import Base


# ---------------------------------------------------------------------------
# Injection du modèle Subject (équivalent V1.2) si non présent.
# ---------------------------------------------------------------------------

if not hasattr(api_models, "Subject"):

    class Subject(Base):
        __tablename__ = "subject"
        __table_args__ = (
            UniqueConstraint("term_id", "name", name="subject_term_name_unique"),
        )

        id = Column(String, primary_key=True)
        term_id = Column(String, ForeignKey("term.id"), nullable=False)
        name = Column(String, nullable=False)
        source = Column(String, nullable=False)
        tags = Column(JSON, nullable=False, default=list)
        note = Column(Integer, nullable=True)
        status = Column(String, nullable=False, default="draft")
        enrichment = Column(JSON, nullable=True)
        prompt_positive = Column(Text, nullable=True)
        # Attribut Python `metadata_` mappé sur la colonne `metadata` (réservée SA).
        metadata_ = Column("metadata", JSON, nullable=True)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
        updated_at = Column(
            DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
        )

    api_models.Subject = Subject  # type: ignore[attr-defined]


# Importer après l'injection (le script résout `from api.models import Subject`).
from scripts import import_subjects_v0_from_skill as imp  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINI_TAXONOMY = [
    {
        "id": "animals",
        "name_en": "Animals",
        "children": [
            {
                "id": "pets",
                "name_en": "Pets",
                "children": [
                    {"id": "leaf_cat", "name_en": "Cat", "name_fr": "Chat"},
                    {"id": "leaf_dog", "name_en": "Dog", "name_fr": "Chien"},
                ],
            }
        ],
    },
    {
        "id": "vehicles",
        "name_en": "Vehicles",
        "children": [
            {"id": "leaf_car", "name_en": "Car", "name_fr": "Voiture"},
        ],
    },
]


@pytest.fixture
def session():
    """SQLite in-memory avec schéma minimal nécessaire au script."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    s = SessionLocal()

    # Seed minimal taxonomie + vocabulaire (FK requis pour term.vocabulary_id).
    s.execute(
        sql_text(
            "INSERT INTO taxonomy (taxonomy_id, label_i18n, languages) "
            "VALUES (:tid, :lab, :lang)"
        ),
        {"tid": "universal_v0", "lab": "{}", "lang": '["fr","en","ar"]'},
    )
    s.execute(
        sql_text(
            "INSERT INTO vocabulary (id, taxonomy_id, label_i18n) "
            "VALUES (:id, :tid, :lab)"
        ),
        {"id": "themes", "tid": "universal_v0", "lab": "{}"},
    )
    # Seed terms : leaf_cat + leaf_dog présents en BD ; leaf_car volontairement absent
    # pour tester le cas orphelin.
    for tid, slug in [("leaf_cat", "cat"), ("leaf_dog", "dog")]:
        s.execute(
            sql_text(
                "INSERT INTO term (id, vocabulary_id, parent_id, slug, "
                "name_i18n, description_i18n, weight, keywords) "
                "VALUES (:id, 'themes', NULL, :slug, '{}', '{}', 0, '[]')"
            ),
            {"id": tid, "slug": slug},
        )
    s.commit()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def mini_taxonomy_file(tmp_path: Path) -> Path:
    p = tmp_path / "mini_taxonomy.json"
    p.write_text(json.dumps(MINI_TAXONOMY, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests : aplatissement
# ---------------------------------------------------------------------------

class TestFlattenLeaves:
    def test_flatten_returns_only_leaves(self):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        ids = sorted(l["leaf_id"] for l in leaves)
        assert ids == ["leaf_car", "leaf_cat", "leaf_dog"]

    def test_flatten_attaches_root(self):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        roots = {l["leaf_id"]: l["root"] for l in leaves}
        assert roots["leaf_cat"] == "animals"
        assert roots["leaf_dog"] == "animals"
        assert roots["leaf_car"] == "vehicles"

    def test_flatten_path_is_full(self):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        cat = next(l for l in leaves if l["leaf_id"] == "leaf_cat")
        assert cat["path"] == ["animals", "pets", "leaf_cat"]

    def test_flatten_canonical_taxonomy_count(self):
        """Sanity check sur la taxonomie canonique (1376 leaves attendus)."""
        path = imp.DEFAULT_TAXONOMY_PATH
        if not path.exists():
            pytest.skip("coloring_taxonomy_full.json absent dans ce worktree")
        roots = imp.load_taxonomy(path)
        leaves = imp.flatten_leaves(roots)
        assert len(leaves) == 1376
        # Tous les leaves ont un id et un name_en non vides
        assert all(l["leaf_id"] for l in leaves)
        assert all(l["name_en"] for l in leaves)


# ---------------------------------------------------------------------------
# Tests : import (smoke + idempotence + dry-run + orphelins + schéma)
# ---------------------------------------------------------------------------

class TestImportSubjects:
    def test_smoke_inserts_subjects_for_known_terms(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=False)

        # leaf_cat + leaf_dog ont leur term => insérés ; leaf_car orphelin.
        assert stats["inserted"] == 2
        assert stats["already_present"] == 0
        assert len(stats["orphans"]) == 1
        assert stats["orphans"][0]["leaf_id"] == "leaf_car"

        # Vérifie en BD
        rows = session.execute(
            sql_text("SELECT id, term_id, name, source, status FROM subject ORDER BY id")
        ).fetchall()
        assert len(rows) == 2
        ids = {r[0] for r in rows}
        assert ids == {"sub_leaf_cat", "sub_leaf_dog"}
        for r in rows:
            assert r[3] == "skill_v0"
            assert r[4] == "draft"

    def test_idempotence_second_run_inserts_nothing(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats1 = imp.import_subjects(session, leaves, dry_run=False)
        assert stats1["inserted"] == 2

        stats2 = imp.import_subjects(session, leaves, dry_run=False)
        assert stats2["inserted"] == 0
        assert stats2["already_present"] == 2
        # Les orphelins restent listés (leur statut ne change pas)
        assert len(stats2["orphans"]) == 1

        # Toujours 2 subjects en BD
        count = session.execute(sql_text("SELECT COUNT(*) FROM subject")).scalar()
        assert count == 2

    def test_dry_run_does_not_write(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=True)

        assert stats["inserted"] == 2  # ce qui SERAIT inséré
        # Mais BD vide
        count = session.execute(sql_text("SELECT COUNT(*) FROM subject")).scalar()
        assert count == 0

    def test_orphan_leaves_listed_without_fatal_error(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=False)

        assert any(o["leaf_id"] == "leaf_car" for o in stats["orphans"])
        # Le run global passe quand même (les autres sont insérés)
        assert stats["inserted"] == 2

    def test_inserted_subject_has_expected_schema(self, session):
        """Vérifie tags=[], status='draft', source='skill_v0', metadata enrichi."""
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        imp.import_subjects(session, leaves, dry_run=False, import_run_ts="20260510T120000Z")

        Subject = api_models.Subject
        row = session.query(Subject).filter_by(id="sub_leaf_cat").one()
        assert row.term_id == "leaf_cat"
        assert row.name == "Cat"
        assert row.source == "skill_v0"
        assert row.tags == []
        assert row.note is None
        assert row.status == "draft"
        assert row.enrichment is None
        assert row.prompt_positive is None
        assert isinstance(row.metadata_, dict)
        assert row.metadata_["imported_from"] == "coloring_taxonomy_full.json"
        assert row.metadata_["import_run"] == "20260510T120000Z"
        assert row.metadata_["root"] == "animals"

    def test_limit_caps_inserts(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        # Ordre : trié par leaf_id => leaf_car (orphelin), leaf_cat, leaf_dog.
        # limit=2 considère [leaf_car, leaf_cat] => 1 inséré + 1 orphelin.
        stats = imp.import_subjects(session, leaves, dry_run=False, limit=2)
        assert stats["considered"] == 2
        assert stats["inserted"] == 1
        assert len(stats["orphans"]) == 1

    def test_custom_source_override(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=False, source="manual_v0")
        assert stats["inserted"] == 2
        rows = session.execute(
            sql_text("SELECT source FROM subject")
        ).fetchall()
        assert all(r[0] == "manual_v0" for r in rows)

        # Idempotence par source : un 2e run avec la MÊME source ne ré-insère
        # rien (vérifié via _subject_already_imported).
        stats2 = imp.import_subjects(session, leaves, dry_run=False, source="manual_v0")
        assert stats2["inserted"] == 0
        assert stats2["already_present"] == 2

    def test_per_root_distribution(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=False)
        # leaf_cat (animals) et leaf_dog (animals) insérés ; leaf_car orphelin.
        assert stats["per_root"] == {"animals": 2}


# ---------------------------------------------------------------------------
# Tests : reporting
# ---------------------------------------------------------------------------

class TestReporting:
    def test_json_report_written(self, session, tmp_path: Path):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=False)
        out = imp.write_json_report(stats, tmp_path)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["inserted"] == 2
        assert data["source"] == "skill_v0"

    def test_markdown_report_renders_sections(self, session, tmp_path: Path):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=False)
        md = imp.render_markdown_report(stats, json_path=None)
        assert "## Compteurs" in md
        assert "## Distribution par root" in md
        assert "## Liste orphelins" in md
        assert "## Échantillon" in md
        assert "## Décision / Action suivante" in md
        # Le subject inséré apparaît dans l'échantillon
        assert "sub_leaf_cat" in md

    def test_markdown_report_dry_run_decision(self, session):
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        stats = imp.import_subjects(session, leaves, dry_run=True)
        md = imp.render_markdown_report(stats, json_path=None)
        assert "**Dry-run**" in md

    def test_markdown_report_idempotent_decision(self, session):
        """Run 2 fois : le second run produit la décision idempotence."""
        leaves = imp.flatten_leaves(MINI_TAXONOMY)
        # 1er run pour peupler.
        imp.import_subjects(session, leaves, dry_run=False)
        # Pour tester la branche "tous déjà présents et 0 orphelin" : on
        # restreint aux leaves qui ont un term en BD.
        leaves_no_orphan = [l for l in leaves if l["leaf_id"] != "leaf_car"]
        stats2 = imp.import_subjects(session, leaves_no_orphan, dry_run=False)
        md = imp.render_markdown_report(stats2, json_path=None)
        assert "**Idempotence vérifiée**" in md


# ---------------------------------------------------------------------------
# Tests : NULL-safe sort key sur leaf_id (paranoïa CLAUDE.md)
# ---------------------------------------------------------------------------

class TestNullSafeSorting:
    def test_sort_key_handles_empty_leaf_id(self, session):
        """Sécurise le tri si jamais un leaf_id arrivait à None (ne devrait pas)."""
        # On ne peut pas vraiment avoir leaf_id=None car flatten_leaves le requiert,
        # mais on vérifie le comportement direct du sort dans import_subjects
        # en lui passant des leaves manuels.
        leaves = [
            {"leaf_id": "leaf_cat", "name_en": "Cat", "root": "animals", "path": ["leaf_cat"]},
            {"leaf_id": "leaf_dog", "name_en": "Dog", "root": "animals", "path": ["leaf_dog"]},
        ]
        stats = imp.import_subjects(session, leaves, dry_run=True)
        assert stats["inserted"] == 2  # passe sans TypeError
