"""Soda ash (light) by the Solvay ammonia soda process.

Limestone is burnt with coke in shaft kilns; the lime is slaked to milk of lime and the kiln gas
(about 41% CO2) is compressed to the carbonation towers. Purified saturated brine is ammoniated
with the gas from the ammonia distiller, then carbonated so that sodium bicarbonate crystallises:
    NaCl + NH3 + CO2 + H2O -> NaHCO3 + NH4Cl
Only about 73% of the salt reacts (Hou). The bicarbonate is filtered and calcined with steam to
light soda ash, and the calciner CO2 goes back to the towers. The mother liquor is limed and steam
stripped to recover the ammonia:
    2 NH4Cl + Ca(OH)2 -> CaCl2 + 2 NH3 + 2 H2O
leaving the distiller waste (calcium chloride, unreacted salt and suspended solids) as the main
effluent. Ammonia only circulates; the make-up covers small losses.

Heats of reaction use standard enthalpies of formation of the solid and aqueous species
(Wikipedia "Standard enthalpy of formation", NBS values) and, for aqueous ammonium chloride, the
value printed in Hou's distiller heat balance. The distiller steam follows Hou's own heat balance
method (heat the liquors, decompose ammonium bicarbonate, desorb NH3 and CO2, 10% radiation).
"""
import math

from .. import core
from .. import thermo as th
from ..design import Design

DEFAULTS = {
    "capacity_tpd": 1000.0,      # t/d light soda ash (Na2CO3)
    "salt_util_pct": 73.0,        # Hou: "can average only 73 per cent"
    "excess_lime_pct": 5.0,       # lime over the fixed ammonia (Hou: "a small excess of lime")
    "limestone_CaCO3_pct": 90.0,  # BREF LVIC-S: German plants about 85% and 95% CaCO3
    "calcination_pct": 95.0,      # share of the CaCO3 burnt in the kiln
    "kiln_gas_CO2_pct": 41.0,     # Hou: 41 to 42% CO2 from a vertical lime kiln
    "tower_exit_CO2_pct": 10.0,   # CO2 left in the gas leaving the carbonation towers
    "free_NH3_kg_t": 150.0,       # Hou: free ammonia in the filter liquor per ton of ash
    "liquor_CO2_kg_t": 273.0,     # Hou: 39 g/L CO2 in 7,000 L filter liquor per ton of ash
    "NH3_loss_pct": 0.3,          # of the ammonia loop (BREF: less than 0.5%)
    "cake_moisture_pct": 15.0,    # Hou: 12 to 19% free moisture in crude bicarbonate
    "calciner_T_C": 180.0,        # BREF: bicarbonate calcined at 160 to 230 C
    "tower_P_bar": 3.5,
}

BREF = "https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/lvic-s_bref_0907.pdf"
SRC = "EU BREF Large Volume Inorganic Chemicals, Solids and Others (JRC, 2007), soda ash chapter"
HOU = "https://archive.org/details/dli.ernet.4162"
HOU_SRC = "Te-Pang Hou, Manufacture of Soda with Special Reference to the Ammonia Process (ACS Monograph, 1942)"

# Standard enthalpies of formation, kJ/mol (Wikipedia list, NBS values unless noted)
HF = {"CaCO3_s": -1206.9, "CaO_s": -635.09, "CaOH2_s": -986.09, "CO2_g": -393.509, "H2O_l": -285.8,
      "H2O_g": -241.818, "NH3_g": -46.1, "NH3_aq": -80.8, "NaHCO3_s": -950.8, "Na2CO3_s": -1130.77,
      "NaCl_aq": -407.27,
      "NH4Cl_aq": -72.8 * 4.184}  # Hou distiller heat balance: NH4Cl.Aq -72,800 cal/mol
DH_CALC = HF["CaO_s"] + HF["CO2_g"] - HF["CaCO3_s"]                        # +178.3 per mol CaCO3
DH_SLAKE = HF["CaOH2_s"] - HF["CaO_s"] - HF["H2O_l"]                       # -65.2 per mol CaO
DH_CARB = HF["NaHCO3_s"] + HF["NH4Cl_aq"] - (HF["NaCl_aq"] + HF["NH3_aq"] + HF["CO2_g"] + HF["H2O_l"])
DH_BICARB = HF["Na2CO3_s"] + HF["CO2_g"] + HF["H2O_g"] - 2 * HF["NaHCO3_s"]  # +135.6 per mol Na2CO3
DH_NH3_ABS = HF["NH3_aq"] - HF["NH3_g"]                                    # -34.7 per mol NH3
LHV_C = -HF["CO2_g"]                                                        # coke as carbon, kJ/mol

# Hou distiller heat balance figures (cal converted at 4.184 J/cal)
Q_NH4HCO3_KJ_KG = 647 * 4.184        # decomposing NH4HCO3, per kg free NH3
Q_DES_NH3 = 8430 * 4.184 / 1000      # heat of solution of NH3, kJ/mol
Q_DES_CO2 = 5880 * 4.184 / 1000      # heat of solution of CO2, kJ/mol
RADIATION = 0.10                      # Hou: radiation from the distiller at 10% of the heat required
T_ML, T_MOL, T_DIST = 318.15, 328.15, 388.15   # Hou: feed liquor 45 C, milk of lime 55 C, steam 115 C
MOL_CAO_G_L, MOL_SG = 250.0, 1.21     # Hou: milk of lime 250 g CaO per litre, sp. gr. 1.21

# Approximate heat capacities, kJ/kg K (water 4.18; solids from Wikipedia infoboxes: NaCl 50.5 J/mol K,
# NH4Cl 84.1, Na2CO3 112.3, CaCO3 83.5, SiO2 44.4, Ca(OH)2 87.5). Solution cp as mass weighted sum.
CP = {"H2O": 4.18, "NaCl": 50.5 / 58.44, "NH4Cl": 84.1 / 53.49, "Na2CO3": 112.3 / 105.99,
      "CaCO3": 83.5 / 100.09, "SiO2": 44.4 / 60.08, "CaOH2": 87.5 / 74.09, "CaCl2": 72.9 / 110.98,
      "NaHCO3": 87.6 / 84.01, "CaO": 42.0 / 56.08, "NH3": 4.7, "CO2": 0.85}
W_SAT = 0.264  # saturated brine, about 26.4 wt% NaCl at 20 C (CRC, Sodium chloride data page)


def _cp_mass(flows):
    kg = {c: n * th.MW(c) for c, n in flows.items()}
    tot = sum(kg.values())
    return sum(CP.get(c, 4.18) * m for c, m in kg.items()) / tot if tot else 4.18, tot


def _sens_liq(flows, T1, T2):
    cp, kg = _cp_mass(flows)
    return kg * cp * (T2 - T1) / 3600  # kW


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)
    t_h = p["capacity_tpd"] / 24
    MW = {c: th.MW(c) for c in ("Na2CO3", "NaHCO3", "NaCl", "NH3", "NH4Cl", "CO2", "H2O", "CaCO3", "CaO",
                                "CaOH2", "CaCl2", "C", "N2", "O2", "SiO2")}
    P = t_h * 1000 / MW["Na2CO3"]                      # kmol/h soda ash
    U = p["salt_util_pct"] / 100
    bicarb = 2 * P
    NaCl_in = bicarb / U
    NaCl_left = NaCl_in - bicarb
    fixed = bicarb                                     # NH4Cl formed
    free = p["free_NH3_kg_t"] * t_h / MW["NH3"]
    co2_liq = p["liquor_CO2_kg_t"] * t_h / MW["CO2"]
    loop = fixed + free
    loss = p["NH3_loss_pct"] / 100 * loop
    loss_air, loss_liq = loss / 2, loss / 2

    # ---- lime kiln
    lime = fixed / 2 * (1 + p["excess_lime_pct"] / 100)   # Ca(OH)2 to the distiller, kmol/h
    cd = p["calcination_pct"] / 100
    caco3_in = lime / cd
    unburnt = caco3_in - lime
    ls_kg = caco3_in * MW["CaCO3"] / (p["limestone_CaCO3_pct"] / 100)
    sio2 = (ls_kg - caco3_in * MW["CaCO3"]) / MW["SiO2"]
    y = p["kiln_gas_CO2_pct"] / 100
    n2_o2 = 79.0 / 21.0
    c = lime * (1 - y) / ((1 + n2_o2) * y - 1)          # coke carbon so the kiln gas holds y CO2
    o2 = c
    n2 = c * n2_o2
    kiln_co2 = lime + c
    Q_coke = c * LHV_C * 1000 / 3600                     # kW
    Q_calc = lime * DH_CALC * 1000 / 3600
    burnt = {"CaO": lime, "CaCO3": unburnt, "SiO2": sio2}
    cao_pct = lime * MW["CaO"] / sum(n * MW[k] for k, n in burnt.items()) * 100

    # ---- kiln gas split: towers take what they need, the rest is vented
    ye = p["tower_exit_CO2_pct"] / 100
    f = P / (kiln_co2 - ye / (1 - ye) * n2)            # share of the kiln gas sent to the towers
    if not 0 < f <= 1:
        raise ValueError("Kiln gas cannot supply the carbonation CO2 at these settings")
    kg_tow = {"CO2": f * kiln_co2, "N2": f * n2}
    kg_vent = {"CO2": (1 - f) * kiln_co2, "N2": (1 - f) * n2}
    exit_co2 = ye / (1 - ye) * kg_tow["N2"]

    # ---- brine and ammoniation
    brine_w = NaCl_in * MW["NaCl"] * (1 - W_SAT) / W_SAT / MW["H2O"]
    T_oh = 333.15
    ps = core.psat("H2O", T_oh)
    dist_gas = {"NH3": loop - loss_liq, "CO2": co2_liq}
    dist_gas["H2O"] = (dist_gas["NH3"] + co2_liq) * ps / (1.0 - ps)
    amm = {"NaCl": NaCl_in, "NH3": loop + loss_air, "CO2": co2_liq, "H2O": brine_w + dist_gas["H2O"]}
    mk = loss  # make-up ammonia

    # ---- carbonation towers
    T_cg = 313.15
    co2_wet = {"CO2": P, "H2O": P * core.psat("H2O", T_cg) / (1.0 - core.psat("H2O", T_cg))}
    slurry = {"NaHCO3": bicarb, "NaCl": NaCl_left, "NH4Cl": fixed, "NH3": free, "CO2": co2_liq,
              "H2O": amm["H2O"] - bicarb + co2_wet["H2O"]}
    tow_gas_out = {"N2": kg_tow["N2"], "CO2": exit_co2, "NH3": loss_air}
    # check CO2 into the towers equals CO2 fixed plus CO2 out
    calc_co2 = P

    # ---- filtration
    mw_frac = p["cake_moisture_pct"] / 100
    cake_w = bicarb * MW["NaHCO3"] * mw_frac / (1 - mw_frac) / MW["H2O"]
    cake = {"NaHCO3": bicarb, "H2O": cake_w}
    ml = {"NaCl": NaCl_left, "NH4Cl": fixed, "NH3": free, "CO2": co2_liq, "H2O": slurry["H2O"] - cake_w}
    ml_m3_t = sum(n * MW[k] for k, n in ml.items()) / 1100 / t_h  # density about 1.1 kg/L

    # ---- calciner and calciner gas cooler
    Tcal = p["calciner_T_C"] + 273.15
    cal_gas = {"CO2": P, "H2O": P + cake_w}
    cal_cond = cal_gas["H2O"] - co2_wet["H2O"]
    Q_cal = (P * DH_BICARB * 1000 / 3600
             + cake_w * (core.h_molar("H2O", Tcal) - core.h_molar("H2O", T_ML, "l")) / 3600
             + _sens_liq({"NaHCO3": bicarb}, T_ML, 373.15)
             + _sens_liq({"Na2CO3": P}, 373.15, Tcal)
             + P * (core.h_molar("H2O", Tcal) - core.h_molar("H2O", 373.15)) / 3600
             + core.hin({"CO2": P}, Tcal) - core.hin({"CO2": P}, 373.15))
    Q_cal *= 1 + RADIATION
    s40 = th.STEAM[40]
    steam_cal = Q_cal * 3600 / (s40[2] - s40[1])
    Q_cg = (core.hin(cal_gas, Tcal) - core.hin(co2_wet, T_cg)
            - cal_cond * (core.h_molar("H2O", T_cg, "l") - core.h_molar("H2O", 298.15, "l")) / 3600
            + cal_cond * (core.h_molar("H2O", 298.15) - core.h_molar("H2O", 298.15, "l")) / 3600)

    # ---- slaker: milk of lime at 250 g CaO/L, sp. gr. 1.21
    w_per_cao = (MOL_SG * 1000 - MOL_CAO_G_L * MW["CaOH2"] / MW["CaO"]) / MOL_CAO_G_L * MW["CaO"] / MW["H2O"]
    mol_w = lime * w_per_cao
    milk = {"CaOH2": lime, "CaCO3": unburnt, "SiO2": sio2, "H2O": mol_w}
    slake_water = mol_w + lime
    fresh_w = slake_water - cal_cond
    if fresh_w < 0:
        raise ValueError("Calciner condensate exceeds slaker water")
    Q_slake = -lime * DH_SLAKE * 1000 / 3600

    # ---- distiller (Hou heat balance method) with live steam
    lat = th.STEAM[3.5][2] - 4.184 * (T_DIST - 273.15)   # steam condensed to liquid at the bottom temperature
    Q_d = (_sens_liq(ml, T_ML, T_DIST) + _sens_liq(milk, T_MOL, T_DIST)
           + p["free_NH3_kg_t"] * t_h * Q_NH4HCO3_KJ_KG / 3600
           + dist_gas["NH3"] * Q_DES_NH3 * 1000 / 3600 + co2_liq * Q_DES_CO2 * 1000 / 3600)
    Q_d *= 1 + RADIATION
    steam_d = Q_d * 3600 / lat
    st_n = steam_d / MW["H2O"]
    waste = {"CaCl2": fixed / 2, "NaCl": NaCl_left, "CaOH2": lime - fixed / 2, "CaCO3": unburnt, "SiO2": sio2,
             "NH3": loss_liq,
             "H2O": ml["H2O"] + mol_w + fixed + st_n - dist_gas["H2O"]}
    waste_kg = sum(n * MW[k] for k, n in waste.items())

    # ---- absorber and carbonation heat
    Q_abs = (dist_gas["NH3"] + mk) * -DH_NH3_ABS * 1000 / 3600 + co2_liq * Q_DES_CO2 * 1000 / 3600 + \
        dist_gas["H2O"] * (core.h_molar("H2O", T_oh) - core.h_molar("H2O", 303.15, "l")) / 3600
    Q_carb = -bicarb * DH_CARB * 1000 / 3600

    # ---- design object
    d = Design("soda_ash", "Soda ash (Solvay ammonia soda process)", "Soda ash", p["capacity_tpd"], region)
    hrs = d.hours
    d.route = ("Limestone is burnt with coke in shaft kilns; brine is ammoniated and carbonated with the kiln gas "
               "so sodium bicarbonate crystallises. The bicarbonate is filtered and calcined with steam to light "
               "soda ash, and the mother liquor is limed and steam stripped to recover the ammonia, leaving calcium "
               "chloride liquor as the effluent.")
    d.summary = (f"{p['capacity_tpd']:,.0f} t/d light soda ash from {NaCl_in * MW['NaCl'] / t_h / 1000:.2f} t salt "
                 f"and {ls_kg / t_h / 1000:.2f} t limestone per tonne, with "
                 f"{(steam_d + steam_cal) / t_h / 1000:.1f} t of steam per tonne.")
    d.reactions = [
        {"eq": "CaCO3 -> CaO + CO2", "where": "Lime kilns", "dH_kJ": DH_CALC},
        {"eq": "C + O2 -> CO2", "where": "Lime kilns (coke)", "dH_kJ": -LHV_C},
        {"eq": "CaO + H2O -> Ca(OH)2", "where": "Slaker", "dH_kJ": DH_SLAKE},
        {"eq": "NaCl + NH3 + CO2 + H2O -> NaHCO3 + NH4Cl", "where": "Carbonation towers", "dH_kJ": DH_CARB},
        {"eq": "2 NaHCO3 -> Na2CO3 + CO2 + H2O", "where": "Calciner", "dH_kJ": DH_BICARB},
        {"eq": "2 NH4Cl + Ca(OH)2 -> CaCl2 + 2 NH3 + 2 H2O", "where": "Distiller", "dH_kJ": 0.0},
    ]
    d.conditions = [
        ("Lime kilns", f"950 to 1,100 C, kiln gas {y * 100:.0f}% CO2, burnt lime {cao_pct:.0f}% CaO"),
        ("Carbonation towers", f"{p['tower_P_bar']:.1f} bar gas, cooled, salt utilisation {U * 100:.0f}%"),
        ("Calciner", f"{p['calciner_T_C']:.0f} C, indirect 40 bar steam"),
        ("Distiller", f"Live 3.5 bar steam, bottoms about {T_DIST - 273.15:.0f} C"),
    ]

    # ---- streams
    s_ls = d.stream("Limestone", {"CaCO3": caco3_in, "SiO2": sio2}, 298.15, 1.0, phase="s")
    s_ck = d.stream("Coke", {"C": c}, 298.15, 1.0, phase="s")
    s_air = d.stream("Kiln air", {"O2": o2, "N2": n2}, 298.15, 1.0)
    s_kg = d.stream("Kiln gas", {"CO2": kiln_co2, "N2": n2}, 393.15, 1.0)
    s_bl = d.stream("Burnt lime", burnt, 353.15, 1.0, phase="s")
    s_kgt = d.stream("Kiln gas to towers", kg_tow, 313.15, p["tower_P_bar"])
    s_kgv = d.stream("Excess kiln gas to stack", kg_vent, 313.15, 1.0)
    s_br = d.stream("Raw brine", {"NaCl": NaCl_in, "H2O": brine_w}, 288.15, 3, phase="l")
    s_pb = d.stream("Purified brine", {"NaCl": NaCl_in, "H2O": brine_w}, 298.15, 3, phase="l")
    s_mk = d.stream("Make-up ammonia", {"NH3": mk}, 298.15, 10)
    s_dg = d.stream("Distiller gas", dist_gas, T_oh, 1.0)
    s_am = d.stream("Ammoniated brine", amm, 303.15, 3, phase="l")
    s_cg = d.stream("Calciner CO2 to towers", co2_wet, 313.15, p["tower_P_bar"])
    s_sl = d.stream("Bicarbonate slurry", slurry, 303.15, 2, phase="l")
    s_tg = d.stream("Tower exit gas to washer and stack", tow_gas_out, 303.15, 1.0)
    s_ck2 = d.stream("Crude bicarbonate cake", cake, 303.15, 1.0, phase="s")
    s_ml = d.stream("Mother liquor", ml, T_ML, 2, phase="l")
    s_sa = d.stream("Light soda ash", {"Na2CO3": P}, Tcal - 30, 1.0, phase="s")
    s_cgh = d.stream("Calciner gas", cal_gas, Tcal, 1.0)
    s_cc = d.stream("Calciner gas condensate", {"H2O": cal_cond}, T_cg, 2, phase="l")
    s_fw = d.stream("Slaker water", {"H2O": fresh_w}, 298.15, 3, phase="l")
    s_mol = d.stream("Milk of lime", milk, T_MOL, 3, phase="l")
    s_st = d.stream("Live steam to distiller", {"H2O": st_n}, th.STEAM[3.5][0] + 273.15, 3.5)
    s_dw = d.stream("Distiller waste", waste, T_DIST - 10, 1.0, phase="l")

    d.feed(s_ls, {"CaCO3": "CaCO3", "SiO2": "CaCO3"})
    d.feed(s_ck, {"C": "C"})
    d.feed(s_air)
    d.feed(s_br, {"NaCl": "NaCl_brine"})
    d.feed(s_mk, {"NH3": "NH3"})
    d.feed(s_fw)
    d.feed(s_st)
    d.out(s_sa, "product", {"Na2CO3": "Na2CO3"})
    d.out(s_kgv, "emission")
    d.out(s_tg, "emission")
    d.out(s_dw, "waste", treat_usd_t=1.0)

    d.unit("K-101", "Lime kilns (shaft, coke fired)", "reactor", [s_ls, s_ck, s_air], [s_kg, s_bl], (0, 0),
           duty_kW=Q_coke - Q_calc, desc=f"Kiln thermal efficiency {Q_calc / Q_coke * 100:.0f}%")
    d.unit("S-101", "Lime slaker and classifier", "mixer", [s_bl, s_fw, s_cc], [s_mol], (1, 2), duty_kW=-Q_slake)
    d.unit("E-101", "Kiln gas washer and compressor", "compressor", [s_kg], [s_kgt, s_kgv], (1, 0))
    d.unit("F-101", "Brine purification", "separator", [s_br], [s_pb], (0, 1),
           desc="Lime and soda ash precipitation of Mg and Ca, clarifier (chemicals not modelled)")
    d.unit("A-101", "Ammonia absorber", "column", [s_pb, s_dg, s_mk], [s_am], (1, 1), duty_kW=-Q_abs)
    d.unit("C-201", "Carbonation towers", "reactor", [s_am, s_kgt, s_cg], [s_sl, s_tg], (2, 1), duty_kW=-Q_carb)
    d.unit("F-201", "Bicarbonate filters", "separator", [s_sl], [s_ck2, s_ml], (3, 1))
    d.unit("D-301", "Steam calciner", "reactor", [s_ck2], [s_sa, s_cgh], (4, 1), duty_kW=Q_cal)
    d.unit("E-301", "Calciner gas cooler and compressor", "exchanger", [s_cgh], [s_cg, s_cc], (4, 0), duty_kW=-Q_cg)
    d.unit("C-401", "Ammonia distiller (prelimer and lime still)", "column", [s_ml, s_mol, s_st], [s_dg, s_dw],
           (3, 2), duty_kW=Q_d)

    # ---- utilities
    d.steam(steam_d, "Ammonia distiller, live 3.5 bar steam")
    d.steam(steam_cal, "Bicarbonate calciner, 40 bar steam")
    d.solids_steps = 3  # limestone and coke handling, lime, soda ash

    # ---- equipment
    W1, _ = d.compressor("K-201", "Kiln gas compressor", core.Stream("x", "x", kg_tow, 313.15, 1.0), p["tower_P_bar"],
                         k=1.33, eta=0.75)
    W2, _ = d.compressor("K-202", "Calciner CO2 compressor", core.Stream("x", "x", co2_wet, 313.15, 1.0), p["tower_P_bar"],
                         k=1.3, eta=0.75)
    lime_tpd = lime * MW["CaO"] * 24 / 1000
    n_k = max(1, math.ceil(lime_tpd / 400.0))
    for i in range(n_k):
        d.heater(f"K-10{i + 1}", f"Lime kiln {i + 1} (shaft kiln, fired heater curve as proxy)", Q_coke / n_k)
    d.cooler_cw("E-102", "Kiln gas cooler and washer", core.hin({"CO2": kiln_co2, "N2": n2}, 393.15)
                - core.hin({"CO2": kiln_co2, "N2": n2}, 313.15), 393.15, 313.15, service="gas-water")
    d.vessel("S-101", "Lime slaker and milk of lime tank",
             sum(n * MW[k] for k, n in milk.items()) / 1210 * 1.0, orientation="vertical")
    brine_m3 = (NaCl_in * MW["NaCl"] + brine_w * MW["H2O"]) / 1200
    d.vessel("F-101", "Brine purification reactors and clarifier", brine_m3 * 3.0, orientation="horizontal")
    d.column("A-101", "Ammonia absorber", sum(dist_gas.values()), 333.15, 1.0, 8, 25.0, packed=True)
    d.cooler_cw("E-103", "Absorber coolers", Q_abs, 338.15, 313.15, service="liquid-water")
    # Hou: a 7.5 ft ID, about 75 ft tower makes 100 to 120 t/d ash
    n_t = math.ceil(p["capacity_tpd"] / 110.0)
    V_t = math.pi / 4 * 2.29 ** 2 * 22.9
    for i in range(n_t):
        d.vessel(f"C-2{i + 1:02d}", f"Carbonation tower {i + 1}", V_t, P_barg=p["tower_P_bar"] - 1)
    d.cooler_cw("E-201", "Carbonation tower cooling boxes", Q_carb, 333.15, 308.15, service="liquid-water")
    # Hou: a 2 m diameter, 1 m wide rotary vacuum filter makes 150 to 200 t/d ash
    n_f = math.ceil(p["capacity_tpd"] / 175.0)
    for i in range(n_f):
        d.generic(f"F-2{i + 1:02d}", f"Bicarbonate filter {i + 1}", "centrifuge", 2.0, "2 m drum",
                  note="Rotary vacuum filter costed on the centrifuge curve (no Turton filter curve)")
    # Hou: a 72 inch by 60 ft rotary dryer turns out 55 t/d ash, i.e. about 1.9 m2 shell per t/d
    A_cal = math.pi * 1.83 * 18.3 / 55.0 * p["capacity_tpd"]
    n_c = math.ceil(A_cal / 100.0)
    for i in range(n_c):
        d.generic(f"D-3{i + 1:02d}", f"Steam calciner {i + 1}", "dryer_rotary", A_cal / n_c, f"{A_cal / n_c:.0f} m2",
                  note="Sized on Hou's rotary dryer output per shell area; modern steam calciners are larger")
    d.cooler_cw("E-301", "Calciner gas cooler", Q_cg, Tcal, T_cg, service="wet-gas")
    d.column("C-401", "Ammonia distiller", sum(dist_gas.values()), 373.15, 1.2, 12, 20.0)
    d.vessel("V-401", "Prelimer", sum(n * MW[k] for k, n in ml.items()) / 1100 * 0.5)
    d.pump("P-101", "Brine pumps", brine_m3 * 1200, 1200, 4)
    d.pump("P-201", "Ammoniated brine pumps", sum(n * MW[k] for k, n in amm.items()), 1100, 4)
    d.pump("P-301", "Mother liquor pumps", sum(n * MW[k] for k, n in ml.items()), 1100, 3)
    d.pump("P-401", "Milk of lime pumps", sum(n * MW[k] for k, n in milk.items()), 1210, 3)
    d.pump("P-402", "Distiller waste pumps", waste_kg, 1100, 3)
    d.tank("TK-301", "Light soda ash silos", P * MW["Na2CO3"], 550, days=7)
    d.tank("TK-101", "Ammonia storage", mk * MW["NH3"], 610, days=30, pressurised=True, P_barg=10)

    # ---- KPIs
    tpt = lambda kmol, cid: kmol * MW[cid] / t_h  # kg per t soda ash
    co2_direct = (kg_vent["CO2"] + exit_co2) * MW["CO2"] / t_h
    steam_total = steam_d + steam_cal
    E_steam = (steam_d * (th.STEAM[3.5][2] - th.H_BFW_105C) + steam_cal * (s40[2] - th.H_BFW_105C)) / 0.9 / 1e6
    fuel_GJ_t = E_steam / t_h + d.power_kW * 3.6 / 1000 / t_h
    kWh_t = d.power_kW / t_h
    waste_m3_t = waste_kg / 1100 / t_h
    ss = (waste["CaOH2"] * MW["CaOH2"] + unburnt * MW["CaCO3"] + sio2 * MW["SiO2"]) / t_h
    d.kpis = [
        {"label": "Salt (as brine)", "value": tpt(NaCl_in, "NaCl"), "unit": "kg NaCl/t"},
        {"label": "Limestone to kilns", "value": ls_kg / t_h, "unit": "kg/t"},
        {"label": "Coke", "value": tpt(c, "C"), "unit": "kg/t"},
        {"label": "Ammonia make-up", "value": tpt(mk, "NH3"), "unit": "kg/t"},
        {"label": "Ammonia circulating", "value": tpt(loop, "NH3"), "unit": "kg/t"},
        {"label": "Steam, ammonia distiller", "value": steam_d / t_h, "unit": "kg/t"},
        {"label": "Steam, calciner", "value": steam_cal / t_h, "unit": "kg/t"},
        {"label": "Kiln fuel (coke)", "value": Q_coke * 3.6 / 1000 / t_h, "unit": "GJ/t"},
        {"label": "Kiln thermal efficiency", "value": Q_calc / Q_coke * 100, "unit": "%"},
        {"label": "Burnt lime CaO content", "value": cao_pct, "unit": "%"},
        {"label": "Direct CO2 to air", "value": co2_direct, "unit": "kg/t"},
        {"label": "Distiller waste", "value": waste_m3_t, "unit": "m3/t"},
        {"label": "Mother liquor to distiller", "value": ml_m3_t, "unit": "m3/t"},
        {"label": "Electricity", "value": kWh_t, "unit": "kWh/t"},
    ]

    # ---- validation
    d.check("Salt consumption (as brine)", tpt(NaCl_in, "NaCl"), [1530, 1800], "kg NaCl/t soda ash",
            SRC + ", Table 2.11", BREF, tol=5,
            note="Model counts only the salt left unreacted at 73% utilisation; handling and purge losses are not "
                 "modelled, so it sits at the low end.")
    d.check("Salt consumption", tpt(NaCl_in, "NaCl") / 1000, [1.6, 1.7], "t NaCl/t soda ash", HOU_SRC, HOU, tol=10)
    d.check("Limestone to lime kilns", ls_kg / t_h, [1050, 1600], "kg/t soda ash", SRC + ", Table 2.11", BREF, tol=5)
    d.check("Kiln fuel", Q_coke * 3.6 / 1000 / t_h, [2.2, 2.8], "GJ/t soda ash", SRC + ", Table 2.11", BREF,
            tol=10, kind="energy",
            note="Coke follows from the 41% CO2 kiln gas Hou reports; coke modelled as pure carbon.")
    d.check("Ammonia make-up", tpt(mk, "NH3"), [0.8, 2.1], "kg/t soda ash", SRC + ", Table 2.11", BREF, tol=10,
            note="Set by the loss share (0.3% of the loop, BREF says under 0.5%), so a consistency check.")
    d.check("Ammonia circulating", tpt(loop, "NH3"), [500, 550], "kg/t soda ash", SRC + ", section 2.2.1.2",
            BREF, tol=10, note="Fixed ammonia is stoichiometric; free ammonia 150 kg/t from Hou.")
    d.check("Steam for ammonia recovery", steam_d / t_h, [1300, 2400], "kg/t soda ash", SRC + ", section 2.3.1",
            BREF, tol=10, kind="energy")
    d.check("Steam for bicarbonate decomposition", steam_cal / t_h, [1100, 1300], "kg/t soda ash",
            SRC + ", section 2.3.1", BREF, tol=15, kind="energy")
    d.check("Process fuels including electricity (light ash, densification 0.9 GJ/t removed)", fuel_GJ_t,
            [7.5 - 0.9, 10.8 - 0.9], "GJ/t soda ash", SRC + ", Table 2.11", BREF, tol=15, kind="energy",
            note="Steam at 90% boiler efficiency plus electricity at 3.6 MJ/kWh.")
    d.check("CO2 to air", co2_direct, [200, 400], "kg/t soda ash", SRC + ", Table 2.11", BREF, tol=10,
            kind="carbon")
    d.check("Chloride in distiller waste", (NaCl_left + fixed) * 35.453 / t_h, [850, 1100], "kg/t soda ash",
            SRC + ", Table 2.11", BREF, tol=5)
    d.check("Calcium in distiller waste (dissolved)", fixed / 2 * 40.078 / t_h, [340, 400], "kg/t soda ash",
            SRC + ", Table 2.11", BREF, tol=5)
    d.check("Sodium in distiller waste", NaCl_left * 22.99 / t_h, [160, 220], "kg/t soda ash",
            SRC + ", Table 2.11", BREF, tol=5)
    d.check("Suspended solids in distiller waste", ss, [90, 700], "kg/t soda ash", SRC + ", Table 2.11", BREF, tol=10)
    d.check("Distiller waste volume", waste_m3_t, 10, "m3/t soda ash", SRC + ", Table 2.13 (illustrative)", BREF,
            tol=25)
    d.check("Burnt lime CaO content", cao_pct, [75, 90], "%", SRC + ", section 2.2.1.2", BREF, tol=5)
    d.check("Electricity", kWh_t, [50, 130], "kWh/t soda ash", SRC + ", Table 2.11", BREF, tol=20, kind="energy",
            note="Gas compressors and pumps only; filter vacuum pumps, conveyors and crushers are not modelled.")

    d.assumptions = [
        f"Salt utilisation {U * 100:.0f}% in the carbonation towers (Hou: 'can average only 73 per cent'). "
        "Unreacted salt leaves with the distiller waste; no other salt losses are modelled.",
        f"Limestone {p['limestone_CaCO3_pct']:.0f}% CaCO3 (BREF: 85 to 95%), rest lumped as silica; "
        f"{p['calcination_pct']:.0f}% of the CaCO3 burnt. Lime fed {p['excess_lime_pct']:.0f}% over the fixed "
        "ammonia.",
        "Coke is pure carbon burnt completely with just enough air; its rate is set so the kiln gas holds 41% CO2 "
        "(Hou). Real kilns make some CO (BREF: 4 to 20 kg/t). Kiln gas not needed in the towers is vented.",
        "The ammonia loop carries the stoichiometric fixed ammonia plus 150 kg/t free ammonia and 273 kg/t "
        "dissolved CO2 (Hou). Losses are 0.3% of the loop, half to air and half to the distiller waste.",
        "Distiller steam follows Hou's heat balance: heating the liquor from 45 C and milk of lime from 55 C to "
        "115 C, decomposing ammonium bicarbonate, desorbing NH3 and CO2, plus 10% radiation. Milk of lime at "
        "250 g CaO/L, sp. gr. 1.21 (Hou).",
        "Calciner uses 40 bar steam to supply the reaction heat, evaporate 15% cake moisture and heat solids and "
        "gas to 180 C, plus 10% losses. Light soda ash only; no densification.",
        "Brine purification chemicals, filter wash water, the brine washers and vacuum pumps are not modelled. "
        "Distiller waste density taken as 1.1 kg/L.",
        "Equipment counts follow Hou's unit capacities (carbonation towers 110 t/d, filters 175 t/d, rotary "
        "calciners by shell area), so capex is conservative for a modern plant. Shaft kilns costed on the fired "
        "heater curve as a proxy, one kiln per 400 t/d of lime.",
    ]
    d.hazop = [
        {"node": "Ammonia absorber and distiller", "deviation": "Loss of containment", "cause": "Corrosion, gasket",
         "consequence": "Toxic ammonia release", "safeguard": "NH3 detectors, brine washers on all vents"},
        {"node": "Carbonation towers", "deviation": "High temperature", "cause": "Loss of cooling water",
         "consequence": "Fine crystals, poor filtration, ammonia slip to vent", "safeguard":
         "Cooling water low flow alarm, tower temperature profile control"},
        {"node": "Lime kilns", "deviation": "Incomplete combustion", "cause": "Poor coke distribution, low air",
         "consequence": "High CO in kiln gas, CO poisoning at the compressor house", "safeguard":
         "CO analysers, ventilation"},
        {"node": "Steam calciner", "deviation": "High pressure in steam tubes", "cause": "Control failure",
         "consequence": "Tube rupture", "safeguard": "Relief valves, pressure trips"},
        {"node": "Distiller waste", "deviation": "High suspended solids or ammonia", "cause": "Lime overdosing, "
         "upset distiller", "consequence": "Effluent limits breached", "safeguard": "Settling ponds, online NH4+ "
         "monitoring"},
    ]
    d.greener = {
        "title": "Natural trona soda ash, or capture the kiln CO2",
        "text": "Soda ash refined from natural trona (as in Wyoming) avoids the lime kiln, the ammonia loop and the "
                "calcium chloride effluent and uses less energy. In a Solvay plant, venting less kiln gas, "
                "recovering distiller heat and selling the calcium chloride cut the footprint.",
        "electricity_MWh_per_t": d.power_kW / 1000 / t_h,
    }
    return d.finish()
