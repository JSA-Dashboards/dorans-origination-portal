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
# The Basis Tracker's Rail FOB seasonal chart: month labels on the x axis (the marketing year starts Sep = week 1), gray true-range band, faded older
# years, last year blue, the Olympic average amber dashed, this year thick black, the latest rundown as a dashed black forward curve, futures-month rules.
MON_WK = {9: 1, 10: 5, 11: 10, 12: 14, 1: 18, 2: 23, 3: 27, 4: 31, 5: 36, 6: 40, 7: 45, 8: 49}
MON_LAB = {1: "Sep", 5: "Oct", 10: "Nov", 14: "Dec", 18: "Jan", 23: "Feb", 27: "Mar", 31: "Apr", 36: "May", 40: "Jun", 45: "Jul", 49: "Aug"}
FUT_RULES = {13: "Z", 27: "H", 35: "K", 44: "N"}
OLD_COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]


def forward_curve(rows: list, market: str) -> dict:
    """{marketing week: bid} of the market's latest posting, one value per delivery month (the tracker's forward-month rule)."""
    sel = [r for r in rows if r["market"] == market and r.get("bid") is not None and not _spread_note(r["period"])]
    if not sel:
        return {}
    d = max(r["date"] for r in sel)
    bm = PER.by_month([[r["period"], r.get("futures"), r["bid"]] for r in sel if r["date"] == d])
    return {MON_WK[m]: v[0] for m, v in bm.items() if m in MON_WK}


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
    today = date.today()
    today_my = today.year if today.month >= 9 else today.year - 1
    window = [y for y in range(today_my - 5, today_my) if y in by_year]
    band = olympic_band(by_year, window)
    lab = lambda y: f"{y}/{str(y + 1)[-2:]}"
    avg_lbl = f"{len(window)}-yr Olympic avg" if len(window) >= 4 else f"{len(window)}-yr avg"

    fig = go.Figure()
    for w, code in FUT_RULES.items():
        fig.add_vline(x=w, line=dict(color="#cbd5e1", width=1.5))
        fig.add_annotation(x=w, y=1, yref="paper", text=code, showarrow=False, yanchor="top", font=dict(size=12, color="#94a3b8"))
    fig.add_hline(y=0, line=dict(color="#94a3b8", width=1, dash="dash"))
    if band:
        ws = sorted(band)
        fig.add_trace(go.Scatter(x=ws + ws[::-1], y=[band[w][2] for w in ws] + [band[w][1] for w in ws[::-1]], fill="toself",
                                 fillcolor="rgba(156,163,175,0.22)", line=dict(width=0), hoverinfo="skip", name=f"{len(window)}-yr range"))
    old = [y for y in by_year if y < cur - 1]
    for i, y in enumerate(old):
        wks = by_year[y]
        fig.add_trace(go.Scatter(x=list(wks), y=list(wks.values()), mode="lines", name=lab(y), opacity=0.5,
                                 line=dict(width=1.3, color=OLD_COLORS[i % len(OLD_COLORS)]), hovertemplate=lab(y) + " wk %{x}: %{y:.1f}¢<extra></extra>"))
    if cur - 1 in by_year:
        wks = by_year[cur - 1]
        fig.add_trace(go.Scatter(x=list(wks), y=list(wks.values()), mode="lines+text", name=lab(cur - 1), line=dict(width=4, color="#2563eb"),
                                 text=[""] * (len(wks) - 1) + [lab(cur - 1)], textposition="middle right", textfont=dict(color="#2563eb", size=10),
                                 hovertemplate=lab(cur - 1) + " wk %{x}: %{y:.1f}¢<extra></extra>"))
    if band:
        ws = sorted(band)
        fig.add_trace(go.Scatter(x=ws, y=[band[w][0] for w in ws], mode="lines+text", name=avg_lbl, line=dict(color="#d97706", width=3, dash="dash"),
                                 text=[""] * (len(ws) - 1) + [avg_lbl], textposition="middle right", textfont=dict(color="#d97706", size=10),
                                 hovertemplate=avg_lbl + " wk %{x}: %{y:.1f}¢<extra></extra>"))
    fwd = forward_curve(all_rows, mk)
    if fwd:
        twk = min(52, max(1, (today - date(today_my, 9, 1)).days // 7 + 1))
        for seg, nm in (({w: v for w, v in fwd.items() if w >= twk}, "Forward curve"), ({w: v for w, v in fwd.items() if w < twk}, "Forward (next marketing year)")):
            if seg:
                ws = sorted(seg)
                fig.add_trace(go.Scatter(x=ws, y=[seg[w] for w in ws], mode="lines+markers", name=nm, line=dict(color="#000", width=2, dash="dash"),
                                         marker=dict(size=7, color="#000"), hovertemplate="Fwd bid wk %{x}: %{y:.0f}¢<extra></extra>"))
    wks = by_year[cur]
    fig.add_trace(go.Scatter(x=list(wks), y=list(wks.values()), mode="lines+text", name=lab(cur), line=dict(width=4, color="#000"),
                             text=[""] * (len(wks) - 1) + [lab(cur)], textposition="middle right", textfont=dict(color="#000", size=10),
                             hovertemplate=lab(cur) + " wk %{x}: %{y:.1f}¢<extra></extra>"))
    comm = next((r.get("commodity") for r in all_rows if r["market"] == mk and r.get("commodity")), "")
    st.markdown(
        f'<div style="margin-top:8px;margin-bottom:2px;font-size:14px;color:#1e293b;font-weight:800">{mk} · {pd_sel}{" · " + comm if comm else ""}</div>'
        '<div style="margin-bottom:4px;font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.1em">Seasonal Bid — Marketing Year (Sep–Aug)'
        f'&nbsp;&nbsp;<span style="font-weight:400;text-transform:none"><b style="color:#000">{lab(cur)} = black</b>'
        + (f' · <b style="color:#2563eb">{lab(cur - 1)} = blue</b>' if cur - 1 in by_year else "")
        + (f' · <b style="color:#d97706">{avg_lbl} = amber dash</b>' if band else "") + "</span></div>", unsafe_allow_html=True)
    fig.update_layout(height=560, margin=dict(l=0, r=60, t=14, b=0), paper_bgcolor="#fff", plot_bgcolor="#fff", legend=dict(orientation="h", y=-0.08, font=dict(size=10)),
                      yaxis=dict(title="Bid (¢)", gridcolor="#e2e8f0", zeroline=False),
                      xaxis=dict(tickmode="array", tickvals=list(MON_LAB), ticktext=list(MON_LAB.values()), range=[1, 52], showgrid=False))
    st.plotly_chart(fig, use_container_width=True)
    first = min(d for d, _ in pts)
    st.caption(f"{len(n[pd_sel])} postings · weekly average where a period was posted more than once. Black = {lab(cur)}, blue = {lab(cur - 1)}, "
               + (f"amber dash = the Olympic average of the last {len(window)} complete years (each week's highest and lowest year dropped; under four years the plain mean) with their true range shaded gray; "
                  if band else "the average and range appear once two complete years are archived; ")
               + f"dashed black = the latest rundown by delivery month. The archive's CN history starts {first:%b %Y}. Source: the Basis Tracker's rail archive.")
