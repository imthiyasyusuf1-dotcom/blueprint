"""Build the Blueprint static website in site/.

Reads site/data/index.json and the per design JSON files, writes every HTML page,
copies the engine into site/py/ for Pyodide, and writes sitemap.xml, robots.txt,
favicons and the Open Graph image. Standard library only, plus Pillow (optional)
for the PNG images. Idempotent; run with no arguments:

    unset PYTHONPATH; ~/.venvs/blueprint/bin/python tools/build_site.py
"""
import html
import json
import math
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(SITE, "data")
SITE_URL = "https://imthiyasyusuf1-dotcom.github.io/blueprint/"
BASE_PATH = "/" + SITE_URL.split("://", 1)[1].split("/", 1)[1]  # "/blueprint/"
SITE_NAME = "Blueprint"
DEFAULT_REGION = "US"
TWITTER = ""

ACCENT = "#2347F5"
INK = "#0B1220"

# ------------------------------------------------------------------------------------- helpers

def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def load(path):
    with open(path) as f:
        return json.load(f)


def write(rel, text, mode="w"):
    path = os.path.join(SITE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if "b" in mode:
        with open(path, mode) as f:
            f.write(text)
    else:
        with open(path, mode, encoding="utf-8") as f:
            f.write(text)
    return path


def fmt_usd(v):
    """USD with M or k, the same rules as site/js/common.js fmtUSD."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    sign = "\u2212" if v < 0 else ""
    a = abs(v)
    if a >= 1e6:
        x = a / 1e6
        d = 0 if x >= 100 else (1 if x >= 10 else 2)
        return "{}${:,.{}f}M".format(sign, x, d)
    if a >= 1e3:
        x = a / 1e3
        d = 0 if x >= 100 else (1 if x >= 10 else 2)
        return "{}${:,.{}f}k".format(sign, x, d)
    d = 0 if a >= 100 else (1 if a >= 10 else 2)
    return "{}${:,.{}f}".format(sign, a, d)


def fmt_num(v):
    if v is None:
        return "n/a"
    a = abs(v)
    d = 0 if a >= 100 or a == 0 else (1 if a >= 10 else (2 if a >= 1 else 3))
    return "{:,.{}f}".format(v, d)


def chem(s):
    """Subscript digits in formula like tokens (CO2 -> CO<sub>2</sub>)."""
    return re.sub(r"(?<=[A-Za-z\)])(\d+)", r"<sub>\1</sub>", esc(s))


def short_route(title):
    m = re.search(r"\(([^)]*)\)", title or "")
    return m.group(1)[:1].upper() + m.group(1)[1:] if m else ""


# --------------------------------------------------------------------- input parameter labels
LABEL_OVERRIDES = {
    "steam_to_carbon": "Steam to carbon ratio",
    "primary_T_C": "Primary reformer outlet temperature",
    "reform_P_bar": "Reforming pressure",
    "reformer_P_bar": "Reformer pressure",
    "reformer_T_C": "Reformer outlet temperature",
    "converter_out_C": "Converter outlet temperature",
    "converter_T_C": "Converter temperature",
    "approach_C": "Approach to equilibrium",
    "inerts_loop_pct": "Inerts in converter feed",
    "separator_C": "Ammonia separator temperature",
    "furnace_eff": "Furnace efficiency",
    "hts_in_C": "HT shift inlet temperature",
    "acid_wt_pct": "Acid strength",
    "tail_O2_pct": "Tail gas O2",
    "tail_NOx_ppm": "Tail gas NOx",
    "nc_ratio": "N/C ratio",
    "hc_ratio": "H/C ratio",
    "reaction_h": "Reaction time",
    "residence_h": "Residence time",
    "anhydride_excess": "Acetic anhydride excess",
    "first_crop": "First crop yield",
    "cake_liquor_frac": "Liquor retained in cake",
    "methanol_ratio": "Methanol to oil molar ratio",
    "meoh_in_ester_phase": "Methanol into the ester phase",
    "meoh_recovery": "Methanol recovery",
    "storage_days": "Product storage",
    "starch_dry": "Starch, dry basis",
    "sugars_dry": "Sugars, dry basis",
    "backset_frac": "Backset fraction",
    "beer_overhead_wt": "Beer column overhead ethanol",
    "rectifier_wt": "Rectifier overhead ethanol",
    "sieve_regen_frac": "Sieve regeneration fraction",
    "thin_stillage_solids_split": "Thin stillage solids split",
    "ddgs_moisture": "DDGS moisture",
    "per_pass_conversion": "Conversion per pass",
    "y_C2H4": "Ethylene in reactor feed",
    "y_O2": "Oxygen in reactor feed",
    "y_CO2": "CO2 in reactor feed",
    "y_Ar": "Argon in reactor feed",
    "o2_purity": "Oxygen purity",
    "asu_o2_recovery": "ASU oxygen recovery",
    "rich_water_eo_wt": "EO in rich absorbent",
    "sel_styrene": "Selectivity to styrene",
    "sel_benzene": "Selectivity to benzene",
    "steam_oil_wt": "Steam to ethylbenzene ratio",
    "rectifier_reflux": "Rectifier reflux ratio",
    "refining_reflux": "Refining reflux ratio",
    "splitter_reflux": "Splitter reflux ratio",
    "evaporator_effects": "Evaporator effects",
    "co2_conversion_pct": "CO2 conversion",
    "stripper_eff_pct": "Stripper efficiency",
}
# Units that a key suffix alone cannot express. Checked before the generic suffix rules.
UNIT_OVERRIDES = {
    "naoh_wt_oil": ("NaOH catalyst", "kg/kg oil"),
    "diluent_kg_per_kg_sa": ("Diluent", "kg/kg SA"),
    "wash_water_kg_per_kg": ("Wash water", "kg/kg"),
    "stripping_steam_kg_kg": ("Stripping steam", "kg/kg"),
    "co2_regen_GJ_t": ("CO2 regeneration heat", "GJ/t CO2"),
    "dryer_kJ_per_kg_water": ("Dryer heat", "kJ/kg water"),
    "ghsv_h": ("Gas hourly space velocity", "1/h"),
    "lhsv_h": ("Liquid hourly space velocity", "1/h"),
    "steam_oil_wt": ("Steam to ethylbenzene ratio", "kg/kg"),
    "storage_days": ("Product storage", "days"),
}
TOKEN_WORDS = {
    "eff": "efficiency", "nh3": "NH3", "co2": "CO2", "so2": "SO2", "o2": "O2", "h2": "H2", "nox": "NOx",
    "no": "NO", "psa": "PSA", "hts": "HT shift", "lts": "LT shift", "bfw": "BFW", "ch4": "CH4", "kj": "kJ",
    "nc": "N/C", "hc": "H/C", "dp": "pressure drop", "t": "temperature", "p": "pressure", "per": "per",
    "bed4": "bed 4", "sa": "SA", "naoh": "NaOH", "meoh": "methanol", "eo": "EO", "asu": "ASU", "ddgs": "DDGS",
    "frac": "fraction", "sel": "selectivity", "ghsv": "GHSV", "lhsv": "LHSV", "c2h4": "C2H4", "ar": "Ar",
}
UNIT_SUFFIX = {"C": "\u00b0C", "bar": "bar", "pct": "%", "tpd": "t/d", "ppm": "ppm", "h": "h", "kW": "kW", "K": "K"}


def param_meta(key, default):
    parts = key.split("_")
    unit = ""
    if key in UNIT_OVERRIDES:
        label, unit = UNIT_OVERRIDES[key]
        parts = []
    elif len(parts) > 1 and parts[-1] in UNIT_SUFFIX:
        unit = UNIT_SUFFIX[parts[-1]]
        parts = parts[:-1]
    if key in UNIT_OVERRIDES:
        pass
    elif key in LABEL_OVERRIDES:
        label = LABEL_OVERRIDES[key]
    else:
        lead, tail = [], []
        for p in parts:
            w = TOKEN_WORDS.get(p.lower(), p)
            if p in ("T", "P", "dP"):
                tail.append(TOKEN_WORDS[p.lower()])
            elif p == "wt":
                continue
            else:
                lead.append(w)
        words = lead + tail
        if unit == "\u00b0C" and "temperature" not in words:
            words.append("temperature")
        label = " ".join(words).strip() or key
        label = label[:1].upper() + label[1:]
    if key.endswith("wt_pct"):
        unit = "wt%"
    kind = "number"
    step = "any"
    if isinstance(default, bool):
        return {"key": key, "label": label, "unit": "", "kind": "bool", "default": default}
    d = float(default)
    if isinstance(default, int):
        lo, hi, step, kind = max(1, math.floor(d / 2)), max(2, d * 2), 1, "int"
    elif unit == "\u00b0C" and ("approach" in key or key.lower().startswith(("dt", "delta"))):
        lo, hi = 0.0, max(50.0, d * 4)  # temperature differences cannot go negative
    elif unit == "\u00b0C":
        span = max(50.0, 0.2 * abs(d))
        lo, hi = max(-200.0, d - span), d + span
    elif unit in ("%", "wt%"):
        lo, hi = (max(0.0, d * 0.5), min(100.0, d * 1.5)) if d > 0 else (0.0, 100.0)
    elif unit == "ppm":
        lo, hi = 0.0, max(10.0, d * 4)
    elif unit == "h":
        lo, hi = d * 0.25, d * 4
    elif 0 < d < 1 and not unit and "ratio" not in key:
        lo, hi = max(0.001, d * 0.5), min(1.0, d * 1.5)
        unit = "fraction"
    elif d > 0:
        lo, hi = d * 0.5, d * 2
    elif d < 0:
        lo, hi = d * 2, d * 0.5
    else:
        lo, hi = -100.0, 100.0
    rnd = lambda x: float("{:.4g}".format(x))  # noqa: E731
    return {"key": key, "label": label, "unit": unit, "kind": kind, "default": default,
            "min": rnd(lo), "max": rnd(hi), "step": step}


def param_defaults(proc):
    params = proc.get("params")
    if params:
        return params
    try:  # older index.json files only carry params for some processes
        sys.path.insert(0, ROOT)
        from engine import registry  # noqa: WPS433
        return registry.defaults(proc["id"])
    except Exception as exc:  # noqa: BLE001
        print("  no params for {}: {}".format(proc["id"], exc))
        return {}


# ---------------------------------------------------------------------------------- icons
ICON = {
    "search": '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="9" cy="9" r="6" stroke="currentColor" stroke-width="1.75"/><path d="m13.5 13.5 3.5 3.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/></svg>',
    "arrow": '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10m0 0L9 4m4 4-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "download": '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 2.5v8m0 0L4.75 7.25M8 10.5l3.25-3.25M2.75 13.25h10.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "sliders": '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2.5 4.5h6m3 0h2m-11 7h2m3 0h6M8.5 3v3m-3 4v3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    "check": '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.6"/><path d="m6.5 10.2 2.3 2.3 4.7-4.9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "info": '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.6"/><path d="M10 9v5m0-7.5v.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "flask": '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M8 2.75h4M8.75 2.75v5L4.2 15.1A1.5 1.5 0 0 0 5.5 17.25h9a1.5 1.5 0 0 0 1.3-2.15L11.25 7.75v-5M6.5 12.5h7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}

MARK = ('<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="{a}"/>'
        '<rect x="6.5" y="8.5" width="8" height="8" rx="1.5" fill="none" stroke="#fff" stroke-width="2"/>'
        '<path d="M14.5 12.5h4.5v7.5" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>'
        '<rect x="15" y="19" width="10.5" height="5.5" rx="1.5" fill="#fff"/></svg>').format(a=ACCENT)

FAVICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="{a}"/>'
               '<rect x="6.5" y="8.5" width="8" height="8" rx="1.5" fill="none" stroke="#fff" stroke-width="2"/>'
               '<path d="M14.5 12.5h4.5v7.5" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>'
               '<rect x="15" y="19" width="10.5" height="5.5" rx="1.5" fill="#fff"/></svg>\n').format(a=ACCENT)


# ---------------------------------------------------------------------------------- layout

def head(page, pre):
    url = SITE_URL + page["path"]
    title = page["title"]
    desc = page["desc"]
    og = SITE_URL + "assets/og.png"
    extra = page.get("head_extra", "")
    noindex = '<meta name="robots" content="noindex">\n' if page.get("noindex") else ""
    canon = "" if page.get("noindex") else '<link rel="canonical" href="{}">\n'.format(esc(url))
    return """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{desc}">
{noindex}{canon}<meta name="theme-color" content="#FCFCFD">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{site}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Blueprint: type a chemical, get a first pass plant design">
<meta property="og:locale" content="en_GB">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{og}">
<link rel="icon" href="{pre}assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="{pre}assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="{pre}assets/apple-touch-icon.png">
<link rel="preload" href="{pre}fonts/inter.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{pre}css/site.css">
{extra}</head>
""".format(title=esc(title), desc=esc(desc), url=esc(url), og=esc(og), site=SITE_NAME, pre=pre,
           extra=extra, noindex=noindex, canon=canon)


def header(pre, current=""):
    links = [("examples/", "Examples"), ("method/", "Method"), ("about/", "About")]
    nav = "".join('<a href="{p}{h}"{c}>{t}</a>'.format(p=pre, h=h, t=t, c=' aria-current="page"' if current == h else "")
                  for h, t in links)
    return """<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="{pre}" aria-label="Blueprint home">{mark}<span>Blueprint</span></a>
    <nav class="nav" aria-label="Main">{nav}</nav>
  </div>
</header>
""".format(pre=pre or "./", mark=MARK, nav=nav)


def footer(pre, scripts=()):
    sc = "".join('<script src="{}{}" defer></script>\n'.format(pre, s) for s in scripts)
    return """<footer class="site-footer">
  <div class="wrap">
    <div class="foot-top">
      <a class="brand" href="{home}" aria-label="Blueprint home">{mark}<span>Blueprint</span></a>
      <nav class="foot-links" aria-label="Footer">
        <a href="{pre}examples/">Examples</a>
        <a href="{pre}method/">Method</a>
        <a href="{pre}about/">About</a>
        <a href="{pre}privacy/">Privacy</a>
      </nav>
    </div>
    <div class="foot-fine">
      <span>Screening tool, not for construction.</span>
      <span>Founded and built by Yusuf Imthiyas.</span>
    </div>
  </div>
</footer>
{sc}</body>
</html>
""".format(pre=pre, home=pre or "./", mark=MARK, sc=sc)


def page_html(page, body, scripts=("js/config.js", "js/common.js"), current=""):
    pre = "../" * page["path"].count("/")
    return head(page, pre) + header(pre, current) + body + footer(pre, scripts)


# ---------------------------------------------------------------------------- shared blocks

def waitlist_block(heading="Hear when new processes go live",
                   text="One short email when a new chemical is added. Nothing else."):
    return """<div class="form-card" id="waitlist">
  <div class="section-head">
    <h2>{h}</h2>
    <p>{t}</p>
  </div>
  <form data-bp-form="waitlist" novalidate>
    <div class="form-body">
      <div class="form-row form-inline">
        <div class="field">
          <label for="wl-email">Email</label>
          <input class="input" id="wl-email" name="email" type="email" autocomplete="email" inputmode="email" placeholder="you@example.com" required>
          <span class="err" aria-live="polite"></span>
        </div>
        <button class="btn btn-primary" type="submit">Join the list</button>
      </div>
      <div class="hp" aria-hidden="true"><label for="wl-honey">Leave this empty</label><input id="wl-honey" name="_honey" type="text" tabindex="-1" autocomplete="off"></div>
      <p class="form-fine">Used only to reply and to announce new processes. See <a href="{{pre}}privacy/">privacy</a>.</p>
    </div>
    <div class="form-status" role="status" aria-live="polite"></div>
  </form>
</div>
""".format(h=esc(heading), t=esc(text))


def example_card(p, d, pre, heading="h3"):
    val = d.get("validation") or []
    npass = sum(1 for v in val if v.get("pass"))
    eco = d.get("economics") or {}
    cap = (d.get("capacity") or {}).get("t_per_day")
    route = short_route(d.get("title")) or (d.get("route") or "")[:60]
    pdf = "pdf/{}.{}.pdf".format(p["id"], DEFAULT_REGION)
    pdf_link = ""
    if os.path.exists(os.path.join(SITE, pdf)):
        pdf_link = ('<a class="btn btn-secondary btn-sm" href="{pre}{pdf}" download>{ic}Sample PDF<span class="sr-only"> for {lab}</span></a>'
                    .format(pre=pre, pdf=pdf, ic=ICON["download"], lab=esc(p["label"])))
    return """<article class="card ex-card">
  <div class="ex-top">
    <div>
      <{h}>{label}</{h}>
      <p class="ex-route">{route}</p>
    </div>
    <span class="pill {vcls}" title="Validation checks within tolerance"><span class="dot"></span>{npass} of {nval} checks</span>
  </div>
  <dl class="ex-stats">
    <div><dt>Capacity</dt><dd>{cap} t/d</dd></div>
    <div><dt>Fixed capital</dt><dd>{fci}</dd></div>
    <div><dt>Cost of manufacture</dt><dd>{cpt}/t</dd></div>
    <div><dt>Levelised cost</dt><dd>{lev}/t</dd></div>
  </dl>
  <div class="ex-actions">
    <a class="btn btn-primary btn-sm" href="{pre}design/{id}/">Open design<span class="sr-only"> for {label}</span></a>
    {pdf}
  </div>
</article>""".format(h=heading, label=esc(p["label"]), route=esc(route), npass=npass, nval=len(val),
                     vcls="pill-pass" if val and npass == len(val) else "", cap=fmt_num(cap),
                     fci=fmt_usd(eco.get("fci")), cpt=fmt_usd(eco.get("cost_per_tonne")),
                     lev=fmt_usd(eco.get("levelised_cost_per_tonne")), pre=pre, id=esc(p["id"]), pdf=pdf_link)


def catalog_json(index, built):
    procs = []
    for p in index.get("processes") or []:
        procs.append({"id": p["id"], "label": p["label"], "aliases": p.get("aliases") or [],
                      "default_tpd": p.get("default_tpd"), "live": p["id"] in built})
    cat = {"processes": procs, "coming_soon": index.get("coming_soon") or []}
    return '<script type="application/json" id="bp-catalog">{}</script>\n'.format(
        json.dumps(cat, separators=(",", ":")).replace("</", "<\\/"))


def search_block(built_procs, pre, idp="q", big=True):
    chips = "".join('<a class="chip" href="{pre}design/{id}/">{l}</a>'.format(pre=pre, id=esc(p["id"]), l=esc(p["label"]))
                    for p in built_procs)
    return """<form class="search" role="search" data-bp-search action="{pre}request/" autocomplete="off">
  <label class="sr-only" for="{idp}">Type a chemical</label>
  <div class="search-field">
    <div class="search-box">
      {ic}
      <input id="{idp}" name="q" type="text" placeholder="Type a chemical" spellcheck="false" autocapitalize="off"
        role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="{idp}-list">
      <button class="btn btn-primary" type="submit">Design</button>
    </div>
    <ul class="typeahead" id="{idp}-list" role="listbox" aria-label="Matches" hidden></ul>
  </div>
  <div class="search-meta"><span class="label">Live now</span>{chips}</div>
</form>
""".format(pre=pre, idp=idp, ic=ICON["search"], chips=chips)


# ------------------------------------------------------------------------------------ pages

def build_landing(index, built, designs):
    page = {"path": "", "title": "Blueprint: first pass chemical plant design from one word",
            "desc": "Type a chemical and get a first pass plant design: flow diagram, mass and energy balance, kit list, "
                    "capex and opex, hazards and carbon, checked against published plant figures. Free."}
    pre = ""
    procs = [p for p in index["processes"] if p["id"] in built]
    features = [
        ("Flow diagram", "Every unit and stream, with temperature, pressure and composition on tap."),
        ("Mass and energy balance", "Full stream table, closure and atom balance errors, utilities and their annual cost."),
        ("Kit list", "Each item sized and costed: type, size, material, pressure, purchased and bare module cost."),
        ("Capex and opex", "Fixed capital, cost of manufacture, NPV, IRR, payback and levelised cost per tonne."),
        ("Hazards", "GHS statements per substance, flammability limits, process hazard flags and a starter HAZOP."),
        ("Carbon", "Scope 1 and 2 emissions per tonne of product, plus the greener route worth looking at."),
        ("Validation", "Model results set against published plant figures, with the source and the error shown."),
        ("PDF report", "The whole design as a tidy report you can share, for the default case or your own inputs."),
    ]
    feat = "".join('<div class="feature"><div class="fnum">{:02d}</div><h3>{}</h3><p>{}</p></div>'.format(i + 1, esc(t), esc(x))
                   for i, (t, x) in enumerate(features))
    cards = "".join(example_card(p, designs[p["id"]], pre) for p in procs[:3])
    more = ""
    if len(procs) > 3:
        more = '<p style="margin:var(--s5) 0 0"><a class="btn btn-secondary" href="examples/">See all {} designs{}</a></p>'.format(len(procs), ICON["arrow"])
    ld = {"@context": "https://schema.org", "@type": "WebApplication", "name": "Blueprint", "url": SITE_URL,
          "applicationCategory": "EngineeringApplication", "operatingSystem": "Any",
          "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
          "creator": {"@type": "Person", "name": "Yusuf Imthiyas"}, "description": page["desc"]}
    page["head_extra"] = '<script type="application/ld+json">{}</script>\n'.format(json.dumps(ld))
    body = """<main id="main">
<section class="hero">
  <div class="wrap">
    <p class="eyebrow">Free first pass chemical plant design</p>
    <h1><span class="line">Type a chemical.</span> <span class="line">Get a plant design.</span></h1>
    <p class="lede">A first pass design you can check, from flow diagram to costs and carbon, measured against published plant figures.</p>
    {search}
  </div>
</section>
<section class="section">
  <div class="wrap">
    <div class="section-head">
      <h2>What you get</h2>
      <p>Eight sections for every design, worked out from first principles and costed with a recognised textbook method. Change the inputs and the engine solves again in your browser.</p>
    </div>
    <div class="features">{feat}</div>
  </div>
</section>
<section class="section">
  <div class="wrap">
    <div class="section-head">
      <h2>Example designs</h2>
      <p>Default cases at typical world scale capacity, US prices. Open one to explore every section, switch region or change the inputs.</p>
    </div>
    <div class="grid grid-3">{cards}</div>
    {more}
  </div>
</section>
<section class="section">
  <div class="wrap">
    {waitlist}
    <p class="disclaimer" style="margin-top:var(--s5)">Blueprint gives a factored, screening level estimate, typically within minus 30 to plus 50 percent. It is a starting point for study and scoping, not a basis for construction or investment.</p>
  </div>
</section>
</main>
""".format(search=search_block(procs, pre), feat=feat, cards=cards, more=more,
           waitlist=waitlist_block().replace("{pre}", pre))
    page["head_extra"] += catalog_json(index, built)
    write("index.html", page_html(page, body))
    return page


def design_config(p, regions, built_pdfs):
    params = param_defaults(p)
    meta = [param_meta(k, v) for k, v in params.items() if k != "capacity_tpd"]
    for m in meta:
        m["label_html"] = chem(m["label"])
    cap = p.get("default_tpd") or params.get("capacity_tpd")
    return {"id": p["id"], "label": p["label"], "default_tpd": cap,
            "cap_min": round(cap * 0.25, 4), "cap_max": round(cap * 4, 4),
            "params": meta, "regions": regions, "default_region": DEFAULT_REGION,
            "pdfs": built_pdfs}


SECTIONS = [
    ("overview", "Overview", "Route, conditions, reactions and the headline numbers."),
    ("flow", "Flow diagram", "Tap any stream or unit for its conditions and composition."),
    ("balance", "Mass and energy balance", "Every stream in kg/h, closure and atom balance errors, and utilities."),
    ("kit", "Kit list", "Major equipment, sized and costed with Turton bare module factors."),
    ("costs", "Capex and opex", "Fixed capital, cost of manufacture and returns over the plant life."),
    ("hazards", "Hazards", "Substance hazards, process hazard flags and a starter HAZOP."),
    ("carbon", "Carbon", "Scope 1 and 2 emissions per tonne of product."),
    ("validation", "Validation", "Model results against published plant figures."),
    ("assumptions", "Assumptions and notes", "What the model takes as given."),
]


def build_design(p, d, regions, built_pdfs):
    pid = p["id"]
    path = "design/{}/".format(pid)
    pre = "../../"
    cap = (d.get("capacity") or {}).get("t_per_day")
    title = "{} plant design: {} t/d | Blueprint".format(p["label"], fmt_num(cap))
    desc = ("First pass {} plant design at {} t/d: {} Flow diagram, mass and energy balance, kit list, "
            "capex, opex, hazards and carbon, validated against published figures.").format(
        p["label"].lower(), fmt_num(cap), (d.get("summary") or "").rstrip(".") + ".")
    page = {"path": path, "title": title, "desc": desc[:300]}
    cfg = design_config(p, regions, built_pdfs)
    page["head_extra"] = '<script type="application/json" id="bp-config">{}</script>\n'.format(
        json.dumps(cfg, separators=(",", ":")).replace("</", "<\\/"))
    val = d.get("validation") or []
    npass = sum(1 for v in val if v.get("pass"))
    region_btns = "".join('<button type="button" data-region="{k}" aria-pressed="{pr}" title="{lab}">{k}</button>'.format(
        k=esc(k), lab=esc(v), pr="true" if k == DEFAULT_REGION else "false") for k, v in regions.items())
    nav = "".join('<li><a href="#{}">{}</a></li>'.format(i, esc(t)) for i, t, _ in SECTIONS)
    secs = []
    for i, t, intro in SECTIONS:
        static = ""
        if i == "overview":
            static = '<p class="route">{}</p>'.format(esc(d.get("route")))
        secs.append("""<section class="dsec" id="{i}" aria-labelledby="{i}-h">
  <div class="wrap">
    <h2 id="{i}-h">{t}</h2>
    <p class="intro">{intro}</p>
    <div data-sec="{i}">{static}</div>
  </div>
</section>""".format(i=i, t=esc(t), intro=esc(intro), static=static))
    pdf_href = "{}pdf/{}.{}.pdf".format(pre, pid, DEFAULT_REGION)
    body = """<main id="main">
<div class="design-head">
  <div class="wrap">
    <nav class="crumbs" aria-label="Breadcrumb"><a href="{pre}">Home</a><span class="sep">/</span><a href="{pre}examples/">Designs</a><span class="sep">/</span><span aria-current="page">{label}</span></nav>
    <h1 id="d-title">{dtitle}</h1>
    <p class="lede" id="d-summary">{summary}</p>
    <div class="head-meta" id="d-meta">
      <span class="pill" id="m-region">{rlabel}</span>
      <span class="pill num" id="m-cap">{cap} t/d</span>
      <span class="pill {vcls}" id="m-val"><span class="dot"></span>{npass} of {nval} checks pass</span>
    </div>
    <div class="toolbar">
      <div class="seg" role="group" aria-label="Price region">{rbtns}</div>
      <span class="spacer"></span>
      <button class="btn btn-secondary" type="button" id="btn-inputs" aria-expanded="false" aria-controls="inputs">{ic_sl}Change inputs</button>
      <a class="btn btn-primary" id="btn-pdf" href="{pdf}" download>{ic_dl}Download PDF</a>
    </div>
    <div class="status-bar" id="status" role="status" aria-live="polite"></div>
    <div class="inputs" id="inputs" hidden>
      <form class="card" id="inputs-form" novalidate>
        <div class="inputs-grid" id="inputs-grid"></div>
        <div class="inputs-actions">
          <button class="btn btn-primary" type="submit" id="btn-run">Run design</button>
          <button class="btn btn-ghost" type="button" id="btn-reset">Reset to defaults</button>
          <span class="note">Runs the same Python engine in your browser. The first run downloads Python (about 10 MB) and takes 10 to 30 seconds.</span>
        </div>
        <div class="progress" id="progress" hidden>
          <ol class="steps"><li data-step="python">Loading Python</li><li data-step="engine">Loading engine</li><li data-step="solve">Solving</li></ol>
        </div>
      </form>
    </div>
  </div>
</div>
<nav class="secnav" aria-label="Sections"><div class="wrap"><ul>{nav}</ul></div></nav>
{secs}
</main>
""".format(pre=pre, label=esc(p["label"]), dtitle=esc(d.get("title")), summary=esc(d.get("summary")),
           rlabel=esc(d.get("region_label")), cap=fmt_num(cap), vcls="pill-pass" if val and npass == len(val) else "",
           npass=npass, nval=len(val), rbtns=region_btns, ic_sl=ICON["sliders"], ic_dl=ICON["download"], pdf=pdf_href,
           nav=nav, secs="\n".join(secs))
    write(path + "index.html", page_html(page, body, scripts=("js/config.js", "js/common.js", "js/design.js")))
    return page


def build_examples(index, built, designs):
    page = {"path": "examples/", "title": "Example plant designs | Blueprint",
            "desc": "Every live Blueprint design at its default capacity: capacity, fixed capital, cost per tonne and "
                    "validation against published plant figures, with a sample PDF report for each."}
    pre = "../"
    procs = [p for p in index["processes"] if p["id"] in built]
    cards = "".join(example_card(p, designs[p["id"]], pre, "h2") for p in procs)
    soon = [p["label"] for p in index["processes"] if p["id"] not in built]
    soon_html = ""
    if soon:
        soon_html = """<div class="block">
      <h2 style="font-size:1.25rem;margin-bottom:var(--s2)">In progress</h2>
      <p class="muted" style="margin:0">Modelled next. Join the list below to hear when each goes live.</p>
      <div class="soon-list">{}</div>
    </div>""".format("".join('<a class="pill" href="{pre}request/?q={q}">{l}</a>'.format(pre=pre, q=esc(l.lower()).replace(" ", "+"), l=esc(l)) for l in soon))
    body = """<main id="main">
<div class="page-head">
  <div class="wrap">
    <p class="eyebrow">Designs</p>
    <h1>Example plant designs</h1>
    <p class="lede">Every live process at its default capacity with US prices. Each design opens in full and can be re-run with your own inputs; the PDF is the same report you get for a custom case.</p>
  </div>
</div>
<div class="wrap">
  <div class="grid grid-3">{cards}</div>
  {soon}
</div>
<section class="section" style="margin-top:var(--s7)">
  <div class="wrap">{waitlist}</div>
</section>
</main>
""".format(cards=cards, soon=soon_html, waitlist=waitlist_block().replace("{pre}", pre))
    write("examples/index.html", page_html(page, body, current="examples/"))
    return page


def build_request(index, built):
    page = {"path": "request/", "title": "Request a chemical | Blueprint",
            "desc": "Ask for a chemical that Blueprint has not modelled yet. Requests decide what gets built next."}
    pre = "../"
    procs = [p for p in index["processes"] if p["id"] in built]
    page["head_extra"] = catalog_json(index, built)
    body = """<main id="main">
<div class="page-head">
  <div class="wrap narrow">
    <p class="eyebrow">Request</p>
    <h1 id="req-title">Request a chemical</h1>
    <p class="lede" id="req-lede">Tell us what you want designed. Requests decide what gets modelled next.</p>
  </div>
</div>
<div class="wrap narrow">
  <div class="req-state" id="req-state" hidden></div>
  <div class="form-card">
    <form data-bp-form="request" novalidate>
      <div class="form-body">
        <div class="form-grid">
          <div class="field">
            <label for="rq-email">Email</label>
            <input class="input" id="rq-email" name="email" type="email" autocomplete="email" inputmode="email" placeholder="you@example.com" required>
            <span class="err" aria-live="polite"></span>
          </div>
          <div class="field">
            <label for="rq-chem">Chemical</label>
            <input class="input" id="rq-chem" name="chemical" type="text" placeholder="For example, acetone" required>
            <span class="err" aria-live="polite"></span>
          </div>
          <div class="field">
            <label for="rq-cap">Capacity, t/d <span class="muted">(optional)</span></label>
            <input class="input" id="rq-cap" name="capacity_tpd" type="number" inputmode="decimal" min="0" step="any" placeholder="For example, 500">
            <span class="err" aria-live="polite"></span>
          </div>
          <div class="field span-2">
            <label for="rq-note">Note <span class="muted">(optional)</span></label>
            <textarea class="textarea" id="rq-note" name="note" rows="4" placeholder="Route, feedstock, region or what you need it for"></textarea>
          </div>
        </div>
        <div class="hp" aria-hidden="true"><label for="rq-honey">Leave this empty</label><input id="rq-honey" name="_honey" type="text" tabindex="-1" autocomplete="off"></div>
        <div style="margin-top:var(--s5)"><button class="btn btn-primary" type="submit">Send request</button></div>
        <p class="form-fine">Used only to reply and to announce new processes. See <a href="{pre}privacy/">privacy</a>.</p>
      </div>
      <div class="form-status" role="status" aria-live="polite"></div>
    </form>
  </div>
  <div class="block">
    <h2 style="font-size:1.25rem;margin-bottom:var(--s4)">Or try another chemical</h2>
    {search}
  </div>
</div>
</main>
""".format(pre=pre, search=search_block(procs, pre, idp="q2"))
    write("request/index.html", page_html(page, body))
    return page


def build_about():
    page = {"path": "about/", "title": "About | Blueprint",
            "desc": "Blueprint is a free tool that turns a chemical name into a first pass plant design. Founded and built by Yusuf Imthiyas."}
    body = """<main id="main">
<div class="page-head">
  <div class="wrap narrow">
    <p class="eyebrow">About</p>
    <h1>About Blueprint</h1>
    <p class="lede">Founded and built by Yusuf Imthiyas.</p>
  </div>
</div>
<div class="wrap narrow">
  <div class="prose">
    <h2>What it is</h2>
    <p>Blueprint is a free web tool. You type a chemical and it returns a first pass design for a plant that makes it: a flow diagram, a solved mass and energy balance, a sized and costed kit list, capital and operating cost, hazards, carbon footprint and a PDF report.</p>
    <p>Every number comes from a process model that solves the chemistry and the energy balance, a recognised costing method and sourced prices. Each design is then checked against published figures for real plants, and the result of that check is shown next to the design rather than hidden.</p>
    <h2>Who it is for</h2>
    <ul>
      <li><strong>Students</strong> working on a design project who want a worked reference to check their own numbers against.</li>
      <li><strong>Early stage founders</strong> who need a sense of the size, cost and footprint of a plant before spending on a feasibility study.</li>
      <li><strong>Engineers scoping ideas</strong> who want a quick, transparent starting point to change and argue with.</li>
    </ul>
    <h2>What it is not</h2>
    <p>Blueprint is a screening tool. Its estimates are factored, typically within minus 30 to plus 50 percent, and the models are simplified on purpose. It is not a substitute for detailed engineering, a licensor package or professional advice, and nothing here is fit for construction.</p>
    <h2>Get in touch</h2>
    <p>Missing a chemical? <a href="../request/">Request it</a>. Every request is read, and the most asked for processes are modelled first.</p>
  </div>
</div>
</main>
"""
    write("about/index.html", page_html(page, body, current="about/"))
    return page


def build_method(designs, built_order):
    page = {"path": "method/", "title": "Method and sources | Blueprint",
            "desc": "How Blueprint designs a plant: Turton bare module costing, CEPCI escalation, ideal gas equilibrium reactors, "
                    "Raoult flash, open thermodynamic data, sourced prices and validation against published plants."}
    prices = load(os.path.join(ROOT, "engine", "data", "prices.json"))
    bench = load(os.path.join(ROOT, "engine", "data", "benchmarks.json"))
    comps = load(os.path.join(ROOT, "engine", "data", "components.json"))
    first = designs[built_order[0]] if built_order else {}
    capex = first.get("capex") or {}
    cepci_year, cepci_val = capex.get("cepci_year"), capex.get("cepci")

    def src_link(e):
        url = e.get("url")
        s = esc(e.get("source") or "Source")
        return '<a href="{}" target="_blank" rel="noopener">{}</a>'.format(esc(url), s) if url else s

    def price_rows(group):
        rows = []
        for key, e in (prices.get(group) or {}).items():
            if not isinstance(e, dict):
                continue
            v = e.get("value")
            if v is None and e.get("value_range"):
                v = "{} to {}".format(*e["value_range"])
            elif v is None:
                continue
            name = key.replace("_", " ")
            name = name[:1].upper() + name[1:]
            rows.append("<tr><td>{}</td><td class=\"r\">{}</td><td>{}</td><td class=\"nw\">{}</td><td>{}</td></tr>".format(
                chem(name), esc(v if isinstance(v, str) else "{:,.4g}".format(v)), esc(e.get("unit") or ""),
                esc(e.get("year") or ""), src_link(e)))
        return "".join(rows)

    def table(rows, head):
        return ('<div class="table-scroll"><table class="t"><thead><tr>{}</tr></thead><tbody>{}</tbody></table></div>'
                .format("".join('<th{}>{}</th>'.format(' class="r"' if h == "Value" else "", h) for h in head), rows))

    bench_rows = []
    for key, items in bench.items():
        if key.startswith("_") or not isinstance(items, list):
            continue
        sources = sorted({(b.get("source") or "", b.get("url") or "") for b in items if isinstance(b, dict)})
        label = key.replace("_", " ")
        label = label[:1].upper() + label[1:]
        links = "; ".join('<a href="{}" target="_blank" rel="noopener">{}</a>'.format(esc(u), esc(s)) if u else esc(s)
                          for s, u in sources if s)
        bench_rows.append('<tr><td class="nw">{}</td><td class="r">{}</td><td>{}</td></tr>'.format(esc(label), len(items), links))
    cmeta = comps.get("_meta") or {}
    comp_src = cmeta.get("_source") or ""
    n_comp = len(comps.get("components") or {})
    cepci_text = ("Costs are escalated with the Chemical Engineering Plant Cost Index from the Turton base (CEPCI 397, 2001) "
                  "to {} (CEPCI {:g}).".format(esc(cepci_year), cepci_val)) if cepci_year and cepci_val else \
        "Costs are escalated with the Chemical Engineering Plant Cost Index from the Turton base (CEPCI 397, 2001)."
    body = """<main id="main">
<div class="page-head">
  <div class="wrap narrow">
    <p class="eyebrow">Method</p>
    <h1>Method and sources</h1>
    <p class="lede">What the engine does, where every number comes from and how far to trust it.</p>
  </div>
</div>
<div class="wrap narrow">
  <div class="prose">
    <h2>Accuracy</h2>
    <p>Blueprint produces a factored estimate, the class used for screening and study work. Expect capital cost to fall typically within minus 30 to plus 50 percent of a detailed estimate. Mass and energy balances are tighter, as they are solved, not factored, and every design reports its own closure and atom balance error.</p>

    <h2>Process models</h2>
    <ul>
      <li><strong>Reactors.</strong> Equilibrium reactors are solved as ideal gas chemical equilibrium by Newton iteration on the reaction extents, with equilibrium constants from Gibbs energies of formation. Adiabatic reactors are solved for the outlet temperature at which outlet enthalpy equals inlet enthalpy. Where industry runs short of equilibrium, an approach temperature is applied and stated in the inputs.</li>
      <li><strong>Separators.</strong> Vapour and liquid splits use Raoult's law over an ideal liquid, solved with the Rachford Rice equation, with Antoine vapour pressures.</li>
      <li><strong>Energy.</strong> Ideal gas enthalpy is the heat of formation at 298 K plus the integral of a fitted heat capacity, with heats of vaporisation for liquids. Steam properties use IAPWS 97 where a process model needs them.</li>
      <li><strong>Heat exchangers.</strong> Areas come from the duty, the log mean temperature difference and typical overall heat transfer coefficients (Sinnott and Towler, Chemical Engineering Design).</li>
    </ul>

    <h2>Thermodynamic data</h2>
    <p>Data for the {n_comp} components come from the open source Python packages <a href="https://github.com/CalebBell/chemicals" target="_blank" rel="noopener">chemicals</a> and <a href="https://github.com/CalebBell/thermo" target="_blank" rel="noopener">thermo</a> by Caleb Bell (MIT licence): critical properties, heats of formation and combustion, Gibbs energies, heat capacities, vapour pressures, flash points and flammability limits. A few condensed phase heats of formation are taken from the NIST Chemistry WebBook. GHS hazard statements are the harmonised EU CLP classifications (Regulation 1272/2008, Annex VI); always use the supplier safety data sheet.</p>
    <p class="small muted">{comp_src}</p>

    <h2>Capital cost</h2>
    <p>Purchased equipment cost follows Turton et al., <em>Analysis, Synthesis and Design of Chemical Processes</em>, 5th edition (2018), Appendix A: log<sub>10</sub>C<sub>p</sub><sup>0</sup> = K<sub>1</sub> + K<sub>2</sub> log<sub>10</sub>A + K<sub>3</sub> (log<sub>10</sub>A)<sup>2</sup>. Bare module cost applies the pressure and material factors, and grassroots fixed capital is 1.18 times the sum of bare module costs plus 0.50 times the bare module cost at base conditions. Units above the correlation range are split into identical parallel trains rather than extrapolated. {cepci}</p>

    <h2>Operating cost and returns</h2>
    <p>Cost of manufacture follows Turton Eq. 8.2 without depreciation: 0.18 FCI + 2.73 C<sub>OL</sub> + 1.23 (C<sub>UT</sub> + C<sub>WT</sub> + C<sub>RM</sub>). Operating labour uses the Alkhayat and Gerrard correlation (Turton Eq. 8.3) and the US BLS mean wage for chemical plant operators. The plant runs 8,000 hours a year. NPV, IRR and payback come from a discounted cash flow over the plant life with the tax rate and discount rate stated in each design.</p>

    <h2>Carbon</h2>
    <p>Scope 1 covers fuel combustion, process CO<sub>2</sub>, N<sub>2</sub>O and methane slip. Scope 2 covers grid electricity and net steam, at the regional grid factor. Upstream feedstock emissions are not included. Emission factors are listed with their sources below.</p>

    <h2>Validation</h2>
    <p>Each design is compared with published figures for real plants: energy use per tonne, conversion, emissions, capital and production cost, taken from industry best available technique documents, IPCC guidance, licensor papers and peer reviewed studies. Each check has a tolerance that reflects how precise the published figure is, and the result is shown on the design page as a pass or a fail. Benchmarks on file:</p>
    {bench}

    <h2>Prices</h2>
    <p>Product, feedstock and utility prices are recent public figures, each with its source. Some are free summaries of paid assessments, so treat them as indicative. Regional cases (United States, European Union, United Kingdom) swap in local energy prices and grid factors.</p>
    {prices}
    <h3>Emission factors</h3>
    {ef}
  </div>
</div>
</main>
""".format(n_comp=n_comp, comp_src=esc(comp_src), cepci=cepci_text,
           bench=table("".join(bench_rows), ["Process", "Value", "Sources"]).replace('<th class="r">Value</th>', '<th class="r">Checks</th>'),
           prices=table(price_rows("prices"), ["Item", "Value", "Unit", "Year", "Source"]),
           ef=table(price_rows("emission_factors"), ["Factor", "Value", "Unit", "Year", "Source"]))
    write("method/index.html", page_html(page, body, current="method/"))
    return page


def build_privacy():
    page = {"path": "privacy/", "title": "Privacy | Blueprint",
            "desc": "What Blueprint collects (only what you type into a form), how it is used, and what loads from third parties."}
    body = """<main id="main">
<div class="page-head">
  <div class="wrap narrow">
    <p class="eyebrow">Privacy</p>
    <h1>Privacy</h1>
    <p class="lede">Short version: no cookies, no analytics, and only what you choose to send.</p>
  </div>
</div>
<div class="wrap narrow">
  <div class="prose">
    <h2>What is collected</h2>
    <p>Nothing, unless you fill in a form. The waitlist form collects your email address. The request form collects your email address, the chemical, and optionally a capacity and a note.</p>
    <h2>How it is sent</h2>
    <p>Form entries are sent through <a href="https://formsubmit.co" target="_blank" rel="noopener">FormSubmit</a>, which forwards them by email to the founder. Blueprint keeps no database of its own.</p>
    <h2>How it is used</h2>
    <p>Only to reply to you and to announce new processes. Your details are never sold or shared. To be removed, reply to any email from Blueprint and ask.</p>
    <h2>Cookies and tracking</h2>
    <p>Blueprint sets no cookies and runs no analytics or advertising scripts. The site is hosted on GitHub Pages, which may keep standard server logs.</p>
    <h2>Third party code</h2>
    <p>Pages load nothing from third parties. When you run a custom design, your browser downloads Python (Pyodide) from the jsDelivr CDN, and fpdf2 from the Python Package Index if you build a custom PDF. The design itself is solved on your device and is not sent anywhere.</p>
  </div>
</div>
</main>
"""
    write("privacy/index.html", page_html(page, body))
    return page


def build_404(built_procs):
    page = {"path": "404.html", "title": "Page not found | Blueprint", "desc": "This page does not exist.", "noindex": True}
    abs_pre = BASE_PATH
    links = "".join('<a class="chip" href="{b}design/{id}/">{l}</a>'.format(b=abs_pre, id=esc(p["id"]), l=esc(p["label"]))
                    for p in built_procs)
    body = """<main id="main">
<div class="wrap narrow notfound">
  <p class="eyebrow">404</p>
  <h1 style="margin-bottom:var(--s4)">Page not found</h1>
  <p class="lede" style="margin-bottom:var(--s5)">The link may be old or mistyped. Start from the home page or open a design.</p>
  <p><a class="btn btn-primary" href="{b}">Go to the home page</a></p>
  <div class="chips" style="margin-top:var(--s5)">{links}</div>
</div>
</main>
""".format(b=abs_pre, links=links)
    html_text = head(page, abs_pre) + header(abs_pre) + body + footer(abs_pre, ())
    write("404.html", html_text)


# ------------------------------------------------------------------------------- engine copy

def copy_engine():
    dst = os.path.join(SITE, "py")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    files = []
    eng = os.path.join(ROOT, "engine")
    patterns = [("engine", ".py"), ("engine/processes", ".py"), ("engine/data", ".json")]
    for sub, ext in patterns:
        src_dir = os.path.join(ROOT, sub)
        if not os.path.isdir(src_dir):
            continue
        for name in sorted(os.listdir(src_dir)):
            if name.endswith(ext) and not name.startswith("."):
                files.append(sub + "/" + name)
    if os.path.exists(os.path.join(eng, "processes")) and "engine/processes/__init__.py" not in files:
        files.append("engine/processes/__init__.py")  # written empty below
    files.append("build_pdf.py")
    out = []
    for rel in files:
        src = os.path.join(ROOT, "tools", "build_pdf.py") if rel == "build_pdf.py" else os.path.join(ROOT, rel)
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(src):
            shutil.copyfile(src, target)
        else:
            open(target, "w").close()
        out.append({"path": rel, "bytes": os.path.getsize(target)})
    with open(os.path.join(dst, "manifest.json"), "w") as f:
        json.dump({"files": out, "fonts": ["Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"]}, f, indent=1)
    return len(out)


# ---------------------------------------------------------------------------------- images

def build_images():
    write("assets/favicon.svg", FAVICON_SVG)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  Pillow not available: PNG icons and og.png skipped")
        return

    def mark(size):
        s = size / 32.0
        sup = 4
        im = Image.new("RGBA", (size * sup, size * sup), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        k = s * sup
        dr.rounded_rectangle([0, 0, 32 * k - 1, 32 * k - 1], radius=8 * k, fill=ACCENT)
        w = max(1, round(2 * k))
        dr.rounded_rectangle([6.5 * k, 8.5 * k, 14.5 * k, 16.5 * k], radius=1.5 * k, outline="white", width=w)
        dr.line([(14.5 * k, 12.5 * k), (19 * k, 12.5 * k), (19 * k, 20 * k)], fill="white", width=w, joint="curve")
        dr.rounded_rectangle([15 * k, 19 * k, 25.5 * k, 24.5 * k], radius=1.5 * k, fill="white")
        return im.resize((size, size), Image.LANCZOS)

    mark(32).save(os.path.join(SITE, "assets", "favicon-32.png"))
    # Apple touch icon: opaque, full bleed accent (iOS rounds the corners itself)
    t = Image.new("RGB", (180, 180), ACCENT)
    m = mark(180)
    t.paste(m, (0, 0), m)
    bg = Image.new("RGB", (180, 180), ACCENT)
    bg.paste(m, (0, 0), m)
    bg.save(os.path.join(SITE, "assets", "apple-touch-icon.png"))

    W, H = 1200, 630
    sup = 2
    im = Image.new("RGB", (W * sup, H * sup), "#FCFCFD")
    dr = ImageDraw.Draw(im)
    fdir = os.path.join(SITE, "fonts")
    f_semi = lambda px: ImageFont.truetype(os.path.join(fdir, "Inter-SemiBold.ttf"), px * sup)  # noqa: E731
    f_reg = lambda px: ImageFont.truetype(os.path.join(fdir, "Inter-Regular.ttf"), px * sup)  # noqa: E731
    for x in range(0, W, 24):  # faint dot grid, like the flow diagram canvas
        for y in range(0, H, 24):
            dr.ellipse([(x + 12) * sup - 2, (y + 12) * sup - 2, (x + 12) * sup + 2, (y + 12) * sup + 2], fill="#ECEEF2")
    mk = mark(56)
    im.paste(mk.resize((56 * sup, 56 * sup), Image.LANCZOS), (72 * sup, 72 * sup), mk.resize((56 * sup, 56 * sup), Image.LANCZOS))
    dr.text((144 * sup, 84 * sup), "Blueprint", font=f_semi(32), fill=INK)
    dr.text((72 * sup, 200 * sup), "Type a chemical.", font=f_semi(64), fill=INK)
    dr.text((72 * sup, 276 * sup), "Get a plant design.", font=f_semi(64), fill=ACCENT)
    sub = "Flow diagram, mass and energy balance, kit list, costs, hazards and carbon,"
    sub2 = "checked against published plant figures."
    dr.text((72 * sup, 380 * sup), sub, font=f_reg(26), fill="#5B6474")
    dr.text((72 * sup, 414 * sup), sub2, font=f_reg(26), fill="#5B6474")
    # simple flow diagram strip
    y0 = 520
    boxes = [(72, "R-101"), (292, "E-101"), (512, "V-101"), (732, "T-101")]
    for i, (x, tag) in enumerate(boxes):
        dr.rounded_rectangle([x * sup, y0 * sup, (x + 150) * sup, (y0 + 52) * sup], radius=8 * sup, fill="white",
                             outline="#9AA3B2", width=2 * sup)
        dr.text(((x + 16) * sup, (y0 + 15) * sup), tag, font=f_semi(18), fill=ACCENT)
        if i < len(boxes) - 1:
            xa, xb, yy = (x + 150) * sup, (x + 220) * sup, (y0 + 26) * sup
            dr.line([(xa, yy), (xb - 10 * sup, yy)], fill="#4A5466", width=2 * sup)
            dr.polygon([(xb, yy), (xb - 12 * sup, yy - 6 * sup), (xb - 12 * sup, yy + 6 * sup)], fill="#4A5466")
    xa, xb, yy = 882 * sup, 1128 * sup, (y0 + 26) * sup
    dr.line([(xa, yy), (xb - 12 * sup, yy)], fill=ACCENT, width=4 * sup)
    dr.polygon([(xb, yy), (xb - 16 * sup, yy - 8 * sup), (xb - 16 * sup, yy + 8 * sup)], fill=ACCENT)
    dr.text((900 * sup, (y0 - 30) * sup), "Product", font=f_semi(18), fill=ACCENT)
    im = im.resize((W, H), Image.LANCZOS)
    im.save(os.path.join(SITE, "assets", "og.png"), optimize=True)


# ----------------------------------------------------------------------------------- main

def main():
    index = load(os.path.join(DATA, "index.json"))
    regions = index.get("regions") or {"US": "United States"}
    built, designs, built_pdfs = [], {}, {}
    for p in index.get("processes") or []:
        if not p.get("live"):
            continue
        files = [os.path.join(DATA, "{}.{}.json".format(p["id"], r)) for r in regions]
        if not all(os.path.exists(f) for f in files):
            print("  skip {}: data files missing".format(p["id"]))
            continue
        built.append(p["id"])
        designs[p["id"]] = load(os.path.join(DATA, "{}.{}.json".format(p["id"], DEFAULT_REGION)))
        built_pdfs[p["id"]] = [r for r in regions if os.path.exists(os.path.join(SITE, "pdf", "{}.{}.pdf".format(p["id"], r)))]

    # remove design pages for processes that are no longer built
    ddir = os.path.join(SITE, "design")
    if os.path.isdir(ddir):
        for name in os.listdir(ddir):
            if name not in built:
                shutil.rmtree(os.path.join(ddir, name), ignore_errors=True)

    pages = [build_landing(index, built, designs)]
    for p in index["processes"]:
        if p["id"] in built:
            pages.append(build_design(p, designs[p["id"]], regions, built_pdfs[p["id"]]))
    pages.append(build_examples(index, built, designs))
    pages.append(build_request(index, built))
    pages.append(build_about())
    pages.append(build_method(designs, built))
    pages.append(build_privacy())
    build_404([p for p in index["processes"] if p["id"] in built])

    n_py = copy_engine()
    build_images()

    urls = "".join("  <url><loc>{}</loc></url>\n".format(esc(SITE_URL + p["path"])) for p in pages)
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")
    write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: {}sitemap.xml\n".format(SITE_URL))
    write(".nojekyll", "")
    print("Built {} pages ({} designs: {}), {} engine files in site/py".format(
        len(pages) + 1, len(built), ", ".join(built), n_py))


if __name__ == "__main__":
    main()
