
import streamlit as st
DEFAULTS = {
    "scan_results":None,"scan_histories":{},"scan_price_map":{},"scan_universe_df":None,
    "macro_snapshot":None,"macro_breadth_detail":None,"economic_snapshot":None,"sector_snapshot":None,
    "fundamentals_cache":{},
    "portfolio_tickers":["BTC-USD","META","GOOGL","AMZN","NVDA","MU","LITE","VST","ISRG","PHM"],
    "last_refresh_label":"Sin actualizar",
}
def init_state():
    for k,v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k]=v
