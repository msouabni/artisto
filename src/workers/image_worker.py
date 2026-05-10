"""Worker pour les jobs image_generation (ComfyUI uniquement — pas de fallback).

MEP v0 ERNIE-only — pattern POC direct (cf. docs/architect/2026-05-10_spec-mep-v0.md §V1.1).
Le worker injecte les valeurs directement par node id sur le workflow ERNIE
(`data/workflows/ernie-image-turbo-q8-api.json`) sans passer par la couche
sidecar/capability/sanitize. Le negative est figé dans le workflow (CLIPTextEncode
node 15) et n'est plus injecté côté Python.
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from pathlib import Path
from typing import Any

from api.job_review_artifact import (
    build_image_generation_artifact,
    build_minimal_image_qc_v1,
    serialize_artifact,
)
from services.image_qc_technical import build_technical_image_qc_v1

from workers.base_worker import BaseWorker, _compute_duration_ms
from workers.comfy_client import (
    ComfyClient,
    ComfyError,
    DEFAULT_WORKFLOW_TEMPLATE,
    workflows_json_dir,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "data" / "outputs"
WORKFLOWS_DIR = workflows_json_dir()

DEFAULT_WORKFLOW = DEFAULT_WORKFLOW_TEMPLATE

# Workflow ERNIE-only en MEP v0 — tout autre template lève une exception explicite.
_ERNIE_TEMPLATE = "ernie-image-turbo-q8-api"

# Défauts d'injection alignés sur le graphe ERNIE (`data/workflows/ernie-image-turbo-q8-api.json`,
# KSampler node 16). Source de vérité pour les paramètres de génération en absence d'override
# explicite dans `job.config`. Conformes aux benchmarks humains 2026-05-06.
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
        workflow_template = config.get("workflow_template", DEFAULT_WORKFLOW)

        # MEP v0 : ERNIE-only. Tout autre template est rejeté explicitement.
        # Cf. docs/architect/2026-05-10_spec-mep-v0.md §V1.1.
        if workflow_template != _ERNIE_TEMPLATE:
            raise ValueError(
                f"workflow_template '{workflow_template}' non supporté en MEP v0 ERNIE-only "
                f"(seul '{_ERNIE_TEMPLATE}' est accepté)."
            )

        out_filename = f"{entity_id}_{job_id}.png"
        out_path = OUTPUTS_DIR / out_filename
        rel_path = f"outputs/{out_filename}"
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

        client = ComfyClient()
        if not client.is_available():
            raise ComfyUnavailableError("ComfyUI non disponible")

        # Pattern POC direct (cf. scripts/poc_bench_gate_ernie.py::submit_to_comfy lignes 230-248)
        wf_path = WORKFLOWS_DIR / f"{workflow_template}.json"
        wf = json.loads(wf_path.read_text(encoding="utf-8-sig"))
        contract_version = wf.get("__meta__", {}).get("contract_version")
        wf.pop("__meta__", None)

        # Lecture des valeurs avec fallback sur defaults ERNIE
        seed = int(config.get("seed", random.randint(0, 2**32 - 1)))
        steps = int(config.get("steps", _ERNIE_SAMPLER_DEFAULTS["steps"]))
        cfg = float(config.get("cfg", _ERNIE_SAMPLER_DEFAULTS["cfg"]))
        width = int(config.get("width", _ERNIE_SAMPLER_DEFAULTS["width"]))
        height = int(config.get("height", _ERNIE_SAMPLER_DEFAULTS["height"]))
        batch_size = int(config.get("batch_size", _ERNIE_SAMPLER_DEFAULTS["batch_size"]))
        sampler_name = config.get("sampler_name", _ERNIE_SAMPLER_DEFAULTS["sampler_name"])
        scheduler = config.get("scheduler", _ERNIE_SAMPLER_DEFAULTS["scheduler"])
        denoise = float(config.get("denoise", _ERNIE_SAMPLER_DEFAULTS["denoise"]))

        # Injection directe par node id (mapping ERNIE connu — cf. workflow JSON)
        wf["13"]["inputs"]["width"] = width
        wf["13"]["inputs"]["height"] = height
        wf["13"]["inputs"]["batch_size"] = batch_size
        wf["14"]["inputs"]["text"] = prompt           # positive
        # NE PAS injecter wf["15"] (negative) — figé dans le workflow depuis 2026-05-05
        wf["16"]["inputs"]["seed"] = seed
        wf["16"]["inputs"]["steps"] = steps
        wf["16"]["inputs"]["sampler_name"] = sampler_name
        wf["16"]["inputs"]["scheduler"] = scheduler
        wf["16"]["inputs"]["cfg"] = cfg

        external_ref_id = client.submit_prompt(wf)
        negative_prompt_meta = ""  # negative figé dans workflow, pas du payload côté ERNIE

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
            "contract_version": contract_version,
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "width": width,
            "height": height,
            "batch_size": batch_size,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": denoise,
        }
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
            # Trigger QC auto sur l'image_output fraîchement créé.
            # Best-effort : un échec d'enqueue ne doit jamais faire échouer
            # la génération (le QC peut être relancé à la main via API).
            try:
                self._enqueue_qc_job(conn, out_id, now)
            except Exception as exc:
                logger.warning(
                    "Échec enqueue image_qc_auto pour image_output=%s : %s",
                    out_id,
                    exc,
                )
            conn.session.commit()
        finally:
            conn.close()

    def _enqueue_qc_job(self, conn, image_output_id: str, now: str) -> None:
        """Crée un job ``image_qc_auto`` avec ``entity_id=<image_output_id>``.

        N'enqueue rien si la table ``job_type_config`` n'a pas la ligne
        ``image_qc_auto`` (déploiement progressif). Idempotence simple :
        un seul job pending par image_output_id.
        """
        cfg_row = conn.execute(
            "SELECT 1 FROM job_type_config WHERE type = ?",
            ["image_qc_auto"],
        ).fetchone()
        if not cfg_row:
            return
        existing = conn.execute(
            """
            SELECT id FROM job
            WHERE type = ? AND entity_id = ? AND status IN ('pending', 'running')
            LIMIT 1
            """,
            ["image_qc_auto", image_output_id],
        ).fetchone()
        if existing:
            return
        qc_job_id = f"qc_{image_output_id}_{uuid.uuid4().hex[:8]}"
        conn.execute(
            """
            INSERT INTO job (id, type, status, config, created_at, priority,
                              retry_count, max_retries, entity_type, entity_id)
            VALUES (?, ?, 'pending', '{}', ?, 5, 0, 3, 'image_output', ?)
            """,
            [qc_job_id, "image_qc_auto", now, image_output_id],
        )

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
