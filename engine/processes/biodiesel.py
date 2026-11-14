"""Biodiesel (fatty acid methyl esters) by base catalysed transesterification of refined vegetable oil.

    Triglyceride + 3 CH3OH -> 3 FAME + glycerol        (oil shown as triolein, FAME as methyl oleate)

Refined, degummed soybean or rapeseed oil is mixed with methanol carrying dissolved sodium hydroxide
catalyst and reacted in two stirred tanks in series at about 60 C, with glycerol drawn off between
them. The ester phase is stripped of methanol under vacuum, water washed and vacuum dried to ASTM
D6751 or EN 14214 grade. The glycerol phase is stripped of methanol and sold as crude glycerol. All
the stripped methanol is rectified and recycled.

Benchmarks: Penn State EGEE 439 (100 lb fat with 16 to 20 lb alcohol gives 100 lb biodiesel and
10 lb glycerin).
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 300.0,  # t/d biodiesel
    "methanol_ratio": 5.5,  # mol methanol per mol oil fed, "almost double" the 3:1 stoichiometric need (Penn State)
    "conversion": 0.995,  # oil to esters over two reactors, needed to meet the bound glycerin limit (assumed)
    "naoh_wt_oil": 0.005,  # catalyst, kg NaOH per kg oil (assumed, typical 0.3 to 1 wt%)
    "reactor_T_C": 60.0,  # Penn State: 1 to 2 h at 60 C
    "residence_h": 1.0,  # per reactor
    "meoh_in_ester_phase": 0.40,  # share of the excess methanol that stays in the ester phase after settling
    "meoh_recovery": 0.995,  # methanol recovered from both phases and recycled
    "wash_water_kg_per_kg": 0.10,  # wash water per kg ester
    "storage_days": 14,
}

SOLID = {"NaOH": "aq"}


def _ph(c):
    return SOLID.get(c, "l")


def _h(flows, T):
    return sum(n * core.h_molar(c, T, _ph(c)) for c, n in flows.items()) / 3600.0  # kW


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    X = p["conversion"]
    # product = esters plus the unconverted glycerides that stay in the ester phase
    oil = P_kg_h / (3 * X * MW("FAME") + (1 - X) * MW("Triolein"))  # kmol/h oil
    fame = 3 * X * oil
    gly = X * oil
    meoh_rxn = 3 * X * oil
    meoh_fed = p["methanol_ratio"] * oil
    meoh_excess = meoh_fed - meoh_rxn
    naoh = p["naoh_wt_oil"] * oil * MW("Triolein") / MW("NaOH")
    meoh_loss = meoh_excess * (1 - p["meoh_recovery"])
    meoh_rec = meoh_excess - meoh_loss
    meoh_fresh = meoh_rxn + meoh_loss

    T0 = 298.15
    TR = p["reactor_T_C"] + 273.15

    f_oil = {"Triolein": oil}
    f_meoh = {"MeOH": meoh_fresh}
    f_cat = {"NaOH": naoh}
    f_rec = {"MeOH": meoh_rec}
    f_mix = {"MeOH": meoh_fed, "NaOH": naoh}
    f_rx = {"Triolein": oil * (1 - X), "MeOH": meoh_excess, "FAME": fame, "Glycerol": gly, "NaOH": naoh}
    a = p["meoh_in_ester_phase"]
    f_ester = {"FAME": fame, "Triolein": oil * (1 - X), "MeOH": meoh_excess * a}
    f_glyph = {"Glycerol": gly, "NaOH": naoh, "MeOH": meoh_excess * (1 - a)}
    # methanol stripping: the losses leave with the ester (to the wash water) and with the crude glycerol
    loss_e = meoh_loss * a
    loss_g = meoh_loss * (1 - a)
    f_ester_strip = {"FAME": fame, "Triolein": oil * (1 - X), "MeOH": loss_e}
    f_meoh_e = {"MeOH": meoh_excess * a - loss_e}
    f_gly_strip = {"Glycerol": gly, "NaOH": naoh, "MeOH": loss_g}
    f_meoh_g = {"MeOH": meoh_excess * (1 - a) - loss_g}
    wash_kg = p["wash_water_kg_per_kg"] * _kg(f_ester_strip)
    dissolved_h2o = 0.0015 * (fame * MW("FAME")) / MW("H2O")  # about 1500 ppm water in washed ester
    f_wash_in = {"H2O": wash_kg / MW("H2O")}
    f_wash_out = {"H2O": f_wash_in["H2O"] - dissolved_h2o, "MeOH": loss_e}
    f_wet = {"FAME": fame, "Triolein": oil * (1 - X), "H2O": dissolved_h2o}
    f_dry_vap = {"H2O": dissolved_h2o}
    f_prod = {"FAME": fame, "Triolein": oil * (1 - X)}

    d = Design("biodiesel", "Biodiesel plant (base catalysed transesterification)", "Biodiesel", p["capacity_tpd"], region)
    d.route = ("Refined vegetable oil reacts with methanol over a sodium hydroxide catalyst at about 60 C. The heavy "
               "glycerol layer settles out, the methanol is stripped and recycled, and the esters are washed and dried "
               "to fuel grade biodiesel. Crude glycerol is sold.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of biodiesel from {oil * MW('Triolein') * 24 / 1000:,.0f} t/d of refined "
                 f"vegetable oil and {meoh_fresh * MW('MeOH') * 24 / 1000:,.0f} t/d of methanol, with "
                 f"{_kg(f_gly_strip) * 24 / 1000:,.0f} t/d of crude glycerol.")
    dH = (3 * core.h_molar("FAME", T0, "l") + core.h_molar("Glycerol", T0, "l") - core.h_molar("Triolein", T0, "l")
          - 3 * core.h_molar("MeOH", T0, "l")) / 1000
    d.reactions = [{"eq": "C57H104O6 + 3 CH3OH -> 3 C19H36O2 + C3H8O3",
                    "where": "Two stirred reactors in series, NaOH catalyst", "dH_kJ": dH}]
    d.conditions = [
        ("Reactors", f"{p['reactor_T_C']:.0f} C, about 2 bar, {p['residence_h']:.0f} h each, two in series"),
        ("Methanol to oil", f"{p['methanol_ratio']:.1f} : 1 molar ({meoh_fed * MW('MeOH') / (oil * MW('Triolein')) * 100:.1f} lb per 100 lb oil)"),
        ("Catalyst", f"NaOH, {p['naoh_wt_oil'] * 100:.1f} wt% of oil"),
        ("Conversion", f"{X * 100:.1f}% of the oil to methyl esters"),
        ("Methanol strippers", "about 0.2 bar, 90 to 120 C"),
        ("Product", "FAME to ASTM D6751 or EN 14214, water below 500 ppm"),
    ]

    s_oil = d.stream("Refined vegetable oil", f_oil, T0, 3.0, phase="l")
    s_meoh = d.stream("Fresh methanol", f_meoh, T0, 3.0, phase="l")
    s_cat = d.stream("Sodium hydroxide catalyst", f_cat, T0, 1.0, phase="s", phases={"NaOH": "s"})
    s_rec = d.stream("Recycled methanol", f_rec, 313.15, 3.0, phase="l")
    s_mix = d.stream("Methoxide solution", f_mix, 313.15, 3.0, phase="l", phases=SOLID)
    s_rx = d.stream("Reactor product", f_rx, TR, 2.0, phase="l", phases=SOLID)
    s_est = d.stream("Ester phase", f_ester, TR, 1.5, phase="l")
    s_glp = d.stream("Glycerol phase", f_glyph, TR, 1.5, phase="l", phases=SOLID)
    s_es = d.stream("Stripped esters", f_ester_strip, 383.15, 0.2, phase="l")
    s_me = d.stream("Methanol from ester stripper", f_meoh_e, 343.15, 0.2, phase="g")
    s_gs = d.stream("Crude glycerol", f_gly_strip, 323.15, 1.5, phase="l", phases=SOLID)
    s_mg = d.stream("Methanol from glycerol stripper", f_meoh_g, 343.15, 0.2, phase="g")
    s_wi = d.stream("Wash water", f_wash_in, 333.15, 3.0, phase="l")
    s_wo = d.stream("Spent wash water", f_wash_out, 333.15, 1.5, phase="l")
    s_wet = d.stream("Washed esters", f_wet, 333.15, 1.5, phase="l")
    s_dv = d.stream("Dryer vapour", f_dry_vap, 373.15, 0.1, phase="g")
    s_prod = d.stream("Biodiesel", f_prod, 313.15, 2.0, phase="l")

    d.feed(s_oil, {"Triolein": "Triolein"})
    d.feed(s_meoh, {"MeOH": "MeOH"})
    d.feed(s_cat)
    d.feed(s_wi)
    d.out(s_prod, "product", {"FAME": "FAME", "Triolein": "FAME"})
    d.out(s_gs, "byproduct", {"Glycerol": "Glycerol"})
    d.out(s_wo, "waste", treat_usd_t=2.0)
    d.out(s_dv, "waste", treat_usd_t=2.0)

    d.unit("M-101", "Methoxide mix tank", "mixer", [s_meoh, s_cat, s_rec], [s_mix], (0, 0))
    d.unit("R-101", "Transesterification reactors (2 in series)", "reactor", [s_oil, s_mix], [s_rx], (1, 0),
           desc="Stirred tanks with glycerol draw off between stages")
    d.unit("S-101", "Glycerol settler", "separator", [s_rx], [s_est, s_glp], (2, 0))
    d.unit("F-101", "Ester methanol stripper", "flash", [s_est], [s_es, s_me], (3, 0))
    d.unit("T-101", "Wash column", "column", [s_es, s_wi], [s_wet, s_wo], (4, 0))
    d.unit("F-102", "Vacuum dryer", "flash", [s_wet], [s_prod, s_dv], (5, 0))
    d.unit("F-103", "Glycerol methanol stripper", "flash", [s_glp], [s_gs, s_mg], (3, 1))
    d.unit("T-102", "Methanol rectifier", "column", [s_me, s_mg], [s_rec], (2, 1))

    # ---------------------------------------------------------------- energy
    lp = 2100.0
    Q_oil = _h(f_oil, TR) - _h(f_oil, T0)
    Q_rx = max(0.0, _h(f_rx, TR) - _h(f_oil, TR) - _h(f_mix, 313.15))  # reaction plus warming the methoxide
    T_es = 383.15
    Q_strip_e = (_h(f_ester_strip, T_es) - _h(f_ester_strip, TR) + _h(f_meoh_e, TR) - _h(f_meoh_e, TR)
                 + f_meoh_e["MeOH"] * th.hvap("MeOH") / 3600)
    Q_strip_g = (_h(f_gly_strip, 393.15) - _h(f_gly_strip, TR) + f_meoh_g["MeOH"] * th.hvap("MeOH") / 3600)
    meoh_vap = meoh_rec
    Q_rect = meoh_vap * th.hvap("MeOH") / 3600 * 1.5  # reflux ratio about 0.5 on dry methanol
    Q_dry = dissolved_h2o * th.hvap("H2O") / 3600 + _h(f_wet, 373.15) - _h(f_wet, 333.15)
    # heat recovery: hot stripped ester preheats the oil feed
    Q_rec = min(Q_oil, (_h(f_ester_strip, T_es) - _h(f_ester_strip, 343.15)) * 0.8)
    d.steam((Q_oil - Q_rec) / lp * 3600, "Oil preheat (after interchange with stripped ester)")
    d.steam(Q_rx / lp * 3600, "Reactor heating")
    d.steam(Q_strip_e / lp * 3600, "Ester methanol stripper")
    d.steam(Q_strip_g / lp * 3600, "Glycerol methanol stripper")
    d.steam(Q_rect / lp * 3600, "Methanol rectifier reboiler")
    d.steam(Q_dry / lp * 3600, "Biodiesel vacuum dryer")
    steam_kg_h = (Q_oil - Q_rec + Q_rx + Q_strip_e + Q_strip_g + Q_rect + Q_dry) / lp * 3600
    Q_cond = (meoh_vap * th.hvap("MeOH") / 3600) * 1.5 + dissolved_h2o * th.hvap("H2O") / 3600
    Q_prod_cool = _h(f_prod, 373.15) - _h(f_prod, 313.15)
    Q_wash_cool = max(0.0, _h(f_ester_strip, 343.15) - _h(f_ester_strip, 333.15))
    d.cooling(Q_cond, "Methanol and dryer condensers")
    d.cooling(Q_prod_cool, "Biodiesel cooler")
    d.cooling(Q_wash_cool, "Ester cooler before washing")
    oil_kg = oil * MW("Triolein")
    V_rx = (oil_kg / 900 + meoh_fed * MW("MeOH") / 790) * p["residence_h"] / 0.8
    d.power(0.5 * V_rx * 2, "Reactor agitators (about 0.5 kW/m3)")
    d.power(0.02 * _kg(f_ester) / 1000 * 50, "Vacuum pumps on strippers and dryer")
    cw_kW = Q_cond + Q_prod_cool + Q_wash_cool
    d.power(cw_kW * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw_kW, "Cooling water pumps and tower fans")

    # ---------------------------------------------------------------- equipment
    d.hx("E-101", "Oil and ester interchanger", Q_rec, T_es, 343.15, T0, T0 + Q_rec / max(Q_oil, 1e-9) * (TR - T0),
         "liquid-liquid")
    d.hx("E-102", "Oil heater", max(1.0, Q_oil - Q_rec), 423.15, 423.15, TR - 10, TR, "liquid-steam")
    d.vessel("R-101", "First reactor", V_rx * 0.6, P_barg=1.0, material="SS", service="stirred, 60 C")
    d.vessel("R-102", "Second reactor", V_rx * 0.5, P_barg=1.0, material="SS", service="stirred, 60 C")
    d.vessel("S-101", "Glycerol settler", (_kg(f_rx) / 880) * 1.0 / 0.8, P_barg=0.5, material="SS",
             orientation="horizontal", service="1 h settling")
    d.vessel("F-101", "Ester methanol flash", _kg(f_ester) / 870 * 0.25, material="SS", service="vacuum")
    d.hx("E-103", "Ester stripper heater", Q_strip_e, 433.15, 433.15, TR, T_es, "liquid-steam", material="SS")
    d.vessel("F-103", "Glycerol methanol flash", _kg(f_glyph) / 1100 * 0.25, material="SS", service="vacuum")
    d.hx("E-104", "Glycerol stripper heater", Q_strip_g, 433.15, 433.15, TR, 393.15, "liquid-steam", material="SS")
    d.column("T-101", "Wash column", _kg(f_ester_strip) / 870, 333.15, 1.5, 6, MW("FAME"), material="SS", packed=True)
    d.column("T-102", "Methanol rectifier", meoh_vap * 1.5, 337.15, 1.2, 20, MW("MeOH"))
    d.hx("E-105", "Rectifier reboiler", Q_rect, 423.15, 423.15, 370.15, 373.15, "reboiler")
    d.hx("E-106", "Methanol condenser", Q_cond, 337.15, 330.15, 303.15, 313.15, "condenser")
    d.vessel("F-102", "Biodiesel vacuum dryer", _kg(f_wet) / 870 * 0.25, material="SS", service="0.1 bar")
    d.hx("E-107", "Biodiesel cooler", Q_prod_cool, 373.15, 313.15, 303.15, 313.15, "liquid-water")
    days = p["storage_days"]
    d.tank("TK-101", "Vegetable oil tanks", oil_kg, 920, days=days)
    d.tank("TK-102", "Methanol tank", meoh_fresh * MW("MeOH"), 790, days=days)
    d.tank("TK-103", "Biodiesel tanks", P_kg_h, 880, days=days)
    d.tank("TK-104", "Crude glycerol tank", _kg(f_gly_strip), 1250, days=days)
    d.pump("P-101", "Oil feed pump", oil_kg, 920, 4)
    d.pump("P-102", "Methoxide pump", _kg(f_mix), 800, 4, material="SS")
    d.pump("P-103", "Ester pump", _kg(f_ester), 870, 3, material="SS")
    d.pump("P-104", "Biodiesel pump", P_kg_h, 880, 4)

    # ---------------------------------------------------------------- KPIs and checks
    per100 = 100.0 / oil_kg
    fame_lb = P_kg_h * per100
    gly_lb = gly * MW("Glycerol") * per100
    meoh_lb = meoh_fed * MW("MeOH") * per100
    d.kpis = [
        {"label": "Biodiesel per 100 kg oil", "value": fame_lb, "unit": "kg"},
        {"label": "Glycerol per 100 kg oil", "value": gly_lb, "unit": "kg (pure basis)"},
        {"label": "Methanol fed per 100 kg oil", "value": meoh_lb, "unit": "kg"},
        {"label": "Fresh methanol", "value": meoh_fresh * MW("MeOH") / P_kg_h, "unit": "t/t biodiesel"},
        {"label": "Oil use", "value": oil_kg / P_kg_h, "unit": "t/t biodiesel"},
        {"label": "Steam", "value": steam_kg_h / P_kg_h, "unit": "t/t biodiesel"},
    ]
    PSU = "https://courses.ems.psu.edu/egee439/node/684"
    PSUS = "Penn State EGEE 439, Alternative Fuels from Biomass Sources, Lesson 10: biodiesel production"
    d.check("Biodiesel per 100 lb oil", fame_lb, 100, "lb", PSUS, PSU, tol=3,
            note="Model esters plus the 0.5% of unconverted glycerides that stay in the product.")
    d.check("Glycerin per 100 lb oil", gly_lb, 10, "lb", PSUS, PSU, tol=10,
            note="Model figure is pure glycerol; the crude glycerin sold also carries catalyst and some methanol.")
    d.check("Alcohol fed per 100 lb oil", meoh_lb, [16, 20], "lb", PSUS, PSU, tol=0,
            note=f"{p['methanol_ratio']:.1f} mol methanol per mol oil fed, most of the excess is recycled.")
    d.assumptions = [
        "Oil is refined and degummed with free fatty acids below 0.5%, so no acid esterification step is needed. "
        "The oil is shown as triolein and the esters as methyl oleate.",
        "Triolein heat of formation from the NIST WebBook (Freedman, Bagby et al., 1989, -2193.7 kJ/mol).",
        f"{X * 100:.1f}% of the oil is converted over two reactors; the rest stays in the product as bound glycerides.",
        f"Sodium hydroxide catalyst at {p['naoh_wt_oil'] * 100:.1f} wt% of oil leaves in the crude glycerol; acid "
        "neutralisation, soap splitting and glycerol refining are not modelled. Catalyst cost is not itemised.",
        f"{(1 - a) * 100:.0f}% of the excess methanol settles with the glycerol; {p['meoh_recovery'] * 100:.1f}% of all "
        "excess methanol is recovered and recycled.",
        f"Wash water {p['wash_water_kg_per_kg'] * 100:.0f}% of ester flow, sent to treatment with the dryer condensate.",
        "Steam bought from the site utility at the regional steam price.",
    ]
    d.hazop = [
        {"node": "Methanol storage and methoxide tank", "deviation": "Loss of containment",
         "cause": "Hose or seal failure during unloading", "consequence": "Methanol pool fire with an almost invisible flame; toxic exposure",
         "safeguard": "Bunding, nitrogen blanket, gas detection, foam, alcohol resistant fire fighting"},
        {"node": "Methoxide make up", "deviation": "Wrong order of addition", "cause": "Water or hot methanol on solid NaOH",
         "consequence": "Heat release and caustic splashing", "safeguard": "Closed dosing system, procedure, PPE"},
        {"node": "Reactors", "deviation": "High temperature", "cause": "Steam control valve fails open",
         "consequence": "Methanol boils, overpressure", "safeguard": "Temperature trip on steam, relief valve to condenser"},
        {"node": "Methanol strippers", "deviation": "Air ingress under vacuum", "cause": "Leaking flange or seal",
         "consequence": "Flammable mixture in the vacuum system", "safeguard": "Oxygen monitoring, nitrogen purge, flame arrester"},
    ]
    d.greener = {
        "title": "Waste oils and glycerol to value",
        "text": "Used cooking oil and animal fats cut the carbon footprint by more than half but need an acid "
                "esterification step first; refining the crude glycerol to pharma grade, or digesting it to biogas, adds value.",
    }
    return d.finish()
