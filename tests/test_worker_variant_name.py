"""Tests C1.3 — ImageWorker stocke variant_name/extract_preset/force_chromakey
dans ``image_output.model_config``.

Couvre :
- Helper unitaire ``_enrich_model_config_with_variant`` (cas variant_name présent,
  legacy sans variant_name, config corrompue, base_model_config dict/str/None).
- Test end-to-end via ``ImageWorker.save_result`` qui lit ``job["config"]`` et
  enrichit la colonne ``image_output.model_config`` à l'INSERT.

Rétrocompat : aucun changement de comportement pour les jobs legacy ; les
champs ``variant_name`` et ``extract_preset`` sont à ``None``, ``force_chromakey``
à ``False``.
"""
from __future__ import annotations

import json

import pytest
from PIL import Image as PILImage

import workers.image_worker as image_worker_mod
from workers.image_worker import ImageWorker, _enrich_model_config_with_variant


# ── Tests unitaires du helper ─────────────────────────────────────────────────


class TestEnrichModelConfigWithVariant:
    def test_job_config_avec_variant_name_pastel(self):
        """job.config avec champs variante → ajout dans model_config."""
        base = {"prompt": "x", "seed": 42, "width": 1024}
        jc = {
            "prompt": "x",
            "variant_name": "pastel_chromakey",
            "extract_preset": "floodfill_chromakey_v1",
            "force_chromakey": True,
        }
        out = _enrich_model_config_with_variant(base, jc)
        data = json.loads(out)
        assert data["variant_name"] == "pastel_chromakey"
        assert data["extract_preset"] == "floodfill_chromakey_v1"
        assert data["force_chromakey"] is True
        # Champs existants préservés.
        assert data["seed"] == 42
        assert data["width"] == 1024

    def test_job_config_lineart_force_chromakey_false(self):
        """variant_name=lineart, extract_preset=None, force_chromakey=False."""
        out = _enrich_model_config_with_variant(
            {"prompt": "p"},
            {
                "variant_name": "lineart",
                "extract_preset": None,
                "force_chromakey": False,
            },
        )
        data = json.loads(out)
        assert data["variant_name"] == "lineart"
        assert data["extract_preset"] is None
        assert data["force_chromakey"] is False

    def test_job_config_legacy_sans_champs_variant(self):
        """job.config legacy (pas de variant_name) → None/None/False."""
        out = _enrich_model_config_with_variant(
            {"prompt": "p", "steps": 8},
            {"prompt": "p", "steps": 8},
        )
        data = json.loads(out)
        assert data["variant_name"] is None
        assert data["extract_preset"] is None
        assert data["force_chromakey"] is False
        assert data["steps"] == 8

    def test_job_config_none(self):
        """job_config=None → enrichit avec champs à None/False (legacy)."""
        out = _enrich_model_config_with_variant({"prompt": "p"}, None)
        data = json.loads(out)
        assert data["variant_name"] is None
        assert data["extract_preset"] is None
        assert data["force_chromakey"] is False

    def test_job_config_str_json_valid(self):
        """job_config peut être un str JSON (ex. SQL brut non parsé)."""
        out = _enrich_model_config_with_variant(
            {"prompt": "p"},
            '{"variant_name": "pastel_chromakey", "extract_preset": "fc_v1", "force_chromakey": true}',
        )
        data = json.loads(out)
        assert data["variant_name"] == "pastel_chromakey"
        assert data["extract_preset"] == "fc_v1"
        assert data["force_chromakey"] is True

    def test_job_config_str_invalid_json(self):
        """job_config corrompu (non-JSON) → traitement legacy, pas d'exception."""
        out = _enrich_model_config_with_variant(
            {"prompt": "p"},
            "not json at all {",
        )
        data = json.loads(out)
        assert data["variant_name"] is None
        assert data["extract_preset"] is None
        assert data["force_chromakey"] is False

    def test_base_model_config_str_json(self):
        """base_model_config peut être un str JSON (déjà sérialisé)."""
        out = _enrich_model_config_with_variant(
            '{"prompt": "p", "steps": 4}',
            {"variant_name": "lineart", "extract_preset": None, "force_chromakey": False},
        )
        data = json.loads(out)
        assert data["steps"] == 4
        assert data["variant_name"] == "lineart"

    def test_base_model_config_none(self):
        """base_model_config=None → dict vide enrichi avec champs variante."""
        out = _enrich_model_config_with_variant(None, {"variant_name": "lineart"})
        data = json.loads(out)
        assert data == {
            "variant_name": "lineart",
            "extract_preset": None,
            "force_chromakey": False,
        }

    def test_base_model_config_str_corrompu(self):
        """base_model_config non-JSON → reset à {} et enrichi (tolérant)."""
        out = _enrich_model_config_with_variant(
            "{not valid",
            {"variant_name": "lineart"},
        )
        data = json.loads(out)
        assert data["variant_name"] == "lineart"

    def test_force_chromakey_truthy_normalise_en_bool(self):
        """force_chromakey doit toujours être un vrai bool dans la sortie."""
        out = _enrich_model_config_with_variant(
            {},
            {"variant_name": "x", "force_chromakey": 1},
        )
        data = json.loads(out)
        assert data["force_chromakey"] is True
        assert isinstance(data["force_chromakey"], bool)

    def test_force_chromakey_absent_defaut_false(self):
        """force_chromakey absent du job.config → False (pas None)."""
        out = _enrich_model_config_with_variant(
            {},
            {"variant_name": "lineart"},
        )
        data = json.loads(out)
        assert data["force_chromakey"] is False
        assert isinstance(data["force_chromakey"], bool)


# ── Test end-to-end via save_result ───────────────────────────────────────────


def _setup_image_and_job(
    test_conn,
    *,
    image_id: str,
    job_id: str,
    job_config: dict | str,
) -> None:
    """Insère une image en status=generating + un job en status=running."""
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt,
                            file_path, created_at, updated_at)
        VALUES (?, ?, 'generating', 'p', '', '',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [image_id, image_id],
    )
    config_str = job_config if isinstance(job_config, str) else json.dumps(job_config)
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at,
                          entity_type, entity_id, worker_id)
        VALUES (?, 'image_generation', 'running', ?, ?,
                '2026-01-01T00:00:00Z', 'image', ?, 'w1')
        """,
        [job_id, image_id, config_str, image_id],
    )
    test_conn.session.commit()


def _make_png(out_dir, name: str) -> None:
    """Crée un PNG minimal blanc 64x64 dans out_dir."""
    PILImage.new("RGB", (64, 64), (255, 255, 255)).save(out_dir / name)


@pytest.fixture
def worker_with_conn(test_conn, tmp_path, monkeypatch):
    """ImageWorker câblé sur test_conn + OUTPUTS_DIR patché vers tmp_path."""
    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    worker = ImageWorker()
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn
    yield worker, tmp_path
    test_conn.close = original_close


class TestImageWorkerSaveResultVariant:
    def test_worker_stocke_variant_name_pastel_chromakey(
        self, test_conn, worker_with_conn,
    ):
        """job.config avec variant_name=pastel_chromakey → propagé dans
        image_output.model_config."""
        worker, out_dir = worker_with_conn
        job_config = {
            "prompt": "soft pastel children's coloring illustration, a lion",
            "negative_prompt": "photographic, realistic",
            "variant_name": "pastel_chromakey",
            "extract_preset": "floodfill_chromakey_v1",
            "force_chromakey": True,
            "seed": 1234,
        }
        _setup_image_and_job(
            test_conn, image_id="img_pastel", job_id="job_pastel",
            job_config=job_config,
        )
        _make_png(out_dir, "img_pastel_job_pastel.png")

        # Le job passé à save_result reproduit la structure renvoyée par
        # fetch_and_start (config = dict déjà parsé).
        worker.save_result(
            {"job_id": "job_pastel", "config": job_config},
            {
                "entity_id": "img_pastel",
                "rel_path": "outputs/img_pastel_job_pastel.png",
                "prompt": job_config["prompt"],
                "negative_prompt": job_config["negative_prompt"],
                "used_comfy": True,
                "external_ref_id": "prompt-abc",
                "generation_params": {"width": 1024, "height": 1024, "steps": 8},
            },
        )

        row = test_conn.execute(
            "SELECT model_config FROM image_output WHERE id = ?",
            ["out_job_pastel"],
        ).fetchone()
        assert row is not None
        mc = json.loads(row[0])
        assert mc["variant_name"] == "pastel_chromakey"
        assert mc["extract_preset"] == "floodfill_chromakey_v1"
        assert mc["force_chromakey"] is True
        # Les champs generation_params sont préservés.
        assert mc["width"] == 1024
        assert mc["steps"] == 8

    def test_worker_legacy_sans_variant_name(
        self, test_conn, worker_with_conn,
    ):
        """job.config legacy (sans variant_name) → champs à None/None/False
        dans model_config. Pas d'exception."""
        worker, out_dir = worker_with_conn
        job_config = {"prompt": "legacy prompt", "steps": 4}
        _setup_image_and_job(
            test_conn, image_id="img_legacy", job_id="job_legacy",
            job_config=job_config,
        )
        _make_png(out_dir, "img_legacy_job_legacy.png")

        worker.save_result(
            {"job_id": "job_legacy", "config": job_config},
            {
                "entity_id": "img_legacy",
                "rel_path": "outputs/img_legacy_job_legacy.png",
                "prompt": "legacy prompt",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": None,
                "generation_params": {"width": 1024, "height": 1024, "steps": 4},
            },
        )

        row = test_conn.execute(
            "SELECT model_config FROM image_output WHERE id = ?",
            ["out_job_legacy"],
        ).fetchone()
        assert row is not None
        mc = json.loads(row[0])
        assert mc["variant_name"] is None
        assert mc["extract_preset"] is None
        assert mc["force_chromakey"] is False
        assert mc["steps"] == 4

    def test_worker_invalid_json_config(
        self, test_conn, worker_with_conn,
    ):
        """job.config corrompu (str non-JSON) ne fait pas planter save_result."""
        worker, out_dir = worker_with_conn
        _setup_image_and_job(
            test_conn, image_id="img_bad", job_id="job_bad",
            job_config="not valid json {",
        )
        _make_png(out_dir, "img_bad_job_bad.png")

        # Simule un job où config est resté en str corrompu (cas pathologique).
        worker.save_result(
            {"job_id": "job_bad", "config": "not valid json {"},
            {
                "entity_id": "img_bad",
                "rel_path": "outputs/img_bad_job_bad.png",
                "prompt": "fallback",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": None,
                "generation_params": {"width": 64, "height": 64},
            },
        )

        row = test_conn.execute(
            "SELECT model_config FROM image_output WHERE id = ?",
            ["out_job_bad"],
        ).fetchone()
        assert row is not None
        mc = json.loads(row[0])
        # Legacy behavior : pas de crash, champs à None/False.
        assert mc["variant_name"] is None
        assert mc["extract_preset"] is None
        assert mc["force_chromakey"] is False

    def test_worker_job_sans_config_du_tout(
        self, test_conn, worker_with_conn,
    ):
        """job dict ne contenant pas la clé 'config' (test minimal historique)
        ne plante pas et stocke variant_name=None."""
        worker, out_dir = worker_with_conn
        _setup_image_and_job(
            test_conn, image_id="img_noconf", job_id="job_noconf",
            job_config={},
        )
        _make_png(out_dir, "img_noconf_job_noconf.png")

        worker.save_result(
            {"job_id": "job_noconf"},  # pas de clé "config" du tout
            {
                "entity_id": "img_noconf",
                "rel_path": "outputs/img_noconf_job_noconf.png",
                "prompt": "p",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": None,
                "generation_params": {"width": 64, "height": 64},
            },
        )

        row = test_conn.execute(
            "SELECT model_config FROM image_output WHERE id = ?",
            ["out_job_noconf"],
        ).fetchone()
        assert row is not None
        mc = json.loads(row[0])
        assert mc["variant_name"] is None
        assert mc["force_chromakey"] is False
