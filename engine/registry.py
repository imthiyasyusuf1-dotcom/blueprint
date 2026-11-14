"""Process registry: which chemicals Blueprint can design, and the words people type for them.

A process is live when engine/processes/<id>.py exists and exposes design(capacity_tpd=None, region="US", **params).
Anything else that matches a known chemical is shown as "coming soon" with request capture.
"""
import importlib

PROCESSES = [
    # id, product label, default t/d, aliases (lower case)
    ("ammonia", "Ammonia", 2000, ["ammonia", "nh3", "haber", "haber bosch", "anhydrous ammonia"]),
    ("methanol", "Methanol", 2500, ["methanol", "meoh", "ch3oh", "methyl alcohol", "wood alcohol"]),
    ("hydrogen", "Hydrogen", 100, ["hydrogen", "h2", "grey hydrogen", "smr", "steam methane reforming", "blue hydrogen"]),
    ("urea", "Urea", 2000, ["urea", "carbamide", "co(nh2)2", "fertiliser", "fertilizer"]),
    ("nitric_acid", "Nitric acid", 1000, ["nitric acid", "hno3", "ostwald", "aqua fortis"]),
    ("sulphuric_acid", "Sulphuric acid", 2000, ["sulphuric acid", "sulfuric acid", "h2so4", "contact process", "oil of vitriol"]),
    ("ethanol", "Ethanol", 1000, ["ethanol", "bioethanol", "etoh", "c2h5oh", "ethyl alcohol", "fuel ethanol", "corn ethanol"]),
    ("biodiesel", "Biodiesel", 300, ["biodiesel", "fame", "fatty acid methyl ester", "rme", "transesterification"]),
    ("ethylene_oxide", "Ethylene oxide", 1000, ["ethylene oxide", "eo", "c2h4o", "oxirane", "epoxyethane"]),
    ("styrene", "Styrene", 1500, ["styrene", "styrene monomer", "sm", "vinylbenzene", "phenylethene", "c8h8"]),
    ("aspirin", "Aspirin", 10, ["aspirin", "acetylsalicylic acid", "asa", "c9h8o4"]),
    # batch A
    ("chlor_alkali", "Chlorine and caustic soda", 500, ["chlor alkali", "chloralkali", "chlorine", "cl2", "caustic soda",
                                                        "sodium hydroxide", "naoh", "caustic", "lye", "membrane cell",
                                                        "brine electrolysis", "chlorine caustic"]),
    ("hydrogen_peroxide", "Hydrogen peroxide", 200, ["hydrogen peroxide", "h2o2", "peroxide", "perhydrol",
                                                     "anthraquinone process", "ao process"]),
    ("e_methanol", "e-Methanol", 300, ["e methanol", "emethanol", "green methanol", "renewable methanol",
                                       "power to methanol", "co2 to methanol", "electro methanol", "synthetic methanol"]),
    ("ammonium_nitrate", "Ammonium nitrate", 1200, ["ammonium nitrate", "nh4no3", "an fertiliser", "an fertilizer",
                                                    "nitram", "prilled ammonium nitrate"]),
    ("soda_ash", "Soda ash", 1000, ["soda ash", "sodium carbonate", "na2co3", "solvay", "solvay process",
                                    "ammonia soda process", "washing soda"]),
]

# Recognised but not yet modelled. Shown as coming soon so the request is captured.
COMING_SOON = [
    "acetic acid", "acetone", "acrylic acid", "adipic acid", "benzene", "bisphenol a", "butadiene", "caprolactam",
    "chlorine", "caustic soda", "sodium hydroxide", "cumene", "dimethyl ether", "ethylene", "ethylene glycol",
    "formaldehyde", "green ammonia", "green hydrogen", "hydrogen peroxide", "isopropanol", "maleic anhydride",
    "melamine", "mtbe", "nylon", "paracetamol", "phenol", "phosphoric acid", "polyethylene", "polypropylene",
    "propylene", "propylene oxide", "pta", "terephthalic acid", "soda ash", "sodium carbonate", "titanium dioxide",
    "toluene", "vinyl chloride", "pvc", "xylene", "e-methanol", "sustainable aviation fuel", "saf", "lithium hydroxide",
    "ammonium nitrate", "glycerol", "lactic acid", "succinic acid", "butanol", "hydrochloric acid",
]


def _norm(s):
    return " ".join(s.lower().replace("-", " ").replace("_", " ").split())


def available(pid):
    try:
        importlib.import_module(f"engine.processes.{pid}")
        return True
    except ImportError:
        return False


def match(query):
    """Return ("live", pid) | ("soon", name) | ("unknown", query)."""
    q = _norm(query)
    for pid, label, _, aliases in PROCESSES:
        if q == _norm(label) or q in aliases:
            return ("live" if available(pid) else "soon", pid)
    if q in COMING_SOON:
        return ("soon", q)
    for pid, label, _, aliases in PROCESSES:
        if any(a in q for a in aliases if len(a) > 3):
            return ("live" if available(pid) else "soon", pid)
    for name in COMING_SOON:
        if q == name or (len(q) > 3 and q in name):
            return ("soon", name)
    return ("unknown", query)


def run(pid, capacity_tpd=None, region="US", **params):
    mod = importlib.import_module(f"engine.processes.{pid}")
    return mod.design(capacity_tpd=capacity_tpd, region=region, **params)


def defaults(pid):
    mod = importlib.import_module(f"engine.processes.{pid}")
    return dict(getattr(mod, "DEFAULTS", {}))
