"""Illinois corn and soybean production for the Dorans origination area: county and NASS-district (ASD) level.

Data is a NASS QuickStats snapshot (build_il_production.py -> data/il_county_prod.json); nothing here calls NASS live.
Pure functions up top (tested), Streamlit drawing at the bottom.
"""
import json
import math
from pathlib import Path

DATA = Path(__file__).parent / "data"
MATTOON = (39.5511, -88.3445)            # Dorans, Coles County (Mattoon is 5 miles south): the reference point for miles
CROPS = ("Corn", "Soybeans")
MEASURES = {"Production": ("production", "bu"), "Harvested acres": ("harvested", "ac"), "Yield": ("yield", "bu/ac")}
SUM_MEASURES = ("production", "harvested")


def haversine_miles(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def load_prod() -> dict:
    return json.loads((DATA / "il_county_prod.json").read_text(encoding="utf-8"))


def load_geo() -> dict:
    return json.loads((DATA / "il_county_geo.json").read_text(encoding="utf-8"))


def years_of(prod: dict, crop: str) -> list:
    """Completed years with county data (the in-season current year has no county survey until January)."""
    return sorted({int(y) for c in prod.get(crop, {}).values() for y in c["years"]})


def estimate_year(prod: dict, crop: str):
    """The in-season year USDA has a state estimate for but no county survey yet (2026 until January), else None."""
    have = set(years_of(prod, crop))
    later = [int(y) for y in prod.get("_state", {}).get(crop, {}) if int(y) > max(have)]
    return max(later) if later else None


LOOKBACK = 3          # earlier years consulted for a withheld county's usual share of its state (as in the NASS / RMA dashboard's heat map)
MIN_GAP = 0.005       # published counties within 0.5% of the official state total count as complete


def year_values(prod: dict, crop: str, year: int, fill: bool = True) -> tuple:
    """{fips: {production, harvested, est}} for one year, made to add up to NASS's official Illinois totals the way the NASS / RMA dashboard's
    heat map does (heat_map.fill_withheld): the counties NASS published keep their published numbers; what they leave of the state total is
    spread over the withheld counties in proportion to the share each held of the state in the latest earlier year (up to LOOKBACK back)
    NASS published it. A withheld county with no earlier figure gets nothing. Returns (values, info)."""
    state = prod.get("_state", {}).get(crop, {})
    counties = prod.get(crop, {})
    out = {f: {"production": None, "harvested": None, "est": False} for f in counties}
    info = {"published": {}, "estimated_n": 0, "short": {}}
    if year == estimate_year(prod, crop):
        return _forecast_values(prod, crop, year, out, info)
    for stat in SUM_MEASURES:
        pub = {f: c["years"][str(year)][stat] for f, c in counties.items() if c["years"].get(str(year), {}).get(stat, 0) > 0}
        for f, v in pub.items():
            out[f][stat] = v
        tot = state.get(str(year), {}).get(stat)
        info["published"][stat] = (sum(pub.values()) / tot) if tot else None
        if not fill or not tot or tot - sum(pub.values()) <= MIN_GAP * tot:
            continue
        short = tot - sum(pub.values())
        w = {}
        for back in range(1, LOOKBACK + 1):
            t0 = state.get(str(year - back), {}).get(stat)
            if not t0:
                continue
            for f, c in counties.items():
                v = c["years"].get(str(year - back), {}).get(stat, 0)
                if f not in pub and f not in w and v > 0:
                    w[f] = v / t0
        tw = sum(w.values())
        if tw <= 0:
            info["short"][stat] = short
            continue
        for f, share in w.items():
            out[f][stat] = short * share / tw
            out[f]["est"] = True
    info["estimated_n"] = sum(1 for v in out.values() if v["est"])
    return out, info


def _forecast_values(prod: dict, crop: str, year: int, out: dict, info: dict) -> tuple:
    """A year with no county survey yet: USDA's state estimate for `year` x each county's average share of the state over the three prior
    completed years (the NASS / RMA dashboard's `_sd_forecast_production` logic, taken to counties; its district numbers are these counties
    dissolved). The shares are on the filled basis, so they add up to one and the counties add up to USDA's state number. Production and
    harvested acres are each spread this way, so a county's yield is its recent production-to-acres mix on USDA's statewide totals."""
    state = prod.get("_state", {}).get(crop, {})
    for stat in SUM_MEASURES:
        tot = state.get(str(year), {}).get(stat)
        if not tot:
            continue
        shares = {}
        prior = [year - b for b in range(1, LOOKBACK + 1)]
        for y in prior:
            vals, _ = year_values(prod, crop, y, True)
            t = state.get(str(y), {}).get(stat)
            if not t:
                continue
            for f, v in vals.items():
                if v[stat]:
                    shares.setdefault(f, []).append(v[stat] / t)
        avg = {f: sum(v) / len(prior) for f, v in shares.items()}
        norm = sum(avg.values())
        for f, a in avg.items():
            out[f][stat] = tot * a / norm
            out[f]["est"] = True
        info["published"][stat] = None
    info["estimated_n"] = sum(1 for v in out.values() if v["est"])
    return out, info


def county_rows(prod: dict, geo: dict, crop: str, years: list, fill: bool = True) -> list:
    """One row per county for the chosen year(s): each year is completed to the state total (year_values), then production and harvested
    acres are averaged over the years; yield = production / harvested over the same years. `est` = any year's figure was filled in."""
    cent = {f["id"]: (f["properties"]["lat"], f["properties"]["lon"]) for f in geo["features"]}
    per = [year_values(prod, crop, y, fill)[0] for y in years]
    rows = []
    for fips, c in prod.get(crop, {}).items():
        ys = [p[fips] for p in per]
        pr = [y["production"] for y in ys if y["production"] is not None]
        ha = [y["harvested"] for y in ys if y["harvested"] is not None]
        both = [y for y in ys if y["production"] is not None and y["harvested"]]
        rows.append({"fips": fips, "county": c["name"], "asd_code": c["asd_code"], "asd": c["asd"],
                     "production": sum(pr) / len(pr) if pr else None,
                     "harvested": sum(ha) / len(ha) if ha else None,
                     "yield": (sum(y["production"] for y in both) / sum(y["harvested"] for y in both)) if both else None,
                     "est": any(y["est"] for y in ys),
                     "miles": round(haversine_miles(MATTOON, cent[fips])) if fips in cent else None})
    return rows


def asd_rows(rows: list) -> list:
    """Counties rolled up to their NASS district: production and acres add, yield = total production / total acres.
    Only counties with both figures count toward a district's yield; `counties` says how many published."""
    out = {}
    for r in rows:
        a = out.setdefault(r["asd_code"], {"asd_code": r["asd_code"], "asd": r["asd"], "production": 0.0, "harvested": 0.0,
                                           "py": 0.0, "hy": 0.0, "counties": 0})
        if r["production"] is not None:
            a["production"] += r["production"]
            a["counties"] += 1
        if r["harvested"] is not None:
            a["harvested"] += r["harvested"]
        if r["production"] is not None and r["harvested"]:
            a["py"] += r["production"]
            a["hy"] += r["harvested"]
    res = []
    for a in out.values():
        a["yield"] = a["py"] / a["hy"] if a["hy"] else None
        res.append({k: a[k] for k in ("asd_code", "asd", "production", "harvested", "yield", "counties")})
    return sorted(res, key=lambda r: -(r["production"] or 0))


def within(rows: list, radius: float, measure: str = "production") -> dict:
    """Total over the counties whose centre is within `radius` miles of Dorans."""
    sel = [r for r in rows if r["miles"] is not None and r["miles"] <= radius and r.get(measure) is not None]
    return {"counties": len(sel), "total": sum(r[measure] for r in sel)}


def fmt(v, unit: str) -> str:
    if v is None:
        return "—"
    if unit == "bu/ac":
        return f"{v:,.1f}"
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.1f} M"
    return f"{v:,.0f}"


# ── drawing ──────────────────────────────────────────────────────────────────────────────────────────────────────
def render() -> None:
    import pandas as pd
    import plotly.graph_objects as go
    import streamlit as st

    prod, geo = load_prod(), load_geo()
    if not prod:
        st.info("No production snapshot yet (data/il_county_prod.json). Run build_il_production.py.")
        return
    c1, c2, c3, c4, c5 = st.columns([1, 1.2, 1.3, 1, 1.4])
    crop = c1.selectbox("Crop", CROPS, key="prod_crop")
    yrs = years_of(prod, crop)
    last = yrs[-1]
    est = estimate_year(prod, crop)
    opts = ([f"{est} (USDA estimate)"] if est else []) + [f"{last} (latest)", f"5-year average ({last - 4}-{last})"] + [str(y) for y in reversed(yrs[:-1])]
    span = c2.selectbox("Years", opts, key="prod_span")
    years = (list(range(last - 4, last + 1)) if span.startswith("5-year") else [est] if "estimate" in span
             else [last if "latest" in span else int(span)])
    measure = c3.selectbox("Measure", list(MEASURES), key="prod_measure")
    level = c4.radio("Level", ["County", "ASD"], horizontal=True, key="prod_level")
    fill = c5.checkbox("Fill withheld counties", True, key="prod_fill",
                       help="NASS withholds some counties' figures (Illinois corn 2025: published counties hold 63% of the state). On: what the published "
                            "counties leave of NASS's official Illinois total is spread over the withheld counties by their share in the earlier years "
                            "(up to three back), so the state adds up to NASS's total and no published figure is changed. Same method as the NASS / RMA "
                            "dashboard's heat map. Off: published counties only.")
    key, unit = MEASURES[measure]

    rows = county_rows(prod, geo, crop, years, fill)
    asds = asd_rows(rows)
    asd_of = {r["fips"]: r["asd_code"] for r in rows}
    asd_val = {a["asd_code"]: a[key] for a in asds}
    z = [asd_val.get(asd_of.get(f["id"])) if level == "ASD" else next((r[key] for r in rows if r["fips"] == f["id"]), None)
         for f in geo["features"]]
    names = {r["fips"]: r for r in rows}
    hover = []
    for f in geo["features"]:
        r = names.get(f["id"])
        if not r:
            hover.append("No published figure")
            continue
        v = asd_val.get(r["asd_code"]) if level == "ASD" else r[key]
        head = f"{r['asd']} district" if level == "ASD" else f"{r['county']} County"
        hover.append(f"<b>{head}</b><br>{measure}: {fmt(v, unit)} {unit}{' (estimated)' if r['est'] and level == 'County' else ''}"
                     f"<br>{r['miles']} mi from Dorans")

    fig = go.Figure(go.Choropleth(geojson=geo, locations=[f["id"] for f in geo["features"]], z=z, text=hover, hoverinfo="text",
                                  colorscale=[[0, "#eaf4fd"], [1, "#0b4f8a"]], marker_line_color="#ffffff", marker_line_width=0.6,
                                  colorbar=dict(title=unit, thickness=12)))
    fig.add_trace(go.Scattergeo(lon=[MATTOON[1]], lat=[MATTOON[0]], mode="markers+text", text=["Dorans"], textposition="top right",
                                marker=dict(size=11, color="#32373c", symbol="star", line=dict(color="#fff", width=1)), hoverinfo="skip"))
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="#ffffff", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    if "estimate" in span:
        st.caption(f"{est}: no county survey exists yet (NASS publishes counties in January). Each county = USDA's latest {est} Illinois estimate "
                   f"(production and harvested acres, NASS Crop Production) x the county's average share of the state over {est - 3}-{est - 1}, "
                   "the same logic the NASS / RMA dashboard uses for districts. Counties are filled the same way for the share years.")
    st.caption(f"NASS survey, {crop.lower()}{' for grain' if crop == 'Corn' else ''}, {span}. Counties NASS withheld are "
               + ("filled in from its official Illinois total (marked estimated); " if fill else "left out (published counties only); ")
               + "a multi-year view averages the years. Districts are the NASS crop-reporting districts, built from their counties.")

    if key in SUM_MEASURES:
        r1, r2 = st.columns([1, 3])
        radius = r1.slider("Miles from Dorans", 25, 250, 100, 25, key="prod_radius")
        w = within(rows, radius, key)
        il = sum(r[key] for r in rows if r[key] is not None)
        r2.metric(f"{measure} within {radius} miles ({w['counties']} counties)", f"{fmt(w['total'], unit)} {unit}",
                  f"{w['total'] / il * 100:.0f}% of Illinois" if il else None, delta_color="off")

    t1, t2 = st.tabs(["Districts (ASD)", "Counties"])
    with t1:
        df = pd.DataFrame(asds).rename(columns={"asd": "District", "production": "Production (bu)", "harvested": "Harvested (ac)",
                                                "yield": "Yield (bu/ac)", "counties": "Counties"}).drop(columns="asd_code")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config={"Production (bu)": st.column_config.NumberColumn(format="%d"),
                                    "Harvested (ac)": st.column_config.NumberColumn(format="%d"),
                                    "Yield (bu/ac)": st.column_config.NumberColumn(format="%.1f")})
    with t2:
        df = pd.DataFrame(sorted(rows, key=lambda r: -(r[key] or 0)))[["county", "asd", "production", "harvested", "yield", "miles", "est"]]
        df["est"] = df["est"].map({True: "estimated", False: ""})
        df.columns = ["County", "District", "Production (bu)", "Harvested (ac)", "Yield (bu/ac)", "Miles from Dorans", "Filled"]
        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config={"Production (bu)": st.column_config.NumberColumn(format="%d"),
                                    "Harvested (ac)": st.column_config.NumberColumn(format="%d"),
                                    "Yield (bu/ac)": st.column_config.NumberColumn(format="%.1f")})

    # Trend: district production by year for the chosen crop
    st.markdown(f"##### {crop} by district, {yrs[0]}-{est or last}")
    tr = []
    for y in yrs + ([est] if est else []):
        for a in asd_rows(county_rows(prod, geo, crop, [y], fill)):
            tr.append({"Year": y, "District": a["asd"], "Value": a[key]})
    t = pd.DataFrame(tr)
    f2 = go.Figure()
    for d, g in t.groupby("District"):
        f2.add_trace(go.Scatter(x=g["Year"], y=g["Value"], name=d, mode="lines+markers"))
    f2.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="#fff", plot_bgcolor="#fff",
                     yaxis=dict(title=unit, gridcolor="#e2e8f0"), xaxis=dict(dtick=1))
    st.plotly_chart(f2, use_container_width=True)
