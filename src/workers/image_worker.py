"""Worker pour les jobs image_generation (ComfyUI uniquement — pas de fallback)."""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from api.job_review_artifact import (
    build_image_generation_artifact,
    build_minimal_image_qc_v1,
    serialize_artifact,
)
from services.image_qc_technical import build_technical_image_qc_v1

from workers.base_worker import BaseWorker, _compute_duration_ms
from workers.comfy_client import DEFAULT_WORKFLOW_TEMPLATE, workflows_json_dir

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "data" / "outputs"
WORKFLOWS_DIR = workflows_json_dir()

DEFAULT_WORKFLOW = DEFAULT_WORKFLOW_TEMPLATE

# Défauts d’injection alignés sur les graphes `data/workflows/*.json` (KSampler public).
_Z_IMAGE_SAMPLER_DEFAULTS: dict[str, Any] = {
    "steps": 4,
    "cfg": 1.0,
    "width": 1024,
    "height": 1024,
    "batch_size": 1,
    "sampler_name": "res_multistep",
    "scheduler": "simple",
    "denoise": 1.0,
    "shift": 3,
}
_ERNIE_SAMPLER_DEFAULTS: dict[str, Any] = {
    "steps": 8,
    "cfg": 1.0,
    "width": 1024,
    "height": 1024,
    "batch_size": 1,
    "sampler_name": "euler",
    "scheduler": "normal",
    "denoise": 1.0,
}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ComfyUnavailableError(Exception):
    """Levée quand ComfyUI est indisponible avant même l'exécution d'un workflow."""


class ImageWorker(BaseWorker):
    """Worker image_generation — ComfyUI uniquement, piloté par contrat workflow.

    Les erreurs de workflow (OOM, mapping, validation Comfy) ne doivent pas couper
    globalement `image_generation` : elles suivent la politique de retry du worker de base.
    """

    job_type = "image_generation"
    category = "image"

    def fetch_and_start(self) -> dict[str, Any] | None:
        """Marque l'image en 'generating' quand le worker prend le job."""
        job = super().fetch_and_start()
        if job:
            entity_id = job.get("entity_id") or job.get("image_id")
            if entity_id:
                conn = self._conn(read_only=False)
                try:
                    conn.execute(
                        """UPDATE image SET status = 'generating', updated_at = ?
                           WHERE id = ? AND status = 'scheduled'""",
                        [_now(), entity_id],
                    )
                    conn.session.commit()
                finally:
                    conn.close()
        return job

    def process(self, job: dict[str, Any]) -> dict[str, Any]:
        entity_id = job.get("entity_id") or job.get("image_id")
        job_id = job["job_id"]
        config = job.get("config", {})
        prompt = str(config.get("positive_prompt") or config.get("prompt") or "")
        raw_neg = config.get("negative_prompt", "")
        stripped_job_neg = str(raw_neg or "").strip()
        workflow_template = config.get("workflow_template", DEFAULT_WORKFLOW)

        out_filename = f"{entity_id}_{job_id}.png"
        out_path = OUTPUTS_DIR / out_filename
        rel_path = f"outputs/{out_filename}"
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

        external_ref_id: str | None = None

        from workers.comfy_client import (
            ComfyClient,
            ComfyError,
            apply_overrides,
            load_workflow_template,
            sanitize_public_workflow_inputs,
        )
        client = ComfyClient()
        if not client.is_available():
            raise ComfyUnavailableError("ComfyUI non disponible")

        wf_base, public_inputs_map, contract = load_workflow_template(WORKFLOWS_DIR, workflow_template)
        negative_prompt_meta = stripped_job_neg
        base_sampler = (
            _Z_IMAGE_SAMPLER_DEFAULTS
            if workflow_template == "z_image_turbo_v1"
            else _ERNIE_SAMPLER_DEFAULTS
        )
        candidate_values: dict[str, Any] = {
            "positive_prompt": prompt,
            "negative_prompt": stripped_job_neg,
            "seed": config.get("seed", random.randint(0, 2**32 - 1)),
        }
        for key, default in base_sampler.items():
            candidate_values[key] = config[key] if key in config else default

        override_values = sanitize_public_workflow_inputs(candidate_values, contract)
        seed = int(override_values.get("seed", candidate_values["seed"]))
        steps = int(override_values.get("steps", candidate_values["steps"]))
        cfg = override_values.get("cfg", candidate_values["cfg"])
        width = int(override_values.get("width", candidate_values["width"]))
        height = int(override_values.get("height", candidate_values["height"]))
        sampler_name = override_values.get("sampler_name", candidate_values["sampler_name"])
        scheduler = override_values.get("scheduler", candidate_values["scheduler"])
        denoise = override_values.get("denoise", candidate_values["denoise"])
        shift = override_values.get("shift", candidate_values.get("shift"))
        workflow = apply_overrides(wf_base, public_inputs_map, override_values)
        if "negative_prompt" not in override_values:
            negative_prompt_meta = ""
        external_ref_id = client.submit_prompt(workflow)

        def _progress(pct: int, msg: str) -> None:
            self._update_progress(job_id, pct, msg)

        history = client.poll_until_done(external_ref_id, progress_callback=_progress)
        images = client.extract_output_images(history)
        if not images:
            raise ComfyError("Aucune image dans l'historique ComfyUI")

        first = images[0]
        client.download_image(
            filename=first["filename"],
            dest=out_path,
            subfolder=first.get("subfolder", ""),
            folder_type=first.get("type", "output"),
        )
        logger.info("ComfyUI : image générée → %s", out_path)
        generation_params: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt_meta,
            "workflow_template": workflow_template,
            "contract_version": contract.get("contract_version"),
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "width": width,
            "height": height,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": denoise,
        }
        if shift is not None:
            generation_params["shift"] = shift
        return {
            "entity_id": entity_id,
            "rel_path": rel_path,
            "prompt": prompt,
            "negative_prompt": negative_prompt_meta,
            "used_comfy": True,
            "external_ref_id": external_ref_id,
            "generation_params": generation_params,
        }

    def save_result(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        """Enregistre image_output, met à jour job et image."""
        job_id = job["job_id"]
        entity_id = result["entity_id"]
        rel_path = result["rel_path"]
        prompt = result["prompt"]
        used_comfy = result.get("used_comfy", False)
        external_ref_id = result.get("external_ref_id")
        gen = result.get("generation_params") or {}
        wt = str((gen.get("workflow_template") or "")).lower()
        if used_comfy and "ernie" in wt:
            model_name = "ernie-image-turbo-q8-api"
        elif used_comfy:
            model_name = "z_image_turbo_bf16"
        else:
            model_name = "pillow_placeholder"
        out_w = int(gen.get("width", 1024) or 1024)
        out_h = int(gen.get("height", 1024) or 1024)
        model_config = json.dumps(gen if gen else {"prompt": prompt})

        abs_image = OUTPUTS_DIR / Path(rel_path).name
        try:
            qc_report = build_technical_image_qc_v1(abs_image)
        except Exception as e:
            logger.warning("QC technique : exception inattendue sur %s (%s)", abs_image, e)
            qc_report = build_minimal_image_qc_v1()
            qc_report["flags"] = ["qc_technical_error"]
            qc_report["checks"] = [
                {
                    "id": "technical_qc",
                    "pass": False,
                    "detail": str(e),
                    "severity": "fail",
                }
            ]
            qc_report["status"] = "fail"
            qc_report["recommendations"] = ["Erreur lors de l'analyse QC technique."]

        conn = self._conn(read_only=False)
        try:
            now = _now()
            out_id = f"out_{job_id}"
            duration_ms = _compute_duration_ms(job)
            conn.execute(
                """
                INSERT INTO image_output
                (id, image_id, job_id, file_path, file_format, width, height, model_name, model_config, created_at)
                VALUES (?, ?, ?, ?, 'png', ?, ?, ?, ?, ?)
                """,
                [out_id, entity_id, job_id, rel_path, out_w, out_h, model_name, model_config, now],
            )
            artifact = build_image_generation_artifact(
                entity_id=entity_id,
                image_output_id=out_id,
                rel_path=rel_path,
                generation_params=gen if gen else {"prompt": prompt},
                prompt=prompt,
                negative_prompt=str(result.get("negative_prompt") or ""),
                external_ref_id=external_ref_id,
                qc=qc_report,
            )
            result_payload = serialize_artifact(artifact)
            if external_ref_id:
                conn.execute(
                    """
                    UPDATE job SET status = 'awaiting_validation', finished_at = ?, progress = 100,
                                   result = ?, external_ref_id = ?, duration_ms = ?
                    WHERE id = ?
                    """,
                    [now, result_payload, external_ref_id, duration_ms, job_id],
                )
            else:
                conn.execute(
                    """
                    UPDATE job SET status = 'awaiting_validation', finished_at = ?, progress = 100,
                                   result = ?, duration_ms = ?
                    WHERE id = ?
                    """,
                    [now, result_payload, duration_ms, job_id],
                )
            conn.session.commit()
        finally:
            conn.close()

    def handle_failure(self, job: dict[str, Any], error: Exception) -> None:
        """Conserve la politique de retry du worker de base et remet l'image dans un état lisible."""
        job_id = job["job_id"]
        entity_id = job.get("entity_id") or job.get("image_id")
        retry_count = job.get("retry_count", 0)
        max_retries = job.get("max_retries", 3)
        will_retry = retry_count < max_retries

        super().handle_failure(job, error)

        if entity_id:
            conn = self._conn(read_only=False)
            try:
                target_status = "scheduled" if will_retry else "prompt_ready"
                conn.execute(
                    """UPDATE image SET status = ?, updated_at = ?
                       WHERE id = ? AND status IN ('generating', 'scheduled')""",
                    [target_status, _now(), entity_id],
                )
                conn.session.commit()
            finally:
                conn.close()
        logger.info(
            "Job %s géré après échec ComfyUI (%s) ; prochaine étape=%s",
            job_id,
            type(error).__name__,
            "retry" if will_retry else "failed",
        )
