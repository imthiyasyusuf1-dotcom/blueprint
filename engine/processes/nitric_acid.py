"""Nitric acid by the dual pressure Ostwald process, with tertiary N2O abatement.

Ammonia is burnt with air over Pt/Rh gauzes at medium pressure. The gauze temperature is the
adiabatic flame temperature of the chosen ammonia in air ratio, solved from formation enthalpies.
The NO yield is the Fertilizers Europe booklet figure for that pressure band. Gas heat raises
40 bar steam and reheats the tail gas; a NOx compressor takes the cooled gas to the high pressure
absorber, which makes 60% acid. A tail gas expander and a condensing steam turbine drive the
compressors and the surplus steam is exported.
"""
from iapws import IAPWS97

from .. import core
from .. import thermo as th
from .. import cost as C
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 1000.0,
    "nh3_in_air_pct": 10.5,
    "P_oxidation_bar": 5.0,
    "P_absorption_bar": 11.0,
    "no_yield_pct": 96.0,
    "acid_wt_pct": 60.0,
    "tail_O2_pct": 3.0,
    "tail_NOx_ppm": 150.0,
    "tertiary_abatement": True,
}
AIR = {"N2": 0.7808, "O2": 0.2095, "Ar": 0.0093}
N2O_GEN_KG_T = 7.0  # IPCC 2006 Table 3.3, medium-pressure combustion plants, unabated
N2O_ABATED_KG_T = 2.5  # IPCC 2006 Table 3.3, process integrated or tail gas N2O destruction
NM3 = 22.414

BOOKLET2 = "https://www.fertilizerseurope.com/wp-content/uploads/2019/08/Booklet_2_final.pdf"
UHDE = "https://pdfcoffee.com/uhde-nitric-acid-process-brochure-pdf-free.html"
IPCC = "https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/3_Volume3/V3_3_Ch3_Chemical_Industry.pdf"

_hin = core.hin
TAU_HOT_S = 2.0  # gas hold-up from boiler exit to economiser exit, s (assumed)


def _k_no_ox(T):
    """2NO + O2 -> 2NO2 rate coefficient, cm6 molecule-2 s-1, IUPAC datasheet NOx23 (273.5 to 780 K)."""
    return 10 ** (44700 / T ** 2 - 10.2 / T - 37.875)


def _oxidise(gas, T_in, T_out, P_bar, tau_s, steps=400):
    """Homogeneous NO oxidation while the gas cools linearly from T_in to T_out over tau_s.

    Rate -d[NO]/dt = 2 k [NO]^2 [O2]; equilibrium of 2NO + O2 = 2NO2 is checked at each step.
    Returns the outlet flows (kmol/h).
    """
    g = dict(gas)
    g.setdefault("NO2", 0.0)
    dt = tau_s / steps
    for i in range(steps):
        T = T_in + (T_out - T_in) * (i + 0.5) / steps
        tot = sum(g.values())
        c = P_bar * 1e5 / (th.R * T) * 6.02214e23 / 1e6  # molecule/cm3
        no, o2 = g["NO"] / tot * c, g["O2"] / tot * c
        r = 2 * _k_no_ox(T) * no * no * o2 * dt / c * tot  # kmol/h of NO converted in this step
        Kp = th.Kp({"NO": -2, "O2": -1, "NO2": 2}, T)
        # equilibrium limit on the NO2/NO ratio
        x_lim = (Kp * (g["O2"] / tot) * P_bar) ** 0.5
        r_max = max(0.0, (x_lim * g["NO"] - g["NO2"]) / (1 + x_lim))
        r = min(r, r_max, g["NO"], 2 * g["O2"])
        g["NO"] -= r
        g["NO2"] += r
        g["O2"] -= r / 2
    return g


def _expander_kW(n_kmol_h, T, P_in, P_out, k=1.39, eta=0.82):
    n = n_kmol_h * 1000 / 3600
    return n * th.R * T * k / (k - 1) * (1 - (P_out / P_in) ** ((k - 1) / k)) * eta / 1000


def _balance(t_h, p):
    """Mass balance for a product rate in t/h of 100% HNO3. Returns flows in kmol/h."""
    MWa = th.MW("HNO3")
    hno3 = t_h * 1000 / MWa
    y = p["no_yield_pct"] / 100
    n2o_gen = t_h * N2O_GEN_KG_T / th.MW("N2O")
    # iterate on the tail gas NOx (a set ppm of the tail gas)
    nox_tail = 0.0
    for _ in range(30):
        no = hno3 + nox_tail
        nh3 = no / y
        nh3_n2o = 2 * n2o_gen
        nh3_n2 = nh3 - no - nh3_n2o
        o2_burn = 1.25 * no + 1.0 * nh3_n2o + 0.75 * nh3_n2
        prim_air = nh3 * (100 / p["nh3_in_air_pct"] - 1)
        burner_out = {
            "NO": no, "N2O": n2o_gen, "H2O": 1.5 * nh3,
            "O2": prim_air * AIR["O2"] - o2_burn,
            "N2": prim_air * AIR["N2"] + nh3_n2 / 2, "Ar": prim_air * AIR["Ar"],
        }
        # absorber: NO + 3/4 O2 + 1/2 H2O -> HNO3
        n2o_out = n2o_gen
        if p["tertiary_abatement"]:
            n2o_out = t_h * N2O_ABATED_KG_T / th.MW("N2O")
        # tail gas before abatement; secondary air S solves O2 spec
        P_t = p["P_absorption_bar"]
        y_w = core.psat("H2O", 303.15) / P_t
        base = {"N2": burner_out["N2"], "Ar": burner_out["Ar"], "N2O": n2o_gen, "NO": nox_tail}
        o2_left = burner_out["O2"] - 0.75 * hno3
        # O2 + 0.2095 S = f * (sum(base) + o2_left + S + water); water = y_w/(1-y_w)*dry
        f = p["tail_O2_pct"] / 100
        k_w = 1 / (1 - y_w)
        S = (f * k_w * (sum(base.values()) + o2_left) - o2_left) / (AIR["O2"] - f * k_w)
        dry = dict(base)
        dry["N2"] += S * AIR["N2"]
        dry["Ar"] += S * AIR["Ar"]
        dry["O2"] = o2_left + S * AIR["O2"]
        tail_tot = sum(dry.values()) * k_w
        nox_new = p["tail_NOx_ppm"] * 1e-6 * tail_tot
        if abs(nox_new - nox_tail) < 1e-9:
            break
        nox_tail = nox_new
    tail = dict(dry)
    tail["H2O"] = tail_tot * y_w
    # water: product acid at acid_wt_pct
    w_prod = t_h * 1000 * (100 / p["acid_wt_pct"] - 1) / th.MW("H2O")
    water_in_gas = burner_out["H2O"] - 0.5 * hno3  # left after the absorber reaction
    makeup = w_prod + tail["H2O"] - water_in_gas
    stack = dict(tail)
    if p["tertiary_abatement"]:
        destroyed = n2o_gen - n2o_out
        stack["N2O"] = n2o_out
        stack["N2"] += destroyed
        stack["O2"] += destroyed / 2
    return {
        "hno3": hno3, "nh3": nh3, "prim_air": prim_air, "sec_air": S, "burner_out": burner_out,
        "tail": tail, "stack": stack, "w_prod": w_prod, "makeup": makeup, "n2o_gen": n2o_gen,
        "air_tot": prim_air + S,
    }


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    t_h = p["capacity_tpd"] / 24
    b = _balance(t_h, p)
    Pox, Pab = p["P_oxidation_bar"], p["P_absorption_bar"]
    MWw = th.MW("H2O")

    # ---- compressors and gauze temperature
    air_f = {c: b["air_tot"] * x for c, x in AIR.items()}
    W_air, n_air, _ = C.compressor_power(b["air_tot"] * 1000 / 3600, 293.15, 1.013, Pox + 0.5, k=1.4, eta=0.80)
    r_st = ((Pox + 0.5) / 1.013) ** (1 / n_air)
    T_air = 313.15 * (1 + (r_st ** (0.4 / 1.4) - 1) / 0.80) if n_air > 1 else 293.15 * (1 + (r_st ** (0.4 / 1.4) - 1) / 0.80)
    prim = {c: b["prim_air"] * x for c, x in AIR.items()}
    sec = {c: b["sec_air"] * x for c, x in AIR.items()}
    nh3_g = {"NH3": b["nh3"]}
    H_in = _hin(prim, T_air) + _hin(nh3_g, 373.15)
    T_g = core.adiabatic_T(H_in, b["burner_out"], Pox, 1150.0)

    gas = b["burner_out"]
    Q_boil = _hin(gas, T_g) - _hin(gas, 723.15)
    # gas leaving the cooler condenser (50 C) mixed with bleacher air, compressed to absorber pressure
    nox_in = sum(gas.values()) - gas["H2O"] + b["sec_air"]
    W_nox, n_nox, Q_nox = C.compressor_power(nox_in * 1000 / 3600, 323.15, Pox - 0.6, Pab + 0.3, k=1.4, eta=0.80)
    # tail gas reheated to 350 C: first by NOx compressor heat (booklet 2.4), the rest by process gas
    T_exp = 623.15
    tail = b["tail"]
    Q_tail = _hin(tail, T_exp) - _hin(tail, 303.15)
    Q_tgh = max(0.0, Q_tail - Q_nox / 1000)
    # NO oxidises to NO2 as the gas cools (Booklet 2, 2.2); its heat goes to the tail gas heater and economiser
    gas_c = _oxidise(gas, 723.15, 423.15, Pox - 0.3, TAU_HOT_S)
    ox_pct = gas_c["NO2"] / gas["NO"] * 100
    T_after_tgh = core.adiabatic_T(_hin(gas, 723.15) - Q_tgh, gas, Pox, 600.0)
    Q_econ = max(0.0, _hin(gas, 723.15) - Q_tgh - _hin(gas_c, 423.15))

    hp = IAPWS97(P=4.0, T=723.15)
    h_hp = float(hp.h)
    h_ex = float(IAPWS97(P=0.01, s=hp.s).h)
    h_cond = float(IAPWS97(P=0.01, x=0).h)
    dh_turb = (h_hp - h_ex) * 0.78
    steam_raised = (Q_boil + Q_econ) / (th.H_STEAM_40BAR_450C - th.H_BFW_105C) * 3600
    W_exp = _expander_kW(sum(tail.values()), T_exp, Pab - 0.5, 1.05)
    W_net = W_air + W_nox - W_exp
    turb_kg_h = max(0.0, W_net / 0.97 / dh_turb * 3600)
    export = steam_raised - turb_kg_h

    # cooler condenser + absorber cooling from an enthalpy balance
    acid = {"HNO3": b["hno3"], "H2O": b["w_prod"]}
    H_acid = sum(n * core.h_molar(c, 313.15, "l") for c, n in acid.items()) / 3600
    H_mk = b["makeup"] * core.h_molar("H2O", 298.15, "l") / 3600
    Q_abs = _hin(gas_c, 423.15) + _hin(sec, T_air) + H_mk - H_acid - _hin(tail, 303.15)

    d = Design("nitric_acid", "Nitric acid plant (dual pressure, tertiary N2O abatement)", "Nitric acid",
               p["capacity_tpd"], region)
    d.route = ("Ammonia is vaporised, mixed with compressed air and burnt over platinum rhodium gauzes to nitric "
               "oxide. The hot gas raises steam and reheats the tail gas, is cooled, compressed again and absorbed "
               "in water in a high-pressure tray column to 60% acid. A catalyst bed destroys most of the N2O in the "
               "tail gas before an expander recovers its energy.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d nitric acid (100% basis, sold as 60% acid) from ammonia, the "
                 "fertiliser grade dual pressure route, with surplus steam exported.")
    d.reactions = [
        {"eq": "4 NH3 + 5 O2 -> 4 NO + 6 H2O", "where": "Pt/Rh gauze", "dH_kJ": th.dh_rxn_gas({"NH3": -4, "O2": -5, "NO": 4, "H2O": 6}) / 1000},
        {"eq": "4 NH3 + 4 O2 -> 2 N2O + 6 H2O", "where": "Pt/Rh gauze (side)", "dH_kJ": th.dh_rxn_gas({"NH3": -4, "O2": -4, "N2O": 2, "H2O": 6}) / 1000},
        {"eq": "4 NH3 + 3 O2 -> 2 N2 + 6 H2O", "where": "Pt/Rh gauze (side)", "dH_kJ": th.dh_rxn_gas({"NH3": -4, "O2": -3, "N2": 2, "H2O": 6}) / 1000},
        {"eq": "2 NO + O2 <=> 2 NO2", "where": "Coolers and absorber", "dH_kJ": th.dh_rxn_gas({"NO": -2, "O2": -1, "NO2": 2}) / 1000},
        {"eq": "3 NO2 + H2O -> 2 HNO3 + NO", "where": "Absorber", "dH_kJ": None},
        {"eq": "2 N2O -> 2 N2 + O2", "where": "Tertiary abatement bed", "dH_kJ": th.dh_rxn_gas({"N2O": -2, "N2": 2, "O2": 1}) / 1000},
    ]
    d.conditions = [
        ("Ammonia oxidation", f"{Pox:.1f} bar, {p['nh3_in_air_pct']:.1f} mol% NH3 in air, gauze {T_g - 273.15:.0f} C (adiabatic, solved)"),
        ("NO yield", f"{p['no_yield_pct']:.0f}% (Booklet 2, 1.7 to 6.5 bar)"),
        ("Gas cooling train", f"{ox_pct:.0f}% of the NO oxidised to NO2 before the cooler condenser (IUPAC kinetics, {TAU_HOT_S:.0f} s)"),
        ("Absorption", f"{Pab:.0f} bar, 30 to 40 C, tail gas {p['tail_NOx_ppm']:.0f} ppm NOx and {p['tail_O2_pct']:.0f}% O2"),
        ("Tail gas", f"N2O abatement {'on' if p['tertiary_abatement'] else 'off'}, expander inlet {T_exp - 273.15:.0f} C"),
    ]

    # ---- streams
    s_nh3 = d.stream("Liquid ammonia", nh3_g, 300.15, 12, phase="l")
    s_air = d.stream("Process air", air_f, 293.15, 1.013)
    s_mix = d.stream("Ammonia air mixture", core.add(prim, nh3_g), T_air, Pox)
    s_g = d.stream("Gauze outlet gas", gas, T_g, Pox - 0.2)
    s_gc = d.stream("Cooled process gas", gas_c, 423.15, Pox - 0.4)
    s_sec = d.stream("Secondary air to bleacher", sec, T_air, Pox)
    s_w = d.stream("Process water make-up", {"H2O": b["makeup"]}, 298.15, Pab + 2, phase="l")
    s_acid = d.stream("Nitric acid 60%", acid, 313.15, 3, phase="l")
    s_tail = d.stream("Tail gas from absorber", tail, 303.15, Pab)
    s_stack = d.stream("Stack gas", b["stack"], 453.15, 1.05)

    d.feed(s_nh3, {"NH3": "NH3"})
    d.feed(s_air)
    d.feed(s_w)
    d.out(s_acid, "product", {"HNO3": "HNO3"})
    d.out(s_stack, "emission")

    d.unit("E-101", "Ammonia vaporiser", "exchanger", [s_nh3], [], (0, 1))
    d.unit("K-101", "Air compressor", "compressor", [s_air], [s_sec], (0, 0), power_kW=W_air)
    d.unit("R-101", "Ammonia burner and gauze", "reactor", [s_mix], [s_g], (1, 0))
    d.unit("E-102", "Waste heat boiler and superheater", "exchanger", [s_g], [s_gc], (2, 0), duty_kW=-(Q_boil + Q_econ))
    d.unit("K-102", "NOx compressor", "compressor", [s_gc], [], (3, 0), power_kW=W_nox)
    d.unit("C-101", "Absorption column", "column", [s_w], [s_acid, s_tail], (4, 0), duty_kW=-Q_abs)
    d.unit("C-102", "Bleacher", "column", [s_sec], [], (4, 1))
    d.unit("R-102", "Tertiary N2O abatement and expander", "reactor", [s_tail], [s_stack], (5, 0), power_kW=-W_exp)
    s_mix.src = "K-101"

    # ---- utilities
    if export >= 0:
        d.steam(-export, "Net 40 bar steam export (after compressor turbine)")
    else:
        d.steam(-export, "40 bar steam import for compressor turbine")
    d.cooling(turb_kg_h * (h_hp - dh_turb - h_cond) / 3600, "Turbine condenser")
    d.cooling(Q_abs, "Cooler condensers and absorber coils")
    nh3_vap_kW = b["nh3"] * th.comp("NH3")["Hvap_298"] / 3600
    acid_kg_h = sum(n * th.MW(c) for c, n in acid.items())
    d.pump("P-101", "Acid product pump", acid_kg_h, 1370, 4, material="SS")
    d.pump("P-102", "Boiler feed water pump", steam_raised, 950, 45)
    d.pump("P-103", "Process water pump", b["makeup"] * MWw, 1000, Pab + 2)
    d.pump("P-104", "Absorber cooling water circulation", Q_abs * 3600 / (4.18 * 10), 1000, 3)
    d.demin_water_m3_h = (b["makeup"] * MWw + steam_raised * 0.03) / 1000

    # ---- equipment
    d.generic("K-101", "Air compressor", "compressor", W_air, f"{W_air:,.0f} kW, {n_air} stages, to {Pox + 0.5:.1f} bar")
    d.generic("K-102", "NOx compressor", "compressor", W_nox, f"{W_nox:,.0f} kW, to {Pab + 0.3:.1f} bar", material="SS")
    d.generic("X-101", "Tail gas expander", "turbine_steam", W_exp, f"{W_exp:,.0f} kW shaft", material="SS",
              note="Costed as a steam turbine of the same power (no Turton gas expander curve)")
    d.generic("X-102", "Condensing steam turbine", "turbine_steam", max(W_net, 70.0), f"{max(W_net, 0):,.0f} kW shaft")
    Vg = core.gas_volume_m3_h(sum(gas.values()), T_g, Pox) / 3600
    d.vessel("R-101", "Ammonia burner (gauze basket)", max(10.0, Vg * 2.0), P_barg=Pox, material="SS")
    d.hx("E-102", "Waste heat boiler", Q_boil * 0.8, T_g, 773.15, 523.15, 523.15, "boiler", P_barg=40, material="SS")
    d.hx("E-103", "Steam superheater", Q_boil * 0.2, 873.15, 723.15, 523.15, 723.15, "gas-steam", P_barg=40, material="SS")
    d.hx("E-104", "Tail gas heater", Q_tgh, 723.15, T_after_tgh, 403.15, T_exp, "hp-gas", P_barg=Pab, material="SS")
    d.hx("E-105", "Economiser", max(Q_econ, 1.0), T_after_tgh, 423.15, 378.15, 473.15, "gas-water", P_barg=45, material="SS")
    d.hx("E-101", "Ammonia vaporiser", nh3_vap_kW, 303.15, 293.15, 278.15, 283.15, "liquid-water")
    d.hx("E-106", "Cooler condensers", Q_abs * 0.5, 423.15, 323.15, 303.15, 313.15, "wet-gas", P_barg=Pab, material="SS")
    d.column("C-101", "Absorption column", sum(tail.values()), 313.15, Pab, 30, 29.0, material="SS", tray_eff=0.6)
    d.column("C-102", "Bleacher", b["sec_air"], 323.15, Pox, 4, 29.0, material="SS")
    d.reactor_bed("R-102", "Tertiary N2O abatement bed", sum(tail.values()), 10000, Pab, material="SS")
    d.tank("TK-101", "Nitric acid tank", acid_kg_h, 1370, days=7, material="SS")
    d.vessel("V-101", "Steam drum", max(5.0, steam_raised / 1000 * 0.5), P_barg=40, orientation="horizontal")

    # ---- KPIs
    tail_Nm3_t = sum(tail.values()) * NM3 / t_h
    n2o_ppm_gen = b["n2o_gen"] / sum(tail.values()) * 1e6
    nh3_kg_t = b["nh3"] * th.MW("NH3") / t_h
    n2o_kg_t = b["stack"]["N2O"] * th.MW("N2O") / t_h
    exp_t_t = export / 1000 / t_h
    d.kpis = [
        {"label": "Ammonia consumption", "value": nh3_kg_t, "unit": "kg/t HNO3"},
        {"label": "Gauze temperature", "value": T_g - 273.15, "unit": "C"},
        {"label": "Steam export (40 bar, 450 C)", "value": exp_t_t, "unit": "t/t HNO3"},
        {"label": "Tail gas flow", "value": tail_Nm3_t, "unit": "Nm3/t HNO3"},
        {"label": "NO oxidised in cooling train", "value": ox_pct, "unit": "%"},
        {"label": "N2O before abatement", "value": n2o_ppm_gen, "unit": "ppmv"},
        {"label": "N2O to air", "value": n2o_kg_t, "unit": "kg/t HNO3"},
        {"label": "N2O as CO2e (GWP100 273)", "value": n2o_kg_t * 273 / 1000, "unit": "t CO2e/t HNO3"},
    ]

    # ---- validation
    d.check("Ammonia consumption", nh3_kg_t, 282.0, "kg/t", "Uhde nitric acid brochure (2012), dual pressure",
            UHDE, tol=3)
    d.check("HP steam export", exp_t_t, 0.65, "t/t", "Uhde nitric acid brochure (2012), dual pressure, 40 bar 450 C",
            UHDE, tol=30, kind="energy")
    d.check("Gauze temperature", T_g - 273.15, [850, 900], "C", "Fertilizers Europe Booklet 2, 1.7 to 6.5 bar band",
            BOOKLET2, tol=0, kind="thermo")
    d.check("Tail gas flow", tail_Nm3_t, [3100, 3400], "Nm3/t", "Fertilizers Europe Booklet 2, section 4.1.1.1",
            BOOKLET2, tol=0)
    d.check("N2O in absorber tail gas (before abatement)", n2o_ppm_gen, [300, 3500], "ppmv",
            "Fertilizers Europe Booklet 2, section 4.1.1.1", BOOKLET2, tol=0)
    if p["tertiary_abatement"]:
        d.check("N2O emission factor", n2o_kg_t, 2.5, "kg/t", "IPCC 2006 Vol 3 Table 3.3, tail gas N2O destruction",
                IPCC, tol=10, kind="emissions", note="Design input: abated emission set to this factor, shown for reference.")
    else:
        d.check("N2O emission factor", n2o_kg_t, 7.0, "kg/t", "IPCC 2006 Vol 3 Table 3.3, medium pressure",
                IPCC, tol=20, kind="emissions", note="Design input: N2O generation set to this factor, shown for reference.")

    d.assumptions = [
        f"NO yield {p['no_yield_pct']:.0f}% from Fertilizers Europe Booklet 2 for 1.7 to 6.5 bar. N2O generation is the "
        "IPCC 2006 default for medium-pressure plants (7 kg/t); the rest of the ammonia goes to N2.",
        "With tertiary abatement the N2O leaving is the IPCC default for plants with tail gas N2O destruction (2.5 kg/t).",
        f"Gauze temperature solved as the adiabatic temperature of {p['nh3_in_air_pct']:.1f}% NH3 in air (typical 9.5 to "
        "11.5%), air at compressor outlet, NH3 vapour at 100 C.",
        f"Tail gas O2 {p['tail_O2_pct']:.0f}% (booklet 2 to 4%) fixes the secondary air; tail gas NOx {p['tail_NOx_ppm']:.0f} "
        "ppm (booklet 100 to 200 ppm for high-pressure absorption), no SCR.",
        "Air and NOx compressors polytropic 0.80; expander 0.82 from 350 C; condensing turbine 40 bar 450 C to 0.1 bar "
        "at 78% isentropic (IAPWS-97). NOx compressor heat goes to the tail gas.",
        f"NO oxidation in the hot cooling train from IUPAC kinetics (datasheet NOx23) over an assumed {TAU_HOT_S:.0f} s "
        "gas hold-up while the gas cools from 450 to 150 C; that heat is recovered as steam.",
        "Absorber and cooler condenser duty from an enthalpy balance, heat of mixing of acid and water ignored.",
        "Platinum gauze inventory and losses are not costed.",
    ]
    d.hazop = [
        {"node": "Ammonia air mixer", "deviation": "High NH3 to air ratio", "cause": "Air compressor surge, NH3 flow control fault",
         "consequence": "Explosive mixture above the lower flammable limit, burner explosion",
         "safeguard": "Ratio trip shutting the NH3 valve, two independent analysers"},
        {"node": "Ammonia burner", "deviation": "High gauze temperature", "cause": "High NH3 ratio, low gas flow",
         "consequence": "Platinum loss, gauze damage, higher N2O", "safeguard": "Gauze thermocouples, ratio control"},
        {"node": "NOx compressor", "deviation": "Ammonium nitrate deposits", "cause": "NH3 slip into the cooled gas",
         "consequence": "Explosive AN salts in compressor and coolers", "safeguard": "NH3 slip monitoring, washing routine"},
        {"node": "Absorber", "deviation": "Loss of cooling", "cause": "Cooling water pump trip",
         "consequence": "High NOx emission, brown plume", "safeguard": "NOx analyser, plant trip, spare pumps"},
        {"node": "Acid tank", "deviation": "Loss of containment", "cause": "Corrosion, overfill",
         "consequence": "Corrosive acid spill, NOx fumes", "safeguard": "Stainless tanks, bunds, level alarms"},
    ]
    d.greener = {
        "title": "Abatement plus green ammonia",
        "text": "N2O is the biggest climate hit of this plant: unabated it is about 7 kg/t, close to 2 t CO2e per tonne "
                "of acid. Tertiary catalysts take it to the IPCC 2.5 kg/t factor or below. After that the footprint "
                "is in the ammonia, so electrolytic ammonia gives an almost zero carbon acid.",
        "electricity_MWh_per_t": 0.0,
    }
    return d.finish()
