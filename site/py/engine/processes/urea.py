"""Urea by the CO2 stripping process (total recycle, prilling).

The synthesis is a liquid phase carbamate system that has no clean ideal gas model, so the
per pass CO2 conversion at the chosen N/C ratio is a design basis taken from the Fertilizers
Europe BAT booklet. Everything downstream is computed: the recycle loop flows, the stripper,
condenser, decomposer and evaporator duties from carbamate and phase change enthalpies, the
CO2 compressor and turbine from IAPWS steam properties, and raw material use from stoichiometry
plus the booklet's emission rates.
"""
from iapws import IAPWS97

from .. import core
from .. import thermo as th
from .. import cost as C
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 2000.0,
    "nc_ratio": 2.95,
    "hc_ratio": 0.45,
    "co2_conversion_pct": 60.0,
    "stripper_eff_pct": 80.0,
    "synthesis_P_bar": 140.0,
}

DH_CARB = 117e3  # J/mol CO2: 2 NH3(l) + CO2(g) -> carbamate, released (Wikipedia, Urea, 160 C, 11 MPa)
DH_UREA = 15.5e3  # J/mol: carbamate -> urea + water, absorbed (Wikipedia, Urea, 160 to 180 C)
BOOKLET5 = "https://www.fertilizerseurope.com/wp-content/uploads/2019/08/Booklet_5_final.pdf"

# emission losses, kg per t urea (Fertilizers Europe Booklet 5, mid points of the ranges given)
LOSS_PRILL_UREA = 1.5  # "particulate urea dust (1-2kg.t-1)"
LOSS_PRILL_NH3 = 0.85  # "NH3 (0.7-1.0kg.t-1)"
LOSS_WATER_UREA = 0.4  # treated process water, 0.01-0.84 kg/t
LOSS_WATER_NH3 = 0.3  # treated process water, 0.01-0.61 kg/t
LOSS_VENT_NH3 = 0.3  # absorber vents, 0.1-0.5 kg/t


def _steam_props():
    hp = IAPWS97(P=12.0, T=783.15)
    s24 = IAPWS97(P=2.4, s=hp.s)
    sat24 = IAPWS97(P=2.4, x=1)
    sat24l = IAPWS97(P=2.4, x=0)
    sat45 = IAPWS97(P=0.45, x=1)
    sat45l = IAPWS97(P=0.45, x=0)
    r = {"h_hp": hp.h, "dh_is": hp.h - s24.h, "L24": sat24.h - sat24l.h, "L45": sat45.h - sat45l.h,
            "T24": sat24.T, "T45": sat45.T}
    return {k: float(v) for k, v in r.items()}


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    st = _steam_props()
    MWu, MWn, MWc, MWw = th.MW("Urea"), th.MW("NH3"), th.MW("CO2"), th.MW("H2O")
    t_h = p["capacity_tpd"] / 24
    P_mol = t_h * 1000 / MWu  # kmol/h urea product

    # ---- losses and fresh feeds (kmol/h)
    u_lost = t_h * (LOSS_PRILL_UREA + LOSS_WATER_UREA) / MWu
    nh3_lost = t_h * (LOSS_PRILL_NH3 + LOSS_WATER_NH3 + LOSS_VENT_NH3) / MWn
    U = P_mol + u_lost  # urea formed
    nh3_fresh = 2 * U + nh3_lost
    co2_fresh = U  # CO2 leaves only as urea; inerts vent CO2 neglected

    # ---- HP loop
    X = p["co2_conversion_pct"] / 100
    R = U / X  # CO2 entering reactor (fresh + recycle)
    nh3_r, h2o_r = p["nc_ratio"] * R, p["hc_ratio"] * R
    react = {"Urea": U, "H2O": h2o_r + U, "CO2": R - U, "NH3": nh3_r - 2 * U}
    eff = p["stripper_eff_pct"] / 100
    co2_str, nh3_str = react["CO2"] * eff, react["NH3"] * eff
    co2_lp, nh3_lp = react["CO2"] - co2_str, react["NH3"] - nh3_str
    hv_n = th.comp("NH3")["Hvap_298"]
    hv_w = th.comp("H2O")["Hvap_298"]

    # stripper: dissociate carbamate and flash free NH3, heated by 24 bar steam
    Q_str = (co2_str * DH_CARB + (nh3_str - 2 * co2_str) * hv_n) / 3.6  # kW (kmol/h * J/mol / 3.6 = W... /1000 below)
    Q_str /= 1000.0
    # HP condenser + reactor: recombine stripped gas and fresh CO2, urea step absorbs heat
    # less the sensible heat to bring liquid NH3 (27 C) and the recycle solution (about 100 C) to 183 C
    cp_n = th.comp("NH3")["Cp_liquid_298"]
    Q_sens = (nh3_fresh * cp_n * (456.15 - 300.15) + h2o_r * 75.3 * 83 + (co2_lp * 3 * 90) * 83) / 3600.0
    Q_hp_rel = ((co2_str + co2_fresh) * DH_CARB + (nh3_str - 2 * co2_str) * hv_n - U * DH_UREA) / 3600.0 - Q_sens
    # LP decomposer (4 bar): rest of the carbamate, LP steam
    Q_lpd = (co2_lp * DH_CARB + (nh3_lp - 2 * co2_lp) * hv_n) / 3600.0
    # LP condenser to cooling water: recombined to recycle carbamate solution
    Q_lpc = Q_lpd
    # evaporation to 99.7% melt: reaction water plus 0.3 kmol water per kmol urea that goes back to the
    # LP condenser as absorbent; the reaction water leaves as process water
    w_evap = U * 1.3
    Q_evap = w_evap * hv_w / 3600.0 * 1.05  # 5% for melt heating
    # process water treatment: hydrolyser/desorber; water heated 40 to 190 C, 75% recovered in interchangers
    w_proc = U * MWw  # kg/h
    Q_pw = w_proc * 4.2 * 150 * 0.25 / 3600.0

    # ---- steam balance
    lp_raised = Q_hp_rel * 3600 / st["L45"]  # kg/h of 4.5 bar steam from the HP carbamate condenser
    lp_used = (Q_lpd + Q_evap + Q_pw) * 3600 / st["L45"]
    s24_str = Q_str * 3600 / st["L24"]
    # CO2 compressor 1.1 to 145 bar, back pressure turbine 120 bar 510 C -> 24 bar exhausting to the stripper
    W_kW, n_st, Q_ic = C.compressor_power(co2_fresh * 1000 / 3600, 313.15, 1.1, p["synthesis_P_bar"] + 5, k=1.3, eta=0.78)
    dh_turb = st["dh_is"] * 0.75
    turb_kg_h = W_kW / 0.97 / dh_turb * 3600
    lp_surplus = lp_raised - lp_used
    # surplus LP steam goes to a condensing section of the compressor turbine (booklet 2.2.1)
    lp_turb_kW = max(0.0, lp_surplus) * 450.0 / 3600 * 0.97  # LP to condensing, ~450 kJ/kg used
    turb_kg_h = max(0.0, (W_kW / 0.97 - lp_turb_kW) / dh_turb * 3600)
    hp_import = max(turb_kg_h, s24_str)
    hp_import += max(0.0, -lp_surplus)  # LP deficit made up from HP letdown

    d = Design("urea", "Urea plant (CO2 stripping, prilling)", "Urea", p["capacity_tpd"], region)
    d.route = ("Liquid ammonia and compressed CO2 react at about 140 bar to ammonium carbamate, which dehydrates "
               "to urea. A steam heated stripper uses the fresh CO2 to strip unreacted carbamate back to the "
               "condenser, whose heat raises LP steam. A 4 bar decomposer, vacuum evaporators and a prill tower "
               "give solid urea.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d prilled urea (46% N) from ammonia and the CO2 by-product of an "
                 "ammonia plant, the CO2 stripping total recycle route.")
    d.reactions = [
        {"eq": "2 NH3 + CO2 <=> NH2COONH4", "where": "HP carbamate condenser and reactor", "dH_kJ": -DH_CARB / 1000},
        {"eq": "NH2COONH4 <=> CO(NH2)2 + H2O", "where": "Urea reactor", "dH_kJ": DH_UREA / 1000},
    ]
    d.conditions = [
        ("Synthesis", f"{p['synthesis_P_bar']:.0f} bar, 180 to 185 C, N/C {p['nc_ratio']:.2f}, H/C {p['hc_ratio']:.2f}"),
        ("CO2 conversion per pass", f"{p['co2_conversion_pct']:.0f}% (design basis, Booklet 5)"),
        ("HP stripper", f"{p['stripper_eff_pct']:.0f}% of unreacted NH3 and CO2 removed, 24 bar steam"),
        ("LP and finishing", "4 bar decomposer, vacuum evaporation to 99.7% melt, prill tower"),
    ]

    # ---- streams (melt stream holds the reaction products; carbamate shown as NH3 + CO2)
    s_n = d.stream("Liquid ammonia", {"NH3": nh3_fresh}, 300.15, 25, phase="l")
    s_c = d.stream("CO2 from ammonia plant", {"CO2": co2_fresh}, 313.15, 1.1)
    s_r = d.stream("Reactor effluent", react, 456.15, p["synthesis_P_bar"], phase="l")
    s_s = d.stream("Stripper bottoms", {"Urea": U, "H2O": react["H2O"], "CO2": co2_lp, "NH3": nh3_lp},
                   443.15, 4.0, phase="l")
    sol = {"Urea": U, "H2O": U * 1.3 + 0.0}
    s_sol = d.stream("Urea solution to evaporators", sol, 363.15, 1.0, phase="l")
    s_v = d.stream("Evaporator vapour to process water", {"H2O": w_evap}, 323.15, 0.2)
    s_pw = d.stream("Treated process water", {"H2O": U, "NH3": t_h * LOSS_WATER_NH3 / MWn,
                                              "Urea": t_h * LOSS_WATER_UREA / MWu}, 313.15, 1.0, phase="l")
    s_pr = d.stream("Urea prills", {"Urea": P_mol}, 323.15, 1.0, phase="s")
    s_dust = d.stream("Prill tower air (dust and NH3)", {"Urea": t_h * LOSS_PRILL_UREA / MWu,
                                                      "NH3": t_h * LOSS_PRILL_NH3 / MWn}, 333.15, 1.0)
    s_vent = d.stream("Absorber vent", {"NH3": t_h * LOSS_VENT_NH3 / MWn}, 313.15, 1.0)

    d.feed(s_n, {"NH3": "NH3"})
    d.feed(s_c, {"CO2": "CO2"})
    d.out(s_pr, "product", {"Urea": "Urea"})
    d.out(s_pw, "waste", treat_usd_t=1.0)
    d.out(s_dust, "emission")
    d.out(s_vent, "emission")

    d.unit("K-101", "CO2 compressor", "compressor", [s_c], [], (0, 0), power_kW=W_kW)
    d.unit("R-101", "Urea reactor", "reactor", [s_n], [s_r], (1, 0))
    d.unit("E-101", "HP stripper", "exchanger", [s_r], [s_s], (2, 0), duty_kW=Q_str)
    d.unit("E-102", "HP carbamate condenser", "exchanger", [], [], (1, 1), duty_kW=-Q_hp_rel * 0.9)
    d.unit("V-101", "LP decomposer and condenser", "drum", [s_s], [s_sol, s_vent], (3, 0), duty_kW=Q_lpd)
    d.unit("E-103", "Vacuum evaporators", "exchanger", [s_sol], [s_v], (4, 0), duty_kW=Q_evap)
    d.unit("C-101", "Process water hydrolyser and desorber", "column", [s_v], [s_pw], (4, 1), duty_kW=Q_pw)
    d.unit("T-101", "Prill tower", "column", [], [s_pr, s_dust], (5, 0))

    # ---- utilities
    d.steam(hp_import, "120 bar steam to CO2 compressor turbine and stripper")
    if lp_surplus > 0 and lp_turb_kW <= 0:
        d.steam(-lp_surplus, "Surplus LP steam")
    # LP carbamate condenser and evaporator condensers are counted by cooler_cw below
    d.cooling(Q_ic / 1000.0, "CO2 compressor intercoolers")
    d.cooling(max(0.0, lp_surplus) * st["L45"] / 3600 * 0.8, "Turbine condenser (LP section)")
    d.cooling(Q_hp_rel * 0.1, "HP scrubber")
    d.pump("P-101", "HP ammonia pump", nh3_fresh * MWn, 610, p["synthesis_P_bar"] + 20 - 25, material="CS")
    carb_kg_h = (co2_lp * MWc + nh3_lp * MWn + h2o_r * MWw)
    d.pump("P-102", "HP carbamate pump", carb_kg_h, 1100, p["synthesis_P_bar"] + 5 - 4, material="SS")
    air_m3_s = t_h * 1000 * 1.6 * 0.0 + t_h * 4.2e3 / 3600  # natural draft tower; forced cooling of prills
    d.generic("K-102", "Prill tower and cooler fans", "fan", min(air_m3_s, 100), f"{air_m3_s:,.0f} m3/s")
    d.power(air_m3_s * 0.02e5 / 0.7 / 1000, "Prill cooler fans (20 mbar)")
    d.power(t_h * 1.5, "Prill bucket, conveyors, solids handling")
    d.demin_water_m3_h = hp_import / 1000 * 0.05

    # ---- equipment
    d.generic("K-101", "CO2 compressor", "compressor", W_kW, f"{W_kW:,.0f} kW, {n_st} stages, 1.1 to 145 bar",
              material="CS", note="Polytropic, eta 0.78, intercooled; last stages stainless")
    d.generic("K-101-T", "CO2 compressor steam turbine", "turbine_steam", W_kW, f"{W_kW:,.0f} kW shaft, 120 to 24 bar")
    liq_m3_h = (U * MWu + react["H2O"] * MWw + react["CO2"] * MWc + react["NH3"] * MWn) / 1100
    d.vessel("R-101", "Urea reactor (sieve trays)", liq_m3_h * 0.75, P_barg=p["synthesis_P_bar"], material="SS")
    d.hx("E-101", "HP stripper (falling film)", Q_str, st["T24"], st["T24"], 456.15, 443.15, "liquid-steam",
         P_barg=p["synthesis_P_bar"], material="SS")
    d.hx("E-102", "HP carbamate condenser", Q_hp_rel * 0.9, 443.15, 443.15, st["T45"], st["T45"], "condenser",
         P_barg=p["synthesis_P_bar"], material="SS")
    d.vessel("V-102", "HP scrubber", liq_m3_h * 0.1, P_barg=p["synthesis_P_bar"], material="SS")
    d.hx("E-104", "LP decomposer heater", Q_lpd, st["T45"], st["T45"], 403.15, 408.15, "liquid-steam", P_barg=4,
         material="SS")
    d.cooler_cw("E-105", "LP carbamate condenser", Q_lpc, 353.15, 323.15, P_barg=4, material="SS", service="condenser")
    d.generic("E-103", "Vacuum evaporators (two stage)", "evaporator", min(Q_evap * 1000 / (900 * 25), 1000),
              f"{Q_evap:,.0f} kW", material="SS", note="U 900 W/m2K, 25 K driving force")
    d.cooler_cw("E-106", "Evaporator condensers", w_evap * hv_w / 3600.0, 333.15, 313.15, material="SS",
                service="condenser")
    d.column("C-101", "Process water desorber", w_proc / MWw * 0.15, 400.0, 3.0, 12, MWw, material="SS")
    d.vessel("R-102", "Hydrolyser", w_proc / 950 * 0.75, P_barg=17, material="SS")
    # prill tower: concrete shell, about 20 m diameter, costed as a vessel the size of the spray zone
    d.vessel("T-101", "Prill tower spray zone", 500, P_barg=0.0)
    d.tank("TK-101", "Ammonia buffer", nh3_fresh * MWn, 610, days=0.5, pressurised=True, P_barg=20)

    # ---- KPIs
    nh3_t = nh3_fresh * MWn / (t_h * 1000)
    co2_t = co2_fresh * MWc / (t_h * 1000)
    steam_t = hp_import / (t_h * 1000)
    cw_m3_t = d.cw_kW * 3600 / (4.18 * 10 * 1000) / t_h
    elec_MJ_t = d.power_kW * 3.6 / t_h
    d.kpis = [
        {"label": "Ammonia consumption", "value": nh3_t, "unit": "t/t urea"},
        {"label": "CO2 consumption", "value": co2_t, "unit": "t/t urea"},
        {"label": "HP steam import (120 bar)", "value": steam_t, "unit": "t/t urea"},
        {"label": "Cooling water (10 K rise)", "value": cw_m3_t, "unit": "m3/t urea"},
        {"label": "Electricity", "value": elec_MJ_t, "unit": "MJ/t urea"},
        {"label": "LP steam raised in HP condenser", "value": lp_raised / (t_h * 1000), "unit": "t/t urea"},
        {"label": "Recycle ratio (CO2 to reactor / fresh)", "value": R / co2_fresh, "unit": "-"},
    ]

    # ---- validation (Fertilizers Europe Booklet 5, Table 4.3, CO2 stripping with steam turbine drive)
    src = "Fertilizers Europe BAT Booklet 5 (Urea), section 4.3, CO2 stripping, prilling, steam turbine drive"
    d.check("Ammonia consumption", nh3_t, 0.57, "t/t", src, BOOKLET5, tol=3)
    d.check("CO2 consumption", co2_t, 0.75, "t/t", src, BOOKLET5, tol=3,
            note="Booklet value includes CO2 lost from vents; the model only loses CO2 in urea dust.")
    d.check("Steam import (120 bar)", steam_t, 0.77, "t/t", src, BOOKLET5, tol=25, kind="energy")
    d.check("Cooling water", cw_m3_t, 70, "m3/t", src, BOOKLET5, tol=35, kind="energy")
    d.check("Electricity", elec_MJ_t, 54, "MJ/t", src, BOOKLET5, tol=50, kind="energy")

    d.assumptions = [
        f"CO2 conversion per pass {p['co2_conversion_pct']:.0f}% at N/C {p['nc_ratio']:.2f} is the Booklet 5 design "
        "basis, not a computed equilibrium. H/C 0.45 and stripper efficiency are typical values.",
        "Carbamate formation releases 117 kJ/mol and urea dehydration absorbs 15.5 kJ/mol (Wikipedia, Urea); "
        "NH3 and water vaporisation from the component data. Sensible heat in the loop is neglected.",
        "Raw material losses are the mid points of the Booklet 5 emission ranges: prill tower dust 1.5 kg/t and "
        "NH3 0.85 kg/t, process water NH3 0.3 and urea 0.4 kg/t, vents NH3 0.3 kg/t.",
        "CO2 compressor 1.1 to 145 bar, polytropic efficiency 0.78. Back pressure turbine 120 bar 510 C to 24 bar "
        "(IAPWS-97, 75% isentropic), exhaust heats the stripper; surplus LP steam drives a condensing section.",
        "Evaporation removes 1.3 kmol water per kmol urea; process water heated 40 to 190 C with 75% interchange.",
        "HP equipment in urea grade stainless steel. Prill tower costed as a 500 m3 vessel (rough).",
    ]
    d.hazop = [
        {"node": "HP synthesis loop", "deviation": "Loss of passivation air", "cause": "Air compressor trip",
         "consequence": "Rapid carbamate corrosion of stainless steel, leak of hot ammonia",
         "safeguard": "Low O2 alarm in CO2 feed, corrosion monitoring, leak detection holes"},
        {"node": "HP synthesis loop", "deviation": "High pressure", "cause": "Blocked outlet, carbamate freezing",
         "consequence": "Vessel rupture, toxic NH3 release", "safeguard": "Relief valves, steam tracing, trips"},
        {"node": "CO2 feed", "deviation": "H2 in CO2", "cause": "Upset in ammonia plant CO2 removal",
         "consequence": "Explosive H2/O2 mixture in HP scrubber vent",
         "safeguard": "H2 removal reactor on CO2, vent analysers"},
        {"node": "Ammonia pump", "deviation": "Loss of containment", "cause": "Seal failure",
         "consequence": "Toxic ammonia cloud", "safeguard": "NH3 detectors, remote isolation, water curtains"},
        {"node": "Prill tower", "deviation": "High dust emission", "cause": "Scrubber fault, melt overheating",
         "consequence": "Permit breach, dust explosion risk low", "safeguard": "Opacity monitoring, scrubbers"},
    ]
    d.greener = {
        "title": "Green ammonia and captured CO2",
        "text": "The urea step itself is fixed; the footprint sits in the ammonia and CO2. Ammonia from electrolytic "
                "hydrogen removes most of it, but then CO2 must come from biogenic or captured sources, and the "
                "carbon in urea is released again in the field.",
        "electricity_MWh_per_t": 0.0,
    }
    return d.finish()
