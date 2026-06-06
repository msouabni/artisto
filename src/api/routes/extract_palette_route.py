"""Endpoint API pour l'exploration coloriage depuis le playground.

Mode EXPLORATION : pas d'integration dans le pipeline. Telecharge une image
generee par ComfyUI, lance extract_palette + render HTML coloriage interactif,
retourne le HTML pret a afficher dans un nouvel onglet du browser.

Endpoint :
    GET /api/extract-palette/coloriage?filename=...&subfolder=...&type=output
        &preset=iso_trait_v3_anomaly_split
    -> HTML coloriage interactif (palette + click-to-fill + voir solution)
"""
from __future__ import annotations

import base64
import html as html_escape
import json
import logging
import os
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from services.extract_palette import (
    PROD_PRESET,
    PRESETS,
    _detect_chromakey_mask,
    _detect_ink_mask,
    _extract_svg_inner,
    _generate_auto_palette,
    _points_to_path_d,
    extract_palette,
    make_params,
)

logger = logging.getLogger(__name__)

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")

router = APIRouter(prefix="/api/extract-palette", tags=["extract-palette"])

# Palette riche categorisee : 4 categories predefinies x 12 couleurs +
# 1 categorie Custom alimentee par color picker HSL (cf. _render_html).
# Acte chantier C3.1 (2026-06-07).
PALETTES_BY_CATEGORY: dict[str, list[str]] = {
    "Vifs": [
        "#E63946", "#F18F01", "#FFE03A", "#00B4D8",
        "#3A86FF", "#D946EF", "#FF6392", "#06AED5",
        "#FF7F50", "#8AC926", "#B5179E", "#FB5607",
    ],
    "Pastels": [
        "#FFB5A7", "#FCD5CE", "#F8EDEB", "#E8E8E4",
        "#D8E2DC", "#FFE5D9", "#FFCAD4", "#C5DEDD",
        "#BFD7EA", "#B5C6E0", "#DDDDF6", "#E5D4FF",
    ],
    "Terre": [
        "#8B5A3C", "#A0522D", "#C68642", "#DEB887",
        "#F4A460", "#D2691E", "#BC8F8F", "#CD853F",
        "#DAA520", "#BDB76B", "#6B8E23", "#556B2F",
    ],
    "Monochromes": [
        "#000000", "#1A1A1A", "#333333", "#4D4D4D",
        "#666666", "#808080", "#999999", "#B3B3B3",
        "#CCCCCC", "#E0E0E0", "#F0F0F0", "#FFFFFF",
    ],
}

# Retrocompat : code legacy peut importer DEFAULT_PALETTE comme liste plate.
# Concatenation des 4 categories dans l'ordre Vifs > Pastels > Terre > Monochromes.
DEFAULT_PALETTE: list[str] = [
    c for cat in PALETTES_BY_CATEGORY.values() for c in cat
]

# Emoji / glyphe associe a chaque categorie pour l'en-tete <summary>.
_CATEGORY_ICONS: dict[str, str] = {
    "Vifs": "🎨",
    "Pastels": "🌸",
    "Terre": "🌍",
    "Monochromes": "◐",
    "Custom": "✨",
}

# Label affiche pour la categorie Custom.
_CUSTOM_LABEL = "Personnalisé"


def _detect_background_region_index(regions, viewbox_w: int, viewbox_h: int) -> int | None:
    """Identifie l'index de la region "fond" : la plus grande qui touche un bord du canvas.

    Heuristique : sur un coloriage, le fond est la zone exterieure au sujet,
    elle est toujours la plus grande composante qui touche un (ou plusieurs)
    bords du canvas.
    """
    bg_idx = None
    max_area = 0
    margin = 2  # tolerance bord
    for i, r in enumerate(regions):
        x, y, w, h = r.bbox
        touches_border = (
            x <= margin or y <= margin
            or x + w >= viewbox_w - margin or y + h >= viewbox_h - margin
        )
        if touches_border and r.area > max_area:
            max_area = r.area
            bg_idx = i
    return bg_idx


def _build_coloring_svg(res, viewbox_w: int, viewbox_h: int, lock_bg: bool = True,
                          region_stroke_width: int = 1) -> str:
    parts = []
    parts.append(
        f'<rect x="0" y="0" width="{viewbox_w}" height="{viewbox_h}" fill="#ffffff"/>'
    )
    bg_idx = _detect_background_region_index(res.regions, viewbox_w, viewbox_h) if lock_bg else None
    region_paths = []
    for i, r in enumerate(res.regions):
        idx = i + 1
        d = _points_to_path_d(r.points)
        r8, g8, b8 = r.color_rgb
        natural = f"rgb({r8},{g8},{b8})"
        bx, by, bw, bh = r.bbox
        cx, cy = bx + bw // 2, by + bh // 2
        is_bg = (i == bg_idx)
        bg_attrs = ' data-bg="1"' if is_bg else ""
        bg_class = " region-bg" if is_bg else ""
        region_paths.append(
            f'<path d="{d}" fill="#ffffff" stroke="#ffffff" stroke-width="{region_stroke_width}" '
            f'stroke-linejoin="round" stroke-linecap="round" '
            f'class="region{bg_class}" data-region-id="{r.color_id}-{r.area}" '
            f'data-idx="{idx}" data-cid="{r.color_id}" data-area="{r.area}" '
            f'data-cx="{cx}" data-cy="{cy}" '
            f'data-natural="{natural}"{bg_attrs}/>'
        )
    parts.append(f'<g class="regions">{"".join(region_paths)}</g>')
    if res.ink_svg_inline:
        inner = _extract_svg_inner(res.ink_svg_inline)
        parts.append(f'<g class="ink-layer" style="pointer-events:none;">{inner}</g>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {viewbox_w} {viewbox_h}" '
        f'preserveAspectRatio="xMidYMid meet" class="canvas-svg">\n'
        f'  {"".join(parts)}\n'
        f'</svg>'
    )


def _render_palette_accordion_html() -> str:
    """Construit le HTML de la palette categorisee (4 categories + Custom).

    - Une categorie = un <details> collapsible. Vifs ouvert par defaut, override
      par localStorage en JS (cf. _render_html script).
    - Chaque swatch est un <button class="swatch"> avec data-color, title, aria-label.
    - La categorie Custom contient un <input type="color"> + bouton "+ Ajouter" +
      conteneur recent-customs (rempli en JS depuis localStorage).
    """
    blocks: list[str] = []
    first = True
    for category, colors in PALETTES_BY_CATEGORY.items():
        icon = _CATEGORY_ICONS.get(category, "")
        cat_esc = html_escape.escape(category)
        open_attr = " open" if first else ""
        first = False
        swatches = "".join(
            f'<button type="button" class="swatch" data-color="{html_escape.escape(c)}" '
            f'style="background:{html_escape.escape(c)};" '
            f'title="{html_escape.escape(c)}" '
            f'aria-label="Couleur {html_escape.escape(c)}"></button>'
            for c in colors
        )
        blocks.append(
            f'<details class="category-block"{open_attr} data-category="{cat_esc}">'
            f'<summary>{icon} <span class="cat-label">{cat_esc}</span></summary>'
            f'<div class="swatches">{swatches}</div>'
            f'</details>'
        )
    # Bloc Custom : color picker + bouton ajouter + grille recent-customs.
    custom_icon = _CATEGORY_ICONS["Custom"]
    custom_label = html_escape.escape(_CUSTOM_LABEL)
    blocks.append(
        '<details class="category-block category-custom" data-category="Custom">'
        f'<summary>{custom_icon} <span class="cat-label">{custom_label}</span></summary>'
        '<div class="custom-picker">'
        '<input type="color" id="custom-color" value="#888888" '
        'aria-label="Choisir couleur personnalisée"/>'
        '<button class="btn-add-custom" type="button">+ Ajouter</button>'
        '<div class="recent-customs" aria-label="Couleurs récentes personnalisées"></div>'
        '</div>'
        '</details>'
    )
    return (
        '<div class="palette-accordion" role="region" aria-label="Palette couleurs">'
        + "".join(blocks)
        + "</div>"
    )


def _render_html(name: str, source_url: str, svg_inline: str, n_regions: int,
                  preset_name: str, elapsed_ms: float) -> str:
    palette_html = _render_palette_accordion_html()
    auto_palettes = {
        "rainbow": [f"rgb({r},{g},{b})" for r, g, b in _generate_auto_palette(n_regions, "rainbow")],
        "pastel":  [f"rgb({r},{g},{b})" for r, g, b in _generate_auto_palette(n_regions, "pastel")],
        "vibrant": [f"rgb({r},{g},{b})" for r, g, b in _generate_auto_palette(n_regions, "vibrant")],
    }
    auto_palettes_json = json.dumps(auto_palettes)
    # Cle localStorage isolee par (name, preset_name) : chaque variante de
    # coloriage (meme image, preset different) a son propre etat sauvegarde.
    # On json.dumps les valeurs pour eviter tout probleme d'echappement
    # (quotes, backslashes) lors de l'injection dans le JS.
    key_state_name_json = json.dumps(name)
    key_state_preset_json = json.dumps(preset_name)

    style = """
    *{box-sizing:border-box;} body{font-family:system-ui,sans-serif;background:#fafafa;color:#222;margin:0;padding:1rem;}
    h1{margin:0 0 .25rem 0;font-size:1.05rem;font-family:ui-monospace,Menlo,Consolas,monospace;}
    header{background:#fff;border:1px solid #ddd;border-radius:.5rem;padding:.75rem 1rem;margin-bottom:1rem;position:sticky;top:.5rem;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.04);}
    .controls{display:flex;flex-wrap:wrap;align-items:flex-start;gap:.5rem;margin-top:.5rem;}
    .palette-accordion{display:flex;flex-direction:column;gap:.4rem;flex:1 1 260px;min-width:240px;max-width:420px;}
    .category-block{background:#fff;border:1px solid #ddd;border-radius:.4rem;overflow:hidden;}
    .category-block summary{cursor:pointer;padding:.5rem .75rem;font-weight:600;font-size:.85rem;background:#f8f8f8;list-style:none;user-select:none;}
    .category-block summary::-webkit-details-marker{display:none;}
    .category-block summary:hover{background:#f0f0f0;}
    .category-block[open] summary{background:#e8e8e8;}
    .category-block .swatches{display:grid;grid-template-columns:repeat(6,1fr);gap:.3rem;padding:.5rem;}
    @media (max-width:480px){.category-block .swatches{grid-template-columns:repeat(8,1fr);}}
    .swatch{width:100%;aspect-ratio:1;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #bbb;cursor:pointer;padding:0;transition:transform .08s;}
    .swatch:hover{transform:scale(1.12);box-shadow:0 0 0 1px #666;}
    .swatch.active{box-shadow:0 0 0 3px #222;transform:scale(1.05);}
    .category-custom .custom-picker{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;padding:.5rem;}
    .category-custom input[type=color]{width:48px;height:36px;cursor:pointer;border:1px solid #ccc;border-radius:.3rem;padding:0;background:transparent;}
    .btn-add-custom{background:#f0f0f0;border:1px solid #c8c8c8;border-radius:.3rem;padding:.35rem .65rem;font-size:.75rem;cursor:pointer;}
    .btn-add-custom:hover{background:#e5e5e5;}
    .recent-customs{display:grid;grid-template-columns:repeat(8,1fr);gap:.25rem;width:100%;margin-top:.3rem;}
    .recent-customs:empty{display:none;}
    .actions{display:flex;flex-wrap:wrap;gap:.4rem;align-content:flex-start;}
    .btn{background:#f0f0f0;border:1px solid #c8c8c8;border-radius:.4rem;padding:.4rem .7rem;font-size:.82rem;cursor:pointer;font-family:ui-monospace,Menlo,Consolas,monospace;}
    .btn:hover{background:#e5e5e5;} .btn.active{background:#222;color:#fff;border-color:#222;}
    .btn:disabled{opacity:.45;cursor:not-allowed;background:#f5f5f5;}
    .btn:disabled:hover{background:#f5f5f5;}
    main{background:#fff;border:1px solid #ddd;border-radius:.5rem;padding:1rem;max-width:920px;margin:0 auto;}
    .canvas{background:#fff;border:1px solid #eee;border-radius:.3rem;overflow:hidden;}
    .canvas-svg{width:100%;height:auto;display:block;}
    .region{cursor:pointer;transition:filter .12s,opacity .12s;}
    .region:hover{filter:brightness(.85);}
    body.solution .region{pointer-events:none;}
    body.show-zones .region{stroke:#999 !important;stroke-width:0.7 !important;}
    /* Fond verrouille : non cliquable + curseur par defaut + opacite legere */
    .region.region-bg{pointer-events:none !important;cursor:default !important;}
    .region.region-bg:hover{filter:none !important;}
    body.show-zones .region.region-bg{stroke-dasharray:3 3;stroke:#bbb !important;}
    .meta{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.75rem;color:#666;margin-top:.5rem;}
    """
    script = f"""
    let currentColor='#E63946';
    const allSwatches=document.querySelectorAll('.swatch');
    function setActiveSwatch(color){{
        const target=(color||'').toUpperCase();
        document.querySelectorAll('.swatch').forEach(x=>{{
            const dc=(x.dataset.color||'').toUpperCase();
            x.classList.toggle('active', dc===target);
        }});
    }}
    allSwatches.forEach(s=>s.addEventListener('click',()=>{{
        currentColor=s.dataset.color;
        setActiveSwatch(currentColor);
    }}));
    if(allSwatches.length){{
        currentColor=allSwatches[0].dataset.color;
        setActiveSwatch(currentColor);
    }}
    // === Persistance categorie ouverte (localStorage : 1 seule ouverte a la fois) ===
    const KEY_OPEN_CAT='coloring.category-open';
    const savedOpen=localStorage.getItem(KEY_OPEN_CAT) || 'Vifs';
    const catBlocks=document.querySelectorAll('details.category-block');
    catBlocks.forEach(d=>{{
        d.open=(d.dataset.category===savedOpen);
        d.addEventListener('toggle',()=>{{
            if(d.open){{
                localStorage.setItem(KEY_OPEN_CAT, d.dataset.category);
                // Mode "1 seule ouverte" : ferme les autres pour eviter overflow vertical.
                catBlocks.forEach(other=>{{ if(other!==d && other.open) other.open=false; }});
            }}
        }});
    }});
    // === Custom color picker + recent customs persistes ===
    const KEY_RECENT_CUSTOMS='coloring.recent-customs';
    let recentList;
    try {{ recentList=JSON.parse(localStorage.getItem(KEY_RECENT_CUSTOMS) || '[]'); }}
    catch(e) {{ recentList=[]; }}
    if(!Array.isArray(recentList)) recentList=[];
    const recentContainer=document.querySelector('.recent-customs');
    function renderRecentCustoms(){{
        if(!recentContainer) return;
        recentContainer.innerHTML='';
        recentList.forEach(hex=>{{
            const btn=document.createElement('button');
            btn.type='button';
            btn.className='swatch';
            btn.dataset.color=hex;
            btn.style.background=hex;
            btn.title=hex;
            btn.setAttribute('aria-label','Couleur récente '+hex);
            btn.addEventListener('click',()=>{{
                currentColor=hex;
                setActiveSwatch(hex);
            }});
            recentContainer.appendChild(btn);
        }});
    }}
    renderRecentCustoms();
    const btnAddCustom=document.querySelector('.btn-add-custom');
    if(btnAddCustom){{
        btnAddCustom.addEventListener('click',()=>{{
            const picker=document.getElementById('custom-color');
            if(!picker) return;
            const hex=picker.value.toUpperCase();
            // dedup (case-insensitive) + max 8 elements (LRU).
            const filtered=[hex, ...recentList.filter(c=>(c||'').toUpperCase()!==hex)].slice(0,8);
            recentList.length=0;
            recentList.push(...filtered);
            try {{ localStorage.setItem(KEY_RECENT_CUSTOMS, JSON.stringify(recentList)); }} catch(e) {{}}
            renderRecentCustoms();
            currentColor=hex;
            setActiveSwatch(hex);
        }});
    }}
    // === Regions click + reset + solution + zones ===
    const regions=document.querySelectorAll('.region');
    // === Undo/redo + auto-save localStorage (C3.2) ===
    // Cle KEY_STATE isolee par (name, preset_name) : chaque variante a son etat.
    const KEY_STATE='coloring.state.'+encodeURIComponent({key_state_name_json})+'__'+encodeURIComponent({key_state_preset_json});
    const undoStack=[];
    const redoStack=[];
    const MAX_STACK=50;
    // Helper : capture l'etat regions colorees (idx -> hex), exclut fond + blanc.
    function captureState(){{
        const out={{}};
        regions.forEach(r=>{{
            if(r.dataset.bg==='1') return;
            if(r.dataset.user && r.dataset.user!=='#ffffff') out[r.dataset.idx]=r.dataset.user;
        }});
        return out;
    }}
    // setRegionColor : push 'paint' sur undoStack sauf si fromHistory=true.
    // Appels programmatiques (restore, applyAction, auto-palette) passent true.
    function setRegionColor(r,c,fromHistory){{
        const prev=r.dataset.user||'#ffffff';
        if(String(prev).toUpperCase()===String(c).toUpperCase()) return;
        r.setAttribute('fill',c);
        r.setAttribute('stroke',c);
        if(c==='#ffffff') delete r.dataset.user; else r.dataset.user=c;
        if(!fromHistory){{
            undoStack.push({{type:'paint', idx:r.dataset.idx, prev:prev, next:c}});
            if(undoStack.length>MAX_STACK) undoStack.shift();
            redoStack.length=0;
            saveState();
            updateUndoRedoButtons();
        }}
    }}
    // Applique un snapshot (idx->color) : tout ce qui n'est pas dans snapshot revient a blanc.
    function applySnapshot(snapshot){{
        regions.forEach(r=>{{
            if(r.dataset.bg==='1') return;
            const target=snapshot[r.dataset.idx]||'#ffffff';
            r.setAttribute('fill',target);
            r.setAttribute('stroke',target);
            if(target==='#ffffff') delete r.dataset.user; else r.dataset.user=target;
        }});
    }}
    // applyAction : reverse=true pour undo (restore 'before' / 'prev'),
    // reverse=false pour redo (applique 'after' / 'next').
    function applyAction(action, reverse){{
        try {{
            if(action.type==='paint'){{
                const target=reverse?action.prev:action.next;
                const r=document.querySelector('.region[data-idx="'+action.idx+'"]');
                if(r && r.dataset.bg!=='1'){{
                    r.setAttribute('fill',target);
                    r.setAttribute('stroke',target);
                    if(target==='#ffffff') delete r.dataset.user; else r.dataset.user=target;
                }}
            }} else if(action.type==='bulk_swap'){{
                applySnapshot(reverse?action.before:action.after);
            }}
        }} catch(e) {{ /* idx inexistant suite a changement SVG : ignore silencieusement */ }}
    }}
    function doUndo(){{
        const a=undoStack.pop(); if(!a) return;
        applyAction(a,true);
        redoStack.push(a);
        saveState();
        updateUndoRedoButtons();
    }}
    function doRedo(){{
        const a=redoStack.pop(); if(!a) return;
        applyAction(a,false);
        undoStack.push(a);
        saveState();
        updateUndoRedoButtons();
    }}
    function updateUndoRedoButtons(){{
        const u=document.getElementById('btn-undo');
        const r=document.getElementById('btn-redo');
        if(u) u.disabled=undoStack.length===0;
        if(r) r.disabled=redoStack.length===0;
    }}
    function saveState(){{
        try {{
            const state={{
                regions:captureState(),
                undoStack:undoStack.slice(-MAX_STACK),
                redoStack:redoStack.slice(-MAX_STACK),
                v:1,
            }};
            localStorage.setItem(KEY_STATE, JSON.stringify(state));
        }} catch(e) {{ /* quota / mode prive : ignore */ }}
    }}
    function restoreState(){{
        try {{
            const raw=localStorage.getItem(KEY_STATE);
            if(!raw) return;
            const data=JSON.parse(raw);
            if(!data || data.v!==1) return;
            Object.entries(data.regions||{{}}).forEach(([idx,color])=>{{
                const r=document.querySelector('.region[data-idx="'+idx+'"]');
                if(r && r.dataset.bg!=='1'){{
                    r.setAttribute('fill',color);
                    r.setAttribute('stroke',color);
                    r.dataset.user=color;
                }}
            }});
            if(Array.isArray(data.undoStack)) undoStack.push(...data.undoStack);
            if(Array.isArray(data.redoStack)) redoStack.push(...data.redoStack);
            updateUndoRedoButtons();
        }} catch(e) {{ /* corrompu : on ignore */ }}
    }}
    document.getElementById('btn-undo')?.addEventListener('click',doUndo);
    document.getElementById('btn-redo')?.addEventListener('click',doRedo);
    // Raccourcis clavier : Ctrl+Z = undo, Ctrl+Shift+Z / Ctrl+Y = redo (Cmd sur Mac).
    document.addEventListener('keydown',e=>{{
        const isMac=/Mac|iPad|iPhone|iPod/.test(navigator.platform);
        const meta=isMac?e.metaKey:e.ctrlKey;
        if(!meta) return;
        const key=(e.key||'').toLowerCase();
        if(key==='z' && !e.shiftKey){{ e.preventDefault(); doUndo(); }}
        else if((key==='z' && e.shiftKey) || key==='y'){{ e.preventDefault(); doRedo(); }}
    }});
    // === Regions click (utilise setRegionColor qui gere undo automatiquement) ===
    regions.forEach(r=>r.addEventListener('click',e=>{{
        if(r.dataset.bg==='1') return;
        e.stopPropagation();
        setRegionColor(r,currentColor);
    }}));
    // === Btn reset : push bulk_swap reversible (before=snapshot, after={{}}) ===
    document.getElementById('btn-reset').addEventListener('click',()=>{{
        const before=captureState();
        if(Object.keys(before).length===0){{
            // Rien a effacer : on nettoie quand meme l'overlay solution.
            document.body.classList.remove('solution');
            document.getElementById('btn-solution').classList.remove('active');
            return;
        }}
        applySnapshot({{}});  // efface tout (sauf fond)
        undoStack.push({{type:'bulk_swap', before:before, after:{{}}}});
        if(undoStack.length>MAX_STACK) undoStack.shift();
        redoStack.length=0;
        document.body.classList.remove('solution');
        document.getElementById('btn-solution').classList.remove('active');
        saveState();
        updateUndoRedoButtons();
    }});
    const btnSolution=document.getElementById('btn-solution');
    btnSolution.addEventListener('click',()=>{{
        const s=document.body.classList.toggle('solution');
        btnSolution.classList.toggle('active',s);
        regions.forEach(r=>{{
            if(r.dataset.bg==='1') return;
            if(s){{r.dataset.userBackup=r.getAttribute('fill');r.setAttribute('fill',r.dataset.natural);r.setAttribute('stroke',r.dataset.natural);}}
            else{{const b=r.dataset.userBackup||'#ffffff';r.setAttribute('fill',b);r.setAttribute('stroke',b);}}
        }});
    }});
    const btnZones=document.getElementById('btn-zones');
    btnZones.addEventListener('click',()=>{{
        const s=document.body.classList.toggle('show-zones');
        btnZones.classList.toggle('active',s);
    }});
    const AUTO_PALETTES={auto_palettes_json};
    // Auto-palette : capture before -> applique sans pousser sur stack (fromHistory)
    // -> capture after -> push 1 seul bulk_swap reversible.
    function applyAutoPalette(name){{
        const pal=AUTO_PALETTES[name]; if(!pal) return;
        const before=captureState();
        const groups={{}};
        regions.forEach(r=>{{
            if(r.dataset.bg==='1') return;
            const cid=r.dataset.regionId.split('-')[0]; if(!groups[cid])groups[cid]=[]; groups[cid].push(r);
        }});
        const keys=Object.keys(groups).sort((a,b)=>parseInt(a)-parseInt(b));
        keys.forEach((cid,idx)=>{{const c=pal[idx%pal.length]; groups[cid].forEach(r=>setRegionColor(r,c,true));}});
        const after=captureState();
        // No-op si rien change (rare : meme palette deja appliquee).
        if(JSON.stringify(before)===JSON.stringify(after)) return;
        undoStack.push({{type:'bulk_swap', before:before, after:after}});
        if(undoStack.length>MAX_STACK) undoStack.shift();
        redoStack.length=0;
        saveState();
        updateUndoRedoButtons();
    }}
    document.getElementById('btn-rainbow').addEventListener('click',()=>applyAutoPalette('rainbow'));
    document.getElementById('btn-pastel').addEventListener('click',()=>applyAutoPalette('pastel'));
    document.getElementById('btn-vibrant').addEventListener('click',()=>applyAutoPalette('vibrant'));
    // Restore au load : applique regions sauvegardees + restaure les stacks.
    restoreState();
    """
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"/><title>Coloriage — {html_escape.escape(name)}</title><style>{style}</style></head>
<body><header>
<h1>Coloriage : {html_escape.escape(name)}</h1>
<div class="meta">{n_regions} régions · preset : {html_escape.escape(preset_name)} · extraction : {elapsed_ms:.0f} ms</div>
<div class="controls">
  {palette_html}
  <div class="actions">
    <button id="btn-undo" class="btn" title="Annuler (Ctrl+Z)" disabled>↶ Annuler</button>
    <button id="btn-redo" class="btn" title="Rétablir (Ctrl+Shift+Z)" disabled>↷ Rétablir</button>
    <button id="btn-reset" class="btn">tout effacer</button>
    <button id="btn-solution" class="btn">voir la solution</button>
    <button id="btn-zones" class="btn">afficher zones</button>
    <button id="btn-rainbow" class="btn">auto rainbow</button>
    <button id="btn-pastel" class="btn">auto pastel</button>
    <button id="btn-vibrant" class="btn">auto vibrant</button>
  </div>
</div></header>
<main><div class="canvas">{svg_inline}</div></main>
<script>{script}</script>
</body></html>
"""


def _parse_colors_param(colors_str: str) -> list[tuple[int, int, int]] | None:
    """Parse '#ffe89c,#ffc8a8,#abcdef' ou 'ffe89c,ffc8a8' en liste de tuples RGB."""
    if not colors_str:
        return None
    out = []
    for token in colors_str.split(","):
        t = token.strip().lstrip("#").lower()
        if len(t) == 6:
            try:
                r = int(t[0:2], 16); g = int(t[2:4], 16); b = int(t[4:6], 16)
                out.append((r, g, b))
            except ValueError:
                continue
    return out or None


@router.get("/detect-palette")
async def detect_palette(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
    n: int = Query(16, ge=2, le=64, description="Nombre de couleurs cibles (8/16/32 recommande)"),
) -> dict:
    """Telecharge l'image depuis ComfyUI et retourne la palette dominante via k-means LAB.

    Reponse :
        {
            "n_colors": 16,
            "colors": ["#RRGGBB", ...],          # tries par frequence DESC
            "frequencies_pct": [12.3, 10.1, ...] # % de pixels par couleur
        }
    """
    import io
    import cv2
    import numpy as np
    from PIL import Image

    # 1. Download
    params = {"filename": filename, "subfolder": subfolder, "type": type}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{COMFY_URL}/view", params=params)
    except httpx.RequestError as e:
        raise HTTPException(502, f"ComfyUI inaccessible : {e}") from e
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"ComfyUI view failed: {r.text[:200]}")

    # 2. Decode + K-means LAB
    img_pil = Image.open(io.BytesIO(r.content)).convert("RGB")
    img_rgb = np.array(img_pil)
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    pixels = img_lab.reshape(-1, 3)
    if len(pixels) < n:
        n = max(2, len(pixels))

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers_lab = cv2.kmeans(
        pixels, n, None, criteria, 5, cv2.KMEANS_PP_CENTERS
    )

    # 3. Frequence de chaque cluster
    counts = np.bincount(labels.flatten(), minlength=n)
    total = counts.sum()
    freq_pct = (counts * 100.0 / total).tolist()

    # 4. Convertit centres LAB -> RGB hex
    centers_lab_u8 = np.clip(centers_lab, 0, 255).astype(np.uint8).reshape(1, -1, 3)
    centers_bgr = cv2.cvtColor(centers_lab_u8, cv2.COLOR_LAB2BGR).reshape(-1, 3)
    hex_colors = [
        f"#{c[2]:02X}{c[1]:02X}{c[0]:02X}" for c in centers_bgr  # B G R -> R G B
    ]

    # 5. Tri par frequence DESC
    pairs = sorted(zip(hex_colors, freq_pct), key=lambda x: -x[1])
    sorted_hex = [p[0] for p in pairs]
    sorted_freq = [round(p[1], 2) for p in pairs]

    return {
        "n_colors": n,
        "colors": sorted_hex,
        "frequencies_pct": sorted_freq,
    }


@router.get("/coloriage", response_class=HTMLResponse)
async def coloriage_from_comfy(
    filename: str = Query(..., description="Nom du fichier image dans ComfyUI"),
    subfolder: str = Query("", description="Sous-dossier ComfyUI (default vide)"),
    type: str = Query("output", description="Type ComfyUI : output, input, temp"),
    preset: str = Query(PROD_PRESET, description="Preset extract_palette"),
    colors: str = Query("", description="Palette imposee : hex CSV, ex '#ffe89c,#ffc8a8'. Si vide -> k-means classique."),
    # === Overrides parametres TRAIT (None = utilise le preset) ===============
    ink_pipeline: str | None = Query(None, pattern="^(simple|skeleton)$"),
    ink_max_value: int | None = Query(None, ge=20, le=200, description="HSV V max (def preset, ~80)"),
    ink_max_sat: int | None = Query(None, ge=20, le=255, description="HSV S max (def preset, ~60)"),
    otsu_max: int | None = Query(None, ge=20, le=200, description="Plafond Otsu (def preset, ~90)"),
    otsu_max_sat: int | None = Query(None, ge=0, le=255, description="Saturation max pour branche Otsu (def preset, 60 pour chromakey, 255 ailleurs). Empeche les couleurs vives sombres d'etre classees trait."),
    geodesic_d: int | None = Query(None, ge=1, le=30, description="Filtre geodesic distance max au noir vrai (def 8 chromakey). Plus haut = trait + continu mais + bleu reste classe trait."),
    no_otsu: bool = Query(False, description="Desactive Otsu, HSV seul"),
    ink_dilate: int | None = Query(None, ge=0, le=10, description="Dilatation finale trait (def preset, ~1)"),
    close_radius: int | None = Query(None, ge=0, le=10, description="Morpho close (def preset, ~3)"),
    ink_thickness: int | None = Query(None, ge=1, le=8, description="Epaisseur cible si skeleton (def 2)"),
    ink_min_speckle: int | None = Query(None, ge=0, le=200, description="Filtre composantes speckle (def 20)"),
    # === Overrides parametres ZONES =========================================
    mask_smooth: int | None = Query(None, ge=0, le=15, description="OPEN+CLOSE intra-couleur (def 0). 3-5 elimine les ruisseaux."),
    merge_small: int | None = Query(None, ge=0, le=5000, description="Composantes < N px fusionnees (def preset, ~400)"),
    no_anomaly: bool = Query(False, description="Desactive anomaly_detection (peut interferer avec palette imposee)"),
    no_expand: bool = Query(False, description="Desactive expand_to_ink (Voronoi vers trait)"),
    min_region_pct: float | None = Query(None, ge=0.00001, le=0.01, description="Surface min region (frac canvas). Def preset (~0.0002 floodfill, ~0.001 kmeans)"),
    # === Overrides FLOODFILL CHROMAKEY (preset floodfill_chromakey_v1) =======
    chromakey_de: float | None = Query(None, ge=5.0, le=80.0, description="Tolerance LAB chromakey (def 25). Reduire = + strict (preserve anti-aliasing)."),
    flood_dilate: int | None = Query(None, ge=0, le=5, description="Dilate trait avant flood (def 1). 0 = sans dilate, preserve micro-zones."),
    flood_min: int | None = Query(None, ge=10, le=2000, description="Aire min bassin px (def 50). Reduire pour preserver les micro-details."),
    region_stroke: int | None = Query(None, ge=0, le=6, description="Epaisseur stroke regions px (def 2 floodfill, 1 prod). Comble les pixels orphelins en bordure."),
    # === UX coloriage ========================================================
    lock_bg: bool = Query(True, description="Verrouille la region du fond (non cliquable). True = production."),
) -> HTMLResponse:
    """Telecharge une image generee par ComfyUI + extract_palette + HTML coloriage interactif.

    Si ``colors`` fourni (liste hex), bypasse le k-means et attribue chaque
    pixel a la couleur de palette la plus proche en LAB perceptuel.

    Tous les params trait (ink_*) sont optionnels - si None, utilise le preset.
    """
    if preset not in PRESETS:
        raise HTTPException(400, f"Preset inconnu : {preset}. Choix : {list(PRESETS)[:5]}...")
    forced_palette = _parse_colors_param(colors)
    # 1. Telecharger l'image depuis ComfyUI
    params = {"filename": filename, "subfolder": subfolder, "type": type}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{COMFY_URL}/view", params=params)
    except httpx.RequestError as e:
        raise HTTPException(502, f"ComfyUI inaccessible : {e}") from e
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"ComfyUI view failed: {r.text[:200]}")

    # 2. Sauve temp + extract_palette
    tmp_dir = Path(tempfile.gettempdir())
    tmp_path = tmp_dir / f"playground_{filename}"
    tmp_path.write_bytes(r.content)
    try:
        import time
        t0 = time.time()
        overrides: dict = {}
        if forced_palette:
            overrides["forced_palette_rgb"] = forced_palette
        # Overrides params trait
        if ink_pipeline is not None: overrides["ink_pipeline"] = ink_pipeline
        if ink_max_value is not None: overrides["ink_max_value"] = ink_max_value
        if ink_max_sat is not None: overrides["ink_max_saturation"] = ink_max_sat
        if otsu_max is not None: overrides["otsu_max_threshold"] = otsu_max
        if otsu_max_sat is not None: overrides["ink_otsu_max_saturation"] = otsu_max_sat
        if geodesic_d is not None: overrides["ink_geodesic_max_distance"] = geodesic_d
        if no_otsu: overrides["use_otsu_grayscale"] = False
        if ink_dilate is not None: overrides["ink_dilate"] = ink_dilate
        if close_radius is not None: overrides["close_radius"] = close_radius
        if ink_thickness is not None: overrides["ink_target_thickness"] = ink_thickness
        if ink_min_speckle is not None: overrides["ink_min_speckle_px"] = ink_min_speckle
        # Overrides ZONES
        if mask_smooth is not None: overrides["morpho_cleanup_radius"] = mask_smooth
        if merge_small is not None: overrides["merge_small_regions_px"] = merge_small
        if no_anomaly: overrides["anomaly_detection_enabled"] = False
        if no_expand: overrides["expand_to_ink"] = False
        if min_region_pct is not None: overrides["min_region_area_ratio"] = min_region_pct
        # Overrides FLOODFILL
        if chromakey_de is not None: overrides["chromakey_delta_e"] = chromakey_de
        if flood_dilate is not None: overrides["flood_pre_dilate"] = flood_dilate
        if flood_min is not None: overrides["flood_min_region_area_px"] = flood_min
        if region_stroke is not None: overrides["region_stroke_width"] = region_stroke
        params_extract = make_params(preset, **overrides)
        result = extract_palette(tmp_path, params_extract)
        elapsed_ms = (time.time() - t0) * 1000
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    # 3. Render HTML coloriage
    svg = _build_coloring_svg(
        result, result.width, result.height,
        lock_bg=lock_bg,
        region_stroke_width=params_extract.region_stroke_width,
    )
    preset_label = preset + (f" + palette imposée ({len(forced_palette)} couleurs)" if forced_palette else "")
    if lock_bg:
        preset_label += " · fond verrouillé"
    html_str = _render_html(
        name=filename,
        source_url=f"/api/comfy/view?filename={filename}&subfolder={subfolder}&type={type}",
        svg_inline=svg,
        n_regions=len(result.regions),
        preset_name=preset_label,
        elapsed_ms=elapsed_ms,
    )
    return HTMLResponse(html_str)


@router.get("/diagnose", response_class=HTMLResponse)
async def diagnose_chromakey(
    filename: str = Query(..., description="Nom du fichier image dans ComfyUI"),
    subfolder: str = Query(""),
    type: str = Query("output"),
    # Chromakey
    chromakey_r: int = Query(0, ge=0, le=255),
    chromakey_g: int = Query(177, ge=0, le=255),
    chromakey_b: int = Query(64, ge=0, le=255),
    chromakey_de: float = Query(25.0, ge=5.0, le=80.0),
    # Trait
    no_otsu: bool = Query(False, description="Desactive Otsu OR (HSV strict only)"),
    otsu_max: int = Query(90, ge=20, le=200),
    otsu_max_sat: int = Query(60, ge=0, le=255, description="Saturation max sur branche Otsu (60 = neutre uniquement, empeche couleurs vives sombres)"),
    ink_max_value: int = Query(80, ge=20, le=200),
    ink_max_sat: int = Query(60, ge=20, le=255),
    ink_dilate: int = Query(1, ge=0, le=10),
    close_radius: int = Query(3, ge=0, le=10),
    # K-means palette
    n_colors: int = Query(16, ge=4, le=64),
) -> HTMLResponse:
    """Diagnostic visuel chromakey + trait + palette LAB du sujet.

    Genere un HTML montrant :
        - Image originale
        - Masque chromakey overlay vert
        - Masque trait overlay rouge
        - Sujet isole (chromakey + trait masques en gris)
        - Palette LAB des pixels sujet (N couleurs avec frequences)
        - Statistiques de couverture des 3 masques

    Permet de juger objectivement :
        - Si le masque trait envahit le sujet (overlay rouge sur silhouette)
        - Si la palette permet de distinguer les regions du sujet
        - L'effet d'override sur les params (no_otsu, otsu_max, etc.)
    """
    import io
    import cv2
    import numpy as np
    from PIL import Image

    # 1. Download
    p_qs = {"filename": filename, "subfolder": subfolder, "type": type}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{COMFY_URL}/view", params=p_qs)
    except httpx.RequestError as e:
        raise HTTPException(502, f"ComfyUI inaccessible : {e}") from e
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"ComfyUI view failed: {r.text[:200]}")

    # 2. Decode
    img_pil = Image.open(io.BytesIO(r.content)).convert("RGB")
    img_rgb = np.array(img_pil)
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    h, w = img_bgr.shape[:2]

    # 3. Build ExtractPaletteParams pour _detect_ink_mask (avec overrides)
    params = make_params(
        "floodfill_chromakey_v1",
        use_otsu_grayscale=not no_otsu,
        otsu_max_threshold=otsu_max,
        ink_otsu_max_saturation=otsu_max_sat,
        ink_max_value=ink_max_value,
        ink_max_saturation=ink_max_sat,
        ink_dilate=ink_dilate,
        close_radius=close_radius,
    )

    # 4. Masques
    chromakey_mask = _detect_chromakey_mask(
        img_bgr, (chromakey_r, chromakey_g, chromakey_b), chromakey_de
    )
    ink_mask = _detect_ink_mask(img_bgr, params)
    subject_mask = ((chromakey_mask == 0) & (ink_mask == 0)).astype(np.uint8) * 255

    # 5. Stats
    total = float(h * w)
    pct_ck = (chromakey_mask > 0).sum() / total * 100
    pct_ink = (ink_mask > 0).sum() / total * 100
    pct_subj = (subject_mask > 0).sum() / total * 100
    pct_overlap = ((chromakey_mask > 0) & (ink_mask > 0)).sum() / total * 100

    # 6. Palette LAB du sujet
    palette: list[tuple[str, float]] = []
    if (subject_mask > 0).sum() > n_colors:
        subj_pixels = img_bgr[subject_mask > 0]
        subj_lab = cv2.cvtColor(
            subj_pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB
        ).astype(np.float32).reshape(-1, 3)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, labels, centers_lab = cv2.kmeans(
            subj_lab, n_colors, None, criteria, 5, cv2.KMEANS_PP_CENTERS
        )
        counts = np.bincount(labels.flatten(), minlength=n_colors)
        freq_pct = (counts * 100.0 / counts.sum()).tolist()
        centers_lab_u8 = np.clip(centers_lab, 0, 255).astype(np.uint8).reshape(1, -1, 3)
        centers_bgr = cv2.cvtColor(centers_lab_u8, cv2.COLOR_LAB2BGR).reshape(-1, 3)
        palette = sorted(
            [
                (f"#{c[2]:02X}{c[1]:02X}{c[0]:02X}", round(f, 2))
                for c, f in zip(centers_bgr, freq_pct)
            ],
            key=lambda x: -x[1],
        )

    # 7. Build overlay images (semi-transparent)
    overlay_ck = img_bgr.copy()
    overlay_ck[chromakey_mask > 0] = (0, 255, 0)  # vert pur BGR
    blend_ck = cv2.addWeighted(img_bgr, 0.5, overlay_ck, 0.5, 0)

    overlay_ink = img_bgr.copy()
    overlay_ink[ink_mask > 0] = (0, 0, 255)  # rouge pur BGR
    blend_ink = cv2.addWeighted(img_bgr, 0.5, overlay_ink, 0.5, 0)

    subject_only = img_bgr.copy()
    subject_only[subject_mask == 0] = (200, 200, 200)  # gris clair

    def _to_b64(img: "np.ndarray") -> str:
        _, buf = cv2.imencode(".png", img)
        return base64.b64encode(buf).decode("ascii")

    img_orig_b64 = _to_b64(img_bgr)
    img_ck_b64 = _to_b64(blend_ck)
    img_ink_b64 = _to_b64(blend_ink)
    img_subj_b64 = _to_b64(subject_only)

    # 8. Render HTML
    palette_html = "".join(
        f'<div class="swatch" title="{hex_} - {pct:.2f}%">'
        f'<div class="chip" style="background:{hex_};"></div>'
        f'<div class="lbl">{hex_}</div>'
        f'<div class="pct">{pct:.1f}%</div></div>'
        for hex_, pct in palette
    )

    # Couleur trait moyenne (info pour decider du seuil)
    if (ink_mask > 0).sum() > 0:
        ink_mean = img_bgr[ink_mask > 0].mean(axis=0)
        ink_mean_hex = f"#{int(ink_mean[2]):02X}{int(ink_mean[1]):02X}{int(ink_mean[0]):02X}"
    else:
        ink_mean_hex = "n/a"

    flags = []
    if pct_ink > 25: flags.append(f"<span class='warn'>! Trait couvre {pct_ink:.1f}% (typique 7-15%) - trait envahit possible</span>")
    if pct_ck < 5: flags.append(f"<span class='warn'>! Chromakey couvre {pct_ck:.1f}% (typique > 30%) - chromakey peu detecte</span>")
    if pct_overlap > 1: flags.append(f"<span class='warn'>! Overlap chromakey ∩ trait : {pct_overlap:.2f}%</span>")
    if not flags: flags.append("<span class='ok'>OK couvertures dans des normes attendues</span>")

    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"/>
<title>Diagnostic chromakey — {html_escape.escape(filename)}</title>
<style>
*{{box-sizing:border-box;}}
body{{font-family:system-ui,sans-serif;background:#fafafa;color:#222;margin:0;padding:1rem;}}
h1{{margin:0 0 .25rem 0;font-size:1rem;font-family:ui-monospace,Menlo,Consolas,monospace;}}
h2{{margin-top:1.5rem;font-size:.9rem;color:#444;border-bottom:1px solid #ddd;padding-bottom:.25rem;}}
.meta{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.75rem;color:#666;margin-bottom:1rem;}}
.row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:.75rem;}}
.cell{{background:#fff;border:1px solid #ddd;border-radius:.4rem;padding:.5rem;}}
.cell h3{{margin:0 0 .25rem 0;font-size:.78rem;color:#555;}}
.cell img{{width:100%;height:auto;display:block;border-radius:.2rem;}}
.stats{{background:#fff;border:1px solid #ddd;border-radius:.4rem;padding:.75rem 1rem;margin-bottom:.5rem;}}
.stats table{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.8rem;border-collapse:collapse;width:100%;}}
.stats td{{padding:.2rem .5rem;border-bottom:1px solid #eee;}}
.stats td:first-child{{color:#666;width:50%;}}
.warn{{color:#b54;font-weight:600;}}
.ok{{color:#2a7;font-weight:600;}}
.swatches{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.4rem;}}
.swatch{{background:#fff;border:1px solid #ddd;border-radius:.3rem;padding:.4rem;text-align:center;}}
.swatch .chip{{width:100%;height:42px;border:1px solid #ccc;border-radius:.2rem;margin-bottom:.2rem;}}
.swatch .lbl{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.7rem;color:#333;}}
.swatch .pct{{font-size:.7rem;color:#888;}}
.params{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.72rem;color:#555;background:#fff;padding:.5rem .75rem;border-radius:.3rem;border:1px solid #ddd;}}
</style></head><body>
<h1>Diagnostic chromakey — {html_escape.escape(filename)}</h1>
<div class="meta">{w}×{h} px · chromakey RGB({chromakey_r},{chromakey_g},{chromakey_b}) ΔE={chromakey_de} · trait : HSV(V&lt;{ink_max_value}, S&lt;{ink_max_sat}){', Otsu≤'+str(otsu_max)+' S&lt;'+str(otsu_max_sat) if not no_otsu else ', Otsu OFF'} · n_colors={n_colors}</div>

<div class="stats">
  <table>
    <tr><td>Chromakey</td><td>{pct_ck:.2f}% du canvas</td></tr>
    <tr><td>Trait</td><td>{pct_ink:.2f}% du canvas (couleur moyenne : {ink_mean_hex})</td></tr>
    <tr><td>Sujet (NOT chromakey AND NOT trait)</td><td>{pct_subj:.2f}% du canvas</td></tr>
    <tr><td>Overlap chromakey ∩ trait</td><td>{pct_overlap:.2f}%</td></tr>
  </table>
  <div style="margin-top:.5rem;">{' | '.join(flags)}</div>
</div>

<h2>Masques visualisés</h2>
<div class="row">
  <div class="cell"><h3>Image originale</h3><img src="data:image/png;base64,{img_orig_b64}"/></div>
  <div class="cell"><h3>Masque chromakey (vert pur)</h3><img src="data:image/png;base64,{img_ck_b64}"/></div>
  <div class="cell"><h3>Masque trait (rouge pur)</h3><img src="data:image/png;base64,{img_ink_b64}"/></div>
  <div class="cell"><h3>Sujet isolé (chromakey + trait → gris)</h3><img src="data:image/png;base64,{img_subj_b64}"/></div>
</div>

<h2>Palette LAB extraite du sujet ({n_colors} clusters, triés par fréquence)</h2>
<div class="swatches">{palette_html}</div>

<h2>Reproduire / Itérer</h2>
<div class="params">Pour tester variantes, ajouter à l'URL :<br/>
&amp;no_otsu=true   → trait HSV strict, désactive Otsu OR<br/>
&amp;otsu_max=40   → Otsu plafond bas (compromis A+B)<br/>
&amp;ink_dilate=0  → pas de dilate (préserve micro-zones)<br/>
&amp;chromakey_de=20  → chromakey + strict<br/>
&amp;n_colors=8    → palette plus large par cluster<br/>
</div>
</body></html>"""
    return HTMLResponse(html)
