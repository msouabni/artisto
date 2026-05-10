"""Worker QC déterministe sur ``image_output`` (brief 2026-05-10).

Pose 5 tags QC sur ``image_output.qc_tags`` après chaque génération
réussie :

- ``qc_color_residual`` : ``color_ratio > 0.001`` (chrominance Pillow/NumPy)
- ``qc_color_intrinsic`` : leaf_id matche ``{rainbow_*, crystal_*,
  prism_*, spectrum_*, aurora_*}`` — coloration attendue par le sujet,
  pas un défaut
- ``qc_low_contrast`` : ``std(intensite) < 30`` sur 0-255
- ``qc_low_complexity`` : ``edges Canny < 500`` (pixels d'arête)
- ``qc_oversaturated`` : ``% pixels noirs (intensite < 30) > 50%``

Si aucun tag de défaut n'est posé → ajoute ``qc_ok``.

Aucun LLM, aucun appel réseau. Calibration des seuils : voir
``docs/reports/2026-05-10_qc-auto-worker.md``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from workers.base_worker import BaseWorker, _compute_duration_ms

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Seuils déterministes (calibrés sur 20 PNG line-art réels du repo —
# voir docs/reports/2026-05-10_qc-auto-worker.md pour la distribution).
QC_COLOR_RESIDUAL_THRESHOLD = 0.001  # ratio pixels colorés
QC_LOW_CONTRAST_STD_THRESHOLD = 30.0  # sur 0-255
QC_LOW_COMPLEXITY_EDGE_THRESHOLD = 500  # nb pixels d'arête (Canny)
QC_OVERSATURATED_BLACK_RATIO_THRESHOLD = 0.50  # part de pixels < 30/255

# Préfixes leaf_id à coloration intrinsèque attendue (le coloriage est
# difficile à rendre 100 % monochrome car le sujet *est* la couleur).
_INTRINSIC_COLOR_PREFIXES: tuple[str, ...] = (
    "rainbow_",
    "crystal_",
    "prism_",
    "spectrum_",
    "aurora_",
)
# Match aussi les leaf_id qui *commencent par* le mot exact (ex.
# ``rainbow``, ``aurora``) sans suffixe ``_``.
_INTRINSIC_COLOR_EXACT: frozenset[str] = frozenset(
    p.rstrip("_") for p in _INTRINSIC_COLOR_PREFIXES
)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_intrinsic_color_leaf(leaf_id: str | None) -> bool:
    """Retourne True si le leaf_id correspond à un sujet à coloration
    intrinsèque attendue (rainbow / crystal / prism / spectrum / aurora).

    NULL-safe : ``None`` ou chaîne vide → False.
    """
    if not leaf_id:
        return False
    s = str(leaf_id).strip().lower()
    if not s:
        return False
    if s in _INTRINSIC_COLOR_EXACT:
        return True
    return any(s.startswith(p) for p in _INTRINSIC_COLOR_PREFIXES)


def _canny_edge_count(gray_u8: np.ndarray) -> int:
    """Approximation Canny en NumPy pur (pas d'opencv requis).

    Étapes : flou gaussien 3x3 → Sobel → magnitude → seuil haut.
    Retourne le nombre de pixels considérés comme arête.
    """
    g = gray_u8.astype(np.float32)
    # Flou 3x3 séparable très simple
    kernel = np.array([1, 2, 1], dtype=np.float32) / 4.0
    # Convolution horizontale puis verticale
    pad = np.pad(g, ((0, 0), (1, 1)), mode="edge")
    gx_blur = (
        kernel[0] * pad[:, :-2]
        + kernel[1] * pad[:, 1:-1]
        + kernel[2] * pad[:, 2:]
    )
    pad2 = np.pad(gx_blur, ((1, 1), (0, 0)), mode="edge")
    blurred = (
        kernel[0] * pad2[:-2, :]
        + kernel[1] * pad2[1:-1, :]
        + kernel[2] * pad2[2:, :]
    )

    # Gradient Sobel
    pad_h = np.pad(blurred, ((0, 0), (1, 1)), mode="edge")
    sx = -pad_h[:, :-2] + pad_h[:, 2:]
    pad_v = np.pad(blurred, ((1, 1), (0, 0)), mode="edge")
    sy = -pad_v[:-2, :] + pad_v[2:, :]
    mag = np.sqrt(sx * sx + sy * sy)
    # Seuil "haut" type Canny : 80 sur 0-255 (line-art noir/blanc → arêtes très marquées)
    return int(np.sum(mag > 80.0))


def compute_qc_metrics(image_path: Path) -> dict[str, Any]:
    """Calcule les métriques brutes utilisées par les 5 règles QC.

    Retourne ``{"readable": False, "error": str}`` si l'image ne peut
    pas être lue ; sinon ``{"readable": True, "color_ratio": ...,
    "intensity_std": ..., "edge_count": ..., "black_ratio": ...}``.
    """
    if not image_path.is_file():
        return {"readable": False, "error": f"missing:{image_path}"}
    try:
        with Image.open(image_path) as img:
            rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)
    except (OSError, UnidentifiedImageError, ValueError) as e:
        return {"readable": False, "error": str(e)}

    h, w = int(rgb.shape[0]), int(rgb.shape[1])
    if h < 8 or w < 8:
        return {"readable": False, "error": f"too_small:{w}x{h}"}

    r = rgb[..., 0].astype(np.float32) / 255.0
    g = rgb[..., 1].astype(np.float32) / 255.0
    b = rgb[..., 2].astype(np.float32) / 255.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    chroma = np.divide(
        mx - mn,
        mx,
        out=np.zeros_like(mx, dtype=np.float32),
        where=(mx > 1e-6),
    )
    colored = (chroma > 0.12) & (mx > 0.12)
    color_ratio = float(np.mean(colored))

    # Intensité luma (Pillow "L")
    gray_u8 = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.uint8)
    intensity_std = float(np.std(gray_u8))
    # Pixels noirs : intensité < 30 / 255
    black_ratio = float(np.mean(gray_u8 < 30))
    edge_count = _canny_edge_count(gray_u8)

    return {
        "readable": True,
        "color_ratio": round(color_ratio, 6),
        "intensity_std": round(intensity_std, 3),
        "edge_count": int(edge_count),
        "black_ratio": round(black_ratio, 5),
        "width": w,
        "height": h,
    }


def evaluate_qc_tags(metrics: dict[str, Any], leaf_id: str | None) -> list[str]:
    """Applique les 5 règles déterministes et retourne la liste des tags.

    Si aucun défaut n'est détecté → ``["qc_ok"]``.
    Si l'image n'est pas lisible → ``["qc_unreadable"]``.
    """
    if not metrics.get("readable"):
        return ["qc_unreadable"]

    tags: list[str] = []
    color_ratio = float(metrics.get("color_ratio") or 0.0)
    if color_ratio > QC_COLOR_RESIDUAL_THRESHOLD:
        tags.append("qc_color_residual")
    if is_intrinsic_color_leaf(leaf_id):
        tags.append("qc_color_intrinsic")
    intensity_std = float(metrics.get("intensity_std") or 0.0)
    if intensity_std < QC_LOW_CONTRAST_STD_THRESHOLD:
        tags.append("qc_low_contrast")
    edge_count = int(metrics.get("edge_count") or 0)
    if edge_count < QC_LOW_COMPLEXITY_EDGE_THRESHOLD:
        tags.append("qc_low_complexity")
    black_ratio = float(metrics.get("black_ratio") or 0.0)
    if black_ratio > QC_OVERSATURATED_BLACK_RATIO_THRESHOLD:
        tags.append("qc_oversaturated")

    # Filtrer les "vrais défauts" pour décider du qc_ok :
    # qc_color_intrinsic est informatif, pas un défaut.
    real_defects = [t for t in tags if t != "qc_color_intrinsic"]
    if not real_defects:
        tags.append("qc_ok")
    return tags


# ── Helpers DB ────────────────────────────────────────────────────────────────

def _resolve_image_output_path(conn, image_output_id: str) -> tuple[str | None, str | None]:
    """Retourne ``(file_path, leaf_id)`` pour un image_output donné, ou
    ``(None, None)`` si introuvable. NULL-safe.
    """
    row = conn.execute(
        """
        SELECT io.file_path, i.origin_term_id
        FROM image_output io
        LEFT JOIN image i ON i.id = io.image_id
        WHERE io.id = ?
        """,
        [image_output_id],
    ).fetchone()
    if not row:
        return None, None
    file_path = row[0] if row[0] is not None else None
    leaf_id = row[1] if row[1] is not None else None
    return file_path, leaf_id


def _save_qc_tags(conn, image_output_id: str, tags: list[str]) -> None:
    """Sérialise et persiste ``qc_tags`` (JSON cross-dialect)."""
    payload = json.dumps(tags or [], ensure_ascii=False)
    conn.execute(
        "UPDATE image_output SET qc_tags = ? WHERE id = ?",
        [payload, image_output_id],
    )


def run_qc_for_output(conn, image_output_id: str, outputs_root: Path) -> dict[str, Any]:
    """Pipeline complet : lit le chemin, calcule métriques, applique
    règles, persiste ``qc_tags``. Retourne un dict
    ``{"image_output_id", "tags", "metrics"}``.
    """
    file_path, leaf_id = _resolve_image_output_path(conn, image_output_id)
    if file_path is None:
        return {
            "image_output_id": image_output_id,
            "tags": ["qc_unreadable"],
            "metrics": {"readable": False, "error": "image_output_not_found"},
        }
    rel = str(file_path).lstrip("/").lstrip("\\")
    abs_path = (outputs_root / Path(rel).name).resolve()
    if not abs_path.is_file():
        # Tente le chemin "tel quel" si relatif depuis project root
        candidate = (PROJECT_ROOT / "data" / rel).resolve()
        if candidate.is_file():
            abs_path = candidate
    metrics = compute_qc_metrics(abs_path)
    tags = evaluate_qc_tags(metrics, leaf_id)
    _save_qc_tags(conn, image_output_id, tags)
    return {
        "image_output_id": image_output_id,
        "tags": tags,
        "metrics": metrics,
        "leaf_id": leaf_id,
    }


# ── Worker ────────────────────────────────────────────────────────────────────

class QCWorker(BaseWorker):
    """Worker pour le job_type ``image_qc_auto``.

    Lit ``entity_id`` (= image_output_id), exécute les règles, persiste
    ``qc_tags``. Aucune dépendance externe (pas de ComfyUI, pas
    d'Ollama).
    """

    job_type = "image_qc_auto"
    category = "image"

    def process(self, job: dict[str, Any]) -> dict[str, Any]:
        image_output_id = job.get("entity_id") or job.get("image_id")
        if not image_output_id:
            raise ValueError("image_qc_auto: entity_id manquant (image_output_id)")
        # Outputs root : data/outputs (cohérent avec ImageWorker)
        outputs_root = PROJECT_ROOT / "data" / "outputs"
        conn = self._conn(read_only=False)
        try:
            res = run_qc_for_output(conn, image_output_id, outputs_root)
            conn.session.commit()
            return res
        finally:
            conn.close()

    def save_result(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        """Marque le job comme ``completed`` (pas de revue humaine pour QC auto)."""
        job_id = job["job_id"]
        conn = self._conn(read_only=False)
        try:
            now = _now()
            duration_ms = _compute_duration_ms(job)
            payload = json.dumps(
                {
                    "image_output_id": result.get("image_output_id"),
                    "tags": result.get("tags") or [],
                    "metrics": result.get("metrics") or {},
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
