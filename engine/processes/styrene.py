"""Styrene by adiabatic dehydrogenation of ethylbenzene with superheated steam.

    C6H5C2H5 -> C6H5CH=CH2 + H2            (main, endothermic, equilibrium limited)
    C6H5C2H5 -> C6H6 + C2H4                (cracking)
    C6H5C2H5 + H2 -> C6H5CH3 + CH4         (hydrodealkylation)

Ethylbenzene is vaporised, mixed with steam superheated in a fired furnace and passed through two
radial flow adiabatic beds of potassium promoted iron oxide catalyst under vacuum, with a reheat
between the beds. The effluent heats the incoming ethylbenzene, raises the dilution steam in a waste
heat boiler and is condensed. The off gas (mainly hydrogen) is compressed and burnt in the furnace,
the water is stripped and reboiled to dilution steam, and the organic layer is distilled: benzene and
toluene off the top, unreacted ethylbenzene recycled from the EB/styrene splitter, and styrene finished
under vacuum with an inhibitor.

Benchmarks: US DOE Energy and Environmental Profile of the US Chemical Industry (2000), Table 4-6,
and the typical yield quoted on Wikipedia (Catalysis Reviews 1974).
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 1000.0,  # t/d styrene
    "per_pass_conversion": 0.65,  # EB converted per pass over two beds (assumed, typical classic adiabatic plant)
    "sel_styrene": 0.94,  # mol styrene per mol EB converted; Wikipedia typical yield 88 to 94%
    "sel_benzene": 0.035,  # rest of the converted EB to benzene + ethylene and toluene + methane (assumed split)
    "steam_oil_wt": 1.6,  # kg dilution steam per kg EB to the reactor (assumed, 1990s US plants 1.3 to 2)
    "inlet_T_C": 620.0,  # each bed inlet
    "outlet_T_C": 560.0,  # each bed outlet after the endothermic drop
    "reactor_P_bar": 0.5,
    "superheater_eff": 0.90,
    "condensate_reuse": 0.90,  # share of the process condensate stripped and reused as dilution steam
    "splitter_reflux": 7.0,  # EB/styrene splitter, reflux on distillate (close boilers, 136 and 145 C)
    "lhsv_h": 0.5,  # liquid EB per volume of catalyst per hour (assumed)
    "storage_days": 7,
}

GAS = ("H2", "CH4", "C2H4", "CO2")
H_LP_STEAM = 2750.0  # kJ/kg, saturated vapour at about 5 bar
H_COND_100 = 419.0  # kJ/kg, condensate at 100 C


def _h(flows, T, ph="g"):
    return sum(n * core.h_molar(c, T, ph) for c, n in flows.items()) / 3600.0  # kW


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    sty = P_kg_h / MW("Styrene")
    sS, sB = p["sel_styrene"], p["sel_benzene"]
    sT = 1 - sS - sB
    eb_conv = sty / sS  # EB reacted = fresh EB (all unreacted EB is recycled)
    benz, tol = sB * eb_conv, sT * eb_conv
    eb_rx = eb_conv / p["per_pass_conversion"]
    eb_rec = eb_rx - eb_conv
    h2 = sty - tol
    steam_kg = p["steam_oil_wt"] * eb_rx * MW("EB")
    w = steam_kg / MW("H2O")

    T0 = 298.15
    Tin = p["inlet_T_C"] + 273.15
    Tout = p["outlet_T_C"] + 273.15
    PR = p["reactor_P_bar"]

    f_fresh = {"EB": eb_conv}
    f_rec = {"EB": eb_rec}
    f_ebv = {"EB": eb_rx}
    f_steam = {"H2O": w}
    f_eff = {"EB": eb_rec, "Styrene": sty, "Benzene": benz, "Toluene": tol, "H2": h2, "CH4": tol, "C2H4": benz, "H2O": w}
    f_off = {"H2": h2, "CH4": tol, "C2H4": benz}
    f_org = {"EB": eb_rec, "Styrene": sty, "Benzene": benz, "Toluene": tol}
    f_bt = {"Benzene": benz, "Toluene": tol}
    f_cond = {"H2O": w}
    w_re = p["condensate_reuse"] * w
    f_cond_re = {"H2O": w_re}
    f_cond_out = {"H2O": w - w_re}
    f_mk = {"H2O": w - w_re}
    f_prod = {"Styrene": sty}

    d = Design("styrene", "Styrene plant (ethylbenzene dehydrogenation)", "Styrene", p["capacity_tpd"], region)
    d.route = ("Ethylbenzene is mixed with steam superheated to about 800 C and dehydrogenated over iron oxide catalyst in "
               "two adiabatic beds under vacuum. The product is condensed, the hydrogen rich off gas fuels the furnace, "
               "and styrene is separated from unreacted ethylbenzene, which is recycled.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of styrene from {eb_conv * MW('EB') * 24 / 1000:,.0f} t/d of "
                 f"ethylbenzene. The hydrogen off gas and {_kg(f_bt) * 24 / 1000:,.0f} t/d of benzene and toluene fire the superheater.")
    dH = lambda prods, reacts: (sum(core.h_molar(c, T0, "g") * n for c, n in prods)
                                - sum(core.h_molar(c, T0, "g") * n for c, n in reacts)) / 1000
    d.reactions = [
        {"eq": "C6H5C2H5 -> C6H5CH=CH2 + H2", "where": "Two adiabatic radial beds, K promoted Fe2O3",
         "dH_kJ": dH([("Styrene", 1), ("H2", 1)], [("EB", 1)])},
        {"eq": "C6H5C2H5 -> C6H6 + C2H4", "where": "Same beds, thermal and catalytic cracking",
         "dH_kJ": dH([("Benzene", 1), ("C2H4", 1)], [("EB", 1)])},
        {"eq": "C6H5C2H5 + H2 -> C6H5CH3 + CH4", "where": "Same beds",
         "dH_kJ": dH([("Toluene", 1), ("CH4", 1)], [("EB", 1), ("H2", 1)])},
    ]
    d.conditions = [
        ("Reactor beds", f"{p['inlet_T_C']:.0f} C in, about {p['outlet_T_C']:.0f} C out, {PR:.1f} bar, reheat between beds"),
        ("Steam to ethylbenzene", f"{p['steam_oil_wt']:.1f} kg/kg ({w / eb_rx:.1f} mol/mol)"),
        ("Per pass conversion", f"{p['per_pass_conversion'] * 100:.0f}% of the ethylbenzene"),
        ("Selectivity", f"{sS * 100:.0f}% styrene, {sB * 100:.1f}% benzene, {sT * 100:.1f}% toluene"),
        ("EB/styrene splitter", f"vacuum, reflux {p['splitter_reflux']:.0f} : 1, styrene below 100 C with inhibitor"),
    ]

    s_fresh = d.stream("Fresh ethylbenzene", f_fresh, T0, 3.0, phase="l")
    s_rec = d.stream("Recycled ethylbenzene", f_rec, 313.15, 3.0, phase="l")
    s_ebv = d.stream("Ethylbenzene vapour", f_ebv, 793.15, 1.0, phase="g")
    s_steam = d.stream("Dilution steam", f_steam, 423.15, 4.0, phase="g")
    s_feed = d.stream("Superheated steam to the beds", f_steam, 1073.15, PR + 0.3, phase="g")
    s_eff = d.stream("Reactor effluent", f_eff, Tout, PR, phase="g")
    s_off = d.stream("Off gas to furnace", f_off, 313.15, 1.3, phase="g")
    s_org = d.stream("Crude styrene", f_org, 313.15, 1.0, phase="l")
    s_cond = d.stream("Process condensate", f_cond, 313.15, 1.0, phase="l")
    s_bt = d.stream("Benzene and toluene to fuel", f_bt, 313.15, 2.0, phase="l")
    s_prod = d.stream("Styrene", f_prod, 298.15, 2.0, phase="l")
    s_cre = d.stream("Stripped condensate to steam drum", f_cond_re, 373.15, 5.0, phase="l")
    s_cout = d.stream("Condensate blowdown", f_cond_out, 313.15, 2.0, phase="l")
    s_mk = d.stream("Demin water make up", f_mk, T0, 5.0, phase="l")
    s_btm1 = d.stream("Ethylbenzene and styrene to splitter", {"EB": eb_rec, "Styrene": sty}, 360.15, 0.3, phase="l")
    s_btm2 = d.stream("Crude styrene to finishing", {"Styrene": sty}, 368.15, 0.2, phase="l")

    d.feed(s_fresh, {"EB": "EB"})
    d.feed(s_mk)
    d.out(s_prod, "product", {"Styrene": "Styrene"})
    d.out(s_bt, "fuel")
    d.out(s_off, "fuel")
    d.out(s_cout, "waste", treat_usd_t=2.0)
    d.demin = (w - w_re) * MW("H2O")

    d.unit("H-101", "Steam superheater and reheat furnace", "furnace", [s_steam, s_off], [s_feed], (1, 1))
    d.unit("E-101", "EB vaporiser and feed effluent exchanger", "hx", [s_fresh, s_rec], [s_ebv], (0, 0))
    d.unit("R-101", "Dehydrogenation reactors (2 beds)", "reactor", [s_ebv, s_feed], [s_eff], (2, 0),
           desc="Radial flow, adiabatic, under vacuum")
    d.unit("S-101", "Effluent condenser and three phase separator", "separator", [s_eff], [s_off, s_org, s_cond], (3, 0))
    d.unit("T-104", "Condensate stripper", "column", [s_cond], [s_cre, s_cout], (3, 1))
    d.unit("E-103", "Waste heat boiler and steam drum", "exchanger", [s_cre, s_mk], [s_steam], (2, 1))
    d.unit("T-101", "Benzene and toluene column", "column", [s_org], [s_bt, s_btm1], (4, 0))
    d.unit("T-102", "EB/styrene splitter", "column", [s_btm1], [s_rec, s_btm2], (5, 0))
    d.unit("T-103", "Styrene finishing column", "column", [s_btm2], [s_prod], (6, 0))

    # ---------------------------------------------------------------- energy
    # furnace: dilution steam from 150 C to the superheat needed, plus the reheat between the beds.
    # Overall, the furnace supplies H(effluent at outlet T) - H(EB vapour at 520 C) - H(steam at 150 C).
    Q_furnace = _h(f_eff, Tout) - _h(f_ebv, 793.15) - _h(f_steam, 423.15)
    fuel_GJ = Q_furnace / p["superheater_eff"] * 3600 / 1e6
    f_burn = dict(f_off, **f_bt)
    off_GJ = sum(n * 1000 * th.lhv_molar(c) for c, n in f_burn.items()) / 1e9
    off_co2 = (f_off["CH4"] + 2 * f_off["C2H4"] + 6 * benz + 7 * tol) * MW("CO2")
    used_off = min(off_GJ, fuel_GJ)
    d.fuel_credit(used_off, "Off gas, benzene and toluene burnt in the superheater", co2_kg_h=off_co2 * used_off / off_GJ)
    d.fuel(fuel_GJ, "Superheater and reheater firing")
    # EB vaporiser on LP steam, then superheated to 520 C against the effluent
    Q_vap = _h({"EB": eb_conv}, 409.15, "g") - _h({"EB": eb_conv}, T0, "l") + _h(f_rec, 409.15, "g") - _h(f_rec, 313.15, "l")
    Q_ix = _h(f_ebv, 793.15) - _h(f_ebv, 409.15)
    mcp_eff = (_h(f_eff, Tout) - _h(f_eff, 573.15)) / (Tout - 573.15)
    T_after_ix = Tout - Q_ix / mcp_eff
    # waste heat boiler raises the dilution steam from stripped condensate; effluent cooled to 150 C
    Q_whb = _h(f_eff, T_after_ix) - _h(f_eff, 423.15)
    Q_dil = w * MW("H2O") * (H_LP_STEAM - H_COND_100) / 3600
    d.steam(Q_vap / 2100 * 3600, "Ethylbenzene vaporiser")
    d.steam((Q_dil - Q_whb) / 2100 * 3600, "Dilution steam not covered by the waste heat boiler")
    Q_cool = _h(f_eff, 423.15) - (_h(f_off, 313.15) + _h(f_org, 313.15, "l") + _h(f_cond, 313.15, "l"))
    d.cooling(Q_cool * 0.3, "Effluent trim cooler (the rest on air coolers)")
    # distillation
    Q_bt = (_kg(f_bt) / 1000) * 3.0 * 360 / 3.6  # reflux 3 on the light cut, latent heat about 360 kJ/kg
    D_sp = eb_rec + benz * 0.0
    Q_split = D_sp * th.hvap("EB") / 3600 * (1 + p["splitter_reflux"])
    Q_fin = sty * th.hvap("Styrene") / 3600 * 1.5
    Q_strip = (w - w_re) * 0 + w_re * MW("H2O") * 0.05 * 2100 / 3600  # stripping steam 5% of condensate
    d.steam(Q_bt / 2100 * 3600, "Benzene and toluene column reboiler")
    d.steam(Q_split / 2100 * 3600, "EB/styrene splitter reboiler")
    d.steam(Q_fin / 2100 * 3600, "Styrene finishing column reboiler")
    d.steam(Q_strip / 2100 * 3600, "Condensate stripper")
    d.cooling(Q_bt + Q_split + Q_fin, "Column condensers")
    steam_kg_h = (Q_vap + max(0.0, Q_dil - Q_whb) + Q_bt + Q_split + Q_fin + Q_strip) / 2100 * 3600

    # ---------------------------------------------------------------- equipment
    V_eb_m3_h = eb_rx * MW("EB") / 867
    Vcat = V_eb_m3_h / p["lhsv_h"]
    for i in (1, 2):
        it = d.generic(f"R-10{i}", f"Dehydrogenation bed {i} (radial flow)", "vessel_vertical", Vcat / 2 * 1.6,
                       f"{Vcat / 2:,.0f} m3 catalyst", material="SS", note=f"LHSV {p['lhsv_h']} 1/h on liquid EB")
        it["catalyst_m3"] = Vcat / 2
    d.heater("H-101", "Steam superheater and interbed reheater", Q_furnace, material="SS")
    d.hx("E-101", "Feed and effluent exchanger", Q_ix, Tout, T_after_ix, 409.15, 793.15, "gas-gas", material="SS")
    d.hx("E-102", "Ethylbenzene vaporiser", Q_vap, 433.15, 433.15, T0, 409.15, "reboiler")
    d.hx("E-103", "Waste heat boiler", max(Q_whb, 1.0), T_after_ix, 423.15, 373.15, 425.15, "gas-steam")
    d.generic("E-104", "Effluent air cooler and trim condenser", "hx_fixed_tube", Q_cool / (0.35 * 30),
              f"{Q_cool / 1000:,.1f} MW", note="Condensing duty, U 350 W/m2K, LMTD 30 K")
    d.flash_drum("V-101", "Three phase separator", s_off, _kg(f_org) + _kg(f_cond), 0.0)
    d.compressor("C-101", "Off gas compressor", d.stream("Off gas from separator", f_off, 313.15, PR - 0.1, phase="g"), 1.5,
                 k=1.4, eta=0.72)
    d.streams.pop()  # sizing only
    d.column("T-101", "Benzene and toluene column", (benz + tol) * 4.0, 360.15, 1.2, 30, 85.0)
    d.column("T-102", "EB/styrene splitter", D_sp * (1 + p["splitter_reflux"]), 350.15, 0.15, 80, MW("EB"), packed=True)
    d.column("T-103", "Styrene finishing column", sty * 1.5, 355.15, 0.1, 15, MW("Styrene"), packed=True)
    d.column("T-104", "Condensate stripper", w * 0.05, 373.15, 1.2, 10, 18.0)
    d.hx("E-105", "Splitter reboiler", Q_split, 433.15, 433.15, 365.15, 368.15, "reboiler")
    d.hx("E-106", "Splitter condenser", Q_split, 350.15, 345.15, 303.15, 313.15, "condenser")
    d.compressor("C-102", "Vacuum system for splitter and finishing column",
                 d.stream("Vacuum load", {"H2O": 2.0, "H2": 0.5}, 313.15, 0.1, phase="g"), 1.1, k=1.3, eta=0.5)
    d.streams.pop()
    days = p["storage_days"]
    d.tank("TK-101", "Ethylbenzene tank", eb_conv * MW("EB"), 867, days=days)
    d.tank("TK-102", "Styrene tanks (chilled, inhibited)", P_kg_h, 906, days=days)
    d.tank("TK-103", "Benzene and toluene tank", _kg(f_bt), 870, days=days)
    d.pump("P-101", "EB feed pump", eb_rx * MW("EB"), 867, 3)
    d.pump("P-102", "Splitter reflux pump", D_sp * MW("EB") * (1 + p["splitter_reflux"]), 830, 3)
    d.pump("P-103", "Styrene product pump", P_kg_h, 906, 3)
    d.pump("P-104", "Condensate pump", w * MW("H2O"), 990, 6)
    cw = d.cw_kW
    d.power(cw * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw, "Cooling water pumps and tower fans")
    d.power(Q_cool * 0.7 * 0.01, "Air cooler fans")
    d.power(P_kg_h / 1000 * 3.0, "Styrene chilling and inhibitor dosing")

    # ---------------------------------------------------------------- KPIs and checks
    eb_tt = eb_conv * MW("EB") / P_kg_h
    hhv_eb = th.lhv_molar("EB") / 1000 + 5 * th.hvap("H2O") / 1000  # kJ/mol, 5 H2O per EB burnt
    feed_btu = eb_conv * hhv_eb * 1000 / (P_kg_h) / 2.326  # Btu per lb styrene
    proc_GJ_h = fuel_GJ + steam_kg_h * 2.1 / 1000 / 0.85  # furnace fuel plus fuel to raise the imported steam
    proc_btu = proc_GJ_h * 1e6 / P_kg_h / 2.326
    d.kpis = [
        {"label": "Ethylbenzene use", "value": eb_tt, "unit": "t/t styrene"},
        {"label": "Styrene selectivity", "value": sS * 100, "unit": "%"},
        {"label": "Per pass conversion", "value": p["per_pass_conversion"] * 100, "unit": "%"},
        {"label": "Superheater fuel", "value": fuel_GJ / (P_kg_h / 1000), "unit": "GJ/t styrene"},
        {"label": "Off gas and BT share of furnace fuel", "value": used_off / max(fuel_GJ, 1e-9) * 100, "unit": "%"},
        {"label": "Steam", "value": steam_kg_h / P_kg_h, "unit": "t/t styrene"},
        {"label": "Process energy", "value": proc_GJ_h / (P_kg_h / 1000), "unit": "GJ/t styrene"},
    ]
    DOE = "https://www.osti.gov/servlets/purl/1218625"
    DOES = "US DOE, Energy and Environmental Profile of the US Chemical Industry (2000), Table 4-6"
    WIKI = "https://en.wikipedia.org/wiki/Styrene"
    d.check("Styrene yield from EB dehydrogenation", sS * 100, [88, 94], "%", "Styrene, Wikipedia (citing Catalysis Reviews 1974)",
            WIKI, tol=0, note="Model selectivity on ethylbenzene converted.")
    d.check("Ethylbenzene per lb styrene", eb_tt, 1.085, "lb/lb", DOES, DOE, tol=3,
            note="DOE footnote d, from Brown 1996. Unreacted ethylbenzene is recycled, so this is the net use.")
    d.check("Heat of combustion of the ethylbenzene feed", feed_btu, 20058, "Btu/lb styrene", DOES, DOE, tol=3,
            note="Model uses the gross (higher) heat of combustion of ethylbenzene.")
    d.check("Net process energy", proc_btu, [14370, 19412], "Btu/lb styrene", DOES, DOE, tol=20,
            note="US 1997 range: furnace fuel plus fuel to raise the steam. The model reads low because it assumes "
                 "modern heat recovery (waste heat boiler raises the dilution steam, off gas fires the furnace) that "
                 "many 1990s US plants did not have.")
    d.assumptions = [
        f"Selectivity {sS * 100:.0f}% to styrene; the losses are split {sB * 100:.1f}% to benzene and ethylene and "
        f"{sT * 100:.1f}% to toluene and methane. Tar and coke make are not modelled.",
        f"Per pass conversion {p['per_pass_conversion'] * 100:.0f}% over two beds at {p['inlet_T_C']:.0f} C inlet; "
        "all unreacted ethylbenzene is recovered in the splitter and recycled.",
        f"Steam to oil ratio {p['steam_oil_wt']:.1f} kg/kg, raised from stripped process condensate in a waste heat "
        "boiler on the effluent, with LP steam topping up any shortfall.",
        "The hydrogen rich off gas is compressed and burnt in the superheater; natural gas covers the balance.",
        "Benzene and toluene are burnt in the superheater; in an integrated complex they go back to the ethylbenzene unit.",
        f"Condensate reuse {p['condensate_reuse'] * 100:.0f}%, with the blowdown sent to treatment.",
    ]
    d.hazop = [
        {"node": "Reactor and furnace", "deviation": "Air ingress under vacuum", "cause": "Flange or expansion joint leak",
         "consequence": "Hydrogen rich flammable mixture in hot equipment", "safeguard": "Oxygen analysers on the off gas, steam purge, trips"},
        {"node": "Superheater", "deviation": "Loss of steam flow", "cause": "Steam drum level or control valve fault",
         "consequence": "Tube overheating and rupture", "safeguard": "Low flow trip on the fuel, tube skin thermocouples"},
        {"node": "EB/styrene splitter", "deviation": "High temperature", "cause": "Loss of vacuum or inhibitor",
         "consequence": "Styrene polymerises in the column, fouling or a runaway", "safeguard": "Inhibitor dosing, temperature trips, vacuum alarms"},
        {"node": "Styrene storage", "deviation": "High temperature", "cause": "Chiller failure in hot weather",
         "consequence": "Self heating runaway polymerisation", "safeguard": "Chilled storage below 20 C, TBC inhibitor with dissolved oxygen checks, short pinch storage"},
    ]
    d.greener = {
        "title": "Oxidative reheat and lower steam ratios",
        "text": "Burning part of the hydrogen with oxygen between the beds reheats the gas and lifts per pass conversion "
                "past 80%, and modern catalysts run at steam to oil ratios near 1, cutting the superheater fuel.",
    }
    return d.finish()
