"""Design object shared by every process model.

A process module builds streams and units, sizes and costs equipment through
the helper methods here, then calls finish() which returns one plain dict that
the website and the PDF both render.
"""
import math

from . import core
from . import cost as C
from . import economics as E
from . import hazards as HZ
from . import prices as PR
from . import thermo as th

ENGINE_VERSION = "1.0.0"

# Overall heat transfer coefficients, W/m2/K (typical design values,
# Sinnott and Towler, Chemical Engineering Design, Table 19.1 ranges, mid points)
U = {
    "gas-gas": 50,
    "gas-water": 120,
    "wet-gas": 300,  # gas with condensing steam
    "hp-gas": 350,  # gas to gas above about 100 bar
    "gas-steam": 150,
    "boiler": 250,
    "condenser": 700,
    "liquid-liquid": 500,
    "liquid-water": 600,
    "liquid-steam": 900,
    "reboiler": 1100,
    "air": 40,
}


class Design:
    def __init__(self, pid, title, product, capacity_tpd, region="US", hours=E.HOURS_PER_YEAR):
        self.pid = pid
        self.title = title
        self.product = product
        self.capacity_tpd = capacity_tpd
        self.region_key = region if region in PR.REGIONS else "US"
        self.region = PR.region(self.region_key)
        self.hours = hours
        self.streams = []
        self.units = []
        self.edges = []
        self.equipment = []
        self.feeds = {}  # cid -> kg/h  (raw materials, priced)
        self.products = {}  # cid -> kg/h (main product)
        self.byproducts = {}  # cid -> kg/h (sold)
        self.wastes = {}  # name -> {cid: kg/h}
        self.waste_cost = {}  # name -> USD per t treated
        self.emissions = {}  # name -> {cid: kg/h} to air
        self.boundary_in = []  # streams entering
        self.boundary_out = []  # streams leaving
        self.fuel_GJ_h = 0.0  # natural gas fuel, LHV
        self.fuel_credit_GJ_h = 0.0  # off gas burnt in place of gas
        self.power_kW = 0.0
        self.power_items = []
        self.steam_import_kg_h = 0.0
        self.steam_export_kg_h = 0.0
        self.steam_items = []
        self.cw_kW = 0.0
        self.process_water_m3_h = 0.0
        self.demin_water_m3_h = 0.0
        self.reactions = []
        self.conditions = []
        self.validation = []
        self.assumptions = []
        self.notes = []
        self.hazop = []
        self.greener = None
        self.alt_carbon = None
        self.solids_steps = 0
        self.route = ""
        self.summary = ""
        self.extra_capex = []  # (label, USD, note) items not covered by Turton
        self.direct_co2_kg_h = 0.0
        self.direct_other = {}  # e.g. N2O kg/h
        self.kpis = []
        self.price_override = {}

    # ------------------------------------------------------------ flowsheet
    def stream(self, name, flows, T, P, phase="g", phases=None, note=""):
        s = core.Stream(f"S{len(self.streams) + 1}", name, flows, T, P, phase, phases, note)
        self.streams.append(s)
        return s

    def unit(self, uid, name, kind, ins=(), outs=(), pos=(0, 0), duty_kW=None, power_kW=None, desc=""):
        u = {
            "id": uid,
            "name": name,
            "kind": kind,
            "pos": pos,
            "duty_kW": None if duty_kW is None else round(duty_kW, 1),
            "power_kW": None if power_kW is None else round(power_kW, 1),
            "desc": desc,
            "in": [s.id for s in ins],
            "out": [s.id for s in outs],
        }
        for s in ins:
            s.dst = uid
        for s in outs:
            s.src = uid
        self.units.append(u)
        return u

    def feed(self, s, priced=None):
        """Mark a stream as entering the plant. priced: {cid: price key} or True."""
        self.boundary_in.append(s)
        s.src = s.src or "IN"
        if priced:
            for c, n in s.flows.items():
                key = priced.get(c) if isinstance(priced, dict) else c
                if key:
                    self.feeds[key] = self.feeds.get(key, 0.0) + n * th.MW(c)

    def out(self, s, role, sell=None, treat_usd_t=2.0):
        """role: product | byproduct | waste | emission. sell: {cid: price key}"""
        self.boundary_out.append(s)
        s.dst = s.dst or "OUT"
        if role == "product":
            for c, n in s.flows.items():
                if sell and c in sell:
                    self.products[sell[c]] = self.products.get(sell[c], 0.0) + n * th.MW(c)
        elif role == "byproduct":
            for c, n in s.flows.items():
                if sell and c in sell:
                    self.byproducts[sell[c]] = self.byproducts.get(sell[c], 0.0) + n * th.MW(c)
        elif role == "emission":
            self.emissions[s.name] = {c: n * th.MW(c) for c, n in s.flows.items()}
            self.direct_co2_kg_h += s.flows.get("CO2", 0.0) * th.MW("CO2")
            if "N2O" in s.flows:
                self.direct_other["N2O"] = self.direct_other.get("N2O", 0.0) + s.flows["N2O"] * th.MW("N2O")
            if "CH4" in s.flows:
                self.direct_other["CH4"] = self.direct_other.get("CH4", 0.0) + s.flows["CH4"] * th.MW("CH4")
        elif role == "waste":
            self.wastes[s.name] = {c: n * th.MW(c) for c, n in s.flows.items()}
            self.waste_cost[s.name] = treat_usd_t

    # ------------------------------------------------------------ utilities
    @property
    def gas_net_GJ_h(self):
        return max(0.0, self.fuel_GJ_h - self.fuel_credit_GJ_h)

    def fuel(self, GJ_h, label, co2=True):
        """Natural gas bought at the regional price. co2=False for feedstock whose carbon is tracked in streams."""
        self.fuel_GJ_h += GJ_h
        self.steam_items.append({"label": label, "fuel_GJ_h": GJ_h})
        if co2:
            self.direct_co2_kg_h += GJ_h * PR.NG_KG_CO2_GJ_LHV

    def fuel_credit(self, GJ_h, label, co2_kg_h=0.0):
        """Off gas burnt in a furnace instead of natural gas; its CO2 is direct."""
        self.fuel_credit_GJ_h += GJ_h
        self.steam_items.append({"label": label, "fuel_GJ_h": -GJ_h})
        self.direct_co2_kg_h += co2_kg_h - GJ_h * PR.NG_KG_CO2_GJ_LHV

    def power(self, kW, label):
        self.power_kW += kW
        self.power_items.append({"label": label, "kW": round(kW, 1)})

    def steam(self, kg_h, label):
        """Positive = consumed (import), negative = raised (export)."""
        if kg_h >= 0:
            self.steam_import_kg_h += kg_h
        else:
            self.steam_export_kg_h += -kg_h
        self.steam_items.append({"label": label, "steam_kg_h": round(kg_h, 1)})

    def cooling(self, kW, label=""):
        self.cw_kW += abs(kW)

    # ------------------------------------------------------------ equipment
    def _add(self, tag, name, kind, size, service, P_barg=0.0, material="CS", D=None, note=""):
        item = C.bare_module(kind, size, P_barg=P_barg, material=material, D_m=D)
        item.update({"tag": tag, "name": name, "service": service, "note": note})
        self.equipment.append(item)
        return item

    def hx(self, tag, name, Q_kW, th_in, th_out, tc_in, tc_out, service="gas-water", P_barg=0.0,
           material="CS", kind=None):
        dt = C.lmtd(th_in, th_out, tc_in, tc_out)
        A = C.hx_area(Q_kW * 1000, U[service], dt)
        kind = kind or ("hx_floating_head" if (th_in - tc_in) > 150 else "hx_fixed_tube")
        note = f"Q {abs(Q_kW):,.0f} kW, LMTD {dt:.0f} K, U {U[service]} W/m2K"
        return self._add(tag, name, kind, max(A, 1.0), f"{abs(Q_kW):,.0f} kW", P_barg, material, note=note)

    def cooler_cw(self, tag, name, Q_kW, T_in, T_out, P_barg=0.0, material="CS", service="gas-water"):
        """Process stream cooled with cooling water 30 to 40 C."""
        self.cooling(Q_kW)
        return self.hx(tag, name, Q_kW, T_in, T_out, 303.15, 313.15, service, P_barg, material)

    def vessel(self, tag, name, V, P_barg=0.0, material="CS", orientation="vertical", LD=3.0, service=""):
        D, L = C.vessel_from_volume(V, LD)
        kind = "vessel_vertical" if orientation == "vertical" else "vessel_horizontal"
        return self._add(tag, name, kind, V, service or f"{V:,.1f} m3, D {D:.1f} m x L {L:.1f} m", P_barg,
                         material, D=D, note=f"D {D:.2f} m, L {L:.2f} m")

    def flash_drum(self, tag, name, s_vap, s_liq_kg_h, P_barg, material="CS"):
        """Vertical knockout drum sized on Souders Brown with K = 0.07 m/s."""
        rho_v = max(core.rho_gas(s_vap), 0.05) if s_vap and s_vap.total else 1.0
        rho_l = 800.0
        u = 0.07 * math.sqrt((rho_l - rho_v) / rho_v)
        Qv = core.gas_volume_m3_h(s_vap.total, s_vap.T, s_vap.P) / 3600 if s_vap else 0.1
        A = Qv / u
        D = max(0.5, math.sqrt(4 * A / math.pi))
        L = max(3 * D, 2.0)
        V = math.pi / 4 * D * D * L
        return self._add(tag, name, "vessel_vertical", V, f"D {D:.1f} m x {L:.1f} m", P_barg, material, D=D,
                         note=f"Souders Brown K 0.07 m/s, gas {Qv:.2f} m3/s")

    def reactor_bed(self, tag, name, gas_kmol_h, GHSV_h, P_barg, material="CS", kind="vessel_vertical"):
        """Catalyst bed vessel. Volume from gas hourly space velocity (Nm3 gas per m3 catalyst per h)."""
        Nm3 = gas_kmol_h * 22.414
        Vcat = Nm3 / GHSV_h
        V = Vcat * 1.25
        D, L = C.vessel_from_volume(V, 2.5)
        it = self._add(tag, name, kind, V, f"{Vcat:,.1f} m3 catalyst", P_barg, material, D=D,
                       note=f"GHSV {GHSV_h:,.0f} 1/h, D {D:.1f} m")
        it["catalyst_m3"] = Vcat
        return it

    def compressor(self, tag, name, s_in, P_out, k=1.4, eta=0.75, driver="electric", stages=None):
        W, n, Q = C.compressor_power(s_in.total * 1000 / 3600, s_in.T, s_in.P, P_out, k, eta, stages)
        self._add(tag, name, "compressor", W, f"{W:,.0f} kW, {n} stage(s), {s_in.P:.0f} to {P_out:.0f} bar",
                  note=f"Polytropic, eta {eta}, intercooled to 40 C")
        if driver == "electric":
            self.power(W / 0.95, name)
        else:
            # steam turbine drive, 30% of steam enthalpy drop converted to work at the shaft
            self._add(tag + "-T", name + " steam turbine", "turbine_steam", W, f"{W:,.0f} kW shaft")
            self.steam(W / (0.30 * (th.H_STEAM_120BAR_510C - th.H_BFW_105C)) * 3600, name + " turbine")
        if n > 1:
            self.cooling(Q / 1000 * (n - 1) / n)
        return W, n

    def pump(self, tag, name, kg_h, rho, dP_bar, material="CS"):
        kW = C.pump_power(kg_h / 3600, rho, dP_bar)
        self._add(tag, name, "pump_centrifugal", max(kW, 1.0), f"{kg_h / rho:,.1f} m3/h, dP {dP_bar:.0f} bar",
                  P_barg=dP_bar, material=material)
        self.power(kW / 0.95, name)
        return kW

    def column(self, tag, name, vap_kmol_h, T, P_bar, stages, MWv, material="CS", tray_eff=0.7, packed=False):
        """Sieve tray column. Diameter from flooding velocity (Fair, F-factor 2.0 Pa^0.5)."""
        rho_v = P_bar * 1e5 * MWv / 1000 / (th.R * T)
        Qv = vap_kmol_h * 1000 * th.R * T / (P_bar * 1e5) / 3600
        u = 2.0 / math.sqrt(rho_v)
        A = Qv / u / 0.85
        D = max(0.6, math.sqrt(4 * A / math.pi))
        n_trays = math.ceil(stages / tray_eff)
        H = n_trays * 0.6 + 4.0
        V = math.pi / 4 * D * D * H
        it = self._add(tag, name, "tower", V, f"D {D:.1f} m x {H:.0f} m, {n_trays} trays", P_bar - 1.013, material,
                       D=D, note=f"{stages} theoretical stages, tray efficiency {tray_eff}")
        if packed:
            self._add(tag + "-P", name + " packing", "packing", V * 0.8, f"{V * 0.8:,.0f} m3")
        else:
            area = math.pi / 4 * D * D
            tr = self._add(tag + "-TR", name + " trays", "trays_sieve", min(area, 12.3), f"{n_trays} trays, D {D:.1f} m",
                           material=material)
            # quantity factor (Turton Eq. A.4): Fq = 1 for N >= 20, otherwise 10^(0.4771 + 0.0816 log N - 0.3473 (log N)^2)
            N = n_trays
            fq = 1.0 if N >= 20 else 10 ** (0.4771 + 0.0816 * math.log10(N) - 0.3473 * math.log10(N) ** 2)
            mult = N * fq * max(1, math.ceil(area / 12.3))
            for k in ("purchased", "bare_module", "bare_module_base"):
                tr[k] *= mult
        return D, H

    def tank(self, tag, name, kg_h, rho, days=14, material="CS", pressurised=False, P_barg=0.0):
        V = kg_h * 24 * days / rho / 0.85
        if pressurised:
            # bullets or spheres: horizontal vessels of max 628 m3 each
            return self._add(tag, name, "vessel_horizontal", V, f"{V:,.0f} m3 total ({days} days)", P_barg, material,
                             D=4.0, note=f"{days} days storage, pressure storage")
        kind = "tank_floating_roof" if V > 1000 and name.lower().find("volatile") >= 0 else "tank_fixed_roof"
        return self._add(tag, name, kind, max(V, 90), f"{V:,.0f} m3 ({days} days)", material=material,
                         note=f"{days} days storage")

    def heater(self, tag, name, duty_kW, P_barg=0.0, kind="heater_fired", material="CS"):
        return self._add(tag, name, kind, max(duty_kW, 1000), f"{duty_kW:,.0f} kW absorbed", P_barg, material)

    def generic(self, tag, name, kind, size, service, P_barg=0.0, material="CS", note=""):
        return self._add(tag, name, kind, size, service, P_barg, material, note=note)

    def lump(self, label, usd, note):
        """Package items priced from a published figure, not Turton."""
        self.extra_capex.append({"label": label, "usd": usd, "note": note})

    # ------------------------------------------------------------ validation
    def check(self, metric, model, published, unit, source, url, note="", tol=None, kind="process"):
        """published may be a number or [lo, hi]. Error is vs mid point, 0 if inside a range."""
        if model is None:
            mid, err, inside = published, None, None
        elif isinstance(published, (list, tuple)):
            lo, hi = published
            mid = (lo + hi) / 2
            if lo <= model <= hi:
                err = 0.0
                inside = True
            else:
                ref = lo if model < lo else hi
                err = (model - ref) / ref * 100
                inside = False
        else:
            mid = published
            err = (model - published) / published * 100 if published else 0.0
            inside = None
        self.validation.append({
            "metric": metric,
            "model": model,
            "published": published,
            "unit": unit,
            "error_pct": err,
            "inside_range": inside,
            "source": source,
            "url": url,
            "note": note,
            "kind": kind,
            "tolerance_pct": tol,
            "pass": (abs(err) <= tol) if (tol is not None and err is not None) else None,
        })

    # ------------------------------------------------------------ finish
    def finish(self):
        prod_kg_h = sum(self.products.values())
        tpy = prod_kg_h * self.hours / 1000
        tpd = prod_kg_h * 24 / 1000

        # mass balance closure over the plant boundary
        m_in = sum(s.mass for s in self.boundary_in)
        m_out = sum(s.mass for s in self.boundary_out)
        closure = (m_out - m_in) / m_in * 100 if m_in else 0.0

        # atom balance
        atoms_in = _atoms(self.boundary_in)
        atoms_out = _atoms(self.boundary_out)
        atom_err = {a: (atoms_out.get(a, 0) - v) / v * 100 for a, v in atoms_in.items() if v > 1e-9}

        # utilities, annual
        reg = self.region
        price = lambda k: self.price_override.get(k, PR.PRICE_T[k])
        gas_net = self.gas_net_GJ_h  # natural gas bought (feed + fuel), net of off gas burnt instead
        cw_m3_h = self.cw_kW * 3600 / (4.18 * 10 * 1000)  # 10 K rise
        steam_net_kg_h = self.steam_import_kg_h - self.steam_export_kg_h
        util_rows = []
        def u(label, qty_h, unit, unit_cost, cost_unit):
            yr = qty_h * self.hours * unit_cost
            util_rows.append({"label": label, "per_h": qty_h, "unit": unit, "unit_cost": unit_cost,
                              "cost_unit": cost_unit, "annual": yr})
            return yr
        cut = 0.0
        cut += u("Natural gas fuel", gas_net, "GJ (LHV)", reg["gas_usd_gj_lhv"], "USD/GJ")
        cut += u("Electricity", self.power_kW / 1000, "MWh", reg["elec_usd_mwh"], "USD/MWh")
        cut += u("Cooling water", cw_m3_h, "m3", PR.COOLING_WATER_USD_M3, "USD/m3")
        cut += u("Process water", self.process_water_m3_h, "m3", PR.PROCESS_WATER_USD_M3, "USD/m3")
        cut += u("Boiler feed water (demin)", self.demin_water_m3_h, "m3", PR.DEMIN_WATER_USD_M3, "USD/m3")
        # steam: net import is bought at the utility price; net export is credited at the
        # value of the gas it saves in a package boiler (90% efficient), which is how
        # integrated sites value surplus steam
        steam_value = (th.H_STEAM_40BAR_450C - th.H_BFW_105C) / 1e6 / 0.9 * reg["gas_usd_gj_lhv"] * 1000
        if steam_net_kg_h >= 0:
            cut += u("Steam import", steam_net_kg_h / 1000, "t", PR.STEAM_USD_T, "USD/t")
        else:
            cut += u("Steam export (credit)", steam_net_kg_h / 1000, "t", steam_value, "USD/t")

        crm = sum(kg * self.hours / 1000 * price(k) for k, kg in self.feeds.items())
        revenue = sum(kg * self.hours / 1000 * price(k) for k, kg in self.products.items())
        by_credit = sum(kg * self.hours / 1000 * price(k) for k, kg in self.byproducts.items())
        # waste water treatment: assumed charge per tonne (set per stream by the process model, default 2 USD/t
        # for aqueous effluent; organic or hazardous wastes are given their own higher rate)
        cwt = sum(sum(v.values()) * self.waste_cost.get(k, 2.0) for k, v in self.wastes.items()) * self.hours / 1000

        # capital
        gr = C.grassroots(self.equipment)
        extra = sum(x["usd"] for x in self.extra_capex)
        fci = gr["fixed_capital"] + extra * 1.18
        n_np = len([e for e in self.equipment if e["kind"] in (
            "compressor", "hx_fixed_tube", "hx_floating_head", "hx_kettle", "hx_air_cooler", "heater_fired",
            "reformer", "boiler", "tower", "reactor_jacketed", "fermenter", "vessel_vertical", "vessel_horizontal",
            "evaporator")])
        lab = E.operating_labour(n_np, self.solids_steps)
        econ = E.evaluate(fci, revenue, crm, cut, cwt, lab["cost"], product_tpy=tpy, byproduct_credit=by_credit)

        # carbon (scope 1 direct + scope 2 electricity), per tonne product
        co2_direct_t = self.direct_co2_kg_h / prod_kg_h if prod_kg_h else 0
        n2o = self.direct_other.get("N2O", 0.0) / prod_kg_h * 273 if prod_kg_h else 0  # GWP100 AR6
        ch4 = self.direct_other.get("CH4", 0.0) / prod_kg_h * 27.9 if prod_kg_h else 0
        co2_power = self.power_kW * reg["grid_kg_kwh"] / prod_kg_h if prod_kg_h else 0
        steam_co2 = steam_net_kg_h * (th.H_STEAM_40BAR_450C - th.H_BFW_105C) / 1e6 / 0.9 * PR.NG_KG_CO2_GJ_LHV / prod_kg_h if prod_kg_h else 0  # kJ/kg*kg/h/1e6 = GJ/h; *kg/GJ = kg/h
        carbon = {
            "direct_co2": co2_direct_t,
            "direct_n2o_co2e": n2o,
            "direct_ch4_co2e": ch4,
            "electricity": co2_power,
            "steam": steam_co2,
            "total": co2_direct_t + n2o + ch4 + co2_power + steam_co2,
            "unit": "t CO2e / t product",
            "scope_note": "Scope 1 (fuel, process CO2, N2O, CH4 slip) and scope 2 (grid power, net steam). "
                          "Upstream feedstock emissions are not included. Net steam export is credited as "
                          "avoided gas fired boiler steam, so a large steam exporter can show a total below zero.",
            "grid_kg_kwh": reg["grid_kg_kwh"],
        }

        hz = HZ.assess(self)
        for v in self.validation:
            if v["kind"] in ("capex", "cost") and v["model"] is None:
                pub = v["published"]
                val = fci if v["kind"] == "capex" else econ["levelised_cost_per_tonne"]
                v["model"] = val
                if isinstance(pub, (list, tuple)):
                    lo_, hi_ = pub
                    v["inside_range"] = lo_ <= val <= hi_
                    ref = lo_ if val < lo_ else (hi_ if val > hi_ else val)
                    v["error_pct"] = (val - ref) / ref * 100
                else:
                    v["error_pct"] = (val - pub) / pub * 100
                v["pass"] = abs(v["error_pct"]) <= v["tolerance_pct"] if v["tolerance_pct"] else None

        out = {
            "engine_version": ENGINE_VERSION,
            "id": self.pid,
            "title": self.title,
            "product": self.product,
            "route": self.route,
            "summary": self.summary,
            "region": self.region_key,
            "region_label": reg["label"],
            "capacity": {"t_per_day": tpd, "t_per_year": tpy, "hours_per_year": self.hours, "kg_h": prod_kg_h},
            "reactions": self.reactions,
            "conditions": self.conditions,
            "kpis": self.kpis,
            "streams": [s.to_dict() for s in self.streams],
            "units": self.units,
            "balance": {
                "mass_in_kg_h": m_in,
                "mass_out_kg_h": m_out,
                "closure_pct": closure,
                "atom_error_pct": atom_err,
                "boundary_in": [s.id for s in self.boundary_in],
                "boundary_out": [s.id for s in self.boundary_out],
            },
            "energy": {
                "fuel_GJ_h": self.fuel_GJ_h,
                "gas_net_GJ_h": self.gas_net_GJ_h,
                "fuel_credit_GJ_h": self.fuel_credit_GJ_h,
                "power_kW": self.power_kW,
                "power_items": self.power_items,
                "steam_import_kg_h": self.steam_import_kg_h,
                "steam_export_kg_h": self.steam_export_kg_h,
                "steam_items": self.steam_items,
                "cooling_kW": self.cw_kW,
                "cooling_water_m3_h": cw_m3_h,
                "unit_duties": [{"unit": u_["name"], "duty_kW": u_["duty_kW"], "power_kW": u_["power_kW"]}
                                for u_ in self.units if u_["duty_kW"] is not None or u_["power_kW"] is not None],
            },
            "raw_materials": [{"id": k, "kg_h": v, "t_per_t": v / prod_kg_h, "usd_t": price(k),
                               "annual_usd": v * self.hours / 1000 * price(k), "source": PR.price_source(k)}
                              for k, v in self.feeds.items()],
            "products": [{"id": k, "kg_h": v, "usd_t": price(k), "annual_usd": v * self.hours / 1000 * price(k),
                          "source": PR.price_source(k)} for k, v in self.products.items()],
            "byproducts": [{"id": k, "kg_h": v, "t_per_t": v / prod_kg_h, "usd_t": price(k),
                            "annual_usd": v * self.hours / 1000 * price(k), "source": PR.price_source(k)}
                           for k, v in self.byproducts.items()],
            "utilities": util_rows,
            "equipment": self.equipment,
            "capex": {**gr, "extra_items": self.extra_capex, "fixed_capital": fci, "cepci_year": C.BASE_YEAR,
                      "cepci": C.CEPCI[C.BASE_YEAR], "method": "Turton et al. (2018) bare module + grassroots factors"},
            "labour": lab,
            "economics": econ,
            "carbon": carbon,
            "greener": self.greener,
            "hazards": hz["components"],
            "hazop": self.hazop,
            "process_hazards": hz["process"],
            "validation": self.validation,
            "assumptions": self.assumptions,
            "notes": self.notes,
        }
        return _clean(out)


def _atoms(streams):
    from .formula import atoms
    tot = {}
    for s in streams:
        for c, n in s.flows.items():
            for a, k in atoms(th.formula(c)).items():
                tot[a] = tot.get(a, 0.0) + n * k
    return tot


def _clean(o):
    if isinstance(o, float):
        if o != o or o in (float("inf"), float("-inf")):
            return None
        return round(o, 6) if abs(o) < 1e15 else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o
