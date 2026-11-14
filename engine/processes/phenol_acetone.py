"""Phenol and acetone from benzene and propylene by the cumene (Hock) process.

    C6H6 + C3H6 -> C9H12 (cumene)                  alkylation, zeolite, liquid phase
    C6H6 + 2 C3H6 -> C12H18 (diisopropylbenzene)    side reaction
    C12H18 + C6H6 -> 2 C9H12                         transalkylation of the DIPB
    C9H12 + O2 -> C9H12O2 (cumene hydroperoxide)     air oxidation
    C9H12 + 1/2 O2 -> C9H10 (AMS) + H2O              side reaction (via dimethylbenzyl alcohol)
    C9H12O2 -> C6H5OH + (CH3)2CO                     acid cleavage

Benzene and polymer grade propylene are alkylated over a zeolite with excess benzene; the DIPB made is
transalkylated back to cumene. Cumene is oxidised with air in bubble column oxidisers to about a
quarter conversion, the hydroperoxide is concentrated under vacuum and cleaved with a trace of
sulphuric acid. The cleavage product is split into acetone, a cumene and AMS cut, and phenol.

Benchmarks: EU BREF for Large Volume Organic Chemicals (JRC109279, 2017), US DOE Energy and Environmental
Profile of the US Chemical Industry (2000), ecoinvent 3.6 via GLAD, and a 2026 project cost report.
"""
from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 600.0,  # t/d phenol
    "benzene_propylene_ratio": 3.0,  # mol/mol at the alkylator inlet (assumed, zeolite liquid phase 2 to 4)
    "alk_cumene_sel": 0.90,  # mol propylene to cumene in the alkylator, the rest to DIPB (assumed)
    "dipb_purge": 0.02,  # share of the DIPB made that leaves as heavies (assumed)
    "trans_benzene_ratio": 4.0,  # mol benzene per mol DIPB to the transalkylator (assumed)
    "alk_T_C": 190.0,
    "alk_P_bar": 35.0,
    "ox_conversion": 0.25,  # cumene converted per pass in the oxidisers (typical 20 to 30%)
    "ox_selectivity": 0.93,  # mol CHP per mol cumene oxidised (typical 90 to 95%); the rest ends as AMS and water
    "ox_T_C": 100.0,
    "ox_P_bar": 5.0,
    "ox_residence_h": 8.0,  # liquid residence time over the oxidiser train (assumed)
    "offgas_o2": 0.05,  # mol O2 in the dry oxidiser off gas, kept below the flammable limit
    "chp_conc_wt": 0.80,  # CHP in the concentrate sent to cleavage
    "cleave_T_C": 60.0,
    "lhsv_h": 1.0,  # liquid hourly space velocity over the alkylation and transalkylation beds (assumed)
    "reflux_benzene": 1.0,  # reflux ratios (assumed, typical)
    "reflux_cumene": 1.5,
    "reflux_acetone": 2.0,
    "reflux_ams": 3.0,
    "reflux_phenol": 1.5,
    "storage_days": 14,
}

AIR = {"N2": 0.78084, "O2": 0.20946, "Ar": 0.00934 + 0.00036}
LATENT = 2100.0  # kJ/kg, heat given by imported steam (same basis as the other models)
H_LP_SAT = 2748.0  # kJ/kg saturated steam at 4.5 bar, raised from the alkylation heat


def _kg(flows):
    return sum(n * th.MW(c) for c, n in flows.items())


def _hl(flows, T):
    return sum(n * core.h_molar(c, T, "l") for c, n in flows.items()) / 3600.0  # kW for kmol/h


def _lhv_from_hf(cid, nC, nH):
    """kJ/mol lower heating value from heats of formation (for species without a tabulated LHV)."""
    return -(nC * core.h_molar("CO2", 298.15, "g") + nH / 2 * core.h_molar("H2O", 298.15, "g")
             - core.h_molar(cid, 298.15, "g")) / 1000


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    MW = th.MW
    T0 = 298.15
    P_kg_h = p["capacity_tpd"] * 1000 / 24
    Ph = P_kg_h / MW("Phenol")  # kmol/h phenol = CHP cleaved = acetone

    # ---------------------------------------------------------------- oxidation and cleavage (back from phenol)
    S = p["ox_selectivity"]
    Cn = Ph / S  # cumene consumed in the oxidisers
    ams = Cn - Ph  # cumene lost to AMS (and water)
    o2u = Ph + 0.5 * ams
    feed_ox = Cn / p["ox_conversion"]
    unreacted = feed_ox - Cn
    # concentrate: CHP at chp_conc_wt, the balance cumene plus the AMS and water already made
    chp_kg = Ph * MW("CHP")
    resid_kg = chp_kg / p["chp_conc_wt"] - chp_kg - ams * (MW("AMS") + MW("H2O"))
    resid = max(resid_kg, 0.0) / MW("Cumene")
    rec_evap = unreacted - resid
    y = p["offgas_o2"]
    air = o2u / (AIR["O2"] - y / (1 - y) * (1 - AIR["O2"]))
    f_air = {c: air * v for c, v in AIR.items()}
    f_off = {"N2": f_air["N2"], "Ar": f_air["Ar"], "O2": f_air["O2"] - o2u}

    # ---------------------------------------------------------------- cumene synthesis
    a = p["alk_cumene_sel"]
    b = (1 - a) / 2  # mol DIPB per mol propylene
    Fp = Cn / (a + 2 * b * (1 - p["dipb_purge"]))  # propylene feed
    m_dipb = b * Fp
    D = m_dipb * (1 - p["dipb_purge"])
    purge = m_dipb - D
    Fb = (a + b) * Fp + D  # fresh benzene
    B_in = p["benzene_propylene_ratio"] * Fp
    rec_a = B_in - Fb
    B_tr = p["trans_benzene_ratio"] * D
    f_alk_in = {"Benzene": B_in, "C3H6": Fp}
    f_alk = {"Benzene": B_in - (a + b) * Fp, "Cumene": a * Fp, "DIPB": m_dipb}
    f_tra = {"Benzene": B_tr - D, "Cumene": 2 * D}
    f_b1 = {"Cumene": a * Fp + 2 * D, "DIPB": m_dipb}
    f_poly = {"DIPB": m_dipb}

    d = Design("phenol_acetone", "Phenol and acetone plant (cumene process)", "Phenol", p["capacity_tpd"], region)
    d.route = ("Benzene is alkylated with propylene over a zeolite to cumene. Cumene is oxidised with air to cumene "
               "hydroperoxide, which is concentrated and split with a trace of sulphuric acid into phenol and acetone. "
               "Both are purified by distillation; about 0.6 t of acetone comes with every tonne of phenol.")
    ac_tpd = Ph * MW("Acetone") * 24 / 1000
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of phenol and {ac_tpd:,.0f} t/d of acetone from "
                 f"{Fb * MW('Benzene') * 24 / 1000:,.0f} t/d of benzene and {Fp * MW('C3H6') * 24 / 1000:,.0f} t/d of "
                 f"propylene, through {Cn * MW('Cumene') * 24 / 1000:,.0f} t/d of cumene.")

    def dh(prod, reac, ph="l"):
        return (sum(n * core.h_molar(c, T0, ph) for c, n in prod.items())
                - sum(n * core.h_molar(c, T0, ph) for c, n in reac.items())) / 1000

    dH_alk = dh({"Cumene": 1}, {"Benzene": 1, "C3H6": 1})
    dH_di = dh({"DIPB": 1}, {"Benzene": 1, "C3H6": 2})
    dH_tr = dh({"Cumene": 2}, {"DIPB": 1, "Benzene": 1})
    dH_ox = (core.h_molar("CHP", T0, "l") - core.h_molar("Cumene", T0, "l") - core.h_molar("O2", T0, "g")) / 1000
    dH_side = (core.h_molar("AMS", T0, "l") + core.h_molar("H2O", T0, "l") - core.h_molar("Cumene", T0, "l")
               - 0.5 * core.h_molar("O2", T0, "g")) / 1000
    dH_cl = dh({"Phenol": 1, "Acetone": 1}, {"CHP": 1})
    d.reactions = [
        {"eq": "C6H6 + C3H6 -> C6H5CH(CH3)2", "where": "Alkylator, zeolite, liquid phase", "dH_kJ": dH_alk},
        {"eq": "C6H6 + 2 C3H6 -> C6H4(C3H7)2", "where": "Alkylator, side reaction", "dH_kJ": dH_di},
        {"eq": "C6H4(C3H7)2 + C6H6 -> 2 C9H12", "where": "Transalkylator, zeolite", "dH_kJ": dH_tr},
        {"eq": "C9H12 + O2 -> C6H5C(CH3)2OOH", "where": "Oxidisers, air bubbled through cumene", "dH_kJ": dH_ox},
        {"eq": "C9H12 + 1/2 O2 -> C9H10 + H2O", "where": "Oxidisers and cleavage, by way of dimethylbenzyl alcohol",
         "dH_kJ": dH_side},
        {"eq": "C6H5C(CH3)2OOH -> C6H5OH + (CH3)2CO", "where": "Cleavage, sulphuric acid catalyst", "dH_kJ": dH_cl},
    ]
    d.conditions = [
        ("Alkylator", f"{p['alk_T_C']:.0f} C, {p['alk_P_bar']:.0f} bar, liquid phase, benzene to propylene "
                      f"{p['benzene_propylene_ratio']:.1f} mol/mol"),
        ("Transalkylator", f"benzene to DIPB {p['trans_benzene_ratio']:.0f} mol/mol"),
        ("Oxidisers", f"{p['ox_T_C']:.0f} C, {p['ox_P_bar']:.0f} bar, {p['ox_conversion'] * 100:.0f}% conversion per pass, "
                      f"{S * 100:.0f}% selectivity to CHP"),
        ("Off gas", f"{y * 100:.0f} mol% O2 (below the flammable limit)"),
        ("Concentrator", f"vacuum, CHP raised to {p['chp_conc_wt'] * 100:.0f} wt%"),
        ("Cleavage", f"{p['cleave_T_C']:.0f} C, trace sulphuric acid, back mixed with product to hold the heat"),
    ]

    # ---------------------------------------------------------------- streams
    TA = p["alk_T_C"] + 273.15
    TO = p["ox_T_C"] + 273.15
    PA = p["alk_P_bar"]
    PO = p["ox_P_bar"]
    s_benz = d.stream("Benzene", {"Benzene": Fb}, T0, 3.0, phase="l")
    s_prop = d.stream("Propylene", {"C3H6": Fp}, T0, PA + 2, phase="l")
    s_brec = d.stream("Benzene recycle to alkylator", {"Benzene": rec_a}, 353.15, PA, phase="l")
    s_alk = d.stream("Alkylator effluent", f_alk, TA + 20, PA - 1, phase="l")
    s_btr = d.stream("Benzene to transalkylator", {"Benzene": B_tr}, 353.15, PA, phase="l")
    s_dipb = d.stream("DIPB recycle", {"DIPB": D}, 453.15, PA, phase="l")
    s_tra = d.stream("Transalkylator effluent", f_tra, TA, PA - 1, phase="l")
    s_b1 = d.stream("Benzene column bottoms", f_b1, 433.15, 2.0, phase="l")
    s_cum = d.stream("Cumene", {"Cumene": Cn}, 313.15, PO + 1, phase="l")
    s_poly = d.stream("Polyalkylates", f_poly, 473.15, 0.5, phase="l")
    s_heavy = d.stream("Heavies to fuel", {"DIPB": purge}, 473.15, 1.5, phase="l")
    s_air = d.stream("Air", f_air, T0, 1.013, phase="g")
    s_crec = d.stream("Cumene recycle from concentrator", {"Cumene": rec_evap}, 313.15, PO + 1, phase="l")
    s_crec2 = d.stream("Cumene recycle from AMS column", {"Cumene": resid}, 313.15, PO + 1, phase="l")
    f_ox = {"Cumene": unreacted, "CHP": Ph, "AMS": ams, "H2O": ams}
    s_ox = d.stream("Oxidate", f_ox, TO, PO, phase="l")
    s_off = d.stream("Oxidiser off gas (after cumene recovery)", f_off, 278.15, PO - 0.5, phase="g")
    f_conc = {"Cumene": resid, "CHP": Ph, "AMS": ams, "H2O": ams}
    s_conc = d.stream("CHP concentrate", f_conc, 343.15, 1.5, phase="l")
    f_cl = {"Cumene": resid, "Phenol": Ph, "Acetone": Ph, "AMS": ams, "H2O": ams}
    s_cl = d.stream("Cleavage product", f_cl, p["cleave_T_C"] + 273.15, 1.5, phase="l")
    s_ace = d.stream("Acetone", {"Acetone": Ph}, 313.15, 1.5, phase="l")
    s_ww = d.stream("Water from the acetone columns", {"H2O": ams}, 323.15, 1.5, phase="l")
    s_bot = d.stream("Acetone column bottoms", {"Cumene": resid, "Phenol": Ph, "AMS": ams}, 433.15, 1.0, phase="l")
    s_ams = d.stream("AMS to fuel", {"AMS": ams}, 313.15, 1.5, phase="l")
    s_crude = d.stream("Crude phenol", {"Phenol": Ph}, 453.15, 0.5, phase="l")
    s_ph = d.stream("Phenol", {"Phenol": Ph}, 333.15, 1.5, phase="l")

    d.feed(s_benz, {"Benzene": "Benzene"})
    d.feed(s_prop, {"C3H6": "C3H6"})
    d.feed(s_air)
    d.out(s_ph, "product", {"Phenol": "Phenol"})
    d.out(s_ace, "byproduct", {"Acetone": "Acetone"})
    d.out(s_off, "emission")
    d.out(s_heavy, "fuel")
    d.out(s_ams, "fuel")
    d.out(s_ww, "waste", treat_usd_t=5.0)

    d.unit("R-101", "Alkylator", "reactor", [s_benz, s_prop, s_brec], [s_alk], (0, 0), desc="Zeolite beds, liquid phase")
    d.unit("R-102", "Transalkylator", "reactor", [s_btr, s_dipb], [s_tra], (0, 1), desc="Zeolite, DIPB back to cumene")
    d.unit("T-101", "Benzene column", "column", [s_alk, s_tra], [s_brec, s_btr, s_b1], (1, 0))
    d.unit("T-102", "Cumene column", "column", [s_b1], [s_cum, s_poly], (2, 0))
    d.unit("T-103", "Polyalkylate column", "column", [s_poly], [s_dipb, s_heavy], (2, 1))
    d.unit("R-201", "Oxidisers", "reactor", [s_cum, s_crec, s_crec2, s_air], [s_ox, s_off], (3, 0),
           desc="Bubble columns, air sparged, cooled")
    d.unit("V-201", "CHP concentrator", "separator", [s_ox], [s_conc, s_crec], (4, 0), desc="Vacuum evaporators")
    d.unit("R-301", "Cleavage reactor", "reactor", [s_conc], [s_cl], (5, 0), desc="Sulphuric acid, product loop cooled")
    d.unit("T-301", "Acetone columns (crude and finishing)", "column", [s_cl], [s_ace, s_ww, s_bot], (6, 0))
    d.unit("T-302", "Cumene and AMS column", "column", [s_bot], [s_crec2, s_ams, s_crude], (7, 0))
    d.unit("T-303", "Phenol column", "column", [s_crude], [s_ph], (8, 0))

    # ---------------------------------------------------------------- energy
    kw = lambda kmol_h, kJ_mol: kmol_h * kJ_mol * 1000 / 3600
    Q_alk = -kw(a * Fp, dH_alk) - kw(b * Fp, dH_di)
    steam_alk = Q_alk * 0.9 / (H_LP_SAT - th.H_BFW_105C) * 3600
    d.steam(-steam_alk, "Alkylator heat raised as 4.5 bar steam")
    d.cooling(Q_alk * 0.1, "Alkylator trim cooling")

    def col(tag, name, top_kmol_h, cid, R, T, P_bar, stages, material="CS", section=None):
        V = top_kmol_h * (1 + R)
        Q = kw(V, th.hvap(cid, T) / 1000)
        kg = Q / LATENT * 3600
        d.steam(kg, f"{name} reboiler")
        d.cooling(Q, f"{name} condenser")
        d.column(tag, name, V, T, P_bar, stages, MW(cid), material=material)
        if section is not None:
            section.append(kg)
        return Q

    cum_sec, ph_sec = [], []
    col("T-101", "Benzene column", rec_a + B_tr, "Benzene", p["reflux_benzene"], 383.15, 2.0, 30, section=cum_sec)
    col("T-102", "Cumene column", Cn, "Cumene", p["reflux_cumene"], 433.15, 1.5, 30, section=cum_sec)
    col("T-103", "Polyalkylate column", D + purge, "DIPB", 1.0, 453.15, 0.3, 15, section=cum_sec)
    # oxidation heat goes to cooling water (about 100 C, too low to raise useful steam)
    Q_ox = -kw(Ph, dH_ox) - kw(ams, dH_side)
    d.cooling(Q_ox, "Oxidiser coolers")
    # concentrator: evaporate the recycled cumene at 80 C under vacuum, plus warming the oxidate
    Q_conc = kw(rec_evap, th.hvap("Cumene", 353.15) / 1000) + _hl(f_ox, 353.15) - _hl(f_ox, TO - 30)
    d.steam(Q_conc / LATENT * 3600, "CHP concentrator")
    ph_sec.append(Q_conc / LATENT * 3600)
    d.cooling(Q_conc, "Concentrator vapour condensers")
    Q_cl = -kw(Ph, dH_cl)
    d.cooling(Q_cl, "Cleavage loop cooler")
    col("T-301", "Acetone columns", Ph, "Acetone", p["reflux_acetone"], 329.15, 1.2, 50, section=ph_sec)
    col("T-302", "Cumene and AMS column", resid + ams, "AMS", p["reflux_ams"], 433.15, 0.5, 40, section=ph_sec)
    col("T-303", "Phenol column", Ph, "Phenol", p["reflux_phenol"], 448.15, 0.3, 30, material="SS", section=ph_sec)

    # AMS and heavies burnt in the site boiler, steam credited, CO2 counted as direct
    lhv_ams = _lhv_from_hf("AMS", 9, 10)
    res_GJ_h = (ams * lhv_ams + purge * th.lhv_molar("DIPB") / 1000) * 1000 / 1e6
    res_steam = res_GJ_h * 1e6 * 0.85 / (th.H_STEAM_40BAR_450C - th.H_BFW_105C)
    d.steam(-res_steam, "AMS and heavies burnt in the site boiler (85% efficient)")
    d.direct_co2_kg_h += (9 * ams + 12 * purge) * MW("CO2")

    # ---------------------------------------------------------------- equipment
    rho = 800.0
    V_alk = _kg(f_alk_in) / rho / p["lhsv_h"] * 1.25
    d.vessel("R-101", "Alkylator (zeolite beds)", V_alk, P_barg=PA, LD=4.0)
    V_tra = _kg({"Benzene": B_tr, "DIPB": D}) / rho / p["lhsv_h"] * 1.25
    d.vessel("R-102", "Transalkylator", max(V_tra, 1.0), P_barg=PA)
    d.hx("E-101", "Alkylator steam generator", Q_alk * 0.9, TA + 20, TA, 420.15, 420.15, "liquid-steam", P_barg=PA)
    ox_kg_h = _kg({"Cumene": feed_ox})
    V_ox = ox_kg_h / 860 * p["ox_residence_h"] * 1.3  # 30% gas hold up and disengagement
    n_ox = max(1, int(-(-V_ox // 450)))
    for i in range(n_ox):
        d.vessel(f"R-201{chr(65 + i)}", f"Oxidiser {i + 1} of {n_ox}", V_ox / n_ox, P_barg=PO, LD=3.0, material="SS")
    d.hx("E-201", "Oxidiser coolers", Q_ox, TO, TO - 5, 303.15, 318.15, "liquid-water", P_barg=PO, material="SS")
    d.compressor("C-201", "Oxidation air compressor", s_air, PO + 1, k=1.4, eta=0.80)
    d.hx("E-202", "CHP concentrator evaporators", Q_conc, 418.15, 418.15, TO - 30, 353.15, "liquid-steam", material="SS")
    d.vessel("V-201", "Concentrator flash vessels", max(_kg(f_ox) / rho * 0.25, 5.0), P_barg=0.0, material="SS")
    V_cl = _kg(f_conc) / 1000 * 1.5  # about 5 min in the circulating loop including the loop volume
    d.vessel("R-301", "Cleavage reactor loop", max(V_cl, 2.0), P_barg=1.0, material="SS")
    d.hx("E-301", "Cleavage loop cooler", Q_cl, 333.15, 328.15, 303.15, 313.15, "liquid-water", material="SS")
    d.vessel("V-301", "Neutraliser and wash", max(_kg(f_cl) / rho * 0.5, 5.0), P_barg=1.0, material="SS")
    d.pump("P-101", "Alkylator feed pump", _kg(f_alk_in), 820, PA - 2)
    d.pump("P-201", "Oxidiser feed pump", ox_kg_h, 860, PO + 1)
    d.pump("P-301", "Cleavage loop pump", _kg(f_conc) * 20, 1000, 3.0, material="SS")
    d.pump("P-302", "Column feed pumps", _kg(f_cl) * 3, 950, 4.0, material="SS")
    d.tank("TK-101", "Benzene tanks", _kg({"Benzene": Fb}), 876, days=p["storage_days"])
    d.tank("TK-102", "Propylene bullets", _kg({"C3H6": Fp}), 520, days=5, pressurised=True, P_barg=20.0)
    d.tank("TK-301", "Phenol tanks (heated)", P_kg_h, 1050, days=p["storage_days"], material="SS")
    d.tank("TK-302", "Acetone tanks", Ph * MW("Acetone"), 785, days=p["storage_days"])
    cw = d.cw_kW
    d.power(cw * 3.6 / (4.18 * 10) / 3600 * 3.5e5 / 0.75 / 1000 + 0.006 * cw, "Cooling water pumps and tower fans")
    d.power(0.0005 * _kg(f_cl) * 3, "Vacuum systems")  # about 0.5 kWh per t of liquid flashed or distilled under vacuum
    d.power(0.05 * d.power_kW, "Compressed air, lighting, HVAC and flare (5% of process load)")

    # ---------------------------------------------------------------- KPIs and checks
    cum_tt = Cn * MW("Cumene") / P_kg_h
    acet_tt = Ph * MW("Acetone") / P_kg_h
    benz_cum = Fb * MW("Benzene") / (Cn * MW("Cumene"))
    prop_cum = Fp * MW("C3H6") / (Cn * MW("Cumene"))
    kwh_t = d.power_kW / (P_kg_h / 1000)
    steam_ph = sum(ph_sec) / P_kg_h
    steam_net = (d.steam_import_kg_h - d.steam_export_kg_h) / P_kg_h
    # phenol section process energy: steam at an 85% boiler, electricity at 3,412 Btu/kWh, per lb phenol + acetone
    lb = (P_kg_h + Ph * MW("Acetone")) * 2.20462
    p_cum = sum(i["kW"] for i in d.power_items if i["label"] in ("Alkylator feed pump",))
    btu_ph = (sum(ph_sec) * LATENT / 0.85 / 1.05506 + (d.power_kW - p_cum) * 3412) / lb
    d.kpis = [
        {"label": "Benzene use", "value": Fb * MW("Benzene") / P_kg_h, "unit": "t/t phenol"},
        {"label": "Propylene use", "value": Fp * MW("C3H6") / P_kg_h, "unit": "t/t phenol"},
        {"label": "Cumene to oxidation", "value": cum_tt, "unit": "t/t phenol"},
        {"label": "Acetone co-product", "value": acet_tt, "unit": "t/t phenol"},
        {"label": "AMS made (burnt here)", "value": ams * MW("AMS") / P_kg_h, "unit": "t/t phenol"},
        {"label": "Electricity", "value": kwh_t, "unit": "kWh/t phenol"},
        {"label": "Net steam", "value": steam_net, "unit": "t/t phenol (negative = export)"},
    ]
    BREF = "https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/JRC109279_LVOC_Bref.pdf"
    DOE = "https://www.osti.gov/servlets/purl/1218625"
    DOES = "US DOE, Energy and Environmental Profile of the US Chemical Industry (2000), Chapter 4 (cumene, phenol/acetone)"
    GLAD = "https://www.globallcadataaccess.org/phenol-production-cumene-upr-ecoinvent-36-allocation-cut-0"
    d.check("Cumene per t phenol", cum_tt, [1.31, 1.38], "t/t phenol",
            "EU BREF LVOC (JRC109279, 2017), Section 8.3.3", BREF, tol=5,
            note="Cumene fed to the oxidisers net of recycle. Set by the oxidation selectivity, a typical design value.")
    d.check("Cumene per lb phenol plus acetone", Cn * MW("Cumene") / (P_kg_h + Ph * MW("Acetone")), 0.81,
            "lb/lb", DOES, DOE, tol=5, note="DOE quotes the stoichiometric ratio; the model includes the AMS loss.")
    d.check("Benzene per lb cumene", benz_cum, 0.651, "lb/lb", DOES, DOE, tol=3)
    d.check("Propylene per lb cumene", prop_cum, 0.351, "lb/lb", DOES, DOE, tol=3,
            note="Polymer grade propylene; propane in refinery grade feed is not modelled.")
    d.check("Acetone co-product per kg phenol", acet_tt, 0.63, "kg/kg", "ecoinvent 3.6 'phenol production, from "
            "cumene' (RoW) via GLAD", GLAD, tol=5, note="Model is the 1 to 1 molar split from cleavage, 0.617 kg/kg.")
    d.check("Steam use, phenol plant", steam_ph, [2.3, 2.8], "t/t phenol", "EU BREF LVOC (JRC109279, 2017), Table 8.5",
            BREF, tol=25, note="Model steam for the phenol section only (concentrator and the three column systems), "
                               "before the credit from burning AMS. Reflux ratios are typical design values.")
    d.check("Electricity, phenol plant", kwh_t, [190, 326], "kWh/t phenol", "EU BREF LVOC (JRC109279, 2017), Table 8.5",
            BREF, tol=25, note="Model covers the whole plant including the cumene unit; the air compressor dominates.")
    d.check("Net process energy, phenol/acetone", btu_ph, [6020, 9680], "Btu/lb phenol + acetone", DOES, DOE, tol=25,
            note="Phenol section steam at an 85% efficient boiler plus electricity at 3,412 Btu/kWh. The model reads "
                 "far below the US 1997 average even though its steam sits near the EU BREF plant; the DOE figure "
                 "includes fuel oil, coal and other purchased energy for older, less integrated plants. Left failing.")
    tpy = p["capacity_tpd"] * d.hours / 24
    capex_pub = 630e6 * (tpy / 345000) ** 0.7
    d.check("Fixed capital, scaled from published plant", None, capex_pub, "USD (2024)",
            "ChemNet News (19 Oct 2026): Haldia Petrochemicals phenol plant, 345,000 t/y phenol and 215,000 t/y acetone, "
            "Lummus technology, total investment INR 60 billion, about USD 630 million. Scaled with exponent 0.7, "
            "not escalated (CEPCI table ends at 2024)",
            "https://news.chemnet.com/news-10860.html", tol=50, kind="capex",
            note="The published figure is a total investment in India, including offsites, a cumene unit and owner's "
                 "costs; the model is a US grassroots Turton estimate.")

    d.assumptions = [
        f"Oxidation selectivity {S * 100:.0f}% to cumene hydroperoxide; the rest is lumped as dimethylbenzyl alcohol, "
        "which dehydrates to AMS and water in the cleavage. Acetophenone and other minor by-products are not modelled.",
        "Cleavage is taken as complete and fully selective to phenol and acetone.",
        f"Alkylator makes {a * 100:.0f}% cumene and the rest DIPB on propylene; {(1 - p['dipb_purge']) * 100:.0f}% of the "
        "DIPB is transalkylated back to cumene and the rest leaves as heavies.",
        "Propylene is polymer grade; benzene is pure.",
        "Sulphuric acid catalyst (tens of ppm) and the caustic used to neutralise it are too small to show as streams.",
        "Cumene carried by the oxidiser off gas is recovered by chilling and carbon adsorption and not counted as a loss.",
        "AMS and heavies are burnt in the site boiler for steam; many plants hydrogenate AMS back to cumene or sell it.",
        "Column duties from reflux ratio times latent heat; reflux ratios are typical design values, not one plant's.",
    ]
    d.hazop = [
        {"node": "Oxidisers", "deviation": "High oxygen in the off gas", "cause": "Loss of cumene feed or low conversion",
         "consequence": "Flammable vapour space above the liquid, explosion",
         "safeguard": "Continuous O2 analysers with air trip, nitrogen purge, vapour space kept small"},
        {"node": "CHP concentrator and cleavage", "deviation": "High temperature", "cause": "Loss of cooling or vacuum, "
         "acid overdose", "consequence": "Runaway decomposition of cumene hydroperoxide (self accelerating)",
         "safeguard": "Temperature trips, acid flow ratio control, emergency dump to a quench tank with water"},
        {"node": "Phenol storage and loading", "deviation": "Loss of containment", "cause": "Line or seal failure on "
         "heated lines", "consequence": "Toxic, corrosive liquid; skin contact can be fatal",
         "safeguard": "Trace heated closed systems, full PPE, safety showers, Diphoterine or PEG first aid"},
        {"node": "Acetone and benzene handling", "deviation": "Release", "cause": "Leak at pumps or flanges",
         "consequence": "Highly flammable vapour cloud; benzene is a carcinogen",
         "safeguard": "Gas detection, sealless pumps, closed sampling, fire protection"},
    ]
    d.greener = {
        "title": "AMS hydrogenation and bio based propylene",
        "text": "Hydrogenating the AMS back to cumene saves about 4% of the cumene. Longer term, propylene from "
                "bio propane or methanol and benzene from bio aromatics cut the feedstock carbon; the plant itself "
                "emits little because both reactions release heat.",
    }
    return d.finish()
