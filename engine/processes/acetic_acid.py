"""Acetic acid by methanol carbonylation, iridium catalysed (Cativa type) process.

    CH3OH + CO -> CH3COOH            main reaction, Ir/Ru promoted iodide catalyst, liquid phase
    CO + H2O -> CO2 + H2             water gas shift, the main CO loss
    CH3OH + H2 -> CH4 + H2O          methane make (propionic acid and other by-products lumped here)

Methanol and carbon monoxide react in a stirred reactor near 190 C and 28 bar. The liquid is flashed: the
catalyst solution returns to the reactor and the vapour goes to the light ends column, then the drying
column and the heavy ends column. Inerts and by-product gases leave as the high-pressure vent, which
carries CO with it. Part of the reaction heat raises low-pressure steam.

Benchmarks: Jones (BP Chemicals), The Cativa process for the manufacture of acetic acid, Platinum Metals
Review 44 (2000); Credence Research CO plant report (2026); Chemwin news on the Shenghong 1 Mt/y project (2024).
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 1500.0,  # t/d acetic acid
    "T_C": 190.0,
    "P_bar": 28.0,
    "co_purity": 0.985,  # mol fraction CO in the feed gas (assumed, cryogenic CO); the rest H2 and N2
    "co_feed_h2": 0.010,
    "co_feed_n2": 0.005,
    "wgs_per_acid": 0.010,  # mol CO2 made by the shift per mol acid (assumed, low for the Ir system)
    "meoh_to_ch4": 0.005,  # share of methanol lost to methane and lumped by-products (assumed)
    "p_co_bar": 8.0,  # CO partial pressure in the reactor head space (assumed typical)
    "p_other_bar": 4.0,  # partial pressure of H2, N2, CO2 and CH4 together in the head space (assumed)
    "sty_kmol_m3_h": 15.0,  # space time yield, kmol acid per m3 liquid per h (assumed)
    "cat_recycle_ratio": 4.0,  # kg catalyst solution returned from the flash per kg acid made (assumed)
    "water_carry": 0.15,  # mol water per mol acid carried to the drying column and recycled (about 4 wt%)
    "heavies_purge": 0.002,  # share of acid lost with the heavy ends purge (assumed)
    "rx_steam_frac": 0.6,  # share of the reactor heat left after the flash that raises 3 bar steam
    "reflux_drying": 1.5,
    "reflux_heavy": 1.0,
    "co_supply_bar": 2.0,  # CO delivered from the cold box (assumed)
    "storage_days": 14,
}

LATENT = 2100.0  # kJ/kg given up by imported steam
H_LP_SAT = 2725.0  # kJ/kg saturated steam at about 3 bar


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    T0 = 298.15
    TR = p["T_C"] + 273.15
    PR_ = p["P_bar"]
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    Pout = P_kg_h / MW("AcOH")
    A = Pout / (1 - p["heavies_purge"])  # acid made
    purge = A - Pout
    M = A / (1 - p["meoh_to_ch4"])
    m4 = M - A
    wgs = p["wgs_per_acid"] * A
    r = p["p_co_bar"] / p["p_other_bar"]
    yi = p["co_feed_h2"] + p["co_feed_n2"]
    # CO feed so that CO in = acid + shift + CO vented with the non condensables
    F = (A + wgs * (1 + 2 * r)) / (p["co_purity"] - r * yi)
    f_co = {"CO": F * p["co_purity"], "H2": F * p["co_feed_h2"], "N2": F * p["co_feed_n2"]}
    h2_out = f_co["H2"] + wgs - m4
    if h2_out < 0:
        raise ValueError("methane make needs more hydrogen than the feed and shift supply")
    others = f_co["N2"] + h2_out + wgs + m4
    co_vent = r * others
    f_vent = {"CO": co_vent, "H2": h2_out, "N2": f_co["N2"], "CO2": wgs, "CH4": m4}
    net_water = wgs - m4  # consumed by the shift, made by methanation
    Wr = p["water_carry"] * A
    Rc = p["cat_recycle_ratio"] * A * MW("AcOH") / MW("AcOH")  # catalyst solution counted as acetic acid

    d = Design("acetic_acid", "Acetic acid plant (methanol carbonylation, iridium catalyst)", "AcOH",
               p["capacity_tpd"], region)
    d.route = ("Methanol and carbon monoxide react over an iridium iodide catalyst dissolved in acetic acid. The "
               "reactor liquid is flashed, the catalyst returns to the reactor, and the crude acid is dried and freed "
               "of heavy ends in three columns. The shift reaction and the vent are the only real losses.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of glacial acetic acid from {M * MW('MeOH') * 24 / 1000:,.0f} t/d of "
                 f"methanol and {_kg(f_co) * 24 / 1000:,.0f} t/d of CO gas.")

    def hl(c):
        return core.h_molar(c, T0, "l")

    def hg(c):
        return core.h_molar(c, T0, "g")

    dH_main = (hl("AcOH") - hl("MeOH") - hg("CO")) / 1000
    dH_wgs = (hg("CO2") + hg("H2") - hg("CO") - hl("H2O")) / 1000
    dH_ch4 = (hg("CH4") + hl("H2O") - hl("MeOH") - hg("H2")) / 1000
    d.reactions = [
        {"eq": "CH3OH + CO -> CH3COOH", "where": "Reactor, Ir/Ru iodide catalyst, liquid phase", "dH_kJ": dH_main},
        {"eq": "CO + H2O -> CO2 + H2", "where": "Reactor, side reaction", "dH_kJ": dH_wgs},
        {"eq": "CH3OH + H2 -> CH4 + H2O", "where": "Reactor, side reaction (by-products lumped)", "dH_kJ": dH_ch4},
    ]
    d.conditions = [
        ("Reactor", f"{p['T_C']:.0f} C, {PR_:.0f} bar, CO partial pressure about {p['p_co_bar']:.0f} bar"),
        ("Catalyst", "iridium with ruthenium promoter, methyl iodide co catalyst, about 5 wt% water"),
        ("Flash", "adiabatic, about 2 bar; catalyst solution recycled"),
        ("Columns", "light ends, drying and heavy ends, near atmospheric"),
    ]

    # ---------------------------------------------------------------- streams
    s_meoh = d.stream("Methanol", {"MeOH": M}, T0, PR_ + 2, phase="l")
    s_co = d.stream("Carbon monoxide", f_co, T0, p["co_supply_bar"], phase="g")
    s_cop = d.stream("CO to reactor", f_co, 313.15, PR_ + 1, phase="g")
    mk = max(net_water, 0.0)
    s_mk = d.stream("Make up water", {"H2O": mk}, T0, PR_ + 2, phase="l") if mk > 0 else None
    s_cat = d.stream("Catalyst solution recycle", {"AcOH": Rc}, 423.15, PR_, phase="l")
    s_wr = d.stream("Water and lights recycle", {"H2O": Wr}, 323.15, PR_, phase="l")
    f_rx = {"AcOH": A + Rc, "H2O": Wr + min(net_water, 0.0) * -1}
    s_rx = d.stream("Reactor liquid to flash", f_rx, TR, PR_, phase="l")
    s_vent = d.stream("High-pressure vent (after scrubbing)", f_vent, 313.15, PR_ - 1, phase="g")
    f_fv = {"AcOH": A, "H2O": f_rx["H2O"]}
    s_fv = d.stream("Flash vapour", f_fv, 413.15, 2.0, phase="g")
    s_wet = d.stream("Wet acid", f_fv, 393.15, 1.8, phase="l")
    s_dry = d.stream("Dry acid", {"AcOH": A}, 403.15, 1.5, phase="l")
    s_xw = d.stream("Excess water", {"H2O": -min(net_water, 0.0)}, 323.15, 1.5, phase="l") if net_water < 0 else None
    s_prod = d.stream("Glacial acetic acid", {"AcOH": Pout}, 313.15, 1.5, phase="l")
    s_heavy = d.stream("Heavy ends purge", {"AcOH": purge}, 433.15, 1.5, phase="l")

    d.feed(s_meoh, {"MeOH": "MeOH"})
    d.feed(s_co, {"CO": "CO"})
    if s_mk:
        d.feed(s_mk)
    d.out(s_prod, "product", {"AcOH": "AcOH"})
    d.out(s_vent, "fuel")
    d.out(s_heavy, "waste", treat_usd_t=50.0)
    if s_xw:
        d.out(s_xw, "waste", treat_usd_t=2.0)

    d.unit("C-101", "CO compressor", "compressor", [s_co], [s_cop], (0, 1))
    rx_in = [s_meoh, s_cop, s_cat, s_wr] + ([s_mk] if s_mk else [])
    d.unit("R-101", "Carbonylation reactor", "reactor", rx_in, [s_rx, s_vent], (1, 0),
           desc="Stirred tank, zirconium, external cooler raising steam")
    d.unit("V-101", "Flash vessel", "separator", [s_rx], [s_fv, s_cat], (2, 0))
    d.unit("T-101", "Light ends column", "column", [s_fv], [s_wet], (3, 0), desc="Methyl iodide and methyl acetate "
           "returned to the reactor (internal, not shown)")
    d.unit("T-102", "Drying column", "column", [s_wet], [s_dry, s_wr] + ([s_xw] if s_xw else []), (4, 0))
    d.unit("T-103", "Heavy ends column", "column", [s_dry], [s_prod, s_heavy], (5, 0))

    # ---------------------------------------------------------------- energy
    kw = lambda kmol_h, kJ_mol: kmol_h * kJ_mol * 1000 / 3600
    Q_rx = -kw(A, dH_main) - kw(wgs, dH_wgs) - kw(m4, dH_ch4)
    Q_flash = kw(A, th.hvap("AcOH", 413.15) / 1000) + kw(f_fv["H2O"], th.hvap("H2O", 413.15) / 1000)
    Q_left = max(Q_rx - Q_flash, 0.0)
    steam_rx = Q_left * p["rx_steam_frac"] / (H_LP_SAT - th.H_BFW_105C) * 3600
    d.steam(-steam_rx, "Reactor cooler raising 3 bar steam")
    d.cooling(Q_left * (1 - p["rx_steam_frac"]), "Reactor trim cooler")
    if Q_flash > Q_rx:
        d.steam((Q_flash - Q_rx) / LATENT * 3600, "Flash heater")
    # light ends column: the flash vapour is partly condensed overhead, 0.5 reflux of the acid (assumed)
    Q_le = kw(0.5 * A, th.hvap("AcOH", 391.15) / 1000)
    d.cooling(Q_le, "Light ends condenser")
    d.steam(Q_le / LATENT * 3600 * 0.3, "Light ends reboiler (vapour feed, small)")
    # drying column: water and some acid overhead
    V_dry = (Wr + max(-net_water, 0.0)) * (1 + p["reflux_drying"]) + 0.1 * A
    Q_dry = kw(V_dry, th.hvap("H2O", 373.15) / 1000)
    d.steam(Q_dry / LATENT * 3600, "Drying column reboiler")
    d.cooling(Q_dry, "Drying column condenser")
    V_hv = Pout * (1 + p["reflux_heavy"])
    Q_hv = kw(V_hv, th.hvap("AcOH", 391.15) / 1000)
    d.steam(Q_hv / LATENT * 3600, "Heavy ends column reboiler")
    d.cooling(Q_hv, "Heavy ends condenser")
    # vent burnt in the site boiler or flare: CO2 counted as direct
    vent_GJ = sum(n * th.lhv_molar(c) for c, n in f_vent.items() if c in ("CO", "H2", "CH4")) * 1000 / 1e9
    d.fuel_credit(vent_GJ, "HP vent burnt in the site boiler in place of gas",
                  co2_kg_h=(co_vent + m4 + wgs) * MW("CO2"))

    # ---------------------------------------------------------------- equipment
    V_liq = A / p["sty_kmol_m3_h"]
    d.vessel("R-101", "Carbonylation reactor", V_liq * 1.5, P_barg=PR_, material="SS", LD=2.0)
    d.power(V_liq * 1.0, "Reactor agitator (about 1 kW per m3 of liquid)")
    d.hx("E-101", "Reactor cooler and steam generator", Q_left, TR, TR - 15, 406.15, 406.15, "liquid-steam",
         P_barg=PR_, material="SS")
    d.vessel("V-101", "Flash vessel", max(_kg(f_rx) / 1000 * 0.1, 5.0), P_barg=2.0, material="SS")
    d.column("T-101", "Light ends column", 1.5 * A, 391.15, 1.8, 25, MW("AcOH"), material="SS")
    d.column("T-102", "Drying column", V_dry, 383.15, 1.6, 40, (MW("H2O") + MW("AcOH")) / 2, material="SS")
    d.column("T-103", "Heavy ends column", V_hv, 393.15, 1.5, 30, MW("AcOH"), material="SS")
    d.hx("E-102", "Drying column reboiler", Q_dry, 418.15, 418.15, 383.15, 388.15, "reboiler", material="SS")
    d.hx("E-103", "Heavy ends reboiler", Q_hv, 418.15, 418.15, 393.15, 398.15, "reboiler", material="SS")
    d.hx("E-104", "Column condensers", Q_le + Q_dry + Q_hv, 383.15, 373.15, 303.15, 313.15, "condenser", material="SS")
    d.compressor("C-101", "CO compressor", s_co, PR_ + 1, k=1.4, eta=0.78)
    d.vessel("T-104", "HP and LP vent scrubbers", max(_kg(f_vent) / 1000 * 0.5, 5.0), P_barg=PR_ - 1, material="SS")
    d.pump("P-101", "Methanol feed pump", M * MW("MeOH"), 790, PR_)
    d.pump("P-102", "Catalyst recycle pump", Rc * MW("AcOH"), 1000, PR_ - 1, material="SS")
    d.pump("P-103", "Water and lights recycle pump", _kg({"H2O": Wr}) * 3, 1000, PR_, material="SS")
    d.tank("TK-101", "Methanol tanks", M * MW("MeOH"), 790, days=p["storage_days"])
    d.tank("TK-102", "Acetic acid tanks", P_kg_h, 1049, days=p["storage_days"], material="SS")
    cw = d.cw_kW
    d.power(cw * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw, "Cooling water pumps and tower fans")
    d.power(0.05 * d.power_kW, "Compressed air, lighting, HVAC and flare (5% of process load)")

    # ---------------------------------------------------------------- KPIs and checks
    meoh_tt = M * MW("MeOH") / P_kg_h
    co_tt = F * p["co_purity"] * MW("CO") / P_kg_h
    util = A / (F * p["co_purity"]) * 100
    sel = A / M * 100
    steam_net = (d.steam_import_kg_h - d.steam_export_kg_h) / P_kg_h
    d.kpis = [
        {"label": "Methanol use", "value": meoh_tt, "unit": "t/t acid"},
        {"label": "CO use", "value": co_tt, "unit": "t/t acid"},
        {"label": "CO utilisation", "value": util, "unit": "%"},
        {"label": "Net steam", "value": steam_net, "unit": "t/t acid (negative = export)"},
        {"label": "Electricity", "value": d.power_kW / (P_kg_h / 1000), "unit": "kWh/t acid"},
    ]
    JM = "https://technology.matthey.com/article/44/3/94-105/"
    JMS = "Jones (BP Chemicals), The Cativa Process for the Manufacture of Acetic Acid, Platinum Metals Review 44(3), 2000"
    d.check("Selectivity on methanol", sel, 99, "%", JMS, JM, tol=1,
            note="Jones gives greater than 99% for the rhodium process and the Cativa process is at least as good. The "
                 "model value follows from the assumed methane and by-product loss, so this confirms the input only.")
    d.check("CO utilisation, Cativa", util, 94, "%", JMS, JM, tol=5,
            note="Jones: about 85% for Monsanto, above 94% for Cativa. Model loss = shift reaction plus CO carried "
                 "out with the vent at the assumed head space partial pressures.")
    d.check("CO per t acetic acid", co_tt, 0.47, "t/t", "Credence Research, Carbon Monoxide Plant Project Report 2026",
            "https://www.credenceresearch.com/plant-projects/carbon-monoxide-manufacturing-plant-project-report", tol=5,
            note="Contained CO only. The stoichiometric minimum is 0.466 t/t, so 0.47 implies about 99% CO "
                 "utilisation, above the 94% Jones gives for Cativa; the model follows Jones and reads high here.")
    tpy = p["capacity_tpd"] * d.hours / 24
    usd_m = 3852 / 7.1957
    d.check("Fixed capital, scaled from published project", None, usd_m * 1e6 * (tpy / 1e6) ** 0.7, "USD (2024)",
            "Chemwin news (April 2024): Shenghong Refining and Chemical, Lianyungang, 1,000,000 t/y acetic acid, "
            "total investment CNY 3,852 million including PSA hydrogen, low-temperature methanol wash and cryogenic "
            "CO units. Converted at 7.1957 CNY/USD (US Federal Reserve G.5A, 2024 average), exponent 0.7",
            "https://en.888chem.com/news/2/20955.html", tol=50, kind="capex",
            note="The published total includes making the CO from syngas, which this model buys over the fence, and "
                 "is a Chinese build cost; the model is a US grassroots Turton estimate.")

    d.assumptions = [
        "Catalyst metals, methyl iodide and methyl acetate stay inside the reactor, flash and light ends loop and are "
        "not shown as streams; the catalyst solution recycle is counted as acetic acid.",
        "Carbon monoxide comes over the fence from a cryogenic cold box at 98.5% CO, with hydrogen and nitrogen.",
        f"Shift reaction makes {p['wgs_per_acid']:.3f} mol CO2 per mol acid and {p['meoh_to_ch4'] * 100:.1f}% of the "
        "methanol goes to methane and lumped by-products such as propionic acid (assumed).",
        "CO lost with the vent follows from the inerts and by-product gases at an assumed 8 bar CO and 4 bar other "
        "gases in the reactor head space.",
        "Reactor and flash vessel are zirconium in practice; the cost method only has carbon and stainless steel, so "
        "they are costed as stainless steel and the capital reads low.",
        "Jones reports steam and cooling water about 30% below the rhodium process but no absolute figure, so steam "
        "is not checked against a number.",
        "The HP vent is burnt in the site boiler in place of gas; its CO2 counts as direct emissions.",
    ]
    d.hazop = [
        {"node": "CO compressor and feed", "deviation": "Loss of containment", "cause": "Seal or flange failure",
         "consequence": "Toxic carbon monoxide release (no smell), fire",
         "safeguard": "CO detectors, dry gas seals, ventilated compressor house, remote isolation"},
        {"node": "Reactor", "deviation": "Low CO partial pressure", "cause": "CO supply trip",
         "consequence": "Catalyst precipitates and is lost, corrosion rises",
         "safeguard": "CO flow and pressure trips, catalyst stabiliser, low water control"},
        {"node": "Reactor and flash", "deviation": "Wrong material or water upset", "cause": "Repairs in the wrong "
         "alloy, high iodide or water", "consequence": "Rapid iodide corrosion and leaks of hot acid",
         "safeguard": "Positive material identification, zirconium or Hastelloy, corrosion coupons"},
        {"node": "Acid storage", "deviation": "Release", "cause": "Tank or hose failure",
         "consequence": "Corrosive, flammable above 39 C", "safeguard": "Bunds, nitrogen blanket, PPE, safety showers"},
    ]
    d.greener = {
        "title": "Green methanol and CO2 based CO",
        "text": "Almost all the carbon footprint sits in the methanol and CO feeds. Methanol from captured CO2 and "
                "green hydrogen, and CO from CO2 by reverse shift or electrolysis, give a near zero carbon acid "
                "from the same plant.",
    }
    return d.finish()
