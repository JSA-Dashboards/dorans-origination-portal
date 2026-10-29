"""data/il_asd_geo.json: Illinois county outlines (as il_county_geo.json) plus the NASS districts dissolved from them, with label points and areas.
Needs shapely (build-time only). Rings are re-oriented CLOCKWISE for plotly's choropleth."""
import json
from pathlib import Path
from shapely.geometry import shape, mapping, MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

HERE = Path(__file__).parent
counties = json.loads((HERE / "data" / "il_county_geo.json").read_text(encoding="utf-8"))
prod = json.loads((HERE / "data" / "il_county_prod.json").read_text(encoding="utf-8"))
asd_of = {f: (c["asd_code"], c["asd"]) for f, c in prod["Corn"].items()}


def cw(g):
    return orient(g, -1.0) if g.geom_type == "Polygon" else MultiPolygon([orient(p, -1.0) for p in g.geoms])


cfeats, cent, groups = [], {}, {}
for f in counties["features"]:
    g = shape(f["geometry"])
    c = g.representative_point()
    cent[f["id"]] = [round(c.x, 4), round(c.y, 4), round(g.area, 4)]
    cfeats.append(f)
    if f["id"] in asd_of:
        groups.setdefault(asd_of[f["id"]], []).append(g)
dfeats = []
for (code, name), gs in sorted(groups.items()):
    u = cw(unary_union([g.buffer(0.0005) for g in gs]).buffer(-0.0005))
    c = u.representative_point()
    dfeats.append({"type": "Feature", "properties": {"District": name, "code": code, "lon": round(c.x, 4), "lat": round(c.y, 4)},
                   "geometry": mapping(u)})
out = {"counties": {"type": "FeatureCollection", "features": cfeats}, "districts": {"type": "FeatureCollection", "features": dfeats},
       "centroids": cent}
(HERE / "data" / "il_asd_geo.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
print(len(cfeats), len(dfeats), [d["properties"]["District"] for d in dfeats])
