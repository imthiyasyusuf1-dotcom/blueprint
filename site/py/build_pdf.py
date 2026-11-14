"""Blueprint plant design report: build a clean multi page PDF from a design JSON dict.

Imports only fpdf2 and the Python standard library, so the same file runs in the browser
under Pyodide (fpdf2 installed with micropip).

    build(data: dict, font_dir: str) -> bytes

CLI (no arguments): for every live process in site/data/index.json and every region, write
site/pdf/<id>.<REGION>.pdf

    unset PYTHONPATH; ~/.venvs/blueprint/bin/python tools/build_pdf.py
    unset PYTHONPATH; ~/.venvs/blueprint/bin/python tools/build_pdf.py site/data/ammonia.US.json out.pdf
"""
import datetime
import json
import math
import os
import re
import sys
import unicodedata

from fpdf import FPDF

# ---------------------------------------------------------------------------------------------
# palette and type
# ---------------------------------------------------------------------------------------------
INK = (11, 18, 32)
INK2 = (52, 61, 77)
MUTED = (91, 100, 116)
FAINT = (148, 156, 170)
HAIR = (228, 231, 236)
LINE = (201, 206, 214)
PANEL = (246, 247, 249)
WHITE = (255, 255, 255)
ACCENT = (35, 71, 245)
ACCENT_SOFT = (233, 237, 254)
ACCENT_MID = (145, 163, 250)
GREEN = (14, 159, 110)
GREEN_SOFT = (231, 246, 240)
RED = (217, 45, 32)
RED_SOFT = (253, 236, 234)
AMBER = (181, 113, 6)
AMBER_SOFT = (253, 244, 226)

RADIUS = 1.6
CARD_H = 21.0
MARGIN = 18.0
HEADER_Y = 9.0
CONTENT_TOP = 24.0
FOOTER_GAP = 16.0
DISCLAIMER = "Screening estimate. Not for construction. Factored estimate, typically -30% to +50%."
METHOD_TEXT = ("Capital costs are Turton et al. bare module costs with grassroots factors, escalated with "
               "the CEPCI shown. Equilibrium models use ideal gas Gibbs minimisation.")
MINUS = "\u2212"
ARROW = "\u2192"

# ---------------------------------------------------------------------------------------------
# text sanitising: Inter subset covers Latin-1 plus a few symbols
# ---------------------------------------------------------------------------------------------
_EXTRA = set("\u2018\u2019\u201a\u201b\u201c\u201d\u2022\u2026\u2082\u2083\u2190\u2191\u2192\u2193\u2212\u2264\u2265")
_ALLOWED = set(chr(c) for c in range(32, 127)) | set(chr(c) for c in range(160, 256) if c != 173) | _EXTRA
_SUP = "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"
_SUB = "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089"
# subscript digits are carried through layout as private use characters and drawn at a smaller
# size by Report.text(), so any digit can be a subscript (the font only has two subscript glyphs)
_PUA0 = 0xE000
_MAP = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u00ad": "", "\u200b": "", "\ufeff": "",
    "\u2032": "'", "\u2033": '"', "\u2248": "~", "\u2243": "~", "\u223c": "~",
    "\u21cc": "<=>", "\u21c4": "<=>", "\u2194": "<->", "\u27f6": ARROW, "\u21d2": "=>",
    "\u03bc": "\u00b5", "\u0394": "d", "\u03b7": "eta", "\u2219": "\u00b7",
    "\u2009": " ", "\u202f": " ", "\u2007": " ", "\u2002": " ", "\u2003": " ", "\u00a0": " ",
    "\u207b": "-", "\u207a": "+",
}
for _i, _c in enumerate(_SUP):
    if _c not in _ALLOWED:
        _MAP[_c] = str(_i)
for _i, _c in enumerate(_SUB):
    _MAP[_c] = chr(_PUA0 + _i)

_ELEMENTS = set("""H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se
Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pt Au Hg Pb Bi U W""".split())
_DIATOMIC = {"H", "N", "O", "F", "Cl", "Br", "I"}
_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(\d{0,2})([A-Z][A-Za-z0-9]*?)(e?)(?![A-Za-z0-9_])")
_PART = re.compile(r"([A-Z][a-z]?)(\d*)")


def _sub(digits):
    return "".join(chr(_PUA0 + int(c)) for c in digits)


def _formula(tok, loose=False):
    """Return tok with formula counts as subscripts, or None when tok is not a formula."""
    pos, parts = 0, []
    for m in _PART.finditer(tok):
        if m.start() != pos:
            return None
        parts.append((m.group(1), m.group(2)))
        pos = m.end()
    if pos != len(tok) or not parts:
        return None
    if any(el not in _ELEMENTS for el, _ in parts):
        return None
    if not any(n for _, n in parts):
        return None
    if not loose:
        if any(n and (len(n) > 2 or n.startswith("0") or n == "1") for _, n in parts):
            return None
        if len(parts) == 1 and parts[0][0] not in _DIATOMIC:
            return None
    return "".join(el + _sub(n) for el, n in parts)


def _prose(s):
    def fix(m):
        f = _formula(m.group(2))
        return (m.group(1) + f + m.group(3)) if f else m.group(0)
    s = _TOKEN.sub(fix, s)
    # units: m2, m3, Nm3 and ^2 / ^3 as real superscripts; "250 C" as degrees; leading minus signs
    s = re.sub(r"(?<![A-Za-z])(N?m|cm|mm|km)([23])(?![0-9])", lambda m: m.group(1) + ("\u00b2" if m.group(2) == "2" else "\u00b3"), s)
    s = re.sub(r"\^([23])(?![0-9])", lambda m: "\u00b2" if m.group(1) == "2" else "\u00b3", s)
    s = re.sub(r"(\d) C(?![A-Za-z0-9])", "\\1 \u00b0C", s)
    s = re.sub(r"(^|[\s(/])-(?=\d)", "\\1" + MINUS, s)
    return s


def clean(s, chem=False, raw=False):
    """Return text that only uses glyphs present in the embedded Inter subset.
    chem: treat the whole string as a formula (every count is a subscript).
    raw: no typographic changes beyond sanitising."""
    if s is None:
        return ""
    s = str(s)
    # spaced en or em dashes read best as a comma
    s = s.replace(" \u2013 ", ", ").replace(" \u2014 ", ", ").replace("\u2014", ", ")
    out = []
    for ch in s:
        o = ord(ch)
        if _PUA0 <= o <= _PUA0 + 9:
            out.append(ch)
        elif ch in _MAP:
            out.append(_MAP[ch])
        elif ch in _ALLOWED:
            out.append(ch)
        elif ch in ("\n", "\t"):
            out.append(" ")
        else:
            dec = unicodedata.normalize("NFKD", ch)
            dec = "".join(c for c in dec if c in _ALLOWED and not unicodedata.combining(c))
            out.append(dec)
    s = "".join(out)
    if raw:
        return s
    if chem:
        return re.sub(r"([A-Za-z)\]])(\d+)", lambda m: m.group(1) + _sub(m.group(2)), s)
    return _prose(s)


_BIND_A = re.compile(r"(?<![A-Za-z])([A-Za-z]{1,2}|LMTD|U|D|L|H|K) (?=[\d\u2212])")
_BIND_B = re.compile(r"(\d) (?=[A-Za-z%\u00b0\u00b5/][A-Za-z0-9/%\u00b2\u00b3\u00b0\u00b5]{0,7}(?:[\s,;.)]|$))")


def _is_digit(c):
    return "0" <= c <= "9"


# ---------------------------------------------------------------------------------------------
# number formatting
# ---------------------------------------------------------------------------------------------
def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _neg(s):
    return s.replace("-", MINUS, 1) if s.startswith("-") else s


def fnum(v, sig=3, dash="-"):
    """Thousands separators, sensible significant figures, true minus sign."""
    x = _num(v)
    if x is None:
        return dash
    if x == 0:
        return "0"
    a = abs(x)
    if a >= 10 ** sig:
        s = "{:,.0f}".format(x)
    else:
        dec = max(0, sig - 1 - int(math.floor(math.log10(a))))
        dec = min(dec, 6)
        s = "{:,.{}f}".format(x, dec)
        if "." in s:
            s = s.rstrip("0").rstrip(".") if dec > 0 and a >= 1 else s
    if s in ("-0", "0.0", "-0.0"):
        s = "0"
    return _neg(s)


def fflow(v):
    """Flows: integers above 100, otherwise 3 significant figures."""
    x = _num(v)
    if x is None:
        return "-"
    if x == 0:
        return "0"
    if abs(x) >= 100:
        return _neg("{:,.0f}".format(x))
    if abs(x) < 0.001:
        return "<0.001" if x > 0 else _neg("-<0.001")
    return fnum(x, 3)


def ffix(v, dec=1, dash="-"):
    x = _num(v)
    if x is None:
        return dash
    s = "{:,.{}f}".format(x, dec)
    if float(s.replace(",", "")) == 0:
        s = s.lstrip("-")
    return _neg(s)


def money(v, dash="-"):
    """USD with k, M or B suffix."""
    x = _num(v)
    if x is None:
        return dash
    a = abs(x)
    sign = MINUS if x < 0 else ""
    if a >= 1e9:
        s = "{:,.2f}B".format(a / 1e9)
    elif a >= 1e8:
        s = "{:,.0f}M".format(a / 1e6)
    elif a >= 1e6:
        s = "{:,.1f}M".format(a / 1e6)
    elif a >= 1e5:
        s = "{:,.0f}k".format(a / 1e3)
    elif a >= 1e3:
        s = "{:,.1f}k".format(a / 1e3)
    else:
        s = "{:,.0f}".format(a)
    return sign + "$" + s


def usd_k(v):
    x = _num(v)
    if x is None:
        return "-"
    k = x / 1e3
    if abs(k) >= 10:
        return _neg("{:,.0f}".format(k))
    return _neg("{:,.1f}".format(k))


def usd_m(v, dec=2):
    x = _num(v)
    if x is None:
        return "-"
    return _neg("{:,.{}f}".format(x / 1e6, dec))


def pct(v, dec=1, frac=False):
    x = _num(v)
    if x is None:
        return "-"
    if frac:
        x *= 100
    return ffix(x, dec) + "%"


def per_t(v):
    x = _num(v)
    if x is None:
        return "-"
    return _neg("${:,.0f}".format(x)) if abs(x) >= 100 else _neg("${:,.2f}".format(x))


def g(d, *path, default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int) and -len(cur) <= p < len(cur):
            cur = cur[p]
        else:
            return default
        if cur is None:
            return default
    return cur


# ---------------------------------------------------------------------------------------------
# the PDF
# ---------------------------------------------------------------------------------------------
class Report(FPDF):
    def __init__(self, data, font_dir):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.data = data
        self.set_margins(MARGIN, CONTENT_TOP, MARGIN)
        self.set_auto_page_break(False)
        self.add_font("Inter", "", os.path.join(font_dir, "Inter-Regular.ttf"))
        self.add_font("Inter", "B", os.path.join(font_dir, "Inter-Bold.ttf"))
        self.add_font("InterSemi", "", os.path.join(font_dir, "Inter-SemiBold.ttf"))
        self.set_font("Inter", "", 9)
        self.alias_nb_pages("{nb}")
        self.section_no = 0
        self.cur_section = ""
        self._zero_w = {}
        self.total_pages = None
        self.toc_entries = None
        self.sections_found = []

    # ---- rich text: private use digits are drawn as subscripts --------------------------------
    @staticmethod
    def _runs(s):
        runs = []
        for ch in s:
            sub = _PUA0 <= ord(ch) <= _PUA0 + 9
            c = str(ord(ch) - _PUA0) if sub else ch
            if runs and runs[-1][1] == sub:
                runs[-1][0] += c
            else:
                runs.append([c, sub])
        return runs

    def get_string_width(self, s, normalized=False, markdown=False):
        s = str(s)
        if not any(_PUA0 <= ord(c) <= _PUA0 + 9 for c in s):
            return super().get_string_width(s, normalized, markdown)
        size = self.font_size_pt
        w = 0.0
        for t, sub in self._runs(s):
            if sub:
                self.set_font_size(size * 0.7)
            w += super().get_string_width(t, normalized, markdown)
            if sub:
                self.set_font_size(size)
        return w

    def text(self, x, y, text=""):
        s = str(text)
        if not any(_PUA0 <= ord(c) <= _PUA0 + 9 for c in s):
            return super().text(x, y, s)
        size = self.font_size_pt
        for t, sub in self._runs(s):
            if sub:
                self.set_font_size(size * 0.7)
                super().text(x, y + size / 72 * 25.4 * 0.16, t)
                w = super().get_string_width(t)
                self.set_font_size(size)
            else:
                super().text(x, y, t)
                w = super().get_string_width(t)
            x += w
        return None

    # ---- primitives -----------------------------------------------------------------------
    def font(self, style="r", size=9, color=INK):
        if style == "b":
            self.set_font("Inter", "B", size)
        elif style == "s":
            self.set_font("InterSemi", "", size)
        else:
            self.set_font("Inter", "", size)
        self.set_text_color(*color)

    def fill(self, c):
        self.set_fill_color(*c)

    def stroke(self, c, w=0.2):
        self.set_draw_color(*c)
        self.set_line_width(w)

    def sw(self, s):
        return self.get_string_width(clean(s))

    def put(self, x, y, s, align="L", w=None, raw=False, chem=False):
        """Write a single line with its baseline placed from the top y of a text box."""
        s = clean(s, chem=chem, raw=raw)
        if align != "L":
            tw = self.get_string_width(s)
            if align == "R":
                x = x - tw if w is None else x + w - tw
            else:
                x = x - tw / 2 if w is None else x + (w - tw) / 2
        self.text(x, y + self.font_size * 0.78, s)

    def tnum(self, x_right, y, s):
        """Right aligned number with tabular (fixed width) digits."""
        s = clean(s)
        key = (self.font_family, self.font_style, self.font_size_pt)
        zw = self._zero_w.get(key)
        if zw is None:
            zw = self._zero_w[key] = self.get_string_width("0")
        x = x_right
        base = y + self.font_size * 0.78
        for ch in reversed(s):
            if _is_digit(ch):
                cw = self.get_string_width(ch)
                x -= zw
                self.text(x + (zw - cw) / 2, base, ch)
            else:
                x -= self.get_string_width(ch)
                self.text(x, base, ch)
        return x

    def tnum_width(self, s):
        s = clean(s)
        zw = self.get_string_width("0")
        return sum(zw if _is_digit(c) else self.get_string_width(c) for c in s)

    def _split_long(self, wd, w):
        """Break a token wider than w, preferring breaks after / - _ . ? & ="""
        out = []
        while self.get_string_width(wd) > w and len(wd) > 1:
            cut = 1
            best = None
            for k in range(1, len(wd)):
                if self.get_string_width(wd[:k]) > w:
                    break
                cut = k
                if wd[k - 1] in "/-_.?&=":
                    best = k
            k = best if best and best > cut * 0.5 else cut
            out.append(wd[:k])
            wd = wd[k:]
        out.append(wd)
        return out

    def wrap(self, s, w, raw=False):
        s = clean(s, raw=raw)
        if not raw:
            # keep short labels with their numbers and numbers with their units
            s = _BIND_A.sub("\\1\u00a0", s)
            s = _BIND_B.sub("\\1\u00a0", s)
        lines = []
        for para in s.split("\n"):
            cur = ""
            for wd in para.split(" "):
                trial = wd if not cur else cur + " " + wd
                if self.get_string_width(trial) <= w:
                    cur = trial
                    continue
                if cur:
                    lines.append(cur)
                pieces = self._split_long(wd, w)
                lines.extend(pieces[:-1])
                cur = pieces[-1]
            lines.append(cur)
        return [ln.replace("\u00a0", " ") for ln in lines]

    def para(self, x, y, w, s, lh=None, max_lines=None, align="L"):
        lh = lh or self.font_size * 1.45
        lines = self.wrap(s, w)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" .,;") + "\u2026"
        for i, ln in enumerate(lines):
            self.put(x, y + i * lh, ln, align=align, w=w)
        return y + len(lines) * lh

    def para_h(self, w, s, lh=None):
        lh = lh or self.font_size * 1.45
        return len(self.wrap(s, w)) * lh

    def rrect(self, x, y, w, h, fill=None, border=None, r=RADIUS, lw=0.2):
        style = ""
        if fill is not None:
            self.fill(fill)
            style += "F"
        if border is not None:
            self.stroke(border, lw)
            style += "D"
        if not style:
            return
        if r <= 0:
            self.rect(x, y, w, h, style=style)
        else:
            self.rect(x, y, w, h, style=style, round_corners=True, corner_radius=min(r, w / 2, h / 2))

    def hline(self, x1, x2, y, c=HAIR, w=0.2):
        self.stroke(c, w)
        self.line(x1, y, x2, y)

    def badge(self, x, y, text, kind="pass", align="L"):
        colors = {"pass": (GREEN, GREEN_SOFT), "fail": (RED, RED_SOFT), "na": (MUTED, PANEL),
                  "warn": (AMBER, AMBER_SOFT), "accent": (ACCENT, ACCENT_SOFT)}
        fg, bg = colors.get(kind, colors["na"])
        self.font("s", 6.5, fg)
        tw = self.sw(text)
        w = tw + 5.2
        if align == "R":
            x -= w
        elif align == "C":
            x -= w / 2
        self.rrect(x, y, w, 4.2, fill=bg, r=2.1)
        self.fill(fg)
        self.ellipse(x + 1.6, y + 1.6, 1.0, 1.0, style="F")
        self.put(x + 3.4, y + 1.05, text)
        return w

    def chem_width(self, s, size):
        self.set_font_size(size)
        return self.get_string_width(clean(s, chem=True))

    def chem(self, x, y, s, size, align="L", w=None):
        """Formula with subscript counts."""
        self.set_font_size(size)
        s = clean(s, chem=True)
        tw = self.get_string_width(s)
        if align == "R":
            x = (x + w - tw) if w is not None else x - tw
        elif align == "C":
            x = (x + (w - tw) / 2) if w is not None else x - tw / 2
        self.text(x, y + self.font_size * 0.78, s)
        return x + tw

    # ---- page furniture --------------------------------------------------------------------
    def header(self):
        x0, x1 = MARGIN, self.w - MARGIN
        # wordmark: a small cobalt tile with a grid motif, then the name
        self.rrect(x0, HEADER_Y, 4.6, 4.6, fill=ACCENT, r=1.1)
        self.stroke(WHITE, 0.25)
        self.line(x0 + 1.2, HEADER_Y + 2.3, x0 + 3.4, HEADER_Y + 2.3)
        self.line(x0 + 2.3, HEADER_Y + 1.2, x0 + 2.3, HEADER_Y + 3.4)
        self.font("b", 9.5, INK)
        self.put(x0 + 6.2, HEADER_Y + 0.75, "Blueprint")
        d = self.data
        label = " \u00b7 ".join(p for p in [clean(d.get("product") or d.get("title") or ""),
                                           clean(d.get("region_label") or d.get("region") or "")] if p)
        self.font("r", 7.5, MUTED)
        wm = self.get_string_width("Blueprint")
        self.set_font("Inter", "B", 9.5)
        wm = self.get_string_width("Blueprint")
        self.font("r", 7.5, MUTED)
        if label:
            self.put(x0 + 6.2 + wm + 3.0, HEADER_Y + 1.25, label)
        total = self.total_pages or "{nb}"
        self.put(x1, HEADER_Y + 1.25, "Page {} of {}".format(self.page_no(), total), align="R")
        self.hline(x0, x1, HEADER_Y + 7.6)

    def footer(self):
        x0, x1 = MARGIN, self.w - MARGIN
        y = self.h - 12.5
        self.hline(x0, x1, y)
        self.font("r", 6.8, MUTED)
        self.put(x0, y + 2.2, DISCLAIMER, raw=True)
        if self.cur_section:
            self.put(x1, y + 2.2, self.cur_section, align="R")

    @property
    def bottom(self):
        return self.h - FOOTER_GAP - 2

    @property
    def cw(self):
        return self.w - 2 * MARGIN

    def section(self, title, subtitle=None, orientation="P"):
        self.section_no += 1
        self.add_page(orientation=orientation)
        self.sections_found.append((self.section_no, clean(title), self.page_no()))
        self.cur_section = clean(title)
        self.start_section(clean(title))
        y = CONTENT_TOP
        self.font("s", 7.5, ACCENT)
        self.put(MARGIN, y, "{:02d}".format(self.section_no))
        self.font("b", 17, INK)
        self.put(MARGIN, y + 4.2, title)
        y += 12.2
        if subtitle:
            self.font("r", 8.6, MUTED)
            y = self.para(MARGIN, y, self.cw, subtitle, lh=4.1) + 1.0
        return y + 4.0

    def continue_page(self):
        self.add_page(orientation=self.cur_orientation)
        self.font("s", 7.5, MUTED)
        self.put(MARGIN, CONTENT_TOP, clean(self.cur_section) + ", continued")
        return CONTENT_TOP + 7.0

    def ensure(self, y, need):
        if y + need > self.bottom:
            return self.continue_page()
        return y

    def subhead(self, y, text, right=None, x=None, w=None):
        x = MARGIN if x is None else x
        w = self.cw if w is None else w
        self.font("s", 10, INK)
        self.put(x, y, text)
        if right:
            self.font("r", 7.5, MUTED)
            self.put(x + w, y + 0.9, right, align="R")
        return y + 6.6

    # ---- tables ---------------------------------------------------------------------------
    def table(self, y, cols, rows, size=7.6, x=None, w=None, head_size=6.8, pad=1.8, min_h=6.2,
              total_rows=(), zebra=False, repeat_title=None):
        """cols: [{title, w (fraction), align L|R|C, kind text|num|chem|badge|link}]
        rows: list of lists; a cell may be a dict {t, sub, color, style, kind, link, badge}."""
        x = MARGIN if x is None else x
        w = self.cw if w is None else w
        tot = sum(c["w"] for c in cols)
        widths = [c["w"] / tot * w for c in cols]
        lh = size / 72 * 25.4 * 1.32

        def fit_size(t, cwid):
            hs = head_size
            while True:
                self.font("s", hs, MUTED)
                lines = t.split("\n") if "\n" in t else self.wrap(t, cwid - 2 * pad + 0.6)
                if len(lines) <= 2 and all(self.sw(ln) <= cwid - 2 * pad + 0.6 for ln in lines) and \
                        all(self.sw(wd) <= cwid - 2 * pad + 0.6 for wd in t.replace("\n", " ").split(" ")) or hs < 5.2:
                    return hs
                hs -= 0.2

        common_hs = min([fit_size(c.get("title", ""), cwid) for c, cwid in zip(cols, widths)] + [head_size])

        def head(y):
            self.rrect(x, y, w, 6.4, fill=PANEL, r=RADIUS)
            self.font("s", head_size, MUTED)
            cx = x
            for c, cwid in zip(cols, widths):
                a = c.get("align", "L")
                t = c.get("title", "")
                hs = common_hs
                self.font("s", hs, MUTED)
                lines = t.split("\n") if "\n" in t else self.wrap(t, cwid - 2 * pad + 0.6)
                self.font("s", head_size, MUTED)
                if len(lines) == 1:
                    self.font("s", hs, MUTED)
                    self.put(cx + pad, y + 2.05, lines[0], align=a, w=cwid - 2 * pad)
                else:
                    self.font("s", hs, MUTED)
                    for i, ln in enumerate(lines[:2]):
                        self.put(cx + pad, y + 0.75 + i * 2.55, ln, align=a, w=cwid - 2 * pad)
                    self.font("s", head_size, MUTED)
                cx += cwid
            return y + 6.4

        def cell_lines(cell, cwid, col):
            if isinstance(cell, dict):
                t = cell.get("t", "")
                st = cell.get("style", "r")
                sub = cell.get("sub")
            else:
                t, st, sub = cell, "r", None
            kind = (cell.get("kind") if isinstance(cell, dict) else None) or col.get("kind", "text")
            self.font(st, size)
            if kind in ("num", "badge", "chem"):
                main = [clean(t)]
            else:
                main = self.wrap(t, cwid - 2 * pad)
            subl = []
            if sub:
                self.font("r", size - 1.0)
                subl = self.wrap(sub, cwid - 2 * pad)
            return main, subl

        y = head(y)
        for ri, row in enumerate(rows):
            layouts = []
            nmax = 1.0
            for cell, cwid, col in zip(row, widths, cols):
                main, subl = cell_lines(cell, cwid, col)
                layouts.append((main, subl))
                nmax = max(nmax, len(main) * lh + len(subl) * lh * 0.88)
            rh = max(min_h, nmax + 2 * pad - 0.3)
            is_total = ri in total_rows or (ri - len(rows)) in total_rows
            if y + rh > self.bottom:
                y = self.continue_page()
                if repeat_title:
                    y = self.subhead(y, repeat_title)
                y = head(y)
            if zebra and ri % 2 == 1:
                self.rrect(x, y, w, rh, fill=(250, 250, 251), r=0)
            if is_total:
                self.hline(x, x + w, y, LINE, 0.3)
            cx = x
            for cell, cwid, col, (main, subl) in zip(row, widths, cols, layouts):
                d = cell if isinstance(cell, dict) else {"t": cell}
                a = d.get("align", col.get("align", "L"))
                kind = d.get("kind") or col.get("kind", "text")
                st = d.get("style", "s" if is_total else "r")
                color = d.get("color", INK)
                ty = y + pad
                if kind == "badge":
                    b = d.get("badge", "na")
                    bx = cx + pad if a == "L" else (cx + cwid - pad if a == "R" else cx + cwid / 2)
                    self.badge(bx, y + pad - 0.55, d.get("t", ""), b, align=a)
                elif kind == "num":
                    self.font(st, size, FAINT if main[0] == "-" else color)
                    self.tnum(cx + cwid - pad, ty, main[0])
                elif kind == "chem":
                    self.font(st, size, color)
                    self.chem(cx + pad, ty, main[0], size, align=a, w=cwid - 2 * pad)
                else:
                    self.font(st, size, color)
                    off = 0
                    if d.get("swatch"):
                        self.rrect(cx + pad, ty + 0.35, 2.4, 2.4, fill=d["swatch"], r=0.5)
                        off = 4.2
                    for i, ln in enumerate(main):
                        self.put(cx + pad + off, ty + i * lh, ln, align=a, w=cwid - 2 * pad - off)
                    if d.get("link"):
                        self.link(cx + pad, ty, min(cwid - 2 * pad, self.get_string_width(main[0]) if len(main) == 1
                                                    else cwid - 2 * pad), len(main) * lh, d["link"])
                if subl:
                    self.font("r", size - 1.0, MUTED)
                    sy = ty + len(main) * lh
                    for i, ln in enumerate(subl):
                        self.put(cx + pad, sy + i * lh * 0.88, ln, align=a, w=cwid - 2 * pad)
                cx += cwid
            y += rh
            self.hline(x, x + w, y, HAIR if not is_total else LINE, 0.2)
        return y + 2.0

    def kv_list(self, y, items, x=None, w=None, size=8.2, row_h=6.4, label_w=None):
        """Two column key value rows with hairlines. items: [(label, value_str, unit_str)]."""
        x = MARGIN if x is None else x
        w = self.cw if w is None else w
        self.font("r", size - 1, MUTED)
        ucol = max([self.sw(u) for _, _, u in items if u] or [0])
        ucol = ucol + 1.6 if ucol else 0
        for label, value, unit in items:
            self.font("r", size, INK2)
            lines = self.wrap(label, (label_w or w * 0.62) - 2)
            rh = max(row_h, len(lines) * size / 72 * 25.4 * 1.32 + 3.0)
            if y + rh > self.bottom:
                y = self.continue_page()
            for i, ln in enumerate(lines):
                self.put(x + 1.8, y + 1.6 + i * size / 72 * 25.4 * 1.32, ln)
            if unit:
                self.font("r", size - 1, MUTED)
                self.put(x + w - 1.8 - ucol + 1.6, y + 1.6 + 0.35, unit)
            self.font("s", size, INK)
            self.tnum(x + w - 1.8 - ucol, y + 1.6, value)
            y += rh
            self.hline(x, x + w, y)
        return y

    def stat_card(self, x, y, w, h, label, value, sub=None, accent=False, color=None):
        """Panel with a label, a large value and an optional caption. h is normally CARD_H."""
        self.rrect(x, y, w, h, fill=PANEL, r=RADIUS + 0.4)
        self.font("r", 7.2, MUTED)
        self.para(x + 4, y + 3.4, w - 8, label, lh=3.2, max_lines=1)
        self.font("b", 15, color or (ACCENT if accent else INK))
        self.put(x + 4, y + 7.6, value)
        if sub:
            self.font("r", 6.8, MUTED)
            self.para(x + 4, y + h - 5.6, w - 8, sub, lh=3.0, max_lines=1)


# ---------------------------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------------------------
def _validation_counts(d):
    v = d.get("validation") or []
    n_pass = sum(1 for r in v if r.get("pass") is True)
    n_fail = sum(1 for r in v if r.get("pass") is False)
    return n_pass, n_fail, len(v)


def cover(pdf, d):
    pdf.add_page()
    pdf.cur_section = "Summary"
    pdf.start_section("Summary")
    x0, cw = MARGIN, pdf.cw
    y = CONTENT_TOP + 4
    pdf.font("s", 7.5, ACCENT)
    pdf.set_char_spacing(0.6)
    pdf.put(x0, y, "PLANT DESIGN REPORT")
    pdf.set_char_spacing(0)
    y += 6
    pdf.font("b", 24, INK)
    title = d.get("title") or d.get("product") or "Process plant"
    y = pdf.para(x0, y, cw, title, lh=10.0)
    y += 2.5

    cap = d.get("capacity") or {}

    def withu(v, u):
        return (fnum(v, 4) + " " + u) if _num(v) is not None else "-"

    meta = [("Capacity", withu(cap.get("t_per_day"), "t/d")),
            ("Annual output", withu(cap.get("t_per_year"), "t/y")),
            ("Region", clean(d.get("region_label") or d.get("region") or "-")),
            ("Operating hours", withu(cap.get("hours_per_year"), "h/y"))]
    gap = 4.0
    c3 = (cw - 2 * gap) / 3
    pdf.hline(x0, x0 + cw, y)
    colw = cw / 4
    for i, (lab, val) in enumerate(meta):
        cx = x0 + i * colw
        if i:
            pdf.stroke(HAIR, 0.2)
            pdf.line(cx - 4, y + 2.5, cx - 4, y + 13.5)
        pdf.font("r", 7.2, MUTED)
        pdf.put(cx, y + 3.2, lab)
        pdf.font("s", 11, INK)
        pdf.put(cx, y + 7.6, val)
    y += 16
    pdf.hline(x0, x0 + cw, y)
    y += 6

    if d.get("summary"):
        pdf.font("r", 10.5, INK)
        y = pdf.para(x0, y, cw, d["summary"], lh=5.4) + 2.5
    if d.get("route"):
        pdf.font("s", 7.5, MUTED)
        pdf.put(x0, y, "Process route")
        pdf.font("r", 8.6, INK2)
        y = pdf.para(x0, y + 4.4, cw, d["route"], lh=4.3) + 4

    e = d.get("economics") or {}
    capx = d.get("capex") or {}
    y = pdf.subhead(y, "Headline economics", right="All money in US dollars")
    fci = e.get("fci") if e.get("fci") is not None else capx.get("fixed_capital")
    irr = _num(e.get("irr"))
    pb = _num(e.get("payback_years"))
    rate, life, tax = e.get("rate"), e.get("life"), e.get("tax")
    cards = [
        ("Fixed capital investment", money(fci),
         "{} per annual tonne".format(per_t(e.get("capex_per_annual_tonne"))) if e.get("capex_per_annual_tonne") is not None else None),
        ("Cost of manufacture per tonne", per_t(e.get("cost_per_tonne")), "Cash cost, excluding capital charge"),
        ("Levelised cost per tonne", per_t(e.get("levelised_cost_per_tonne")),
         "Capital at {} over {} years".format(pct(rate, 0, frac=True), fnum(life, 3)) if rate is not None and life is not None else None),
        ("Net present value", money(e.get("npv")),
         "At {} discount rate".format(pct(rate, 0, frac=True)) if rate is not None else None),
        ("Internal rate of return", pct(irr, 1, frac=True) if irr is not None else "None",
         ("After tax at {}".format(pct(tax, 0, frac=True)) if tax is not None else None) if irr is not None else "Never pays back"),
        ("Payback period", (ffix(pb, 1) + " years") if pb is not None else "-",
         "After start-up" if pb is not None else None),
    ]
    for i, (lab, val, sub) in enumerate(cards):
        cx = x0 + (i % 3) * (c3 + gap)
        cy = y + (i // 3) * (CARD_H + gap)
        pdf.stat_card(cx, cy, c3, CARD_H, lab, val, sub)
    y += 2 * CARD_H + gap + 7

    # bottom: KPIs over two grid columns, checks in the third
    lw = 2 * c3 + gap
    rx = x0 + lw + gap + 6
    rw = x0 + cw - rx
    rx = x0 + 2 * (c3 + gap)
    rw = c3
    lw = 2 * c3 + gap
    ytop = y
    kpis = d.get("kpis") or []
    if kpis:
        yl = pdf.subhead(y, "Key performance indicators", x=x0, w=lw)
        pdf.hline(x0, x0 + lw, yl - 1.6)
        items = [(k.get("label") or "", fnum(k.get("value"), 3), k.get("unit") or "") for k in kpis]
        yl = pdf.kv_list(yl - 1.6, items, x=x0, w=lw, size=7.8, row_h=5.9)
    else:
        yl = y

    n_pass, n_fail, n = _validation_counts(d)
    yr = pdf.subhead(ytop, "Checks", x=rx, w=rw) - 1.6
    if n:
        pdf.stat_card(rx, yr, rw, CARD_H, "Validation against published data", "{} of {}".format(n_pass, n),
                      "checks within tolerance", color=GREEN if n_pass == n else INK)
        if n_fail:
            pdf.badge(rx + rw - 4, yr + 9.0, "{} outside".format(n_fail), "fail", align="R")
        elif n_pass == n:
            pdf.badge(rx + rw - 4, yr + 9.0, "All pass", "pass", align="R")
        yr += CARD_H + gap
    c = d.get("carbon") or {}
    if c.get("total") is not None:
        pdf.stat_card(rx, yr, rw, CARD_H, "Carbon intensity, scope 1 and 2", fnum(c.get("total"), 3), c.get("unit") or "")
        yr += CARD_H + gap
    bal = d.get("balance") or {}
    if bal.get("closure_pct") is not None:
        pdf.stat_card(rx, yr, rw, CARD_H, "Mass balance closure", ffix(bal.get("closure_pct"), 3) + "%",
                      "Out minus in, plant boundary")
        yr += CARD_H + gap

    # contents, filling the rest of the page when there is room
    toc = pdf.toc_entries or []
    y = yl + 8
    rows_n = (len(toc) + 1) // 2
    if toc and y + 8 + rows_n * 5.6 <= pdf.bottom:
        y = pdf.subhead(y, "Contents")
        colw2 = lw / 2 - 3
        cols_x = [x0, x0 + lw / 2 + 3]
        toc_size = 7.8
        pdf.font("r", toc_size)
        while max(pdf.sw(t_) for _, t_, _ in toc) > colw2 - 6.5 - 7 and toc_size > 6.2:
            toc_size -= 0.2
            pdf.font("r", toc_size)
        for i, (num, title_, page) in enumerate(toc):
            cx = cols_x[i // rows_n]
            cy = y + (i % rows_n) * 5.6
            pdf.font("s", 7.4, ACCENT)
            pdf.put(cx, cy + 1.2, "{:02d}".format(num))
            pdf.font("r", toc_size, INK2)
            pdf.put(cx + 6.5, cy + 1.1 + (7.8 - toc_size) * 0.12, title_)
            pdf.link(cx, cy, colw2, 5.6, pdf.add_link(page=page))
            pdf.font("r", 7.6, MUTED)
            pdf.tnum(cx + colw2, cy + 1.1, str(page))
            pdf.hline(cx, cx + colw2, cy + 5.6)


# ---- process flow diagram ---------------------------------------------------------------------
def _stream_is_product(s, prod_ids):
    comps = s.get("components") or {}
    for pid in prod_ids:
        c = comps.get(pid) or {}
        if (_num(c.get("mass_frac")) or 0) >= 0.5:
            return True
    return False


def _is_unit_ref(v, ids):
    return isinstance(v, str) and v in ids


def pfd(pdf, d):
    units = [u for u in (d.get("units") or []) if isinstance(u, dict) and u.get("id")]
    streams = [s for s in (d.get("streams") or []) if isinstance(s, dict)]
    if not units:
        return
    y_top = pdf.section("Process flow diagram",
                        "Units placed on the design grid, streams labelled with their ids (see the stream table). "
                        "Feeds enter from the left, products and other exits leave to the right.",
                        orientation="L")

    # grid positions (fall back to a single row if pos is missing or clashes)
    ids = {}
    taken = set()
    for i, u in enumerate(units):
        p = u.get("pos")
        try:
            c, r = int(p[0]), int(p[1])
        except (TypeError, ValueError, IndexError):
            c, r = None, None
        if c is None or (c, r) in taken or c < 0 or r < 0:
            c, r = 0, 0
            while (c, r) in taken:
                c += 1
        taken.add((c, r))
        ids[u["id"]] = {"u": u, "c": c, "r": r}
    ncol = max(v["c"] for v in ids.values()) + 1
    nrow = max(v["r"] for v in ids.values()) + 1
    occupied = {(v["c"], v["r"]) for v in ids.values()}

    W, H = pdf.w, pdf.h
    label_w = 34.0
    gx0 = MARGIN + label_w + 2
    gx1 = W - MARGIN - label_w - 2
    gy0 = y_top + 1
    gy1 = pdf.bottom - 9
    pitch_x = (gx1 - gx0) / ncol
    box_w = min(40.0, pitch_x - 9.0)
    box_h = 16.0
    lane_h = min(34.0, (gy1 - gy0 - nrow * box_h) / (nrow + 1))
    used_h = nrow * box_h + (nrow + 1) * lane_h
    gy0 = gy0 + max(0.0, (gy1 - gy0 - used_h) / 2) * 0.3

    def col_cx(c):
        return gx0 + (c + 0.5) * pitch_x

    def row_top(r):
        return gy0 + lane_h * (r + 1) + box_h * r

    def gap_x(gi):
        return gx0 + gi * pitch_x

    def lane_y(li):
        return gy0 + li * (lane_h + box_h) + lane_h / 2

    for k, v in ids.items():
        v["x"] = col_cx(v["c"]) - box_w / 2
        v["y"] = row_top(v["r"])
        v["cx"] = col_cx(v["c"])
        v["cy"] = v["y"] + box_h / 2

    prod_ids = [p.get("id") for p in (d.get("products") or []) if p.get("id")]

    # ---- classify streams ------------------------------------------------------------------
    def src_of(s):
        f = s.get("from")
        if _is_unit_ref(f, ids):
            return ("unit", f)
        if f == "IN":
            return ("in", None)
        return ("none", None)

    def dst_of(s):
        t = s.get("to")
        if _is_unit_ref(t, ids):
            return ("unit", t)
        if t == "OUT":
            return ("out", None)
        return ("none", None)

    incoming = {k: [] for k in ids}
    outgoing = {k: [] for k in ids}
    for s in streams:
        a, b = src_of(s), dst_of(s)
        if b[0] == "unit" and a[0] != "none":
            incoming[b[1]].append(s)
        if a[0] == "unit":
            outgoing[a[1]].append(s)

    # mixers: a stream with no source feeding a unit that has no other inlet
    mixers = {}
    hidden = set()
    for s in streams:
        a, b = src_of(s), dst_of(s)
        if a[0] == "none" and b[0] == "unit":
            if incoming[b[1]]:
                hidden.add(s.get("id"))  # internal mix of streams already drawn
            else:
                mixers[s.get("id")] = {"stream": s, "unit": b[1]}
    mixer_list = list(mixers.values())

    # recycle detection: back edges in a depth first walk from the fed units
    adj = {k: [] for k in ids}
    for s in streams:
        a, b = src_of(s), dst_of(s)
        if a[0] == "unit" and b[0] == "unit":
            adj[a[1]].append((s.get("id"), b[1]))
    starts = []
    for s in streams:
        a, b = src_of(s), dst_of(s)
        if b[0] == "unit" and a[0] in ("in", "none") and b[1] not in starts:
            starts.append(b[1])
    for m in mixer_list:
        if m["unit"] not in starts:
            starts.append(m["unit"])
    starts += [k for k in sorted(ids, key=lambda k: (ids[k]["c"], ids[k]["r"])) if k not in starts]
    state = {}
    back = set()

    def dfs(n):
        state[n] = 1
        for sid, m in adj[n]:
            if state.get(m) == 1:
                back.add(sid)
            elif m not in state:
                dfs(m)
        state[n] = 2

    for s0 in starts:
        if s0 not in state:
            dfs(s0)

    # ---- routing --------------------------------------------------------------------------
    ports = {}  # (unit, side) -> list of [key_fn, slot] entries

    def port(unit, side, other_xy):
        lst = ports.setdefault((unit, side), [])
        ent = {"other": other_xy, "pos": None}
        lst.append(ent)
        return ent

    edges = []
    left_x = gx0 - 2.0 if True else 0
    left_x = MARGIN + label_w + 1.0
    right_x = W - MARGIN - label_w - 1.0

    def row_has_left(c, r):
        return any((cc, r) in occupied for cc in range(0, c))

    def row_has_right(c, r):
        return any((cc, r) in occupied for cc in range(c + 1, ncol))

    bottom_exit_rows = set()
    for s in streams:
        a, b = src_of(s), dst_of(s)
        if a[0] == "unit" and b[0] == "out":
            A = ids[a[1]]
            if row_has_right(A["c"], A["r"]) and not (A["r"] == 0 and nrow > 1):
                bottom_exit_rows.add(A["r"])

    for s in streams:
        sid = s.get("id")
        if sid in hidden:
            continue
        a, b = src_of(s), dst_of(s)
        e = {"s": s, "id": sid, "recycle": sid in back,
             "product": b[0] == "out" and _stream_is_product(s, prod_ids)}
        if a[0] == "unit" and b[0] == "unit" and a[1] != b[1]:
            A, B = ids[a[1]], ids[b[1]]
            dc, dr = B["c"] - A["c"], B["r"] - A["r"]
            if dr == 0 and abs(dc) == 1:
                sa, sb = ("right", "left") if dc > 0 else ("left", "right")
                e.update(kind="HVH", gap=max(A["c"], B["c"]),
                         p0=port(a[1], sa, (B["cx"], B["cy"])), p1=port(b[1], sb, (A["cx"], A["cy"])))
            elif abs(dr) == 1:
                sa, sb = ("bottom", "top") if dr > 0 else ("top", "bottom")
                e.update(kind="VHV", lane=max(A["r"], B["r"]),
                         p0=port(a[1], sa, (B["cx"], B["cy"])), p1=port(b[1], sb, (A["cx"], A["cy"])))
            elif dr == 0:
                # same row, not adjacent: go round through the lane below, or above when exits use the lane below
                if A["r"] in bottom_exit_rows and A["r"] > 0:
                    e.update(kind="VHV", lane=A["r"],
                             p0=port(a[1], "top", (B["cx"], B["cy"] - 99)), p1=port(b[1], "top", (A["cx"], A["cy"] - 99)))
                else:
                    e.update(kind="VHV", lane=A["r"] + 1,
                             p0=port(a[1], "bottom", (B["cx"], B["cy"] + 99)), p1=port(b[1], "bottom", (A["cx"], A["cy"] + 99)))
            elif dc == 0:
                e.update(kind="HVH", gap=A["c"] + 1,
                         p0=port(a[1], "right", (B["cx"] + 99, B["cy"])), p1=port(b[1], "right", (A["cx"] + 99, A["cy"])))
            elif abs(dc) == 1:
                sa, sb = ("right", "left") if dc > 0 else ("left", "right")
                e.update(kind="HVH", gap=max(A["c"], B["c"]),
                         p0=port(a[1], sa, (B["cx"], B["cy"])), p1=port(b[1], sb, (A["cx"], A["cy"])))
            else:
                sa, sb = ("right", "left") if dc > 0 else ("left", "right")
                ga = A["c"] + 1 if dc > 0 else A["c"]
                gb = B["c"] if dc > 0 else B["c"] + 1
                lane = B["r"] if dr > 0 else B["r"] + 1
                e.update(kind="HVHVH", gap=ga, gap2=gb, lane=lane,
                         p0=port(a[1], sa, (B["cx"], B["cy"])), p1=port(b[1], sb, (A["cx"], A["cy"])))
            edges.append(e)
        elif a[0] == "in" and b[0] == "unit":
            B = ids[b[1]]
            if row_has_left(B["c"], B["r"]):
                e.update(kind="FEED_LANE", lane=B["r"], gap=B["c"], p1=port(b[1], "left", (B["cx"] - 99, B["cy"] - 30)))
            else:
                e.update(kind="FEED", p1=port(b[1], "left", (B["cx"] - 99, B["cy"])))
            edges.append(e)
        elif a[0] == "unit" and b[0] == "out":
            A = ids[a[1]]
            if row_has_right(A["c"], A["r"]):
                if A["r"] == 0 and nrow > 1:
                    e.update(kind="EXIT_LANE", lane=0, p0=port(a[1], "top", (A["cx"] + 99, A["cy"] - 99)))
                else:
                    e.update(kind="EXIT_LANE", lane=A["r"] + 1, p0=port(a[1], "bottom", (A["cx"] + 99, A["cy"] + 99)))
            else:
                e.update(kind="EXIT", p0=port(a[1], "right", (A["cx"] + 99, A["cy"])))
            edges.append(e)
        elif a[0] == "none" and b[0] == "unit" and sid in mixers:
            B = ids[b[1]]
            mixers[sid]["p1"] = port(b[1], "left", (B["cx"] - 99, B["cy"]))
            e.update(kind="MIX_OUT", mixer=sid, p1=mixers[sid]["p1"])
            edges.append(e)
        elif a[0] == "in" and b[0] == "none" and mixer_list:
            m = mixer_list[0]
            e.update(kind="FEED_MIX", mixer=m["stream"].get("id"), lane=ids[m["unit"]]["r"])
            edges.append(e)
        elif a[0] == "unit" and b[0] == "none" and mixer_list:
            m = mixer_list[0]
            A = ids[a[1]]
            e.update(kind="UNIT_MIX", mixer=m["stream"].get("id"), p0=port(a[1], "right", (A["cx"] + 99, A["cy"])))
            edges.append(e)
    # units with no outgoing stream feed the nearest mixer (their outlet is the mixer inlet)
    for k, v in ids.items():
        if outgoing[k] or not mixer_list or not incoming[k]:
            continue
        best = min(mixer_list, key=lambda m: abs(ids[m["unit"]]["c"] - v["c"]) + abs(ids[m["unit"]]["r"] - v["r"]))
        if ids[best["unit"]]["c"] == v["c"] + 1 and ids[best["unit"]]["r"] == v["r"]:
            edges.append({"s": None, "id": None, "recycle": False, "product": False, "kind": "UNIT_MIX",
                          "mixer": best["stream"].get("id"),
                          "p0": port(k, "right", (ids[best["unit"]]["cx"], ids[best["unit"]]["cy"]))})

    # assign port positions along each side, ordered by the far end
    for (unit, side), lst in ports.items():
        v = ids[unit]
        n = len(lst)
        if side in ("left", "right"):
            lst.sort(key=lambda e_: e_["other"][1])
            span = box_h
            for i, ent in enumerate(lst):
                off = (i + 1) / (n + 1) * span if n > 1 else span / 2
                if n > 1:
                    off = box_h / 2 + (i - (n - 1) / 2) * min(4.6, (box_h - 3) / max(1, n - 1))
                x = v["x"] if side == "left" else v["x"] + box_w
                ent["pos"] = (x, v["y"] + off)
        else:
            lst.sort(key=lambda e_: e_["other"][0])
            for i, ent in enumerate(lst):
                off = box_w / 2 + (i - (n - 1) / 2) * min(7.0, (box_w - 6) / max(1, n - 1))
                y = v["y"] if side == "top" else v["y"] + box_h
                ent["pos"] = (v["x"] + off, y)
    # mixer positions: in the gap just left of the unit, level with its inlet port
    for sid, m in mixers.items():
        B = ids[m["unit"]]
        p = m.get("p1", {}).get("pos") or (B["x"], B["cy"])
        m["pos"] = (B["x"] - (pitch_x - box_w) / 2, p[1])

    # ---- track assignment in gaps (vertical) and lanes (horizontal) -------------------------
    gap_uses = {}
    lane_uses = {}

    def use_gap(gi, lo, hi, e, key):
        gap_uses.setdefault(gi, []).append((min(lo, hi), max(lo, hi), e, key))

    def use_lane(li, lo, hi, e, key):
        lane_uses.setdefault(li, []).append((min(lo, hi), max(lo, hi), e, key))

    for e in edges:
        k = e["kind"]
        if k == "HVH":
            p0, p1 = e["p0"]["pos"], e["p1"]["pos"]
            if abs(p0[1] - p1[1]) > 0.05:
                use_gap(e["gap"], p0[1], p1[1], e, "gx")
        elif k == "VHV":
            p0, p1 = e["p0"]["pos"], e["p1"]["pos"]
            if abs(p0[0] - p1[0]) > 0.05 or e["p0"] is not None and \
                    (e["s"] and ids.get(e["s"].get("from"), {}).get("r") == ids.get(e["s"].get("to"), {}).get("r")):
                use_lane(e["lane"], p0[0], p1[0], e, "ly")
        elif k == "HVHVH":
            p0, p1 = e["p0"]["pos"], e["p1"]["pos"]
            ly = lane_y(e["lane"])
            use_gap(e["gap"], p0[1], ly, e, "gx")
            use_gap(e["gap2"], ly, p1[1], e, "gx2")
            use_lane(e["lane"], gap_x(e["gap"]), gap_x(e["gap2"]), e, "ly")
        elif k == "FEED_LANE":
            p1 = e["p1"]["pos"]
            ly = lane_y(e["lane"])
            use_lane(e["lane"], left_x, gap_x(e["gap"]), e, "ly")
            use_gap(e["gap"], ly, p1[1], e, "gx")
        elif k == "EXIT_LANE":
            p0 = e["p0"]["pos"]
            use_lane(e["lane"], p0[0], right_x, e, "ly")
        elif k == "FEED_MIX":
            m = mixers[e["mixer"]]
            use_lane(e["lane"], left_x, m["pos"][0], e, "ly")

    track_sp = 3.0

    def assign(uses, center_fn, store, track_sp):
        for ch, lst in uses.items():
            lst.sort(key=lambda t: (t[0], t[1]))
            tracks = []  # end coordinate per track
            assign_ = []
            for lo, hi, e, key in lst:
                for ti, end in enumerate(tracks):
                    if lo > end + 2.0:
                        tracks[ti] = hi
                        assign_.append((ti, e, key))
                        break
                else:
                    tracks.append(hi)
                    assign_.append((len(tracks) - 1, e, key))
            n = len(tracks)
            for ti, e, key in assign_:
                e[key] = center_fn(ch) + (ti - (n - 1) / 2) * track_sp
            store[ch] = n

    assign(gap_uses, gap_x, {}, 3.0)
    assign(lane_uses, lane_y, {}, 4.2)
    # exits sharing a lane: the one leaving furthest right takes the highest track, so the
    # verticals never cross the other exits; feeds: the one reaching furthest right goes highest
    for li, lst in lane_uses.items():
        for kind, keyf in (("EXIT_LANE", lambda t: -t[0]), ("FEED_LANE", lambda t: -t[1])):
            sel = [t for t in lst if t[2]["kind"] == kind]
            if len(sel) > 1:
                up = kind == "EXIT_LANE" and sel[0][2]["p0"]["pos"][1] > lane_y(li)
                ys = sorted((t[2]["ly"] for t in sel), reverse=up)
                for yv_, t in zip(ys, sorted(sel, key=keyf)):
                    t[2]["ly"] = yv_

    # ---- geometry --------------------------------------------------------------------------
    for e in edges:
        k = e["kind"]
        if k == "HVH":
            p0, p1 = e["p0"]["pos"], e["p1"]["pos"]
            gx = e.get("gx", gap_x(e["gap"]))
            pts = [p0, p1] if abs(p0[1] - p1[1]) <= 0.05 else [p0, (gx, p0[1]), (gx, p1[1]), p1]
        elif k == "VHV":
            p0, p1 = e["p0"]["pos"], e["p1"]["pos"]
            ly = e.get("ly")
            if ly is None:
                pts = [p0, p1] if abs(p0[0] - p1[0]) <= 0.05 else [p0, (p0[0], lane_y(e["lane"])),
                                                                   (p1[0], lane_y(e["lane"])), p1]
            else:
                pts = [p0, (p0[0], ly), (p1[0], ly), p1]
        elif k == "HVHVH":
            p0, p1 = e["p0"]["pos"], e["p1"]["pos"]
            pts = [p0, (e["gx"], p0[1]), (e["gx"], e["ly"]), (e["gx2"], e["ly"]), (e["gx2"], p1[1]), p1]
        elif k == "FEED":
            p1 = e["p1"]["pos"]
            pts = [(left_x, p1[1]), p1]
        elif k == "FEED_LANE":
            p1 = e["p1"]["pos"]
            pts = [(left_x, e["ly"]), (e["gx"], e["ly"]), (e["gx"], p1[1]), p1]
        elif k == "EXIT":
            p0 = e["p0"]["pos"]
            pts = [p0, (right_x, p0[1])]
        elif k == "EXIT_LANE":
            p0 = e["p0"]["pos"]
            pts = [p0, (p0[0], e["ly"]), (right_x, e["ly"])]
        elif k == "MIX_OUT":
            m = mixers[e["mixer"]]
            pts = [(m["pos"][0] + 1.3, m["pos"][1]), e["p1"]["pos"]]
        elif k == "FEED_MIX":
            m = mixers[e["mixer"]]
            ly = e.get("ly", lane_y(e["lane"]))
            mx, my = m["pos"]
            pts = [(left_x, ly), (mx, ly), (mx, my - 1.3)] if ly < my else [(left_x, ly), (mx, ly), (mx, my + 1.3)]
        elif k == "UNIT_MIX":
            m = mixers[e["mixer"]]
            p0 = e["p0"]["pos"]
            mx, my = m["pos"]
            pts = [p0, (mx - 1.3, my)] if abs(p0[1] - my) < 0.05 else [p0, (mx, p0[1]), (mx, my + (1.3 if p0[1] > my else -1.3))]
        else:
            continue
        e["pts"] = pts

    # ---- draw ------------------------------------------------------------------------------
    def arrow(p, q, color, size=1.5):
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dy) or 1
        ux, uy = dx / L, dy / L
        bx, by = q[0] - ux * size * 1.5, q[1] - uy * size * 1.5
        pts = [q, (bx - uy * size * 0.62, by + ux * size * 0.62), (bx + uy * size * 0.62, by - ux * size * 0.62)]
        pdf.fill(color)
        pdf.set_draw_color(*color)
        pdf.polygon(pts, style="F")

    REC = (102, 112, 133)
    order = sorted([e for e in edges if "pts" in e], key=lambda e: (e["product"], not e["recycle"]))
    for e in order:
        col = ACCENT if e["product"] else (REC if e["recycle"] else INK2)
        lw = 0.42 if e["product"] else 0.28
        pts = e["pts"]
        pdf.stroke(col, lw)
        if e["recycle"]:
            pdf.set_dash_pattern(dash=1.2, gap=0.8)
        end = pts[-1]
        prev = pts[-2]
        L = math.hypot(end[0] - prev[0], end[1] - prev[1]) or 1
        cut = (end[0] - (end[0] - prev[0]) / L * 1.6, end[1] - (end[1] - prev[1]) / L * 1.6)
        poly = pts[:-1] + [cut]
        for p, q in zip(poly, poly[1:]):
            pdf.line(p[0], p[1], q[0], q[1])
        pdf.set_dash_pattern()
        if e["kind"] != "UNIT_MIX" or True:
            arrow(prev, end, col, 1.25 if not e["product"] else 1.45)

    # mixers
    for sid, m in mixers.items():
        mx, my = m["pos"]
        pdf.stroke(INK2, 0.28)
        pdf.fill(WHITE)
        pdf.ellipse(mx - 1.3, my - 1.3, 2.6, 2.6, style="FD")

    # unit boxes: tag on top, name below; one font size for every box, small enough that no
    # word is split and each name fits in three lines (four on very busy diagrams)
    def _names_fit(size, max_lines, pad):
        pdf.font("s", size, INK)
        if 6.0 + max_lines * (size / 72 * 25.4 * 1.22) > box_h - 0.8:
            return False
        return all(all(pdf.sw(wd) <= box_w - 2 * pad for wd in clean(v["u"].get("name") or "").split(" ")) and
                   len(pdf.wrap(v["u"].get("name") or "", box_w - 2 * pad)) <= max_lines for v in ids.values())

    name_size, max_name_lines, name_pad = 4.6, 4, 1.6
    found = False
    for pad_try, max_lines_try in ((2.4, 3), (2.4, 4), (1.6, 4)):
        s_try = 6.3
        while s_try >= 4.6 - 1e-9:
            if _names_fit(s_try, max_lines_try, pad_try):
                name_size, max_name_lines, name_pad, found = s_try, max_lines_try, pad_try, True
                break
            s_try = round(s_try - 0.3, 2)
        if found:
            break
    for k, v in ids.items():
        u = v["u"]
        pdf.rrect(v["x"], v["y"], box_w, box_h, fill=WHITE, border=LINE, r=RADIUS, lw=0.3)
        pdf.font("s", 6.4, ACCENT)
        pdf.put(v["x"] + name_pad, v["y"] + 2.0, u.get("id") or "")
        name = u.get("name") or ""
        size = name_size
        pdf.font("s", size, INK)
        lines = pdf.wrap(name, box_w - 2 * name_pad)
        if len(lines) > max_name_lines:
            lines = lines[:max_name_lines]
            lines[-1] = lines[-1].rstrip(" ,.") + "\u2026"
        lh = size / 72 * 25.4 * 1.22
        for i, ln in enumerate(lines):
            pdf.put(v["x"] + name_pad, v["y"] + 6.0 + i * lh, ln)

    # stream id pills: on the line where there is room, otherwise just beside it; never on a
    # box, an arrow head, another pill or (where avoidable) another stream
    hard = [(v["x"] - 0.8, v["y"] - 0.8, v["x"] + box_w + 0.8, v["y"] + box_h + 0.8) for v in ids.values()]
    for m in mixers.values():
        hard.append((m["pos"][0] - 1.8, m["pos"][1] - 1.8, m["pos"][0] + 1.8, m["pos"][1] + 1.8))
    seg_rects = []
    for e in edges:
        if "pts" not in e:
            continue
        q, pq = e["pts"][-1], e["pts"][-2]
        hard.append((min(q[0], pq[0] if abs(q[0] - pq[0]) < 3.2 else q[0] - math.copysign(3.2, q[0] - pq[0])) - 1.2,
                     min(q[1], pq[1] if abs(q[1] - pq[1]) < 3.2 else q[1] - math.copysign(3.2, q[1] - pq[1])) - 1.2,
                     max(q[0], pq[0] if abs(q[0] - pq[0]) < 3.2 else q[0] - math.copysign(3.2, q[0] - pq[0])) + 1.2,
                     max(q[1], pq[1] if abs(q[1] - pq[1]) < 3.2 else q[1] - math.copysign(3.2, q[1] - pq[1])) + 1.2))
        for a_, b_ in zip(e["pts"], e["pts"][1:]):
            seg_rects.append((id(e), (min(a_[0], b_[0]) - 0.25, min(a_[1], b_[1]) - 0.25,
                                      max(a_[0], b_[0]) + 0.25, max(a_[1], b_[1]) + 0.25)))
    pills = []

    def overlap(r, b):
        return r[0] < b[2] and r[2] > b[0] and r[1] < b[3] and r[3] > b[1]

    def score(r, eid):
        if r[0] < MARGIN or r[2] > W - MARGIN:
            return None
        if any(overlap(r, b) for b in hard + pills):
            return None
        return sum(1 for k_, b in seg_rects if k_ != eid and overlap(r, b))

    boundary_kinds = ("FEED", "FEED_LANE", "FEED_MIX", "EXIT", "EXIT_LANE")
    for e in sorted([e for e in edges if "pts" in e and e["id"] and e["kind"] not in boundary_kinds],
                    key=lambda e: -len(e["pts"])):
        label = clean(e["id"])
        pdf.font("s", 5.6, INK2)
        tw = pdf.get_string_width(label) + 2.4
        th = 3.2
        segs = []
        for a_, b_ in zip(e["pts"], e["pts"][1:]):
            segs.append((math.hypot(b_[0] - a_[0], b_[1] - a_[1]), a_, b_))
        segs.sort(key=lambda t: -t[0])
        best = None
        if e["kind"] == "MIX_OUT":
            mx, my = mixers[e["mixer"]]["pos"]
            for dy in (th / 2 + 2.6, -(th / 2 + 2.6)):
                r = (mx - tw / 2, my + dy - th / 2, mx + tw / 2, my + dy + th / 2)
                s_ = score(r, id(e))
                if s_ is not None and (best is None or s_ * 5 + 3 < best[0]):
                    best = (s_ * 5 + 3, r)
        for L, a_, b_ in segs:
            horiz = abs(a_[1] - b_[1]) < 0.01
            for f in (0.5, 0.38, 0.62, 0.26, 0.74, 0.15, 0.85, 0.0, 1.0):
                cx = a_[0] + (b_[0] - a_[0]) * f
                cy = a_[1] + (b_[1] - a_[1]) * f
                offs = [(0, 0, 0)]
                if horiz:
                    offs += [(0, -(th / 2 + 1.5), 2), (0, th / 2 + 1.5, 2)]
                else:
                    offs += [(-(tw / 2 + 1.5), 0, 2), (tw / 2 + 1.5, 0, 2)]
                if f in (0.15, 0.85, 0.0, 1.0):
                    # beside the ends, clear of boxes and mixing points
                    offs += [(0, -(th / 2 + 2.6), 4), (0, th / 2 + 2.6, 4)] if horiz else \
                            [(-(tw / 2 + 2.6), 0, 4), (tw / 2 + 2.6, 0, 4)]
                for dx, dy, pen in offs:
                    r = (cx + dx - tw / 2, cy + dy - th / 2, cx + dx + tw / 2, cy + dy + th / 2)
                    s_ = score(r, id(e))
                    if s_ is None:
                        continue
                    tot = s_ * 5 + pen + (0 if L > tw + 7 else 1)
                    if best is None or tot < best[0]:
                        best = (tot, r)
            if best is not None and best[0] == 0:
                break
        if best is None:
            continue
        spot = best[1]
        pills.append((spot[0] - 0.5, spot[1] - 0.5, spot[2] + 0.5, spot[3] + 0.5))
        colr = ACCENT if e["product"] else (REC if e["recycle"] else INK2)
        pdf.rrect(spot[0], spot[1], tw, th, fill=WHITE, border=colr, r=1.6, lw=0.22)
        pdf.font("s", 5.6, colr)
        pdf.put(spot[0], spot[1] + 0.62, label, align="C", w=tw)

    # boundary labels: name plus stream id pill, next to where the stream enters or leaves
    def side_labels(items, x_edge, side):
        items.sort(key=lambda t: t[0])
        blocks = []
        for y, text, e in items:
            pdf.font("s", 5.6)
            pw = pdf.sw(e["id"] or "") + 2.4 if e["id"] else 0
            avail = label_w - pw - 3.0
            size = 6.6
            while True:
                pdf.font("s" if e["product"] else "r", size)
                lines = pdf.wrap(text, avail)
                if len(lines) == 1 or size <= 5.8:
                    break
                size -= 0.2
            lines = lines[:2]
            lh = size / 72 * 25.4 * 1.2
            blocks.append({"y": y, "lines": lines, "h": max(len(lines) * lh, 3.4), "lh": lh, "size": size, "e": e, "pw": pw})
        # spread blocks that would collide, keeping each as close to its stream as possible
        for _ in range(30):
            moved = False
            for a_, b_ in zip(blocks, blocks[1:]):
                top_a = a_["y"] - a_["h"] / 2
                need = (a_["h"] + b_["h"]) / 2 + 0.8
                if b_["y"] - a_["y"] < need:
                    push = (need - (b_["y"] - a_["y"])) / 2
                    a_["y"] -= push
                    b_["y"] += push
                    moved = True
            if not moved:
                break
        for b_ in blocks:
            e = b_["e"]
            colr = ACCENT if e["product"] else (REC if e["recycle"] else INK2)
            ly_ = e["pts"][0][1] if side == "L" else e["pts"][-1][1]
            if b_["pw"]:
                px = x_edge - 1.0 - b_["pw"] if side == "L" else x_edge + 1.4
                pdf.rrect(px, ly_ - 1.6, b_["pw"], 3.2, fill=WHITE, border=colr, r=1.6, lw=0.22)
                pdf.font("s", 5.6, colr)
                pdf.put(px, ly_ - 1.6 + 0.62, e["id"], align="C", w=b_["pw"])
            tx = (x_edge - 2.2 - b_["pw"]) if side == "L" else (x_edge + 2.6 + b_["pw"])
            pdf.font("s" if e["product"] else "r", b_["size"], ACCENT if e["product"] else INK2)
            ty = b_["y"] - (len(b_["lines"]) - 1) * b_["lh"] / 2 - pdf.font_size * 0.42
            for i, ln in enumerate(b_["lines"]):
                pdf.put(tx, ty + i * b_["lh"], ln, align="R" if side == "L" else "L")

    lefts, rights = [], []
    for e in edges:
        if "pts" not in e or e["s"] is None:
            continue
        if e["kind"] in ("FEED", "FEED_LANE", "FEED_MIX"):
            lefts.append((e["pts"][0][1], e["s"].get("name") or e["id"] or "", e))
        elif e["kind"] in ("EXIT", "EXIT_LANE"):
            rights.append((e["pts"][-1][1], e["s"].get("name") or e["id"] or "", e))
    side_labels(lefts, left_x, "L")
    side_labels(rights, right_x, "R")

    # legend
    ly = pdf.bottom - 3.5
    lx = MARGIN
    items = [("Process stream", INK2, False, 0.28), ("Main product", ACCENT, False, 0.42),
             ("Recycle", REC, True, 0.28)]
    for text, colr, dash, lw in items:
        pdf.stroke(colr, lw)
        if dash:
            pdf.set_dash_pattern(dash=1.2, gap=0.8)
        pdf.line(lx, ly + 1.4, lx + 7, ly + 1.4)
        pdf.set_dash_pattern()
        arrow((lx, ly + 1.4), (lx + 8.2, ly + 1.4), colr, 1.2)
        pdf.font("r", 6.8, MUTED)
        pdf.put(lx + 10, ly, text)
        lx += 12 + pdf.sw(text) + 6
    if mixers:
        pdf.stroke(INK2, 0.28)
        pdf.fill(WHITE)
        pdf.ellipse(lx + 1, ly + 0.1, 2.6, 2.6, style="FD")
        pdf.font("r", 6.8, MUTED)
        pdf.put(lx + 5, ly, "Mixing point")
        lx += 5 + pdf.sw("Mixing point") + 6
    pdf.rrect(lx, ly - 0.2, 6, 3.2, fill=WHITE, border=INK2, r=1.6, lw=0.22)
    pdf.font("s", 5.6, INK2)
    pdf.put(lx, ly + 0.45, "S1", align="C", w=6)
    pdf.font("r", 6.8, MUTED)
    pdf.put(lx + 8, ly, "Stream id")
    if hidden:
        pdf.font("r", 6.8, MUTED)
        pdf.put(pdf.w - MARGIN, ly, "Internal mixed streams not drawn: " + ", ".join(sorted(clean(h) for h in hidden if h)),
                align="R")


# ---- reactions, conditions, units ----------------------------------------------------------------
def _split_eq(eq):
    eq = clean(eq)
    for tok, kind in (("<=>", "eq"), ("<->", "eq"), ("\u2192", "fw"), ("->", "fw"), ("=>", "fw"), (" = ", "eq")):
        if tok in eq:
            lhs, rhs = eq.split(tok, 1)
            return lhs.strip(), rhs.strip(), kind
    return eq, None, None


def draw_equation(pdf, x, y, eq, size, maxw):
    lhs, rhs, kind = _split_eq(eq)
    pdf.font("s", size, INK)
    aw = 7.0
    tot = pdf.chem_width(lhs, size) + (aw + 3.0 + pdf.chem_width(rhs, size) if rhs is not None else 0)
    while tot > maxw and size > 6:
        size -= 0.4
        pdf.font("s", size, INK)
        tot = pdf.chem_width(lhs, size) + (aw + 3.0 + pdf.chem_width(rhs, size) if rhs is not None else 0)
    x2 = pdf.chem(x, y, lhs, size)
    if rhs is None:
        return
    mid = y + size / 72 * 25.4 * 0.5
    ax0, ax1 = x2 + 1.5, x2 + 1.5 + aw
    pdf.stroke(INK2, 0.25)
    if kind == "eq":
        pdf.line(ax0, mid - 0.45, ax1, mid - 0.45)
        pdf.line(ax1, mid - 0.45, ax1 - 1.3, mid - 1.35)
        pdf.line(ax0, mid + 0.45, ax1, mid + 0.45)
        pdf.line(ax0, mid + 0.45, ax0 + 1.3, mid + 1.35)
    else:
        pdf.line(ax0, mid, ax1, mid)
        pdf.line(ax1, mid, ax1 - 1.2, mid - 0.9)
        pdf.line(ax1, mid, ax1 - 1.2, mid + 0.9)
    pdf.font("s", size, INK)
    pdf.chem(ax1 + 1.5, y, rhs, size)


def reactions_page(pdf, d):
    y = pdf.section("Reactions and operating conditions")
    rx = d.get("reactions") or []
    if rx:
        y = pdf.subhead(y, "Reactions", right="Heat of reaction per mole of reaction as written")
        x0, w = MARGIN, pdf.cw
        cw_eq, cw_wh, cw_h = w * 0.42, w * 0.38, w * 0.20
        pdf.rrect(x0, y, w, 6.4, fill=PANEL)
        pdf.font("s", 6.8, MUTED)
        pdf.put(x0 + 1.8, y + 2.05, "Reaction")
        pdf.put(x0 + cw_eq + 1.8, y + 2.05, "Where")
        pdf.put(x0 + cw_eq + cw_wh, y + 2.05, "Heat of reaction, kJ/mol", align="R", w=cw_h - 1.8)
        y += 6.4
        for r in rx:
            pdf.font("r", 7.6, INK2)
            lines = pdf.wrap(r.get("where") or "", cw_wh - 3.6)
            rh = max(10.0, len(lines) * 3.4 + 4.4)
            y = pdf.ensure(y, rh)
            draw_equation(pdf, x0 + 1.8, y + (rh - 3.0) / 2 - 0.4, r.get("eq") or "", 8.6, cw_eq - 4)
            pdf.font("r", 7.6, INK2)
            for i, ln in enumerate(lines):
                pdf.put(x0 + cw_eq + 1.8, y + (rh - len(lines) * 3.4) / 2 + i * 3.4 + 0.2, ln)
            dh = _num(r.get("dH_kJ"))
            pdf.font("s", 8.2, INK if dh is not None else FAINT)
            if dh is not None and dh != 0:
                pdf.tnum(x0 + w - 1.8, y + (rh - 3.0) / 2 - 1.5, ffix(dh, 1))
                pdf.font("r", 6.3, RED if dh > 0 else MUTED)
                pdf.put(x0 + w - 1.8, y + (rh - 3.0) / 2 + 2.0, "endothermic" if dh > 0 else "exothermic", align="R")
            else:
                pdf.tnum(x0 + w - 1.8, y + (rh - 3.0) / 2, ffix(dh, 1) if dh is not None else "-")
            y += rh
            pdf.hline(x0, x0 + w, y)
        y += 7
    conds = [c for c in (d.get("conditions") or []) if isinstance(c, (list, tuple)) and len(c) >= 2]
    if conds:
        y = pdf.ensure(y, 20)
        y = pdf.subhead(y, "Operating conditions")
        pdf.hline(MARGIN, MARGIN + pdf.cw, y - 1.6)
        y -= 1.6
        for lab, val in [(c[0], c[1]) for c in conds]:
            pdf.font("r", 8.2, INK2)
            lw = pdf.cw * 0.42
            vl = pdf.wrap(val if val is not None else "-", pdf.cw - lw - 3.6)
            rh = max(6.6, len(vl) * 3.6 + 3.2)
            y = pdf.ensure(y, rh)
            pdf.para(MARGIN + 1.8, y + 1.7, lw - 3.6, lab or "", lh=3.6, max_lines=2)
            pdf.font("s", 8.2, INK)
            for i, ln in enumerate(vl):
                pdf.put(MARGIN + lw + 1.8, y + 1.7 + i * 3.6, ln)
            y += rh
            pdf.hline(MARGIN, MARGIN + pdf.cw, y)
        y += 7
    units = d.get("units") or []
    if units:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "Process units")
        cols = [{"title": "Tag", "w": 11}, {"title": "Unit", "w": 50}, {"title": "Duty, kW", "w": 15, "align": "R", "kind": "num"},
                {"title": "Power, kW", "w": 15, "align": "R", "kind": "num"}]
        rows = []
        for u in units:
            rows.append([{"t": u.get("id") or "", "style": "s", "color": ACCENT},
                         {"t": u.get("name") or "", "sub": u.get("desc")},
                         fnum(u.get("duty_kW"), 3), fnum(u.get("power_kW"), 3)])
        y = pdf.table(y, cols, rows, repeat_title="Process units")


# ---- stream table -------------------------------------------------------------------------------
def stream_table(pdf, d):
    streams = [s for s in (d.get("streams") or []) if isinstance(s, dict)]
    if not streams:
        return
    y0 = pdf.section("Stream table", "Mass flows in kg/h unless stated. A dash means the component is absent.",
                     orientation="L")
    unit_names = {u.get("id"): u.get("name") for u in (d.get("units") or [])}
    label_w = 40.0
    col_w = 17.6
    per_page = max(1, int((pdf.cw - label_w) // col_w))
    npg = max(1, -(-len(streams) // per_page))
    even = -(-len(streams) // npg)
    pages = [streams[i:i + even] for i in range(0, len(streams), even)]
    # global component order: by total mass across all streams
    tot = {}
    for s in streams:
        for c, v in (s.get("components") or {}).items():
            tot[c] = tot.get(c, 0.0) + (_num((v or {}).get("kg_h")) or 0.0)
    order = sorted(tot, key=lambda c: -tot[c])

    def end_name(v):
        if v == "IN":
            return "Feed"
        if v == "OUT":
            return "Exit"
        if v in (None, "mix"):
            return "Mix"
        return clean(v)

    for pi, group in enumerate(pages):
        if pi:
            y0 = pdf.continue_page()
        x0 = MARGIN
        cw = (pdf.cw - label_w) / len(group) if len(group) >= per_page - 1 else col_w
        cw = min(cw, 22.0)
        width = label_w + cw * len(group)
        y = y0
        # header: stream id and name
        pdf.rrect(x0, y, width, 15.5, fill=PANEL)
        pdf.font("s", 6.8, MUTED)
        pdf.put(x0 + 1.8, y + 2.0, "Stream")
        for i, s in enumerate(group):
            cx = x0 + label_w + i * cw
            pdf.font("b", 7.4, ACCENT)
            pdf.put(cx, y + 1.9, s.get("id") or "", align="R", w=cw - 1.8)
            pdf.font("r", 5.8, INK2)
            lines = pdf.wrap(s.get("name") or "", cw - 2.6)
            if len(lines) > 3:
                lines = lines[:3]
                lines[2] = lines[2].rstrip(" ,.") + "\u2026"
            for li, ln in enumerate(lines):
                pdf.put(cx, y + 5.4 + li * 2.5, ln, align="R", w=cw - 1.8)
        y += 15.5
        comps = [c for c in order if any(c in (s.get("components") or {}) for s in group)]

        rows = [("From", [end_name(s.get("from")) for s in group], "t"),
                ("To", [end_name(s.get("to")) for s in group], "t"),
                ("Temperature, \u00b0C", [fnum(s.get("T_C"), 3) for s in group], "n"),
                ("Pressure, bar", [fnum(s.get("P_bar"), 3) for s in group], "n"),
                ("Phase", [{"g": "Gas", "l": "Liquid", "s": "Solid", "vl": "Two phase", "lv": "Two phase"}.get(
                    (s.get("phase") or "").lower(), clean(s.get("phase") or "-")) for s in group], "t"),
                ("Total, kg/h", [fflow(s.get("kg_h")) for s in group], "nb"),
                ("Total, kmol/h", [fflow(s.get("kmol_h")) for s in group], "n")]
        rh = 5.0
        for ri, (lab, vals, kind) in enumerate(rows):
            if ri == 5:
                pdf.rrect(x0, y, width, rh * 2, fill=ACCENT_SOFT, r=0)
            pdf.font("r", 7.0, INK2)
            pdf.put(x0 + 1.8, y + 1.25, lab)
            for i, v in enumerate(vals):
                cx = x0 + label_w + (i + 1) * cw - 1.8
                if kind == "t":
                    pdf.font("r", 6.6, INK2)
                    pdf.put(cx, y + 1.35, v, align="R")
                else:
                    pdf.font("s" if kind == "nb" else "r", 7.0, INK)
                    pdf.tnum(cx, y + 1.25, v)
            y += rh
            pdf.hline(x0, x0 + width, y)
        y += 1.5
        pdf.font("s", 6.8, MUTED)
        pdf.put(x0 + 1.8, y + 1.2, "Component flows, kg/h")
        y += 5.2
        pdf.hline(x0, x0 + width, y)
        for c in comps:
            if y + rh > pdf.bottom:
                y = pdf.continue_page()
            pdf.font("s", 7.0, INK)
            pdf.chem(x0 + 1.8, y + 1.25, c, 7.0)
            for i, s in enumerate(group):
                v = (s.get("components") or {}).get(c)
                cx = x0 + label_w + (i + 1) * cw - 1.8
                if v is None:
                    pdf.font("r", 7.0, FAINT)
                    pdf.put(cx, y + 1.25, "-", align="R")
                else:
                    pdf.font("r", 7.0, INK)
                    pdf.tnum(cx, y + 1.25, fflow(v.get("kg_h")))
            y += rh
            pdf.hline(x0, x0 + width, y)
        # light vertical separators between stream columns
        pdf.stroke(HAIR, 0.15)
        for i in range(1, len(group)):
            cx = x0 + label_w + i * cw
            pdf.line(cx, y0 + 15.5, cx, y)


# ---- mass and energy balance --------------------------------------------------------------------
def balance_page(pdf, d):
    y = pdf.section("Mass and energy balance")
    b = d.get("balance") or {}
    en = d.get("energy") or {}
    x0, cw = MARGIN, pdf.cw
    gap = 4.0
    cards = [("Mass in, kg/h", fflow(b.get("mass_in_kg_h"))),
             ("Mass out, kg/h", fflow(b.get("mass_out_kg_h"))),
             ("Closure, out minus in", ffix(b.get("closure_pct"), 3) + "%" if b.get("closure_pct") is not None else "-"),
             ("Electric power, kW", fnum(en.get("power_kW"), 4))]
    w4 = (cw - 3 * gap) / 4
    for i, (lab, val) in enumerate(cards):
        pdf.stat_card(x0 + i * (w4 + gap), y, w4, 19, lab, val)
    y += 19 + 8

    # atom balance and boundary streams side by side
    ae = b.get("atom_error_pct") or {}
    lw = cw * 0.34
    rx = x0 + lw + 8
    rw = cw - lw - 8
    ytop = y
    if ae:
        yl = pdf.subhead(y, "Atom balance error")
        cols = [{"title": "Element", "w": 1}, {"title": "Error, %", "w": 1, "align": "R", "kind": "num"}]
        rows = [[k, ffix(v, 4)] for k, v in ae.items()]
        yl = pdf.table(yl, cols, rows, x=x0, w=lw)
    else:
        yl = y
    streams = {s.get("id"): s for s in (d.get("streams") or [])}
    bi, bo = b.get("boundary_in") or [], b.get("boundary_out") or []
    yr = ytop
    if bi or bo:
        pdf.font("s", 10, INK)
        pdf.put(rx, yr, "Plant boundary")
        yr += 6.6
        cols = [{"title": "Stream", "w": 9}, {"title": "Name", "w": 34}, {"title": "Direction", "w": 12},
                {"title": "kg/h", "w": 13, "align": "R", "kind": "num"}]
        rows = []
        for sid in bi:
            s = streams.get(sid) or {}
            rows.append([{"t": sid, "style": "s", "color": ACCENT}, s.get("name") or "", "In", fflow(s.get("kg_h"))])
        for sid in bo:
            s = streams.get(sid) or {}
            rows.append([{"t": sid, "style": "s", "color": ACCENT}, s.get("name") or "", "Out", fflow(s.get("kg_h"))])
        yr = pdf.table(yr, cols, rows, x=rx, w=rw, size=7.4)
    y = max(yl, yr) + 5

    # feeds and products with prices
    mats = []
    for key, lab in (("raw_materials", "Raw material"), ("products", "Product"), ("byproducts", "By-product")):
        for m in d.get(key) or []:
            mats.append((lab, m))
    if mats:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "Materials and prices")
        cols = [{"title": "Material", "w": 14, "kind": "chem"}, {"title": "Role", "w": 12}, {"title": "kg/h", "w": 12, "align": "R", "kind": "num"},
                {"title": "Price, USD/t", "w": 12, "align": "R", "kind": "num"}, {"title": "Annual, USD M", "w": 13, "align": "R", "kind": "num"},
                {"title": "Price source", "w": 37}]
        rows = []
        for lab, m in mats:
            src = m.get("source") or {}
            st = ", ".join(clean(p) for p in [src.get("source"), src.get("basis"), str(src.get("year")) if src.get("year") else None] if p)
            rows.append([{"t": m.get("id") or "", "style": "s"}, lab, fflow(m.get("kg_h")), fnum(m.get("usd_t"), 4),
                         usd_m(m.get("annual_usd"), 1), {"t": st or "-", "link": src.get("url"), "color": ACCENT if src.get("url") else INK2}])
        y = pdf.table(y, cols, rows) + 4

    utils = d.get("utilities") or []
    if utils:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "Utilities", right="Annual cost at the stated operating hours")
        cols = [{"title": "Utility", "w": 34}, {"title": "Per hour", "w": 14, "align": "R", "kind": "num"}, {"title": "Unit", "w": 11},
                {"title": "Unit cost", "w": 12, "align": "R", "kind": "num"}, {"title": "Cost unit", "w": 13},
                {"title": "Annual, USD M", "w": 14, "align": "R", "kind": "num"}]
        rows = [[u.get("label") or "", fnum(u.get("per_h"), 4), u.get("unit") or "", fnum(u.get("unit_cost"), 3),
                 u.get("cost_unit") or "", usd_m(u.get("annual"), 2)] for u in utils]
        y = pdf.table(y, cols, rows, repeat_title="Utilities") + 4

    pi = en.get("power_items") or []
    si = en.get("steam_items") or []
    if pi:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "Power consumers")
        cols = [{"title": "Item", "w": 70}, {"title": "Power, kW", "w": 30, "align": "R", "kind": "num"}]
        rows = [[p.get("label") or "", fnum(p.get("kW"), 4)] for p in pi]
        if en.get("power_kW") is not None:
            rows.append([{"t": "Total electric power", "style": "s"}, {"t": fnum(en.get("power_kW"), 4), "style": "s"}])
        y = pdf.table(y, cols, rows, total_rows=(-1,) if en.get("power_kW") is not None else ()) + 4
    if si:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "Steam and fuel balance", right="Negative steam is raised, negative fuel is a credit")
        cols = [{"title": "Item", "w": 70}, {"title": "Steam, kg/h", "w": 15, "align": "R", "kind": "num"},
                {"title": "Fuel, GJ/h", "w": 15, "align": "R", "kind": "num"}]
        rows = [[s.get("label") or "", fflow(s.get("steam_kg_h")) if s.get("steam_kg_h") is not None else "",
                 fnum(s.get("fuel_GJ_h"), 4) if s.get("fuel_GJ_h") is not None else ""] for s in si]
        y = pdf.table(y, cols, rows, repeat_title="Steam and fuel balance") + 4
    summ = [("Fuel fired", fnum(en.get("fuel_GJ_h"), 4), "GJ/h"),
            ("Natural gas bought, net of off gas burnt", fnum(en.get("gas_net_GJ_h"), 4), "GJ/h"),
            ("Fuel credit from off gas", fnum(en.get("fuel_credit_GJ_h"), 4), "GJ/h"),
            ("Steam raised and used", fflow(en.get("steam_import_kg_h")), "kg/h"),
            ("Cooling duty", fflow(en.get("cooling_kW")), "kW"),
            ("Cooling water", fflow(en.get("cooling_water_m3_h")), "m3/h")]
    summ = [t for t, k in zip(summ, ["fuel_GJ_h", "gas_net_GJ_h", "fuel_credit_GJ_h", "steam_import_kg_h", "cooling_kW",
                                       "cooling_water_m3_h"]) if en.get(k) is not None]
    if summ:
        y = pdf.ensure(y, 12 + 6.4 * len(summ))
        y = pdf.subhead(y, "Energy summary")
        pdf.hline(MARGIN, MARGIN + pdf.cw, y - 1.6)
        y = pdf.kv_list(y - 1.6, summ) + 4
    ud = en.get("unit_duties") or []
    if ud:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "Unit duties", right="Positive duty is heat added")
        cols = [{"title": "Unit", "w": 70}, {"title": "Duty, kW", "w": 15, "align": "R", "kind": "num"},
                {"title": "Power, kW", "w": 15, "align": "R", "kind": "num"}]
        rows = [[u.get("unit") or "", fnum(u.get("duty_kW"), 4), fnum(u.get("power_kW"), 4)] for u in ud]
        y = pdf.table(y, cols, rows, repeat_title="Unit duties")


# ---- equipment -----------------------------------------------------------------------------------
def equipment_page(pdf, d):
    eq = d.get("equipment") or []
    if not eq:
        return
    capx = d.get("capex") or {}
    y = pdf.section("Equipment list",
                    "Sized for the design case. Costs in thousands of US dollars at CEPCI {} ({}).".format(
                        fnum(capx.get("cepci"), 4), clean(capx.get("cepci_year") or "-")))
    pdf.font("s", 7.2)
    tag_w = max([pdf.sw((q.get("tag") or "") + " *") for q in eq] + [8]) + 3.8
    cw_ = pdf.cw
    rest = cw_ - tag_w
    cols = [{"title": "Tag", "w": tag_w}, {"title": "Equipment", "w": rest * 0.29}, {"title": "Type", "w": rest * 0.175},
            {"title": "Size", "w": rest * 0.085, "align": "R", "kind": "num"}, {"title": "Unit", "w": rest * 0.07},
            {"title": "No.", "w": rest * 0.045, "align": "R", "kind": "num"}, {"title": "Material", "w": rest * 0.07},
            {"title": "P\nbarg", "w": rest * 0.06, "align": "R", "kind": "num"},
            {"title": "Purchased\nUSD k", "w": rest * 0.10, "align": "R", "kind": "num"},
            {"title": "Bare module\nUSD k", "w": rest * 0.10, "align": "R", "kind": "num"}]
    rows = []
    flagged = False
    for e in eq:
        name = e.get("name") or ""
        sub = e.get("service") or None
        note = e.get("note")
        if note:
            sub = (sub + ". " if sub else "") + note
        tag = clean(e.get("tag") or "")
        if e.get("in_range") is False:
            tag += " *"
            flagged = True
        rows.append([{"t": tag, "style": "s", "color": ACCENT}, {"t": name, "sub": sub},
                     {"t": e.get("label") or (e.get("kind") or "").replace("_", " "), "color": INK2},
                     fnum(e.get("size"), 3), {"t": e.get("unit") or "", "color": INK2},
                     fnum(e.get("units_parallel"), 3), {"t": e.get("material") or "-", "color": INK2},
                     fnum(e.get("P_barg"), 3), usd_k(e.get("purchased")), usd_k(e.get("bare_module"))])
    if capx.get("bare_module_total") is not None:
        rows.append(["", {"t": "Total bare module cost", "style": "s"}, "", "", "", "", "", "", "",
                     {"t": usd_k(capx.get("bare_module_total")), "style": "s"}])
    y = pdf.table(y, cols, rows, size=7.2, head_size=6.4,
                  total_rows=(-1,) if capx.get("bare_module_total") is not None else ())
    if flagged:
        y = pdf.ensure(y, 8)
        pdf.font("r", 7.2, MUTED)
        pdf.put(MARGIN, y + 1, "* Size outside the cost correlation range; cost extrapolated.")


# ---- capital cost --------------------------------------------------------------------------------
def capex_page(pdf, d):
    capx = d.get("capex") or {}
    e = d.get("economics") or {}
    if not capx:
        return
    y = pdf.section("Capital cost")
    x0, cw = MARGIN, pdf.cw
    bm = _num(capx.get("bare_module_total"))
    cf = _num(capx.get("contingency_and_fee"))
    aux = _num(capx.get("auxiliary_facilities"))
    fci = _num(capx.get("fixed_capital"))
    extra = capx.get("extra_items") or []
    parts = [("Bare module equipment", bm, ACCENT), ("Contingency and fee", cf, (110, 135, 248)),
             ("Auxiliary facilities", aux, (176, 190, 251))]
    extra_total = None
    if extra and fci is not None and None not in (bm, cf, aux):
        extra_total = fci - bm - cf - aux
        parts.append(("Items outside the correlations", extra_total, (120, 130, 150)))
    gap = 4
    w3 = (cw - 2 * gap) / 3
    pdf.stat_card(x0, y, w3, 19, "Fixed capital investment", money(fci), accent=True)
    pdf.stat_card(x0 + w3 + gap, y, w3, 19, "Working capital", money(e.get("working_capital")))
    pdf.stat_card(x0 + 2 * (w3 + gap), y, w3, 19, "Capital per annual tonne", per_t(e.get("capex_per_annual_tonne")))
    y += 19 + 8

    # stacked bar
    known = [(l, v, c) for l, v, c in parts if v is not None and v > 0]
    tot = sum(v for _, v, _ in known)
    if tot > 0:
        y = pdf.subhead(y, "Build up of fixed capital")
        bx = x0
        for l, v, c in known:
            bw = v / tot * cw
            pdf.rrect(bx, y, bw, 6.5, fill=c, r=0)
            bx += bw
        pdf.stroke(WHITE, 0.6)
        bx = x0
        for l, v, c in known[:-1]:
            bx += v / tot * cw
            pdf.line(bx, y, bx, y + 6.5)
        y += 10
        rows = []
        for l, v, c in parts:
            rows.append([{"t": l, "swatch": c if (v is not None and v > 0) else None}, usd_m(v, 1),
                         pct(v / fci * 100 if (v is not None and fci) else None, 1)])
        rows.append([{"t": "Fixed capital investment", "style": "s", "swatch": WHITE}, {"t": usd_m(fci, 1), "style": "s"},
                     {"t": "100.0%" if fci else "-", "style": "s"}])
        cols = [{"title": "Item", "w": 60}, {"title": "USD M", "w": 20, "align": "R", "kind": "num"},
                {"title": "Share", "w": 20, "align": "R", "kind": "num"}]
        # colour keys drawn in front of the first column
        ystart = y
        y = pdf.table(y, cols, rows, total_rows=(-1,))
        yy = ystart + 6.4
        for l, v, c in parts:
            pass
    if extra:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "Items outside the Turton correlations")
        cols = [{"title": "Item", "w": 50}, {"title": "Note", "w": 35}, {"title": "USD M", "w": 15, "align": "R", "kind": "num"}]
        rows = [[x.get("label") or "", {"t": x.get("note") or "", "color": INK2}, usd_m(x.get("usd"), 2)] for x in extra]
        y = pdf.table(y, cols, rows) + 2

    # biggest equipment items
    eq = sorted([q for q in (d.get("equipment") or []) if _num(q.get("bare_module"))],
                key=lambda q: -_num(q.get("bare_module")))[:8]
    if eq:
        y = pdf.ensure(y + 4, 12 + 7 * len(eq))
        y = pdf.subhead(y, "Largest equipment items", right="Bare module cost, USD M")
        top = _num(eq[0].get("bare_module"))
        labw = 62
        for q in eq:
            v = _num(q.get("bare_module"))
            pdf.font("s", 7.4, ACCENT)
            pdf.put(x0, y + 1.0, q.get("tag") or "")
            pdf.font("r", 7.4, INK2)
            pdf.para(x0 + 16, y + 1.0, labw - 18, q.get("name") or "", lh=3, max_lines=1)
            bw = (cw - labw - 18) * v / top
            pdf.rrect(x0 + labw, y + 0.6, max(bw, 0.6), 3.6, fill=ACCENT if q is eq[0] else ACCENT_MID, r=0.8)
            pdf.font("s", 7.4, INK)
            pdf.tnum(x0 + cw, y + 1.0, usd_m(v, 1))
            y += 6.6
        y += 4
    y = pdf.ensure(y, 30)
    y = pdf.subhead(y, "Basis")
    pdf.hline(x0, x0 + cw, y - 1.6)
    items = [("Cost method", clean(capx.get("method") or "-"), ""),
             ("Cost index basis", "CEPCI {} ({})".format(fnum(capx.get("cepci"), 4), clean(capx.get("cepci_year") or "-")), "")]
    y = pdf.kv_list(y - 1.6, items, label_w=60) + 4
    pdf.font("r", 8, MUTED)
    pdf.para(x0, y, cw, METHOD_TEXT, lh=3.9)


# ---- operating cost and economics ----------------------------------------------------------------
def nice_step(span, n=5):
    raw = span / max(n, 1)
    if raw <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def economics_page(pdf, d):
    e = d.get("economics") or {}
    if not e:
        return
    y = pdf.section("Operating cost and economics")
    x0, cw = MARGIN, pdf.cw
    gap = 4
    w3 = (cw - 2 * gap) / 3
    irr = _num(e.get("irr"))
    pb = _num(e.get("payback_years"))
    cards = [("Revenue", money(e.get("revenue")), "per year"),
             ("Cost of manufacture", money(e.get("com")), "per year"),
             ("Profit before tax", money(e.get("annual_profit_before_tax")), "per year"),
             ("Net present value", money(e.get("npv")), None),
             ("Internal rate of return", pct(irr, 1, frac=True) if irr is not None else "None", None if irr is not None else "Never pays back"),
             ("Payback", ffix(pb, 1) + " years" if pb is not None else "-", None)]
    for i, (lab, val, sub) in enumerate(cards):
        pdf.stat_card(x0 + (i % 3) * (w3 + gap), y + (i // 3) * (19 + gap), w3, 19, lab, val, sub)
    y += 2 * 19 + gap + 8

    lw = cw * 0.58
    rx = x0 + lw + 8
    rw = cw - lw - 8
    ytop = y
    br = e.get("com_breakdown") or {}
    com = _num(e.get("com"))
    if br:
        yl = pdf.subhead(y, "Cost of manufacture", x=x0, w=lw)
        cols = [{"title": "Item", "w": 54}, {"title": "USD M/y", "w": 18, "align": "R", "kind": "num"},
                {"title": "Share", "w": 16, "align": "R", "kind": "num"}]
        stot = sum((_num(v) or 0) for v in br.values())
        rows = [[k, usd_m(v, 1), pct((_num(v) or 0) / stot * 100 if stot else None, 1)] for k, v in br.items()]
        rows.append([{"t": "Total cost of manufacture", "style": "s"}, {"t": usd_m(com if com is not None else stot, 1), "style": "s"},
                     {"t": "100.0%" if stot else "-", "style": "s"}])
        yl = pdf.table(yl, cols, rows, x=x0, w=lw, total_rows=(-1,))
    else:
        yl = y
    yr = pdf.subhead(ytop, "Unit costs and basis", x=rx, w=rw)
    pdf.hline(rx, rx + rw, yr)
    items = [("Cost of manufacture", per_t(e.get("cost_per_tonne")), "/t"),
             ("Levelised cost", per_t(e.get("levelised_cost_per_tonne")), "/t"),
             ("Capital per annual tonne", per_t(e.get("capex_per_annual_tonne")), "/t"),
             ("Discount rate", pct(e.get("rate"), 1, frac=True), ""),
             ("Plant life", fnum(e.get("life"), 3), "years"),
             ("Tax rate", pct(e.get("tax"), 1, frac=True), ""),
             ("Working capital", money(e.get("working_capital")), "")]
    lab = d.get("labour") or {}
    if lab.get("operators") is not None:
        items.append(("Operators", fnum(lab.get("operators"), 3), ""))
    yr = pdf.kv_list(yr, items, x=rx, w=rw, size=7.8, row_h=6.2)
    y = max(yl, yr) + 6

    cum = [(_num(v)) for v in (e.get("cumulative") or [])]
    cf = [(_num(v)) for v in (e.get("cashflows") or [])]
    if cum and any(v is not None for v in cum):
        y = pdf.ensure(y, 90)
        y = pdf.subhead(y, "Cumulative cash flow", right="USD M, after tax, undiscounted; year 0 is the start of construction")
        ch_h = min(80.0, pdf.bottom - y - 14)
        ax0 = x0 + 14
        ax1 = x0 + cw
        vals = [v if v is not None else 0 for v in cum]
        lo, hi = min(min(vals), 0), max(max(vals), 0)
        step = nice_step((hi - lo) / 1e6, 8) * 1e6
        lo_t = math.floor(lo / step) * step
        hi_t = math.ceil(hi / step) * step
        if hi_t == lo_t:
            hi_t = lo_t + step

        def yv(v):
            return y + ch_h - (v - lo_t) / (hi_t - lo_t) * ch_h

        t = lo_t
        while t <= hi_t + step * 0.01:
            yy = yv(t)
            pdf.hline(ax0, ax1, yy, HAIR if abs(t) > 1e-6 else LINE, 0.2 if abs(t) > 1e-6 else 0.35)
            pdf.font("r", 6.4, MUTED)
            pdf.tnum(ax0 - 2, yy - 1.2, fnum(t / 1e6, 4))
            t += step
        n = len(vals)
        slot = (ax1 - ax0) / n
        bw = slot * 0.62
        for i, v in enumerate(vals):
            bx = ax0 + i * slot + (slot - bw) / 2
            y0_, y1_ = yv(0), yv(v)
            col = ACCENT if v >= 0 else (176, 184, 198)
            top, h = min(y0_, y1_), abs(y1_ - y0_)
            if h > 0.05:
                pdf.rrect(bx, top, bw, h, fill=col, r=min(0.6, h / 2))
            if n <= 12 or i % (2 if n <= 30 else 5) == 0:
                pdf.font("r", 6.2, MUTED)
                pdf.put(bx + bw / 2, y + ch_h + 1.4, str(i), align="C")
        if pb is not None:
            # mark where the cumulative cash position crosses zero, labelled with the payback from the data
            cross = None
            for i in range(1, n):
                if vals[i - 1] < 0 <= vals[i]:
                    cross = (i - 1) + (-vals[i - 1]) / (vals[i] - vals[i - 1])
                    break
            if cross is not None:
                px = ax0 + (cross + 0.5) * slot
                pdf.stroke(GREEN, 0.3)
                pdf.set_dash_pattern(dash=0.8, gap=0.7)
                pdf.line(px, y, px, y + ch_h)
                pdf.set_dash_pattern()
                pdf.font("s", 6.4, GREEN)
                plab = "Payback {} years from start-up".format(ffix(pb, 1))
                pdf.rrect(px + 0.8, y - 0.2, pdf.sw(plab) + 2.4, 3.6, fill=WHITE, r=0)
                pdf.put(px + 2.0, y + 0.4, plab)
        # legend
        ly = y + ch_h + 6.0
        pdf.rrect(ax0, ly + 0.4, 2.4, 2.4, fill=(176, 184, 198), r=0.5)
        pdf.font("r", 6.8, MUTED)
        pdf.put(ax0 + 3.6, ly + 0.3, "Cumulative cash position below zero")
        lx2 = ax0 + 3.6 + pdf.sw("Cumulative cash position below zero") + 6
        pdf.rrect(lx2, ly + 0.4, 2.4, 2.4, fill=ACCENT, r=0.5)
        pdf.put(lx2 + 3.6, ly + 0.3, "Cumulative cash position above zero")
        pdf.font("r", 6.4, MUTED)
        pdf.put(ax1, y + ch_h + 6.3, "Year", align="R")


# ---- carbon --------------------------------------------------------------------------------------
def carbon_page(pdf, d):
    c = d.get("carbon") or {}
    gr = d.get("greener") or {}
    if not c and not gr:
        return
    y = pdf.section("Carbon footprint", c.get("scope_note"))
    x0, cw = MARGIN, pdf.cw
    unit = clean(c.get("unit") or "")
    parts = [("Scope 1", "Direct CO2 (fuel and process)", c.get("direct_co2"), ACCENT),
             ("Scope 1", "Direct N2O, as CO2e", c.get("direct_n2o_co2e"), (93, 118, 248)),
             ("Scope 1", "Direct CH4 slip, as CO2e", c.get("direct_ch4_co2e"), ACCENT_MID),
             ("Scope 2", "Grid electricity", c.get("electricity"), (14, 159, 110)),
             ("Scope 2", "Net steam", c.get("steam"), (110, 200, 168))]
    tot = _num(c.get("total"))
    if tot is not None:
        pdf.stat_card(x0, y, (cw - 4) / 2, 19, "Total, scope 1 and 2", fnum(tot, 3), unit, accent=True)
        grid = c.get("grid_kg_kwh")
        if grid is not None:
            pdf.stat_card(x0 + (cw - 4) / 2 + 4, y, (cw - 4) / 2, 19, "Grid emission factor used", fnum(grid, 3), "kg CO2 per kWh")
        y += 19 + 8
    pos = [(s, l, _num(v), col) for s, l, v, col in parts if _num(v) is not None and _num(v) > 0]
    ptot = sum(v for _, _, v, _ in pos)
    if ptot > 0:
        y = pdf.subhead(y, "Breakdown")
        bx = x0
        for s, l, v, col in pos:
            bw = v / ptot * cw
            pdf.rrect(bx, y, bw, 6.5, fill=col, r=0)
            bx += bw
        pdf.stroke(WHITE, 0.6)
        bx = x0
        for s, l, v, col in pos[:-1]:
            bx += v / ptot * cw
            pdf.line(bx, y, bx, y + 6.5)
        y += 8.5
        lx = x0
        for s, l, v, col in pos:
            pdf.rrect(lx, y + 0.5, 2.4, 2.4, fill=col, r=0.5)
            pdf.font("r", 6.8, MUTED)
            pdf.put(lx + 3.6, y + 0.4, l)
            lx += 3.6 + pdf.sw(l) + 6
        y += 7
    cols = [{"title": "Scope", "w": 14}, {"title": "Source", "w": 50},
            {"title": unit or "Value", "w": 22, "align": "R", "kind": "num"}, {"title": "Share", "w": 14, "align": "R", "kind": "num"}]
    rows = [[{"t": s, "color": INK2}, l, fnum(v, 3), pct((_num(v) or 0) / tot * 100 if tot else None, 1)]
            for s, l, v, col in parts if v is not None]
    if tot is not None:
        rows.append(["", {"t": "Total", "style": "s"}, {"t": fnum(tot, 3), "style": "s"}, {"t": "100.0%", "style": "s"}])
    y = pdf.table(y, cols, rows, total_rows=(-1,) if tot is not None else ()) + 6
    if gr.get("title") or gr.get("text"):
        pdf.font("r", 8.6, INK2)
        th = pdf.para_h(cw - 16, gr.get("text") or "", lh=4.3)
        h = th + 17
        y = pdf.ensure(y, h)
        pdf.rrect(x0, y, cw, h, fill=GREEN_SOFT, r=RADIUS + 0.4)
        pdf.rrect(x0, y, 1.2, h, fill=GREEN, r=0)
        pdf.font("s", 7.2, GREEN)
        pdf.put(x0 + 8, y + 5, "A greener route")
        pdf.font("s", 10.5, INK)
        pdf.put(x0 + 8, y + 9.2, gr.get("title") or "")
        pdf.font("r", 8.6, INK2)
        pdf.para(x0 + 8, y + 15.2, cw - 16, gr.get("text") or "", lh=4.3)


# ---- hazards -------------------------------------------------------------------------------------
def hazards_page(pdf, d):
    hz = d.get("hazards") or []
    ph = d.get("process_hazards") or []
    hop = d.get("hazop") or []
    if not (hz or ph or hop):
        return
    y = pdf.section("Hazards", "Substance data with GHS hazard statements, process hazards and a first pass HAZOP. "
                               "A screening view only; a full HAZOP and layer of protection analysis are needed.")
    x0, cw = MARGIN, pdf.cw
    if hz:
        y = pdf.subhead(y, "Substances")
        cols = [{"title": "Substance", "w": 30}, {"title": "GHS hazard statements", "w": 72},
                {"title": "Flash point, \u00b0C", "w": 13, "align": "R", "kind": "num"},
                {"title": "Autoignition, \u00b0C", "w": 13, "align": "R", "kind": "num"},
                {"title": "LFL to UFL, %", "w": 15, "align": "R", "kind": "num"},
                {"title": "Boiling point, \u00b0C", "w": 13, "align": "R", "kind": "num"}]
        rows = []
        for h in hz:
            ghs = h.get("ghs") or []
            ghs_t = "; ".join("{} {}".format(clean(gg.get("code") or ""), clean(gg.get("text") or "")).strip() for gg in ghs) or "None listed"
            sub = ", ".join(p for p in [clean(h.get("formula") or ""), "CAS " + clean(h.get("cas")) if h.get("cas") else ""] if p)
            name = clean(h.get("name") or h.get("id") or "")
            lfl, ufl = _num(h.get("LFL_pct")), _num(h.get("UFL_pct"))
            rng = "-" if lfl is None and ufl is None else "{} to {}".format(fnum(lfl, 3) if lfl is not None else "-",
                                                                          fnum(ufl, 3) if ufl is not None else "-")
            rows.append([{"t": name, "style": "s", "sub": sub + (" \u00b7 severe" if h.get("severe") else ""),
                          "color": RED if h.get("severe") else INK},
                         {"t": ghs_t, "color": INK2}, fnum(h.get("flash_point_C"), 3), fnum(h.get("autoignition_C"), 3),
                         rng, fnum(h.get("Tb_C"), 3)])
        y = pdf.table(y, cols, rows, size=7.0, head_size=6.3, repeat_title="Substances") + 4
    if ph:
        y = pdf.ensure(y, 26)
        y = pdf.subhead(y, "Process hazards")
        cols = [{"title": "Hazard", "w": 22}, {"title": "Detail", "w": 78}]
        rows = [[{"t": p.get("hazard") or "", "style": "s"}, {"t": p.get("detail") or "", "color": INK2}] for p in ph]
        y = pdf.table(y, cols, rows, size=7.4, repeat_title="Process hazards") + 4
    if hop:
        y = pdf.ensure(y, 30)
        y = pdf.subhead(y, "HAZOP, first pass")
        cols = [{"title": "Node", "w": 15}, {"title": "Deviation", "w": 14}, {"title": "Cause", "w": 21},
                {"title": "Consequence", "w": 25}, {"title": "Safeguards", "w": 25}]
        rows = [[{"t": h.get("node") or "", "style": "s"}, h.get("deviation") or "", {"t": h.get("cause") or "", "color": INK2},
                 {"t": h.get("consequence") or "", "color": INK2}, {"t": h.get("safeguard") or "", "color": INK2}] for h in hop]
        pdf.table(y, cols, rows, size=7.0, head_size=6.3, repeat_title="HAZOP, first pass")


# ---- validation ----------------------------------------------------------------------------------
def validation_page(pdf, d):
    v = d.get("validation") or []
    if not v:
        return
    n_pass, n_fail, n = _validation_counts(d)
    y = pdf.section("Validation", "Model results compared with published data. A check passes when the error is within "
                                  "the stated tolerance, or the model sits inside a published range.")
    x0, cw = MARGIN, pdf.cw
    pdf.badge(x0, y - 1, "{} of {} pass".format(n_pass, n), "pass" if n_pass == n else "na")
    y += 6
    cols = [{"title": "Metric", "w": 37}, {"title": "Model", "w": 12, "align": "R", "kind": "num"},
            {"title": "Published", "w": 15, "align": "R", "kind": "num"}, {"title": "Unit", "w": 15},
            {"title": "Error", "w": 9, "align": "R", "kind": "num"}, {"title": "Tolerance", "w": 9, "align": "R", "kind": "num"},
            {"title": "Result", "w": 10, "align": "R", "kind": "badge"}]
    rows = []
    for r in v:
        pub = r.get("published")
        if isinstance(pub, (list, tuple)) and len(pub) == 2:
            pub_s = "{} to {}".format(fnum(pub[0], 3), fnum(pub[1], 3))
        else:
            pub_s = fnum(pub, 3)
        err = _num(r.get("error_pct"))
        if r.get("inside_range") is True:
            err_s = "in range"
        else:
            err_s = (("+" if err > 0 else "") + ffix(err, 1) + "%") if err is not None else "-"
        tol = _num(r.get("tolerance_pct"))
        ps = r.get("pass")
        badge = ("Pass", "pass") if ps is True else (("Fail", "fail") if ps is False else ("n/a", "na"))
        src = clean(r.get("source") or "")
        note = clean(r.get("note") or "")
        sub = src + ("" if not note else ". " + note)
        rows.append([{"t": r.get("metric") or "", "sub": sub},
                     fnum(r.get("model"), 4), pub_s, {"t": r.get("unit") or "", "color": INK2},
                     {"t": err_s, "color": INK if ps is not False else RED}, ("\u00b1" + fnum(tol, 3) + "%") if tol is not None else "-",
                     {"t": badge[0], "badge": badge[1]}])
    y = pdf.table(y, cols, rows, size=7.2, head_size=6.4, repeat_title=None) + 5

    # sources with links
    seen = []
    for r in v:
        key = (clean(r.get("source") or ""), r.get("url"))
        if key[0] and key not in seen:
            seen.append(key)
    if seen:
        y = pdf.ensure(y, 20)
        y = pdf.subhead(y, "Sources")
        for i, (src, url) in enumerate(seen):
            pdf.font("r", 7.6, INK2)
            lines = pdf.wrap(src, cw - 8)
            ul = pdf.wrap(url, cw - 8) if url else []
            h = len(lines) * 3.5 + len(ul) * 3.2 + 2.4
            y = pdf.ensure(y, h)
            pdf.font("s", 7.6, MUTED)
            pdf.put(x0, y, "{}.".format(i + 1))
            pdf.font("r", 7.6, INK)
            for j, ln in enumerate(lines):
                pdf.put(x0 + 6, y + j * 3.5, ln)
            yy = y + len(lines) * 3.5
            if url:
                pdf.font("r", 6.8, ACCENT)
                for j, ln in enumerate(ul):
                    pdf.put(x0 + 6, yy + j * 3.2, ln)
                    pdf.link(x0 + 6, yy + j * 3.2, pdf.sw(ln), 3.2, url)
            y += h


# ---- assumptions and notes -----------------------------------------------------------------------
def assumptions_page(pdf, d):
    a = [clean(t) for t in (d.get("assumptions") or []) if t]
    notes = [clean(t) for t in (d.get("notes") or []) if t]
    y = pdf.section("Assumptions and notes")
    x0, cw = MARGIN, pdf.cw

    def bullets(y, items):
        for t in items:
            pdf.font("r", 8.6, INK2)
            h = pdf.para_h(cw - 6, t, lh=4.3) + 2.4
            y = pdf.ensure(y, h)
            pdf.fill(ACCENT)
            pdf.ellipse(x0 + 0.6, y + 1.5, 1.2, 1.2, style="F")
            pdf.para(x0 + 5, y, cw - 6, t, lh=4.3)
            y += h
        return y

    if a:
        y = pdf.subhead(y, "Assumptions")
        y = bullets(y, a) + 4
    if notes:
        y = pdf.ensure(y, 20)
        y = pdf.subhead(y, "Notes")
        y = bullets(y, notes) + 4
    y = pdf.ensure(y, 30)
    y = pdf.subhead(y, "Method")
    y = bullets(y, [METHOD_TEXT]) + 4
    if d.get("engine_version"):
        pdf.font("r", 7.2, MUTED)
        pdf.put(x0, y + 2, "Blueprint engine version {}".format(clean(d.get("engine_version"))))


# ---------------------------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------------------------
def build(data: dict, font_dir: str) -> bytes:
    """Return the PDF report for one design (the dict from Design.finish()) as bytes."""
    d = data or {}
    first = _render(d, font_dir, None, None)
    return bytes(_render(d, font_dir, first.pages_count, first.sections_found).output())


def _render(d, font_dir, total, toc):
    pdf = Report(d, font_dir)
    pdf.total_pages = total
    pdf.toc_entries = toc
    product = clean(d.get("product") or d.get("title") or "Process plant")
    region = clean(d.get("region_label") or d.get("region") or "")
    pdf.set_title(clean("{} plant design report{}".format(product, ", " + region if region else "")))
    pdf.set_author("Blueprint")
    pdf.set_creator("Blueprint")
    pdf.set_producer("Blueprint")
    pdf.set_subject(clean(d.get("title") or "First pass plant design"))
    pdf.set_creation_date(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    pdf.set_lang("en-GB")
    cover(pdf, d)
    pfd(pdf, d)
    reactions_page(pdf, d)
    stream_table(pdf, d)
    balance_page(pdf, d)
    equipment_page(pdf, d)
    capex_page(pdf, d)
    economics_page(pdf, d)
    carbon_page(pdf, d)
    hazards_page(pdf, d)
    validation_page(pdf, d)
    assumptions_page(pdf, d)
    return pdf


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    font_dir = os.path.join(root, "site", "fonts")
    if len(argv) >= 1:
        with open(argv[0]) as f:
            data = json.load(f)
        out = argv[1] if len(argv) > 1 else os.path.splitext(argv[0])[0] + ".pdf"
        with open(out, "wb") as f:
            f.write(build(data, font_dir))
        print(out)
        return
    data_dir = os.path.join(root, "site", "data")
    out_dir = os.path.join(root, "site", "pdf")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(data_dir, "index.json")) as f:
        index = json.load(f)
    regions = list((index.get("regions") or {}).keys()) or ["US", "EU", "UK"]
    import time
    for p in index.get("processes") or []:
        if not p.get("live"):
            continue
        for reg in regions:
            src = os.path.join(data_dir, "{}.{}.json".format(p["id"], reg))
            if not os.path.exists(src):
                continue
            with open(src) as f:
                data = json.load(f)
            t = time.time()
            pdf = build(data, font_dir)
            dst = os.path.join(out_dir, "{}.{}.pdf".format(p["id"], reg))
            with open(dst, "wb") as f:
                f.write(pdf)
            print("{:12s} {} {:6.1f} KB {:5.2f}s".format(p["id"], reg, len(pdf) / 1024, time.time() - t))


if __name__ == "__main__":
    main()
