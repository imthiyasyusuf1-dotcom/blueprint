"""Prices, utilities and emission factors used by every design.

All numbers come from research/prices.json, where each entry has the
source URL and a verbatim quote. This module only converts units.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "data", "prices.json")) as _f:
    RAW = json.load(_f)

MMBTU_GJ = 1.055056  # GJ per MMBtu (exact definition basis)
HHV_TO_LHV_GAS = 0.9025  # natural gas LHV/HHV (methane: 802.6/889.0 kJ/mol)
GAL_L = 3.785411784
BUSHEL_CORN_KG = 25.401  # 56 lb
SHORT_TON_KG = 907.185

P = RAW["prices"]


def _v(key):
    return P[key]["value"]


# product and raw material prices, USD per tonne
PRICE_T = {
    "NH3": _v("ammonia"),
    "MeOH": _v("methanol"),
    "EtOH": P["ethanol_fuel"]["value_usd_per_t"],
    "H2_grey": _v("hydrogen_grey") * 1000,
    "H2_green": _v("hydrogen_green") * 1000,
    "H2SO4": _v("sulphuric_acid"),
    "S": _v("sulphur"),
    "ASA": _v("acetylsalicylic_acid"),
    "SalAcid": _v("salicylic_acid"),
    "Ac2O": _v("acetic_anhydride"),
    "AcOH": _v("acetic_acid"),
    "Urea": _v("urea"),
    "HNO3": _v("nitric_acid"),
    "C2H4": _v("ethylene"),
    "EO": _v("ethylene_oxide"),
    "EB": _v("ethylbenzene"),
    "Styrene": _v("styrene"),
    "FAME": _v("biodiesel_fame"),
    "Triolein": _v("soybean_oil"),
    "Glycerol": _v("crude_glycerol"),
    "Corn": P["corn"]["value_usd_per_t"],
    "DDGS": P["ddgs"]["value_usd_per_t"],
    "CO2": _v("co2"),
}

REGIONS = {
    "US": {
        "label": "United States",
        "gas_usd_gj_lhv": _v("natural_gas_henry_hub") / MMBTU_GJ / HHV_TO_LHV_GAS,
        "elec_usd_mwh": _v("electricity_us_industrial"),
        "grid_kg_kwh": RAW["emission_factors"]["grid_us"]["value"],
    },
    "EU": {
        "label": "European Union",
        "gas_usd_gj_lhv": _v("natural_gas_ttf") / MMBTU_GJ / HHV_TO_LHV_GAS,
        "elec_usd_mwh": _v("electricity_eu_industrial"),
        "grid_kg_kwh": RAW["emission_factors"]["grid_eu"]["value"],
    },
    "UK": {
        "label": "United Kingdom",
        "gas_usd_gj_lhv": _v("natural_gas_ttf") / MMBTU_GJ / HHV_TO_LHV_GAS,
        "elec_usd_mwh": _v("electricity_uk_industrial"),
        "grid_kg_kwh": RAW["emission_factors"]["grid_uk"]["value"],
    },
}

# Utilities (Ulrich and Vasudevan 2006 method, CEPCI 800.3, as derived in research)
COOLING_WATER_USD_M3 = P["cooling_water"]["alt"]["value"]
PROCESS_WATER_USD_M3 = P["process_water"]["value"]
DEMIN_WATER_USD_M3 = 6.62
STEAM_USD_T = P["steam"]["alt"]["value"]

# natural gas combustion, kg CO2 per GJ (LHV basis)
NG_KG_CO2_GJ_LHV = RAW["emission_factors"]["natural_gas_combustion"]["value"] / HHV_TO_LHV_GAS


def region(r="US"):
    return REGIONS.get(r, REGIONS["US"])


def source(key):
    e = P.get(key) or RAW["emission_factors"].get(key) or RAW["product_footprints"].get(key)
    if not e:
        return None
    return {"value": e.get("value"), "unit": e.get("unit"), "basis": e.get("basis"),
            "year": e.get("year"), "source": e.get("source"), "url": e.get("url")}


PRICE_KEYS = {
    "NH3": "ammonia", "MeOH": "methanol", "EtOH": "ethanol_fuel", "H2_grey": "hydrogen_grey",
    "H2_green": "hydrogen_green", "H2SO4": "sulphuric_acid", "S": "sulphur",
    "ASA": "acetylsalicylic_acid", "SalAcid": "salicylic_acid", "Ac2O": "acetic_anhydride",
    "AcOH": "acetic_acid", "Urea": "urea", "HNO3": "nitric_acid", "C2H4": "ethylene",
    "EO": "ethylene_oxide", "EB": "ethylbenzene", "Styrene": "styrene", "FAME": "biodiesel_fame",
    "Triolein": "soybean_oil", "Glycerol": "crude_glycerol", "Corn": "corn", "DDGS": "ddgs",
    "CO2": "co2",
}


def price_source(cid):
    return source(PRICE_KEYS[cid])
