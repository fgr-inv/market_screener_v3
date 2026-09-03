import pandas as pd
import streamlit as st

from core.trade_journal import add_trade, close_trade, list_trades, journal_stats
from core.access_control import current_user
from core.ui import hero, section_note

hero('Trade Journal','Guardá tesis, setup, catalyst, score, ejecución y resultado.','Process Analytics')
user=current_user(); uid=user['user_id']

with st.expander('➕ New trade',expanded=False):
    c1,c2,c3=st.columns(3)
    ticker=c1.text_input('Ticker','NVDA').strip().upper(); side=c2.selectbox('Side',['LONG','SHORT']); setup=c3.text_input('Setup','Uptrend Pullback')
    thesis=st.text_area('Thesis'); catalyst=st.text_input('Catalyst / Event')
    a,b,c,d=st.columns(4)
    entry=a.number_input('Entry',min_value=0.000001,value=100.0)
    default_stop=95.0 if side=='LONG' else 105.0
    stop=b.number_input('Stop',min_value=0.0,value=default_stop,key=f'stop_{side}')
    target=c.number_input('Target',min_value=0.0,value=115.0 if side=='LONG' else 85.0,key=f'target_{side}')
    qty=d.number_input('Quantity',min_value=0.000001,value=10.0)
    e,f=st.columns(2); score=e.number_input('Opportunity Score',min_value=0.0,max_value=100.0,value=70.0); conf=f.number_input('Confidence',min_value=0.0,max_value=100.0,value=80.0)
    notes=st.text_area('Notes')
    risk_per_unit=abs(entry-stop) if stop>0 else 0
    reward_per_unit=abs(target-entry) if target>0 else 0
    rr=(reward_per_unit/risk_per_unit) if risk_per_unit>0 else None
    st.caption(f'Planned risk: ${risk_per_unit*qty:,.2f}' + (f' · Planned R/R: {rr:.2f}' if rr is not None else ''))
    if st.button('Save trade',type='primary'):
        try:
            tid=add_trade(ticker,side,setup,thesis,catalyst,entry,stop,target,qty,score,conf,notes,user_id=uid)
            st.success(f'Trade #{tid} saved'); st.rerun()
        except Exception as exc: st.error(str(exc))

open_df=list_trades('OPEN',user_id=uid)
if not open_df.empty:
    st.subheader('Open Trades'); st.dataframe(open_df,width='stretch',hide_index=True)
    with st.expander('Close trade'):
        tid=st.selectbox('Trade ID',open_df['id'].tolist()); px=st.number_input('Exit price',min_value=0.000001,value=100.0); note=st.text_input('Close note')
        if st.button('Close selected trade'):
            try:
                if close_trade(tid,px,note,user_id=uid): st.success('Trade closed'); st.rerun()
                else: st.warning('Trade no encontrado o ya estaba cerrado.')
            except Exception as exc: st.error(str(exc))

closed=list_trades('CLOSED',user_id=uid); stats=journal_stats(user_id=uid)
if stats:
    st.subheader('Process Stats')
    cols=st.columns(len(stats))
    for col,(k,v) in zip(cols,stats.items()): col.metric(k,'N/D' if pd.isna(v) else (f'{v:.2f}' if isinstance(v,float) else v))
if not closed.empty:
    st.subheader('Closed Trades'); st.dataframe(closed,width='stretch',hide_index=True)
    if 'setup' in closed and 'pnl_percent' in closed:
        by=closed.groupby('setup')['pnl_percent'].agg(['count','mean','median']).reset_index().sort_values('mean',ascending=False)
        st.subheader('Setup Analytics'); st.dataframe(by,width='stretch',hide_index=True)
section_note('El journal es privado por usuario. No se envían órdenes; registra proceso y resultados para detectar qué setups funcionan mejor.')
