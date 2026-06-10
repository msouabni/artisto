"""Service de vectorisation PNG → SVG via VTracer (post-ERNIE, sans correction sémantique).

Pipeline cible : taxonomie → PromptGenerator → ComfyUI → QC → [Vectorizer] → SVG.

Le service convertit les line-art ERNIE (1024×1024 ou 848×1264) en SVG
**géométriquement fidèles** au raster d'entrée. Aucun enrichissement, aucune
correction sémantique : un défaut 2_objets / 3_jambes / traits_flous est
reproduit tel quel. Le filtrage qualité reste en amont (QC vision + humain).

Moteur : **VTracer 0.6.15+** (Rust port via PyO3, pip-installable, OS-agnostique).
Référence : bench `_lab/vectorize-bench/VERDICT.md` (2026-05-30) — VTracer
sélectionné après comparaison face à potrace : install simplifiée, vitesse
identique (~30-50 ms / image), presets riches en Python, support natif des
modes spline / polygon / couleur.

Recette technique :
    1. (Optionnel — opt-in) Pre-clean OpenCV : grayscale → médian 3×3 → MINMAX
       → Otsu (ou adaptive 31,10) → CLOSE ellipse 2×2.
       Désactivé par défaut : VTracer gère déjà ``filter_speckle`` natif.
       Activer ``pre_clean=True`` si le raster source est dégradé (ERNIE
       avec couleur résiduelle, scan, screenshot, etc.).
    2. Tracé : ``vtracer.convert_image_to_svg_py`` avec un preset nommé ou
       des paramètres explicites.

Hors périmètre (phase 2 séparée) : coloriage interactif web — segmentation
des régions blanches fermées en paths SVG remplissables. La piste sérieuse
identifiée est le preset ``bw_polygon`` (ratio ×3-4 plus léger, régions
faciles à isoler) ; voir `_lab/vectorize-bench/VERDICT.md` §3.
"""
from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterator, Literal

import cv2
import numpy as np
import vtracer

logger = logging.getLogger(__name__)


ColorMode = Literal["binary", "color"]
Hierarchical = Literal["stacked", "cutout"]
TraceMode = Literal["spline", "polygon", "none"]


@dataclass
class VectorizeParams:
    """Paramètres VTracer + pre-clean OpenCV optionnel.

    Defauts calibrés pour line-art ERNIE 1024×1024 / 848×1264. Voir
    ``_lab/vectorize-bench/VERDICT.md`` pour le benchmark détaillé et les
    arbitrages (qualité ↔ poids ↔ temps).
    """

    # === VTracer (moteur principal) ==========================================
    colormode: ColorMode = "binary"
    hierarchical: Hierarchical = "stacked"
    mode: TraceMode = "spline"
    filter_speckle: int = 4
    corner_threshold: int = 60
    splice_threshold: int = 45
    path_precision: int = 3

    # === Pre-clean OpenCV (opt-in, défaut OFF) ===============================
    pre_clean: bool = False
    adaptive: bool = False
    close_gaps: bool = True
    despeckle: bool = True


# Presets nommés — figés par le bench du 2026-05-30 (6 cas ERNIE, 4 presets).
# Sources : ``_lab/vectorize-bench/VERDICT.md``.
PRESETS: dict[str, VectorizeParams] = {
    # Equilibre fidélité ↔ poids ↔ temps. Choix par défaut pour la prod.
    "bw_default": VectorizeParams(),
    # Simplification agressive : -20 % de poids vs default, perte minime de
    # détail. Cible CDN / impression légère.
    "bw_clean": VectorizeParams(
        filter_speckle=10,
        corner_threshold=80,
        splice_threshold=60,
        path_precision=2,
    ),
    # Préservation maximale : +35 % de poids, capture les subtilités du trait.
    # Cible archivage éditorial.
    "bw_detail": VectorizeParams(
        filter_speckle=2,
        corner_threshold=40,
        splice_threshold=30,
        path_precision=5,
    ),
    # Polygones droits. ×3-4 plus léger. Piste sérieuse pour la phase 2
    # coloriage interactif (régions fermées identifiables).
    "bw_polygon": VectorizeParams(mode="polygon"),
}


@dataclass
class VectorizeResult:
    """Résultat d'une conversion PNG → SVG."""

    name: str
    svg_path: Path
    kb_in: float
    kb_svg: float
    n_paths: int
    n_subpaths: int
    ratio: float
    clean_path: Path | None = field(default=None)


_PATH_TAG_RE = re.compile(r"<path\b", re.IGNORECASE)
_MOVE_RE = re.compile(r"\bM\s*-?\d")
_IMG_EXTS = {".png", ".jpg", ".jpeg"}


class Vectorizer:
    """Convertit un PNG line-art en SVG via VTracer (+ pre-clean OpenCV opt-in).

    Service importable tel quel depuis le pipeline FastAPI ou utilisable en
    batch via ``scripts/vectorize_cli.py``.

    Usage :
        >>> vec = Vectorizer.from_preset("bw_default")
        >>> result = vec.process(png_path, out_dir)

        >>> # Override d'un preset
        >>> vec = Vectorizer.from_preset("bw_default", filter_speckle=8)

        >>> # Paramètres explicites
        >>> vec = Vectorizer(VectorizeParams(mode="polygon", filter_speckle=6))
    """

    def __init__(self, params: VectorizeParams | None = None) -> None:
        self.params = params or VectorizeParams()

    @classmethod
    def from_preset(cls, name: str, **overrides) -> "Vectorizer":
        """Instancie depuis un preset nommé avec overrides optionnels.

        Lève ``KeyError`` si ``name`` n'est pas dans ``PRESETS``.
        """
        if name not in PRESETS:
            raise KeyError(
                f"Preset inconnu : '{name}'. Disponibles : {sorted(PRESETS)}"
            )
        base = PRESETS[name]
        if overrides:
            base = replace(base, **overrides)
        return cls(base)

    # === Pre-clean OpenCV ====================================================
    def clean(self, path: Path) -> np.ndarray:
        """Nettoie un PNG et retourne un ndarray binaire uint8 (0=encre, 255=papier).

        Étapes (dans l'ordre) : grayscale → médian 3×3 (si despeckle) → MINMAX
        → seuillage Otsu (ou adaptive 31,10) → CLOSE ellipse 2×2 (si close_gaps).

        Appelé uniquement si ``params.pre_clean=True``.
        """
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Lecture impossible (format non supporté ?) : {path}")

        if self.params.despeckle:
            img = cv2.medianBlur(img, 3)

        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)

        if self.params.adaptive:
            binary = cv2.adaptiveThreshold(
                img,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                10,
            )
        else:
            _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        if self.params.close_gaps:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        return binary

    # === Process =============================================================
    def process(
        self,
        src: Path,
        out_dir: Path,
        save_clean: bool = False,
    ) -> VectorizeResult:
        """Vectorise ``src`` vers ``out_dir/<stem>.svg`` et renvoie les métriques.

        Si ``params.pre_clean=True``, le PNG est d'abord nettoyé par OpenCV puis
        écrit dans un fichier temporaire passé à VTracer. Si ``save_clean=True``,
        le PNG nettoyé est conservé à côté du SVG (suffixe ``.clean.png``)
        — utile pour le rapport HTML.
        """
        src = Path(src)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        svg_path = out_dir / f"{src.stem}.svg"

        # === Pre-clean optionnel =============================================
        clean_path: Path | None = None
        vtracer_input: Path = src
        tmp_clean: Path | None = None

        if self.params.pre_clean:
            binary = self.clean(src)
            if save_clean:
                clean_path = out_dir / f"{src.stem}.clean.png"
                cv2.imwrite(str(clean_path), binary)
                vtracer_input = clean_path
            else:
                tmp_clean = Path(
                    tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False
                    ).name
                )
                cv2.imwrite(str(tmp_clean), binary)
                vtracer_input = tmp_clean

        # === VTracer =========================================================
        try:
            vtracer.convert_image_to_svg_py(
                str(vtracer_input),
                str(svg_path),
                colormode=self.params.colormode,
                hierarchical=self.params.hierarchical,
                mode=self.params.mode,
                filter_speckle=self.params.filter_speckle,
                corner_threshold=self.params.corner_threshold,
                splice_threshold=self.params.splice_threshold,
                path_precision=self.params.path_precision,
            )
        finally:
            if tmp_clean is not None:
                try:
                    tmp_clean.unlink()
                except OSError:
                    pass

        # === Métriques =======================================================
        svg_bytes = svg_path.read_bytes()
        svg_text = svg_bytes.decode("utf-8", errors="replace")
        n_paths = len(_PATH_TAG_RE.findall(svg_text))
        n_subpaths = len(_MOVE_RE.findall(svg_text))

        kb_in = src.stat().st_size / 1024.0
        kb_svg = len(svg_bytes) / 1024.0
        ratio = (kb_svg / kb_in) if kb_in > 0 else 0.0

        logger.info(
            "vectorize ok name=%s mode=%s kb_in=%.1f kb_svg=%.1f ratio=%.2f paths=%d subpaths=%d",
            src.stem,
            self.params.mode,
            kb_in,
            kb_svg,
            ratio,
            n_paths,
            n_subpaths,
        )

        return VectorizeResult(
            name=src.stem,
            svg_path=svg_path,
            kb_in=kb_in,
            kb_svg=kb_svg,
            n_paths=n_paths,
            n_subpaths=n_subpaths,
            ratio=ratio,
            clean_path=clean_path,
        )

    def process_batch(
        self,
        src_dir: Path,
        out_dir: Path,
        limit: int | None = None,
        save_clean: bool = False,
    ) -> Iterator[VectorizeResult]:
        """Itère sur les images d'un dossier et yield ``VectorizeResult``.

        Skip silencieusement les fichiers ``.clean.png`` pour éviter une
        boucle si ``out_dir == src_dir``. Les erreurs par image sont
        loguées et n'interrompent pas le batch.
        """
        src_dir = Path(src_dir)
        if not src_dir.is_dir():
            raise NotADirectoryError(f"Dossier source introuvable : {src_dir}")

        candidates = sorted(
            p
            for p in src_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() in _IMG_EXTS
            and not p.name.endswith(".clean.png")
        )
        if limit is not None:
            candidates = candidates[:limit]

        for src in candidates:
            try:
                yield self.process(src, out_dir, save_clean=save_clean)
            except Exception:
                logger.exception("vectorize fail name=%s", src.stem)


__all__ = [
    "PRESETS",
    "VectorizeParams",
    "VectorizeResult",
    "Vectorizer",
]
