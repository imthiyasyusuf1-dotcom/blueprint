"""Thermodynamic helpers. Standard library only.

Data comes from engine/data/components.json (generated from the open source
`chemicals` package). Ideal gas enthalpy is Hf(298) + integral of a fitted Cp.
"""
import json
import math
import os

R = 8.314462618  # J/mol/K
T0 = 298.15
P_ATM = 101325.0

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "data", "components.json")) as _f:
    _DB = json.load(_f)["components"]

# A few standard state heats of formation that the generated database leaves
# empty or gives for the wrong reference phase. Values in J/mol.
# Source: NIST Chemistry WebBook (condensed phase thermochemistry).
_HF_STD_OVERRIDE = {
    "Glucose": -1273300.0,  # alpha-D-glucose, solid
    "S": 0.0,  # rhombic sulphur is the reference state
}
# Triolein liquid: gas value minus a group contribution heat of vaporisation is
# not reliable, so the liquid value is derived where needed from the biodiesel
# reaction, which is close to thermoneutral (see processes/biodiesel.py).


def comp(cid):
    return _DB[cid]


def MW(cid):
    return _DB[cid]["MW"]


def name(cid):
    return _DB[cid]["name"]


def formula(cid):
    return _DB[cid]["formula"]


def hf_std(cid):
    if cid in _HF_STD_OVERRIDE:
        return _HF_STD_OVERRIDE[cid]
    v = _DB[cid].get("Hf_std")
    return v if v is not None else _DB[cid]["Hf_gas"]


def hf_gas(cid):
    return _DB[cid]["Hf_gas"]


def cp_gas(cid, T):
    c = _DB[cid]["cp_gas"]
    return c["a"] + c["b"] * T + c["c"] * T * T + c["d"] * T ** 3


def dh_sensible(cid, T1, T2):
    """Integral of ideal gas Cp dT from T1 to T2, J/mol."""
    c = _DB[cid]["cp_gas"]

    def F(T):
        return c["a"] * T + c["b"] * T ** 2 / 2 + c["c"] * T ** 3 / 3 + c["d"] * T ** 4 / 4

    return F(T2) - F(T1)


def ds_sensible(cid, T1, T2):
    c = _DB[cid]["cp_gas"]

    def F(T):
        return c["a"] * math.log(T) + c["b"] * T + c["c"] * T ** 2 / 2 + c["d"] * T ** 3 / 3

    return F(T2) - F(T1)


def h_gas(cid, T):
    """Molar enthalpy of ideal gas relative to elements at 298 K, J/mol."""
    return hf_gas(cid) + dh_sensible(cid, T0, T)


def dh_rxn_gas(stoich, T=T0):
    """Heat of reaction for all-gas reaction at T, J/mol of reaction.
    stoich: {cid: nu}, products positive."""
    return sum(nu * h_gas(c, T) for c, nu in stoich.items())


def dh_rxn_std(stoich):
    """Heat of reaction at 298 K using standard state (liquid/solid) enthalpies."""
    return sum(nu * hf_std(c) for c, nu in stoich.items())


def dg_rxn_gas(stoich, T):
    dH = dh_rxn_gas(stoich, T)
    dS = sum(nu * (_DB[c]["S0_gas"] + ds_sensible(c, T0, T)) for c, nu in stoich.items())
    return dH - T * dS


def Kp(stoich, T):
    """Equilibrium constant with pressures in bar (standard state 1 bar)."""
    return math.exp(-dg_rxn_gas(stoich, T) / (R * T))


def stream_h(flows, T):
    """Enthalpy of an ideal gas stream, flows in mol/s, returns W."""
    return sum(n * h_gas(c, T) for c, n in flows.items() if n)


def mix_temperature(flows, H_target, T_guess=600.0):
    """Find T at which ideal gas stream enthalpy equals H_target (W)."""
    T = T_guess
    for _ in range(60):
        H = stream_h(flows, T)
        cp = sum(n * cp_gas(c, T) for c, n in flows.items() if n)
        dT = (H_target - H) / cp
        T += max(-200, min(200, dT))
        if abs(dT) < 1e-4:
            break
    return T


def mass_flow(flows_mol_s):
    """mol/s dict to kg/s dict."""
    return {c: n * MW(c) / 1000.0 for c, n in flows_mol_s.items()}


def lhv_mass(cid):
    """Lower heating value in MJ/kg (positive)."""
    v = _DB[cid]["LHV"]
    return -v / MW(cid) / 1000.0 if v else None  # J/mol / g/mol = kJ/kg; /1000 = MJ/kg


def lhv_molar(cid):
    v = _DB[cid]["LHV"]
    return -v if v else None  # J/mol, positive


def hvap(cid, T=T0):
    v = _DB[cid].get("Hvap_298")
    return v or 0.0


def cp_liq(cid):
    return _DB[cid].get("Cp_liquid_298")


def safety(cid):
    c = _DB[cid]
    return {
        "flash_point_C": None if c["flash_point_K"] is None else round(c["flash_point_K"] - 273.15),
        "autoignition_C": None if c["autoignition_K"] is None else round(c["autoignition_K"] - 273.15),
        "LFL_pct": None if c["LFL"] is None else round(c["LFL"] * 100, 1),
        "UFL_pct": None if c["UFL"] is None else round(c["UFL"] * 100, 1),
        "Tb_C": None if c["Tb"] is None else round(c["Tb"] - 273.15),
    }


# Water and steam (IAPWS-IF97 values at the stated conditions, kJ/kg)
# Saturated steam enthalpies from IAPWS-IF97 steam tables.
STEAM = {
    # pressure bar: (T_sat C, h_f kJ/kg, h_g kJ/kg)
    3.5: (138.9, 584.3, 2732.0),
    5: (151.8, 640.1, 2748.1),
    10: (179.9, 762.7, 2777.1),
    24: (221.8, 952.0, 2801.5),
    40: (250.4, 1087.4, 2800.9),
    42: (253.3, 1101.6, 2799.9),
    100: (311.0, 1407.9, 2725.5),
    120: (324.7, 1491.3, 2685.6),
}
H_WATER_25C = 104.9  # kJ/kg liquid water at 25 C
H_BFW_105C = 441.2  # kJ/kg deaerated boiler feed water at 105 C
# Superheated steam (IAPWS-IF97, checked with the iapws package)
H_STEAM_40BAR_450C = 3331.0
H_STEAM_120BAR_510C = 3376.8


def steam_raised_t(Q_W, h_steam=H_STEAM_40BAR_450C, h_bfw=H_BFW_105C):
    """kg/s of steam that heat Q (W) can raise from deaerated BFW."""
    return Q_W / ((h_steam - h_bfw) * 1000.0)
