"""Market Share tab: Dorans' receipts each market year against the production of Coles County (and any other counties picked), corn and soybeans."""
import pandas as pd
import streamlit as st

import il_figs as nf
import production as P
import receipts as R


def _receipts():
    rec = R.load_saved()
    if rec:
        return rec, "secret / private file"
    up = st.file_uploader("Dorans receipts workbook (5 YR RECEIPTS ANALYSIS.xlsx)", type=["xlsx"], key="ms_upload",
                          help="Read in this session only; nothing is stored. To keep it loaded, add the DORANS_RECEIPTS secret.")
    if up is None:
        st.info("Dorans' receipts aren't in the app (they are the elevator's own numbers, so they are kept out of the public repo). Upload the "
                "workbook here, or add the `DORANS_RECEIPTS` secret to keep them loaded.")
        return None, ""
    try:
        return R.parse_xlsx(up), "uploaded workbook"
    except Exception as e:
        st.error(f"Couldn't read the first tab of that workbook: {e}")
        return None, ""


def _production_by_year(prod, geo, crop, fips: list, years: list) -> dict:
    """{crop year: (production of the picked counties, any county filled in)} - withheld counties filled as on the IL Production tab."""
    out = {}
    for y in years:
        rows = {r["fips"]: r for r in P.county_rows(prod, geo, crop, [y], True)}
        vals = [rows[f] for f in fips if f in rows and rows[f]["production"]]
        out[y] = (sum(r["production"] for r in vals), any(r["est"] for r in vals))
    return out


def render() -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    prod, geo = P.load_prod(), nf.load_geo()
    rec, src = _receipts()
    if not rec:
        return
    names = {f: c["name"] for f, c in prod["Corn"].items()}
    cent = {f["id"]: (f["properties"]["lat"], f["properties"]["lon"]) for f in geo["counties"]["features"] if "lat" in f["properties"]}
    cent = cent or {f["id"]: (f["properties"]["lon"], f["properties"]["lat"]) for f in geo["counties"]["features"]}
    order = sorted(names, key=lambda f: names[f])
    c1, c2 = st.columns([2.2, 1.4])
    picked = c1.multiselect("Benchmark counties", order, default=["17029"], format_func=lambda f: f"{names[f]} County", key="ms_counties")
    near = c2.slider("Also add counties within (miles of Dorans)", 0, 50, 0, 5, key="ms_near",
                     help="0 = just the counties picked. Adds every county whose centre is within that many miles of the Dorans elevator.")
    fips = list(picked)
    if near:
        meta = P.county_rows(prod, geo, "Corn", [2025], True)
        fips += [r["fips"] for r in meta if r["miles"] is not None and r["miles"] <= near and r["fips"] not in fips]
    if not fips:
        st.info("Pick at least one county.")
        return
    label = ", ".join(names[f] for f in fips[:4]) + (f" +{len(fips) - 4} more" if len(fips) > 4 else "")

    last = P.years_of(prod, "Corn")[-1]
    est = P.estimate_year(prod, "Corn")
    cols = st.columns(2)
    summary = {}
    for col, crop, r_crop in zip(cols, ("Corn", "Soybeans"), ("Corn", "Soybeans")):
        recs = R.by_crop_year(rec, r_crop)
        years = [int(y) for y in recs if int(y) <= (est or last)]
        pr = _production_by_year(prod, geo, crop, fips, years)
        rows = []
        for y in years:
            bu, kind = recs[str(y)]
            p, filled = pr[y]
            rows.append({"Crop year": y, "FYE": f"FYE {str(y + 1)[-2:]}", "Dorans receipts (bu)": bu, "Basis": kind, "County production (bu)": p,
                         "Filled": "est" if filled else "", "Share (%)": R.share(bu, p) if kind != "to date" and y <= last else None})
        df = pd.DataFrame(rows)
        summary[crop] = df
        with col:
            st.markdown(f"##### {crop}")
            full = df[df["Share (%)"].notna()]
            now = full.iloc[-1] if len(full) else None
            avg = full["Share (%)"].mean() if len(full) else None
            m1, m2 = st.columns(2)
            m1.metric(f"{int(now['Crop year'])} share" if now is not None else "Share", f"{now['Share (%)']:.1f}%" if now is not None else "—",
                      f"{now['Share (%)'] - full.iloc[-2]['Share (%)']:+.1f} pts vs {int(full.iloc[-2]['Crop year'])}" if now is not None and len(full) > 1 else None)
            m2.metric(f"{len(full)}-yr average", f"{avg:.1f}%" if avg is not None else "—")
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=df["Crop year"], y=df["County production (bu)"] / 1e6, name="County production", marker_color="#c3ccd6"), secondary_y=False)
            fig.add_trace(go.Bar(x=df["Crop year"], y=df["Dorans receipts (bu)"] / 1e6, name="Dorans receipts", marker_color="#0693e3"), secondary_y=False)
            fig.add_trace(go.Scatter(x=full["Crop year"], y=full["Share (%)"], name="Share of production", mode="lines+markers", line=dict(color="#32373c", width=3)),
                          secondary_y=True)
            fig.update_layout(barmode="group", height=340, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="#fff", plot_bgcolor="#fff", legend=dict(orientation="h", y=-0.18),
                              xaxis=dict(dtick=1))
            fig.update_yaxes(title_text="M bu", gridcolor="#e2e8f0", secondary_y=False)
            fig.update_yaxes(title_text="% share", showgrid=False, secondary_y=True, rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

    st.caption(f"Benchmark: {label} County production (NASS, withheld years filled as on the IL Production tab; 'est' = a filled year). Dorans receipts from the {src}. "
               "Crop year = the harvest; the workbook's FYE n is the fiscal year ending Aug of n, i.e. crop n-1 (FYE 25 = fall 2024 + the after-harvest receipts). "
               f"Crop 2025 = its fall harvest + after-harvest receipts (the sheet's FYE 26 cell actually points at the Fall 26 column, so it is not used); "
               f"{est or last + 1} is the harvest received so far against a forecast, so it has no share yet.")

    st.markdown("##### By year")
    year_tbl = []
    for crop, df in summary.items():
        t = df.copy()
        t.insert(0, "Crop", crop)
        year_tbl.append(t)
    allt = pd.concat(year_tbl).sort_values(["Crop", "Crop year"], ascending=[True, False])
    st.dataframe(allt, hide_index=True, use_container_width=True,
                 column_config={"Dorans receipts (bu)": st.column_config.NumberColumn(format="%d"), "County production (bu)": st.column_config.NumberColumn(format="%d"),
                                "Share (%)": st.column_config.NumberColumn(format="%.1f"), "Crop year": st.column_config.NumberColumn(format="%d")})

    st.markdown("##### Each county, one crop year")
    d1, d2 = st.columns(2)
    yr = d1.selectbox("Crop year", list(range(last, last - 10, -1)), key="ms_year")
    crop = d2.radio("Crop", ["Corn", "Soybeans"], horizontal=True, key="ms_crop")
    recs = R.by_crop_year(rec, crop)
    bu = recs.get(str(yr), (None, ""))[0]
    rows = P.county_rows(prod, geo, crop, [yr], True)
    tot = sum(r["production"] or 0 for r in rows if r["fips"] in fips)
    tbl = pd.DataFrame([{"County": f"{r['county']}", "District": r["asd"], "Miles from Dorans": r["miles"], "Production (bu)": r["production"],
                         "Dorans receipts as % of this county": R.share(bu, r["production"]), "% of benchmark production": (r["production"] / tot * 100 if tot and r["fips"] in fips else None),
                         "In benchmark": "yes" if r["fips"] in fips else ""} for r in sorted(rows, key=lambda r: (r["miles"] is None, r["miles"]))])
    st.dataframe(tbl.head(25), hide_index=True, use_container_width=True,
                 column_config={"Production (bu)": st.column_config.NumberColumn(format="%d"), "Dorans receipts as % of this county": st.column_config.NumberColumn(format="%.0f%%"),
                                "% of benchmark production": st.column_config.NumberColumn(format="%.0f%%")})
    st.caption(f"The 25 counties nearest Dorans for {yr} {crop.lower()}. Dorans' receipts ({(bu or 0) / 1e6:,.1f} M bu) are everything it handled, wherever it came from, "
               "so a county percentage above 100 just means grain is coming in from outside that county.")
