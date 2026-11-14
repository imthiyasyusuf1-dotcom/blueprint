# Blueprint

Type a chemical, get a first pass plant design and a costed report in seconds.

Live: https://imthiyasyusuf1-dotcom.github.io/blueprint/

Founded and built by Yusuf Imthiyas.

## What you get for each product

- Process route, reactions and operating conditions
- Process flow diagram with every stream tappable
- Solved mass and energy balance (closure and atom balance shown)
- Equipment list, sized from the balance and costed with Turton bare module correlations, CEPCI 2024
- Capex, opex, cost per tonne, NPV, IRR and payback, for US, EU or UK prices
- Hazards and a mini HAZOP
- Carbon footprint (scope 1 and 2) and a greener route
- Validation against published plant figures, with the percentage error shown
- A 13 to 20 page PDF report, and a custom re-run in your browser (change capacity and conditions)

## Processes live now

Ammonia, methanol, hydrogen (SMR), urea, nitric acid, sulphuric acid, ethanol (dry grind),
biodiesel, ethylene oxide, styrene, aspirin, chlorine and caustic soda (membrane cell), hydrogen
peroxide, e-methanol, ammonium nitrate, soda ash (Solvay), phenol and acetone (cumene), acetic acid
(Cativa), formaldehyde, ethylene (ethane cracker), ethylene glycol. Anything else goes to a request page.

## How it works

The engine is plain Python, standard library only, so the same code runs on the build machine
and in the browser through Pyodide. Species data comes from the open source `chemicals` and
`thermo` packages. Reactors use ideal gas Gibbs equilibrium or stated conversions, separations
use Raoult flashes and stated recoveries, costs are factored (screening class, typically minus 30
to plus 50 percent). No number is invented: each is either calculated or cited.

    engine/            core thermo, solver, costing, economics, hazards
    engine/processes/  one file per process (see ENGINE.md to add one)
    tools/             build_data.py, build_pdf.py, build_site.py
    site/              the static website (GitHub Pages)

## Rebuild

    unset PYTHONPATH
    P=~/.venvs/blueprint/bin/python
    $P tools/build_data.py
    for f in site/data/*.*.json; do $P tools/build_pdf.py $f site/pdf/$(basename $f .json).pdf; done
    $P tools/build_site.py
    git add -A && git commit -m "Rebuild" && git push

Pushing to main publishes `site/` through `.github/workflows/pages.yml`.

## Status

Free to use. No payments.
