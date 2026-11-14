"""Operating cost and profitability.

Cost of manufacture (Turton et al. 2018, Eq. 8.2, without depreciation):
    COMd = 0.18 FCI + 2.73 COL + 1.23 (CUT + CWT + CRM)
Operating labour (Turton Eq. 8.3, Alkhayat and Gerrard):
    N_OL = (6.29 + 31.7 P^2 + 0.23 Nnp)^0.5 operators per shift,
    4.5 operators hired per operator position.
Operator wage: US BLS OEWS May 2023, chemical plant and system operators in
chemical manufacturing (NAICS 3251-3259), mean annual wage USD 83,460.
"""
import math

OPERATOR_WAGE_USD = 83460.0
HOURS_PER_YEAR = 8000.0  # 91% on stream, a common design basis


def operating_labour(n_nonparticulate_units, n_solids_steps=0, wage=OPERATOR_WAGE_USD):
    n_ol = math.sqrt(6.29 + 31.7 * n_solids_steps ** 2 + 0.23 * n_nonparticulate_units)
    operators = math.ceil(4.5 * n_ol)
    return {"per_shift": n_ol, "operators": operators, "cost": operators * wage}


def npv(cashflows, rate):
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def irr(cashflows):
    """Bisection between -99% and 1000%. None when there is no sign change (the project never pays back)."""
    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(cashflows, lo), npv(cashflows, hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f = npv(cashflows, mid)
        if f_lo * f < 0:
            hi, f_hi = mid, f
        else:
            lo, f_lo = mid, f
    return (lo + hi) / 2


def evaluate(fci, revenue, crm, cut, cwt, col, *, life=20, rate=0.10, tax=0.25,
             build_years=2, working_capital_frac=0.10, product_tpy=None, byproduct_credit=0.0):
    """Discounted cash flow, straight line depreciation over 10 years."""
    comd = 0.18 * fci + 2.73 * col + 1.23 * (crm + cut + cwt)
    variable = crm + cut + cwt
    fixed = comd - 1.23 * variable
    wc = working_capital_frac * fci
    dep = fci / 10.0
    flows = []
    for y in range(build_years):
        flows.append(-fci / build_years)
    flows[-1] -= wc
    cum = []
    profit_before_tax = revenue + byproduct_credit - comd
    for y in range(life):
        d = dep if y < 10 else 0.0
        taxable = profit_before_tax - d
        t = tax * taxable if taxable > 0 else 0.0
        cf = profit_before_tax - t
        if y == life - 1:
            cf += wc
        flows.append(cf)
    c = 0.0
    payback = None
    for i, f in enumerate(flows):
        c += f
        cum.append(c)
        if payback is None and i >= build_years and c >= 0:
            prev = cum[i - 1]
            payback = (i - build_years) + (-prev / f if f else 0)
    out = {
        "fci": fci,
        "working_capital": wc,
        "revenue": revenue,
        "byproduct_credit": byproduct_credit,
        "raw_materials": crm,
        "utilities": cut,
        "waste_treatment": cwt,
        "labour": col,
        "com": comd,
        "com_breakdown": {
            "Raw materials": 1.23 * crm,
            "Utilities": 1.23 * cut,
            "Waste treatment": 1.23 * cwt,
            "Labour and supervision": 2.73 * col,
            "Maintenance, overheads, insurance (0.18 FCI)": 0.18 * fci,
        },
        "annual_profit_before_tax": profit_before_tax,
        "npv": npv(flows, rate),
        "irr": irr(flows),
        "payback_years": payback,
        "rate": rate,
        "life": life,
        "tax": tax,
        "cashflows": flows,
        "cumulative": cum,
    }
    if product_tpy:
        out["cost_per_tonne"] = (comd - byproduct_credit) / product_tpy
        # levelised cost: annualised capital at the discount rate plus cash cost
        crf = rate * (1 + rate) ** life / ((1 + rate) ** life - 1)
        out["levelised_cost_per_tonne"] = (comd - byproduct_credit + crf * fci) / product_tpy
        out["capex_per_annual_tonne"] = fci / product_tpy
    return out
