"""Draw Territory view of the IL Production tab: where the grain around Dorans goes against the buyers that compete for it (draw.py)."""
import numpy as np
import pandas as pd
import streamlit as st

import draw as DR
import il_figs as nf
import production as P


@st.cache_resource
def _lattice():
    return DR.load_lattice()


def render(crop: str, year: int, key: str, cdf, comp_rows: list, plants: list, extent, is_fc: bool) -> None:
    if key not in P.SUM_MEASURES:
        st.info("Draw territory moves bushels (or acres): pick Production or Harvested Acres as the Metric.")
        return
    geo = st.session_state["_il_geo"]
    lat = _lattice()
    val = dict(zip(cdf["fips"], cdf["Raw"]))
    bu = np.nan_to_num(np.array([float(val.get(f) or 0.0) / n for f, n in zip(lat["fips"], lat["n"])], dtype=float))
    c1, c2, c3, c4 = st.columns(4)
    freight = c1.slider("Haul cost (¢/bu per road mile)", 0.2, 1.5, 0.6, 0.05, key="il_dr_freight",
                        help="Default 0.6 is about what the Devon Warren Decatur rate works out to (29¢ for roughly 45 road miles). Road miles = straight-line x 1.25.")
    tau = c2.slider("Crossover (¢/bu)", 0.5, 15.0, 3.0, 0.5, key="il_dr_tau",
                    help="How far apart two buyers' net prices can be before the farther one stops getting grain. Small = the nearest / best buyer takes "
                         "almost all; large = more crossover.")
    haul = c3.slider("Max haul (miles)", 20, 150, 60, 5, key="il_dr_haul", help="Grain only goes to buyers within this straight-line distance.")
    d_add = c4.number_input("Dorans bid adder (¢/bu)", -30.0, 30.0, 0.0, 1.0, key="il_dr_dadd",
                            help="Cents per bushel Dorans bids above (+) or below (-) the others, on top of the haul.")
    t1, t2 = st.columns(2)
    inc_pl = t1.checkbox("Compete against ethanol / crush plants", True, key="il_dr_plants")
    inc_ot = t2.checkbox("Compete against the other shipper-list candidates", False, key="il_dr_cand")

    nodes = [{"name": "Dorans", "lat": nf.DORANS["lat"], "lon": nf.DORANS["lon"], "adder": d_add, "kind": "Dorans", "miles": 0}]
    for r in comp_rows:
        if r["lat"] is None or not (r["confirmed"] or r.get("truck") or inc_ot):
            continue
        nodes.append({"name": r["name"], "lat": r["lat"], "lon": r["lon"], "adder": 0.0, "miles": r["miles"], "kind": "Named" if r["confirmed"] else "Elevator"})
    if inc_pl:
        pk = "crush" if crop == "Soybeans" else "ethanol"
        for p in plants:
            if p["kind"] == pk and (p.get("status") or "Run") != "Build":
                nodes.append({"name": f"{p['name']}, {p['city']}", "lat": p["lat"], "lon": p["lon"], "adder": 0.0, "kind": "Plant",
                              "miles": round(P.haversine_miles((nf.DORANS["lat"], nf.DORANS["lon"]), (p["lat"], p["lon"])))})
    with st.expander("Competitor bid adders (¢/bu vs Dorans)", expanded=False):
        base = pd.DataFrame({"Buyer": [n["name"] for n in nodes[1:]], "Type": [n["kind"] for n in nodes[1:]], "Miles": [n["miles"] for n in nodes[1:]],
                             "Adder (¢/bu)": [0.0] * (len(nodes) - 1)})
        ed = st.data_editor(base, hide_index=True, use_container_width=True, disabled=["Buyer", "Type", "Miles"], key=f"il_dr_adders_{crop}_{len(nodes)}")
        for n, a in zip(nodes[1:], ed["Adder (¢/bu)"]):
            n["adder"] = float(a or 0.0)
        st.caption("Positive = that buyer bids that many cents better than the others at the elevator door; its haul cost still applies.")

    res = DR.compute(lat["lat"], lat["lon"], bu, nodes, freight, tau, haul)
    total = float(bu.sum())
    mine = float(res["bu"][0])
    unit = "bu" if key == "production" else "ac"
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Dorans draw ({year} {crop.lower()})", f"{mine / 1e6:,.1f} M {unit}", f"{mine / total * 100:.1f}% of Illinois" if total else None, delta_color="off")
    near = res["miles"][:, 0] <= 25
    k2.metric("Draw within 25 mi", f"{float((res['share'][:, 0] * bu)[near].sum()) / 1e6:,.1f} M {unit}")
    k3.metric("Supply within 25 mi", f"{float(bu[near].sum()) / 1e6:,.1f} M {unit}", help="All the grain grown within 25 miles of Dorans, drawn by anyone.")
    k4.metric("Unplaced", f"{res['unplaced'] / 1e6:,.0f} M {unit}", help="Grain with no buyer in this model within the maximum haul (it only knows the buyers listed).")

    fig = nf.territory_fig(lat["lat"], lat["lon"], res["share"][:, 0], bu, nodes, geo, crop, year, extent)
    fig.update_layout(dragmode=False)
    st.plotly_chart(fig, use_container_width=True, key="il_territory_map", config={"scrollZoom": False, "displayModeBar": False, "doubleClick": False})
    st.caption("A micro version of the NASS / RMA Draw Territory: each ~4 mile dot sends its county's grain to the buyers in reach in proportion to "
               "exp(-net cost / crossover). Only the buyers on the Competition map (and the plants above) exist in the model, so the edges overstate Dorans' share "
               "where an unlisted buyer sits closer." + (" Forecast year: county grain is USDA's state estimate x 3-year shares." if is_fc else ""))

    order = np.argsort(-res["bu"])
    placed = max(total - res["unplaced"], 1.0)
    tbl = pd.DataFrame({"Buyer": [nodes[i]["name"] for i in order], "Type": [nodes[i]["kind"] for i in order],
                        f"Draw (M {unit})": [res["bu"][i] / 1e6 for i in order], "% of draw": [res["bu"][i] / placed * 100 for i in order],
                        "Miles from Dorans": [nodes[i]["miles"] for i in order]})
    ca, cb = st.columns(2)
    ca.markdown("##### Draw by buyer")
    ca.dataframe(tbl[tbl[f"Draw (M {unit})"] > 0.005], hide_index=True, use_container_width=True,
                 column_config={f"Draw (M {unit})": st.column_config.NumberColumn(format="%.1f"), "% of draw": st.column_config.NumberColumn(format="%.1f%%")})
    names = {r["fips"]: (r["County"], r["District"]) for r in cdf.to_dict("records")}
    cc = DR.by_county(lat["fips"], bu, res["share"][:, 0])
    ct = pd.DataFrame([{"County": names[f][0], "District": names[f][1], f"County (M {unit})": v[0] / 1e6, f"To Dorans (M {unit})": v[1] / 1e6,
                        "% to Dorans": (v[1] / v[0] * 100 if v[0] else 0)} for f, v in cc.items() if v[1] > 0]).sort_values(f"To Dorans (M {unit})", ascending=False)
    cb.markdown("##### Where Dorans' draw comes from")
    cfg = {c: st.column_config.NumberColumn(format="%.2f") for c in ct.columns[2:4]}
    cfg["% to Dorans"] = st.column_config.NumberColumn(format="%.0f%%")
    cb.dataframe(ct, hide_index=True, use_container_width=True, column_config=cfg)
