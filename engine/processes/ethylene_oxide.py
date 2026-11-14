"""Ethylene oxide by direct oxidation of ethylene with oxygen over a silver catalyst.

    C2H4 + 1/2 O2 -> C2H4O              (selective)
    C2H4 + 3 O2   -> 2 CO2 + 2 H2O      (combustion)

Oxygen based process. Ethylene and oxygen are added to a methane ballasted cycle gas and pass
through a multitubular reactor at about 250 C and 20 bar, with boiling water on the shell side
raising steam. Ethylene oxide is scrubbed out of the reactor gas with water, stripped and refined.
The cycle gas goes through a hot potassium carbonate unit to remove the CO2 made by combustion and is
recompressed; a small purge keeps argon from the oxygen in check and is burnt as fuel. Oxygen comes
from an on site air separation unit.

Benchmarks: IPCC 2006 Guidelines Vol 3 Ch 3, Table 3.20 (feedstock use and CO2 against catalyst
selectivity) and the US DOE Energy and Environmental Profile of the US Chemical Industry (2000),
Table 2-5 (energy use in EO manufacture).
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 1000.0,  # t/d ethylene oxide
    "selectivity": 0.80,  # mol EO per mol ethylene converted; IPCC Table 3.20 oxygen process range 75 to 85%
    "per_pass_conversion": 0.10,  # ethylene converted per pass (assumed, typical 7 to 15%)
    "y_C2H4": 0.30,  # reactor inlet mole fractions (assumed, typical oxygen process)
    "y_O2": 0.08,
    "y_CO2": 0.01,
    "y_Ar": 0.05,
    "reactor_T_C": 250.0,  # Wikipedia: 200 to 300 C
    "reactor_P_bar": 20.0,  # Wikipedia: 1 to 3 MPa
    "o2_purity": 0.995,  # ASU product, the rest argon
    "asu_o2_recovery": 0.95,
    "co2_regen_GJ_t": 2.8,  # hot potassium carbonate regeneration steam, GJ per t CO2 (assumed)
    "rich_water_eo_wt": 0.025,  # EO in the rich absorber water (assumed)
    "stripping_steam_kg_kg": 1.0,  # open steam per kg EO stripped (assumed)
    "refining_reflux": 3.0,
    "ghsv_h": 4000.0,  # gas hourly space velocity on the catalyst (assumed)
    "storage_days": 2,
}

AIR = {"N2": 0.78084, "O2": 0.20946, "Ar": 0.00934 + 0.00036}  # CO2 lumped with argon
H_SAT_25BAR = 2802.0  # kJ/kg, saturated steam at 25 bar (224 C)
CYCLE = ("C2H4", "O2", "CO2", "Ar", "CH4")


def _h(flows, T, ph="g"):
    return sum(n * core.h_molar(c, T, ph) for c, n in flows.items()) / 3600.0


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    P = P_kg_h / MW("EO")
    S = p["selectivity"]
    R = P / S  # ethylene reacted
    Rc = R - P  # ethylene burnt
    O2u = 0.5 * P + 3 * Rc
    co2_made = 2 * Rc
    h2o_made = 2 * Rc

    # ---------------------------------------------------------------- cycle gas, closed form
    G = R / (p["per_pass_conversion"] * p["y_C2H4"])
    n_in = {"C2H4": p["y_C2H4"] * G, "O2": p["y_O2"] * G, "CO2": p["y_CO2"] * G, "Ar": p["y_Ar"] * G}
    n_in["CH4"] = G - sum(n_in.values())
    k = (1 - p["o2_purity"]) / p["o2_purity"]  # mol Ar per mol O2 in the oxygen
    # purge fraction phi of the recycle gas holds argon steady: phi n_Ar = k * fresh O2
    phi = k * O2u / (n_in["Ar"] - k * (n_in["O2"] - O2u))
    out_rx = {"C2H4": n_in["C2H4"] - R, "O2": n_in["O2"] - O2u, "CO2": n_in["CO2"] + co2_made, "Ar": n_in["Ar"],
              "CH4": n_in["CH4"], "EO": P, "H2O": h2o_made}
    # CO2 removal so that no fresh CO2 is needed: n_CO2 = (1 - phi) (n_CO2 + made - removed)
    co2_rm = n_in["CO2"] + co2_made - n_in["CO2"] / (1 - phi)
    rec = {c: out_rx[c] for c in CYCLE}
    rec["CO2"] -= co2_rm
    purge = {c: phi * v for c, v in rec.items()}
    back = {c: (1 - phi) * v for c, v in rec.items()}
    fresh_c2h4 = n_in["C2H4"] - back["C2H4"]
    fresh_o2 = n_in["O2"] - back["O2"]
    fresh_ar = n_in["Ar"] - back["Ar"]
    fresh_ch4 = n_in["CH4"] - back["CH4"]

    # ---------------------------------------------------------------- air separation
    air = fresh_o2 / (AIR["O2"] * p["asu_o2_recovery"])
    f_air = {c: air * y for c, y in AIR.items()}
    f_o2 = {"O2": fresh_o2, "Ar": fresh_ar}
    f_asu_vent = {"N2": f_air["N2"], "O2": f_air["O2"] - fresh_o2, "Ar": f_air["Ar"] - fresh_ar}

    T0 = 298.15
    TR = p["reactor_T_C"] + 273.15
    PR_ = p["reactor_P_bar"]

    d = Design("ethylene_oxide", "Ethylene oxide plant (oxygen based direct oxidation)", "Ethylene oxide",
               p["capacity_tpd"], region)
    d.route = ("Ethylene is oxidised with pure oxygen over a silver catalyst in a cooled tubular reactor. Ethylene oxide "
               "is washed out of the gas with water, stripped and distilled; the gas is cleaned of CO2 and recycled.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of ethylene oxide from {fresh_c2h4 * MW('C2H4') * 24 / 1000:,.0f} t/d of "
                 f"ethylene at {S * 100:.0f}% catalyst selectivity, with oxygen from an on site air separation unit.")
    dH1 = (core.h_molar("EO", T0, "g") - core.h_molar("C2H4", T0, "g")) / 1000
    dH2 = (2 * core.h_molar("CO2", T0, "g") + 2 * core.h_molar("H2O", T0, "g") - core.h_molar("C2H4", T0, "g")) / 1000
    d.reactions = [
        {"eq": "C2H4 + 1/2 O2 -> C2H4O", "where": "Multitubular reactor, silver on alumina", "dH_kJ": dH1},
        {"eq": "C2H4 + 3 O2 -> 2 CO2 + 2 H2O", "where": "Same reactor, side reaction", "dH_kJ": dH2},
    ]
    d.conditions = [
        ("Reactor", f"{p['reactor_T_C']:.0f} C, {PR_:.0f} bar, boiling water shell side"),
        ("Inlet gas", f"{p['y_C2H4'] * 100:.0f}% C2H4, {p['y_O2'] * 100:.0f}% O2, {p['y_CO2'] * 100:.0f}% CO2, "
                      f"{p['y_Ar'] * 100:.0f}% Ar, rest methane ballast"),
        ("Per pass conversion", f"{p['per_pass_conversion'] * 100:.0f}% of the ethylene"),
        ("Selectivity", f"{S * 100:.0f}% to ethylene oxide"),
        ("Reactor outlet EO", f"{P / sum(out_rx.values()) * 100:.1f} mol%"),
        ("Purge", f"{phi * 100:.2f}% of the recycle gas, burnt as fuel"),
    ]

    s_c2h4 = d.stream("Ethylene", {"C2H4": fresh_c2h4}, T0, PR_ + 2, phase="g")
    s_air = d.stream("Air", f_air, T0, 1.013, phase="g")
    s_vent = d.stream("ASU waste nitrogen", f_asu_vent, T0, 1.1, phase="g")
    s_o2 = d.stream("Oxygen", f_o2, 313.15, PR_ + 2, phase="g")
    s_ch4 = d.stream("Methane ballast make up", {"CH4": fresh_ch4}, T0, PR_ + 2, phase="g")
    s_in = d.stream("Reactor feed gas", n_in, 493.15, PR_, phase="g")
    s_out = d.stream("Reactor effluent", out_rx, TR + 10, PR_ - 1, phase="g")
    s_cyc = d.stream("Cycle gas to CO2 removal", {c: out_rx[c] for c in CYCLE}, 313.15, PR_ - 2, phase="g")
    s_back = d.stream("Recycle gas to compressor", back, 313.15, PR_ - 2, phase="g")
    s_purge = d.stream("Purge gas to fuel", purge, 313.15, PR_ - 2, phase="g")
    s_co2 = d.stream("CO2 vent (process CO2)", {"CO2": co2_rm}, 373.15, 1.2, phase="g")
    s_rich = d.stream("EO and water from absorber", {"EO": P, "H2O": h2o_made}, 313.15, PR_ - 1, phase="l")
    s_eo = d.stream("Ethylene oxide", {"EO": P}, 283.15, 3.0, phase="l")
    s_ww = d.stream("Water of reaction bleed", {"H2O": h2o_made}, 373.15, 2.0, phase="l")

    d.feed(s_c2h4, {"C2H4": "C2H4"})
    d.feed(s_air)
    d.feed(s_ch4)
    d.out(s_eo, "product", {"EO": "EO"})
    d.out(s_vent, "byproduct")
    d.out(s_co2, "emission")
    d.out(s_purge, "byproduct")
    d.out(s_ww, "waste", treat_usd_t=2.0)

    d.unit("A-101", "Air separation unit", "separator", [s_air], [s_o2, s_vent], (0, 1))
    d.unit("M-101", "Mixing station", "mixer", [s_c2h4, s_o2, s_ch4, s_back], [s_in], (1, 0))
    d.unit("R-101", "EO reactor", "reactor", [s_in], [s_out], (2, 0), desc="Multitubular, silver catalyst, boiling water shell")
    d.unit("T-101", "EO absorber", "column", [s_out], [s_rich, s_cyc], (3, 0))
    d.unit("T-102", "CO2 removal (hot carbonate)", "column", [s_cyc], [s_back, s_co2, s_purge], (3, 1))
    d.unit("T-103", "EO stripper and refining column", "column", [s_rich], [s_eo, s_ww], (4, 0))

    # ---------------------------------------------------------------- energy
    T_pre = 493.15  # feed heated to 220 C against the effluent
    # heat removed by the shell side water = reaction heat less the sensible rise of the gas from 220 C to the outlet
    Q_rx = -(_h(out_rx, TR + 10) - _h(n_in, T_pre))
    steam_rx = Q_rx * 0.95 / (H_SAT_25BAR - th.H_BFW_105C) * 3600
    d.steam(-steam_rx, "Reactor shell steam (25 bar saturated)")
    Q_fe = _h(n_in, T_pre) - _h(n_in, 313.15)
    mcp_o = (_h(out_rx, TR + 10) - _h(out_rx, 383.15)) / (TR + 10 - 383.15)
    d.cooling(_h(out_rx, TR + 10 - Q_fe / mcp_o) - _h(out_rx, 313.15), "Effluent cooler before the absorber")
    # EO stripping: rich water heated against lean water, steam for the approach and open stripping steam
    lean_kg = P_kg_h / p["rich_water_eo_wt"]
    Q_strip = lean_kg * 4.18 * 10 / 3600 + P_kg_h * p["stripping_steam_kg_kg"] * 2100 / 3600
    d.steam(Q_strip / 2100 * 3600, "EO stripper (approach and open steam)")
    d.cooling(lean_kg * 4.18 * 10 / 3600 + P_kg_h * p["stripping_steam_kg_kg"] * 2100 / 3600, "Lean water cooler and stripper condenser")
    Q_ref = P * th.hvap("EO") / 3600 * (1 + p["refining_reflux"])
    d.steam(Q_ref / 2100 * 3600, "EO refining column reboiler")
    d.cooling(Q_ref, "EO refining condenser (column at 4.5 bar, condensing near 45 C)")
    Q_chill = P_kg_h * 1.95 * 35 / 3600  # product chilled from 45 C to 10 C for storage
    co2_t_h = co2_rm * MW("CO2") / 1000
    d.steam(co2_t_h * p["co2_regen_GJ_t"] * 1e6 / 2100, "Hot carbonate regenerator")
    d.cooling(co2_t_h * p["co2_regen_GJ_t"] * 1e6 / 3600 * 0.6, "Carbonate regenerator overhead")
    # purge burnt in the site fuel system; methane make up bought as natural gas (carbon tracked in the streams)
    lhv = {c: th.lhv_molar(c) for c in ("C2H4", "CH4")}
    purge_GJ = sum(purge[c] * 1000 * lhv[c] for c in lhv) / 1e9
    purge_co2 = (2 * purge["C2H4"] + purge["CH4"] + purge["CO2"]) * MW("CO2")
    d.fuel(fresh_ch4 * 1000 * lhv["CH4"] / 1e9, "Methane ballast make up", co2=False)
    d.fuel_credit(purge_GJ, "Purge gas burnt as fuel", co2_kg_h=purge_co2)

    # ---------------------------------------------------------------- equipment
    d.reactor_bed("R-101", "EO reactor (multitubular)", G, p["ghsv_h"], PR_ - 1, material="CS")
    d.hx("E-101", "Reactor tubes to boiling water (shell side)", Q_rx, TR + 10, TR, 497.15, 497.15, "gas-steam", P_barg=PR_)
    mcp_out = (_h(out_rx, TR + 10) - _h(out_rx, 383.15)) / (TR + 10 - 383.15)
    T_fe_out = TR + 10 - Q_fe / mcp_out
    d.hx("E-102", "Feed and effluent interchanger", Q_fe, TR + 10, T_fe_out, 313.15, T_pre, "gas-gas", P_barg=PR_)
    Q_eff = _h(out_rx, T_fe_out) - _h(out_rx, 313.15)
    d.hx("E-103", "Effluent cooler", Q_eff, T_fe_out, 313.15, 303.15, 313.15, "gas-water", P_barg=PR_ - 1)
    d.column("T-101", "EO absorber", sum(out_rx.values()), 313.15, PR_ - 1, 12, _kg(out_rx) / sum(out_rx.values()), material="SS")
    d.column("T-102", "Carbonate absorber and regenerator", co2_rm * 20, 373.15, PR_ - 2, 20, 30.0)
    d.column("T-103", "EO stripper", P * 3, 383.15, 2.0, 15, 30.0, material="SS")
    d.column("T-104", "EO refining column", P * (1 + p["refining_reflux"]), 318.15, 4.5, 40, MW("EO"), material="SS")
    d.hx("E-105", "EO refining condenser", Q_ref, 318.15, 317.15, 303.15, 313.15, "condenser", material="SS")
    d.hx("E-106", "EO product chiller", Q_chill, 318.15, 283.15, 268.15, 273.15, "liquid-liquid", material="SS")
    d.compressor("C-101", "Cycle gas compressor", s_back, PR_ + 0.5, k=1.3, eta=0.78, stages=1)
    d.compressor("C-201", "ASU main air compressor", s_air, 6.0, k=1.4, eta=0.82)
    s_o2_lp = d.stream("Oxygen from cold box", f_o2, 293.15, 1.3, phase="g")
    d.compressor("C-202", "Oxygen compressor", s_o2_lp, PR_ + 2, k=1.4, eta=0.75)
    d.streams.remove(s_o2_lp)  # sizing only, the oxygen stream on the diagram is the delivered one
    d.generic("A-201", "ASU cold box and main exchanger", "hx_fixed_tube", max(10.0, air * 1000 / 3600 * 25),
              f"{fresh_o2 * MW('O2') * 24 / 1000:,.0f} t/d oxygen", material="SS",
              note="Plate fin exchangers and columns costed as stainless shell and tube area, 25 m2 per mol/s of air")
    d.hx("E-104", "Lean and rich water interchanger", lean_kg * 4.18 * 50 / 3600, 383.15, 333.15, 313.15, 363.15, "liquid-liquid", material="SS")
    d.pump("P-101", "Absorber water pump", lean_kg, 990, PR_, material="SS")
    d.pump("P-102", "Carbonate solution pump", co2_rm * MW("CO2") * 40, 1250, PR_)
    d.tank("TK-101", "EO product tanks (chilled, nitrogen padded)", P_kg_h, 880, days=p["storage_days"], material="SS",
           pressurised=True, P_barg=3.0)
    # cooling water and chilled water for the refining condenser
    cw = d.cw_kW
    d.power(cw * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw, "Cooling water pumps and tower fans")
    d.power(Q_chill / 3.0 + 0.002 * P_kg_h, "Refrigeration for product chilling and storage boil off (COP 3)")
    p_asu = sum(i["kW"] for i in d.power_items if i["label"] in ("ASU main air compressor", "Oxygen compressor"))
    d.power(0.05 * d.power_kW, "Compressed air, lighting, HVAC and flare (5% of process load)")

    # ---------------------------------------------------------------- KPIs and checks
    c2h4_tt = fresh_c2h4 * MW("C2H4") / P_kg_h
    co2_tt = co2_rm * MW("CO2") / P_kg_h
    kwh_t = d.power_kW / (P_kg_h / 1000)
    btu_lb_power = (d.power_kW - p_asu * 1.05) / (P_kg_h / 1000) * 3600 / 2.326 / 1000
    d.kpis = [
        {"label": "Ethylene use", "value": c2h4_tt, "unit": "t/t EO"},
        {"label": "Oxygen use", "value": fresh_o2 * MW("O2") / P_kg_h, "unit": "t/t EO"},
        {"label": "Process CO2 vented", "value": co2_tt, "unit": "t/t EO"},
        {"label": "Electricity", "value": kwh_t, "unit": "kWh/t EO"},
        {"label": "Net steam", "value": (d.steam_import_kg_h - d.steam_export_kg_h) / P_kg_h, "unit": "t/t EO (negative = export)"},
        {"label": "Purge", "value": phi * 100, "unit": "% of recycle gas"},
    ]
    IPCC = "https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/3_Volume3/V3_3_Ch3_Chemical_Industry.pdf"
    IPCCS = "IPCC 2006 Guidelines, Vol 3 Ch 3, Table 3.20 (from the EU IPPC LVOC BAT document)"
    DOE = "https://www.osti.gov/servlets/purl/1218625"
    DOES = "US DOE, Energy and Environmental Profile of the US Chemical Industry (2000), Table 2-5"
    d.check("Ethylene use at 80% selectivity, oxygen process", c2h4_tt, 0.80, "t C2H4 / t EO", IPCCS, IPCC, tol=3,
            note="Model includes the ethylene lost in the purge gas.")
    d.check("CO2 at 80% selectivity, oxygen process", co2_tt, 0.5, "t CO2 / t EO", IPCCS, IPCC, tol=5,
            note="CO2 removed in the hot carbonate unit; the purge carries a little more, which is burnt.")
    d.check("Electricity use, excluding oxygen supply", btu_lb_power, [360, 627], "Btu/lb EO", DOES, DOE, tol=10,
            note="US 1997 range. DOE counts the energy to make the oxygen as feedstock energy, so the ASU compressors "
                 "are left out here. The DOE table describes an air based plant, which needs extra purge compression; "
                 "an oxygen plant is expected at or below the low end.")
    d.assumptions = [
        f"Catalyst selectivity {S * 100:.0f}% (IPCC Table 3.20 gives 75 to 85% for the oxygen process). Small losses to "
        "acetaldehyde and to glycol in the stripper are not modelled.",
        "Cycle gas composition, per pass conversion and space velocity are typical published ranges, not one plant's data.",
        f"Oxygen from an on site cryogenic ASU at {p['o2_purity'] * 100:.1f}% purity; the argon it carries sets the purge.",
        f"CO2 removed in a hot potassium carbonate unit using {p['co2_regen_GJ_t']:.1f} GJ of steam per t CO2.",
        "Reactor heat raises saturated 40 bar steam on the shell side, credited at the regional steam price.",
        "The purge is burnt in the site fuel system; methane ballast make up is bought as natural gas.",
        "Product is high purity EO; no ethylene glycol unit is attached.",
    ]
    d.hazop = [
        {"node": "Oxygen mixing station", "deviation": "High oxygen concentration", "cause": "Oxygen flow control fault or loss of ethylene",
         "consequence": "Cycle gas inside the flammable envelope, deflagration in the reactor or piping",
         "safeguard": "Online O2 analysers with fast trip of the oxygen supply, mixing nozzle design, flame arresters"},
        {"node": "EO reactor", "deviation": "High temperature", "cause": "Loss of shell side water level, catalyst runaway",
         "consequence": "Runaway combustion, tube damage", "safeguard": "Steam drum level trips, temperature trips, inhibitor dosing"},
        {"node": "EO refining and storage", "deviation": "Contamination", "cause": "Rust, caustic or acid traces in storage",
         "consequence": "Runaway polymerisation or decomposition of liquid EO",
         "safeguard": "Stainless steel, nitrogen padding, refrigeration, temperature monitoring, water deluge"},
        {"node": "EO handling", "deviation": "Loss of containment", "cause": "Seal or flange failure",
         "consequence": "Toxic, carcinogenic and highly flammable vapour release",
         "safeguard": "Sealless pumps, gas detection, water curtains, remote isolation"},
    ]
    d.greener = {
        "title": "Higher selectivity catalyst and CO2 capture",
        "text": "Rhenium promoted silver catalysts run near 85 to 90% selectivity, cutting ethylene use and CO2. The CO2 "
                "from the carbonate unit is already a pure stream, ready for sale or storage at low cost.",
    }
    return d.finish()
