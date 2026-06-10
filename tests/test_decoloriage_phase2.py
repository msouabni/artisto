"""Tests Phase 2 — industrialisation backend décoloriage.

Couvre (cf. brief Phase 2) :
  - ``produce_coloring_artifact(engine="decoloriage")`` sur l'image réelle du
    spike → SVG bicouche écrit + métadonnées typées attendues.
  - Dispatch flag : ``engine="extract_palette"`` sélectionne le chemin legacy
    (services natifs mockés, pas de dépendance au preset réel).
  - ``ARTISTE_COLORING_ENGINE`` lu à CHAQUE appel (rollback sans redémarrage).
  - ``DecoloriageResult.to_metadata()`` : JSON-sérialisable + numériques natifs
    (pas de ``numpy.*``).
  - Enrichissement ``model_config`` additif (clés existantes préservées).
  - Aucun accès DB : le service décoloriage ne touche aucune base.

Portable SQLite : ``tests/conftest.py`` force ``DATABASE_URL`` SQLite in-memory.
Aucun ComfyUI, aucune queue.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import workers.image_post_processing_worker as pp_mod
from workers.image_post_processing_worker import (
    DEFAULT_COLORING_ENGINE,
    ENGINE_DECOLORIAGE,
    ENGINE_EXTRACT_PALETTE,
    _resolve_coloring_engine,
    produce_coloring_artifact,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Image pastel réelle (sortie ERNIE prod, leaf polar_bear_on_ice) — celle du spike.
TEST_PNG = (
    PROJECT_ROOT
    / "data" / "outputs"
    / "test_e2e_polar_bear_on_ice_job_gen_1780755027700885100_0_pastel_chromakey.png"
)

_DECOLORIAGE_METADATA_KEYS = {
    "coloring_engine",
    "level",
    "n_clickable",
    "n_ink_regions",
    "publishable_tp",
    "crayon_distribution",
    "delta_e_median",
    "processing_s",
}


# ── Flag : lecture à chaque appel ────────────────────────────────────────────


def test_default_engine_is_decoloriage(monkeypatch):
    """Sans variable d'env, le moteur par défaut est décoloriage (D1)."""
    monkeypatch.delenv("ARTISTE_COLORING_ENGINE", raising=False)
    assert DEFAULT_COLORING_ENGINE == ENGINE_DECOLORIAGE
    assert _resolve_coloring_engine() == ENGINE_DECOLORIAGE


def test_flag_read_each_call(monkeypatch):
    """Le flag est relu à chaque appel (pattern ARTISTE_PROMPT_STYLE)."""
    monkeypatch.setenv("ARTISTE_COLORING_ENGINE", "extract_palette")
    assert _resolve_coloring_engine() == ENGINE_EXTRACT_PALETTE
    monkeypatch.setenv("ARTISTE_COLORING_ENGINE", "decoloriage")
    assert _resolve_coloring_engine() == ENGINE_DECOLORIAGE


def test_flag_unknown_falls_back(monkeypatch):
    """Une valeur inconnue retombe sur le défaut décoloriage."""
    monkeypatch.setenv("ARTISTE_COLORING_ENGINE", "bogus")
    assert _resolve_coloring_engine() == ENGINE_DECOLORIAGE


# ── Dispatch decoloriage (fixture réelle) ────────────────────────────────────


@pytest.fixture(scope="module")
def decoloriage_run(tmp_path_factory):
    if not TEST_PNG.exists():
        pytest.skip(f"Image de test absente : {TEST_PNG}")
    out_dir = tmp_path_factory.mktemp("decoloriage_phase2")
    out_svg = out_dir / "polar_bear_coloriage.svg"
    meta = produce_coloring_artifact(
        TEST_PNG, out_svg, engine=ENGINE_DECOLORIAGE, level="enfant",
    )
    return out_svg, meta


def test_dispatch_decoloriage_writes_bilayer_svg(decoloriage_run):
    """engine=decoloriage → SVG bicouche écrit sur disque."""
    out_svg, _meta = decoloriage_run
    assert out_svg.is_file()
    svg = out_svg.read_text(encoding="utf-8")
    assert '<g id="fills"' in svg
    assert '<g id="strokes"' in svg
    assert 'fill-rule="evenodd"' in svg


def test_dispatch_decoloriage_metadata_keys(decoloriage_run):
    """Les métadonnées portent exactement les clés contractuelles."""
    _out_svg, meta = decoloriage_run
    assert set(meta.keys()) == _DECOLORIAGE_METADATA_KEYS
    assert meta["coloring_engine"] == ENGINE_DECOLORIAGE
    assert meta["level"] == "enfant"
    assert meta["n_clickable"] > 0
    assert isinstance(meta["delta_e_median"], float)
    assert isinstance(meta["crayon_distribution"], dict)
    assert meta["crayon_distribution"]  # non vide


def test_dispatch_decoloriage_metadata_native_types(decoloriage_run):
    """Toutes les valeurs sont des types Python natifs (pas de numpy.*)."""
    _out_svg, meta = decoloriage_run
    assert type(meta["n_clickable"]) is int
    assert type(meta["n_ink_regions"]) is int
    assert type(meta["publishable_tp"]) is bool
    assert type(meta["delta_e_median"]) is float
    assert type(meta["processing_s"]) is float
    for k, v in meta["crayon_distribution"].items():
        assert type(k) is str
        assert type(v) is int


def test_to_metadata_json_serializable(decoloriage_run):
    """json.dumps ne lève pas (types JSON natifs)."""
    _out_svg, meta = decoloriage_run
    dumped = json.dumps(meta)  # ne doit pas lever
    reloaded = json.loads(dumped)
    assert reloaded["coloring_engine"] == ENGINE_DECOLORIAGE


def test_to_metadata_from_result_directly():
    """to_metadata() est cohérent appelé directement sur DecoloriageResult."""
    from services.decoloriage import DecoloriageResult, RegionMeta

    result = DecoloriageResult(
        svg="<svg/>",
        regions=[RegionMeta(1, "Ocean", "#118AB2", "#1199CC", False, 12.3)],
        n_clickable=1,
        publishable_tp=False,
        crayon_distribution={"#118AB2": 1},
        delta_e_median=12.3,
        level="enfant",
        n_ink_regions=0,
        timing_s=1.5,
    )
    meta = result.to_metadata()
    assert set(meta.keys()) == _DECOLORIAGE_METADATA_KEYS
    assert meta == {
        "coloring_engine": "decoloriage",
        "level": "enfant",
        "n_clickable": 1,
        "n_ink_regions": 0,
        "publishable_tp": False,
        "crayon_distribution": {"#118AB2": 1},
        "delta_e_median": 12.3,
        "processing_s": 1.5,
    }
    json.dumps(meta)  # ne lève pas


def test_to_metadata_null_safe():
    """to_metadata() reste robuste si des numériques sont None (NULL-safe)."""
    from services.decoloriage import DecoloriageResult

    result = DecoloriageResult(
        svg="<svg/>",
        regions=[],
        n_clickable=None,  # type: ignore[arg-type]
        publishable_tp=False,
        crayon_distribution={"#FF2E63": None},  # type: ignore[dict-item]
        delta_e_median=None,  # type: ignore[arg-type]
        level="enfant",
    )
    meta = result.to_metadata()
    assert meta["n_clickable"] == 0
    assert meta["delta_e_median"] == 0.0
    assert meta["processing_s"] == 0.0
    assert meta["crayon_distribution"]["#FF2E63"] == 0
    json.dumps(meta)  # ne lève pas


# ── Dispatch rollback extract_palette (mocké) ────────────────────────────────


def test_dispatch_extract_palette_mocked(tmp_path, monkeypatch):
    """engine=extract_palette → chemin legacy (make_params/extract_palette/
    render_svg), services natifs mockés."""
    calls: dict = {}

    def fake_make_params(preset):
        calls["preset"] = preset
        return SimpleNamespace(preset=preset)

    def fake_extract_palette(png_path, params):
        calls["png"] = Path(png_path)
        calls["params"] = params
        return SimpleNamespace(name="fake")

    def fake_render_svg(result, mode="full"):
        calls["mode"] = mode
        return f"<svg data-mode='{mode}' data-fake='1'/>"

    monkeypatch.setattr(pp_mod, "make_params", fake_make_params)
    monkeypatch.setattr(pp_mod, "extract_palette", fake_extract_palette)
    monkeypatch.setattr(pp_mod, "render_svg", fake_render_svg)

    png = tmp_path / "in.png"
    png.write_bytes(b"not-a-real-png")  # jamais lu (extract_palette mocké)
    out_svg = tmp_path / "out_coloriage.svg"

    meta = produce_coloring_artifact(
        png, out_svg,
        engine=ENGINE_EXTRACT_PALETTE,
        extract_preset="iso_trait_v3_anomaly_split",
    )

    assert calls["preset"] == "iso_trait_v3_anomaly_split"
    assert calls["mode"] == pp_mod.DEFAULT_COLORING_MODE  # blank_outlined inchangé
    assert out_svg.is_file()
    assert "data-fake='1'" in out_svg.read_text(encoding="utf-8")
    assert meta == {
        "coloring_engine": ENGINE_EXTRACT_PALETTE,
        "extract_preset": "iso_trait_v3_anomaly_split",
    }


def test_extract_palette_requires_preset(tmp_path):
    """engine=extract_palette sans preset → ValueError explicite."""
    png = tmp_path / "in.png"
    png.write_bytes(b"x")
    with pytest.raises(ValueError, match="extract_preset"):
        produce_coloring_artifact(
            png, tmp_path / "out.svg", engine=ENGINE_EXTRACT_PALETTE,
        )


def test_unknown_engine_raises(tmp_path):
    """Moteur inconnu → ValueError."""
    png = tmp_path / "in.png"
    png.write_bytes(b"x")
    with pytest.raises(ValueError, match="inconnu"):
        produce_coloring_artifact(png, tmp_path / "out.svg", engine="nope")


# ── Enrichissement model_config additif ──────────────────────────────────────


def test_model_config_enrichment_additive(test_conn, tmp_path, monkeypatch):
    """save_result fusionne les métadonnées coloriage SANS écraser les clés
    existantes (variant_name, force_chromakey, seed, …)."""
    from workers.image_post_processing_worker import ImagePostProcessingWorker

    # Seed un image_output avec model_config riche pré-existant.
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, origin_term_id, file_path,
                           created_at, updated_at)
        VALUES ('img_mc', 'img_mc', 'generated', 'p', 'polar_bear_on_ice', '',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.execute(
        """
        INSERT INTO image_output (id, image_id, file_path, model_config, created_at)
        VALUES ('out_mc', 'img_mc', 'outputs/x.png', ?, '2026-01-01T00:00:00Z')
        """,
        [
            json.dumps(
                {
                    "variant_name": "pastel_chromakey",
                    "extract_preset": "floodfill_chromakey_v1",
                    "force_chromakey": True,
                    "seed": 98765,
                },
                ensure_ascii=False,
            )
        ],
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type,
                         entity_id, started_at)
        VALUES ('job_mc', 'image_post_processing', 'running', '{}',
                '2026-01-01T00:00:00Z', 'image_output', 'out_mc',
                '2026-01-01T00:00:00Z')
        """
    )
    test_conn.session.commit()

    worker = ImagePostProcessingWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn
    try:
        worker.save_result(
            {"job_id": "job_mc", "started_at": "2026-01-01T00:00:00Z"},
            {
                "image_output_id": "out_mc",
                "leaf_id": "polar_bear_on_ice",
                "variant_name": "pastel_chromakey",
                "extract_preset": "floodfill_chromakey_v1",
                "vector_svg_path": "data/generated/polar_bear_on_ice__pastel_chromakey.svg",
                "coloring_svg_path": "data/generated/polar_bear_on_ice__pastel_chromakey_coloriage.svg",
                "coloring_metadata": {
                    "coloring_engine": "decoloriage",
                    "level": "enfant",
                    "n_clickable": 37,
                    "n_ink_regions": 3,
                    "publishable_tp": False,
                    "crayon_distribution": {"#118AB2": 15, "#ffffff": 14},
                    "delta_e_median": 41.28,
                    "processing_s": 2.24,
                },
            },
        )
    finally:
        test_conn.close = original_close

    row = test_conn.execute(
        "SELECT model_config FROM image_output WHERE id = ?", ["out_mc"],
    ).fetchone()
    mc = json.loads(row[0])

    # Clés décoloriage ajoutées.
    assert mc["coloring_engine"] == "decoloriage"
    assert mc["level"] == "enfant"
    assert mc["n_clickable"] == 37
    assert mc["n_ink_regions"] == 3
    assert mc["publishable_tp"] is False
    assert mc["crayon_distribution"] == {"#118AB2": 15, "#ffffff": 14}
    assert mc["delta_e_median"] == 41.28
    assert mc["processing_s"] == 2.24
    # Chemins ajoutés.
    assert mc["coloring_svg_path"].endswith("pastel_chromakey_coloriage.svg")
    assert mc["vector_svg_path"].endswith("pastel_chromakey.svg")
    # Clés pré-existantes PRÉSERVÉES.
    assert mc["variant_name"] == "pastel_chromakey"
    assert mc["force_chromakey"] is True
    assert mc["seed"] == 98765


# ── Aucun accès DB par le service ────────────────────────────────────────────


def test_decoloriage_service_no_db_import():
    """Le module service décoloriage n'importe aucun accès base de données."""
    import services.decoloriage as deco

    src = Path(deco.__file__).read_text(encoding="utf-8")
    assert "api.db" not in src
    assert "SessionLocal" not in src
    assert "sqlalchemy" not in src.lower()
