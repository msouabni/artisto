"""Sidecar .overrides.json pour load_workflow_template."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "src")
from workers.comfy_client import (
    WORKFLOW_CONTRACT_VERSION,
    load_workflow_template,
    resolve_negative_prompt_for_workflow,
    sanitize_public_workflow_inputs,
)


def test_sidecar_replaces_embedded_overrides(tmp_path: Path) -> None:
    wf = {
        "__meta__": {
            "overrides": {"positive_prompt": ["1", "text"], "seed": ["9", "seed"]},
        },
        "1": {"class_type": "CLIPTextEncode", "inputs": {}},
        "9": {"class_type": "KSampler", "inputs": {}},
    }
    side = {"overrides": {"positive_prompt": ["88", "text"], "steps": ["3", "steps"]}}
    (tmp_path / "templ.json").write_text(json.dumps(wf), encoding="utf-8")
    (tmp_path / "templ.overrides.json").write_text(json.dumps(side), encoding="utf-8")

    data, omap, contract = load_workflow_template(tmp_path, "templ")
    assert "__meta__" not in data
    assert omap["positive_prompt"] == ["88", "text"]
    assert omap["steps"] == ["3", "steps"]
    assert "seed" not in omap
    assert contract["contract_version"] == "legacy_overrides"
    assert contract["public_inputs"]["positive_prompt"] == ["88", "text"]


def test_embedded_only_when_no_sidecar(tmp_path: Path) -> None:
    wf = {
        "__meta__": {"overrides": {"positive_prompt": ["6", "text"]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {}},
    }
    (tmp_path / "solo.json").write_text(json.dumps(wf), encoding="utf-8")

    data, omap, contract = load_workflow_template(tmp_path, "solo")
    assert omap == {"positive_prompt": ["6", "text"]}
    assert contract["capabilities"]["positive_prompt"] == "required"


def test_sidecar_policy_only_keeps_embedded_overrides(tmp_path: Path) -> None:
    wf = {
        "__meta__": {
            "overrides": {"positive_prompt": ["6", "text"], "negative_prompt": ["7", "text"]},
            "negative_prompt_policy": {"mode": "use_if_present", "default_text": "from_embed"},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {}},
    }
    side = {"negative_prompt_policy": {"mode": "ignore", "default_text": "ignored"}}
    (tmp_path / "pol.json").write_text(json.dumps(wf), encoding="utf-8")
    (tmp_path / "pol.overrides.json").write_text(json.dumps(side), encoding="utf-8")

    data, omap, contract = load_workflow_template(tmp_path, "pol")
    assert omap["positive_prompt"] == ["6", "text"]
    assert omap["negative_prompt"] == ["7", "text"]
    assert contract["negative_prompt_policy"]["mode"] == "ignore"
    assert contract["negative_prompt_policy"]["default_text"] == "ignored"


def test_z_image_template_loads_from_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    wf_dir = root / "data" / "workflows"
    data, omap, contract = load_workflow_template(wf_dir, "z_image_turbo_v1")
    assert "3" in data and data["3"].get("class_type") == "KSampler"
    assert "positive_prompt" in omap
    assert contract["contract_version"] == WORKFLOW_CONTRACT_VERSION
    assert contract["capabilities"]["negative_prompt"] == "unsupported"


def test_ernie_uses_sidecar_from_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    wf_dir = root / "data" / "workflows"
    data, omap, contract = load_workflow_template(wf_dir, "ernie-image-turbo-q8-api")
    assert data.get("10", {}).get("class_type") == "UnetLoaderGGUF"
    assert omap["positive_prompt"] == ["14", "text"]
    assert omap["seed"] == ["16", "seed"]
    assert "shift" not in omap
    assert "__meta__" not in data
    assert contract["contract_version"] == WORKFLOW_CONTRACT_VERSION
    assert contract["capabilities"]["positive_prompt"] == "required"
    assert contract["capabilities"]["negative_prompt"] == "unsupported"
    assert data.get("19", {}).get("class_type") == "ConditioningZeroOut"


def test_resolve_negative_prompt_ignore_z_image_style() -> None:
    omap = {"positive_prompt": ["6", "text"]}
    txt, inj = resolve_negative_prompt_for_workflow("  hello  ", omap, {"mode": "ignore"})
    assert txt == "hello"
    assert inj is False


def test_resolve_negative_prompt_use_if_present_fallback() -> None:
    omap = {"negative_prompt": ["15", "text"]}
    txt, inj = resolve_negative_prompt_for_workflow("", omap, {"mode": "use_if_present", "default_text": "fallback"})
    assert txt == "fallback"
    assert inj is True


def test_resolve_negative_prompt_empty_no_inject() -> None:
    omap = {"negative_prompt": ["15", "text"]}
    txt, inj = resolve_negative_prompt_for_workflow("", omap, {"mode": "use_if_present", "default_text": ""})
    assert txt == ""
    assert inj is False


def test_load_workflow_template_public_inputs_contract(tmp_path: Path) -> None:
    wf = {
        "__meta__": {"description": "x"},
        "1": {"class_type": "CLIPTextEncode", "inputs": {}},
        "2": {"class_type": "KSampler", "inputs": {}},
    }
    side = {
        "contract_version": WORKFLOW_CONTRACT_VERSION,
        "public_inputs": {
            "positive_prompt": ["1", "text"],
            "steps": ["2", "steps"],
        },
        "capabilities": {
            "positive_prompt": "required",
            "negative_prompt": "unsupported",
            "steps": "optional",
        },
    }
    (tmp_path / "contracted.json").write_text(json.dumps(wf), encoding="utf-8")
    (tmp_path / "contracted.overrides.json").write_text(json.dumps(side), encoding="utf-8")

    _, input_map, contract = load_workflow_template(tmp_path, "contracted")
    assert input_map["positive_prompt"] == ["1", "text"]
    assert contract["contract_version"] == WORKFLOW_CONTRACT_VERSION
    assert contract["capabilities"]["negative_prompt"] == "unsupported"


def test_sanitize_public_workflow_inputs_drops_unsupported_and_empty() -> None:
    contract = {
        "public_inputs": {"positive_prompt": ["1", "text"], "seed": ["2", "seed"]},
        "capabilities": {"positive_prompt": "required", "negative_prompt": "unsupported", "seed": "optional"},
    }
    out = sanitize_public_workflow_inputs(
        {"positive_prompt": " hello ", "negative_prompt": "x", "seed": 123, "shift": 3},
        contract,
    )
    assert out == {"positive_prompt": "hello", "seed": 123}
