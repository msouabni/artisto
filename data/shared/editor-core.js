/**
 * editor-core.js — Classe générique EditorCore pour les éditeurs CRUD plats.
 *
 * Usage :
 *   const editor = new EditorCore({
 *     title:      'Sites',
 *     apiBase:    EditorUtils.apiBase(8000),  // ou '' si servi
 *     apiPrefix:  '/api/sites',
 *     pk:         'id',
 *     columns:    [...],   // définitions Tabulator (sans la colonne Actions)
 *     formFields: [...],   // [{field, label, type?, required?, options?}]
 *     storagePrefix: 'sites_editor',
 *   });
 *   editor.init();
 *
 * Dépendances : Tabulator >= 6.x, EditorUtils (utils.js), editor-core.css
 */
(function (global) {
  'use strict';

  // ── Constantes ─────────────────────────────────────────────────────────────

  const ICON_EDIT = '<svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>';
  const ICON_DELETE = '<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';
  const ICON_DUPLICATE = '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';

  // ── EditorCore ──────────────────────────────────────────────────────────────

  function EditorCore(config) {
    this.cfg = Object.assign({
      title: 'Éditeur',
      apiBase: '',
      apiPrefix: '/api/items',
      pk: 'id',
      columns: [],
      formFields: [],
      storagePrefix: 'editor',
      undoMax: 50,
      debouncePut: 400,
    }, config);

    this.table = null;
    this._editingId = null;
    this._undoStack = [];
    this._redoStack = [];
    this._modifiedIds = new Set();
    this._autosaveEnabled = false;
    this._debounceTimers = {};
  }

  // ── init ────────────────────────────────────────────────────────────────────

  EditorCore.prototype.init = function () {
    this._initTheme();
    this._initTable();
    this._initFormPanel();
    this._initToolbar();
    this._initConfirmDeleteModal();
    this._updateUndoRedoButtons();
    this.reload();
  };

  // ── Theme ───────────────────────────────────────────────────────────────────

  EditorCore.prototype._initTheme = function () {
    const self = this;
    const key = this.cfg.storagePrefix + '_theme';
    EditorUtils.applyTheme(EditorUtils.loadTheme(key), key);
    const btnLight = document.getElementById('btn-theme-light');
    const btnDark  = document.getElementById('btn-theme-dark');
    if (btnLight) btnLight.addEventListener('click', function () { EditorUtils.applyTheme('light', key); });
    if (btnDark)  btnDark.addEventListener('click',  function () { EditorUtils.applyTheme('dark',  key); });
  };

  // ── Table ───────────────────────────────────────────────────────────────────

  EditorCore.prototype._buildColumns = function () {
    const self = this;
    const selectionCol = document.getElementById('selection-bar')
      ? { formatter: 'rowSelection', titleFormatter: 'rowSelection', width: 40, hozAlign: 'center', headerSort: false, frozen: true }
      : null;
    const actionsCol = {
      title: 'Actions',
      field: '__actions',
      width: 100,
      formatter: function (cell) {
        const id = cell.getRow().getData()[self.cfg.pk];
        const wrap = document.createElement('div');
        wrap.className = 'action-btns';

        const editBtn = _makeIconBtn(ICON_EDIT, 'edit', 'Modifier');
        editBtn.dataset.id = id;
        editBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          self.openForm(id);
        });

        const dupBtn = _makeIconBtn(ICON_DUPLICATE, 'duplicate', 'Dupliquer');
        dupBtn.dataset.id = id;
        dupBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          self._duplicateItem(id);
        });

        const delBtn = _makeIconBtn(ICON_DELETE, 'delete', 'Supprimer');
        delBtn.dataset.id = id;
        delBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          self._confirmDelete(id);
        });

        wrap.appendChild(editBtn);
        wrap.appendChild(dupBtn);
        wrap.appendChild(delBtn);
        return wrap;
      },
      headerSort: false,
      frozen: true,
    };

    const cols = this.cfg.columns.concat([actionsCol]);
    return selectionCol ? [selectionCol].concat(cols) : cols;
  };

  EditorCore.prototype._initTable = function () {
    const self = this;
    const hasSelectionBar = !!document.getElementById('selection-bar');
    this.table = new Tabulator('#table-container', {
      data: [],
      layout: 'fitData',
      layoutColumnsOnNewData: true,
      editTriggerEvent: 'dblclick',
      height: '100%',
      columns: this._buildColumns(),
      rowSelection: hasSelectionBar,
      selectable: hasSelectionBar,
      selectableRangeMode: hasSelectionBar ? 'click' : undefined,
      rowSelectionChanged: function (data, rows) {
        self._updateSelectionBar(rows.length);
      },
    });
  };

  // ── Data API ────────────────────────────────────────────────────────────────

  EditorCore.prototype._url = function (id) {
    const base = this.cfg.apiBase + this.cfg.apiPrefix;
    return id != null ? base + '/' + encodeURIComponent(id) : base;
  };

  EditorCore.prototype.reload = async function () {
    try {
      const res = await fetch(this._url());
      if (!res.ok) throw new Error(await EditorUtils.parseApiError(res));
      const data = await res.json();
      const items = Array.isArray(data) ? data : (data.items || data.results || data.data || []);
      if (this.table) this.table.setData(items);
      this.setStatus('Chargé (' + items.length + ' enregistrement(s)).');
    } catch (err) {
      this.setStatus('Erreur chargement : ' + err.message);
    }
  };

  EditorCore.prototype._getItem = async function (id) {
    const res = await fetch(this._url(id));
    if (!res.ok) throw new Error(await EditorUtils.parseApiError(res));
    return res.json();
  };

  EditorCore.prototype._saveItem = async function (payload, isNew) {
    const id = payload[this.cfg.pk];
    const url = isNew ? this._url() : this._url(id);
    const method = isNew ? 'POST' : 'PUT';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await EditorUtils.parseApiError(res));
    return res.json();
  };

  EditorCore.prototype._deleteItem = async function (id) {
    let url = this._url(id);
    if (this.cfg.deleteForce) url += (url.includes('?') ? '&' : '?') + 'force=true';
    const res = await fetch(url, { method: 'DELETE' });
    if (!res.ok) throw new Error(await EditorUtils.parseApiError(res));
  };

  // ── Undo / Redo ─────────────────────────────────────────────────────────────

  EditorCore.prototype._pushUndo = function (op) {
    this._undoStack.push(op);
    if (this._undoStack.length > this.cfg.undoMax) this._undoStack.shift();
    this._redoStack.length = 0;
    this._updateUndoRedoButtons();
  };

  EditorCore.prototype._updateUndoRedoButtons = function () {
    const btnUndo = document.getElementById('btn-undo');
    const btnRedo = document.getElementById('btn-redo');
    if (btnUndo) btnUndo.disabled = this._undoStack.length === 0;
    if (btnRedo) btnRedo.disabled = this._redoStack.length === 0;
  };

  EditorCore.prototype.undo = async function () {
    const op = this._undoStack.pop();
    if (!op) return;
    try {
      if (op.type === 'save')   { await this._saveItem(op.before, false); this._redoStack.push(op); }
      if (op.type === 'create') { await this._deleteItem(op.payload[this.cfg.pk]); this._redoStack.push(op); }
      if (op.type === 'delete') { await this._saveItem(op.payload, true); this._redoStack.push(op); }
      await this.reload();
      this.setStatus('Annulé.');
    } catch (err) {
      this._undoStack.push(op);
      this.setStatus('Undo : ' + err.message);
    }
    this._updateUndoRedoButtons();
  };

  EditorCore.prototype.redo = async function () {
    const op = this._redoStack.pop();
    if (!op) return;
    try {
      if (op.type === 'save')   { await this._saveItem(op.after, false); this._undoStack.push(op); }
      if (op.type === 'create') { await this._saveItem(op.payload, true); this._undoStack.push(op); }
      if (op.type === 'delete') { await this._deleteItem(op.payload[this.cfg.pk]); this._undoStack.push(op); }
      await this.reload();
      this.setStatus('Refait.');
    } catch (err) {
      this._redoStack.push(op);
      this.setStatus('Redo : ' + err.message);
    }
    this._updateUndoRedoButtons();
  };

  // ── Form panel ──────────────────────────────────────────────────────────────

  EditorCore.prototype._initFormPanel = function () {
    const self = this;
    const panel = document.getElementById('form-panel');
    const form  = document.getElementById('editor-form');
    if (!panel || !form) return;

    const btnClose  = panel.querySelector('.form-panel-close');
    const btnCancel = document.getElementById('btn-form-cancel');
    const btnSave   = document.getElementById('btn-form-save');

    if (btnClose)  btnClose.addEventListener('click',  function () { self.closeForm(); });
    if (btnCancel) btnCancel.addEventListener('click', function () { self.closeForm(); });
    if (btnSave)   btnSave.addEventListener('click',   function () { self._submitForm(); });

    // Render form fields from config
    this._renderFormFields();
  };

  EditorCore.prototype._renderFormFields = function () {
    const self = this;
    const container = document.getElementById('editor-form-fields');
    if (!container) return;
    container.innerHTML = '';
    this.cfg.formFields.forEach(function (f) {
      if (f.type === 'taxonomy_term') {
        self._renderTaxonomyTermField(f, container);
        return;
      }
      const label = document.createElement('label');
      label.htmlFor = 'ef-' + f.field;
      if (f.readonly) label.classList.add('form-field-readonly-wrap');

      const span = document.createElement('span');
      span.className = 'form-field-label';
      span.textContent = f.label || f.field;
      label.appendChild(span);

      if (f.readonly) {
        const displaySpan = document.createElement('span');
        displaySpan.id = 'ef-' + f.field + '-display';
        displaySpan.className = 'form-field-readonly-value';
        displaySpan.textContent = '—';
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.id = 'ef-' + f.field;
        hidden.name = f.field;
        label.appendChild(displaySpan);
        label.appendChild(hidden);
      } else {
        let input;
        if (f.type === 'textarea') {
          input = document.createElement('textarea');
          input.rows = f.rows || 3;
        } else if (f.type === 'select' && f.options) {
          input = document.createElement('select');
          f.options.forEach(function (opt) {
            const o = document.createElement('option');
            o.value = typeof opt === 'object' ? opt.value : opt;
            o.textContent = typeof opt === 'object' ? opt.label : opt;
            input.appendChild(o);
          });
        } else {
          input = document.createElement('input');
          input.type = f.type || 'text';
        }
        input.id = 'ef-' + f.field;
        input.name = f.field;
        if (f.required) input.required = true;
        label.appendChild(input);
      }
      container.appendChild(label);
    });
  };

  EditorCore.prototype._renderTaxonomyTermField = function (f, container) {
    const self = this;
    const label = document.createElement('label');
    label.htmlFor = 'ef-' + f.field;

    const span = document.createElement('span');
    span.className = 'form-field-label';
    span.textContent = f.label || f.field;
    label.appendChild(span);

    const select = document.createElement('select');
    select.id = 'ef-' + f.field;
    select.name = f.field;
    select.className = 'taxonomy-term-select';
    select.dataset.relatedField = f.relatedField || '';
    select.dataset.taxonomyApiBase = (f.taxonomyApiBase || this.cfg.apiBase || '').replace(/\/$/, '');
    select.dataset.vocabularyId = f.vocabularyId || 'themes';
    const emptyOpt = document.createElement('option');
    emptyOpt.value = '';
    emptyOpt.textContent = '(Aucun terme)';
    select.appendChild(emptyOpt);

    const hiddenTax = document.createElement('input');
    hiddenTax.type = 'hidden';
    hiddenTax.id = 'ef-' + (f.relatedField || '');
    hiddenTax.name = f.relatedField || '';

    select.addEventListener('change', function () {
      const opt = select.options[select.selectedIndex];
      const taxId = opt && opt.dataset ? opt.dataset.taxonomyId : '';
      if (hiddenTax) hiddenTax.value = taxId || '';
    });

    label.appendChild(select);
    label.appendChild(hiddenTax);
    container.appendChild(label);
  };

  EditorCore.prototype._populateTaxonomyTermSelects = async function (initialData) {
    const self = this;
    const taxonomyFields = this.cfg.formFields.filter(function (f) { return f.type === 'taxonomy_term'; });
    if (!taxonomyFields.length) return;

    var apiBase = (this.cfg.apiBase || '').replace(/\/$/, '');
    if (!apiBase && typeof window !== 'undefined' && window.location) {
      apiBase = window.location.origin;
    }

    taxonomyFields.forEach(function (f) {
      const select = document.getElementById('ef-' + f.field);
      const hiddenTax = document.getElementById('ef-' + (f.relatedField || ''));
      if (!select || !hiddenTax) return;

      const vocabIdUse = f.vocabularyId || 'themes';
      const termVal = initialData && initialData[f.field] != null ? String(initialData[f.field]) : '';
      const taxVal = initialData && initialData[f.relatedField] != null ? String(initialData[f.relatedField]) : 'universal_v0';

      select.innerHTML = '';
      const emptyOpt = document.createElement('option');
      emptyOpt.value = '';
      emptyOpt.textContent = '(Chargement…)';
      select.appendChild(emptyOpt);
    });

    try {
      const vocabId = taxonomyFields[0].vocabularyId || 'themes';
      const termsUrl = apiBase + '/api/taxonomy/vocabularies/' + encodeURIComponent(vocabId) + '/terms';
      const res = await fetch(termsUrl);
      if (!res.ok) {
        console.warn('Taxonomy term selector: API', res.status, termsUrl);
        _setTaxonomySelectEmpty(taxonomyFields, '(Aucun terme — erreur API)');
        return;
      }
      const data = await res.json();
      const termsTree = data.terms || [];
      const taxonomyId = data.taxonomy_id || 'universal_v0';

      taxonomyFields.forEach(function (f) {
        const select = document.getElementById('ef-' + f.field);
        const hiddenTax = document.getElementById('ef-' + (f.relatedField || ''));
        if (!select || !hiddenTax) return;

        const vocabIdUse = f.vocabularyId || vocabId;
        const terms = (vocabIdUse === vocabId)
          ? self._flattenTerms(termsTree, 0)
          : self._flattenTerms([], 0);
        const termVal = initialData && initialData[f.field] != null ? String(initialData[f.field]) : '';
        const taxVal = initialData && initialData[f.relatedField] != null ? String(initialData[f.relatedField]) : taxonomyId;

        select.innerHTML = '';
        const emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = '(Aucun terme)';
        select.appendChild(emptyOpt);
        terms.forEach(function (t) {
          if (t.id == null || t.id === '') return;
          const o = document.createElement('option');
          o.value = t.id;
          o.textContent = (t.label || t.id || '').trim() || t.id;
          o.dataset.taxonomyId = taxonomyId;
          select.appendChild(o);
        });
        select.value = termVal || '';
        const opt = select.options[select.selectedIndex];
        hiddenTax.value = (opt && opt.dataset && opt.dataset.taxonomyId) || taxVal || taxonomyId;
      });
    } catch (err) {
      console.warn('Taxonomy term selector: failed to load terms', err);
      _setTaxonomySelectEmpty(taxonomyFields, '(Aucun terme — erreur)');
    }
  };

  function _setTaxonomySelectEmpty(taxonomyFields, emptyLabel) {
    taxonomyFields.forEach(function (f) {
      const select = document.getElementById('ef-' + f.field);
      if (!select) return;
      select.innerHTML = '';
      const o = document.createElement('option');
      o.value = '';
      o.textContent = emptyLabel;
      select.appendChild(o);
    });
  }

  var TREE_INDENT = '\u00A0\u00A0\u00A0\u00A0'; // 4 non-breaking spaces per level
  var TREE_BRANCH = '\u25B8\u00A0'; // "▸ " (triangle right)

  EditorCore.prototype._flattenTerms = function (terms, level) {
    const out = [];
    if (!Array.isArray(terms)) return out;
    level = level || 0;
    const prefix = level === 0 ? '' : Array(level + 1).join(TREE_INDENT) + TREE_BRANCH;
    terms.forEach(function (t) {
      const name = (t.name_fr || t.name_en || t.id || t.slug || '').trim();
      out.push({ id: t.id, label: prefix + name });
      if (t.children && t.children.length) {
        out.push.apply(out, this._flattenTerms(t.children, level + 1));
      }
    }.bind(this));
    return out;
  };

  EditorCore.prototype._populateForm = function (data) {
    this.cfg.formFields.forEach(function (f) {
      const el = document.getElementById('ef-' + f.field);
      if (!el) return;
      const val = data[f.field];
      el.value = (val == null ? '' : val);
      if (f.readonly) {
        const displayEl = document.getElementById('ef-' + f.field + '-display');
        if (displayEl) {
          let displayText = (val == null ? '' : String(val));
          if (f.type === 'select' && f.options && displayText) {
            const opt = f.options.find(function (o) {
              return (typeof o === 'object' ? o.value : o) === displayText;
            });
            displayText = opt && typeof opt === 'object' ? opt.label : displayText;
          }
          displayEl.textContent = displayText || '—';
        }
      }
      if (f.type === 'taxonomy_term' && f.relatedField) {
        const hiddenEl = document.getElementById('ef-' + f.relatedField);
        if (hiddenEl) hiddenEl.value = (data[f.relatedField] == null ? '' : data[f.relatedField]);
      }
    });
  };

  EditorCore.prototype._collectForm = function () {
    const result = {};
    this.cfg.formFields.forEach(function (f) {
      const el = document.getElementById('ef-' + f.field);
      if (!el) return;
      result[f.field] = f.type === 'number' ? (parseFloat(el.value) || 0)
                      : f.type === 'checkbox' ? el.checked
                      : el.value;
      if (f.type === 'taxonomy_term' && f.relatedField) {
        const relEl = document.getElementById('ef-' + f.relatedField);
        result[f.relatedField] = relEl ? relEl.value : '';
      }
    });
    return result;
  };

  EditorCore.prototype.openForm = async function (id) {
    this._editingId = id || null;
    const panel = document.getElementById('form-panel');
    const header = panel && panel.querySelector('.form-panel-header h2');
    if (panel) { panel.classList.add('open'); panel.setAttribute('aria-hidden', 'false'); }
    if (id) {
      try {
        const item = await this._getItem(id);
        await this._populateTaxonomyTermSelects();
        this._populateForm(item);
        if (header) header.textContent = 'Modifier';
      } catch (err) {
        this.setStatus('Erreur chargement : ' + err.message);
        if (panel) { panel.classList.remove('open'); panel.setAttribute('aria-hidden', 'true'); }
        return;
      }
    } else {
      await this._populateTaxonomyTermSelects({});
      this._populateForm({});
      if (header) header.textContent = 'Nouveau';
    }
  };

  EditorCore.prototype.openFormNew = function () {
    this.openForm(null);
  };

  EditorCore.prototype.closeForm = function () {
    this._editingId = null;
    const panel = document.getElementById('form-panel');
    if (panel) { panel.classList.remove('open'); panel.setAttribute('aria-hidden', 'true'); }
  };

  EditorCore.prototype._submitForm = async function () {
    const payload = this._collectForm();
    const isNew = this._editingId == null;
    try {
      let before = null;
      if (!isNew) {
        try { before = await this._getItem(this._editingId); } catch (_) {}
      }
      await this._saveItem(payload, isNew);
      this._pushUndo(isNew
        ? { type: 'create', payload }
        : { type: 'save', before, after: payload });
      await this.reload();
      this.closeForm();
      this.setStatus(isNew ? 'Créé.' : 'Enregistré.');
    } catch (err) {
      this.setStatus('Erreur : ' + err.message);
    }
  };

  // ── Delete ──────────────────────────────────────────────────────────────────

  EditorCore.prototype._initConfirmDeleteModal = function () {
    const self = this;
    const btnConfirm = document.getElementById('btn-confirm-delete-ok');
    const btnCancel  = document.getElementById('btn-confirm-delete-cancel');
    if (btnConfirm) btnConfirm.addEventListener('click', function () { self._doDelete(); });
    if (btnCancel)  btnCancel.addEventListener('click',  function () { self._closeDeleteModal(); });
    const modal = document.getElementById('modal-confirm-delete');
    if (modal) modal.addEventListener('click', function (e) {
      if (e.target === modal) self._closeDeleteModal();
    });
  };

  EditorCore.prototype._confirmDelete = function (id) {
    this._pendingDeleteId = id;
    const modal = document.getElementById('modal-confirm-delete');
    const msg   = document.getElementById('modal-confirm-delete-message');
    if (msg) msg.textContent = 'Supprimer l\'enregistrement « ' + id + ' » ? Cette action est irréversible.';
    if (modal) modal.classList.add('open');
  };

  EditorCore.prototype._closeDeleteModal = function () {
    this._pendingDeleteId = null;
    const modal = document.getElementById('modal-confirm-delete');
    if (modal) modal.classList.remove('open');
  };

  EditorCore.prototype._doDelete = async function () {
    const id = this._pendingDeleteId;
    this._closeDeleteModal();
    if (id == null) return;
    try {
      let snapshot = null;
      try { snapshot = await this._getItem(id); } catch (_) {}
      await this._deleteItem(id);
      if (snapshot) this._pushUndo({ type: 'delete', payload: snapshot });
      await this.reload();
      this.setStatus('Supprimé.');
    } catch (err) {
      this.setStatus('Erreur suppression : ' + err.message);
    }
  };

  // ── Duplicate ───────────────────────────────────────────────────────────────

  EditorCore.prototype._duplicateItem = async function (id) {
    try {
      const item = await this._getItem(id);
      const newItem = Object.assign({}, item);
      delete newItem[this.cfg.pk];
      newItem[this.cfg.pk] = id + '_copy_' + Date.now();
      await this._saveItem(newItem, true);
      this._pushUndo({ type: 'create', payload: newItem });
      await this.reload();
      this.setStatus('Dupliqué.');
    } catch (err) {
      this.setStatus('Erreur duplication : ' + err.message);
    }
  };

  // ── Toolbar ─────────────────────────────────────────────────────────────────

  EditorCore.prototype._initToolbar = function () {
    const self = this;

    const btnAdd = document.getElementById('btn-add-row');
    if (btnAdd) btnAdd.addEventListener('click', function () { self.openFormNew(); });

    const btnUndo = document.getElementById('btn-undo');
    if (btnUndo) btnUndo.addEventListener('click', function () { self.undo(); });

    const btnRedo = document.getElementById('btn-redo');
    if (btnRedo) btnRedo.addEventListener('click', function () { self.redo(); });

    const btnExport = document.getElementById('btn-export-json');
    if (btnExport) btnExport.addEventListener('click', function () { self._exportJson(); });

    const filterInput = document.getElementById('filter-input');
    if (filterInput) {
      filterInput.addEventListener('input', EditorUtils.debounce(function () {
        self._applyFilter(filterInput.value);
      }, 250));
    }

    // Theme buttons
    const btnLight = document.getElementById('btn-theme-light');
    const btnDark  = document.getElementById('btn-theme-dark');
    const themeKey = this.cfg.storagePrefix + '_theme';
    if (btnLight) btnLight.addEventListener('click', function () { EditorUtils.applyTheme('light', themeKey); });
    if (btnDark)  btnDark.addEventListener('click',  function () { EditorUtils.applyTheme('dark',  themeKey); });
  };

  EditorCore.prototype._applyFilter = function (q) {
    if (!this.table) return;
    const val = (q || '').trim().toLowerCase();
    if (!val) { this.table.clearFilter(); return; }
    const fields = this.cfg.columns.map(function (c) { return c.field; });
    this.table.setFilter(function (data) {
      return fields.some(function (f) {
        return String(data[f] || '').toLowerCase().includes(val);
      });
    });
  };

  EditorCore.prototype._exportJson = function () {
    if (!this.table) return;
    const data = this.table.getData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = this.cfg.storagePrefix + '_export.json';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  };

  // ── Selection bar ───────────────────────────────────────────────────────────

  EditorCore.prototype._updateSelectionBar = function (count) {
    const bar = document.getElementById('selection-bar');
    const countEl = document.getElementById('sel-count');
    if (!bar) return;
    bar.classList.toggle('visible', count > 0);
    if (countEl) countEl.textContent = count + ' sélectionné(s)';
  };

  // ── Status ──────────────────────────────────────────────────────────────────

  EditorCore.prototype.setStatus = function (msg) {
    EditorUtils.setStatus(msg, 'status');
  };

  // ── Private helpers ─────────────────────────────────────────────────────────

  function _makeIconBtn(svg, extraClass, title) {
    const btn = document.createElement('button');
    btn.type = 'button';
    if (extraClass) btn.className = extraClass;
    if (title) btn.title = title;
    btn.innerHTML = svg;
    return btn;
  }

  // ── Export global ───────────────────────────────────────────────────────────

  global.EditorCore = EditorCore;
})(window);
