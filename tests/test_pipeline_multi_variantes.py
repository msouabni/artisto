"""Tests du pipeline multi-variantes (C2.3).

Couvre les helpers ``_build_variants_dict``, ``_pick_legacy_image``,
``_copy_variant_artefacts`` ainsi que l'integration dans le frontmatter
genere par ``post_json_to_md``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


LEAF_ID = "garden_snail"


def _touch(p: Path, content: bytes = b"x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


# ── _build_variants_dict ────────────────────────────────────────────────────


def test_build_variants_dict_avec_3_fichiers(tmp_path):
    """3 artefacts (png + svg + _coloriage.svg) → dict avec 3 clés."""
    from alwanbooks_pipeline import _build_variants_dict

    base = tmp_path
    _touch(base / f"{LEAF_ID}__pastel_chromakey.png")
    _touch(base / f"{LEAF_ID}__pastel_chromakey.svg")
    _touch(base / f"{LEAF_ID}__pastel_chromakey_coloriage.svg")

    out = _build_variants_dict(LEAF_ID, base_dir=base)
    assert "pastel_chromakey" in out
    pc = out["pastel_chromakey"]
    assert set(pc.keys()) == {"raw_png", "vector_svg", "coloring_svg"}
    assert pc["raw_png"] == "/assets/coloriages/garden_snail__pastel_chromakey.png"
    assert pc["vector_svg"] == "/assets/coloriages/garden_snail__pastel_chromakey.svg"
    assert pc["coloring_svg"] == (
        "/assets/coloriages/garden_snail__pastel_chromakey_coloriage.svg"
    )


def test_build_variants_dict_partiel(tmp_path):
    """Seul le PNG existe → dict avec raw_png uniquement (pas de svg)."""
    from alwanbooks_pipeline import _build_variants_dict

    base = tmp_path
    _touch(base / f"{LEAF_ID}__pastel_chromakey.png")

    out = _build_variants_dict(LEAF_ID, base_dir=base)
    assert out == {
        "pastel_chromakey": {
            "raw_png": "/assets/coloriages/garden_snail__pastel_chromakey.png",
        },
    }


def test_build_variants_dict_vide(tmp_path):
    """Aucun fichier → dict vide."""
    from alwanbooks_pipeline import _build_variants_dict

    out = _build_variants_dict(LEAF_ID, base_dir=tmp_path)
    assert out == {}


def test_build_variants_dict_multi_variantes(tmp_path):
    """Plusieurs variantes detectees correctement."""
    from alwanbooks_pipeline import _build_variants_dict

    base = tmp_path
    _touch(base / f"{LEAF_ID}__lineart.png")
    _touch(base / f"{LEAF_ID}__lineart.svg")
    _touch(base / f"{LEAF_ID}__pastel_chromakey.png")
    _touch(base / f"{LEAF_ID}__pastel_chromakey.svg")
    _touch(base / f"{LEAF_ID}__pastel_chromakey_coloriage.svg")

    out = _build_variants_dict(LEAF_ID, base_dir=base)
    assert set(out.keys()) == {"lineart", "pastel_chromakey"}
    assert "coloring_svg" not in out["lineart"]
    assert "coloring_svg" in out["pastel_chromakey"]


def test_build_variants_dict_public_url_prefix_custom(tmp_path):
    """Le prefixe URL est respecte."""
    from alwanbooks_pipeline import _build_variants_dict

    base = tmp_path
    _touch(base / f"{LEAF_ID}__lineart.png")

    out = _build_variants_dict(
        LEAF_ID, base_dir=base, public_url_prefix="/static/c"
    )
    assert out["lineart"]["raw_png"] == "/static/c/garden_snail__lineart.png"


# ── _pick_legacy_image ──────────────────────────────────────────────────────


def test_pick_legacy_image_lineart_present():
    """variants_dict avec lineart → choisit lineart."""
    from alwanbooks_pipeline import _pick_legacy_image

    variants = {
        "lineart": {"raw_png": "/x/lineart.png"},
        "pastel_chromakey": {"raw_png": "/x/pastel.png"},
    }
    assert _pick_legacy_image(variants) == "/x/lineart.png"


def test_pick_legacy_image_fallback_default_active(tmp_path, monkeypatch):
    """Pas de lineart → premier du default_active."""
    from alwanbooks_pipeline import _pick_legacy_image

    variants = {
        "pastel_chromakey": {"raw_png": "/x/pastel.png"},
        "flat_cartoon_chromakey": {"raw_png": "/x/flat.png"},
    }
    result = _pick_legacy_image(variants)
    # default_active actuel commence par "lineart" puis "pastel_chromakey"
    # → pastel_chromakey doit etre choisi (premier disponible dans
    # default_active present dans variants).
    assert result == "/x/pastel.png"


def test_pick_legacy_image_fallback_alphabetique(monkeypatch):
    """Pas de lineart, registre cassé → tri alphabetique fallback."""
    from alwanbooks_pipeline import _pick_legacy_image
    import alwanbooks_pipeline as mod

    variants = {
        "zzz_variant": {"raw_png": "/x/zzz.png"},
        "aaa_variant": {"raw_png": "/x/aaa.png"},
    }
    # Forcer le fallback en cassant le registre via monkeypatch :
    # on ne touche pas le registre, mais ces noms ne sont pas dans
    # default_active → on tombe naturellement sur le tri alphabetique.
    result = _pick_legacy_image(variants)
    assert result == "/x/aaa.png"


def test_pick_legacy_image_dict_vide():
    """dict vide → None."""
    from alwanbooks_pipeline import _pick_legacy_image

    assert _pick_legacy_image({}) is None


def test_pick_legacy_image_sans_raw_png():
    """Variante sans raw_png ignoree."""
    from alwanbooks_pipeline import _pick_legacy_image

    variants = {
        "lineart": {"vector_svg": "/x/lineart.svg"},  # pas de raw_png
    }
    assert _pick_legacy_image(variants) is None


# ── Integration frontmatter ────────────────────────────────────────────────


def test_frontmatter_contient_variants_dict():
    """post_json_to_md emet le bloc variants en YAML imbrique."""
    from alwanbooks_pipeline import post_json_to_md

    post = {
        "locale": "en",
        "slug": "garden-snail",
        "title": "Garden Snail Coloring Page",
        "description": "A coloring page with a snail.",
        "keywords": ["snail"],
        "categoryId": "animals_pets",
        "themeIds": [],
        "status": "approved",
        "datePublication": "2026-06-06",
        "dateModification": "2026-06-06",
        "featured": False,
        "variants": {
            "pastel_chromakey": {
                "raw_png": "/assets/coloriages/garden_snail__pastel_chromakey.png",
                "vector_svg": "/assets/coloriages/garden_snail__pastel_chromakey.svg",
                "coloring_svg": (
                    "/assets/coloriages/garden_snail__pastel_chromakey_coloriage.svg"
                ),
            },
        },
        "image": "/assets/coloriages/garden_snail__pastel_chromakey.png",
    }
    md = post_json_to_md(post)
    assert "variants:" in md
    assert "pastel_chromakey:" in md
    assert "raw_png:" in md
    assert "vector_svg:" in md
    assert "coloring_svg:" in md
    assert "image:" in md
    # Le YAML imbrique des variantes doit etre indente (au moins 2 niveaux).
    assert "  pastel_chromakey:" in md or "    raw_png:" in md


def test_image_legacy_pas_ecrasee_si_deja_presente(tmp_path):
    """Si post.image deja present, _pick_legacy_image ne doit pas l'ecraser.

    Ce test reproduit la logique d'integration dans run_pipeline.
    """
    from alwanbooks_pipeline import _build_variants_dict, _pick_legacy_image

    base = tmp_path
    _touch(base / f"{LEAF_ID}__lineart.png")

    post = {"image": "/explicitly/set.png"}
    variants_dict = _build_variants_dict(LEAF_ID, base_dir=base)
    assert variants_dict  # On a bien detecte la variante.

    # Reproduit la logique exacte du run_pipeline :
    if variants_dict:
        post["variants"] = variants_dict
        legacy_image = _pick_legacy_image(variants_dict)
        if legacy_image and not post.get("image"):
            post["image"] = legacy_image

    # `image` doit avoir conserve sa valeur initiale.
    assert post["image"] == "/explicitly/set.png"


def test_image_legacy_pose_si_absente(tmp_path):
    """Si post.image absent, _pick_legacy_image le pose."""
    from alwanbooks_pipeline import _build_variants_dict, _pick_legacy_image

    base = tmp_path
    _touch(base / f"{LEAF_ID}__lineart.png")

    post: dict = {}
    variants_dict = _build_variants_dict(LEAF_ID, base_dir=base)

    if variants_dict:
        post["variants"] = variants_dict
        legacy_image = _pick_legacy_image(variants_dict)
        if legacy_image and not post.get("image"):
            post["image"] = legacy_image

    assert post["image"] == "/assets/coloriages/garden_snail__lineart.png"


# ── _copy_variant_artefacts ────────────────────────────────────────────────


def test_copy_variant_artefacts_copie_les_3_artefacts(tmp_path):
    """3 artefacts source → 3 copies dans public/assets/coloriages."""
    from alwanbooks_pipeline import _copy_variant_artefacts

    src = tmp_path / "generated"
    site = tmp_path / "site"
    _touch(src / f"{LEAF_ID}__pastel_chromakey.png", b"PNG")
    _touch(src / f"{LEAF_ID}__pastel_chromakey.svg", b"<svg/>")
    _touch(src / f"{LEAF_ID}__pastel_chromakey_coloriage.svg", b"<svg coloriage/>")

    result = _copy_variant_artefacts(LEAF_ID, site, base_dir=src)
    assert len(result["copied"]) == 3
    assert result["skipped"] == []

    dest = site / "public" / "assets" / "coloriages"
    assert (dest / f"{LEAF_ID}__pastel_chromakey.png").read_bytes() == b"PNG"
    assert (dest / f"{LEAF_ID}__pastel_chromakey.svg").read_bytes() == b"<svg/>"


def test_copy_variant_artefacts_idempotent(tmp_path):
    """2eme copie avec memes bytes → skipped."""
    from alwanbooks_pipeline import _copy_variant_artefacts

    src = tmp_path / "generated"
    site = tmp_path / "site"
    _touch(src / f"{LEAF_ID}__lineart.png", b"PNG-LINEART")

    _copy_variant_artefacts(LEAF_ID, site, base_dir=src)
    result = _copy_variant_artefacts(LEAF_ID, site, base_dir=src)
    # 2eme passe : tout skip (bytes identiques).
    assert result["copied"] == []
    assert f"{LEAF_ID}__lineart.png" in result["skipped"]


def test_copy_variant_artefacts_aucune_variante(tmp_path):
    """Aucune variante generee → result vide, pas d'erreur."""
    from alwanbooks_pipeline import _copy_variant_artefacts

    result = _copy_variant_artefacts(
        LEAF_ID, tmp_path / "site", base_dir=tmp_path / "empty",
    )
    assert result == {"copied": [], "skipped": []}
