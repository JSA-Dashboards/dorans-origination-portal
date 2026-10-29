"""CN basis seasonals, the way the Basis Tracker's Rail FOB seasonal chart draws them: a corridor and a shipping period, one line per marketing year
(Sep-Aug, weekly means), the current year in bold, last year in blue, and the trailing 5-year Olympic average with its range band.

The bids come from the Basis Tracker's rail archive (`rail_fob`, read through rail_data), so what is charted is what the tracker's views chart.
Bucketing and the one-value-per-month rule are periods.py (the tracker's `_seasonal_bucket` and forward_month). Pure functions first; drawing last.
"""
from datetime import date

import periods as PER

# Markets the tracker's view never draws, and lines that are freight rather than a bid
HIDDEN_MARKETS = {"BN COBO Buyers"}
_NOT_A_BID = ("freight", "shuttle")


def cn_markets(rows: list) -> list:
    """CN bid corridors in the archive, with the commodity each carries."""
    seen = {}
    for r in rows:
        m = r["market"]
        if m in HIDDEN_MARKETS or any(w in m.lower() for w in _NOT_A_BID):
            continue
        if str(r.get("rail") or "").upper() == "CN" or m.upper().startswith("CN"):
            seen.setdefault(m, r.get("commodity") or "")
    return sorted(seen)


def _spread_note(period) -> bool:
    p = str(period).lower()
    return "spread" in p or p.startswith(("sellers", "buyers"))


def bucket_rows(rows: list, market: str) -> list:
    """[(period bucket, date, bid)] for one corridor. A month posted several ways on a day is ONE value (full bid, else FH/LH midpoint); a day
    with no 'Spot' row gets a derived Spot from its nearest period, as the tracker does so the Spot series runs on into the current year."""
    mon, other, order, spot_days = {}, [], {}, set()
    for r in rows:
        if r["market"] != market or r.get("bid") is None or _spread_note(r["period"]):
            continue
        b = PER.seasonal_bucket(r["period"])
        d = r["date"]
        po = r.get("period_order")
        order.setdefault(d, []).append((po if po is not None else 99, r["bid"]))
        if b in PER.MONTHS:
            mon.setdefault((b, d), []).append((PER.kind_of(r["period"]), r["bid"]))
        elif b:
            other.append((b, d, r["bid"]))
            if b == "Spot":
                spot_days.add(d)
    out = list(other)
    for (b, d), qs in mon.items():
        v = PER.month_value(qs)
        if v is not None:
            out.append((b, d, v))
    for d, lst in order.items():
        if d not in spot_days:
            lst.sort(key=lambda t: t[0])
            out.append(("Spot", d, lst[0][1]))
    return out


def marketing_week(d: date) -> tuple:
    """(marketing year number, week 1-52): the year starts Sep 1, like the tracker's seasonal charts."""
    my = d.year if d.month >= 9 else d.year - 1
    return my, min((d - date(my, 9, 1)).days // 7 + 1, 52)


def weekly(points: list) -> dict:
    """[(date, bid)] -> {marketing year: {week: mean bid}}."""
    acc = {}
    for d, v in points:
        my, wk = marketing_week(d)
        acc.setdefault(my, {}).setdefault(wk, []).append(v)
    return {y: {w: sum(v) / len(v) for w, v in sorted(wks.items())} for y, wks in sorted(acc.items())}


def olympic_band(by_year: dict, window: list) -> dict:
    """{week: (olympic average, low, high)} over the `window` years: each week's highest and lowest year are dropped before averaging
    (four or more years), the range is the true min to max (Kolten 2026-10-20 / 10-26)."""
    out = {}
    for w in range(1, 53):
        v = sorted(by_year[y][w] for y in window if y in by_year and w in by_year[y])
        if len(v) >= 2:
            core = v[1:-1] if len(v) >= 4 else v
            out[w] = (sum(core) / len(core), v[0], v[-1])
    return out


def week_label(w: int) -> str:
    d = date.fromordinal(date(2025, 9, 1).toordinal() + (w - 1) * 7)
    return d.strftime("%b %d").replace(" 0", " ")


# ── drawing ──────────────────────────────────────────────────────────────────────────────────────────────────────
def render(all_rows: list) -> None:
    import plotly.graph_objects as go
    import streamlit as st

    markets = cn_markets(all_rows)
    if not markets:
        st.info("No CN corridors in the rail archive yet.")
        return
    c1, c2 = st.columns([1.3, 1])
    mk = c1.selectbox("Corridor", markets, key="cnseas_mkt")
    rb = bucket_rows(all_rows, mk)
    n = {}
    for b, d, _ in rb:
        n.setdefault(b, set()).add(d)
    opts = [p for p in PER.SEAS_PERIODS if len(n.get(p, ())) >= 3]
    if not opts:
        st.caption(f"{mk} has no shipping period with enough postings to chart yet.")
        return
    pd_sel = c2.selectbox("Shipping period", opts, format_func=lambda p: f"{p}  ({len(n[p])})", key="cnseas_per")
    pts = [(d, v) for b, d, v in rb if b == pd_sel]
    by_year = weekly(pts)
    cur = max(by_year)
    today_my = date.today().year if date.today().month >= 9 else date.today().year - 1
    window = [y for y in range(today_my - 5, today_my) if y in by_year]
    band = olympic_band(by_year, window)

    fig = go.Figure()
    if band:
        ws = sorted(band)
        fig.add_trace(go.Scatter(x=ws + ws[::-1], y=[band[w][2] for w in ws] + [band[w][1] for w in ws[::-1]], fill="toself",
                                 fillcolor="rgba(217,119,6,0.12)", line=dict(width=0), hoverinfo="skip", name=f"{len(window)}-yr range"))
        fig.add_trace(go.Scatter(x=ws, y=[band[w][0] for w in ws], mode="lines", name=f"{len(window)}-yr Olympic avg",
                                 line=dict(color="#d97706", width=2, dash="dash")))
    for y, wks in by_year.items():
        if y == cur or y == cur - 1 or y not in window:
            continue
        fig.add_trace(go.Scatter(x=list(wks), y=list(wks.values()), mode="lines", name=f"{y}/{str(y + 1)[-2:]}", line=dict(width=1, color="#c3ccd6")))
    for y, color, width in ((cur - 1, "#2563eb", 2.5), (cur, "#32373c", 3.5)):
        if y in by_year:
            wks = by_year[y]
            fig.add_trace(go.Scatter(x=list(wks), y=list(wks.values()), mode="lines+markers" if y == cur else "lines", name=f"{y}/{str(y + 1)[-2:]}",
                                     line=dict(width=width, color=color), marker=dict(size=4)))
    ticks = list(range(1, 53, 4))
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="#fff", plot_bgcolor="#fff",
                      yaxis=dict(title="¢/bu vs futures", gridcolor="#e2e8f0", zeroline=True, zerolinecolor="#94a3b8"),
                      xaxis=dict(tickmode="array", tickvals=ticks, ticktext=[week_label(w) for w in ticks]), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, use_container_width=True)
    first = min(d for d, _ in pts)
    st.caption(f"{mk} · {pd_sel}: marketing years Sep–Aug, weekly means. Bold = {cur}/{str(cur + 1)[-2:]}, blue = last year"
               + (f", dashed = the Olympic average of the last {len(window)} complete years with the full range shaded." if band else
                  "; the 5-year band appears once two complete years are archived.")
               + f" The archive's CN history starts {first:%b %Y}. Source: the Basis Tracker's rail archive.")
