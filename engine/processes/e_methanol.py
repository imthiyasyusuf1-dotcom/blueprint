"""e-Methanol: captured CO2 + electrolytic hydrogen in a low pressure Cu/ZnO synthesis loop.

Green hydrogen and a concentrated CO2 stream are bought over the fence, compressed and fed to the
same boiling water converter loop as the natural gas plant. The converter outlet is a solved ideal
gas equilibrium of CO2 hydrogenation and reverse water gas shift; the recycle, purge and crude
condensation (Raoult's law) are converged numerically with the methanol module's loop solver.
The crude is about half water, so the column reboiler is the main heat user; the converter's boiling
water steam covers most of it. Electrolysis sits outside the fence: the hydrogen is priced at the
green hydrogen market price and its electricity is shown as a KPI, not in the plant power.
"""
from .. import core
from .. import thermo as th
from .. import cost as C
from ..design import Design
from .methanol import loop

CO2_HYD = {"CO2": -1, "H2": -3, "MeOH": 1, "H2O": 1}
MEOH_CO = {"CO": -1, "H2": -2, "MeOH": 1}
WGS = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}

DEFAULTS = {
    "capacity_tpd": 300.0,
    "loop_P_bar": 80.0,
    "converter_T_C": 250.0,
    "approach_C": 10.0,
    "recycle_ratio": 5.0,
    "h2_supply_P_bar": 30.0,
    "co2_supply_P_bar": 1.5,
    "reflux_ratio": 1.5,
    "electrolyser_kwh_kg_h2": 50.0,
    "boiler_eff": 0.9,
}

hin = core.hin
IRENA = "https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2021/Jan/IRENA_Innovation_Renewable_Methanol_2021.pdf"
IRS = "IRENA and Methanol Institute, Innovation Outlook: Renewable Methanol (2021)"


def _solve(p, target):
    H = target * 3.3
    for _ in range(4):
        mk = {"H2": H, "CO2": H / 3.0}
        lp = loop(mk, p)
        H *= target / (lp["liq"]["MeOH"] * 0.995)
    mk = {"H2": H, "CO2": H / 3.0}
    return mk, loop(mk, p)


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    target = p["capacity_tpd"] * 1000 / 24 / th.MW("MeOH")
    mk, lp = _solve(p, target)
    PL = p["loop_P_bar"]
    T = lp["T"]

    crude = lp["liq"]
    meoh_prod = crude["MeOH"] * 0.995
    product = {"MeOH": meoh_prod, "H2O": meoh_prod * 0.0005}
    bottoms = {"H2O": crude.get("H2O", 0) - product["H2O"], "MeOH": crude["MeOH"] - meoh_prod}
    dissolved = {c: n for c, n in crude.items() if c not in ("MeOH", "H2O")}
    crude_liq = {"MeOH": crude["MeOH"], "H2O": crude.get("H2O", 0)}

    d = Design("e_methanol", "e-Methanol plant (CO2 + green hydrogen, low pressure synthesis)", "Methanol",
               p["capacity_tpd"], region)
    d.route = ("Electrolytic hydrogen and captured CO2 are compressed to loop pressure and converted on a copper "
               "zinc oxide catalyst in a boiling water reactor (CO2 + 3 H2 -> CH3OH + H2O). Unconverted gas is "
               "recycled, a small purge is burnt in the package boiler, and the crude methanol water mix is "
               "let down and distilled to AA grade.")
    d.summary = f"{p['capacity_tpd']:,.0f} t/d of AA grade e-methanol from CO2 and green hydrogen."
    d.reactions = [
        {"eq": "CO2 + 3 H2 <=> CH3OH + H2O", "where": "Methanol converter (Cu/ZnO)", "dH_kJ": th.dh_rxn_gas(CO2_HYD) / 1000},
        {"eq": "CO2 + H2 <=> CO + H2O", "where": "Methanol converter (reverse shift)",
         "dH_kJ": -th.dh_rxn_gas(WGS) / 1000},
        {"eq": "CO + 2 H2 <=> CH3OH", "where": "Methanol converter (Cu/ZnO)", "dH_kJ": th.dh_rxn_gas(MEOH_CO) / 1000},
    ]
    out = lp["out"]
    co2_conv_pass = 1 - out["CO2"] / lp["cin"]["CO2"]
    co2_conv_overall = (crude["MeOH"]) / mk["CO2"]
    d.conditions = [
        ("Make up H2 / CO2 molar ratio", "3.0 (stoichiometric number 2.0)"),
        ("Synthesis loop", f"{PL:.0f} bar, converter {p['converter_T_C']:.0f} C, approach {p['approach_C']:.0f} K"),
        ("CO2 conversion per pass", f"{co2_conv_pass * 100:.1f}% (equilibrium limited)"),
        ("Recycle to make up ratio", f"{p['recycle_ratio']:.1f} (purge {lp['pf'] * 100:.2f}% of loop gas)"),
        ("Hydrogen supply", f"{p['h2_supply_P_bar']:.0f} bar from pressurised electrolysers"),
        ("CO2 supply", f"{p['co2_supply_P_bar']:.1f} bar, dry, from capture"),
        ("Distillation reflux ratio", f"{p['reflux_ratio']:.1f}"),
    ]

    s_h2 = d.stream("Green hydrogen", {"H2": mk["H2"]}, 313.15, p["h2_supply_P_bar"])
    s_co2 = d.stream("Captured CO2", {"CO2": mk["CO2"]}, 303.15, p["co2_supply_P_bar"])
    s_mk = d.stream("Compressed make up gas", mk, 313.15, PL)
    s_cin = d.stream("Converter feed", lp["cin"], 493.15, PL)
    s_out = d.stream("Converter outlet", out, T, PL - 2)
    s_rec = d.stream("Recycle gas", lp["rec"], 313.15, PL - 3)
    s_pg = d.stream("Purge gas to boiler", lp["purge"], 313.15, PL - 3)
    s_cr = d.stream("Crude methanol", crude, 313.15, PL - 3, phase="l")
    s_fl = d.stream("Let down gas to boiler", dissolved, 313.15, 5)
    s_crl = d.stream("Degassed crude methanol", crude_liq, 313.15, 5, phase="l")
    s_pr = d.stream("Methanol product", product, 313.15, 1.5, phase="l")
    s_bt = d.stream("Column bottoms water", bottoms, 373.15, 1.5, phase="l")

    d.feed(s_h2, {"H2": "H2_green"})
    d.feed(s_co2, {"CO2": "CO2"})
    d.out(s_pr, "product", {"MeOH": "MeOH"})
    d.out(s_bt, "waste", treat_usd_t=2.0)
    d.out(s_pg, "fuel")
    d.out(s_fl, "fuel")

    d.unit("C-101", "CO2 and hydrogen compressors", "compressor", [s_h2, s_co2], [s_mk], (0, 0))
    d.unit("R-101", "Methanol converter", "reactor", [s_mk, s_rec], [s_out], (1, 0),
           desc="Boiling water reactor, Cu/ZnO catalyst")
    d.unit("V-101", "Crude methanol separator", "drum", [s_out], [s_rec, s_pg, s_cr], (2, 0))
    d.unit("V-102", "Let down vessel", "drum", [s_cr], [s_fl, s_crl], (2, 1))
    d.unit("T-101", "Methanol distillation", "column", [s_crl], [s_pr, s_bt], (1, 1))
    s_cin.src, s_cin.dst = "mix", "R-101"

    # converter heat raises saturated steam (24 bar) in the boiling water reactor
    Q_rxn = hin(lp["cin"], T) - hin(out, T)
    steam_bwr = Q_rxn / (2801.5 - 441.2) * 3600
    d.steam(-steam_bwr, "Boiling water converter (saturated MP steam)")
    Q_fe = hin(lp["cin"], 493.15) - hin(lp["cin"], 313.15)
    T_after_fe = core.adiabatic_T(hin(out, T) - Q_fe, out, PL, 380)
    Q_crude_cool = (hin(out, T_after_fe) - (hin(lp["vap"], 313.15) +
                    sum(n * core.h_molar(c, 313.15, "l") for c, n in crude.items()) / 3600))
    # distillation: (R + 1) x distillate x latent heat, plus heating the water bottoms to 100 C
    hv = th.hvap("MeOH", 337.8)
    Q_reb = (p["reflux_ratio"] + 1) * meoh_prod * 1000 * hv / 3.6e6
    Q_reb += (sum(n * core.h_molar(c, 373.15, "l") for c, n in bottoms.items())
              - sum(n * core.h_molar(c, 313.15, "l") for c, n in bottoms.items())) / 3600
    d.steam(Q_reb / 2100.0 * 3600, "Distillation reboiler")
    d.cooling(Q_reb, "Column condenser")
    # purge and let down gas burnt in a package boiler that raises steam
    fuel = core.add(lp["purge"], dissolved)
    purge_GJ = sum(n * (th.lhv_molar(c) or 0) for c, n in fuel.items()) / 1e6
    purge_co2 = sum(fuel.get(c, 0) for c in ("CO", "CO2", "MeOH", "CH4")) * th.MW("CO2")
    d.fuel_credit(purge_GJ, "Purge and let down gas burnt in package boiler", co2_kg_h=purge_co2)
    hs_mp = th.H_STEAM_40BAR_450C - th.H_BFW_105C
    d.steam(-purge_GJ * 1e6 * p["boiler_eff"] / hs_mp, "Package boiler on purge gas")
    net = d.steam_import_kg_h - d.steam_export_kg_h
    if net > 0:
        d.fuel(net * hs_mp / p["boiler_eff"] / 1e6, "Auxiliary boiler (natural gas)")
        d.steam(-net, "Auxiliary boiler")

    # machines (electric drives: there is no high pressure steam on an e-methanol site)
    d.compressor("C-101", "CO2 compressor", core.Stream("x", "", {"CO2": mk["CO2"]}, 303.15, p["co2_supply_P_bar"]),
                 PL, k=1.29)
    d.compressor("C-102", "Hydrogen compressor", core.Stream("x", "", {"H2": mk["H2"]}, 313.15, p["h2_supply_P_bar"]),
                 PL, k=1.41)
    d.compressor("C-103", "Recycle circulator", core.Stream("x", "", lp["rec"], 313.15, PL - 3), PL + 2, stages=1)
    d.pump("P-101", "Methanol product pump", meoh_prod * th.MW("MeOH"), 790, 5)
    d.pump("P-102", "Column reflux and bottoms pumps", (p["reflux_ratio"] + 1) * meoh_prod * th.MW("MeOH"), 790, 4)

    # equipment
    d.reactor_bed("R-101", "Methanol converter (boiling water, multiple shells)", sum(lp["cin"].values()), 8000, PL)
    d.hx("E-101", "Loop feed / effluent exchanger", Q_fe, T, T_after_fe, 313.15, 493.15, "hp-gas", P_barg=PL)
    d.cooler_cw("E-102", "Crude methanol cooler / condenser", Q_crude_cool, T_after_fe, 313.15, P_barg=PL,
                service="wet-gas")
    d.flash_drum("V-101", "Crude methanol separator", core.Stream("x", "", lp["vap"], 313.15, PL - 3), 0, PL - 3)
    d.vessel("V-102", "Let down vessel", max(2.0, sum(crude.values()) * 0.03 * 0.25), P_barg=5)
    d.column("T-101", "Methanol refining column", (p["reflux_ratio"] + 1) * meoh_prod, 340, 1.5, 30, th.MW("MeOH"))
    d.hx("E-103", "Column reboiler", Q_reb, 433.15, 433.15, 373.15, 375.15, "reboiler", kind="hx_kettle")
    d.cooler_cw("E-104", "Column condenser", Q_reb, 338.15, 336.15, service="condenser")
    d.heater("B-101", "Package boiler on purge gas", purge_GJ * 1e6 / 3600 * p["boiler_eff"], P_barg=40, kind="boiler")
    d.tank("TK-101", "Methanol product storage", meoh_prod * th.MW("MeOH"), 790, days=14)
    d.tank("TK-102", "Crude methanol buffer", sum(n * th.MW(c) for c, n in crude_liq.items()), 870, days=2)

    prod_t_h = meoh_prod * th.MW("MeOH") / 1000
    h2_t_t = mk["H2"] * th.MW("H2") / 1000 / prod_t_h
    co2_t_t = mk["CO2"] * th.MW("CO2") / 1000 / prod_t_h
    elec_plant = d.power_kW / prod_t_h / 1000
    elec_total = elec_plant + h2_t_t * p["electrolyser_kwh_kg_h2"]
    d.kpis = [
        {"label": "Hydrogen", "value": h2_t_t, "unit": "t H2/t MeOH"},
        {"label": "CO2 feed", "value": co2_t_t, "unit": "t CO2/t MeOH"},
        {"label": "Overall CO2 to methanol conversion", "value": co2_conv_overall * 100, "unit": "%"},
        {"label": "Plant electricity (compressors, pumps)", "value": elec_plant * 1000, "unit": "kWh/t MeOH"},
        {"label": "Electricity incl. electrolysis", "value": elec_total, "unit": "MWh/t MeOH"},
        {"label": "MeOH at converter outlet", "value": out["MeOH"] / sum(out.values()) * 100, "unit": "mol%"},
    ]

    d.check("Hydrogen per tonne of methanol", h2_t_t, 0.188, "t H2/t MeOH", IRS + ", section 2.3", IRENA, tol=5,
            note="Stoichiometric figure. The model is above it by the hydrogen lost to the purge and to the "
                 "reverse shift CO dissolved in the crude.")
    d.check("CO2 per tonne of methanol", co2_t_t, 1.373, "t CO2/t MeOH", IRS + ", section 2.3", IRENA, tol=5)
    d.check("Electricity including electrolysis", elec_total, [10, 11], "MWh/t MeOH", IRS + ", section 2.3", IRENA,
            tol=10, kind="energy",
            note=f"Electrolysis taken at {p['electrolyser_kwh_kg_h2']:.0f} kWh/kg H2, the practical figure IRENA "
                 "gives in the same chapter, so most of this check rests on that input; the plant's own compressors "
                 "and pumps are computed.")
    d.check("Fixed capital, CRI Norway e-methanol plant, scaled", None,
            200e6 * (p["capacity_tpd"] / 300) ** 0.6 * C.CEPCI[C.BASE_YEAR] / C.CEPCI[2019], "USD",
            IRS + ", Table 25 (CRI Norway: 300 t/d, 100 000 t/y, USD 200 million, Stefansson 2019); six tenths "
            f"scaling and CEPCI {C.CEPCI[2019]} (2019) to {C.CEPCI[C.BASE_YEAR]} ({C.BASE_YEAR})", IRENA, tol=50,
            kind="capex",
            note="The published figure includes the electrolysers and CO2 supply, which this design buys over the "
                 "fence, so the model is expected to sit well below it. Honest fail, not tuned.")
    d.check("Production cost, e-methanol (CO2 from combined sources)", None, [820, 1620], "USD/t",
            IRS + ", Table 15 (current cost, no carbon credit)", IRENA, tol=25, kind="cost",
            note="IRENA range assumes green hydrogen at 4 000 to 8 000 USD/t; this run uses the regional green "
                 "hydrogen price.")

    d.assumptions = [
        "Green hydrogen and dry CO2 are bought over the fence; electrolysers, power supply and capture are outside "
        "the battery limit and their capital is not in the plant cost.",
        f"Electrolysis electricity for the KPI is {p['electrolyser_kwh_kg_h2']:.0f} kWh/kg H2 (IRENA 2021: 'closer to "
        "50 MWh/t').",
        "The converter reaches ideal gas chemical equilibrium with an approach of "
        f"{p['approach_C']:.0f} K; CO2 hydrogenation and reverse shift are both active.",
        "Crude condensation follows Raoult's law with Antoine vapour pressures; dissolved gases are let down and "
        "burnt with the purge in a package boiler.",
        "0.5% of the methanol is lost to the column bottoms and vents.",
        "All compressors are motor driven (no high pressure steam system on site).",
        "Distillation reboiler duty is (R + 1) x distillate latent heat plus heating the water bottoms; 30 "
        "theoretical stages in one column.",
    ]
    d.hazop = [
        {"node": "Hydrogen compressor", "deviation": "Loss of containment", "cause": "Seal or flange leak",
         "consequence": "Hydrogen jet fire or explosion; invisible flame",
         "safeguard": "Gas detection with automatic isolation, ventilated enclosure, hazardous area rating"},
        {"node": "Methanol converter", "deviation": "High temperature", "cause": "Loss of boiler water circulation",
         "consequence": "Catalyst sintering, by product formation, overpressure",
         "safeguard": "Steam drum level control, high temperature trip"},
        {"node": "CO2 supply", "deviation": "Off spec CO2 (O2, sulphur)", "cause": "Capture plant upset",
         "consequence": "Catalyst poisoning; oxygen in a hydrogen rich loop",
         "safeguard": "Online O2 and H2S analysers with feed trip, guard bed"},
        {"node": "Crude separator", "deviation": "High level", "cause": "Level control failure",
         "consequence": "Liquid carry over into recycle circulator",
         "safeguard": "High high level trip on circulator"},
        {"node": "Methanol storage", "deviation": "Loss of containment", "cause": "Overfill, tank failure",
         "consequence": "Pool fire with an almost invisible flame; toxic exposure",
         "safeguard": "Bund, foam system, nitrogen blanket, flame detectors"},
    ]
    d.greener = {
        "title": "Already the greener route; the carbon sits in the electricity",
        "text": "Each tonne needs about 9.5 MWh for electrolysis. On a 2026 grid that is several tonnes of CO2, far "
                "worse than gas based methanol, so the plant only makes sense on dedicated renewable or nuclear "
                "power with biogenic or direct air CO2. Heat integration of electrolyser waste heat into the "
                "column reboiler would cut the remaining steam demand.",
    }
    return d.finish()
