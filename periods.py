"""Reading posted period labels ('Nov', 'FH Dec', 'Nov 9-30', "Mch '27", 'January 2027', 'JFM'): which calendar month a bid is for, and the one value
a month gets when it is posted several ways. Pure; no database, no Streamlit.

The month rule is the Basis Tracker's (forward_month.py, Kolten 2026-10-20): a month's FULL bid is the month; with none, the midpoint of the first
half and the last half when both are posted, else the lone half. The seasonal bucketing is the Rail FOB tab's (`_seasonal_bucket`, 2026-07-21):
spelling normalised, Dom/Mex and forward-year marks dropped, FH/LH/MP/Split qualifiers stripped, the rest filed under its FIRST named month.
"""
import re

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEAS_PERIODS = ["Spot"] + MONTHS + ["OND", "JFM", "AM", "JJ", "AMJJ", "Jan-Jul", "AS"]
_MONWORD = {"JANUARY": "Jan", "FEBRUARY": "Feb", "MARCH": "Mar", "MCH": "Mar", "APRIL": "Apr", "MAY": "May", "JUNE": "Jun", "JULY": "Jul",
            "AUGUST": "Aug", "SEPTEMBER": "Sep", "SEPT": "Sep", "OCTOBER": "Oct", "NOVEMBER": "Nov", "DECEMBER": "Dec"}
_MON3 = {m.upper(): m for m in MONTHS}
_HALF = {"LP": "LH", "FP": "FH"}
_ALIAS = {"JFMAMJJ": "Jan-Jul", "DJFMAMJJ": "Jan-Jul", "DJFM": "JFM", "ND": "Nov/Dec"}


def canon_period(p) -> str:
    """Spelling only: month words to 3 letters, LP / FP to LH / FH, F/H and L/H to FH / LH."""
    s = re.sub(r"\b([FL])\s*[/.]\s*H\b\.?", lambda m: m.group(1).upper() + "H", str(p), flags=re.I)

    def tok(m):
        u = m.group(0).upper()
        return _MONWORD.get(u) or _MON3.get(u) or _HALF.get(u) or (u if u in ("FH", "LH", "MP") else m.group(0))
    return re.sub(r"[A-Za-z]+", tok, " ".join(s.split()))


def seasonal_bucket(p):
    """One of SEAS_PERIODS, or None for a period the seasonals leave out (an unlisted package, 'Return Trip' ...)."""
    s = canon_period(p)
    s = re.sub(r"\s*\b(?:Dom|Mex)\b", "", s).strip()
    s = re.sub(r"\s*'\d\d$", "", s).strip()
    s = _ALIAS.get(s, s)
    if s in SEAS_PERIODS:
        return s
    core = _ALIAS.get(re.sub(r"^(?:FH|LH|MP|Split|Full)\s+", "", s), re.sub(r"^(?:FH|LH|MP|Split|Full)\s+", "", s))
    if core in SEAS_PERIODS:
        return core
    m = re.search(r"\b(" + "|".join(MONTHS) + r")\b", core)
    return m.group(1) if m else None


def kind_of(label) -> str:
    """'fh' | 'lh' | 'split' | 'full' for a month-bearing label ('FH Dec', 'LH Dec', 'Split Dec', anything else)."""
    s = canon_period(label)
    if re.match(r"^FH\b", s):
        return "fh"
    if re.match(r"^LH\b", s):
        return "lh"
    if re.match(r"^Split\b", s):
        return "split"
    return "full"


def month_value(quotes: list):
    """[(kind, value)] posted for one month on one day -> the month's single value. Full (or Split) bid wins; else the FH / LH midpoint; else the lone half."""
    full = [v for k, v in quotes if k in ("full", "split") and v is not None]
    if full:
        return sum(full) / len(full)
    fh = [v for k, v in quotes if k == "fh" and v is not None]
    lh = [v for k, v in quotes if k == "lh" and v is not None]
    if fh and lh:
        return (sum(fh) / len(fh) + sum(lh) / len(lh)) / 2
    half = fh or lh
    return sum(half) / len(half) if half else None


def month_of(label):
    """Calendar month (1-12) a single-month label names, else None (packages and unreadable labels). 'Nov 9-30' and 'LH Oct' are single months."""
    b = seasonal_bucket(label)
    return MONTHS.index(b) + 1 if b in MONTHS else None


def by_month(rows: list) -> dict:
    """[[label, symbol, basis, is_spot, ...]] -> {month: (basis, futures symbol)}: each month's one value, the futures month of the quote behind it."""
    acc = {}
    for r in rows:
        m = month_of(r[0])
        if m is not None and r[2] is not None:
            acc.setdefault(m, []).append((kind_of(r[0]), r[2], r[1]))
    out = {}
    for m, qs in acc.items():
        v = month_value([(k, b) for k, b, _ in qs])
        if v is not None:
            out[m] = (v, qs[0][2])
    return out
