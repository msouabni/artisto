"""Tests du rendu HTML pour le chantier C3.2 (undo/redo + raccourcis + auto-save).

On verifie la presence dans le HTML rendu de :
- Boutons UI btn-undo / btn-redo (disabled au render initial)
- Fonctions JS doUndo, doRedo, restoreState, saveState
- Listener keydown pour Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y
- KEY_STATE isole par (name, preset_name)
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


def test_render_html_contient_boutons_undo_redo():
    """Boutons ↶/↷ presents dans la zone .actions, disabled par defaut."""
    html = _render()
    assert 'id="btn-undo"' in html
    assert 'id="btn-redo"' in html
    # Tooltip raccourci visible
    assert "Ctrl+Z" in html
    # Disabled au render initial (stacks vides)
    assert 'id="btn-undo" class="btn"' in html and "disabled" in html
    # Labels visibles
    assert "Annuler" in html
    assert "Rétablir" in html


def test_render_html_contient_js_undo_redo():
    """Les fonctions JS du systeme undo/redo + auto-save sont presentes."""
    html = _render()
    for fn in (
        "function doUndo",
        "function doRedo",
        "function saveState",
        "function restoreState",
        "function captureState",
        "function applyAction",
        "function updateUndoRedoButtons",
    ):
        assert fn in html, f"fonction JS manquante : {fn}"
    # Stack constants
    assert "undoStack" in html
    assert "redoStack" in html
    assert "MAX_STACK=50" in html or "MAX_STACK = 50" in html


def test_render_html_contient_shortcuts_keydown():
    """Listener keydown qui filtre sur Ctrl/Cmd + Z (avec/sans shift) ou Y."""
    html = _render()
    # Listener keydown global
    assert "addEventListener('keydown'" in html or 'addEventListener("keydown"' in html
    # Test sur la touche 'z'
    assert "'z'" in html
    # Test sur la touche 'y' (redo alternatif)
    assert "'y'" in html
    # Detection Mac vs PC (metaKey vs ctrlKey)
    assert "metaKey" in html
    assert "ctrlKey" in html


def test_render_html_key_state_isole_par_preset():
    """KEY_STATE varie quand le preset_name change : 2 variantes => 2 cles distinctes."""
    html_a = _render(name="cat.png", preset_name="iso_trait_v3_anomaly_split")
    html_b = _render(name="cat.png", preset_name="floodfill_chromakey_v1")
    # KEY_STATE present dans les 2
    assert "coloring.state." in html_a
    assert "coloring.state." in html_b
    # Le nom du preset doit apparaitre dans le JS d'init (en chaine encodee).
    assert "iso_trait_v3_anomaly_split" in html_a
    assert "floodfill_chromakey_v1" in html_b
    # Les valeurs doivent etre encodees (presence des injections JSON-quoted).
    assert '"iso_trait_v3_anomaly_split"' in html_a
    assert '"floodfill_chromakey_v1"' in html_b


def test_render_html_key_state_isole_par_name():
    """KEY_STATE varie quand le name change : 2 fichiers => 2 cles distinctes."""
    html_a = _render(name="cat.png", preset_name="p1")
    html_b = _render(name="dog.png", preset_name="p1")
    assert '"cat.png"' in html_a
    assert '"dog.png"' in html_b
    # Pas de fuite croisee
    assert '"dog.png"' not in html_a
    assert '"cat.png"' not in html_b


def test_render_html_setregioncolor_supporte_fromhistory():
    """setRegionColor refactore : prend un 3e parametre fromHistory."""
    html = _render()
    # Signature avec 3 args (regex-friendly : "function setRegionColor(r,c,fromHistory)")
    assert "function setRegionColor(r,c,fromHistory)" in html
    # Pousse sur undoStack quand !fromHistory
    assert "undoStack.push" in html


def test_render_html_btn_reset_reversible():
    """Le btn-reset capture un snapshot before et pousse un bulk_swap reversible."""
    html = _render()
    # Le handler reset utilise captureState() pour snapshot before
    # + push un bulk_swap (pas un simple clear)
    assert "type:'bulk_swap'" in html or 'type:"bulk_swap"' in html


def test_render_html_auto_palette_reversible():
    """Les boutons auto rainbow/pastel/vibrant doivent etre reversibles via undo."""
    html = _render()
    # applyAutoPalette appelle setRegionColor avec fromHistory=true pour eviter
    # de spammer undoStack, puis push 1 seul bulk_swap.
    assert "applyAutoPalette" in html
    # Le push bulk_swap apparait au moins 2 fois (reset + auto-palette)
    assert html.count("bulk_swap") >= 2
