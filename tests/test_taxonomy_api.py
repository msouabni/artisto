"""Tests API taxonomie : robustesse aux champs NULL (weight, etc.) et réponses attendues."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.routes.taxonomy import _build_terms_tree


def _flatten_terms_tree(nodes, out):
    for n in nodes or []:
        out.append(n)
        _flatten_terms_tree(n.get("children"), out)


class TestBuildTermsTree:
    """Tests unitaires sur _build_terms_tree (tri, NULL)."""

    def test_tree_handles_null_weight(self):
        """Un terme avec weight=None ne doit pas faire planter le tri."""
        rows = [
            {"id": "a", "parent_id": None, "slug": "a", "name_i18n": "{}", "description_i18n": "{}", "weight": None, "keywords": "[]"},
            {"id": "b", "parent_id": None, "slug": "b", "name_i18n": "{}", "description_i18n": "{}", "weight": 1, "keywords": "[]"},
        ]
        tree = _build_terms_tree(rows, None)
        assert len(tree) == 2
        assert tree[0]["weight"] == 0
        assert tree[1]["weight"] == 1

    def test_tree_handles_all_null_weights(self):
        """Tous les termes avec weight=None doivent donner un arbre trié sans erreur."""
        rows = [
            {"id": "x", "parent_id": None, "slug": "x", "name_i18n": "{}", "description_i18n": "{}", "weight": None, "keywords": "[]"},
            {"id": "y", "parent_id": None, "slug": "y", "name_i18n": "{}", "description_i18n": "{}", "weight": None, "keywords": "[]"},
        ]
        tree = _build_terms_tree(rows, None)
        assert len(tree) == 2
        assert all(n["weight"] == 0 for n in tree)


class TestGetVocabularyTerms:
    """Tests d'intégration GET /api/taxonomy/vocabularies/{vid}/terms."""

    def test_get_terms_returns_200_when_term_has_null_weight(self, app_with_test_db, test_conn):
        """Un vocabulaire contenant un terme avec weight NULL doit répondre 200."""
        test_conn.execute(
            """
            INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
            VALUES ('term_null_weight', 'themes', NULL, 'slug', '{}', '{}', NULL, '[]')
            """
        )
        client = TestClient(app_with_test_db)
        res = client.get("/api/taxonomy/vocabularies/themes/terms")
        assert res.status_code == 200
        data = res.json()
        assert "terms" in data
        terms = data["terms"]
        assert len(terms) >= 1
        # Le nœud renvoyé doit avoir weight entier (sérialisation JSON sûre)
        for node in terms:
            assert isinstance(node.get("weight"), int), f"weight should be int, got {type(node.get('weight'))}"
            assert isinstance(node.get("subjects_count"), int)

    def test_get_terms_response_is_valid_json_and_weights_are_int(self, app_with_test_db, test_conn):
        """La réponse GET terms doit être du JSON valide avec weight de type int (pas numpy, etc.)."""
        test_conn.execute(
            """
            INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
            VALUES ('term_serial', 'themes', NULL, 'slug_serial', '{}', '{}', 42, '[]')
            """
        )
        client = TestClient(app_with_test_db)
        res = client.get("/api/taxonomy/vocabularies/themes/terms")
        assert res.status_code == 200
        data = res.json()
        assert "terms" in data
        terms = data["terms"]
        for node in terms:
            assert isinstance(node.get("weight"), int), f"weight must be int for JSON, got {type(node.get('weight'))}"
            assert isinstance(node.get("subjects_count"), int)
            assert isinstance(node.get("id"), str)
            assert isinstance(node.get("slug"), str)

    def test_get_terms_with_realistic_tree(self, app_with_test_db, test_conn):
        """Avec parent + enfant (dont un weight NULL), GET terms renvoie 200 et structure arbre cohérente."""
        test_conn.execute(
            """
            INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
            VALUES
                ('parent_1', 'themes', NULL, 'parent1', '{}', '{}', 0, '[]'),
                ('child_1', 'themes', 'parent_1', 'child1', '{}', '{}', NULL, '[]')
            """
        )
        client = TestClient(app_with_test_db)
        res = client.get("/api/taxonomy/vocabularies/themes/terms")
        assert res.status_code == 200
        data = res.json()
        assert "terms" in data
        terms = data["terms"]
        assert len(terms) >= 1
        ids = [t["id"] for t in terms]
        assert "parent_1" in ids
        parent = next(t for t in terms if t["id"] == "parent_1")
        assert "children" in parent
        children = parent["children"]
        assert any(c["id"] == "child_1" for c in children)
        flat = []
        _flatten_terms_tree(terms, flat)
        for node in flat:
            assert isinstance(node.get("weight"), int)
            assert isinstance(node.get("subjects_count"), int)
