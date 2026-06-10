"""Tests POST /api/images/bulk-create-generation-jobs — extension multi-variantes (C1.2).

Couvre l'extension multi-variantes (2026-06-01) de l'endpoint
``/api/images/bulk-create-generation-jobs`` : 1 job par image x variante active,
ADD-ONLY check via image_output, fallback lineart legacy, etc.

Les tests utilisent :
- monkeypatch sur ``services.pipeline_variants`` pour pointer vers un registre
  test (3 variantes lineart/pastel_chromakey/flat_cartoon_chromakey).
- monkeypatch sur ``PromptGenerator.build_prompt`` pour éviter de charger les
  JSONs taxonomie/cartographie (~10 MB) et rester déterministe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from services import pipeline_variants  # noqa: E402


# ── Helpers DB ────────────────────────────────────────────────────────────────

def _insert_image(
    conn, image_id: str, *, status: str = "prompt_ready",
    prompt: str = "img prompt", negative_prompt: str = "img negative",
    origin_term_id: str | None = "lion_in_savanna",
) -> None:
    conn.execute(
        """
        INSERT INTO image (
            id, title, status, prompt, negative_prompt, origin_term_id,
            origin_taxonomy_id, file_path, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'universal_v0', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [image_id, image_id, status, prompt, negative_prompt, origin_term_id],
    )


def _insert_image_output(
    conn, *, image_id: str, output_id: str, model_config: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO image_output (
            id, image_id, file_path, model_config, created_at
        )
        VALUES (?, ?, '', ?, '2026-01-01T00:00:00Z')
        """,
        [output_id, image_id, json.dumps(model_config, ensure_ascii=False)],
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_variants_cache():
    """Reset le cache lru du registre entre les tests pour éviter les fuites."""
    pipeline_variants._clear_cache()
    yield
    pipeline_variants._clear_cache()


def _registry_full() -> dict:
    """Registre test : 3 variantes, default_active=pastel_chromakey."""
    return {
        "version": 1,
        "default_active": ["pastel_chromakey"],
        "variants": {
            "pastel_chromakey": {
                "prompt_style": "pastel",
                "force_chromakey": True,
                "chromakey_rgb": [0, 177, 64],
                "extract_preset": "floodfill_chromakey_v1",
                "output_kind": "online_coloring",
                "label": "Pastel chromakey",
            },
            "flat_cartoon_chromakey": {
                "prompt_style": "flat_cartoon",
                "force_chromakey": True,
                "chromakey_rgb": [0, 177, 64],
                "extract_preset": "floodfill_chromakey_v1",
                "output_kind": "online_coloring",
                "label": "Flat cartoon chromakey",
            },
            "lineart": {
                "prompt_style": "lineart",
                "force_chromakey": False,
                "chromakey_rgb": None,
                "extract_preset": None,
                "output_kind": "print",
                "label": "Lineart",
            },
        },
        "per_category_override": {},
    }


@pytest.fixture
def variants_registry(tmp_path, monkeypatch):
    """Écrit un registre test dans tmp_path et patch DEFAULT_REGISTRY_PATH."""
    data = _registry_full()
    p = tmp_path / "pipeline_variants.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(pipeline_variants, "DEFAULT_REGISTRY_PATH", p)
    # Clear cache après le patch pour qu'il prenne effet.
    pipeline_variants._clear_cache()
    return p


@pytest.fixture
def mock_prompt_generator(monkeypatch):
    """Patch PromptGenerator pour ne pas charger les JSONs taxonomie.

    Retourne un faux `build_prompt` qui produit un dict déterministe.
    """
    # On crée un faux "singleton" qu'on installera dans le module routes.images.
    class FakePromptGenerator:
        def __init__(self):
            self.calls: list[tuple[str, str | None]] = []

        def build_prompt(self, leaf_id: str, style: str | None = None) -> dict:
            self.calls.append((leaf_id, style))
            # Fragment "illustration," présent pour permettre l'injection chromakey
            # après ce marker (cf. _inject_chromakey).
            if style == "pastel":
                positive = (
                    "soft pastel children's coloring illustration, "
                    f"a beautiful {leaf_id} subject, thick black outlines"
                )
                negative = "photographic, realistic, 3d render"
            elif style == "flat_cartoon":
                positive = (
                    f"flat cartoon illustration on pure cinema chromakey green background (#00B140), "
                    f"a beautiful {leaf_id} subject"
                )
                negative = "photographic, realistic, gradient fill"
            else:
                positive = f"coloring book page for kids, a {leaf_id} subject"
                negative = "no colors"
            return {
                "positive": positive,
                "negative": negative,
                "resolution": (1024, 1024),
                "workflow_class": "Solo objet",
            }

    fake = FakePromptGenerator()

    # Patch directement le singleton dans le module routes.images :
    # _get_prompt_generator() lit _PROMPT_GENERATOR_SINGLETON.
    from api.routes import images as images_module
    monkeypatch.setattr(images_module, "_PROMPT_GENERATOR_SINGLETON", fake)
    return fake


@pytest.fixture
def client(app_with_test_db):
    return TestClient(app_with_test_db)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBulkVariantsJobs:
    def test_endpoint_sans_variants_comportement_legacy_si_registre_vide(
        self, client, test_conn, tmp_path, monkeypatch,
    ):
        """Si default_active=[] (registre minimal) ET variants non fournis,
        bascule en mode legacy : 1 job par image basé sur Image.prompt direct."""
        data = _registry_full()
        data["default_active"] = []
        p = tmp_path / "pipeline_variants.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(pipeline_variants, "DEFAULT_REGISTRY_PATH", p)
        pipeline_variants._clear_cache()

        _insert_image(test_conn, "img_legacy", prompt="legacy prompt", origin_term_id=None)
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_legacy"]},
        )
        assert r.status_code == 200, r.text
        data_resp = r.json()
        assert data_resp["summary"]["success"] == 1
        results = data_resp["results"]
        assert len(results) == 1
        # En legacy : pas de variant_name dans le résultat.
        assert "variant_name" not in results[0]
        # Le job stocké a le prompt de l'image (legacy).
        cfg_row = test_conn.execute(
            "SELECT config FROM job WHERE image_id = 'img_legacy'"
        ).fetchone()
        cfg = json.loads(cfg_row[0])
        assert cfg["prompt"] == "legacy prompt"
        assert "variant_name" not in cfg

    def test_endpoint_avec_2_variants(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """variants=["pastel_chromakey","lineart"] → 2 jobs créés pour 1 image."""
        _insert_image(test_conn, "img_dual", prompt="raw lineart prompt")
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={
                "image_ids": ["img_dual"],
                "variants": ["pastel_chromakey", "lineart"],
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["summary"]["success"] == 2, data
        assert data["summary"]["total"] == 1

        jobs = test_conn.execute(
            "SELECT id, config FROM job WHERE image_id = 'img_dual' ORDER BY id"
        ).fetchall()
        assert len(jobs) == 2
        variant_names = {json.loads(j[1])["variant_name"] for j in jobs}
        assert variant_names == {"pastel_chromakey", "lineart"}

    def test_addonly_skip_si_image_output_existe(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """Si un image_output a déjà variant_name=pastel_chromakey, on skip cette
        variante au prochain enqueue (ADD-ONLY)."""
        _insert_image(test_conn, "img_addonly", prompt="raw")
        _insert_image_output(
            test_conn,
            image_id="img_addonly",
            output_id="out_existing",
            model_config={"variant_name": "pastel_chromakey", "seed": 42},
        )
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={
                "image_ids": ["img_addonly"],
                "variants": ["pastel_chromakey", "lineart"],
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # 1 success (lineart) + 1 skipped (pastel_chromakey).
        assert data["summary"]["success"] == 1, data
        assert data["summary"]["skipped"] == 1, data

        skipped_entries = [r for r in data["results"] if r.get("skipped")]
        assert len(skipped_entries) == 1
        assert skipped_entries[0]["variant_name"] == "pastel_chromakey"

        # 1 seul job créé en DB (lineart).
        jobs = test_conn.execute(
            "SELECT config FROM job WHERE image_id = 'img_addonly'"
        ).fetchall()
        assert len(jobs) == 1
        assert json.loads(jobs[0][0])["variant_name"] == "lineart"

    def test_variant_inconnue_renvoie_400(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """variants=["bogus"] → 400 immédiat, 0 job créé."""
        _insert_image(test_conn, "img_bogus", prompt="raw")
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_bogus"], "variants": ["bogus"]},
        )
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "bogus" in detail.lower() or "inconnue" in detail.lower()

        jobs = test_conn.execute(
            "SELECT 1 FROM job WHERE image_id = 'img_bogus'"
        ).fetchall()
        assert len(jobs) == 0

    def test_lineart_utilise_image_prompt(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """La variante lineart utilise Image.prompt + Image.negative_prompt directement
        (sans appeler PromptGenerator)."""
        custom_prompt = "MY_CUSTOM_LINEART_PROMPT_42"
        custom_neg = "MY_CUSTOM_NEG_42"
        _insert_image(
            test_conn, "img_lineart",
            prompt=custom_prompt, negative_prompt=custom_neg,
        )
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_lineart"], "variants": ["lineart"]},
        )
        assert r.status_code == 200, r.text
        cfg_row = test_conn.execute(
            "SELECT config FROM job WHERE image_id = 'img_lineart'"
        ).fetchone()
        cfg = json.loads(cfg_row[0])
        assert cfg["prompt"] == custom_prompt
        assert cfg["negative_prompt"] == custom_neg
        assert cfg["variant_name"] == "lineart"
        # PromptGenerator NE doit PAS avoir été appelé pour lineart.
        assert mock_prompt_generator.calls == []

    def test_pastel_reconstruit_prompt_via_generator(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """La variante pastel_chromakey reconstruit le prompt via PromptGenerator
        et injecte chromakey green (#00B140) si absent du header pastel."""
        _insert_image(
            test_conn, "img_pastel",
            prompt="ORIGINAL_PROMPT_NOT_USED",
            origin_term_id="lion_in_savanna",
        )
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_pastel"], "variants": ["pastel_chromakey"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["summary"]["success"] == 1, r.json()

        cfg_row = test_conn.execute(
            "SELECT config FROM job WHERE image_id = 'img_pastel'"
        ).fetchone()
        cfg = json.loads(cfg_row[0])
        # Le prompt diffère du prompt original de l'image.
        assert cfg["prompt"] != "ORIGINAL_PROMPT_NOT_USED"
        assert "pastel" in cfg["prompt"].lower()
        # Chromakey injecté car absent du header pastel.
        assert "chromakey green" in cfg["prompt"].lower()
        assert "#00b140" in cfg["prompt"].lower()
        # PromptGenerator a été appelé avec leaf_id + style=pastel.
        assert ("lion_in_savanna", "pastel") in mock_prompt_generator.calls

    def test_flat_cartoon_pas_de_double_injection_chromakey(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """flat_cartoon a déjà 'chromakey green' dans son header (cf. mock) →
        pas de double injection."""
        _insert_image(test_conn, "img_flat", origin_term_id="lion_in_savanna")
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_flat"], "variants": ["flat_cartoon_chromakey"]},
        )
        assert r.status_code == 200, r.text
        cfg_row = test_conn.execute(
            "SELECT config FROM job WHERE image_id = 'img_flat'"
        ).fetchone()
        cfg = json.loads(cfg_row[0])
        # Compte d'occurrences "chromakey green" doit rester 1 (pas de doublement).
        assert cfg["prompt"].lower().count("chromakey green") == 1

    def test_jobconfig_contient_variant_name_et_extract_preset(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """Chaque job a variant_name, extract_preset et force_chromakey dans son config JSON."""
        _insert_image(test_conn, "img_meta", origin_term_id="lion_in_savanna")
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={
                "image_ids": ["img_meta"],
                "variants": ["pastel_chromakey", "lineart"],
            },
        )
        assert r.status_code == 200, r.text
        rows = test_conn.execute(
            "SELECT config FROM job WHERE image_id = 'img_meta'"
        ).fetchall()
        configs_by_variant = {
            json.loads(r[0])["variant_name"]: json.loads(r[0]) for r in rows
        }
        assert "pastel_chromakey" in configs_by_variant
        assert "lineart" in configs_by_variant

        pc = configs_by_variant["pastel_chromakey"]
        assert pc["extract_preset"] == "floodfill_chromakey_v1"
        assert pc["force_chromakey"] is True

        la = configs_by_variant["lineart"]
        assert la["extract_preset"] is None
        assert la["force_chromakey"] is False

    def test_default_active_si_variants_none(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """Sans le champ variants, utilise default_active du registre (= ['pastel_chromakey'])."""
        _insert_image(test_conn, "img_default", origin_term_id="lion_in_savanna")
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_default"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["summary"]["success"] == 1, r.json()

        cfg_row = test_conn.execute(
            "SELECT config FROM job WHERE image_id = 'img_default'"
        ).fetchone()
        cfg = json.loads(cfg_row[0])
        assert cfg["variant_name"] == "pastel_chromakey"

    def test_pastel_sans_origin_term_id_echoue_proprement(
        self, client, test_conn, variants_registry, mock_prompt_generator,
    ):
        """Une variante non-lineart sans leaf_id (origin_term_id NULL) doit
        échouer avec ok=False et message clair — sans planter l'endpoint."""
        _insert_image(
            test_conn, "img_no_leaf",
            origin_term_id=None,
            prompt="raw",
        )
        r = client.post(
            "/api/images/bulk-create-generation-jobs",
            json={"image_ids": ["img_no_leaf"], "variants": ["pastel_chromakey"]},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["summary"]["success"] == 0
        assert data["summary"]["failed"] == 1
        err_msg = data["results"][0]["error"].lower()
        assert "leaf_id" in err_msg or "origin_term_id" in err_msg
