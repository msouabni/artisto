"""Worker pour les jobs ``image_post_processing`` (C2.2).

Applique automatiquement le post-traitement sur le PNG raw d'un
``image_output`` fraichement genere :

- Variante chromakey (ex. ``pastel_chromakey``, ``flat_cartoon_chromakey``)
  → ``extract_palette`` (preset ``extract_preset`` de la variante) puis
  rendu SVG coloriage interactif (mode ``blank_outlined``) ET un SVG
  print vectorise via ``Vectorizer``.
- Variante lineart (sans ``extract_preset``) → ``Vectorizer`` (preset
  ``bw_default``) → uniquement le SVG print.

Les chemins de sortie suivent la convention C2.1
(``services/coloring_storage``) :
``data/generated/{leaf_id}__{variant_name}.{ext}``.

L'``image_output.model_config`` est enrichi avec les chemins relatifs des
artefacts produits (``vector_svg_path`` et ``coloring_svg_path``).

Dependances : ``cv2`` + ``numpy`` + ``vtracer`` (via les services
``extract_palette`` et ``vectorizer``). Les tests doivent mocker
``extract_palette``/``Vectorizer.from_preset`` pour ne pas dependre de
ces bibliotheques natives.

Voir aussi :
    - C1.1 : registre ``data/pipeline_variants.json``
    - C1.2/C1.3 : enqueue + propagation ``variant_name`` dans
      ``image_output.model_config``
    - C2.1 : conventions de storage (``services/coloring_storage``)
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.coloring_storage import (
    KIND_COLORING_SVG,
    KIND_VECTOR_SVG,
    get_storage_paths,
)
from services.extract_palette import extract_palette, make_params, render_svg
from services.vectorizer import Vectorizer
from workers.base_worker import BaseWorker, _compute_duration_ms

logger = logging.getLogger(__name__)

# Chemin absolu du projet (resout le TBD CWD pose en C2.1 : on n'utilise
# pas ``DEFAULT_GENERATED_DIR`` relatif, on calcule depuis ``__file__``).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = PROJECT_ROOT / "data" / "generated"

# Preset Vectorizer pour le SVG print : par defaut ``bw_default``
# (validation prod 2026-05-30, cf. _lab/vectorize-bench/VERDICT.md).
DEFAULT_VECTOR_PRESET = "bw_default"

# Mode ``render_svg`` pour le SVG coloriage interactif : ``blank_outlined``
# (toutes regions en blanc + stroke fin gris par region + trait noir,
# cible coloriage a remplir). Voir docstring ``render_svg`` dans
# ``services/extract_palette.py``.
DEFAULT_COLORING_MODE = "blank_outlined"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_png_abspath(file_path: str) -> Path:
    """Resout le ``file_path`` d'un ``image_output`` en chemin absolu.

    ``image_output.file_path`` est stocke en relatif depuis ``data/``
    (ex. ``"outputs/img_xyz.png"`` ou
    ``"generated/leaf__variant.png"``). On essaie d'abord
    ``PROJECT_ROOT/data/<file_path>`` puis ``PROJECT_ROOT/<file_path>``
    par tolerance.
    """
    rel = str(file_path).lstrip("/").lstrip("\\")
    candidate = (PROJECT_ROOT / "data" / rel).resolve()
    if candidate.is_file():
        return candidate
    fallback = (PROJECT_ROOT / rel).resolve()
    return fallback


class ImagePostProcessingWorker(BaseWorker):
    """Worker pour le job_type ``image_post_processing``.

    Lit ``entity_id`` (= image_output_id), genere les SVG print +
    coloriage selon la variante, persiste les chemins dans
    ``image_output.model_config``. Marque le job ``completed``.
    """

    job_type = "image_post_processing"
    category = "image"

    def process(self, job: dict[str, Any]) -> dict[str, Any]:
        image_output_id = job.get("entity_id") or job.get("image_id")
        if not image_output_id:
            raise ValueError(
                "image_post_processing: entity_id manquant (image_output_id)"
            )

        # Lecture image_output + image associee (file_path + model_config +
        # leaf_id origin_term_id).
        conn = self._conn(read_only=False)
        try:
            row = conn.execute(
                """
                SELECT io.file_path, io.model_config, i.origin_term_id
                FROM image_output io
                LEFT JOIN image i ON i.id = io.image_id
                WHERE io.id = ?
                """,
                [image_output_id],
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise ValueError(
                f"image_post_processing: image_output {image_output_id!r} introuvable"
            )

        file_path = row[0]
        model_config_raw = row[1]
        leaf_id = row[2]

        if not file_path:
            raise ValueError(
                f"image_post_processing: file_path manquant pour {image_output_id!r}"
            )
        if not leaf_id:
            raise ValueError(
                f"image_post_processing: image.origin_term_id manquant pour {image_output_id!r}"
            )

        # Lecture des champs variant_name / extract_preset depuis le
        # job.config en priorite, puis model_config en fallback.
        job_config = job.get("config") or {}
        if isinstance(job_config, str):
            try:
                job_config = json.loads(job_config) if job_config.strip() else {}
            except (json.JSONDecodeError, ValueError):
                job_config = {}
        variant_name = job_config.get("variant_name")
        extract_preset = job_config.get("extract_preset")

        mc_data: dict[str, Any] = {}
        if isinstance(model_config_raw, dict):
            mc_data = dict(model_config_raw)
        elif isinstance(model_config_raw, str) and model_config_raw.strip():
            try:
                parsed = json.loads(model_config_raw)
                if isinstance(parsed, dict):
                    mc_data = parsed
            except (json.JSONDecodeError, ValueError):
                mc_data = {}

        if not variant_name:
            variant_name = mc_data.get("variant_name")
        if extract_preset is None:
            extract_preset = mc_data.get("extract_preset")

        if not variant_name:
            raise ValueError(
                f"image_post_processing: variant_name manquant pour {image_output_id!r}"
            )

        png_path = _resolve_png_abspath(file_path)
        if not png_path.is_file():
            raise ValueError(
                f"image_post_processing: PNG introuvable : {png_path}"
            )

        # Calcule les chemins cibles via la convention C2.1.
        paths = get_storage_paths(leaf_id, variant_name, base_dir=GENERATED_DIR)
        paths.vector_svg.parent.mkdir(parents=True, exist_ok=True)

        # Copie le PNG raw vers paths.raw_png pour respecter la convention
        # storage : list_existing_variants() glob `{leaf}__*.png` et
        # alwanbooks_pipeline._build_variants_dict en depend pour le frontmatter.
        if paths.raw_png.resolve() != png_path.resolve():
            shutil.copyfile(png_path, paths.raw_png)
            logger.info(
                "post-processing copy PNG OK leaf=%s variant=%s -> %s",
                leaf_id, variant_name, paths.raw_png,
            )

        # === SVG coloriage interactif (si variante chromakey/extract) =====
        coloring_svg_path: Path | None = None
        if extract_preset:
            params = make_params(extract_preset)
            result = extract_palette(png_path, params)
            svg_text = render_svg(result, mode=DEFAULT_COLORING_MODE)
            paths.coloring_svg.write_text(svg_text, encoding="utf-8")
            coloring_svg_path = paths.coloring_svg
            logger.info(
                "post-processing extract_palette OK leaf=%s variant=%s preset=%s -> %s",
                leaf_id, variant_name, extract_preset, paths.coloring_svg,
            )

        # === SVG print via Vectorizer (toujours genere) ====================
        vectorizer = Vectorizer.from_preset(DEFAULT_VECTOR_PRESET)
        vec_result = vectorizer.process(png_path, paths.vector_svg.parent)
        # Vectorizer ecrit out_dir / {png_stem}.svg : on renomme/deplace
        # vers paths.vector_svg si necessaire (cas general : noms
        # differents car raw PNG est ``outputs/{image_id}_{job_id}.png``
        # tandis que la convention C2.1 attend ``{leaf}__{variant}.svg``).
        produced_svg = Path(vec_result.svg_path)
        if produced_svg.resolve() != paths.vector_svg.resolve():
            # ``replace`` est atomique cote OS, ecrase si la cible existe.
            produced_svg.replace(paths.vector_svg)
        logger.info(
            "post-processing vectorize OK leaf=%s variant=%s -> %s",
            leaf_id, variant_name, paths.vector_svg,
        )

        # Chemins persistes en relatif depuis PROJECT_ROOT (lisible en
        # multi-machine ; les workers downstream sauront resoudre).
        def _rel(p: Path) -> str:
            try:
                return str(p.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
            except ValueError:
                return str(p)

        return {
            "image_output_id": image_output_id,
            "leaf_id": leaf_id,
            "variant_name": variant_name,
            "extract_preset": extract_preset,
            "vector_svg_path": _rel(paths.vector_svg),
            "coloring_svg_path": _rel(coloring_svg_path) if coloring_svg_path else None,
        }

    def save_result(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        """Enrichit ``image_output.model_config`` + marque le job
        ``completed``.

        Idempotent : les cles ``vector_svg_path``/``coloring_svg_path``
        sont ecrasees a chaque execution (rejouable).
        """
        job_id = job["job_id"]
        image_output_id = result.get("image_output_id")
        conn = self._conn(read_only=False)
        try:
            now = _now()
            duration_ms = _compute_duration_ms(job)

            # Re-lit le model_config courant pour fusionner les nouvelles cles
            # sans ecraser les champs existants (variant_name, etc.).
            mc_data: dict[str, Any] = {}
            if image_output_id:
                row = conn.execute(
                    "SELECT model_config FROM image_output WHERE id = ?",
                    [image_output_id],
                ).fetchone()
                if row and row[0]:
                    raw = row[0]
                    if isinstance(raw, dict):
                        mc_data = dict(raw)
                    elif isinstance(raw, str) and raw.strip():
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                mc_data = parsed
                        except (json.JSONDecodeError, ValueError):
                            mc_data = {}

            mc_data["vector_svg_path"] = result.get("vector_svg_path")
            mc_data["coloring_svg_path"] = result.get("coloring_svg_path")
            mc_serialized = json.dumps(mc_data, ensure_ascii=False)

            if image_output_id:
                conn.execute(
                    "UPDATE image_output SET model_config = ? WHERE id = ?",
                    [mc_serialized, image_output_id],
                )

            payload = json.dumps(
                {
                    "image_output_id": image_output_id,
                    "leaf_id": result.get("leaf_id"),
                    "variant_name": result.get("variant_name"),
                    "extract_preset": result.get("extract_preset"),
                    "vector_svg_path": result.get("vector_svg_path"),
                    "coloring_svg_path": result.get("coloring_svg_path"),
                },
                ensure_ascii=False,
            )
            conn.execute(
                """
                UPDATE job
                SET status = 'completed', finished_at = ?, progress = 100,
                    result = ?, duration_ms = ?
                WHERE id = ?
                """,
                [now, payload, duration_ms, job_id],
            )
            conn.session.commit()
        finally:
            conn.close()


__all__ = [
    "ImagePostProcessingWorker",
    "GENERATED_DIR",
    "PROJECT_ROOT",
    "DEFAULT_VECTOR_PRESET",
    "DEFAULT_COLORING_MODE",
    "KIND_VECTOR_SVG",
    "KIND_COLORING_SVG",
]
