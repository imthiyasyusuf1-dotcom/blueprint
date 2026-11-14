"""Aspirin (acetylsalicylic acid) by batch acetylation of salicylic acid with acetic anhydride.

    C7H6O3 (salicylic acid) + C4H6O3 (acetic anhydride) -> C9H8O4 (aspirin) + C2H4O2 (acetic acid)

Pharma scale batch plant shown as time averaged flows. Glass lined jacketed reactors at about
85 C with acetic acid as diluent, cooling crystallisation, centrifuge, vacuum dryer. The mother
liquor is distilled under vacuum: excess anhydride and diluent acid are recycled, the acetic acid
made by the reaction is sold, the still residue is worked up for a second crop and the rest purged.

Yield basis (all from US 3,373,187 and US 3,235,583, see the checks):
  * reaction completion 97% after 2 h at 85 C without catalyst (US 3,373,187 Table I, run 3),
  * first crop on cooling 66 of those 97 points (same run: 66% crystals, 31% in the residue),
  * acetic acid recovery about 97% (US 3,235,583).
"""
from .. import core
from .. import thermo as th
from ..design import Design

ACETYLATION = {"SalAcid": -1, "Ac2O": -1, "ASA": 1, "AcOH": 1}

DEFAULTS = {
    "capacity_tpd": 10.0,
    "anhydride_excess": 0.18,  # mol excess over salicylic acid, 2 to 20% with 18% preferred (US 3,235,583)
    "diluent_kg_per_kg_sa": 0.32,  # acetic acid diluent, 45 g per 140 g salicylic acid (US 3,373,187 Example I)
    "reactor_T_C": 85.0,  # US 3,373,187 Table I; Ullmann's (via HSDB): below 90 C
    "reaction_h": 2.0,  # US 3,373,187 Table I, run 3
    "conversion": 0.97,  # US 3,373,187 Table I, run 3 (85 C, 2 h, no catalyst): 66 + 31 = 97% of theoretical
    "first_crop": 66.0 / 97.0,  # same run: share of the aspirin formed that crystallises on cooling
    "second_crop_recovery": 0.90,  # share of the aspirin left in the mother liquor won back from the still residue
    "volatiles_recovery": 0.97,  # acetic acid and anhydride recovered overhead (US 3,235,583: about 97%)
    "crystalliser_T_C": 20.0,
    "cake_liquor_frac": 0.10,  # kg mother liquor per kg wet cake leaving the centrifuge
    "handling_loss": 0.005,  # dryer dust and packing losses, fraction of aspirin dried
}

hin = core.hin


def _h(flows, T, ph):
    """kW of a flow dict where each component has its own phase."""
    return sum(n * core.h_molar(c, T, ph.get(c, "l")) for c, n in flows.items()) / 3600.0


SOLID = {"SalAcid": "s", "ASA": "s"}


def design(capacity_tpd=None, region="US", **over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in over.items() if k in DEFAULTS and v is not None})
    if capacity_tpd:
        p["capacity_tpd"] = float(capacity_tpd)

    X, f1, r2, rv, loss = p["conversion"], p["first_crop"], p["second_crop_recovery"], p["volatiles_recovery"], p["handling_loss"]
    E = p["anhydride_excess"]
    # overall yield on salicylic acid
    Y = X * (f1 + (1 - f1) * r2) * (1 - loss)
    # The cake liquor and second crop make the product a little more than the yield formula Y suggests,
    # and the product carries a trace of salicylic acid. The flowsheet is linear in the feed, so solve once
    # with the Y estimate and rescale the feed so the product stream hits the requested capacity exactly.
    target_kg_h = p["capacity_tpd"] * 1000 / 24
    sa = target_kg_h / th.MW("ASA") / Y  # fresh salicylic acid, kmol/h (first estimate)
    for _pass in range(3):
        rx = sa * X  # extent of acetylation
        ac2o_in = sa * (1 + E)  # anhydride charged to the reactor
        ac2o_left = ac2o_in - rx
        ac2o_rec = ac2o_left * rv
        ac2o_fresh = ac2o_in - ac2o_rec
        acoh_dil = sa * th.MW("SalAcid") * p["diluent_kg_per_kg_sa"] / th.MW("AcOH")
        acoh_tot = acoh_dil + rx
        acoh_rec = acoh_tot * rv
        acoh_sold = acoh_rec - acoh_dil  # by-product acetic acid
        acoh_purge = acoh_tot - acoh_rec
        ac2o_purge = ac2o_left - ac2o_rec

        asa_formed = rx
        asa_crop1 = asa_formed * f1
        asa_ml = asa_formed - asa_crop1
        asa_crop2 = asa_ml * r2
        asa_dried = asa_crop1 + asa_crop2
        asa_prod = asa_dried * (1 - loss)
        asa_lost_dryer = asa_dried - asa_prod
        sa_left = sa - rx

        TR = p["reactor_T_C"] + 273.15
        TX = p["crystalliser_T_C"] + 273.15

        # streams (kmol/h, time averaged over the batch cycle)
        f_sa = {"SalAcid": sa}
        f_ac2o = {"Ac2O": ac2o_fresh}
        f_rec = {"Ac2O": ac2o_rec, "AcOH": acoh_dil}
        f_rin = core.add(f_sa, f_ac2o, f_rec)
        f_rout = {"ASA": asa_formed, "SalAcid": sa_left, "Ac2O": ac2o_left, "AcOH": acoh_tot}
        # centrifuge: first crop crystals plus the liquor held in the cake (about 10 wt% of the wet cake)
        liq_ml = {"ASA": asa_ml, "SalAcid": sa_left, "Ac2O": ac2o_left, "AcOH": acoh_tot}
        m_liq = sum(n * th.MW(c) for c, n in liq_ml.items())
        m_crop1 = asa_crop1 * th.MW("ASA")
        m_cake_liq = m_crop1 * p["cake_liquor_frac"] / (1 - p["cake_liquor_frac"])
        fr = min(m_cake_liq / m_liq, 0.5)
        cake_liq = core.scale(liq_ml, fr)
        # the dissolved solids in the cake liquor are deposited on drying; count them with the cake
        f_cake = {"ASA": asa_crop1 + cake_liq["ASA"], "SalAcid": cake_liq["SalAcid"],
                  "Ac2O": cake_liq["Ac2O"], "AcOH": cake_liq["AcOH"]}
        f_ml = core.scale(liq_ml, 1 - fr)
        # dryer: volatiles off, condensed and sent to the still; ASA and the small SA content stay in the solid
        f_dry_vap = {"Ac2O": f_cake["Ac2O"], "AcOH": f_cake["AcOH"]}
        # still: mother liquor plus dryer condensate. Overheads recovered at rv, rest leaves with the residue
        f_still_in = core.add(f_ml, f_dry_vap)
        f_dist = {"Ac2O": ac2o_rec, "AcOH": acoh_rec}
        f_resid = {c: f_still_in.get(c, 0.0) - f_dist.get(c, 0.0) for c in f_still_in}
        # second crop from the residue: ASA held in the residue is the mother liquor ASA less what the cake took
        asa_resid = f_resid.get("ASA", 0.0)
        crop2_from_resid = min(asa_crop2, asa_resid)
        # any second crop ASA that left with the cake liquor is already in the dryer feed
        f_crop2 = {"ASA": crop2_from_resid}
        f_purge = {c: n for c, n in f_resid.items()}
        f_purge["ASA"] = asa_resid - crop2_from_resid
        # SA in the cake leaves with the product as a trace; the rest is purged
        sa_in_product = f_cake["SalAcid"]
        f_dry_sol = {"ASA": f_cake["ASA"] + crop2_from_resid, "SalAcid": sa_in_product}
        asa_dried = f_dry_sol["ASA"]
        asa_prod = asa_dried * (1 - loss)
        asa_lost_dryer = asa_dried - asa_prod
        f_prod = {"ASA": asa_prod, "SalAcid": sa_in_product}
        f_dust = {"ASA": asa_lost_dryer}
        f_acoh = {"AcOH": acoh_sold}
        f_waste = f_purge
        m_prod = asa_prod * th.MW("ASA")  # capacity is counted as aspirin
        if abs(m_prod / target_kg_h - 1) < 1e-12:
            break
        sa *= target_kg_h / m_prod

    d = Design("aspirin", "Aspirin plant (batch acetylation of salicylic acid)", "Aspirin", p["capacity_tpd"], region)
    d.solids_steps = 2  # centrifuging and drying (powder charging and packing sit in the packing line allowance)
    d.route = ("Salicylic acid is acetylated with acetic anhydride in acetic acid at about 85 C in glass lined batch "
               "reactors, aspirin is crystallised by cooling, centrifuged and vacuum dried. The mother liquor is distilled "
               "under vacuum to recycle anhydride and diluent, sell the acetic acid made and win a second crop.")
    d.summary = f"{p['capacity_tpd']:,.0f} t/d of pharmaceutical aspirin from salicylic acid and acetic anhydride."
    dH = sum(n * core.h_molar(c, 298.15, SOLID.get(c, "l")) for c, n in ACETYLATION.items()) / 1000  # kJ/mol
    d.reactions = [
        {"eq": "C7H6O3 + (CH3CO)2O -> C9H8O4 + CH3COOH", "where": "Acetylation reactors (glass lined, batch)",
         "dH_kJ": dH},
    ]
    d.conditions = [
        ("Reactor", f"{p['reactor_T_C']:.0f} C, atmospheric, {p['reaction_h']:.0f} h at temperature"),
        ("Acetic anhydride excess", f"{E * 100:.0f} mol% over salicylic acid"),
        ("Acetic acid diluent", f"{p['diluent_kg_per_kg_sa']:.2f} kg per kg salicylic acid"),
        ("Conversion of salicylic acid", f"{X * 100:.0f}%"),
        ("Crystallisation", f"cooled to {p['crystalliser_T_C']:.0f} C, first crop {f1 * 100:.0f}% of the aspirin formed"),
        ("Mother liquor still", "vacuum, about 50 mbar"),
        ("Overall yield on salicylic acid", f"{asa_prod / sa * 100:.1f}% of theoretical"),
    ]

    s_sa = d.stream("Salicylic acid feed", f_sa, 298.15, 1.013, phase="s")
    s_ac = d.stream("Acetic anhydride feed", f_ac2o, 298.15, 2.0, phase="l")
    s_rec = d.stream("Recycled anhydride and diluent", f_rec, 313.15, 2.0, phase="l")
    s_rout = d.stream("Reactor batch (aspirin solution)", f_rout, TR, 1.013, phase="l")
    s_slurry = d.stream("Crystal slurry", f_rout, TX, 1.013, phase="mixed", phases={"ASA": "s"})
    s_cake = d.stream("Wet cake", f_cake, TX, 1.013, phase="mixed", phases={"ASA": "s", "SalAcid": "s"})
    s_ml = d.stream("Mother liquor", f_ml, TX, 1.013, phase="l")
    s_dvap = d.stream("Dryer vapours (condensed)", f_dry_vap, 313.15, 0.1, phase="l")
    s_dist = d.stream("Still overheads", f_dist, 313.15, 0.05, phase="l")
    s_res = d.stream("Still residue", f_resid, 363.15, 0.05, phase="mixed", phases={"ASA": "s", "SalAcid": "s"})
    s_c2 = d.stream("Second crop crystals", f_crop2, 298.15, 1.013, phase="s")
    s_prod = d.stream("Aspirin product", f_prod, 303.15, 1.013, phase="s")
    s_acoh = d.stream("Acetic acid by-product", f_acoh, 313.15, 2.0, phase="l")
    s_dust = d.stream("Dryer dust to incineration", f_dust, 313.15, 1.013, phase="s")
    s_waste = d.stream("Residue purge to incineration", f_waste, 313.15, 1.013, phase="mixed",
                       phases={"ASA": "s", "SalAcid": "s"})

    d.feed(s_sa, {"SalAcid": "SalAcid"})
    d.feed(s_ac, {"Ac2O": "Ac2O"})
    d.out(s_prod, "product", {"ASA": "ASA"})
    d.out(s_acoh, "byproduct", {"AcOH": "AcOH"})
    d.out(s_waste, "waste", treat_usd_t=2.0)
    d.out(s_dust, "waste", treat_usd_t=2.0)

    d.unit("R-101", "Acetylation reactors", "reactor", [s_sa, s_ac, s_rec], [s_rout], (0, 0),
           desc="Glass lined jacketed batch reactors")
    d.unit("X-101", "Cooling crystallisers", "crystalliser", [s_rout], [s_slurry], (1, 0))
    d.unit("S-101", "Centrifuge", "centrifuge", [s_slurry], [s_cake, s_ml], (2, 0))
    d.unit("D-101", "Vacuum dryer", "dryer", [s_cake, s_c2], [s_prod, s_dvap, s_dust], (3, 0))
    d.unit("T-101", "Mother liquor vacuum still", "column", [s_ml, s_dvap], [s_dist, s_res], (2, 1))
    d.unit("X-102", "Second crop crystalliser and filter", "crystalliser", [s_res], [s_c2, s_waste], (3, 1))
    d.unit("V-101", "Distillate receiver and splitter", "drum", [s_dist], [s_rec, s_acoh], (1, 1))

    # ---------------------------------------------------------------- energy
    # reactor: heat the charge to 85 C, then the exotherm is removed by the jacket
    H_charge = _h(f_sa, 298.15, SOLID) + _h(f_ac2o, 298.15, SOLID) + _h(f_rec, 313.15, SOLID)
    H_hot = _h(f_rin, TR, SOLID)
    Q_heat = H_hot - H_charge
    Q_rx = -rx * (dH * 1000) / 3600.0  # kW released
    # most of the exotherm is used in place of jacket steam once the batch is above about 60 C;
    # heating and cooling happen at different times in the cycle, so they are sized separately
    Q_reactor_net = Q_heat - Q_rx
    lp = 2100.0  # kJ/kg latent heat of low pressure steam, about 3.5 bar (IAPWS table above)
    if Q_reactor_net > 0:
        d.steam(Q_reactor_net / lp * 3600, "Reactor jacket heating")
    else:
        d.cooling(-Q_reactor_net, "Reactor jacket cooling (exotherm)")
    # crystalliser: cool the batch from 85 C to 20 C (chilled water below 30 C)
    Q_cryst = _h(f_rout, TR, SOLID) - _h(f_rout, TX, SOLID)
    d.cooling(Q_cryst, "Crystalliser cooling")
    # dryer: evaporate the cake liquor (acetic acid and anhydride) under vacuum
    Q_dry = sum(n * th.hvap(c) for c, n in f_dry_vap.items()) / 3600.0 + _h(f_cake, 333.15, SOLID) - _h(f_cake, TX, SOLID)
    d.steam(Q_dry / 0.8 / lp * 3600, "Vacuum dryer (80% thermal efficiency)")
    d.cooling(Q_dry, "Dryer vapour condenser")
    # still: everything taken overhead is evaporated once, reflux ratio 0.5 for the anhydride and acid split
    Q_still = sum(n * th.hvap(c) for c, n in f_dist.items()) / 3600.0 * 1.5
    d.steam(Q_still / lp * 3600, "Mother liquor still reboiler")
    d.cooling(Q_still, "Still condenser")
    # power: agitators, vacuum pumps, centrifuge, about 1.5 kW per m3 agitated volume plus fixed loads
    batch_h = p["reaction_h"] + 2.0  # charge, heat up, discharge
    m_batch_h = sum(n * th.MW(c) for c, n in f_rin.items())
    V_work = m_batch_h * batch_h / 1150.0  # m3, slurry density about 1150 kg/m3
    V_reactor = V_work / 0.8
    n_r = max(1, int(-(-V_reactor // 10.0)))  # glass lined reactors up to about 10 m3 each
    d.power(1.5 * V_reactor * 2, "Agitators (reactors and crystallisers)")
    d.power(15.0, "Centrifuge drive")
    d.power(11.0, "Vacuum pumps (dryer and still)")
    d.process_water_m3_h = 0.0

    # ---------------------------------------------------------------- equipment
    for i in range(n_r):
        d.generic(f"R-101{chr(65 + i)}", "Acetylation reactor (glass lined)", "reactor_jacketed", V_reactor / n_r,
                  f"{V_reactor / n_r:.1f} m3, {p['reactor_T_C']:.0f} C", material="SS",
                  note=f"Batch cycle {batch_h:.0f} h, working volume {V_work:.1f} m3")
    V_cr = (m_batch_h * 4.0 / 1150.0) / 0.8  # 4 h cooling cycle
    n_c = max(1, int(-(-V_cr // 10.0)))
    for i in range(n_c):
        d.generic(f"X-101{chr(65 + i)}", "Cooling crystalliser", "crystalliser", V_cr / n_c, f"{V_cr / n_c:.1f} m3",
                  material="SS", note="4 h cooling programme")
    d.generic("S-101", "Peeler centrifuge", "centrifuge", 1.25, "1.25 m basket", material="SS")
    # dryer heat transfer area: U about 60 W/m2K, dT about 60 K under vacuum
    A_dry = max(5.0, Q_dry * 1000 / (60 * 60))
    d.generic("D-101", "Vacuum dryer", "dryer_rotary", A_dry, f"{A_dry:.0f} m2", material="SS")
    V_dist = sum(f_dist.values())
    d.column("T-101", "Mother liquor vacuum still", V_dist * 1.5, 340, 0.05, 8, 70.0, material="SS")
    d.hx("E-101", "Still reboiler", Q_still, 420.15, 420.15, 340.15, 345.15, "reboiler", kind="hx_kettle", material="SS")
    d.hx("E-102", "Still condenser", Q_still, 340.15, 330.15, 303.15, 313.15, "condenser", material="SS")
    d.generic("X-102", "Second crop crystalliser", "crystalliser", max(1.5, V_cr / 4), f"{max(1.5, V_cr / 4):.1f} m3",
              material="SS")
    d.vessel("V-101", "Distillate receiver", max(1.0, sum(n * th.MW(c) for c, n in f_dist.items()) * 2 / 1050), material="SS")
    d.tank("TK-101", "Acetic anhydride storage", ac2o_fresh * th.MW("Ac2O"), 1080, days=14, material="SS")
    d.tank("TK-102", "Acetic acid by-product storage", acoh_sold * th.MW("AcOH"), 1050, days=14, material="SS")
    d.vessel("TK-103", "Salicylic acid silo", sa * th.MW("SalAcid") * 24 * 7 / 700, service="7 days, bulk density 700 kg/m3")
    d.vessel("TK-104", "Aspirin product hopper", asa_prod * th.MW("ASA") * 24 * 2 / 600, material="SS",
             service="2 days before packing, bulk density 600 kg/m3")
    d.pump("P-101", "Recycle pump", sum(n * th.MW(c) for c, n in f_rec.items()), 1060, 3, material="SS")
    d.pump("P-102", "Mother liquor pump", sum(n * th.MW(c) for c, n in f_ml.items()), 1100, 3, material="SS")
    d.lump("Clean room packing line and powder handling", 750000.0,
           "Allowance for GMP finishing (milling, sieving, packing) not covered by Turton correlations")

    # ---------------------------------------------------------------- KPIs
    prod_kg_h = asa_prod * th.MW("ASA")
    sa_t_t = sa * th.MW("SalAcid") / prod_kg_h
    ac2o_t_t = ac2o_fresh * th.MW("Ac2O") / prod_kg_h
    acoh_t_t = acoh_sold * th.MW("AcOH") / prod_kg_h
    Y_model = asa_prod / sa * 100
    d.kpis = [
        {"label": "Overall yield on salicylic acid", "value": Y_model, "unit": "% of theoretical"},
        {"label": "Salicylic acid use", "value": sa_t_t, "unit": "t/t aspirin"},
        {"label": "Acetic anhydride use", "value": ac2o_t_t, "unit": "t/t aspirin"},
        {"label": "Acetic acid by-product", "value": acoh_t_t, "unit": "t/t aspirin"},
        {"label": "Salicylic acid in product", "value": sa_in_product / max(asa_prod, 1e-9) * th.MW("SalAcid") / th.MW("ASA") * 100,
         "unit": "wt% (before any recrystallisation)"},
    ]

    P1 = "https://patents.google.com/patent/US3235583A/en"
    P2 = "https://patents.google.com/patent/US3373187A/en"
    PC = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/2244/JSON?heading=Methods+of+Manufacturing"
    IM = "https://www.imarcgroup.com/aspirin-pricing-report"
    d.check("Overall aspirin yield on salicylic acid, crystallisation route", Y_model, [91.0, 97.4], "% of theoretical",
            "US 3,235,583 (prior art crystallisation route, 91%) and US 3,373,187 (catalysed batch, 97.4%)", P1, tol=3,
            note="Model yield comes from the conversion, first crop, second crop and handling losses, not set directly.")
    d.check("Acetic acid by-product recovered", acoh_sold / rx * 100, 97.0, "% of acetic acid made",
            "US 3,235,583", P1, tol=5,
            note="Patent: recovery of by-product acetic acid in the neighbourhood of 97%. Model figure is net of the "
                 "diluent lost with the residue purge.")
    d.check("Reaction temperature", p["reactor_T_C"], [40.0, 90.0], "C",
            "Ullmann's Encyclopedia of Industrial Chemistry via PubChem HSDB (below 90 C); US 3,235,583 claims 40 to 95 C", PC,
            tol=0, kind="process")
    d.check("Production cost against the market price of aspirin", None, [2356, 2887], "USD/t",
            "IMARC Group, Aspirin Pricing Report, Q4 2025 (Germany 2,356 to USA 2,887 USD/t)", IM, tol=None, kind="cost",
            note="Shown for information. A 10 t/d plant carries a heavy labour and capital charge per tonne compared "
                 "with the large Chinese producers that set the bulk price.")

    d.assumptions = [
        "Batch operation is shown as time averaged flows over 8,000 h a year.",
        f"Reaction completion {X * 100:.0f}% after {p['reaction_h']:.0f} h at {p['reactor_T_C']:.0f} C without catalyst, and "
        f"{f1 * 100:.0f}% of the aspirin formed crystallising on cooling, both from US 3,373,187 Table I (run 3).",
        f"{r2 * 100:.0f}% of the aspirin left in the mother liquor is won back as a second crop from the still residue "
        "(assumed; US 3,235,583 describes the filtrate being distilled for more product).",
        f"Acetic acid and anhydride recovered overhead in the still: {rv * 100:.0f}% (US 3,235,583).",
        f"Wet cake holds {p['cake_liquor_frac'] * 100:.0f} wt% mother liquor; the salicylic acid it carries ends up in the "
        "dried product as a trace. Pharmacopoeia grade may need a recrystallisation, not modelled.",
        f"Dryer dust and packing losses {loss * 100:.1f}% of the aspirin dried.",
        "Reaction enthalpy from solid aspirin and salicylic acid and liquid anhydride and acid standard heats of "
        "formation; heats of solution and crystallisation are not included.",
        "Hydrolysis of anhydride by moisture and by-products such as acetylsalicylic anhydride and salsalate are not "
        "modelled; they end up in the residue purge in practice.",
        "The residue purge goes to incineration and is charged at the default effluent rate, which understates the "
        "true incineration cost.",
        "Crystalliser cooling below 30 C needs chilled water; it is costed as cooling water.",
        "A packing line allowance of 0.75 M USD (GMP finishing) is added as a lump; this is an estimate, not a quote.",
    ]
    d.hazop = [
        {"node": "Acetylation reactor", "deviation": "High temperature", "cause": "Anhydride added too fast or jacket cooling lost during the exotherm",
         "consequence": "Boil up of acetic acid and anhydride, overpressure, colour bodies and by-products",
         "safeguard": "Controlled anhydride dosing interlocked with temperature, jacket cooling, relief to a scrubber"},
        {"node": "Acetylation reactor", "deviation": "Water ingress", "cause": "Wet salicylic acid or leaking jacket",
         "consequence": "Exothermic hydrolysis of anhydride, pressure rise, hydrolysis of aspirin back to salicylic acid",
         "safeguard": "Moisture specification on raw materials, jacket leak testing, high temperature trip"},
        {"node": "Solids charging and dryer", "deviation": "Dust cloud", "cause": "Open charging of powder, dryer discharge",
         "consequence": "Combustible dust explosion (aspirin and salicylic acid dusts)",
         "safeguard": "Closed charging with nitrogen inerting, earthing and bonding, explosion venting, dust extraction"},
        {"node": "Acetic anhydride storage and transfer", "deviation": "Loss of containment", "cause": "Hose or gasket failure",
         "consequence": "Corrosive and toxic vapour release, flammable liquid pool",
         "safeguard": "Bunding, dry break couplings, vapour detection, PPE and safety showers"},
        {"node": "Mother liquor still", "deviation": "Air ingress under vacuum", "cause": "Seal or flange leak",
         "consequence": "Flammable acetic acid and anhydride vapour mixture in the column and vacuum system",
         "safeguard": "Nitrogen bleed, oxygen monitoring on the vacuum line, flame arrester on the vent"},
    ]
    d.greener = {
        "title": "Continuous flow acetylation with solvent recycle",
        "text": "Running the acetylation in a continuous flow reactor with in line crystallisation cuts the anhydride excess "
                "and the batch heating and cooling cycles, and lowers the solvent hold up. Salicylic acid itself can be "
                "made from bio based phenol in future, which lowers the upstream carbon.",
    }
    return d.finish()
