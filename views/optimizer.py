import pandas as pd
import streamlit as st
from core.storage import load_positions
from core.market_data import download_prices
from core.optimizer import risk_parity_weights, correlation_penalty_weights
from core.advanced_optimizer import min_variance_weights, max_sharpe_weights
from core.ui import hero, section_note

hero('Portfolio Optimizer','Risk parity, correlation-aware, shrinkage min-variance y constrained max-Sharpe.','Portfolio Construction')
pos=load_positions()
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
    vals={}
    total=0
    for _,r in pos.iterrows():
        raw=pm.get(str(r['ticker']).upper())
        if raw is None or raw.empty: continue
        val=float(r['quantity'])*float(raw['Close'].dropna().iloc[-1]); vals[str(r['ticker']).upper()]=val; total+=val
    current={t:v/total for t,v in vals.items()} if total else {}
    out=min_variance_weights(tickers,pm,max_weight=maxw,shrink=shrink,current_weights=current,turnover_penalty=turn)
else:
    rf=st.number_input('Risk-free rate (%)',0.0,15.0,4.0,.25)/100
    shrink=st.slider('Covariance shrinkage',0.0,0.9,0.35,0.05,key='sharpe_shrink')
    out=max_sharpe_weights(tickers,pm,max_weight=maxw,risk_free=rf,shrink=shrink)

st.dataframe(out,use_container_width=True,hide_index=True)
if not out.empty and 'Ticker' in out and 'Weight %' in out:
    st.bar_chart(out.set_index('Ticker')['Weight %'])
section_note('Expected-return optimization is noisy. Use constrained solutions, shrinkage and turnover limits; compare with risk-parity instead of trusting one optimizer.')
