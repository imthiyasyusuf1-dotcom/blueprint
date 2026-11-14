"""Chlorine and caustic soda by membrane cell electrolysis of brine (bipolar membrane electrolysers).

Solid salt is dissolved in returning depleted brine to saturation, purified (primary precipitation
and filtration, then ion exchange) and fed to the anolyte. The electrolysers are modelled with
Faraday's law: current efficiency sets how much of the charge makes chlorine (the rest, carried
back by hydroxide through the membrane, makes oxygen at the anode). Cell voltage comes from a
straight line through the EU fleet averages for bipolar membrane cells (CAK BREF 2014 Table 3.10),
so power, membrane area and Joule heat follow from the current density chosen.

Heats of reaction for the electrolyte species use standard enthalpies of formation of the aqueous
and solid species (Wikipedia list of standard enthalpies of formation, which reproduces the NBS
tables), not components.json, whose 'aq' enthalpies are wrong for electrolytes.

Wet chlorine is cooled, dried with sulphuric acid, compressed and liquefied with refrigeration;
the oxygen and a little chlorine leave as tail gas to the hypochlorite unit. The 32% caustic from
the cells is concentrated to 50% in a double effect evaporator. Hydrogen is cooled and burnt in
the site boiler as fuel (credited against natural gas).
"""
import math

from .. import core
from .. import thermo as th
from .. import cost as C
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 500.0,        # t/d liquid chlorine (industry capacity basis)
    "current_density_kA_m2": 5.0,
    "current_eff_pct": 96.0,
    "rectifier_eff_pct": 96.0,
    "cell_T_C": 88.0,
    "caustic_cell_wt_pct": 32.0,
    "caustic_product_wt_pct": 50.0,
    "evap_effects": 2,
    "water_transport": 4.0,       # mol H2O carried through the membrane per mol Na+
    "purge_m3_per_t": 0.33,       # brine purge, m3 per t Cl2 (CAK BREF Table 3.5 median)
    "liquefaction_bar": 10.0,
    "liquefaction_C": -5.0,
}

BREF = "https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/CAK_BREF_102014.pdf"
SRC = "EU BREF Production of Chlor-alkali (JRC, 2014)"
F = 96485.33  # C/mol

# Standard enthalpies of formation at 25 C, kJ/mol (Wikipedia "Standard enthalpy of formation",
# inorganic table, which reproduces the NBS/CRC values): NaCl(aq) -407.27, NaCl(s) -411.12,
# NaOH(aq) -469.15, H2O(l) -285.8. Cl2, H2, O2 gas 0.
HF_NACL_AQ, HF_NACL_S, HF_NAOH_AQ, HF_H2O_L = -407.27, -411.12, -469.15, -285.8
# Main reaction 2 NaCl(aq) + 2 H2O(l) -> 2 NaOH(aq) + Cl2 + H2, per mol Cl2 (kJ)
DH_MAIN = 2 * HF_NAOH_AQ - 2 * HF_NACL_AQ - 2 * HF_H2O_L          # +447.8 kJ/mol Cl2
DH_O2 = -2 * HF_H2O_L                                              # 2 H2O -> 2 H2 + O2, +571.6 kJ/mol O2
DH_SOL_NACL = HF_NACL_AQ - HF_NACL_S                               # +3.85 kJ/mol, salt dissolution

# Fleet average operating points of bipolar membrane cells, CAK BREF Table 3.10:
# current density min 2.9 kA/m2 with cell voltage min 2.86 V; max 5.4 kA/m2 with 3.40 V.
J1, V1, J2, V2 = 2.9, 2.86, 5.4, 3.40
K_V = (V2 - V1) / (J2 - J1)  # V per kA/m2 (the "k factor")

# CRC Handbook densities of aqueous NaCl at 20 C (via Wikipedia "Sodium chloride (data page)"),
# wt% -> g/cm3; and saturation 27.03 wt% at 60 C from the same table.
RHO_NACL = [(16, 1.1162), (18, 1.1319), (20, 1.1478), (22, 1.164)]
W_SAT_60C = 0.2703
# Heat capacities, kJ/kg K: solid NaCl 0.853 (same data page), solid NaOH 59.5 J/mol K (Wikipedia Sodium
# hydroxide infobox), water 4.18. Solution cp is taken as the mass weighted sum, a simple estimate.
CP_NACL_S, CP_NAOH_S, CP_W = 0.853, 59.5 / 40.0, 4.18

# Investment in the cell room, CAK BREF Table 4.4 (Euro Chlor 2010), EUR per t annual Cl2 capacity
# for a 100 kt/yr plant: (current density, electrolysers min/max, ancillaries min/max, building max,
# electricity supply max). Building and electricity supply have no minimum given, so the maximum is used.
CELLROOM = [(4.0, 53, 106, 33, 43, 14, 121), (5.0, 43, 85, 26, 34, 11, 97), (6.0, 36, 71, 22, 28, 9, 81)]
EUR_USD_2010 = 1.3261  # mean of the 250 daily 2010 noon buying rates, Federal Reserve H.10 dat00_eu.htm
SPENT_ACID = 0.65      # three drying stages give 50 to 65 wt% spent acid (CAK BREF, chlorine drying, PDF page 65)


def _rho_brine(w):
    """Density (kg/L) of NaCl brine at mass fraction w, linear in the CRC table."""
    pct = w * 100
    for (w1, r1), (w2, r2) in zip(RHO_NACL, RHO_NACL[1:]):
        if pct <= w2:
            return r1 + (r2 - r1) * (pct - w1) / (w2 - w1)
    return RHO_NACL[-1][1]


def _w_from_gl(gl):
    """Mass fraction of a brine holding gl g NaCl per litre (solves w * rho(w) = gl)."""
    lo, hi = 0.10, 0.26
    for _ in range(60):
        w = (lo + hi) / 2
        if w * _rho_brine(w) * 1000 > gl:
            hi = w
        else:
            lo = w
    return (lo + hi) / 2


def _cellroom_eur_t(j):
    """Mid point EUR per t annual capacity for the cell room, interpolated in current density."""
    rows = [(r[0], (r[1] + r[2]) / 2 + (r[3] + r[4]) / 2 + r[5] + r[6]) for r in CELLROOM]
    j = min(max(j, rows[0][0]), rows[-1][0])
    for (j1, c1), (j2, c2) in zip(rows, rows[1:]):
        if j <= j2:
            return c1 + (c2 - c1) * (j - j1) / (j2 - j1)
    return rows[-1][1]


def _sens_gas(flows, T):
    """Sensible heat (kW) of a gas mixture from 25 C to T."""
    return core.hin(flows, T) - core.hin(flows, 298.15)


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    t_h = p["capacity_tpd"] / 24
    MW = {c: th.MW(c) for c in ("Cl2", "NaCl", "NaOH", "H2O", "H2", "O2", "H2SO4")}
    CE = p["current_eff_pct"] / 100
    j = p["current_density_kA_m2"]
    Tc = p["cell_T_C"] + 273.15
    P_an, P_cat = 1.05, 1.08  # bar abs in the anolyte and catholyte gas spaces
    nw = p["water_transport"]

    # ---- product chlorine and tail gas loss at the liquefier
    Cl2_p = t_h * 1000 / MW["Cl2"]
    T_liq, P_liq = p["liquefaction_C"] + 273.15, p["liquefaction_bar"]
    y_cl = core.psat("Cl2", T_liq) / P_liq           # Cl2 left in the uncondensed tail gas
    o2_per_cl2 = (1 - CE) / (2 * CE)
    Cl2 = Cl2_p / (1 - o2_per_cl2 * y_cl / (1 - y_cl))  # gross chlorine from the cells
    n_e = 2 * Cl2 / CE                                   # kmol/h of electrons
    O2 = (1 - CE) * n_e / 4
    H2 = n_e / 2
    NaOH = CE * n_e                                      # Na+ through the membrane = NaOH made
    c_nacl = CE * n_e                                    # NaCl split
    Cl2_tail = Cl2 - Cl2_p

    # ---- electrochemistry
    V = V1 + K_V * (j - J1)
    I_A = n_e * 1000 * F / 3600
    P_dc = I_A * V / 1000                                # kW
    P_ac = P_dc / (p["rectifier_eff_pct"] / 100)
    A_mem = I_A / (j * 1000)
    V_tn = DH_MAIN * 1000 / (2 * F)                      # thermoneutral voltage of the main reaction
    dH_rxn = (Cl2 * DH_MAIN + O2 * DH_O2) * 1000 / 3600  # kW absorbed (kmol/h times kJ/mol)
    Q_joule = P_dc - dH_rxn

    # ---- water vapour in the cell gases (pure water vapour pressure, an upper bound)
    ps = core.psat("H2O", Tc)
    vap_a = (Cl2 + O2) * ps / (P_an - ps)
    vap_c = H2 * ps / (P_cat - ps)

    # ---- brine loop: saturated brine in, depleted brine (200 g/L) out
    ws = W_SAT_60C
    wd = _w_from_gl(200.0)
    form_a = (1 - CE) * n_e / 2                          # water made at the anode with the O2
    Wl = nw * c_nacl - form_a + vap_a                    # net water leaving the anolyte, kmol/h
    a = (c_nacl * MW["NaCl"] * (1 - wd) / wd - Wl * MW["H2O"]) / (MW["NaCl"] * ((1 - wd) / wd - (1 - ws) / ws))
    b = a * MW["NaCl"] * (1 - ws) / ws / MW["H2O"]
    dep = {"NaCl": a - c_nacl, "H2O": b - Wl}
    dep_kg = dep["NaCl"] * MW["NaCl"] + dep["H2O"] * MW["H2O"]

    # ---- catholyte: water in so the caustic leaves at 32%
    xc = p["caustic_cell_wt_pct"] / 100
    w32 = NaOH * MW["NaOH"] * (1 - xc) / xc / MW["H2O"]
    Wc = w32 + n_e + vap_c - nw * c_nacl                 # cathode uses one H2O per electron
    caus32 = {"NaOH": NaOH, "H2O": w32}

    # ---- caustic evaporation to 50%, double effect, LP steam
    xp = p["caustic_product_wt_pct"] / 100
    w50 = NaOH * MW["NaOH"] * (1 - xp) / xp / MW["H2O"]
    E = w32 - w50                                        # kmol/h water evaporated
    s35 = th.STEAM[10]
    lat_steam = s35[2] - s35[1]                          # 10 bar steam latent, kJ/kg
    lat_vap = 2257.0                                     # kJ/kg water vapour at 100 C (IAPWS-97)
    steam_evap = E * MW["H2O"] * lat_vap / lat_steam / p["evap_effects"]  # kg/h
    Q_evap1 = steam_evap * lat_steam / 3600              # kW into effect 1
    caus50 = {"NaOH": NaOH, "H2O": w50}

    # ---- chlorine cooling to 15 C, drying with 98% acid (spent at 75%), compression, liquefaction
    T_cc = 288.15
    res_w = (Cl2 + O2) * core.psat("H2O", T_cc) / (1.0 - core.psat("H2O", T_cc))
    cond_cl = vap_a - res_w
    acid_kg = res_w * MW["H2O"] * SPENT_ACID / (0.98 - SPENT_ACID)  # 98% acid fed per hour
    acid_in = {"H2SO4": acid_kg * 0.98 / MW["H2SO4"], "H2O": acid_kg * 0.02 / MW["H2O"]}
    acid_out = {"H2SO4": acid_in["H2SO4"], "H2O": acid_in["H2O"] + res_w}
    wet_cl2 = {"Cl2": Cl2, "O2": O2, "H2O": vap_a}
    cool_cl2 = {"Cl2": Cl2, "O2": O2, "H2O": res_w}
    dry_cl2 = {"Cl2": Cl2, "O2": O2}
    Q_clcool = _sens_gas(wet_cl2, Tc) - _sens_gas(cool_cl2, T_cc) + cond_cl * (
        core.h_molar("H2O", Tc) - core.h_molar("H2O", T_cc, "l")) / 3600
    tail = {"Cl2": Cl2_tail, "O2": O2}
    liq = {"Cl2": Cl2_p}
    Q_liq = (_sens_gas(liq, 313.15) - _sens_gas(liq, T_liq)) + Cl2_p * th.hvap("Cl2", T_liq) / 3600
    T_ev = T_liq - 10
    cop = 0.5 * T_ev / (313.15 + 5 - T_ev)               # half of Carnot, condensing at 45 C
    W_ref = Q_liq / cop

    # ---- hydrogen cooled to 40 C and burnt in the site boiler
    T_hc = 313.15
    res_h = H2 * core.psat("H2O", T_hc) / (1.0 - core.psat("H2O", T_hc))
    cond_h = vap_c - res_h
    wet_h2 = {"H2": H2, "H2O": vap_c}
    h2_fuel = {"H2": H2, "H2O": res_h}
    Q_hcool = _sens_gas({"H2": H2}, Tc) - _sens_gas({"H2": H2}, T_hc) + vap_c * (
        core.h_molar("H2O", Tc) - core.h_molar("H2O", 298.15)) / 3600 + cond_h * (
        core.h_molar("H2O", 298.15) - core.h_molar("H2O", T_hc, "l")) / 3600 - res_h * (
        core.h_molar("H2O", T_hc) - core.h_molar("H2O", 298.15)) / 3600
    h2_GJ_h = H2 * th.lhv_molar("H2") / 1e6

    # ---- purge (sulphate and chlorate control) and resaturation
    rho_d = _rho_brine(wd)
    purge_kg = p["purge_m3_per_t"] * t_h * rho_d * 1000
    f_pg = purge_kg / dep_kg
    purge = {c: n * f_pg for c, n in dep.items()}
    ret = {c: n * (1 - f_pg) for c, n in dep.items()}
    salt = a - ret["NaCl"]
    need_w = b - ret["H2O"]
    cond_ev_cell = min(E, max(Wc, 0.0))
    demin = max(Wc - E, 0.0)
    surplus = E - cond_ev_cell
    to_sat = cond_cl + cond_h
    ev_to_sat = min(surplus, max(need_w - to_sat, 0.0))
    ev_out = surplus - ev_to_sat
    makeup = need_w - to_sat - ev_to_sat
    if makeup < -1e-9:
        raise ValueError("Brine loop has surplus water; purge would have to rise")
    makeup = max(makeup, 0.0)

    # ---- energy balances around the cells and the brine loop (25 C, liquid water/aqueous reference)
    def brine_cp(w):
        return w * CP_NACL_S + (1 - w) * CP_W
    feed_kg = a * MW["NaCl"] + b * MW["H2O"]
    cp_f = brine_cp(ws)
    cp_d = brine_cp(wd)
    cp_c = xc * CP_NAOH_S + (1 - xc) * CP_W
    caus32_kg = NaOH * MW["NaOH"] + w32 * MW["H2O"]
    H_wv = lambda n, T: n * (core.h_molar("H2O", T) - core.h_molar("H2O", 298.15, "l")) / 3600
    out_cells = (dep_kg * cp_d * (Tc - 298.15) / 3600 + caus32_kg * cp_c * (Tc - 298.15) / 3600
                 + _sens_gas({"Cl2": Cl2, "O2": O2}, Tc) + _sens_gas({"H2": H2}, Tc)
                 + H_wv(vap_a, Tc) + H_wv(vap_c, Tc))
    T_cat_w = 333.15  # evaporator condensate returned to the catholyte at about 60 C
    in_water = Wc * MW["H2O"] * CP_W * (T_cat_w - 298.15) / 3600
    Q_feed = out_cells - Q_joule - in_water             # kW the feed brine must bring in above 25 C
    T_feed = 298.15 + Q_feed * 3600 / (feed_kg * cp_f)
    T_ix = 333.15                                       # ion exchange resins limit the brine to about 60 C
    Q_bh = max(0.0, feed_kg * cp_f * (T_feed - T_ix) / 3600)
    s35 = th.STEAM[3.5]
    lat_lp = s35[2] - s35[1]
    steam_bh = Q_bh * 3600 / lat_lp
    T_in_cells = max(T_feed, T_ix)
    T_cool_to = min(T_feed, T_ix)                       # brine cooled further if the cells need cooling

    # resaturator outlet temperature, then a brine cooler down to the ion exchange temperature
    H_sat_in = (sum(n * MW[c] for c, n in ret.items()) * cp_d * (Tc - 298.15) / 3600
                + (cond_cl + cond_h) * MW["H2O"] * CP_W * (313.15 - 298.15) / 3600
                + ev_to_sat * MW["H2O"] * CP_W * (T_cat_w - 298.15) / 3600
                - salt * DH_SOL_NACL * 1000 / 3600)
    T_sat = 298.15 + H_sat_in * 3600 / (feed_kg * cp_f)
    Q_brine_cool = max(0.0, feed_kg * cp_f * (T_sat - T_cool_to) / 3600)

    # ---- design object
    d = Design("chlor_alkali", "Chlorine and caustic soda (membrane cell electrolysis)", "Chlorine",
               p["capacity_tpd"], region)
    hrs = d.hours
    d.route = ("Rock salt is dissolved in returning brine, purified by precipitation, filtration and ion exchange, "
               "and split in bipolar membrane electrolysers into chlorine at the anode and hydrogen with 32% caustic "
               "soda at the cathode. Chlorine is cooled, dried with sulphuric acid, compressed and liquefied. Caustic "
               "is evaporated to 50% and the hydrogen is burnt in the site boiler.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d liquid chlorine with {NaOH * MW['NaOH'] * 24 / 1000:,.0f} t/d caustic "
                 f"soda (100% basis, sold as 50% liquor), using {P_ac * 24 / 1000:,.0f} MWh a day of electricity.")
    d.reactions = [
        {"eq": "2 NaCl + 2 H2O -> 2 NaOH + Cl2 + H2", "where": "Membrane electrolysers", "dH_kJ": DH_MAIN},
        {"eq": "4 OH- -> O2 + 2 H2O + 4 e-", "where": "Anode side reaction (back migrated hydroxide)",
         "dH_kJ": DH_O2 / 2},
        {"eq": "NaCl(s) -> NaCl(aq)", "where": "Resaturator", "dH_kJ": DH_SOL_NACL},
    ]
    d.conditions = [
        ("Electrolysers", f"{j:.1f} kA/m2, {V:.2f} V per cell, {Tc - 273.15:.0f} C, current efficiency "
                          f"{CE * 100:.0f}%"),
        ("Brine", f"Saturated {ws * 100:.1f} wt% in, depleted 200 g/L ({wd * 100:.1f} wt%) out"),
        ("Caustic", f"{xc * 100:.0f}% from the cells, {xp * 100:.0f}% after a {p['evap_effects']} effect evaporator"),
        ("Chlorine liquefaction", f"{P_liq:.0f} bar, {p['liquefaction_C']:.0f} C (refrigerated)"),
    ]

    # ---- streams
    s_salt = d.stream("Rock salt", {"NaCl": salt}, 298.15, 1.0, phase="s")
    s_mk = d.stream("Make-up water", {"H2O": makeup}, 298.15, 3, phase="l")
    s_raw = d.stream("Saturated brine", {"NaCl": a, "H2O": b}, T_sat, 2, phase="l")
    s_pb = d.stream("Primary purified brine", {"NaCl": a, "H2O": b}, T_cool_to, 2, phase="l")
    s_ub = d.stream("Ultrapure brine to cells", {"NaCl": a, "H2O": b}, T_in_cells, 4, phase="l")
    s_cw = d.stream("Process condensate to catholyte", {"H2O": cond_ev_cell}, T_cat_w, 3, phase="l")
    streams_in_cell = [s_ub, s_cw]
    if demin > 1e-9:
        s_dm = d.stream("Demineralised water", {"H2O": demin}, 298.15, 3, phase="l")
        streams_in_cell.append(s_dm)
    s_wcl = d.stream("Wet chlorine", wet_cl2, Tc, P_an)
    s_wh = d.stream("Wet hydrogen", wet_h2, Tc, P_cat)
    s_c32 = d.stream("Caustic soda 32%", caus32, Tc, 3, phase="l")
    s_dep = d.stream("Depleted brine", dep, Tc, 1.5, phase="l")
    s_ret = d.stream("Dechlorinated brine return", ret, Tc - 5, 2, phase="l")
    s_pg = d.stream("Brine purge", purge, Tc - 5, 2, phase="l")
    s_ccl = d.stream("Cooled chlorine", cool_cl2, T_cc, 1.0)
    s_cc = d.stream("Chlorine cooler condensate", {"H2O": cond_cl}, T_cc, 2, phase="l")
    s_acid = d.stream("Sulphuric acid 98%", acid_in, 298.15, 3, phase="l")
    s_spent = d.stream("Spent acid 65%", acid_out, 303.15, 2, phase="l")
    s_dry = d.stream("Dry chlorine", dry_cl2, 303.15, 0.95)
    s_hp = d.stream("Compressed chlorine", dry_cl2, 313.15, P_liq)
    s_lcl = d.stream("Liquid chlorine", liq, T_liq, P_liq, phase="l")
    s_tail = d.stream("Tail gas to hypochlorite unit", tail, T_liq, P_liq - 0.5)
    s_h2 = d.stream("Hydrogen to boiler fuel", h2_fuel, T_hc, 1.05)
    s_hc = d.stream("Hydrogen cooler condensate", {"H2O": cond_h}, T_hc, 2, phase="l")
    s_c50 = d.stream("Caustic soda 50%", caus50, 318.15, 3, phase="l")

    d.feed(s_salt, {"NaCl": "NaCl"})
    d.feed(s_mk)
    d.feed(s_acid, {"H2SO4": "H2SO4"})
    if demin > 1e-9:
        d.feed(s_dm)
    d.out(s_lcl, "product", {"Cl2": "Cl2"})
    d.out(s_c50, "byproduct", {"NaOH": "NaOH"})
    d.out(s_h2, "byproduct")
    d.out(s_spent, "waste", treat_usd_t=2.0)
    d.out(s_pg, "waste", treat_usd_t=2.0)
    d.out(s_tail, "waste", treat_usd_t=2.0)
    ev_streams = [s_c50, s_cw]
    sat_ins = [s_salt, s_mk, s_ret, s_cc, s_hc]
    if ev_to_sat > 1e-9:
        s_ev = d.stream("Evaporator condensate to resaturator", {"H2O": ev_to_sat}, T_cat_w, 2, phase="l")
        ev_streams.append(s_ev)
        sat_ins.append(s_ev)
    if ev_out > 1e-9:
        s_evx = d.stream("Surplus process condensate", {"H2O": ev_out}, T_cat_w, 2, phase="l")
        d.out(s_evx, "waste", treat_usd_t=0.5)
        ev_streams.append(s_evx)

    d.unit("D-101", "Salt resaturator", "mixer", sat_ins, [s_raw], (0, 1),
           duty_kW=-salt * DH_SOL_NACL * 1000 / 3600, desc="Solid salt dissolved to saturation in returning brine")
    d.unit("F-101", "Primary brine purification and cooler", "separator", [s_raw], [s_pb], (1, 1),
           duty_kW=-Q_brine_cool, desc="Precipitation of Ca and Mg, clarifier, filters, cooled to 60 C")
    d.unit("X-101", "Ion exchange and brine heater", "adsorber", [s_pb], [s_ub], (2, 1), duty_kW=Q_bh,
           desc="Chelating resin softening to ppb Ca and Mg, then steam heated to the cell feed temperature")
    d.unit("R-101", "Membrane electrolysers", "reactor", streams_in_cell, [s_wcl, s_wh, s_c32, s_dep], (3, 1),
           duty_kW=-Q_joule, power_kW=P_ac, desc=f"{A_mem:,.0f} m2 of membrane at {j:.1f} kA/m2")
    d.unit("C-104", "Brine dechlorination and purge", "column", [s_dep], [s_ret, s_pg], (3, 2),
           desc="Acidified vacuum dechlorination, bisulphite polish")
    d.unit("E-102", "Chlorine coolers", "exchanger", [s_wcl], [s_ccl, s_cc], (4, 0), duty_kW=-Q_clcool)
    d.unit("C-102", "Chlorine drying towers", "column", [s_ccl, s_acid], [s_dry, s_spent], (5, 0))
    d.unit("K-101", "Chlorine compressor", "compressor", [s_dry], [s_hp], (6, 0))
    d.unit("E-103", "Chlorine liquefier (refrigerated)", "exchanger", [s_hp], [s_lcl, s_tail], (7, 0),
           duty_kW=-Q_liq, power_kW=W_ref)
    d.unit("E-104", "Hydrogen cooler", "exchanger", [s_wh], [s_h2, s_hc], (4, 1), duty_kW=-Q_hcool)
    d.unit("V-101", "Caustic evaporator (double effect)", "evaporator", [s_c32], ev_streams, (4, 2),
           duty_kW=Q_evap1)

    # ---- utilities
    d.power(P_ac, "Electrolysers (AC, rectifier and transformer losses included)")
    d.steam(steam_evap, "Caustic evaporation, 10 bar steam")
    if steam_bh > 0:
        d.steam(steam_bh, "Brine heating to cell feed temperature, 3.5 bar steam")
    d.fuel_credit(h2_GJ_h, "Hydrogen burnt in the site boiler")
    d.cooling(Q_liq + W_ref, "Refrigeration condenser")
    d.cooling(0.2 * Q_clcool, "Chlorine trim cooler (chilled water, counted as cooling water)")
    d.power(W_ref, "Chlorine liquefaction refrigeration")
    d.demin_water_m3_h = demin * MW["H2O"] / 1000
    circ_kg_h = feed_kg
    d.pump("P-101", "Brine feed pumps", circ_kg_h, 1200, 4)
    d.pump("P-102", "Depleted brine pumps", dep_kg, 1130, 3)
    d.pump("P-103", "Caustic pumps", caus32_kg, 1340, 4)
    d.pump("P-104", "Drying acid circulation", acid_kg * 30, 1800, 3, material="SS")
    d.solids_steps = 1  # salt unloading, storage and feeding

    # ---- equipment
    W_k, n_k = d.compressor("K-101", "Chlorine compressor (liquid ring or centrifugal)", s_dry, P_liq, k=1.33, eta=0.75)
    d.generic("K-102", "Refrigeration compressor (liquefaction)", "compressor", max(W_ref, 1.0),
              f"{W_ref:,.0f} kW, evaporating at {T_ev - 273.15:.0f} C")
    liq_brine_m3_h = feed_kg / (_rho_brine(0.22) * 1000)
    d.vessel("D-101", "Salt resaturator", liq_brine_m3_h * 1.0, material="SS")
    d.vessel("F-101", "Brine clarifier and reaction tanks", liq_brine_m3_h * 2.0, orientation="horizontal")
    d.vessel("F-102", "Brine filters (candle)", liq_brine_m3_h * 0.25, P_barg=3)
    for i in range(3):
        d.vessel(f"X-10{i + 1}", f"Ion exchange column {i + 1}", liq_brine_m3_h / 20 * 1.5, P_barg=4, material="SS")
    d.cooler_cw("E-101", "Brine cooler before ion exchange", max(Q_brine_cool, 1.0), max(T_sat, T_cool_to + 1), T_cool_to,
                material="SS", service="liquid-water")
    if Q_bh > 0:
        d.hx("E-105", "Brine heater (titanium plate)", Q_bh, s35[0] + 273.15, s35[0] + 273.15, T_ix, T_in_cells,
             "liquid-steam", P_barg=4, material="SS")
    cap_kt = p["capacity_tpd"] * hrs / 24 / 1000
    eur_t = _cellroom_eur_t(j) * (100 / cap_kt) ** 0.3
    usd_cell = eur_t * cap_kt * 1000 * EUR_USD_2010 * C.CEPCI[C.BASE_YEAR] / C.CEPCI[2010]
    d.lump("Membrane cell room (electrolysers, ancillaries, building, transformers and rectifiers)", usd_cell,
           f"CAK BREF 2014 Table 4.4 (Euro Chlor 2010): mid point EUR {_cellroom_eur_t(j):.0f}/t annual Cl2 capacity at "
           f"{j:.1f} kA/m2 for 100 kt/yr, scaled by (100/C)^0.3 (BREF Equation 2) to EUR {eur_t:.0f}/t, converted at "
           f"{EUR_USD_2010} USD/EUR (2010 average, Federal Reserve H.10) and CEPCI {C.CEPCI[2010]} (2010) to "
           f"{C.CEPCI[C.BASE_YEAR]} ({C.BASE_YEAR}). "
           "Table 4.4 is for a mercury cell conversion, so a new site cell room may cost more.")
    d.vessel("C-104", "Dechlorination tower", dep_kg / 1130 * 0.25, material="SS")
    d.cooler_cw("E-102", "Chlorine coolers (titanium)", 0.8 * Q_clcool, Tc, T_cc + 10, material="SS", service="wet-gas")
    d.hx("E-102B", "Chlorine chilled water trim cooler", Q_clcool * 0.2, T_cc + 10, T_cc, 280.15, 285.15,
         "wet-gas", material="SS")
    d.column("C-102", "Chlorine drying towers", Cl2 + O2 + res_w, 300.0, 1.0, 4, 70.0, packed=True)
    Q_cond = Q_liq
    d.hx("E-103", "Chlorine liquefier", Q_cond, 313.15, T_liq, T_ev, T_ev + 2, "condenser", P_barg=P_liq - 1)
    d.cooler_cw("E-104", "Hydrogen coolers", Q_hcool, Tc, T_hc, service="wet-gas")
    # Falling film effects costed as a shell and tube calandria plus a vapour separator (the only Turton
    # evaporator curve is forced circulation). Effect 1 on 10 bar steam boils 50% caustic near 150 C;
    # the last effect runs under vacuum near 75 C on vapour from the effect before. Nickel costed as SS.
    n_eff = p["evap_effects"]
    T_hot = [th.STEAM[10][0] + 273.15] + [373.15 - 15 * k for k in range(n_eff - 1)]
    for i in range(n_eff):
        Tb = 423.15 if i == 0 else T_hot[i] - 27
        d.hx(f"V-10{i + 1}", f"Caustic evaporator effect {i + 1} calandria", Q_evap1, T_hot[i], T_hot[i], Tb - 5, Tb,
             "liquid-steam", material="SS")
        vap = core.Stream("x", "vapour", {"H2O": E / n_eff}, Tb, 1.0 if i == 0 else 0.35)
        d.flash_drum(f"V-11{i + 1}", f"Evaporator {i + 1} vapour separator", vap, caus32_kg, 0.0, material="SS")
    d.cooler_cw("E-106", "Evaporator surface condenser", Q_evap1 / p["evap_effects"], 333.15, 323.15,
                service="condenser")
    d.tank("TK-101", "Caustic soda 50% tanks", NaOH * MW["NaOH"] + w50 * MW["H2O"], 1520, days=14)
    d.tank("TK-102", "Liquid chlorine storage", Cl2_p * MW["Cl2"], 1470, days=2, pressurised=True, P_barg=P_liq)
    d.tank("TK-103", "Sulphuric acid tank", acid_kg, 1840, days=30)
    d.vessel("V-110", "Hydrogen seal pot and knock out", 10.0)

    # ---- KPIs
    tCl2 = t_h
    ac_kwh_t = P_ac / tCl2
    dc_kwh_t = P_dc / tCl2
    other_kw = d.power_kW - P_ac - W_ref - W_k / 0.95
    liq_kwh_t = (W_ref + W_k / 0.95) / tCl2
    naoh_t_t = NaOH * MW["NaOH"] / 1000 / tCl2
    salt_kg_t = salt * MW["NaCl"] / tCl2
    steam_ev_t = steam_evap / (NaOH * MW["NaOH"])
    steam_bh_t = steam_bh / 1000 / tCl2
    mem_eur_t = 500 / 4 * A_mem / (cap_kt * 1000)
    d.kpis = [
        {"label": "Electricity to electrolysis (AC)", "value": ac_kwh_t, "unit": "kWh/t Cl2"},
        {"label": "Electricity, DC at the cells", "value": dc_kwh_t, "unit": "kWh/t Cl2"},
        {"label": "Cell voltage", "value": V, "unit": "V"},
        {"label": "Thermoneutral voltage", "value": V_tn, "unit": "V"},
        {"label": "Current efficiency", "value": CE * 100, "unit": "%"},
        {"label": "Membrane area", "value": A_mem, "unit": "m2"},
        {"label": "Salt consumption", "value": salt_kg_t, "unit": "kg/t Cl2"},
        {"label": "Caustic soda (100%)", "value": naoh_t_t, "unit": "t/t Cl2"},
        {"label": "Hydrogen", "value": H2 * MW["H2"] / tCl2, "unit": "kg/t Cl2"},
        {"label": "Steam for caustic evaporation", "value": steam_ev_t, "unit": "t/t NaOH (100%)"},
        {"label": "Steam for brine heating", "value": steam_bh_t, "unit": "t/t Cl2"},
        {"label": "Chlorine liquefaction power", "value": liq_kwh_t, "unit": "kWh/t Cl2"},
        {"label": "Sulphuric acid for drying", "value": acid_kg * 0.98 / tCl2, "unit": "kg/t Cl2 (100%)"},
        {"label": "Oxygen in cell chlorine", "value": O2 / (Cl2 + O2) * 100, "unit": "mol %"},
        {"label": "Membrane replacement", "value": mem_eur_t, "unit": "EUR/t Cl2 (not in opex)"},
    ]

    # ---- validation (benchmarks.json, chlor_alkali)
    d.check("Electricity for electrolysis, bipolar membrane cells (AC)", ac_kwh_t, [2279, 2865], "kWh/t Cl2",
            SRC + ", Table 3.10 (bipolar, EU-27 and EFTA, min to max; average 2,574)", BREF, tol=10, kind="energy",
            note="Voltage line through the fleet average operating points of the same table, so this is a "
                 "consistency check of Faraday, current efficiency and rectifier losses, not an independent one.")
    d.check("Electricity, cells plus other equipment (membrane, median plant)", (P_ac + other_kw) / tCl2, 2800,
            "kWh/t Cl2", SRC + ", Table 3.13 (median membrane plant: 2,600 cells + 200 other)", BREF, tol=10,
            kind="energy", note="Model 'other' is pumps only, so it sits below the 200 kWh/t the survey reports.")
    d.check("Salt consumption", salt_kg_t, 1700, "kg NaCl/t Cl2", SRC + ", Table 3.3 (median of 62 plants)", BREF,
            tol=5, note="Purge set at the Table 3.5 median (0.33 m3/t); theory is 1,648 kg/t.")
    d.check("Steam for caustic evaporation to 50%", steam_ev_t, [0.46, 1.5], "t/t NaOH (100%)",
            SRC + ", Table 3.11 (membrane, min to max, median 0.70)", BREF, tol=20, kind="energy")
    d.check("Steam for brine and equipment heating", steam_bh_t, [0.08, 1.27], "t/t Cl2",
            SRC + ", Table 3.12 (all cell techniques, median 0.23)", BREF, tol=50, kind="energy",
            note="From the cell energy balance: at 5 kA/m2 the Joule heat almost exactly covers brine heating and the "
                 "water evaporated into the gases, so no steam is needed. Heat losses from the cell room, tanks "
                 "and dechlorination are not modelled, and the BREF notes membrane plants at low current density "
                 "need the most steam.")
    d.check("Chlorine liquefaction electricity", liq_kwh_t, [8, 200], "kWh/t Cl2", SRC + ", Table 3.12 (median 53)",
            BREF, tol=20, kind="energy")
    d.check("Caustic soda per tonne of chlorine", naoh_t_t, 1.128, "t NaOH/t Cl2",
            SRC + ", Table 3.13 note 4 (production ratio)", BREF, tol=2)
    new_eur_t = 1000 * (100 / cap_kt) ** 0.3
    d.check("Fixed capital, new membrane cell plant, scaled", None,
            new_eur_t * cap_kt * 1000 * EUR_USD_2010 * C.CEPCI[C.BASE_YEAR] / C.CEPCI[2010], "USD",
            SRC + ", mercury cell conversion costs (PDF page 162): a completely new membrane cell plant about EUR 1,000/t annual Cl2 capacity "
            "(Euro Chlor 2010) for 100 kt/yr. Scaled by BREF Equation 2, converted at 1.3261 USD/EUR (2010) and "
            "CEPCI 550.8 to 800.0", BREF, tol=50, kind="capex",
            note="The cell room lump uses the Table 4.4 conversion costs, which assume an existing site, building "
                 "and power supply, and the rest is Turton equipment with standard factors. A greenfield plant "
                 "also carries salt handling, power intake, chlorine storage and site works, so the model sits "
                 "low. Honest fail, not tuned.")

    d.assumptions = [
        f"Cell voltage {V:.2f} V from a straight line through the bipolar fleet averages in BREF Table 3.10 "
        f"(2.86 V at 2.9 kA/m2, 3.40 V at 5.4 kA/m2, k {K_V:.3f} V per kA/m2). New zero gap cells run lower "
        "(BREF: about 3.0 V at 6 kA/m2).",
        f"Current efficiency {CE * 100:.0f}% (BREF: above 95% for new membranes); the lost charge makes oxygen at the "
        f"anode. Rectifier and transformer efficiency {p['rectifier_eff_pct']:.0f}% (BREF: 94 to 98%).",
        "Water carried through the membrane taken as 4.0 mol per mol Na+; this sets how much condensate goes back "
        "to the catholyte, not the overall balance. It is a typical design figure, not taken from a fetched source.",
        "Feed brine saturated at 60 C (27.0 wt%, CRC), depleted brine 200 g/L as quoted in the BREF. Salt treated as "
        "pure NaCl; brine treatment chemicals, the HCl used to acidify the anolyte and chlorate are not modelled.",
        "Gases leave the cells saturated with water at the pure water vapour pressure, an upper bound that slightly "
        "overstates brine heating. Cell room heat losses are ignored.",
        "Chlorine is cooled to 15 C (above the hydrate point), dried with 98% acid spent at 65% (spent acid returned "
        "without credit), compressed to 10 bar and liquefied at -5 C. Refrigeration at half Carnot efficiency.",
        f"Caustic evaporated in {p['evap_effects']} effects; each kg of 10 bar steam evaporates "
        f"{p['evap_effects']} kg times the latent heat ratio. Heat of dilution of NaOH is ignored.",
        "Hydrogen is burnt in the site boiler and credited at the natural gas price; it could be sold instead.",
        "Membrane replacement (about EUR 500/m2 and a four year life, BREF economics of membrane cells) is reported "
        "as a KPI but not added to operating cost; the BREF puts it near 1% of variable cost.",
    ]
    d.hazop = [
        {"node": "Electrolysers", "deviation": "Hydrogen in chlorine", "cause": "Membrane pinhole or tear",
         "consequence": "Explosive H2/Cl2 mixture in the chlorine header", "safeguard":
         "H2 in Cl2 analysers, trip on cell voltage deviation, membrane inspection"},
        {"node": "Electrolysers", "deviation": "Loss of brine flow", "cause": "Pump trip",
         "consequence": "Membrane damage, high voltage, local overheating", "safeguard": "Low flow trip of the rectifier"},
        {"node": "Chlorine drying and compression", "deviation": "Wet chlorine", "cause": "Spent acid too weak",
         "consequence": "Rapid corrosion of carbon steel, chlorine leak", "safeguard": "Acid strength analysers, "
         "moisture analyser after the towers"},
        {"node": "Chlorine liquefaction", "deviation": "Hydrogen build up in tail gas", "cause": "High H2 in cell gas",
         "consequence": "Explosive tail gas", "safeguard": "Limit liquefaction ratio, H2 analysers, dilution air"},
        {"node": "Liquid chlorine storage", "deviation": "Loss of containment", "cause": "Corrosion, overfilling",
         "consequence": "Toxic cloud", "safeguard": "Emergency absorption unit, double containment, detectors"},
        {"node": "Hydrogen system", "deviation": "Air ingress", "cause": "Leak at low pressure",
         "consequence": "Fire or explosion", "safeguard": "Positive pressure control, seal pots, O2 analysers"},
    ]
    d.greener = {
        "title": "Run on low carbon power, or use oxygen depolarised cathodes",
        "text": "Nearly all of the footprint is electricity, so the carbon intensity follows the grid. Oxygen "
                "depolarised cathodes lower the cell voltage by about 1 V and the power by about 30% (BREF section "
                "6.2), at the cost of losing the hydrogen and needing pure oxygen.",
        "electricity_MWh_per_t": d.power_kW / 1000 / tCl2,
    }
    return d.finish()
