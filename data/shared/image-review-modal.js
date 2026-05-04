/**
 * Modale « Revue image » pour jobs image_generation (QC + apply/reject).
 * Usage : var m = window.mountImageReviewModal(apiBase, { onAfterAction: fn });
 *         m.open(jobId);
 */
(function (global) {
  'use strict';

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function injectStylesOnce() {
    if (document.getElementById('image-review-modal-styles')) return;
    var st = document.createElement('style');
    st.id = 'image-review-modal-styles';
    st.textContent = [
      '.irm-overlay{display:none;position:fixed;inset:0;z-index:1200;background:rgba(0,0,0,.5);align-items:center;justify-content:center;padding:1rem;}',
      '.irm-overlay.open{display:flex;}',
      '.irm-dialog{background:#fff;border-radius:12px;max-width:960px;width:100%;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.2);}',
      'body[data-theme="dark"] .irm-dialog{background:#1e293b;color:#f1f5f9;}',
      '.irm-head{padding:1rem 1.25rem;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;gap:0.75rem;flex-wrap:wrap;}',
      'body[data-theme="dark"] .irm-head{border-color:#334155;}',
      '.irm-head h3{margin:0;font-size:1.05rem;}',
      '.irm-body{overflow:auto;padding:1rem 1.25rem;flex:1;}',
      '.irm-grid{display:grid;grid-template-columns:minmax(200px,1fr) minmax(280px,1.2fr);gap:1.25rem;}',
      '@media(max-width:720px){.irm-grid{grid-template-columns:1fr;}}',
      '.irm-preview img{max-width:100%;max-height:320px;border-radius:8px;border:1px solid #e2e8f0;display:block;margin:0 auto;}',
      'body[data-theme="dark"] .irm-preview img{border-color:#334155;}',
      '.irm-meta{font-size:0.78rem;color:#64748b;margin-top:0.5rem;}',
      'body[data-theme="dark"] .irm-meta{color:#94a3b8;}',
      '.irm-qc-badge{display:inline-block;padding:0.2rem 0.55rem;border-radius:8px;font-size:0.78rem;font-weight:700;margin-bottom:0.5rem;}',
      '.irm-qc-pass{background:#dcfce7;color:#166534;}',
      '.irm-qc-warning{background:#fef9c3;color:#a16207;}',
      '.irm-qc-fail{background:#fee2e2;color:#b91c1c;}',
      '.irm-qc-scores{font-size:0.85rem;margin:0.35rem 0 0.75rem;}',
      '.irm-check{font-size:0.8rem;padding:0.35rem 0;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;gap:0.5rem;flex-wrap:wrap;}',
      'body[data-theme="dark"] .irm-check{border-color:#334155;}',
      '.irm-sev-pass{color:#15803d;}',
      '.irm-sev-warn{color:#ca8a04;}',
      '.irm-sev-fail{color:#b91c1c;}',
      '.irm-flags,.irm-reco{font-size:0.78rem;margin:0.5rem 0 0;padding-left:1.1rem;}',
      '.irm-section{margin-top:1rem;padding-top:0.75rem;border-top:1px solid #e2e8f0;}',
      'body[data-theme="dark"] .irm-section{border-color:#334155;}',
      '.irm-section summary{cursor:pointer;font-weight:600;font-size:0.88rem;}',
      '.irm-prompt{font-size:0.8rem;white-space:pre-wrap;max-height:140px;overflow:auto;background:#f8fafc;padding:0.5rem;border-radius:6px;margin-top:0.35rem;}',
      'body[data-theme="dark"] .irm-prompt{background:#0f172a;}',
      '.irm-plan{font-size:0.8rem;}',
      '.irm-plan li{margin:0.25rem 0;}',
      '.irm-banner{padding:0.6rem 0.85rem;border-radius:8px;font-size:0.82rem;margin-bottom:0.75rem;background:#fef2f2;color:#991b1b;border:1px solid #fecaca;}',
      'body[data-theme="dark"] .irm-banner{background:#450a0a;color:#fecaca;border-color:#7f1d1d;}',
      '.irm-foot{padding:0.85rem 1.25rem;border-top:1px solid #e2e8f0;display:flex;flex-wrap:wrap;gap:0.5rem;justify-content:flex-end;align-items:center;}',
      'body[data-theme="dark"] .irm-foot{border-color:#334155;}',
      '.irm-btn{padding:0.5rem 1rem;border-radius:6px;border:none;cursor:pointer;font-size:0.88rem;}',
      '.irm-btn-apply{background:#15803d;color:#fff;}',
      '.irm-btn-reject{background:#b91c1c;color:#fff;}',
      '.irm-btn-close{background:#e2e8f0;color:#202124;}',
      'body[data-theme="dark"] .irm-btn-close{background:#4a5568;color:#f7fafc;}',
      '.irm-loading,.irm-err{padding:1rem;text-align:center;color:#64748b;}',
    ].join('');
    document.head.appendChild(st);
  }

  function qcBadgeClass(status) {
    var s = (status || '').toLowerCase();
    if (s === 'pass') return 'irm-qc-pass';
    if (s === 'warning') return 'irm-qc-warning';
    return 'irm-qc-fail';
  }

  function sevClass(sev) {
    var s = (sev || '').toLowerCase();
    if (s === 'warn') return 'irm-sev-warn';
    if (s === 'fail') return 'irm-sev-fail';
    return 'irm-sev-pass';
  }

  function renderChecks(checks) {
    if (!checks || !checks.length) return '<p class="irm-meta">Aucun détail de check.</p>';
    return checks
      .map(function (c) {
        var id = esc(c.id || '');
        var det = esc(c.detail || '');
        var sev = esc(c.severity || (c.pass ? 'pass' : 'fail'));
        return (
          '<div class="irm-check"><span><code>' +
          id +
          '</code> — ' +
          det +
          '</span><span class="' +
          sevClass(c.severity) +
          '">' +
          sev +
          '</span></div>'
        );
      })
      .join('');
  }

  function renderPlan(items) {
    if (!items || !items.length) return '<p class="irm-meta">—</p>';
    var html = '<ul class="irm-plan" style="margin:0;padding-left:1.2rem;">';
    items.forEach(function (it) {
      if (it.field) {
        html +=
          '<li><code>' +
          esc(it.entity || '') +
          '.' +
          esc(it.field) +
          '</code> : <code>' +
          esc(it.from) +
          '</code> → <code>' +
          esc(it.to) +
          '</code>' +
          (it.note ? ' <span class="irm-meta">(' + esc(it.note) + ')</span>' : '') +
          '</li>';
      } else {
        html += '<li><strong>' + esc(it.action || '') + '</strong> — ' + esc(it.detail || '') + '</li>';
      }
    });
    html += '</ul>';
    return html;
  }

  function resolveBase(apiBase, options) {
    if (options && typeof options.getApiBase === 'function') {
      try {
        return options.getApiBase() || '';
      } catch (_) {
        return '';
      }
    }
    return apiBase || '';
  }

  /**
   * Origine HTTP(S) pour les appels API (évite fetch relatif incorrect hors même origine).
   */
  function resolveRequestOrigin(apiBase, options) {
    var b = resolveBase(apiBase, options);
    if (b) return b.replace(/\/$/, '');
    if (typeof window !== 'undefined' && window.location) {
      if (window.location.protocol === 'file:') {
        var p = window.ARTISTE_API_PORT || 8000;
        return 'http://127.0.0.1:' + p;
      }
      return window.location.origin;
    }
    return '';
  }

  function jobEndpointUrl(apiBase, options, jobId, suffix) {
    var path = '/api/jobs/' + encodeURIComponent(jobId) + suffix;
    var origin = resolveRequestOrigin(apiBase, options);
    try {
      return new URL(path, origin + '/').href;
    } catch (_) {
      return origin + path;
    }
  }

  function mountImageReviewModal(apiBase, options) {
    options = options || {};
    var onAfterAction = typeof options.onAfterAction === 'function' ? options.onAfterAction : function () {};
    var root = options.root || document.body;

    injectStylesOnce();

    var overlay = document.createElement('div');
    overlay.className = 'irm-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML =
      '<div class="irm-dialog">' +
      '<div class="irm-head"><h3 id="irm-title">Revue image</h3><span id="irm-sub" class="irm-meta"></span></div>' +
      '<div class="irm-body" id="irm-body"><div class="irm-loading">Chargement…</div></div>' +
      '<div class="irm-foot">' +
      '<button type="button" class="irm-btn irm-btn-apply" id="irm-apply">Appliquer et marquer generated</button>' +
      '<button type="button" class="irm-btn irm-btn-reject" id="irm-reject">Rejeter (supprimer output)</button>' +
      '<button type="button" class="irm-btn irm-btn-close" id="irm-close">Fermer</button>' +
      '</div>' +
      '</div>';

    root.appendChild(overlay);

    var bodyEl = overlay.querySelector('#irm-body');
    var titleEl = overlay.querySelector('#irm-title');
    var subEl = overlay.querySelector('#irm-sub');
    var currentJobId = null;

    function close() {
      overlay.classList.remove('open');
      currentJobId = null;
    }

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) close();
    });

    overlay.querySelector('#irm-close').addEventListener('click', close);

    overlay.querySelector('#irm-apply').addEventListener('click', async function () {
      if (!currentJobId) return;
      try {
        var r = await fetch(jobEndpointUrl(apiBase, options, currentJobId, '/validate'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'apply' }),
        });
        if (!r.ok) {
          var t = await r.text();
          alert('Erreur apply: ' + r.status + ' ' + t);
          return;
        }
        close();
        onAfterAction();
      } catch (err) {
        alert('Erreur: ' + err.message);
      }
    });

    overlay.querySelector('#irm-reject').addEventListener('click', async function () {
      if (!currentJobId) return;
      if (!confirm('Rejeter cette génération ? Le fichier output sera supprimé et l’image repassera en prompt_ready.')) return;
      try {
        var r = await fetch(jobEndpointUrl(apiBase, options, currentJobId, '/validate'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'reject' }),
        });
        if (!r.ok) {
          var t = await r.text();
          alert('Erreur reject: ' + r.status + ' ' + t);
          return;
        }
        close();
        onAfterAction();
      } catch (err) {
        alert('Erreur: ' + err.message);
      }
    });

    async function open(jobId) {
      currentJobId = jobId;
      titleEl.textContent = 'Revue image — ' + jobId;
      subEl.textContent = '';
      bodyEl.innerHTML = '<div class="irm-loading">Chargement…</div>';
      overlay.classList.add('open');

      try {
        var reviewUrl = jobEndpointUrl(apiBase, options, jobId, '/review');
        var res = await fetch(reviewUrl);
        if (!res.ok) {
          bodyEl.innerHTML =
            '<div class="irm-err">Erreur ' + esc(res.status) + ' : ' + esc(await res.text()) + '</div>';
          return;
        }
        var data = await res.json();

        if (data.legacy) {
          subEl.textContent = data.legacy_note || 'Résultat legacy';
        } else {
          subEl.textContent = '';
        }

        var qc = data.qc || {};
        var qcStatus = qc.status || 'unknown';
        var banner =
          qcStatus === 'fail'
            ? '<div class="irm-banner">QC technique : échec détecté. Vous pouvez quand même appliquer si vous validez manuellement le rendu.</div>'
            : qcStatus === 'warning'
              ? '<div class="irm-banner" style="background:#fffbeb;color:#92400e;border-color:#fde68a;">QC : avertissements — vérifiez le rendu avant d’appliquer.</div>'
            : '';

        var relImg =
          (data.preview && data.preview.image_url) || '/api/jobs/' + encodeURIComponent(jobId) + '/output-image';
        var imgUrl;
        if (relImg.indexOf('http') === 0) {
          imgUrl = relImg;
        } else if (relImg.charAt(0) === '/') {
          try {
            imgUrl = new URL(relImg, resolveRequestOrigin(apiBase, options) + '/').href;
          } catch (_) {
            imgUrl = resolveRequestOrigin(apiBase, options) + relImg;
          }
        } else {
          imgUrl = resolveRequestOrigin(apiBase, options) + '/' + relImg;
        }

        var resMeta = data.resources || {};
        var gen = resMeta.generation_params || {};
        var metaLines = [];
        if (gen.width || gen.height) metaLines.push('Dimensions : ' + (gen.width || '?') + ' × ' + (gen.height || '?'));
        if (gen.workflow_template) metaLines.push('Workflow : ' + gen.workflow_template);
        if (gen.seed != null) metaLines.push('Seed : ' + gen.seed);
        if (data.preview && data.preview.rel_path) metaLines.push('Fichier : ' + data.preview.rel_path);

        var reviewSummary = data.review_summary ? '<p class="irm-meta">' + esc(data.review_summary) + '</p>' : '';

        bodyEl.innerHTML =
          banner +
          '<div class="irm-grid">' +
          '<div class="irm-preview">' +
          '<img src="' +
          esc(imgUrl) +
          '" alt="Aperçu génération">' +
          '<div class="irm-meta">' +
          metaLines.map(function (l) {
            return '<div>' + esc(l) + '</div>';
          }).join('') +
          '</div>' +
          '</div>' +
          '<div>' +
          '<div><span class="irm-qc-badge ' +
          qcBadgeClass(qcStatus) +
          '">QC : ' +
          esc(qcStatus) +
          '</span></div>' +
          '<div class="irm-qc-scores">Score technique : <strong>' +
          esc(qc.technical_score != null ? qc.technical_score : '—') +
          '</strong> · Global : <strong>' +
          esc(qc.overall_score != null ? qc.overall_score : '—') +
          '</strong></div>' +
          renderChecks(qc.checks || []) +
          (qc.flags && qc.flags.length
            ? '<div class="irm-flags"><strong>Flags</strong> : ' +
              qc.flags.map(function (f) {
                return '<code>' + esc(f) + '</code>';
              }).join(', ') +
              '</div>'
            : '') +
          (qc.recommendations && qc.recommendations.length
            ? '<ul class="irm-reco">' +
              qc.recommendations.map(function (r) {
                return '<li>' + esc(r) + '</li>';
              }).join('') +
              '</ul>'
            : '') +
          '<div class="irm-section">' +
          '<details><summary>Prompt utilisé</summary>' +
          '<div class="irm-prompt">' +
          esc((data.preview && data.preview.prompt) || '') +
          '</div>' +
          '<div class="irm-meta" style="margin-top:0.5rem;">Négatif</div>' +
          '<div class="irm-prompt">' +
          esc((data.preview && data.preview.negative_prompt) || '') +
          '</div></details></div>' +
          '<div class="irm-section">' +
          '<details open><summary>Effet de « Appliquer »</summary>' +
          '<p class="irm-meta" title="Les champs title, prompt et negative_prompt de l’image ne sont pas modifiés.">Aucun champ texte (titre / prompts) ne sera modifié.</p>' +
          renderPlan(data.apply_plan_summary || []) +
          reviewSummary +
          '</details></div>' +
          '<div class="irm-section">' +
          '<details><summary>Effet de « Rejeter »</summary>' +
          renderPlan(data.reject_plan_summary || []) +
          '</details></div>' +
          '</div></div>';
      } catch (e) {
        bodyEl.innerHTML = '<div class="irm-err">' + esc(e.message) + '</div>';
      }
    }

    return { open: open, close: close, destroy: function () { overlay.remove(); } };
  }

  global.mountImageReviewModal = mountImageReviewModal;
})(typeof window !== 'undefined' ? window : globalThis);
