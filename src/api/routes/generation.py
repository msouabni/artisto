"""Paramètres de génération d'image (ComfyUI) — presets pour l'UI et l'API."""
from __future__ import annotations

from fastapi import APIRouter

from api.helpers import json_response
from workers.comfy_client import DEFAULT_WORKFLOW_TEMPLATE, list_workflow_template_names, workflows_json_dir

router = APIRouter(prefix="/api/generation", tags=["generation"])

# Aligné sur ComfyUI `blueprints/Text to Image (Z-Image-Turbo).json`
# (sous-graphe : KSampler widgets + ModelSamplingAuraFlow.shift).
COMFY_BLUEPRINT_TEXT_TO_IMAGE_Z_IMAGE_TURBO: dict[str, int | float | str] = {
    "steps": 4,
    "cfg": 1.0,
    "sampler_name": "res_multistep",
    "scheduler": "simple",
    "denoise": 1.0,
    "shift": 3.0,
    "width": 1024,
    "height": 1024,
}
COMFY_BLUEPRINT_SOURCE = (
    "ComfyUI blueprints/Text to Image (Z-Image-Turbo).json "
    "(nœud KSampler : res_multistep / simple ; steps=4 dans le blueprint livré)."
)

# Aligné sur `data/workflows/ernie-image-turbo-q8-api.json` (nœud 16 KSampler).
COMFY_BLUEPRINT_ERNIE_IMAGE_TURBO_Q8_API: dict[str, int | float | str] = {
    "steps": 8,
    "cfg": 1.0,
    "sampler_name": "euler",
    "scheduler": "normal",
    "denoise": 1.0,
    "width": 1024,
    "height": 1024,
}
COMFY_BLUEPRINT_ERNIE_SOURCE = (
    "data/workflows/ernie-image-turbo-q8-api.json (KSampler : euler / normal ; steps=8)."
)

# Options courantes pour KSampler + ModelSamplingAuraFlow (z_image_turbo_v1).
SAMPLER_NAMES = [
    "euler",
    "res_multistep",
    "dpmpp_2m",
    "uni_pc",
    "dpmpp_2m_sde",
]
SCHEDULERS = [
    "simple",
    "normal",
    "karras",
    "sgm_uniform",
]

DEFAULTS = dict(COMFY_BLUEPRINT_ERNIE_IMAGE_TURBO_Q8_API)


@router.get("/presets")
def generation_presets():
    """Valeurs par défaut et listes d'options pour le panneau « paramètres avancés »."""
    wf_dir = workflows_json_dir()
    return json_response({
        "sampler_names": SAMPLER_NAMES,
        "schedulers": SCHEDULERS,
        "defaults": DEFAULTS,
        "comfy_blueprint_text_to_image_z_image_turbo": COMFY_BLUEPRINT_TEXT_TO_IMAGE_Z_IMAGE_TURBO,
        "comfy_blueprint_ernie_image_turbo_q8_api": COMFY_BLUEPRINT_ERNIE_IMAGE_TURBO_Q8_API,
        "comfy_blueprint_source": COMFY_BLUEPRINT_SOURCE,
        "comfy_blueprint_ernie_source": COMFY_BLUEPRINT_ERNIE_SOURCE,
        "workflow_templates": list_workflow_template_names(wf_dir),
        "default_workflow_template": DEFAULT_WORKFLOW_TEMPLATE,
    })
