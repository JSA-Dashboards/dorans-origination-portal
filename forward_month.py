"""forward_month.py - one number per delivery month, for every forward curve drawn from posted period labels.

A posting often quotes a month several ways at once: 'Dec' (the whole month), 'FH Dec' / 'LH Dec' (its halves), and packages that span it
('JFM', 'Nov-Jul'). Averaging all of them made a chart disagree with the bid on the board: CSX Columbus posted Dec +16 and FH Dec +13 on
2026-10-20, and the emailed forward curve drew +14.5 ('+15') for December - and +10 for November, whose own bid was +19, because FH Nov and the
Nov-Jul package were averaged in (Kolten, 2026-10-20: "for months that show a full month but also a FH or LH just default to the full month
indication, only take the midpoint if its a FH and LH separate bids"). The rule, in one place:

  * a month's FULL bid is the month - its half-month bids and day windows are left out of it;
  * no full bid: the MIDPOINT of the first part (FH, or a window that opens the month) and the last part (LH), when both are posted;
  * no full bid and only one part posted: that part;
  * a package ('JFM', 'AMJJ', 'Nov-Jul', 'Oct/Nov') never overrides a month's own quote: it fills a month nothing of its own names, the narrowest
    package first, spread by a carry so its months average back to its bid (rail_forward).

Pure - no database, no Streamlit. A label is classified by return_to_carry_data.parse_label (the reading the shipment table and the Spread tab
use), imported on first use. Callers: rail_report (the emailed seasonal chart), app.py (the Rail FOB tab's seasonal chart; the Bids and Spread tabs'
forward points) and rail_spread (the Spread tab's forward spread).


VENDORED from the Basis Tracker (forward_month.py + return_to_carry_data.parse_label / is_spread_note, one file): the tracker is the source of truth - change it there, then re-copy.
"""
from __future__ import annotations

import re
from functools import lru_cache

_SPREAD_NOTE = re.compile(r"\bspread\b", re.I)


def _is_spread_note(period: str | None) -> bool:
    """A posted line that quotes a SPREAD between two delivery periods ('Spread-Sell FH Nov CP / Buy FH Nov ; offered'), not a period's basis: its number
    is the spread (-2), so it is never a nearby bid, a forward quote or a month's value. BN PNW charted -2 as its spot on 2026-10-19 because the note was
    that posting's first line (Kolten: "fix the BN PNW")."""
    return bool(_SPREAD_NOTE.search(period or ""))


_MON = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
        "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12}
_NAME = re.compile(r"\b(" + "|".join(sorted(_MON, key=len, reverse=True)) + r")\b")
_NOISE = re.compile(r"\b(bid|offer|split|late|early|bal|balance|thru|through|no holiday)\b")
_RING = "JFMAMJJASOND" * 2


def _expand_initials(tok: str):
    """'JFM' -> (1, 2, 3), 'AMJJ' -> (4, 5, 6, 7): a run of month initials, if it spells exactly one run of months."""
    s = tok.upper()
    n = len(s)
    if n < 2 or n > 12 or not re.fullmatch(r"[JFMASOND]+", s):
        return None
    starts = [i for i in range(12) if _RING[i:i + n] == s]
    return tuple((starts[0] + k) % 12 + 1 for k in range(n)) if len(starts) == 1 else None


@lru_cache(maxsize=4096)
def _parse_label(label: str | None) -> dict | None:
    """What delivery window a posted period covers: {'months': (m, ...), 'kind', 'span', 'year'}, or None when it names
    no month ('Spot', 'Nearby', 'NC 26', note rows). (Cached — a few hundred distinct labels cover years of postings;
    the result is shared, so treat it as read-only.)

    kind   'full'    a whole month ('Dec', 'Dec 2026', 'Nov (no holiday)')
           'window'  a month's first weeks to about the 20th ('Dec 1-20', 'Nov 1-25')
           'lh'/'fh' the last / first half of a month ('LH Nov', 'FH Dec')
           'bundle'  several months at one price ('JFM', 'AMJJ', 'DJFM', 'Jan-Jul', 'Oct/Nov', 'LH Oct / FH Nov')"""
    t = (label or "").lower()
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\s+", " ", _NOISE.sub(" ", t)).strip()
    if not t:
        return None
    ym = re.search(r"(?<!\d)(20\d\d)(?!\d)", t)
    year = int(ym.group(1)) if ym else None
    names = list(_NAME.finditer(t))
    if not names:
        # a run of initials ('JFM', 'LH OND'): the one word that is not a half-month qualifier must spell the months —
        # a stray letter ('k JFM', left by the old paste parser) or an unknown word ('ex AM') is not a package
        core = [w for w in t.split() if w not in ("fh", "lh", "mp", "lp")]
        months = _expand_initials(core[0]) if len(core) == 1 else None
        return {"months": months, "kind": "bundle", "span": len(months), "year": None} if months else None
    seq, prev_end = [], 0
    for i, m in enumerate(names):
        pre = t[prev_end:m.start()]
        post = t[m.end():(names[i + 1].start() if i + 1 < len(names) else len(t))]
        q = None
        if re.search(r"\b(fh|f\.h\.|first half)\s*$", pre) or re.match(r"\s*(fh|first half)\b", post):
            q = "fh"
        elif re.search(r"\b(lh|l\.h\.|last half)\s*$", pre) or re.match(r"\s*(lh|last half)\b", post):
            q = "lh"
        seq.append((_MON[m.group(1)], q, post))
        prev_end = m.end()
    if len(seq) == 1:
        month, q, post = seq[0]
        kind = q or "full"
        w = re.match(r"\s*(?:20\d\d\s*)?(\d{1,2})\s*-\s*(\d{1,2})\b", post)
        if w and q is None:
            s, e = int(w.group(1)), int(w.group(2))
            kind = "full" if (s <= 1 and e >= 28) else "lh" if s >= 16 else "fh" if e <= 15 else "window"
        return {"months": (month,), "kind": kind, "span": 1, "year": year}
    months = [seq[0][0]]
    for i in range(len(seq) - 1):
        a, b = seq[i][0], seq[i + 1][0]
        j = re.sub(r"\b(?:fh|lh|first half|last half)\b|\d+", " ", t[names[i].end():names[i + 1].start()])
        if re.search(r"-|\bto\b", j) or not re.sub(r"[().:\s]", "", j):       # Jan-Jul, Oct-Mar, 'Jan July': every month in between
            months += [(a - 1 + k) % 12 + 1 for k in range(1, ((b - a) % 12) + 1)]
        else:                                                                # Oct/Nov, LH Oct / FH Nov, 'Nov, Dec': just those two
            months.append(b)
    months = tuple(dict.fromkeys(months))
    return {"months": months, "kind": "bundle", "span": len(months), "year": None}


FIRST_PART = ("fh", "window")      # a half, or a window to about the 20th, that opens the month
LAST_PART = ("lh",)                # the last half
CARRY = 2.0                        # cents per month: how a package is spread across the months it names (the chart's long-standing 2c)
ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

_PLACEMENT = re.compile(r"\b(lp|fp)\b", re.I)      # LP (last placement) = LH, FP = FH: how the Rail FOB seasonal chart reads them
_SLASH_HALF = re.compile(r"\b([fl])\s*[/.]\s*h\b\.?", re.I)    # F/H, L/H (the freight sheets' spelling), F.H. = FH, LH
_MID_PLACEMENT = re.compile(r"\bmp\b", re.I)       # MP (mid-month placement): a partial of its month, not the whole month


@lru_cache(maxsize=4096)
def label_info(label):
    """(kind, months) of a posted period label: kind 'full' | 'window' | 'fh' | 'lh' | 'bundle', months a tuple of month numbers in the
    order the label names them. (None, ()) when the label names no month ('Spot', 'Return Trip', 'NC 26', note rows). The reading is
    return_to_carry_data.parse_label's, except that LP / FP / F/H / L/H are the last / first half and MP is a partial window (parse_label
    would call all of them whole-month bids). A spread note ('Spread-Sell FH Nov CP / Buy FH Nov ; offered') is no delivery period at all."""
    if _is_spread_note(label):
        return None, ()
    text = _SLASH_HALF.sub(lambda m: m.group(1).upper() + "H", str(label or ""))
    text = _PLACEMENT.sub(lambda m: "LH" if m.group(1).lower() == "lp" else "FH", text)
    info = _parse_label(text)
    if not info or not info.get("months"):
        return None, ()
    kind = info["kind"]
    if kind == "full" and _MID_PLACEMENT.search(text):
        kind = "window"
    return kind, tuple(info["months"])


def is_spread_note(label) -> bool:
    """A posted line that quotes a spread between two periods, not a period's basis (return_to_carry_data.is_spread_note): never a spot, a month or a package."""
    return _is_spread_note(label)


def kind_of(label):
    """The kind of one delivery label as a month quote - 'full' when it names no month at all (a 'New Crop' row stands for its futures month)."""
    return label_info(label)[0] or "full"


def month_value(quotes):
    """The one value a month stands for, from its quotes [(kind, value)]; None when there are none (a value of None is skipped).
    The mean of the full bids (normally one); else the midpoint of the first part's and the last part's means when both are posted; else the
    lone part; else - only package folds left - their mean."""
    full, first, last, folded = [], [], [], []
    for kind, v in quotes:
        if v is None:
            continue
        v = float(v)
        if kind in FIRST_PART:
            first.append(v)
        elif kind in LAST_PART:
            last.append(v)
        elif kind == "bundle":
            folded.append(v)
        else:
            full.append(v)

    def mean(xs):
        return sum(xs) / len(xs)

    if full:
        return mean(full)
    if first and last:
        return (mean(first) + mean(last)) / 2.0
    if first or last:
        return mean(first or last)
    return mean(folded) if folded else None


def pick_months(items):
    """{key: value} from [(key, kind, value)] - month_value over each key's quotes, keys in the order first seen. The key is whatever
    identifies a month to the caller: a month number, (year, month), (marketing year, week), or a whole (market, month, date) tuple."""
    by: dict = {}
    for key, kind, v in items:
        by.setdefault(key, []).append((kind, v))
    out: dict = {}
    for key, qs in by.items():
        v = month_value(qs)
        if v is not None:
            out[key] = v
    return out


def rail_forward(cells, carry=CARRY):
    """{month number: value} for ONE rail posting; cells = [(period label, bid)], a bid of None skipped, a label naming no month ignored.
    A month's own quotes go through month_value. A package (one price for several months) fills each month nothing of its own names, the
    narrowest package first (the higher bid between equals), spread by `carry` cents a month around its centre so its months average back to
    the package bid: JFM +19 -> Jan 17 / Feb 19 / Mar 21."""
    own: dict = {}
    packages: list = []
    for label, bid in cells:
        if bid is None:
            continue
        kind, months = label_info(label)
        if not months:
            continue
        if kind == "bundle" or len(months) > 1:
            packages.append((len(months), -float(bid), months, float(bid)))
        else:
            own.setdefault(months[0], []).append((kind, bid))
    out = {m: month_value(qs) for m, qs in own.items()}
    for _span, _nb, months, bid in sorted(packages, key=lambda p: (p[0], p[1])):
        centre = (len(months) - 1) / 2.0
        for i, m in enumerate(months):
            if m not in out:
                out[m] = round(bid + carry * (i - centre), 1)
    return out
