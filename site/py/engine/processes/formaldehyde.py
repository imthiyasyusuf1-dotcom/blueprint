"""Formaldehyde (as formalin) from methanol by the silver catalyst process, high conversion (BASF type).

    CH3OH -> HCHO + H2                 dehydrogenation, endothermic
    CH3OH + 1/2 O2 -> HCHO + H2O       oxidative dehydrogenation, exothermic
    CH3OH + 3/2 O2 -> CO2 + 2 H2O      combustion, side reaction
    CH3OH -> CO + 2 H2                 decomposition, side reaction

A methanol and water vapour mix is fed with air over a thin bed of silver crystals near 650 C and just
above atmospheric pressure. The reactor runs adiabatically: the air rate is what holds the bed at
temperature, so the split between the two formaldehyde reactions comes from the energy balance. The gas
is quenched in a waste heat boiler under the bed, then absorbed in water to give formalin. The tail gas,
rich in hydrogen, is burnt to raise more steam.

Benchmarks: EU BREF for Large Volume Organic Chemicals (JRC109279, 2017), Table 6.10.
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 300.0,  # t/d of 100% formaldehyde
    "T_C": 650.0,  # silver bed outlet
    "P_bar": 1.5,
    "feed_T_C": 100.0,  # methanol, water and air mix at the bed inlet
    "water_methanol_kg": 0.67,  # kg water per kg methanol in the vaporised feed (about 60 wt% methanol, assumed)
    "conversion": 0.98,  # methanol converted in the single pass (high conversion process, assumed)
    "selectivity": 0.91,  # mol HCHO per mol methanol converted (assumed typical)
    "loss_to_co2": 0.6,  # share of the converted methanol not going to HCHO that burns to CO2; the rest to CO
    "formalin_wt": 0.37,  # HCHO in the product; absorber water added if the reactor water is not enough
    "absorber_T_C": 30.0,
    "ghsv_h": 1.0e5,  # gas hourly space velocity over the thin silver bed (assumed)
    "wh_out_C": 150.0,  # gas leaving the waste heat boiler
    "boiler_eff": 0.85,  # tail gas burnt for steam
    "storage_days": 10,
}

AIR = {"N2": 0.78084, "O2": 0.20946, "Ar": 0.00934 + 0.00036}
LATENT = 2100.0
H_LP_SAT = 2748.0  # kJ/kg, saturated steam at about 4.5 bar from the waste heat boiler


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def _hg(flows, T):
    return sum(n * core.h_molar(c, T, "g") for c, n in flows.items()) / 3600.0  # kW


def _hl(flows, T):
    return sum(n * core.h_molar(c, T, "l") for c, n in flows.items()) / 3600.0


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    T0 = 298.15
    TR = p["T_C"] + 273.15
    TF = p["feed_T_C"] + 273.15
    P_ = p["P_bar"]
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    Hc = P_kg_h / MW("HCHO")
    Mf = Hc / (p["selectivity"] * p["conversion"])
    reacted = Mf * p["conversion"]
    lost = reacted - Hc
    c2 = lost * p["loss_to_co2"]
    c1 = lost - c2
    Wf = Mf * MW("MeOH") * p["water_methanol_kg"] / MW("H2O")

    def gas(x):
        """Outlet gas and air for a share x of the HCHO made by oxidation."""
        o2 = 0.5 * x * Hc + 1.5 * c2
        air = o2 / AIR["O2"]
        f_air = {c: air * v for c, v in AIR.items()}
        out = {"HCHO": Hc, "MeOH": Mf - reacted, "H2": (1 - x) * Hc + 2 * c1, "H2O": Wf + x * Hc + 2 * c2,
               "CO2": c2, "CO": c1, "N2": f_air["N2"], "Ar": f_air["Ar"]}
        return f_air, out

    def resid(x):
        f_air, out = gas(x)
        return _hg(out, TR) - _hg(f_air, TF) - _hg({"MeOH": Mf, "H2O": Wf}, TF)

    r0, r1 = resid(0.0), resid(1.0)
    x = r0 / (r0 - r1)
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"no adiabatic solution, oxidation share {x:.2f}")
    f_air, f_rx = gas(x)

    # absorber: tail gas leaves saturated with water at the absorber top; methanol stays in the formalin
    TA = p["absorber_T_C"] + 273.15
    dry = f_rx["H2"] + f_rx["CO2"] + f_rx["CO"] + f_rx["N2"] + f_rx["Ar"]
    yw = core.psat("H2O", TA) / P_
    w_tail = dry * yw / (1 - yw)
    f_tail = {"H2": f_rx["H2"], "CO2": f_rx["CO2"], "CO": f_rx["CO"], "N2": f_rx["N2"], "Ar": f_rx["Ar"],
              "H2O": w_tail}
    w_liq = f_rx["H2O"] - w_tail
    w_need = P_kg_h * (1 - p["formalin_wt"]) / p["formalin_wt"] - (Mf - reacted) * MW("MeOH")
    aw = max(w_need / MW("H2O") - w_liq, 0.0)
    f_form = {"HCHO": Hc, "MeOH": Mf - reacted, "H2O": w_liq + aw}
    form_wt = P_kg_h / _kg(f_form)

    d = Design("formaldehyde", "Formaldehyde plant (silver catalyst, high conversion)", "HCHO", p["capacity_tpd"],
               region)
    d.route = ("Methanol and water are vaporised, mixed with air and passed over a thin bed of silver crystals at "
               "about 650 C. The hot gas raises steam straight away, then water absorbs the formaldehyde to make "
               "formalin. The hydrogen rich tail gas is burnt for more steam.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of formaldehyde (100% basis) as {form_wt * 100:.0f} wt% formalin, "
                 f"{_kg(f_form) * 24 / 1000:,.0f} t/d, from {Mf * MW('MeOH') * 24 / 1000:,.0f} t/d of methanol.")

    def dhg(prod, reac):
        return (sum(n * core.h_molar(c, T0, "g") for c, n in prod.items())
                - sum(n * core.h_molar(c, T0, "g") for c, n in reac.items())) / 1000

    d.reactions = [
        {"eq": "CH3OH -> HCHO + H2", "where": f"Silver bed, {(1 - x) * 100:.0f}% of the HCHO",
         "dH_kJ": dhg({"HCHO": 1, "H2": 1}, {"MeOH": 1})},
        {"eq": "CH3OH + 1/2 O2 -> HCHO + H2O", "where": f"Silver bed, {x * 100:.0f}% of the HCHO (from the heat balance)",
         "dH_kJ": dhg({"HCHO": 1, "H2O": 1}, {"MeOH": 1, "O2": 0.5})},
        {"eq": "CH3OH + 3/2 O2 -> CO2 + 2 H2O", "where": "Silver bed, side reaction",
         "dH_kJ": dhg({"CO2": 1, "H2O": 2}, {"MeOH": 1, "O2": 1.5})},
        {"eq": "CH3OH -> CO + 2 H2", "where": "Silver bed, side reaction", "dH_kJ": dhg({"CO": 1, "H2": 2}, {"MeOH": 1})},
    ]
    d.conditions = [
        ("Silver bed", f"{p['T_C']:.0f} C outlet, {P_:.1f} bar, adiabatic, {p['conversion'] * 100:.0f}% methanol "
                       f"conversion, {p['selectivity'] * 100:.0f}% selectivity"),
        ("Feed", f"{p['water_methanol_kg']:.2f} kg water per kg methanol, air {_kg(f_air) / (Mf * MW('MeOH')):.2f} "
                 "kg/kg methanol, kept rich of the upper explosive limit"),
        ("Waste heat boiler", f"gas quenched to {p['wh_out_C']:.0f} C in under a second"),
        ("Absorber", f"{p['absorber_T_C']:.0f} C, product {form_wt * 100:.0f} wt% HCHO"),
    ]

    # ---------------------------------------------------------------- streams
    s_meoh = d.stream("Methanol", {"MeOH": Mf}, T0, 3.0, phase="l")
    s_pw = d.stream("Process water to vaporiser", {"H2O": Wf}, T0, 3.0, phase="l")
    s_vap = d.stream("Methanol and water vapour", {"MeOH": Mf, "H2O": Wf}, TF, P_ + 0.3, phase="g")
    s_air = d.stream("Air", f_air, T0, 1.013, phase="g")
    s_airc = d.stream("Air to reactor", f_air, TF, P_ + 0.3, phase="g")
    s_rx = d.stream("Reactor gas", f_rx, TR, P_, phase="g")
    s_rxc = d.stream("Cooled reactor gas", f_rx, p["wh_out_C"] + 273.15, P_ - 0.1, phase="g")
    s_aw = d.stream("Absorber water", {"H2O": aw}, T0, 2.0, phase="l") if aw > 0 else None
    s_form = d.stream("Formalin", f_form, TA, 1.5, phase="l")
    s_tail = d.stream("Tail gas to boiler", f_tail, TA, P_ - 0.3, phase="g")

    d.feed(s_meoh, {"MeOH": "MeOH"})
    d.feed(s_pw)
    d.feed(s_air)
    if s_aw:
        d.feed(s_aw)
    d.out(s_form, "product", {"HCHO": "HCHO"})
    d.out(s_tail, "fuel")

    d.unit("E-100", "Methanol vaporiser", "hx", [s_meoh, s_pw], [s_vap], (0, 0))
    d.unit("C-101", "Air blower", "compressor", [s_air], [s_airc], (0, 1))
    d.unit("R-101", "Silver catalyst reactor", "reactor", [s_vap, s_airc], [s_rx], (1, 0),
           desc="Thin silver bed over a waste heat boiler")
    d.unit("E-101", "Waste heat boiler", "hx", [s_rx], [s_rxc], (2, 0))
    d.unit("T-101", "Absorber", "column", [s_rxc] + ([s_aw] if s_aw else []), [s_form, s_tail], (3, 0))

    # ---------------------------------------------------------------- energy
    Q_vap = _hg({"MeOH": Mf, "H2O": Wf}, TF) - _hl({"MeOH": Mf, "H2O": Wf}, T0)
    Q_air = _hg(f_air, TF) - _hg(f_air, T0)
    f_aw = {"H2O": aw}
    Q_abs = (_hg(f_rx, p["wh_out_C"] + 273.15) + _hl(f_aw, T0)) - (_hl(f_form, TA) + _hg(f_tail, TA))
    # the air is bubbled through the methanol and water in the evaporator at about 70 C, which is heated by the
    # first absorber stage circulation; steam only superheats the mix to the bed inlet temperature
    T_ev = 343.15
    Q_ev = _hg({"MeOH": Mf, "H2O": Wf}, T_ev) - _hl({"MeOH": Mf, "H2O": Wf}, T0) \
        + _hg(f_air, T_ev) - _hg(f_air, T0)
    Q_ev = min(Q_ev, 0.9 * Q_abs)
    Q_sh = Q_vap + Q_air - Q_ev
    d.steam(Q_sh / LATENT * 3600, "Feed superheater (methanol, water and air)")
    Q_whb = _hg(f_rx, TR) - _hg(f_rx, p["wh_out_C"] + 273.15)
    st_whb = Q_whb / (H_LP_SAT - th.H_BFW_105C) * 3600
    d.steam(-st_whb, "Waste heat boiler under the silver bed")
    d.cooling(Q_abs - Q_ev, "Absorber coolers (heat left after the evaporator)")
    tail_GJ = sum(n * th.lhv_molar(c) for c, n in f_tail.items() if c in ("H2", "CO")) * 1000 / 1e9
    st_tail = tail_GJ * 1e6 * p["boiler_eff"] / (th.H_STEAM_40BAR_450C - th.H_BFW_105C)
    d.steam(-st_tail, f"Tail gas burnt in a boiler ({p['boiler_eff'] * 100:.0f}% efficient)")
    d.direct_co2_kg_h += (f_tail["CO2"] + f_tail["CO"]) * MW("CO2")

    # ---------------------------------------------------------------- equipment
    d.reactor_bed("R-101", "Silver catalyst reactor", sum(f_rx.values()), p["ghsv_h"], P_ - 1.013, material="SS")
    d.hx("E-101", "Waste heat boiler", Q_whb, TR, p["wh_out_C"] + 273.15, 421.15, 421.15, "boiler", P_barg=P_ - 1,
         material="SS")
    d.hx("E-100", "Evaporator (heated by first absorber stage)", Q_ev, 358.15, 348.15, T0, T_ev, "liquid-water",
         material="SS")
    d.hx("E-103", "Feed superheater", Q_sh, 421.15, 421.15, T_ev, TF, "gas-steam", P_barg=P_)
    d.column("T-101", "Absorber", sum(f_rx.values()), 323.15, P_ - 0.1, 12, _kg(f_rx) / sum(f_rx.values()),
             material="SS", packed=True)
    d.hx("E-102", "Absorber circulation coolers", Q_abs - Q_ev, 343.15, TA + 5, 303.15, 313.15, "liquid-water", material="SS")
    d.compressor("C-101", "Air blower", s_air, P_ + 0.3, k=1.4, eta=0.75)
    d.heater("B-101", "Tail gas boiler", tail_GJ * 1e6 / 3600 * p["boiler_eff"], kind="boiler")
    d.pump("P-101", "Methanol feed pump", Mf * MW("MeOH"), 790, 3.0)
    d.pump("P-102", "Absorber circulation pumps", _kg(f_form) * 10, 1090, 3.0, material="SS")
    d.tank("TK-101", "Methanol tanks", Mf * MW("MeOH"), 790, days=p["storage_days"])
    d.tank("TK-102", "Formalin tanks (heated)", _kg(f_form), 1090, days=p["storage_days"], material="SS")
    cw = d.cw_kW
    d.power(cw * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw, "Cooling water pumps and tower fans")
    d.power(0.05 * d.power_kW, "Compressed air, lighting, HVAC and flare (5% of process load)")

    # ---------------------------------------------------------------- KPIs and checks
    meoh_kg = Mf * MW("MeOH") / (P_kg_h / 1000)
    yld = Hc / Mf * 100
    steam_exp = (d.steam_export_kg_h - d.steam_import_kg_h) / P_kg_h
    kwh_t = d.power_kW / (P_kg_h / 1000)
    d.kpis = [
        {"label": "Methanol use", "value": meoh_kg, "unit": "kg/t HCHO (100%)"},
        {"label": "Share of HCHO by oxidation", "value": x * 100, "unit": "%"},
        {"label": "Formalin strength", "value": form_wt * 100, "unit": "wt% HCHO"},
        {"label": "Net steam export", "value": steam_exp, "unit": "t/t HCHO"},
        {"label": "Electricity", "value": kwh_t, "unit": "kWh/t HCHO"},
    ]
    BREF = "https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/JRC109279_LVOC_Bref.pdf"
    BS = "EU BREF LVOC (JRC109279, 2017), Table 6.10"
    d.check("Methanol per t formaldehyde, silver process", meoh_kg, [1185, 1226], "kg/t 100% HCHO", BS, BREF, tol=3,
            note="Set by the assumed conversion and selectivity; unconverted methanol stays in the formalin.")
    d.check("Conversion of methanol to formaldehyde", yld, [87, 90], "%", BS, BREF, tol=3,
            note="BREF gives 87 to 90% for the silver process (91 to 94% for the oxide process). Model value is the "
                 "molar yield, conversion times selectivity.")
    d.check("Net steam export, silver process high conversion", steam_exp, 2.6, "t/t 100% HCHO", BS, BREF, tol=25,
            note="Waste heat boiler plus tail gas boiler, less the feed superheater. The tail gas gives about 45% of the "
                 "export, close to the share BREF gives.")
    d.check("Electricity, silver process", kwh_t, [50, 100], "kWh/t 100% HCHO", BS, BREF, tol=25,
            note="Air blower, pumps and cooling water.")

    d.assumptions = [
        f"Single pass conversion {p['conversion'] * 100:.0f}% and selectivity {p['selectivity'] * 100:.0f}% are typical "
        "design values for the high conversion silver process, not fitted.",
        "Reactor is adiabatic; the split between dehydrogenation and oxidation is solved from the heat balance at the "
        "bed outlet temperature. Hydrogen burnt in the bed is counted inside the oxidation route.",
        "Formic acid and methyl formate (tens to hundreds of ppm) are not modelled; no ion exchange step is shown.",
        "Methanol and water are evaporated into the air at about 70 C using heat from the first absorber stage "
        "circulation (as in the BASF type process); steam only superheats the feed.",
        "Absorber tail gas is saturated with water; its methanol and HCHO slip is taken as zero.",
        "Product priced on contained HCHO (formalin quotes converted at 37 wt%).",
    ]
    d.hazop = [
        {"node": "Methanol and air mixing", "deviation": "Air ratio too high", "cause": "Methanol flow drop or air "
         "control fault", "consequence": "Mix inside the explosive range, flashback to the vaporiser",
         "safeguard": "Ratio control with trips, rich operation above the upper limit, flame arresters, bursting discs"},
        {"node": "Silver bed", "deviation": "High temperature", "cause": "Air surge or catalyst poisoning",
         "consequence": "Catalyst sintering, more CO2, fire risk", "safeguard": "Bed thermocouples with air trip"},
        {"node": "Absorber and formalin storage", "deviation": "Low temperature", "cause": "Heat tracing failure",
         "consequence": "Paraformaldehyde solids block lines and tanks",
         "safeguard": "Heated tanks, temperature alarms, methanol stabiliser"},
        {"node": "Formalin handling", "deviation": "Release", "cause": "Leak at pumps or loading",
         "consequence": "Toxic, sensitising and carcinogenic vapour", "safeguard": "Closed loading with vapour return, "
         "gas detection, PPE"},
    ]
    d.greener = {
        "title": "Green methanol feed",
        "text": "The process itself exports steam and burns its own tail gas, so the footprint is mostly the methanol. "
                "Methanol from biomass or from CO2 and green hydrogen cuts it to a fraction.",
    }
    return d.finish()
