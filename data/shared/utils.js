/**
 * utils.js — Utilitaires partagés entre tous les éditeurs d'administration.
 * Pas de dépendances externes. Exporte un objet global `EditorUtils`.
 */
(function (global) {
  'use strict';

  const EditorUtils = {};

  // ── HTML escaping ─────────────────────────────────────────────────────────

  EditorUtils.escHtml = function (s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  // ── Debounce ──────────────────────────────────────────────────────────────

  EditorUtils.debounce = function (fn, ms) {
    let timer = null;
    return function () {
      const args = arguments;
      const ctx = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  };

  // ── API error parsing ─────────────────────────────────────────────────────

  /**
   * Parse le body JSON d'une réponse HTTP en erreur et retourne le message d'erreur.
   * Compatible avec les réponses FastAPI (field `detail`) et les erreurs génériques.
   * @param {Response} res — réponse fetch (non-ok)
   * @returns {Promise<string>}
   */
  EditorUtils.parseApiError = async function (res) {
    let errBody = {};
    try { errBody = await res.json(); } catch (_) {}
    const detail = errBody.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail.message === 'string') {
      let msg = detail.message;
      if (detail.children_count != null) msg += ' (' + detail.children_count + ' enfant(s)).';
      if (detail.references && typeof detail.references === 'object') {
        msg += ' Références : ' + JSON.stringify(detail.references);
      }
      return msg;
    }
    if (detail) return JSON.stringify(detail);
    return res.statusText || 'Erreur HTTP ' + res.status;
  };

  // ── Tree traversal ────────────────────────────────────────────────────────

  /**
   * Cherche un nœud par son `id` dans un arbre (nœuds avec `.children`).
   * @param {Array} nodes
   * @param {string|number} id
   * @returns {object|null}
   */
  EditorUtils.findInTree = function findInTree(nodes, id) {
    if (!nodes) return null;
    for (let i = 0; i < nodes.length; i++) {
      if (String(nodes[i].id) === String(id)) return nodes[i];
      const found = findInTree(nodes[i].children, id);
      if (found) return found;
    }
    return null;
  };

  // ── Theme management ──────────────────────────────────────────────────────

  /**
   * Applique un thème (light/dark) sur le body et le persiste dans localStorage.
   * @param {string} theme — 'light' | 'dark'
   * @param {string} [storageKey] — clé localStorage (défaut : 'editor_theme')
   */
  EditorUtils.applyTheme = function (theme, storageKey) {
    document.body.setAttribute('data-theme', theme);
    const key = storageKey || 'editor_theme';
    try { localStorage.setItem(key, theme); } catch (_) {}
    document.querySelectorAll('.btn-theme-light, .btn-theme-dark').forEach(function (btn) {
      const isActive = btn.classList.contains('btn-theme-' + theme);
      btn.classList.toggle('active', isActive);
    });
  };

  EditorUtils.loadTheme = function (storageKey) {
    const key = storageKey || 'editor_theme';
    try {
      const saved = localStorage.getItem(key);
      if (saved === 'light' || saved === 'dark') return saved;
    } catch (_) {}
    return 'light';
  };

  // ── Keywords helpers ──────────────────────────────────────────────────────

  EditorUtils.parseKeywords = function (value) {
    if (Array.isArray(value)) return value;
    if (!value) return [];
    return String(value).split(/[,;]/).map(function (s) { return s.trim(); }).filter(Boolean);
  };

  EditorUtils.keywordsToString = function (value) {
    if (Array.isArray(value)) return value.join(', ');
    return String(value || '');
  };

  // ── API base URL ──────────────────────────────────────────────────────────

  /**
   * Retourne le préfixe de l'API selon le contexte d'exécution.
   * En mode fichier (file://), on pointe vers localhost:port.
   * En mode servi, on utilise l'origine courante (chemin vide).
   * @param {number} [port=8000]
   */
  EditorUtils.apiBase = function (port) {
    return (window.location.protocol === 'file:')
      ? ('http://localhost:' + (port || 8000))
      : '';
  };

  // ── Status bar helper ─────────────────────────────────────────────────────

  EditorUtils.setStatus = function (msg, elementId) {
    const el = document.getElementById(elementId || 'status');
    if (el) el.textContent = msg;
  };

  global.EditorUtils = EditorUtils;
})(window);
