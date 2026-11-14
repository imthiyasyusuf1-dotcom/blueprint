/* Blueprint design page: renders a design JSON, region switch, in browser re-run, PDF. */
(function () {
  'use strict';
  var BP = window.BP;
  var cfg = JSON.parse(document.getElementById('bp-config').textContent);
  var ROOT = BP.root();
  var $ = function (s, el) { return (el || document).querySelector(s); };
  var esc = BP.esc, num = BP.num, usd = BP.usd, chem = BP.chem;

  var state = {
    region: cfg.default_region,
    data: null,
    custom: null,      // {capacity, params} when the shown design is a custom run
    defaultCache: {},
    pending: null,     // custom inputs from a shared link, not yet run
    unit: 'kg'         // stream table basis
  };

  var ICON = {
    ext: '<svg viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M4.5 2.5h-2v7h7v-2M7 2.5h2.5V5M9.5 2.5 5.5 6.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    pass: '<svg viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="m2.5 6.2 2.2 2.2 4.8-4.9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    fail: '<svg viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="m3 3 6 6M9 3 3 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    warn: '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 2.2 14.5 13.5h-13L8 2.2Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.5v3.2m0 2v.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    close: '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    minus: '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3.5 8h9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plus: '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3.5 8h9M8 3.5v9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    hand: '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 8h12M2 8l2.5-2.5M2 8l2.5 2.5M14 8l-2.5-2.5M14 8l-2.5 2.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };

  function finite(v) { return typeof v === 'number' && isFinite(v); }
  function arr(v) { return Array.isArray(v) ? v : []; }
  function obj(v) { return v && typeof v === 'object' && !Array.isArray(v) ? v : {}; }
  function link(url, text) {
    if (!url) return esc(text || '');
    return '<a class="src-link" href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(text || 'Source') + ICON.ext + '</a>';
  }
  function stat(label, value, unit, cls, note) {
    return '<div class="stat' + (cls ? ' ' + cls : '') + '"><span class="stat-label">' + label + '</span>' +
      '<span class="stat-value">' + value + (unit ? '<span class="u">' + unit + '</span>' : '') + '</span>' +
      (note ? '<span class="stat-note">' + note + '</span>' : '') + '</div>';
  }
  function subHead(title, aside) {
    return '<div class="sub-h"><h3>' + title + '</h3>' + (aside ? '<span class="small">' + aside + '</span>' : '') + '</div>';
  }
  function tableWrap(inner, cls) {
    if (/class="t stack/.test(inner)) {
      inner = inner.replace(/(<td[^>]*data-label="[^"]*"[^>]*>)([\s\S]*?)(<\/td>)/g, function (m, a, b, c) { return a + '<span class="v">' + b + '</span>' + c; });
    }
    return '<div class="table-scroll' + (cls ? ' ' + cls : '') + '" tabindex="0">' + inner + '</div>';
  }
  function unitLabel(u) { return u ? esc(u).replace(/(\d)/g, '$1').replace(/\bC\b/g, '\u00b0C') : ''; }
  function streamById(d, id) { return arr(d.streams).filter(function (s) { return s.id === id; })[0]; }
  function unitById(d, id) { return arr(d.units).filter(function (u) { return u.id === id; })[0]; }
  function compName(d, cid) {
    var h = arr(d.hazards).filter(function (x) { return x.id === cid; })[0];
    return h && h.name ? h.name : cid;
  }
  function endLabel(d, e) {
    if (e === 'IN') return 'Feed';
    if (e === 'OUT') return 'Leaves plant';
    if (e === 'mix') return 'Mixing point';
    if (!e) return 'n/a';
    var u = unitById(d, e);
    return u ? esc(u.id) + ' ' + esc(u.name) : esc(e);
  }

  /* ================================================================ sections */

  function secOverview(d) {
    var eco = obj(d.economics), cap = obj(d.capacity), carbon = obj(d.carbon), h = '';
    h += '<p class="route">' + esc(d.route) + '</p>';
    h += '<div class="stats stats-4" style="margin-top:var(--s5)">' +
      stat('Capacity', num(cap.t_per_day), 't/d', '', finite(cap.t_per_year) ? num(cap.t_per_year) + ' t/yr' : '') +
      stat('Fixed capital', usd(eco.fci), '', 'hl', obj(d.capex).cepci_year ? 'CEPCI ' + d.capex.cepci_year + ' basis' : '') +
      stat('Cost of manufacture', usd(eco.cost_per_tonne), '/t') +
      stat('Levelised cost', usd(eco.levelised_cost_per_tonne), '/t', '', 'Includes capital recovery') +
      stat('Revenue', usd(eco.revenue), '/yr') +
      stat('NPV', usd(eco.npv), '', '', finite(eco.rate) ? 'At ' + BP.pct(eco.rate * 100, 0) + ', ' + eco.life + ' years' : '') +
      stat('IRR', finite(eco.irr) ? BP.pct(eco.irr * 100, 1) : 'n/a') +
      stat('Carbon', num(carbon.total), 't CO<sub>2</sub>e/t') +
      '</div>';
    if (arr(d.kpis).length) {
      h += subHead('Key figures');
      h += '<div class="stats">' + arr(d.kpis).map(function (k) {
        return stat(chem(k.label), num(k.value), unitLabel(k.unit) ? chem(k.unit) : '');
      }).join('') + '</div>';
    }
    if (arr(d.conditions).length) {
      h += subHead('Operating conditions');
      h += '<dl class="kv">' + arr(d.conditions).map(function (c) {
        return '<div><dt>' + chem(c[0]) + '</dt><dd>' + tidy(c[1]) + '</dd></div>';
      }).join('') + '</dl>';
    }
    if (arr(d.reactions).length) {
      h += subHead('Reactions', 'Heat of reaction as written, 298 K');
      h += '<ul class="rx">' + arr(d.reactions).map(function (r) {
        return '<li><span class="eq">' + chem(r.eq).replace(/&lt;=&gt;/g, '\u21cc').replace(/-&gt;/g, '\u2192') + '</span>' +
          '<span class="rx-where">' + esc(r.where) + '</span>' +
          '<span class="rx-dh num">' + (finite(r.dH_kJ) ? num(r.dH_kJ, 1) + '<span class="u">kJ/mol</span>' : '') + '</span></li>';
      }).join('') + '</ul>';
    }
    var flows = [];
    arr(d.raw_materials).forEach(function (x) { flows.push(['Feed', x]); });
    arr(d.products).forEach(function (x) { flows.push(['Product', x]); });
    arr(d.byproducts).forEach(function (x) { flows.push(['By product', x]); });
    if (flows.length) {
      h += subHead(arr(d.raw_materials).length ? 'Feeds and products' : 'Products', 'Prices for ' + esc(d.region_label || state.region));
      h += tableWrap('<table class="t stack"><thead><tr><th>Item</th><th>Role</th><th class="r">kg/h</th><th class="r">Price, USD/t</th><th class="r">Per year</th><th>Price source</th></tr></thead><tbody>' +
        flows.map(function (f) {
          var x = f[1], s = obj(x.source);
          return '<tr><td data-label="Item"><strong>' + esc(compName(d, x.id)) + '</strong></td><td data-label="Role">' + f[0] + '</td>' +
            '<td class="r" data-label="kg/h">' + num(x.kg_h) + '</td><td class="r" data-label="Price, USD/t">' + num(x.usd_t) + '</td>' +
            '<td class="r" data-label="Per year">' + usd(x.annual_usd) + '</td>' +
            '<td data-label="Price source"><span>' + link(s.url, s.source) + (s.basis ? '<span class="sub">' + esc(s.basis) + '</span>' : '') + '</span></td></tr>';
        }).join('') + '</tbody></table>', 'has-stack');
    }
    return h;
  }

  // engine text uses plain ASCII; show proper degree and minus signs
  function tidy(t) {
    return chem(String(t == null ? '' : t)
      .replace(/(\d)\s?C\b/g, '$1\u00a0\u00b0C')
      .replace(/(^|[\s(,])-(?=\d)/g, '$1\u2212'));
  }

  function secBalance(d) {
    var b = obj(d.balance), h = '';
    var atoms = obj(b.atom_error_pct);
    h += '<div class="stats stats-4">' +
      stat('Mass in', num(b.mass_in_kg_h), 'kg/h') +
      stat('Mass out', num(b.mass_out_kg_h), 'kg/h') +
      stat('Closure', finite(b.closure_pct) ? BP.num(Math.abs(b.closure_pct) < 5e-4 ? 0 : b.closure_pct, 3) + '%' : 'n/a', '', 'hl') +
      stat('Worst atom error', (function () {
        var w = 0; Object.keys(atoms).forEach(function (k) { if (Math.abs(atoms[k]) > Math.abs(w)) w = atoms[k]; });
        return BP.num(Math.abs(w) < 5e-4 ? 0 : w, 3) + '%';
      })()) + '</div>';
    if (Object.keys(atoms).length) {
      h += '<div class="chips" style="margin-top:var(--s3)">' + Object.keys(atoms).map(function (k) {
        return '<span class="pill num">' + chem(k) + ' ' + BP.num(Math.abs(atoms[k]) < 5e-4 ? 0 : atoms[k], 3) + '%</span>';
      }).join('') + '</div>';
    }
    h += subHead('Stream table', '<span class="seg seg-sm" role="group" aria-label="Flow basis">' +
      ['kg', 'kmol', 'frac'].map(function (u) {
        return '<button type="button" data-basis="' + u + '" aria-pressed="' + (state.unit === u) + '">' +
          ({ kg: 'kg/h', kmol: 'kmol/h', frac: 'Mass %' })[u] + '</button>';
      }).join('') + '</span>');
    h += '<div id="stream-table">' + streamTable(d) + '</div>';

    var e = obj(d.energy);
    var es = [];
    if (finite(e.fuel_GJ_h)) es.push(stat('Fuel fired', num(e.fuel_GJ_h), 'GJ/h'));
    if (finite(e.gas_net_GJ_h)) es.push(stat('Natural gas fuel, net', num(e.gas_net_GJ_h), 'GJ/h'));
    if (finite(e.power_kW)) es.push(stat('Electric power', num(e.power_kW), 'kW'));
    if (finite(e.cooling_kW)) es.push(stat('Cooling duty', num(e.cooling_kW), 'kW'));
    if (finite(e.steam_export_kg_h) && e.steam_export_kg_h > 0) es.push(stat('Steam raised and used', num(e.steam_export_kg_h), 'kg/h'));
    if (es.length) { h += subHead('Energy'); h += '<div class="stats">' + es.join('') + '</div>'; }

    var ud = arr(d.units).filter(function (u) { return finite(u.duty_kW) || finite(u.power_kW); });
    if (ud.length) {
      h += subHead('Unit duties', 'Positive is heat in');
      h += tableWrap('<table class="t"><thead><tr><th class="sticky">Unit</th><th class="r">Duty, kW</th><th class="r">Power, kW</th></tr></thead><tbody>' +
        ud.map(function (u) {
          return '<tr><th class="sticky" scope="row">' + esc(u.id) + '<span class="sub">' + esc(u.name) + '</span></th><td class="r">' +
            (finite(u.duty_kW) ? num(u.duty_kW) : '<span class="muted">n/a</span>') + '</td><td class="r">' +
            (finite(u.power_kW) ? num(u.power_kW) : '<span class="muted">n/a</span>') + '</td></tr>';
        }).join('') + '</tbody></table>');
    }

    var ut = arr(d.utilities);
    if (ut.length) {
      var tot = ut.reduce(function (a, u) { return a + (finite(u.annual) ? u.annual : 0); }, 0);
      h += subHead('Utilities', esc(d.region_label || '') + ' prices');
      h += tableWrap('<table class="t stack"><thead><tr><th>Utility</th><th class="r">Use per hour</th><th class="r">Unit cost</th><th class="r">Per year</th></tr></thead><tbody>' +
        ut.map(function (u) {
          return '<tr><td data-label="Utility">' + esc(u.label) + '</td><td class="r" data-label="Use per hour">' + num(u.per_h) + ' ' + esc(u.unit) + '</td>' +
            '<td class="r" data-label="Unit cost">' + num(u.unit_cost) + ' ' + esc(u.cost_unit) + '</td><td class="r" data-label="Per year">' + usd(u.annual) + '</td></tr>';
        }).join('') + '</tbody><tfoot><tr><td>Total</td><td></td><td></td><td class="r">' + usd(tot) + '</td></tr></tfoot></table>', 'has-stack');
    }
    return h;
  }

  function streamTable(d) {
    var ss = arr(d.streams);
    if (!ss.length) return '<p class="muted">No streams in this design.</p>';
    var comps = [], seen = {};
    ss.forEach(function (s) {
      Object.keys(obj(s.components)).forEach(function (c) {
        if (!seen[c]) { seen[c] = 1; comps.push(c); }
      });
    });
    // order components by total flow
    var tot = {};
    comps.forEach(function (c) { tot[c] = ss.reduce(function (a, s) { var x = obj(s.components)[c]; return a + (x && finite(x.kg_h) ? x.kg_h : 0); }, 0); });
    comps.sort(function (a, b) { return tot[b] - tot[a]; });
    var basis = state.unit;
    var head = '<tr><th class="sticky">Stream</th>' + ss.map(function (s) {
      return '<th class="r" scope="col"><button type="button" data-stream="' + esc(s.id) + '" title="Show ' + esc(s.id) + ' in the flow diagram">' + esc(s.id) + '</button></th>';
    }).join('') + '</tr>';
    function row(label, fn, cls) {
      return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><th class="sticky" scope="row">' + label + '</th>' + ss.map(function (s) {
        var v = fn(s);
        return '<td class="r">' + (v == null ? '<span class="muted">n/a</span>' : v) + '</td>';
      }).join('') + '</tr>';
    }
    var body = '';
    body += row('Name', function (s) { return '<span style="white-space:normal;display:block;min-width:96px;text-align:right">' + esc(s.name) + '</span>'; });
    body += row('From', function (s) { return esc(s.from === 'IN' ? 'Feed' : s.from === 'mix' ? 'Mix' : s.from || 'n/a'); });
    body += row('To', function (s) { return esc(s.to === 'OUT' ? 'Out' : s.to || 'n/a'); });
    body += row('Phase', function (s) { return esc(({ g: 'Vapour', l: 'Liquid', s: 'Solid', vl: 'Two phase', lv: 'Two phase' })[s.phase] || s.phase || 'n/a'); });
    body += row('Temperature, \u00b0C', function (s) { return finite(s.T_C) ? num(s.T_C, 0) : null; });
    body += row('Pressure, bar', function (s) { return finite(s.P_bar) ? num(s.P_bar) : null; });
    body += row('Total, kg/h', function (s) { return finite(s.kg_h) ? num(s.kg_h, 0) : null; }, 'is-total');
    body += row('Total, kmol/h', function (s) { return finite(s.kmol_h) ? num(s.kmol_h) : null; });
    body += '<tr class="group"><th class="sticky" scope="rowgroup">' + ({ kg: 'Components, kg/h', kmol: 'Components, kmol/h', frac: 'Components, mass %' })[basis] + '</th>' +
      ss.map(function () { return '<th></th>'; }).join('') + '</tr>';
    comps.forEach(function (c) {
      body += row(chem(c), function (s) {
        var x = obj(s.components)[c];
        var v = !x ? 0 : basis === 'kg' ? x.kg_h : basis === 'kmol' ? x.kmol_h : (finite(x.mass_frac) ? x.mass_frac * 100 : 0);
        if (!finite(v) || Math.abs(v) < (basis === 'frac' ? 0.005 : 0.05)) return '<span class="blank">\u00b7</span>';
        return basis === 'frac' ? BP.num(v, 2) : num(v, basis === 'kg' ? 0 : (Math.abs(v) >= 100 ? 0 : 2));
      });
    });
    return tableWrap('<table class="t stream-table"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>');
  }

  function secKit(d) {
    var eq = arr(d.equipment);
    if (!eq.length) return '<p class="muted">No equipment list in this design.</p>';
    var tp = 0, tb = 0;
    var rows = eq.map(function (e) {
      tp += finite(e.purchased) ? e.purchased : 0;
      tb += finite(e.bare_module) ? e.bare_module : 0;
      var n = e.units_parallel || 1;
      var size = finite(e.size_each) ? num(e.size_each) : finite(e.size) ? num(e.size) : 'n/a';
      return '<tr><td data-label="Item"><span class="tag">' + esc(e.tag || '') + '</span><strong>' + esc(e.name || e.label) + '</strong>' + (e.service ? '<span class="sub">' + esc(e.service) + '</span>' : '') + '</td>' +
        '<td data-label="Type">' + esc(e.label || e.kind) + '</td>' +
        '<td class="r" data-label="Size' + (n > 1 ? ', each' : '') + '"><span>' + size + ' ' + BP.unit(e.unit || '') + (e.attribute ? '<span class="sub">' + esc(e.attribute) + '</span>' : '') + '</span></td>' +
        '<td class="r" data-label="Parallel units">' + n + '</td>' +
        '<td data-label="Material">' + esc(e.material || '') + '</td>' +
        '<td class="r" data-label="Pressure, barg">' + (finite(e.P_barg) ? num(e.P_barg) : 'n/a') + '</td>' +
        '<td class="r" data-label="Purchased">' + usd(e.purchased) + '</td>' +
        '<td class="r" data-label="Bare module">' + usd(e.bare_module) + '</td></tr>';
    }).join('');
    var h = '<div class="stats stats-4" style="margin-bottom:var(--s5)">' +
      stat('Items', String(eq.length)) +
      stat('Purchased cost', usd(tp)) +
      stat('Bare module cost', usd(tb), '', 'hl') +
      stat('Cost basis', obj(d.capex).cepci_year ? 'CEPCI ' + num(d.capex.cepci, 0) : 'n/a', '', '', obj(d.capex).cepci_year ? String(d.capex.cepci_year) : '') +
      '</div>';
    h += tableWrap('<table class="t stack kit"><thead><tr><th>Item</th><th>Type</th><th class="r">Size</th><th class="r">Parallel</th><th>Material</th><th class="r">P, barg</th><th class="r">Purchased</th><th class="r">Bare module</th></tr></thead><tbody>' +
      rows + '</tbody><tfoot><tr><td>Total, ' + eq.length + ' items</td><td></td><td></td><td></td><td></td><td></td><td class="r">' + usd(tp) + '</td><td class="r">' + usd(tb) + '</td></tr></tfoot></table>', 'has-stack');
    h += '<p class="small muted" style="margin-top:var(--s3)">CS carbon steel, SS stainless steel. Sizes above the correlation range are split into identical parallel units.</p>';
    return h;
  }

  function barBlock(items) {
    var total = items.reduce(function (a, x) { return a + Math.max(0, x[1] || 0); }, 0) || 1;
    return '<div class="bar" role="img" aria-label="' + esc(items.map(function (x) { return x[0] + ' ' + usd(x[1]); }).join(', ')) + '">' +
      items.map(function (x, i) { return '<span class="c' + (i % 6) + '" style="width:' + (Math.max(0, x[1]) / total * 100).toFixed(2) + '%"></span>'; }).join('') +
      '</div><ul class="legend-list">' + items.map(function (x, i) {
        return '<li><i class="c' + (i % 6) + '"></i><span>' + esc(x[0]) + '</span><span class="lv">' + usd(x[1]) + '</span></li>';
      }).join('') + '</ul>';
  }

  function secCosts(d) {
    var c = obj(d.capex), e = obj(d.economics), h = '';
    var parts = [['Bare module equipment', c.bare_module_total], ['Contingency and fee', c.contingency_and_fee], ['Auxiliary facilities', c.auxiliary_facilities]];
    arr(c.extra_items).forEach(function (x) {
      if (x && (finite(x.cost) || finite(x.value))) parts.push([x.label || x.name || 'Other', finite(x.cost) ? x.cost : x.value]);
    });
    h += '<div class="split">';
    h += '<div class="card"><div class="sub-h" style="margin-top:0"><h3>Fixed capital</h3><span class="stat-value num" style="font-size:1.25rem">' + usd(c.fixed_capital || e.fci) + '</span></div>' +
      barBlock(parts.filter(function (p) { return finite(p[1]); })) +
      '<p class="small muted" style="margin:var(--s4) 0 0">' + esc(c.method || '') + (c.cepci_year ? ', CEPCI ' + num(c.cepci, 0) + ' (' + c.cepci_year + ')' : '') + '.</p></div>';
    var com = obj(e.com_breakdown), comItems = Object.keys(com).map(function (k) { return [k, com[k]]; }).filter(function (x) { return finite(x[1]) && x[1] > 0; });
    h += '<div class="card"><div class="sub-h" style="margin-top:0"><h3>Cost of manufacture</h3><span class="stat-value num" style="font-size:1.25rem">' + usd(e.com) + '<span class="u">/yr</span></span></div>' +
      barBlock(comItems) +
      '<p class="small muted" style="margin:var(--s4) 0 0">Turton Eq. 8.2, before depreciation. Utility, waste and raw material costs carry the 1.23 overhead factor.</p></div>';
    h += '</div>';
    h += subHead('Returns');
    h += '<div class="stats stats-4">' +
      stat('Revenue', usd(e.revenue), '/yr', '', finite(e.byproduct_credit) && e.byproduct_credit ? 'Includes ' + usd(e.byproduct_credit) + ' by product credit' : '') +
      stat('Profit before tax', usd(e.annual_profit_before_tax), '/yr') +
      stat('NPV', usd(e.npv), '', 'hl', finite(e.rate) ? 'At ' + BP.pct(e.rate * 100, 0) + ' over ' + e.life + ' years, ' + BP.pct(e.tax * 100, 0) + ' tax' : '') +
      stat('IRR', finite(e.irr) ? BP.pct(e.irr * 100, 1) : 'n/a') +
      stat('Payback', finite(e.payback_years) ? num(e.payback_years, 1) : 'n/a', 'years', '', 'From start up') +
      stat('Cost of manufacture', usd(e.cost_per_tonne), '/t') +
      stat('Levelised cost', usd(e.levelised_cost_per_tonne), '/t', '', 'Cost plus capital recovery') +
      stat('Capital intensity', usd(e.capex_per_annual_tonne), '/t per yr') +
      '</div>';
    var opex = [['Raw materials', e.raw_materials], ['Utilities', e.utilities], ['Waste treatment', e.waste_treatment], ['Operating labour', e.labour], ['Working capital', e.working_capital]].filter(function (x) { return finite(x[1]) && x[1] !== 0; });
    if (opex.length) {
      h += subHead('Direct costs', 'Per year, before overheads');
      h += '<dl class="kv">' + opex.map(function (x) { return '<div><dt>' + x[0] + '</dt><dd class="num">' + usd(x[1]) + '</dd></div>'; }).join('') +
        (obj(d.labour).operators ? '<div><dt>Operators</dt><dd class="num">' + d.labour.operators + ' (' + num(d.labour.per_shift, 1) + ' per shift)</dd></div>' : '') + '</dl>';
    }
    if (arr(e.cumulative).length > 1) {
      h += subHead('Cumulative cash flow', 'Undiscounted, by year from the start of construction');
      h += '<div class="card chart-card">' + cashChart(arr(e.cumulative)) + '</div>';
    }
    return h;
  }

  function niceStep(range, n) {
    var raw = range / n, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }

  function cashChart(cum) {
    var host = document.querySelector('[data-sec="costs"]');
    var W = Math.max(300, Math.min(1000, (host && host.clientWidth ? host.clientWidth : 640) - 34));
    var H = W < 520 ? 220 : 280, L = 62, R = 10, T = 12, B = 28;
    var lo = Math.min(0, Math.min.apply(null, cum)), hi = Math.max(0, Math.max.apply(null, cum));
    var step = niceStep(hi - lo || 1, 4);
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    var n = cum.length - 1;
    var x = function (i) { return L + (W - L - R) * i / n; };
    var y = function (v) { return T + (H - T - B) * (hi - v) / (hi - lo || 1); };
    var s = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Cumulative cash flow from ' + usd(cum[0]) + ' to ' + usd(cum[n]) + ' over ' + n + ' years">';
    for (var v = lo; v <= hi + step / 2; v += step) {
      s += '<line class="' + (Math.abs(v) < step / 2 ? 'zero' : 'axis') + '" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '"/>';
      s += '<text x="' + (L - 8) + '" y="' + (y(v) + 4).toFixed(1) + '" text-anchor="end">' + usd(Math.abs(v) < step / 2 ? 0 : v) + '</text>';
    }
    var tick = n > 15 ? 5 : n > 8 ? (W < 520 ? 5 : 2) : 1;
    for (var i = 0; i <= n; i += tick) s += '<text x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle">' + i + '</text>';
    var pts = cum.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); });
    var y0 = y(0).toFixed(1);
    s += '<defs><clipPath id="cpos"><rect x="0" y="0" width="' + W + '" height="' + y0 + '"/></clipPath><clipPath id="cneg"><rect x="0" y="' + y0 + '" width="' + W + '" height="' + H + '"/></clipPath></defs>';
    var area = 'M' + x(0).toFixed(1) + ',' + y0 + ' L' + pts.join(' L') + ' L' + x(n).toFixed(1) + ',' + y0 + 'Z';
    s += '<path class="area-pos" clip-path="url(#cpos)" d="' + area + '"/><path class="area-neg" clip-path="url(#cneg)" d="' + area + '"/>';
    s += '<polyline class="line" points="' + pts.join(' ') + '"/>';
    s += '</svg>';
    return s;
  }

  function secHazards(d) {
    var h = '';
    var ph = arr(d.process_hazards);
    if (ph.length) {
      h += subHead('Process hazards');
      h += '<div class="flag-list">' + ph.map(function (x) {
        return '<div class="card flag"><span class="ico">' + ICON.warn + '</span><div><h4>' + esc(x.hazard) + '</h4><p>' + chem(x.detail) + '</p></div></div>';
      }).join('') + '</div>';
    }
    var hz = arr(d.hazards);
    if (hz.length) {
      h += subHead('Substances', 'GHS statements, EU CLP harmonised classification');
      h += '<div class="haz-grid">' + hz.map(function (s) {
        var props = [];
        var pv = function (lab, v, u) { props.push('<div><dt>' + lab + '</dt><dd>' + (finite(v) ? num(v) + (u ? ' ' + u : '') : '<span class="muted">n/a</span>') + '</dd></div>'); };
        pv('Flash point', s.flash_point_C, '\u00b0C');
        pv('Autoignition', s.autoignition_C, '\u00b0C');
        pv('LFL', s.LFL_pct, '% vol');
        pv('UFL', s.UFL_pct, '% vol');
        var ghs = arr(s.ghs);
        return '<div class="card sub-card"><div class="head"><div><h4>' + esc(s.name) + '</h4><span class="meta">' + chem(s.formula || '') + (s.cas ? ' \u00b7 CAS ' + esc(s.cas) : '') + '</span></div>' +
          (s.severe ? '<span class="pill pill-fail">Severe</span>' : ghs.length ? '<span class="pill pill-warn">Hazardous</span>' : '<span class="pill">Not classified</span>') + '</div>' +
          (ghs.length ? '<ul class="ghs">' + ghs.map(function (g) { return '<li><code>' + esc(g.code) + '</code><span>' + esc(g.text) + '</span></li>'; }).join('') + '</ul>'
            : '<p class="small muted" style="margin:0">No harmonised GHS hazard statements.</p>') +
          '<dl class="props">' + props.join('') + '</dl></div>';
      }).join('') + '</div>';
    }
    var hp = arr(d.hazop);
    if (hp.length) {
      h += subHead('Starter HAZOP', 'Worked examples, not a full study');
      h += tableWrap('<table class="t stack stack-text"><thead><tr><th>Node</th><th>Deviation</th><th>Cause</th><th>Consequence</th><th>Safeguard</th></tr></thead><tbody>' +
        hp.map(function (r) {
          return '<tr><td data-label="Node"><strong>' + esc(r.node) + '</strong></td><td data-label="Deviation">' + esc(r.deviation) + '</td><td data-label="Cause">' + esc(r.cause) +
            '</td><td data-label="Consequence">' + esc(r.consequence) + '</td><td data-label="Safeguard">' + esc(r.safeguard) + '</td></tr>';
        }).join('') + '</tbody></table>', 'has-stack');
    }
    return h || '<p class="muted">No hazard data in this design.</p>';
  }

  function secCarbon(d) {
    var c = obj(d.carbon), h = '';
    var parts = [['Direct CO\u2082', c.direct_co2, 1], ['N\u2082O as CO\u2082e', c.direct_n2o_co2e, 1], ['Methane as CO\u2082e', c.direct_ch4_co2e, 1], ['Electricity', c.electricity, 2], ['Steam', c.steam, 2]];
    var s1 = parts.filter(function (p) { return p[2] === 1; }).reduce(function (a, p) { return a + (finite(p[1]) ? p[1] : 0); }, 0);
    var s2 = parts.filter(function (p) { return p[2] === 2; }).reduce(function (a, p) { return a + (finite(p[1]) ? p[1] : 0); }, 0);
    var unit = 't CO<sub>2</sub>e/t';
    h += '<div class="stats">' + stat('Total', num(c.total), unit, 'hl') + stat('Scope 1', num(s1), unit) + stat('Scope 2', num(s2), unit) + '</div>';
    h += subHead('Breakdown', 'Per tonne of product');
    var items = parts.filter(function (p) { return finite(p[1]) && Math.abs(p[1]) > 0; });
    var tot = items.reduce(function (a, p) { return a + Math.max(0, p[1]); }, 0) || 1;
    h += '<div class="card"><div class="bar" role="img" aria-label="Carbon breakdown">' + items.map(function (p, i) {
      return '<span class="c' + i + '" style="width:' + (Math.max(0, p[1]) / tot * 100).toFixed(2) + '%"></span>';
    }).join('') + '</div><ul class="legend-list">' + items.map(function (p, i) {
      return '<li><i class="c' + i + '"></i><span>' + p[0] + '</span><span class="lv"><span class="muted">Scope ' + p[2] + '</span>' + num(p[1]) + '</span></li>';
    }).join('') + '</ul>' +
      '<p class="small muted" style="margin:var(--s4) 0 0">' + esc(c.scope_note || '') + (finite(c.grid_kg_kwh) ? ' Grid factor ' + num(c.grid_kg_kwh) + ' kg CO<sub>2</sub>/kWh.' : '') + '</p></div>';
    var g = obj(d.greener);
    if (g.title || g.text) {
      h += subHead('Greener route');
      h += '<div class="card greener"><h4>' + chem(g.title || '') + '</h4><p>' + chem(g.text || '') + '</p>' +
        (finite(g.electricity_MWh_per_t) ? '<p class="greener-fig"><span>Electricity needed</span><strong class="num">' + num(g.electricity_MWh_per_t) + '<span class="u">MWh/t</span></strong></p>' : '') + '</div>';
    }
    return h;
  }

  function secValidation(d) {
    var v = arr(d.validation);
    if (!v.length) return '<p class="muted">No published benchmarks for this design yet.</p>';
    var np = v.filter(function (x) { return x.pass; }).length;
    var h = '<div class="val-summary"><span class="val-big">' + np + ' of ' + v.length + '</span><span class="muted">checks within tolerance of published figures</span></div>';
    h += tableWrap('<table class="t stack"><thead><tr><th>Check</th><th class="r">Model</th><th class="r">Published</th><th>Unit</th><th class="r">Error</th><th class="r">Tolerance</th><th>Result</th><th>Source</th></tr></thead><tbody>' +
      v.map(function (x) {
        var pub = Array.isArray(x.published) ? num(x.published[0]) + ' to ' + num(x.published[1]) : num(x.published);
        var badge = x.pass === true ? '<span class="badge badge-pass">' + ICON.pass + 'Pass</span>' : x.pass === false ? '<span class="badge badge-fail">' + ICON.fail + 'Outside</span>' : '<span class="badge badge-na">n/a</span>';
        var err = finite(x.error_pct) ? (x.error_pct > 0 ? '+' : '') + BP.num(x.error_pct, 1) + '%' : 'n/a';
        if (Array.isArray(x.published) && x.error_pct === 0) err = 'In range';
        return '<tr><td data-label="Check"><strong>' + chem(x.metric) + '</strong>' + (x.note ? '<span class="sub">' + esc(x.note) + '</span>' : '') + '</td>' +
          '<td class="r" data-label="Model">' + num(x.model) + '</td><td class="r" data-label="Published">' + pub + '</td><td data-label="Unit">' + BP.unit(x.unit || '') + '</td>' +
          '<td class="r" data-label="Error">' + err + '</td><td class="r" data-label="Tolerance">' + (finite(x.tolerance_pct) ? '\u00b1' + num(x.tolerance_pct, 0) + '%' : 'n/a') + '</td>' +
          '<td data-label="Result">' + badge + '</td><td data-label="Source">' + link(x.url, x.source) + '</td></tr>';
      }).join('') + '</tbody></table>', 'has-stack');
    return h;
  }

  function secAssumptions(d) {
    var h = '';
    var a = arr(d.assumptions), n = arr(d.notes);
    if (a.length) h += '<ol class="list">' + a.map(function (x, i) { return '<li><span class="n">' + (i + 1) + '</span><span>' + chem(x) + '</span></li>'; }).join('') + '</ol>';
    if (n.length) { h += subHead('Notes'); h += '<ol class="list">' + n.map(function (x, i) { return '<li><span class="n">' + (i + 1) + '</span><span>' + chem(x) + '</span></li>'; }).join('') + '</ol>'; }
    h += '<p class="disclaimer" style="margin-top:var(--s5)">Screening level design for study and scoping. Capital cost is a factored estimate, typically within minus 30 to plus 50 percent. Not for construction.' +
      (d.engine_version ? ' Engine version ' + esc(d.engine_version) + '.' : '') + '</p>';
    return h;
  }

  /* ================================================================ flow diagram */

  var G = { BW: 164, BH: 68, CW: 240, RH: 176, ML: 250, MR: 250, MT: 72, MB: 72 };

  function wrapText(s, max) {
    var words = String(s || '').split(/\s+/), lines = [], cur = '';
    words.forEach(function (w) {
      if (!cur) cur = w;
      else if ((cur + ' ' + w).length <= max) cur += ' ' + w;
      else { lines.push(cur); cur = w; }
    });
    if (cur) lines.push(cur);
    var cap = arguments[2] || 2;
    if (lines.length > cap) { lines = lines.slice(0, cap); lines[cap - 1] = lines[cap - 1].replace(/\s*\S*$/, '') + '\u2026'; }
    return lines;
  }

  function layoutPFD(d) {
    var units = arr(d.units).filter(function (u) { return Array.isArray(u.pos) && u.pos.length >= 2; });
    if (!units.length) return null;
    var cols = [], rows = [];
    units.forEach(function (u) { if (cols.indexOf(u.pos[0]) < 0) cols.push(u.pos[0]); if (rows.indexOf(u.pos[1]) < 0) rows.push(u.pos[1]); });
    cols.sort(function (a, b) { return a - b; }); rows.sort(function (a, b) { return a - b; });
    var X0 = G.ML, Y0 = G.MT, gapX = G.CW - G.BW, gapY = G.RH - G.BH;
    var U = {}, occ = {};
    units.forEach(function (u) {
      var c = cols.indexOf(u.pos[0]), r = rows.indexOf(u.pos[1]);
      var key = c + ',' + r;
      if (occ[key]) return; // two units on one cell: keep the first
      occ[key] = u.id;
      U[u.id] = { u: u, c: c, r: r, x: X0 + c * G.CW, y: Y0 + r * G.RH, ports: { L: [], R: [], T: [], B: [] } };
    });
    var nC = cols.length, nR = rows.length;
    var unitsRight = X0 + (nC - 1) * G.CW + G.BW;
    var W = unitsRight + G.MR, H = Y0 + (nR - 1) * G.RH + G.BH + G.MB;
    var vx = function (k) { return X0 + k * G.CW - gapX / 2; };          // vertical channel left of column k
    var hy = function (k) { return Y0 + k * G.RH - gapY / 2; };          // horizontal channel above row k
    var blockedLeft = function (c, r) { for (var k = 0; k < c; k++) if (occ[k + ',' + r]) return true; return false; };
    var blockedRight = function (c, r) { for (var k = c + 1; k < nC; k++) if (occ[k + ',' + r]) return true; return false; };

    var all = arr(d.streams);
    var mixInto = {};
    all.forEach(function (s) { if (s.from === 'mix' && U[s.to]) mixInto[s.to] = s; });
    var drawn = all.filter(function (s) {
      if (!s.from || !s.to || s.from === s.to) return false;
      var okFrom = U[s.from] || s.from === 'IN' || (s.from === 'mix' && U[s.to]);
      var okTo = U[s.to] || s.to === 'OUT';
      return okFrom && okTo && !(s.from === 'IN' && s.to === 'OUT');
    });

    // recycle detection: back edges in a depth first walk from the feeds
    var adj = {};
    drawn.forEach(function (s) { var f = s.from === 'mix' ? '@mix:' + s.to : s.from; (adj[f] = adj[f] || []).push(s); });
    drawn.forEach(function (s) { if (s.from !== 'mix' && mixInto[s.to] && U[s.to]) { /* edge into mix node */ } });
    var recycle = {}, color = {};
    function nodeOf(s) { return s.to === 'OUT' ? null : (mixInto[s.to] && s.from !== 'mix' ? '@mix:' + s.to : s.to); }
    function dfs(n) {
      color[n] = 1;
      (adj[n] || []).forEach(function (s) {
        var t = nodeOf(s); if (!t) return;
        if (color[t] === 1) recycle[s.id] = true;
        else if (!color[t]) dfs(t);
      });
      color[n] = 2;
    }
    dfs('IN');
    Object.keys(U).forEach(function (k) { if (!color[k]) dfs(k); });
    drawn.forEach(function (s) { if (/recycle/i.test(s.name || '')) recycle[s.id] = true; });

    // main product: the exit stream carrying most of the first product
    var prodId = arr(d.products)[0] && d.products[0].id, mainProd = null, best = -1;
    drawn.forEach(function (s) {
      if (s.to !== 'OUT') return;
      var x = obj(s.components)[prodId], v = x && finite(x.kg_h) ? x.kg_h : 0;
      if (/product/i.test(s.name || '')) v += 1e-6;
      if (v > best) { best = v; mainProd = s.id; }
    });

    // mix nodes
    var mixNode = {};
    Object.keys(mixInto).forEach(function (uid) { mixNode[uid] = { uid: uid, s: mixInto[uid] }; });

    // decide routing class and port sides for each stream
    var routes = drawn.map(function (s) {
      var r = { s: s, recycle: !!recycle[s.id], product: s.id === mainProd };
      var A = U[s.from], B = U[s.to];
      var toMix = B && mixNode[s.to] && s.from !== 'mix';
      r.toMix = toMix ? mixNode[s.to] : null;
      if (s.from === 'mix') { r.kind = 'mixout'; r.B = B; r.inSide = 'L'; B.ports.L.push(r); return r; }
      if (s.from === 'IN') {
        r.kind = 'feed'; r.B = B;
        if (toMix) { r.kind = 'feedmix'; return r; }
        if (!blockedLeft(B.c, B.r)) { r.inSide = 'L'; B.ports.L.push(r); }
        else { r.inSide = 'T'; B.ports.T.push(r); }
        return r;
      }
      if (s.to === 'OUT') {
        r.kind = 'exit'; r.A = A;
        if (!blockedRight(A.c, A.r)) { r.outSide = 'R'; A.ports.R.push(r); }
        else { r.outSide = 'B'; A.ports.B.push(r); }
        return r;
      }
      r.A = A; r.B = B;
      var dc = B.c - A.c, dr = B.r - A.r;
      if (toMix) {
        // target is a point just left of B
        if (dr === 0 && dc === -1 + 0 && false) return r;
        if (dr === 0 && dc === 1) { r.kind = 'straight'; r.outSide = 'R'; A.ports.R.push(r); }
        else if (dr === 0) { r.kind = 'chan'; r.outSide = r.recycle || dc < 0 ? 'B' : 'T'; A.ports[r.outSide].push(r); }
        else if (Math.abs(dr) === 1) { r.kind = 'chan'; r.outSide = dr > 0 ? 'B' : 'T'; A.ports[r.outSide].push(r); }
        else { r.kind = 'side'; r.outSide = (vx(B.c) > A.x + G.BW / 2) ? 'R' : 'L'; A.ports[r.outSide].push(r); }
        return r;
      }
      if (dr === 0 && Math.abs(dc) === 1) {
        r.kind = 'straight'; r.outSide = dc > 0 ? 'R' : 'L'; r.inSide = dc > 0 ? 'L' : 'R';
      } else if (dc === 0 && Math.abs(dr) === 1) {
        r.kind = 'vert'; r.outSide = dr > 0 ? 'B' : 'T'; r.inSide = dr > 0 ? 'T' : 'B';
      } else if (dr === 0) {
        r.kind = 'chan'; r.outSide = r.recycle || dc < 0 ? 'B' : 'T'; r.inSide = r.outSide;
      } else if (Math.abs(dr) === 1) {
        r.kind = 'chan'; r.outSide = dr > 0 ? 'B' : 'T'; r.inSide = dr > 0 ? 'T' : 'B';
      } else {
        r.kind = 'side'; r.outSide = dc >= 0 ? 'R' : 'L'; r.inSide = dr > 0 ? 'T' : 'B';
      }
      A.ports[r.outSide].push(r); B.ports[r.inSide].push(r);
      return r;
    });

    // other end position, used to order ports and so reduce crossings
    function otherEnd(r, atUnit) {
      var o = (atUnit === r.A) ? (r.B || null) : (r.A || null);
      if (o) return { x: o.x + G.BW / 2, y: o.y + G.BH / 2 };
      if (r.kind === 'exit') return { x: W, y: atUnit.y + G.BH / 2 + 1 };
      return { x: 0, y: atUnit.y + G.BH / 2 - 1 };
    }
    Object.keys(U).forEach(function (id) {
      var P = U[id];
      ['L', 'R', 'T', 'B'].forEach(function (side) {
        var list = P.ports[side];
        list.sort(function (a, b) {
          var ea = otherEnd(a, P), eb = otherEnd(b, P);
          return side === 'L' || side === 'R' ? ea.y - eb.y : ea.x - eb.x;
        });
        list.forEach(function (r, i) {
          var f = (i + 1) / (list.length + 1);
          var pt = side === 'L' ? { x: P.x, y: P.y + G.BH * f } : side === 'R' ? { x: P.x + G.BW, y: P.y + G.BH * f }
            : side === 'T' ? { x: P.x + G.BW * f, y: P.y } : { x: P.x + G.BW * f, y: P.y + G.BH };
          if (r.A === P && r.outSide === side) r.p0 = pt; else r.p1 = pt;
        });
      });
    });
    // mix node points
    Object.keys(mixNode).forEach(function (uid) {
      var m = mixNode[uid], r = routes.filter(function (x) { return x.s === m.s; })[0];
      m.x = U[uid].x - 26; m.y = r && r.p1 ? r.p1.y : U[uid].y + G.BH / 2;
      if (r) r.p0 = { x: m.x, y: m.y };
    });

    // channel track allocation (interval colouring per horizontal channel)
    var tracks = {};
    var PREF_MID = [0, -1, 1, -2, 2, -3, 3, -4, 4], PREF_LOW = [0, 1, 2, 3, 4, -1, -2, -3, -4];
    function trackFor(key, a, b, prefs) {
      var lo = Math.min(a, b) - 8, hi = Math.max(a, b) + 8;
      var used = tracks[key] = tracks[key] || [];
      prefs = prefs || PREF_MID;
      for (var i = 0; i < prefs.length; i++) {
        var t = prefs[i];
        var clash = used.some(function (u) { return u.t === t && !(hi < u.lo || lo > u.hi); });
        if (!clash) { used.push({ t: t, lo: lo, hi: hi }); return t; }
      }
      return 0;
    }
    function step(gap) { return Math.max(10, Math.min(12, (gap - 28) / 8)); }
    function chanY(k, x1, x2, prefs) { return hy(k) + trackFor('h' + k, x1, x2, prefs) * step(gapY); }
    function chanX(k, y1, y2) { return vx(k) + trackFor('v' + k, y1, y2) * step(gapX); }

    var leftX = X0 - 64, rightX = unitsRight + 64;
    // route internal streams first, then exits right to left so exits from further left run lower and never cross
    var ordered = routes.filter(function (r) { return r.kind !== 'exit'; })
      .concat(routes.filter(function (r) { return r.kind === 'exit'; }).sort(function (a, b) { return b.p0.x - a.p0.x; }));
    ordered.forEach(function (r) {
      var s = r.s, p, A = r.A, B = r.B, m = r.toMix;
      var target = m ? { x: m.x, y: m.y } : r.p1;
      if (r.kind === 'mixout') { r.pts = [r.p0, r.p1]; return; }
      if (r.kind === 'feed' || r.kind === 'feedmix') {
        if (r.kind === 'feed' && r.inSide === 'L') { r.pts = [{ x: leftX, y: r.p1.y }, r.p1]; }
        else {
          var tgt = target || { x: B.x - 26, y: B.y + G.BH / 2 };
          if (r.kind === 'feedmix' && !blockedLeft(B.c, B.r)) r.pts = [{ x: leftX, y: tgt.y }, tgt];
          else { var yh = chanY(B.r, leftX, tgt.x); r.pts = [{ x: leftX, y: yh }, { x: tgt.x, y: yh }, tgt]; }
        }
        r.labelSide = 'L';
        return;
      }
      if (r.kind === 'exit') {
        if (r.outSide === 'R') r.pts = [r.p0, { x: rightX, y: r.p0.y }];
        else { var y2 = chanY(A.r + 1, r.p0.x, rightX, PREF_LOW); r.pts = [r.p0, { x: r.p0.x, y: y2 }, { x: rightX, y: y2 }]; }
        r.labelSide = 'R';
        return;
      }
      p = r.p0;
      if (r.kind === 'straight') {
        var t = target;
        if (Math.abs(p.y - t.y) < 0.5) r.pts = [p, t];
        else { var mx = m ? (p.x + t.x) / 2 : (p.x + t.x) / 2; r.pts = [p, { x: mx, y: p.y }, { x: mx, y: t.y }, t]; }
      } else if (r.kind === 'vert') {
        var t2 = target;
        if (Math.abs(p.x - t2.x) < 0.5) r.pts = [p, t2];
        else { var my = (p.y + t2.y) / 2; r.pts = [p, { x: p.x, y: my }, { x: t2.x, y: my }, t2]; }
      } else if (r.kind === 'chan') {
        var k = r.outSide === 'B' ? A.r + 1 : A.r;
        var yc = chanY(k, p.x, target.x);
        r.pts = [p, { x: p.x, y: yc }, { x: target.x, y: yc }, target];
      } else { // side: out of A horizontally, along a vertical channel, along the channel next to B, into B
        var kv = r.outSide === 'R' ? A.c + 1 : A.c;
        var kh = B.r > A.r ? B.r : B.r + 1;
        var yc2 = hy(kh);
        var xc = chanX(kv, p.y, yc2);
        yc2 = chanY(kh, xc, target.x);
        r.pts = [p, { x: xc, y: p.y }, { x: xc, y: yc2 }, { x: target.x, y: yc2 }, target];
      }
    });

    // spread feed and exit labels so they never overlap
    ['L', 'R'].forEach(function (side) {
      var list = routes.filter(function (r) { return r.labelSide === side; });
      list.sort(function (a, b) { return (side === 'L' ? a.pts[0].y - b.pts[0].y : a.pts[a.pts.length - 1].y - b.pts[b.pts.length - 1].y); });
      var minGap = 50, prev = -1e9;
      list.forEach(function (r, i) {
        var end = side === 'L' ? r.pts[0] : r.pts[r.pts.length - 1];
        var ly = Math.max(end.y, prev + minGap);
        prev = ly;
        r.labelY = ly;
        if (Math.abs(ly - end.y) > 0.5) {
          var jx = side === 'L' ? leftX + 14 + i * 5 : rightX - 14 - i * 5;
          if (side === 'L') r.pts = [{ x: leftX - 10, y: ly }, { x: jx, y: ly }, { x: jx, y: end.y }].concat(r.pts.slice(1));
          else r.pts = r.pts.slice(0, -1).concat([{ x: jx, y: end.y }, { x: jx, y: ly }, { x: rightX + 10, y: ly }]);
        } else if (side === 'L') { r.pts[0] = { x: leftX - 10, y: end.y }; }
        else { r.pts[r.pts.length - 1] = { x: rightX + 10, y: end.y }; }
      });
      if (list.length) {
        var last = list[list.length - 1].labelY + 30;
        if (last > H - 8) H = last + 8;
      }
    });

    return { U: U, routes: routes, mixNode: mixNode, W: W, H: H, leftX: leftX, rightX: rightX, mainProd: mainProd };
  }

  function simplify(pts) {
    var out = [];
    pts.forEach(function (p) {
      var last = out[out.length - 1];
      if (last && Math.abs(last.x - p.x) < 0.01 && Math.abs(last.y - p.y) < 0.01) return;
      out.push({ x: p.x, y: p.y });
      if (out.length >= 3) {
        var a = out[out.length - 3], b = out[out.length - 2], c = out[out.length - 1];
        if ((Math.abs(a.x - b.x) < 0.01 && Math.abs(b.x - c.x) < 0.01) || (Math.abs(a.y - b.y) < 0.01 && Math.abs(b.y - c.y) < 0.01)) out.splice(out.length - 2, 1);
      }
    });
    return out;
  }

  function pathD(pts) {
    var r = 6, d = 'M' + pts[0].x.toFixed(1) + ' ' + pts[0].y.toFixed(1);
    for (var i = 1; i < pts.length; i++) {
      var p = pts[i];
      if (i < pts.length - 1) {
        var a = pts[i - 1], n = pts[i + 1];
        var l1 = Math.hypot(p.x - a.x, p.y - a.y), l2 = Math.hypot(n.x - p.x, n.y - p.y);
        var rr = Math.min(r, l1 / 2, l2 / 2);
        var b = { x: p.x - (p.x - a.x) / l1 * rr, y: p.y - (p.y - a.y) / l1 * rr };
        var c = { x: p.x + (n.x - p.x) / l2 * rr, y: p.y + (n.y - p.y) / l2 * rr };
        d += ' L' + b.x.toFixed(1) + ' ' + b.y.toFixed(1) + ' Q' + p.x.toFixed(1) + ' ' + p.y.toFixed(1) + ' ' + c.x.toFixed(1) + ' ' + c.y.toFixed(1);
      } else d += ' L' + p.x.toFixed(1) + ' ' + p.y.toFixed(1);
    }
    return d;
  }

  function arrowHead(a, b, cls) {
    var dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, s = 7, w = 3.6;
    var p1 = (b.x - ux * s - uy * w).toFixed(1) + ',' + (b.y - uy * s + ux * w).toFixed(1);
    var p2 = (b.x - ux * s + uy * w).toFixed(1) + ',' + (b.y - uy * s - ux * w).toFixed(1);
    return '<polygon class="' + cls + '" points="' + b.x.toFixed(1) + ',' + b.y.toFixed(1) + ' ' + p1 + ' ' + p2 + '"/>';
  }

  function renderPFD(d) {
    var L = layoutPFD(d);
    if (!L) return null;
    var occupied = [];
    Object.keys(L.U).forEach(function (id) { var P = L.U[id]; occupied.push({ x: P.x - 4, y: P.y - 4, w: G.BW + 8, h: G.BH + 8 }); });
    function hits(b) { return occupied.some(function (o) { return !(b.x + b.w < o.x || b.x > o.x + o.w || b.y + b.h < o.y || b.y > o.y + o.h); }); }

    var svg = '<svg class="pfd" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + L.W + ' ' + Math.ceil(L.H) + '" width="' + L.W + '" height="' + Math.ceil(L.H) + '" role="group" aria-label="Process flow diagram">';
    // labels for feeds and exits first so stream pills avoid them
    var labels = '';
    L.routes.forEach(function (r) {
      if (!r.labelSide) return;
      var lines = wrapText(r.s.name, 26, 3), lx, anchor;
      if (r.labelSide === 'L') { lx = L.leftX - 18; anchor = 'end'; } else { lx = L.rightX + 18; anchor = 'start'; }
      var y0 = r.labelY - (lines.length - 1) * 7.5 + 4;
      var maxw = Math.max.apply(null, lines.map(function (t) { return t.length; })) * 6.9;
      occupied.push({ x: anchor === 'end' ? lx - maxw : lx, y: y0 - 12, w: maxw, h: lines.length * 14 + 4 });
      r.labelSvg = '<text class="t-label" x="' + lx + '" y="' + y0 + '" text-anchor="' + anchor + '">' + lines.map(function (t, i) {
        return '<tspan x="' + lx + '" dy="' + (i ? 15 : 0) + '">' + esc(t) + '</tspan>';
      }).join('') + '</text>';
    });
    var streamsSvg = '', pillsSvg = '';
    // draw non highlighted first, product last
    var order = L.routes.slice().sort(function (a, b) { return (a.product ? 1 : 0) - (b.product ? 1 : 0); });
    var allSegs = [];
    order.forEach(function (r) {
      r.pts = simplify(r.pts);
      for (var i = 1; i < r.pts.length; i++) allSegs.push({ id: r.s.id, a: r.pts[i - 1], b: r.pts[i] });
    });
    function crossesOther(b, sid) {
      return allSegs.some(function (sg) {
        if (sg.id === sid) return false;
        var x1 = Math.min(sg.a.x, sg.b.x) - 2, x2 = Math.max(sg.a.x, sg.b.x) + 2, y1 = Math.min(sg.a.y, sg.b.y) - 2, y2 = Math.max(sg.a.y, sg.b.y) + 2;
        return !(x2 < b.x || x1 > b.x + b.w || y2 < b.y || y1 > b.y + b.h);
      });
    }
    order.forEach(function (r) {
      var pts = r.pts;
      var cls = 'stream' + (r.recycle ? ' recycle' : '') + (r.product ? ' product' : '');
      var d0 = pathD(pts);
      var last = pts[pts.length - 1], prev = pts[pts.length - 2];
      var headCls = r.product ? 'arrow arrow-accent' : 'arrow';
      var arrow = r.toMix ? '' : arrowHead(prev, last, headCls);
      // pill on the longest segment, avoiding units and other pills
      var segs = [];
      for (var i = 1; i < pts.length; i++) segs.push({ a: pts[i - 1], b: pts[i], len: Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y) });
      var cand = segs.slice().sort(function (a, b) { return b.len - a.len; });
      var pw = 10 + r.s.id.length * 6.9, ph = 18, pos = null;
      if (r.labelSide) {
        var sg = r.labelSide === 'L' ? segs[0] : segs[segs.length - 1];
        cand = [sg].concat(cand.filter(function (x) { return x !== sg; }));
      }
      var fr = r.labelSide === 'L' ? [0.35, 0.55, 0.75, 0.2, 0.9] : r.labelSide === 'R' ? [0.6, 0.45, 0.3, 0.75, 0.15] : [0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9];
      outer: for (var c = 0; c < cand.length; c++) {
        if (cand[c].len < pw + 10) continue;
        for (var f = 0; f < fr.length; f++) {
          var cx = cand[c].a.x + (cand[c].b.x - cand[c].a.x) * fr[f], cy = cand[c].a.y + (cand[c].b.y - cand[c].a.y) * fr[f];
          var box = { x: cx - pw / 2, y: cy - ph / 2, w: pw, h: ph };
          if (!hits(box) && !crossesOther(box, r.s.id)) { pos = box; break outer; }
        }
      }
      if (!pos) {
        outer2: for (var c2 = 0; c2 < cand.length; c2++) {
          if (cand[c2].len < pw + 10) continue;
          for (var f2 = 0; f2 < fr.length; f2++) {
            var cx2 = cand[c2].a.x + (cand[c2].b.x - cand[c2].a.x) * fr[f2], cy2 = cand[c2].a.y + (cand[c2].b.y - cand[c2].a.y) * fr[f2];
            var box2 = { x: cx2 - pw / 2, y: cy2 - ph / 2, w: pw, h: ph };
            if (!hits(box2)) { pos = box2; break outer2; }
          }
        }
      }
      if (!pos && r.kind === 'mixout') {
        var a0 = pts[0];
        [[-pw - 6, -ph - 4], [-pw - 6, 4], [-pw / 2, -ph - 6], [-pw / 2, 6]].some(function (o) {
          var bx = { x: a0.x + o[0], y: a0.y + o[1], w: pw, h: ph };
          if (!hits(bx) && !crossesOther(bx, r.s.id)) { pos = bx; return true; }
          return false;
        });
      }
      if (!pos) { var sgm = cand[0]; var mx = (sgm.a.x + sgm.b.x) / 2, my = (sgm.a.y + sgm.b.y) / 2; pos = { x: mx - pw / 2, y: my - ph / 2, w: pw, h: ph }; }
      occupied.push(pos);
      var label = esc(r.s.id) + ' ' + esc(r.s.name) + (finite(r.s.kg_h) ? ', ' + num(r.s.kg_h, 0) + ' kg/h' : '');
      streamsSvg += '<g class="' + cls + '" data-stream="' + esc(r.s.id) + '"><path class="s-line" d="' + d0 + '"/>' + arrow + '<path class="s-hit" d="' + d0 + '"/>' + (r.labelSvg || '') + '</g>';
      pillsSvg += '<g class="' + cls + '" data-stream="' + esc(r.s.id) + '" tabindex="0" role="button" aria-label="' + label + '"><g class="s-pill"><rect x="' + pos.x.toFixed(1) + '" y="' + pos.y.toFixed(1) + '" width="' + pw.toFixed(1) + '" height="' + ph + '" rx="9"/>' +
        '<text x="' + (pos.x + pw / 2).toFixed(1) + '" y="' + (pos.y + 12.5).toFixed(1) + '" text-anchor="middle">' + esc(r.s.id) + '</text></g></g>';
    });
    var mixSvg = '';
    Object.keys(L.mixNode).forEach(function (k) { var m = L.mixNode[k]; mixSvg += '<circle class="mix" cx="' + m.x + '" cy="' + m.y + '" r="4"/>'; });
    var unitsSvg = '';
    Object.keys(L.U).forEach(function (id) {
      var P = L.U[id], u = P.u, lines = wrapText(u.name, 22, 3);
      unitsSvg += '<g class="unit" data-unit="' + esc(u.id) + '" tabindex="0" role="button" aria-label="' + esc(u.id + ' ' + lines.join(' ')) + '">' +
        '<rect class="u-box" x="' + P.x + '" y="' + P.y + '" width="' + G.BW + '" height="' + G.BH + '" rx="8"/>' +
        '<text class="u-tag" x="' + (P.x + 12) + '" y="' + (P.y + 20) + '">' + esc(u.id) + '</text>' +
        lines.map(function (t, i) { return '<text class="u-name" x="' + (P.x + 12) + '" y="' + (P.y + 37 + i * 14) + '">' + esc(t) + '</text>'; }).join('') +
        '</g>';
    });
    // fit the canvas to everything drawn so nothing is clipped
    var minX = 0, minY = 0, maxX = L.W, maxY = L.H;
    occupied.forEach(function (o) { minX = Math.min(minX, o.x - 16); minY = Math.min(minY, o.y - 16); maxX = Math.max(maxX, o.x + o.w + 16); maxY = Math.max(maxY, o.y + o.h + 16); });
    L.routes.forEach(function (r) { r.pts.forEach(function (p) { minY = Math.min(minY, p.y - 24); maxY = Math.max(maxY, p.y + 24); }); });
    var VW = Math.ceil(maxX - minX), VH = Math.ceil(maxY - minY);
    svg = svg.replace(/viewBox="[^"]*" width="[^"]*" height="[^"]*"/, 'viewBox="' + Math.floor(minX) + ' ' + Math.floor(minY) + ' ' + VW + ' ' + VH + '" width="' + VW + '" height="' + VH + '"');
    svg += streamsSvg + mixSvg + unitsSvg + pillsSvg + '</svg>';
    return { svg: svg, W: VW, H: VH, L: L };
  }

  var pfd = { zoom: 1, W: 0, H: 0 };

  function secFlow(d) {
    var R = renderPFD(d);
    if (!R) return '<p class="muted">No flow diagram for this design.</p>';
    pfd.W = R.W; pfd.H = R.H;
    var shown = {};
    R.L.routes.forEach(function (r) { shown[r.s.id] = 1; });
    var hidden = arr(d.streams).filter(function (s) { return !shown[s.id]; });
    var h = '<div class="pfd-card">' +
      '<div class="pfd-bar"><ul class="legend">' +
      '<li><svg width="24" height="8" aria-hidden="true"><path d="M0 4h24" stroke="#4A5466" stroke-width="1.5"/></svg>Stream</li>' +
      '<li><svg width="24" height="8" aria-hidden="true"><path d="M0 4h24" stroke="#4A5466" stroke-width="1.5" stroke-dasharray="5 4"/></svg>Recycle</li>' +
      '<li><svg width="24" height="8" aria-hidden="true"><path d="M0 4h24" stroke="#2347F5" stroke-width="2.25"/></svg>Main product</li></ul>' +
      '<div class="pfd-zoom"><button type="button" data-zoom="-1" aria-label="Zoom out">' + ICON.minus + '</button>' +
      '<button type="button" class="zlabel" data-zoom="fit" title="Fit to width">Fit</button>' +
      '<button type="button" data-zoom="1" aria-label="Zoom in">' + ICON.plus + '</button></div></div>' +
      '<div class="pfd-scroll" id="pfd-scroll" tabindex="0" aria-label="Flow diagram, scroll to pan">' + R.svg + '</div>' +
      '<div class="detail" id="pfd-detail" hidden aria-live="polite"></div>' +
      (hidden.length ? '<div class="other-streams"><span>In the stream table only:</span>' + hidden.map(function (s) {
        return '<button type="button" data-stream="' + esc(s.id) + '">' + esc(s.id) + ' ' + esc(s.name) + '</button>';
      }).join('') + '</div>' : '') +
      '<div class="pfd-hint">' + ICON.hand + '<span>Drag or scroll to pan. Tap a stream label or a unit for details.</span></div>' +
      '</div>';
    return h;
  }

  function setZoom(z) {
    var sc = $('#pfd-scroll'); if (!sc) return;
    var svg = sc.querySelector('svg'); if (!svg) return;
    var fit = (sc.clientWidth - 2) / pfd.W;
    if (z === 'fit') z = fit;
    z = Math.max(Math.min(fit, 0.35), Math.min(1.6, z));
    var cx = (sc.scrollLeft + sc.clientWidth / 2) / (pfd.zoom || 1);
    pfd.zoom = z;
    svg.setAttribute('width', Math.round(pfd.W * z));
    svg.setAttribute('height', Math.round(pfd.H * z));
    sc.scrollLeft = Math.max(0, cx * z - sc.clientWidth / 2);
    var lab = $('.pfd-zoom .zlabel'); if (lab) lab.textContent = Math.abs(z - fit) < 0.01 ? 'Fit' : Math.round(z * 100) + '%';
  }

  function initialZoom() {
    var sc = $('#pfd-scroll'); if (!sc) return;
    var fit = (sc.clientWidth - 2) / pfd.W;
    // readable text first: on a phone keep labels near 8 px and pan instead of shrinking further
    var z = fit >= 0.72 ? Math.min(1, fit) : Math.max(fit, 0.72);
    pfd.zoom = z;
    setZoom(z);
    sc.scrollLeft = 0;
  }

  function showStream(id, scroll) {
    var d = state.data, s = streamById(d, id), box = $('#pfd-detail');
    if (!s || !box) return;
    document.querySelectorAll('svg.pfd .sel').forEach(function (n) { n.classList.remove('sel'); });
    document.querySelectorAll('svg.pfd [data-stream="' + CSS.escape(id) + '"]').forEach(function (n) { n.classList.add('sel'); });
    var comps = Object.keys(obj(s.components)).map(function (c) { return [c, s.components[c]]; })
      .filter(function (x) { return x[1] && finite(x[1].kg_h) && Math.abs(x[1].kg_h) > 1e-6; })
      .sort(function (a, b) { return b[1].kg_h - a[1].kg_h; });
    var phase = ({ g: 'Vapour', l: 'Liquid', s: 'Solid' })[s.phase] || s.phase || 'n/a';
    box.innerHTML = '<div class="detail-head"><div><h3>' + esc(s.id) + ' ' + esc(s.name) + '</h3><span class="small">' + endLabel(d, s.from) + ' to ' + endLabel(d, s.to) + '</span></div>' +
      '<button type="button" class="close-x" data-close aria-label="Close details">' + ICON.close + '</button></div>' +
      '<div class="stats">' + stat('Temperature', finite(s.T_C) ? num(s.T_C, 0) : 'n/a', '\u00b0C') + stat('Pressure', num(s.P_bar), 'bar') + stat('Phase', esc(phase)) +
      stat('Total mass', num(s.kg_h, 0), 'kg/h') + stat('Total molar', num(s.kmol_h), 'kmol/h') + stat('Components', String(comps.length)) + '</div>' +
      (comps.length ? tableWrap('<table class="t"><thead><tr><th class="sticky">Component</th><th class="r">kg/h</th><th class="r">kmol/h</th><th class="r">Mass %</th><th class="r">Mol %</th></tr></thead><tbody>' +
        comps.map(function (x) {
          var c = x[1];
          return '<tr><th class="sticky" scope="row">' + chem(x[0]) + '<span class="sub">' + esc(compName(d, x[0]) !== x[0] ? compName(d, x[0]) : '') + '</span></th><td class="r">' + num(c.kg_h, Math.abs(c.kg_h) >= 100 ? 0 : 2) + '</td><td class="r">' + num(c.kmol_h) +
            '</td><td class="r">' + BP.num((c.mass_frac || 0) * 100, 2) + '</td><td class="r">' + BP.num((c.mol_frac || 0) * 100, 2) + '</td></tr>';
        }).join('') + '</tbody></table>') : '');
    box.hidden = false;
    if (scroll) revealDetail(box);
  }

  function showUnit(id, scroll) {
    var d = state.data, u = unitById(d, id), box = $('#pfd-detail');
    if (!u || !box) return;
    document.querySelectorAll('svg.pfd .sel').forEach(function (n) { n.classList.remove('sel'); });
    var g = document.querySelector('svg.pfd [data-unit="' + CSS.escape(id) + '"]'); if (g) g.classList.add('sel');
    var ins = arr(d.streams).filter(function (s) { return s.to === id; }), outs = arr(d.streams).filter(function (s) { return s.from === id; });
    var btns = function (l) { return l.length ? l.map(function (s) { return '<button type="button" class="chip" data-stream="' + esc(s.id) + '">' + esc(s.id) + ' ' + esc(s.name) + '</button>'; }).join('') : '<span class="muted small">None shown</span>'; };
    box.innerHTML = '<div class="detail-head"><div><h3>' + esc(u.id) + ' ' + esc(u.name) + '</h3><span class="small">' + esc(u.kind ? u.kind.charAt(0).toUpperCase() + u.kind.slice(1) : '') + '</span></div>' +
      '<button type="button" class="close-x" data-close aria-label="Close details">' + ICON.close + '</button></div>' +
      (u.desc ? '<p style="color:var(--ink-2);font-size:0.9375rem">' + chem(u.desc) + '</p>' : '') +
      '<div class="stats">' + stat('Heat duty', finite(u.duty_kW) ? num(u.duty_kW) : 'n/a', finite(u.duty_kW) ? 'kW' : '') + stat('Shaft power', finite(u.power_kW) ? num(u.power_kW) : 'n/a', finite(u.power_kW) ? 'kW' : '') + '</div>' +
      '<div class="sub-h" style="margin-top:var(--s4)"><h3>Streams in</h3></div><div class="chips">' + btns(ins) + '</div>' +
      '<div class="sub-h" style="margin-top:var(--s4)"><h3>Streams out</h3></div><div class="chips">' + btns(outs) + '</div>';
    box.hidden = false;
    if (scroll) revealDetail(box);
  }

  function revealDetail(box) {
    var r = box.getBoundingClientRect();
    if (r.top > window.innerHeight - 120 || r.top < 110) {
      box.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
    }
  }

  function bindFlow() {
    var sc = $('#pfd-scroll'); if (!sc) return;
    initialZoom();
    var card = sc.closest('.pfd-card');
    card.addEventListener('click', function (e) {
      var z = e.target.closest('[data-zoom]');
      if (z) { var v = z.getAttribute('data-zoom'); setZoom(v === 'fit' ? 'fit' : pfd.zoom * (v === '1' ? 1.25 : 0.8)); return; }
      if (e.target.closest('[data-close]')) { $('#pfd-detail').hidden = true; document.querySelectorAll('svg.pfd .sel').forEach(function (n) { n.classList.remove('sel'); }); return; }
      if (moved) return;
      var st = e.target.closest('[data-stream]'); if (st) { showStream(st.getAttribute('data-stream'), true); return; }
      var un = e.target.closest('[data-unit]'); if (un) showUnit(un.getAttribute('data-unit'), true);
    });
    sc.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var st = e.target.closest('[data-stream]'), un = e.target.closest('[data-unit]');
      if (st) { e.preventDefault(); showStream(st.getAttribute('data-stream'), true); }
      else if (un) { e.preventDefault(); showUnit(un.getAttribute('data-unit'), true); }
    });
    // mouse drag to pan (touch uses native scrolling)
    var drag = null, moved = false;
    sc.addEventListener('pointerdown', function (e) {
      if (e.pointerType !== 'mouse' || e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY, l: sc.scrollLeft, t: sc.scrollTop }; moved = false;
    });
    window.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!moved && Math.hypot(dx, dy) > 4) { moved = true; sc.classList.add('dragging'); }
      if (moved) { sc.scrollLeft = drag.l - dx; sc.scrollTop = drag.t - dy; }
    });
    window.addEventListener('pointerup', function () { if (drag) { drag = null; sc.classList.remove('dragging'); setTimeout(function () { moved = false; }, 0); } });
  }

  /* ================================================================ render all */

  var RENDER = { overview: secOverview, flow: secFlow, balance: secBalance, kit: secKit, costs: secCosts, hazards: secHazards, carbon: secCarbon, validation: secValidation, assumptions: secAssumptions };

  function render(d) {
    state.data = d;
    Object.keys(RENDER).forEach(function (k) {
      var el = document.querySelector('[data-sec="' + k + '"]');
      if (!el) return;
      try { el.innerHTML = RENDER[k](d); }
      catch (e) { el.innerHTML = '<p class="muted">This section could not be shown for this design.</p>'; if (window.console) console.error(k, e); }
    });
    bindFlow();
    var cap = obj(d.capacity).t_per_day;
    $('#d-title').textContent = d.title || cfg.label;
    $('#d-summary').innerHTML = chem(d.summary || '');
    $('#m-region').textContent = d.region_label || state.region;
    $('#m-cap').textContent = num(cap) + ' t/d';
    var v = arr(d.validation), np = v.filter(function (x) { return x.pass; }).length;
    var mv = $('#m-val');
    mv.className = 'pill' + (v.length && np === v.length ? ' pill-pass' : '');
    mv.innerHTML = '<span class="dot"></span>' + np + ' of ' + v.length + ' checks pass';
    updatePdfButton();
  }

  /* ================================================================ data loading */

  function loadDefault(region) {
    if (state.defaultCache[region]) return Promise.resolve(state.defaultCache[region]);
    return fetch(ROOT + 'data/' + cfg.id + '.' + region + '.json').then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (j) { state.defaultCache[region] = j; return j; });
  }

  function setRegionButtons() {
    document.querySelectorAll('[data-region]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-region') === state.region)); });
  }

  function switchRegion(region) {
    if (region === state.region && state.data) return;
    state.region = region;
    setRegionButtons();
    if (state.custom) { runCustom(state.custom.capacity, state.custom.params); return; }
    loadDefault(region).then(function (d) { render(d); syncUrl(); })
      .catch(function () { status('error', 'Could not load the ' + esc(region) + ' design. Check your connection and try again.'); });
  }

  /* ================================================================ status, url */

  function status(kind, html, action) {
    var el = $('#status');
    if (!kind) { el.className = 'status-bar'; el.innerHTML = ''; return; }
    el.className = 'status-bar show' + (kind === 'custom' ? ' custom' : kind === 'error' ? ' error' : '');
    el.innerHTML = (kind === 'busy' ? '<span class="spinner" aria-hidden="true"></span>' : '') + '<span class="grow">' + html + '</span>' + (action || '');
  }

  function syncUrl() {
    var q = new URLSearchParams();
    if (state.region !== cfg.default_region) q.set('region', state.region);
    if (state.custom) {
      q.set('capacity', String(state.custom.capacity));
      Object.keys(state.custom.params).forEach(function (k) {
        var m = paramMeta(k); if (m && !same(state.custom.params[k], m.default)) q.set(k, String(state.custom.params[k]));
      });
    }
    var s = q.toString();
    history.replaceState(null, '', location.pathname + (s ? '?' + s : '') + location.hash);
  }

  /* ================================================================ inputs */

  function paramMeta(k) { return cfg.params.filter(function (p) { return p.key === k; })[0]; }
  function same(a, b) {
    if (typeof a === 'boolean' || typeof b === 'boolean') return a === b;
    return Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(b));
  }
  function shortNum(v) { return typeof v === 'number' ? String(+v.toPrecision(6)) : String(v); }

  function buildInputs() {
    var grid = $('#inputs-grid');
    var html = field('capacity', 'Capacity', 't/d', cfg.default_tpd, cfg.cap_min, cfg.cap_max, 'any', 'number');
    cfg.params.forEach(function (p) {
      if (p.kind === 'bool') {
        html += '<div class="field"><label for="in-' + p.key + '">' + p.label_html + '</label>' +
          '<span class="seg seg-sm" role="group" aria-label="' + esc(p.label) + '" data-bool="' + p.key + '" id="in-' + p.key + '">' +
          '<button type="button" data-val="true" aria-pressed="' + (p.default === true) + '">On</button><button type="button" data-val="false" aria-pressed="' + (p.default === false) + '">Off</button></span><span class="err"></span></div>';
      } else html += field(p.key, p.label_html, p.unit, p.default, p.min, p.max, p.step, p.kind);
    });
    grid.innerHTML = html;
    grid.addEventListener('click', function (e) {
      var b = e.target.closest('[data-bool] button'); if (!b) return;
      b.parentNode.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
    });
  }

  function field(key, label, unit, def, min, max, step, kind) {
    var u = unit === 'fraction' ? '' : unit;
    return '<div class="field"><label for="in-' + key + '">' + label + (u ? ', ' + esc(u) : '') + '</label>' +
      '<input class="input" id="in-' + key + '" name="' + key + '" type="number" inputmode="decimal" step="' + step + '" min="' + min + '" max="' + max + '" value="' + shortNum(def) + '" data-kind="' + kind + '" aria-describedby="h-' + key + '">' +
      '<span class="hint" id="h-' + key + '">' + shortNum(min) + ' to ' + shortNum(max) + '</span><span class="err" aria-live="polite"></span></div>';
  }

  function readInputs() {
    var ok = true, capacity, params = {};
    function check(el, min, max, isInt) {
      var v = el.value.trim() === '' ? NaN : +el.value, err = el.parentNode.querySelector('.err'), msg = '';
      if (!isFinite(v)) msg = 'Enter a number.';
      else if (v < min || v > max) msg = 'Use ' + shortNum(min) + ' to ' + shortNum(max) + '.';
      else if (isInt && Math.round(v) !== v) msg = 'Use a whole number.';
      if (msg) { el.setAttribute('aria-invalid', 'true'); err.textContent = msg; ok = false; }
      else { el.removeAttribute('aria-invalid'); err.textContent = ''; }
      return v;
    }
    capacity = check($('#in-capacity'), cfg.cap_min, cfg.cap_max, false);
    cfg.params.forEach(function (p) {
      if (p.kind === 'bool') {
        var on = document.querySelector('[data-bool="' + p.key + '"] [aria-pressed="true"]');
        params[p.key] = on ? on.getAttribute('data-val') === 'true' : p.default;
      } else {
        var v = check(document.getElementById('in-' + p.key), p.min, p.max, p.kind === 'int');
        params[p.key] = same(v, p.default) ? p.default : v;
      }
    });
    if (same(capacity, cfg.default_tpd)) capacity = cfg.default_tpd;
    return ok ? { capacity: capacity, params: params } : null;
  }

  function setInputs(capacity, params) {
    $('#in-capacity').value = shortNum(capacity);
    cfg.params.forEach(function (p) {
      var v = params && p.key in params ? params[p.key] : p.default;
      if (p.kind === 'bool') {
        document.querySelectorAll('[data-bool="' + p.key + '"] button').forEach(function (b) { b.setAttribute('aria-pressed', String((b.getAttribute('data-val') === 'true') === v)); });
      } else document.getElementById('in-' + p.key).value = shortNum(v);
    });
    document.querySelectorAll('#inputs-grid [aria-invalid]').forEach(function (el) { el.removeAttribute('aria-invalid'); el.parentNode.querySelector('.err').textContent = ''; });
  }

  function isDefault(inp) {
    if (!same(inp.capacity, cfg.default_tpd)) return false;
    return cfg.params.every(function (p) { return same(inp.params[p.key], p.default); });
  }

  function toggleInputs(open) {
    var panel = $('#inputs'), btn = $('#btn-inputs');
    var show = open == null ? panel.hidden : open;
    panel.hidden = !show;
    btn.setAttribute('aria-expanded', String(show));
    if (show) { var f = $('#in-capacity'); if (f) f.focus({ preventScroll: true }); }
  }

  /* ================================================================ worker */

  var worker = null, jobId = 0, jobs = {}, busy = false;

  function getWorker() {
    if (worker) return worker;
    worker = new Worker(ROOT + 'js/engine-worker.js', { type: 'module' });
    worker.onmessage = function (ev) {
      var m = ev.data, j = jobs[m.id]; if (!j) return;
      if (m.type === 'progress') j.progress(m.step);
      else if (m.type === 'error') { delete jobs[m.id]; j.reject(m); }
      else { delete jobs[m.id]; j.resolve(m); }
    };
    worker.onerror = function (e) {
      Object.keys(jobs).forEach(function (k) { jobs[k].reject({ message: e.message || 'The engine stopped unexpectedly.' }); delete jobs[k]; });
      worker = null;
    };
    return worker;
  }

  function call(msg, progress) {
    return new Promise(function (resolve, reject) {
      var id = ++jobId;
      jobs[id] = { resolve: resolve, reject: reject, progress: progress || function () {} };
      msg.id = id;
      getWorker().postMessage(msg);
    });
  }

  function setSteps(step) {
    var order = ['python', 'engine', 'solve'], idx = order.indexOf(step);
    document.querySelectorAll('#progress [data-step]').forEach(function (li) {
      var i = order.indexOf(li.getAttribute('data-step'));
      li.className = i < idx ? 'done' : i === idx ? 'active' : '';
    });
  }

  var STEP_TEXT = { python: 'Loading Python in your browser', engine: 'Loading the Blueprint engine', solve: 'Solving the flowsheet', pdf: 'Building the PDF' };

  function runCustom(capacity, params) {
    if (busy) return;
    if (isDefault({ capacity: capacity, params: params })) {
      state.custom = null;
      status(null);
      loadDefault(state.region).then(function (d) { render(d); syncUrl(); });
      return;
    }
    busy = true;
    var runBtn = $('#btn-run'); runBtn.disabled = true;
    $('#progress').hidden = false;
    var t0 = performance.now();
    status('busy', STEP_TEXT.python + '\u2026');
    call({ type: 'run', pid: cfg.id, capacity: capacity, region: state.region, params: params }, function (step) {
      setSteps(step);
      status('busy', (STEP_TEXT[step] || 'Working') + '\u2026');
    }).then(function (m) {
      var d = JSON.parse(m.json);
      state.custom = { capacity: capacity, params: params };
      state.pending = null;
      render(d);
      syncUrl();
      setSteps('done');
      var secs = ((performance.now() - t0) / 1000).toFixed(1);
      status('custom', '<strong>Custom design</strong> at ' + num(capacity) + ' t/d, ' + esc(d.region_label || state.region) + '. Solved in your browser in ' + secs + ' s.',
        '<button type="button" class="btn btn-secondary btn-sm" id="btn-back">Back to default</button>');
    }).catch(function (e) {
      var msg = String(e.message || '');
      if (msg.indexOf('NET: ') === 0) status('error', '<strong>The engine could not start.</strong> ' + esc(msg.slice(5)));
      else status('error', '<strong>The engine could not solve this case.</strong> ' + esc(msg) + ' Try values closer to the defaults.');
      if (window.console && e.detail) console.warn(e.detail);
    }).then(function () {
      busy = false; runBtn.disabled = false; $('#progress').hidden = true;
    });
  }

  /* ================================================================ PDF */

  function pdfName() {
    var cap = obj(state.data && state.data.capacity).t_per_day;
    return cfg.id + '-' + String(Math.round(cap * 100) / 100) + 'tpd-' + state.region + '.pdf';
  }

  function updatePdfButton() {
    var a = $('#btn-pdf');
    if (!state.custom && cfg.pdfs.indexOf(state.region) >= 0) {
      a.setAttribute('href', ROOT + 'pdf/' + cfg.id + '.' + state.region + '.pdf');
      a.setAttribute('download', pdfName());
      a.dataset.mode = 'static';
    } else {
      a.setAttribute('href', '#');
      a.removeAttribute('download');
      a.dataset.mode = 'build';
    }
  }

  function buildPdf() {
    if (busy || !state.data) return;
    busy = true;
    var a = $('#btn-pdf'); a.setAttribute('aria-disabled', 'true');
    status('busy', STEP_TEXT.pdf + '. The first PDF downloads the PDF library, so it can take a little while\u2026');
    call({ type: 'pdf', data: JSON.stringify(state.data) }, function (step) {
      if (step !== 'pdf') status('busy', (STEP_TEXT[step] || 'Working') + '\u2026');
    }).then(function (m) {
      var blob = new Blob([m.bytes], { type: 'application/pdf' });
      var url = URL.createObjectURL(blob), tmp = document.createElement('a');
      tmp.href = url; tmp.download = pdfName();
      document.body.appendChild(tmp); tmp.click(); tmp.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
      status(state.custom ? 'custom' : null, state.custom ? '<strong>Custom design</strong> at ' + num(state.custom.capacity) + ' t/d. PDF downloaded as ' + esc(pdfName()) + '.' : '',
        state.custom ? '<button type="button" class="btn btn-secondary btn-sm" id="btn-back">Back to default</button>' : '');
    }).catch(function (e) {
      status('error', '<strong>The PDF could not be built.</strong> ' + esc(String(e.message || '').replace(/^NET: /, '')) + ' Please try again.');
    }).then(function () { busy = false; a.removeAttribute('aria-disabled'); });
  }

  /* ================================================================ section nav */

  function initSecNav() {
    var links = Array.prototype.slice.call(document.querySelectorAll('.secnav a'));
    var list = $('.secnav ul');
    var current = null;
    function activate(id) {
      if (id === current) return; current = id;
      links.forEach(function (a) {
        var on = a.getAttribute('href') === '#' + id;
        a.classList.toggle('active', on);
        if (on) {
          a.setAttribute('aria-current', 'true');
          var l = a.offsetLeft - 20, r = a.offsetLeft + a.offsetWidth + 20;
          if (l < list.scrollLeft || r > list.scrollLeft + list.clientWidth) list.scrollTo({ left: l, behavior: 'auto' });
        } else a.removeAttribute('aria-current');
      });
    }
    var secs = links.map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); }).filter(Boolean);
    function onScroll() {
      var y = 140, id = secs[0] && secs[0].id;
      secs.forEach(function (s) { if (s.getBoundingClientRect().top <= y) id = s.id; });
      activate(id);
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ================================================================ boot */

  function boot() {
    buildInputs();
    initSecNav();
    var q = new URLSearchParams(location.search);
    var reg = q.get('region');
    if (reg && cfg.regions[reg]) state.region = reg;
    setRegionButtons();
    var capQ = q.get('capacity');
    var params = {}, any = false;
    cfg.params.forEach(function (p) {
      var raw = q.get(p.key);
      if (raw == null) { params[p.key] = p.default; return; }
      any = true;
      params[p.key] = p.kind === 'bool' ? raw === 'true' : +raw;
    });
    var capacity = capQ != null && isFinite(+capQ) ? +capQ : cfg.default_tpd;
    if (capQ != null) any = true;

    loadDefault(state.region).then(function (d) {
      render(d);
      if (any && !isDefault({ capacity: capacity, params: params })) {
        setInputs(capacity, params);
        toggleInputs(true);
        state.pending = { capacity: capacity, params: params };
        status('custom', 'This link holds a custom case at ' + num(capacity) + ' t/d. The default design is shown until you run it.',
          '<button type="button" class="btn btn-primary btn-sm" id="btn-run-link">Run this case</button>');
      }
      if (location.hash) { var t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
    }).catch(function () {
      status('error', 'Could not load the design data. Check your connection and reload the page.');
    });

    document.querySelectorAll('[data-region]').forEach(function (b) {
      b.addEventListener('click', function () { if (!busy) switchRegion(b.getAttribute('data-region')); });
    });
    $('#btn-inputs').addEventListener('click', function () { toggleInputs(); });
    $('#inputs-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var inp = readInputs();
      if (!inp) { var bad = $('#inputs-grid [aria-invalid="true"]'); if (bad) bad.focus(); return; }
      runCustom(inp.capacity, inp.params);
    });
    $('#btn-reset').addEventListener('click', function () {
      setInputs(cfg.default_tpd, null);
      if (state.custom) { state.custom = null; status(null); loadDefault(state.region).then(function (d) { render(d); syncUrl(); }); }
      else { status(null); syncUrl(); }
    });
    $('#status').addEventListener('click', function (e) {
      if (e.target.closest('#btn-back')) {
        state.custom = null; setInputs(cfg.default_tpd, null); status(null);
        loadDefault(state.region).then(function (d) { render(d); syncUrl(); });
      }
      if (e.target.closest('#btn-run-link') && state.pending) runCustom(state.pending.capacity, state.pending.params);
    });
    $('#btn-pdf').addEventListener('click', function (e) {
      if (this.dataset.mode === 'build') { e.preventDefault(); buildPdf(); }
    });
    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-basis]');
      if (b) { state.unit = b.getAttribute('data-basis'); document.querySelectorAll('[data-basis]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); }); $('#stream-table').innerHTML = streamTable(state.data); return; }
      var st = e.target.closest('.stream-table [data-stream], .other-streams [data-stream], #pfd-detail [data-stream]');
      if (st) {
        var id = st.getAttribute('data-stream');
        if (st.closest('.stream-table')) { document.getElementById('flow').scrollIntoView({ behavior: 'auto' }); }
        showStream(id, !st.closest('.stream-table'));
      }
    });
    var rt;
    window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { if ($('#pfd-scroll')) setZoom(pfd.zoom); }, 150); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
