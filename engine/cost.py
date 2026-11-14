"""Equipment and plant capital cost.

Method: Turton et al., Analysis, Synthesis and Design of Chemical Processes,
5th ed. (2018), Appendix A. Purchased cost of a base unit:
    log10 Cp0 = K1 + K2 log10 A + K3 (log10 A)^2      (USD, CEPCI 397, 2001)
Bare module cost CBM = Cp0 (B1 + B2 Fm Fp) or Cp0 FBM.
Grassroots capital = 1.18 sum(CBM) + 0.50 sum(CBM at base conditions).
Units above the correlation range are split into identical parallel trains,
which is the approach Turton recommends; nothing is extrapolated.

Constants were cross-checked against two independent open source
transcriptions (OpenPyTEA cost_correlations.csv and ChemE-as-Code
turton-capcost.yaml, both MIT licensed) and agree to 4 decimal places.
"""
import math

CEPCI = {
    # Chemical Engineering Plant Cost Index, annual averages
    2001: 397.0,  # Turton base year (CAPCOST basis)
    2004: 444.2,
    2007: 525.4,
    2010: 550.8,
    2019: 607.5,
    2020: 596.2,
    2023: 797.9,
    2024: 800.0,
}
# Sources: Chemical Engineering magazine annual averages as tabulated in the
# OpenPyTEA cepci_values.csv (2004 444.2, 2007 525.4, 2010 550.8, 2019 607.5,
# 2020 596.2, 2023 797.9, 2024 800) and the eqcost catalog (2001 397).
BASE_YEAR = 2024

# (K1, K2, K3, Amin, Amax, attribute, unit)
K = {
    "vessel_vertical": (3.4974, 0.4485, 0.1074, 0.3, 520, "volume", "m3"),
    "vessel_horizontal": (3.5565, 0.3776, 0.0905, 0.1, 628, "volume", "m3"),
    "tower": (3.4974, 0.4485, 0.1074, 0.3, 520, "volume", "m3"),
    "tank_fixed_roof": (4.8509, -0.3973, 0.1445, 90, 30000, "volume", "m3"),
    "tank_floating_roof": (5.9567, -0.7585, 0.1749, 1000, 40000, "volume", "m3"),
    "hx_fixed_tube": (4.3247, -0.3030, 0.1634, 10, 1000, "area", "m2"),
    "hx_floating_head": (4.8306, -0.8509, 0.3187, 10, 1000, "area", "m2"),
    "hx_kettle": (4.4646, -0.5277, 0.3955, 10, 100, "area", "m2"),
    "hx_air_cooler": (4.0336, 0.2341, 0.0497, 10, 10000, "area", "m2"),
    "pump_centrifugal": (3.3892, 0.0536, 0.1538, 1, 300, "shaft power", "kW"),
    "compressor": (2.2897, 1.3604, -0.1027, 450, 3000, "fluid power", "kW"),
    "fan": (3.5391, -0.3533, 0.4477, 1, 100, "gas flow", "m3/s"),
    "turbine_steam": (2.6259, 1.4398, -0.1776, 70, 7500, "shaft power", "kW"),
    "heater_fired": (7.3488, -1.1666, 0.2028, 1000, 100000, "duty", "kW"),
    "reformer": (3.0680, 0.6597, 0.0194, 3000, 100000, "duty", "kW"),
    "boiler": (6.9617, -1.4800, 0.3161, 1200, 9400, "duty", "kW"),
    "reactor_jacketed": (4.1052, 0.5320, -0.0005, 0.1, 35, "volume", "m3"),
    "fermenter": (4.1052, 0.5320, -0.0005, 0.1, 35, "volume", "m3"),
    "crystalliser": (4.5097, 0.1731, 0.1344, 1.5, 30, "volume", "m3"),
    "centrifuge": (4.9697, 1.1689, 0.0038, 0.3, 2.0, "diameter", "m"),
    "dryer_rotary": (3.5645, 1.1118, -0.0777, 5, 100, "area", "m2"),
    "evaporator": (5.0238, 0.3475, 0.0703, 5, 1000, "area", "m2"),
    "packing": (2.4493, 0.9744, 0.0055, 0.03, 628, "volume", "m3"),
    "trays_sieve": (2.9949, 0.4465, 0.3961, 0.07, 12.3, "area", "m2"),
}

LABEL = {
    "vessel_vertical": "Vertical vessel",
    "vessel_horizontal": "Horizontal vessel",
    "tower": "Column shell",
    "tank_fixed_roof": "Storage tank (fixed roof)",
    "tank_floating_roof": "Storage tank (floating roof)",
    "hx_fixed_tube": "Shell and tube exchanger",
    "hx_floating_head": "Shell and tube exchanger (floating head)",
    "hx_kettle": "Kettle reboiler",
    "hx_air_cooler": "Air cooler",
    "pump_centrifugal": "Centrifugal pump",
    "compressor": "Centrifugal compressor",
    "fan": "Centrifugal fan",
    "turbine_steam": "Steam turbine",
    "heater_fired": "Fired heater",
    "reformer": "Reformer furnace",
    "boiler": "Steam boiler",
    "reactor_jacketed": "Jacketed agitated reactor",
    "fermenter": "Fermenter",
    "crystalliser": "Crystalliser",
    "centrifuge": "Centrifuge",
    "dryer_rotary": "Rotary dryer",
    "evaporator": "Evaporator",
    "packing": "Tower packing",
    "trays_sieve": "Sieve trays",
}

# Bare module factors.
# (B1, B2) Table A.4 where cross-checked; otherwise a direct FBM (Figure A.19 /
# Table A.7). Fm (material) Table A.3 / Figure A.18.
B = {
    "vessel_vertical": (2.25, 1.82),
    "vessel_horizontal": (1.49, 1.52),
    "tower": (2.25, 1.82),
    "hx_fixed_tube": (1.63, 1.66),
    "hx_floating_head": (1.63, 1.66),
    "hx_kettle": (1.63, 1.66),
    "hx_air_cooler": (0.96, 1.21),  # approximate
    "pump_centrifugal": (1.89, 1.35),
}
FBM = {
    # carbon steel, direct bare module factors
    "compressor": 2.7,  # Fig A.19, eqcost catalog (ChemEngDPpy gives 2.8)
    "fan": 2.1,  # Fig A.19 read off chart (eqcost, approximate)
    "turbine_steam": 3.5,  # Table A.7 drives (approximate)
    "heater_fired": 2.13,  # Table A.6, eqcost catalog
    "reformer": 2.13,  # taken as fired heater (approximate)
    "boiler": 2.13,  # taken as fired heater (approximate)
    "reactor_jacketed": 4.0,  # Table A.7 (approximate)
    "fermenter": 4.0,  # Table A.7 (approximate)
    "crystalliser": 1.6,  # Table A.7 (approximate)
    "centrifuge": 1.6,  # approximate
    "dryer_rotary": 1.6,  # Table A.7 (approximate)
    "evaporator": 2.9,  # Table A.7 (approximate)
    "packing": 4.1,  # ceramic packing (approximate)
    "tank_fixed_roof": 2.5,  # Fig A.19 read off chart (eqcost, approximate)
    "tank_floating_roof": 2.5,  # as fixed roof (approximate)
    "trays_sieve": 1.0,  # eqcost catalog
}
# factors marked approximate are flagged in the report
APPROX_FBM = {"fan", "turbine_steam", "reformer", "boiler", "reactor_jacketed", "fermenter",
              "crystalliser", "centrifuge", "dryer_rotary", "evaporator", "packing",
              "tank_fixed_roof", "tank_floating_roof", "hx_air_cooler"}
FM = {
    "CS": {"_": 1.0, "pump_centrifugal": 1.6},
    "SS": {"_": 3.1, "hx_fixed_tube": 2.73, "hx_floating_head": 2.73, "hx_kettle": 2.73,
           "pump_centrifugal": 2.3, "compressor": 5.8 / 2.7},
}
# trays: quantity factor folded into a flat 1.0 for > 20 trays (Turton Eq. A.4)


def cepci_factor(year=BASE_YEAR, base=2001):
    return CEPCI[year] / CEPCI[base]


def purchased_cost(kind, A):
    """Return (cost per unit at CEPCI 397, number of parallel units, size per unit)."""
    k1, k2, k3, amin, amax = K[kind][:5]
    n = 1
    if A > amax:
        n = math.ceil(A / amax)
    a = max(A / n, amin)
    la = math.log10(a)
    cp = 10 ** (k1 + k2 * la + k3 * la * la)
    return cp, n, a


def pressure_factor(kind, P_barg, D_m=None):
    if P_barg is None or P_barg <= 0.5:
        return 1.0
    if kind in ("vessel_vertical", "vessel_horizontal", "tower", "reactor_jacketed"):
        D = D_m or 2.0
        fp = ((P_barg + 1) * D / (2 * (850 - 0.6 * (P_barg + 1))) + 0.00315) / 0.0063
        return max(1.0, fp)
    if kind in ("hx_fixed_tube", "hx_floating_head", "hx_kettle"):
        if P_barg < 5:
            return 1.0
        P = min(P_barg, 140)
        lp = math.log10(P)
        return 10 ** (0.03881 - 0.11272 * lp + 0.08183 * lp * lp)
    if kind == "pump_centrifugal":
        if P_barg < 10:
            return 1.0
        P = min(P_barg, 100)
        lp = math.log10(P)
        return 10 ** (-0.3935 + 0.3957 * lp - 0.00226 * lp * lp)
    if kind in ("heater_fired", "reformer"):
        # Turton Table A.2 fired heater pressure factor, 10 to 200 barg (eqcost catalog)
        if P_barg < 10:
            return 1.0
        P = min(P_barg, 200)
        lp = math.log10(P)
        return 10 ** (0.1347 - 0.2368 * lp + 0.1021 * lp * lp)
    return 1.0


def bare_module(kind, A, P_barg=0.0, material="CS", D_m=None, year=BASE_YEAR):
    cp, n, a = purchased_cost(kind, A)
    fm = FM[material].get(kind, FM[material]["_"]) if material != "CS" else FM["CS"].get(kind, 1.0)
    fp = pressure_factor(kind, P_barg, D_m)
    if kind in B:
        b1, b2 = B[kind]
        fbm = b1 + b2 * fm * fp
        fbm0 = b1 + b2 * (FM["CS"].get(kind, 1.0))
    else:
        base = FBM[kind]
        fbm = base * fm * fp
        fbm0 = base
    f = cepci_factor(year)
    return {
        "kind": kind,
        "label": LABEL[kind],
        "size": A,
        "attribute": K[kind][5],
        "unit": K[kind][6],
        "units_parallel": n,
        "size_each": a,
        "material": material,
        "P_barg": P_barg,
        "Fp": fp,
        "Fm": fm,
        "FBM": fbm,
        "purchased": cp * n * f,
        "bare_module": cp * n * fbm * f,
        "bare_module_base": cp * n * fbm0 * f,
        "in_range": K[kind][3] <= A / n <= K[kind][4],
        "approx_factor": kind in APPROX_FBM,
    }


def grassroots(items):
    """Turton grassroots capital: 1.18 sum CBM + 0.5 sum CBM0."""
    s = sum(i["bare_module"] for i in items)
    s0 = sum(i["bare_module_base"] for i in items)
    return {
        "bare_module_total": s,
        "contingency_and_fee": 0.18 * s,
        "auxiliary_facilities": 0.5 * s0,
        "fixed_capital": 1.18 * s + 0.5 * s0,
    }


# Vessel sizing helpers -------------------------------------------------------

def vessel_from_volume(V, LD=3.0):
    D = (4 * V / (math.pi * LD)) ** (1 / 3)
    return D, LD * D


def hx_area(Q_W, U_W_m2K, dT_lm):
    return abs(Q_W) / (U_W_m2K * max(dT_lm, 1.0))


def lmtd(th_in, th_out, tc_in, tc_out):
    d1 = th_in - tc_out
    d2 = th_out - tc_in
    if d1 <= 0 or d2 <= 0:
        return max(1.0, min(abs(d1), abs(d2)))
    if abs(d1 - d2) < 1e-6:
        return d1
    return (d1 - d2) / math.log(d1 / d2)


def compressor_power(n_mol_s, T_in, P_in, P_out, k=1.4, eta=0.75, stages=None, intercool_T=313.15):
    """Fluid power (kW) for multistage compression with intercooling.
    Returns (power_kW, stages, intercooler_duty_W)."""
    R = 8.314462618
    ratio = P_out / P_in
    if stages is None:
        stages = max(1, math.ceil(math.log(ratio) / math.log(3.0)))
    r = ratio ** (1 / stages)
    W = 0.0
    Q = 0.0
    T = T_in
    for s in range(stages):
        w = n_mol_s * R * T * k / (k - 1) * (r ** ((k - 1) / k) - 1) / eta
        T_out = T + (T * (r ** ((k - 1) / k) - 1)) / eta
        W += w
        if s < stages - 1 or True:
            Q += n_mol_s * (k / (k - 1)) * R * (T_out - intercool_T)
        T = intercool_T
    return W / 1000.0, stages, Q


def pump_power(m_kg_s, rho, dP_bar, eta=0.7):
    return m_kg_s / rho * dP_bar * 1e5 / eta / 1000.0  # kW
