"""Tests du rendu HTML pour le chantier C3.4 (polish UX hover + onboarding + mobile + a11y).

On verifie la presence dans le HTML rendu de :
- Overlay onboarding (premier load) + flag localStorage + bouton ❓ Aide pour rouvrir
- Animation paint-pulse (CSS) + classe just-painted appliquee en JS
- Hover preview couleur via pointer events (souris + touch)
- Accessibilite : aria-label SVG, role application, role group, kbd dans tuto
- Media query mobile (max-width 600px ou 480px)
- Touch-action: manipulation pour eliminer le delai 300ms iOS
- Aucune regression C3.1 / C3.2 / C3.3
"""
from __future__ import annotations

from api.routes.extract_palette_route import _render_html


def _render(name: str = "dummy.png", preset_name: str = "test") -> str:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    return _render_html(
        name=name,
        source_url="/dummy",
        svg_inline=svg,
        n_regions=4,
        preset_name=preset_name,
        elapsed_ms=12.0,
    )


def test_render_html_contient_onboarding_overlay():
    """L'overlay onboarding et son CSS sont presents."""
    html = _render()
    assert 'id="onboarding-tip"' in html
    assert "onboarding-overlay" in html
    assert "onboarding-card" in html
    # CSS associe
    assert ".onboarding-overlay" in html
    assert ".onboarding-card" in html
    # JS : flag localStorage + ouverture differee + bouton close
    assert "coloring.onboarding-seen" in html
    assert "btn-onboarding-close" in html
    # Le bouton recoit autofocus
    assert "autofocus" in html


def test_render_html_contient_btn_help():
    """Le bouton ❓ Aide permet de rouvrir le tutoriel a tout moment."""
    html = _render()
    assert 'id="btn-help"' in html
    # JS : ecouteur click qui rouvre l'overlay
    assert "btn-help" in html
    assert "openOnboarding" in html


def test_render_html_contient_animations_css():
    """Les transitions douces + animation paint-pulse sont en CSS."""
    html = _render()
    # Transitions sur fill/stroke
    assert "transition:" in html
    assert "fill" in html
    # Animation pulse keyframe + classe
    assert "@keyframes paint-pulse" in html
    assert "paint-pulse" in html
    assert ".just-painted" in html
    assert "transform-box:fill-box" in html
    # JS : la classe est ajoutee transitoirement au paint utilisateur
    assert "just-painted" in html
    # Et retiree apres timeout (260ms)
    assert "260" in html


def test_render_html_contient_hover_preview_js():
    """Hover preview via pointer events couvre souris + touch (pointerenter/leave)."""
    html = _render()
    # Pointer events (preferes a mouse pour compat tactile)
    assert "pointerenter" in html
    assert "pointerleave" in html
    # Le hover skip pendant le mode solution
    assert "classList.contains('solution')" in html
    # Et restaure les attributs originaux a la sortie (hoverPrev pattern)
    assert "hoverPrev" in html


def test_render_html_a11y_svg_aria_label():
    """Le SVG racine a un aria-label parlant pour les lecteurs d'ecran."""
    html = _render()
    # Le SVG a recu role + aria-label via injection post-traitement
    assert 'aria-label="Zone de coloriage interactive"' in html
    assert 'role="img"' in html
    # main = application role
    assert 'role="application"' in html
    # controls = role group + label
    assert 'role="group"' in html
    assert 'aria-label="Outils"' in html
    # Onboarding modal a roles ARIA
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    # kbd dans le tuto pour les raccourcis clavier
    assert "<kbd>" in html


def test_render_html_responsive_media_query():
    """Une media query mobile rend la palette compacte + header non sticky."""
    html = _render()
    # Au moins une media query mobile (600px) presente
    assert "max-width: 600px" in html or "max-width:600px" in html
    # CSS palette compacte
    assert ".palette-accordion" in html
    # touch-action manipulation = elimine le delai 300ms iOS
    assert "touch-action:manipulation" in html or "touch-action: manipulation" in html


def test_render_html_compat_c3_1_c3_2_c3_3():
    """Aucune regression : C3.1 (palette) + C3.2 (undo/redo) + C3.3 (export) preserves."""
    html = _render()
    # C3.1 : palette accordion
    assert 'class="palette-accordion"' in html
    assert "data-category=" in html
    # C3.2 : undo/redo + auto-save
    assert 'id="btn-undo"' in html
    assert 'id="btn-redo"' in html
    assert "function doUndo" in html
    assert "function restoreState" in html
    assert "coloring.state." in html
    # C3.3 : export PNG/SVG + share
    assert 'id="btn-export"' in html
    assert 'id="btn-export-png"' in html
    assert 'id="btn-export-svg"' in html
    assert 'id="btn-share-link"' in html
    assert "function exportPng" in html
    assert "function exportSvg" in html
