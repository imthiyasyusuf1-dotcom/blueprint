"""Hydrogen from natural gas: steam methane reforming + HT shift + PSA.

Reformer and shift outlets are ideal gas chemical equilibria computed from
NIST/chemicals formation data. The PSA recovers a set fraction of the hydrogen
as pure product; its tail gas is burnt in the reformer furnace and natural gas
trim fuel makes up the rest of the fired duty. The steam system is balanced
from the computed heat duties and surplus steam is exported.
"""
from .. import core
from .. import thermo as th
from ..design import Design

SMR = {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3}
WGS = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}
AIR = {"N2": 0.7808, "O2": 0.2095, "Ar": 0.0093}

DEFAULTS = {
    "capacity_tpd": 100.0,
    "steam_to_carbon": 2.6,
    "reformer_T_C": 870.0,
    "reform_P_bar": 28.0,
    "hts_in_C": 350.0,
    "psa_recovery_pct": 89.0,
    "excess_air_pct": 10.0,
    "radiant_exit_C": 1000.0,
    "stack_C": 160.0,
    "air_preheat_C": 250.0,
}

_hin = core.hin
NM3_KMOL = 22.414  # Nm3 per kmol (0 C, 1 atm)


def front_end(F_CH4, p):
    S = {}
    Pr = p["reform_P_bar"]
    feed = {"CH4": F_CH4}
    steam = {"H2O": F_CH4 * p["steam_to_carbon"]}
    mix = core.add(feed, steam)
    T_mix = 893.15  # mixed feed preheated to 620 C in the convection section
    T1 = p["reformer_T_C"] + 273.15
    ref, _ = core.equilibrium(mix, [SMR, WGS], T1, Pr)
    Q_ref = _hin(ref, T1) - _hin(mix, T_mix)
    Q_pre = _hin(mix, T_mix) - (_hin(feed, 298.15) + _hin(steam, 523.15))
    S.update(feed=feed, steam=steam, mix=mix, T_mix=T_mix, ref=ref, T1=T1, Q_ref=Q_ref, Q_pre=Q_pre)

    # process gas boiler down to the HT shift inlet, adiabatic HT shift
    T_in = p["hts_in_C"] + 273.15
    Q_pgb = _hin(ref, T1) - _hin(ref, T_in)
    T_hts, hts = core.adiabatic_eq(ref, _hin(ref, T_in), [WGS], Pr - 1, T_in, T_in + 200)
    # shift effluent: heat above 150 C goes to BFW preheat and steam, the rest to cooling water
    Q_hts_hi = _hin(hts, T_hts) - _hin(hts, 423.15)
    S.update(T_in=T_in, Q_pgb=Q_pgb, T_hts=T_hts, hts=hts, Q_hts_hi=Q_hts_hi)

    # cool to 40 C, knock out condensate; PSA feed saturated with water at 40 C
    P_psa = Pr - 3
    dry = {c: n for c, n in hts.items() if c != "H2O"}
    y_w = core.psat("H2O", 313.15) / P_psa
    w_vap = y_w / (1 - y_w) * sum(dry.values())
    cond = {"H2O": hts["H2O"] - w_vap}
    gas40 = core.add(dry, {"H2O": w_vap})
    Q_lo = _hin(hts, 423.15) - (_hin(gas40, 313.15) + sum(n * core.h_molar(c, 313.15, "l") for c, n in cond.items()) / 3600.0)
    S.update(P_psa=P_psa, cond=cond, gas40=gas40, Q_lo=Q_lo)

    rec = p["psa_recovery_pct"] / 100.0
    h2 = {"H2": gas40["H2"] * rec}
    tail = dict(gas40)
    tail["H2"] -= h2["H2"]
    S.update(h2=h2, tail=tail)
    return S


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    target_kmol = p["capacity_tpd"] * 1000 / 24 / th.MW("H2")

    # everything is linear in the feed, so one rescale hits the capacity exactly
    F = target_kmol / 3.0
    for _ in range(2):
        fe = front_end(F, p)
        F *= target_kmol / fe["h2"]["H2"]
    fe = front_end(F, p)
    Pr = p["reform_P_bar"]

    d = Design("hydrogen", "Hydrogen plant (steam methane reforming, PSA)", "Hydrogen", p["capacity_tpd"], region)
    d.route = ("Natural gas is desulphurised, mixed with steam and reformed over nickel catalyst in a fired tubular "
               "reformer. A high-temperature shift converts most of the CO to more hydrogen, the gas is cooled and "
               "dried, and a pressure swing adsorption unit delivers 99.9%+ hydrogen. PSA tail gas fuels the reformer.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d of 99.9%+ hydrogen from natural gas, the grey hydrogen route used "
                 "by refineries and merchant gas suppliers. No carbon capture.")
    d.reactions = [
        {"eq": "CH4 + H2O <=> CO + 3 H2", "where": "Reformer tubes (Ni)", "dH_kJ": th.dh_rxn_gas(SMR) / 1000},
        {"eq": "CO + H2O <=> CO2 + H2", "where": "Reformer and HT shift (Fe-Cr)", "dH_kJ": th.dh_rxn_gas(WGS) / 1000},
        {"eq": "CH4 + 2 O2 -> CO2 + 2 H2O", "where": "Reformer furnace burners", "dH_kJ": th.dh_rxn_gas({"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}) / 1000},
    ]
    ch4_conv = 1 - fe["ref"]["CH4"] / fe["feed"]["CH4"]
    d.conditions = [
        ("Steam to carbon ratio", f"{p['steam_to_carbon']:.2f} mol/mol"),
        ("Reformer outlet", f"{p['reformer_T_C']:.0f} C, {Pr:.0f} bar, CH4 conversion {ch4_conv * 100:.1f}% (equilibrium)"),
        ("HT shift", f"inlet {p['hts_in_C']:.0f} C, outlet {fe['T_hts'] - 273.15:.0f} C (adiabatic, solved)"),
        ("PSA", f"{fe['P_psa']:.0f} bar feed, {p['psa_recovery_pct']:.0f}% H2 recovery, tail gas at 1.3 bar"),
    ]

    # ---- streams
    s_ng = d.stream("Natural gas feed", fe["feed"], 298.15, Pr + 4)
    s_st = d.stream("Process steam", fe["steam"], 523.15, Pr + 4)
    s_mix = d.stream("Reformer feed", fe["mix"], fe["T_mix"], Pr + 2)
    s_ref = d.stream("Reformed gas", fe["ref"], fe["T1"], Pr)
    s_cg = d.stream("Cooled reformed gas", fe["ref"], fe["T_in"], Pr - 0.5)
    s_hts = d.stream("HT shift outlet", fe["hts"], fe["T_hts"], Pr - 1)
    s_cool = d.stream("Cooled shifted gas", fe["hts"], 313.15, fe["P_psa"], phases={"H2O": "l"})
    s_cond = d.stream("Process condensate", fe["cond"], 313.15, fe["P_psa"], phase="l")
    s_psa = d.stream("PSA feed", fe["gas40"], 313.15, fe["P_psa"])
    s_h2 = d.stream("Hydrogen product", fe["h2"], 313.15, fe["P_psa"] - 0.5)
    s_tail = d.stream("PSA tail gas to burners", fe["tail"], 303.15, 1.3)

    d.feed(s_ng)  # natural gas is costed as a utility at the regional gas price
    d.feed(s_st)
    d.out(s_h2, "product", {"H2": "H2_grey"})
    d.out(s_cond, "waste", treat_usd_t=1.0)
    d.out(s_tail, "fuel")

    d.unit("D-101", "Desulphuriser", "reactor", [s_ng], [], (0, 0), desc="Hydrotreater and ZnO bed protect the reformer catalyst")
    d.unit("H-101", "Steam reformer", "furnace", [s_mix, s_tail], [s_ref], (1, 0), duty_kW=fe["Q_ref"],
           desc="Ni catalyst in fired tubes, tail gas plus trim gas burners")
    d.unit("E-101", "Process gas boiler", "exchanger", [s_ref], [s_cg], (2, 0), duty_kW=-fe["Q_pgb"])
    d.unit("R-101", "HT shift converter", "reactor", [s_cg], [s_hts], (3, 0), desc="Fe-Cr catalyst")
    d.unit("E-102", "Shift effluent coolers", "exchanger", [s_hts], [s_cool], (4, 0),
           duty_kW=-(fe["Q_hts_hi"] + fe["Q_lo"]))
    d.unit("V-101", "Condensate separator", "drum", [s_cool], [s_psa, s_cond], (4, 1))
    d.unit("A-101", "PSA unit", "column", [s_psa], [s_h2, s_tail], (3, 1), desc="Multi bed adsorption, 99.9%+ H2")
    s_st.dst, s_mix.src = "mix", "D-101"

    # ---- fuel and heat balance
    # Radiant box: all PSA tail gas plus trim natural gas burn with excess air (air at 25 C); the flue gas leaves
    # the box at radiant_exit_C, having given the reformer tubes their duty. Trim gas is solved from that balance.
    # The convection section then cools the flue gas to the stack, preheating the mixed feed, then raising and
    # superheating 40 bar steam.
    tail = fe["tail"]
    tail_GJ_h = sum(n * (th.lhv_molar(c) or 0) for c, n in tail.items()) / 1e6
    tail_C = tail.get("CH4", 0) + tail.get("CO", 0) + tail.get("CO2", 0)
    T_rad, T_stack = p["radiant_exit_C"] + 273.15, p["stack_C"] + 273.15
    xs = 1 + p["excess_air_pct"] / 100
    T_air = p["air_preheat_C"] + 273.15

    def burn(trim):
        fuel = core.add(tail, {"CH4": trim})
        o2 = 2 * fuel.get("CH4", 0) + 0.5 * fuel.get("CO", 0) + 0.5 * fuel.get("H2", 0)
        air = {c: o2 * xs / AIR["O2"] * x for c, x in AIR.items()}
        flue = core.add(air, {c: n for c, n in fuel.items() if c not in ("CH4", "CO", "H2")})
        flue["O2"] -= o2
        flue["CO2"] = flue.get("CO2", 0) + fuel.get("CH4", 0) + fuel.get("CO", 0)
        flue["H2O"] = flue.get("H2O", 0) + 2 * fuel.get("CH4", 0) + fuel.get("H2", 0)
        H_in = _hin(tail, 298.15) + _hin(air, T_air) + _hin({"CH4": trim}, 298.15)
        return H_in - _hin(flue, T_rad), flue, air

    lo, hi = 0.0, fe["feed"]["CH4"] * 2
    if burn(0.0)[0] >= fe["Q_ref"]:
        hi = 0.0
    for _ in range(80):
        if hi - lo < 1e-6:
            break
        mid = (lo + hi) / 2
        if burn(mid)[0] < fe["Q_ref"]:
            lo = mid
        else:
            hi = mid
    trim_kmol = hi
    _, flue, air = burn(trim_kmol)
    Q_rad = burn(trim_kmol)[0]
    trim_GJ_h = trim_kmol * th.lhv_molar("CH4") / 1e6
    fired_GJ_h = tail_GJ_h + trim_GJ_h
    Q_conv = _hin(flue, T_rad) - _hin(flue, T_stack)
    d.fuel_credit(tail_GJ_h, "PSA tail gas burnt in reformer", co2_kg_h=tail_C * th.MW("CO2"))
    d.fuel(fired_GJ_h, "Reformer furnace (tail gas plus trim gas)")
    feed_GJ_h = fe["feed"]["CH4"] * th.lhv_molar("CH4") / 1e6
    d.fuel(feed_GJ_h, "Natural gas feedstock", co2=False)  # feed carbon leaves in the tail gas flue (counted above)

    air_kmol = sum(air.values())
    air_m3_s = core.gas_volume_m3_h(air_kmol, 298.15, 1.013) / 3600
    fan_kW = air_m3_s * 0.05e5 / 0.70 / 1000  # 50 mbar, 70% efficient
    d.generic("K-101", "Combustion air fan", "fan", min(air_m3_s, 100), f"{air_m3_s:,.1f} m3/s, 50 mbar")
    d.power(fan_kW, "Combustion air fan")
    flue_kmol = sum(flue.values())
    fid_m3_s = core.gas_volume_m3_h(flue_kmol, T_stack, 1.013) / 3600
    d.generic("K-102", "Flue gas fan", "fan", min(fid_m3_s, 100), f"{fid_m3_s:,.1f} m3/s, 50 mbar")
    d.power(fid_m3_s * 0.05e5 / 0.70 / 1000, "Flue gas fan")

    hs = th.H_STEAM_40BAR_450C - th.H_BFW_105C
    Q_aph = _hin(air, T_air) - _hin(air, 298.15)
    Q_conv_steam = Q_conv - fe["Q_pre"] - Q_aph
    steam_raised = (fe["Q_pgb"] + fe["Q_hts_hi"] * 0.85 + Q_conv_steam) / hs * 3600  # kg/h
    d.steam(-steam_raised, "Process gas boiler, shift cooler and convection section (40 bar steam)")
    proc_steam = fe["steam"]["H2O"] * th.MW("H2O")
    d.steam(proc_steam, "Process steam to reformer")
    d.cooling(fe["Q_hts_hi"] * 0.15)
    cond_t_h = fe["cond"]["H2O"] * th.MW("H2O") / 1000
    d.demin_water_m3_h = max(0.0, steam_raised / 1000 * 0.03 + proc_steam / 1000 - cond_t_h)
    d.pump("P-101", "Boiler feed water pump", steam_raised, 950, 45)
    net = d.steam_import_kg_h - d.steam_export_kg_h
    if net > 0:
        d.fuel(net * hs / 0.90 / 1e6, "Auxiliary boiler")
        d.steam(-net, "Auxiliary boiler")
    export_kg_h = max(0.0, -net)
    eff_fired = (Q_rad + Q_conv - Q_aph) / (fired_GJ_h * 1e6 / 3600) * 100

    # ---- equipment
    d.reactor_bed("D-101", "Desulphuriser (ZnO)", fe["feed"]["CH4"], 1500, Pr + 3)
    d.heater("H-101", "Steam reformer", fe["Q_ref"] + fe["Q_pre"], P_barg=Pr + 1, kind="reformer")
    d.hx("E-101", "Process gas boiler", fe["Q_pgb"], fe["T1"], fe["T_in"], 523.15, 530.0, "boiler", P_barg=40)
    d.reactor_bed("R-101", "HT shift converter", sum(fe["ref"].values()), 3000, Pr - 1)
    d.hx("E-102", "Shift effluent BFW preheater", fe["Q_hts_hi"], fe["T_hts"], 423.15, 378.15, 503.15, "gas-water", P_barg=45)
    d.cooler_cw("E-103", "Final gas cooler", fe["Q_lo"], 423.15, 313.15, P_barg=Pr, service="wet-gas")
    d.flash_drum("V-101", "Process condensate separator", s_psa, fe["cond"]["H2O"] * 18, fe["P_psa"])
    # PSA: ten adsorber beds; adsorbent volume from a gas hourly space velocity of 1,000 per h, costed per bed
    psa = d.reactor_bed("A-101", "PSA adsorber vessels (10 beds)", sum(fe["gas40"].values()) / 10, 1000, fe["P_psa"])
    psa["service"] = f"10 x {psa['catalyst_m3']:,.1f} m3 adsorbent"
    for k in ("purchased", "bare_module", "bare_module_base"):
        psa[k] *= 10
    # convection section coils and steam system
    T_flue = T_rad
    d.hx("E-104", "Convection coil, mixed feed preheat", fe["Q_pre"], T_flue, 1073.15, 523.15, fe["T_mix"], "gas-gas",
         P_barg=Pr + 2, material="SS")
    h40 = th.H_STEAM_40BAR_450C
    Q_sh = steam_raised * (h40 - 2801.0) / 3600  # 40 bar saturated vapour 2801 kJ/kg (IAPWS-97) to 450 C
    d.hx("E-105", "Convection coil, steam superheater", Q_sh, 1073.15, 873.15, 523.15, 723.15, "gas-steam", P_barg=40)
    d.vessel("V-103", "Steam drum", max(5.0, steam_raised / 1000 * 0.5), P_barg=40, orientation="horizontal")
    d.vessel("V-104", "Deaerator", max(5.0, steam_raised / 1000 * 0.3), P_barg=1.5, orientation="horizontal")
    d.vessel("V-102", "PSA tail gas surge drum", max(10.0, core.gas_volume_m3_h(sum(tail.values()), 303.15, 1.3) / 60), 1.0)
    d.tank("TK-101", "Boiler feed water tank", steam_raised, 950, days=0.5)

    # ---- KPIs
    h2_kg_h = fe["h2"]["H2"] * th.MW("H2")
    h2_Nm3_h = fe["h2"]["H2"] * NM3_KMOL
    ng_GJ_h = d.gas_net_GJ_h
    ng_MJ_Nm3 = ng_GJ_h * 1000 / h2_Nm3_h
    co2_kg_kg = d.direct_co2_kg_h / h2_kg_h
    steam_MJ_kg = export_kg_h * hs / 1000 / h2_kg_h
    eff = h2_kg_h * th.lhv_mass("H2") / 1000 / ng_GJ_h * 100 if ng_GJ_h else 0
    co_slip = fe["hts"]["CO"] / sum(v for c, v in fe["hts"].items() if c != "H2O") * 100
    d.kpis = [
        {"label": "Natural gas, feed + fuel", "value": ng_GJ_h / (h2_kg_h / 1000), "unit": "GJ(LHV)/t H2"},
        {"label": "Natural gas per Nm3 H2", "value": ng_MJ_Nm3, "unit": "MJ(LHV)/Nm3"},
        {"label": "Cold gas efficiency (H2 LHV / gas LHV)", "value": eff, "unit": "%"},
        {"label": "Methane conversion in reformer", "value": ch4_conv * 100, "unit": "%"},
        {"label": "CO after HT shift (dry)", "value": co_slip, "unit": "mol%"},
        {"label": "PSA hydrogen recovery", "value": p["psa_recovery_pct"], "unit": "%"},
        {"label": "Direct CO2", "value": co2_kg_kg, "unit": "kg/kg H2"},
        {"label": "Net export steam (40 bar, 450 C)", "value": export_kg_h / h2_kg_h, "unit": "kg/kg H2"},
        {"label": "Furnace thermal efficiency (to stack)", "value": eff_fired, "unit": "% of fired LHV"},
    ]

    # ---- validation
    IEAGHG = ("https://ieaghg.org/publications/2017-02%20Techno%20-%20Economic%20Evaluation%20of%20SMR%20Based%20"
              "Standalone%20(Merchant)%20Hydrogen%20Plant%20with%20CCS.pdf")
    IEA = "https://iea.blob.core.windows.net/assets/9e3a3493-b9a6-4b7d-b499-7ca48e357561/The_Future_of_Hydrogen.pdf"
    NETL = ("https://netl.doe.gov/projects/files/ComparisonofCommercialStateofArtFossilBasedHydrogenProduction"
            "Technologies_041222.pdf")
    d.check("Natural gas, feed + fuel, per Nm3 H2", ng_MJ_Nm3, 14.212, "MJ(LHV)/Nm3 H2",
            "IEAGHG Technical Report 2017/02, base case without CCS, Table 2", IEAGHG, tol=10)
    d.check("Direct CO2 per Nm3 H2", d.direct_co2_kg_h / h2_Nm3_h, 0.8091, "kg CO2/Nm3 H2",
            "IEAGHG Technical Report 2017/02, base case without CCS", IEAGHG, tol=10)
    d.check("Stack CO2 per kg H2", co2_kg_kg, 9.3, "kg CO2/kg H2",
            "NETL 2022, Comparison of fossil hydrogen technologies, Case 1 SMR without capture", NETL, tol=15)
    d.check("Methane conversion in the reformer", ch4_conv * 100, 77, "%",
            "NETL 2022, Case 1: S/C 2.56, 870 C, 2.8 MPa, 'more than 77 percent'", NETL, tol=10, kind="thermo",
            note="Published figure is a lower bound at nearly the same conditions as the default.")
    d.check("Export steam energy", steam_MJ_kg, 26, "MJ/kg H2",
            "NETL 2022, Case 1 modelled steam output 514 GJ/h", NETL, tol=50,
            note="NETL exports superheated steam from a plant about 4.8 times this size; steam conditions differ.")
    # capital: IEA 2019, USD 500 to 900 per kW H2 (LHV) in 2018, escalated CEPCI 603.1 (2018) to 800.0
    kw_h2 = h2_kg_h * th.lhv_mass("H2") / 3.6
    capex_pub = [500 * kw_h2 * 800.0 / 603.1, 900 * kw_h2 * 800.0 / 603.1]
    d.check("Fixed capital vs published range", None, capex_pub, "USD (2024)",
            "IEA, The Future of Hydrogen (2019): SMR without CCUS USD 500 to 900 per kW H2 (2018). "
            "Escalated with CEPCI 603.1 (2018) to 800.0", IEA, tol=50, kind="capex",
            note="Factored Turton estimate; the PSA is costed as adsorber vessels only, not as a vendor package.")

    d.assumptions = [
        "Natural gas is modelled as pure methane, already desulphurised. Gas is available at reformer pressure.",
        "Reformer and HT shift reach ideal gas chemical equilibrium. Defaults follow NETL 2022 Case 1 "
        "(S/C 2.56, 870 C, 2.8 MPa), rounded.",
        f"PSA recovers {p['psa_recovery_pct']:.0f}% of the hydrogen fed (IEAGHG 2017/02 quotes 85 to 90%) as pure "
        "product; all other species and the remaining hydrogen leave in the tail gas.",
        f"Furnace: tail gas plus trim gas with {p['excess_air_pct']:.0f}% excess air (combustion air preheated to {p['air_preheat_C']:.0f} C against flue gas at the cold end). "
        f"Flue gas leaves the radiant box at {p['radiant_exit_C']:.0f} C and the stack at {p['stack_C']:.0f} C; "
        "trim gas is solved so the radiant heat equals the reformer duty. No casing losses. Fans 50 mbar, 70%.",
        "Convection section preheats the mixed feed to 620 C and raises 40 bar steam with the rest. Heat from the "
        "reformed gas down to the shift inlet and 85% of the shift effluent heat above 150 C also raise steam. "
        "Steam left after the process steam is exported.",
        "PSA adsorber vessels sized at a gas hourly space velocity of 1,000 per hour (ten beds as one item).",
        "No CO2 capture: all feed and fuel carbon leaves in the reformer flue gas.",
    ]
    d.hazop = [
        {"node": "Steam reformer", "deviation": "Low steam flow", "cause": "Steam valve failure, BFW pump trip",
         "consequence": "Carbon on catalyst, tube overheating and rupture, fire",
         "safeguard": "Low steam to carbon trip, tube skin thermocouples, burner management system"},
        {"node": "Reformer furnace", "deviation": "Loss of tail gas flow", "cause": "PSA valve sequence fault",
         "consequence": "Flame out then fuel rich relight, firebox explosion",
         "safeguard": "Flame scanners, fuel gas trip, purge before relight"},
        {"node": "HT shift converter", "deviation": "High temperature", "cause": "Low steam, high CO in feed",
         "consequence": "Catalyst sintering, vessel overheating", "safeguard": "Bed thermocouples and high-temperature trip"},
        {"node": "PSA unit", "deviation": "Valve fails open", "cause": "Valve or controller failure",
         "consequence": "Impure hydrogen to users, overpressure of tail gas system",
         "safeguard": "Online H2 purity analyser, relief on tail gas drum, valve position monitoring"},
        {"node": "Hydrogen product line", "deviation": "Loss of containment", "cause": "Flange leak, hydrogen attack",
         "consequence": "Jet fire or vapour cloud explosion", "safeguard": "Gas detection, Nelson curve material "
         "selection, emergency shutdown and depressurising"},
    ]
    d.greener = {
        "title": "Electrolytic hydrogen or SMR with capture",
        "text": "Water electrolysis on low carbon power removes the reformer entirely; IRENA puts system use at 50 to "
                "83 kWh per kg H2. Adding capture to this SMR would take out the concentrated shift CO2 (about half the "
                "total) cheaply, but flue gas capture is needed to get above roughly 90%.",
        "electricity_MWh_per_t": 52.5,
    }
    return d.finish()
