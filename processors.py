"""Processor and terminal basis seasonals: one tab per buyer, corn and soybeans, a line per year.

Data is a snapshot of the basis tracker's archive (data/processors_history.json, pulled read-only from its database on 2026-10-29 by the
droplet; refresh by re-running the extraction). Each day holds that buyer's posted rows [delivery month, futures symbol, basis cents, is_spot, location].

The nearby basis for a day is the buyer's SPOT bid when it posts one (ADM does); otherwise the mean basis of the rows quoted against the earliest
futures month that day (Cargill, Bunge, CGB, Primient and Incobrasa post forward months only). A roll to the next contract can step the line.
"""
import json
import re
from datetime import date
from pathlib import Path

import periods as PER

DATA = Path(__file__).parent / "data" / "processors_history.json"
# tab label -> (key in the history file, crops to show, location note)
PROCESSORS = [
    ("ADM Decatur", "ADM Decatur", ("Corn", "Soybeans"), "Decatur, IL — corn and soy processing"),
    ("Primient Decatur", "Primient Decatur", ("Corn",), "Decatur, IL — corn processing"),
    ("ADM St. Louis", "ADM St. Louis", ("Corn", "Soybeans"), "St. Louis, MO — river elevator"),
    ("Cargill St. Louis", "Cargill East St. Louis", ("Corn", "Soybeans"), "East St. Louis, IL — river terminal"),
    ("Bunge Fairmont City", "Bunge Fairmont City", ("Corn", "Soybeans"), "Fairmont City, IL — river terminal"),
    ("CGB Cahokia", "CGB Cahokia", ("Corn", "Soybeans"), "Cahokia, IL — river terminal"),
    ("Bunge Cairo", "Bunge Cairo", ("Soybeans",), "Cairo, IL — soy processing"),
    ("Incobrasa", "Incobrasa Gilman", ("Soybeans",), "Gilman, IL — soy processing"),
]
_SYM = re.compile(r"Z[CS]([FGHJKMNQUVXZ])(\d\d)")
_MONTH = dict(zip("FGHJKMNQUVXZ", range(1, 13)))


# the basis tracker's (provider, location) pairs behind each history key (same list the snapshot was pulled with)
PAIRS = {
    "ADM Decatur": [("ADM", "Decatur, IL (Corn Processing)"), ("ADM", "Decatur, IL (Soy Processing)"), ("ADM", "ADM Decatur")],
    "Primient Decatur": [("Primient", "Decatur")],
    "ADM St. Louis": [("ADM", "St. Louis, MO (Elevator)"), ("ADM", "ADM St. Louis")],
    "Cargill East St. Louis": [("Cargill", "East St. Louis")],
    "Bunge Fairmont City": [("Bunge", "Fairmont City, IL")],
    "CGB Cahokia": [("CGB", "CGB - Cahokia")],
    "Bunge Cairo": [("Bunge", "Cairo, IL")],
    "Incobrasa Gilman": [("INCO", "Gilman, IL")],
}


def load_snapshot() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def snapshot_end(hist: dict) -> str:
    return max((d for v in hist.values() for days in v.values() for d in days), default="2000-01-01")


def live_rows(since: str) -> dict:
    """Days posted since `since` (YYYY-MM-DD) straight from the basis tracker's archive, which its scrapers and email imports keep current:
    {key: {crop: {day: [[month, symbol, basis, is_spot, location], ...]}}}. Raises if the archive can't be reached."""
    import rail_data as RD
    pairs = [(k, p, l) for k, ps in PAIRS.items() for p, l in ps]
    cond = " OR ".join("(s.provider=%s AND s.location=%s)" for _ in pairs)
    params = [v for _, p, l in pairs for v in (p, l)] + [since]
    rows = RD._rows(f"""SELECT s.timestamp, s.provider, s.location, r.grain, r.delivery_month, r.futures_symbol, r.basis_cents, r.is_spot
                        FROM snapshots s JOIN snapshot_rows r ON r.snapshot_id = s.id
                        WHERE ({cond}) AND s.timestamp >= %s ORDER BY s.timestamp""", tuple(params))
    key_of = {(p, l): k for k, p, l in pairs}
    out = {}
    for r in rows:
        g = (r["grain"] or "").lower()
        crop = "Corn" if "corn" in g else "Soybeans" if "soy" in g else None
        if crop is None or r["basis_cents"] is None:
            continue
        key = key_of[(r["provider"], r["location"])]
        out.setdefault(key, {}).setdefault(crop, {}).setdefault(str(r["timestamp"])[:10], []).append(
            [r["delivery_month"], r["futures_symbol"], r["basis_cents"], 1 if r["is_spot"] else 0, r["location"]])
    return out


def merge_live(hist: dict, live: dict, since: str) -> dict:
    """The snapshot with every day from `since` on replaced by the live pull (a day re-scraped changes its rows)."""
    out = {k: {c: {d: v for d, v in days.items() if d < since} for c, days in crops.items()} for k, crops in hist.items()}
    for k, crops in live.items():
        for c, days in crops.items():
            out.setdefault(k, {}).setdefault(c, {}).update(days)
    return {k: {c: dict(sorted(d.items())) for c, d in crops.items()} for k, crops in out.items()}


def load() -> tuple:
    """(history, note): the shipped snapshot topped up with whatever the basis tracker has posted since it; the snapshot alone, with a note, when the
    archive isn't reachable here."""
    hist = load_snapshot()
    since = snapshot_end(hist)
    try:
        import rail_data as RD
        if not RD.configured():
            return hist, f"Showing the snapshot through {since}: the basis tracker archive isn't connected, so newer bids aren't included."
        import streamlit as st

        @st.cache_data(ttl=3600, show_spinner="Adding the latest scraped bids…")
        def go(since_day):
            return live_rows(since_day)
        live = go(since)
        return merge_live(hist, live, since), ""
    except Exception as e:
        return hist, f"Showing the snapshot through {since}; the basis tracker archive couldn't be read ({e})."


def _contract(sym: str):
    m = _SYM.fullmatch(sym or "")
    return (int(m.group(2)), _MONTH[m.group(1)]) if m else None


def nearby(rows: list):
    """Nearby basis (cents) for one day's rows, or None."""
    spot = [r[2] for r in rows if r[3]]
    if spot:
        return sum(spot) / len(spot)
    dated = [(c, r[2]) for r in rows if (c := _contract(r[1]))]
    if not dated:
        return None
    first = min(c for c, _ in dated)
    v = [b for c, b in dated if c == first]
    return sum(v) / len(v)


def daily_series(hist: dict, key: str, crop: str) -> list:
    """[(date, nearby basis)] oldest first."""
    out = []
    for day, rows in hist.get(key, {}).get(crop, {}).items():
        v = nearby(rows)
        if v is not None:
            out.append((date.fromisoformat(day), v))
    return sorted(out)


def seasonal(series: list) -> dict:
    """{year: {iso week 1-52: mean basis}} — weekly means smooth the daily scatter and line the years up."""
    acc = {}
    for d, v in series:
        wk = min(d.isocalendar()[1], 52)
        acc.setdefault(d.year, {}).setdefault(wk, []).append(v)
    return {y: {w: sum(v) / len(v) for w, v in sorted(wks.items())} for y, wks in sorted(acc.items())}


def week_label(w: int) -> str:
    d = date.fromisocalendar(2025, w, 1)
    return d.strftime("%b %d").replace(" 0", " ")


def trucking() -> dict:
    return json.loads((Path(__file__).parent / "data" / "trucking.json").read_text(encoding="utf-8"))


def truck_options(tr: dict, tab: str, crop: str) -> list:
    """[(carrier, cents/bu)] to the destination a processor tab sits at, cheapest first. Fairmont City, Cargill and ADM St. Louis share the
    'St. Louis' rate (the sheet has one St. Louis line; Cahokia has its own)."""
    dest = tr["tab_destination"].get(tab)
    out = [(c, rates[dest][crop]) for c, rates in tr["carriers"].items() if dest in rates and crop in rates[dest]]
    return sorted(out, key=lambda t: t[1])


def destinations(hist: dict, crop: str) -> dict:
    """{tab label: (as-of day, {month: (basis, futures symbol)})} for every buyer that posts a `crop` bid, from each one's latest posted day."""
    out = {}
    for label, key, crops, _ in PROCESSORS:
        days = hist.get(key, {}).get(crop) if crop in crops else None
        if not days:
            continue
        d = max(days)
        bm = PER.by_month(days[d])
        if bm:
            out[label] = (d, bm)
    return out


def summary_rows(dest: dict, tr: dict, crop: str, view: str, today: date, n_months: int = 9) -> tuple:
    """(row labels, columns, skipped): rows = the next n_months delivery months; one column per destination with a bid; `view` 'Delivered' = the bid as
    posted, 'FOB Dorans' = the bid less the cheapest truck rate from Dorans (a destination with no trucking rate is skipped). Cells are (value, futures symbol)."""
    months = []
    y, m = today.year, today.month
    for _ in range(n_months):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    rows = [f"{PER.MONTHS[m - 1]} {str(y)[-2:]}" for y, m in months]
    cols, skipped = [], []
    for label, entry in dest.items():
        asof, bm = entry[0], entry[1]
        cents = 0
        if len(entry) > 2:                                         # a rail strip: its FOB Dorans strip is worked out from the freight, not the trucking sheet
            if view == "FOB Dorans":
                bm = entry[2]
                if not bm:
                    skipped.append(label)
                    continue
        elif view == "FOB Dorans":
            opts = truck_options(tr, label, crop)
            if not opts:
                skipped.append(label)
                continue
            cents = opts[0][1]
        cells = [(bm[m][0] - cents, bm[m][1]) if m in bm else None for _, m in months]
        cols.append({"label": label, "asof": asof, "cells": cells, "truck": cents})
    return rows, cols, skipped


_SUM_CSS = """<style>
table.sum{width:100%;border-collapse:collapse;font-size:.85rem}
table.sum th{font-size:.7rem;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.03em;padding:7px 10px;border-bottom:2px solid #e2e8f0;text-align:center;white-space:nowrap}
table.sum th small{display:block;font-weight:400;text-transform:none;letter-spacing:0;color:#9aa5b1}
table.sum td{padding:6px 10px;text-align:center;border-bottom:1px solid #f1f1f1;color:#333;white-space:nowrap;font-variant-numeric:tabular-nums}
table.sum td.lbl{text-align:left;font-weight:600;color:#2c3e50}
table.sum td.best{background:#eaf4fc;font-weight:700}
table.sum td.neg{color:#c00000}
table.sum td.stale{opacity:.55}
table.sum .fut{display:block;font-size:.65rem;color:#9aa5b1;font-weight:400}
.sumwrap{border-radius:10px;box-shadow:0 1px 6px rgba(0,0,0,.08);padding:8px;overflow-x:auto;background:#fff;margin:6px 0}
</style>"""


def summary_html(rows: list, cols: list, today: date) -> str:
    h = ['<div class="sumwrap"><table class="sum"><tbody><tr><th style="text-align:left">Delivery</th>']
    for c in cols:
        stale = (today - date.fromisoformat(c["asof"])).days > 5
        h.append(f'<th>{c["label"]}<small>{date.fromisoformat(c["asof"]):%b %d}{" · stale" if stale else ""}</small></th>')
    h.append("</tr>")
    for i, label in enumerate(rows):
        vals = [c["cells"][i][0] if c["cells"][i] else None for c in cols]
        top = max((v for v in vals if v is not None), default=None)
        h.append(f'<tr><td class="lbl">{label}</td>')
        for c, v in zip(cols, vals):
            stale = (today - date.fromisoformat(c["asof"])).days > 5
            if v is None:
                h.append("<td>—</td>")
                continue
            cls = ("best " if v == top and sum(x is not None for x in vals) > 1 else "") + ("neg " if v < 0 else "") + ("stale" if stale else "")
            sym = c["cells"][i][1]
            h.append(f'<td class="{cls.strip()}">{v:+.0f}<span class="fut">{sym}</span></td>')
        h.append("</tr>")
    h.append("</tbody></table></div>")
    return _SUM_CSS + "".join(h)


CN25 = "CN 25's (rail)"


def cn_destination() -> tuple:
    """({CN 25's label: (as-of day, {month: (bid, symbol)}, {month: FOB Dorans})}, note): the CN 25's corn bid from the Basis Tracker's rail archive.
    Empty with a note when the archive isn't reachable here."""
    import rail_data as RD
    if not RD.configured():
        return {}, "CN 25's isn't shown: the rail archive isn't connected."
    try:
        import cn_sheet
        import rail_fsc as RF
        import streamlit as st
        rows = cn_sheet._cached_bids()
        cells, d = cn_sheet._latest_cells(rows, "CN 25's")
        if not cells:
            return {}, "CN 25's has no bids posted yet."
        bm = {x["m"]: (x["bid"], x["futures"]) for x in cn_sheet.month_bids(cells)}      # packages split into months with the carry
        win = RF.window("CN", cn_sheet._diesel(), date.today())
        fob_bm = cn_sheet.dorans_fob_by_month(bm, "Corn", win, date.today(), ref="CN 25's")
        return {CN25: (str(d), bm, fob_bm)}, ""
    except Exception as e:
        return {}, f"CN 25's couldn't be read ({e})."


def spread_matrix(tr: dict, today: date) -> tuple:
    """(truck table rows, rail table rows) - the spreads the FOB Dorans view applies, nothing else.
    Truck: per destination tab and commodity, the cheapest carrier's cents/bu from Dorans (trucking.json; subtracted from that buyer's delivered bid).
    Rail: cents/bu to ADD to a CN bid to get FOB Dorans, by delivery month - freight(reference origin) less freight(Dorans, 25-49 cars), tariff at the month's USDA
    level plus the CN fuel surcharge on the estimated rail miles; split into the tariff part and the fuel part. No truck freight in a rail value."""
    truck = []
    for tab in sorted(tr["tab_destination"]):
        r = {"Destination": tab, "Trucked to": tr["tab_destination"][tab]}
        for crop in ("Corn", "Soybeans"):
            o = truck_options(tr, tab, crop)
            r[f"{crop} (¢/bu)"] = o[0][1] if o else None
            r[f"{crop} carrier"] = o[0][0] if o else ""
        truck.append(r)
    rail = []
    try:
        import cn_sheet as S
        import freight_data as FD
        import rail_fsc as RF
        rows = FD.load_cn()
        dor = next((r for r in rows if (r["origin"], r["state"], r["tier"]) == ("DORANS", "IL", "25-49 cars")), None)
        win = RF.window("CN", S._diesel(), today)
        months = []
        y, m = today.year, today.month
        for _ in range(9):
            months.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        names = [PER.MONTHS[m - 1] for _, m in months]
        up, fsc = S.uplift_and_fsc(names, win, today)
        field = FD.CN_RATE_FIELD[("Large", "Railroad")]
        refs = [("Thomasboro, 25-49 cars", S.ref_row(rows, "CN 25's"), "CN 25's bid"), ("Champaign, 105+ cars", S.champaign_row(rows), "CN 105s bid")]
        for label, ref, bid in refs:
            if ref is None or dor is None:
                continue
            row = {"From (bid is FOB)": label, "Applies to": bid, "Rail miles to Gulf, ref / Dorans": f"{S.CM.miles_to_gulf(ref['origin'], ref['state'])[0]:,.0f} / {S.CM.miles_to_gulf('DORANS', 'IL')[0]:,.0f}"}
            for nm in names:
                mo = S.month_of(nm)
                a = S.freight_cpb(ref, "Large", field, "Corn", mo, fsc, up, True)
                b = S.freight_cpb(dor, "Large", field, "Corn", mo, fsc, up, True)
                row[nm] = None if a is None or b is None else a - b
            tar = None
            try:
                tar = S.freight_cpb(ref, "Large", field, "Corn", S.month_of(names[0]), fsc, up, False) - S.freight_cpb(dor, "Large", field, "Corn", S.month_of(names[0]), fsc, up, False)
            except Exception:
                pass
            row["of which tariff only"] = tar
            rail.append(row)
    except Exception as e:
        rail.append({"From (bid is FOB)": f"rail spreads unavailable ({e})"})
    return truck, rail


def render_summary(hist: dict, tr: dict) -> None:
    import streamlit as st
    c1, c2 = st.columns([1, 1.4])
    crop = c1.radio("Commodity", ["Corn", "Soybeans"], horizontal=True, key="proc_sum_crop")
    view = c2.radio("View", ["Delivered bids", "FOB Dorans"], horizontal=True, key="proc_sum_view",
                    help="Delivered = the bid as the buyer posts it. FOB Dorans = that bid less the cheapest truck rate from Dorans to the buyer.")
    dest = destinations(hist, crop)                                       # only buyers that actually post a bid for this commodity
    cn_note = ""
    if crop == "Corn":
        cn, cn_note = cn_destination()
        dest.update(cn)
    names = list(dest)
    picked = st.multiselect("Destinations", names, default=names, key=f"proc_sum_dest_{crop}")
    chosen = {k: v for k, v in dest.items() if k in picked}
    today = date.today()
    rows, cols, skipped = summary_rows(chosen, tr, crop, "FOB Dorans" if view == "FOB Dorans" else "Delivered", today)
    if not cols:
        st.info("Pick at least one destination." if not chosen else "None of the picked destinations has a trucking rate from Dorans.")
        return
    st.markdown(summary_html(rows, cols, today), unsafe_allow_html=True)
    with st.expander("Spread matrix: what the FOB Dorans view applies", expanded=False):
        import pandas as pd
        trk, rl = spread_matrix(tr, today)
        st.markdown("**Truck, cents/bu from Dorans** (subtracted from the buyer's delivered bid; your trucking sheet, cheapest carrier per destination)")
        st.dataframe(pd.DataFrame(trk), hide_index=True, use_container_width=True,
                     column_config={"Corn (¢/bu)": st.column_config.NumberColumn(format="%.0f"), "Soybeans (¢/bu)": st.column_config.NumberColumn(format="%.0f")})
        st.markdown("**Rail, cents/bu added to a CN bid** to reach FOB Dorans (reference origin's freight less Dorans' freight, 25-49 car tariff, large car, fuel surcharge included; no truck freight)")
        st.dataframe(pd.DataFrame(rl), hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in (rl[0] if rl else {}) if c not in ("From (bid is FOB)", "Applies to", "Rail miles to Gulf, ref / Dorans")})
    st.caption(("Basis in cents against the futures month shown under each bid (each buyer quotes its own month, so read down a column more than across). "
                if view == "Delivered bids" else
                "Basis less the cheapest truck rate from Dorans, cents/bu; the futures month is the buyer's. ") +
               "Blue = the best bid in that delivery month. A month with a full bid uses it; with none, the FH / LH midpoint. Faded = last posted more than 5 days ago."
               + (f" No trucking rate on the sheet for: {', '.join(skipped)}." if skipped else "")
               + (" CN 25's is a rail bid: its FOB Dorans = the bid (the 25-49 car tier, taken as FOB Thomasboro) + CN freight from Thomasboro less CN freight from Dorans, both on the 25-49 car tariff, with the fuel surcharge. No truck freight is involved in a rail value." if "CN 25's (rail)" in [c['label'] for c in cols] else "")
               + (f" {cn_note}" if cn_note else ""))


def render() -> None:
    import plotly.graph_objects as go
    import streamlit as st

    hist, note = load()
    if note:
        st.warning(note)
    tr = trucking()
    import pandas as pd
    rows = [{"Carrier": c, "Destination": d, "Corn (¢/bu)": r.get("Corn"), "Soybeans (¢/bu)": r.get("Soybeans")}
            for c, dests in tr["carriers"].items() for d, r in dests.items()]
    with st.expander("Trucking rates from Dorans"):
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("St. Louis applies to ADM, Cargill and Bunge Fairmont City (the sheet has one St. Louis line). Netted back = the latest nearby basis less the cheapest truck rate.")
    tabs = st.tabs(["📊 Summary"] + [p[0] for p in PROCESSORS])
    with tabs[0]:
        render_summary(hist, tr)
    for tab, (label, key, crops, note) in zip(tabs[1:], PROCESSORS):
        with tab:
            st.caption(note)
            if tr["tab_destination"].get(label) is None:
                st.caption("No trucking rate on the sheet for this destination.")
            for crop in crops:
                ser = daily_series(hist, key, crop)
                if not ser:
                    st.info(f"No {crop.lower()} bids archived for {label}.")
                    continue
                seas = seasonal(ser)
                st.markdown(f"##### {crop} nearby basis — {label}")
                fig = go.Figure()
                years = list(seas)[-6:]                     # this year and the five before; older years bury the pattern
                shades = ["#c3ccd6", "#9aa9ba", "#6b9fd0", "#3b82c4", "#0693e3", "#0b4f8a"]
                for i, y in enumerate(years):
                    cur = y == years[-1]
                    col = "#32373c" if cur else shades[min(len(years) - 1 - i, len(shades) - 1)] if len(years) > 1 else "#32373c"
                    wk = list(seas[y])
                    fig.add_trace(go.Scatter(x=wk, y=[seas[y][w] for w in wk], name=str(y), mode="lines", connectgaps=True,
                                             line=dict(width=3 if cur else 1.5, color=col),
                                             hovertemplate=f"{y} wk %{{x}}: %{{y:.0f}}¢<extra></extra>"))
                ticks = list(range(1, 53, 4))
                fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="#fff", plot_bgcolor="#fff",
                                  yaxis=dict(title="¢/bu vs futures", gridcolor="#e2e8f0", zeroline=True, zerolinecolor="#94a3b8"),
                                  xaxis=dict(tickmode="array", tickvals=ticks, ticktext=[week_label(w) for w in ticks]),
                                  legend=dict(orientation="h", y=-0.15))
                st.plotly_chart(fig, use_container_width=True)
                first = ser[0][0]
                spot = any(r[3] for rows in hist[key][crop].values() for r in rows)
                opts = truck_options(tr, label, crop)
                if opts:
                    best = opts[0]
                    last_v = ser[-1][1]
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Latest nearby basis", f"{last_v:+.0f}¢", f"as of {ser[-1][0]:%b %d}", delta_color="off")
                    c2.metric("Truck from Dorans", f"{best[1]}¢", best[0] + (f" (+{opts[1][0]} {opts[1][1]}¢)" if len(opts) > 1 else ""), delta_color="off")
                    c3.metric("Netted back to Dorans", f"{last_v - best[1]:+.0f}¢", "basis less the cheapest truck", delta_color="off")
                    dest = tr["tab_destination"][label]
                    if dest in tr["notes"] and crop == "Soybeans":
                        st.caption(tr["notes"][dest])
                st.caption(f"Lines: the last six years with data. {len(ser):,} posted days, {first:%b %Y} to {ser[-1][0]:%b %d, %Y}. "
                           + ("Spot bid." if spot else "Earliest futures month quoted that day (no spot bid posted).")
                           + (" History only goes back this far in the archive, so there is no seasonal pattern to read yet." if (date.today() - first).days < 500 else ""))
