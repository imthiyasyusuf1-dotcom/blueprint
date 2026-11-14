"""Build engine/data/components.json from the open source `chemicals`/`thermo` packages.

Run with CPython (needs thermo). The output is plain JSON so the engine can run
with the standard library only (also inside Pyodide in the browser).
"""
import json
import math
import os
import warnings

warnings.filterwarnings("ignore")
from thermo import Chemical  # noqa: E402
from chemicals import heat_capacity  # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "engine", "data", "components.json")

# id: (lookup name, formula for display, display name)
COMPONENTS = {
    "CH4": ("methane", "CH4", "Methane"),
    "H2O": ("water", "H2O", "Water"),
    "H2": ("hydrogen", "H2", "Hydrogen"),
    "N2": ("nitrogen", "N2", "Nitrogen"),
    "O2": ("oxygen", "O2", "Oxygen"),
    "Ar": ("argon", "Ar", "Argon"),
    "CO": ("carbon monoxide", "CO", "Carbon monoxide"),
    "CO2": ("carbon dioxide", "CO2", "Carbon dioxide"),
    "NH3": ("ammonia", "NH3", "Ammonia"),
    "MeOH": ("methanol", "CH3OH", "Methanol"),
    "EtOH": ("ethanol", "C2H5OH", "Ethanol"),
    "Glucose": ("glucose", "C6H12O6", "Glucose"),
    "S": ("sulfur", "S", "Sulphur"),
    "SO2": ("sulfur dioxide", "SO2", "Sulphur dioxide"),
    "SO3": ("sulfur trioxide", "SO3", "Sulphur trioxide"),
    "H2SO4": ("sulfuric acid", "H2SO4", "Sulphuric acid"),
    "NO": ("nitric oxide", "NO", "Nitric oxide"),
    "NO2": ("nitrogen dioxide", "NO2", "Nitrogen dioxide"),
    "HNO3": ("nitric acid", "HNO3", "Nitric acid"),
    "N2O": ("nitrous oxide", "N2O", "Nitrous oxide"),
    "Urea": ("urea", "CH4N2O", "Urea"),
    "SalAcid": ("salicylic acid", "C7H6O3", "Salicylic acid"),
    "Ac2O": ("acetic anhydride", "C4H6O3", "Acetic anhydride"),
    "AcOH": ("acetic acid", "C2H4O2", "Acetic acid"),
    "ASA": ("aspirin", "C9H8O4", "Aspirin (acetylsalicylic acid)"),
    "C2H4": ("ethylene", "C2H4", "Ethylene"),
    "EO": ("ethylene oxide", "C2H4O", "Ethylene oxide"),
    "EB": ("ethylbenzene", "C8H10", "Ethylbenzene"),
    "Styrene": ("styrene", "C8H8", "Styrene"),
    "Benzene": ("benzene", "C6H6", "Benzene"),
    "Toluene": ("toluene", "C7H8", "Toluene"),
    "Triolein": ("triolein", "C57H104O6", "Vegetable oil (as triolein)"),
    "FAME": ("methyl oleate", "C19H36O2", "Biodiesel (as methyl oleate)"),
    "Glycerol": ("glycerol", "C3H8O3", "Glycerol"),
    "NaOH": ("sodium hydroxide", "NaOH", "Sodium hydroxide"),
    "KOH": ("potassium hydroxide", "KOH", "Potassium hydroxide"),
    # batch A (chlor-alkali, hydrogen peroxide, e-methanol, ammonium nitrate, soda ash)
    "Cl2": ("chlorine", "Cl2", "Chlorine"),
    "HCl": ("hydrochloric acid", "HCl", "Hydrogen chloride"),
    "NaCl": ("sodium chloride", "NaCl", "Sodium chloride (salt)"),
    "H2O2": ("hydrogen peroxide", "H2O2", "Hydrogen peroxide"),
    "Na2CO3": ("sodium carbonate", "Na2CO3", "Sodium carbonate (soda ash)"),
    "NaHCO3": ("sodium bicarbonate", "NaHCO3", "Sodium bicarbonate"),
    "CaCO3": ("calcium carbonate", "CaCO3", "Calcium carbonate (limestone)"),
    "CaO": ("calcium oxide", "CaO", "Calcium oxide (quicklime)"),
    "CaOH2": ("calcium hydroxide", "CaO2H2", "Calcium hydroxide (slaked lime)"),
    "CaCl2": ("calcium chloride", "CaCl2", "Calcium chloride"),
    "NH4Cl": ("ammonium chloride", "NH4Cl", "Ammonium chloride"),
    "NH4NO3": ("ammonium nitrate", "N2H4O3", "Ammonium nitrate"),
    "EAQ": ("2-ethylanthraquinone", "C16H12O2", "2-Ethylanthraquinone"),
    "C": ("carbon", "C", "Carbon (coke, as graphite)"),
    # batch B (phenol and acetone, acetic acid, formaldehyde, ethylene, ethylene glycol)
    "C2H6": ("ethane", "C2H6", "Ethane"),
    "C3H6": ("propylene", "C3H6", "Propylene"),
    "C4H6": ("1,3-butadiene", "C4H6", "1,3-Butadiene"),
    "Cumene": ("cumene", "C9H12", "Cumene (isopropylbenzene)"),
    "DIPB": ("1,4-diisopropylbenzene", "C12H18", "Diisopropylbenzene"),
    "CHP": ("cumene hydroperoxide", "C9H12O2", "Cumene hydroperoxide"),
    "Phenol": ("phenol", "C6H6O", "Phenol"),
    "Acetone": ("acetone", "C3H6O", "Acetone"),
    "AMS": ("alpha-methylstyrene", "C9H10", "alpha-Methylstyrene"),
    "HCHO": ("formaldehyde", "CH2O", "Formaldehyde"),
    "MEG": ("ethylene glycol", "C2H6O2", "Monoethylene glycol"),
    "DEG": ("diethylene glycol", "C4H10O3", "Diethylene glycol"),
    "TEG": ("triethylene glycol", "C6H14O4", "Triethylene glycol"),
    # hydrogen peroxide working solution: the aromatic quinone solvent (EU BREF LVOC 2017, 12.3.3 lists
    # trimethylbenzene among the alkylanthraquinone solvents)
    "TMB": ("1,2,4-trimethylbenzene", "C9H12", "1,2,4-Trimethylbenzene (aromatic solvent)"),
    # soda ash: inert limestone impurities (silica and clay), lumped as quartz
    "SiO2": ("silicon dioxide", "SiO2", "Silica (limestone impurities)"),
}

# Standard heats of combustion (lower heating value) are computed by chemicals.

# Liquid heats of formation the packages lack, taken from cited measurements.
HF_STD_CITED = {
    # NIST WebBook, triolein (https://webbook.nist.gov/cgi/cbook.cgi?ID=C122327&Mask=2), from the heat of
    # combustion of Freedman, Bagby et al. (1989): "Corresponding Δ f Hº liquid = -2193.7 kJ/mol"
    "Triolein": (-2193700.0, "NIST WebBook C122327, Freedman, Bagby et al. 1989, liquid"),
    # Graphite is the reference state of carbon, so its standard heat of formation is zero by definition.
    "C": (0.0, "Reference state of the element (graphite), zero by definition"),
}

# Pseudo components that the chemicals package does not hold. Corn is split into starch
# (anhydroglucose units) and the non fermentable solids that leave as distillers grains.
# Starch: heat of formation from solid glucose (NIST, -1273.3 kJ/mol) less liquid water
# (-285.83 kJ/mol), so hydrolysis is taken as thermoneutral. Corn solids pass through
# unreacted, so their heat of formation cancels; Cp about 1.5 kJ/kg K for dry grain.
MANUAL = {
    "Starch": {"id": "Starch", "name": "Starch (as anhydroglucose)", "formula": "C6H10O5", "CAS": "9005-25-8",
               "MW": 162.1406, "Tb": None, "Tm": None, "Tc": None, "Pc": None, "omega": None,
               "Hf_gas": -987470.0, "Gf_gas": None, "S0_gas": None, "Hf_std": -987470.0, "phase_298": "s",
               "Hvap_Tb": None, "Hvap_298": None, "LHV": None, "Cp_liquid_298": 243.0, "Cp_solid_298": 243.0,
               "rho_298": 1500.0, "flash_point_K": None, "autoignition_K": None, "LFL": None, "UFL": None,
               "TWA": None, "STEL": None, "cp_gas": None, "antoine": None},
    "CornSolids": {"id": "CornSolids", "name": "Corn protein, fibre, oil and ash", "formula": "C6H10O5", "CAS": "",
                   "MW": 162.1406, "Tb": None, "Tm": None, "Tc": None, "Pc": None, "omega": None,
                   "Hf_gas": -987470.0, "Gf_gas": None, "S0_gas": None, "Hf_std": -987470.0, "phase_298": "s",
                   "Hvap_Tb": None, "Hvap_298": None, "LHV": None, "Cp_liquid_298": 243.0, "Cp_solid_298": 243.0,
                   "rho_298": 1300.0, "flash_point_K": None, "autoignition_K": None, "LFL": None, "UFL": None,
                   "TWA": None, "STEL": None, "cp_gas": None, "antoine": None},
}

# Liquid Cp method overrides (component: (method, T in K)). The VDI table thermo picks for phenol
# gives about 850 J/mol K, four times the real value; phenol melts at 41 C, so the corresponding
# states (Rowlinson-Poling) value is taken just above the melt and used for the molten liquid.
CP_LIQ_METHOD = {"Phenol": ("ROWLINSON_POLING", 319.15)}


def fit_cp(chem, T_lo=298.15, T_hi=1200.0, n=40):
    """Least squares fit Cp_ig [J/mol/K] = a + bT + cT^2 + dT^3 over T_lo..T_hi."""
    Ts, Cps = [], []
    for i in range(n):
        T = T_lo + (T_hi - T_lo) * i / (n - 1)
        try:
            v = chem.HeatCapacityGas.T_dependent_property(T)
        except Exception:
            v = None
        if v is not None and v == v:
            Ts.append(T)
            Cps.append(v)
    if len(Ts) < 6:
        return None
    # normal equations for cubic, scaled T
    s = 1000.0
    X = [[1, t / s, (t / s) ** 2, (t / s) ** 3] for t in Ts]
    A = [[sum(r[i] * r[j] for r in X) for j in range(4)] for i in range(4)]
    bvec = [sum(X[k][i] * Cps[k] for k in range(len(Ts))) for i in range(4)]
    # gaussian elimination
    M = [A[i] + [bvec[i]] for i in range(4)]
    for i in range(4):
        p = max(range(i, 4), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(4):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [M[r][c] - f * M[i][c] for c in range(5)]
    coef = [M[i][4] / M[i][i] for i in range(4)]
    a, b, c, d = coef[0], coef[1] / s, coef[2] / s ** 2, coef[3] / s ** 3
    err = max(abs((a + b * t + c * t * t + d * t ** 3) - cp) / cp for t, cp in zip(Ts, Cps))
    return {"a": a, "b": b, "c": c, "d": d, "Tmin": Ts[0], "Tmax": Ts[-1], "max_rel_err": err}


def fit_antoine(chem):
    """ln P(Pa) = A - B / (T + C) fitted to thermo's recommended vapour pressure
    correlation between max(Tm, 0.5 Tb) and 0.95 Tc. Returns dict or None."""
    try:
        import numpy as np
        from scipy.optimize import curve_fit
        Tc = chem.Tc
        Tb = chem.Tb
        if not (Tc and Tb):
            return None
        # fit where process models use it: from the melting point (or 0.6 Tb) up to 1.35 Tb
        lo = max(chem.Tm or 0.0, 0.6 * Tb, 150.0)
        hi = min(0.95 * Tc, 1.35 * Tb)
        if hi <= lo + 10:
            return None
        Ts = np.linspace(lo, hi, 60)
        P = np.array([chem.VaporPressure(T) for T in Ts], dtype=float)
        ok = np.isfinite(P) & (P > 0)
        Ts, P = Ts[ok], P[ok]
        if len(Ts) < 10:
            return None
        f = lambda T, A, B, C: A - B / (T + C)
        p, _ = curve_fit(f, Ts, np.log(P), p0=[22.0, 3000.0, -40.0], maxfev=20000)
        err = float(np.max(np.abs(np.exp(f(Ts, *p)) / P - 1)))
        return {"A": float(p[0]), "B": float(p[1]), "C": float(p[2]), "Tmin": float(lo), "Tmax": float(hi),
                "max_rel_err": err}
    except Exception:
        return None


def num(x):
    if x is None:
        return None
    try:
        x = float(x)
    except Exception:
        return None
    return None if x != x else x


def main():
    out = {}
    for cid, (name, formula, disp) in COMPONENTS.items():
        c = Chemical(name, T=298.15, P=101325)
        rec = {
            "id": cid,
            "name": disp,
            "formula": formula,
            "CAS": c.CAS,
            "MW": c.MW,
            "Tb": num(c.Tb),
            "Tm": num(c.Tm),
            "Tc": num(c.Tc),
            "Pc": num(c.Pc),
            "omega": num(c.omega),
            "Hf_gas": num(c.Hfgm),  # J/mol ideal gas 298 K
            "Gf_gas": num(c.Gfgm),
            "S0_gas": num(c.S0gm),
            "Hf_std": num(c.Hfm),  # J/mol standard state
            "phase_298": c.phase,
            "Hvap_Tb": num(c.Hvapm) if c.phase == "g" else None,
            "Hvap_298": None,
            "LHV": None,
            "Cp_liquid_298": None,
            "Cp_solid_298": None,
            "rho_298": num(c.rho),
            "flash_point_K": num(c.Tflash),
            "autoignition_K": num(c.Tautoignition),
            "LFL": num(c.LFL),
            "UFL": num(c.UFL),
            "TWA": None,
            "STEL": None,
            "cp_gas": fit_cp(c),
        }
        try:
            rec["Hvap_298"] = num(c.EnthalpyVaporization(298.15))
        except Exception:
            pass
        if rec["Hvap_298"] is None and rec["Tb"]:
            try:
                rec["Hvap_298"] = num(c.EnthalpyVaporization(min(298.15, rec["Tb"])))
            except Exception:
                pass
        try:
            rec["Hvap_Tb"] = num(c.EnthalpyVaporization(c.Tb)) if c.Tb else None
        except Exception:
            pass
        try:
            rec["LHV"] = num(c.Hcm_lower) if c.Hcm_lower else None  # J/mol, negative
        except Exception:
            pass
        try:
            if cid in CP_LIQ_METHOD:
                m, T = CP_LIQ_METHOD[cid]
                rec["Cp_liquid_298"] = num(c.HeatCapacityLiquid.calculate(T, m))
            else:
                rec["Cp_liquid_298"] = num(c.HeatCapacityLiquid.T_dependent_property(298.15))
        except Exception:
            pass
        try:
            rec["Cp_solid_298"] = num(c.HeatCapacitySolid.T_dependent_property(298.15))
        except Exception:
            pass
        try:
            t = c.TWA
            rec["TWA"] = list(t) if t else None
        except Exception:
            pass
        try:
            s = c.STEL
            rec["STEL"] = list(s) if s else None
        except Exception:
            pass
        rec["antoine"] = fit_antoine(c)
        out[cid] = rec
    out.update(MANUAL)
    for cid, (hf, why) in HF_STD_CITED.items():
        out[cid]["Hf_std"] = hf
        out[cid]["Hf_std_source"] = why
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    meta = {
        "_source": "Generated from the open source Python packages chemicals and thermo (Caleb Bell, MIT licence). "
        "Ideal gas Cp fitted as a cubic in T over 298 to 1200 K.",
    }
    with open(OUT, "w") as f:
        json.dump({"_meta": meta, "components": out}, f, indent=1)
    for cid, r in out.items():
        cp = r["cp_gas"]
        print(f"{cid:9s} MW {r['MW']:8.3f} Hfg {r['Hf_gas']} Hfstd {r['Hf_std']} ph {r['phase_298']} "
              f"Hv298 {r['Hvap_298']} LHV {r['LHV']} cp_err {cp and round(cp['max_rel_err'],4)} "
              f"Cpl {r['Cp_liquid_298']} Cps {r['Cp_solid_298']}")


if __name__ == "__main__":
    main()
