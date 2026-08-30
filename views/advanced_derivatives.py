import streamlit as st
from core.ui import hero,section_note
from core.advanced_options import advanced_options_snapshot
from core.institutional_providers import polygon_short_interest,finnhub_insider_transactions
from core.free_market_providers import free_crypto_derivatives_snapshot

hero('Advanced Derivatives & Positioning','IV term structure, unusual options, crowding y datos públicos/free-first.','Derivatives Intelligence')
ticker=st.text_input('Ticker','NVDA').upper().strip()
if not ticker: st.stop()

with st.spinner('Analizando opciones...'):
    opt=advanced_options_snapshot(ticker)
a,b,c,d=st.columns(4)
a.metric('ATM IV term proxy', 'N/D' if opt['term_structure'].empty else f"{opt['term_structure'].iloc[0]['atm_iv_%']:.1f}%")
b.metric('IV Rank proxy', 'N/D' if opt.get('iv_rank_proxy_%')!=opt.get('iv_rank_proxy_%') else f"{opt['iv_rank_proxy_%']:.0f}%")
c.metric('Max Pain proxy', 'N/D' if opt.get('max_pain')!=opt.get('max_pain') else f"${opt['max_pain']:.2f}")
d.metric('Unusual contracts',len(opt.get('unusual_flow',[])))
st.caption(opt.get('note',''))
st.dataframe(opt['term_structure'],use_container_width=True,hide_index=True)
with st.expander('Unusual options heuristic'):
    st.dataframe(opt['unusual_flow'],use_container_width=True,hide_index=True)

st.subheader('Positioning / optional enrichments')
short=polygon_short_interest(ticker)
st.json(short)
ins=finnhub_insider_transactions(ticker)
if len(ins): st.dataframe(ins.head(50),use_container_width=True,hide_index=True)
else: st.info('Insider premium feed not configured or unavailable.')

if ticker in {'BTC','ETH','BTC-USD','ETH-USD'}:
    st.subheader('Crypto derivatives — free multi-exchange')
    st.json(free_crypto_derivatives_snapshot('BTC' if ticker.startswith('BTC') else 'ETH'))
