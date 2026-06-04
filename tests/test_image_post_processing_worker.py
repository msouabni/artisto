"""Tests du worker ``image_post_processing`` (C2.2).

Couvre :
- Le dispatch extract_palette vs vectorizer selon ``extract_preset``.
- L'enrichissement de ``image_output.model_config`` apres succes.
- Les cas d'erreur (PNG inexistant, leaf_id manquant, etc.).
- L'idempotence des reruns.
- L'auto-enqueue depuis ``ImageWorker.save_result``.
- L'inscription dans ``DEFAULT_JOB_TYPES`` (max_concurrent=2).

Les services natifs (``extract_palette``, ``Vectorizer.from_preset``) sont
toujours mockes pour ne pas dependre de cv2/vtracer ni d'un vrai PNG.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

import workers.image_post_processing_worker as pp_mod
import workers.image_worker as image_worker_mod
from workers.image_post_processing_worker import ImagePostProcessingWorker
from workers.image_worker import ImageWorker


# ── Helpers ────────────────────────────────────────────────────────────────


def _seed_image_output(
    test_conn,
    image_output_id: str,
    leaf_id: str | None,
    file_path: str,
    model_config: dict | None,
) -> None:
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, origin_term_id, file_path,
                           created_at, updated_at)
        VALUES (?, ?, 'generated', 'p', ?, '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        [f"img_{image_output_id}", f"img_{image_output_id}", leaf_id],
    )
    test_conn.execute(
        """
        INSERT INTO image_output (id, image_id, file_path, model_config, created_at)
        VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z')
        """,
        [
            image_output_id,
            f"img_{image_output_id}",
            file_path,
            json.dumps(model_config or {}, ensure_ascii=False),
        ],
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id, started_at)
        VALUES (?, 'image_post_processing', 'running', ?, '2026-01-01T00:00:00Z',
                'image_output', ?, '2026-01-01T00:00:00Z')
        """,
        [
            f"job_{image_output_id}",
            json.dumps({}, ensure_ascii=False),
            image_output_id,
        ],
    )
    test_conn.session.commit()


def _make_fake_png(tmp_path: Path, name: str = "fake.png") -> Path:
    """Cree un PNG minimaliste (pas vraiment lu par le worker, juste pour
    passer le test d'existence)."""
    p = tmp_path / name
    Image.new("RGB", (16, 16), (255, 255, 255)).save(p)
    return p


def _bind_worker_to_test_conn(worker, test_conn):
    """Patch worker._conn pour reutiliser la connexion SQLite in-memory du test."""
    original_close = test_conn.close
    test_conn.close = lambda: None
    worker._conn = lambda read_only=False: test_conn
    return original_close


# ── Fake services ──────────────────────────────────────────────────────────


def _install_fake_extract_palette(monkeypatch, calls: list):
    def fake_extract_palette(png_path, params):
        calls.append({"png_path": Path(png_path), "params": params})
        return SimpleNamespace(name="fake")

    def fake_make_params(preset):
        return SimpleNamespace(preset=preset)

    def fake_render_svg(result, mode="full"):
        return f"<svg data-mode='{mode}' data-fake='1'/>"

    monkeypatch.setattr(pp_mod, "extract_palette", fake_extract_palette)
    monkeypatch.setattr(pp_mod, "make_params", fake_make_params)
    monkeypatch.setattr(pp_mod, "render_svg", fake_render_svg)


def _install_fake_vectorizer(monkeypatch, calls: list):
    class FakeVectorizer:
        @classmethod
        def from_preset(cls, preset):
            instance = cls()
            instance.preset = preset
            calls.append({"action": "from_preset", "preset": preset})
            return instance

        def process(self, png_path, out_dir):
            png_path = Path(png_path)
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            svg_path = out_dir / f"{png_path.stem}.svg"
            svg_path.write_text("<svg data-vec='1'/>", encoding="utf-8")
            calls.append(
                {
                    "action": "process",
                    "png_path": png_path,
                    "out_dir": out_dir,
                    "svg_path": svg_path,
                }
            )
            return SimpleNamespace(
                name=png_path.stem,
                svg_path=svg_path,
                kb_in=1.0,
                kb_svg=1.0,
                n_paths=1,
                n_subpaths=1,
                ratio=1.0,
                clean_path=None,
            )

    monkeypatch.setattr(pp_mod, "Vectorizer", FakeVectorizer)


# ── Tests ──────────────────────────────────────────────────────────────────


def test_dispatch_extract_palette_pour_chromakey(test_conn, tmp_path, monkeypatch):
    """variant pastel_chromakey + extract_preset -> extract_palette appele
    + SVG coloriage ecrit."""
    extract_calls: list = []
    vec_calls: list = []
    _install_fake_extract_palette(monkeypatch, extract_calls)
    _install_fake_vectorizer(monkeypatch, vec_calls)
    monkeypatch.setattr(pp_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp_mod, "GENERATED_DIR", tmp_path / "data" / "generated")

    # PNG existant resolu via data/<rel>
    png_dir = tmp_path / "data" / "outputs"
    png_dir.mkdir(parents=True)
    _make_fake_png(png_dir, "img_pp1_job_pp1.png")

    _seed_image_output(
        test_conn,
        "out_pp1",
        leaf_id="lion_in_savanna",
        file_path="outputs/img_pp1_job_pp1.png",
        model_config={
            "variant_name": "pastel_chromakey",
            "extract_preset": "floodfill_chromakey_v1",
        },
    )

    worker = ImagePostProcessingWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        result = worker.process(
            {
                "job_id": "job_out_pp1",
                "entity_id": "out_pp1",
                "config": {},
            }
        )
    finally:
        test_conn.close = original_close

    assert len(extract_calls) == 1
    assert extract_calls[0]["params"].preset == "floodfill_chromakey_v1"
    # vectorizer aussi appele (toujours)
    assert any(c["action"] == "process" for c in vec_calls)
    # Fichier coloriage ecrit
    coloring_svg = (
        tmp_path / "data" / "generated" / "lion_in_savanna__pastel_chromakey_coloriage.svg"
    )
    assert coloring_svg.is_file()
    assert result["coloring_svg_path"] is not None
    assert result["vector_svg_path"] is not None


def test_dispatch_vectorizer_pour_lineart(test_conn, tmp_path, monkeypatch):
    """variant=lineart + extract_preset=None -> seul Vectorizer appele,
    PAS d'extract_palette."""
    extract_calls: list = []
    vec_calls: list = []
    _install_fake_extract_palette(monkeypatch, extract_calls)
    _install_fake_vectorizer(monkeypatch, vec_calls)
    monkeypatch.setattr(pp_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp_mod, "GENERATED_DIR", tmp_path / "data" / "generated")

    png_dir = tmp_path / "data" / "outputs"
    png_dir.mkdir(parents=True)
    _make_fake_png(png_dir, "img_pp2_job_pp2.png")

    _seed_image_output(
        test_conn,
        "out_pp2",
        leaf_id="happy_cat",
        file_path="outputs/img_pp2_job_pp2.png",
        model_config={
            "variant_name": "lineart",
            "extract_preset": None,
        },
    )

    worker = ImagePostProcessingWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        result = worker.process(
            {
                "job_id": "job_out_pp2",
                "entity_id": "out_pp2",
                "config": {},
            }
        )
    finally:
        test_conn.close = original_close

    assert extract_calls == []
    assert any(c["action"] == "process" for c in vec_calls)
    # Pas de coloring SVG
    coloring_svg = tmp_path / "data" / "generated" / "happy_cat__lineart_coloriage.svg"
    assert not coloring_svg.is_file()
    vector_svg = tmp_path / "data" / "generated" / "happy_cat__lineart.svg"
    assert vector_svg.is_file()
    assert result["coloring_svg_path"] is None
    assert result["vector_svg_path"] is not None


def test_update_model_config_apres_succes(test_conn, tmp_path, monkeypatch):
    """save_result enrichit image_output.model_config avec vector_svg_path
    + coloring_svg_path, en preservant les champs existants."""
    extract_calls: list = []
    vec_calls: list = []
    _install_fake_extract_palette(monkeypatch, extract_calls)
    _install_fake_vectorizer(monkeypatch, vec_calls)
    monkeypatch.setattr(pp_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp_mod, "GENERATED_DIR", tmp_path / "data" / "generated")

    png_dir = tmp_path / "data" / "outputs"
    png_dir.mkdir(parents=True)
    _make_fake_png(png_dir, "img_pp3_job_pp3.png")

    _seed_image_output(
        test_conn,
        "out_pp3",
        leaf_id="hammer",
        file_path="outputs/img_pp3_job_pp3.png",
        model_config={
            "variant_name": "pastel_chromakey",
            "extract_preset": "floodfill_chromakey_v1",
            "force_chromakey": True,
            "seed": 12345,
        },
    )

    worker = ImagePostProcessingWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        result = worker.process(
            {
                "job_id": "job_out_pp3",
                "entity_id": "out_pp3",
                "config": {},
            }
        )
        worker.save_result(
            {
                "job_id": "job_out_pp3",
                "started_at": "2026-01-01T00:00:00Z",
            },
            result,
        )
    finally:
        test_conn.close = original_close

    row = test_conn.execute(
        "SELECT model_config FROM image_output WHERE id = ?",
        ["out_pp3"],
    ).fetchone()
    mc = json.loads(row[0])
    assert mc["vector_svg_path"].endswith("hammer__pastel_chromakey.svg")
    assert mc["coloring_svg_path"].endswith(
        "hammer__pastel_chromakey_coloriage.svg"
    )
    # Champs existants preserves
    assert mc["variant_name"] == "pastel_chromakey"
    assert mc["force_chromakey"] is True
    assert mc["seed"] == 12345
    # Job marque completed
    job_row = test_conn.execute(
        "SELECT status, progress FROM job WHERE id = ?",
        ["job_out_pp3"],
    ).fetchone()
    assert job_row[0] == "completed"
    assert job_row[1] == 100


def test_job_failed_si_png_inexistant(test_conn, tmp_path, monkeypatch):
    """file_path bidon -> ValueError clair."""
    extract_calls: list = []
    vec_calls: list = []
    _install_fake_extract_palette(monkeypatch, extract_calls)
    _install_fake_vectorizer(monkeypatch, vec_calls)
    monkeypatch.setattr(pp_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp_mod, "GENERATED_DIR", tmp_path / "data" / "generated")

    _seed_image_output(
        test_conn,
        "out_missing",
        leaf_id="happy_cat",
        file_path="outputs/does_not_exist.png",
        model_config={
            "variant_name": "lineart",
            "extract_preset": None,
        },
    )

    worker = ImagePostProcessingWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        with pytest.raises(ValueError, match="PNG introuvable"):
            worker.process(
                {
                    "job_id": "job_out_missing",
                    "entity_id": "out_missing",
                    "config": {},
                }
            )
    finally:
        test_conn.close = original_close


def test_job_failed_si_origin_term_id_none(test_conn, tmp_path, monkeypatch):
    """image.origin_term_id NULL -> ValueError."""
    extract_calls: list = []
    vec_calls: list = []
    _install_fake_extract_palette(monkeypatch, extract_calls)
    _install_fake_vectorizer(monkeypatch, vec_calls)
    monkeypatch.setattr(pp_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp_mod, "GENERATED_DIR", tmp_path / "data" / "generated")

    png_dir = tmp_path / "data" / "outputs"
    png_dir.mkdir(parents=True)
    _make_fake_png(png_dir, "img_pp_no_leaf_job_pp_no_leaf.png")

    _seed_image_output(
        test_conn,
        "out_no_leaf",
        leaf_id=None,
        file_path="outputs/img_pp_no_leaf_job_pp_no_leaf.png",
        model_config={
            "variant_name": "lineart",
            "extract_preset": None,
        },
    )

    worker = ImagePostProcessingWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        with pytest.raises(ValueError, match="origin_term_id"):
            worker.process(
                {
                    "job_id": "job_out_no_leaf",
                    "entity_id": "out_no_leaf",
                    "config": {},
                }
            )
    finally:
        test_conn.close = original_close


def test_job_failed_si_variant_name_absent(test_conn, tmp_path, monkeypatch):
    """variant_name absent du job.config ET du model_config -> ValueError."""
    extract_calls: list = []
    vec_calls: list = []
    _install_fake_extract_palette(monkeypatch, extract_calls)
    _install_fake_vectorizer(monkeypatch, vec_calls)
    monkeypatch.setattr(pp_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp_mod, "GENERATED_DIR", tmp_path / "data" / "generated")

    png_dir = tmp_path / "data" / "outputs"
    png_dir.mkdir(parents=True)
    _make_fake_png(png_dir, "img_pp_no_variant_job_pp_no_variant.png")

    _seed_image_output(
        test_conn,
        "out_no_variant",
        leaf_id="happy_cat",
        file_path="outputs/img_pp_no_variant_job_pp_no_variant.png",
        model_config={},  # pas de variant_name
    )

    worker = ImagePostProcessingWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        with pytest.raises(ValueError, match="variant_name"):
            worker.process(
                {
                    "job_id": "job_out_no_variant",
                    "entity_id": "out_no_variant",
                    "config": {},
                }
            )
    finally:
        test_conn.close = original_close


def test_idempotence_rejouable(test_conn, tmp_path, monkeypatch):
    """Run 2x le meme job -> pas d'erreur, fichiers ecrases."""
    extract_calls: list = []
    vec_calls: list = []
    _install_fake_extract_palette(monkeypatch, extract_calls)
    _install_fake_vectorizer(monkeypatch, vec_calls)
    monkeypatch.setattr(pp_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp_mod, "GENERATED_DIR", tmp_path / "data" / "generated")

    png_dir = tmp_path / "data" / "outputs"
    png_dir.mkdir(parents=True)
    _make_fake_png(png_dir, "img_pp_idem_job_pp_idem.png")

    _seed_image_output(
        test_conn,
        "out_idem",
        leaf_id="hammer",
        file_path="outputs/img_pp_idem_job_pp_idem.png",
        model_config={
            "variant_name": "pastel_chromakey",
            "extract_preset": "floodfill_chromakey_v1",
        },
    )

    worker = ImagePostProcessingWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        r1 = worker.process(
            {"job_id": "job_out_idem", "entity_id": "out_idem", "config": {}}
        )
        worker.save_result(
            {"job_id": "job_out_idem", "started_at": "2026-01-01T00:00:00Z"},
            r1,
        )
        # Rerun
        r2 = worker.process(
            {"job_id": "job_out_idem", "entity_id": "out_idem", "config": {}}
        )
        worker.save_result(
            {"job_id": "job_out_idem", "started_at": "2026-01-01T00:00:00Z"},
            r2,
        )
    finally:
        test_conn.close = original_close

    # Les chemins de sortie restent les memes
    assert r1["vector_svg_path"] == r2["vector_svg_path"]
    assert r1["coloring_svg_path"] == r2["coloring_svg_path"]


def test_auto_enqueue_apres_image_generation(test_conn, tmp_path, monkeypatch):
    """ImageWorker.save_result avec variant_name dans le job.config
    cree 1 job image_post_processing pending."""
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_aep', 'img_aep', 'generating', 'p', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    job_config = json.dumps(
        {
            "variant_name": "pastel_chromakey",
            "extract_preset": "floodfill_chromakey_v1",
            "force_chromakey": True,
        }
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, worker_id)
        VALUES ('job_aep', 'image_generation', 'running', 'img_aep', ?,
                '2026-01-01T00:00:00Z', 'image', 'img_aep', 'w1')
        """,
        [job_config],
    )
    test_conn.session.commit()

    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    png = tmp_path / "img_aep_job_aep.png"
    Image.new("RGB", (32, 32), (255, 255, 255)).save(png)

    worker = ImageWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        worker.save_result(
            {"job_id": "job_aep", "config": json.loads(job_config)},
            {
                "entity_id": "img_aep",
                "rel_path": "outputs/img_aep_job_aep.png",
                "prompt": "p",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": "ext-1",
                "generation_params": {"width": 32, "height": 32, "steps": 4},
            },
        )
    finally:
        test_conn.close = original_close

    rows = test_conn.execute(
        """
        SELECT id, type, status, entity_type, entity_id, config
        FROM job
        WHERE type = ? AND entity_id = ?
        """,
        ["image_post_processing", "out_job_aep"],
    ).fetchall()
    assert len(rows) == 1
    pp_job = rows[0]
    assert pp_job[2] == "pending"
    assert pp_job[3] == "image_output"
    cfg = json.loads(pp_job[5])
    assert cfg["variant_name"] == "pastel_chromakey"
    assert cfg["extract_preset"] == "floodfill_chromakey_v1"


def test_pas_dauto_enqueue_si_legacy(test_conn, tmp_path, monkeypatch):
    """ImageWorker.save_result avec job.config legacy (pas de variant_name)
    -> aucun job image_post_processing cree."""
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_legacy', 'img_legacy', 'generating', 'p', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id, worker_id)
        VALUES ('job_legacy', 'image_generation', 'running', 'img_legacy', '{}',
                '2026-01-01T00:00:00Z', 'image', 'img_legacy', 'w1')
        """
    )
    test_conn.session.commit()

    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    png = tmp_path / "img_legacy_job_legacy.png"
    Image.new("RGB", (32, 32), (255, 255, 255)).save(png)

    worker = ImageWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        worker.save_result(
            {"job_id": "job_legacy"},
            {
                "entity_id": "img_legacy",
                "rel_path": "outputs/img_legacy_job_legacy.png",
                "prompt": "p",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": None,
                "generation_params": {"width": 32, "height": 32},
            },
        )
    finally:
        test_conn.close = original_close

    rows = test_conn.execute(
        "SELECT id FROM job WHERE type = ? AND entity_id = ?",
        ["image_post_processing", "out_job_legacy"],
    ).fetchall()
    assert rows == []


def test_auto_enqueue_idempotent(test_conn, tmp_path, monkeypatch):
    """Si un job image_post_processing pending existe deja, on ne le double pas."""
    test_conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt, file_path, created_at, updated_at)
        VALUES ('img_pp_idemp', 'img_pp_idemp', 'generating', 'p', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    job_config = json.dumps(
        {
            "variant_name": "pastel_chromakey",
            "extract_preset": "floodfill_chromakey_v1",
        }
    )
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, image_id, config, created_at, entity_type, entity_id)
        VALUES ('job_pp_idemp', 'image_generation', 'running', 'img_pp_idemp', ?,
                '2026-01-01T00:00:00Z', 'image', 'img_pp_idemp')
        """,
        [job_config],
    )
    # Pre-cree un job pp pending pour out_job_pp_idemp
    test_conn.execute(
        """
        INSERT INTO job (id, type, status, config, created_at, entity_type, entity_id)
        VALUES ('pp_pre', 'image_post_processing', 'pending', '{}',
                '2026-01-01T00:00:00Z', 'image_output', 'out_job_pp_idemp')
        """
    )
    test_conn.session.commit()

    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    png = tmp_path / "img_pp_idemp_job_pp_idemp.png"
    Image.new("RGB", (32, 32), (255, 255, 255)).save(png)

    worker = ImageWorker()
    original_close = _bind_worker_to_test_conn(worker, test_conn)
    try:
        worker.save_result(
            {"job_id": "job_pp_idemp", "config": json.loads(job_config)},
            {
                "entity_id": "img_pp_idemp",
                "rel_path": "outputs/img_pp_idemp_job_pp_idemp.png",
                "prompt": "p",
                "negative_prompt": "",
                "used_comfy": True,
                "external_ref_id": None,
                "generation_params": {"width": 32, "height": 32},
            },
        )
    finally:
        test_conn.close = original_close

    rows = test_conn.execute(
        "SELECT id FROM job WHERE type = ? AND entity_id = ?",
        ["image_post_processing", "out_job_pp_idemp"],
    ).fetchall()
    assert len(rows) == 1


def test_image_post_processing_in_default_job_types():
    """Inscription dans DEFAULT_JOB_TYPES garantit le seed automatique avec
    ``max_concurrent=2``."""
    from api.db import DEFAULT_JOB_TYPES

    types = {t["type"] for t in DEFAULT_JOB_TYPES}
    assert "image_post_processing" in types
    spec = next(
        t for t in DEFAULT_JOB_TYPES if t["type"] == "image_post_processing"
    )
    assert spec["max_concurrent"] == 2
    assert spec["category"] == "image"
    assert spec["enabled"] is True
