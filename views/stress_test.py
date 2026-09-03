import pandas as pd
import streamlit as st
from core.access_control import current_user
from core.storage import load_positions
from core.market_data import download_prices
from core.scenario import DEFAULT_SCENARIOS, stress_portfolio
from core.historical_stress import HISTORICAL_WINDOWS, historical_stress_portfolio
from core.ui import hero

hero('Portfolio Stress Test','Hypothetical shocks + realized historical crisis windows.','Scenario Engine')
user=current_user(); uid=user['user_id']
pos=load_positions(user_id=uid)
if pos.empty:
    st.info('No hay posiciones guardadas.'); st.stop()

mode=st.radio('Stress type',['Hypothetical','Historical'],horizontal=True)
all_proxy=list({k for s in DEFAULT_SCENARIOS.values() for k in s.keys()})
syms=list(dict.fromkeys(pos['ticker'].astype(str).tolist()+all_proxy+['SPY','QQQ','IWM','TLT','GLD','CL=F']))
pm=download_prices(syms,period='10y')

if mode=='Hypothetical':
    scenario=st.selectbox('Scenario',list(DEFAULT_SCENARIOS.keys()))
    summary,detail=stress_portfolio(pos,pm,scenario)
else:
    scenario=st.selectbox('Historical crisis',list(HISTORICAL_WINDOWS.keys()))
    summary,detail=historical_stress_portfolio(pos,pm,scenario)

a,b,c=st.columns(3)
portfolio_value=summary.get('Portfolio Value'); estimated_pnl=summary.get('Estimated P&L $'); impact=summary.get('Estimated Portfolio %')
a.metric('Portfolio Value','N/D' if portfolio_value is None or pd.isna(portfolio_value) else f"${portfolio_value:,.0f}")
b.metric('Estimated P&L','N/D' if estimated_pnl is None or pd.isna(estimated_pnl) else f"${estimated_pnl:,.0f}")
c.metric('Estimated Impact','N/D' if impact is None or pd.isna(impact) else f"{impact:+.1f}%")
st.dataframe(detail,use_container_width=True,hide_index=True)
st.warning('Stress results are sensitivity estimates. Correlations, liquidity and gaps can worsen materially during a real crisis.')
