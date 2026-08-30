import pandas as pd
import streamlit as st
from core.market_data import download_prices
from core.backtest import backtest_symbol, summarize_backtest
from core.edge_calibration import calibrate_score_buckets, bootstrap_edge, walk_forward_summary
from core.model_registry import get_active_model, model_label
from core.point_in_time import point_in_time_status
from core.ui import hero, section_note

hero('Model Validation','Backtest, walk-forward, bootstrap y calibración del score.','Model Governance')
model=get_active_model(); st.info(f"Active model: **{model_label()}** · Effective: {model.get('effective_date')}")
pit=point_in_time_status('SP500')
st.warning('Backtest Quality: TECHNICAL POINT-IN-TIME ONLY · historical constituents '+('AVAILABLE' if pit.get('available') else 'MISSING / survivorship-bias risk'))
with st.expander('Model weights'):
    st.json(model)

ticker=st.text_input('Ticker','SPY').strip().upper()
entry_min=st.slider('Entry Score minimum',40,90,65)
trend_min=st.slider('Trend Score minimum',40,90,65)
step=st.slider('Sampling step (days)',1,20,5)
if st.button('Run validation',type='primary'):
    pm=download_prices(list(dict.fromkeys([ticker,'SPY'])),period='10y')
    raw=pm.get(ticker); spy=pm.get('SPY')
    if raw is None or raw.empty:
        st.error('No data'); st.stop()
    ev=backtest_symbol(ticker,raw,spy,step=step,entry_min=entry_min,trend_min=trend_min)
    summary,stats=summarize_backtest(ev)
    st.subheader('Event Study'); st.dataframe(summary,use_container_width=True,hide_index=True)
    if not ev.empty:
        wf=walk_forward_summary(ev,return_col='20d_Alpha')
        if wf:
            st.subheader('Walk-forward'); cols=st.columns(len(wf));
            for c,(k,v) in zip(cols,wf.items()): c.metric(k,f'{v:.2f}' if isinstance(v,float) else v)
        boot=bootstrap_edge(ev.get('20d_Alpha',pd.Series(dtype=float)))
        if boot:
            st.subheader('Bootstrap 20d Alpha'); st.dataframe(pd.DataFrame([boot]),use_container_width=True,hide_index=True)
        cal=calibrate_score_buckets(ev,'Entry_Score','20d_Alpha')
        if not cal.empty:
            st.subheader('Score Calibration'); st.dataframe(cal,use_container_width=True,hide_index=True)
        with st.expander('Raw events'):
            st.dataframe(ev,use_container_width=True,hide_index=True)
section_note('Este backtest técnico evita aplicar fundamentales actuales retroactivamente. No uses fundamentals/revisions históricos sin datasets point-in-time; si faltan constituyentes históricos, los backtests de universo pueden sufrir survivorship bias.')
