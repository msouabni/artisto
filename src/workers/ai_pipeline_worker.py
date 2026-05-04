"""Worker Ollama : file d'attente unifiée (taxonomie, prompts image, texte libre)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from api.job_review_artifact import (
    build_image_concepts_artifact,
    build_image_text_patch_artifact,
    build_taxonomy_batch_patch_artifact,
    build_taxonomy_import_ops_artifact,
    build_term_patch_artifact,
    normalize_flat_term_suggestions_to_proposal,
    serialize_artifact,
)
from services.ai_jobs_sync import (
    run_generate_concepts_sync,
    run_generate_prompts_sync,
    run_image_prompt_create_sync,
    run_image_prompt_improve_sync,
    run_image_prompt_validate_sync,
    run_prompts_bulk_sync,
    run_suggest_prompt_sync,
    run_taxonomy_enrich_keywords_sync,
    run_taxonomy_enrich_term_sync,
    run_taxonomy_enrich_terms_batch_sync,
    run_taxonomy_generate_vocabulary_sync,
    run_taxonomy_suggest_children_sync,
    run_text_enrichment_sync,
)

from workers.base_worker import BaseWorker, _compute_duration_ms

logger = logging.getLogger(__name__)

AI_PIPELINE_JOB_TYPES = (
    "text_enrichment",
    "taxonomy_enrich_term",
    "taxonomy_enrich_terms_batch",
    "taxonomy_enrich_keywords",
    "taxonomy_suggest_children",
    "taxonomy_generate_vocabulary",
    "image_prompt_create",
    "image_prompt_improve",
    "image_prompt_validate",
    "image_generate_concepts",
    "image_generate_prompts",
    "image_prompt_suggest",
    "image_prompts_bulk",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _terms_batch_to_patch(suggestions: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tid, sug in suggestions.items():
        if not isinstance(sug, dict):
            continue
        prop = normalize_flat_term_suggestions_to_proposal(sug)
        if prop:
            out[tid] = prop
        else:
            out[tid] = sug
    return out


def _suggestions_to_add_ops(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for item in items:
        vid = item.get("id")
        if not vid:
            continue
        ops.append(
            {
                "op": "add",
                "value": {
                    "id": str(vid),
                    "slug": str(item.get("slug") or vid),
                    "name_fr": item.get("name_fr", ""),
                    "name_en": item.get("name_en", ""),
                    "name_ar": item.get("name_ar", ""),
                    "description_fr": item.get("description_fr", ""),
                    "description_en": item.get("description_en", ""),
                    "description_ar": item.get("description_ar", ""),
                    "weight": int(item.get("weight", 0)),
                    "parent_id": item.get("parent_id"),
                    "keywords": item.get("keywords", []) if isinstance(item.get("keywords"), list) else [],
                },
            }
        )
    return ops


class AiPipelineWorker(BaseWorker):
    """Traite les jobs IA texte / taxonomie / prompts image via la même boucle worker."""

    job_type = "text_enrichment"
    job_types = AI_PIPELINE_JOB_TYPES
    category = "text"

    def process(self, job: dict[str, Any]) -> dict[str, Any]:
        jt = job.get("type") or ""
        config = job.get("config") or {}
        if jt == "text_enrichment":
            return run_text_enrichment_sync(config)
        conn = self._conn(read_only=False)
        try:
            if jt == "taxonomy_enrich_term":
                return run_taxonomy_enrich_term_sync(conn, config)
            if jt == "taxonomy_enrich_terms_batch":
                return run_taxonomy_enrich_terms_batch_sync(conn, config)
            if jt == "taxonomy_enrich_keywords":
                return run_taxonomy_enrich_keywords_sync(conn, config)
            if jt == "taxonomy_suggest_children":
                return run_taxonomy_suggest_children_sync(conn, config)
            if jt == "taxonomy_generate_vocabulary":
                return run_taxonomy_generate_vocabulary_sync(conn, config)
            if jt == "image_prompt_create":
                return run_image_prompt_create_sync(conn, config)
            if jt == "image_prompt_improve":
                return run_image_prompt_improve_sync(conn, config)
            if jt == "image_prompt_validate":
                return run_image_prompt_validate_sync(conn, config)
            if jt == "image_generate_concepts":
                return run_generate_concepts_sync(conn, config)
            if jt == "image_generate_prompts":
                return run_generate_prompts_sync(conn, config)
            if jt == "image_prompt_suggest":
                return run_suggest_prompt_sync(conn, config)
            if jt == "image_prompts_bulk":
                return run_prompts_bulk_sync(conn, config)
        finally:
            conn.close()
        raise ValueError(f"Type de job non géré : {jt!r}")

    def save_result(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        job_id = job["job_id"]
        jt = job.get("type") or ""
        config = job.get("config") or {}
        now = _now()
        duration_ms = _compute_duration_ms(job)

        if result.get("skipped"):
            result_json = json.dumps(
                {"status": "skipped", "message": result.get("message", ""), "detail": result},
                ensure_ascii=False,
            )
            conn = self._conn(read_only=False)
            try:
                conn.execute(
                    """
                    UPDATE job SET status = 'completed', finished_at = ?, result = ?, duration_ms = ?
                    WHERE id = ?
                    """,
                    [now, result_json, duration_ms, job_id],
                )
                conn.session.commit()
            finally:
                conn.close()
            return

        artifact: dict[str, Any] | None = None

        if jt == "text_enrichment":
            raw = result.get("result", result)
            entity_type = job.get("entity_type") or "term"
            entity_id = job.get("entity_id") or ""
            if isinstance(raw, dict):
                if entity_type == "term":
                    proposal = normalize_flat_term_suggestions_to_proposal(raw)
                    if not proposal:
                        proposal = raw
                else:
                    proposal = raw
            else:
                proposal = {}
            artifact = build_term_patch_artifact(
                entity_type=entity_type,
                entity_id=entity_id,
                proposal=proposal,
                job_type=jt,
            )

        elif jt == "taxonomy_enrich_term":
            vocabulary_id = str(config.get("vocabulary_id") or "")
            term_id = str(config.get("term_id") or "")
            sug = result.get("suggestions") or {}
            proposal = normalize_flat_term_suggestions_to_proposal(sug) if isinstance(sug, dict) else {}
            artifact = build_term_patch_artifact(
                entity_type="term",
                entity_id=term_id,
                proposal=proposal,
                job_type=jt,
                preview={"vocabulary_id": vocabulary_id},
            )

        elif jt == "taxonomy_enrich_terms_batch":
            vocabulary_id = str(config.get("vocabulary_id") or "")
            suggestions = result.get("suggestions") or {}
            terms_patch = _terms_batch_to_patch(suggestions) if isinstance(suggestions, dict) else {}
            artifact = build_taxonomy_batch_patch_artifact(
                vocabulary_id=vocabulary_id,
                terms_patch=terms_patch,
                job_type=jt,
            )

        elif jt == "taxonomy_enrich_keywords":
            term_id = str(config.get("term_id") or "")
            vocabulary_id = str(config.get("vocabulary_id") or "")
            kws = result.get("suggestions_keywords") or []
            joined = ", ".join(kws) if isinstance(kws, list) else str(kws)
            artifact = build_term_patch_artifact(
                entity_type="term",
                entity_id=term_id,
                proposal={"keywords": joined},
                job_type=jt,
                preview={"vocabulary_id": vocabulary_id},
            )

        elif jt == "taxonomy_suggest_children":
            vocabulary_id = str(config.get("vocabulary_id") or "")
            ops = _suggestions_to_add_ops(result.get("suggestions") or [])
            artifact = build_taxonomy_import_ops_artifact(
                vocabulary_id=vocabulary_id,
                operations=ops,
                job_type=jt,
            )

        elif jt == "taxonomy_generate_vocabulary":
            vocabulary_id = str(config.get("target_vocabulary_id") or config.get("vocabulary_id") or "").strip()
            if not vocabulary_id:
                raise ValueError("config.target_vocabulary_id ou vocabulary_id requis pour appliquer l'import")
            ops = _suggestions_to_add_ops(result.get("suggestions_flat") or [])
            artifact = build_taxonomy_import_ops_artifact(
                vocabulary_id=vocabulary_id,
                operations=ops,
                job_type=jt,
            )

        elif jt == "image_prompt_create":
            image_id = str(config.get("image_id") or job.get("entity_id") or "").strip()
            if not image_id:
                raise ValueError("config.image_id ou entity_id requis pour l'artefact image")
            artifact = build_image_text_patch_artifact(
                entity_id=image_id,
                proposal={
                    "prompt": result.get("prompt", ""),
                    "negative_prompt": result.get("negative_prompt", ""),
                },
                job_type=jt,
            )

        elif jt == "image_prompt_improve":
            image_id = str(config.get("image_id") or job.get("entity_id") or "").strip()
            if not image_id:
                raise ValueError("config.image_id ou entity_id requis")
            suggestions = result.get("suggestions") or []
            first = suggestions[0] if suggestions and isinstance(suggestions[0], dict) else {}
            artifact = build_image_text_patch_artifact(
                entity_id=image_id,
                proposal={
                    "prompt": first.get("prompt", ""),
                    "negative_prompt": first.get("negative_prompt", ""),
                },
                job_type=jt,
            )

        elif jt == "image_prompt_validate":
            image_id = str(config.get("image_id") or job.get("entity_id") or "").strip()
            prompt_echo = str(config.get("prompt") or "")
            if not image_id:
                raise ValueError("config.image_id ou entity_id requis")
            artifact = build_image_text_patch_artifact(
                entity_id=image_id,
                proposal={
                    "prompt": prompt_echo,
                    "validation": {
                        "score": result.get("score"),
                        "checks": result.get("checks"),
                        "recommendations": result.get("recommendations"),
                    },
                },
                job_type=jt,
            )

        elif jt == "image_generate_concepts":
            suggestions = result.get("suggestions") or []
            if not suggestions:
                result_json = json.dumps(
                    {
                        "status": "skipped",
                        "message": "Aucun concept exploitable après nettoyage.",
                        "detail": result,
                    },
                    ensure_ascii=False,
                )
                conn2 = self._conn(read_only=False)
                try:
                    conn2.execute(
                        """
                        UPDATE job SET status = 'completed', finished_at = ?, result = ?, duration_ms = ?
                        WHERE id = ?
                        """,
                        [now, result_json, duration_ms, job_id],
                    )
                    conn2.session.commit()
                finally:
                    conn2.close()
                return
            theme = str(result.get("theme") or config.get("theme") or "")
            anchor = None
            tid = str(config.get("term_id") or "").strip()
            vid = str(config.get("vocabulary_id") or "").strip()
            if tid and vid:
                anchor = {"term_id": tid, "vocabulary_id": vid}
            artifact = build_image_concepts_artifact(
                job_id=job_id,
                theme=theme,
                suggestions=suggestions if isinstance(suggestions, list) else [],
                anchor=anchor,
                job_type=jt,
            )

        elif jt == "image_generate_prompts":
            suggestions = result.get("suggestions") or []
            image_id = str(config.get("image_id") or job.get("entity_id") or "").strip()
            artifact = build_image_text_patch_artifact(
                entity_id=image_id or "unknown",
                proposal={"suggestions": suggestions},
                job_type=jt,
            )

        elif jt == "image_prompt_suggest":
            image_id = str(config.get("image_id") or job.get("entity_id") or "").strip()
            suggestions = result.get("suggestions") or []
            first = suggestions[0] if suggestions and isinstance(suggestions[0], dict) else {}
            artifact = build_image_text_patch_artifact(
                entity_id=image_id or "unknown",
                proposal={
                    "prompt": first.get("prompt", ""),
                    "negative_prompt": first.get("negative_prompt", ""),
                    "suggestions": suggestions,
                },
                job_type=jt,
            )

        elif jt == "image_prompts_bulk":
            results_list = result.get("results") or []
            summary = result.get("summary") or {}
            # entity_id = first image_id present in results, or fallback to job entity_id
            first_image_id = next(
                (str(r.get("image_id") or "") for r in results_list if r.get("image_id")),
                str(job.get("entity_id") or ""),
            )
            artifact = build_image_text_patch_artifact(
                entity_id=first_image_id or "unknown",
                proposal={"results": results_list, "summary": summary},
                job_type=jt,
            )

        if artifact is None:
            raise ValueError(f"Artefact non construit pour le type {jt}")

        result_json = serialize_artifact(artifact)
        conn = self._conn(read_only=False)
        try:
            conn.execute(
                """
                UPDATE job SET status = 'awaiting_validation', finished_at = ?, result = ?, duration_ms = ?
                WHERE id = ?
                """,
                [now, result_json, duration_ms, job_id],
            )
            conn.session.commit()
        finally:
            conn.close()
