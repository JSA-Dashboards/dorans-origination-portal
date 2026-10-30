"""Competition page: the Illinois county map with the competing elevators layered over the production map (the same map as the IL Production tab's
County view). Pick the production layer (corn, soybeans, both or none), the year, the extent (Illinois or zoomed on Dorans) and which pins to show."""
import json
import math
from pathlib import Path

import pandas as pd

import il_figs as nf
import production as P

DATA = Path(__file__).parent / "data"


def load() -> dict:
    return json.loads((DATA / "competitors.json").read_text(encoding="utf-8"))


def ring(lat, lon, miles, n=90):
    """Lon/lat points of a circle `miles` around a point (a small-circle approximation, fine at 25-50 miles)."""
    return [(lon + miles / (69.0 * math.cos(math.radians(lat))) * math.sin(2 * math.pi * i / n), lat + miles / 69.0 * math.cos(2 * math.pi * i / n))
            for i in range(n + 1)]


def render() -> None:
    import plotly.graph_objects as go
    import streamlit as st

    d = load()
    rows = d["rows"]
    plants = json.loads((DATA / "il_plants.json").read_text(encoding="utf-8"))
    prod, geo = P.load_prod(), nf.load_geo()
    last = P.years_of(prod, "Corn")[-1]
    est = P.estimate_year(prod, "Corn")

    view = st.radio("Map view", ["Draw Territory", "Production map"], horizontal=True, key="comp_view")
    if view == "Draw Territory":
        _draw(d, plants, prod, geo, last, est)
        _competitor_list(rows)
        return

    c1, c2, c3, c4 = st.columns([1.3, 1.5, 1.2, 1.2])
    layer = c1.selectbox("Production layer", ["Corn", "Soybeans", "Corn + soybeans", "None"], key="comp_under")
    yopts = [f"{last} (latest)", f"5-year average ({last - 4}-{last})"] + ([f"{est} (forecast)"] if est else [])
    ysel = c2.selectbox("Production year", yopts, key="comp_year")
    zoom = c3.radio("Map extent", ["Illinois", "Dorans area"], horizontal=True, key="comp_extent")
    extent = None
    if zoom == "Dorans area":
        extent = (nf.DORANS["lat"], nf.DORANS["lon"], c4.slider("Zoom radius (miles)", 25, 120, 50, 5, key="comp_zoom_r"))
    years = list(range(last - 4, last + 1)) if ysel.startswith("5-year") else [est] if "forecast" in ysel else [last]

    p1, p2, p3, p4, p5 = st.columns(5)
    show_named = p1.checkbox("Named elevators", True, key="comp_named")
    show_truck = p2.checkbox("Bidding elevators ≤30 mi", True, key="comp_truck")
    show_cand = p3.checkbox("Other candidates", False, key="comp_cand")
    show_pl = p4.checkbox("Ethanol / crush plants", False, key="comp_plants")
    show_ring = p5.checkbox("25-mile ring", False, key="comp_ring")

    def by(crop):
        return {r["fips"]: r for r in P.county_rows(prod, geo, crop, years)}
    names = {f: r["county"] for f, r in by("Corn").items()}
    if layer == "None":
        vals, est_f, crop_lbl = {f: None for f in names}, {}, "Illinois"
    else:
        corn, soy = by("Corn"), by("Soybeans")
        pick = {"Corn": [corn], "Soybeans": [soy], "Corn + soybeans": [corn, soy]}[layer]
        vals = {f: (sum((s.get(f) or {}).get("production") or 0 for s in pick) or None) for f in names}
        est_f = {f: any((s.get(f) or {}).get("est") for s in pick) for f in names}
        crop_lbl = layer
    df = pd.DataFrame([{"County": names[f], "fips": f, "Value": vals.get(f), "is_estimated": est_f.get(f, False)} for f in names])
    sel = [r for r in rows if (r["confirmed"] and show_named) or (not r["confirmed"] and r.get("truck") and show_truck)
           or (not r["confirmed"] and not r.get("truck") and show_cand)]
    fig = nf.county_fig(df, geo, crop_lbl, int(ysel.split()[0]) if "average" not in ysel else last, "Production (bu)", "Current Year", sel or None, None,
                        forecast="forecast" in ysel, extent=extent)
    if show_pl:
        for crop in ("Corn", "Soybeans"):
            if layer in (crop, "Corn + soybeans", "None"):
                nf.add_plants(fig, plants, crop)
    if show_ring:
        pts = ring(nf.DORANS["lat"], nf.DORANS["lon"], 25)
        fig.add_trace(go.Scattergeo(lon=[p[0] for p in pts], lat=[p[1] for p in pts], mode="lines", line=dict(color="#32373c", width=1.2, dash="dot"),
                                    hoverinfo="skip", showlegend=False))
    fig.update_layout(dragmode=False, legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.005, yanchor="top"), margin=dict(l=0, r=0, t=60, b=110))
    st.plotly_chart(fig, use_container_width=True, key="comp_map", config={"scrollZoom": False, "displayModeBar": False, "doubleClick": False})
    st.caption("Red = the elevators you named; orange = every other elevator within 30 miles that posts a bid in the basis tracker (the truck-delivered competition); "
               "grey = other candidates from the rail shipper directories and crush / ethanol lists within 45 miles. Primient Coles, Primient Mattoon and ADM Sullivan "
               "are placed from street addresses; the rest from the Basis Tracker's pins. County labels = M bu, withheld counties filled as on the IL Production tab (* = estimated).")

    _competitor_list(rows)


def _draw(d, plants, prod, geo, last, est) -> None:
    """Dorans' draw territory (territory_tab) on this page: pick the crop, year and extent; the competitors in the data file are the buyers."""
    import streamlit as st
    import territory_tab

    c1, c2, c3, c4 = st.columns([1.1, 1.5, 1.2, 1.2])
    crop = c1.radio("Crop", ["Corn", "Soybeans"], horizontal=True, key="comp_dr_crop")
    yopts = ([f"{est} (forecast)"] if est else []) + [str(y) for y in range(last, last - 5, -1)]
    ysel = c2.selectbox("Production year", yopts, index=1 if est else 0, key="comp_dr_year")
    year = int(ysel.split()[0])
    extent = None
    if c3.radio("Map extent", ["Illinois", "Dorans area"], horizontal=True, key="comp_dr_extent") == "Dorans area":
        extent = (nf.DORANS["lat"], nf.DORANS["lon"], c4.slider("Zoom radius (miles)", 25, 120, 60, 5, key="comp_dr_zoom"))
    cdf, _ = P.view_frames(prod, geo, crop, "production", year, "Current Year", None, True, None)
    st.session_state["_il_geo"] = geo
    territory_tab.render(crop, year, "production", cdf, d["rows"], plants, extent, year == est, pfx="comp")


CN_MARKETS = [("CN 105s", "CN 105s corn"), ("CN 105s Beans", "CN 105s soybeans"), ("CN 25's", "CN 25's corn")]


def cn_front_bids() -> tuple:
    """({market: (as-of day, front period, bid cents, futures)}, note) from the rail bid archive (the same read as the CN tabs); empty with a note when it isn't connected."""
    import rail_data as RD
    if not RD.configured():
        return {}, "CN bids aren't shown: the rail bid archive isn't connected here (see the CN Rail FOB tab)."
    try:
        import cn_sheet
        all_rows = cn_sheet._cached_bids()
        out = {}
        for m, _ in CN_MARKETS:
            cells, day = cn_sheet._latest_cells(all_rows, m)
            ps = [p for p in cn_sheet._ordered(cells) if cells[p].get("bid") is not None]
            if ps:
                c = cells[ps[0]]
                out[m] = (str(day), ps[0], c["bid"], c.get("futures"))
        return out, "" if out else "No CN bids posted yet."
    except Exception as e:
        return {}, f"CN bids couldn't be read ({e})."


def _cn_market(r) -> str | None:
    """Which CN bid applies to a competitor: 105-car points the 105s bid, smaller CN loaders (25 / 50 cars) the 25's bid."""
    cn = next((x for x in (r.get("rail") or []) if x.startswith("CN:")), None)
    if not cn:
        return None
    return "CN 105s" if cn.startswith("CN: 105") else "CN 25's"


def _fmt_bid(b) -> str:
    return "" if not b else f"{b[2]:+.0f} {b[1]}" + (f" ({b[3]})" if b[3] else "")


def _competitor_list(rows) -> None:
    import streamlit as st

    bids, note = cn_front_bids()
    if bids:
        cols = st.columns(len(CN_MARKETS))
        for col, (m, lbl) in zip(cols, CN_MARKETS):
            b = bids.get(m)
            col.metric(f"{lbl} (front month)", f"{b[2]:+.0f}¢ {b[1]}" if b else "—", f"posted {b[0]}, vs {b[3]}" if b and b[3] else (f"posted {b[0]}" if b else None), delta_color="off")
        st.caption("CN bids are FOB Champaign (the 25's taken as the same), cents vs the futures month shown. Each CN-served competitor is matched to the bid for its loading size: "
                   "105-car points to the 105s bid, 25 / 50-car points to the 25's bid.")
    elif note:
        st.caption(note)
    with st.expander("Competitor list"):
        st.dataframe(pd.DataFrame([{"Name": r["name"], "Type": r["kind"], "Place": r["place"], "Miles from Dorans": r["miles"], "Named": "yes" if r["confirmed"] else "",
                                    "Rail access / loading capacity": "; ".join(r.get("rail") or []) + ((" | " if r.get("rail") else "") + r["company_rail"] if r.get("company_rail") else ""),
                                    **({"CN bid that applies (front month)": f"{_cn_market(r)}: {_fmt_bid(bids.get(_cn_market(r)))}" if _cn_market(r) and bids.get(_cn_market(r)) else ""} if bids else {}),
                                    "Location source": r["source"]} for r in rows]), hide_index=True, use_container_width=True)
