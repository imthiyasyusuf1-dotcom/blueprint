# Blueprint engine: how to add a process

Blueprint turns a chemical name into a first pass plant design. The engine is plain Python
(standard library only, so it also runs in the browser through Pyodide). Every number must
come from a calculation or a cited source. Never invent data.

Run things with:

    cd ~/Desktop/Blah\ Projects/blueprint
    unset PYTHONPATH            # REQUIRED, otherwise numpy/thermo imports break
    ~/.venvs/blueprint/bin/python tools/peek.py <process_id> [capacity_tpd]
    ~/.venvs/blueprint/bin/python tools/build_data.py [process_id ...]

Reference implementations: `engine/processes/ammonia.py` and `engine/processes/methanol.py`.
Copy their structure.

## Files you may edit

- `engine/processes/<id>.py` (your process). One file per process.
- New species: add to the species list in `tools/build_components.py` then re-run it
  (rebuilds `engine/data/components.json`). Append only; do not change existing entries.
- Do NOT edit `engine/core.py`, `engine/design.py`, `engine/cost.py`, `engine/thermo.py`,
  `engine/economics.py`, `engine/prices.py` or `engine/registry.py`. If you need a helper, put it
  in your process file. If something in the shared code is truly wrong, leave a comment on your
  kanban card starting `hotspot:` and work around it.

## Process module contract

```python
DEFAULTS = {"capacity_tpd": ..., <every user adjustable parameter with a sensible industrial default>}

def design(capacity_tpd=None, region="US", **over) -> dict:
    p = dict(DEFAULTS); p.update(...)
    d = Design("<id>", "<title>", "<Product>", p["capacity_tpd"], region)
    ...
    return d.finish()
```

`design()` must hit the requested capacity exactly (scale the feed and re-solve) and run in
under about 5 s.

## Toolbox (see source for details)

- `core.Stream`, `core.add`, `core.scale`, `core.h_molar(cid, T, phase)`, `core.hin(flows, T)` (kW),
  `core.equilibrium(flows, [rxn dicts], T, P)` ideal gas Gibbs equilibrium,
  `core.adiabatic_eq(...)`, `core.adiabatic_T(H_kW, flows, P, T_guess)`, `core.psat(cid, T)` (bar, Antoine fit),
  `core.condense(flows, T, P, condensables)` Raoult flash, `core.rho_gas`, `core.gas_volume_m3_h`.
- `thermo`: `MW`, `Kp(rxn, T)`, `dh_rxn_gas`, `lhv_molar`, `hvap`, `cp_liq`, steam constants
  `H_STEAM_120BAR_510C`, `H_STEAM_40BAR_450C`, `H_BFW_105C`.
- Units everywhere: kmol/h, K, bar absolute, kW.
- Design object (`engine/design.py`):
  - streams `d.stream(name, flows, T, P, phase)`; units `d.unit(id, name, kind, ins, outs, pos=(col,row), duty_kW=...)`
    where kind is one of furnace, reactor, exchanger, drum, column, compressor, pump, tank, other.
  - plant boundary: `d.feed(stream, priced={cid: price_key})`, `d.out(stream, "product"|"byproduct"|"waste"|"emission"|"fuel", sell={cid: price_key})`.
    Mass and atom balances are checked automatically over these boundary streams; they must close (< 0.1%).
  - utilities: `d.fuel(GJ_h, label, co2=True)`, `d.fuel_credit(...)`, `d.power(kW, label)`, `d.steam(kg_h, label)` (+ use, - raise),
    `d.cooling(kW)`, `d.process_water_m3_h`, `d.demin_water_m3_h`.
  - equipment, sized from the balance and costed by Turton: `d.hx`, `d.cooler_cw`, `d.vessel`, `d.flash_drum`,
    `d.reactor_bed`, `d.compressor`, `d.pump`, `d.column`, `d.tank`, `d.heater`, `d.generic(tag, name, kind, size, ...)`
    (kinds are the keys of `cost.K`), and `d.lump(label, usd, note)` for packaged items priced from a cited source.
  - text: `d.route`, `d.summary`, `d.reactions`, `d.conditions`, `d.kpis`, `d.assumptions`, `d.hazop` (4 to 6 rows),
    `d.greener` (lower carbon route), `d.solids_steps` (number of solids handling steps, for labour).
  - validation: `d.check(metric, model_value, published, unit, source, url, tol=..., kind="process"|"thermo"|"capex"|"cost")`.
    Use `model=None` with kind capex (compares fixed capital) or cost (compares levelised USD/t).
    Published figures MUST come from `engine/data/benchmarks.json` (quote, source, url are there).
    Aim for at least 3 checks per process, all passing honestly. Never tune a parameter outside its
    normal industrial range just to pass; if a check fails, find the modelling reason.
- Prices: price keys in `engine/prices.PRICE_T` (USD/t). Gas, power, cooling water and steam are
  regional utilities, do not price them as raw materials.

## Quality bar

- Mass and atom balance closure under 0.1%.
- Every stream on the flow diagram connected (src and dst are unit ids, "IN", "OUT" or "mix").
- KPIs a chemical engineer would look for (yield, selectivity, specific energy, conversion).
- No em or en dashes anywhere in text.
