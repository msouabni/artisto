"""Tests Phase 3 — surface de revue décoloriage (endpoint de listing).

Couvre (cf. brief Phase 3, critères 1-2) :
  - Un ``image_output`` avec ``model_config`` décoloriage (coloring_engine +
    coloring_svg_path + métadonnées) est listé, expose ``coloring_svg_url``
    servable et des métadonnées en types Python NATIFS.
  - Une entrée ``coloring_engine="extract_palette"`` (ou sans
    ``coloring_svg_path``) N'apparaît PAS.
  - ``model_config`` None / JSON invalide → entrée ignorée, jamais de 500.
  - NULL-safe : métadonnée numérique absente/NULL → 0 / 0.0, pas de TypeError
    au tri.

Portable SQLite : ``tests/conftest.py`` force ``DATABASE_URL`` SQLite in-memory.
Aucun ComfyUI, aucune queue, aucun Postgres.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

ENDPOINT = "/api/decoloriage/artifacts"


# ── Helpers de seed ──────────────────────────────────────────────────────────


def _seed_image(conn, image_id: str, leaf_id: str | None) -> None:
    conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, origin_term_id, file_path,
                           created_at, updated_at)
        VALUES (?, ?, 'generated', 'p', ?, '',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [image_id, image_id, leaf_id],
    )


def _seed_output(conn, output_id, image_id, model_config, created_at="2026-01-01T00:00:00Z"):
    """model_config : dict (sérialisé) | str brut | None."""
    if isinstance(model_config, dict):
        mc = json.dumps(model_config, ensure_ascii=False)
    else:
        mc = model_config  # str brut ou None
    conn.execute(
        """
        INSERT INTO image_output (id, image_id, file_path, model_config, created_at)
        VALUES (?, ?, 'outputs/x.png', ?, ?)
        """,
        [output_id, image_id, mc, created_at],
    )


def _decoloriage_mc(**overrides) -> dict:
    base = {
        "variant_name": "pastel_chromakey",
        "extract_preset": "floodfill_chromakey_v1",
        "force_chromakey": True,
        "seed": 98765,
        "vector_svg_path": "data/generated/polar_bear_on_ice__pastel_chromakey.svg",
        "coloring_svg_path": "data/generated/polar_bear_on_ice__pastel_chromakey_coloriage.svg",
        "coloring_engine": "decoloriage",
        "level": "enfant",
        "n_clickable": 37,
        "n_ink_regions": 3,
        "publishable_tp": False,
        "crayon_distribution": {"#118AB2": 15, "#ffffff": 14},
        "delta_e_median": 41.28,
        "processing_s": 2.24,
    }
    base.update(overrides)
    return base


# ── Cas nominal ──────────────────────────────────────────────────────────────


def test_decoloriage_artifact_listed_with_url_and_native_metadata(
    app_with_test_db, test_conn
):
    _seed_image(test_conn, "img1", "polar_bear_on_ice")
    _seed_output(test_conn, "out1", "img1", _decoloriage_mc())
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    data = resp.json()

    assert data["count"] == 1
    item = data["items"][0]

    assert item["image_output_id"] == "out1"
    assert item["image_id"] == "img1"
    assert item["leaf_id"] == "polar_bear_on_ice"
    assert item["variant_name"] == "pastel_chromakey"
    assert item["level"] == "enfant"
    # URL servable via le mount static /data/.
    assert item["coloring_svg_url"] == (
        "/data/generated/polar_bear_on_ice__pastel_chromakey_coloriage.svg"
    )
    # Métadonnées de revue présentes + types NATIFS (JSON les rend int/float/bool).
    assert item["n_clickable"] == 37
    assert isinstance(item["n_clickable"], int)
    assert item["n_ink_regions"] == 3
    assert item["publishable_tp"] is False
    assert isinstance(item["delta_e_median"], float)
    assert item["delta_e_median"] == 41.28
    assert item["crayon_distribution"] == {"#118AB2": 15, "#ffffff": 14}

    # Tout est JSON-sérialisable (déjà passé par le wire, mais on re-vérifie).
    json.dumps(item)


def test_decoloriage_url_handles_windows_backslashes(app_with_test_db, test_conn):
    """Un coloring_svg_path stocké avec des backslashes Windows reste servable."""
    _seed_image(test_conn, "imgw", "carpet_cleaner")
    _seed_output(
        test_conn, "outw", "imgw",
        _decoloriage_mc(
            coloring_svg_path=r"data\generated\carpet_cleaner__pastel_coloriage.svg",
            variant_name="pastel",
        ),
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    item = client.get(ENDPOINT).json()["items"][0]
    assert item["coloring_svg_url"] == (
        "/data/generated/carpet_cleaner__pastel_coloriage.svg"
    )


# ── Exclusions ───────────────────────────────────────────────────────────────


def test_extract_palette_entry_excluded(app_with_test_db, test_conn):
    """Une entrée extract_palette n'apparaît pas dans la liste décoloriage."""
    _seed_image(test_conn, "img_ep", "lion_in_savanna")
    _seed_output(
        test_conn, "out_ep", "img_ep",
        {
            "variant_name": "pastel",
            "coloring_engine": "extract_palette",
            "extract_preset": "iso_trait_v3_anomaly_split",
            "coloring_svg_path": "data/generated/lion__pastel_coloriage.svg",
        },
    )
    # + un vrai artefact décoloriage pour prouver que le filtre est sélectif.
    _seed_image(test_conn, "img_ok", "polar_bear_on_ice")
    _seed_output(test_conn, "out_ok", "img_ok", _decoloriage_mc())
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    data = client.get(ENDPOINT).json()
    ids = {it["image_output_id"] for it in data["items"]}
    assert "out_ep" not in ids
    assert "out_ok" in ids
    assert data["count"] == 1


def test_decoloriage_without_svg_path_excluded(app_with_test_db, test_conn):
    """Moteur décoloriage mais sans coloring_svg_path interprétable → exclu."""
    _seed_image(test_conn, "img_nosvg", "tiger")
    mc = _decoloriage_mc()
    del mc["coloring_svg_path"]
    _seed_output(test_conn, "out_nosvg", "img_nosvg", mc)
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    data = client.get(ENDPOINT).json()
    assert data["count"] == 0


def test_empty_svg_path_excluded(app_with_test_db, test_conn):
    """coloring_svg_path vide → exclu (pas d'URL servable)."""
    _seed_image(test_conn, "img_empty", "tiger")
    _seed_output(
        test_conn, "out_empty", "img_empty",
        _decoloriage_mc(coloring_svg_path=""),
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    assert client.get(ENDPOINT).json()["count"] == 0


# ── model_config None / invalide → ignoré, pas de 500 ────────────────────────


def test_model_config_none_ignored_no_500(app_with_test_db, test_conn):
    _seed_image(test_conn, "img_none", "leaf_none")
    _seed_output(test_conn, "out_none", "img_none", None)
    _seed_image(test_conn, "img_ok2", "polar_bear_on_ice")
    _seed_output(test_conn, "out_ok2", "img_ok2", _decoloriage_mc())
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200  # pas de 500
    data = resp.json()
    ids = {it["image_output_id"] for it in data["items"]}
    assert "out_none" not in ids
    assert "out_ok2" in ids


def test_model_config_invalid_json_ignored_no_500(app_with_test_db, test_conn):
    """JSON mal formé mais contenant le motif 'coloring_engine: decoloriage'
    (donc capté par le pré-filtre SQL LIKE) → ignoré sans 500."""
    _seed_image(test_conn, "img_bad", "leaf_bad")
    # Chaîne qui matche le LIKE mais n'est PAS du JSON valide.
    _seed_output(
        test_conn, "out_bad", "img_bad",
        '{ "coloring_engine": "decoloriage", "coloring_svg_path": ',  # tronqué
    )
    _seed_image(test_conn, "img_ok3", "polar_bear_on_ice")
    _seed_output(test_conn, "out_ok3", "img_ok3", _decoloriage_mc())
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    ids = {it["image_output_id"] for it in resp.json()["items"]}
    assert "out_bad" not in ids
    assert "out_ok3" in ids


def test_model_config_non_object_json_ignored(app_with_test_db, test_conn):
    """model_config = tableau JSON (racine non-objet) contenant le motif →
    ignoré sans 500."""
    _seed_image(test_conn, "img_arr", "leaf_arr")
    _seed_output(
        test_conn, "out_arr", "img_arr",
        '["coloring_engine", "decoloriage"]',
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ── NULL-safe métadonnées ────────────────────────────────────────────────────


def test_null_metadata_coerced_to_zero(app_with_test_db, test_conn):
    """Métadonnées numériques NULL/absentes → 0 / 0.0, pas de TypeError au tri."""
    _seed_image(test_conn, "img_null", "polar_bear_on_ice")
    _seed_output(
        test_conn, "out_null", "img_null",
        {
            "coloring_engine": "decoloriage",
            "coloring_svg_path": "data/generated/x__pastel_coloriage.svg",
            # n_clickable / n_ink_regions / delta_e_median ABSENTS
            "n_clickable": None,
            "delta_e_median": None,
            "crayon_distribution": {"#118AB2": None},
            # publishable_tp absent
        },
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["n_clickable"] == 0
    assert item["n_ink_regions"] == 0
    assert item["delta_e_median"] == 0.0
    assert item["publishable_tp"] is False
    assert item["crayon_distribution"]["#118AB2"] == 0


def test_null_created_at_sort_no_typeerror(app_with_test_db, test_conn):
    """Plusieurs entrées dont une avec created_at NULL : le tri ne lève pas."""
    _seed_image(test_conn, "imgA", "polar_bear_on_ice")
    _seed_output(test_conn, "outA", "imgA", _decoloriage_mc(), created_at="2026-02-02T00:00:00Z")
    _seed_image(test_conn, "imgB", "tiger")
    # created_at NULL.
    _seed_output(test_conn, "outB", "imgB", _decoloriage_mc(variant_name="pastel"), created_at=None)
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_empty_list_when_no_decoloriage_output(app_with_test_db, test_conn):
    """Aucun artefact décoloriage → count 0, items [], pas d'erreur."""
    _seed_image(test_conn, "img_plain", "leaf_plain")
    _seed_output(
        test_conn, "out_plain", "img_plain",
        {"variant_name": "lineart"},  # pas de coloring_engine du tout
    )
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"count": 0, "items": []}


def test_leaf_id_null_when_image_missing(app_with_test_db, test_conn):
    """Output sans image jointe (LEFT JOIN) → leaf_id None, pas d'erreur."""
    # On insère un output dont l'image n'existe pas (orphelin) — LEFT JOIN.
    _seed_output(test_conn, "out_orphan", "img_ghost", _decoloriage_mc())
    test_conn.session.commit()

    client = TestClient(app_with_test_db)
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["image_output_id"] == "out_orphan"
    assert item["leaf_id"] is None
