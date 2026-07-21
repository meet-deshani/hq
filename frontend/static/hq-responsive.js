/* ═══════════════════════════════════════════════════════════════════════
   ZEROONE HQ — RESPONSIVE / MOBILE LAYER (behaviour)
   Pairs with hq-responsive.css.

   The HQ shell is hydrated by a proprietary runtime that OWNS and re-creates
   the DOM inside <x-dc>, so anything we inject there — or any class we set on
   its nodes — can be wiped on the next re-render. To stay robust we keep ALL
   of our own state and chrome on nodes the runtime never touches:
     • open/closed state  → a class on <html>;
     • hamburger + backdrop → elements appended to <body>, outside <x-dc>.
   The CSS targets the shell structurally (the app's only <aside> and its
   sibling column), so no per-node tagging is required.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var MOBILE = 768;
  var root = document.documentElement;

  function openNav()  { root.classList.add('hq-nav-open'); }
  function closeNav() { root.classList.remove('hq-nav-open'); }
  function toggleNav() { root.classList.toggle('hq-nav-open'); }

  function svgBurger() {
    return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"></line>' +
      '<line x1="3" y1="12" x2="21" y2="12"></line>' +
      '<line x1="3" y1="18" x2="21" y2="18"></line></svg>';
  }

  /* Create the burger + backdrop once, on <body>, and keep them there. */
  function ensureChrome() {
    var body = document.body;
    if (!body) return;

    if (!document.getElementById('hq-burger')) {
      var b = document.createElement('button');
      b.id = 'hq-burger';
      b.type = 'button';
      b.className = 'hq-burger';
      b.setAttribute('aria-label', 'Open navigation');
      b.innerHTML = svgBurger();
      b.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        toggleNav();
      });
      body.appendChild(b);
    }

    if (!document.getElementById('hq-backdrop')) {
      var d = document.createElement('div');
      d.id = 'hq-backdrop';
      d.className = 'hq-backdrop';
      d.addEventListener('click', closeNav);
      body.appendChild(d);
    }
  }

  /* Close the drawer after the user picks a destination from the sidebar's
     module/tab nav. Workspace-switcher taps are intentionally excluded so a
     user can switch workspace, then pick a module, without it snapping shut.
     Structural (no classes): target = inside <aside> AND inside its <nav>. */
  document.addEventListener('click', function (e) {
    if (window.innerWidth > MOBILE) return;
    if (!root.classList.contains('hq-nav-open')) return;
    var t = e.target;
    if (!t || !t.closest) return;
    if (t.closest('#hq-burger')) return;
    var aside = t.closest('aside');
    if (aside && t.closest('nav') && t.closest('button, a, [role="button"]')) {
      setTimeout(closeNav, 160);
    }
  }, true);

  /* Escape closes; leaving mobile width resets the state. */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeNav();
  });
  window.addEventListener('resize', function () {
    if (window.innerWidth > MOBILE) closeNav();
  });

  /* Keep the chrome alive if anything ever detaches it, and re-assert it as
     the runtime finishes hydrating. Cheap + idempotent. */
  function boot() {
    ensureChrome();
    try {
      new MutationObserver(function () { ensureChrome(); })
        .observe(document.body, { childList: true });
    } catch (_) { /* no-op */ }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
