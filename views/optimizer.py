import pandas as pd
import streamlit as st
from core.access_control import current_user
from core.storage import load_positions
from core.market_data import download_prices
from core.optimizer import risk_parity_weights, correlation_penalty_weights
from core.advanced_optimizer import min_variance_weights, max_sharpe_weights
from core.portfolio_positions import resolve_position_allocations
from core.ui import hero, section_note

hero('Portfolio Optimizer','Risk parity, correlation-aware, shrinkage min-variance y constrained max-Sharpe.','Portfolio Construction')
user=current_user(); uid=user['user_id']
pos=load_positions(user_id=uid)
if pos.empty:
    st.info('No positions saved.'); st.stop()

tickers=pos['ticker'].astype(str).tolist()
maxw=st.slider('Max weight per position (%)',5,50,20)/100
pm=download_prices(tickers,period='3y')
method=st.radio('Method',['Risk Parity','Correlation-Aware','Shrinkage Min-Variance','Constrained Max-Sharpe'],horizontal=False)

if method=='Risk Parity':
    out=risk_parity_weights(tickers,pm,maxw)
elif method=='Correlation-Aware':
    out=correlation_penalty_weights(tickers,pm,max_weight=maxw)
elif method=='Shrinkage Min-Variance':
    shrink=st.slider('Covariance shrinkage',0.0,0.9,0.35,0.05)
    turn=st.slider('Turnover penalty',0.0,1.0,0.05,0.05)
    resolved,allocation=resolve_position_allocations(pos,pm)
    current={str(r['Ticker']):float(r.get('Weight %',0) or 0)/100 for _,r in resolved.iterrows()} if allocation.get('status')=='CURRENT' else {}
    out=min_variance_weights(tickers,pm,max_weight=maxw,shrink=shrink,current_weights=current,turnover_penalty=turn)
else:
    rf=st.number_input('Risk-free rate (%)',0.0,15.0,4.0,.25)/100
    shrink=st.slider('Covariance shrinkage',0.0,0.9,0.35,0.05,key='sharpe_shrink')
    out=max_sharpe_weights(tickers,pm,max_weight=maxw,risk_free=rf,shrink=shrink)

st.dataframe(out,width='stretch',hide_index=True)
if not out.empty and 'Ticker' in out and 'Weight %' in out:
    st.bar_chart(out.set_index('Ticker')['Weight %'])
section_note('Expected-return optimization is noisy. Use constrained solutions, shrinkage and turnover limits; compare with risk-parity instead of trusting one optimizer.')
