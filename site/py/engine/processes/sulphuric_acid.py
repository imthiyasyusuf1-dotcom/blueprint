"""Sulphuric acid from sulphur burning, double contact double absorption (3 + 1 beds).

Molten sulphur is burnt in dried air. The furnace temperature is solved from an enthalpy balance.
Each of the four converter beds is an adiabatic equilibrium reactor for SO2 + 1/2 O2 = SO3, using
the Gibbs energies in components.json, with a small approach to equilibrium. SO3 is absorbed in
98.5% acid after bed 3 (interpass) and after bed 4 (final). All gas cooling down to 180 C
raises 40 bar steam, less the duty needed to reheat the gas coming back from the interpass absorber.
"""
from .. import core
from .. import thermo as th
from .. import cost as C
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 2000.0,
    "so2_pct": 11.0,
    "bed_inlet_C": 430.0,
    "bed4_inlet_C": 420.0,
    "approach_C": 10.0,
    "acid_wt_pct": 98.5,
    "blower_dP_bar": 0.45,
}
AIR = {"N2": 0.7808, "O2": 0.2095, "Ar": 0.0093}
AIR_H2O = 0.015  # mol water per mol dry air (about 60% RH at 20 C), removed in the drying tower
RXN = {"SO2": -1, "O2": -0.5, "SO3": 1}
LOSS_FRAC = 0.016  # heat lost from furnace, boiler and converter shells (Booklet 3, appendix A8, "Loss 1.6%")
BOOKLET3 = "https://www.fertilizerseurope.com/wp-content/uploads/2019/08/Booklet_3_final.pdf"
SRC3 = "ESA/Fertilizers Europe BAT Booklet No. 3 (2000)"


def _bed(feed, T_in, P, approach):
    """Adiabatic bed: outlet where enthalpy balance and equilibrium at T + approach both hold."""
    H_in = core.hin(feed, T_in)
    Kfun = lambda r, T: th.Kp(r, T + approach)
    lo, hi = T_in, T_in + 300
    out = feed
    for _ in range(60):
        T = (lo + hi) / 2
        out, _ = core.equilibrium(feed, [RXN], T, P, Kfun=Kfun)
        if core.hin(out, T) > H_in:
            hi = T
        else:
            lo = T
        if hi - lo < 0.01:
            break
    return (lo + hi) / 2, out


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    t_h = p["capacity_tpd"] / 24
    MWa, MWw, MWs = th.MW("H2SO4"), th.MW("H2O"), th.MW("S")
    P1 = 1.0 + p["blower_dP_bar"]
    Tin, Tin4, appr = p["bed_inlet_C"] + 273.15, p["bed4_inlet_C"] + 273.15, p["approach_C"]

    # ---- solve the sulphur rate so that product H2SO4 matches capacity (stack SO2 is the only S loss)
    acid_mol = t_h * 1000 / MWa
    S = acid_mol
    for _ in range(20):
        # air such that SO2 is so2_pct of the burner gas (burner gas moles = air moles)
        air = S / (p["so2_pct"] / 100)
        dry_air = {c: air * x for c, x in AIR.items()}
        burner = dict(dry_air)
        burner["O2"] -= S
        burner["SO2"] = S
        T1, b1 = _bed(burner, Tin, P1 - 0.05, appr)
        T2, b2 = _bed(b1, Tin, P1 - 0.1, appr)
        T3, b3 = _bed(b2, Tin, P1 - 0.15, appr)
        so3_ipa = b3["SO3"]
        g4 = {c: n for c, n in b3.items() if c != "SO3"}
        T4, b4 = _bed(g4, Tin4, P1 - 0.25, appr)
        made = so3_ipa + b4["SO3"]
        S_new = S * acid_mol / made
        if abs(S_new - S) < 1e-8:
            break
        S = S_new
    conv = made / S * 100
    conv3 = so3_ipa / S * 100
    stack = {c: n for c, n in b4.items() if c != "SO3"}

    # ---- furnace: molten sulphur at 140 C, air from the blower and drier at about 80 C
    T_air = 353.15
    H_f = core.hin(dry_air, T_air) + S * core.h_molar("S", 413.15, "l") / 3600
    T_f = core.adiabatic_T(H_f, burner, P1, 1300.0)

    # ---- heat recovery to 40 bar steam (gas cooling) and the interpass reheat
    Q_whb = core.hin(burner, T_f) - core.hin(burner, Tin)
    Q_b1 = core.hin(b1, T1) - core.hin(b1, Tin)
    Q_b2 = core.hin(b2, T2) - core.hin(b2, Tin)
    Q_b3 = core.hin(b3, T3) - core.hin(b3, 453.15)
    Q_reheat = core.hin(g4, Tin4) - core.hin(g4, 353.15)  # IPA gas 80 C back to bed 4 inlet
    Q_b4 = core.hin(b4, T4) - core.hin(b4, 453.15)
    Q_steam = Q_whb + Q_b1 + Q_b2 + Q_b3 + Q_b4 - Q_reheat
    h_net = th.H_STEAM_40BAR_450C - th.H_BFW_105C

    # ---- absorbers and acid coolers (cooling water): SO3 at 180 C to 98.5% acid at 75 C, then cooled to 40 C
    w_prod = t_h * 1000 * (100 / p["acid_wt_pct"] - 1) / MWw
    w_air = air * AIR_H2O
    w_mk = acid_mol + w_prod - w_air
    acid = {"H2SO4": acid_mol, "H2O": w_prod}
    H_acid40 = sum(n * core.h_molar(c, 313.15, "l") for c, n in acid.items()) / 3600
    H_in_abs = core.hin({"SO3": so3_ipa}, 453.15) + core.hin({"SO3": b4["SO3"]}, 453.15)
    H_in_abs += w_mk * core.h_molar("H2O", 298.15, "l") / 3600 + w_air * core.h_molar("H2O", 293.15, "l") / 3600
    # inert gas through the absorbers: 180 C in, 80 C out
    Q_gas_abs = core.hin(g4, 453.15) - core.hin(g4, 353.15) + core.hin(stack, 453.15) - core.hin(stack, 353.15)
    Q_cw = H_in_abs - H_acid40 + Q_gas_abs

    # ---- blower and power
    W_bl, n_bl, _ = C.compressor_power(air * (1 + AIR_H2O) * 1000 / 3600, 303.15, 1.0, P1, k=1.4, eta=0.80)
    total_heat = (S * (core.h_molar("S", 413.15, "l") - 0) / 3600 + core.hin(dry_air, 298.15)
                  + w_mk * core.h_molar("H2O", 298.15, "l") / 3600 + w_air * core.h_molar("H2O", 298.15, "l") / 3600
                  - sum(n * core.h_molar(c, 298.15, "l") for c, n in acid.items()) / 3600
                  - core.hin(stack, 298.15))

    # Booklet A8 basis: inputs are sulphur heat plus blower power; 1.6% of it is lost from hot surfaces
    Q_steam_net = Q_steam - LOSS_FRAC * (total_heat + W_bl)
    share = Q_steam_net / (total_heat + W_bl) * 100
    steam_kg_h = Q_steam_net * 3600 / h_net

    d = Design("sulphuric_acid", "Sulphuric acid plant (sulphur burning, double contact)", "Sulphuric acid",
               p["capacity_tpd"], region)
    d.route = ("Molten sulphur is burnt in dried air to SO2. A four bed vanadium catalyst converter oxidises it to "
               "SO3, which is absorbed in strong acid after the third bed and again after the fourth (double contact "
               "double absorption). The heat of burning and conversion raises high pressure steam for export.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d sulphuric acid (100% basis, sold as {p['acid_wt_pct']:.1f}%) from "
                 "sulphur, a net steam exporter.")
    d.reactions = [
        {"eq": "S + O2 -> SO2", "where": "Sulphur furnace", "dH_kJ": (core.h_molar("SO2", 298.15) - core.h_molar("S", 298.15, "l")) / 1000},
        {"eq": "SO2 + 1/2 O2 <=> SO3", "where": "Converter beds 1 to 4 (V2O5)", "dH_kJ": th.dh_rxn_gas(RXN) / 1000},
        {"eq": "SO3 + H2O -> H2SO4", "where": "Interpass and final absorbers",
         "dH_kJ": (core.h_molar("H2SO4", 298.15, "l") - core.h_molar("SO3", 298.15) - core.h_molar("H2O", 298.15, "l")) / 1000},
    ]
    d.conditions = [
        ("Sulphur furnace", f"{p['so2_pct']:.1f}% SO2, {T_f - 273.15:,.0f} C (adiabatic, solved)"),
        ("Converter", f"Beds 1 to 3 inlet {p['bed_inlet_C']:.0f} C, bed 4 inlet {p['bed4_inlet_C']:.0f} C, "
                      f"{appr:.0f} K approach to equilibrium"),
        ("Bed outlet temperatures", f"{T1 - 273.15:.0f}, {T2 - 273.15:.0f}, {T3 - 273.15:.0f}, {T4 - 273.15:.0f} C"),
        ("Absorbers", f"{p['acid_wt_pct']:.1f}% acid, gas in at 180 C, out at 80 C"),
    ]

    # ---- streams
    s_s = d.stream("Molten sulphur", {"S": S}, 413.15, 3, phase="l")
    s_air = d.stream("Ambient air", {**{c: air * x for c, x in AIR.items()}, "H2O": w_air}, 293.15, 1.0)
    s_w = d.stream("Process water", {"H2O": w_mk}, 298.15, 3, phase="l")
    s_dry = d.stream("Dried air", dry_air, T_air, P1)
    s_bg = d.stream("Furnace gas", burner, T_f, P1 - 0.02)
    s_b3 = d.stream("Bed 3 outlet", b3, T3, P1 - 0.15)
    s_g4 = d.stream("Gas from interpass absorber", g4, 353.15, P1 - 0.2)
    s_b4 = d.stream("Bed 4 outlet", b4, T4, P1 - 0.25)
    s_stack = d.stream("Stack gas", stack, 353.15, 1.02)
    s_acid = d.stream("Sulphuric acid", acid, 313.15, 3, phase="l")

    d.feed(s_s, {"S": "S"})
    d.feed(s_air)
    d.feed(s_w)
    d.out(s_acid, "product", {"H2SO4": "H2SO4"})
    d.out(s_stack, "emission")

    d.unit("C-101", "Air drying tower and blower", "column", [s_air], [s_dry], (0, 0), power_kW=W_bl)
    d.unit("F-101", "Sulphur furnace and waste heat boiler", "furnace", [s_s, s_dry], [s_bg], (1, 0), duty_kW=-Q_whb)
    d.unit("R-101", "Converter beds 1 to 3", "reactor", [s_bg], [s_b3], (2, 0), duty_kW=-(Q_b1 + Q_b2 + Q_b3))
    d.unit("C-102", "Interpass absorber", "column", [s_b3, s_w], [s_g4], (3, 0))
    d.unit("R-102", "Converter bed 4", "reactor", [s_g4], [s_b4], (4, 0), duty_kW=-Q_b4)
    d.unit("C-103", "Final absorber", "column", [s_b4], [s_stack, s_acid], (5, 0), duty_kW=-Q_cw)

    # ---- utilities
    d.steam(-steam_kg_h * 0.97, "40 bar steam export (3% to sulphur melting and tracing)")
    d.cooling(Q_cw, "Absorber and acid coolers")
    d.demin_water_m3_h = steam_kg_h * 1.03 / 1000
    acid_kg_h = sum(n * th.MW(c) for c, n in acid.items())
    circ_kg_h = (so3_ipa + b4["SO3"]) * th.MW("SO3") * 25  # acid circulation about 25 kg per kg SO3
    d.pump("P-101", "Acid circulation pumps", circ_kg_h, 1830, 4, material="SS")
    d.pump("P-102", "Boiler feed water pump", steam_kg_h, 950, 45)
    d.pump("P-103", "Sulphur pump", S * MWs, 1790, 6)

    # ---- equipment
    d.generic("K-101", "Main air blower", "compressor", W_bl, f"{W_bl:,.0f} kW, dP {p['blower_dP_bar']:.2f} bar",
              note="Centrifugal blower, costed on the compressor curve")
    Vf = core.gas_volume_m3_h(sum(burner.values()), T_f, P1) / 3600
    d.vessel("F-101", "Sulphur furnace (brick lined)", Vf * 2.0, P_barg=P1 - 1, orientation="horizontal")
    d.hx("E-101", "Waste heat boiler", Q_whb, T_f, Tin, 523.15, 523.15, "boiler", P_barg=40)
    d.hx("E-102", "Superheater after bed 1", Q_b1, T1, Tin, 523.15, 723.15, "gas-steam", P_barg=40)
    d.hx("E-103", "Hot interpass exchanger after bed 2", Q_b2, T2, Tin, 353.15, 653.15, "gas-gas", P_barg=P1 - 1)
    d.hx("E-104", "Cold interpass exchanger and economiser after bed 3", Q_b3, T3, 453.15, 378.15, 503.15, "gas-water", P_barg=45)
    d.hx("E-105", "Economiser after bed 4", Q_b4, T4, 453.15, 378.15, 503.15, "gas-water", P_barg=45)
    gas_kmol = sum(burner.values())
    for tag, name, n in (("R-101", "Converter bed 1", gas_kmol), ("R-102", "Converter bed 2", gas_kmol),
                         ("R-103", "Converter bed 3", gas_kmol), ("R-104", "Converter bed 4", sum(g4.values()))):
        d.reactor_bed(tag, f"{name} (V2O5 catalyst)", n, 1500, P1 - 1, material="SS")
    d.column("C-101", "Air drying tower", air, 313.15, P1, 4, 29.0, packed=True)
    d.column("C-102", "Interpass absorption tower", sum(b3.values()), 353.15, P1 - 0.15, 4, 30.0, packed=True)
    d.column("C-103", "Final absorption tower", sum(b4.values()), 353.15, 1.05, 4, 29.5, packed=True)
    d.cooler_cw("E-106", "Acid coolers (plate, Hastelloy)", Q_cw, 373.15, 313.15, material="SS", service="liquid-water")
    d.tank("TK-101", "Sulphuric acid tank", acid_kg_h, 1830, days=14)
    d.tank("TK-102", "Molten sulphur pit", S * MWs, 1790, days=7)
    d.vessel("V-101", "Steam drum", max(5.0, steam_kg_h / 1000 * 0.5), P_barg=40, orientation="horizontal")

    # ---- KPIs
    s_t = S * MWs / (t_h * 1000)
    steam_t = steam_kg_h * 0.97 / (t_h * 1000)
    export_MJ_t = (steam_kg_h * 0.97 * h_net / 1000 - d.power_kW * 3.6) / t_h
    so2_kg_t = stack["SO2"] * th.MW("SO2") / t_h
    d.kpis = [
        {"label": "Sulphur consumption", "value": s_t, "unit": "t/t H2SO4"},
        {"label": "Overall SO2 conversion", "value": conv, "unit": "%"},
        {"label": "Conversion before interpass absorption", "value": conv3, "unit": "%"},
        {"label": "Furnace temperature", "value": T_f - 273.15, "unit": "C"},
        {"label": "Steam export (40 bar, 450 C)", "value": steam_t, "unit": "t/t H2SO4"},
        {"label": "Net energy export (steam less power)", "value": export_MJ_t, "unit": "MJ/t H2SO4"},
        {"label": "Share of reaction heat to HP steam", "value": share, "unit": "%"},
        {"label": "SO2 to air", "value": so2_kg_t, "unit": "kg/t H2SO4"},
    ]

    # ---- validation (benchmarks.json, sulphuric_acid)
    d.check("Overall SO2 conversion, double absorption", conv, [99.2, 99.6], "%",
            SRC3 + ", appendix A2: sulphur burning, double absorption", BOOKLET3, tol=1,
            note="Equilibrium beds give an upper bound; the booklet range is for plants of the late 1990s.")
    d.check("Net energy export", export_MJ_t, 2500, "MJ/t",
            SRC3 + ", appendix A2: net balance, sulphur burning", BOOKLET3, tol=25, kind="energy",
            note="Model counts 40 bar steam less blower and pump power; low grade absorber heat is not recovered. "
                 "The same booklet puts 57 to 62% of the input heat into 31 bar steam (checked below), which is "
                 "about 3,200 MJ/t on its own, so the 2,500 MJ/t net figure uses a basis the booklet does not state.")
    d.check("Share of reaction heat recovered as HP steam", share, [57, 62], "%",
            SRC3 + ", appendix A8: Bayer 625 t/d plant, 31 bar steam", BOOKLET3, tol=5, kind="energy",
            note="Booklet basis: sulphur heat plus blower power in, 1.6% shell losses.")
    d.check("Double absorption conversion (general statement)", conv, [99.0, 99.6], "%",
            SRC3 + ", section 4: double absorption gives 99 to 99.6%", BOOKLET3, tol=1)

    d.assumptions = [
        "Each converter bed reaches equilibrium for SO2 + 1/2 O2 = SO3 evaluated "
        f"{appr:.0f} K above its adiabatic outlet temperature (ideal gas, components.json Gibbs data).",
        f"Furnace gas {p['so2_pct']:.1f}% SO2 (booklet sulphur burning range 6 to 12%). Air is dried to nil water; "
        "the removed water ends up in the product acid.",
        "All gas cooling down to 180 C raises 40 bar 450 C steam, less the reheat of the interpass gas from 80 C. "
        "3% of the steam is used to keep sulphur molten. Low grade absorber heat goes to cooling water.",
        "SO3 is fully absorbed; the stack carries only the unconverted SO2.",
        "Blower polytropic efficiency 0.80. Catalyst beds sized at a GHSV of 1,500 per h.",
    ]
    d.hazop = [
        {"node": "Sulphur furnace", "deviation": "Sulphur fire or H2S in pit", "cause": "Leaks, sulphur degassing",
         "consequence": "SO2 release, H2S toxicity and explosion in the pit", "safeguard": "Pit ventilation, H2S detectors, steam snuffing"},
        {"node": "Waste heat boiler", "deviation": "Tube leak", "cause": "Corrosion, low water level",
         "consequence": "Water into SO3 gas makes acid, severe corrosion downstream", "safeguard": "Level trips, conductivity monitoring"},
        {"node": "Converter", "deviation": "High bed temperature", "cause": "High SO2 strength",
         "consequence": "Catalyst damage above 630 C, high emissions", "safeguard": "SO2 analyser, bed thermocouples, furnace trip"},
        {"node": "Absorbers", "deviation": "Low acid strength", "cause": "Water dosing fault",
         "consequence": "Acid mist from the stack, fast corrosion", "safeguard": "Strength analysers, candle filters"},
        {"node": "Acid tanks and pumps", "deviation": "Loss of containment", "cause": "Corrosion, gasket failure",
         "consequence": "Severe burns, reaction with water", "safeguard": "Bunds, shields on flanges, PPE"},
    ]
    d.greener = {
        "title": "Already a net energy source",
        "text": "Sulphur burning gives off no CO2 and the plant exports steam. Recovering the absorber heat as low "
                "pressure steam (heat recovery systems) adds roughly another third to the export.",
        "electricity_MWh_per_t": 0.0,
    }
    return d.finish()
