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


def year_values(prod: dict, crop: str, year: int, fill: bool = True, fc_yield=None) -> tuple:
    """{fips: {production, harvested, est}} for one year, made to add up to NASS's official Illinois totals the way the NASS / RMA dashboard's
    heat map does (heat_map.fill_withheld): the counties NASS published keep their published numbers; what they leave of the state total is
    spread over the withheld counties in proportion to the share each held of the state in the latest earlier year (up to LOOKBACK back)
    NASS published it. A withheld county with no earlier figure gets nothing. Returns (values, info)."""
    state = prod.get("_state", {}).get(crop, {})
    counties = prod.get(crop, {})
    out = {f: {"production": None, "harvested": None, "est": False} for f in counties}
    info = {"published": {}, "estimated_n": 0, "short": {}}
    if year == estimate_year(prod, crop):
        return _forecast_values(prod, crop, year, out, info, fc_yield)
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


def _forecast_values(prod: dict, crop: str, year: int, out: dict, info: dict, fc_yield=None) -> tuple:
    """A year with no county survey yet: USDA's state estimate for `year` x each county's average share of the state over the three prior
    completed years (the NASS / RMA dashboard's `_sd_forecast_production` logic, taken to counties; its district numbers are these counties
    dissolved). The shares are on the filled basis, so they add up to one and the counties add up to USDA's state number. Production and
    harvested acres are each spread this way, so a county's yield is its recent production-to-acres mix on USDA's statewide totals."""
    state = prod.get("_state", {}).get(crop, {})
    for stat in SUM_MEASURES:
        tot = state.get(str(year), {}).get(stat)
        if stat == "production" and fc_yield:                       # the user's own yield: production = yield x USDA's harvested acres
            tot = fc_yield * (state.get(str(year), {}).get("harvested") or 0) or tot
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


def county_rows(prod: dict, geo: dict, crop: str, years: list, fill: bool = True, fc_yield=None) -> list:
    """One row per county for the chosen year(s): each year is completed to the state total (year_values), then production and harvested
    acres are averaged over the years; yield = production / harvested over the same years. `est` = any year's figure was filled in."""
    feats = geo["counties"]["features"] if "counties" in geo else geo["features"]
    cent = {f["id"]: (f["properties"]["lat"], f["properties"]["lon"]) for f in feats if "lat" in f["properties"]}
    per = [year_values(prod, crop, y, fill, fc_yield)[0] for y in years]
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
                                           "py": 0.0, "hy": 0.0, "counties": 0, "est": 0})
        if r["production"] is not None:
            a["production"] += r["production"]
            a["counties"] += 1
            a["est"] += 1 if r.get("est") else 0
        if r["harvested"] is not None:
            a["harvested"] += r["harvested"]
        if r["production"] is not None and r["harvested"]:
            a["py"] += r["production"]
            a["hy"] += r["harvested"]
    res = []
    for a in out.values():
        a["yield"] = a["py"] / a["hy"] if a["hy"] else None
        res.append({k: a[k] for k in ("asd_code", "asd", "production", "harvested", "yield", "counties", "est")})
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


# ── views: the NASS tab's Metric x Change-view model ────────────────────────────────────────────────────────────
METRICS = {"Production (bu)": "production", "Harvested Acres": "harvested", "Yield (bu/ac)": "yield"}
CHANGE_OPTS = ["Current Year", "vs Prior Year", "vs 3-Yr Avg", "vs Selected Year"]


def entity_values(prod: dict, geo: dict, crop: str, year: int, key: str, fill: bool = True, fc_yield=None) -> tuple:
    """({fips: value}, {asd_code: value}, {fips: estimated?}, {fips: row}, {asd_code: asd row}) for one year and statistic."""
    rows = county_rows(prod, geo, crop, [year], fill, fc_yield)
    asd = asd_rows(rows)
    return ({r["fips"]: r[key] for r in rows}, {a["asd_code"]: a[key] for a in asd}, {r["fips"]: r["est"] for r in rows},
            {r["fips"]: r for r in rows}, {a["asd_code"]: a for a in asd})


def _chg(cur, base):
    return (cur - base) / abs(base) * 100 if cur is not None and base else None


def view_frames(prod: dict, geo: dict, crop: str, key: str, year: int, change: str, comp=None, fill: bool = True, fc_yield=None):
    """(county_df, district_df) for the map and tables. county_df: County, fips, District, DistrictCode, Value (the view: the value, or its % change),
    Raw (the year's value), is_estimated. district_df: District, DistrictCode, Value, Raw, est (counties filled), counties."""
    import pandas as pd
    cur_c, cur_d, est, crow, drow = entity_values(prod, geo, crop, year, key, fill, fc_yield)
    done = set(years_of(prod, crop))
    bases = []
    if change == "vs Prior Year":
        bases = [year - 1]
    elif change == "vs 3-Yr Avg":
        bases = [year - 3, year - 2, year - 1]
    elif change == "vs Selected Year" and comp:
        bases = [comp]
    bases = [b for b in bases if b in done]
    base_c, base_d = {}, {}
    if bases:
        per = [entity_values(prod, geo, crop, b, key, fill) for b in bases]
        for f in cur_c:
            v = [p[0].get(f) for p in per if p[0].get(f) is not None]
            base_c[f] = sum(v) / len(v) if v else None
        for d in cur_d:
            v = [p[1].get(d) for p in per if p[1].get(d) is not None]
            base_d[d] = sum(v) / len(v) if v else None
    cdf = pd.DataFrame([{"County": crow[f]["county"], "fips": f, "District": crow[f]["asd"], "DistrictCode": crow[f]["asd_code"],
                         "Raw": cur_c[f], "Value": (_chg(cur_c[f], base_c.get(f)) if change != "Current Year" else cur_c[f]),
                         "is_estimated": est[f]} for f in cur_c])
    ddf = pd.DataFrame([{"District": drow[d]["asd"], "DistrictCode": d, "Raw": cur_d[d],
                         "Value": (_chg(cur_d[d], base_d.get(d)) if change != "Current Year" else cur_d[d]),
                         "est": drow[d]["est"], "counties": drow[d]["counties"]} for d in cur_d])
    return cdf, ddf


def state_total(prod: dict, geo: dict, crop: str, year: int, key: str, fill: bool = True, fc_yield=None):
    rows = county_rows(prod, geo, crop, [year], fill, fc_yield)
    if key == "yield":
        p = sum(r["production"] for r in rows if r["production"] is not None and r["harvested"])
        h = sum(r["harvested"] for r in rows if r["production"] is not None and r["harvested"])
        return p / h if h else None
    v = [r[key] for r in rows if r[key] is not None]
    return sum(v) if v else None
