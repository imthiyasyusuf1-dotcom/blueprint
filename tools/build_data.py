"""Build the JSON the website reads: site/data/<id>.json for every live process at its default
capacity in each region, plus site/data/index.json (catalogue + aliases + coming soon list).

    unset PYTHONPATH; ~/.venvs/blueprint/bin/python tools/build_data.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import registry  # noqa: E402
from engine.prices import REGIONS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "data")


def main(only=None):
    os.makedirs(OUT, exist_ok=True)
    cat = []
    for pid, label, cap, aliases in registry.PROCESSES:
        live = registry.available(pid)
        entry = {"id": pid, "label": label, "default_tpd": cap, "aliases": aliases, "live": live}
        if live and (not only or pid in only):
            for reg in REGIONS:
                t = time.time()
                r = registry.run(pid, region=reg)
                with open(os.path.join(OUT, f"{pid}.{reg}.json"), "w") as f:
                    json.dump(r, f, separators=(",", ":"))
                ok = [v for v in r["validation"] if v["pass"]]
                print(f"{pid:16s} {reg} {time.time() - t:5.1f}s  validation {len(ok)}/{len(r['validation'])} pass")
            entry["params"] = registry.defaults(pid)
            entry["summary"] = r["summary"]
        cat.append(entry)
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump({"processes": cat, "coming_soon": registry.COMING_SOON, "regions": {k: v["label"] for k, v in REGIONS.items()}},
                  f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
