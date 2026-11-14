"""Core flowsheet objects: streams, units, enthalpy with phase, equilibrium.

Units used everywhere inside the engine:
    flows  kmol/h       T  K        P  bar (absolute)       duties  kW
Standard library only, so it also runs in the browser (Pyodide).
"""
import math

from . import thermo as th

R = th.R
T0 = th.T0


# ---------------------------------------------------------------- enthalpy

def hf_liquid(cid):
    c = th.comp(cid)
    if c["phase_298"] == "l" and c.get("Hf_std") is not None:
        return th.hf_std(cid)
    hv = c.get("Hvap_298") or c.get("Hvap_Tb") or 0.0
    return th.hf_gas(cid) - hv


def hf_solid(cid):
    c = th.comp(cid)
    if c["phase_298"] == "s":
        return th.hf_std(cid)
    return hf_liquid(cid) - 15000.0  # rough fusion enthalpy if a liquid is shown as solid


def cp_cond(cid, phase):
    c = th.comp(cid)
    if phase == "s":
        v = c.get("Cp_solid_298") or c.get("Cp_liquid_298")
    else:
        v = c.get("Cp_liquid_298") or c.get("Cp_solid_298")
    if v is None:
        v = th.cp_gas(cid, 298.15) * 1.4
    return v


def h_molar(cid, T, phase="g"):
    """J/mol relative to the elements at 298.15 K."""
    if phase == "g":
        return th.h_gas(cid, T)
    if phase == "l":
        return hf_liquid(cid) + cp_cond(cid, "l") * (T - T0)
    if phase == "s":
        return hf_solid(cid) + cp_cond(cid, "s") * (T - T0)
    if phase == "aq":  # dilute in water, ignore heat of solution
        return hf_liquid(cid) + cp_cond(cid, "l") * (T - T0)
    raise ValueError(phase)


def psat(cid, T):
    """Vapour pressure (bar). Lee Kesler corresponding states from Tc, Pc and the acentric
    factor; falls back to Clausius Clapeyron anchored at the normal boiling point."""
    c = th.comp(cid)
    a = c.get("antoine")
    if a:
        Tx = min(max(T, a["Tmin"] - 30), a["Tmax"] + 60)
        return math.exp(a["A"] - a["B"] / (Tx + a["C"])) / 1e5
    Tc, Pc, w = c.get("Tc"), c.get("Pc"), c.get("omega")
    if Tc and Pc and w is not None:
        Tr = min(T / Tc, 1.0)
        f0 = 5.92714 - 6.09648 / Tr - 1.28862 * math.log(Tr) + 0.169347 * Tr ** 6
        f1 = 15.2518 - 15.6875 / Tr - 13.4721 * math.log(Tr) + 0.43577 * Tr ** 6
        return Pc / 1e5 * math.exp(f0 + w * f1)
    Tb = c["Tb"]
    hv = c.get("Hvap_Tb") or c.get("Hvap_298") or 30000.0
    return 1.01325 * math.exp(hv / R * (1.0 / Tb - 1.0 / T))


# ---------------------------------------------------------------- streams

class Stream:
    def __init__(self, sid, name, flows, T, P, phase="g", phases=None, note=""):
        self.id = sid
        self.name = name
        self.flows = {k: v for k, v in flows.items() if v and v > 1e-9}
        self.T = T
        self.P = P
        self.phase = phase  # 'g', 'l', 's', 'mixed'
        self.phases = phases or {}  # per component override: {'NH3': 'l'}
        self.note = note
        self.src = None
        self.dst = None

    def ph(self, cid):
        if cid in self.phases:
            return self.phases[cid]
        return self.phase if self.phase in ("g", "l", "s", "aq") else "g"

    @property
    def total(self):
        return sum(self.flows.values())

    @property
    def mass(self):  # kg/h
        return sum(n * th.MW(c) for c, n in self.flows.items())

    def H(self):  # kW
        return sum(n * h_molar(c, self.T, self.ph(c)) for c, n in self.flows.items()) / 3600.0

    def y(self, cid):
        t = self.total
        return self.flows.get(cid, 0.0) / t if t else 0.0

    def to_dict(self):
        m = self.mass
        return {
            "id": self.id,
            "name": self.name,
            "from": self.src,
            "to": self.dst,
            "T_C": round(self.T - 273.15, 1),
            "P_bar": round(self.P, 2),
            "phase": self.phase,
            "kmol_h": round(self.total, 3),
            "kg_h": round(m, 2),
            "components": {
                c: {
                    "kmol_h": round(n, 4),
                    "kg_h": round(n * th.MW(c), 3),
                    "mass_frac": round(n * th.MW(c) / m, 5) if m else 0,
                    "mol_frac": round(n / self.total, 5) if self.total else 0,
                }
                for c, n in sorted(self.flows.items(), key=lambda kv: -kv[1] * th.MW(kv[0]))
            },
        }


def add(*flow_dicts):
    out = {}
    for f in flow_dicts:
        for c, n in f.items():
            out[c] = out.get(c, 0.0) + n
    return out


def scale(f, k):
    return {c: n * k for c, n in f.items()}


def split(f, fractions):
    """fractions: {cid: fraction to top}; returns (top, bottom)."""
    top, bot = {}, {}
    for c, n in f.items():
        x = fractions.get(c, fractions.get("_", 0.0))
        top[c] = n * x
        bot[c] = n * (1 - x)
    return top, bot


# ---------------------------------------------------------------- equilibrium

def equilibrium(feed, reactions, T, P, Kfun=None, max_iter=200):
    """Ideal gas chemical equilibrium by Newton iteration on reaction extents.

    feed: {cid: kmol/h}; reactions: list of stoich dicts (products +).
    Returns (out_flows, extents). Kp uses a 1 bar standard state.
    """
    comps = sorted(set(feed) | {c for r in reactions for c in r})
    n0 = {c: feed.get(c, 0.0) for c in comps}
    lnK = [math.log(Kfun(r, T)) if Kfun else math.log(th.Kp(r, T)) for r in reactions]
    m = len(reactions)
    xi = [0.0] * m
    scale_n = max(sum(n0.values()), 1e-9)

    def flows(x):
        return {c: n0[c] + sum(x[j] * reactions[j].get(c, 0.0) for j in range(m)) for c in comps}

    def resid(x):
        n = flows(x)
        if any(v <= 0 for v in n.values()):
            return None
        nt = sum(n.values())
        r = []
        for j, rx in enumerate(reactions):
            dn = sum(rx.values())
            r.append(sum(nu * math.log(n[c]) for c, nu in rx.items()) - dn * math.log(nt) + dn * math.log(P) - lnK[j])
        return r

    # seed tiny amounts so logs are defined, then a small feasible start where
    # reaction j advances 10x less than reaction j-1 (works for chains like SMR then WGS)
    eps = 1e-12 * scale_n
    for c in comps:
        if n0[c] <= 0:
            n0[c] = eps
    for j in range(m):
        xi[j] = 1e-6 * scale_n * 10.0 ** (-j)
    if resid(xi) is None:
        xi = [0.0] * m
    for it in range(max_iter):
        r = resid(xi)
        if r is None:
            raise RuntimeError("equilibrium left feasible region")
        if max(abs(v) for v in r) < 1e-10:
            break
        J = []
        for j in range(m):
            h = max(abs(xi[j]) * 1e-6, 1e-14 * scale_n)
            xp = xi[:]
            xp[j] += h
            rp = resid(xp)
            if rp is None:
                xp[j] = xi[j] - h
                rp = resid(xp)
                if rp is None:
                    J.append([0.0] * m)
                    continue
                J.append([(r[i] - rp[i]) / h for i in range(m)])
            else:
                J.append([(rp[i] - r[i]) / h for i in range(m)])
        # J[j][i] = d r_i / d xi_j  -> solve sum_j J[j][i] dx_j = -r_i
        A = [[J[j][i] for j in range(m)] + [-r[i]] for i in range(m)]
        dx = _solve(A, m)
        lam = 1.0
        while lam > 1e-8:
            xn = [xi[j] + lam * dx[j] for j in range(m)]
            rn = resid(xn)
            if rn is not None and max(abs(v) for v in rn) < max(abs(v) for v in r) * (1 - 1e-4 * lam) + 1e-12:
                xi = xn
                break
            lam *= 0.5
        else:
            break
    n = flows(xi)
    return {c: v for c, v in n.items() if v > 1e-8 * scale_n}, xi


def _solve(A, m):
    for i in range(m):
        p = max(range(i, m), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        if abs(A[i][i]) < 1e-300:
            continue
        for r in range(m):
            if r != i:
                f = A[r][i] / A[i][i]
                A[r] = [A[r][c] - f * A[i][c] for c in range(m + 1)]
    return [A[i][m] / A[i][i] if abs(A[i][i]) > 1e-300 else 0.0 for i in range(m)]


def adiabatic_T(stream_in_H_kW, flows, P, T_guess, phase="g"):
    """Temperature (K) of an ideal gas stream with given total enthalpy."""
    T = T_guess
    for _ in range(80):
        H = sum(n * h_molar(c, T, phase) for c, n in flows.items()) / 3600.0
        cp = sum(n * th.cp_gas(c, T) for c, n in flows.items()) / 3600.0
        dT = (stream_in_H_kW - H) / cp
        T += max(-150.0, min(150.0, dT))
        if abs(dT) < 1e-3:
            break
    return T


def gas_volume_m3_h(n_kmol_h, T, P):
    return n_kmol_h * 1000 * R * T / (P * 1e5)


def rho_gas(stream):
    return stream.mass / max(gas_volume_m3_h(stream.total, stream.T, stream.P), 1e-9)


def hin(flows, T, phase="g"):
    """Total enthalpy (kW) of a single phase stream given as a flow dict."""
    return sum(n * h_molar(c, T, phase) for c, n in flows.items()) / 3600.0


def adiabatic_eq(flows_in, H_in_kW, reactions, P, T_lo, T_hi):
    """Adiabatic equilibrium reactor: temperature where H(outlet at T) equals H_in."""
    def f(T):
        out, _ = equilibrium(flows_in, reactions, T, P)
        return hin(out, T) - H_in_kW, out
    a, b = T_lo, T_hi
    fa, _ = f(a)
    out = None
    for _ in range(60):
        m = (a + b) / 2
        fm, out = f(m)
        if (fa < 0) == (fm < 0):
            a, fa = m, fm
        else:
            b = m
        if b - a < 0.01:
            break
    return (a + b) / 2, out


def condense(flows, T, P, condensables, solubles=()):
    """Split a gas into vapour and liquid at T, P.
    Condensables follow Raoult's law over an ideal liquid (solved by Rachford Rice);
    everything else stays in the vapour except `solubles`, which are ignored (stay vapour)."""
    K = {c: psat(c, T) / P for c in condensables if c in flows}
    z_tot = sum(flows.values())
    if not K or z_tot <= 0:
        return dict(flows), {}
    z = {c: n / z_tot for c, n in flows.items()}
    def rr(v):
        s = 0.0
        for c, zc in z.items():
            k = K.get(c, 1e6)
            s += zc * (k - 1) / (1 + v * (k - 1))
        return s
    lo, hi = 1e-9, 1 - 1e-9
    if rr(hi) > 0:
        return dict(flows), {}
    if rr(lo) < 0:
        return {}, dict(flows)
    for _ in range(200):
        m = (lo + hi) / 2
        if rr(m) > 0:
            lo = m
        else:
            hi = m
    v = (lo + hi) / 2
    vap, liq = {}, {}
    for c, zc in z.items():
        k = K.get(c, 1e6)
        x = zc / (1 + v * (k - 1))
        liq[c] = x * (1 - v) * z_tot
        vap[c] = flows[c] - liq[c]
    return vap, {c: n for c, n in liq.items() if n > 1e-12}
