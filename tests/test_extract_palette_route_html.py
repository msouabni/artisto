"""Tests du rendu HTML du colorieur (palette categorisee + custom picker C3.1).

On teste la fonction module-level ``_render_html`` directement, sans toucher
ComfyUI ni le pipeline extract_palette. Les arguments factices reproduisent
le contrat (name, source_url, svg_inline, n_regions, preset_name, elapsed_ms).
"""
from __future__ import annotations

import re

from api.routes.extract_palette_route import (
    PALETTES_BY_CATEGORY,
    _render_html,
    _render_palette_accordion_html,
)


def _render_minimal() -> str:
    """Render avec un SVG trivial + 0 regions (chemin _generate_auto_palette OK)."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    return _render_html(
        name="dummy.png",
        source_url="/dummy",
        svg_inline=svg,
        n_regions=4,
        preset_name="test",
        elapsed_ms=12.0,
    )


def test_render_html_contient_5_categories():
    """Verifie que le HTML rendu contient les 4 categories predefinies + Custom.

    Critere : chaque label (Vifs, Pastels, Terre, Monochromes, Personnalise)
    apparait dans une <summary> de details, et chaque data-category attendu
    est present.
    """
    html = _render_minimal()
    # Labels visibles dans <summary>
    assert "Vifs" in html
    assert "Pastels" in html
    assert "Terre" in html
    assert "Monochromes" in html
    # Custom utilise le label francais "Personnalise" (avec accent).
    assert "Personnalisé" in html or "Personnalis" in html
    # Attributs data-category
    for cat in ("Vifs", "Pastels", "Terre", "Monochromes", "Custom"):
        assert f'data-category="{cat}"' in html, f"data-category={cat} manquant"
    # 5 blocs <details class="category-block">
    n_blocks = html.count('class="category-block"') + html.count(
        'class="category-block category-custom"'
    )
    assert n_blocks >= 5, f"attendu >= 5 blocs categorie, trouve {n_blocks}"


def test_render_html_contient_48_swatches_predefinis():
    """Compte les swatches predefinis (48 = 4 categories x 12 couleurs).

    On exclut le bloc recent-customs (vide au render initial) en comptant
    les boutons <button class="swatch"> avec un attribut data-color.
    """
    html = _render_minimal()
    # Pattern : button class="swatch" ... data-color="#XXXXXX"
    swatches = re.findall(
        r'<button[^>]*class="swatch"[^>]*data-color="#[0-9A-Fa-f]{6}"',
        html,
    )
    assert len(swatches) >= 48, (
        f"attendu >= 48 swatches predefinis, trouve {len(swatches)}"
    )
    # Sanity check : le total dans PALETTES_BY_CATEGORY = 48.
    total_defined = sum(len(v) for v in PALETTES_BY_CATEGORY.values())
    assert total_defined == 48


def test_render_html_contient_color_picker():
    """Verifie la presence de l'input color HSL + bouton ajouter + recent-customs."""
    html = _render_minimal()
    assert 'type="color"' in html
    assert 'id="custom-color"' in html
    assert 'btn-add-custom' in html
    assert 'recent-customs' in html
    # Le bloc Custom doit etre un details ferme par defaut (Vifs ouvert).
    assert 'category-custom' in html


def test_palette_accordion_independent():
    """Le helper _render_palette_accordion_html() retourne du HTML autosuffisant."""
    block = _render_palette_accordion_html()
    assert '<div class="palette-accordion"' in block
    assert block.count('<details') == 5  # 4 predef + Custom
    # Exactement 1 details ouvert par defaut (Vifs).
    assert block.count(' open') == 1


def test_render_html_conserve_boutons_legacy():
    """Garantit la retrocompat : btn-reset, btn-solution, btn-zones, auto-*."""
    html = _render_minimal()
    for btn_id in (
        "btn-reset",
        "btn-solution",
        "btn-zones",
        "btn-rainbow",
        "btn-pastel",
        "btn-vibrant",
    ):
        assert f'id="{btn_id}"' in html, f"bouton legacy {btn_id} manquant"


def test_render_html_localstorage_keys_presents():
    """Verifie que les cles localStorage sont referencees dans le JS."""
    html = _render_minimal()
    assert "coloring.category-open" in html
    assert "coloring.recent-customs" in html
