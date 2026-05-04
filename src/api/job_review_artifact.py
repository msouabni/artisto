"""Contrat canonique `job.result` pour la revue humaine (workflow_contract_v1 côté jobs).

- Enveloppe v1 : métadonnées + `proposal` (patch métier) + `preview` / `resources` / `apply_plan`.
- Compatibilité : résultats historiques sans enveloppe (dict JSON brut) traités comme `proposal` seul.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACT_VERSION = 1

# Types d'artefacts reconnus par le dispatcher apply/diff
ARTIFACT_TERM_PATCH = "term_patch"
ARTIFACT_IMAGE_TEXT_PATCH = "image_text_patch"
ARTIFACT_IMAGE_GENERATION_OUTPUT = "image_generation_output"
ARTIFACT_TAXONOMY_BATCH_PATCH = "taxonomy_batch_patch"
ARTIFACT_TAXONOMY_IMPORT_OPS = "taxonomy_import_ops"
ARTIFACT_IMAGE_CONCEPTS_PROPOSAL = "image_concepts_proposal"


def build_minimal_image_qc_v1() -> dict[str, Any]:
    """Rapport QC image v1 avant exécution des checks (scores remplis aux étapes suivantes).

    ``status`` ``pending`` signifie qu'aucune analyse image n'a encore été appliquée.
    """
    return {
        "schema_version": 1,
        "overall_score": 0,
        "technical_score": 0,
        "relevance_score": 0,
        "safety_score": 0,
        "status": "pending",
        "flags": ["qc_not_evaluated"],
        "checks": [],
        "recommendations": [],
    }


def is_wrapped_v1(data: dict[str, Any]) -> bool:
    return bool(
        data.get("artifact_version") == ARTIFACT_VERSION
        and data.get("artifact_type")
    )


def parse_stored_job_result(result_json: str | None) -> dict[str, Any]:
    if not result_json or not str(result_json).strip():
        return {}
    try:
        data = json.loads(result_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def get_proposal_for_diff(stored: dict[str, Any]) -> dict[str, Any]:
    """Extrait le dict « proposé » pour comparaison avec l'entité courante (diff field-level)."""
    if is_wrapped_v1(stored):
        prop = stored.get("proposal")
        return prop if isinstance(prop, dict) else {}
    return stored


def build_term_patch_artifact(
    *,
    entity_type: str,
    entity_id: str,
    proposal: dict[str, Any],
    job_type: str,
    review_summary: str = "",
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enveloppe v1 pour enrichissement terme / texte."""
    return {
        "artifact_version": ARTIFACT_VERSION,
        "artifact_type": ARTIFACT_TERM_PATCH,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "job_type": job_type,
        "proposal": proposal,
        "review_summary": review_summary,
        "preview": preview or {},
        "apply_plan": {"mode": "merge_entity_fields"},
        "resources": {},
    }


def build_taxonomy_batch_patch_artifact(
    *,
    vocabulary_id: str,
    terms_patch: dict[str, Any],
    job_type: str,
    review_summary: str = "",
) -> dict[str, Any]:
    """Plusieurs termes : clés = term_id, valeurs = patch champs (name_i18n, …)."""
    return {
        "artifact_version": ARTIFACT_VERSION,
        "artifact_type": ARTIFACT_TAXONOMY_BATCH_PATCH,
        "entity_type": "taxonomy_batch",
        "entity_id": vocabulary_id,
        "job_type": job_type,
        "proposal": {"vocabulary_id": vocabulary_id, "terms": terms_patch},
        "review_summary": review_summary,
        "preview": {},
        "apply_plan": {"mode": "merge_terms_batch"},
        "resources": {},
    }


def build_taxonomy_import_ops_artifact(
    *,
    vocabulary_id: str,
    operations: list[dict[str, Any]],
    job_type: str,
    review_summary: str = "",
) -> dict[str, Any]:
    """Création / mise à jour de termes via le même format que POST import/diff."""
    return {
        "artifact_version": ARTIFACT_VERSION,
        "artifact_type": ARTIFACT_TAXONOMY_IMPORT_OPS,
        "entity_type": "vocabulary",
        "entity_id": vocabulary_id,
        "job_type": job_type,
        "proposal": {"vocabulary_id": vocabulary_id, "operations": operations},
        "review_summary": review_summary,
        "preview": {},
        "apply_plan": {"mode": "taxonomy_import_operations"},
        "resources": {},
    }


def build_image_concepts_artifact(
    *,
    job_id: str,
    theme: str,
    suggestions: list[dict[str, Any]],
    anchor: dict[str, str] | None,
    job_type: str,
    review_summary: str = "",
) -> dict[str, Any]:
    """Liste de concepts image proposés par l'IA ; apply crée des lignes ``image`` en brouillon."""
    proposal: dict[str, Any] = {"theme": theme, "suggestions": suggestions}
    if anchor:
        proposal["anchor"] = anchor
    return {
        "artifact_version": ARTIFACT_VERSION,
        "artifact_type": ARTIFACT_IMAGE_CONCEPTS_PROPOSAL,
        "entity_type": "concept_batch",
        "entity_id": job_id,
        "job_type": job_type,
        "proposal": proposal,
        "review_summary": review_summary,
        "preview": {},
        "apply_plan": {"mode": "create_images_from_concepts"},
        "resources": {},
    }


def build_image_text_patch_artifact(
    *,
    entity_id: str,
    proposal: dict[str, Any],
    job_type: str,
    review_summary: str = "",
) -> dict[str, Any]:
    """Mise à jour title / prompt / negative_prompt sur une image."""
    return {
        "artifact_version": ARTIFACT_VERSION,
        "artifact_type": ARTIFACT_IMAGE_TEXT_PATCH,
        "entity_type": "image",
        "entity_id": entity_id,
        "job_type": job_type,
        "proposal": proposal,
        "review_summary": review_summary,
        "preview": {},
        "apply_plan": {"mode": "merge_entity_fields"},
        "resources": {},
    }


def build_image_generation_artifact(
    *,
    entity_id: str,
    image_output_id: str,
    rel_path: str,
    generation_params: dict[str, Any],
    prompt: str,
    negative_prompt: str = "",
    external_ref_id: str | None = None,
    qc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Résultat worker image : proposition vide au sens « champs texte » ; promotion via apply_plan.

    ``qc`` : rapport qualité image (v1). Par défaut, placeholder jusqu'à branchement des checks.
    """
    preview = {
        "rel_path": rel_path,
        "prompt_echo": prompt,
        "negative_prompt_echo": negative_prompt,
    }
    qc_report = qc if qc is not None else build_minimal_image_qc_v1()
    return {
        "artifact_version": ARTIFACT_VERSION,
        "artifact_type": ARTIFACT_IMAGE_GENERATION_OUTPUT,
        "entity_type": "image",
        "entity_id": entity_id,
        "job_type": "image_generation",
        "proposal": {},
        "review_summary": "Génération image prête pour validation.",
        "preview": preview,
        "qc": qc_report,
        "apply_plan": {
            "mode": "promote_image_output",
            "output_id": image_output_id,
        },
        "resources": {
            "image_output_id": image_output_id,
            "rel_path": rel_path,
            "generation_params": generation_params,
            "external_ref_id": external_ref_id,
        },
    }


def normalize_flat_term_suggestions_to_proposal(flat: dict[str, Any]) -> dict[str, Any]:
    """Convertit des clés plates (name_fr, description_en, …) en name_i18n / description_i18n."""
    if not flat:
        return {}
    if any(k in flat for k in ("name_i18n", "description_i18n", "keywords")):
        return flat
    name_i18n: dict[str, str] = {}
    desc_i18n: dict[str, str] = {}
    keywords_val: str | None = None
    for k, v in flat.items():
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s:
            continue
        if k == "keywords":
            keywords_val = s
        elif k.startswith("name_"):
            lang = k.replace("name_", "", 1)
            name_i18n[lang] = s
        elif k.startswith("description_"):
            lang = k.replace("description_", "", 1)
            desc_i18n[lang] = s
    out: dict[str, Any] = {}
    if name_i18n:
        out["name_i18n"] = name_i18n
    if desc_i18n:
        out["description_i18n"] = desc_i18n
    if keywords_val is not None:
        out["keywords"] = keywords_val
    return out


def serialize_artifact(artifact: dict[str, Any]) -> str:
    return json.dumps(artifact, ensure_ascii=False)


def artifact_json_bytes(artifact: dict[str, Any]) -> bytes:
    return serialize_artifact(artifact).encode("utf-8")
