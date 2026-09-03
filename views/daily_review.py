import pandas as pd
import streamlit as st
from core.ui import hero, section_note
from core.storage import load_score_history, load_latest_snapshot, load_json_snapshot

hero('Daily Review','Qué cambió materialmente en scores, sectores y régimen.','End-of-Day Review')
hist=load_score_history(days=10)
if hist.empty:
    st.info('No score history yet. Run scans/daily refresh to accumulate snapshots.'); st.stop()

hist=hist.sort_values('ts')
latest_ts=hist['ts'].max(); prev_dates=sorted(hist['ts'].dt.date.unique())
if len(prev_dates)<2:
    st.info('Need at least two snapshot dates.'); st.stop()
prev_date=prev_dates[-2]
latest=hist[hist['ts'].dt.date==latest_ts.date()].copy()
prev=hist[hist['ts'].dt.date==prev_date].copy()
merged=latest.merge(prev,on='ticker',suffixes=('_now','_prev'))
for c in ['technical','trend','entry','opportunity','confidence','rs_percentile']:
    if f'{c}_now' in merged and f'{c}_prev' in merged:
        merged[f'Delta {c}']=merged[f'{c}_now']-merged[f'{c}_prev']

st.subheader('Largest score improvements')
if 'Delta opportunity' in merged:
    st.dataframe(merged.sort_values('Delta opportunity',ascending=False)[['ticker','opportunity_prev','opportunity_now','Delta opportunity','action_now']].head(20),width='stretch',hide_index=True)
else:
    st.dataframe(merged.sort_values('Delta entry',ascending=False)[['ticker','entry_prev','entry_now','Delta entry','action_now']].head(20),width='stretch',hide_index=True)

st.subheader('Largest deteriorations')
key='Delta opportunity' if 'Delta opportunity' in merged else 'Delta entry'
st.dataframe(merged.sort_values(key)[['ticker',key,'action_now']].head(20),width='stretch',hide_index=True)

macro=load_json_snapshot('latest_macro')
if macro:
    st.subheader('Current Macro')
    st.json({k:macro.get(k) for k in ['Macro_Score','Institutional_Regime','Economic_Regime_Slow','Momentum','Breadth','Credit','Rates','Liquidity'] if k in macro})
section_note('For a full morning brief add pre-market/intraday feeds; this review is deliberately based on persisted daily data.')
