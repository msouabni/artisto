"""Tests endpoints API /api/prompt-generator/* (playground)."""
from __future__ import annotations

import os

import pytest

# Tests : utilisent le default conftest (ARTISTE_PROMPT_STYLE=lineart).
# Quand on veut tester pastel, on passe style=pastel explicite.

from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# === /leafs ==================================================================
def test_list_leafs_default(client):
    r = client.get("/api/prompt-generator/leafs")
    assert r.status_code == 200
    data = r.json()
    assert "count" in data
    assert "total" in data
    assert "leafs" in data
    assert data["total"] > 100  # taxonomie volumineuse
    assert len(data["leafs"]) <= 50  # limit default


def test_list_leafs_search_polar(client):
    r = client.get("/api/prompt-generator/leafs?search=polar")
    assert r.status_code == 200
    data = r.json()
    assert "polar_bear_on_ice" in data["leafs"]


def test_list_leafs_search_no_match(client):
    r = client.get("/api/prompt-generator/leafs?search=zzzzzz_nope")
    assert r.status_code == 200
    assert r.json()["count"] == 0


# === /{leaf_id} =============================================================
def test_get_prompt_leaf_id_pastel(client):
    r = client.get("/api/prompt-generator/polar_bear_on_ice?style=pastel")
    assert r.status_code == 200
    data = r.json()
    assert data["leaf_id"] == "polar_bear_on_ice"
    assert data["input_format"] == "leaf_id_direct"
    assert data["prompt"]["style"] == "pastel"
    assert "soft pastel" in data["prompt"]["positive"].lower()


def test_get_prompt_leaf_id_lineart(client):
    r = client.get("/api/prompt-generator/polar_bear_on_ice?style=lineart")
    assert r.status_code == 200
    assert r.json()["prompt"]["style"] == "lineart"


def test_get_prompt_invalid_leaf(client):
    r = client.get("/api/prompt-generator/zzzzz_not_a_leaf")
    assert r.status_code == 404


def test_get_prompt_invalid_style(client):
    r = client.get("/api/prompt-generator/polar_bear_on_ice?style=baroque")
    # FastAPI doit valider via regex ^(pastel|lineart)$ -> 422
    assert r.status_code == 422


# === /resolve ===============================================================
def test_resolve_leaf_id_direct(client):
    r = client.get("/api/prompt-generator/resolve?q=polar_bear_on_ice")
    assert r.status_code == 200
    data = r.json()
    assert data["leaf_id"] == "polar_bear_on_ice"
    assert data["input_format"] == "leaf_id_direct"


def test_resolve_url_relative_alwanbooks(client):
    """URL relative type ar/colorier/aldb-alqtby/."""
    r = client.get("/api/prompt-generator/resolve?q=ar/colorier/aldb-alqtby/")
    if r.status_code == 200:
        data = r.json()
        assert data["leaf_id"] == "polar_bear_on_ice"
        assert data["locale_detected"] == "ar"
        assert data["slug_used"] == "aldb-alqtby"
        assert data["input_format"] == "url_relative"
    else:
        # Si data/export/posts/ar/aldb-alqtby.json n'existe pas dans le repo,
        # le test passe en mode skip (env dependant).
        assert r.status_code == 404


def test_resolve_url_absolute(client):
    r = client.get(
        "/api/prompt-generator/resolve?q=https://alwanbooks.com/ar/talween/hayawanat/bariyya/alnmr-albnghaly/"
    )
    if r.status_code == 200:
        data = r.json()
        assert data["leaf_id"] == "bengal_tiger"
        assert data["locale_detected"] == "ar"
        assert data["slug_used"] == "alnmr-albnghaly"
        assert data["input_format"] == "url_absolute"
    else:
        assert r.status_code == 404


def test_resolve_slug_nu(client):
    r = client.get("/api/prompt-generator/resolve?q=ala-tnzyf-alsjad")
    if r.status_code == 200:
        data = r.json()
        assert data["leaf_id"] == "carpet_cleaner"
        assert data["slug_used"] == "ala-tnzyf-alsjad"
    else:
        assert r.status_code == 404


def test_resolve_empty_q(client):
    r = client.get("/api/prompt-generator/resolve?q=")
    # Param vide rejete par FastAPI ou par notre code (400 ou 422)
    assert r.status_code in (400, 422)


def test_resolve_not_found(client):
    r = client.get("/api/prompt-generator/resolve?q=zzzzz_not_a_slug")
    assert r.status_code == 404


def test_resolve_style_propagated(client):
    """Le style demande dans /resolve est applique au prompt."""
    r = client.get("/api/prompt-generator/resolve?q=polar_bear_on_ice&style=pastel")
    assert r.status_code == 200
    assert r.json()["prompt"]["style"] == "pastel"

    r = client.get("/api/prompt-generator/resolve?q=polar_bear_on_ice&style=lineart")
    assert r.status_code == 200
    assert r.json()["prompt"]["style"] == "lineart"
