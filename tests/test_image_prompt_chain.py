"""Tests unitaires de run_image_prompt_chain_sync (POC-3 v2 intégré au worker).

Mocks :
- ``call_ollama_sync`` (writer + validator)
- ``call_ollama_sync_with_drift_retry`` (planner)

Stratégie : queue déterministe de réponses canned. La signature de
``call_ollama_sync_with_drift_retry`` retourne ``(raw, drift_meta)`` et celle
de ``call_ollama_sync`` retourne juste ``raw`` — on patch les deux séparément
sur ``services.ai_jobs_sync``.
"""
from __future__ import annotations

import json

import pytest

from services import ai_jobs_sync as ajs


def _writer_json(prompt: str = "a friendly cat in a sunny library, line art coloring page", neg: str = "color, shading") -> str:
    return json.dumps({"prompt": prompt, "negative_prompt": neg}, ensure_ascii=False)


def _validator_json(score: int, checks: list[dict] | None = None, recs: list[str] | None = None) -> str:
    return json.dumps(
        {
            "score": score,
            "checks": checks or [{"name": "subject_clarity", "ok": True}],
            "recommendations": recs or [],
        },
        ensure_ascii=False,
    )


def _planner_json(plan: dict | None = None) -> str:
    base = {
        "subject": "cat",
        "setting": "library",
        "props": ["books", "shelf", "lamp", "rug", "globe"],
        "style": "line-art for kids",
        "mood": "calm",
    }
    return json.dumps(plan or base, ensure_ascii=False)


def _patch_chain(monkeypatch, planner_responses: list, writer_responses: list, validator_responses: list,
                 planner_drift: list[bool] | None = None):
    """Câble fake_drift et fake_call avec queues déterministes."""
    p_idx = {"i": 0}
    w_v_idx = {"i": 0}
    drift_flags = planner_drift or [False] * len(planner_responses)

    def fake_drift(prompt, system, model=None, temperature=None, timeout=None):
        i = p_idx["i"]
        p_idx["i"] += 1
        return planner_responses[i], {"drift_retry": drift_flags[i], "first_raw": ""}

    queue_wv = list(writer_responses) + list(validator_responses)

    def fake_call(prompt, system, model=None, temperature=0.0, timeout=180, num_ctx=None):
        i = w_v_idx["i"]
        w_v_idx["i"] += 1
        return queue_wv[i]

    monkeypatch.setattr(ajs, "call_ollama_sync_with_drift_retry", fake_drift)
    monkeypatch.setattr(ajs, "call_ollama_sync", fake_call)


def test_chain_happy_path_score_above_75(monkeypatch):
    """Score ≥ 75 → low_score absent / False, prompt renvoyé, drift_retried False."""
    _patch_chain(
        monkeypatch,
        planner_responses=[_planner_json()],
        writer_responses=[_writer_json("a curious cat sitting at a library desk surrounded by tall bookshelves, line art")],
        validator_responses=[_validator_json(score=82)],
    )
    result = ajs.run_image_prompt_chain_sync(
        conn=None,
        config={
            "concept_name_en": "Cat in a Library",
            "title": "Cat in a Library",
            "keywords": "cat, library",
        },
    )
    assert result["prompt"].startswith("a curious cat")
    assert result["score"] == 82
    assert result["low_score"] is False
    assert result["drift_retried"] is False
    assert result["planner_latency_ms"] >= 0
    assert result["writer_latency_ms"] >= 0
    assert result["validator_latency_ms"] >= 0
    assert result["total_latency_ms"] == (
        result["planner_latency_ms"] + result["writer_latency_ms"] + result["validator_latency_ms"]
    )
    assert isinstance(result["plan"], dict)
    assert result["checks"] and result["checks"][0]["ok"] is True


def test_chain_low_score_flag(monkeypatch):
    """Score = 60 → low_score True, mais pas d'erreur — l'admin tranche."""
    _patch_chain(
        monkeypatch,
        planner_responses=[_planner_json()],
        writer_responses=[_writer_json("a vague cat scene, line art")],
        validator_responses=[_validator_json(score=60, recs=["clarify the setting"])],
    )
    result = ajs.run_image_prompt_chain_sync(
        conn=None,
        config={"title": "Cat", "keywords": "cat"},
    )
    assert result["score"] == 60
    assert result["low_score"] is True
    assert "clarify the setting" in result["recommendations"]


def test_chain_drift_retry(monkeypatch):
    """Le planner retourne d'abord du drift (la fonction wrap renvoie quand même
    un JSON valide après retry interne — on simule en flaggant drift_retry=True
    dans le drift_meta)."""
    _patch_chain(
        monkeypatch,
        planner_responses=[_planner_json()],
        writer_responses=[_writer_json()],
        validator_responses=[_validator_json(score=80)],
        planner_drift=[True],
    )
    result = ajs.run_image_prompt_chain_sync(
        conn=None,
        config={"title": "Cat in a Library", "keywords": "cat, library"},
    )
    assert result["drift_retried"] is True
    assert result["score"] == 80
    assert result["low_score"] is False


def test_chain_artifact_shape_in_save_result(monkeypatch):
    """Vérifie que le worker sait construire l'artefact avec les bons champs."""
    from api.job_review_artifact import build_image_text_patch_artifact

    fake_result = {
        "prompt": "a curious cat at a library desk",
        "negative_prompt": "color, shading",
        "score": 82,
        "checks": [{"name": "subject", "ok": True}],
        "recommendations": [],
        "low_score": False,
        "drift_retried": False,
        "planner_latency_ms": 1000,
        "writer_latency_ms": 2000,
        "validator_latency_ms": 1500,
        "total_latency_ms": 4500,
    }

    artifact = build_image_text_patch_artifact(
        entity_id="img_test",
        proposal={
            "prompt": fake_result["prompt"],
            "negative_prompt": fake_result["negative_prompt"],
            "chain_score": fake_result["score"],
            "chain_checks": fake_result["checks"],
            "chain_recommendations": fake_result["recommendations"],
            "chain_low_score": fake_result["low_score"],
            "chain_latencies_ms": {
                "planner": fake_result["planner_latency_ms"],
                "writer": fake_result["writer_latency_ms"],
                "validator": fake_result["validator_latency_ms"],
                "total": fake_result["total_latency_ms"],
            },
            "chain_drift_retried": fake_result["drift_retried"],
        },
        job_type="image_prompt_chain",
    )
    assert artifact["job_type"] == "image_prompt_chain"
    assert artifact["entity_id"] == "img_test"
    assert artifact["proposal"]["chain_score"] == 82
    assert artifact["proposal"]["chain_latencies_ms"]["total"] == 4500
    assert artifact["apply_plan"]["mode"] == "merge_entity_fields"
