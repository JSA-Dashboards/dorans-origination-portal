"""IL Production tab: the DuMond (New York) dashboard's NASS Production tab, for Illinois.

Same flow: crop / year / state drill-down / refresh, Metric, View (current year or change vs prior year / 3-year average / a chosen year), KPI row,
ASD District or County map with the competition toggle, district table, then the history section (State / ASD / County, bar chart, heat-map tables
with district expanders, detail table), county ranking and county data table. 2026 has no county survey yet, so it is a forecast with a yield box.
Withheld counties are filled the NASS / RMA dashboard's way (production.py).
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import il_figs as nf
import production as P
import territory_tab

HERE = Path(__file__).parent
STATS = ("production", "harvested", "yield")
STAT_LABEL = {"production": "Production (bu)", "harvested": "Harvested Acres", "yield": "Yield (bu/ac)"}
UNIT = {"Production (bu)": ("M bu", 1e6, ".1f"), "Harvested Acres": ("M ac", 1e6, ".2f"), "Yield (bu/ac)": ("bu/ac", 1, ".1f")}


@st.cache_resource
def _data():
    return P.load_prod(), nf.load_geo()


@st.cache_resource
def _competition():
    comp = json.loads((HERE / "data" / "competitors.json").read_text(encoding="utf-8"))["rows"]
    plants = json.loads((HERE / "data" / "il_plants.json").read_text(encoding="utf-8"))
    return comp, plants


def _fmt_val(metric: str, v) -> str:
    if v is None:
        return "—"
    if metric == "Yield (bu/ac)":
        return f"{v:,.1f} bu/ac"
    if metric == "Production (bu)":
        return f"{v / 1e6:,.1f} M bu"
    return f"{v / 1e6:,.2f} M ac"


def _hist_fmt(s: str, v) -> str:
    return _fmt_val(STAT_LABEL[s], v)


def _label(txt: str) -> None:
    st.markdown(f"<p style='color:#5f7267;font-size:0.78rem;margin:4px 0 2px 0;'>{txt}</p>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _history(crop: str, key: str, fill: bool, fc_yield, years: tuple):
    """Per-year values for every scope: state, district and county (with which county cells were filled in)."""
    prod, geo = _data()
    state, asd, cty, est, names, asd_names = {}, {}, {}, {}, {}, {}
    for y in years:
        cvals, dvals, e, crow, drow = P.entity_values(prod, geo, crop, y, key, fill, fc_yield)
        state[y] = P.state_total(prod, geo, crop, y, key, fill, fc_yield)
        for d, v in dvals.items():
            asd.setdefault(d, {})[y] = v
            asd_names[d] = drow[d]["asd"]
        for f, v in cvals.items():
            cty.setdefault(f, {})[y] = v
            est.setdefault(f, {})[y] = e[f]
            names[f] = (crow[f]["county"], crow[f]["asd"], crow[f]["asd_code"])
    return state, asd, cty, est, names, asd_names


def render() -> None:
    prod, geo = _data()
    if not prod:
        st.info("No production snapshot yet (data/il_county_prod.json). Run build_il_production.py.")
        return

    c1, c2, c3, c4 = st.columns([1, 0.9, 1.6, 0.55])
    crop = c1.selectbox("Crop", P.CROPS, key="il_crop")
    done = P.years_of(prod, crop)
    est_year = P.estimate_year(prod, crop)
    year_opts = ([f"{est_year} (forecast)"] if est_year else []) + [str(y) for y in reversed(done)]
    ysel = c2.selectbox("Year", year_opts, index=1 if est_year else 0, key="il_year")
    year = int(ysel.split()[0])
    c3.selectbox("State Drill-Down", ["IL  —  Illinois"], key="il_state", disabled=True)
    with c4:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("Refresh", use_container_width=True, key="il_refresh"):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()

    with st.expander("Adjustments", expanded=False):
        fill = st.checkbox("Fill withheld counties", True, key="il_fill",
                           help="NASS withholds some counties' figures (Illinois corn 2025: published counties hold 63% of the state). On: what the "
                                "published counties leave of NASS's official Illinois total is spread over the withheld counties by their share in the "
                                "earlier years (up to three back), so the state adds up to NASS's total and no published figure is changed. Same method "
                                "as the NASS / RMA dashboard's heat map. Off: published counties only.")
        st.caption("Estimated counties are marked Est / E / * on the map and tables.")

    _label("Metric")
    metric = st.radio("Metric", list(P.METRICS), horizontal=True, key="il_metric", label_visibility="collapsed")
    _label("View")
    change = st.radio("Change View", P.CHANGE_OPTS, horizontal=True, key="il_change", label_visibility="collapsed")
    comp_year = None
    if change == "vs Selected Year":
        cc, _ = st.columns([0.55, 2.6])
        comp_year = cc.selectbox("Compare to Year", [y for y in done if y != year], key="il_comp_year")
    key = P.METRICS[metric]

    is_fc = year == est_year
    fc_yield = None
    if is_fc:
        fc_yield = _forecast_block(prod, crop, year)

    # ── KPI row ──
    cdf, ddf = P.view_frames(prod, geo, crop, key, year, change, comp_year, fill, fc_yield)
    state_val = P.state_total(prod, geo, crop, year, key, fill, fc_yield)
    _, info = P.year_values(prod, crop, year, fill, fc_yield)
    pub = info["published"].get("production")
    n_pub = int((~cdf["is_estimated"]).sum())
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"{year} {metric}", _fmt_val(metric, state_val))
    if change == "Current Year":
        if is_fc:
            k2.metric("County Coverage", "Forecast", help=f"County data not yet published for {year}")
            k3.metric("Counties Reporting", "—")
        else:
            k2.metric("County Coverage", f"{(pub or 0) * 100:.0f}%", help="Share of NASS's official Illinois production that sits in counties NASS published.")
            k3.metric("Counties Reporting", f"{n_pub:,}", help=f"of {len(cdf)} Illinois counties; the rest are filled in" if fill else f"of {len(cdf)} Illinois counties")
        k4.metric("ASD Districts", f"{len(ddf)}")
    else:
        vals = cdf["Value"].dropna()
        k2.metric("County Coverage", "Forecast" if is_fc else f"{(pub or 0) * 100:.0f}%")
        k3.metric("Counties Above Prior", f"{int((vals > 0).sum()):,} ▲")
        k4.metric("Counties Below Prior", f"{int((vals < 0).sum()):,} ▼")

    # ── radius: how much sits near Dorans ──
    if key in P.SUM_MEASURES:
        rows = P.county_rows(prod, geo, crop, [year], fill, fc_yield)
        r1, r2 = st.columns([1.2, 2.8])
        radius = r1.slider("Miles from Dorans", 25, 250, 100, 25, key="il_radius")
        w = P.within(rows, radius, key)
        r2.metric(f"{metric} within {radius} miles ({w['counties']} counties)", _fmt_val(metric, w["total"]),
                  f"{w['total'] / state_val * 100:.0f}% of Illinois" if state_val else None, delta_color="off")

    # ── map ──
    mv1, mv2, mv3 = st.columns([1, 1.9, 1.5])
    mv1.radio("Map View", ["ASD District", "County", "Draw Territory"], horizontal=True, key="il_map_view")
    map_view = st.session_state["il_map_view"]
    comp_rows, plants = _competition()
    with mv2:
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        show_comp = st.checkbox("Show competition on the map (named, ≤30 mi elevators, candidates)", key="il_comp")
    with mv3:
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        show_pl = st.checkbox("Show soy crush plants" if crop == "Soybeans" else "Show ethanol plants", True, key="il_plants")
    cr = comp_rows if show_comp else None
    pl = plants if show_pl else None
    ex1, ex2, _ = st.columns([1.1, 1.6, 1.8])
    zoom = ex1.radio("Map extent", ["Illinois", "Dorans area"], horizontal=True, key="il_extent")
    extent = None
    if zoom == "Dorans area":
        radius = ex2.slider("Zoom radius (miles)", 25, 120, 60, 5, key="il_zoom_r")
        extent = (nf.DORANS["lat"], nf.DORANS["lon"], radius)

    if map_view == "ASD District":
        est_d = set(ddf.loc[ddf["est"] > 0, "District"])
        fig = nf.district_fig(ddf, ddf, geo, crop, year, metric, change, est_d, cr, pl, forecast=is_fc, extent=extent)
        if fig is None:
            st.info("ASD district map not available for this selection.")
        else:
            fig.update_layout(dragmode=False)
            st.plotly_chart(fig, use_container_width=True, key="il_district_map", config={"scrollZoom": False, "displayModeBar": False, "doubleClick": False})
        if not ddf.empty:
            ratio = key == "yield"
            raw = ddf.sort_values("DistrictCode").reset_index(drop=True)
            tot = state_val
            t = pd.DataFrame({"District": raw["District"], "ASD": raw["DistrictCode"], metric: [_fmt_val(metric, v) for v in raw["Raw"]],
                              "% of State": ["—" if ratio or not tot else f"{v / tot * 100:.1f}" for v in raw["Raw"]]})
            if raw["est"].sum():
                t["Est. Counties"] = raw["est"].map(lambda n: str(int(n)) if n else "—")
            if change != "Current Year":
                t[change] = [f"{v:+.1f}%" if v is not None and not pd.isna(v) else "—" for v in raw["Value"]]
            st.markdown(f"<p style='color:#5f7267;font-size:0.82rem;font-weight:600;margin:6px 0 4px 0;'>Illinois {year} {crop} — by ASD district</p>",
                        unsafe_allow_html=True)
            tc, kc = st.columns([2.4, 1])
            tc.dataframe(t, use_container_width=True, hide_index=True)
            with kc:
                m1, m2 = st.columns(2)
                m1.metric("State Avg" if ratio else "State Total", _fmt_val(metric, tot))
                m2.metric("Districts", f"{len(t)}")
                if raw["est"].sum():
                    st.caption("Est = some counties not published by NASS. Each is filled with its usual share of what the published counties leave "
                               "of NASS's official Illinois total, so the districts add up to the state." if not is_fc else
                               "Forecast: every county is USDA's state estimate times its 3-year share.")
    elif map_view == "Draw Territory":
        st.session_state["_il_geo"] = geo
        territory_tab.render(crop, year, key, cdf, comp_rows, plants, extent, is_fc)
    else:
        fig = nf.county_fig(cdf, geo, crop, year, metric, change, cr, pl, forecast=is_fc, extent=extent)
        if fig is None:
            st.info("County map not available for this selection.")
        else:
            fig.update_layout(dragmode=False)
            st.plotly_chart(fig, use_container_width=True, key="il_county_map", config={"scrollZoom": False, "displayModeBar": False, "doubleClick": False})
            n_est = int(cdf["is_estimated"].sum())
            if is_fc:
                st.caption(f"{year} forecast: NASS has no {year} county data until January, so each county = USDA's {year} Illinois estimate times the "
                           f"county's average share of the state over {year - 3}-{year - 1}. Counties add up to the state forecast; it is not county data.")
            elif n_est:
                st.caption(f"* = {n_est} counties not published by NASS, filled with their usual share of the state's remainder (adds up to NASS's state total).")

    st.markdown("<hr style='border-color:#d7e2dc;margin:8px 0'>", unsafe_allow_html=True)
    _history_section(prod, geo, crop, year, metric, key, change, comp_year, fill, fc_yield, is_fc, done, cdf, map_view)


def _forecast_block(prod: dict, crop: str, year: int):
    """The yield box for a year with no county survey: USDA's implied state yield is the default; type your own to rerun the allocation."""
    st_ = prod["_state"][crop][str(year)]
    usda = st_["production"] / st_["harvested"] if st_.get("harvested") else None
    ly_s = prod["_state"][crop].get(str(year - 1), {})
    ly = ly_s["production"] / ly_s["harvested"] if ly_s.get("harvested") else None
    k = f"il_fc_yield_{crop}"
    if k not in st.session_state:
        st.session_state[k] = round(float(usda or ly or 0.0), 1)
    st.info(f"**{year} Forecast** — USDA's latest {crop.lower()} estimate for Illinois is **{usda:.1f} bu/ac** on {st_['harvested'] / 1e6:.2f} M harvested acres"
            + (f" (last year {ly:.1f})" if ly else "") + "; it is the default below. Change it to run your own estimate: Illinois production = your yield x "
            "USDA's harvested acres, split across districts and counties by their 3-year shares.")
    f1, f2, _ = st.columns([1.2, 1.4, 2.4])
    y_in = f1.number_input(f"{crop} Yield Est. (bu/ac)", min_value=0.0, max_value=500.0, step=0.5, format="%.1f", key=k)
    with f2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if usda and abs(y_in - usda) > 0.05:
            st.button(f"Reset to USDA ({usda:.1f})", key=f"il_fc_reset_{crop}", on_click=lambda: st.session_state.__setitem__(k, round(float(usda), 1)))
    return y_in if usda and abs(y_in - usda) > 0.05 else None        # None = USDA's own number


def _history_section(prod, geo, crop, year, metric, key, change, comp_year, fill, fc_yield, is_fc, done, cdf, map_view) -> None:
    unit_lbl, div, fmt = UNIT[metric]
    ratio = key == "yield"
    all_years = [y for y in sorted(done) + ([year] if is_fc else []) if y <= year]
    h1, h2 = st.columns([1.4, 2.6])
    scope = h1.radio("View", ["State", "ASD District", "County"], horizontal=True, key="il_scope")
    state, asd, cty, est, names, asd_names = _history(crop, key, fill, fc_yield, tuple(all_years))
    dist = county = None
    with h2:
        if scope == "ASD District":
            dist = st.selectbox("District", sorted(asd_names, key=lambda c: asd_names[c]), format_func=lambda c: f"{asd_names[c]} ({c})", key="il_hist_district")
            label = f"Illinois — {asd_names[dist]}"
        elif scope == "County":
            order = sorted(names, key=lambda f: names[f][0])
            sel = st.selectbox("County", order, format_func=lambda f: names[f][0], index=order.index("17029") if "17029" in order else 0, key="il_hist_county")
            county = sel
            label = f"Illinois — {names[sel][0]} County"
        else:
            label = "Illinois"

    def series(s_key: str):
        _s, _a, _c, *_ = _history(crop, s_key, fill, fc_yield, tuple(all_years))
        src = _s if scope == "State" else _a.get(dist, {}) if scope == "ASD District" else _c.get(county, {})
        return {y: (src.get(y) if isinstance(src, dict) else None) for y in all_years}

    n_chart = st.radio("Chart history (years)", [5, 10], horizontal=True, key="il_chart_yrs", index=1)
    yrs = all_years[-n_chart:]
    cur = series(key)
    vals = [cur.get(y) for y in yrs]
    mx = max((v for v in vals if v), default=0)
    unit, ylab = (nf.auto_bu(mx) if key == "production" else nf.auto_ac(mx) if key == "harvested" else (1, "bu/ac"))
    st.plotly_chart(nf.history_bar({metric: [v / unit if v else 0 for v in vals]}, yrs, f"{label} — {crop} {metric}", ylab),
                    use_container_width=True, key="il_hist_chart", config={"displayModeBar": False})
    st.markdown("<hr style='border-color:#d7e2dc;margin:8px 0'>", unsafe_allow_html=True)

    n_tbl = st.radio("Table history (years)", [5, 10], horizontal=True, key="il_tbl_yrs", index=0)
    hyears = all_years[-n_tbl:]
    st.markdown(f"<p style='color:#5f7267;font-size:0.82rem;font-weight:600;margin:0 0 6px 0;letter-spacing:0.04em;'>📅 HISTORICAL SUMMARY — {label} | "
                f"{hyears[0]}–{hyears[-1]}</p>", unsafe_allow_html=True)
    title_tail = f"({unit_lbl}) | {hyears[0]}–{hyears[-1]}"
    if scope == "State":
        fig = nf.heatmap_table({"Illinois": {y: state.get(y) for y in hyears}}, hyears, f"{crop} — {metric} {title_tail}", unit_lbl, div, ratio, fmt=fmt,
                               first_col="State", cell_status={"Illinois": {y: is_fc and y == year for y in hyears}})
        st.plotly_chart(fig, use_container_width=True, key="il_heatmap", config={"displayModeBar": False})
    elif scope == "ASD District":
        rows = {asd_names[d]: {y: asd[d].get(y) for y in hyears} for d in sorted(asd, key=lambda c: asd_names[c])}
        status = {asd_names[d]: {y: any(est[f].get(y) for f in names if names[f][2] == d) for y in hyears} for d in asd}
        tot = {y: state.get(y) for y in hyears}
        fig = nf.heatmap_table(rows, hyears, f"Illinois {crop} — {metric} by ASD District {title_tail}", unit_lbl, div, ratio, total=None if ratio else tot,
                               fmt=fmt, cell_status=status, total_label="IL Total", first_col="District")
        st.plotly_chart(fig, use_container_width=True, key="il_heatmap", config={"displayModeBar": False})
        st.caption("▼ Expand any district below to view county detail  ·  Top 2 = green  ·  Bottom 2 = red per row  ·  E = estimated  ·  "
                   "Olympic Avg drops single highest and lowest year.")
        for d in sorted(asd, key=lambda c: asd_names[c]):
            members = [f for f in names if names[f][2] == d]
            with st.expander(f"▼  {asd_names[d]}  —  {len(members)} counties", expanded=False):
                cd = {names[f][0]: {y: cty[f].get(y) for y in hyears} for f in sorted(members, key=lambda f: names[f][0])}
                cs = {names[f][0]: {y: est[f].get(y, False) for y in hyears} for f in members}
                cfig = nf.heatmap_table(cd, hyears, f"{asd_names[d]} — County Detail ({unit_lbl})", unit_lbl, div, ratio, fmt=fmt,
                                        top_row={y: asd[d].get(y) for y in hyears}, top_row_label=f"{asd_names[d]} District Total", cell_status=cs,
                                        top_row_cell_status={y: any(cs[n].get(y) for n in cs) for y in hyears}, first_col="County")
                st.plotly_chart(cfig, use_container_width=True, key=f"il_cty_tbl_{d}", config={"displayModeBar": False})
    else:
        rows = {names[f][0]: {y: cty[f].get(y) for y in hyears} for f in sorted(names, key=lambda f: names[f][0])}
        cs = {names[f][0]: {y: est[f].get(y, False) for y in hyears} for f in names}
        fig = nf.heatmap_table(rows, hyears, f"Illinois {crop} — {metric} by County {title_tail}", unit_lbl, div, ratio, fmt=fmt, cell_status=cs,
                               total={y: state.get(y) for y in hyears} if not ratio else None, total_label="IL Total", first_col="County")
        st.plotly_chart(fig, use_container_width=True, key="il_heatmap", config={"displayModeBar": False})
    if scope != "ASD District":
        st.caption("Top 2 = green  ·  Bottom 2 = red per row  ·  E = estimated  ·  Olympic Avg drops single highest and lowest year.")

    # ── detail expander ──
    hist = {y: {s: series(s).get(y) for s in STATS} for y in hyears}
    with st.expander(f"📋 {label} Detail — {metric} ({hyears[0]}–{hyears[-1]})", expanded=False):
        delta = {y: {} for y in hyears}
        if change == "vs Prior Year":
            for i, y in enumerate(hyears[1:], 1):
                for s in STATS:
                    c, p = hist[y].get(s), hist[hyears[i - 1]].get(s)
                    delta[y][s] = (c - p) / abs(p) * 100 if c and p else None
        elif change == "vs 3-Yr Avg":
            for s in STATS:
                base = [hist[y].get(s) for y in (year - 3, year - 2, year - 1) if hist.get(y, {}).get(s)]
                avg = sum(base) / len(base) if base else None
                for y in hyears:
                    c = hist[y].get(s)
                    delta[y][s] = (c - avg) / abs(avg) * 100 if c and avg else None
        elif change == "vs Selected Year" and comp_year in hist:
            for y in hyears:
                for s in STATS:
                    c, b = hist[y].get(s), hist[comp_year].get(s)
                    delta[y][s] = (c - b) / abs(b) * 100 if c and b and y != comp_year else None
        tbl = []
        for s in STATS:
            row = {"": STAT_LABEL[s]}
            for y in hyears:
                dv = delta[y].get(s)
                dtxt = f" ({'+' if dv >= 0 else ''}{dv:.1f}%)" if dv is not None and change != "Current Year" else ""
                row[str(y)] = f"{_hist_fmt(s, hist[y].get(s))}{dtxt}"
            tbl.append(row)
        df = pd.DataFrame(tbl).set_index("")
        if is_fc:
            df = df.rename(columns={str(year): f"{year} (Est)"})
        st.dataframe(df, use_container_width=True)
        if is_fc:
            st.caption("Est = forecast from USDA's state estimate and each county's 3-year share.")

    st.markdown("<hr style='border-color:#d7e2dc;margin:8px 0'>", unsafe_allow_html=True)

    # ── county ranking + table ──
    if not cdf.empty:
        st.plotly_chart(nf.ranking_chart(cdf, crop, year, metric, change, by_district=map_view == "ASD District"), use_container_width=True, key="il_ranking")
        with st.expander("County Data Table — Illinois", expanded=False):
            t = cdf.dropna(subset=["Value"]).sort_values("Value", ascending=False)
            col = f"% Change ({metric})" if change != "Current Year" else metric
            st.dataframe(pd.DataFrame({"County": t["County"], "District": t["District"],
                                       col: [f"{v:+.1f}%" if change != "Current Year" else _fmt_val(metric, v) for v in t["Value"]],
                                       "Estimated": ["Est" if e else "" for e in t["is_estimated"]]}), use_container_width=True, hide_index=True)
