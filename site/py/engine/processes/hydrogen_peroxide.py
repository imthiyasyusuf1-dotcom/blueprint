"""Hydrogen peroxide by the anthraquinone autoxidation process (2-ethylanthraquinone working solution).

A working solution of 2-ethylanthraquinone in an organic solvent mixture circulates round a closed
loop: hydrogenation on palladium turns the quinone into the hydroquinone, air oxidises it back and
releases hydrogen peroxide, and demineralised water extracts the peroxide as a crude 35% solution.
The crude is concentrated to the 50% commercial grade in a vacuum column whose overhead vapour is
mechanically recompressed to drive its own reboiler. Air compression and the distillation are the
main energy users; the reaction heat goes to cooling water.

The solvent is never consumed in quantity and stays inside the battery limit, so the loop is
reported as a working solution flow (from its peroxide productivity) rather than as components;
only the quinone make up, which is degraded and purged, crosses the boundary.
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 200.0,          # t/d of H2O2 on a 100% basis
    "ws_productivity_g_l": 10.0,
    "h2_vent_pct": 2.0,
    "h2_to_water_pct": 3.0,
    "hydrogenation_P_bar": 3.0,
    "hydrogenation_T_C": 55.0,
    "oxidation_P_bar": 4.0,
    "oxidation_T_C": 50.0,
    "o2_excess_pct": 30.0,
    "crude_wt_pct": 35.0,
    "product_wt_pct": 50.0,
    "column_P_bar": 0.06,
    "reflux_ratio": 0.3,
    "mvr": True,
    "quinone_kg_t": 1.0,
}

LVOC = "https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/JRC109279_LVOC_Bref.pdf"
LVOCS = "EU BREF Large Volume Organic Chemicals (2017), chapter 12, hydrogen peroxide"


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    t_h = p["capacity_tpd"] / 24
    MW = {c: th.MW(c) for c in ("H2O2", "H2", "O2", "N2", "H2O", "EAQ")}
    P = t_h * 1000 / MW["H2O2"]                     # kmol/h H2O2
    f_w = p["h2_to_water_pct"] / 100
    h2_react = P / (1 - f_w)
    h2_water = h2_react - P                          # over hydrogenation and peroxide decomposition, net H2 + 1/2 O2 -> H2O
    h2_feed = h2_react / (1 - p["h2_vent_pct"] / 100)
    h2_vent = h2_feed - h2_react
    o2_used = P + h2_water / 2
    o2_air = o2_used * (1 + p["o2_excess_pct"] / 100)
    n2_air = o2_air * 79 / 21
    Po, Ph = p["oxidation_P_bar"], p["hydrogenation_P_bar"]
    To, Thy = p["oxidation_T_C"] + 273.15, p["hydrogenation_T_C"] + 273.15

    # spent air leaves the off-gas condenser at 40 C saturated with water (taken up from the working solution)
    y_w = core.psat("H2O", 313.15) / Po
    off_dry = {"N2": n2_air, "O2": o2_air - o2_used}
    w_off = sum(off_dry.values()) * y_w / (1 - y_w)

    # extraction gives a crude of crude_wt_pct; distillation takes it to product_wt_pct
    xc, xp = p["crude_wt_pct"] / 100, p["product_wt_pct"] / 100
    w_crude = P * MW["H2O2"] * (1 - xc) / xc / MW["H2O"]
    w_prod = P * MW["H2O2"] * (1 - xp) / xp / MW["H2O"]
    w_top = w_crude - w_prod
    h2o2_top = P * 0.002                              # peroxide lost with the column overhead water
    P_net = P - h2o2_top
    # demin water to the extractor = crude water + water lost to spent air - water formed in the loop
    demin = w_crude + w_off - h2_water
    eaq = p["quinone_kg_t"] * t_h / MW["EAQ"]

    # working solution circulation
    ws_m3_h = P * MW["H2O2"] / p["ws_productivity_g_l"]
    ws_kg_h = ws_m3_h * 930.0

    # ---- energy
    T0 = 298.15
    dH_overall = (core.h_molar("H2O2", T0, "l") - core.h_molar("H2", T0, "g") - core.h_molar("O2", T0, "g")) / 1000
    dH_water = (core.h_molar("H2O", T0, "l") - core.h_molar("H2", T0, "g") - 0.5 * core.h_molar("O2", T0, "g")) / 1000
    Q_rxn = -(P * dH_overall + h2_water * dH_water) * 1000 / 3600     # kW released
    Q_hyd, Q_ox = 0.5 * Q_rxn, 0.5 * Q_rxn
    # vacuum column: overhead water vapour (R + 1) times, latent heat at column pressure
    lo, hi = 273.2, 373.2
    for _ in range(60):
        T_top = (lo + hi) / 2
        lo, hi = (T_top, hi) if core.psat("H2O", T_top) < p["column_P_bar"] else (lo, T_top)
    hv = (core.h_molar("H2O", T_top, "g") - core.h_molar("H2O", T_top, "l"))       # kJ/kmol
    V_top = (p["reflux_ratio"] + 1) * (w_top + h2o2_top)
    Q_reb = V_top * hv / 3600
    T_bot = T_top + 22.0                                                          # 50% H2O2 boils about 22 K above water

    d = Design("hydrogen_peroxide", "Hydrogen peroxide plant (anthraquinone autoxidation)", "Hydrogen peroxide",
               p["capacity_tpd"], region)
    d.route = ("A 2-ethylanthraquinone working solution is hydrogenated on palladium, oxidised with compressed air to "
               "release hydrogen peroxide, and the peroxide extracted with demineralised water. The crude is "
               "concentrated to 50% in a vacuum column driven by mechanical vapour recompression, and the working "
               "solution is dried and returned.")
    d.summary = f"{p['capacity_tpd']:,.0f} t/d of hydrogen peroxide (100% basis), sold as 50% solution."
    d.reactions = [
        {"eq": "EAQ + H2 -> EAQH2 (hydroquinone)", "where": "Hydrogenator (Pd)", "dH_kJ": None},
        {"eq": "EAQH2 + O2 -> EAQ + H2O2", "where": "Oxidiser (autoxidation)", "dH_kJ": None},
        {"eq": "H2 + O2 -> H2O2 (overall, liquid)", "where": "Working solution loop", "dH_kJ": dH_overall},
        {"eq": "H2 + 1/2 O2 -> H2O (side reactions, net)", "where": "Working solution loop", "dH_kJ": dH_water},
    ]
    d.conditions = [
        ("Hydrogenation", f"{Ph:.0f} bar, {p['hydrogenation_T_C']:.0f} C, palladium catalyst"),
        ("Oxidation", f"{Po:.0f} bar, {p['oxidation_T_C']:.0f} C, air with {p['o2_excess_pct']:.0f}% excess oxygen"),
        ("Working solution", f"{ws_m3_h:,.0f} m3/h at {p['ws_productivity_g_l']:.0f} g H2O2 per litre"),
        ("Extraction", f"counter current with demineralised water, crude {p['crude_wt_pct']:.0f}% H2O2"),
        ("Distillation", f"{p['column_P_bar'] * 1000:.0f} mbar, reflux {p['reflux_ratio']}, product "
                         f"{p['product_wt_pct']:.0f}%" + (", vapour recompression" if p["mvr"] else "")),
    ]

    s_h2 = d.stream("Hydrogen", {"H2": h2_feed}, 313.15, Ph + 1)
    s_air = d.stream("Process air", {"O2": o2_air, "N2": n2_air}, 298.15, 1.013)
    s_cair = d.stream("Compressed air", {"O2": o2_air, "N2": n2_air}, 313.15, Po + 0.3)
    s_dw = d.stream("Demineralised water", {"H2O": demin}, 298.15, 3.0, phase="l")
    s_q = d.stream("Quinone make up", {"EAQ": eaq}, 298.15, 1.0, phase="s")
    s_hv = d.stream("Hydrogenator vent", {"H2": h2_vent}, Thy, Ph)
    s_off = d.stream("Spent air (after condenser and carbon adsorber)", dict(off_dry, H2O=w_off), 313.15, 1.1)
    s_cr = d.stream("Crude hydrogen peroxide", {"H2O2": P, "H2O": w_crude}, 313.15, 1.5, phase="l")
    s_top = d.stream("Column overhead water", {"H2O": w_top, "H2O2": h2o2_top}, T_top, p["column_P_bar"], phase="l")
    s_pr = d.stream("Hydrogen peroxide 50%", {"H2O2": P_net, "H2O": w_prod}, 303.15, 1.5, phase="l")
    s_res = d.stream("Degraded quinone purge", {"EAQ": eaq}, 313.15, 1.0, phase="l")

    d.feed(s_h2, {"H2": "H2_grey"})
    d.feed(s_air)
    d.feed(s_dw)
    d.feed(s_q, {"EAQ": "EAQ"})
    d.out(s_pr, "product", {"H2O2": "H2O2"})
    d.out(s_hv, "emission")
    d.out(s_off, "emission")
    d.out(s_top, "waste", treat_usd_t=2.0)
    d.out(s_res, "waste", treat_usd_t=500.0)
    d.demin_water_m3_h = demin * MW["H2O"] / 1000

    d.unit("C-101", "Air compressor", "compressor", [s_air], [s_cair], (0, 1))
    d.unit("R-101", "Hydrogenator", "reactor", [s_h2], [s_hv], (1, 0), desc="Pd catalyst, working solution loop")
    d.unit("R-102", "Oxidiser", "reactor", [s_cair], [s_off], (2, 1), desc="Air bubble column")
    d.unit("T-101", "Extraction column", "column", [s_dw], [s_cr], (3, 0), desc="Sieve tray, water continuous")
    d.unit("V-101", "Working solution treatment", "separator", [s_q], [s_res], (2, 0),
           desc="Drying, alkaline reversion and quinone make up")
    d.unit("T-102", "Peroxide concentration column", "column", [s_cr], [s_pr, s_top], (4, 0))

    # ---- utilities
    d.cooling(Q_hyd, "Hydrogenation heat")
    d.cooling(Q_ox, "Oxidation heat")
    Q_offcond = sum(off_dry.values()) * 29.1 * (To - 313.15) / 3600
    d.cooling(Q_offcond, "Spent air condenser")
    W_air, _ = d.compressor("C-101", "Process air compressor", core.Stream("x", "", {"O2": o2_air, "N2": n2_air}, 298.15, 1.013),
                 Po + 0.3)
    W_mvr = 0.0
    if p["mvr"]:
        # overhead vapour recompressed to condense 10 K above the reboiler; 10% of the duty trimmed with steam
        P_cond = core.psat("H2O", T_bot + 10)
        W_mvr, _ = d.compressor("C-102", "Vapour recompressor", core.Stream("x", "", {"H2O": V_top}, T_top, p["column_P_bar"]),
                     P_cond, k=1.33, stages=1)
        d.steam(0.1 * Q_reb * 3600 / 2100.0, "Column reboiler trim")
        d.cooling(0.1 * Q_reb, "Column trim condenser")
    else:
        d.steam(Q_reb * 3600 / 2100.0, "Column reboiler")
        d.cooling(Q_reb, "Column condenser")
    d.pump("P-101", "Working solution pumps (three loop stages)", ws_kg_h * 3, 930, 5, material="SS")
    d.pump("P-102", "Demineralised water and crude pumps", (demin + w_crude) * MW["H2O"], 1100, 4, material="SS")
    d.power(t_h * 15.0, "Vacuum ejectors, filters, carbon adsorbers and small drives")

    # ---- equipment
    d.vessel("R-101", "Hydrogenator (working solution, 10 min)", max(5.0, ws_m3_h / 6), P_barg=Ph, material="SS")
    d.generic("R-102", "Oxidiser column (working solution, 20 min)", "tower", max(5.0, ws_m3_h / 3) * 1.5,
              f"{ws_m3_h / 3:,.0f} m3 liquid", P_barg=Po - 1, material="SS")
    d.generic("T-101", "Extraction column (sieve tray)", "tower", max(5.0, ws_m3_h / 4), f"{ws_m3_h:,.0f} m3/h solvent",
              material="SS")
    d.vessel("V-101", "Working solution dryer and reversion vessels", max(5.0, ws_m3_h / 6), material="SS")
    d.vessel("V-102", "Safety filters and coalescers", max(2.0, ws_m3_h / 30), P_barg=Ph, material="SS")
    d.vessel("V-103", "Spent air carbon adsorbers (two beds)", max(5.0, sum(off_dry.values()) * 22.4 / 3600 * 60),
             material="CS")
    d.hx("E-101", "Hydrogenation cooler", Q_hyd, Thy, Thy - 10, 303.15, 313.15, "liquid-water", material="SS")
    d.hx("E-102", "Oxidiser coolers", Q_ox, To, To - 8, 303.15, 313.15, "liquid-water", material="SS")
    d.cooler_cw("E-104", "Spent air condenser", Q_offcond, To, 313.15, P_barg=Po - 1, service="wet-gas")
    d.column("T-102", "Peroxide concentration column", V_top, T_top, max(p["column_P_bar"], 0.05) + 0.0, 12,
             MW["H2O"], material="SS", packed=True)
    d.hx("E-105", "Column reboiler (falling film, condensing vapour)", Q_reb, T_bot + 10, T_bot + 10, T_bot - 2, T_bot,
         "liquid-steam", material="SS")
    d.tank("TK-101", "Hydrogen peroxide 50% storage (passivated)", P_net * MW["H2O2"] / xp, 1200, days=14,
           material="SS")
    d.tank("TK-102", "Working solution storage (one hour of circulation)", ws_kg_h / 24, 930, days=1, material="SS")

    # ---- KPIs and checks
    per_t = lambda kg_h: kg_h / t_h
    h2_kg_t = per_t(h2_feed * MW["H2"])
    o2_kg_t = per_t(o2_air * MW["O2"])
    air_Nm3_t = (o2_air + n2_air) * 22.414 / t_h
    demin_m3_t = d.demin_water_m3_h / t_h
    air_GJ_t = W_air / 0.95 * 3.6 / 1000 / t_h
    dist_kW = W_mvr / 0.95
    dist_GJ_t = (dist_kW * 3.6 / 1000 + (0.1 if p["mvr"] else 1.0) * Q_reb * 3.6 / 1000) / t_h
    total_GJ_t = (d.power_kW * 3.6 + (d.steam_import_kg_h - d.steam_export_kg_h) * 2.0) / 1000 / t_h
    d.kpis = [
        {"label": "Hydrogen", "value": h2_kg_t, "unit": "kg/t H2O2"},
        {"label": "Oxygen fed in air", "value": o2_kg_t, "unit": "kg/t H2O2"},
        {"label": "Process air", "value": air_Nm3_t, "unit": "Nm3/t H2O2"},
        {"label": "Working solution circulation", "value": ws_m3_h, "unit": "m3/h"},
        {"label": "Electricity", "value": d.power_kW / t_h, "unit": "kWh/t H2O2"},
        {"label": "Net energy", "value": total_GJ_t, "unit": "GJ/t H2O2"},
    ]
    T124 = LVOCS + ", Table 12.4 (input of a hydrogen peroxide plant)"
    T125 = LVOCS + ", Table 12.5 (energy data, three plants, 50% product)"
    d.check("Hydrogen per tonne", h2_kg_t, [60, 70], "kg/t H2O2", T124, LVOC, tol=5, kind="mass_balance")
    d.check("Oxygen per tonne", o2_kg_t, [1000, 1300], "kg/t H2O2", T124, LVOC, tol=5, kind="mass_balance")
    d.check("Process air", air_Nm3_t, [3300, 4600], "Nm3/t H2O2", T124 + ", note 1", LVOC, tol=5,
            kind="mass_balance")
    d.check("Demineralised water", demin_m3_t, [1, 2], "m3/t H2O2", T124, LVOC, tol=10, kind="mass_balance")
    d.check("Air compression energy", air_GJ_t, 1.4, "GJ/t H2O2", T125, LVOC, tol=30, kind="energy",
            note="Model figure is electricity at the meter, no off gas expander.")
    d.check("Distillation net energy", dist_GJ_t, [0.3, 1.5], "GJ/t H2O2", T125, LVOC, tol=20, kind="energy",
            note="Vapour recompression electricity plus 10% steam trim.")
    d.check("Total net energy", total_GJ_t, [2.9, 5.7], "GJ/t H2O2", T125, LVOC, tol=20, kind="energy",
            note="Honest fail, not tuned. Model counts steam at 2 GJ/t and electricity at 3.6 GJ/MWh (the BREF does "
                 "not state its basis) and leaves out the steam the BREF lists for carbon adsorber and reversion "
                 "agent regeneration and steam ejectors, which the model has no basis to size.")

    d.assumptions = [
        f"Working solution productivity {p['ws_productivity_g_l']:.0f} g H2O2 per litre (assumed, typical "
        "for EAQ solutions); it sets pump and vessel sizes, not the mass balance.",
        f"{p['h2_vent_pct']:.0f}% of the hydrogen is vented with the hydrogenator purge and "
        f"{p['h2_to_water_pct']:.0f}% of the reacted hydrogen ends as water (over hydrogenation, peroxide "
        "decomposition); both assumed to land inside the BREF hydrogen range.",
        "Reaction heat is the overall H2 + O2 -> H2O2 enthalpy, split evenly between the hydrogenation and "
        "oxidation coolers for sizing (assumed split).",
        "Spent air leaves the condenser saturated at 40 C; solvent losses and the carbon adsorber are not in "
        "the mass balance.",
        f"Quinone make up {p['quinone_kg_t']} kg/t (BREF 0.5 to 2.5) leaves as degraded quinone for "
        "incineration at 500 USD/t.",
        "0.2% of the peroxide is lost with the column overhead water.",
        "Product sold as 50% solution; the price is per tonne of 50% solution, so 100% H2O2 is valued at twice it.",
        "Vacuum column reboiler driven by mechanical vapour recompression of its own overhead (10 K condensing "
        "approach, 10% steam trim).",
    ]
    d.hazop = [
        {"node": "Oxidiser", "deviation": "Flammable atmosphere in the off gas",
         "cause": "Low air excess, solvent vapour build up",
         "consequence": "Explosion in the oxidiser head space or off gas line",
         "safeguard": "Off gas O2 analysers with trips, nitrogen inerting on start up, flame arrestors"},
        {"node": "Hydrogenator to oxidiser", "deviation": "Palladium carried over", "cause": "Safety filter failure",
         "consequence": "Catalytic peroxide decomposition, oxygen release and overpressure",
         "safeguard": "Duplicate safety filters, pressure drop alarms, relief sized for decomposition"},
        {"node": "Extraction and storage", "deviation": "Contamination", "cause": "Rust, alkali or metal ions",
         "consequence": "Self accelerating decomposition, tank rupture",
         "safeguard": "Passivated aluminium or stainless equipment, stabilisers, vented tanks, temperature alarms"},
        {"node": "Hydrogenator", "deviation": "Loss of containment", "cause": "Seal or flange leak",
         "consequence": "Hydrogen fire or explosion", "safeguard": "Gas detection, isolation valves, area rating"},
        {"node": "Concentration column", "deviation": "High peroxide concentration", "cause": "Loss of reflux or feed",
         "consequence": "Detonable peroxide vapour in the column",
         "safeguard": "Vapour concentration kept below explosive limit by design, high-temperature trips"},
    ]
    d.greener = {
        "title": "Green hydrogen and pure oxygen",
        "text": "Hydrogen and air compression are most of the footprint. Electrolytic hydrogen removes the "
                "reformer CO2, and oxidising with the electrolyser's own oxygen cuts the air compressor and the "
                "spent air volume (about 10 instead of 3 000 to 4 000 Nm3/t, per the BREF).",
    }
    return d.finish()
