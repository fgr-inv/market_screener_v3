import pandas as pd
import streamlit as st
from core.options_data import get_options_snapshot
from core.crowding import get_crowding_snapshot
from core.market_data import download_prices
from core.liquidity import liquidity_score
from core.ui import hero, section_note
from core.utils import fmt_pct, fmt_num

hero('Options, Crowding & Liquidity','IV, expected move, put/call, short interest y execution risk.','Positioning Intelligence')
ticker=st.text_input('Ticker','NVDA').strip().upper()
if not ticker: st.stop()

opts=get_options_snapshot(ticker); crowd=get_crowding_snapshot(ticker)
pm=download_prices([ticker],period='6mo'); liq=liquidity_score(pm.get(ticker))

st.subheader('Options')
if not opts['available']:
    st.info('No hay option chain disponible para este ticker/proveedor.')
else:
    a,b,c,d=st.columns(4)
    a.metric('Nearest Expiry',opts['expiration'])
    b.metric('Expected Move',fmt_pct(opts['expected_move_%']))
    c.metric('ATM IV',fmt_pct(opts['atm_iv_%']))
    d.metric('Put/Call OI',fmt_num(opts['put_call_oi']))
    e,f,g=st.columns(3)
    e.metric('Put/Call Volume',fmt_num(opts['put_call_volume']))
    f.metric('Put - Call IV skew',fmt_pct(opts['iv_skew_put_minus_call_%']))
    g.metric('Total OI',fmt_num((opts['call_oi'] or 0)+(opts['put_oi'] or 0),0))
    with st.expander('Near-the-money chain'):
        st.dataframe(opts['detail'],width='stretch',hide_index=True)

st.subheader('Crowding / Short Interest')
a,b,c,d=st.columns(4)
a.metric('Crowding Risk',crowd['Crowding_Risk'])
b.metric('Short % Float',fmt_pct(crowd['Short_%_Float']))
c.metric('Days to Cover',fmt_num(crowd['Short_Ratio_Days']))
d.metric('Institutional Ownership',fmt_pct(crowd['Institution_%']))
st.dataframe(pd.DataFrame([[k,v] for k,v in crowd.items()],columns=['Metric','Value']),width='stretch',hide_index=True)

st.subheader('Liquidity / Execution')
a,b,c=st.columns(3)
a.metric('Liquidity Score',f"{liq['Liquidity_Score']}/100")
b.metric('Label',liq['Liquidity_Label'])
c.metric('ADV20 $',f"${liq['ADV20_$']:,.0f}" if pd.notna(liq['ADV20_$']) else 'N/D')
section_note('Bid/ask histórico y slippage real requieren datos intradía/Level 1 de un proveedor especializado; ADV es una proxy conservadora.')
