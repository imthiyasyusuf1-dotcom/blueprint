"""Hazard summary.

GHS hazard statements are the harmonised EU CLP (Regulation 1272/2008,
Annex VI) classifications for the pure substances, summarised. They are a
screening aid only: always use the supplier safety data sheet.
Flash point, autoignition and flammable limits come from the `chemicals`
package database (components.json).
"""
from . import thermo as th

H_TEXT = {
    "H220": "Extremely flammable gas",
    "H221": "Flammable gas",
    "H225": "Highly flammable liquid and vapour",
    "H226": "Flammable liquid and vapour",
    "H230": "May react explosively even without air",
    "H270": "May cause or intensify fire; oxidiser",
    "H272": "May intensify fire; oxidiser",
    "H280": "Contains gas under pressure; may explode if heated",
    "H290": "May be corrosive to metals",
    "H301": "Toxic if swallowed",
    "H302": "Harmful if swallowed",
    "H304": "May be fatal if swallowed and enters airways",
    "H311": "Toxic in contact with skin",
    "H314": "Causes severe skin burns and eye damage",
    "H315": "Causes skin irritation",
    "H318": "Causes serious eye damage",
    "H319": "Causes serious eye irritation",
    "H330": "Fatal if inhaled",
    "H331": "Toxic if inhaled",
    "H332": "Harmful if inhaled",
    "H335": "May cause respiratory irritation",
    "H336": "May cause drowsiness or dizziness",
    "H340": "May cause genetic defects",
    "H350": "May cause cancer",
    "H360D": "May damage the unborn child",
    "H360Fd": "May damage fertility; suspected of damaging the unborn child",
    "H361d": "Suspected of damaging the unborn child",
    "H370": "Causes damage to organs",
    "H372": "Causes damage to organs through prolonged or repeated exposure",
    "H373": "May cause damage to organs through prolonged or repeated exposure",
    "H400": "Very toxic to aquatic life",
    "H411": "Toxic to aquatic life with long lasting effects",
    "ASPH": "Simple asphyxiant in confined spaces",
    "DUST": "Combustible dust",
}

GHS = {
    "NH3": ["H221", "H280", "H314", "H331", "H400"],
    "CH4": ["H220", "H280"],
    "H2": ["H220", "H280"],
    "CO": ["H220", "H280", "H331", "H360D", "H372"],
    "CO2": ["H280", "ASPH"],
    "N2": ["H280", "ASPH"],
    "Ar": ["H280", "ASPH"],
    "O2": ["H270", "H280"],
    "MeOH": ["H225", "H301", "H311", "H331", "H370"],
    "EtOH": ["H225", "H319"],
    "H2SO4": ["H314"],
    "SO2": ["H280", "H314", "H331"],
    "SO3": ["H314", "H335"],
    "S": ["H315", "DUST"],
    "HNO3": ["H272", "H290", "H314", "H331"],
    "NO2": ["H270", "H280", "H314", "H330"],
    "NO": ["H270", "H280", "H314", "H330"],
    "N2O": ["H270", "H280"],
    "Urea": [],
    "SalAcid": ["H302", "H318", "H361d"],
    "Ac2O": ["H226", "H302", "H314", "H330"],
    "AcOH": ["H226", "H314"],
    "ASA": ["H302", "DUST"],
    "C2H4": ["H220", "H280", "H336"],
    "EO": ["H220", "H230", "H280", "H301", "H314", "H331", "H340", "H350", "H360Fd", "H372"],
    "EB": ["H225", "H304", "H332", "H373"],
    "Styrene": ["H226", "H315", "H319", "H332", "H361d", "H372"],
    "Benzene": ["H225", "H304", "H315", "H319", "H340", "H350", "H372"],
    "Toluene": ["H225", "H304", "H315", "H336", "H361d", "H373"],
    "Triolein": [],
    "FAME": [],
    "Glycerol": [],
    "NaOH": ["H290", "H314"],
    "KOH": ["H290", "H302", "H314"],
    "Glucose": [],
    "H2O": [],
}

SEVERE = {"H220", "H221", "H225", "H230", "H270", "H272", "H314", "H330", "H331", "H340", "H350", "H360D", "H360Fd"}


def assess(design):
    seen = []
    for s in design.streams:
        for c in s.flows:
            if c not in seen:
                seen.append(c)
    comps = []
    for c in seen:
        codes = GHS.get(c, [])
        sf = th.safety(c)
        comps.append({
            "id": c,
            "name": th.name(c),
            "formula": th.formula(c),
            "cas": th.comp(c)["CAS"],
            "ghs": [{"code": k, "text": H_TEXT[k]} for k in codes],
            "severe": any(k in SEVERE for k in codes),
            **sf,
        })
    comps.sort(key=lambda r: (not r["severe"], -len(r["ghs"])))

    # process level flags from the actual flowsheet conditions
    Pmax = max((s.P for s in design.streams), default=1.0)
    Tmax = max((s.T for s in design.streams), default=298.15)
    flam = [c["name"] for c in comps if any(k in ("H220", "H221", "H225", "H226") for k in (x["code"] for x in c["ghs"]))]
    tox = [c["name"] for c in comps if any(k in ("H330", "H331", "H301") for k in (x["code"] for x in c["ghs"]))]
    corr = [c["name"] for c in comps if any(k == "H314" for k in (x["code"] for x in c["ghs"]))]
    flags = []
    if Pmax > 70:
        flags.append({"hazard": "High pressure", "detail": f"Up to {Pmax:.0f} bar. Stored energy and loss of containment risk; "
                      "relief, high integrity pressure protection, regular inspection of vessels and piping."})
    elif Pmax > 10:
        flags.append({"hazard": "Pressure", "detail": f"Up to {Pmax:.0f} bar. Relief valves sized for fire and blocked outlet."})
    if Tmax > 673:
        flags.append({"hazard": "High temperature", "detail": f"Up to {Tmax - 273.15:.0f} C. Creep, hydrogen attack and burns; "
                      "refractory and tube skin temperature monitoring."})
    if flam:
        flags.append({"hazard": "Flammable materials", "detail": ", ".join(flam) + ". Hazardous area classification, "
                      "ignition source control, gas detection, fire protection."})
    if tox:
        flags.append({"hazard": "Toxic materials", "detail": ", ".join(tox) + ". Toxic gas detection, emergency shutdown "
                      "and isolation, escape sets, minimise inventory."})
    if corr:
        flags.append({"hazard": "Corrosive materials", "detail": ", ".join(corr) + ". Material selection, "
                      "PPE, safety showers, bunded storage."})
    return {"components": comps, "process": flags}
