"""CN seasonal charts: one line per year across Jan-Dec, from USDA AMS's monthly CN series (Gibson City -> Reserve, large car, 105+ cars)
and, once the archive has accumulated them, the CN 105s bids by posting date.

The USDA series is the only multi-year CN history there is (Nov 2023 on): CN's tariff peaks in October and steps down in November, and its
fuel surcharge follows diesel two months back. Dorans' own delivered-to-Gulf freight is the same moves applied to its tariff rate and miles.
"""
import calendar

import freight_data as FD
import cn_miles as CM

MONTHS = [calendar.month_abbr[m] for m in range(1, 13)]


def series_by_year(metric: str) -> dict:
    """{year: [value or None for Jan..Dec]} for 'Railroad' | 'Private' | 'fsc_per_mile' from the USDA CN series."""
    out = {}
    for ym, row in FD.cn_usda_series().items():
        y, m = int(ym[:4]), int(ym[5:])
        v = row.get(metric)
        if v is not None:
            out.setdefault(y, [None] * 12)[m - 1] = float(v)
    return dict(sorted(out.items()))


def dorans_freight_by_year(commodity="Corn", size="Large", source="Railroad", tier="25-49 cars", origin=("DORANS", "IL")) -> dict:
    """{year: [cents/bu per month]}: Dorans' tariff rate moved by that month's USDA level change, plus the month's CN surcharge on its miles."""
    field = FD.CN_RATE_FIELD[(size, source)]
    row = next((r for r in FD.load_cn() if (r["origin"], r["state"]) == origin and r["tier"] == tier), None)
    miles = CM.miles_to_gulf(*origin)[0]
    if row is None:
        return {}
    seed = FD.cn_seed_level()
    out = {}
    for ym, u in FD.cn_usda_series().items():
        y, m = int(ym[:4]), int(ym[5:])
        extra = u["Railroad"] - seed + (u.get("fsc_per_mile") or 0) * (miles or 0)
        out.setdefault(y, [None] * 12)[m - 1] = FD.cn_freight_cpb(row[field], size, commodity, extra)
    return dict(sorted(out.items()))


def tier_spread_by_year(commodity="Corn", size="Large", source="Railroad", small=("DORANS", "IL", "25-49 cars"), big=("CHAMPAIGN", "IL", "105+ cars")) -> dict:
    """{year: {"small": [¢/bu per month], "big": [...], "spread": [...]}}: freight from Dorans on its 25-49 car tariff against Champaign on the 105+ car
    tariff, month by month (each month's USDA tariff level and CN fuel surcharge on each one's estimated miles)."""
    field = FD.CN_RATE_FIELD[(size, source)]
    rows = FD.load_cn()
    pick = lambda o: next((r for r in rows if (r["origin"], r["state"], r["tier"]) == o), None)
    rs, rb = pick(small), pick(big)
    if rs is None or rb is None:
        return {}
    ms, mb = CM.miles_to_gulf(small[0], small[1])[0], CM.miles_to_gulf(big[0], big[1])[0]
    seed = FD.cn_seed_level()
    out = {}
    for ym, u in FD.cn_usda_series().items():
        y, m = int(ym[:4]), int(ym[5:])
        up, fsc = u["Railroad"] - seed, u.get("fsc_per_mile") or 0
        a = FD.cn_freight_cpb(rs[field], size, commodity, up + fsc * (ms or 0))
        b = FD.cn_freight_cpb(rb[field], size, commodity, up + fsc * (mb or 0))
        d = out.setdefault(y, {k: [None] * 12 for k in ("small", "big", "spread")})
        d["small"][m - 1], d["big"][m - 1], d["spread"][m - 1] = a, b, a - b
    return dict(sorted(out.items()))


def bid_history(all_rows, market: str) -> dict:
    """{period: [(date, bid)]} for a CN bid market from the rail archive, oldest first."""
    out = {}
    for r in sorted((r for r in all_rows if r["market"] == market and r.get("bid") is not None), key=lambda r: r["date"]):
        out.setdefault(r["period"], []).append((r["date"], r["bid"]))
    return out


def render() -> None:
    import plotly.graph_objects as go
    import streamlit as st
    import rail_data as RD
    import rail_seasonals

    st.markdown("##### CN basis seasonals")
    if RD.configured():
        try:
            rail_seasonals.render(_cached_bids())
        except Exception as e:
            st.info(f"Couldn't read the Basis Tracker's rail archive: {e}")
    else:
        st.info("The Basis Tracker's rail archive isn't connected here yet, so the CN basis seasonals can't be drawn.")
    st.markdown("---")
    st.markdown("##### CN freight and tariff")

    def lines(data, title, unit, fmt="%{y:,.1f}"):
        fig = go.Figure()
        palette = ["#9aa5b1", "#6b9fd0", "#0693e3", "#32373c"]
        for i, (y, vals) in enumerate(data.items()):
            last = i == len(data) - 1
            fig.add_trace(go.Scatter(x=MONTHS, y=vals, name=str(y), mode="lines+markers", connectgaps=False,
                                     line=dict(width=3 if last else 1.8, color=palette[min(i + max(0, 4 - len(data)), 3)]),
                                     hovertemplate=f"{y} %{{x}}: {fmt} {unit}<extra></extra>"))
        fig.update_layout(title=dict(text=title, font=dict(size=14)), height=330, margin=dict(l=0, r=0, t=40, b=0),
                          paper_bgcolor="#fff", plot_bgcolor="#fff", yaxis=dict(title=unit, gridcolor="#e2e8f0"),
                          legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    commodity = c1.radio("Commodity", FD.CN_COMMODITIES, horizontal=True, key="seas_commodity")
    size = c2.radio("Car size", list(FD.CN_SIZES), index=1, horizontal=True, key="seas_size")
    source = c3.radio("Car source", list(FD.CN_SOURCES), horizontal=True, key="seas_source")

    a, b = st.columns(2)
    with a:
        lines(series_by_year("Railroad" if source == "Railroad" else "Private"),
              f"CN tariff, Gibson City → Reserve ({source.lower()} car, 105+)", "$/car", "%{y:,.0f}")
    with b:
        lines(series_by_year("fsc_per_mile"), "CN fuel surcharge", "$/car-mile", "%{y:.3f}")
    lines(dorans_freight_by_year(commodity, size, source), f"Dorans → Gulf freight, {commodity.lower()} (25-49 car tier, tariff + fuel)", "¢/bu")
    ts = tier_spread_by_year(commodity, size, source)
    if ts:
        st.markdown("##### Freight spread: 25-49 car tariff vs 105+ cars")
        latest = max(ts)
        d = ts[latest]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=MONTHS, y=d["spread"], name="Spread (25-49 less 105+)", marker_color="#f59e0b", opacity=0.55,
                             hovertemplate="%{x}: %{y:.1f}¢ more for the small block<extra></extra>"))
        fig.add_trace(go.Scatter(x=MONTHS, y=d["small"], name="Dorans, 25-49 cars", mode="lines+markers", line=dict(color="#0693e3", width=3)))
        fig.add_trace(go.Scatter(x=MONTHS, y=d["big"], name="Champaign, 105+ cars", mode="lines+markers", line=dict(color="#32373c", width=3)))
        fig.update_layout(title=dict(text=f"{latest}: freight to the Gulf, ¢/bu ({commodity.lower()}, {size.lower()} {source.lower()} car)", font=dict(size=14)),
                          height=340, margin=dict(l=0, r=0, t=40, b=0), paper_bgcolor="#fff", plot_bgcolor="#fff", yaxis=dict(title="¢/bu", gridcolor="#e2e8f0"),
                          legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, use_container_width=True)
        lines({y: v["spread"] for y, v in ts.items()}, "Spread by year: what loading under 105 cars costs, ¢/bu", "¢/bu")
        vals = [v for v in d["spread"] if v is not None]
        st.caption(f"Dorans only has a 25-49 car tariff rate; Champaign is the 105+ shuttle point the CN 105s bids are FOB. The spread is the tariff difference plus "
                   f"the fuel surcharge on Dorans' extra rail miles, so it moves with the surcharge: {min(vals):.1f}¢ to {max(vals):.1f}¢ across {latest}.")
    st.caption("USDA AMS AgTransport, CN's monthly series from Nov 2023 (snapshot 2026-10-28). October is the seasonal peak and November steps down "
               "(−$220 in 2024, −$330 in 2025). Dorans' line applies each month's change in the USDA tariff level to its own rate and adds the "
               "month's surcharge on its estimated rail miles; USDA lists no other CN origin, so that move is assumed for Dorans too.")

    import rail_data as RD
    if RD.configured():
        try:
            import streamlit as st2
            hist = bid_history(_cached_bids(), "CN 105s" if commodity == "Corn" else "CN 105s Beans")
        except Exception as e:
            st.caption(f"CN bid history unavailable: {e}")
            return
        if hist:
            st.markdown(f"##### CN 105s {commodity.lower()} bids by posting date")
            fig = go.Figure()
            for p, pts in hist.items():
                fig.add_trace(go.Scatter(x=[d for d, _ in pts], y=[v for _, v in pts], name=p, mode="lines+markers"))
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="#fff", plot_bgcolor="#fff",
                              yaxis=dict(title="¢/bu vs futures", gridcolor="#e2e8f0"))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("The archive only holds these forward bids since Aug 2026, so this fills in as the season goes; a true bid seasonal needs a year of history.")


def _cached_bids():
    import cn_sheet
    return cn_sheet._cached_bids()
