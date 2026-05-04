"""Génération d'images line art — mode placeholder Pillow pour valider le pipeline."""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "data" / "outputs"
DEFAULT_SIZE = (512, 512)
DEFAULT_BG = (255, 255, 255)
DEFAULT_FG = (0, 0, 0)


def generate_placeholder(
    prompt: str,
    output_path: Path,
    size: tuple[int, int] = DEFAULT_SIZE,
    negative_prompt: str = "",
) -> Path:
    """
    Génère une image placeholder via Pillow (forme + texte du prompt).
    Mode dégradé pour valider le flux jobs → worker → image_output.
    """
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, DEFAULT_BG)
    draw = ImageDraw.Draw(img)

    # Rectangle avec bordure noire (simule line art)
    margin = 40
    draw.rectangle(
        [margin, margin, size[0] - margin, size[1] - margin],
        outline=DEFAULT_FG,
        width=3,
    )

    # Texte du prompt (tronqué si trop long)
    text = (prompt or "placeholder")[:80]
    font = None
    for path in ("arial.ttf", "Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(path, 16)
            break
        except OSError:
            pass
    if font is None:
        font = ImageFont.load_default()

    # Découper en lignes (max ~50 caractères par ligne)
    max_chars = 50
    lines = []
    for i in range(0, len(text), max_chars):
        lines.append(text[i : i + max_chars])
    if not lines:
        lines = ["(vide)"]

    y = size[1] // 2 - (len(lines) * 22) // 2
    for line in lines[:5]:
        # Centrer horizontalement (approximation)
        draw.text((size[0] // 2, y), line, fill=DEFAULT_FG, font=font, anchor="mm")
        y += 22

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    logger.info("Placeholder généré: %s", output_path)
    return output_path
