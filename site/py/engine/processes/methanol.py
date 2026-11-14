"""Methanol from natural gas: steam reforming + low pressure Cu/Zn synthesis loop.

Reformer and converter outlets are solved ideal gas equilibria. The loop recycle,
purge and crude methanol condensation (Raoult's law with Antoine vapour pressures)
are converged numerically. Distillation duty from a reflux ratio.
"""
from .. import core
from .. import thermo as th
from ..design import Design

SMR = {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3}
WGS = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}
MEOH_CO = {"CO": -1, "H2": -2, "MeOH": 1}

DEFAULTS = {
    "capacity_tpd": 2500.0,
    "steam_to_carbon": 3.0,
    "reformer_T_C": 880.0,
    "reformer_P_bar": 20.0,
    "loop_P_bar": 80.0,
    "converter_T_C": 250.0,
    "approach_C": 10.0,
    "recycle_ratio": 4.0,
    "reflux_ratio": 1.5,
    "furnace_eff": 0.92,
}

hin = core.hin


def front(F, p):
    Pr = p["reformer_P_bar"]
    feed = {"CH4": F}
    steam = {"H2O": F * p["steam_to_carbon"]}
    mix = core.add(feed, steam)
    T1 = p["reformer_T_C"] + 273.15
    ref, _ = core.equilibrium(mix, [SMR, WGS], T1, Pr)
    Q_ref = hin(ref, T1) - hin(mix, 773.15)
    Q_pre = hin(mix, 773.15) - (hin(feed, 298.15) + hin(steam, 523.15))
    vap, liq = core.condense(ref, 313.15, Pr - 2, ["H2O"])
    Q_cool_total = hin(ref, T1) - (hin(vap, 313.15) + sum(n * core.h_molar(c, 313.15, "l") for c, n in liq.items()) / 3600)
    Q_whb = hin(ref, T1) - hin(ref, 623.15)  # down to 350 C raising HP steam
    return dict(feed=feed, steam=steam, ref=ref, T1=T1, Q_ref=Q_ref, Q_pre=Q_pre, syn=vap, cond=liq,
                Q_whb=Q_whb, Q_low=Q_cool_total - Q_whb)


def loop(makeup, p):
    P = p["loop_P_bar"]
    T = p["converter_T_C"] + 273.15
    Teq = T + p["approach_C"]
    mk = sum(makeup.values())

    def run(pf):
        rec = {}
        for _ in range(500):
            cin = core.add(makeup, rec)
            out, _ = core.equilibrium(cin, [MEOH_CO, WGS], Teq, P)
            vap, liq = core.condense(out, 313.15, P - 3, ["MeOH", "H2O"])
            purge = core.scale(vap, pf)
            new = core.scale(vap, 1 - pf)
            err = max(abs(new.get(c, 0) - rec.get(c, 0)) for c in new)
            rec = new
            if err < 1e-8 * mk:
                break
        return cin, out, vap, liq, purge, rec

    lo, hi = 0.005, 0.9
    for _ in range(45):
        pf = (lo + hi) / 2
        cin, out, vap, liq, purge, rec = run(pf)
        if sum(rec.values()) / mk > p["recycle_ratio"]:
            lo = pf
        else:
            hi = pf
        if hi - lo < 1e-6:
            break
    return dict(cin=cin, out=out, vap=vap, liq=liq, purge=purge, rec=rec, pf=pf, T=T, Teq=Teq)


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    target = p["capacity_tpd"] * 1000 / 24 / th.MW("MeOH")
    purity_loss = 0.995  # 0.5% of methanol lost to fusel / bottoms / vents
    F = target * 1.5
    for _ in range(3):
        fe = front(F, p)
        lp = loop(fe["syn"], p)
        F *= target / (lp["liq"]["MeOH"] * purity_loss)
    fe = front(F, p)
    lp = loop(fe["syn"], p)
    Pr, PL = p["reformer_P_bar"], p["loop_P_bar"]

    crude = lp["liq"]
    meoh_prod = crude["MeOH"] * purity_loss
    product = {"MeOH": meoh_prod, "H2O": meoh_prod * 0.0005}
    bottoms = {"H2O": crude.get("H2O", 0) - product["H2O"], "MeOH": crude["MeOH"] - meoh_prod}
    dissolved = {c: n for c, n in crude.items() if c not in ("MeOH", "H2O")}

    d = Design("methanol", "Methanol plant (natural gas, low pressure synthesis)", "Methanol", p["capacity_tpd"], region)
    d.route = ("Steam methane reforming, heat recovery and compression, then a low pressure methanol loop on a "
               "copper zinc catalyst in a boiling water reactor, crude methanol separation and distillation.")
    d.summary = f"{p['capacity_tpd']:,.0f} t/d of AA grade methanol from natural gas."
    d.reactions = [
        {"eq": "CH4 + H2O <=> CO + 3 H2", "where": "Steam reformer (Ni)", "dH_kJ": th.dh_rxn_gas(SMR) / 1000},
        {"eq": "CO + H2O <=> CO2 + H2", "where": "Reformer and converter", "dH_kJ": th.dh_rxn_gas(WGS) / 1000},
        {"eq": "CO + 2 H2 <=> CH3OH", "where": "Methanol converter (Cu/Zn)", "dH_kJ": th.dh_rxn_gas(MEOH_CO) / 1000},
        {"eq": "CO2 + 3 H2 <=> CH3OH + H2O", "where": "Methanol converter (Cu/Zn)",
         "dH_kJ": th.dh_rxn_gas({"CO2": -1, "H2": -3, "MeOH": 1, "H2O": 1}) / 1000},
    ]
    syn = fe["syn"]
    SN = (syn["H2"] - syn["CO2"]) / (syn["CO"] + syn["CO2"])
    d.conditions = [
        ("Steam to carbon ratio", f"{p['steam_to_carbon']:.1f}"),
        ("Reformer outlet", f"{p['reformer_T_C']:.0f} C, {Pr:.0f} bar"),
        ("Make up gas stoichiometric number (H2-CO2)/(CO+CO2)", f"{SN:.2f} (ideal 2.0; excess H2 is purged as fuel)"),
        ("Synthesis loop", f"{PL:.0f} bar, converter {p['converter_T_C']:.0f} C, approach {p['approach_C']:.0f} K"),
        ("Recycle to make up ratio", f"{p['recycle_ratio']:.1f} (purge {lp['pf'] * 100:.1f}% of loop gas)"),
        ("Distillation reflux ratio", f"{p['reflux_ratio']:.1f}"),
    ]

    s_ng = d.stream("Natural gas feed", fe["feed"], 298.15, 25)
    s_st = d.stream("Process steam", fe["steam"], 523.15, 25)
    s_ref = d.stream("Reformed gas", fe["ref"], fe["T1"], Pr)
    s_cond = d.stream("Process condensate", fe["cond"], 313.15, Pr - 2, phase="l")
    s_syn = d.stream("Make up syngas", syn, 313.15, Pr - 2)
    s_sync = d.stream("Compressed make up gas", syn, 313.15, PL)
    s_cin = d.stream("Converter feed", lp["cin"], 493.15, PL)
    s_out = d.stream("Converter outlet", lp["out"], lp["T"], PL - 2)
    s_rec = d.stream("Recycle gas", lp["rec"], 313.15, PL - 3)
    s_pg = d.stream("Purge gas to reformer fuel", lp["purge"], 313.15, PL - 3)
    s_cr = d.stream("Crude methanol", crude, 313.15, PL - 3, phase="l")
    s_fl = d.stream("Let down gas", dissolved, 313.15, 5)
    s_pr = d.stream("Methanol product", product, 313.15, 1.5, phase="l")
    s_bt = d.stream("Column bottoms water", bottoms, 373.15, 1.5, phase="l")

    d.feed(s_ng)
    d.feed(s_st)
    d.out(s_pr, "product", {"MeOH": "MeOH"})
    d.out(s_cond, "waste", treat_usd_t=1.0)
    d.out(s_bt, "waste", treat_usd_t=2.0)
    d.out(s_pg, "fuel")
    d.out(s_fl, "fuel")

    d.unit("H-101", "Steam reformer", "furnace", [s_ng, s_st], [s_ref], (0, 0), duty_kW=fe["Q_ref"])
    d.unit("E-101", "Waste heat boiler and coolers", "exchanger", [s_ref], [s_syn, s_cond], (1, 0), duty_kW=-fe["Q_whb"])
    d.unit("C-101", "Syngas compressor", "compressor", [s_syn], [s_sync], (2, 0))
    d.unit("R-101", "Methanol converter", "reactor", [s_sync, s_rec], [s_out], (3, 0), desc="Boiling water reactor, Cu/Zn catalyst")
    d.unit("V-101", "Crude methanol separator", "drum", [s_out], [s_rec, s_pg, s_cr], (3, 1))
    d.unit("V-102", "Let down vessel", "drum", [s_cr], [s_fl], (2, 1))
    d.unit("T-101", "Methanol distillation", "column", [], [s_pr, s_bt], (1, 1))
    s_cin.src, s_cin.dst = "mix", "R-101"
    s_cr.dst = "T-101"

    # heat and steam
    hs = th.H_STEAM_120BAR_510C - th.H_BFW_105C
    hs_mp = th.H_STEAM_40BAR_450C - th.H_BFW_105C
    purge_GJ = sum(n * (th.lhv_molar(c) or 0) for c, n in core.add(lp["purge"], dissolved).items()) / 1e6
    purge_co2 = (lp["purge"].get("CH4", 0) + lp["purge"].get("CO", 0) + lp["purge"].get("CO2", 0) + lp["purge"].get("MeOH", 0)
                 + dissolved.get("CH4", 0) + dissolved.get("CO", 0) + dissolved.get("CO2", 0)) * th.MW("CO2")
    d.fuel_credit(purge_GJ, "Purge and let down gas burnt in reformer", co2_kg_h=purge_co2)
    d.fuel((fe["Q_ref"] + fe["Q_pre"]) / p["furnace_eff"] * 3.6 / 1000, "Reformer furnace (incl. feed preheat)")
    # converter heat raises saturated MP steam in the boiling water reactor
    Q_conv = hin(lp["cin"], 493.15) - hin(lp["out"], lp["T"])  # exotherm plus feed heat up to 250 C
    Q_rxn = hin(lp["cin"], lp["T"]) - hin(lp["out"], lp["T"])
    steam_bwr = Q_rxn / (2801.5 - 441.2) * 3600  # saturated 24 bar steam
    steam_whb = fe["Q_whb"] / hs * 3600
    d.steam(-steam_whb, "Reformed gas waste heat boiler (HP steam)")
    d.steam(-steam_bwr, "Boiling water converter (saturated MP steam)")
    proc = fe["steam"]["H2O"] * th.MW("H2O")
    d.steam(proc, "Process steam to reformer")
    # loop feed/effluent: converter outlet heats converter feed to 220 C
    Q_fe = hin(lp["cin"], 493.15) - hin(lp["cin"], 313.15)
    T_after_fe = core.adiabatic_T(hin(lp["out"], lp["T"]) - Q_fe, lp["out"], PL, 380)
    # distillation reboiler: (R + 1) x distillate x latent heat, LP steam from low grade reformed gas heat
    hv = th.hvap("MeOH", 337.8)
    Q_reb = (p["reflux_ratio"] + 1) * meoh_prod * 1000 * hv / 3.6e6  # kW
    Q_cond = Q_reb
    low_grade_for_reboiler = min(Q_reb, fe["Q_low"] * 0.5)
    lp_steam = (Q_reb - low_grade_for_reboiler) / 2100.0 * 3600
    d.steam(lp_steam, "Distillation reboiler (balance after reformed gas heat)")
    d.cooling(Q_cond, "Column condenser")
    d.cooling(fe["Q_low"] - low_grade_for_reboiler, "Reformed gas final cooling")

    Q_crude_cool = (hin(lp["out"], T_after_fe) - (hin(lp["vap"], 313.15) +
                    sum(n * core.h_molar(c, 313.15, "l") for c, n in crude.items()) / 3600))
    d.compressor("C-101", "Syngas compressor", core.Stream("x", "", syn, 313.15, Pr - 2), PL, driver="steam")
    d.compressor("C-102", "Recycle circulator", core.Stream("x", "", lp["rec"], 313.15, PL - 3), PL + 2, driver="steam", stages=1)
    d.pump("P-101", "Boiler feed water pump", steam_whb + steam_bwr, 950, 125)
    d.pump("P-102", "Methanol product pump", meoh_prod * 32.04, 790, 5)

    net = d.steam_import_kg_h - d.steam_export_kg_h
    if net > 0:
        d.fuel(net * hs_mp / 0.9 / 1e6, "Auxiliary boiler")
        d.steam(-net, "Auxiliary boiler")
    feed_GJ = fe["feed"]["CH4"] * th.lhv_molar("CH4") / 1e6
    d.fuel(feed_GJ, "Natural gas feedstock", co2=False)
    cond_t = sum(fe["cond"].values()) * 18.015 / 1000
    d.demin_water_m3_h = max(0.0, (steam_whb + steam_bwr) / 1000 * 0.03 + proc / 1000 - cond_t)

    # equipment
    d.heater("H-101", "Steam reformer", fe["Q_ref"] + fe["Q_pre"], P_barg=Pr + 2, kind="reformer")
    d.hx("E-101", "Reformed gas waste heat boiler", fe["Q_whb"], fe["T1"], 623.15, 378.15, 597.0, "boiler", P_barg=120)
    d.hx("E-102", "Reformed gas coolers", fe["Q_low"], 623.15, 313.15, 303.15, 393.15, "wet-gas", P_barg=Pr)
    d.flash_drum("V-100", "Process condensate separator", core.Stream("x", "", syn, 313.15, Pr - 2), 0, Pr - 2)
    d.reactor_bed("R-101", "Methanol converter (boiling water, multiple shells)", sum(lp["cin"].values()), 8000, PL)
    d.hx("E-103", "Loop feed / effluent exchanger", Q_fe, lp["T"], T_after_fe, 313.15, 493.15, "hp-gas", P_barg=PL)
    d.cooler_cw("E-104", "Crude methanol cooler / condenser", Q_crude_cool, T_after_fe, 313.15, P_barg=PL, service="wet-gas")
    d.flash_drum("V-101", "Crude methanol separator", core.Stream("x", "", lp["vap"], 313.15, PL - 3), 0, PL - 3)
    mw_v = 32.04
    d.column("T-101", "Methanol refining column", (p["reflux_ratio"] + 1) * meoh_prod, 340, 1.5, 30, mw_v)
    d.hx("E-105", "Column reboiler", Q_reb, 433.15, 433.15, 373.15, 375.15, "reboiler", kind="hx_kettle")
    d.cooler_cw("E-106", "Column condenser", Q_cond, 338.15, 336.15, service="condenser")
    d.tank("TK-101", "Methanol product storage", meoh_prod * 32.04, 790, days=14)

    prod_t_h = meoh_prod * th.MW("MeOH") / 1000
    gas_total_GJ_t = d.gas_net_GJ_h / prod_t_h
    carbon_eff = meoh_prod / fe["feed"]["CH4"] * 100
    d.kpis = [
        {"label": "Natural gas, feed + fuel", "value": gas_total_GJ_t, "unit": "GJ/t MeOH"},
        {"label": "Natural gas, feed only", "value": feed_GJ / prod_t_h, "unit": "GJ/t MeOH"},
        {"label": "Carbon efficiency, feed to product", "value": carbon_eff, "unit": "%"},
        {"label": "Make up gas stoichiometric number", "value": SN, "unit": ""},
        {"label": "MeOH at converter outlet", "value": lp["out"]["MeOH"] / sum(lp["out"].values()) * 100, "unit": "mol%"},
    ]

    IPCC = "https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/3_Volume3/V3_3_Ch3_Chemical_Industry.pdf"
    IRENA = "https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2021/Jan/IRENA_Innovation_Renewable_Methanol_2021.pdf"
    d.check("Natural gas use, conventional steam reforming with primary reformer", gas_total_GJ_t, 33.4, "GJ/t methanol",
            "IPCC 2006 Guidelines Vol 3 Ch 3, Table 3.13", IPCC, tol=15)
    d.check("Natural gas use, range of published processes", gas_total_GJ_t, [30.1, 36.5], "GJ/t methanol",
            "IPCC 2006 Guidelines Vol 3 Ch 3, Table 3.13 (Lurgi Mega Methanol 30.1 to default 36.5)", IPCC, tol=15)
    d.check("Production cost, natural gas methanol", None, [100, 250], "USD/t",
            "IRENA and Methanol Institute, Innovation Outlook: Renewable Methanol (2021)", IRENA, tol=60, kind="cost",
            note="Published range is for 2020 gas prices; this run uses current regional gas prices.")

    d.assumptions = [
        "Natural gas is modelled as pure methane, already desulphurised.",
        "Reformer and converter reach chemical equilibrium (ideal gas); the converter uses an approach of "
        f"{p['approach_C']:.0f} K.",
        "Crude methanol condensation follows Raoult's law with Antoine vapour pressures; dissolved gases are let "
        "down and burnt with the purge.",
        f"Reformer furnace efficiency {p['furnace_eff'] * 100:.0f}%. Compressors driven by steam turbines.",
        "0.5% of the methanol is lost to the column bottoms and vents.",
        "Half of the low grade heat in the reformed gas (below 350 C) drives the distillation reboiler.",
        f"Distillation reflux ratio {p['reflux_ratio']} with 30 theoretical stages (single column in place of the "
        "usual topping and refining pair).",
    ]
    d.hazop = [
        {"node": "Steam reformer", "deviation": "Low steam flow", "cause": "Steam valve or BFW pump failure",
         "consequence": "Carbon formation, tube overheating and rupture", "safeguard": "Low steam to carbon trip, tube skin temperature monitoring"},
        {"node": "Methanol converter", "deviation": "High temperature", "cause": "Loss of boiler water circulation",
         "consequence": "Catalyst sintering, by product formation, overpressure", "safeguard": "Steam drum level control, high temperature trip"},
        {"node": "Crude separator", "deviation": "High level", "cause": "Level control failure",
         "consequence": "Liquid carry over into recycle compressor", "safeguard": "High high level trip on circulator"},
        {"node": "Methanol storage", "deviation": "Loss of containment", "cause": "Overfill, tank failure",
         "consequence": "Pool fire with an almost invisible flame; toxic exposure", "safeguard": "Bund, foam system, nitrogen blanket, flame detectors"},
    ]
    d.greener = {
        "title": "E-methanol: green hydrogen + captured CO2",
        "text": "Feed the same Cu/Zn loop with electrolytic hydrogen and captured CO2 (CO2 + 3 H2 -> CH3OH + H2O). "
                "No reformer and no flue gas, but about 0.19 t H2 and 1.37 t CO2 per t methanol, so roughly 10 MWh "
                "of electricity per tonne. Low carbon only on renewable power.",
    }
    return d.finish()
