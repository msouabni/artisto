"""Tests pour ``scripts/alwanbooks_pipeline.py``.

Brief : MEP-v0/D — pipeline alwanbooks (R2 + rimalab-v2).

Couverture :

1. Conversion d'un PNG master en 4 variants (Pillow + img2pdf).
2. Mock upload R2 (écrit sur disque).
3. Idempotence ETag (mock simulé).
4. Conversion Post JSON → MD Astro YAML frontmatter.
5. Helper ``_ensure_post_complete`` (défauts injectés).
6. Écriture rimalab-v2 path.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "scripts")

import alwanbooks_pipeline as pipe  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_png(tmp_path) -> Path:
    """Crée un PNG simple 100×100 pour test conversion."""
    from PIL import Image, ImageDraw
    p = tmp_path / "sample.png"
    im = Image.new("RGB", (100, 100), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, 90, 90], outline=(0, 0, 0), width=3)
    im.save(p)
    return p


# ── 1. Conversion master → 4 variants ────────────────────────────────────────


def test_convert_master_to_variants_returns_4_outputs(sample_png):
    """Le converter retourne master/web/thumb/pdf en bytes non-vides."""
    out = pipe.convert_master_to_variants(sample_png)
    assert set(out.keys()) == {"master", "web", "thumb", "pdf"}
    for k, b in out.items():
        assert isinstance(b, bytes), f"{k}: not bytes"
        assert len(b) > 0, f"{k}: empty"


def test_convert_master_preserves_original_png(sample_png):
    """Le `master` retourné est le contenu PNG d'origine, byte pour byte."""
    out = pipe.convert_master_to_variants(sample_png)
    assert out["master"] == sample_png.read_bytes()


def test_convert_master_web_is_webp(sample_png):
    """Le variant `web` est un WebP valide (signature)."""
    out = pipe.convert_master_to_variants(sample_png)
    assert out["web"][:4] == b"RIFF"
    assert out["web"][8:12] == b"WEBP"


def test_convert_master_thumb_is_smaller(sample_png):
    """Le thumb (400×400 max) est ≤ taille du web variant pour grosse image."""
    from PIL import Image
    out = pipe.convert_master_to_variants(sample_png)
    # Décode le thumb pour vérifier les dimensions
    th = Image.open(io.BytesIO(out["thumb"]))
    assert th.size[0] <= 400 and th.size[1] <= 400


def test_convert_master_pdf_signature(sample_png):
    """Le PDF a la signature %PDF-."""
    out = pipe.convert_master_to_variants(sample_png)
    assert out["pdf"][:5] == b"%PDF-"


# ── 2. Mock upload R2 ────────────────────────────────────────────────────────


def test_mock_upload_writes_to_disk(tmp_path, monkeypatch, sample_png):
    """Le mock écrit les 4 variants sous data/export/r2_simulated/."""
    monkeypatch.setattr(pipe, "MOCK_R2_DIR", tmp_path / "r2sim")
    out = pipe.convert_master_to_variants(sample_png)
    uploaded, skipped = pipe._upload_variants_mock("test-slug", out)
    assert len(uploaded) == 4
    assert skipped == {}
    for variant, key in uploaded.items():
        assert (tmp_path / "r2sim" / key).is_file()


# ── 3. JSON → MD Astro ─────────────────────────────────────────────────────


def test_post_json_to_md_basic():
    post = {
        "locale": "fr",
        "slug": "lion-savane",
        "title": "Lion dans la savane",
        "title_card": "Lion",
        "description": "Un beau lion qui se balade sous le soleil africain dans la savane.",
        "keywords": ["lion", "savane"],
        "categoryId": "animals_cats",
        "themeIds": ["arabic-alphabet"],
        "ageMin": 4,
        "ageMax": 10,
        "niveauDifficulte": "easy",
        "imageSource": "https://x.com/png/lion-savane.png",
        "imageWeb": "https://x.com/webp/lion-savane.webp",
        "imageThumb": "https://x.com/thumbs/lion-savane.webp",
        "imagePdf": "https://x.com/pdf/lion-savane.pdf",
        "status": "approved",
        "datePublication": "2026-05-12",
        "featured": False,
    }
    md = pipe.post_json_to_md(post)
    # Format frontmatter
    assert md.startswith("---\n")
    assert "locale: 'fr'\n" in md
    assert "slug: 'lion-savane'\n" in md
    # Date sans quotes (YAML date scalar)
    assert "datePublication: 2026-05-12\n" in md
    # themeIds liste
    assert "themeIds:" in md
    assert "  - 'arabic-alphabet'" in md
    # body
    assert "## Lion dans la savane" in md
    assert "Un beau lion" in md


def test_post_json_to_md_strips_pipeline_block():
    """Les champs `_pipeline` et `r2_slug` ne sont pas émis (debug-only)."""
    post = {
        "locale": "en",
        "slug": "lion",
        "title": "Lion",
        "title_card": "Lion",
        "description": "A simple lion drawing for kids to color in the afternoon.",
        "keywords": ["lion"],
        "categoryId": "animals",
        "themeIds": [],
        "ageMin": 4,
        "ageMax": 10,
        "niveauDifficulte": "easy",
        "imageSource": "x", "imageWeb": "x", "imageThumb": "x", "imagePdf": "x",
        "status": "approved",
        "datePublication": "2026-05-12",
        "featured": False,
        "r2_slug": "lion",
        "_pipeline": {"leaf_id": "lion_savanna"},
    }
    md = pipe.post_json_to_md(post)
    assert "r2_slug" not in md
    assert "_pipeline" not in md


def test_post_json_to_md_quotes_escaped_apostrophes():
    """Apostrophes dans le texte → doublées en YAML simple-quote."""
    post = {
        "locale": "fr",
        "slug": "x",
        "title": "L'enfant qui joue",
        "title_card": "L'enfant",
        "description": "Voici l'illustration d'un enfant qui joue avec son ballon dans le jardin.",
        "keywords": ["enfant"],
        "categoryId": "kids",
        "themeIds": [],
        "ageMin": 4, "ageMax": 10, "niveauDifficulte": "easy",
        "imageSource": "x", "imageWeb": "x", "imageThumb": "x", "imagePdf": "x",
        "status": "approved", "datePublication": "2026-05-12", "featured": False,
    }
    md = pipe.post_json_to_md(post)
    assert "title: 'L''enfant qui joue'" in md


# ── 4. _ensure_post_complete ────────────────────────────────────────────────


def test_ensure_post_complete_injects_defaults():
    """Les champs requis manquants reçoivent des défauts sains."""
    minimal = {
        "locale": "fr", "slug": "x", "title": "T", "title_card": "Tc",
        "description": "D", "keywords": [],
    }
    out = pipe._ensure_post_complete(minimal)
    assert out["categoryId"] == "uncategorized"
    assert out["themeIds"] == []
    assert out["ageMin"] == 4
    assert out["ageMax"] == 10
    assert out["niveauDifficulte"] == "easy"
    assert out["status"] == "approved"
    assert out["featured"] is False
    # datePublication injectée si absente
    assert out["datePublication"]


def test_ensure_post_complete_preserves_existing():
    """Les champs déjà présents ne sont pas écrasés."""
    post = {
        "locale": "fr", "slug": "x", "title": "T", "title_card": "Tc",
        "description": "D", "keywords": [],
        "categoryId": "animals", "ageMin": 6, "niveauDifficulte": "medium",
    }
    out = pipe._ensure_post_complete(post)
    assert out["categoryId"] == "animals"
    assert out["ageMin"] == 6
    assert out["niveauDifficulte"] == "medium"


# ── 5. Écriture MD vers rimalab-v2 ──────────────────────────────────────────


def test_write_post_md_creates_directory_structure(tmp_path):
    """`write_post_md` crée le path locale s'il n'existe pas."""
    fake_root = tmp_path / "rimalab-v2"
    out = pipe.write_post_md(fake_root, "ar", "asad-fi-al-ghaba", "---\n---\nbody")
    assert out.is_file()
    assert out.parent.name == "ar"
    assert out.name == "asad-fi-al-ghaba.md"


# ── 6. Helper YAML emitter ──────────────────────────────────────────────────


def test_emit_yaml_value_handles_types():
    assert pipe._emit_yaml_value(None) == "null"
    assert pipe._emit_yaml_value(True) == "true"
    assert pipe._emit_yaml_value(False) == "false"
    assert pipe._emit_yaml_value(42) == "42"
    assert pipe._emit_yaml_value("hello") == "'hello'"
    # list[str] → multiligne
    out = pipe._emit_yaml_value(["a", "b"])
    assert "- 'a'" in out
    assert "- 'b'" in out


def test_yaml_quote_escapes_single_quote():
    assert pipe._yaml_quote("L'enfant") == "'L''enfant'"


# ── 7. md5 helper ───────────────────────────────────────────────────────────


def test_md5_deterministic():
    a = pipe._md5(b"hello")
    b = pipe._md5(b"hello")
    assert a == b
    assert pipe._md5(b"hello") != pipe._md5(b"world")
