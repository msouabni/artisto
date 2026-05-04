"""Payload structuré pour la revue humaine des jobs ``image_generation`` (hors diff générique)."""
from __future__ import annotations

from typing import Any

from api.job_review_artifact import (
    ARTIFACT_IMAGE_GENERATION_OUTPUT,
    build_minimal_image_qc_v1,
    is_wrapped_v1,
)


def _status_will_become_generated(current_status: str | None) -> str:
    transitional = {"scheduled", "generating", "draft", "prompt_ready"}
    if (current_status or "") in transitional:
        return "generated"
    return current_status or ""


def build_image_generation_review_payload(
    *,
    job_id: str,
    job_status: str,
    entity_id: str,
    stored: dict[str, Any],
    image_status: str | None,
    image_selected_output_id: str | None,
) -> dict[str, Any]:
    """Assemble le JSON ``GET /api/jobs/{id}/review`` à partir du résultat stocké et de l'état image courant.

    Si l'artefact n'est pas un ``image_generation_output`` v1, renvoie un payload minimal avec ``legacy: true``.
    """
    preview_block = stored.get("preview") if isinstance(stored.get("preview"), dict) else {}
    resources = stored.get("resources") if isinstance(stored.get("resources"), dict) else {}
    apply_plan = stored.get("apply_plan") if isinstance(stored.get("apply_plan"), dict) else {}

    if not is_wrapped_v1(stored) or stored.get("artifact_type") != ARTIFACT_IMAGE_GENERATION_OUTPUT:
        rel_path = ""
        if isinstance(preview_block, dict):
            rel_path = str(preview_block.get("rel_path") or "")
        if not rel_path and isinstance(resources, dict):
            rel_path = str(resources.get("rel_path") or "")
        return {
            "job_id": job_id,
            "status": job_status,
            "entity_id": entity_id,
            "artifact_type": stored.get("artifact_type") if isinstance(stored, dict) else None,
            "legacy": True,
            "legacy_note": "Résultat sans enveloppe v1 image_generation_output ; revue limitée.",
            "preview": {
                "rel_path": rel_path,
                "image_url": f"/api/jobs/{job_id}/output-image",
                "prompt": str(preview_block.get("prompt_echo") or stored.get("prompt") or ""),
                "negative_prompt": str(
                    preview_block.get("negative_prompt_echo") or stored.get("negative_prompt") or ""
                ),
            },
            "qc": stored.get("qc") if isinstance(stored.get("qc"), dict) else build_minimal_image_qc_v1(),
            "apply_plan_summary": [],
            "resources": resources if isinstance(resources, dict) else {},
            "reject_plan_summary": [
                {
                    "action": "delete_output_file",
                    "detail": "Supprime le fichier PNG associé à l'output du job (si présent).",
                },
                {
                    "action": "delete_image_output_row",
                    "detail": "Supprime la ligne ``image_output`` du job.",
                },
                {
                    "action": "update_image_status",
                    "field": "status",
                    "to": "prompt_ready",
                    "detail": "Remet l'image en ``prompt_ready`` si elle était en ``generating``.",
                },
            ],
        }

    qc = stored.get("qc")
    if not isinstance(qc, dict):
        qc = build_minimal_image_qc_v1()

    out_id = str(apply_plan.get("output_id") or resources.get("image_output_id") or "").strip()
    rel_path = str(preview_block.get("rel_path") or resources.get("rel_path") or "")

    new_status = _status_will_become_generated(image_status)
    apply_plan_summary: list[dict[str, Any]] = [
        {
            "entity": "image",
            "id": entity_id,
            "field": "status",
            "from": image_status,
            "to": new_status,
            "note": None
            if new_status == "generated"
            else "Le statut ne change pas (hors brouillon / prompt_ready / generating / scheduled).",
        },
        {
            "entity": "image",
            "id": entity_id,
            "field": "selected_output_id",
            "from": image_selected_output_id,
            "to": out_id or None,
        },
    ]

    reject_plan_summary: list[dict[str, Any]] = [
        {
            "action": "delete_output_file",
            "detail": "Supprime le fichier PNG sur disque (chemins relatifs sous ``data/``).",
        },
        {
            "action": "delete_image_output_row",
            "detail": "Supprime la ligne ``image_output`` liée à ce job.",
        },
        {
            "action": "update_image_status",
            "field": "status",
            "to": "prompt_ready",
            "detail": "Si l'image est en ``generating``, repasse en ``prompt_ready`` pour régénérer.",
        },
    ]

    return {
        "job_id": job_id,
        "status": job_status,
        "entity_id": entity_id,
        "artifact_type": ARTIFACT_IMAGE_GENERATION_OUTPUT,
        "legacy": False,
        "preview": {
            "rel_path": rel_path,
            "image_url": f"/api/jobs/{job_id}/output-image",
            "prompt": str(preview_block.get("prompt_echo") or ""),
            "negative_prompt": str(preview_block.get("negative_prompt_echo") or ""),
        },
        "qc": qc,
        "apply_plan_summary": apply_plan_summary,
        "resources": resources,
        "reject_plan_summary": reject_plan_summary,
        "review_summary": str(stored.get("review_summary") or ""),
    }
