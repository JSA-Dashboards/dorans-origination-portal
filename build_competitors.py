"""Builds data/competitors.json: the elevators Kolten named (confirmed) plus candidates found in the rail-shipper directories,
crush and ethanol lists within RADIUS miles of Dorans. Run again after refreshing rma-production-map/data/rail_map/map_points.json."""
import json, math
from pathlib import Path

DORANS = (39.5511, -88.3445)          # Dorans, Coles County (OSM/Nominatim)
RADIUS = 45
SRC = Path(__file__).parent.parent / "rma-production-map" / "data" / "rail_map" / "map_points.json"


def miles(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


# Named by Kolten 2026-10-29. Coordinates: TGM Arcola/Neoga and ADM Tuscola from the rail shipper directories; Coles from OpenStreetMap;
# Primient Mattoon / Primient Coles / ADM Sullivan are placed at their TOWN (approximate - the plant/elevator itself isn't in any list I have);
# Jones Switch was dropped (Kolten, 2026-10-29).
NAMED = [
    ("Primient Coles", "Primient", "Coles Station, 9838 N County Rd 000 E, Mattoon, IL", 39.5174, -88.4709, "street address (Census geocoder)", "Elevator"),
    ("Primient Mattoon", "Primient", "7278 E County Rd 550 N, Mattoon, IL", 39.4533, -88.3350, "street address (Census geocoder)", "Elevator"),
    ("ADM Sullivan", "ADM", "417 E Water St, Sullivan, IL", 39.5971, -88.6034, "street address (Census geocoder)", "Elevator"),
    ("ADM Tuscola", "ADM", "Tuscola, IL", 39.7999, -88.2885, "basis tracker pin", "Elevator"),
    ("TGM Arcola", "TGM", "Arcola, IL", 39.6832, -88.30913, "basis tracker pin", "Elevator"),
    ("TGM Neoga", "TGM", "Neoga, IL", 39.31608, -88.45233, "basis tracker pin", "Elevator"),
]
SKIP = ("FRITO",)                      # snack maker, not a grain bid
out = []
for n, co, loc, la, lo, src, kind in NAMED:
    out.append(dict(name=n, company=co, place=loc, lat=la, lon=lo, source=src, kind=kind, confirmed=True, truck=True,
                    miles=None if la is None else round(miles(DORANS, (la, lo)), 1)))

pts = json.loads(SRC.read_text(encoding="utf-8"))
pins = json.loads((Path(__file__).parent / "data" / "tracker_pins_near.json").read_text(encoding="utf-8"))["rows"]
named_xy = [(o["lat"], o["lon"]) for o in out if o["lat"]]
# Elevators with a posted bid in the basis tracker within 30 miles (trucks deliver to these): added first so they win over the shipper-list duplicates
NAMED_PINS = {("Primient", "Mattoon"), ("Primient", "Coles"), ("ADM", "Sullivan, IL"), ("ADM", "Tuscola, IL"),
              ("Total Grain Marketing", "Arcola, IL"), ("Total Grain Marketing", "Neoga, IL")}      # the named sites above, already placed
for prov, loc, st_, kind, la, lo in pins:
    if (prov, loc) in NAMED_PINS:
        continue
    dd = miles(DORANS, (la, lo))
    if dd > 30 or any(miles((la, lo), xy) < 1.0 for xy in named_xy):
        continue
    name = f"{prov} {loc}" if not loc.startswith(prov.split()[0]) else loc
    out.append(dict(name=name, company=prov, place=loc, lat=la, lon=lo, source="basis tracker pin", kind=f"{kind} (bids in tracker)",
                    confirmed=False, truck=True, miles=round(dd, 1)))
    named_xy.append((la, lo))
seen = set()


def add(name, state, lat, lon, kind, source, extra=""):
    d = miles(DORANS, (lat, lon))
    if state not in ("IL", "IN") or d > RADIUS or any(s in name.upper() for s in SKIP):
        return
    if any(miles((lat, lon), xy) < 1.5 for xy in named_xy):       # already one of the named sites
        return
    key = (name.upper(), round(lat, 2), round(lon, 2))
    if key in seen:
        return
    seen.add(key)
    out.append(dict(name=name.title() if name.isupper() else name, company="", place=extra, lat=lat, lon=lon, source=source, kind=kind,
                    confirmed=False, truck=False, miles=round(d, 1)))


for p in pts["shipper"]:
    add(p["name"], p["state"], p["lat"], p["lon"], "Elevator / shipper", f"{p['road']} shipper directory", p["road"])
for k, label in (("crush", "Soy crush plant"), ("ethanol", "Ethanol / corn processor")):
    for p in pts[k]:
        add(p["name"], p["state"], p["lat"], p["lon"], label, "NASS/RMA map lists", p.get("city", ""))
# Rail access and loading capacity, from the Rail Origins & Destinations directories (CN origins, UP shuttle list, NS loaders, CSX shippers) and what Kolten told me
# (2026-10-29: ADM can hit CN, CSX and UP, Oakland too). Cars = the loading size as the railroad's list shows it; a blank means no directory lists the site.
RAIL = {
    "ADM Tuscola": ["CN: 105 cars (CN origins list)", "UP: 110-car shuttle origin (UP 4052-A list, Oct 2023)"],
    "ADM Oakland, IL": ["CN: 105 cars (CN origins list)"],
    "TGM Arcola": ["CN: 50 cars (CN origins list) - not a 105-car point"],
    "TGM Neoga": ["CN: 105 cars (CN origins list)", "NS: 20-car track, 817,000 bu storage, not a unit-train loader (NS list)"],
    "Primient Coles": ["CN: 25-car loader (Kolten, 2026-10-29); the CN origins list shows Coles at 50 cars (listed as Premient)"],
    "Primient Mattoon": ["CN: 50 cars (CN origins list, listed as Premient)"],
    "Total Grain Marketing Casey, IL": ["CSX: express service (CSX list)"],
}
COMPANY_RAIL = {"ADM": "ADM can reach CN, CSX and UP (Kolten); Decatur is also a CSX unit-train and NS 120-car loader"}
for o in out:
    o["rail"] = RAIL.get(o["name"], [])
    o["company_rail"] = COMPANY_RAIL.get(o["name"].split()[0], "")
out.sort(key=lambda o: (not o["confirmed"], o["miles"] if o["miles"] is not None else 999))
json.dump(dict(dorans=dict(name="Farmers Grain Co of Dorans", lat=DORANS[0], lon=DORANS[1]), radius=RADIUS, rows=out),
          open(Path(__file__).parent / "data" / "competitors.json", "w", encoding="utf-8"), indent=1)
print(len(out), sum(o["confirmed"] for o in out))
