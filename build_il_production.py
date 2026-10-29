"""One-off: Illinois county corn + soybean production, area and yield (NASS QuickStats) -> data/il_county_prod.json.
Run locally with NASS_API_KEY in the environment (key never leaves this machine; only the snapshot ships)."""
import json, os, sys, time
import requests

KEY = os.environ["NASS_API_KEY"]
URL = "https://quickstats.nass.usda.gov/api/api_GET/"
CROPS = {"Corn": ("CORN", "GRAIN"), "Soybeans": ("SOYBEANS", "ALL UTILIZATION PRACTICES")}
STATS = {"PRODUCTION": "production", "AREA HARVESTED": "harvested", "YIELD": "yield"}
YEARS = range(2015, 2026)

def pull(commodity, cls, stat, year):
    # one call per crop+statistic for the whole year range (the per-year version took ~an hour)
    p = dict(key=KEY, format="JSON", source_desc="SURVEY", commodity_desc=commodity,
             agg_level_desc="COUNTY", state_alpha="IL", statisticcat_desc=stat, year__GE=YEARS.start, year__LE=YEARS.stop - 1)
    r = requests.get(URL, params=p, timeout=180)
    if r.status_code == 400:
        return []                                   # NASS answers 400 when nothing matches
    r.raise_for_status()
    return r.json().get("data", [])

out = {}
for crop, (com, cls) in CROPS.items():
    for stat, name in STATS.items():
        for _ in [0]:
            for row in pull(com, cls, stat, None):
                if row.get("util_practice_desc") != cls: continue
                if row.get("prodn_practice_desc") not in ("ALL PRODUCTION PRACTICES", None, ""): continue
                if row.get("domain_desc") != "TOTAL" or row.get("class_desc") not in ("ALL CLASSES", "GRAIN"): continue
                if row["unit_desc"] not in ("BU", "BU / ACRE", "ACRES"): continue
                v = row["Value"].replace(",", "").strip()
                if not v.replace(".", "").isdigit(): continue          # (D) withheld etc.
                fips = row["state_ansi"] + row["county_ansi"]
                if not row["county_ansi"] or row["county_code"] == "998": continue   # "other (combined) counties"
                c = out.setdefault(crop, {}).setdefault(fips, {"name": row["county_name"].title(), "asd_code": row["asd_code"].strip(),
                                                                "asd": row["asd_desc"].title(), "years": {}})
                c["years"].setdefault(row["year"], {})[name] = float(v)
            time.sleep(0.3)
    print(crop, len(out.get(crop, {})), "counties", file=sys.stderr)
json.dump(out, open("data/il_county_prod.json", "w"), separators=(",", ":"))
