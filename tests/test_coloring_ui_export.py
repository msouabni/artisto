"""Tests du rendu HTML pour le chantier C3.3 (export PNG/SVG + partage clipboard).

On verifie la presence dans le HTML rendu de :
- Boutons UI menu Exporter (btn-export, btn-export-png, btn-export-svg, btn-share-link)
- Fonctions JS exportPng, exportSvg, shareLink, downloadBlob, showToast, escapeFilename
- Element toast pour les notifications
- Injection securisee du `name` via json.dumps (PAGE_NAME)
- CSS dropdown + toast
"""
from __future__ import annotations

import json

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


def test_render_html_contient_boutons_export():
    """Le menu dropdown + ses 3 items sont presents avec leurs ids."""
    html = _render()
    assert 'id="btn-export"' in html
    assert 'id="export-menu"' in html
    assert 'id="btn-export-png"' in html
    assert 'id="btn-export-svg"' in html
    assert 'id="btn-share-link"' in html
    # Labels visibles
    assert "Exporter" in html
    assert "Image PNG" in html
    assert "SVG vectoriel" in html
    assert "Copier le lien" in html
    # ARIA accessibility
    assert 'aria-haspopup="true"' in html
    assert 'aria-expanded="false"' in html
    assert 'role="menu"' in html
    assert 'role="menuitem"' in html


def test_render_html_contient_js_export_functions():
    """Les fonctions JS du systeme export + helpers sont presentes."""
    html = _render()
    for fn in (
        "function exportPng",
        "function exportSvg",
        "async function shareLink",
        "function downloadBlob",
        "function showToast",
        "function escapeFilename",
    ):
        assert fn in html, f"fonction JS manquante : {fn}"
    # Toggle menu
    assert "exportMenu.hidden" in html
    # Clipboard API
    assert "navigator.clipboard.writeText" in html
    # Canvas rasterization (XMLSerializer + Blob + canvas.toBlob)
    assert "XMLSerializer" in html
    assert "canvas.toBlob" in html
    assert "image/png" in html
    assert "image/svg+xml" in html


def test_render_html_name_injecte_via_json_dumps():
    """Le name est injecte via json.dumps : caracteres speciaux echappes proprement.

    Empeche les injections JS / breakages de syntaxe quand name contient quotes,
    backslashes ou caracteres unicode.
    """
    tricky = 'my "special" file\\name'
    html = _render(name=tricky)
    # json.dumps(tricky) doit etre present dans la constante PAGE_NAME
    expected_literal = json.dumps(tricky)
    assert f"const PAGE_NAME={expected_literal}" in html
    # La forme brute (non echappee) ne doit PAS apparaitre dans le script JS
    # (elle peut apparaitre dans <title> ou <h1>, c'est ok cote HTML escape).
    # On verifie que le script JS contient bien la forme echappee.
    assert '\\"special\\"' in html  # \" present dans JSON-encoded value
    # Pas de syntax error JS evidente (le json.dumps gere les quotes)


def test_render_html_contient_toast_element_et_css():
    """Le toast (notification) a son CSS et est cree dynamiquement par le JS."""
    html = _render()
    # CSS classe .toast
    assert ".toast{" in html
    assert ".toast.show" in html
    # JS instancie le toast en runtime
    assert "toastEl.className='toast'" in html or 'toastEl.className="toast"' in html
    # Duree 2200ms (2.2s)
    assert "2200" in html


def test_render_html_contient_css_dropdown():
    """Le CSS du dropdown menu est present (positionnement + visibilite)."""
    html = _render()
    assert ".dropdown-export" in html
    assert ".dropdown-menu" in html
    assert ".dropdown-item" in html
    # Le menu est cache au repos via attribut [hidden]
    assert ".dropdown-menu[hidden]" in html


def test_render_html_filename_safe_via_escapeFilename():
    """Le nom de fichier telecharge passe par escapeFilename pour etre OS-safe."""
    html = _render()
    # Le suffix _coloriage.png et _coloriage.svg sont construits via concat
    assert "_coloriage.png" in html
    assert "_coloriage.svg" in html
    # escapeFilename est appele avec PAGE_NAME
    assert "escapeFilename(PAGE_NAME)" in html


def test_render_html_export_compat_undo_redo_palette():
    """Aucune regression : C3.1 (palette) + C3.2 (undo/redo) preserves."""
    html = _render()
    # C3.1 : palette accordion
    assert 'class="palette-accordion"' in html
    assert "data-category=" in html
    # C3.2 : undo/redo
    assert 'id="btn-undo"' in html
    assert 'id="btn-redo"' in html
    assert "function doUndo" in html
    assert "function restoreState" in html
