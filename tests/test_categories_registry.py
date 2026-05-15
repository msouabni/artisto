"""Tests du registry des catégories Astro côté rimalab-v2.

Source unique de vérité : ``data/categories_registry.json``. Ces tests
sont les garde-fous :

- schema/format/cohérence du registry lui-même
- garantie que ``map_leaf_to_category()`` ne peut émettre **que** des IDs
  présents dans le registry (refus fail-fast sinon)

Brief : ``docs/architect/briefs/2026-05-15_brief-categories-registry-cross-repo.md``
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "data" / "categories_registry.json"

# Path setup pour importer alwanbooks_pipeline (test_alwanbooks_pipeline.py
# fait pareil ; module non-package).
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registry() -> dict:
    """Charge le registry une fois pour le module entier."""
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def categories(registry) -> list[dict]:
    return registry["categories"]


@pytest.fixture(scope="module")
def known_ids(categories) -> set[str]:
    return {c["id"] for c in categories}


# ── Tests schéma ─────────────────────────────────────────────────────────────


def test_registry_is_valid_json():
    """Le fichier registry parse en JSON valide."""
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "version" in data
    assert "categories" in data
    assert isinstance(data["categories"], list)
    assert len(data["categories"]) >= 1


def test_registry_has_required_schema(categories):
    """Chaque catégorie a les champs requis."""
    required_keys = {
        "id", "parent_id", "weight",
        "slug_i18n", "name_i18n", "description_i18n", "keywords_i18n",
        "body",
    }
    for cat in categories:
        missing = required_keys - set(cat.keys())
        assert not missing, (
            f"category {cat.get('id', '?')!r} missing keys: {missing}"
        )
        assert isinstance(cat["id"], str)
        assert cat["parent_id"] is None or isinstance(cat["parent_id"], str)
        assert isinstance(cat["weight"], int)
        assert isinstance(cat["body"], str) and cat["body"], (
            f"category {cat['id']}: body must be non-empty string"
        )


def test_registry_ids_are_unique(categories):
    """Pas de doublon d'id dans le registry."""
    ids = [c["id"] for c in categories]
    assert len(ids) == len(set(ids)), (
        f"duplicate ids in registry: "
        f"{[i for i in ids if ids.count(i) > 1]}"
    )


def test_registry_ids_match_regex(categories):
    """Tous les id matchent ``^[a-z][a-z0-9_]*$``."""
    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    for cat in categories:
        assert pattern.match(cat["id"]), (
            f"id {cat['id']!r} does not match ^[a-z][a-z0-9_]*$"
        )


def test_registry_parent_ids_resolve(categories, known_ids):
    """Tout parent_id non-null pointe vers un id existant dans le registry."""
    for cat in categories:
        pid = cat["parent_id"]
        if pid is None:
            continue
        assert pid in known_ids, (
            f"category {cat['id']!r} has parent_id={pid!r} "
            f"not in registry (known: {sorted(known_ids)})"
        )


def test_registry_i18n_has_three_locales(categories):
    """slug_i18n / name_i18n / description_i18n / keywords_i18n ont AR/FR/EN."""
    expected_locales = {"ar", "fr", "en"}
    i18n_fields = ("slug_i18n", "name_i18n", "description_i18n", "keywords_i18n")
    for cat in categories:
        for field in i18n_fields:
            assert isinstance(cat[field], dict), (
                f"category {cat['id']}: {field} must be a dict"
            )
            locales = set(cat[field].keys())
            assert locales == expected_locales, (
                f"category {cat['id']}.{field}: expected locales "
                f"{expected_locales}, got {locales}"
            )
            # Chaque valeur doit être non vide
            for loc, val in cat[field].items():
                assert val, (
                    f"category {cat['id']}.{field}.{loc} is empty"
                )


def test_registry_keywords_count(categories):
    """Chaque locale a exactement 3 keywords (cohérent avec les MDs existants)."""
    for cat in categories:
        for loc, kws in cat["keywords_i18n"].items():
            assert isinstance(kws, list), (
                f"category {cat['id']}.keywords_i18n.{loc} must be list"
            )
            assert len(kws) == 3, (
                f"category {cat['id']}.keywords_i18n.{loc}: expected 3 "
                f"keywords, got {len(kws)} ({kws!r})"
            )
            for kw in kws:
                assert isinstance(kw, str) and kw, (
                    f"category {cat['id']}.keywords_i18n.{loc}: empty kw"
                )


# ── Tests mapper ─────────────────────────────────────────────────────────────


def _collect_leaves(node: dict | list) -> list[str]:
    """Aplatit l'arbre récursif taxonomy en liste de feuilles (id de leaves)."""
    leaves: list[str] = []

    def visit(n):
        if isinstance(n, list):
            for x in n:
                visit(x)
            return
        if not isinstance(n, dict):
            return
        children = n.get("children")
        if children:
            for c in children:
                visit(c)
        else:
            # Pas d'enfants → feuille
            if "id" in n:
                leaves.append(n["id"])

    visit(node)
    return leaves


def test_mapper_only_emits_known_categories(known_ids):
    """Pour toutes les leaves taxonomy, ``map_leaf_to_category`` renvoie
    un id présent dans le registry.
    """
    from alwanbooks_pipeline import map_leaf_to_category

    taxonomy_path = (
        PROJECT_ROOT / "data" / "prompt_generator" / "coloring_taxonomy_full.json"
    )
    if not taxonomy_path.is_file():
        pytest.skip(f"taxonomy file not found at {taxonomy_path}")

    data = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    leaves = _collect_leaves(data)
    assert len(leaves) > 100, (
        f"expected many leaves, got {len(leaves)}"
    )

    for leaf_id in leaves:
        result = map_leaf_to_category(leaf_id)
        assert result in known_ids, (
            f"mapper emitted unknown id {result!r} for leaf {leaf_id!r} "
            f"(known: {sorted(known_ids)})"
        )


def test_mapper_known_category_ids_constant_matches_registry(known_ids):
    """Le ``KNOWN_CATEGORY_IDS`` du mapper est cohérent avec le registry."""
    from alwanbooks_pipeline import KNOWN_CATEGORY_IDS

    assert set(KNOWN_CATEGORY_IDS) == set(known_ids)


def test_mapper_handles_edge_cases(known_ids):
    """None / empty string / fallback ultime → ``objects_things`` (registry-valid)."""
    from alwanbooks_pipeline import map_leaf_to_category

    for edge in (None, "", "xyz_random_unknown_leaf_42"):
        result = map_leaf_to_category(edge)
        assert result in known_ids, (
            f"mapper emitted {result!r} for edge case {edge!r}"
        )
