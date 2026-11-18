"""Ammonia from natural gas: steam reforming + Haber-Bosch synthesis loop.

Every composition below is solved, not assumed: reformer, secondary reformer,
shift and synthesis outlets are ideal gas chemical equilibria computed from
NIST/chemicals formation data; the loop recycle and purge are converged
numerically; the steam system is balanced from the computed heat duties.
"""
import math

from .. import core
from .. import thermo as th
from ..design import Design

SMR = {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3}
WGS = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}
NH3R = {"N2": -1, "H2": -3, "NH3": 2}
AIR = {"N2": 0.7808, "O2": 0.2095, "Ar": 0.0093}  # dry air, mole fractions (CO2 neglected)

DEFAULTS = {
    "capacity_tpd": 2000.0,
    "steam_to_carbon": 3.3,
    "primary_T_C": 790.0,
    "reform_P_bar": 32.0,
    "loop_P_bar": 150.0,
    "converter_out_C": 450.0,
    "approach_C": 15.0,
    "inerts_loop_pct": 12.0,
    "separator_C": -5.0,
    "furnace_eff": 0.91,
}


_hin = core.hin
_adiabatic_eq = core.adiabatic_eq


def front_end(F_CH4, p):
    S = {}
    Pr = p["reform_P_bar"]
    feed = {"CH4": F_CH4}
    steam = {"H2O": F_CH4 * p["steam_to_carbon"]}
    mix = core.add(feed, steam)
    S["mix_T"] = 773.15
    T1 = p["primary_T_C"] + 273.15
    prim, _ = core.equilibrium(mix, [SMR, WGS], T1, Pr)
    Q_primary = _hin(prim, T1) - _hin(mix, 773.15)
    Q_preheat = _hin(mix, 773.15) - (_hin(feed, 298.15) + _hin(steam, 523.15))
    S.update(feed=feed, steam=steam, prim=prim, T1=T1, Q_primary=Q_primary, Q_preheat=Q_preheat)

    # secondary reformer: air rate so that (H2 + CO) / N2 = 3 at the outlet
    def secondary(air_kmol):
        air = {k: v * air_kmol for k, v in AIR.items()}
        Hin = _hin(prim, T1) + _hin(air, 823.15)
        # oxygen burns hydrogen first; the equilibrium then rebalances everything
        burn = dict(prim)
        burn["H2"] -= 2 * air["O2"]
        burn["H2O"] += 2 * air["O2"]
        burn = core.add(burn, {"N2": air["N2"], "Ar": air["Ar"]})
        T2, sec = _adiabatic_eq(burn, Hin, [SMR, WGS], Pr - 1, 1100, 1500)
        return air, T2, sec

    lo, hi = 0.2 * F_CH4, 3.0 * F_CH4
    for _ in range(50):
        a = (lo + hi) / 2
        air, T2, sec = secondary(a)
        r = (sec["H2"] + sec["CO"] - 3 * sec.get("CH4", 0)) / sec["N2"]
        if r > 3.0:
            lo = a
        else:
            hi = a
        if hi - lo < 1e-6 * F_CH4:
            break
    S.update(air=air, T2=T2, sec=sec)

    # waste heat boiler to 370 C, HT shift adiabatic, cool to 210 C, LT shift adiabatic
    Q_whb = _hin(sec, T2) - _hin(sec, 643.15)
    T_hts, hts = _adiabatic_eq(sec, _hin(sec, 643.15), [WGS], Pr - 2, 643.15, 800)
    Q_hts_cool = _hin(hts, T_hts) - _hin(hts, 483.15)
    T_lts, lts = _adiabatic_eq(hts, _hin(hts, 483.15), [WGS], Pr - 3, 483.15, 600)
    S.update(Q_whb=Q_whb, T_hts=T_hts, hts=hts, Q_hts_cool=Q_hts_cool, T_lts=T_lts, lts=lts)

    # cool to 40 C and knock out condensate (gas saturated with water at 40 C)
    dry = {c: n for c, n in lts.items() if c != "H2O"}
    y_w = core.psat("H2O", 313.15) / (Pr - 4)
    w_vap = y_w / (1 - y_w) * sum(dry.values())
    cond1 = {"H2O": lts["H2O"] - w_vap}
    gas40 = core.add(dry, {"H2O": w_vap})
    Q_lts_cool = _hin(lts, T_lts) - (_hin(gas40, 313.15) + sum(n * core.h_molar(c, 313.15, "l") for c, n in cond1.items()) / 3600.0)
    S.update(cond1=cond1, gas40=gas40, Q_lts_cool=Q_lts_cool)

    # CO2 removal (activated MDEA): 99.9% of CO2 to the stripper overhead
    co2_out = {"CO2": gas40["CO2"] * 0.999, "H2O": 0.0}
    gas_sw = dict(gas40)
    gas_sw["CO2"] -= co2_out["CO2"]
    S.update(co2=co2_out, gas_sw=gas_sw)

    # methanation, complete, preheated to 300 C
    meth = dict(gas_sw)
    co, co2 = meth.pop("CO", 0.0), meth.pop("CO2", 0.0)
    meth["H2"] -= 3 * co + 4 * co2
    meth["CH4"] = meth.get("CH4", 0.0) + co + co2
    meth["H2O"] = meth.get("H2O", 0.0) + co + 2 * co2
    Q_meth_pre = _hin(gas_sw, 573.15) - _hin(gas_sw, 313.15)
    T_meth = core.adiabatic_T(_hin(gas_sw, 573.15), meth, Pr - 5, 600)
    S.update(meth=meth, T_meth=T_meth, Q_meth_pre=Q_meth_pre, co_slip=co, co2_slip=co2)

    makeup = {c: n for c, n in meth.items() if c != "H2O"}
    cond2 = {"H2O": meth["H2O"]}
    S.update(makeup=makeup, cond2=cond2)
    return S


def loop(makeup, p):
    P = p["loop_P_bar"]
    T_out = p["converter_out_C"] + 273.15
    T_eq = T_out + p["approach_C"]
    T_sep = p["separator_C"] + 273.15
    y_nh3_v = core.psat("NH3", T_sep) / (P - 5)
    target = p["inerts_loop_pct"] / 100.0

    def run(purge_frac):
        rec = {}
        for _ in range(400):
            conv_in = core.add(makeup, rec)
            out, _ = core.equilibrium(conv_in, [NH3R], T_eq, P)
            non = {c: n for c, n in out.items() if c != "NH3"}
            nv = sum(non.values())
            nh3_v = y_nh3_v / (1 - y_nh3_v) * nv
            vap = core.add(non, {"NH3": nh3_v})
            liq = {"NH3": out["NH3"] - nh3_v}
            purge = core.scale(vap, purge_frac)
            new_rec = core.scale(vap, 1 - purge_frac)
            err = max(abs(new_rec.get(c, 0) - rec.get(c, 0)) for c in new_rec)
            rec = new_rec
            if err < 1e-7 * sum(makeup.values()):
                break
        return conv_in, out, vap, liq, purge, rec

    lo, hi = 0.001, 0.5
    for _ in range(50):
        pf = (lo + hi) / 2
        conv_in, out, vap, liq, purge, rec = run(pf)
        inert = (conv_in.get("CH4", 0) + conv_in.get("Ar", 0)) / sum(conv_in.values())
        if inert > target:
            lo = pf
        else:
            hi = pf
        if hi - lo < 1e-6:
            break
    return dict(conv_in=conv_in, out=out, vap=vap, liq=liq, purge=purge, rec=rec, purge_frac=pf,
                T_out=T_out, T_eq=T_eq, T_sep=T_sep, inert=inert)


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    target_kmol = p["capacity_tpd"] * 1000 / 24 / th.MW("NH3")

    # front end and loop are linear in feed, so one rescale hits the capacity exactly
    F = target_kmol * 0.6
    for _ in range(2):
        fe = front_end(F, p)
        lp = loop(fe["makeup"], p)
        F *= target_kmol / lp["liq"]["NH3"]
    fe = front_end(F, p)
    lp = loop(fe["makeup"], p)

    d = Design("ammonia", "Ammonia plant (natural gas, Haber-Bosch)", "Ammonia", p["capacity_tpd"], region)
    d.route = ("Steam methane reforming with a primary and an air blown secondary reformer, high and low "
               "temperature shift, CO2 removal with activated MDEA, methanation, then the Haber-Bosch synthesis "
               "loop on an iron catalyst with refrigerated ammonia recovery.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of liquid ammonia from natural gas. Typical of a single-train "
                 "world-scale plant.")
    d.reactions = [
        {"eq": "CH4 + H2O <=> CO + 3 H2", "where": "Primary and secondary reformer (Ni)", "dH_kJ": th.dh_rxn_gas(SMR) / 1000},
        {"eq": "CO + H2O <=> CO2 + H2", "where": "Shift converters (Fe-Cr, Cu-Zn)", "dH_kJ": th.dh_rxn_gas(WGS) / 1000},
        {"eq": "2 H2 + O2 -> 2 H2O", "where": "Secondary reformer burner", "dH_kJ": th.dh_rxn_gas({"H2": -2, "O2": -1, "H2O": 2}) / 1000},
        {"eq": "CO + 3 H2 -> CH4 + H2O", "where": "Methanator (Ni)", "dH_kJ": th.dh_rxn_gas({"CO": -1, "H2": -3, "CH4": 1, "H2O": 1}) / 1000},
        {"eq": "N2 + 3 H2 <=> 2 NH3", "where": "Ammonia converter (Fe)", "dH_kJ": th.dh_rxn_gas(NH3R) / 1000},
    ]
    Pr, PL = p["reform_P_bar"], p["loop_P_bar"]
    d.conditions = [
        ("Steam to carbon ratio", f"{p['steam_to_carbon']:.1f} mol/mol"),
        ("Primary reformer outlet", f"{p['primary_T_C']:.0f} C, {Pr:.0f} bar"),
        ("Secondary reformer outlet", f"{fe['T2'] - 273.15:.0f} C (adiabatic, solved)"),
        ("HT / LT shift outlet", f"{fe['T_hts'] - 273.15:.0f} C / {fe['T_lts'] - 273.15:.0f} C (adiabatic, solved)"),
        ("Synthesis loop", f"{PL:.0f} bar, converter outlet {p['converter_out_C']:.0f} C, approach {p['approach_C']:.0f} K"),
        ("Inerts in converter feed", f"{lp['inert'] * 100:.1f} mol% (purge {lp['purge_frac'] * 100:.2f}% of loop gas)"),
        ("Ammonia separator", f"{p['separator_C']:.0f} C"),
    ]

    # ---- streams
    s_ng = d.stream("Natural gas feed", fe["feed"], 298.15, 40)
    s_st = d.stream("Process steam", fe["steam"], 523.15, 40)
    s_air = d.stream("Process air", fe["air"], 298.15, 1.013)
    s_mix = d.stream("Reformer feed", core.add(fe["feed"], fe["steam"]), 773.15, Pr + 2)
    s_p = d.stream("Primary reformer outlet", fe["prim"], fe["T1"], Pr)
    s_air2 = d.stream("Compressed air", fe["air"], 823.15, Pr)
    s_sec = d.stream("Secondary reformer outlet", fe["sec"], fe["T2"], Pr - 1)
    s_whb = d.stream("Cooled reformed gas", fe["sec"], 643.15, Pr - 1.5)
    s_hts = d.stream("HT shift outlet", fe["hts"], fe["T_hts"], Pr - 2)
    s_lts_in = d.stream("LT shift inlet", fe["hts"], 483.15, Pr - 2.5)
    s_lts = d.stream("LT shift outlet", fe["lts"], fe["T_lts"], Pr - 3)
    s_c1 = d.stream("Process condensate", fe["cond1"], 313.15, Pr - 4, phase="l")
    s_raw = d.stream("Raw synthesis gas", fe["gas40"], 313.15, Pr - 4)
    s_co2 = d.stream("CO2 to vent or urea", fe["co2"], 313.15, 1.5)
    s_sw = d.stream("CO2 free gas", fe["gas_sw"], 313.15, Pr - 4.5)
    s_me = d.stream("Methanator outlet", fe["meth"], fe["T_meth"], Pr - 5)
    s_c2 = d.stream("Methanator condensate", fe["cond2"], 313.15, Pr - 5.5, phase="l")
    s_mu = d.stream("Make up gas", fe["makeup"], 313.15, Pr - 5.5)
    s_muc = d.stream("Compressed make up gas", fe["makeup"], 313.15, PL)
    s_cin = d.stream("Converter feed", lp["conv_in"], 473.15, PL)
    s_cout = d.stream("Converter outlet", lp["out"], lp["T_out"], PL - 3)
    s_sep = d.stream("Chilled loop gas", lp["out"], lp["T_sep"], PL - 5, phases={"NH3": "l"})
    s_rec = d.stream("Recycle gas", lp["rec"], lp["T_sep"], PL - 5)
    s_pg = d.stream("Purge gas to fuel", lp["purge"], lp["T_sep"], PL - 5)
    s_nh3 = d.stream("Liquid ammonia product", lp["liq"], 239.8, 1.013, phase="l")

    # flue gas from burning the purge (CO2 only from its CH4) and natural gas fuel is reported via fuel()
    d.feed(s_ng)  # natural gas is costed as a utility at the regional gas price, not as a raw material
    d.feed(s_st)
    d.feed(s_air)
    d.out(s_nh3, "product", {"NH3": "NH3"})
    d.out(s_co2, "emission")
    # process condensate is steam stripped and reused as boiler feed water (standard practice)
    d.out(s_c1, "waste", treat_usd_t=1.0)
    d.out(s_c2, "waste", treat_usd_t=1.0)
    # purge gas leaves the plant boundary as fuel (burnt in the reformer furnace)
    d.out(s_pg, "fuel")

    # ---- units (pos = column, row on the flow diagram)
    d.unit("D-101", "Desulphuriser", "reactor", [s_ng], [], (0, 0), desc="ZnO bed removes sulphur that would poison the reformer catalyst")
    d.unit("H-101", "Primary reformer", "furnace", [s_mix], [s_p], (1, 0), duty_kW=fe["Q_primary"],
           desc="Ni catalyst in fired tubes")
    d.unit("C-101", "Air compressor", "compressor", [s_air], [s_air2], (1, 1))
    d.unit("R-101", "Secondary reformer", "reactor", [s_p, s_air2], [s_sec], (2, 0), desc="Air burns part of the gas; adds the nitrogen")
    d.unit("E-101", "Waste heat boiler", "exchanger", [s_sec], [s_whb], (3, 0), duty_kW=-fe["Q_whb"])
    d.unit("R-102", "HT shift", "reactor", [s_whb], [s_hts], (4, 0))
    d.unit("E-102", "Shift cooler", "exchanger", [s_hts], [s_lts_in], (5, 0), duty_kW=-fe["Q_hts_cool"])
    d.unit("R-103", "LT shift", "reactor", [s_lts_in], [s_lts], (6, 0))
    d.unit("V-101", "Condensate separator", "drum", [s_lts], [s_raw, s_c1], (6, 1), duty_kW=-fe["Q_lts_cool"])
    d.unit("T-101", "CO2 absorber / stripper", "column", [s_raw], [s_sw, s_co2], (5, 1))
    d.unit("R-104", "Methanator", "reactor", [s_sw], [s_me], (4, 1))
    d.unit("V-102", "Make up gas drier", "drum", [s_me], [s_mu, s_c2], (3, 1))
    d.unit("C-102", "Syngas compressor", "compressor", [s_mu], [s_muc], (2, 1))
    d.unit("R-105", "Ammonia converter", "reactor", [s_muc, s_rec], [s_cout], (1, 2), desc="Three beds, iron catalyst, interbed cooling")
    d.unit("E-105", "Loop boiler and chillers", "exchanger", [s_cout], [s_sep], (2, 2))
    d.unit("V-103", "Ammonia separator", "drum", [s_sep], [s_rec, s_pg, s_nh3], (3, 2))
    s_cin.src, s_cin.dst = "mix", "R-105"

    # ---- heat and steam balance
    Q_prim = fe["Q_primary"]
    Q_pre = fe["Q_preheat"]
    fired_absorbed = Q_prim + Q_pre + fe["Q_meth_pre"] * 0  # methanator preheat by process gas
    purge_LHV = sum(n * (th.lhv_molar(c) or 0) for c, n in lp["purge"].items()) / 1e6  # kmol/h x J/mol = kJ/h, so /1e6 gives GJ/h
    purge_co2 = lp["purge"].get("CH4", 0) * th.MW("CO2")
    fuel_total_GJ_h = fired_absorbed / p["furnace_eff"] * 3.6 / 1000
    d.fuel_credit(purge_LHV, "Purge gas burnt in reformer", co2_kg_h=purge_co2)
    d.fuel(fuel_total_GJ_h, "Reformer furnace (incl. feed preheat)")

    # loop heat recovered as HP steam: converter outlet cooled to 330 C, then the feed / effluent
    # exchanger heats converter feed 40 -> 250 C (the rest of the preheat is inside the converter),
    # then cooling water to 40 C before the chillers
    T_after_boiler = 533.15  # loop boiler plus BFW preheater
    Q_loop = _hin(lp["out"], lp["T_out"]) - _hin(lp["out"], T_after_boiler)
    Q_fe = _hin(lp["conv_in"], 473.15) - _hin(lp["conv_in"], 313.15)
    T_after_fe = core.adiabatic_T(_hin(lp["out"], T_after_boiler) - Q_fe, lp["out"], PL, 450)
    Q_loop_cw = _hin(lp["out"], T_after_fe) - _hin(lp["out"], 313.15)
    # chilling and condensing: 40 C -> separator T, NH3 condensed
    Q_chill = (_hin(lp["out"], 313.15) - (_hin(lp["vap"], lp["T_sep"]) + sum(
        n * core.h_molar(c, lp["T_sep"], "l") for c, n in lp["liq"].items()) / 3600.0))
    COP = 2.4
    W_ref = Q_chill / COP
    Q_ref_cond = Q_chill + W_ref
    hs = th.H_STEAM_120BAR_510C - th.H_BFW_105C
    steam_raised = (fe["Q_whb"] + fe["Q_hts_cool"] * 0.85 + Q_loop) / hs * 3600  # kg/h
    d.steam(-steam_raised, "Waste heat boiler, shift cooler and loop boiler (HP steam)")
    proc_steam = fe["steam"]["H2O"] * th.MW("H2O")
    d.steam(proc_steam, "Process steam to reformer")
    # make up = boiler blowdown + process steam consumed, less process condensate recovered
    cond_t_h = (fe["cond1"]["H2O"] + fe["cond2"]["H2O"]) * th.MW("H2O") / 1000
    d.demin_water_m3_h = max(0.0, steam_raised / 1000 * 0.03 + proc_steam / 1000 - cond_t_h)

    # compressors on steam turbines; process steam is extracted from the HP turbine at 40 bar
    W_air, _ = d.compressor("C-101", "Air compressor", s_air, Pr + 1, driver="steam")
    W_syn, _ = d.compressor("C-102", "Syngas compressor", core.Stream("x", "", fe["makeup"], 313.15, Pr - 5.5), PL,
                            driver="steam")
    rec_s = core.Stream("x", "", lp["rec"], lp["T_sep"] + 40, PL - 5)
    W_rec, _ = d.compressor("C-103", "Recycle circulator", rec_s, PL + 3, driver="steam", stages=1)
    W_ref_kW = W_ref
    d._add("C-104", "Refrigeration compressor", "compressor", W_ref_kW, f"{W_ref_kW:,.0f} kW, NH3 refrigerant",
           note=f"Chilling duty {Q_chill:,.0f} kW, COP {COP}")
    d._add("C-104-T", "Refrigeration compressor steam turbine", "turbine_steam", W_ref_kW, f"{W_ref_kW:,.0f} kW shaft")
    d.steam(W_ref_kW / (0.30 * hs) * 3600, "Refrigeration compressor turbine")
    d.cooling(Q_ref_cond)
    # extraction credit: process steam passing the HP turbine 120 -> 40 bar does ~ 250 kJ/kg of work
    extraction_work = proc_steam / 3600 * 250.0
    credit = extraction_work / (0.30 * hs) * 3600
    d.steam(-credit, "Back pressure work from process steam extraction")

    # CO2 removal: aMDEA regeneration about 1.0 GJ/t CO2 supplied from LT shift outlet heat
    co2_t_h = fe["co2"]["CO2"] * th.MW("CO2") / 1000
    Q_regen = co2_t_h * 1.0e6 / 3600  # kW
    solvent_m3_h = co2_t_h * 15
    d.pump("P-101", "Lean solvent pump", solvent_m3_h * 1040, 1040, Pr)
    d.pump("P-102", "Boiler feed water pump", steam_raised, 950, 125)
    d.cooling(max(0.0, fe["Q_lts_cool"] - Q_regen))
    d.cooling(Q_regen)  # stripper overhead condenser
    d.cooling(fe["Q_hts_cool"] * 0.15)

    # steam balance: any deficit is made up by an auxiliary boiler on natural gas
    net = d.steam_import_kg_h - d.steam_export_kg_h
    if net > 0:
        aux_GJ_h = net * hs / 0.90 / 1e6
        d.fuel(aux_GJ_h, "Auxiliary boiler")
        d.steam(-net, "Auxiliary boiler")
    # natural gas feed is costed with fuel at the gas price
    feed_GJ_h = fe["feed"]["CH4"] * th.lhv_molar("CH4") / 1e6
    # feed carbon leaves as the CO2 vent (counted there) and in the purge flue gas (counted in fuel_credit)
    d.fuel(feed_GJ_h, "Natural gas feedstock", co2=False)

    # ---- equipment sizing and cost
    d.reactor_bed("D-101", "Desulphuriser (ZnO)", fe["feed"]["CH4"], 1500, Pr + 3)
    d.heater("H-101", "Primary reformer", Q_prim + Q_pre, P_barg=Pr + 1, kind="reformer")
    d.reactor_bed("R-101", "Secondary reformer", sum(fe["sec"].values()), 10000, Pr)
    d.hx("E-101", "Waste heat boiler", fe["Q_whb"], fe["T2"], 643.15, 590.0, 597.0, "boiler", P_barg=120)
    d.reactor_bed("R-102", "HT shift converter", sum(fe["sec"].values()), 3000, Pr - 1)
    d.hx("E-102", "HT shift effluent cooler (BFW preheat)", fe["Q_hts_cool"], fe["T_hts"], 483.15, 378.15, 473.15, "gas-water", P_barg=120)
    d.reactor_bed("R-103", "LT shift converter", sum(fe["hts"].values()), 3000, Pr - 2)
    d.hx("E-103", "LT shift effluent cooler", fe["Q_lts_cool"], fe["T_lts"], 313.15, 303.15, 373.15, "wet-gas", P_barg=Pr)
    d.flash_drum("V-101", "Process condensate separator", s_raw, fe["cond1"]["H2O"] * 18, Pr - 4)
    co2_raw_kmol = sum(fe["gas40"].values())
    d.column("T-101", "CO2 absorber", co2_raw_kmol, 313.15, Pr - 4, 12, 15.0, packed=True)
    d.column("T-102", "CO2 stripper", fe["co2"]["CO2"] * 2.0, 383.15, 1.8, 10, 30.0, packed=True)
    d.hx("E-104", "Stripper reboiler", Q_regen, fe["T_lts"], 400.0, 380.0, 385.0, "gas-steam", P_barg=Pr)
    d.reactor_bed("R-104", "Methanator", sum(fe["gas_sw"].values()), 7000, Pr - 5)
    d.hx("E-106", "Methanator feed preheater (HT shift effluent)", fe["Q_meth_pre"], fe["T_hts"], fe["T_hts"] - 60, 313.15, 573.15, "gas-gas", P_barg=Pr)
    d.reactor_bed("R-105", "Ammonia converter", sum(lp["conv_in"].values()), 12000, PL)
    d.hx("E-105", "Loop boiler and BFW preheater", Q_loop, lp["T_out"], T_after_boiler, 378.15, 597.0, "boiler", P_barg=PL)
    d.hx("E-107", "Converter feed / effluent exchanger", Q_fe, T_after_boiler, T_after_fe, 313.15, 473.15, "hp-gas", P_barg=PL)
    d.cooler_cw("E-109", "Loop water cooler", Q_loop_cw, T_after_fe, 313.15, P_barg=PL)
    d.hx("E-108", "Ammonia chillers", Q_chill, 313.15, lp["T_sep"], lp["T_sep"] - 10, lp["T_sep"] - 5, "condenser", P_barg=PL)
    d.flash_drum("V-103", "Ammonia separator", s_rec, 0, PL - 5)
    nh3_kg_h = lp["liq"]["NH3"] * th.MW("NH3")
    d.tank("TK-101", "Refrigerated ammonia storage", nh3_kg_h, 682, days=14, material="SS")

    # ---- KPIs
    prod_t_h = nh3_kg_h / 1000
    feed_GJ_t = feed_GJ_h / prod_t_h
    fuel_GJ_t = (d.gas_net_GJ_h - feed_GJ_h) / prod_t_h
    elec_GJ_t = d.power_kW * 3.6 / 1000 / prod_t_h
    export_GJ_t = d.steam_export_kg_h * 0  # all surplus already netted inside the steam balance
    total_GJ_t = feed_GJ_t + fuel_GJ_t + elec_GJ_t / 0.4
    co2_vent_t = fe["co2"]["CO2"] * th.MW("CO2") / 1000 / prod_t_h
    co2_flue_t = d.direct_co2_kg_h / 1000 / prod_t_h - co2_vent_t
    per_pass = (lp["out"]["NH3"] - lp["conv_in"].get("NH3", 0)) / 2 / lp["conv_in"]["N2"] * 100
    d.kpis = [
        {"label": "Natural gas, feed", "value": feed_GJ_t, "unit": "GJ/t NH3"},
        {"label": "Natural gas, fuel (net of purge)", "value": fuel_GJ_t, "unit": "GJ/t NH3"},
        {"label": "Total energy", "value": total_GJ_t, "unit": "GJ/t NH3"},
        {"label": "N2 conversion per pass", "value": per_pass, "unit": "%"},
        {"label": "NH3 at converter outlet", "value": lp["out"]["NH3"] / sum(lp["out"].values()) * 100, "unit": "mol%"},
        {"label": "Process CO2 (pure stream)", "value": co2_vent_t, "unit": "t/t NH3"},
        {"label": "Steam raised", "value": steam_raised / 1000 / prod_t_h, "unit": "t/t NH3"},
    ]

    # ---- validation vs published figures
    BAT = "https://www.fertilizerseurope.com/wp-content/uploads/2019/08/Booklet_1_final.pdf"
    IPCC = "https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/3_Volume3/V3_3_Ch3_Chemical_Industry.pdf"
    WIKI = "https://en.wikipedia.org/wiki/Haber_process"
    K400 = th.Kp(NH3R, 673.15) * 1.01325 ** 2
    d.check("Equilibrium constant N2 + 3H2 = 2NH3 at 400 C", K400, 1.64e-4, "atm^-2",
            "Haber process, Wikipedia (citing Brown, LeMay et al.)", WIKI, tol=5, kind="thermo")
    d.check("Natural gas feedstock", feed_GJ_t, 22.1, "GJ(LHV)/t NH3",
            "EFMA / Fertilizers Europe BAT Booklet No. 1", BAT, tol=15)
    d.check("Total energy, feed + fuel", feed_GJ_t + fuel_GJ_t, [28.8, 31.5], "GJ(LHV)/t NH3",
            "EFMA / Fertilizers Europe BAT Booklet No. 1, modern plants", BAT, tol=15)
    d.check("Total fuel + feedstock, modern European plant", feed_GJ_t + fuel_GJ_t, 30.2, "GJ(NCV)/t NH3",
            "IPCC 2006 Guidelines Vol 3 Ch 3, Table 3.1", IPCC, tol=15)
    d.check("CO2 generated per tonne NH3", co2_vent_t + co2_flue_t, 1.694, "t CO2/t NH3",
            "IPCC 2006 Guidelines Vol 3 Ch 3, Table 3.1", IPCC, tol=20)
    d.check("Single pass conversion in the synthesis loop", per_pass, 15, "%",
            "Haber process, Wikipedia (citing Clark, Chemguide)", WIKI, tol=50,
            note="Published figure is a rounded textbook value; real loops run 15 to 25%.")
    eur_usd_2004 = 1.2438
    capex_pub = 250e6 * eur_usd_2004 * 800.0 / 444.2 * (p["capacity_tpd"] / 2000) ** 0.7
    d.check("Fixed capital, scaled from published plant", None, capex_pub, "USD (2024)",
            "Uhde dual pressure process paper: EUR 250 million for 2,000 t/d (2004). Converted at 1.2438 USD/EUR "
            "(Fed G.5A 2004), CEPCI 444.2 to 800.0, six tenths style exponent 0.7 for other capacities",
            "https://ucpcdn.thyssenkrupp.com/_legacy/UCPthyssenkruppBAIS/assets.files/download_1/ammonia_2/uhde_publications_pdf_en_5000002.pdf",
            tol=50, kind="capex")

    d.assumptions = [
        "Natural gas is modelled as pure methane, already desulphurised.",
        "All gas phase reactors reach chemical equilibrium (ideal gas). The ammonia converter uses an approach to "
        f"equilibrium of {p['approach_C']:.0f} K.",
        "Loop gas leaving the separator is saturated with ammonia (Clausius Clapeyron vapour pressure). "
        "Gas dissolved in liquid ammonia is neglected.",
        "Purge gas is burnt in the reformer furnace; no hydrogen recovery unit.",
        f"Reformer furnace efficiency {p['furnace_eff'] * 100:.0f}% (radiant plus convection section).",
        "Compressors are driven by steam turbines (30% of HP steam enthalpy to shaft work, condensing). Process "
        "steam is extracted from the HP turbine at 40 bar.",
        "CO2 removal by activated MDEA, 99.9% removal, 1.0 GJ regeneration heat per t CO2 supplied by the LT "
        "shift effluent, 15 m3 solvent per t CO2.",
        "Refrigeration coefficient of performance 2.4.",
    ]
    d.hazop = [
        {"node": "Primary reformer", "deviation": "Low steam flow", "cause": "Steam valve failure, BFW pump trip",
         "consequence": "Carbon laying on catalyst, tube overheating and rupture, fire",
         "safeguard": "Low steam to carbon trip, tube skin thermocouples, burner management system"},
        {"node": "Secondary reformer", "deviation": "High air flow", "cause": "Air controller failure",
         "consequence": "Excess N2 and oxygen breakthrough, overtemperature, explosive mixture downstream",
         "safeguard": "Ratio control, high-temperature trip, O2 analyser on outlet"},
        {"node": "Methanator", "deviation": "High CO/CO2 slip", "cause": "CO2 absorber upset, LT shift deactivated",
         "consequence": "Runaway methanation exotherm (about 70 K per 1% CO2)",
         "safeguard": "High-temperature trip isolating feed, CO2 analyser at absorber outlet"},
        {"node": "Synthesis loop", "deviation": "High pressure", "cause": "Purge valve closed, inerts build up",
         "consequence": "Loss of containment of hydrogen and ammonia at 150 bar",
         "safeguard": "Pressure relief to flare, inert analyser and purge control"},
        {"node": "Ammonia storage", "deviation": "Loss of containment", "cause": "Overfill, refrigeration failure",
         "consequence": "Toxic ammonia cloud", "safeguard": "Double integrity tank, bund, boil off compressors, "
         "ammonia detectors, water curtains"},
    ]
    d.greener = {
        "title": "Green ammonia: electrolytic hydrogen + air separation",
        "text": "Swap the reformer, shifts and CO2 removal for water electrolysis (about 0.18 t H2 per t NH3) and a "
                "small air separation unit for nitrogen. Direct CO2 falls to near zero; the footprint then depends "
                "on the electricity. At about 50 kWh per kg H2 the electrolysers need roughly 9 to 10 MWh per t "
                "NH3, so it only beats natural gas on a low carbon grid or dedicated renewables.",
        "electricity_MWh_per_t": 0.1776 * 1000 * 52.5 / 1000 + 0.6,
    }
    return d.finish()
