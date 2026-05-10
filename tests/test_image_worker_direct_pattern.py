"""Tests pour le pattern POC direct du worker image (ERNIE-only, MEP v0).

Cf. docs/architect/2026-05-10_spec-mep-v0.md §V1.1 et
docs/architect/briefs/2026-05-10_brief-simplification-worker-image-pattern-poc.md.

Le worker doit :
1. Injecter le positive prompt directement au node 14 (CLIPTextEncode positive).
2. Ne pas injecter le negative pour ERNIE (négatif figé dans le workflow JSON node 15).
3. Lire le ``contract_version`` depuis le ``__meta__`` du workflow JSON.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

import workers.image_worker as image_worker_mod
from workers.image_worker import ImageWorker


class _FakeComfyClient:
    """Fake ComfyClient capturant le workflow soumis pour assertions."""

    def __init__(self) -> None:
        self.submitted_workflow: dict[str, Any] | None = None
        self.prompt_id = "fake-prompt-id"

    def is_available(self) -> bool:
        return True

    def submit_prompt(self, workflow: dict, prompt_id: str | None = None) -> str:
        self.submitted_workflow = workflow
        return self.prompt_id

    def poll_until_done(self, prompt_id: str, progress_callback=None) -> dict:
        return {
            "outputs": {
                "18": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}
            }
        }

    def extract_output_images(self, history_entry: dict) -> list[dict]:
        return [
            {"filename": "out.png", "subfolder": "", "type": "output", "node_id": "18"}
        ]

    def download_image(self, filename: str, dest: Path, subfolder: str = "", folder_type: str = "output") -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), (255, 255, 255)).save(dest)
        return dest


def _patch_worker_with_fake_client(monkeypatch) -> _FakeComfyClient:
    fake = _FakeComfyClient()
    monkeypatch.setattr(image_worker_mod, "ComfyClient", lambda: fake)
    return fake


def test_image_worker_injects_positive_at_node_14(tmp_path, monkeypatch):
    """Le positive prompt est injecté à wf['14']['inputs']['text']."""
    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    fake = _patch_worker_with_fake_client(monkeypatch)

    worker = ImageWorker()
    worker._update_progress = lambda *args, **kwargs: None

    job = {
        "job_id": "job_inject_pos",
        "entity_id": "img_inject_pos",
        "config": {
            "positive_prompt": "a calm cat outline",
            "workflow_template": "ernie-image-turbo-q8-api",
            "seed": 42,
            "steps": 8,
            "cfg": 1.0,
            "width": 1024,
            "height": 1024,
            "sampler_name": "euler",
            "scheduler": "normal",
        },
    }
    result = worker.process(job)

    # Positive injecté au node 14
    assert fake.submitted_workflow is not None
    assert fake.submitted_workflow["14"]["inputs"]["text"] == "a calm cat outline"
    # KSampler node 16 reçoit les défauts ERNIE
    assert fake.submitted_workflow["16"]["inputs"]["seed"] == 42
    assert fake.submitted_workflow["16"]["inputs"]["steps"] == 8
    assert fake.submitted_workflow["16"]["inputs"]["sampler_name"] == "euler"
    assert fake.submitted_workflow["16"]["inputs"]["scheduler"] == "normal"
    assert float(fake.submitted_workflow["16"]["inputs"]["cfg"]) == 1.0
    # Latent node 13 width/height/batch_size injectés
    assert fake.submitted_workflow["13"]["inputs"]["width"] == 1024
    assert fake.submitted_workflow["13"]["inputs"]["height"] == 1024
    # Pas de __meta__ dans le payload soumis
    assert "__meta__" not in fake.submitted_workflow

    # Generation params persistés
    gen = result["generation_params"]
    assert gen["prompt"] == "a calm cat outline"
    assert gen["workflow_template"] == "ernie-image-turbo-q8-api"
    assert gen["seed"] == 42
    assert gen["sampler_name"] == "euler"


def test_image_worker_ignores_negative_for_ernie(tmp_path, monkeypatch):
    """Même si ``negative_prompt`` est dans job.config, il n'est pas injecté côté ERNIE.

    Le négatif est figé dans le workflow JSON (CLIPTextEncode node 15) depuis 2026-05-05.
    Le worker laisse le node 15 inchangé et stocke ``negative_prompt = ""`` en
    ``generation_params`` pour traçabilité.
    """
    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    fake = _patch_worker_with_fake_client(monkeypatch)

    worker = ImageWorker()
    worker._update_progress = lambda *args, **kwargs: None

    job = {
        "job_id": "job_ignore_neg",
        "entity_id": "img_ignore_neg",
        "config": {
            "positive_prompt": "a horse running",
            "negative_prompt": "blurry, ugly, deformed",
            "workflow_template": "ernie-image-turbo-q8-api",
            "seed": 7,
        },
    }
    result = worker.process(job)

    # Le node 15 (negative) n'est pas modifié — il garde la valeur figée du workflow JSON.
    # Le workflow ERNIE en repo a node 15 = " " (espace). Quoi que ce soit, ça ne doit pas
    # contenir le negative passé en config.
    assert fake.submitted_workflow is not None
    node15_text = fake.submitted_workflow["15"]["inputs"]["text"]
    assert "blurry" not in node15_text
    assert "deformed" not in node15_text

    # generation_params : negative_prompt vidé pour cohérence (non injecté)
    assert result["negative_prompt"] == ""
    assert result["generation_params"]["negative_prompt"] == ""


def test_image_worker_uses_workflow_meta_contract_version(tmp_path, monkeypatch):
    """Le ``contract_version`` est lu depuis le ``__meta__`` du workflow JSON.

    Si présent dans __meta__, il est exposé dans ``generation_params``. Sinon None.
    """
    # On patch WORKFLOWS_DIR pour pointer vers un dossier temporaire avec un workflow custom
    custom_wf_dir = tmp_path / "wf"
    custom_wf_dir.mkdir()
    fake_wf = {
        "__meta__": {
            "description": "test",
            "contract_version": "test_contract_v42",
        },
        "13": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "14": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "15": {"class_type": "CLIPTextEncode", "inputs": {"text": " "}},
        "16": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0, "steps": 8, "cfg": 1.0,
                "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
            },
        },
    }
    (custom_wf_dir / "ernie-image-turbo-q8-api.json").write_text(
        json.dumps(fake_wf), encoding="utf-8"
    )
    monkeypatch.setattr(image_worker_mod, "WORKFLOWS_DIR", custom_wf_dir)
    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path / "out")
    _patch_worker_with_fake_client(monkeypatch)

    worker = ImageWorker()
    worker._update_progress = lambda *args, **kwargs: None

    job = {
        "job_id": "job_meta",
        "entity_id": "img_meta",
        "config": {
            "positive_prompt": "p",
            "workflow_template": "ernie-image-turbo-q8-api",
        },
    }
    result = worker.process(job)
    assert result["generation_params"]["contract_version"] == "test_contract_v42"


def test_image_worker_rejects_non_ernie_workflow(tmp_path, monkeypatch):
    """ERNIE-only : tout autre ``workflow_template`` lève ValueError explicite."""
    monkeypatch.setattr(image_worker_mod, "OUTPUTS_DIR", tmp_path)
    _patch_worker_with_fake_client(monkeypatch)

    worker = ImageWorker()
    worker._update_progress = lambda *args, **kwargs: None

    job = {
        "job_id": "job_z",
        "entity_id": "img_z",
        "config": {
            "positive_prompt": "p",
            "workflow_template": "z_image_turbo_v1",
        },
    }
    with pytest.raises(ValueError, match="ERNIE-only"):
        worker.process(job)
