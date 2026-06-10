"""Tests Phase 4 — export du SVG bicouche décoloriage vers R2 (ADD-ONLY).

Couvre (cf. brief Phase 4) :
  - Résolution du ``coloring_svg`` par leaf via la convention ``coloring_storage``
    (``data/generated/{leaf_id}__{variant}_coloriage.svg``).
  - Planification de l'upload à la bonne clé R2 ``coloriages/svg/{slug}.svg``
    (Content-Type ``image/svg+xml``), vérifiable en mode ``--mock`` (pas
    d'appel R2 réel : écriture dans ``r2_simulated/``).
  - Idempotence ``master-md5`` : 2e passe sur SVG inchangé → skip.
  - Leaf sans ``coloring_svg`` → ``missing`` / skip propre, pas d'erreur.
  - ``--mock`` n'effectue AUCUN appel réseau R2 (client mocké interdit).

Portable SQLite : ``tests/conftest.py`` force ``DATABASE_URL`` SQLite in-memory.
Aucun ComfyUI, aucune queue, aucun réseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import alwanbooks_pipeline as mod  # noqa: E402


# leaf_id valide (coloring_storage regex : minuscules + underscores) +
# variante connue du registre.
LEAF_ID = "garden_snail"
VARIANT = "pastel_chromakey"
SLUG = "garden-snail"

SVG_CONTENT = b'<svg xmlns="http://www.w3.org/2000/svg"><g id="fills"/></svg>'


def _make_coloring_svg(base: Path, content: bytes = SVG_CONTENT) -> Path:
    """Crée le PNG pivot + le SVG coloriage attendus par coloring_storage."""
    from services.coloring_storage import get_storage_paths

    base.mkdir(parents=True, exist_ok=True)
    paths = get_storage_paths(LEAF_ID, VARIANT, base_dir=base)
    paths.raw_png.write_bytes(b"PNG")          # pivot requis par list_existing
    paths.coloring_svg.write_bytes(content)
    return paths.coloring_svg


# ── Résolution du coloring_svg par leaf ─────────────────────────────────────


def test_resolve_coloring_svg_present(tmp_path):
    svg = _make_coloring_svg(tmp_path)
    resolved = mod._resolve_coloring_svg(LEAF_ID, base_dir=tmp_path)
    assert resolved == svg


def test_resolve_coloring_svg_absent(tmp_path):
    # PNG présent mais pas de _coloriage.svg → None.
    from services.coloring_storage import get_storage_paths

    tmp_path.mkdir(parents=True, exist_ok=True)
    get_storage_paths(LEAF_ID, VARIANT, base_dir=tmp_path).raw_png.write_bytes(b"PNG")
    assert mod._resolve_coloring_svg(LEAF_ID, base_dir=tmp_path) is None


def test_resolve_coloring_svg_dossier_vide(tmp_path):
    assert mod._resolve_coloring_svg(LEAF_ID, base_dir=tmp_path / "nope") is None


def test_resolve_coloring_svg_leaf_invalide_ne_leve_pas(tmp_path):
    # leaf_id non conforme → None (pas d'exception), publication non cassée.
    assert mod._resolve_coloring_svg("Bad/Leaf..", base_dir=tmp_path) is None


# ── Clé R2 + Content-Type ───────────────────────────────────────────────────


def test_r2_svg_key_convention():
    assert mod.R2_SVG_PATH.format(slug=SLUG) == "coloriages/svg/garden-snail.svg"
    assert mod.R2_SVG_CONTENT_TYPE == "image/svg+xml"


# ── Upload mock : bonne clé, écriture r2_simulated, pas de réseau ───────────


def test_upload_svg_mock_writes_to_simulated(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "MOCK_R2_DIR", tmp_path / "r2_simulated")
    up, skip = mod._upload_svg_mock(SLUG, SVG_CONTENT)
    assert up == "coloriages/svg/garden-snail.svg"
    assert skip is None
    out = tmp_path / "r2_simulated" / "coloriages" / "svg" / "garden-snail.svg"
    assert out.read_bytes() == SVG_CONTENT


# ── Upload réel mocké : ADD-ONLY + idempotence master-md5 ───────────────────


class _FakeR2:
    """R2Client factice : pas de réseau, garde l'état des objets en mémoire."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.put_calls: list[str] = []

    def head(self, key):
        return self.objects.get(key)

    def put(self, key, body, content_type, metadata=None):
        self.put_calls.append(key)
        etag = mod._md5(body)
        self.objects[key] = {
            "ETag": f'"{etag}"',
            "Metadata": dict(metadata or {}),
            "ContentType": content_type,
            "_body": body,
        }
        return etag

    def delete(self, key):
        self.objects.pop(key, None)


def test_upload_svg_real_first_pass_uploads():
    r2 = _FakeR2()
    up, skip = mod._upload_svg_real(r2, SLUG, SVG_CONTENT)
    assert up == "coloriages/svg/garden-snail.svg"
    assert skip is None
    key = "coloriages/svg/garden-snail.svg"
    assert r2.put_calls == [key]
    # Content-Type + master-md5 posés.
    obj = r2.objects[key]
    assert obj["ContentType"] == "image/svg+xml"
    assert obj["Metadata"]["master-md5"] == mod._md5(SVG_CONTENT)


def test_upload_svg_real_idempotent_second_pass_skips():
    r2 = _FakeR2()
    mod._upload_svg_real(r2, SLUG, SVG_CONTENT)        # 1re passe : upload
    up, skip = mod._upload_svg_real(r2, SLUG, SVG_CONTENT)  # 2e : skip
    assert up is None
    assert skip == "coloriages/svg/garden-snail.svg"
    # Aucun second PUT (idempotence master-md5).
    assert r2.put_calls == ["coloriages/svg/garden-snail.svg"]


def test_upload_svg_real_changed_content_reuploads():
    r2 = _FakeR2()
    mod._upload_svg_real(r2, SLUG, SVG_CONTENT)
    up, skip = mod._upload_svg_real(r2, SLUG, SVG_CONTENT + b"<!--changed-->")
    assert up == "coloriages/svg/garden-snail.svg"
    assert skip is None
    assert len(r2.put_calls) == 2


def test_upload_svg_real_legacy_etag_fallback():
    """Objet existant sans master-md5 (legacy) → fallback ETag == md5(svg)."""
    r2 = _FakeR2()
    key = "coloriages/svg/garden-snail.svg"
    r2.objects[key] = {
        "ETag": f'"{mod._md5(SVG_CONTENT)}"',
        "Metadata": {},  # legacy : pas de master-md5
    }
    up, skip = mod._upload_svg_real(r2, SLUG, SVG_CONTENT)
    assert up is None
    assert skip == key
    assert r2.put_calls == []


# ── Intégration run_pipeline en --mock ──────────────────────────────────────


@pytest.fixture
def _pipeline_env(tmp_path, monkeypatch):
    """Stub minimal de l'environnement run_pipeline : 1 leaf, master factice."""
    generated = tmp_path / "generated"
    monkeypatch.setattr(mod, "MOCK_R2_DIR", tmp_path / "r2_simulated")

    # Manifest 1 leaf.
    manifest = {
        "leaves": [
            {
                "image_id": "benchmark:fake/garden_snail.png",
                "leaf_id": LEAF_ID,
                "r2_slug": SLUG,
                "post_slugs": {},  # pas de posts → focus SVG/variantes
                "image_id_": "x",
            }
        ]
    }
    import json as _json
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(_json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(mod, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(mod, "POSTS_DIR", tmp_path / "posts")

    # Master PNG factice + conversion variantes stubée (pas de Pillow réel).
    fake_master = tmp_path / "master.png"
    fake_master.write_bytes(b"PNG-MASTER")
    monkeypatch.setattr(
        mod.export_mep_v0, "_resolve_master_png", lambda tid: fake_master
    )
    monkeypatch.setattr(
        mod, "convert_master_to_variants",
        lambda m: {"master": b"M", "web": b"W", "thumb": b"T", "pdf": b"P"},
    )

    # _resolve_coloring_svg pointe sur notre base_dir de test (sinon il scanne
    # data/generated/ réel). On wrappe pour injecter base_dir.
    orig_resolve = mod._resolve_coloring_svg
    monkeypatch.setattr(
        mod, "_resolve_coloring_svg",
        lambda leaf_id, base_dir=None: orig_resolve(leaf_id, base_dir=generated),
    )
    # Neutralise la copie d'artefacts (hors périmètre du test).
    monkeypatch.setattr(
        mod, "_copy_variant_artefacts",
        lambda *a, **k: {"copied": [], "skipped": []},
    )
    return tmp_path, generated


def test_run_pipeline_mock_svg_present_uploaded(_pipeline_env):
    tmp_path, generated = _pipeline_env
    _make_coloring_svg(generated)

    summary = mod.run_pipeline(
        mock=True, no_git_push=True, leaf_id=None, limit=None,
        rimalab_root=tmp_path / "site", sync_themes_flag=False,
    )
    assert summary.svg_uploaded == 1
    assert summary.svg_missing == 0
    # SVG écrit dans r2_simulated à la bonne clé, en --mock (aucun R2 réel).
    out = tmp_path / "r2_simulated" / "coloriages" / "svg" / f"{SLUG}.svg"
    assert out.read_bytes() == SVG_CONTENT
    leaf = summary.leaves[0]
    assert leaf.svg_uploaded == "coloriages/svg/garden-snail.svg"


def test_run_pipeline_mock_svg_missing_skips_clean(_pipeline_env):
    tmp_path, generated = _pipeline_env
    generated.mkdir(parents=True, exist_ok=True)  # vide : pas de SVG

    summary = mod.run_pipeline(
        mock=True, no_git_push=True, leaf_id=None, limit=None,
        rimalab_root=tmp_path / "site", sync_themes_flag=False,
    )
    assert summary.svg_uploaded == 0
    assert summary.svg_missing == 1
    # La leaf reste OK malgré le SVG manquant (publication non cassée).
    assert summary.leaves_ok == 1
    assert summary.leaves[0].svg_missing is True


def test_run_pipeline_mock_no_real_r2_client(_pipeline_env, monkeypatch):
    """--mock : aucun client R2 réel ne doit être construit."""
    tmp_path, generated = _pipeline_env
    _make_coloring_svg(generated)

    def _boom():
        raise AssertionError("R2 client must NOT be built in --mock mode")

    monkeypatch.setattr(mod, "_r2_client_from_env", _boom)
    summary = mod.run_pipeline(
        mock=True, no_git_push=True, leaf_id=None, limit=None,
        rimalab_root=tmp_path / "site", sync_themes_flag=False,
    )
    assert summary.svg_uploaded == 1
