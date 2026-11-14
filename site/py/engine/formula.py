"""Tiny chemical formula parser (no brackets needed for the species used)."""
import re

_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")


def atoms(formula):
    out = {}
    for el, n in _TOKEN.findall(formula):
        out[el] = out.get(el, 0) + (int(n) if n else 1)
    return out
