/* Blueprint shared helpers: number formatting, chemical search, forms. */
(function () {
  'use strict';
  var BP = (window.BP = window.BP || {});

  /* ------------------------------------------------------------ formatting */
  function finite(v) { return typeof v === 'number' && isFinite(v); }

  function fix(v, d) {
    var s = v.toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
    if (/^-0(\.0*)?$/.test(s)) return s.slice(1);
    return s.replace(/^-/, '\u2212');
  }

  // Plain number with sensible significant figures and thousands separators.
  BP.num = function (v, dp) {
    if (!finite(v)) return 'n/a';
    if (dp != null) return fix(v, dp);
    var a = Math.abs(v);
    if (a === 0) return '0';
    if (a >= 100) return fix(v, 0);
    if (a >= 10) return fix(v, 1);
    if (a >= 1) return fix(v, 2);
    if (a >= 0.01) return fix(v, 3);
    var e = v.toExponential(2).split('e');
    return e[0] + '\u00d710<sup>' + parseInt(e[1], 10) + '</sup>';
  };

  // USD with M or k (same rules as tools/build_site.py fmt_usd).
  BP.usd = function (v) {
    if (!finite(v)) return 'n/a';
    var s = v < 0 ? '\u2212' : '', a = Math.abs(v), x, d;
    if (a < 0.005) return '$0';
    if (a >= 1e6) { x = a / 1e6; d = x >= 100 ? 0 : x >= 10 ? 1 : 2; return s + '$' + fix(x, d) + 'M'; }
    if (a >= 1e3) { x = a / 1e3; d = x >= 100 ? 0 : x >= 10 ? 1 : 2; return s + '$' + fix(x, d) + 'k'; }
    d = a >= 100 ? 0 : a >= 10 ? 1 : 2;
    return s + '$' + fix(a, d);
  };

  BP.pct = function (v, dp) {
    if (!finite(v)) return 'n/a';
    return fix(v, dp == null ? (Math.abs(v) >= 10 ? 1 : 2) : dp) + '%';
  };

  BP.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  // Subscript the digits in formula like text: CO2 -> CO<sub>2</sub>
  BP.chem = function (s) {
    return BP.esc(s).replace(/([A-Za-z\)])(\d+)/g, '$1<sub>$2</sub>');
  };

  // Units: m3 -> m with superscript 3, everything else escaped
  BP.unit = function (s) {
    return BP.chem(s).replace(/\bm<sub>([23])<\/sub>/g, 'm<sup>$1</sup>')
      .replace(/\^(-?\d+)/g, function (m, e) { return '<sup>' + e.replace('-', '\u2212') + '</sup>'; })
      .replace(/<sub>(\d+)<\/sub>\^/g, '$1^');
  };
  BP.unitPlain = function (s) {
    return BP.esc(s).replace(/\bm([23])\b/g, 'm<sup>$1</sup>');
  };

  /* ------------------------------------------------------------ search */
  function norm(s) {
    return String(s || '').toLowerCase().replace(/[-_]/g, ' ').replace(/\s+/g, ' ').trim();
  }
  BP.norm = norm;

  function catalog() {
    if (BP._cat) return BP._cat;
    var el = document.getElementById('bp-catalog');
    BP._cat = el ? JSON.parse(el.textContent) : { processes: [], coming_soon: [] };
    return BP._cat;
  }
  BP.catalog = catalog;

  // Mirrors engine/registry.match(). Returns {kind: 'live'|'soon'|'unknown', id, label, name, query}
  BP.match = function (query) {
    var cat = catalog(), q = norm(query), i, j, p;
    var procs = cat.processes || [], soon = cat.coming_soon || [];
    if (!q) return { kind: 'empty', query: query };
    for (i = 0; i < procs.length; i++) {
      p = procs[i];
      if (q === norm(p.label) || (p.aliases || []).indexOf(q) >= 0) {
        return { kind: p.live ? 'live' : 'soon', id: p.id, label: p.label, name: p.label, query: query };
      }
    }
    if (soon.indexOf(q) >= 0) return { kind: 'soon', name: q, label: q, query: query };
    for (i = 0; i < procs.length; i++) {
      p = procs[i];
      var al = p.aliases || [];
      for (j = 0; j < al.length; j++) {
        if (al[j].length > 3 && q.indexOf(al[j]) >= 0) {
          return { kind: p.live ? 'live' : 'soon', id: p.id, label: p.label, name: p.label, query: query };
        }
      }
    }
    for (i = 0; i < soon.length; i++) {
      if (q === soon[i] || (q.length > 3 && soon[i].indexOf(q) >= 0)) {
        return { kind: 'soon', name: soon[i], label: soon[i], query: query };
      }
    }
    return { kind: 'unknown', query: query, name: String(query || '').trim() };
  };

  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  // Typeahead suggestions: live first, then in progress, then coming soon.
  BP.suggest = function (query) {
    var cat = catalog(), q = norm(query), out = [], seen = {};
    if (!q) return out;
    function add(item) { if (!seen[item.key] && out.length < 6) { seen[item.key] = 1; out.push(item); } }
    var procs = cat.processes || [];
    [true, false].forEach(function (liveFirst) {
      procs.forEach(function (p) {
        if (!!p.live !== liveFirst) return;
        var hit = norm(p.label).indexOf(q) === 0 ? 2 : 0;
        (p.aliases || []).forEach(function (a) {
          if (a.indexOf(q) === 0) hit = Math.max(hit, 2);
          else if (q.length > 2 && a.indexOf(q) >= 0) hit = Math.max(hit, 1);
        });
        if (hit) add({ key: 'p:' + p.id, label: p.label, kind: p.live ? 'live' : 'soon', id: p.id });
      });
    });
    (cat.coming_soon || []).forEach(function (n) {
      if (n.indexOf(q) === 0 || (q.length > 2 && n.indexOf(q) >= 0)) add({ key: 's:' + n, label: cap(n), kind: 'soon', name: n });
    });
    return out;
  };

  BP.root = function () {
    // relative prefix to the site root, from the stylesheet link
    var l = document.querySelector('link[rel="stylesheet"][href$="css/site.css"]');
    return l ? l.getAttribute('href').replace(/css\/site\.css$/, '') : '';
  };

  BP.routeFor = function (m) {
    var root = BP.root();
    if (m.kind === 'live') return root + 'design/' + m.id + '/';
    return root + 'request/?q=' + encodeURIComponent(m.kind === 'unknown' ? m.query.trim() : (m.label || m.name || m.query));
  };

  function initSearch(form) {
    var input = form.querySelector('input[name="q"]');
    var list = form.querySelector('.typeahead');
    var items = [], active = -1;

    function close() {
      list.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1;
      input.removeAttribute('aria-activedescendant');
    }
    function go(m) { window.location.href = BP.routeFor(m); }
    function render() {
      items = BP.suggest(input.value);
      if (!items.length) { list.innerHTML = ''; close(); return; }
      list.innerHTML = items.map(function (it, i) {
        var badge = it.kind === 'live' ? '<span class="pill pill-pass">Live</span>' : '<span class="pill">Coming soon</span>';
        return '<li role="option" id="' + list.id + '-' + i + '" aria-selected="' + (i === active) + '" data-i="' + i + '">' +
          '<span class="ta-name">' + BP.chem(it.label) + '</span>' + badge + '</li>';
      }).join('');
      list.hidden = false; input.setAttribute('aria-expanded', 'true');
    }
    function setActive(i) {
      active = i;
      Array.prototype.forEach.call(list.children, function (li, k) { li.setAttribute('aria-selected', String(k === i)); });
      if (i >= 0) input.setAttribute('aria-activedescendant', list.id + '-' + i);
    }
    function pick(it) {
      if (it.kind === 'live') go({ kind: 'live', id: it.id });
      else go({ kind: 'soon', label: it.name || it.label });
    }
    input.addEventListener('input', function () { active = -1; render(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' && items.length) { e.preventDefault(); if (list.hidden) render(); setActive((active + 1) % items.length); }
      else if (e.key === 'ArrowUp' && items.length) { e.preventDefault(); setActive(active <= 0 ? items.length - 1 : active - 1); }
      else if (e.key === 'Escape') { close(); }
      else if (e.key === 'Enter' && active >= 0 && !list.hidden) { e.preventDefault(); pick(items[active]); }
    });
    input.addEventListener('blur', function () { setTimeout(close, 150); });
    list.addEventListener('mousedown', function (e) {
      var li = e.target.closest('li'); if (!li) return;
      e.preventDefault(); pick(items[+li.getAttribute('data-i')]);
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var q = input.value.trim();
      if (!q) { input.focus(); return; }
      go(BP.match(q));
    });
  }

  /* ------------------------------------------------------------ forms */
  var ICON_OK = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.6"/><path d="m6.5 10.2 2.3 2.3 4.7-4.9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var ICON_BAD = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.6"/><path d="M10 6v5m0 3v.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

  function fieldErr(input, msg) {
    var err = input.closest('.field') && input.closest('.field').querySelector('.err');
    if (msg) { input.setAttribute('aria-invalid', 'true'); if (err) err.textContent = msg; }
    else { input.removeAttribute('aria-invalid'); if (err) err.textContent = ''; }
    return !msg;
  }

  function initForm(form) {
    var kind = form.getAttribute('data-bp-form');
    var status = form.querySelector('.form-status');
    var btn = form.querySelector('button[type="submit"]');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var honey = form.querySelector('[name="_honey"]');
      var email = form.querySelector('[name="email"]');
      var ok = fieldErr(email, /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim()) ? '' : 'Enter a valid email address.');
      var chem = form.querySelector('[name="chemical"]');
      if (chem) ok = fieldErr(chem, chem.value.trim() ? '' : 'Which chemical?') && ok;
      var capEl = form.querySelector('[name="capacity_tpd"]');
      if (capEl && capEl.value) ok = fieldErr(capEl, +capEl.value > 0 ? '' : 'Use a positive number, or leave blank.') && ok;
      if (!ok) { var bad = form.querySelector('[aria-invalid="true"]'); if (bad) bad.focus(); return; }
      if (honey && honey.value) { done(true); return; } // bots: pretend success, send nothing
      var body = { email: email.value.trim(), _template: 'table', _captcha: 'false', _honey: '', page: location.href };
      if (kind === 'request') {
        body.chemical = chem.value.trim();
        body.capacity_tpd = capEl ? capEl.value.trim() : '';
        var note = form.querySelector('[name="note"]');
        body.note = note ? note.value.trim() : '';
        body._subject = 'Blueprint request: ' + body.chemical;
      } else {
        body._subject = 'Blueprint waitlist';
      }
      btn.disabled = true;
      var label = btn.textContent;
      btn.textContent = 'Sending';
      status.className = 'form-status';
      fetch(BP.formEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body)
      }).then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) { done(j && (j.success === true || j.success === 'true'), j && j.message); })
        .catch(function () { done(false); })
        .then(function () { btn.disabled = false; btn.textContent = label; });
    });
    function done(success) {
      if (success) {
        form.classList.add('sent');
        status.className = 'form-status ok';
        status.innerHTML = ICON_OK + '<span>' + (kind === 'request'
          ? 'Request received. You will get an email when it is modelled.'
          : 'You are on the list. One email when new processes go live.') + '</span>';
      } else {
        status.className = 'form-status bad';
        status.innerHTML = ICON_BAD + '<span>That did not send. Check your connection and try again in a moment.</span>';
      }
    }
  }

  /* ------------------------------------------------------------ request page */
  function initRequest() {
    var state = document.getElementById('req-state');
    if (!state) return;
    var q = new URLSearchParams(location.search).get('q') || '';
    var chem = document.getElementById('rq-chem');
    var title = document.getElementById('req-title');
    var lede = document.getElementById('req-lede');
    if (!q.trim()) return;
    var m = BP.match(q);
    var shown = m.kind === 'unknown' ? q.trim() : (m.label || m.name);
    chem.value = cap(shown);
    var ICON_I = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.6"/><path d="M10 9v5m0-7.5v.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    var head, text;
    if (m.kind === 'live') {
      head = BP.esc(cap(shown)) + ' is live';
      text = 'Open the <a href="' + BP.routeFor(m) + '">' + BP.esc(m.label) + ' design</a>, or ask for a different route or capacity below.';
      title.textContent = 'Request a variation';
    } else if (m.kind === 'soon') {
      head = BP.esc(cap(shown)) + ' is on the list';
      text = 'It is recognised and planned but not modelled yet. Leave your email and it will be sent to you the day it goes live. Requests move it up the queue.';
      title.innerHTML = 'Request ' + BP.chem(cap(shown));
      lede.textContent = 'Coming soon. Add your request to bring it forward.';
    } else {
      head = BP.esc(cap(shown)) + ' has not been modelled yet';
      text = 'Blueprint does not recognise it yet. Send a request and it will be considered for a future model; a route or capacity helps.';
      title.innerHTML = 'Request ' + BP.chem(cap(shown));
    }
    state.innerHTML = '<span class="ico">' + ICON_I + '</span><div><h2>' + head + '</h2><p>' + text + '</p></div>';
    state.hidden = false;
  }

  /* ------------------------------------------------------------ boot */
  function initNav() {
    var btn = document.querySelector('.nav-toggle'), nav = document.getElementById('site-nav');
    if (!btn || !nav) return;
    function set(open) { nav.classList.toggle('open', open); btn.setAttribute('aria-expanded', open ? 'true' : 'false'); }
    btn.addEventListener('click', function (e) { e.stopPropagation(); set(!nav.classList.contains('open')); });
    document.addEventListener('click', function (e) { if (!nav.contains(e.target)) set(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') set(false); });
  }
  function initChips() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-bp-allchips]'), function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        var meta = a.closest('.search-meta'); if (meta) meta.classList.remove('is-collapsed');
      });
    });
  }

  function boot() {
    initNav(); initChips();
    Array.prototype.forEach.call(document.querySelectorAll('[data-bp-search]'), initSearch);
    Array.prototype.forEach.call(document.querySelectorAll('[data-bp-form]'), initForm);
    initRequest();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
