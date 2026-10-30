"""Plotly figures for the Illinois NASS Production tab, ported from the DuMond (New York) dashboard's ny_asd_figs.py: same palette, map labels,
district outlines, history bars, heat-map tables and county rankings, drawn from data/il_asd_geo.json. No Streamlit import."""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).parent
DARK, PANEL, SURFACE = "#f6f8f7", "#ffffff", "#eef3f0"
BORDER, TEXT, MUTED = "#d7e2dc", "#32373c", "#5f7267"
ACCENT, LAND = "#5e7164", "#e1e9e4"
SAGE_SEQ = [[0, "#f0f6f3"], [0.2, "#cfe6da"], [0.55, "#98d0b6"], [1, "#58a784"]]
SAGE_DIV = [[0, "#b22222"], [0.25, "#e08080"], [0.5, "#f5f5f5"], [0.75, "#7dbfa7"], [1, "#1a6645"]]
ASD_PALETTE = {"10": "#0693e3", "20": "#f59e0b", "30": "#ef4444", "40": "#a78bfa", "50": "#16a34a",
               "60": "#fb923c", "70": "#38bdf8", "80": "#e879f9", "90": "#6366f1"}
DORANS = {"name": "Farmers Grain Co of Dorans", "lat": 39.5511, "lon": -88.3445}
LABEL_SHIFT = {"Southwest": -0.12, "Southeast": 0.12}      # the two southern districts are side by side; nudge their labels apart
_STAR, _STAR_EDGE = "#fbbf24", "#7c2d12"


def load_geo() -> dict:
    return json.loads((HERE / "data" / "il_asd_geo.json").read_text(encoding="utf-8"))


# ── label formatters ──────────────────────────────────────────────────────────
def fmt_bu(v):
    return "" if v is None or pd.isna(v) or v == 0 else f"{v / 1_000_000:.1f}"


def fmt_chg(v):
    return "" if v is None or pd.isna(v) or abs(v) < 0.05 else f"{v:+.1f}%"


def fmt_acres(v):
    return "" if v is None or pd.isna(v) or v < 500 else f"{v / 1_000:,.0f}K"


def fmt_yield(v):
    return "" if v is None or pd.isna(v) or v == 0 else f"{v:.0f}"


def auto_bu(mx: float) -> tuple:
    if mx >= 500e6:
        return 1e9, "B bu"
    if mx >= 1e6:
        return 1e6, "M bu"
    return (1e3, "K bu") if mx >= 1e3 else (1, "bu")


def auto_ac(mx: float) -> tuple:
    if mx >= 500e3:
        return 1e6, "M ac"
    return (1e3, "K ac") if mx >= 1e3 else (1, "ac")


def view_cfg(metric: str, change_view: str) -> dict:
    if change_view != "Current Year":
        return {"cscale": SAGE_DIV, "diverging": True, "clabel": "Change (%)", "hover_fmt": ":+.1f", "hover_sfx": "%", "label_unit": "% chg",
                "label_fn": fmt_chg, "rank_unit": "%", "rank_div": 1, "rank_fmt": "+.1f"}
    bu = {"cscale": SAGE_SEQ, "diverging": False, "hover_fmt": ":,.0f", "hover_sfx": " bu", "label_unit": "M bu", "label_fn": fmt_bu,
          "rank_unit": "M bu", "rank_div": 1_000_000, "rank_fmt": ",.2f"}
    ac = {"cscale": SAGE_SEQ, "diverging": False, "hover_fmt": ":,.0f", "hover_sfx": " ac", "label_unit": "K ac", "label_fn": fmt_acres,
          "rank_unit": "K ac", "rank_div": 1_000, "rank_fmt": ",.1f"}
    return {"Production (bu)": {**bu, "clabel": "Production<br>(bu)"},
            "Harvested Acres": {**ac, "cscale": "BuGn", "clabel": "Harvested<br>Acres"},
            "Yield (bu/ac)": {"cscale": SAGE_DIV, "diverging": False, "clabel": "Yield<br>(bu/ac)", "hover_fmt": ":.1f", "hover_sfx": " bu/ac",
                              "label_unit": "bu/ac", "label_fn": fmt_yield, "rank_unit": "bu/ac", "rank_div": 1, "rank_fmt": ".1f"}}[metric]


def _base_layout(title: str, size: int = 15, top: int = 50) -> dict:
    return dict(paper_bgcolor=DARK, plot_bgcolor=SURFACE, font=dict(color=TEXT, family="Arial"),
                title=dict(text=title, font=dict(size=size, color=ACCENT)), margin=dict(l=0, r=0, t=top, b=0))


# ── map plumbing ──────────────────────────────────────────────────────────────
def _repel(lon: float, lat: float, r: float, pts=None):
    """Push a label out to r degrees from any marker so a marker never covers it (default: the Dorans star)."""
    k = math.cos(math.radians(40.0))
    for plon, plat in ([(DORANS["lon"], DORANS["lat"])] if pts is None else pts):
        dx, dy = (lon - plon) * k, lat - plat
        d = math.hypot(dx, dy)
        if d < r:
            if d < 1e-6:
                dx, dy, d = 0.0, 1.0, 1.0
            lon, lat = plon + dx * r / d / k, plat + dy * r / d
    return lon, lat


def geo_view(geo: dict, pad_lon: float = 0.25, pad_lat: float = 0.2) -> dict:
    lats, lons = [], []

    def walk(o):
        if isinstance(o, list):
            if o and isinstance(o[0], (int, float)):
                lons.append(o[0])
                lats.append(o[1])
            else:
                for i in o:
                    walk(i)
    for f in geo["counties"]["features"]:
        walk(f["geometry"]["coordinates"])
    return {"lon": [min(lons) - pad_lon, max(lons) + pad_lon], "lat": [min(lats) - pad_lat, max(lats) + pad_lat]}


def extent_view(extent) -> dict:
    """extent = (lat, lon, radius miles) -> lon / lat ranges around that point."""
    lat, lon, r = extent
    return {"lon": [lon - r / (69.0 * math.cos(math.radians(lat))), lon + r / (69.0 * math.cos(math.radians(lat)))], "lat": [lat - r / 69.0, lat + r / 69.0]}


def frame_map(fig, geo: dict, extent=None) -> None:
    v = extent_view(extent) if extent else geo_view(geo)
    fig.update_geos(projection_type="mercator", lonaxis_range=v["lon"], lataxis_range=v["lat"], visible=False, bgcolor=DARK, landcolor=LAND,
                    showframe=False, showlakes=False)


def place_labels(fig, fips_list, values, centroids, label_fn, avoid=(), suffix=None, zoom: float = 1.0):
    """County value labels, biggest counties first, thinned so they don't collide; `suffix` = {fips: text} (an asterisk for an estimate)."""
    areas = [centroids[f][2] for f in fips_list if f in centroids]
    avg_area = float(np.mean(areas)) if areas else 0.1
    size = int(np.clip(10 + np.log(max(avg_area, 0.01) / 0.05) * 1.6, 9, 13) + (3 if zoom < 1 else 0))
    cands = []
    for fips, val in zip(fips_list, values):
        label = label_fn(val)
        if label and fips in centroids:
            cx, cy, area = centroids[fips]
            cands.append((area, cx, cy, label + (suffix or {}).get(fips, "")))
    cands.sort(reverse=True)
    min_sep = float(np.clip(0.12 + avg_area * 0.8, 0.14, 0.3)) * zoom
    placed, lons, lats, texts = [], [], [], []
    for area, cx, cy, label in cands:
        if not any((cx - px) ** 2 + (cy - py) ** 2 < min_sep ** 2 for px, py in placed):
            placed.append((cx, cy))
            cx, cy = _repel(cx, cy, 0.14)
            if avoid:
                cx, cy = _repel(cx, cy, 0.2, avoid)
            lons.append(cx)
            lats.append(cy)
            texts.append(label)
    if lons:
        fig.add_trace(go.Scattergeo(lon=lons, lat=lats, text=texts, mode="text", textfont=dict(color="#4b5563", size=size, family="Arial Black"),
                                    showlegend=False, hoverinfo="skip"))


def _z_range(cfg, z_vals):
    if cfg["diverging"]:
        m = max(max((abs(v) for v in z_vals if v is not None and not pd.isna(v)), default=1.0), 1.0)
        return -m, m
    pos = [v for v in z_vals if v and v > 0]
    return (min(pos) if pos else 0), (max(pos) if pos else 1)


def add_dorans(fig, legend_bottom: bool = False) -> None:
    fig.add_trace(go.Scattergeo(lon=[DORANS["lon"]], lat=[DORANS["lat"]], mode="markers", name="Dorans", showlegend=True,
                                text=[DORANS["name"]], hovertemplate="<b>%{text}</b><extra></extra>",
                                marker=dict(symbol="star", size=24, color=_STAR, line=dict(color=_STAR_EDGE, width=2.2))))
    leg = (dict(orientation="h", x=0.5, xanchor="center", y=-0.005, yanchor="top") if legend_bottom
           else dict(x=0.01, y=0.985, xanchor="left", yanchor="top"))
    fig.update_layout(legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor=BORDER, borderwidth=1, font=dict(size=12, color=TEXT), **leg))


# competition layers: (label, colour, size) per group
_COMP = {"named": ("Competing elevators (named)", "#dc2626", 13), "truck": ("Elevators bidding in the tracker (≤30 mi)", "#f59e0b", 10),
         "other": ("Other shipper / plant candidates", "#9aa5b1", 8)}


def _rail_hover(p: dict) -> str:
    bits = list(p.get("rail") or []) + ([p["company_rail"]] if p.get("company_rail") else [])
    return ("<br><i>Rail:</i> " + "<br>".join(bits)) if bits else ""


def add_competition(fig, rows: list) -> int:
    n = 0
    groups = {"named": [r for r in rows if r["confirmed"]], "truck": [r for r in rows if not r["confirmed"] and r.get("truck")],
              "other": [r for r in rows if not r["confirmed"] and not r.get("truck")]}
    for key, pts in groups.items():
        pts = [p for p in pts if p["lat"] is not None]
        if not pts:
            continue
        label, color, size = _COMP[key]
        fig.add_trace(go.Scattergeo(
            lon=[p["lon"] for p in pts], lat=[p["lat"] for p in pts], mode="markers", name=label,
            marker=dict(symbol="circle", size=size, color=color, line=dict(color="white", width=1.4)),
            text=[f"<b>{p['name']}</b><br>{p['kind']}<br>{p['place']}<br>{p['miles']} mi from Dorans" + _rail_hover(p) for p in pts],
            hovertemplate="%{text}<extra></extra>", showlegend=True))
        n += len(pts)
    return n


def add_plants(fig, plants: list, crop: str) -> None:
    """Illinois soy crush plants for beans, ethanol plants for corn."""
    kind = "crush" if crop == "Soybeans" else "ethanol"
    pts = [p for p in plants if p["kind"] == kind and (p.get("status") or "Run") != "Build"]
    if not pts:
        return
    fig.add_trace(go.Scattergeo(
        lon=[p["lon"] for p in pts], lat=[p["lat"] for p in pts], mode="markers", name="Soy crush plants" if kind == "crush" else "Ethanol plants",
        marker=dict(symbol="diamond", size=10, color="#7c3aed", line=dict(color="white", width=1.2)),
        text=[f"<b>{p['name']}</b><br>{p['city']}, IL" + (f"<br>{p['mbu']:.0f} M bu/yr" if p.get("mbu") else "")
              + (f"<br>{p['mgy']:.0f} M gal/yr" if p.get("mgy") else "") for p in pts],
        hovertemplate="%{text}<extra></extra>", showlegend=True))


def _finish(fig, title: str, sub: str, geo: dict, bottom: bool, extent=None) -> None:
    frame_map(fig, geo, extent)
    fig.update_layout(**_base_layout(f"{title}<br><sup>{sub}</sup>", 17, 60), height=(760 if extent else 860 if bottom else 800))
    if bottom:
        fig.update_layout(margin=dict(l=0, r=0, t=60, b=110))


def county_fig(df: pd.DataFrame, geo: dict, crop: str, year: int, metric: str, change_view: str, comp_rows=None, plants=None,
               forecast: bool = False, extent=None):
    """df: [County, fips, Value, is_estimated]. Estimated counties' labels end in an asterisk."""
    if df is None or df.empty:
        return None
    cfg = view_cfg(metric, change_view)
    view_label = metric if change_view == "Current Year" else f"{change_view} — {metric}"
    counties = geo["counties"]
    all_fips = [f["id"] for f in counties["features"]]
    val, name, est = dict(zip(df["fips"], df["Value"])), dict(zip(df["fips"], df["County"])), dict(zip(df["fips"], df["is_estimated"]))
    z, hover = [], []
    for f in all_fips:
        v = val.get(f)
        z.append(v if v is not None and not pd.isna(v) else None)
        sfx = " (Est)" if est.get(f) else ""
        lab = name.get(f, f)
        hover.append(f"{lab} County{sfx}: {cfg['label_fn'](v) if change_view != 'Current Year' else _hover_val(metric, v)}{cfg['hover_sfx']}"
                     if v else f"{lab} County: No data")
    z_min, z_max = _z_range(cfg, [v for v in z if v is not None])
    line = dict(color="#8fa6bb", width=1.1)
    fig = go.Figure()
    fig.add_trace(go.Choropleth(geojson=counties, featureidkey="id", locations=all_fips, z=[0] * len(all_fips), colorscale=[[0, PANEL], [1, PANEL]],
                                showscale=False, marker=dict(line=line), hoverinfo="skip"))
    fig.add_trace(go.Choropleth(
        geojson=counties, featureidkey="id", locations=all_fips, z=z, colorscale=cfg["cscale"], zmin=z_min, zmax=z_max, marker=dict(line=line),
        text=hover, hovertemplate="%{text}<extra></extra>",
        colorbar=dict(title=dict(text=cfg["clabel"], font=dict(color=TEXT, size=13)), tickfont=dict(color=TEXT, size=12), thickness=18, len=0.3,
                      x=0.01, xanchor="left", y=0.02, yanchor="bottom", bgcolor="rgba(255,255,255,0.85)")))
    rep = [f for f in all_fips if val.get(f) is not None and not pd.isna(val.get(f))]
    place_labels(fig, rep, [val[f] for f in rep], geo["centroids"], cfg["label_fn"], avoid=[(DORANS["lon"], DORANS["lat"])],
                 suffix={f: "*" for f in rep if est.get(f)}, zoom=(0.45 if extent else 1.0))
    if plants:
        add_plants(fig, plants, crop)
    if comp_rows:
        add_competition(fig, comp_rows)
    add_dorans(fig, bool(comp_rows))
    sub = f"Map labels in {cfg['label_unit']}" + ("  ·  * = county value estimated" if any(est.values()) else "")
    if forecast:
        sub += "  ·  forecast: USDA's state estimate split by each county's 3-year share"
    _finish(fig, f"NASS {year}{' forecast' if forecast else ''} {crop} — {view_label} | Illinois Counties", sub, geo, bool(comp_rows), extent)
    return fig


def _hover_val(metric, v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.1f}" if metric == "Yield (bu/ac)" else f"{v:,.0f}"


def _exteriors(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return [p[0] for p in polys]


def district_fig(view_df: pd.DataFrame, raw_df: pd.DataFrame, geo: dict, crop: str, year: int, metric: str, change_view: str,
                 est_districts: set, comp_rows=None, plants=None, forecast: bool = False, extent=None):
    """Counties coloured by NASS district value, bold district outlines, name + value labels."""
    if view_df is None or view_df.empty:
        return None
    cfg, abs_cfg = view_cfg(metric, change_view), view_cfg(metric, "Current Year")
    view_label = metric if change_view == "Current Year" else f"{change_view} — {metric}"
    dist_val, raw_map = dict(zip(view_df["District"], view_df["Value"])), dict(zip(raw_df["District"], raw_df["Value"]))
    dfeats = geo["districts"]["features"]
    districts = [f["properties"]["District"] for f in dfeats]
    z = [dist_val.get(d) if dist_val.get(d) is not None else 0 for d in districts]

    def hover(d, zv):
        s = abs_cfg["label_fn"](raw_map.get(d))
        if change_view != "Current Year" and zv:
            return f"<b>{d}</b><br>{s}<br>{'+' if zv >= 0 else ''}{zv:.1f}%"
        return f"<b>{d}</b><br>{s}"

    pos = [v for v in z if v > 0]
    if cfg["diverging"]:
        m = max(max((abs(v) for v in z), default=1.0), 1.0)
        z_min, z_max = -m, m
    else:
        z_min, z_max = 0, (max(pos) if pos else 1)
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geo["districts"], featureidkey="properties.District", locations=districts, z=z, colorscale=cfg["cscale"], zmin=z_min, zmax=z_max,
        marker=dict(line=dict(color=BORDER, width=0.3)),
        colorbar=dict(title=dict(text=cfg["clabel"], font=dict(color=TEXT, size=13)), tickfont=dict(color=TEXT, size=12), thickness=18, len=0.3,
                      x=0.01, xanchor="left", y=0.02, yanchor="bottom", bgcolor="rgba(255,255,255,0.85)"),
        text=[hover(d, v) for d, v in zip(districts, z)], hovertemplate="%{text}<extra></extra>"))
    cfips = [f["id"] for f in geo["counties"]["features"]]
    fig.add_trace(go.Choropleth(geojson=geo["counties"], featureidkey="id", locations=cfips, z=[0] * len(cfips),
                                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
                                marker=dict(line=dict(color="rgba(90,90,90,0.6)", width=0.8)), hoverinfo="skip"))
    xs, ys, lons, lats, texts = [], [], [], [], []
    for f in dfeats:
        for ring in _exteriors(f["geometry"]):
            xs += [p[0] for p in ring] + [None]
            ys += [p[1] for p in ring] + [None]
        d = f["properties"]["District"]
        dv = dist_val.get(d)
        flag = "<br>Est" if d in est_districts else ""
        texts.append(f"{d.upper()}{flag}<br>" + (f"{dv:+.1f}%" if change_view != "Current Year" and dv is not None else abs_cfg["label_fn"](raw_map.get(d))))
        lon, lat = _repel(f["properties"]["lon"] + LABEL_SHIFT.get(d, 0.0), f["properties"]["lat"], 0.3)
        lons.append(lon)
        lats.append(lat)
    fig.add_trace(go.Scattergeo(lon=xs, lat=ys, mode="lines", line=dict(color="white", width=3.2), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scattergeo(lon=lons, lat=lats, mode="text", text=texts, textfont=dict(color="black", size=10, family="Arial Black"),
                                showlegend=False, hoverinfo="skip"))
    if plants:
        add_plants(fig, plants, crop)
    if comp_rows:
        add_competition(fig, comp_rows)
    add_dorans(fig, bool(comp_rows))
    _finish(fig, f"NASS {year}{' forecast' if forecast else ''} {crop} — {view_label} | Illinois Ag Districts",
            "District = its counties added up" + ("  ·  Est = some counties filled in" if est_districts else ""), geo, bool(comp_rows), extent)
    return fig


# ── history + rankings ────────────────────────────────────────────────────────
def history_bar(series: dict, years: list, title: str, y_label: str = "", fmt: str = ".2f") -> go.Figure:
    colors = ["#0693e3", "#f59e0b", "#ef4444", "#a78bfa", "#16a34a"]
    fig = go.Figure()
    for i, (name, vals) in enumerate(series.items()):
        fig.add_trace(go.Bar(x=years, y=vals, name=name, marker_color=colors[i % len(colors)], marker_line_width=0,
                             text=[f"{v:{fmt}}" for v in vals], textposition="outside", textfont=dict(color=TEXT, size=9), cliponaxis=False))
    layout = _base_layout(title)
    layout.update(height=320, barmode="group", legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center", font=dict(color=TEXT, size=10)),
                  xaxis=dict(tickvals=years, ticktext=[str(y) for y in years], gridcolor=BORDER, tickfont=dict(color=MUTED)),
                  yaxis=dict(title=y_label, gridcolor=BORDER, tickfont=dict(color=MUTED), title_font=dict(color=MUTED)),
                  margin=dict(l=60, r=20, t=50, b=30))
    fig.update_layout(**layout)
    return fig


def _rank_layout(fig, title, n, cfg, view_label, l_margin=10):
    fig.update_layout(paper_bgcolor=DARK, plot_bgcolor=SURFACE, font=dict(color=TEXT, family="Arial"), title=dict(text=title, font=dict(size=14, color=ACCENT)),
                      height=max(380, n * 22 + 80), margin=dict(l=l_margin, r=90, t=50, b=20), bargap=0.18,
                      xaxis=dict(title=f"{view_label} ({cfg['rank_unit']})", gridcolor=BORDER, tickfont=dict(color=MUTED), title_font=dict(color=MUTED),
                                 zeroline=True, zerolinecolor=MUTED),
                      yaxis=dict(gridcolor=BORDER, tickfont=dict(color=TEXT, size=9), automargin=True))


def ranking_chart(df: pd.DataFrame, crop: str, year: int, metric: str, change_view: str, by_district: bool = False):
    """Horizontal county ranking; optionally grouped and coloured by district. df: [County, Value, District, DistrictCode]."""
    cfg = view_cfg(metric, change_view)
    view_label = metric if change_view == "Current Year" else f"{change_view} — {metric}"
    d = df.dropna(subset=["Value"]).copy()
    if d.empty:
        return go.Figure()
    fmt = cfg["rank_fmt"]
    raw_avg = d["Value"].mean()
    avg_disp = raw_avg / cfg["rank_div"]
    if by_district:
        d = d.sort_values(["DistrictCode", "Value"]).reset_index(drop=True)
        x = d["Value"] / cfg["rank_div"]
        fig = go.Figure(go.Bar(x=x, y=d["County"], orientation="h", marker_color=d["DistrictCode"].map(ASD_PALETTE).fillna(MUTED).tolist(),
                               marker_line_width=0, text=[f"{v:{fmt}}" for v in x], textposition="outside", textfont=dict(color=TEXT, size=8),
                               cliponaxis=False, customdata=d["District"].fillna("—").tolist(),
                               hovertemplate=f"%{{y}} — %{{customdata}}: %{{x:{fmt}}} {cfg['rank_unit']}<extra></extra>"))
        cum = 0
        for code in sorted(d["DistrictCode"].dropna().unique()):
            grp = d[d["DistrictCode"] == code]
            if cum > 0:
                fig.add_hline(y=cum - 0.5, line_color=BORDER, line_width=1.5, line_dash="dot")
            fig.add_annotation(x=0, y=cum + len(grp) / 2 - 0.5, xref="paper", yref="y", text=f"<b>{grp.iloc[0]['District'] or code}</b>",
                               font=dict(color=ASD_PALETTE.get(code, MUTED), size=9), showarrow=False, xanchor="right", xshift=-72)
            cum += len(grp)
        title, margin = f"Illinois County Rankings by Ag District — {crop} {view_label} (NASS {year})", 165
    else:
        d = d.sort_values("Value", ascending=True)
        x = d["Value"] / cfg["rank_div"]
        fig = go.Figure(go.Bar(x=x, y=d["County"], orientation="h", marker_color=[ACCENT if v >= raw_avg else "#e05252" for v in d["Value"]],
                               marker_line_width=0, text=[f"{v:{fmt}}" for v in x], textposition="outside", textfont=dict(color=TEXT, size=8),
                               cliponaxis=False, hovertemplate=f"%{{y}}: %{{x:{fmt}}} {cfg['rank_unit']}<extra></extra>"))
        title, margin = f"Illinois County Rankings — {crop} {view_label} (NASS {year})", 10
    fig.add_vline(x=avg_disp, line_color="#d97706", line_width=1.5, line_dash="dash", annotation_text=f"  Avg: {avg_disp:{fmt}} {cfg['rank_unit']}",
                  annotation_position="top left", annotation_font=dict(color="#d97706", size=10))
    _rank_layout(fig, title, len(d), cfg, view_label, margin)
    return fig


def _row_bg_text(rank: int, n: int):
    if n == 0:
        return SURFACE, TEXT
    p = rank / max(n - 1, 1)
    if rank == 0:
        return "#fecaca", "#991b1b"
    if rank == 1:
        return "#fee2e2", "#b91c1c"
    if rank == n - 1:
        return "#bbf7d0", "#166534"
    if rank == n - 2:
        return "#dcfce7", "#15803d"
    if p < 0.35:
        return "#fef2f2", TEXT
    if p > 0.65:
        return "#f0fdf4", TEXT
    return SURFACE, TEXT


def heatmap_table(rows: dict, years: list, title: str, unit: str = "M bu", divisor: float = 1e6, is_ratio: bool = False, total: dict | None = None,
                  total_label: str = "IL Total", fmt: str = ".1f", top_row: dict | None = None, top_row_label: str = "", cell_status: dict | None = None,
                  top_row_cell_status: dict | None = None, first_col: str = "Row") -> go.Figure:
    """Per-row heat map (top 2 green, bottom 2 red) with % vs LY, Olympic average, % of average, min / max and share of the total.
    rows: {label: {year: raw value or None}}; cell_status {label: {year: True}} marks estimated cells with an E."""
    _D, _P, _S, _BR, _T, _M, _A, _G = "#f5f7fa", "#edf1f7", "#e2e8f2", "#c8d5e3", "#1a2332", "#64748b", "#0693e3", "#d97706"

    def disp(v):
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else v / divisor

    def num(v):
        return "—" if v is None else f"{v:{fmt}}"

    def pct(v):
        return "—" if v is None else f"{'▲' if v >= 0 else '▼'} {abs(v):.1f}%"

    def olympic(vals):
        c = [v for v in vals if v is not None]
        if len(c) >= 4:
            c = sorted(c)[1:-1]
        return sum(c) / len(c) if c else None

    def row_colors(vals):
        valid = [(i, v) for i, v in enumerate(vals) if v is not None]
        n = len(valid)
        rank_of = {idx: r for r, (idx, _) in enumerate(sorted(valid, key=lambda x: x[1]))}
        bgs, fgs = [], []
        for i in range(len(vals)):
            if i not in rank_of:
                bgs.append(_S)
                fgs.append(_M)
            else:
                b, f = _row_bg_text(rank_of[i], n)
                bgs.append(b)
                fgs.append(f)
        return bgs, fgs

    labels, data, bg, fg, pinned = [], [], [], [], []
    if top_row and top_row_label:
        labels.append(f"▶  {top_row_label}")
        data.append([disp(top_row.get(y)) for y in years])
        bg.append(["#dbeafe"] * len(years))
        fg.append([_G] * len(years))
        pinned.append(True)
    for lbl in rows:
        vals = [disp(rows[lbl].get(y)) for y in years]
        b, f = row_colors(vals)
        labels.append(lbl)
        data.append(vals)
        bg.append(b)
        fg.append(f)
        pinned.append(False)
    if total:
        vals = [disp(total.get(y)) for y in years]
        b, f = row_colors(vals)
        labels.append(total_label)
        data.append(vals)
        bg.append(b)
        fg.append(f)
        pinned.append(True)
    n_rows = len(labels)
    latest, prev = years[-1], (years[-2] if len(years) >= 2 else None)
    s_ly, s_avg, s_pavg, s_min, s_max, s_share = [], [], [], [], [], []
    bg_ly, fg_ly, bg_pavg, fg_pavg = [], [], [], []
    for lbl, vals in zip(labels, data):
        clean = [v for v in vals if v is not None]
        cur = vals[years.index(latest)]
        pv = vals[years.index(prev)] if prev is not None else None
        for cond, out_s, out_bg, out_fg in ((cur and pv, s_ly, bg_ly, fg_ly),):
            if cond and pv != 0:
                p = (cur - pv) / abs(pv) * 100
                out_s.append(pct(p))
                out_bg.append("#dcfce7" if p >= 0 else "#fee2e2")
                out_fg.append("#166534" if p >= 0 else "#991b1b")
            else:
                out_s.append("—")
                out_bg.append(_S)
                out_fg.append(_M)
        avg = olympic(clean)
        s_avg.append(num(avg))
        if cur and avg:
            pa = (cur - avg) / abs(avg) * 100
            s_pavg.append(pct(pa))
            bg_pavg.append("#dcfce7" if pa >= 0 else "#fee2e2")
            fg_pavg.append("#166534" if pa >= 0 else "#991b1b")
        else:
            s_pavg.append("—")
            bg_pavg.append(_S)
            fg_pavg.append(_M)
        s_min.append(num(min(clean)) if clean else "—")
        s_max.append(num(max(clean)) if clean else "—")
        tot = disp(total.get(latest)) if total else None
        s_share.append(f"{cur / tot * 100:.1f}%" if not is_ratio and tot and tot > 0 and cur else "—")

    status = dict(cell_status or {})
    if top_row_cell_status and top_row_label:
        status[f"▶  {top_row_label}"] = top_row_cell_status

    def cell(r, c):
        s = num(data[r][c])
        return f"{s} E" if status.get(labels[r], {}).get(years[c], False) else s

    hdr = [first_col] + [str(y) for y in years] + ["% vs LY", f"Olympic Avg\n({unit})", "% of Avg", "Min", "Max", "% of IL"]
    vals = [labels] + [[cell(r, c) for r in range(n_rows)] for c in range(len(years))] + [s_ly, s_avg, s_pavg, s_min, s_max, s_share]
    fills = ([[(_BR if pinned[i] else _P) for i in range(n_rows)]] + [[bg[r][c] for r in range(n_rows)] for c in range(len(years))]
             + [bg_ly, [_S] * n_rows, bg_pavg, [_S] * n_rows, [_S] * n_rows, [_S] * n_rows])
    fonts = ([[(_G if pinned[i] else _T) for i in range(n_rows)]] + [[fg[r][c] for r in range(n_rows)] for c in range(len(years))]
             + [fg_ly, [_T] * n_rows, fg_pavg, [_T] * n_rows, [_A] * n_rows, [_G] * n_rows])
    fig = go.Figure(go.Table(
        columnwidth=[130] + [60] * len(years) + [70, 90, 70, 55, 55, 65],
        header=dict(values=hdr, fill_color=[_P] * len(hdr), font=dict(color=[_M] + [_T] * len(years) + [_M] * 6, size=11, family="Arial"),
                    align="center", height=28, line_color=_BR),
        cells=dict(values=vals, fill_color=fills, font=dict(color=fonts, size=11, family="Arial"), align=["left"] + ["right"] * (len(years) + 6),
                   height=24, line_color=_BR)))
    fig.update_layout(paper_bgcolor=_D, margin=dict(l=0, r=0, t=30, b=0), height=max(150, n_rows * 26 + 70), title=dict(text=title, font=dict(color=_A, size=13)))
    return fig


# ── draw territory ────────────────────────────────────────────────────────────
def territory_fig(lat, lon, share, bushels, nodes: list, geo: dict, crop: str, year: int, extent=None):
    """Lattice points coloured by the share of their bushels that goes to Dorans (node 0), sized by bushels; the competing buyers drawn on top."""
    keep = np.ones(len(lat), dtype=bool)
    if extent:
        v = extent_view(extent)
        keep = (lon >= v["lon"][0]) & (lon <= v["lon"][1]) & (lat >= v["lat"][0]) & (lat <= v["lat"][1])
    sz = np.clip(np.sqrt(bushels[keep] / max(float(bushels[keep].max()) if keep.any() else 1.0, 1.0)) * (16 if extent else 9) + 2, 2, 20)
    fig = go.Figure()
    cfips = [f["id"] for f in geo["counties"]["features"]]
    fig.add_trace(go.Choropleth(geojson=geo["counties"], featureidkey="id", locations=cfips, z=[0] * len(cfips), colorscale=[[0, PANEL], [1, PANEL]],
                                showscale=False, marker=dict(line=dict(color="#8fa6bb", width=1.0)), hoverinfo="skip"))
    fig.add_trace(go.Scattergeo(
        lon=lon[keep], lat=lat[keep], mode="markers", name="Draw", showlegend=False,
        marker=dict(size=sz, color=share[keep] * 100, colorscale=[[0, "#e5e7eb"], [0.15, "#bfdbfe"], [0.5, "#3b82f6"], [1, "#1e3a8a"]], cmin=0, cmax=100,
                    line=dict(width=0), opacity=0.9, colorbar=dict(title=dict(text="% to<br>Dorans", font=dict(color=TEXT, size=13)), thickness=18, len=0.3,
                                                                    x=0.01, xanchor="left", y=0.02, yanchor="bottom", bgcolor="rgba(255,255,255,0.85)")),
        text=[f"{s * 100:.0f}% to Dorans · {b / 1e3:,.0f}K bu" for s, b in zip(share[keep], bushels[keep])], hovertemplate="%{text}<extra></extra>"))
    others = [n for n in nodes[1:] if n["lat"] is not None]
    fig.add_trace(go.Scattergeo(lon=[n["lon"] for n in others], lat=[n["lat"] for n in others], mode="markers", name="Competing buyers",
                                marker=dict(symbol="circle", size=9, color="#dc2626", line=dict(color="white", width=1.3)),
                                text=[f"<b>{n['name']}</b><br>{n.get('miles', '')} mi from Dorans · adder {n.get('adder', 0):+.0f}¢" for n in others],
                                hovertemplate="%{text}<extra></extra>"))
    add_dorans(fig, False)
    _finish(fig, f"{year} {crop} draw territory — share of grain going to Dorans | Illinois",
            "Each dot = ~4 miles of county production, sized by bushels, coloured by Dorans' share", geo, False, extent)
    return fig
