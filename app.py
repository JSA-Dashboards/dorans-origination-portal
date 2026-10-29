"""Farmers Grain Co of Dorans (Mattoon, IL) - origination portal. Production, CN rail FOB and CN seasonals for one location."""
import os

import streamlit as st

import cn_seasonals
import competitors
import cn_sheet
import processors
import production_tab

for _k in ("USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_PRIVATE_KEY",
           "SNOWFLAKE_PRIVATE_KEY_PWD", "EIA_API_KEY"):          # Cloud secrets -> environment, where the vendored readers look
    try:
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

st.set_page_config(page_title="Dorans Origination Portal", page_icon="🌽", layout="wide")
st.markdown("""<style>
html, body, [class*="css"], h1, h2, h3, h4 { font-family: "Source Sans Pro", system-ui, sans-serif; }
.dash-header { text-align:center; padding:10px 0 12px; border-bottom:3px solid #0693e3; margin-bottom:14px; }
.dash-header h1 { margin:0; font-size:1.7rem; color:#32373c; }
.dash-header p { margin:2px 0 0; color:#6b7280; font-size:0.95rem; }
</style>
<div class="dash-header"><h1>Dorans Origination Portal</h1><p>Farmers Grain Co of Dorans · Mattoon, IL</p></div>""", unsafe_allow_html=True)

tab_prod, tab_comp, tab_proc, tab_cn, tab_seas = st.tabs(["🌽 IL Production", "📍 Competition", "🏭 Processors", "🚂 CN Rail FOB", "📈 CN Seasonals"])
with tab_prod:
    production_tab.render()
with tab_comp:
    competitors.render()
with tab_proc:
    processors.render()
with tab_cn:
    cn_sheet.render()
with tab_seas:
    cn_seasonals.render()
