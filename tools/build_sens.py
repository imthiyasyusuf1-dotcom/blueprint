"""Precompute the capacity curve and the sensitivity tornado for every live process and region.

Every number is a real engine run (or, for capex, the same economics function re-evaluated with the
fixed capital moved), so the site never interpolates or invents a value.

    unset PYTHONPATH; ~/.venvs/blueprint/bin/python tools/build_sens.py [pid ...]

Writes site/data/<pid>.sens.json:
  {"swing": 0.3,
   "regions": {"US": {"base": {...}, "curve": [{"x": 0.25, "tpd": .., "fci": .., "lev": .., ...}, ...],
                      "tornado": [{"key": "gas", "label": .., "lo": {...}, "hi": {...}}, ...]}}}
"""
import copy
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import registry  # noqa: E402
from engine import economics as E  # noqa: E402
from engine import prices as PR  # noqa: E402

OUT = os.path.join(ROOT, "site", "data")
CURVE = [0.25, 0.5, 0.7, 1.0, 1.3, 2.0, 3.0, 4.0]  # multiples of the default capacity (input range is 0.25x to 4x)
SWING = 0.30


def headline(r):
    e = r.get("economics") or {}
    c = r.get("carbon") or {}
    val = r.get("validation") or []
    return {
        "tpd": (r.get("capacity") or {}).get("t_per_day"),
        "tpy": (r.get("capacity") or {}).get("t_per_year"),
        "fci": e.get("fci"),
        "lev": e.get("levelised_cost_per_tonne"),
        "cpt": e.get("cost_per_tonne"),
        "npv": e.get("npv"),
        "irr": e.get("irr"),
        "payback": e.get("payback_years"),
        "co2": c.get("total"),
        "checks": [sum(1 for v in val if v.get("pass")), len(val)],
    }


def run_with_prices(pid, region, gas=1.0, elec=1.0, capacity=None):
    """Run the engine with the regional gas and power price scaled. Restores the table afterwards."""
    saved = copy.deepcopy(PR.REGIONS[region])
    try:
        PR.REGIONS[region]["gas_usd_gj_lhv"] = saved["gas_usd_gj_lhv"] * gas
        PR.REGIONS[region]["elec_usd_mwh"] = saved["elec_usd_mwh"] * elec
        return registry.run(pid, capacity_tpd=capacity, region=region)
    finally:
        PR.REGIONS[region].clear()
        PR.REGIONS[region].update(saved)


def capex_case(r, f):
    """Same economics, fixed capital times f (equipment cost uncertainty)."""
    e = r["economics"]
    tpy = r["capacity"]["t_per_year"]
    ev = E.evaluate(e["fci"] * f, e["revenue"], e["raw_materials"], e["utilities"], e["waste_treatment"],
                    e["labour"], life=e["life"], rate=e["rate"], tax=e["tax"], product_tpy=tpy,
                    byproduct_credit=e.get("byproduct_credit") or 0.0)
    out = headline(r)
    out.update({"fci": ev["fci"], "lev": ev["levelised_cost_per_tonne"], "cpt": ev["cost_per_tonne"],
                "npv": ev["npv"], "irr": ev["irr"], "payback": ev["payback_years"]})
    return out


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


def build(pid, cap):
    res = {"swing": SWING, "curve_x": CURVE, "regions": {}}
    for reg in PR.REGIONS:
        base = registry.run(pid, region=reg)
        hb = headline(base)
        # check the base run matches the shipped data file exactly (deterministic engine)
        with open(os.path.join(OUT, f"{pid}.{reg}.json")) as f:
            shipped = json.load(f)
        assert close(hb["lev"], shipped["economics"]["levelised_cost_per_tonne"]), (pid, reg, "base mismatch")
        # the capex re-evaluation at f = 1 must reproduce the engine exactly
        assert close(capex_case(base, 1.0)["lev"], hb["lev"]), (pid, reg, "capex re-eval mismatch")

        curve = []
        for x in CURVE:
            if x == 1.0:
                pt = dict(hb)
            else:
                try:
                    pt = headline(registry.run(pid, capacity_tpd=cap * x, region=reg))
                except Exception as ex:  # a point the engine cannot solve is left out, never guessed
                    print(f"  {pid} {reg} x{x}: skipped ({ex})")
                    continue
            pt["x"] = x
            curve.append(pt)

        tornado = []
        gas_cost = sum(abs(u.get("annual") or 0) for u in (base.get("utilities") or [])
                       if u.get("cost_unit") == "USD/GJ" or "Steam export" in (u.get("label") or ""))
        elec_cost = sum(abs(u.get("annual") or 0) for u in (base.get("utilities") or []) if u.get("label") == "Electricity")
        cases = []
        if gas_cost > 0:
            cases.append(("gas", "Natural gas price", lambda f: headline(run_with_prices(pid, reg, gas=f))))
        if elec_cost > 0:
            cases.append(("power", "Power price", lambda f: headline(run_with_prices(pid, reg, elec=f))))
        cases.append(("capacity", "Plant capacity", lambda f: next(p for p in curve if p["x"] == round(f, 2))))
        cases.append(("capex", "Capital cost", lambda f: capex_case(base, f)))
        for key, label, fn in cases:
            try:
                lo, hi = fn(1 - SWING), fn(1 + SWING)
            except StopIteration:
                continue
            tornado.append({"key": key, "label": label, "lo": lo, "hi": hi})
        tornado.sort(key=lambda t: -abs((t["hi"]["lev"] or 0) - (t["lo"]["lev"] or 0)))
        res["regions"][reg] = {"base": hb, "curve": curve, "tornado": tornado}
    return res


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, float):
        return float("{:.6g}".format(o)) if math.isfinite(o) else None
    return o


def main(only=None):
    for pid, label, cap, _ in registry.PROCESSES:
        if not registry.available(pid) or (only and pid not in only):
            continue
        t = time.time()
        res = clean(build(pid, cap))
        with open(os.path.join(OUT, f"{pid}.sens.json"), "w") as f:
            json.dump(res, f, separators=(",", ":"))
        us = res["regions"]["US"]
        print(f"{pid:18s} {time.time() - t:5.1f}s  curve {len(us['curve'])}/{len(CURVE)}  tornado "
              + ", ".join(f"{x['key']} {x['lo']['lev']:.0f}..{x['hi']['lev']:.0f}" for x in us["tornado"]))


if __name__ == "__main__":
    main(sys.argv[1:] or None)
