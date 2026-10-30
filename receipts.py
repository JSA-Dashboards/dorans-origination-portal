"""Dorans' grain receipts (the '5 YR RECEIPTS ANALYSIS' workbook, first tab) and their market share against county production.

The receipts are Farmers Grain Co of Dorans' own handle, so they are NOT in the (public) repo: they come from the DORANS_RECEIPTS secret (a JSON block),
else a local data/private/dorans_receipts.json (gitignored), else the workbook uploaded on the tab. Pure functions here; drawing in market_share_tab.py.

Reading the sheet: 'FYE n' (the fiscal year ending Aug of n) = fall n-1's harvest plus the after-harvest receipts that follow it, so FYE 25 = crop 2024. The sheet's
'FYE 26' cell points at the Fall 26 column (the harvest being received now), so it is NOT used as a total: crop 2025's total is its fall harvest + its after-harvest
receipts, and crop 2026 is the harvest received so far.
"""
import json
import re
from pathlib import Path

PRIVATE = Path(__file__).parent / "data" / "private" / "dorans_receipts.json"
CROPS = {"Corn": "CORN", "Beans": "BEANS"}            # sheet label -> the app's crop name below
CROP_NAME = {"Corn": "Corn", "Beans": "Soybeans"}


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def parse_xlsx(path_or_file) -> dict:
    """The first tab -> {"total": {crop: {crop_year: bu}}, "harvest": {...}, "after": {...}} with crop = Corn | Soybeans, crop_year as a string."""
    import openpyxl
    ws = openpyxl.load_workbook(path_or_file, data_only=True).worksheets[0]
    rows = {i: [c.value for c in r] for i, r in enumerate(ws.iter_rows(), start=1)}

    def find(label, start=1):
        for i in range(start, ws.max_row + 1):
            if any(isinstance(v, str) and v.strip().upper() == label for v in rows[i]):
                return i
        raise ValueError(f"'{label}' not found on the first tab")

    def block(title, nxt):
        top = find(title)
        hdr = rows[top + 1]
        cols = {j: str(h).strip() for j, h in enumerate(hdr) if isinstance(h, str) and re.fullmatch(r"(FYE|FALL)\s*\d+", h.strip(), re.I)}
        out = {}
        for i in range(top + 2, find(nxt, top + 2) if nxt else top + 8):
            lab = str(rows[i][0] or "").strip().upper()
            crop = {"CORN": "Corn", "BEANS": "Soybeans", "AFTER HARVEST CORN": "Corn", "AFTER HARVEST BEANS": "Soybeans"}.get(lab)
            if crop:
                out.setdefault(lab, {crop: {}})
                for j, h in cols.items():
                    v = _num(rows[i][j])
                    if v is not None:
                        out[lab][crop][re.sub(r"\D", "", h)] = v
        return out, cols
    total_b, _ = block("TOTAL RECEIPTS", "HARVEST RECEIPTS")
    harv_b, _ = block("HARVEST RECEIPTS", "TOTAL SHIPMENTS")
    out = {"total": {}, "harvest": {}, "after": {}, "ship": {}}
    # shipments: TOTAL SHIPMENTS block, CORN then its TRUCK / RAIL rows, BEANS then its TRUCK / RAIL rows; columns FYE / FY n
    top = find("TOTAL SHIPMENTS")
    hdr = rows[top + 1]
    scols = {j: int(re.sub(r"\D", "", str(h))) for j, h in enumerate(hdr) if isinstance(h, str) and re.fullmatch(r"(FYE|FY)\s*\d+", h.strip(), re.I)}
    crop = None
    for i in range(top + 2, min(top + 14, ws.max_row + 1)):
        lab = str(rows[i][0] or "").strip().upper()
        if lab in ("CORN", "BEANS"):
            crop = "Corn" if lab == "CORN" else "Soybeans"
        elif lab in ("TRUCK", "RAIL") and crop:
            d = out["ship"].setdefault(crop, {}).setdefault(lab.lower(), {})
            for j, n in scols.items():
                v = _num(rows[i][j])
                if v is not None:
                    d[str(2000 + n - 1 if n <= 25 else 2000 + n)] = v         # FYE n = crop n-1; the newest column is the current year to date (crop 2026)
        elif lab.startswith("AFTER HARVEST"):
            break
    for lab, d in total_b.items():
        for crop, vals in d.items():
            if lab in ("CORN", "BEANS"):
                out["total"][crop] = {str(2000 + int(k) - 1): v for k, v in vals.items() if int(k) <= 25}      # FYE n -> crop n-1; FYE 26 is a pointer, left out
    for lab, d in harv_b.items():
        for crop, vals in d.items():
            tgt = "harvest" if lab in ("CORN", "BEANS") else "after"
            out[tgt][crop] = {str(2000 + int(k)): v for k, v in vals.items()}
    return out


def load_saved():
    """The receipts dict from the secret or the local private file, else None."""
    try:
        import streamlit as st
        raw = st.secrets.get("DORANS_RECEIPTS", None)
        if raw:
            return json.loads(raw) if isinstance(raw, str) else json.loads(json.dumps(dict(raw)))
    except Exception:
        pass
    if PRIVATE.exists():
        return json.loads(PRIVATE.read_text(encoding="utf-8"))
    return None


def by_crop_year(rec: dict, crop: str) -> dict:
    """{crop year: (bushels, kind)}: 'total' = the sheet's total receipts (FYE n -> crop n-1); 'built' = fall harvest + after-harvest receipts (crop 2025, whose
    FYE 26 cell is not used); 'to date' = the harvest received so far (the newest fall)."""
    out = {y: (v, "total") for y, v in rec["total"].get(crop, {}).items()}
    harv, aft = rec["harvest"].get(crop, {}), rec["after"].get(crop, {})
    for y in sorted(harv):
        if y in out:
            continue
        if y in aft:
            out[y] = (harv[y] + aft[y], "built")
        else:
            out[y] = (harv[y], "to date")
    return dict(sorted(out.items()))


def ship_by_crop_year(rec: dict, crop: str) -> dict:
    """{crop year: (truck bu, rail bu)} from the shipments block. Truck + rail is the total used (the sheet's hard-coded corn totals differ slightly in some years)."""
    d = rec.get("ship", {}).get(crop, {})
    years = sorted(set(d.get("truck", {})) | set(d.get("rail", {})))
    return {y: (d.get("truck", {}).get(y, 0.0), d.get("rail", {}).get(y, 0.0)) for y in years}


def share(receipts: float, production: float):
    return receipts / production * 100 if receipts and production else None
