"""Farmers Grain Co of Dorans (Mattoon, IL) - origination portal. Production, CN rail FOB and CN seasonals for one location."""
import os

import streamlit as st

import cn_seasonals
import competitors
import cn_sheet
import processors
import market_share_tab
import production_tab

for _k in ("USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_PRIVATE_KEY",
           "SNOWFLAKE_PRIVATE_KEY_PWD", "EIA_API_KEY"):          # Cloud secrets -> environment, where the vendored readers look
    try:
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

st.set_page_config(page_title="Dorans Merchandising Portal", page_icon="🌽", layout="wide")
import hashlib
import hmac

# Password gate. The repo is public, so the default password is stored only as a salted hash; set the APP_PASSWORD secret to change it without touching the code.
_PW_HASH = "35896195271b2e3d795e5c6b7f0d791303f46f9dabffad245b76aa8bc2334c6c"


def _password_ok(attempt: str) -> bool:
    try:
        secret = str(st.secrets.get("APP_PASSWORD", "") or "")
    except Exception:
        secret = ""
    if secret:
        return hmac.compare_digest(attempt.encode(), secret.encode())
    return hmac.compare_digest(hashlib.sha256(("dorans-portal:" + attempt).encode()).hexdigest(), _PW_HASH)


if not st.session_state.get("_authed"):
    st.markdown("<h2 style='text-align:center;margin-top:60px'>Dorans Merchandising Portal</h2>", unsafe_allow_html=True)
    _l, _m, _r = st.columns([1, 1, 1])
    with _m:
        _pw = st.text_input("Password", type="password", key="_pw_input")
        if _pw:
            if _password_ok(_pw):
                st.session_state["_authed"] = True
                st.rerun()
            st.error("That password isn't right.")
    st.stop()

st.markdown("""<style>
html, body, [class*="css"], h1, h2, h3, h4 { font-family: "Source Sans Pro", system-ui, sans-serif; }
.dash-header { text-align:center; padding:10px 0 12px; border-bottom:3px solid #0693e3; margin-bottom:14px; }
.dash-header h1 { margin:0; font-size:1.7rem; color:#32373c; }
.dash-header p { margin:2px 0 0; color:#6b7280; font-size:0.95rem; }
</style>
<div class="dash-header"><h1>Dorans Merchandising Portal</h1><p>Farmers Grain Co of Dorans · Mattoon, IL</p></div>""", unsafe_allow_html=True)

st.markdown(
    "<p style='text-align:center;color:#6b7280;font-size:0.78rem;margin:-6px 0 8px 0'>Basis, processor and rail bids come from the "
    "<a href='https://basis-tracker-view.streamlit.app' target='_blank'>Basis Tracker view</a> data only: the same archive and the same hidden markets "
    "the view build shows.</p>", unsafe_allow_html=True)

tab_prod, tab_share, tab_comp, tab_proc, tab_cn, tab_seas = st.tabs(["🌽 IL Production", "📊 Market Share", "📍 Competition", "🏭 Processors", "🚂 CN Rail FOB", "📈 CN Seasonals"])
with tab_prod:
    production_tab.render()
with tab_share:
    market_share_tab.render()
with tab_comp:
    competitors.render()
with tab_proc:
    processors.render()
with tab_cn:
    cn_sheet.render()
with tab_seas:
    cn_seasonals.render()
