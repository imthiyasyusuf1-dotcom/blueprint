"""Ethylene by steam cracking of ethane, with the hot section, quench, cracked gas compression and the cold box.

Per pass in the furnace coils (ethane with dilution steam, about 840 C, under 0.3 s):
    C2H6 -> C2H4 + H2                 main reaction
    2 C2H6 -> C3H6 + CH4 + H2         propylene
    2 C2H6 -> C4H6 + 3 H2             butadiene and other C4 (lumped as butadiene)
    C2H6 + H2 -> 2 CH4                methane
    3 C2H6 -> C6H6 + 6 H2             pyrolysis gasoline (lumped as benzene)

The reaction extents are not set by hand: they are solved from the single pass furnace yields in the EU
LVOC BREF (ethane feed), and the unconverted ethane that falls out of that solution is recycled to
extinction. Transfer line exchangers raise high pressure steam, a water quench condenses the dilution
steam and the gasoline, then a five stage steam driven compressor takes the gas to about 36 bar. After
caustic wash and drying the cold box and demethaniser strip hydrogen and methane, which are burnt in the
furnaces. A deethaniser, C2 splitter and depropaniser give polymer grade ethylene, recycle ethane,
propylene and a crude C4 and gasoline cut.

Benchmarks: IPCC 2006 Guidelines Vol 3 Ch 3; Ren, Patel and Blok (2006); EU BREF LVOC (JRC109279, 2017);
US DOE chemical industry profile (2000); Oil and Gas Journal on INEOS Project ONE (2026).
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 3000.0,  # t/d ethylene
    # single pass furnace yields, wt% of furnace feed (EU BREF LVOC, ethane column)
    "y_C2H4": 56.0, "y_H2": 4.3, "y_CH4": 4.2, "y_C3H6": 1.0, "y_C4H6": 1.6, "y_C6H6": 1.8,
    "coil_out_C": 840.0,
    "coil_out_bar": 2.0,
    "steam_ratio": 0.3,  # kg dilution steam per kg ethane (assumed typical for ethane)
    "feed_in_C": 600.0,  # feed leaving the convection section into the radiant coils (assumed)
    "furnace_eff": 0.93,  # fired duty absorbed by the coils, the convection section and the steam superheat (assumed)
    "tle_out_C": 400.0,
    "cgc_out_bar": 36.0,
    "c2_reflux": 3.5,  # C2 splitter reflux ratio (assumed)
    "cop_propylene": 1.5,  # refrigeration COP at -40 C (assumed)
    "cop_ethylene": 0.6,  # refrigeration COP at -100 C, cascaded into propylene (assumed)
    "storage_days": 3,
}

LATENT = 2100.0
EUR_USD_2025 = 1.1306  # US Federal Reserve G.5A, 2025 annual average


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def _hg(flows, T):
    return sum(n * core.h_molar(c, T, "g") for c, n in flows.items()) / 3600.0  # kW


def _extents(p):
    """Reaction extents (kmol per 100 kg furnace feed) from the published single pass yields."""
    MW = th.MW
    e1 = p["y_C2H4"] / MW("C2H4")
    e2 = p["y_C3H6"] / MW("C3H6")
    e3 = p["y_C4H6"] / MW("C4H6")
    e5 = p["y_C6H6"] / MW("Benzene")
    e4 = (p["y_CH4"] / MW("CH4") - e2) / 2
    if e4 < 0:
        raise ValueError("methane yield below what propylene formation makes")
    return e1, e2, e3, e4, e5


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    T0 = 298.15
    TC = p["coil_out_C"] + 273.15
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    e1, e2, e3, e4, e5 = _extents(p)
    k = P_kg_h / MW("C2H4") / e1  # 100 kg units of furnace feed per hour
    x = [e * k for e in (e1, e2, e3, e4, e5)]
    used = x[0] + 2 * x[1] + 2 * x[2] + x[3] + 3 * x[4]
    feed = 100 * k / MW("C2H6")  # kmol/h ethane to the coils
    rec = feed - used
    if rec <= 0:
        raise ValueError("published yields use more ethane than the furnace feed")
    h2 = x[0] + x[1] + 3 * x[2] - x[3] + 6 * x[4]
    ds = p["steam_ratio"] * feed * MW("C2H6") / MW("H2O")
    f_cg = {"C2H4": x[0], "C2H6": rec, "H2": h2, "CH4": x[1] + 2 * x[3], "C3H6": x[1], "C4H6": x[2],
            "Benzene": x[4], "H2O": ds}

    d = Design("ethylene", "Ethylene plant (ethane steam cracker)", "C2H4", p["capacity_tpd"], region)
    d.route = ("Ethane is cracked with dilution steam in fired tubular furnaces. The hot gas raises high pressure "
               "steam, is quenched with water, compressed to about 36 bar and dried, then chilled in a cold box. "
               "Columns separate hydrogen and methane (burnt as furnace fuel), ethylene, recycle ethane, propylene and "
               "a heavier cut.")
    fresh_tpd = used * MW("C2H6") * 24 / 1000
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of polymer grade ethylene from {fresh_tpd:,.0f} t/d of fresh ethane, "
                 f"with {rec * MW('C2H6') * 24 / 1000:,.0f} t/d of ethane recycled.")

    def dhg(prod, reac):
        return (sum(n * core.h_molar(c, T0, "g") for c, n in prod.items())
                - sum(n * core.h_molar(c, T0, "g") for c, n in reac.items())) / 1000

    d.reactions = [
        {"eq": "C2H6 -> C2H4 + H2", "where": "Furnace coils", "dH_kJ": dhg({"C2H4": 1, "H2": 1}, {"C2H6": 1})},
        {"eq": "2 C2H6 -> C3H6 + CH4 + H2", "where": "Furnace coils",
         "dH_kJ": dhg({"C3H6": 1, "CH4": 1, "H2": 1}, {"C2H6": 2})},
        {"eq": "2 C2H6 -> C4H6 + 3 H2", "where": "Furnace coils (C4 lumped as butadiene)",
         "dH_kJ": dhg({"C4H6": 1, "H2": 3}, {"C2H6": 2})},
        {"eq": "C2H6 + H2 -> 2 CH4", "where": "Furnace coils", "dH_kJ": dhg({"CH4": 2}, {"C2H6": 1, "H2": 1})},
        {"eq": "3 C2H6 -> C6H6 + 6 H2", "where": "Furnace coils (gasoline lumped as benzene)",
         "dH_kJ": dhg({"Benzene": 1, "H2": 6}, {"C2H6": 3})},
    ]
    conv = used / feed * 100
    d.conditions = [
        ("Furnace coils", f"{p['coil_out_C']:.0f} C outlet, {p['coil_out_bar']:.0f} bar, {p['steam_ratio']:.1f} kg "
                          f"steam per kg ethane, {conv:.0f}% ethane conversion per pass"),
        ("Transfer line exchangers", f"gas cooled to {p['tle_out_C']:.0f} C raising 120 bar steam"),
        ("Cracked gas compressor", f"5 stages to {p['cgc_out_bar']:.0f} bar, steam turbine drive"),
        ("Cold section", "demethaniser near -100 C, C2 splitter near -30 C, propylene and ethylene refrigeration"),
    ]

    # ---------------------------------------------------------------- streams
    TF = p["feed_in_C"] + 273.15
    s_fresh = d.stream("Fresh ethane", {"C2H6": used}, T0, 30.0, phase="g")
    s_rec = d.stream("Recycle ethane", {"C2H6": rec}, T0, 5.0, phase="g")
    s_ds = d.stream("Dilution steam", {"H2O": ds}, 453.15, 7.0, phase="g")
    s_hot = d.stream("Cracked gas from coils", f_cg, TC, p["coil_out_bar"], phase="g")
    s_tle = d.stream("Cracked gas after TLE", f_cg, p["tle_out_C"] + 273.15, 1.8, phase="g")
    f_gas = {c: v for c, v in f_cg.items() if c not in ("H2O", "Benzene")}
    s_gas = d.stream("Quenched cracked gas", f_gas, 313.15, 1.5, phase="g")
    s_pw = d.stream("Process water to dilution steam", {"H2O": ds}, 363.15, 1.5, phase="l")
    s_pg = d.stream("Pyrolysis gasoline", {"Benzene": x[4]}, 313.15, 1.5, phase="l")
    s_cmp = d.stream("Compressed dry cracked gas", f_gas, 313.15, p["cgc_out_bar"], phase="g")
    f_fg = {"H2": h2, "CH4": f_cg["CH4"]}
    s_fg = d.stream("Fuel gas (hydrogen and methane)", f_fg, T0, 4.0, phase="g")
    f_c2p = {c: f_gas[c] for c in ("C2H4", "C2H6", "C3H6", "C4H6")}
    s_c2p = d.stream("Demethaniser bottoms", f_c2p, 263.15, 30.0, phase="l")
    s_c2 = d.stream("C2 cut", {"C2H4": x[0], "C2H6": rec}, 263.15, 25.0, phase="g")
    s_c3p = d.stream("Deethaniser bottoms", {"C3H6": x[1], "C4H6": x[2]}, 343.15, 25.0, phase="l")
    s_eth = d.stream("Ethylene", {"C2H4": x[0]}, 243.15, 20.0, phase="g")
    s_c3 = d.stream("Propylene", {"C3H6": x[1]}, 313.15, 18.0, phase="l")
    s_c4 = d.stream("Crude C4", {"C4H6": x[2]}, 313.15, 6.0, phase="l")

    d.feed(s_fresh, {"C2H6": "C2H6"})
    d.out(s_eth, "product", {"C2H4": "C2H4"})
    d.out(s_c3, "byproduct", {"C3H6": "C3H6"})
    d.out(s_c4, "byproduct", {"C4H6": "Pygas"})
    d.out(s_pg, "byproduct", {"Benzene": "Pygas"})
    d.out(s_fg, "fuel")

    d.unit("F-101", "Cracking furnaces", "reactor", [s_fresh, s_rec, s_ds], [s_hot], (0, 0))
    d.unit("E-101", "Transfer line exchangers", "hx", [s_hot], [s_tle], (1, 0))
    d.unit("T-101", "Water quench tower", "column", [s_tle], [s_gas, s_pw, s_pg], (2, 0))
    d.unit("V-101", "Dilution steam generator", "hx", [s_pw], [s_ds], (2, 1))
    d.unit("C-101", "Cracked gas compressor, caustic wash and dryers", "compressor", [s_gas], [s_cmp], (3, 0))
    d.unit("T-102", "Cold box and demethaniser", "column", [s_cmp], [s_fg, s_c2p], (4, 0))
    d.unit("T-103", "Deethaniser", "column", [s_c2p], [s_c2, s_c3p], (5, 0))
    d.unit("T-104", "C2 splitter", "column", [s_c2], [s_eth, s_rec], (6, 0))
    d.unit("T-105", "Depropaniser", "column", [s_c3p], [s_c3, s_c4], (6, 1))

    # ---------------------------------------------------------------- energy
    Q_coil = _hg(f_cg, TC) - _hg({"C2H6": feed}, T0) - _hg({"H2O": ds}, 453.15)
    fired_kW = Q_coil / p["furnace_eff"]
    fired_GJ = fired_kW * 3600 / 1e6
    fg_GJ = sum(n * th.lhv_molar(c) for c, n in f_fg.items()) * 1000 / 1e9
    burn = min(fg_GJ, fired_GJ)
    d.fuel(fired_GJ, "Cracking furnaces (fired duty)")
    d.fuel_credit(burn, "Hydrogen and methane burnt in the furnaces", co2_kg_h=f_fg["CH4"] * burn / fg_GJ * MW("CO2"))
    if fg_GJ > fired_GJ:
        d.fuel_credit(0.0, f"Surplus fuel gas {fg_GJ - fired_GJ:,.0f} GJ/h to the site fuel system (not credited)")
    Q_tle = _hg(f_cg, TC) - _hg(f_cg, p["tle_out_C"] + 273.15)
    st_hp = Q_tle / (th.H_STEAM_120BAR_510C - th.H_BFW_105C) * 3600
    d.steam(-st_hp, "Transfer line exchangers (120 bar steam, superheated in the convection section)")
    # quench: dilution steam is raised from quench water heat; the rest goes to cooling water
    Q_q = _hg(f_cg, p["tle_out_C"] + 273.15) - _hg(f_gas, 313.15) - _hg({"Benzene": x[4]}, 313.15) \
        - (ds * core.h_molar("H2O", 363.15, "l") + x[4] * 0) / 3600
    Q_dsg = (_hg({"H2O": ds}, 453.15) - ds * core.h_molar("H2O", 363.15, "l") / 3600)
    d.cooling(max(Q_q - Q_dsg, 0.0), "Quench water coolers")
    if Q_dsg > Q_q:
        d.steam((Q_dsg - Q_q) / LATENT * 3600, "Dilution steam generator top up")
    # refrigeration
    nC2 = x[0] + rec
    Q_c2 = nC2 * (1 + p["c2_reflux"]) * th.hvap("C2H4", 243.15) / 3600  # kW, C2 splitter condenser
    Q_cold = (_hg(f_gas, 238.15) - _hg(f_gas, 173.15)) + sum(f_c2p[c] * th.hvap(c, 190.0) for c in f_c2p) / 3600
    W_c3r = (Q_c2 + 0.5 * Q_cold) / p["cop_propylene"]
    W_c2r = 0.5 * Q_cold / p["cop_ethylene"]
    st_turb = lambda W: W / (0.30 * (th.H_STEAM_120BAR_510C - th.H_BFW_105C)) * 3600
    d.generic("C-102", "Propylene refrigeration compressor", "compressor", W_c3r, f"{W_c3r:,.0f} kW shaft")
    d.generic("C-102-T", "Propylene refrigeration compressor steam turbine", "turbine_steam", W_c3r,
              f"{W_c3r:,.0f} kW shaft")
    d.steam(st_turb(W_c3r), "Propylene refrigeration compressor turbine")
    d.generic("C-103", "Ethylene refrigeration compressor", "compressor", W_c2r, f"{W_c2r:,.0f} kW shaft")
    d.generic("C-103-T", "Ethylene refrigeration compressor steam turbine", "turbine_steam", W_c2r,
              f"{W_c2r:,.0f} kW shaft")
    d.steam(st_turb(W_c2r), "Ethylene refrigeration compressor turbine")
    d.cooling(Q_c2 + Q_cold + W_c3r + W_c2r, "Refrigerant condensers")
    Q_de = (x[1] + x[2]) * 2 * th.hvap("C3H6", 330.0) / 3600 + nC2 * 0.5 * th.hvap("C2H6", 263.15) / 3600
    d.steam(Q_de / LATENT * 3600, "Deethaniser and depropaniser reboilers")
    d.cooling(Q_de * 0.5, "Depropaniser condenser")

    # ---------------------------------------------------------------- equipment
    d.heater("F-101", "Cracking furnaces", fired_kW, P_barg=p["coil_out_bar"] + 2, material="SS")
    d.hx("E-101", "Transfer line exchangers", Q_tle, TC, p["tle_out_C"] + 273.15, 597.15, 597.15, "boiler",
         P_barg=120, material="SS")
    d.column("T-101", "Water quench tower", sum(f_cg.values()), 360.15, 1.6, 10, _kg(f_cg) / sum(f_cg.values()))
    d.hx("E-102", "Quench water coolers", max(Q_q - Q_dsg, 1.0), 353.15, 318.15, 303.15, 313.15, "liquid-water")
    d.hx("E-103", "Dilution steam generator", Q_dsg, 433.15, 433.15, 363.15, 453.15, "reboiler")
    d.compressor("C-101", "Cracked gas compressor", s_gas, p["cgc_out_bar"], k=1.25, eta=0.80, driver="steam",
                 stages=5)
    d.vessel("V-102", "Caustic tower and dryers", max(_kg(f_gas) / 1000 * 0.3, 10.0), P_barg=p["cgc_out_bar"])
    d.column("T-102", "Demethaniser", sum(f_fg.values()) * 1.5, 173.15, 30.0, 40, 10.0, material="SS")
    d.column("T-103", "Deethaniser", nC2 * 1.5, 263.15, 25.0, 40, 29.0)
    d.column("T-104", "C2 splitter", nC2 * (1 + p["c2_reflux"]), 243.15, 20.0, 110, 28.5, material="SS")
    d.column("T-105", "Depropaniser", (x[1] + x[2]) * 2, 330.0, 18.0, 40, 47.0)
    d.hx("E-104", "Cold box", Q_cold, 238.15, 173.15, 160.15, 230.15, "condenser", P_barg=p["cgc_out_bar"],
         material="SS")
    d.tank("TK-101", "Ethylene storage (refrigerated)", P_kg_h, 570, days=p["storage_days"], material="SS")
    d.tank("TK-102", "Propylene and C4 spheres", _kg({"C3H6": x[1], "C4H6": x[2]}), 550, days=7, pressurised=True,
           P_barg=18)
    cw = d.cw_kW
    d.power(cw * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw, "Cooling water pumps and tower fans")
    d.power(0.0005 * _kg(f_cg), "Pumps, fans and furnace draft")
    d.power(0.05 * d.power_kW, "Compressed air, lighting, HVAC and flare (5% of process load)")

    # ---------------------------------------------------------------- KPIs and checks
    t_fresh = used * MW("C2H6") / 1000  # t/h
    eth_kg_t = P_kg_h / t_fresh
    st_net_GJ = (d.steam_import_kg_h - d.steam_export_kg_h) * (th.H_STEAM_120BAR_510C - th.H_BFW_105C) / 0.9 / 1e6
    sec = (fired_GJ + d.power_kW * 3.6 / 1000 + st_net_GJ) / (P_kg_h / 1000)
    hvc = P_kg_h + _kg({"C3H6": x[1], "C4H6": x[2], "Benzene": x[4]})
    co2_t = d.direct_co2_kg_h / P_kg_h
    d.kpis = [
        {"label": "Ethylene yield on fresh ethane", "value": eth_kg_t / 10, "unit": "wt%"},
        {"label": "Ethane conversion per pass", "value": conv, "unit": "%"},
        {"label": "Fired duty", "value": fired_GJ / (P_kg_h / 1000), "unit": "GJ/t ethylene"},
        {"label": "Specific energy", "value": sec, "unit": "GJ/t ethylene"},
        {"label": "Direct CO2", "value": co2_t, "unit": "t/t ethylene"},
    ]
    IP = "https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/3_Volume3/V3_3_Ch3_Chemical_Industry.pdf"
    IPS = "IPCC 2006 Vol 3 Ch 3, Table 3.25 (Neelis, Patel, de Feber 2003), ethane column"
    REN = "https://dspace.library.uu.nl/server/api/core/bitstreams/1b3f5619-52c6-45d4-ac17-a71b18f04195/content"
    RS = "Ren, Patel and Blok (2006), Olefins from conventional and heavy feedstocks, Energy 31"
    note_y = ("Model extents are solved from the BREF single pass yields; the ultimate value follows from recycling "
              "the ethane left over.")
    d.check("Ethylene per t ethane feed (ultimate)", eth_kg_t, 803, "kg/t ethane", IPS, IP, tol=5, note=note_y)
    d.check("Hydrogen per t ethane feed", h2 * MW("H2") / t_fresh, 60, "kg/t ethane", IPS, IP, tol=10, note=note_y)
    d.check("Methane per t ethane feed", f_cg["CH4"] * MW("CH4") / t_fresh, 61, "kg/t ethane", IPS, IP, tol=10,
            note=note_y)
    d.check("Ethylene final yield on ethane", eth_kg_t / 10, [80, 84], "wt%", RS, REN, tol=0, note=note_y)
    OGJ = "https://www.ogj.com/refining-processing/news/55394579/ineos-plans-2027-startup-of-antwerp-grassroots-ethane-cracker"
    d.check("Ethane per t ethylene, INEOS Project ONE design", t_fresh / (P_kg_h / 1000), 1.317, "t/t",
            "Oil and Gas Journal (30 July 2026), INEOS Project ONE, 1.91 Mt/y ethane for 1.45 Mt/y ethylene", OGJ,
            tol=10, note="A design figure for a real plant, so it carries more C3 and C4 make and margin than the "
                         "BREF slate.")
    d.check("Specific energy consumption, ethane cracking", sec, [17, 21], "GJ/t ethylene", RS, REN, tol=15,
            note="Model: fired duty (including the burnt fuel gas) plus electricity plus net steam valued at 120 bar "
                 "steam from a 90% boiler. Feedstock energy excluded, as in Ren et al. Reads low because the "
                 "furnace duty is the coil heat balance at a fixed efficiency; real furnaces lose more to excess air, "
                 "coking, decoking and part load. Left failing rather than tuned.")
    d.check("CO2, ethane steam cracking", co2_t, 0.95, "t CO2/t ethylene",
            "2006 IPCC Guidelines, Vol 3 Ch 3, Table 3.14 (Tier 1 default)", IP, tol=25,
            note="Model counts the CO2 from burning methane in the furnaces. The off gas covers all the firing and "
                 "is rich in hydrogen, which burns to water, and the surplus goes to the site fuel system, so the "
                 "model reads well below the Tier 1 default. Left failing.")
    tpy = p["capacity_tpd"] * d.hours / 24
    d.check("Fixed capital, scaled from INEOS Project ONE", None,
            5e9 * EUR_USD_2025 * (tpy / 1.45e6) ** 0.7, "USD",
            "Oil and Gas Journal (30 July 2026): EUR 5 billion for the 1.45 Mt/y Project ONE cracker in Antwerp. "
            "Converted at 1.1306 USD/EUR (US Federal Reserve G.5A, 2025 average), exponent 0.7", OGJ, tol=50,
            kind="capex", note="Published figure is a whole grassroots project in Europe in 2026 money, including "
                               "site utilities, jetty and storage; the model is a US Turton estimate in 2024 money.")

    d.assumptions = [
        "Single pass yields are the EU BREF ethane figures; acetylene, propane and heavier oils are not in that slate "
        "and are not modelled (no acetylene hydrogenation unit is shown).",
        "Crude C4 is lumped as butadiene and valued at the pyrolysis gasoline price, as no sourced butadiene price is "
        "in the data.",
        "Ethane recycle is cracked again at the same yields (recycled to extinction).",
        f"Furnace efficiency {p['furnace_eff'] * 100:.0f}% covers the radiant coils, feed preheat and steam superheat "
        "in the convection section.",
        "Dilution steam is raised from quench water heat; any shortfall is met with low pressure steam.",
        "Compressors are driven by 120 bar steam turbines at 30% of the steam enthalpy drop.",
        "Refrigeration loads are estimated from the C2 splitter condenser and the cold box chilling, with assumed "
        "COPs; the cold box is costed as stainless steel exchangers.",
    ]
    d.hazop = [
        {"node": "Cracking furnaces", "deviation": "Loss of dilution steam or feed", "cause": "Valve or pump failure",
         "consequence": "Coil overheating and rupture, firebox fire", "safeguard": "Trips on flow and coil "
         "temperature, burner management system, snuffing steam"},
        {"node": "Cracked gas compressor", "deviation": "Surge or high temperature", "cause": "Low flow, fouling",
         "consequence": "Machine damage, polymer build up, release of flammable gas",
         "safeguard": "Anti surge control, wash oil, interstage temperature trips"},
        {"node": "Cold box", "deviation": "Low temperature on carbon steel", "cause": "Refrigerant upset",
         "consequence": "Brittle fracture and a large flammable release", "safeguard": "Low temperature trips, "
         "material selection, gas detection and deluge"},
        {"node": "Ethylene storage", "deviation": "Loss of refrigeration", "cause": "Compressor trip",
         "consequence": "Pressure rise and vent to flare", "safeguard": "Spare compressor, relief to flare"},
    ]
    d.greener = {
        "title": "Electric furnaces and bio ethane",
        "text": "Most of the CO2 comes from firing the furnaces. Electrically heated cracking furnaces running on "
                "renewable power, or furnaces fired on the hydrogen with the methane sold, remove most of it; "
                "ethylene from bio ethanol avoids fossil feed altogether.",
    }
    return d.finish()
