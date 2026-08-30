import pandas as pd
import streamlit as st
from core.trade_journal import add_trade, close_trade, list_trades, journal_stats
from core.ui import hero

hero('Trade Journal','Guardá tesis, setup, catalyst, score, ejecución y resultado.','Process Analytics')
with st.expander('➕ New trade',expanded=False):
    c1,c2,c3=st.columns(3)
    ticker=c1.text_input('Ticker','NVDA').strip().upper(); side=c2.selectbox('Side',['LONG','SHORT']); setup=c3.text_input('Setup','Uptrend Pullback')
    thesis=st.text_area('Thesis'); catalyst=st.text_input('Catalyst / Event')
    a,b,c,d=st.columns(4)
    entry=a.number_input('Entry',min_value=0.0,value=100.0); stop=b.number_input('Stop',min_value=0.0,value=95.0); target=c.number_input('Target',min_value=0.0,value=115.0); qty=d.number_input('Quantity',min_value=0.0,value=10.0)
    e,f=st.columns(2); score=e.number_input('Opportunity Score',min_value=0.0,max_value=100.0,value=70.0); conf=f.number_input('Confidence',min_value=0.0,max_value=100.0,value=80.0)
    notes=st.text_area('Notes')
    if st.button('Save trade',type='primary'):
        tid=add_trade(ticker,side,setup,thesis,catalyst,entry,stop,target,qty,score,conf,notes); st.success(f'Trade #{tid} saved')

open_df=list_trades('OPEN')
if not open_df.empty:
    st.subheader('Open Trades'); st.dataframe(open_df,use_container_width=True,hide_index=True)
    with st.expander('Close trade'):
        tid=st.selectbox('Trade ID',open_df['id'].tolist()); px=st.number_input('Exit price',min_value=0.0,value=100.0); note=st.text_input('Close note')
        if st.button('Close selected trade'):
            close_trade(tid,px,note); st.success('Trade closed'); st.rerun()

closed=list_trades('CLOSED'); stats=journal_stats()
if stats:
    st.subheader('Process Stats')
    cols=st.columns(len(stats))
    for col,(k,v) in zip(cols,stats.items()): col.metric(k,f'{v:.2f}' if isinstance(v,float) else v)
if not closed.empty:
    st.subheader('Closed Trades'); st.dataframe(closed,use_container_width=True,hide_index=True)
    if 'setup' in closed and 'pnl_percent' in closed:
        by=closed.groupby('setup')['pnl_percent'].agg(['count','mean','median']).reset_index().sort_values('mean',ascending=False)
        st.subheader('Setup Analytics'); st.dataframe(by,use_container_width=True,hide_index=True)
