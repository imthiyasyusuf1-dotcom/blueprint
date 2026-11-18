# Changelog

## v1.1 (18 Nov 2026)
- Phone: header collapses to a menu under 480px, tighter hero so search and chips sit above the fold at 360 to 430 wide, 8 popular chips plus "See all 21", placeholder "e.g. ammonia, methanol", flow diagram opens further zoomed out on phones.
- New "What if" section on every design (all numbers are real engine runs made at build time by tools/build_sens.py, base case checked against the shipped data):
  - Capacity slider, 0.25x to 4x, each stop a full re-solve, with the six-tenths rule shown next to the engine figure.
  - Sensitivity tornado: gas price, power price, capacity and capital cost each 30% down and up vs levelised cost.
  - Region compare (US, EU, UK side by side) and route compare for methanol vs e-methanol.
- Share button: copies (or on phones, shares) a link holding region, capacity and custom inputs.
- Per-design 1200x630 preview images (assets/og/<id>.png) for LinkedIn and other link previews.
- Wording: compound modifiers hyphenated (first-pass, Haber-Bosch, world-scale, single-train, high-pressure ...). No numbers changed (checked: 0 numeric diffs across all 64 data files).
