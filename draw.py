"""Draw territory for Dorans: where the grain around Dorans naturally goes, against the elevators and plants that compete for it.

A micro version of the Draw Territory model in the NASS / RMA dashboard (county grain -> buyer, with limited crossover between buyers): every point of a ~4 mile
lattice carries its county's production (the county total spread evenly over its points), and sends it to the buyers in reach in proportion to
exp(-net cost / tau), where a buyer's net cost to a producer = haul cents (miles x cents per bu-mile) - that buyer's bid adder. A small tau = the nearest / best
buyer takes nearly everything; a large tau = more crossover. Every bushel is placed (or left unplaced when no buyer is within the maximum haul).

Pure numpy; the lattice is data/il_lattice.json (build_il_lattice.py).
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
EARTH_MI = 3958.8


def load_lattice() -> dict:
    d = json.loads((HERE / "data" / "il_lattice.json").read_text(encoding="utf-8"))
    return {"lon": np.array(d["lon"]), "lat": np.array(d["lat"]), "fips": np.array(d["fips"]), "n": np.array(d["n"], dtype=float)}


def miles_matrix(lat, lon, nlat, nlon) -> np.ndarray:
    """Great-circle miles, points x nodes."""
    p1, p2 = np.radians(lat)[:, None], np.radians(nlat)[None, :]
    dl = np.radians(nlon)[None, :] - np.radians(lon)[:, None]
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_MI * np.arcsin(np.sqrt(h))


def compute(lat, lon, bushels, nodes: list, freight: float, tau: float, max_haul: float, road: float = 1.25) -> dict:
    """lat / lon / bushels: per lattice point. nodes: [{name, lat, lon, adder}] (adder = cents/bu that buyer adds to its bid), index 0 = Dorans.
    freight = cents per bu per ROAD mile; straight-line miles are scaled by `road` (a typical circuity). Returns
      share   points x nodes   share of each point's bushels each buyer gets (rows sum to 1, or 0 where no buyer is in reach)
      miles   points x nodes   straight-line miles
      bu      per node         bushels drawn
      unplaced                 bushels with no buyer within max_haul"""
    nlat, nlon = np.array([n["lat"] for n in nodes]), np.array([n["lon"] for n in nodes])
    add = np.array([float(n.get("adder", 0.0)) for n in nodes])
    mi = miles_matrix(lat, lon, nlat, nlon)
    cost = freight * road * mi - add[None, :]
    reach = mi <= max_haul
    z = np.where(reach, -cost / max(tau, 1e-6), -np.inf)
    zmax = np.max(z, axis=1, keepdims=True)
    zmax = np.where(np.isfinite(zmax), zmax, 0.0)
    e = np.where(reach, np.exp(z - zmax), 0.0)
    tot = e.sum(axis=1, keepdims=True)
    share = np.divide(e, tot, out=np.zeros_like(e), where=tot > 0)
    got = share * bushels[:, None]
    return {"share": share, "miles": mi, "bu": got.sum(axis=0), "unplaced": float(bushels[tot[:, 0] == 0].sum())}


def by_county(fips, bushels, share_col) -> dict:
    """{fips: (county bushels in the lattice, bushels drawn by the node)}."""
    out = {}
    for f, b, s in zip(fips, bushels, share_col):
        a = out.setdefault(f, [0.0, 0.0])
        a[0] += b
        a[1] += b * s
    return {f: (v[0], v[1]) for f, v in out.items()}
