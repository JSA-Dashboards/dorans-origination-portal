"""CN basis seasonals, the way the Basis Tracker's Rail FOB seasonal chart draws them: a corridor and a shipping period, one line per marketing year
(Sep-Aug, weekly means), the current year in bold, last year in blue, and the trailing 5-year Olympic average with its range band.

The bids come from the Basis Tracker's rail archive (`rail_fob`, read through rail_data), so what is charted is what the tracker's views chart.
Bucketing and the one-value-per-month rule are periods.py (the tracker's `_seasonal_bucket` and forward_month). Pure functions first; drawing last.
"""
import base64
from datetime import date
from pathlib import Path

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


# ── drawing: the Basis Tracker's Rail FOB seasonal chart (app.py `_rail_seasonal`), ported line for line to Altair ───────────────────────────────────────
# Same data prep (a month's day-bids become ONE value, derived Spot, weekly means), same layers and colours, best-fit y-axis, years picker, Olympic average,
# true-range band, forward curve with packages spread by the carry, futures-month rules, logo watermark, title block, caption and PNG download.
_CHART_PAD = {"left": 6, "right": 22, "top": 8, "bottom": 6}
_YFIT = {"75%": (0.125, 0.875), "90%": (0.05, 0.95), "95%": (0.025, 0.975), "Full": None}
_YFIT_DEFAULT = "90%"
_LOGO = Path(__file__).parent / "assets" / "50 Year logo JSA.png"
_MON_WK = {"Sep": 1, "Oct": 5, "Nov": 10, "Dec": 14, "Jan": 18, "Feb": 23, "Mar": 27, "Apr": 31, "May": 36, "Jun": 40, "Jul": 45, "Aug": 49}
_CARRY = 2.0        # cents a month a package is spread across the months it names


def _yfit_scale(values, fit=_YFIT_DEFAULT, pad_frac=0.08):
    """alt.Scale zoomed to the central `fit` % of `values`. Needs >=8 points to clamp."""
    import altair as _alt
    import pandas as _pd
    vals = [v for v in values if v is not None]
    pct = _YFIT.get(fit)
    if pct is None or len(vals) < 8:
        return _alt.Scale(zero=False)
    q = _pd.Series(vals).quantile(list(pct))
    lo, hi = float(q.iloc[0]), float(q.iloc[1])
    if hi <= lo:
        return _alt.Scale(zero=False)
    pad = (hi - lo) * pad_frac
    return _alt.Scale(zero=False, domain=[round(lo - pad), round(hi + pad)], clamp=True)


def _chart_png(chart, width: int = 1100, height: int = 560, scale: float = 2.0):
    """Altair chart -> PNG bytes via vl-convert; None on failure."""
    try:
        import json as _json
        import vl_convert as _vlc
        spec = _json.dumps(chart.properties(width=width, height=height).to_dict(), default=str)
        return _vlc.vegalite_to_png(spec, scale=scale)
    except Exception:
        return None


def render(all_rows: list) -> None:
    import altair as _alt
    import pandas as _pd
    import streamlit as st

    import forward_month as _fm
    import seasonal_band as _sband

    cn = set(cn_markets(all_rows))
    if not cn:
        st.info("No CN corridors in the rail archive yet.")
        return
    _SEAS_MON = PER.MONTHS
    _rows = []
    _spot_seen = set()                     # (market, date) with an explicit "Spot" row
    _mdate = {}                            # (market, date, commodity) -> [(period_order, bid)]
    _mquotes = {}                          # (market, month, date, commodity) -> [(kind, bid)]
    _fwd_cells = {}                        # (market, date) -> [(period, bid)] for the forward curve
    for _r in all_rows:
        if _r["market"] not in cn or _r.get("bid") is None or _fm.is_spread_note(_r["period"]):
            continue                      # a spread note's number is the spread, not a period's basis
        _b = PER.seasonal_bucket(_r["period"])
        _rc = _r.get("commodity") or "Corn"
        if _b in _SEAS_MON:             # a month: the day's full / FH / LH bids become ONE value below
            _mquotes.setdefault((_r["market"], _b, _r["date"], _rc), []).append((_fm.kind_of(_r["period"]), _r["bid"]))
        elif _b:                        # None = not a tracked seasonal period
            _rows.append((_r["market"], _b, _r["date"], _r["bid"], _rc, _r.get("bid_raw") == "est"))
            if _b == "Spot":
                _spot_seen.add((_r["market"], _r["date"]))
        if _b and _b != "Spot":         # the forward curve reads the posted label (a tracked package by its bucket name)
            _fwd_cells.setdefault((_r["market"], _r["date"]), []).append((_r["period"] if _b in _SEAS_MON else _b, _r["bid"]))
        _po = _r.get("period_order")
        _mdate.setdefault((_r["market"], _r["date"], _rc), []).append((_po if _po is not None else 99, _r["bid"]))
    # A month posted several ways on one day is ONE value (forward_month): its full-month bid; with none, the midpoint of FH and LH when both are posted, else the lone half.
    for (_m, _b, _d, _c), _qs in _mquotes.items():
        _mv = _fm.month_value(_qs)
        if _mv is not None:
            _rows.append((_m, _b, _d, _mv, _c, False))
    # Derived Spot = nearest-period bid, added only where no explicit "Spot" exists.
    for (_m, _d, _c), _lst in _mdate.items():
        if (_m, _d) in _spot_seen:
            continue
        _lst.sort(key=lambda t: t[0])
        _sb = next((b for _o, b in _lst if b is not None), None)
        if _sb is not None:
            _rows.append((_m, "Spot", _d, _sb, _c, False))
    if not _rows:
        st.caption("No rail history archived yet — the seasonal chart fills in as postings are saved.")
        return
    _df = _pd.DataFrame(_rows, columns=["Market", "Period", "Date", "Bid", "Commodity", "Est"])

    _mk_n = _df.groupby("Market")["Date"].nunique()
    _mk_opts = sorted(m for m in _mk_n.index if _mk_n[m] >= 6)
    if not _mk_opts:
        st.caption("Not enough rail history yet to chart a season.")
        return

    _c1, _c2, _c3 = st.columns([3, 2, 5])
    with _c1:
        _mk = st.selectbox("Corridor", _mk_opts, key="cnseas_mkt")
    _pv = _df[_df["Market"] == _mk]
    _p_n = _pv.groupby("Period")["Date"].nunique()
    # Fixed order — Spot, calendar months, then the tracked packages — rather than by frequency.
    _p_opts = [p for p in PER.SEAS_PERIODS if _p_n.get(p, 0) >= 3]
    if not _p_opts:
        st.caption(f"{_mk} has no shipping period with enough postings to chart yet.")
        return
    with _c2:
        _pd_sel = st.selectbox("Shipping period", _p_opts, key="cnseas_per", format_func=lambda p: f"{p}  ({_p_n[p]})")
    with _c3:
        st.caption("Best fit")
        _rfit = st.radio("Best fit", list(_YFIT), index=list(_YFIT).index(_YFIT_DEFAULT), horizontal=True, key="cnseas_fit", label_visibility="collapsed",
                         help="Zoom the y-axis to the central % of values so outlier weeks don't squash the chart. 'Full' shows the raw min/max.")

    _sel = _pv[_pv["Period"] == _pd_sel][["Date", "Bid", "Est"]].copy()
    _dts = _pd.to_datetime(_sel["Date"])
    _yr, _mo = _dts.dt.year, _dts.dt.month
    _sel["MktYearNum"] = _yr.where(_mo >= 9, _yr - 1)
    _sel["MktYear"] = _sel["MktYearNum"].apply(lambda y: f"{y}/{str(y + 1)[-2:]}")
    _sep1 = _pd.to_datetime(_sel["MktYearNum"].astype(str) + "-09-01")
    _sel["MktWeek"] = ((_dts - _sep1).dt.days // 7 + 1).clip(1, 52)
    _sel = (_sel.groupby(["MktYear", "MktYearNum", "MktWeek"], as_index=False).agg(Bid=("Bid", "mean"), Est=("Est", "max")))
    _sel["Bid"] = _sel["Bid"].round(1)

    _mx = int(_sel["MktYearNum"].max())
    # Year picker — defaults to the most recent 10 marketing years; band/average stay on calendar trailing-5.
    _all_yrs = sorted(_sel["MktYearNum"].unique(), reverse=True)
    _default_yrs = [y for y in _all_yrs if y >= _mx - 9]
    _yr_lab = {y: f"{y}/{str(y + 1)[-2:]}" for y in _all_yrs}
    with _c3:
        if len(_all_yrs) > 1:
            _pick = st.multiselect("Years shown", _all_yrs, default=_default_yrs, format_func=lambda y: _yr_lab[y], key="cnseas_yrs")
            _sel_yrs = sorted(_pick) if _pick else _default_yrs
        else:
            _sel_yrs = _all_yrs
    _drawn = _sel[_sel["MktYearNum"].isin(_sel_yrs)]
    _hist = _drawn[_drawn["MktYearNum"] < _mx]
    _hist_prev = _hist[_hist["MktYearNum"] == _mx - 1]     # most recent complete year
    _hist_old = _hist[_hist["MktYearNum"] < _mx - 1]
    _curr = _drawn[_drawn["MktYearNum"] == _mx]
    _curr_yr = _curr["MktYear"].iloc[0] if not _curr.empty else ""
    _prev_yr = _hist_prev["MktYear"].iloc[0] if not _hist_prev.empty else ""
    _old_years = sorted(_hist_old["MktYear"].unique())
    _hist_color = _alt.Color("MktYear:N", sort=_old_years, scale=_alt.Scale(scheme="tableau10", domain=_old_years),
                             legend=_alt.Legend(title="Mkt Year", orient="bottom", columns=6, labelFontSize=10, titleFontSize=10))
    _PREV_CLR, _AVG_CLR = "#2563eb", "#d97706"   # hero blue / amber

    # 5-yr range band + average for THIS period — the five completed crop years immediately before the CURRENT calendar marketing year.
    # OLYMPIC AVERAGE (each week's highest and lowest year dropped); the RANGE is not trimmed: lowest to highest of every year.
    _bw = 5
    _rcur_my = date.today().year if date.today().month >= 9 else date.today().year - 1
    _rwin_yrs = list(range(_rcur_my - _bw, _rcur_my))
    _nu = _bw
    _avg_lbl = f"{_nu}-yr Olympic avg" if _sband.is_trimmed(_nu) else f"{_nu}-yr avg"
    _rwin = _sel[_sel["MktYearNum"].isin(_rwin_yrs)]
    _rband = (_rwin.groupby("MktWeek")["Bid"].agg(avg=_sband.olympic_avg, lo=_sband.range_lo, hi=_sband.range_hi).reset_index())

    # Forward curve = the corridor's LATEST full rundown, each delivery month placed at its week (dashed same-colour line over the historical band).
    # One value per month (forward_month); a package bid is spread into a per-month carry that fills only the months nothing of their own names.
    _lastdate = _pv["Date"].max()
    _rfw = [{"MktWeek": _MON_WK[_fm.ABBR[_m]], "Bid": _v} for _m, _v in _fm.rail_forward(_fwd_cells.get((_mk, _lastdate), ()), _CARRY).items()]
    # Today's marketing week — periods whose week has already passed this year roll to the NEXT marketing year (a separate segment starting back at the Sep side).
    _t = date.today()
    _tmy = _t.year if _t.month >= 9 else _t.year - 1
    _twk = min(52, max(1, ((_t - date(_tmy, 9, 1)).days // 7) + 1))
    _df_rfwd = _pd.DataFrame(_rfw)
    _rfwd_cur = _rfwd_nxt = None
    if not _df_rfwd.empty:
        _df_rfwd = _df_rfwd.groupby("MktWeek", as_index=False)["Bid"].mean()
        _df_rfwd["Bid"] = _df_rfwd["Bid"].round(1)
        _rfwd_cur = _df_rfwd[_df_rfwd["MktWeek"] >= _twk].sort_values("MktWeek")
        _rfwd_nxt = _df_rfwd[_df_rfwd["MktWeek"] < _twk].sort_values("MktWeek")

    # Best-fit y-axis: clamp to the central N% of bids so outlier days don't squash the chart.
    _ryvals = list(_drawn["Bid"]) + list(_rband["lo"]) + list(_rband["hi"])
    if not _df_rfwd.empty:
        _ryvals += list(_df_rfwd["Bid"])
    _ry_scale = _yfit_scale(_ryvals, _rfit)
    # Month references on the X axis (marketing year starts Sep = week 1).
    _mlab = ("{1:'Sep',5:'Oct',10:'Nov',14:'Dec',18:'Jan',23:'Feb',27:'Mar',31:'Apr',36:'May',40:'Jun',45:'Jul',49:'Aug'}[datum.value]")
    _x = _alt.X("MktWeek:Q", title=None, scale=_alt.Scale(domain=[1, 52]),
                axis=_alt.Axis(values=[1, 5, 10, 14, 18, 23, 27, 31, 36, 40, 45, 49], labelExpr=_mlab, labelFontSize=11))
    _y = _alt.Y("Bid:Q", title="Bid (¢)", scale=_ry_scale, axis=_alt.Axis(labelFontSize=10))
    _tip = [_alt.Tooltip("MktYear:N", title="Mkt Year"), _alt.Tooltip("MktWeek:Q", title="Week"), _alt.Tooltip("Bid:Q", title="Bid (¢)")]
    _H = 560

    _wm = None
    if _LOGO.exists():
        _wm_h = int(_H * 0.50)
        _wm = (_alt.Chart(_pd.DataFrame({"MktWeek": [26.5], "url": ["data:image/png;base64," + base64.b64encode(_LOGO.read_bytes()).decode()]}))
               .mark_image(width=int(_wm_h * 0.93), height=_wm_h, opacity=0.20, align="center", baseline="middle")
               .encode(x=_alt.X("MktWeek:Q"), y=_alt.value(_H // 2), url="url:N"))

    _zero = (_alt.Chart(_pd.DataFrame({"MktWeek": [1, 52], "Bid": [0.0, 0.0]})).mark_line(color="#94a3b8", strokeDash=[4, 4], strokeWidth=1)
             .encode(x=_alt.X("MktWeek:Q"), y=_alt.Y("Bid:Q")))
    _cur_ln = _alt.Chart(_curr).mark_line(strokeWidth=4, color="#000000").encode(x=_x, y=_y, tooltip=_tip)
    _cur_lb = (_alt.Chart(_curr.nlargest(1, "MktWeek") if not _curr.empty else _curr)
               .mark_text(align="left", dx=6, fontSize=10, fontWeight="bold", color="#000000")
               .encode(x=_alt.X("MktWeek:Q"), y=_alt.Y("Bid:Q"), text="MktYear:N"))

    _layers = ([_wm] if _wm else []) + [_zero]
    # 5-yr range band (gray) area, behind everything.
    if not _rband.empty:
        _layers.append(_alt.Chart(_rband).mark_area(color="#9ca3af", opacity=0.22)
                       .encode(x=_alt.X("MktWeek:Q"), y=_alt.Y("lo:Q", title="Bid (¢)", scale=_ry_scale), y2="hi:Q"))
    # Older marketing years — faded thin context lines behind the heroes.
    if not _hist_old.empty:
        _layers.append(_alt.Chart(_hist_old).mark_line(strokeWidth=1.3, opacity=0.45).encode(x=_x, y=_y, color=_hist_color, tooltip=_tip))
    # Most recent COMPLETE year — HERO blue, thick, with an end-label.
    if not _hist_prev.empty:
        _layers.append(_alt.Chart(_hist_prev).mark_line(strokeWidth=4, color=_PREV_CLR).encode(x=_x, y=_y, tooltip=_tip))
        _layers.append(_alt.Chart(_hist_prev.nlargest(1, "MktWeek")).mark_text(align="left", dx=6, fontSize=10, fontWeight="bold", color=_PREV_CLR)
                       .encode(x=_alt.X("MktWeek:Q"), y=_alt.Y("Bid:Q"), text="MktYear:N"))
    # 5-yr average — HERO amber, bold heavy-dash, drawn OVER the year lines.
    if not _rband.empty:
        _layers.append(_alt.Chart(_rband).mark_line(color=_AVG_CLR, strokeDash=[8, 4], strokeWidth=3)
                       .encode(x=_alt.X("MktWeek:Q"), y=_alt.Y("avg:Q", scale=_ry_scale)))
        _r_avg_end = _rband.nlargest(1, "MktWeek").assign(_lbl=_avg_lbl)
        _layers.append(_alt.Chart(_r_avg_end).mark_text(align="left", dx=6, fontSize=10, fontWeight="bold", color=_AVG_CLR)
                       .encode(x=_alt.X("MktWeek:Q"), y=_alt.Y("avg:Q", scale=_ry_scale), text="_lbl:N"))
    # Forward curve — dashed black line of the latest rundown; the next-marketing-year stretch is its own segment so it never draws a line back across the chart.
    _rfwd_tip = [_alt.Tooltip("MktWeek:Q", title="Week"), _alt.Tooltip("Bid:Q", title="Fwd bid (¢)", format=".0f")]
    for _seg in (_rfwd_cur, _rfwd_nxt):
        if _seg is not None and not _seg.empty:
            _layers += [_alt.Chart(_seg).mark_line(strokeWidth=2, color="#000000", strokeDash=[6, 4]).encode(x=_x, y=_y),
                        _alt.Chart(_seg).mark_point(filled=True, color="#000000", size=34).encode(x=_x, y=_y, tooltip=_rfwd_tip)]
    # Current year — thickest black line, drawn OVER everything.
    _layers += [_cur_ln, _cur_lb]
    _fut = _pd.DataFrame([{"MktWeek": 13, "code": "Z"}, {"MktWeek": 27, "code": "H"}, {"MktWeek": 35, "code": "K"}, {"MktWeek": 44, "code": "N"}])
    _layers = [_alt.Chart(_fut).mark_rule(color="#cbd5e1", strokeWidth=1.5).encode(x="MktWeek:Q"),
               _alt.Chart(_fut).mark_text(fontSize=12, color="#94a3b8", fontWeight="bold", align="center", baseline="top")
               .encode(x=_alt.X("MktWeek:Q"), y=_alt.value(6), text="code:N")] + _layers

    _comm = _pv["Commodity"].iloc[0] if not _pv.empty else "Corn"
    _rail_title = f"{_mk} · {_pd_sel} · {_comm}"
    st.markdown(
        '<div style="margin-top:8px;margin-bottom:2px;font-size:14px;color:#1e293b;font-weight:800;letter-spacing:.01em">' + _rail_title + '</div>'
        '<div style="margin-bottom:4px;font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.1em">'
        'Seasonal Bid — Marketing Year (Sep–Aug)'
        + '&nbsp;&nbsp;<span style="font-weight:400;text-transform:none">'
        + (f'<b style="color:#000">{_curr_yr} = black</b>' if _curr_yr else '')
        + (f'  ·  <b style="color:#2563eb">{_prev_yr} = blue</b>' if _prev_yr else '')
        + (f'  ·  <b style="color:#d97706">{_avg_lbl} = amber dash</b>' if not _rband.empty else '')
        + '</span></div>', unsafe_allow_html=True)
    _rail_chart = _alt.layer(*_layers).properties(height=_H, padding=_CHART_PAD)
    st.altair_chart(_rail_chart, use_container_width=True)
    _rail_fname = f"cn_seasonal_{_mk}_{_pd_sel}.png".replace(" ", "_").replace("/", "-").replace(",", "").replace("'", "")
    _rail_export = _rail_chart.properties(title=_alt.TitleParams(_rail_title, subtitle="Seasonal Bid — Marketing Year (Sep–Aug)", fontSize=15, fontWeight="bold",
                                                               color="#1e293b", subtitleFontSize=11, subtitleColor="#64748b", anchor="start", offset=12))
    _png = _chart_png(_rail_export, width=1100, height=_H)
    if _png is None:
        st.caption("PNG export unavailable")
    else:
        _d1, _ = st.columns([1, 4])
        _d1.download_button("⬇️  PNG", _png, file_name=_rail_fname, mime="image/png", key=f"dl_cnseas_{_mk}_{_pd_sel}", use_container_width=True)
    if _sband.is_trimmed(_nu):
        _band_txt = (f"the {_nu}-yr average is Olympic (each week's highest and lowest year are dropped; a week with fewer than five years uses them all) and the gray band is the true range: "
                     f"each week's lowest to highest of the last {_nu} completed crop years ({', '.join(f'{y}/{(y + 1) % 100:02d}' for y in _rwin_yrs)}).")
    else:
        _band_txt = "no completed crop year has enough weekly bids yet for an average and a gray band."
    st.caption(f"{int(_p_n[_pd_sel])} postings · weekly average where a period was posted more than once · partial windows fold into their month "
               f"(FH/LH/Split Oct, Oct 10-31, LH Oct/FH Nov → Oct) · a package bid (JFM, AMJJ ...) is spread across its months with a {_CARRY:g}¢ a month carry on the forward curve · "
               + _band_txt + " Source: the Basis Tracker's rail archive.")
