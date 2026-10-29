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


def render() -> None:
    import plotly.graph_objects as go
    import streamlit as st

    hist, note = load()
    if note:
        st.warning(note)
    tabs = st.tabs([p[0] for p in PROCESSORS])
    for tab, (label, key, crops, note) in zip(tabs, PROCESSORS):
        with tab:
            st.caption(note)
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
                st.caption(f"Lines: the last six years with data. {len(ser):,} posted days, {first:%b %Y} to {ser[-1][0]:%b %d, %Y}. "
                           + ("Spot bid." if spot else "Earliest futures month quoted that day (no spot bid posted).")
                           + (" History only goes back this far in the archive, so there is no seasonal pattern to read yet." if (date.today() - first).days < 500 else ""))
