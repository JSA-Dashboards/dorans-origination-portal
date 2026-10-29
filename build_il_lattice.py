"""data/il_lattice.json: a ~4 mile lattice of points inside Illinois counties, each carrying its county's FIPS and weight 1/(points in that county), so a county's
production spread evenly over its points adds back to the county total. Gives the draw-territory model finer than county resolution (the rma-production-map heat
layer does the same with a lattice). Build-time only (shapely)."""
import json
from pathlib import Path
import numpy as np
from shapely.geometry import shape, Point
from shapely.prepared import prep

HERE = Path(__file__).parent
geo = json.loads((HERE / "data" / "il_asd_geo.json").read_text(encoding="utf-8"))
STEP = 0.055
pts = []
for f in geo["counties"]["features"]:
    g = shape(f["geometry"])
    pg = prep(g)
    x0, y0, x1, y1 = g.bounds
    inside = [(round(x, 4), round(y, 4)) for x in np.arange(x0 + STEP / 2, x1, STEP) for y in np.arange(y0 + STEP / 2, y1, STEP) if pg.contains(Point(x, y))]
    if not inside:
        c = g.representative_point()
        inside = [(round(c.x, 4), round(c.y, 4))]
    for x, y in inside:
        pts.append((x, y, f["id"], len(inside)))
out = {"lon": [p[0] for p in pts], "lat": [p[1] for p in pts], "fips": [p[2] for p in pts], "n": [p[3] for p in pts]}
(HERE / "data" / "il_lattice.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
print(len(pts))
