"""Fuel ethanol from corn by dry grind (dry mill), the route behind most US fuel ethanol.

    Starch hydrolysis:  (C6H10O5) + H2O -> C6H12O6
    Fermentation:       C6H12O6 -> 2 C2H5OH + 2 CO2

Corn is hammer milled, slurried with recycled water, liquefied with alpha amylase at about
85 C after a jet cooker, saccharified with glucoamylase in the fermenters (simultaneous
saccharification and fermentation, about 32 C, 50 to 60 h). The beer is stripped in a beer
column, rectified to about 92.5 wt% and dried to fuel grade on molecular sieves. Whole
stillage is centrifuged; thin stillage is partly recycled as backset and the rest evaporated
to syrup, which is mixed with the wet cake and dried to DDGS in gas fired dryers. Steam comes
from an on site gas fired package boiler.

Corn basis: one bushel is 56 lb at 15.5% moisture; dry matter is 72.0% starch and 2.6% simple
sugars (Purdue ID-328). Benchmarks: Mueller and Kwik, 2012 Corn Ethanol survey.
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 1000.0,  # t/d anhydrous ethanol
    "corn_moisture": 0.155,  # 15.5% moisture, the US bushel basis
    "starch_dry": 0.720,  # Purdue ID-328, Table 1
    "sugars_dry": 0.026,  # Purdue ID-328, Table 1
    "starch_conversion": 0.98,  # starch hydrolysed to glucose (assumed)
    "fermentation_efficiency": 0.95,  # glucose to ethanol, share of the theoretical 0.511 g/g (assumed)
    "mash_solids": 0.32,  # wt% dry solids in the mash
    "backset_frac": 0.30,  # share of thin stillage recycled to the mash
    "beer_overhead_wt": 0.50,  # ethanol wt fraction in the beer column vapour
    "rectifier_wt": 0.925,  # ethanol wt fraction to the molecular sieves
    "sieve_regen_frac": 0.15,  # share of sieve feed used to regenerate and recycled to the rectifier
    "wetcake_solids": 0.35,
    "syrup_solids": 0.35,
    "thin_stillage_solids_split": 0.30,  # share of the stillage solids that leave in the thin stillage
    "ddgs_moisture": 0.10,
    "beer_preheat_C": 85.0,  # beer heated against stillage before the column
    "boiler_eff": 0.85,  # package boiler, LHV
    "dryer_kJ_per_kg_water": 3300.0,  # gas fired ring or rotary dryer, about 1.4 times the latent heat
    "evaporator_effects": 4,
    "rectifier_reflux": 1.5,  # extra reflux vapour raised by the side stripper, per unit distillate vapour  # thin stillage evaporators heated by distillation vapour
}

LB = 0.45359237
GAL = 3.785411784  # L
RHO_ETOH = 0.7893  # kg/L at 20 C
BU_KG = 56 * LB  # one bushel of corn at 15.5% moisture
BTU_KJ = 1.055056

SOLID = {"Starch": "s", "CornSolids": "s", "Glucose": "s", "EtOH": "l", "H2O": "l", "CO2": "g"}


def _h(flows, T):
    return sum(n * core.h_molar(c, T, SOLID.get(c, "l")) for c, n in flows.items()) / 3600.0  # kW


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)

    MW = th.MW
    # ---------------------------------------------------------------- yields per kg corn
    dry = 1 - p["corn_moisture"]
    w_starch = dry * p["starch_dry"]
    w_sugar = dry * p["sugars_dry"]
    w_solids = dry - w_starch - w_sugar
    Xs, Ef = p["starch_conversion"], p["fermentation_efficiency"]
    glc_kmol = w_starch * Xs / MW("Starch") + w_sugar / MW("Glucose")  # kmol glucose per kg corn
    etoh_kg_per_kg = glc_kmol * Ef * 2 * MW("EtOH")

    P_kg_h = p["capacity_tpd"] * 1000 / 24
    corn_kg_h = P_kg_h / etoh_kg_per_kg
    f_corn = {"Starch": corn_kg_h * w_starch / MW("Starch"), "Glucose": corn_kg_h * w_sugar / MW("Glucose"),
              "CornSolids": corn_kg_h * w_solids / MW("CornSolids"), "H2O": corn_kg_h * p["corn_moisture"] / MW("H2O")}
    hyd = f_corn["Starch"] * Xs
    glc = f_corn["Glucose"] + hyd
    ferm = glc * Ef
    etoh = 2 * ferm
    co2 = 2 * ferm

    # ---------------------------------------------------------------- recycle loop (steady state)
    # Unconverted solids (residual starch, residual sugar standing for yeast and glycerol, corn protein,
    # fibre, oil, ash) pass through. A share of them returns with the backset, so at steady state the
    # stillage carries X = S0 / (1 - b * split) of each, where S0 is what the fresh corn leaves behind.
    sol_keys = ("Starch", "Glucose", "CornSolids")
    split = p["thin_stillage_solids_split"]
    b = p["backset_frac"]
    S0 = {"Starch": f_corn["Starch"] - hyd, "Glucose": glc - ferm, "CornSolids": f_corn["CornSolids"]}
    loop = 1 / (1 - b * split)
    X = {k: v * loop for k, v in S0.items()}
    f_back_sol = {k: X[k] * split * b for k in sol_keys}

    # ---------------------------------------------------------------- mash and fermentation
    dry_kg_h = corn_kg_h * dry + _kg(f_back_sol)
    mash_kg_h = dry_kg_h / p["mash_solids"]
    W_mash = (mash_kg_h - dry_kg_h) / MW("H2O")  # kmol/h water in the mash
    f_mash = core.add(f_corn, f_back_sol)
    f_mash["H2O"] = W_mash
    f_sacch = {"Starch": f_mash["Starch"] - hyd, "Glucose": f_mash["Glucose"] + hyd,
               "CornSolids": f_mash["CornSolids"], "H2O": W_mash - hyd}
    # CO2 leaves the fermenters saturated; the water scrubber returns the ethanol to the beer well
    vent_h2o = co2 * 0.04  # about 4 mol% water at 32 C and 1 bar
    f_vent = {"CO2": co2, "H2O": vent_h2o}
    f_beer = {"Starch": X["Starch"], "Glucose": X["Glucose"], "CornSolids": X["CornSolids"],
              "EtOH": etoh, "H2O": f_sacch["H2O"] - vent_h2o}
    beer_kg = _kg(f_beer)
    beer_etoh_wt = etoh * MW("EtOH") / beer_kg

    # ---------------------------------------------------------------- distillation
    x_ov = p["beer_overhead_wt"]
    f_beer_ov = {"EtOH": etoh, "H2O": etoh * MW("EtOH") * (1 - x_ov) / x_ov / MW("H2O")}
    f_stillage = {k: v for k, v in f_beer.items() if k != "EtOH"}
    f_stillage["H2O"] -= f_beer_ov["H2O"]
    x_r = p["rectifier_wt"]
    regen = p["sieve_regen_frac"]
    # the sieves take out all the water plus a share of the ethanol as regenerant, both go back to the rectifier
    sieve_h2o = etoh * MW("EtOH") * (1 - x_r) / x_r / MW("H2O")
    f_sieve_in = {"EtOH": etoh / (1 - regen), "H2O": sieve_h2o}
    f_regen = {"EtOH": f_sieve_in["EtOH"] - etoh, "H2O": sieve_h2o}
    f_rect_in = core.add(f_beer_ov, f_regen)
    f_rect_btm = {"H2O": f_beer_ov["H2O"]}  # side stripper bottoms, recycled to the slurry tank
    f_product = {"EtOH": etoh}

    # ---------------------------------------------------------------- stillage, evaporation, drying
    f_cake = {k: X[k] * (1 - split) for k in sol_keys}
    cake_sol_kg = _kg(f_cake)
    f_cake["H2O"] = cake_sol_kg * (1 - p["wetcake_solids"]) / p["wetcake_solids"] / MW("H2O")
    f_thin = {k: X[k] * split for k in sol_keys}
    f_thin["H2O"] = f_stillage["H2O"] - f_cake["H2O"]
    f_backset = core.scale(f_thin, b)
    f_thin_ev = core.scale(f_thin, 1 - b)
    f_syrup = {k: f_thin_ev[k] for k in sol_keys}
    f_syrup["H2O"] = _kg(f_syrup) * (1 - p["syrup_solids"]) / p["syrup_solids"] / MW("H2O")
    f_evap_cond = {"H2O": f_thin_ev["H2O"] - f_syrup["H2O"]}
    f_dryer_in = core.add(f_cake, f_syrup)
    f_ddgs = {k: f_dryer_in[k] for k in sol_keys}
    dd_solids_kg = _kg(f_ddgs)
    f_ddgs["H2O"] = dd_solids_kg * p["ddgs_moisture"] / (1 - p["ddgs_moisture"]) / MW("H2O")
    f_dryer_vap = {"H2O": f_dryer_in["H2O"] - f_ddgs["H2O"]}

    # ---------------------------------------------------------------- water recycle and make up
    recycled = f_backset["H2O"] + f_evap_cond["H2O"] + f_rect_btm["H2O"]
    fresh_h2o = W_mash - f_corn["H2O"] - recycled
    # a negative value means surplus condensate, which is sent to treatment
    purge_h2o = max(0.0, -fresh_h2o)
    fresh_h2o = max(0.0, fresh_h2o)
    f_evc_recyc = {"H2O": f_evap_cond["H2O"] - purge_h2o}

    TF = 32 + 273.15
    T_liq = 85 + 273.15
    T_slurry = 60 + 273.15

    # ---------------------------------------------------------------- flowsheet
    d = Design("ethanol", "Fuel ethanol plant (corn dry grind)", "Ethanol", p["capacity_tpd"], region)
    d.solids_steps = 3  # grain receiving and milling, centrifuges, DDGS drying and load out
    d.route = ("Dry grind: corn is milled, cooked with enzymes to turn starch into sugar, fermented by yeast, then "
               "distilled and dried on molecular sieves to fuel ethanol. The leftover grain is dried to DDGS for animal feed.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of fuel ethanol from {corn_kg_h * 24 / 1000:,.0f} t/d of corn, "
                 f"with {_kg(f_ddgs) * 24 / 1000:,.0f} t/d of DDGS.")
    dH_hyd = (core.h_molar("Glucose", 298.15, "s") - core.h_molar("Starch", 298.15, "s") - core.h_molar("H2O", 298.15, "l")) / 1000
    dH_f = (2 * core.h_molar("EtOH", 298.15, "l") + 2 * core.h_molar("CO2", 298.15, "g") - core.h_molar("Glucose", 298.15, "s")) / 1000
    d.reactions = [
        {"eq": "(C6H10O5)n + n H2O -> n C6H12O6", "where": "Liquefaction and saccharification (alpha amylase, glucoamylase)",
         "dH_kJ": dH_hyd},
        {"eq": "C6H12O6 -> 2 C2H5OH + 2 CO2", "where": "Fermenters (Saccharomyces cerevisiae)", "dH_kJ": dH_f},
    ]
    gal_per_bu = etoh_kg_per_kg * BU_KG / RHO_ETOH / GAL
    d.conditions = [
        ("Mash solids", f"{p['mash_solids'] * 100:.0f} wt%"),
        ("Liquefaction", "jet cooker then 85 C, about 2 h, alpha amylase"),
        ("Fermentation", f"{TF - 273.15:.0f} C, 50 to 60 h, simultaneous saccharification"),
        ("Beer strength", f"{beer_etoh_wt * 100:.1f} wt% ethanol"),
        ("Rectifier overhead", f"{x_r * 100:.1f} wt% ethanol to the molecular sieves"),
        ("Product", "anhydrous ethanol, 99.5 wt% or better (before denaturant)"),
        ("Ethanol yield", f"{gal_per_bu:.2f} gal per bushel"),
    ]

    s_corn = d.stream("Corn", f_corn, 298.15, 1.013, phase="s", phases=SOLID)
    s_water = d.stream("Fresh process water", {"H2O": fresh_h2o}, 293.15, 3.0, phase="l")
    s_mash = d.stream("Mash", f_mash, T_slurry, 3.0, phase="mixed", phases=SOLID)
    s_liq = d.stream("Liquefied mash", f_sacch, T_liq, 3.0, phase="mixed", phases=SOLID)
    s_vent = d.stream("Fermentation CO2 (biogenic, scrubbed)", f_vent, TF, 1.013, phase="g")
    s_beer = d.stream("Beer", f_beer, TF, 3.0, phase="mixed", phases=SOLID)
    s_bov = d.stream("Beer column vapour", f_beer_ov, 368.15, 1.5, phase="g")
    s_still = d.stream("Whole stillage", f_stillage, 373.15, 1.5, phase="mixed", phases=SOLID)
    s_sin = d.stream("Rectifier overhead to sieves", f_sieve_in, 351.15, 1.3, phase="g")
    s_regen = d.stream("Sieve regenerant (recycled)", f_regen, 333.15, 0.2, phase="l")
    s_rbtm = d.stream("Rectifier and side stripper bottoms", f_rect_btm, 373.15, 1.5, phase="l")
    s_prod = d.stream("Anhydrous ethanol", f_product, 313.15, 2.0, phase="l")
    s_cake = d.stream("Wet cake", f_cake, 353.15, 1.013, phase="mixed", phases=SOLID)
    s_thin = d.stream("Thin stillage", f_thin, 353.15, 2.0, phase="mixed", phases=SOLID)
    s_back = d.stream("Backset", f_backset, 353.15, 2.0, phase="mixed", phases=SOLID)
    s_tev = d.stream("Thin stillage to evaporators", f_thin_ev, 353.15, 2.0, phase="mixed", phases=SOLID)
    s_syrup = d.stream("Syrup", f_syrup, 343.15, 2.0, phase="mixed", phases=SOLID)
    s_evc = d.stream("Evaporator condensate (recycled)", f_evc_recyc, 343.15, 2.0, phase="l")
    s_ddgs = d.stream("DDGS", f_ddgs, 313.15, 1.013, phase="s", phases=SOLID)
    s_dvap = d.stream("Dryer exhaust water vapour", f_dryer_vap, 393.15, 1.013, phase="g")
    s_purge = d.stream("Surplus condensate", {"H2O": purge_h2o}, 313.15, 1.013, phase="l") if purge_h2o > 0 else None

    d.feed(s_corn, {"Starch": "Corn", "Glucose": "Corn", "CornSolids": "Corn", "H2O": "Corn"})
    d.feed(s_water)
    d.out(s_prod, "product", {"EtOH": "EtOH"})
    d.out(s_ddgs, "byproduct", {"Starch": "DDGS", "Glucose": "DDGS", "CornSolids": "DDGS", "H2O": "DDGS"})
    # biogenic CO2: carbon taken up by the corn, so it is shown but not counted as direct fossil CO2
    d.out(s_vent, "byproduct")
    d.out(s_dvap, "byproduct")
    if purge_h2o > 0:
        d.out(s_purge, "waste")

    d.unit("M-101", "Hammer mills and slurry tank", "mixer", [s_corn, s_water, s_back, s_evc, s_rbtm], [s_mash], (0, 0))
    d.unit("R-101", "Jet cooker and liquefaction tanks", "reactor", [s_mash], [s_liq], (1, 0))
    d.unit("R-102", "Fermenters (SSF)", "reactor", [s_liq], [s_beer, s_vent], (2, 0))
    d.unit("T-101", "Beer column", "column", [s_beer], [s_bov, s_still], (3, 0))
    d.unit("T-102", "Rectifier and side stripper", "column", [s_bov, s_regen], [s_sin, s_rbtm], (4, 0))
    d.unit("A-101", "Molecular sieve beds", "adsorber", [s_sin], [s_prod, s_regen], (5, 0))
    d.unit("S-101", "Decanter centrifuges", "centrifuge", [s_still], [s_cake, s_thin], (3, 1))
    d.unit("V-101", "Thin stillage tank (backset split)", "drum", [s_thin], [s_back, s_tev], (2, 1))
    d.unit("E-201", "Thin stillage evaporators", "evaporator", [s_tev], [s_syrup, s_evc] + ([s_purge] if purge_h2o > 0 else []), (4, 1))
    d.unit("D-101", "DDGS dryers", "dryer", [s_cake, s_syrup], [s_ddgs, s_dvap], (5, 1))

    # ---------------------------------------------------------------- energy
    lp = 2100.0  # kJ/kg, low pressure steam latent heat
    steam_items = []
    # cooking: slurry at 60 C (hot backset and condensate) raised to 85 C by direct steam in the jet cooker
    Q_cook = mash_kg_h * 3.8 * (T_liq - T_slurry) / 3600
    steam_items.append(("Jet cooker and liquefaction", Q_cook))
    # fermentation: cool the mash to 32 C, then remove the heat of fermentation
    Q_mash_cool = mash_kg_h * 3.8 * (T_liq - TF) / 3600
    Q_ferm = -ferm * dH_f * 1000 / 3600
    d.cooling(Q_mash_cool * 0.5, "Mash cooler (after interchange with beer)")
    d.cooling(Q_ferm, "Fermenter cooling (heat of fermentation)")
    # beer column: beer preheated against stillage, the reboiler supplies the rest of the sensible heat and the vapour
    T_pre = p["beer_preheat_C"] + 273.15
    Q_beer_sens = beer_kg * 3.9 * (373.15 - T_pre) / 3600
    Q_beer_vap = (f_beer_ov["EtOH"] * th.hvap("EtOH") + f_beer_ov["H2O"] * th.hvap("H2O")) / 3600
    # Split pressure distillation, as used in modern dry mills: the rectifier and side stripper run at about 3 bar
    # and their overhead vapour condenses in the beer column reboiler (beer column under vacuum). Steam covers the
    # side stripper and any shortfall on the beer column; leftover overhead heat goes to the first evaporator effect.
    hv_D = (f_sieve_in["EtOH"] * th.hvap("EtOH") + f_sieve_in["H2O"] * th.hvap("H2O")) / 3600  # kW per unit D vapour
    R = p["rectifier_reflux"]
    Q_rect = R * hv_D
    steam_items.append(("Side stripper reboiler", Q_rect))
    Q_rect_cond = (1 + R) * hv_D  # rectifier overhead condensed in the beer column reboiler
    Q_beer = Q_beer_sens + Q_beer_vap
    Q_beer_steam = max(0.0, Q_beer - Q_rect_cond)
    steam_items.append(("Beer column reboiler (steam trim)", Q_beer_steam))
    Q_left = max(0.0, Q_rect_cond - Q_beer)
    # molecular sieves: superheat the feed vapour; the dry ethanol vapour is condensed against cooling water
    steam_items.append(("Molecular sieve superheater", _kg(f_sieve_in) * 1.8 * 40 / 3600))
    Q_prod_cond = etoh * th.hvap("EtOH") / 3600
    # evaporators: multiple effect on steam, plus any overhead heat left from the distillation
    Q_evap = f_evap_cond["H2O"] * th.hvap("H2O") / 3600 / p["evaporator_effects"]
    Q_evap_steam = max(0.0, Q_evap - Q_left)
    steam_items.append(("Evaporators, first effect", Q_evap_steam))
    Q_ov_cw = max(0.0, Q_left - Q_evap) + Q_prod_cond + Q_evap  # last effect vapour goes to cooling water
    d.cooling(Q_ov_cw, "Product and last effect condensers")
    Q_steam = sum(q for _, q in steam_items)
    steam_kg_h = Q_steam / lp * 3600
    # on site boiler: steam is raised from natural gas, not bought
    boiler_GJ_h = Q_steam * 3600 / 1e6 / p["boiler_eff"]
    d.fuel(boiler_GJ_h, "Package boiler (process steam)")
    # dryers: natural gas fired, about 1.4 times the latent heat per kg water removed (includes air losses)
    dry_GJ_h = _kg(f_dryer_vap) * p["dryer_kJ_per_kg_water"] / 1e6
    d.fuel(dry_GJ_h, "DDGS dryers")
    # power: specific loads per unit throughput (engineering estimates, listed so they can be checked)
    corn_t_h = corn_kg_h / 1000
    P_mill = 12.0 * corn_t_h  # hammer mills, about 12 kWh per t of corn through a fine screen
    P_conv = 2.0 * (corn_t_h + _kg(f_ddgs) / 1000)  # grain and DDGS conveyors, elevators, load out, about 2 kWh/t
    P_agit = 0.04 * mash_kg_h / 1000 * 55 / 1.1  # fermenter agitators, about 0.04 kW/m3 over a 55 h hold
    P_cent = 1.2 * _kg(f_stillage) / 1000  # decanters about 1.2 kW per t/h whole stillage
    P_dryer = 45.0 * _kg(f_dryer_vap) / 1000  # dryer, cyclone and thermal oxidiser fans, about 45 kW per t/h water
    cw_kW_total = Q_mash_cool * 0.5 + Q_ferm + Q_ov_cw
    cw_m3_h = cw_kW_total * 3.6 / (4.18 * 10)
    P_cw = cw_m3_h / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw_kW_total  # circulation at 3.5 bar plus tower fans
    P_vac = 0.02 * _kg(f_sieve_in) / 1000 * 100  # sieve vacuum pumps
    P_scrub = 0.08 * co2 * 44 / 1000 * 10  # CO2 scrubber blower, about 0.8 kW per t/h CO2
    d.power(P_mill, "Hammer mills")
    d.power(P_conv, "Grain and DDGS handling")
    d.power(P_agit, "Fermenter agitators")
    d.power(P_cent, "Decanter centrifuges")
    d.power(P_dryer, "Dryer and oxidiser fans")
    d.power(P_cw, "Cooling water pumps and tower fans")
    d.power(P_vac, "Sieve vacuum pumps")
    d.power(P_scrub, "CO2 scrubber blower")
    # cooling tower make up: evaporation of about 1.8% of circulation per 10 K plus blowdown, about 1.5 times the latent loss
    ct_makeup_m3_h = cw_kW_total * 3600 / 2400 / 1000 * 1.5
    d.process_water_m3_h = ct_makeup_m3_h + fresh_h2o * th.MW("H2O") / 1000

    # ---------------------------------------------------------------- equipment
    mash_m3_h = mash_kg_h / 1080
    d.generic("C-101", "Hammer mills", "fan", max(1.0, corn_t_h / 20), f"{corn_t_h:,.0f} t/h corn",
              note="Costed on the fan correlation as a stand in; see the grain handling allowance")
    d.lump("Grain receiving, storage silos and hammer mills", 180000.0 * corn_t_h ** 0.6 * 4,
           "Allowance scaled from corn throughput; Turton has no correlation for grain handling")
    V_liq = mash_m3_h * 2.0
    d.generic("R-101", "Liquefaction tanks", "tank_fixed_roof", max(90.0, V_liq), f"{V_liq:,.0f} m3, 2 h hold", material="SS")
    d.hx("E-101", "Jet cooker", Q_cook, 433.15, 433.15, T_slurry, T_liq, "liquid-steam", material="SS")
    d.hx("E-102", "Mash cooler", Q_mash_cool * 0.5, T_liq, TF + 5, 298.15, 308.15, "liquid-water", material="SS")
    V_ferm = mash_m3_h * 55 / 0.85
    n_ferm = max(3, int(-(-V_ferm // 2500)))
    d.generic("R-102", "Fermenters", "tank_fixed_roof", V_ferm, f"{n_ferm} x {V_ferm / n_ferm:,.0f} m3, 55 h", material="SS",
              note="Field erected fermenters costed on the fixed roof tank correlation in stainless steel")
    d.generic("V-102", "Beer well", "tank_fixed_roof", mash_m3_h * 12, f"{mash_m3_h * 12:,.0f} m3, 12 h", material="SS")
    d.hx("E-103", "Fermenter coolers", Q_ferm, TF + 2, TF, 298.15, 306.15, "liquid-water", material="SS")
    d.column("T-103", "CO2 scrubber", co2, 308.15, 1.1, 8, 44.0, material="SS")
    d.column("T-101", "Beer column (vacuum)", sum(f_beer_ov.values()) * 1.3, 343.15, 0.5, 20, 30.0, material="SS")
    d.hx("E-104", "Beer and stillage interchanger", beer_kg * 3.9 * (T_pre - TF - 10) / 3600 * 0.5, 373.15, 323.15, TF, T_pre,
         "liquid-liquid", material="SS")
    d.hx("E-105", "Beer column reboiler (rectifier vapour and steam)", Q_beer, 400.15, 398.15, 343.15, 348.15, "reboiler",
         material="SS")
    d.column("T-102", "Rectifier and side stripper", sum(f_sieve_in.values()) * (1 + R), 400.15, 3.0, 40, 40.0, material="SS")
    d.hx("E-106", "Product condenser", Q_prod_cond, 351.15, 345.15, 303.15, 313.15, "condenser", material="SS")
    sieve_kg_h = _kg(f_sieve_in)
    d.vessel("A-101", "Molecular sieve beds (2 or 3 beds)", max(5.0, sieve_kg_h / 1000 * 1.2), P_barg=1.0, material="SS",
             service="3A zeolite, pressure swing")
    d.generic("S-101", "Decanter centrifuges", "centrifuge", min(2.0, 0.5 + _kg(f_stillage) / 1000 / 150),
              f"{_kg(f_stillage) / 1000:,.0f} t/h whole stillage", material="SS")
    A_evap = Q_evap * p["evaporator_effects"] * 1000 / (1500 * 8)  # U 1.5 kW/m2K, 8 K per effect
    d.generic("E-201", "Thin stillage evaporators (falling film)", "hx_fixed_tube", A_evap,
              f"{p['evaporator_effects']} effects, {A_evap:,.0f} m2", material="SS",
              note="Falling film effects costed as stainless shell and tube exchangers; the Turton evaporator correlation is for forced circulation units")
    # direct fired rotary drums: about 60 kg water per m3 drum per h; lateral area of a drum is 4 V / D with D 4.5 m
    V_dry = _kg(f_dryer_vap) / 60
    A_dry = V_dry * 4 / 4.5
    d.generic("D-101", "DDGS dryers (rotary drums)", "dryer_rotary", A_dry, f"{_kg(f_dryer_vap) / 1000:,.1f} t/h water removed",
              note=f"{V_dry:,.0f} m3 of drum at 60 kg water per m3 h")
    d.heater("B-101", "Package boilers", Q_steam, kind="boiler")
    d.tank("TK-101", "Ethanol product tanks", P_kg_h, 789, days=10)
    d.tank("TK-102", "Denaturant tank", P_kg_h * 0.025, 700, days=10)
    d.lump("DDGS flat storage and load out", 25.0 * _kg(f_ddgs) * 24 * 5 / 1000 * 1.6,
           "Allowance of about 25 USD per t of covered flat storage for 5 days of DDGS, with handling")
    d.pump("P-101", "Mash pump", mash_kg_h, 1080, 4, material="SS")
    d.pump("P-102", "Beer pump", beer_kg, 1030, 4, material="SS")
    d.pump("P-103", "Stillage pump", _kg(f_stillage), 1050, 4, material="SS")
    d.pump("P-104", "Thin stillage and backset pump", _kg(f_thin), 1020, 3, material="SS")
    d.pump("P-105", "Rectifier reflux pump", _kg(f_sieve_in) * R, 850, 3, material="SS")
    # fermenter recirculation through the external coolers, 3 K rise on the mash side
    d.pump("P-106", "Fermenter recirculation pumps", Q_ferm * 3600 / (3.8 * 3), 1050, 2.5, material="SS")
    d.power(0.05 * d.power_kW, "Compressed air, lighting, HVAC and wastewater (5% of process load)")

    # ---------------------------------------------------------------- KPIs and checks
    gal_h = P_kg_h / RHO_ETOH / GAL
    thermal_btu_gal = (boiler_GJ_h + dry_GJ_h) * 1e6 / BTU_KJ / gal_h
    kwh_gal = d.power_kW / gal_h
    ddg_lb_bu = dd_solids_kg / (corn_kg_h / BU_KG) / LB
    fresh_m3_h = (fresh_h2o * MW("H2O")) / 1000 + ct_makeup_m3_h
    water_gal_gal = fresh_m3_h * 1000 / GAL / gal_h
    ddgs_t_t = _kg(f_ddgs) / P_kg_h
    d.kpis = [
        {"label": "Ethanol yield", "value": gal_per_bu, "unit": "gal per bushel"},
        {"label": "Corn use", "value": corn_kg_h / P_kg_h, "unit": "t/t ethanol"},
        {"label": "DDGS (10% moisture)", "value": ddgs_t_t, "unit": "t/t ethanol"},
        {"label": "Thermal energy (natural gas)", "value": thermal_btu_gal, "unit": "Btu/gal LHV"},
        {"label": "Electricity", "value": kwh_gal, "unit": "kWh/gal"},
        {"label": "Fresh water", "value": water_gal_gal, "unit": "gal/gal ethanol"},
        {"label": "Beer strength", "value": beer_etoh_wt * 100, "unit": "wt% ethanol"},
    ]
    MK = "https://d35t1syewk4d42.cloudfront.net/file/1462/2012-Corn-Ethanol-Emerging-Plant-Energy-and-Environmental-Technologies.pdf"
    MKS = "Mueller and Kwik, 2012 Corn Ethanol: Emerging Plant Energy and Environmental Technologies (UIC ERC)"
    d.check("Ethanol yield", gal_per_bu, 2.82, "gal/bu (anhydrous)", MKS, MK, tol=3,
            note="Model yield from starch and sugar content (Purdue ID-328), 98% starch conversion and 95% fermentation efficiency.")
    d.check("Thermal energy use", thermal_btu_gal, 23862, "Btu/gal (LHV)", MKS, MK, tol=20,
            note="Boiler gas for cooking, distillation, sieves and evaporators plus dryer gas, from the energy balance. "
                 "The model dries all distillers grains; the survey average covers plants that sell part as wet cake.")
    d.check("Electricity use", kwh_gal, 0.75, "kWh/gal", MKS, MK, tol=20,
            note="Sum of the listed motor loads. Reads low: corn oil extraction, chillers and the thermal oxidiser are not "
                 "modelled, and real plants run motors well below their best efficiency point.")
    d.check("DDG yield, dry basis", ddg_lb_bu, 15.73, "lb/bu", MKS, MK, tol=10,
            note="Model DDG excludes yeast cell mass, which is why it reads a little low.")
    d.check("Fresh water use", water_gal_gal, 2.70, "gal/gal", MKS, MK, tol=30,
            note="Process make up plus cooling tower evaporation and blowdown; the plant recycles all condensate.")

    d.assumptions = [
        "Corn: 56 lb per bushel at 15.5% moisture; dry matter 72.0% starch and 2.6% simple sugars (Purdue ID-328, Table 1). "
        "The rest (protein, fibre, oil, ash) passes through to DDGS.",
        f"{Xs * 100:.0f}% of the starch is hydrolysed to glucose and {Ef * 100:.0f}% of the glucose is fermented at the theoretical "
        "0.511 g ethanol per g glucose; the rest of the glucose stands for yeast growth and glycerol and ends up in DDGS.",
        "Corn oil extraction, which most plants now run, is not modelled; the oil stays in the DDGS.",
        "Fermentation CO2 is biogenic and is vented after a water scrubber; it is shown as a by-product and is not counted "
        "as fossil CO2. Many plants sell it to CO2 merchants.",
        f"Steam from an on site gas boiler ({p['boiler_eff'] * 100:.0f}% efficient on LHV); DDGS dryers are gas fired at "
        f"{p['dryer_kJ_per_kg_water']:,.0f} kJ per kg water removed.",
        f"Beer column overhead {x_ov * 100:.0f} wt% ethanol; the rectifier runs on beer column vapour and its condensers feed "
        f"the {p['evaporator_effects']} effect thin stillage evaporators.",
        f"Wet cake {p['wetcake_solids'] * 100:.0f}% solids, syrup {p['syrup_solids'] * 100:.0f}% solids, "
        f"{b * 100:.0f}% of thin stillage recycled as backset, DDGS at {p['ddgs_moisture'] * 100:.0f}% moisture.",
        "Denaturant blending, enzyme and yeast costs and chemicals are not itemised.",
        "Fermenters are field erected tanks costed on the fixed roof tank correlation; grain handling is an allowance.",
    ]
    d.hazop = [
        {"node": "Grain receiving and hammer mills", "deviation": "Dust cloud", "cause": "Leaking conveyors, open transfer points",
         "consequence": "Grain dust explosion",
         "safeguard": "Dust collection, explosion venting and isolation, housekeeping, spark detection on mills"},
        {"node": "Fermenters", "deviation": "Loss of ventilation", "cause": "Entry or work near open hatches",
         "consequence": "Asphyxiation from CO2 build up in the fermenter or cellar",
         "safeguard": "Confined space permits, CO2 detectors, forced ventilation before entry"},
        {"node": "Fermenters", "deviation": "High temperature", "cause": "Cooling water loss during peak fermentation",
         "consequence": "Yeast stress, stuck fermentation, contamination", "safeguard": "Temperature alarms, standby cooling pumps"},
        {"node": "Distillation and ethanol storage", "deviation": "Loss of containment", "cause": "Seal or flange failure, tank overfill",
         "consequence": "Flammable ethanol vapour, pool fire", "safeguard": "Bunding, high level trips, gas detection, foam systems"},
        {"node": "DDGS dryers", "deviation": "High temperature", "cause": "Low moisture feed, burner control fault",
         "consequence": "Dryer fire, smouldering in DDGS storage",
         "safeguard": "Exhaust temperature trips, spark detection and deluge, cooling of DDGS before storage"},
    ]
    d.greener = {
        "title": "Corn oil extraction, CO2 capture and biogas",
        "text": "Extracting corn oil from the syrup gives a biodiesel feedstock, the fermentation CO2 is almost pure and cheap to "
                "capture for sale or storage, and a combined heat and power unit or biogas from thin stillage cuts the gas "
                "bought for steam and drying.",
    }
    r = d.finish()
    # plant cost per gallon of annual capacity (2026 survey)
    gal_yr = gal_h * d.hours
    fci = r["capex"]["fixed_capital"]
    r["validation"].append(_cost_check(fci / gal_yr))
    r["kpis"].append({"label": "Fixed capital per annual gallon", "value": fci / gal_yr, "unit": "USD/gal"})
    return r


def _cost_check(model):
    from .. import cost as C
    pub = 2.11 * C.CEPCI[C.BASE_YEAR] / C.CEPCI[2007]  # 2007 build cost escalated with CEPCI
    err = (model - pub) / pub * 100
    return {"metric": "Plant construction cost per annual gallon (2024 USD)", "model": model, "published": round(pub, 2), "unit": "USD/gal",
            "error_pct": err, "inside_range": None,
            "source": "farmdoc daily (University of Illinois), 4 March 2026, representative Iowa ethanol plant model",
            "url": "https://farmdocdaily.illinois.edu/wp-content/uploads/2026/03/fdd030426.pdf",
            "note": "Published figure is $2.11 per gallon for a 100 million gallon dry mill built in 2007, escalated here to the "
                    "2024 cost basis with CEPCI (525.4 to 800). Shown for information: dry mills were built under fixed price "
                    "design build contracts, so factored estimates scatter widely around this figure.",
            "kind": "cost", "tolerance_pct": None, "pass": None}
