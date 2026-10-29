"""NASS official Illinois state totals (production, area harvested) per year -> data/il_county_prod.json under "_state", the totals the county fill is made to add up to."""
import json, os
import requests
KEY = os.environ["NASS_API_KEY"]; URL = "https://quickstats.nass.usda.gov/api/api_GET/"
CROPS = {"Corn": ("CORN", "GRAIN"), "Soybeans": ("SOYBEANS", "ALL UTILIZATION PRACTICES")}
STATS = {"PRODUCTION": "production", "AREA HARVESTED": "harvested"}
d = json.load(open("data/il_county_prod.json", encoding="utf-8")); d.pop("_asd", None); d["_state"] = {}
for crop, (com, util) in CROPS.items():
    for stat, name in STATS.items():
        r = requests.get(URL, timeout=180, params=dict(key=KEY, format="JSON", source_desc="SURVEY", commodity_desc=com, agg_level_desc="STATE",
                         state_alpha="IL", statisticcat_desc=stat, year__GE=2015, year__LE=2025))
        for x in (r.json().get("data", []) if r.ok else []):
            if x["reference_period_desc"] != "YEAR" or x["util_practice_desc"] != util or x["domain_desc"] != "TOTAL" or x["class_desc"] not in ("ALL CLASSES", "GRAIN"): continue
            if x["unit_desc"] not in ("BU", "ACRES"): continue
            v = x["Value"].replace(",", "").strip()
            if v.replace(".", "").isdigit():
                d["_state"].setdefault(crop, {}).setdefault(x["year"], {})[name] = float(v)
        print(crop, stat, r.status_code)
json.dump(d, open("data/il_county_prod.json", "w", encoding="utf-8"), separators=(",", ":"))
print({c: {y: v for y, v in d["_state"][c].items() if y in ("2024", "2025")} for c in d["_state"]})
