"""Competing elevators around Dorans on the county map (same layout as the DuMond maps: county production underneath, pins on top)."""
import json
import math
from pathlib import Path

import production

DATA = Path(__file__).parent / "data" / "competitors.json"
POS = {"Primient Mattoon": "bottom right", "Primient Coles": "middle left", "ADM Sullivan": "middle left", "TGM Neoga": "bottom center"}   # keeps the crowded labels apart


def load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def ring(lat, lon, miles, n=90):
    """Lon/lat points of a circle `miles` around a point (a small-circle approximation, fine at 25-50 miles)."""
    pts = []
    for i in range(n + 1):
        b = 2 * math.pi * i / n
        dlat = miles / 69.0 * math.cos(b)
        dlon = miles / (69.0 * math.cos(math.radians(lat))) * math.sin(b)
        pts.append((lon + dlon, lat + dlat))
    return pts


def render() -> None:
    import pandas as pd
    import plotly.graph_objects as go
    import streamlit as st

    d = load()
    me, rows = d["dorans"], d["rows"]
    prod, geo = production.load_prod(), production.load_geo()

    c1, c2, c3, c4 = st.columns([1.3, 1.2, 1.4, 1.2])
    under = c1.selectbox("County production layer", ["Corn", "Soybeans", "Corn + soybeans", "None"], key="comp_under")
    last = production.years_of(prod, "Corn")[-1]
    est = production.estimate_year(prod, "Corn")
    yopts = [f"{last} (latest)", f"5-year average ({last - 4}-{last})"] + ([f"{est} (forecast)"] if est else [])
    ysel = c2.selectbox("Production year", yopts, key="comp_year")
    show_c = c3.checkbox("Candidates from the shipper / plant lists", True, key="comp_cand")
    rings = c4.multiselect("Distance rings (miles)", [15, 25, 50], default=[25], key="comp_rings")
    years = list(range(last - 4, last + 1)) if ysel.startswith("5-year") else [est] if "forecast" in ysel else [last]

    def prod_by(crop):
        return {r["fips"]: r["production"] for r in production.county_rows(prod, geo, crop, years)}

    fig = go.Figure()
    fips_all = [f["id"] for f in geo["features"]]
    fig.add_trace(go.Choropleth(geojson=geo, locations=fips_all, z=[0] * len(fips_all), showscale=False, colorscale=[[0, "#f4f6f8"], [1, "#f4f6f8"]],
                                marker_line_color="#c9d1d9", marker_line_width=0.6, hoverinfo="skip"))
    if under != "None" and prod:
        corn, soy = prod_by("Corn"), prod_by("Soybeans")
        val = ({f: corn.get(f) for f in fips_all} if under == "Corn" else {f: soy.get(f) for f in fips_all} if under == "Soybeans"
               else {f: (corn.get(f) or 0) + (soy.get(f) or 0) for f in fips_all})
        nm = {r["fips"]: r["county"] for r in production.county_rows(prod, geo, "Corn", [last])}
        fig.data = ()
        fig.add_trace(go.Choropleth(
            geojson=geo, locations=fips_all, z=[val.get(f) for f in fips_all], colorscale=[[0, "#eaf4fd"], [0.5, "#7fb6e3"], [1, "#0b4f8a"]],
            marker_line_color="#ffffff", marker_line_width=0.5, colorbar=dict(title=f"{under}<br>bu, {ysel.split(' (')[0]}", thickness=10),
            customdata=[[nm.get(f, ""), corn.get(f) or 0, soy.get(f) or 0] for f in fips_all],
            hovertemplate="<b>%{customdata[0]} County</b><br>Corn %{customdata[1]:,.0f} bu<br>Soybeans %{customdata[2]:,.0f} bu<extra></extra>"))
        cent = {f["id"]: (f["properties"]["lon"], f["properties"]["lat"]) for f in geo["features"]}
        lab = [(cent[f], val[f]) for f in fips_all if val.get(f)]
        fig.add_trace(go.Scattergeo(lon=[c[0][0] for c in lab], lat=[c[0][1] for c in lab], mode="text", text=[f"{v / 1e6:.1f}" for _, v in lab],
                                    textfont=dict(size=9, color="#374151"), hoverinfo="skip", showlegend=False))
    for m in rings:
        pts = ring(me["lat"], me["lon"], m)
        fig.add_trace(go.Scattergeo(lon=[p[0] for p in pts], lat=[p[1] for p in pts], mode="lines", line=dict(color="#32373c", width=1, dash="dot"),
                                    hoverinfo="skip", showlegend=False))
    placed = [r for r in rows if r["lat"] is not None]
    if show_c:
        truck = [r for r in placed if not r["confirmed"] and r.get("truck")]
        fig.add_trace(go.Scattergeo(lon=[r["lon"] for r in truck], lat=[r["lat"] for r in truck], mode="markers", name="Elevators bidding in the tracker (≤30 mi)",
                                    marker=dict(size=9, color="#f59e0b", line=dict(color="#fff", width=1)),
                                    text=[f"<b>{r['name']}</b><br>{r['kind']}<br>{r['miles']} mi from Dorans" for r in truck], hoverinfo="text"))
        cand = [r for r in placed if not r["confirmed"] and not r.get("truck")]
        fig.add_trace(go.Scattergeo(lon=[r["lon"] for r in cand], lat=[r["lat"] for r in cand], mode="markers", name="Other shipper / plant candidates",
                                    marker=dict(size=8, color="#9aa5b1", line=dict(color="#fff", width=1)),
                                    text=[f"<b>{r['name']}</b><br>{r['kind']} · {r['place']}<br>{r['miles']} mi · {r['source']}" for r in cand],
                                    hoverinfo="text"))
    named = [r for r in placed if r["confirmed"]]
    fig.add_trace(go.Scattergeo(lon=[r["lon"] for r in named], lat=[r["lat"] for r in named], mode="markers+text", name="Competitors",
                                text=[r["name"] for r in named], textposition=[POS.get(r["name"], "top center") for r in named], textfont=dict(size=10, color="#7f1d1d"),
                                marker=dict(size=11, color="#dc2626", line=dict(color="#fff", width=1.5)),
                                hovertext=[f"<b>{r['name']}</b><br>{r['place']}<br>{r['miles']} mi from Dorans<br>Location: {r['source']}" for r in named],
                                hoverinfo="text"))
    fig.add_trace(go.Scattergeo(lon=[me["lon"]], lat=[me["lat"]], mode="markers+text", name="Dorans", text=["Farmers Grain Co of Dorans"],
                                textposition="top right", textfont=dict(size=11, color="#32373c"),
                                marker=dict(size=16, color="#0693e3", symbol="star", line=dict(color="#fff", width=1.5)), hoverinfo="skip"))
    lat0, lon0 = me["lat"], me["lon"]
    span = (max(rings) if rings else 25) / 69.0 + 0.35
    fig.update_geos(visible=False, lonaxis_range=[lon0 - span * 1.3, lon0 + span * 1.3], lataxis_range=[lat0 - span, lat0 + span])
    fig.update_layout(height=640, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="#fff", legend=dict(orientation="h", y=0.01, x=0.01))
    st.plotly_chart(fig, use_container_width=True)

    unplaced = [r["name"] for r in rows if r["lat"] is None]
    st.caption(f"County labels: {under.lower()} production in M bu ({ysel}), withheld counties filled the same way as the IL Production tab. "
               "Red = the elevators you named; orange = every other elevator within 30 miles that posts a bid in the basis tracker (the truck-delivered "
               "competition, from its pins); grey = candidates from the BNSF / CSX / NS / CN / UP shipper directories and the crush and ethanol lists "
               "within 45 miles (a rail-shipper entry is a loading elevator, not proof it bids for the same grain). Primient Coles, Primient Mattoon and ADM Sullivan are placed from their street addresses; the other pins are the basis tracker's."
               + (f" Not pinned, no coordinates yet: {', '.join(unplaced)}." if unplaced else ""))

    df = pd.DataFrame([{"Name": r["name"], "Type": r["kind"], "Place": r["place"], "Miles from Dorans": r["miles"],
                        "Named": "yes" if r["confirmed"] else "", "Location source": r["source"]} for r in rows])
    st.dataframe(df, hide_index=True, use_container_width=True)
