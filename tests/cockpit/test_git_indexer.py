"""Tests de l'indexeur git sur Postgres éphémère.

Couvre : scan des mocks → git_index correct, content_hash stable & idempotent
(2 runs → mêmes hash, aucun INSERT supplémentaire), parsing de publishDate.
Aucun SQLite (cf. tests/cockpit/conftest.py).
"""
from __future__ import annotations

from pathlib import Path

from services.git_indexer import DEFAULT_REPO, reindex, scan_docs, split_frontmatter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOCK_ROOT = PROJECT_ROOT / "data" / "mock-content"


def _rows(conn):
    return conn.execute(
        "SELECT repo, locale, slug, exists, publish_date, content_hash, "
        "frontmatter_digest FROM git_index ORDER BY slug"
    ).fetchall()


def test_split_frontmatter_basic():
    fm, body = split_frontmatter("---\nslug: 'x'\npublishDate: 2026-06-29\n---\n\nHello\n")
    assert fm["slug"] == "x"
    assert "Hello" in body


def test_split_frontmatter_none_when_absent():
    fm, body = split_frontmatter("No frontmatter here")
    assert fm == {}
    assert body == "No frontmatter here"


def test_scan_docs_finds_ten_marine_posts():
    docs = scan_docs(MOCK_ROOT)
    assert len(docs) == 10, f"attendu 10 posts marins, trouvé {len(docs)}"
    slugs = {d.slug for d in docs}
    assert "baleine" in slugs
    assert all(d.locale == "fr" for d in docs)
    # publishDate parsé (au moins certains en date).
    assert any(d.publish_date is not None for d in docs)


def test_reindex_populates_git_index(conn):
    report = reindex(conn, repo=DEFAULT_REPO, root=MOCK_ROOT)
    conn.session.commit()

    assert report.scanned == 10
    assert report.inserted == 10
    assert report.updated == 0
    assert report.errors == []

    rows = _rows(conn)
    assert len(rows) == 10
    for r in rows:
        assert r[0] == DEFAULT_REPO          # repo
        assert r[2]                          # slug non vide
        assert bool(r[3]) is True            # exists
        assert r[5]                          # content_hash non vide
        assert r[6]                          # frontmatter_digest non vide


def test_reindex_publish_date_parsed(conn):
    reindex(conn, repo=DEFAULT_REPO, root=MOCK_ROOT)
    conn.session.commit()
    row = conn.execute(
        "SELECT publish_date FROM git_index WHERE slug = ?", ["baleine"]
    ).fetchone()
    # baleine (index 0) → futur → date non nulle, type Date natif.
    assert row[0] is not None
    assert hasattr(row[0], "isoformat")


def test_reindex_idempotent_same_hash_no_new_rows(conn):
    r1 = reindex(conn, repo=DEFAULT_REPO, root=MOCK_ROOT)
    conn.session.commit()
    hashes_1 = {(r[2], r[5]) for r in _rows(conn)}

    r2 = reindex(conn, repo=DEFAULT_REPO, root=MOCK_ROOT)
    conn.session.commit()
    hashes_2 = {(r[2], r[5]) for r in _rows(conn)}

    # 2e run : rien d'inséré ni de modifié (tout 'unchanged'), mêmes hash.
    assert r1.inserted == 10
    assert r2.inserted == 0
    assert r2.updated == 0
    assert r2.unchanged == 10
    assert hashes_1 == hashes_2
    assert len(_rows(conn)) == 10


def test_reindex_marks_absent_when_file_gone(conn):
    reindex(conn, repo=DEFAULT_REPO, root=MOCK_ROOT)
    conn.session.commit()

    # Injecte une ligne orpheline (slug qui n'existe pas sur le FS).
    conn.execute(
        "INSERT INTO git_index (id, repo, locale, slug, exists, content_hash, "
        "last_indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["gidx_orphan", DEFAULT_REPO, "fr", "sujet-fantome", True, "deadbeef", "now"],
    )
    conn.session.commit()

    report = reindex(conn, repo=DEFAULT_REPO, root=MOCK_ROOT)
    conn.session.commit()

    assert report.marked_absent == 1
    row = conn.execute(
        "SELECT exists FROM git_index WHERE slug = ?", ["sujet-fantome"]
    ).fetchone()
    assert bool(row[0]) is False
