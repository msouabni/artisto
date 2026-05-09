"""Tests pour ``src/api/routes/benchmark.py``.

Couvre :
- Helpers de fusion d'index (3 schémas : subjects / results-by-leaf-id / results-legacy)
- Filtre exclusion du fichier métriques canonique ``<dir>/<dir>.json``
- Fallback : aucun fichier d'index → None
- Endpoints v2 : annotate (validation score 1-6 + vocabulaires fermés),
  dirs (autocomplete), custom-tags (union)
- Lecture rétro-compat des annotations v1 par ``GET /api/benchmark/images``
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api.routes.benchmark as bm
from api.main import app
from api.routes.benchmark import (  # noqa: E402
    IMAGE_AXIS,
    IMAGE_TAGS_VOCAB,
    PROMPT_AXIS,
    PROMPT_TAGS_VOCAB,
    _find_prompt_index,
    _resolve_prompt_meta,
    _result_entry_to_subject,
)


# ───────────────── Helpers ─────────────────
def _write_json(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ───────────────── _result_entry_to_subject ─────────────────
def test_result_entry_with_filename_field():
    """Une entrée results avec un champ 'filename' interne est convertie."""
    entry = {
        "leaf_id": "lion",
        "leaf_name_en": "Lion",
        "filename": "lion_1024x1024_euler8s.png",
        "positive": "A lion in savanna",
        "negative": "no colors",
        "workflow_class": "Solo animal",
        "confidence": "Haute",
        "pitfalls": ["acacia tree visible"],
    }
    out = _result_entry_to_subject("lion", entry)
    assert out is not None
    assert out["filename"] == "lion_1024x1024_euler8s.png"
    assert out["name_en"] == "Lion"
    assert out["positive_prompt"] == "A lion in savanna"
    assert out["negative_prompt"] == "no colors"
    assert out["workflow_class"] == "Solo animal"
    assert out["confidence"] == "Haute"
    assert out["pitfalls"] == ["acacia tree visible"]


def test_result_entry_keyed_by_filename_legacy():
    """Schéma legacy : la clé EST le filename, pas de 'filename' interne."""
    entry = {"leaf_id": "tiger", "positive": "A tiger"}
    out = _result_entry_to_subject("tiger_1024x1024_euler8s.png", entry)
    assert out is not None
    assert out["filename"] == "tiger_1024x1024_euler8s.png"
    assert out["positive_prompt"] == "A tiger"


def test_result_entry_no_filename_no_png_key_returns_none():
    """Sans filename inline et sans clé .png, rien à matcher."""
    entry = {"leaf_id": "ghost", "positive": "..."}
    assert _result_entry_to_subject("ghost", entry) is None


def test_result_entry_falls_back_to_alternative_field_names():
    """Champs alternatifs name_en/positive_prompt acceptés."""
    entry = {
        "filename": "x.png",
        "name_en": "Alt Name",
        "positive_prompt": "alt prompt",
        "negative_prompt": "alt neg",
    }
    out = _result_entry_to_subject("x", entry)
    assert out is not None
    assert out["name_en"] == "Alt Name"
    assert out["positive_prompt"] == "alt prompt"
    assert out["negative_prompt"] == "alt neg"


# ───────────────── Schéma subjects (index-humans style) ─────────────────
def test_find_prompt_index_subjects_schema(tmp_path: Path):
    """Un fichier *-index.json avec clé 'subjects' renvoie l'index fusionné."""
    _write_json(tmp_path / "index-humans.json", {
        "subjects": [
            {
                "filename": "lion_1024x1024_euler8s.png",
                "name_en": "Lion",
                "positive_prompt": "A lion",
                "tier": "Solo animal",
            },
            {
                "filename": "elephant_1024x1024_euler8s.png",
                "name_en": "Elephant",
                "positive_prompt": "An elephant",
            },
        ]
    })
    idx = _find_prompt_index(tmp_path)
    assert idx is not None
    assert len(idx["subjects"]) == 2
    titles = {s["name_en"] for s in idx["subjects"]}
    assert titles == {"Lion", "Elephant"}

    # Resolver doit trouver la lion par exact filename
    meta = _resolve_prompt_meta("lion_1024x1024_euler8s.png", idx)
    assert meta["title"] == "Lion"
    assert meta["prompt"] == "A lion"
    assert meta["tier"] == "Solo animal"


# ───────────────── Schéma results (index-nature style) ─────────────────
def test_find_prompt_index_results_keyed_by_leaf_id(tmp_path: Path):
    """Un *-index.json avec ``results: {leaf_id: {filename, ...}}`` est converti
    en entrées subjects exploitables par le resolver."""
    _write_json(tmp_path / "index-nature.json", {
        "poc": "scale-benchmark-nature",
        "results": {
            "african_elephant": {
                "leaf_id": "african_elephant",
                "leaf_name_en": "African Elephant",
                "filename": "african_elephant_1024x1024_euler8s.png",
                "positive": "An African elephant in savanna",
                "negative": "no colors",
                "workflow_class": "Solo animal",
            },
            "blue_whale": {
                "leaf_id": "blue_whale",
                "leaf_name_en": "Blue Whale",
                "filename": "blue_whale_1024x1024_euler8s.png",
                "positive": "A blue whale",
                "workflow_class": "Solo fish",
            },
        }
    })
    idx = _find_prompt_index(tmp_path)
    assert idx is not None
    assert len(idx["subjects"]) == 2

    # Resolver via filename exact
    meta = _resolve_prompt_meta("african_elephant_1024x1024_euler8s.png", idx)
    assert meta["title"] == "African Elephant"
    assert meta["prompt"] == "An African elephant in savanna"
    assert meta["negative"] == "no colors"
    assert meta["workflow_class"] == "Solo animal"

    meta2 = _resolve_prompt_meta("blue_whale_1024x1024_euler8s.png", idx)
    assert meta2["title"] == "Blue Whale"
    assert meta2["workflow_class"] == "Solo fish"


# ───────────────── Multi-index fusion ─────────────────
def test_find_prompt_index_merges_multiple_index_files(tmp_path: Path):
    """3 fichiers *-index.json (subjects + 2× results) fusionnés en un index."""
    # File 1 : subjects schema (humans)
    _write_json(tmp_path / "index-humans.json", {
        "subjects": [{
            "filename": "firefighter_848x1264_euler8s.png",
            "name_en": "Firefighter",
            "positive_prompt": "A firefighter with hose",
            "workflow_class": "Solo humain pose active",
        }],
    })
    # File 2 : results keyed by leaf_id (nature)
    _write_json(tmp_path / "index-nature.json", {
        "results": {
            "lion_in_savanna": {
                "filename": "lion_in_savanna_1024x1024_euler8s.png",
                "leaf_name_en": "Lion in Savanna",
                "positive": "A lion in savanna",
                "workflow_class": "Solo animal",
            },
        },
    })
    # File 3 : results keyed by leaf_id (objects)
    _write_json(tmp_path / "index-objects.json", {
        "results": {
            "air_fryer": {
                "filename": "air_fryer_1024x1024_euler8s.png",
                "leaf_name_en": "Air Fryer",
                "positive": "An air fryer",
                "workflow_class": "Solo objet",
            },
        },
    })

    idx = _find_prompt_index(tmp_path)
    assert idx is not None
    # Tous les sujets fusionnés (1 + 1 + 1 = 3)
    assert len(idx["subjects"]) == 3
    titles = {s["name_en"] for s in idx["subjects"]}
    assert titles == {"Firefighter", "Lion in Savanna", "Air Fryer"}

    # Le resolver retrouve chacun par son filename exact
    for fname, expected_title, expected_class in [
        ("firefighter_848x1264_euler8s.png", "Firefighter", "Solo humain pose active"),
        ("lion_in_savanna_1024x1024_euler8s.png", "Lion in Savanna", "Solo animal"),
        ("air_fryer_1024x1024_euler8s.png", "Air Fryer", "Solo objet"),
    ]:
        meta = _resolve_prompt_meta(fname, idx)
        assert meta["title"] == expected_title, f"title mismatch for {fname}"
        assert meta["workflow_class"] == expected_class, f"class mismatch for {fname}"


def test_find_prompt_index_excludes_metrics_file(tmp_path: Path):
    """Le fichier ``<dir>/<dir>.json`` (métriques canoniques) est ignoré pour
    éviter la double-lecture (il est consommé par ``_read_index``)."""
    dir_name = tmp_path.name  # le nom du tmp_path est utilisé comme métrique
    # Fichier métriques canonique — doit être ignoré par _find_prompt_index
    _write_json(tmp_path / f"{dir_name}.json", {
        "results": {
            "should_not_appear": {
                "filename": "should_not_appear.png",
                "leaf_name_en": "Should Not Appear",
                "positive": "metrics content",
            },
        },
    })
    # Fichier index normal — doit être lu
    _write_json(tmp_path / "index-real.json", {
        "subjects": [{
            "filename": "real.png", "name_en": "Real",
            "positive_prompt": "real content",
        }],
    })
    idx = _find_prompt_index(tmp_path)
    assert idx is not None
    assert len(idx["subjects"]) == 1
    assert idx["subjects"][0]["name_en"] == "Real"


def test_find_prompt_index_returns_none_when_no_index(tmp_path: Path):
    """Aucun fichier d'index → None."""
    # Créer un fichier non-pertinent
    _write_json(tmp_path / "random.json", {"foo": "bar"})
    assert _find_prompt_index(tmp_path) is None


def test_find_prompt_index_handles_corrupt_files(tmp_path: Path):
    """Un fichier JSON corrompu est ignoré, les autres sont quand même fusionnés."""
    (tmp_path / "index-broken.json").write_text("{not valid json", encoding="utf-8")
    _write_json(tmp_path / "index-good.json", {
        "subjects": [{"filename": "ok.png", "name_en": "OK", "positive_prompt": "p"}],
    })
    idx = _find_prompt_index(tmp_path)
    assert idx is not None
    assert len(idx["subjects"]) == 1
    assert idx["subjects"][0]["name_en"] == "OK"


def test_find_prompt_index_first_file_wins_on_subject_filename_conflict(tmp_path: Path):
    """Si 2 index ont une entrée pour le même filename, le resolver prend la
    1re trouvée par ordre d'itération (alphabétique sur le nom de fichier)."""
    _write_json(tmp_path / "index-a.json", {
        "subjects": [{"filename": "shared.png", "name_en": "FromA", "positive_prompt": "from a"}],
    })
    _write_json(tmp_path / "index-b.json", {
        "subjects": [{"filename": "shared.png", "name_en": "FromB", "positive_prompt": "from b"}],
    })
    idx = _find_prompt_index(tmp_path)
    assert idx is not None
    # Les 2 sujets sont dans la liste fusionnée mais le resolver prend le 1er match
    assert len(idx["subjects"]) == 2
    meta = _resolve_prompt_meta("shared.png", idx)
    assert meta["title"] == "FromA"


# ───────────────── v2 endpoints (annotate / dirs / custom-tags) ─────────────────
@pytest.fixture
def reports_root(tmp_path, monkeypatch):
    """Patch ``REPORTS_DIR`` pour pointer vers un tmp_path → endpoints isolés.

    On crée un dossier ``poc-test`` avec une image factice, ce qui satisfait
    ``_safe_dir`` (regex + existence) et permet d'exercer ``annotate``.
    """
    monkeypatch.setattr(bm, "REPORTS_DIR", tmp_path)
    sub = tmp_path / "poc-test"
    sub.mkdir()
    # PNG factice (1 octet, le contenu n'est pas validé par les routes)
    (sub / "lion_1024x1024_euler8s.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def _client():
    return TestClient(app)


def test_annotate_v2_payload_ok(reports_root):
    client = _client()
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": 4,
        "score_legacy": 7,
        "image_tags": ["image_compo_bonne", "image_anatomie_pb"],
        "prompt_tags": ["prompt_complexe"],
        "custom_tags": ["sujet_iconique", "ramadan_set"],
        "flags": {
            "pattern": True,
            "pattern_note": "Symétrie sur Solo bird flying",
            "sample": False,
            "publishable": True,
        },
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    a = body["annotation"]
    assert a["score"] == 4
    assert a["score_legacy"] == 7
    assert a["image_tags"] == ["image_compo_bonne", "image_anatomie_pb"]
    assert a["prompt_tags"] == ["prompt_complexe"]
    assert a["custom_tags"] == ["sujet_iconique", "ramadan_set"]
    assert a["flags"]["pattern"] is True
    assert a["flags"]["pattern_note"] == "Symétrie sur Solo bird flying"
    assert a["flags"]["publishable"] is True
    assert "updated_at" in a

    # Le fichier est bien écrit en v2 sur disque
    saved = json.loads((reports_root / "poc-test" / "annotations.json").read_text(encoding="utf-8"))
    assert "image_tags" in saved["annotations"]["lion_1024x1024_euler8s.png"]


def test_annotate_v2_score_out_of_range_rejected(reports_root):
    client = _client()
    # Score 7 ∉ [1,6]
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": 7,
    })
    assert r.status_code == 400
    assert "score" in r.json()["detail"].lower()


def test_annotate_v2_score_legacy_out_of_range_rejected(reports_root):
    client = _client()
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score_legacy": 11,
    })
    assert r.status_code == 400
    assert "score_legacy" in r.json()["detail"].lower()


def test_annotate_v2_unknown_image_tag_rejected(reports_root):
    client = _client()
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": 3,
        "image_tags": ["image_compo_bonne", "image_unknown_xxx"],
    })
    assert r.status_code == 400
    assert "image_unknown_xxx" in r.json()["detail"]


def test_annotate_v2_unknown_prompt_tag_rejected(reports_root):
    client = _client()
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": 3,
        "prompt_tags": ["prompt_creatif", "totally_made_up"],
    })
    assert r.status_code == 400
    assert "totally_made_up" in r.json()["detail"]


def test_annotate_v2_custom_tags_dedup_and_strip(reports_root):
    client = _client()
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": 3,
        "custom_tags": [" foo ", "foo", "bar", ""],
    })
    assert r.status_code == 200
    a = r.json()["annotation"]
    # strip + dédup en gardant l'ordre
    assert a["custom_tags"] == ["foo", "bar"]


def test_annotate_v2_flags_default_when_absent(reports_root):
    client = _client()
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": 5,
    })
    assert r.status_code == 200
    a = r.json()["annotation"]
    assert a["flags"]["pattern"] is False
    assert a["flags"]["pattern_note"] == ""
    assert a["flags"]["sample"] is False
    assert a["flags"]["publishable"] is None


def test_annotate_score_null_resets(reports_root):
    """Un score null est accepté (reset)."""
    client = _client()
    r = client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": None,
    })
    assert r.status_code == 200
    assert r.json()["annotation"]["score"] is None


def test_dirs_endpoint_lists_pngs(reports_root):
    """``GET /api/benchmark/dirs`` retourne les sous-dossiers contenant des PNG."""
    # Crée 2 autres dirs : un avec PNG, un sans
    (reports_root / "poc-with-pngs").mkdir()
    (reports_root / "poc-with-pngs" / "x.png").write_bytes(b"x")
    (reports_root / "poc-with-pngs" / "y.png").write_bytes(b"y")
    (reports_root / "poc-empty").mkdir()
    (reports_root / "poc-empty" / "readme.txt").write_text("nope", encoding="utf-8")

    client = _client()
    r = client.get("/api/benchmark/dirs")
    assert r.status_code == 200
    names = {d["name"] for d in r.json()["dirs"]}
    assert "poc-test" in names
    assert "poc-with-pngs" in names
    assert "poc-empty" not in names
    # png_count présent et > 0
    pngs_dir = next(d for d in r.json()["dirs"] if d["name"] == "poc-with-pngs")
    assert pngs_dir["png_count"] == 2


def test_custom_tags_endpoint_aggregates(reports_root):
    """``GET /api/benchmark/custom-tags`` agrège l'union de tous les annotations."""
    # Premier dir : déjà via annotate
    client = _client()
    client.post("/api/benchmark/annotate", json={
        "dir": "poc-test",
        "filename": "lion_1024x1024_euler8s.png",
        "score": 3,
        "custom_tags": ["alpha", "beta"],
    })

    # Deuxième dir avec annotation manuelle (legacy v1 + v2 mixés)
    other = reports_root / "poc-other"
    other.mkdir()
    (other / "x.png").write_bytes(b"x")
    (other / "annotations.json").write_text(json.dumps({
        "dir": "poc-other",
        "annotations": {
            "x.png": {  # legacy v1 avec notes JSON pills
                "score": 5,
                "defects": [],
                "notes": json.dumps(["custom_legacy_pill", "alpha"]),
                "publishable": True,
            },
            "y.png": {  # v2 natif
                "score": 4, "score_legacy": 7,
                "image_tags": [], "prompt_tags": [],
                "custom_tags": ["gamma"],
                "flags": {"pattern": False, "pattern_note": "", "sample": False, "publishable": None},
            },
        },
    }, ensure_ascii=False), encoding="utf-8")

    r = client.get("/api/benchmark/custom-tags")
    assert r.status_code == 200
    tags = r.json()["tags"]
    assert "alpha" in tags
    assert "beta" in tags
    assert "gamma" in tags
    assert "custom_legacy_pill" in tags
    # tri alpha + dédup
    assert tags == sorted(set(tags))


def test_images_endpoint_serves_v1_legacy_unchanged(reports_root):
    """Lecture v1 : ``GET /api/benchmark/images`` ne re-formatte pas le JSON
    sur disque ; l'annotation legacy est exposée telle quelle (le front gère
    la projection v2)."""
    sub = reports_root / "poc-test"
    (sub / "annotations.json").write_text(json.dumps({
        "dir": "poc-test",
        "annotations": {
            "lion_1024x1024_euler8s.png": {
                "score": 7,
                "defects": ["3_jambes"],
                "notes": "[\"prompt_trop_vague\"]",
                "publishable": True,
                "updated_at": "2026-05-06T12:00:00+00:00",
            }
        },
    }, ensure_ascii=False), encoding="utf-8")

    client = _client()
    r = client.get("/api/benchmark/images?dir=poc-test")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    item = body["items"][0]
    a = item["annotation"]
    # v1 fields preserved as-is (front-side normalize)
    assert a["score"] == 7
    assert a["defects"] == ["3_jambes"]
    assert a["notes"] == "[\"prompt_trop_vague\"]"
    assert a["publishable"] is True


def test_images_endpoint_serves_v2(reports_root):
    """Lecture v2 : annotation v2 native exposée telle quelle."""
    sub = reports_root / "poc-test"
    (sub / "annotations.json").write_text(json.dumps({
        "dir": "poc-test",
        "annotations": {
            "lion_1024x1024_euler8s.png": {
                "score": 4, "score_legacy": 7,
                "image_tags": ["image_anatomie_pb"],
                "prompt_tags": ["prompt_ambigu"],
                "custom_tags": ["foo"],
                "flags": {"pattern": True, "pattern_note": "X", "sample": False, "publishable": True},
                "updated_at": "2026-05-09T10:00:00+00:00",
            }
        },
    }, ensure_ascii=False), encoding="utf-8")

    client = _client()
    r = client.get("/api/benchmark/images?dir=poc-test")
    assert r.status_code == 200
    item = r.json()["items"][0]
    a = item["annotation"]
    assert a["score"] == 4
    assert a["score_legacy"] == 7
    assert a["image_tags"] == ["image_anatomie_pb"]
    assert a["flags"]["pattern"] is True


def test_vocabularies_match_brief_count():
    """Les vocabulaires doivent matcher le brief (18 image, 8 prompt).

    Source désormais : ``IMAGE_AXIS`` / ``PROMPT_AXIS`` (listes ordonnées).
    Les frozensets ``IMAGE_TAGS_VOCAB`` / ``PROMPT_TAGS_VOCAB`` en sont
    dérivés et doivent rester cohérents — ce test verrouille les deux
    représentations à la fois.
    """
    assert len(IMAGE_AXIS) == 18
    assert len(PROMPT_AXIS) == 8
    assert len(IMAGE_TAGS_VOCAB) == 18
    assert len(PROMPT_TAGS_VOCAB) == 8
    # Cohérence : chaque clé de la liste ordonnée est dans le frozenset
    assert {t["key"] for t in IMAGE_AXIS} == set(IMAGE_TAGS_VOCAB)
    assert {t["key"] for t in PROMPT_AXIS} == set(PROMPT_TAGS_VOCAB)


def test_image_axis_order_preserved():
    """L'ordre des entrées détermine la numérotation chord côté front
    (touche ``D`` + chiffre 1-9). Toute permutation accidentelle change
    l'expérience utilisateur — on verrouille la première et la dernière
    clé pour détecter une dérive triviale.
    """
    assert IMAGE_AXIS[0]["key"] == "image_compo_bonne"
    assert IMAGE_AXIS[-1]["key"] == "image_prompt_non_respecte"
    # Les 9 premiers (touches 1-9) doivent rester stables : on les fige.
    expected_first_nine = [
        "image_compo_bonne",
        "image_coherente",
        "image_creative",
        "image_complexe",
        "image_compo_mauvaise",
        "image_pas_coherente",
        "image_simpliste",
        "image_incomprehensible",
        "image_traces_couleur",
    ]
    assert [t["key"] for t in IMAGE_AXIS[:9]] == expected_first_nine


def test_prompt_axis_order_preserved():
    """Idem pour le chord ``T`` + chiffre 1-8 (les 8 entrées entières
    sont chord-bindées sur prompt_axis).
    """
    expected = [
        "prompt_interessant",
        "prompt_creatif",
        "prompt_complexe",
        "prompt_ambigu",
        "prompt_approximatif",
        "prompt_vide",
        "prompt_creux",
        "prompt_ennuyeux",
    ]
    assert [t["key"] for t in PROMPT_AXIS] == expected


def test_vocabularies_endpoint_returns_axes():
    """``GET /api/benchmark/vocabularies`` expose les 2 axes + score range
    + schema_version. Pas de DB, idempotent."""
    client = _client()
    r = client.get("/api/benchmark/vocabularies")
    assert r.status_code == 200, r.text
    body = r.json()
    # Présence des clés top-level
    assert set(body.keys()) >= {"image_axis", "prompt_axis", "score_range", "schema_version"}
    # Comptes
    assert len(body["image_axis"]) == 18
    assert len(body["prompt_axis"]) == 8
    # Schema version
    assert body["schema_version"] == 2
    # Score range
    assert body["score_range"] == {"min": 1, "max": 6}
    # Structure de chaque entrée
    for axis_name in ("image_axis", "prompt_axis"):
        for entry in body[axis_name]:
            assert set(entry.keys()) == {"key", "label", "polarity"}
            assert isinstance(entry["key"], str) and entry["key"]
            assert isinstance(entry["label"], str) and entry["label"]
            assert entry["polarity"] in {"pos", "neut", "neg"}
    # Les clés exposées matchent les frozensets côté validation
    assert {t["key"] for t in body["image_axis"]} == set(IMAGE_TAGS_VOCAB)
    assert {t["key"] for t in body["prompt_axis"]} == set(PROMPT_TAGS_VOCAB)
    # L'ordre est préservé entre la liste back et la réponse API
    assert [t["key"] for t in body["image_axis"]] == [t["key"] for t in IMAGE_AXIS]
    assert [t["key"] for t in body["prompt_axis"]] == [t["key"] for t in PROMPT_AXIS]
