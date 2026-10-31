"""CN rail FOB sheet for Farmers Grain Co of Dorans (Mattoon, IL).

Same method as the Rail Corridors app's CN tab, cut down to the origins that matter here: the CN 105s bid (corn; the beans twin
`CN 105s Beans`) is FOB Champaign for a 105-car shuttle, so an origin's FOB = bid + freight(Champaign, 105+ cars) - freight(origin).
Freight = CN tariff $/car (moved to the month's USDA level) + CN 7403 fuel surcharge $/car-mile x rail miles, / bu per car -> cents/bu.
Dorans only has a 25-49 car tariff rate (its 1-2 note) and Mattoon 25-49 and 50-104, so each tier is its own row and the tier is
named: a smaller block of cars pays more freight, which is the real cost of loading at Dorans rather than a 105-car shuttle point.

Pure functions (tested) take the bids and the freight inputs; `render()` does the reading and drawing.
"""
from datetime import date

import freight_data as FD
import cn_miles as CM

MARKETS = {"Corn": "CN 105s", "Soybeans": "CN 105s Beans"}
BID_MARKETS = {"Corn": ["CN 105s", "CN 25's"], "Soybeans": ["CN 105s Beans"]}   # one sheet per bid; the 25's is taken as FOB Champaign like the 105s
DEFAULT_ORIGINS = [("DORANS", "IL"), ("MATTOON", "IL"), ("COLES", "IL"), ("CHAMPAIGN", "IL")]
TOP_TIER = FD.CN_VOLUME_TIER_ORDER[-1]


def month_of(period: str):
    return FD.bn_period_first_month(period)


def freight_cpb(row, size, field, commodity, month, fsc_by_month, uplift_by_month, fsc_on=True, miles_over=None):
    """Freight in cents/bu for one tariff row in one month, or None when the fuel surcharge or the miles aren't known (so a cell
    shows '—' rather than a freight without its fuel)."""
    extra = float(uplift_by_month.get(month, 0))
    if fsc_on:
        key = (row["origin"], row["state"])
        mi = (miles_over or {}).get(key)
        if mi is None:
            mi = CM.miles_to_gulf(key[0], key[1])[0]
        f = fsc_by_month.get(month)
        if f is None or mi is None:
            return None
        extra += f * mi
    return FD.cn_freight_cpb(row[field], size, commodity, extra)


def fob(bid, champ_row, row, size, field, commodity, month, fsc_by_month, uplift_by_month, fsc_on=True):
    """bid (cents vs the futures tag, FOB Champaign) carried to `row`: bid + freight(Champaign) - freight(row)."""
    if bid is None:
        return None
    fc = freight_cpb(champ_row, size, field, commodity, month, fsc_by_month, uplift_by_month, fsc_on)
    fo = freight_cpb(row, size, field, commodity, month, fsc_by_month, uplift_by_month, fsc_on)
    return None if fc is None or fo is None else bid + fc - fo


def champaign_row(rows):
    return next((r for r in rows if r["origin"] == "CHAMPAIGN" and r["state"] == "IL" and r["tier"] == TOP_TIER), None)


def uplift_and_fsc(periods, fsc_window, today):
    """({month: tariff uplift $/car vs the seed}, {month: CN surcharge $/mile}) for the months the periods name."""
    seed = FD.cn_seed_level()
    up, fsc = {}, {}
    for p in periods:
        mo = month_of(p)
        if not mo:
            continue
        level, _ = FD.cn_tariff_level(mo, today)
        up[mo] = 0 if level is None else level - seed
        fsc[mo] = (fsc_window.get(FD._BN_MONTH3_REV[mo]) or {}).get("fsc")
    return up, fsc


def sheet_rows(rows, origins, size_source):
    """Tariff rows for the picked origins, in origin then tier order."""
    order = FD.CN_VOLUME_TIER_ORDER
    pick = [r for r in rows if (r["origin"], r["state"]) in set(origins) and r["tier"]]
    return sorted(pick, key=lambda r: (r["state"], r["origin"], order.index(r["tier"])))


def dorans_fob_by_month(bm: dict, commodity: str, fsc_window: dict, today: date, size="Large", source="Railroad", tier="25-49 cars") -> dict:
    """{month: (cents/bu, futures symbol)} for a CN bid strip {month: (bid, symbol)} FOB Champaign, carried to Dorans on its own tariff tier:
    bid + freight(Champaign, 105+ cars) - freight(Dorans, tier). The summary's FOB Dorans view for CN 25's."""
    rows = FD.load_cn()
    champ = champaign_row(rows)
    dor = next((r for r in rows if (r["origin"], r["state"], r["tier"]) == ("DORANS", "IL", tier)), None)
    if champ is None or dor is None:
        return {}
    names = [periods_name(m) for m in bm]
    up, fsc = uplift_and_fsc(names, fsc_window, today)
    field = FD.CN_RATE_FIELD[(size, source)]
    out = {}
    for m, (bid, sym) in bm.items():
        v = fob(bid, champ, dor, size, field, commodity, m, fsc, up, bool(fsc_window))
        if v is not None:
            out[m] = (v, sym)
    return out


def month_bids(cells: dict, today: date | None = None) -> list:
    """One bid per delivery month from a posting's cells {period label: row}, the tracker's rule (forward_month.rail_forward): a month's own full bid is the month
    (FH / LH midpoint when only the halves are posted); a package ('JFM', 'AMJJ', 'Nov-Jul') fills the months nothing of their own names, spread 2 cents a month
    around its centre so the months average back to the package bid (JFM +19 -> Jan 17 / Feb 19 / Mar 21). -> [{'p': 'Nov', 'm': 11, 'bid', 'futures'}] from today's month on."""
    import forward_month as FM
    items = [(p, c.get("bid")) for p, c in cells.items() if c.get("bid") is not None and not FM.is_spread_note(p)]
    fwd = FM.rail_forward(items)
    fut = {}
    for pass_own in (True, False):                      # a month's own quote names its futures month; a package only fills a month with none
        for p, c in cells.items():
            kind, months = FM.label_info(p)
            if not c.get("futures") or not months or (len(months) == 1) != pass_own:
                continue
            for m in months:
                fut.setdefault(m, c["futures"])
    t = (today or date.today()).month
    return [{"p": FM.ABBR[m], "m": m, "bid": v, "futures": fut.get(m)} for m, v in sorted(fwd.items(), key=lambda kv: (kv[0] - t) % 12)]


def periods_name(m: int) -> str:
    import calendar
    return calendar.month_abbr[m]


# ── drawing ──────────────────────────────────────────────────────────────────────────────────────────────────────
CSS = """<style>
table.sheet{width:100%;border-collapse:collapse;font-size:.85rem}
table.sheet th{font-size:.68rem;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.03em;padding:7px 10px;
 border-bottom:2px solid #e2e8f0;text-align:right;white-space:nowrap}
table.sheet th.l{text-align:left}
table.sheet td{padding:6px 10px;text-align:right;border-bottom:1px solid #f1f1f1;color:#333;white-space:nowrap;font-variant-numeric:tabular-nums}
table.sheet td.lbl{text-align:left;font-weight:600;color:#2c3e50}
table.sheet td.sub{text-align:left;color:#6b7280;font-size:.78rem}
table.sheet td.best{background:#eaf4fc;font-weight:700}
table.sheet td.neg{color:#c00000}
table.sheet tr.ref td{background:#fff9c4}
.wrap{border-radius:10px;box-shadow:0 1px 6px rgba(0,0,0,.08);padding:8px;overflow-x:auto;background:#fff;margin:6px 0}
</style>"""


def _cell(v):
    if v is None:
        return "<td>—</td>"
    t = f"{v:+.1f}"
    return f'<td class="{"neg" if v < 0 else ""}">{t}</td>'


VIEW_URL = "https://rail-fob-view-only.streamlit.app/"


def render() -> None:
    import streamlit as st
    import rail_data as RD
    import rail_fsc as RF
    import bn_fsc as BNF

    st.caption("CN 105s bids (FOB Champaign) carried to the Dorans area: bid + freight(Champaign) − freight(origin), cents/bu. "
               "Freight = CN tariff at the month's USDA level + CN fuel surcharge on estimated rail miles, ÷ bushels per car.")
    if not RD.configured():
        st.info("The rail bid archive isn't connected here, so this shows the Rail FOB view-only app "
                f"([open it in its own tab]({VIEW_URL})). Set `USE_SNOWFLAKE = 1` and the `SNOWFLAKE_*` secrets to build the Dorans sheet from the archive instead.")
        import streamlit.components.v1 as components
        components.iframe(VIEW_URL + "?embed=true", height=900, scrolling=True)
        return

    c1, c2, c3, c4 = st.columns([1, 1, 1, 1.4])
    commodity = c1.radio("Commodity", FD.CN_COMMODITIES, horizontal=True, key="cn_commodity")
    size = c2.radio("Car size", list(FD.CN_SIZES), index=1, horizontal=True, key="cn_size")
    source = c3.radio("Car source", list(FD.CN_SOURCES), horizontal=True, key="cn_source")
    fsc_on = c4.checkbox("Include CN fuel surcharge", True, key="cn_fsc")
    field = FD.CN_RATE_FIELD[(size, source)]

    rows = FD.load_cn()
    names = sorted({f"{r['origin'].title()}, {r['state']}" for r in rows if r["state"] == "IL"})
    default = [f"{o.title()}, {s}" for o, s in DEFAULT_ORIGINS]
    picked = st.multiselect("Origins (Illinois)", names, default=[n for n in default if n in names], key="cn_origins")
    origins = [(n.split(", ")[0].upper(), n.split(", ")[1]) for n in picked]

    try:
        all_rows = _cached_bids()
    except Exception as e:
        st.error(f"Couldn't read the rail bid archive: {e}")
        return
    champ = champaign_row(rows)
    if champ is None:
        st.error("The tariff has no Champaign, IL 105+ car rate to carry the bid from.")
        return
    weekly = _diesel()
    win = RF.window("CN", weekly, date.today()) if fsc_on else {}
    as_ofs, shown = [], False
    for mkt in BID_MARKETS[commodity]:
        cells, as_of = _latest_cells(all_rows, mkt)
        cells = {x["p"]: x for x in month_bids(cells)}      # one value per delivery month; packages split out with the carry
        periods = [p for p in cells if month_of(p)]
        if not periods:
            st.info(f"No {mkt} bids posted yet.")
            continue
        shown = True
        as_ofs.append(f"{mkt} {as_of}")
        uplift, fsc = uplift_and_fsc(periods, win, date.today())
        hdr = "".join(f"<th>{p}<br><span style='font-weight:400;text-transform:none'>{cells[p].get('futures') or ''}</span></th>" for p in periods)
        html = [CSS, '<div class="wrap"><table class="sheet"><tbody>', f'<tr><th class="l">Origin · tier</th>{hdr}</tr>']
        html.append(f'<tr class="ref"><td class="lbl">{mkt} bid <span class="sub">(FOB Champaign)</span></td>'
                    + "".join(f'<td>{cells[p]["bid"]:+.0f}</td>' for p in periods) + "</tr>")
        for r in sheet_rows(rows, origins, (size, source)):
            vals = [fob(cells[p]["bid"], champ, r, size, field, commodity, month_of(p), fsc, uplift, fsc_on) for p in periods]
            html.append(f'<tr><td class="lbl">{r["origin"].title()}, {r["state"]} <span class="fut-sub sub">{r["tier"]}</span></td>'
                        + "".join(_cell(v) for v in vals) + "</tr>")
        html.append("</tbody></table></div>")
        st.markdown("".join(html), unsafe_allow_html=True)
    if not shown:
        return
    as_of = "; ".join(as_ofs)

    miles = [f"{o.title()} {CM.miles_to_gulf(o, s)[0]:,.0f}" for o, s in origins if CM.miles_to_gulf(o, s)[0]]
    st.caption(f"Bids as of {as_of} (cents vs the futures month shown). {size} car ({FD.CN_BU_PER_CAR[commodity][size]:,} bu), "
               f"{source.lower()}-supplied. Rail miles to the Gulf (estimated): {', '.join(miles) or '—'}. "
               "A package (JFM, AMJJ ...) is split across its months with a 2 cent a month carry; a month's own bid always wins. A tier below 105+ cars pays more freight, so a Dorans row sits below the Champaign bid by that difference plus its extra miles. The CN 25's bid is taken as FOB Champaign like the 105s (to confirm).")


# cached readers (Streamlit's cache sits here so the pure functions above import without Streamlit)
def _cached_bids():
    import streamlit as st
    import rail_data as RD

    @st.cache_data(ttl=300, show_spinner="Reading the rail bid archive…")
    def go():
        return [r for src in RD.SOURCES for r in RD.get_all(src)]       # manual + palmetto, as the tracker's Rail FOB tab reads
    return go()


def _diesel():
    import streamlit as st
    import bn_fsc as BNF
    if not BNF.available():
        return None

    @st.cache_data(ttl=21600)
    def go(anchor):
        try:
            return BNF.fetch_weekly(date(anchor, 7, 1))
        except Exception:
            return None
    return go(BNF.crop_year_anchor(date.today()))


def _latest_cells(all_rows, market):
    """{period: row} for the market's latest posting date, and that date."""
    sel = [r for r in all_rows if r["market"] == market]
    if not sel:
        return {}, None
    d = max(r["date"] for r in sel)
    return {r["period"]: r for r in sel if r["date"] == d}, d


def _ordered(cells):
    return sorted(cells, key=lambda p: (cells[p].get("period_order") if cells[p].get("period_order") is not None else 99, p))
