"""Tests des helpers de storage des variantes de coloriage (C2.1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from services.coloring_storage import (  # noqa: E402
    DEFAULT_GENERATED_DIR,
    KIND_COLORING_SVG,
    KIND_RAW_PNG,
    KIND_VECTOR_SVG,
    StoragePaths,
    get_storage_paths,
    has_variant,
    list_existing_variants,
    validate_leaf_id,
    validate_variant_name,
)


# ---------------------------------------------------------------------------
# get_storage_paths
# ---------------------------------------------------------------------------


def test_get_storage_paths_basic(tmp_path):
    paths = get_storage_paths(
        "lion_in_savanna", "pastel_chromakey", base_dir=tmp_path
    )
    assert isinstance(paths, StoragePaths)
    assert paths.raw_png == tmp_path / "lion_in_savanna__pastel_chromakey.png"
    assert paths.vector_svg == tmp_path / "lion_in_savanna__pastel_chromakey.svg"
    assert (
        paths.coloring_svg
        == tmp_path / "lion_in_savanna__pastel_chromakey_coloriage.svg"
    )


def test_get_storage_paths_default_base_dir():
    """base_dir=None doit utiliser DEFAULT_GENERATED_DIR."""
    paths = get_storage_paths("hammer", "lineart")
    assert paths.raw_png == DEFAULT_GENERATED_DIR / "hammer__lineart.png"
    assert paths.vector_svg == DEFAULT_GENERATED_DIR / "hammer__lineart.svg"
    assert (
        paths.coloring_svg
        == DEFAULT_GENERATED_DIR / "hammer__lineart_coloriage.svg"
    )


def test_get_storage_paths_avec_base_dir_override(tmp_path):
    custom = tmp_path / "custom" / "out"
    paths = get_storage_paths("flower", "lineart", base_dir=custom)
    assert paths.raw_png.parent == custom
    assert paths.raw_png.name == "flower__lineart.png"


# ---------------------------------------------------------------------------
# validate_leaf_id (via get_storage_paths)
# ---------------------------------------------------------------------------


def test_get_storage_paths_invalid_leaf_id_traversal(tmp_path):
    with pytest.raises(ValueError, match="leaf_id"):
        get_storage_paths("../etc/passwd", "lineart", base_dir=tmp_path)


def test_get_storage_paths_invalid_leaf_id_with_slash(tmp_path):
    with pytest.raises(ValueError, match="leaf_id"):
        get_storage_paths("foo/bar", "lineart", base_dir=tmp_path)


def test_get_storage_paths_invalid_leaf_id_chars(tmp_path):
    with pytest.raises(ValueError, match="leaf_id"):
        get_storage_paths("lion in savanna", "lineart", base_dir=tmp_path)


def test_get_storage_paths_invalid_leaf_id_uppercase(tmp_path):
    with pytest.raises(ValueError, match="leaf_id"):
        get_storage_paths("Lion_In_Savanna", "lineart", base_dir=tmp_path)


def test_get_storage_paths_invalid_leaf_id_empty(tmp_path):
    with pytest.raises(ValueError, match="leaf_id"):
        get_storage_paths("", "lineart", base_dir=tmp_path)


def test_get_storage_paths_invalid_leaf_id_starts_with_digit(tmp_path):
    with pytest.raises(ValueError, match="leaf_id"):
        get_storage_paths("3_legs", "lineart", base_dir=tmp_path)


def test_validate_leaf_id_accepts_real_taxonomy_samples():
    """Echantillon de leaf_id reels de la taxonomie prod (1376 feuilles)."""
    for leaf in [
        "labrador_retriever",
        "lion_in_savanna",
        "hammer",
        "polar_bear_on_ice",
        "carpet_cleaner",
        "bengal_tiger",
        "sheep_with_lamb",
        "hen_with_chicks",
    ]:
        validate_leaf_id(leaf)  # ne doit pas lever


# ---------------------------------------------------------------------------
# validate_variant_name
# ---------------------------------------------------------------------------


def test_get_storage_paths_invalid_variant(tmp_path):
    with pytest.raises(ValueError, match="Variante inconnue"):
        get_storage_paths("hammer", "bogus_variant", base_dir=tmp_path)


def test_validate_variant_name_empty():
    with pytest.raises(ValueError, match="variant_name"):
        validate_variant_name("")


def test_validate_variant_name_known():
    # ``pastel_chromakey`` existe dans data/pipeline_variants.json
    validate_variant_name("pastel_chromakey")
    validate_variant_name("lineart")


# ---------------------------------------------------------------------------
# StoragePaths.kind_path
# ---------------------------------------------------------------------------


def test_kind_path_all_kinds(tmp_path):
    paths = get_storage_paths("hammer", "lineart", base_dir=tmp_path)
    assert paths.kind_path(KIND_RAW_PNG) == paths.raw_png
    assert paths.kind_path(KIND_VECTOR_SVG) == paths.vector_svg
    assert paths.kind_path(KIND_COLORING_SVG) == paths.coloring_svg


def test_kind_path_invalid(tmp_path):
    paths = get_storage_paths("hammer", "lineart", base_dir=tmp_path)
    with pytest.raises(ValueError, match="Unknown kind"):
        paths.kind_path("bogus")


# ---------------------------------------------------------------------------
# list_existing_variants
# ---------------------------------------------------------------------------


def test_list_existing_variants_empty(tmp_path):
    assert list_existing_variants("lion_in_savanna", base_dir=tmp_path) == []


def test_list_existing_variants_dossier_inexistant(tmp_path):
    missing = tmp_path / "does_not_exist"
    assert list_existing_variants("lion_in_savanna", base_dir=missing) == []


def test_list_existing_variants_avec_fichiers(tmp_path):
    # Cree 2 variantes pour lion + 1 variante pour un autre leaf (ignore)
    (tmp_path / "lion_in_savanna__pastel_chromakey.png").write_bytes(b"")
    (tmp_path / "lion_in_savanna__lineart.png").write_bytes(b"")
    (tmp_path / "hammer__lineart.png").write_bytes(b"")
    # Et un SVG print qui ne doit pas etre liste comme variant raw
    (tmp_path / "lion_in_savanna__pastel_chromakey.svg").write_bytes(b"")

    result = list_existing_variants("lion_in_savanna", base_dir=tmp_path)
    assert result == ["lineart", "pastel_chromakey"]


def test_list_existing_variants_exclut_coloriage_svg(tmp_path):
    """Le suffix _coloriage doit etre ignore meme s'il y a un .png parasite."""
    (tmp_path / "lion_in_savanna__pastel_chromakey.png").write_bytes(b"")
    # SVG coloriage interactif (ne doit pas matcher *.png de toute facon)
    (tmp_path / "lion_in_savanna__pastel_chromakey_coloriage.svg").write_bytes(
        b""
    )
    # Cas defensif : un PNG mal nomme avec le suffix _coloriage doit etre exclu
    (tmp_path / "lion_in_savanna__weird_coloriage.png").write_bytes(b"")

    result = list_existing_variants("lion_in_savanna", base_dir=tmp_path)
    assert result == ["pastel_chromakey"]


def test_list_existing_variants_invalid_leaf_id(tmp_path):
    with pytest.raises(ValueError, match="leaf_id"):
        list_existing_variants("../etc", base_dir=tmp_path)


# ---------------------------------------------------------------------------
# has_variant
# ---------------------------------------------------------------------------


def test_has_variant_true_raw_png(tmp_path):
    (tmp_path / "hammer__lineart.png").write_bytes(b"")
    assert has_variant("hammer", "lineart", base_dir=tmp_path) is True


def test_has_variant_false_raw_png(tmp_path):
    assert has_variant("hammer", "lineart", base_dir=tmp_path) is False


def test_has_variant_true_coloring_svg(tmp_path):
    (tmp_path / "hammer__lineart_coloriage.svg").write_bytes(b"")
    assert (
        has_variant(
            "hammer", "lineart", kind=KIND_COLORING_SVG, base_dir=tmp_path
        )
        is True
    )
    # Le raw_png n'existe pas
    assert (
        has_variant("hammer", "lineart", kind=KIND_RAW_PNG, base_dir=tmp_path)
        is False
    )


def test_has_variant_true_vector_svg(tmp_path):
    (tmp_path / "hammer__lineart.svg").write_bytes(b"")
    assert (
        has_variant(
            "hammer", "lineart", kind=KIND_VECTOR_SVG, base_dir=tmp_path
        )
        is True
    )


def test_has_variant_invalid_variant(tmp_path):
    with pytest.raises(ValueError, match="Variante inconnue"):
        has_variant("hammer", "bogus", base_dir=tmp_path)
