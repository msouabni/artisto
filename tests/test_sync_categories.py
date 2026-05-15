"""Tests pour le flag ``--sync-categories`` de ``alwanbooks_pipeline.py``.

Vérifie :

- 2 catégories minimales → 2 MDs écrits avec le bon contenu
- Idempotence byte-identique : re-run sur contenu inchangé → 0 écriture
- ``scope_note`` n'est **jamais** propagé dans le .md généré
- Format YAML déterministe (ordre des champs, locales, indentation)

Brief : ``docs/architect/briefs/2026-05-15_brief-categories-registry-cross-repo.md``
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def minimal_registry() -> dict:
    """Registry minimal de 2 catégories — racine + enfant."""
    return {
        "version": 1,
        "categories": [
            {
                "id": "test_root",
                "parent_id": None,
                "weight": 1,
                "slug_i18n": {"ar": "judhur", "fr": "racine", "en": "root"},
                "name_i18n": {"ar": "جذور", "fr": "Racine", "en": "Root"},
                "description_i18n": {
                    "ar": "وصف عربي",
                    "fr": "Description française",
                    "en": "English description",
                },
                "keywords_i18n": {
                    "ar": ["كلمة1", "كلمة2", "كلمة3"],
                    "fr": ["mot1", "mot2", "mot3"],
                    "en": ["kw1", "kw2", "kw3"],
                },
                "body": "Racine de test.",
                "scope_note": "INTERNE — ne doit jamais apparaître dans le .md",
            },
            {
                "id": "test_child",
                "parent_id": "test_root",
                "weight": 10,
                "slug_i18n": {"ar": "ibn", "fr": "enfant", "en": "child"},
                "name_i18n": {"ar": "ابن", "fr": "Enfant", "en": "Child"},
                "description_i18n": {
                    "ar": "وصف الطفل",
                    "fr": "Description enfant",
                    "en": "Child description",
                },
                "keywords_i18n": {
                    "ar": ["طفل", "ابن", "صغير"],
                    "fr": ["enfant", "petit", "jeune"],
                    "en": ["child", "kid", "young"],
                },
                "body": "Sous-catégorie test.",
                "scope_note": "INTERNE — confidentiel",
            },
        ],
    }


# ── Tests ────────────────────────────────────────────────────────────────────


def test_sync_categories_writes_md_files(tmp_path, minimal_registry):
    """2 catégories → 2 fichiers MD écrits."""
    from alwanbooks_pipeline import sync_categories

    summary = sync_categories(tmp_path, registry=minimal_registry)

    assert summary.total == 2
    assert summary.wrote == 2
    assert summary.skipped == 0

    categories_dir = tmp_path / "src" / "content" / "categories"
    assert categories_dir.is_dir()
    assert (categories_dir / "test_root.md").is_file()
    assert (categories_dir / "test_child.md").is_file()


def test_sync_categories_md_content_structure(tmp_path, minimal_registry):
    """Le contenu MD a la bonne structure YAML frontmatter."""
    from alwanbooks_pipeline import sync_categories

    sync_categories(tmp_path, registry=minimal_registry)
    md = (tmp_path / "src" / "content" / "categories" / "test_root.md").read_text(
        encoding="utf-8"
    )

    # Frontmatter delimiters
    assert md.startswith("---\n")
    assert "\n---\n" in md
    # Champs principaux présents
    assert "id: 'test_root'" in md
    assert "weight: 1" in md
    assert "parent_id: null" in md
    # i18n présents
    assert "  ar: 'judhur'" in md
    assert "  fr: 'racine'" in md
    assert "  en: 'root'" in md
    # Caractères AR préservés
    assert "جذور" in md
    # Body après frontmatter
    assert "Racine de test." in md


def test_sync_categories_scope_note_never_in_md(tmp_path, minimal_registry):
    """``scope_note`` n'apparaît jamais dans le contenu MD généré."""
    from alwanbooks_pipeline import sync_categories

    sync_categories(tmp_path, registry=minimal_registry)
    for fname in ("test_root.md", "test_child.md"):
        md = (tmp_path / "src" / "content" / "categories" / fname).read_text(
            encoding="utf-8"
        )
        assert "scope_note" not in md, (
            f"{fname}: scope_note leaked into MD content"
        )
        assert "INTERNE" not in md, (
            f"{fname}: scope_note value leaked into MD content"
        )


def test_sync_categories_idempotent_byte_identical(tmp_path, minimal_registry):
    """Re-run sur contenu inchangé → 0 écriture (compare bytes, pas mtime)."""
    from alwanbooks_pipeline import sync_categories

    # 1er run : 2 wrote, 0 skipped
    s1 = sync_categories(tmp_path, registry=minimal_registry)
    assert s1.wrote == 2
    assert s1.skipped == 0

    # Capture bytes + mtime avant 2e run
    root_md = tmp_path / "src" / "content" / "categories" / "test_root.md"
    child_md = tmp_path / "src" / "content" / "categories" / "test_child.md"
    bytes_before_root = root_md.read_bytes()
    bytes_before_child = child_md.read_bytes()
    mtime_before_root = root_md.stat().st_mtime_ns

    # 2e run : doit être 100% skipped (bytes identiques)
    s2 = sync_categories(tmp_path, registry=minimal_registry)
    assert s2.wrote == 0, (
        f"expected 0 writes on idempotent re-run, got {s2.wrote}"
    )
    assert s2.skipped == 2

    # Vérif byte-identique
    assert root_md.read_bytes() == bytes_before_root
    assert child_md.read_bytes() == bytes_before_child
    # mtime inchangé puisqu'on n'a pas réécrit
    assert root_md.stat().st_mtime_ns == mtime_before_root


def test_sync_categories_detects_change_and_rewrites(tmp_path, minimal_registry):
    """Si le registry change, le MD correspondant est réécrit."""
    from alwanbooks_pipeline import sync_categories

    sync_categories(tmp_path, registry=minimal_registry)

    # Modifier 1 catégorie : changer le body
    modified = {
        "version": 1,
        "categories": [
            dict(minimal_registry["categories"][0], body="Nouveau body modifié."),
            minimal_registry["categories"][1],
        ],
    }
    s2 = sync_categories(tmp_path, registry=modified)
    assert s2.wrote == 1, (
        f"expected 1 write on changed registry, got {s2.wrote}"
    )
    assert s2.skipped == 1

    root_md = (tmp_path / "src" / "content" / "categories" / "test_root.md").read_text(
        encoding="utf-8"
    )
    assert "Nouveau body modifié." in root_md
    assert "Racine de test." not in root_md


def test_sync_categories_no_utf8_bom(tmp_path, minimal_registry):
    """Le MD écrit ne contient pas de BOM UTF-8."""
    from alwanbooks_pipeline import sync_categories

    sync_categories(tmp_path, registry=minimal_registry)
    raw = (tmp_path / "src" / "content" / "categories" / "test_root.md").read_bytes()
    # BOM UTF-8 = 0xEF 0xBB 0xBF
    assert raw[:3] != b"\xef\xbb\xbf", (
        f"MD file unexpectedly starts with UTF-8 BOM: {raw[:3]!r}"
    )


def test_sync_categories_yaml_field_order(tmp_path, minimal_registry):
    """Les champs YAML sont émis dans l'ordre déterministe."""
    from alwanbooks_pipeline import sync_categories

    sync_categories(tmp_path, registry=minimal_registry)
    md = (tmp_path / "src" / "content" / "categories" / "test_root.md").read_text(
        encoding="utf-8"
    )

    # Détecter les positions des champs racine
    idx_id = md.find("\nid:")
    idx_slug = md.find("\nslug_i18n:")
    idx_name = md.find("\nname_i18n:")
    idx_desc = md.find("\ndescription_i18n:")
    idx_kw = md.find("\nkeywords_i18n:")
    idx_parent = md.find("\nparent_id:")
    idx_weight = md.find("\nweight:")

    # Note : id est le tout 1er champ après ---, donc idx_id == -1 si on cherche '\nid:'
    # (car ce sera ---\nid:). Workaround : on regarde la position dans le frontmatter.
    pos_id = md.index("id: 'test_root'")
    pos_slug = md.index("slug_i18n:")
    pos_name = md.index("name_i18n:")
    pos_desc = md.index("description_i18n:")
    pos_kw = md.index("keywords_i18n:")
    pos_parent = md.index("parent_id:")
    pos_weight = md.index("weight:")

    # Ordre strict : id < slug < name < description < keywords < parent_id < weight
    assert pos_id < pos_slug < pos_name < pos_desc < pos_kw < pos_parent < pos_weight


def test_sync_categories_lf_line_endings(tmp_path, minimal_registry):
    """Les MDs écrits utilisent LF universel (pas de CRLF)."""
    from alwanbooks_pipeline import sync_categories

    sync_categories(tmp_path, registry=minimal_registry)
    raw = (tmp_path / "src" / "content" / "categories" / "test_root.md").read_bytes()
    assert b"\r\n" not in raw, (
        "MD file unexpectedly contains CRLF line endings"
    )
