/**
 * nav.js — injection d'une barre de navigation commune sur /data/*.html
 * Inclure avec : <script src="/data/shared/nav.js"></script>
 */
(function () {
  'use strict';

  function normPath(p) {
    try { return String(p || '').split('?')[0].split('#')[0]; } catch (_) { return String(p || ''); }
  }

  function isCurrentPath(itemPath, currentPath) {
    const a = normPath(itemPath);
    const c = normPath(currentPath);
    if (!a || !c) return false;
    return c === a || c.endsWith(a);
  }

  function buildNav() {
    const items = [
      { href: '/data/admin.html',          label: 'Admin' },
      { href: '/data/taxonomy_editor.html', label: 'Taxonomie' },
      { href: '/data/sites_editor.html',   label: 'Sites' },
      { href: '/data/images_editor.html',  label: 'Images' },
      { href: '/data/jobs_editor.html',    label: 'Jobs' },
      { href: '/docs',                     label: 'Docs API', external: true },
    ];

    const current = normPath(window.location.pathname);

    const nav = document.createElement('nav');
    nav.className = 'ac-topnav';
    nav.setAttribute('aria-label', 'Navigation principale');

    const brand = document.createElement('a');
    brand.className = 'ac-topnav__brand';
    brand.href = '/data/admin.html';
    brand.textContent = 'Artiste Coloriage';

    const links = document.createElement('div');
    links.className = 'ac-topnav__links';

    items.forEach(function (it) {
      const a = document.createElement('a');
      a.className = 'ac-topnav__link';
      a.href = it.href;
      a.textContent = it.label;
      if (it.external) {
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
      }
      if (isCurrentPath(it.href, current)) {
        a.setAttribute('aria-current', 'page');
      }
      links.appendChild(a);
    });

    const right = document.createElement('div');
    right.className = 'ac-topnav__right';
    // Zone extensible: on évite d'ajouter du thème ici pour ne pas dupliquer la logique existante.

    nav.appendChild(brand);
    nav.appendChild(links);
    nav.appendChild(right);

    return nav;
  }

  function mount() {
    if (!document || !document.body) return;
    if (document.body.getAttribute('data-ac-nav-mounted') === '1') return;
    if (document.body.getAttribute('data-ac-nav') === 'off') return;

    const nav = buildNav();
    document.body.insertBefore(nav, document.body.firstChild);
    document.body.setAttribute('data-ac-nav-mounted', '1');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();

