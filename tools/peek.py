"""Quick look at one design: python tools/peek.py ammonia [capacity]"""
import importlib
import sys

sys.path.insert(0, ".")
pid = sys.argv[1]
mod = importlib.import_module(f"engine.processes.{pid}")
kw = {"capacity_tpd": float(sys.argv[2])} if len(sys.argv) > 2 else {}
r = mod.design(**kw)
f = lambda x: f"{x:,.3g}" if isinstance(x, (int, float)) else str(x)
print("cap", f(r["capacity"]["t_per_day"]), "t/d")
for k in r["kpis"]:
    print(" kpi", k["label"], f(k["value"]), k["unit"])
for c in r["conditions"]:
    print(" cond", c)
for v in r["validation"]:
    print(" VAL", "PASS" if v["pass"] else ("fail" if v["pass"] is False else "-"), f(v["model"]), "vs", v["published"],
          f"{(v['error_pct'] or 0):+.1f}%", v["metric"][:60])
b = r["balance"]
print("closure %", f(b["closure_pct"]), {a: round(e, 3) for a, e in b["atom_error_pct"].items()})
e = r["economics"]
print("FCI $M", f(r["capex"]["fixed_capital"] / 1e6), "| rev", f(e["revenue"] / 1e6), "COM", f(e["com"] / 1e6),
      "NPV", f(e["npv"] / 1e6), "IRR", e["irr"], "payback", e["payback_years"])
print("cost/t", f(e.get("cost_per_tonne")), "levelised", f(e.get("levelised_cost_per_tonne")))
for k, v in e["com_breakdown"].items():
    print("   com", k, f(v / 1e6))
c = r["carbon"]
print("carbon t/t", {k: round(v, 3) for k, v in c.items() if isinstance(v, float)})
en = r["energy"]
print("energy", {k: f(en[k]) for k in ["fuel_GJ_h", "fuel_credit_GJ_h", "power_kW", "steam_import_kg_h", "steam_export_kg_h", "cooling_kW"]})
for s in en["steam_items"]:
    print("   ", s)
for x in r["equipment"]:
    print(" EQ", x["tag"], x["label"], f(x["size"]), x["unit"], "x" + str(x["units_parallel"]), "$M", f(x["bare_module"] / 1e6),
          "" if x["in_range"] else "OUT OF RANGE")
for x in r["capex"]["extra_items"]:
    print(" EXTRA", x)
for u in r["utilities"]:
    print(" UT", u["label"], f(u["per_h"]), u["unit"], "/h  $M/y", f(u["annual"] / 1e6))
for m in r["raw_materials"] + r["byproducts"]:
    print(" RM/BY", m["id"], f(m["t_per_t"]), "t/t", f(m["annual_usd"] / 1e6))
print("hazards", [h["id"] for h in r["hazards"]], [p["hazard"] for p in r["process_hazards"]])
