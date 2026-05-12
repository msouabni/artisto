"""Tests unitaires du script ``scripts/poc_generate_i18n.py`` (MEP-v0/B).

Mocks ``content_generator.generate_content`` pour ne pas dépendre d'un Ollama
vivant. Vérifie :

- Validation SOFT caps détecte trop court / trop long
- Strip harakat fonctionne sur un AR connu (regex codepoints explicites)
- Checkpoint atomique (pas de corruption sur écriture)
- ``--resume`` skip les leaves status=ok déjà checkpointées
- Build du payload final stats
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "poc_generate_i18n.py"


def _load_script_module():
    """Charge ``poc_generate_i18n`` comme module sans le faire passer par sys.argv."""
    # Le script a un side-effect (shim ollama_json) à l'import — c'est intentionnel.
    if "poc_generate_i18n" in sys.modules:
        return sys.modules["poc_generate_i18n"]
    spec = importlib.util.spec_from_file_location("poc_generate_i18n", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Enregistrer AVANT exec_module pour que dataclasses puissent résoudre cls.__module__
    sys.modules["poc_generate_i18n"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def script_mod():
    return _load_script_module()


# ─── strip_harakat ───────────────────────────────────────────────────────────
def test_strip_harakat_removes_fatha_damma_kasra(script_mod):
    """Vérifie que les harakat (fatha, damma, kasra, sukun, shadda) sont retirés."""
    # ﻙَﻟْﺐٌ avec voyellation explicite
    vocalised = "كَلْبٌ"  # kalbun avec fatha, sukun, damma
    stripped = script_mod.strip_harakat(vocalised)
    assert stripped == "كلب"


def test_strip_harakat_keeps_ascii_intact(script_mod):
    """No-op sur ASCII / pas d'arabe."""
    assert script_mod.strip_harakat("Mickey") == "Mickey"
    assert script_mod.strip_harakat("") == ""
    assert script_mod.strip_harakat("") == ""


def test_strip_harakat_already_clean_text(script_mod):
    """Texte AR déjà sans harakat → inchangé."""
    text = "أسد ذكي في الغابة"
    assert script_mod.strip_harakat(text) == text


def test_strip_harakat_partial_vocalisation(script_mod):
    """Vocalisation partielle au milieu d'une phrase."""
    text = "هذا أَسَد كبير"  # asad partiellement vocalisé
    stripped = script_mod.strip_harakat(text)
    assert stripped == "هذا أسد كبير"


# ─── check_soft_caps ─────────────────────────────────────────────────────────
def test_check_soft_caps_all_valid(script_mod):
    """Tous les champs dans les bornes → aucune violation."""
    violations = script_mod.check_soft_caps(
        title_en="A" * 50,
        title_fr="A" * 50,
        title_ar="ا" * 40,
        desc_en="A" * 100,
        desc_fr="A" * 100,
        desc_ar="ا" * 80,
    )
    assert violations == []


def test_check_soft_caps_title_en_too_short(script_mod):
    """title_en avec 30 chars (min=40) → too_short."""
    v = script_mod.check_soft_caps(
        title_en="A" * 30,
        title_fr="A" * 50,
        title_ar="ا" * 40,
        desc_en="A" * 100,
        desc_fr="A" * 100,
        desc_ar="ا" * 80,
    )
    assert len(v) == 1
    assert v[0].field == "title_en"
    assert v[0].kind == "too_short"
    assert v[0].value_len == 30


def test_check_soft_caps_description_ar_too_long(script_mod):
    """description_ar avec 200 chars (max=115) → too_long."""
    v = script_mod.check_soft_caps(
        title_en="A" * 50,
        title_fr="A" * 50,
        title_ar="ا" * 40,
        desc_en="A" * 100,
        desc_fr="A" * 100,
        desc_ar="ا" * 200,
    )
    assert len(v) == 1
    assert v[0].field == "description_ar"
    assert v[0].kind == "too_long"


def test_has_too_long_helper(script_mod):
    """``has_too_long`` retourne True dès qu'une violation kind=too_long."""
    only_short = [
        script_mod.FieldViolation("title_en", 10, 40, 60, "too_short"),
    ]
    assert script_mod.has_too_long(only_short) is False

    mixed = [
        script_mod.FieldViolation("title_en", 10, 40, 60, "too_short"),
        script_mod.FieldViolation("description_fr", 200, 80, 130, "too_long"),
    ]
    assert script_mod.has_too_long(mixed) is True


def test_soft_caps_bornes_actees_2026_05_05(script_mod):
    """Sanity check des bornes (cf. CLAUDE.md §Validation 2026-05-05)."""
    assert script_mod.SOFT_CAPS["title_fr_en"] == (40, 60)
    assert script_mod.SOFT_CAPS["title_ar"] == (25, 55)
    assert script_mod.SOFT_CAPS["description_fr_en"] == (80, 130)
    assert script_mod.SOFT_CAPS["description_ar"] == (40, 115)


# ─── atomic_write_json ───────────────────────────────────────────────────────
def test_atomic_write_creates_file(script_mod, tmp_path):
    """L'écriture atomique crée le fichier final avec contenu valide."""
    target = tmp_path / "out.json"
    payload = {"hello": "world", "count": 42}
    script_mod.atomic_write_json(target, payload)
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_atomic_write_replaces_existing(script_mod, tmp_path):
    """Réécriture remplace le contenu sans corruption."""
    target = tmp_path / "out.json"
    target.write_text(json.dumps({"old": True}), encoding="utf-8")
    new = {"new": True, "n": 1}
    script_mod.atomic_write_json(target, new)
    assert json.loads(target.read_text(encoding="utf-8")) == new


def test_atomic_write_no_temp_leftover(script_mod, tmp_path):
    """Pas de fichier .tmp laissé après une écriture réussie."""
    target = tmp_path / "out.json"
    script_mod.atomic_write_json(target, {"k": "v"})
    # Liste tout le contenu du dossier — seul ``out.json`` doit subsister
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftovers == []


def test_atomic_write_creates_parent_dir(script_mod, tmp_path):
    """Le parent inexistant est créé."""
    target = tmp_path / "nested" / "deeper" / "out.json"
    script_mod.atomic_write_json(target, {"a": 1})
    assert target.exists()


def test_atomic_write_no_corruption_on_unicode(script_mod, tmp_path):
    """Caractères AR/UTF-8 préservés."""
    target = tmp_path / "out.json"
    payload = {"title_ar": "أسد في الغابة", "title_fr": "Éléphant"}
    script_mod.atomic_write_json(target, payload)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == payload


# ─── load_checkpoint ─────────────────────────────────────────────────────────
def test_load_checkpoint_missing_returns_none(script_mod, tmp_path):
    ck = script_mod.load_checkpoint(tmp_path / "missing.json")
    assert ck is None


def test_load_checkpoint_invalid_json_returns_none(script_mod, tmp_path):
    target = tmp_path / "ck.json"
    target.write_text("not json {{", encoding="utf-8")
    assert script_mod.load_checkpoint(target) is None


def test_load_checkpoint_valid(script_mod, tmp_path):
    target = tmp_path / "ck.json"
    target.write_text(json.dumps({"leaves": []}), encoding="utf-8")
    assert script_mod.load_checkpoint(target) == {"leaves": []}


# ─── generate_leaf with mocked content_generator ─────────────────────────────
def _make_fake_content(
    script_mod,
    *,
    title_en="A" * 50,
    title_fr="B" * 50,
    title_ar="ا" * 40,
    desc_en="A" * 100,
    desc_fr="B" * 100,
    desc_ar="ا" * 80,
    title_card_en="card en",
    title_card_fr="card fr",
    title_card_ar="بطاقة",
    keywords_en=None,
    keywords_fr=None,
    keywords_ar=None,
    review_flags=None,
    retries_ar=0,
    latency_ms=1234,
):
    from services.content_generator import ContentResult, LocaleContent

    return ContentResult(
        en=LocaleContent(
            title=title_en,
            title_card=title_card_en,
            description=desc_en,
            keywords=keywords_en or ["a", "b", "c", "d", "e"],
        ),
        fr=LocaleContent(
            title=title_fr,
            title_card=title_card_fr,
            description=desc_fr,
            keywords=keywords_fr or ["a", "b", "c", "d", "e"],
        ),
        ar=LocaleContent(
            title=title_ar,
            title_card=title_card_ar,
            description=desc_ar,
            keywords=keywords_ar or ["ا", "ب", "ج", "د", "ه"],
        ),
        review_flags=review_flags or [],
        retries_ar=retries_ar,
        latency_ms=latency_ms,
    )


def test_generate_leaf_ok_no_retry(script_mod, monkeypatch):
    """Happy path : 1 appel, status=ok, aucune violation."""
    calls = {"n": 0}

    def fake_generate(**kwargs):
        calls["n"] += 1
        return _make_fake_content(script_mod)

    monkeypatch.setattr(script_mod.cg, "generate_content", fake_generate)
    result = script_mod.generate_leaf(
        "test_leaf",
        "Test Concept",
        "Concept Test",
        "مفهوم",
        max_retries=3,
    )
    assert result.status == "ok"
    assert calls["n"] == 1
    assert result.title_en == "A" * 50
    assert result.title_ar == "ا" * 40
    assert result.soft_cap_violations == []


def test_generate_leaf_retries_on_too_long_then_ok(script_mod, monkeypatch):
    """Si la 1ère gen dépasse borne haute, retry et accepter au 2e essai."""
    sequence = [
        _make_fake_content(script_mod, title_en="A" * 80),  # too_long (max 60)
        _make_fake_content(script_mod, title_en="A" * 50),  # ok
    ]
    idx = {"i": 0}

    def fake_generate(**kwargs):
        c = sequence[idx["i"]]
        idx["i"] += 1
        return c

    monkeypatch.setattr(script_mod.cg, "generate_content", fake_generate)
    result = script_mod.generate_leaf(
        "test_leaf",
        "Test",
        "Test",
        "اختبار",
        max_retries=3,
    )
    assert result.status == "ok"
    assert idx["i"] == 2
    assert result.generation_attempts["content_generator"] == 2
    assert result.generation_attempts["regen_for_caps"] == 1


def test_generate_leaf_soft_caps_violated_after_max_retries(script_mod, monkeypatch):
    """Si toutes les tentatives dépassent borne haute → status=soft_caps_violated."""

    def fake_generate(**kwargs):
        return _make_fake_content(script_mod, title_en="A" * 80)

    monkeypatch.setattr(script_mod.cg, "generate_content", fake_generate)
    result = script_mod.generate_leaf(
        "test_leaf", "Test", "Test", "اختبار", max_retries=3
    )
    assert result.status == "soft_caps_violated"
    assert result.generation_attempts["content_generator"] == 3
    # title_en violation présente
    fields = {v["field"] for v in result.soft_cap_violations}
    assert "title_en" in fields


def test_generate_leaf_strip_harakat_applied_post_process(script_mod, monkeypatch):
    """Le strip_harakat doit être appliqué sur les outputs AR."""
    vocalised_title = "أَسَدٌ ذَكِيٌّ فِي الْغَابَةِ"  # avec harakat
    vocalised_desc = "هَذَا أَسَد كَبِير وَجَمِيل جِدًّا"

    def fake_generate(**kwargs):
        return _make_fake_content(
            script_mod,
            title_ar=vocalised_title,
            desc_ar=vocalised_desc,
        )

    monkeypatch.setattr(script_mod.cg, "generate_content", fake_generate)
    result = script_mod.generate_leaf(
        "test_leaf", "Test", "Test", "اختبار", max_retries=1
    )
    # Les harakat doivent être absentes
    assert "َ" not in result.title_ar
    assert "ُ" not in result.title_ar
    assert "ِ" not in result.title_ar
    assert "ْ" not in result.title_ar
    assert "ّ" not in result.title_ar
    assert "ٌ" not in result.title_ar
    # mais le squelette consonne doit rester
    assert "أسد" in result.title_ar
    assert "كبير" in result.description_ar


def test_generate_leaf_failed_on_ollama_error(script_mod, monkeypatch):
    """Erreur Ollama hard 3x → status=failed (sans sleep réel)."""
    monkeypatch.setattr(script_mod, "RETRY_DELAYS_S", [0, 0, 0])

    def fake_generate(**kwargs):
        raise RuntimeError("Ollama timeout après 60s sur qwen3.5:4b")

    monkeypatch.setattr(script_mod.cg, "generate_content", fake_generate)
    result = script_mod.generate_leaf(
        "test_leaf", "Test", "Test", "اختبار", max_retries=3
    )
    assert result.status == "failed"
    assert "ollama_error" in (result.error or "")
    assert result.generation_attempts["content_generator"] == 3


# ─── build_payload ───────────────────────────────────────────────────────────
def test_build_payload_stats(script_mod):
    results = [
        script_mod.LeafResult(
            leaf_id="a",
            name_en="A",
            name_fr="A",
            name_ar="ا",
            status="ok",
            generation_attempts={"content_generator": 1, "regen_for_caps": 0},
        ),
        script_mod.LeafResult(
            leaf_id="b",
            name_en="B",
            name_fr="B",
            name_ar="ب",
            status="failed",
            generation_attempts={"content_generator": 3, "regen_for_caps": 0},
        ),
        script_mod.LeafResult(
            leaf_id="c",
            name_en="C",
            name_fr="C",
            name_ar="ج",
            status="soft_caps_violated",
            generation_attempts={"content_generator": 3, "regen_for_caps": 2},
        ),
    ]
    payload = script_mod.build_payload(results)
    assert payload["schema_version"] == script_mod.SCHEMA_VERSION
    assert payload["stats"]["total_leaves"] == 3
    assert payload["stats"]["ok"] == 1
    assert payload["stats"]["failed"] == 1
    assert payload["stats"]["soft_caps_violated"] == 1
    assert payload["soft_caps"]["title_fr_en"] == [40, 60]


# ─── run_batch with --resume ─────────────────────────────────────────────────
def test_run_batch_resume_skips_ok_leaves(script_mod, monkeypatch, tmp_path):
    """``--resume`` ne ré-appelle pas Ollama pour les leaves status=ok déjà chkpt."""
    out_path = tmp_path / "out.json"
    ck_path = tmp_path / "ck.json"

    # Pré-écrit un checkpoint où "leaf_a" est ok et "leaf_b" est failed
    initial_results = [
        script_mod.LeafResult(
            leaf_id="leaf_a",
            name_en="A",
            name_fr="A",
            name_ar="ا",
            title_en="X" * 50,
            description_en="X" * 100,
            title_fr="Y" * 50,
            description_fr="Y" * 100,
            title_ar="ا" * 40,
            description_ar="ا" * 80,
            status="ok",
            generation_attempts={"content_generator": 1, "regen_for_caps": 0},
        ),
        script_mod.LeafResult(
            leaf_id="leaf_b",
            name_en="B",
            name_fr="B",
            name_ar="ب",
            status="failed",
            generation_attempts={"content_generator": 3, "regen_for_caps": 0},
        ),
    ]
    ck_payload = script_mod.build_payload(initial_results)
    script_mod.atomic_write_json(ck_path, ck_payload)

    calls: list[str] = []

    def fake_generate(**kwargs):
        calls.append(kwargs.get("concept_name_en", ""))
        return _make_fake_content(script_mod)

    monkeypatch.setattr(script_mod.cg, "generate_content", fake_generate)

    leaves_to_process = [
        ("leaf_a", {"name_en": "A", "name_fr": "A", "name_ar": "ا"}),
        ("leaf_b", {"name_en": "B", "name_fr": "B", "name_ar": "ب"}),
        ("leaf_c", {"name_en": "C", "name_fr": "C", "name_ar": "ج"}),
    ]
    payload = script_mod.run_batch(
        leaves_to_process,
        out_path=out_path,
        checkpoint_path=ck_path,
        resume=True,
        model="qwen3.5:4b",
        max_retries=1,
    )

    # leaf_a est ok → skip
    # leaf_b status=failed dans le checkpoint → on doit le retenter
    # leaf_c jamais vu → on doit l'appeler
    assert "A" not in calls  # leaf_a skipped
    assert "B" in calls  # leaf_b retried
    assert "C" in calls  # leaf_c first run
    assert len(calls) == 2

    assert payload["stats"]["total_leaves"] == 3
    # leaf_a (ok) + B (re-generated → ok) + C (ok)
    assert payload["stats"]["ok"] == 3


def test_run_batch_checkpoint_written_after_each_leaf(script_mod, monkeypatch, tmp_path):
    """Le checkpoint est mis à jour après chaque leaf (pas seulement à la fin)."""
    out_path = tmp_path / "out.json"
    ck_path = tmp_path / "ck.json"
    saved_snapshots: list[int] = []

    def fake_generate(**kwargs):
        return _make_fake_content(script_mod)

    # Wrap atomic_write_json pour observer les snapshots checkpoint
    original = script_mod.atomic_write_json

    def wrapped(p, payload):
        if str(p) == str(ck_path):
            saved_snapshots.append(len(payload.get("leaves", [])))
        return original(p, payload)

    monkeypatch.setattr(script_mod, "atomic_write_json", wrapped)
    monkeypatch.setattr(script_mod.cg, "generate_content", fake_generate)

    leaves_to_process = [
        ("a", {"name_en": "A", "name_fr": "A", "name_ar": "ا"}),
        ("b", {"name_en": "B", "name_fr": "B", "name_ar": "ب"}),
        ("c", {"name_en": "C", "name_fr": "C", "name_ar": "ج"}),
    ]
    script_mod.run_batch(
        leaves_to_process,
        out_path=out_path,
        checkpoint_path=ck_path,
        resume=False,
        model="qwen3.5:4b",
        max_retries=1,
    )
    # 3 leaves → 3 snapshots checkpoint, croissants
    assert saved_snapshots == [1, 2, 3]


# ─── collect_taxonomy_leaves ─────────────────────────────────────────────────
def test_collect_taxonomy_leaves_from_real_file(script_mod):
    """Charge la vraie taxonomie et vérifie ≥ 1000 leaves et présence d'un cas connu."""
    taxonomy_path = PROJECT_ROOT / "data" / "prompt_generator" / "coloring_taxonomy_full.json"
    if not taxonomy_path.exists():
        pytest.skip("Taxonomy file not present")
    leaves = script_mod.collect_taxonomy_leaves(taxonomy_path)
    assert len(leaves) >= 1000
    # cas connu (cf. data/prompt_generator/coloring_taxonomy_full.json)
    assert "lion_in_savanna" in leaves
    sample = leaves["lion_in_savanna"]
    assert sample.get("name_en")
    assert sample.get("name_fr")
    assert sample.get("name_ar")


# ─── think: false patch (2026-05-10) ─────────────────────────────────────────
def test_supports_native_think_disable_qwen35(script_mod):
    """qwen3.5:4b et qwen3.6:* supportent le param natif Ollama ``"think": false``."""
    assert script_mod._supports_native_think_disable("qwen3.5:4b") is True
    assert script_mod._supports_native_think_disable("qwen3.5:9b") is True
    assert script_mod._supports_native_think_disable("qwen3.6:7b") is True
    # case-insensitive
    assert script_mod._supports_native_think_disable("Qwen3.5:4B") is True


def test_supports_native_think_disable_excludes_qwen3_strict(script_mod):
    """qwen3:8b et qwen3:4b NE supportent PAS le param natif (→ /no_think tag)."""
    assert script_mod._supports_native_think_disable("qwen3:8b") is False
    assert script_mod._supports_native_think_disable("qwen3:4b") is False


def test_supports_native_think_disable_excludes_other_models(script_mod):
    """Autres modèles (qwen2.5, llama3, …) → False."""
    assert script_mod._supports_native_think_disable("qwen2.5:7b") is False
    assert script_mod._supports_native_think_disable("llama3.1:8b") is False
    assert script_mod._supports_native_think_disable("aya-expanse:8b") is False
    assert script_mod._supports_native_think_disable(None) is False
    assert script_mod._supports_native_think_disable("") is False


def test_is_qwen3_strict(script_mod):
    """qwen3:8b → True ; qwen3.5:4b → False."""
    assert script_mod._is_qwen3_strict("qwen3:8b") is True
    assert script_mod._is_qwen3_strict("qwen3:4b") is True
    assert script_mod._is_qwen3_strict("qwen3.5:4b") is False
    assert script_mod._is_qwen3_strict("qwen2.5:7b") is False
    assert script_mod._is_qwen3_strict(None) is False


def test_call_ollama_sync_is_patched(script_mod):
    """Le module a bien monkey-patché ``services.ollama_json.call_ollama_sync``."""
    import services.ollama_json as oj
    assert getattr(oj.call_ollama_sync, "_patched_for_native_think_disable", False) is True


def test_patched_call_injects_think_false_for_qwen35(script_mod, monkeypatch):
    """Pour qwen3.5:4b, le payload POST Ollama contient ``"think": false``."""
    import services.ollama_json as oj

    captured: dict = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "ok"}

    class _FakeClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    # Remplace httpx.Client le temps du test
    import httpx
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    out = oj.call_ollama_sync(
        prompt="hi",
        system="",
        model="qwen3.5:4b",
        temperature=0.0,
        timeout=10,
    )
    assert out == "ok"
    assert captured["json"]["model"] == "qwen3.5:4b"
    assert captured["json"]["think"] is False
    assert captured["json"]["stream"] is False


def test_patched_call_does_not_inject_think_for_qwen3_strict(script_mod, monkeypatch):
    """Pour qwen3:8b, le payload NE doit PAS contenir ``"think": false``.

    qwen3 strict utilise le tag ``/no_think`` dans le system prompt (géré par
    ``apply_no_think_system`` dans ``services.ollama_json``), pas le param natif.
    """
    import services.ollama_json as oj

    captured: dict = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "ok"}

    class _FakeClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    out = oj.call_ollama_sync(
        prompt="hi",
        system="some system prompt",
        model="qwen3:8b",
        temperature=0.0,
        timeout=10,
    )
    assert out == "ok"
    # Pas de "think" dans le payload pour qwen3 strict
    assert "think" not in captured["json"]
    # En revanche le tag /no_think doit avoir été ajouté côté system prompt
    assert captured["json"]["system"].startswith("/no_think")


def test_patched_call_does_not_inject_think_for_other_models(script_mod, monkeypatch):
    """Pour qwen2.5:7b, ni ``think`` ni ``/no_think`` ne doivent être injectés."""
    import services.ollama_json as oj

    captured: dict = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "ok"}

    class _FakeClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    out = oj.call_ollama_sync(
        prompt="hi",
        system="",
        model="qwen2.5:7b",
        temperature=0.0,
        timeout=10,
    )
    assert out == "ok"
    assert "think" not in captured["json"]
    # qwen2.5 ne déclenche pas /no_think non plus
    assert not captured["json"]["system"].startswith("/no_think")


# ─── collect_publishable_leaves ──────────────────────────────────────────────
def test_collect_publishable_leaves_from_real_annotations(script_mod):
    """Croise les annotations publishables avec la taxonomie : retourne ≥ 100 leaves."""
    taxonomy_path = PROJECT_ROOT / "data" / "prompt_generator" / "coloring_taxonomy_full.json"
    if not taxonomy_path.exists():
        pytest.skip("Taxonomy file not present")
    leaves = script_mod.collect_taxonomy_leaves(taxonomy_path)
    matched, orphans = script_mod.collect_publishable_leaves(
        "docs/reports/poc-*/annotations.json", leaves
    )
    # corpus MEP v0 (mesuré 2026-05-10) : ≥ 100 leaves
    assert len(matched) >= 100
    # tous les matched sont bien dans la taxonomie
    for lid in matched:
        assert lid in leaves
