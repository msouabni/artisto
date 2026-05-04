"""QC technique déterministe sur PNG (line art / coloriage).

Utilise Pillow et NumPy (NumPy est une dépendance transitive d'opencv-python).
Les seuils sont volontairement simples : à calibrer avec des données réelles (étape 7 du plan QC).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


def _error_qc(flag: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "overall_score": 0,
        "technical_score": 0,
        "relevance_score": 0,
        "safety_score": 0,
        "status": "fail",
        "flags": [flag],
        "checks": [{"id": "image_readable", "pass": False, "detail": detail}],
        "recommendations": ["Impossible d'analyser l'image pour le QC technique."],
        "metrics": {},
    }


def _severity_to_points(sev: str) -> float:
    if sev == "pass":
        return 1.0
    if sev == "warn":
        return 0.65
    return 0.0


def build_technical_image_qc_v1(image_path: Path) -> dict[str, Any]:
    """Analyse ``image_path`` (PNG/RGB) et renvoie un rapport ``qc`` complet (v1).

    Champs non techniques : ``relevance_score`` et ``safety_score`` restent à 0.
    ``overall_score`` reprend le score technique tant que les autres axes sont absents.
    """
    checks: list[dict[str, Any]] = []
    flags: list[str] = []
    metrics: dict[str, Any] = {}
    recommendations: list[str] = []

    if not image_path.is_file():
        return _error_qc("image_file_missing", str(image_path))

    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            arr = np.asarray(img, dtype=np.uint8)
    except (OSError, UnidentifiedImageError, ValueError) as e:
        logger.warning("QC technique : lecture image impossible %s (%s)", image_path, e)
        return _error_qc("image_read_error", str(e))

    h, w = int(arr.shape[0]), int(arr.shape[1])
    if h < 8 or w < 8:
        return _error_qc("image_too_small", f"{w}x{h}")

    r = arr[..., 0].astype(np.float32) / 255.0
    g = arr[..., 1].astype(np.float32) / 255.0
    b = arr[..., 2].astype(np.float32) / 255.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    chroma = np.divide(
        mx - mn,
        mx,
        out=np.zeros_like(mx, dtype=np.float32),
        where=(mx > 1e-6),
    )
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    # 1) Couleur (chrominance)
    colored = (chroma > 0.12) & (mx > 0.12)
    color_ratio = float(np.mean(colored))
    metrics["color_ratio"] = round(color_ratio, 5)
    if color_ratio > 0.08:
        sev = "fail"
        flags.append("strong_color")
        recommendations.append("Couleur significative détectée : vérifier la conformité line art monochrome.")
    elif color_ratio > 0.025:
        sev = "warn"
        flags.append("noticeable_color")
        recommendations.append("Légère présence de couleur : possible anti-aliasing ou teinte résiduelle.")
    else:
        sev = "pass"
    checks.append(
        {
            "id": "color_presence",
            "pass": sev != "fail",
            "detail": f"colored_pixel_ratio={color_ratio:.4f}",
            "severity": sev,
        }
    )

    # 2) Fond clair (zone type coloriage)
    white_like = (lum > 0.90) & (chroma < 0.10)
    white_ratio = float(np.mean(white_like))
    metrics["white_ratio"] = round(white_ratio, 5)
    if white_ratio < 0.12:
        sev = "fail"
        flags.append("low_white_background")
        recommendations.append("Peu de zones très claires : fond attendu type coloriage ?")
    elif white_ratio < 0.22:
        sev = "warn"
        flags.append("moderate_white_background")
    else:
        sev = "pass"
    checks.append(
        {
            "id": "background_whiteness",
            "pass": sev != "fail",
            "detail": f"bright_low_chroma_ratio={white_ratio:.4f}",
            "severity": sev,
        }
    )

    # 3) Encre / traits sombres
    dark = lum < 0.22
    ink_ratio = float(np.mean(dark))
    metrics["ink_ratio"] = round(ink_ratio, 5)
    if ink_ratio < 0.0015:
        sev = "fail"
        flags.append("near_empty")
        recommendations.append("Très peu d'encre détectée : image quasi vide ou trop pâle.")
    elif ink_ratio < 0.004:
        sev = "warn"
        flags.append("low_ink")
    elif ink_ratio > 0.55:
        sev = "fail"
        flags.append("overdrawn")
        recommendations.append("Très forte densité d'encre : scène peut-être trop chargée pour un coloriage.")
    elif ink_ratio > 0.48:
        sev = "warn"
        flags.append("very_dense_ink")
    else:
        sev = "pass"
    checks.append(
        {
            "id": "ink_density",
            "pass": sev != "fail",
            "detail": f"dark_pixel_ratio={ink_ratio:.4f}",
            "severity": sev,
        }
    )

    # 4) Contraste global (ligne noire sur fond blanc : percentiles sur toute l'image)
    spread = float(np.percentile(lum, 99) - np.percentile(lum, 1))
    metrics["luminance_spread_p95_p5"] = round(spread, 5)
    if spread < 0.08:
        sev = "fail"
        flags.append("low_contrast")
        recommendations.append("Contraste faible : image très plate ou grisée.")
    elif spread < 0.12:
        sev = "warn"
        flags.append("moderate_contrast")
    else:
        sev = "pass"
    checks.append(
        {
            "id": "contrast",
            "pass": sev != "fail",
            "detail": f"spread={spread:.4f}",
            "severity": sev,
        }
    )

    # 5) Vide (seuil plus strict que ink_density seul)
    if ink_ratio < 0.0008:
        sev = "fail"
        if "near_empty" not in flags:
            flags.append("empty_image")
        recommendations.append("Image quasi vide : aucun dessin exploitable détecté.")
    elif ink_ratio < 0.002:
        sev = "warn"
    else:
        sev = "pass"
    checks.append(
        {
            "id": "empty_or_near_empty",
            "pass": sev != "fail",
            "detail": f"dark_pixel_ratio={ink_ratio:.4f}",
            "severity": sev,
        }
    )

    # 6) Traits collés au bord
    edge = max(1, min(10, h // 80, w // 80))
    edge_pixels = np.concatenate(
        [
            lum[:edge, :].ravel(),
            lum[-edge:, :].ravel(),
            lum[:, :edge].ravel(),
            lum[:, -edge:].ravel(),
        ]
    )
    core = lum[edge : h - edge, edge : w - edge]
    edge_ink = float(np.mean(edge_pixels < 0.32))
    core_ink = float(np.mean(core < 0.32)) if core.size > 0 else edge_ink
    metrics["edge_ink_ratio"] = round(edge_ink, 5)
    metrics["core_ink_ratio"] = round(core_ink, 5)
    core_safe = max(core_ink, 1e-5)
    if edge_ink > 0.22 and edge_ink > core_safe * 2.2:
        sev = "warn"
        flags.append("possible_border_clipping")
        recommendations.append("Beaucoup d'encre sur les bords : risque de cadrage ou de sujet coupé.")
    else:
        sev = "pass"
    checks.append(
        {
            "id": "border_clipping",
            "pass": True,
            "detail": f"edge_ink={edge_ink:.4f} core_ink={core_ink:.4f}",
            "severity": sev,
        }
    )

    severities = [str(c.get("severity", "pass" if c.get("pass") else "fail")) for c in checks]
    if any(s == "fail" for s in severities):
        status = "fail"
    elif any(s == "warn" for s in severities):
        status = "warning"
    else:
        status = "pass"

    n = len(checks)
    technical_score = int(round(100.0 * sum(_severity_to_points(s) for s in severities) / n)) if n else 0
    technical_score = max(0, min(100, technical_score))

    return {
        "schema_version": 1,
        "overall_score": technical_score,
        "technical_score": technical_score,
        "relevance_score": 0,
        "safety_score": 0,
        "status": status,
        "flags": flags,
        "checks": checks,
        "recommendations": recommendations,
        "metrics": metrics,
    }
