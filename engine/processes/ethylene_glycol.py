"""Ethylene glycol (MEG) from ethylene oxide by uncatalysed thermal hydration, with DEG and TEG co-products.

    C2H4O + H2O -> HOCH2CH2OH (MEG)                    main reaction
    C2H4O + MEG -> DEG                                 consecutive reaction
    C2H4O + DEG -> TEG                                 consecutive reaction (heavier glycols lumped in TEG)

Ethylene oxide is mixed with a large excess of water and reacted to completion in a pipe reactor near
190 C and 20 bar, with no catalyst. The excess water keeps the consecutive reactions down; the glycol split
follows from integrating the competing rates over the EO consumed. The water is boiled off in a
three effect evaporator and a vacuum drying column and recycled, then MEG, DEG and TEG are separated by
vacuum distillation.

Benchmarks: US DOE Energy and Environmental Profile of the US Chemical Industry (2000), EU BREF for Large
Volume Organic Chemicals (JRC109279, 2017), and Shehata et al., Scientific Reports 14 (2024).
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 1500.0,  # t/d MEG
    "water_eo_ratio": 10.0,  # mol water per mol EO at the reactor inlet (Shehata et al. 2024 design; BREF range 10 to 25)
    "k_ratio": 2.0,  # rate constant of EO with a glycol over EO with water, per mol (assumed, typical value about 2)
    "T_in_C": 130.0,  # reactor inlet (assumed), chosen so the adiabatic outlet stays inside 150 to 250 C
    "P_bar": 40.0,  # keeps the effluent liquid at the outlet temperature (BREF 10 to 40 barg)
    "residence_min": 30.0,  # pipe reactor residence time (assumed)
    "effects": 3,  # evaporator effects
    "economy_per_effect": 0.9,  # kg water evaporated per kg steam, per effect (assumed)
    "conc_glycol_wt": 0.85,  # glycols in the evaporator concentrate sent to the drying column (assumed)
    "reflux_dry": 0.5,  # reflux ratios (assumed, typical)
    "reflux_meg": 1.0,
    "reflux_deg": 1.0,
    "storage_days": 14,
}

LATENT = 2100.0


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def _split(ratio, K, n=4000):
    """Moles of water used, MEG, DEG, TEG per mol EO for full EO conversion.

    Consecutive competing reactions in plug flow; each EO molecule picks a partner in proportion to the rate:
    water at k, MEG and DEG at K k. Integrated with RK4 in the EO consumed.
    """
    def f(y):
        W, M, D = y[0], y[1], y[2]
        S = W + K * M + K * D
        return [-W / S, (W - K * M) / S, (K * M - K * D) / S, K * D / S]

    y = [ratio, 0.0, 0.0, 0.0]
    h = 1.0 / n
    for _ in range(n):
        k1 = f(y)
        k2 = f([a + h / 2 * b for a, b in zip(y, k1)])
        k3 = f([a + h / 2 * b for a, b in zip(y, k2)])
        k4 = f([a + h * b for a, b in zip(y, k3)])
        y = [a + h / 6 * (b + 2 * c + 2 * e + g) for a, b, c, e, g in zip(y, k1, k2, k3, k4)]
    return ratio - y[0], y[1], y[2], y[3]


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    T0 = 298.15
    P_ = p["P_bar"]
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    w1, m1, d1, t1 = _split(p["water_eo_ratio"], p["k_ratio"])
    M = P_kg_h / MW("MEG")
    E = M / m1
    Dg, Tg = d1 * E, t1 * E
    Wc = w1 * E  # water consumed = MEG + DEG + TEG
    W0 = p["water_eo_ratio"] * E
    Wleft = W0 - Wc
    Wd = _kg({"MEG": M, "DEG": d1 * E, "TEG": t1 * E}) * (1 / p["conc_glycol_wt"] - 1) / MW("H2O")
    We = Wleft - Wd

    d = Design("ethylene_glycol", "Ethylene glycol plant (EO thermal hydration)", "MEG", p["capacity_tpd"], region)
    d.route = ("Ethylene oxide is reacted with a large excess of water in a pipe reactor without a catalyst. The water "
               "is boiled off in a three effect evaporator and a vacuum drying column and recycled, then vacuum "
               "columns split the glycols into MEG, DEG and TEG.")
    tot = _kg({"MEG": M, "DEG": Dg, "TEG": Tg})
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of MEG plus {Dg * MW('DEG') * 24 / 1000:,.0f} t/d of DEG and "
                 f"{Tg * MW('TEG') * 24 / 1000:,.0f} t/d of TEG from {E * MW('EO') * 24 / 1000:,.0f} t/d of ethylene "
                 f"oxide. MEG is {M * MW('MEG') / tot * 100:.0f} wt% of the glycols.")

    def dh(prod, reac):
        return (sum(n * core.h_molar(c, T0, "l") for c, n in prod.items())
                - sum(n * core.h_molar(c, T0, "l") for c, n in reac.items())) / 1000

    dH1 = dh({"MEG": 1}, {"EO": 1, "H2O": 1})
    dH2 = dh({"DEG": 1}, {"EO": 1, "MEG": 1})
    dH3 = dh({"TEG": 1}, {"EO": 1, "DEG": 1})
    d.reactions = [
        {"eq": "C2H4O + H2O -> HOCH2CH2OH", "where": "Pipe reactor, no catalyst", "dH_kJ": dH1},
        {"eq": "C2H4O + HOCH2CH2OH -> (HOCH2CH2)2O", "where": "Pipe reactor, consecutive", "dH_kJ": dH2},
        {"eq": "C2H4O + DEG -> TEG", "where": "Pipe reactor, consecutive (heavier glycols lumped)", "dH_kJ": dH3},
    ]
    Q_rx = (M * -dH1 + Dg * (-dH1 - dH2) + Tg * (-dH1 - dH2 - dH3)) * 1000 / 3600  # kW
    f_in = {"EO": E, "H2O": W0}
    cp_mix = sum(n * th.cp_liq(c) for c, n in f_in.items()) / 1000  # kJ/K per kmol/h basis -> kW/K / 3.6
    dT = Q_rx * 3600 / (cp_mix * 1000)
    T_out = p["T_in_C"] + dT
    d.conditions = [
        ("Reactor", f"{p['T_in_C']:.0f} C in, about {T_out:.0f} C out (adiabatic), {P_:.0f} bar, water to EO "
                    f"{p['water_eo_ratio']:.0f} mol/mol, full EO conversion"),
        ("Evaporators", f"{p['effects']} effects, falling pressure, glycols concentrated to {p['conc_glycol_wt'] * 100:.0f} wt%"),
        ("Columns", "drying, MEG and DEG columns under vacuum"),
    ]

    # ---------------------------------------------------------------- streams
    TR = T_out + 273.15
    s_eo = d.stream("Ethylene oxide", {"EO": E}, 283.15, P_ + 2, phase="l")
    s_w = d.stream("Make up water", {"H2O": Wc}, T0, P_ + 2, phase="l")
    s_r1 = d.stream("Water recycle from evaporators", {"H2O": We}, 373.15, P_ + 2, phase="l")
    s_r2 = d.stream("Water recycle from drying column", {"H2O": Wd}, 323.15, P_ + 2, phase="l")
    f_rx = {"H2O": Wleft, "MEG": M, "DEG": Dg, "TEG": Tg}
    s_rx = d.stream("Reactor effluent", f_rx, TR, P_, phase="l")
    f_conc = {"H2O": Wd, "MEG": M, "DEG": Dg, "TEG": Tg}
    s_conc = d.stream("Concentrated glycols", f_conc, 403.15, 0.3, phase="l")
    f_dry = {"MEG": M, "DEG": Dg, "TEG": Tg}
    s_dry = d.stream("Dry glycols", f_dry, 433.15, 0.15, phase="l")
    s_meg = d.stream("MEG", {"MEG": M}, 313.15, 1.5, phase="l")
    s_hv = d.stream("MEG column bottoms", {"DEG": Dg, "TEG": Tg}, 453.15, 0.1, phase="l")
    s_deg = d.stream("DEG", {"DEG": Dg}, 313.15, 1.5, phase="l")
    s_teg = d.stream("TEG and heavier", {"TEG": Tg}, 313.15, 1.5, phase="l")

    d.feed(s_eo, {"EO": "EO"})
    d.feed(s_w)
    d.out(s_meg, "product", {"MEG": "MEG"})
    d.out(s_deg, "byproduct", {"DEG": "DEG"})
    d.out(s_teg, "byproduct", {"TEG": "TEG"})

    d.unit("R-101", "Hydration reactor", "reactor", [s_eo, s_w, s_r1, s_r2], [s_rx], (0, 0), desc="Pipe reactor")
    d.unit("V-101", "Multiple effect evaporator", "separator", [s_rx], [s_conc, s_r1], (1, 0))
    d.unit("T-101", "Drying column", "column", [s_conc], [s_dry, s_r2], (2, 0))
    d.unit("T-102", "MEG column", "column", [s_dry], [s_meg, s_hv], (3, 0))
    d.unit("T-103", "DEG column", "column", [s_hv], [s_deg, s_teg], (4, 0))

    # ---------------------------------------------------------------- energy
    kw = lambda kmol_h, kJ_mol: kmol_h * kJ_mol * 1000 / 3600
    Q_ev = kw(We, th.hvap("H2O", 393.15) / 1000)
    econ = p["effects"] * p["economy_per_effect"]
    # the reaction heat arrives as sensible heat in the effluent and flashes water in the first effect
    Q_first = max(Q_ev / econ - Q_rx, 0.0)
    d.steam(Q_first / LATENT * 3600, f"Evaporator first effect ({p['effects']} effects)")
    d.cooling(Q_ev / econ, "Last effect condenser")
    Q_dry = kw(Wd * (1 + p["reflux_dry"]), th.hvap("H2O", 333.15) / 1000)
    d.steam(Q_dry / LATENT * 3600, "Drying column reboiler")
    d.cooling(Q_dry, "Drying column condenser")
    Q_meg = kw(M * (1 + p["reflux_meg"]), th.hvap("MEG", 433.15) / 1000)
    d.steam(Q_meg / LATENT * 3600, "MEG column reboiler")
    d.cooling(Q_meg, "MEG column condenser")
    Q_deg = kw(Dg * (1 + p["reflux_deg"]), th.hvap("DEG", 453.15) / 1000)
    d.steam(Q_deg / LATENT * 3600, "DEG column reboiler")
    d.cooling(Q_deg, "DEG column condenser")

    # ---------------------------------------------------------------- equipment
    rho = 950.0
    V_rx = _kg(f_in) / rho * p["residence_min"] / 60
    d.vessel("R-101", "Hydration pipe reactor", V_rx, P_barg=P_, material="SS", orientation="horizontal", LD=20.0)
    d.hx("E-101", "Feed and effluent interchanger", 0.5 * Q_ev / econ, TR, TR - 40, 373.15, p["T_in_C"] + 273.15,
         "liquid-water", P_barg=P_, material="SS")
    # falling film effects costed as shell and tube reboilers plus a vapour separator; about 12 K per effect
    for i in range(p["effects"]):
        Th = 433.15 - 25.0 * i
        d.hx(f"E-11{i}", f"Evaporator effect {i + 1} (falling film)", Q_ev / econ, Th, Th, Th - 12, Th - 12, "reboiler",
             material="SS")
        d.vessel(f"V-11{i}", f"Evaporator effect {i + 1} separator", max(_kg(f_rx) / 1000 * 0.05, 5.0), P_barg=5.0,
                 material="SS")
    d.column("T-101", "Drying column", Wd * (1 + p["reflux_dry"]), 333.15, 0.2, 15, MW("H2O"), material="SS")
    d.column("T-102", "MEG column", M * (1 + p["reflux_meg"]), 433.15, 0.1, 30, MW("MEG"), material="SS",
             packed=True)
    d.column("T-103", "DEG column", max(Dg * (1 + p["reflux_deg"]), 1.0), 453.15, 0.05, 20, MW("DEG"), material="SS",
             packed=True)
    d.hx("E-102", "Glycol column reboilers", Q_dry + Q_meg + Q_deg, 523.15, 523.15, 433.15, 443.15, "reboiler",
         material="SS")
    d.hx("E-103", "Condensers", Q_ev / econ + Q_dry + Q_meg + Q_deg, 373.15, 343.15, 303.15, 313.15, "condenser",
         material="SS")
    d.pump("P-101", "Reactor feed pump", _kg(f_in), 980, P_ + 2, material="SS")
    d.pump("P-102", "EO feed pump", E * MW("EO"), 880, P_ + 2)
    d.tank("TK-101", "EO bullets", E * MW("EO"), 880, days=1, pressurised=True, P_barg=5.0, material="SS")
    d.tank("TK-102", "MEG tanks", P_kg_h, 1110, days=p["storage_days"])
    d.tank("TK-103", "DEG and TEG tanks", _kg({"DEG": Dg, "TEG": Tg}), 1120, days=p["storage_days"])
    cw = d.cw_kW
    d.power(cw * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw, "Cooling water pumps and tower fans")
    d.power(0.0005 * _kg(f_conc) * 3, "Vacuum systems")
    d.power(0.05 * d.power_kW, "Compressed air, lighting, HVAC and flare (5% of process load)")

    # ---------------------------------------------------------------- KPIs and checks
    eo_t = E * MW("EO") / P_kg_h
    eo_eg = E * MW("EO") / tot
    meg_wt = M * MW("MEG") / tot * 100
    steam_t = d.steam_import_kg_h / P_kg_h
    lb = tot * 2.20462
    btu_steam = d.steam_import_kg_h * LATENT / 0.85 / 1.05506 / lb
    btu_net = btu_steam + d.power_kW * 3412 / lb
    d.kpis = [
        {"label": "EO use", "value": eo_t, "unit": "t/t MEG"},
        {"label": "MEG share of glycols", "value": meg_wt, "unit": "wt%"},
        {"label": "Steam", "value": steam_t, "unit": "t/t MEG"},
        {"label": "Electricity", "value": d.power_kW / (P_kg_h / 1000), "unit": "kWh/t MEG"},
        {"label": "Reactor temperature rise", "value": dT, "unit": "K"},
    ]
    DOE = "https://www.osti.gov/servlets/purl/1218625"
    DOES = "US DOE, Energy and Environmental Profile of the US Chemical Industry (2000), ethylene glycol"
    BREF = "https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/JRC109279_LVOC_Bref.pdf"
    SH = "https://www.nature.com/articles/s41598-024-77713-y"
    d.check("Ethylene oxide per lb ethylene glycol", eo_eg, 0.75, "lb/lb", DOES, DOE, tol=5,
            note="Model counts EO per lb of all glycols; with no EO losses it sits at the stoichiometric 0.71 plus the "
                 "extra EO in DEG and TEG.")
    d.check("MEG share of crude glycols", meg_wt, [75, 92], "wt%", "EU BREF LVOC (JRC109279, 2017), Section 7",
            BREF, tol=3, note=f"From the competing rate model at {p['water_eo_ratio']:.0f} mol water per mol EO and a "
                               f"rate ratio of {p['k_ratio']:.1f}.")
    d.check("Natural gas for steam and process heat", btu_steam, 1164, "Btu/lb EG", DOES, DOE, tol=25,
            note="Model steam at an 85% efficient gas boiler. DOE is the US 1997 average (range 865 to 1,463). The MEG "
                 "column dominates; see the reboiler check below.")
    d.check("Net process energy, ethylene glycol", btu_net, 2045, "Btu/lb EG", DOES, DOE, tol=25,
            note="Steam at an 85% boiler plus electricity at 3,412 Btu/kWh. DOE counts 533 Btu/lb of electricity, "
                 "far above this model's pumps and cooling water, and includes coal and other fuels.")
    d.check("Hydration reactor outlet temperature", T_out, [150, 250], "C", "EU BREF LVOC (JRC109279, 2017), "
            "Section 7", BREF, tol=0, note="Adiabatic rise from the reaction heat at the set water ratio and inlet "
                                           "temperature. Effluent stays liquid only if the pressure is above "
                                           f"{core.psat('H2O', TR):.0f} bar.")
    tpy = p["capacity_tpd"] * d.hours / 24
    d.check("MEG column reboiler duty", Q_meg / 1000, 30.66 * tpy / 600000, "MW",
            "Shehata et al. (2024), Scientific Reports 14, HYSYS design, scaled linearly from 600,000 t/y", SH, tol=25,
            note="Model uses an assumed reflux ratio of 1.0; the paper's design implies a lower one. Left failing "
                 "rather than tuned.")
    d.check("Capital, EO hydration to MEG unit, scaled", None, 70e6 * (tpy / 600000) ** 0.7, "USD",
            "Shehata et al. (2024), Scientific Reports 14: total capital investment USD 70 million for 600,000 t/y MEG "
            "(Aspen Process Economic Analyzer, accuracy plus or minus 25%, cost year not stated). Exponent 0.7",
            SH, tol=50, kind="capex", note="Published figure is a simulation estimate, not a built plant.")

    d.assumptions = [
        f"Glycol split from consecutive competing reactions with an assumed rate ratio of {p['k_ratio']:.1f} "
        "(EO with a glycol over EO with water, per mol); heavier glycols are lumped in TEG.",
        "EO conversion is complete and no EO is lost to acetaldehyde or other by-products.",
        "EO is bought over the fence; in practice MEG units sit next to an EO plant, so the margin here reads low "
        "(EO costs more per tonne than MEG sells for).",
        "Reaction heat flashes water in the first evaporator effect; feed is preheated against reactor effluent.",
        "EO buffer storage is one day, as the unit normally sits beside the EO plant.",
        f"Evaporator economy {p['economy_per_effect']:.1f} per effect over {p['effects']} effects; column reflux "
        "ratios are typical design values.",
    ]
    d.hazop = [
        {"node": "EO feed and storage", "deviation": "Contamination or high temperature", "cause": "Backflow of water, "
         "glycol, acid or caustic into EO", "consequence": "Runaway polymerisation or hydration, vessel rupture, "
         "toxic and explosive EO release", "safeguard": "Non return valves, EO kept cold under nitrogen, temperature "
         "alarms, water deluge"},
        {"node": "Hydration reactor", "deviation": "Low water to EO ratio", "cause": "Water recycle pump trip",
         "consequence": "Higher temperature rise and pressure, more DEG and TEG",
         "safeguard": "Ratio trip on the EO feed, relief to a catch tank"},
        {"node": "Vacuum columns", "deviation": "Air ingress", "cause": "Flange leak under vacuum",
         "consequence": "Glycol oxidation, product colour and acid", "safeguard": "Leak testing, oxygen monitoring"},
    ]
    d.greener = {
        "title": "Catalytic hydration or the ethylene carbonate route",
        "text": "Shell's OMEGA process goes through ethylene carbonate and gives nearly all MEG with far less water to "
                "boil off, cutting the steam use sharply. Bio ethylene from ethanol makes the whole chain renewable.",
    }
    return d.finish()
