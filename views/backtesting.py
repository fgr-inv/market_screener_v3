import pandas as pd
import streamlit as st
from core.market_data import download_prices, classify_symbol
from core.backtest import backtest_symbol, summarize_backtest
from core.ui import hero, section_note

hero('Backtesting Lab','Validá setups históricos antes de confiar en un score.','Model Validation')

with st.sidebar:
    ticker=st.text_input('Ticker','NVDA').strip().upper()
    entry_min=st.slider('Entry mínimo',40,95,65)
    trend_min=st.slider('Trend mínimo',40,95,65)
    setup=st.selectbox('Setup',['Todos','Uptrend Pullback','EMA62/79 Buy Zone','200D Bounce','Breakout / Base'])
    step=st.slider('Muestreo (días)',1,20,5)
    run=st.button('▶ Ejecutar backtest',type='primary',use_container_width=True)

if not run:
    st.info('Configurá el test y presioná Ejecutar backtest.')
    st.stop()

pm=download_prices([ticker,'SPY'],period='10y')
raw=pm.get(ticker); spy=pm.get('SPY')
if raw is None or raw.empty:
    st.error('No hay histórico suficiente.'); st.stop()

detected=classify_symbol(ticker)
events=backtest_symbol(
    ticker,raw,spy_raw=spy,step=step,asset_type=detected,
    setup_filter=None if setup=='Todos' else setup,
    entry_min=entry_min,trend_min=trend_min,
)
summary,stats=summarize_backtest(events)

c1,c2=st.columns(2)
c1.metric('Señales',stats.get('Total Signals',0))
c2.metric('Años de datos',round(len(raw)/252,1))

st.subheader('Resultados por horizonte')
section_note(f'Este backtest usa el modelo técnico de {detected} y evita usar fundamentales actuales sobre datos históricos.')
st.dataframe(summary,use_container_width=True,hide_index=True)

st.subheader('Eventos')
st.dataframe(events.sort_values('Date',ascending=False).head(250),use_container_width=True,hide_index=True)

st.warning('No incorpora slippage, gaps, impuestos ni ejecución real. Úsalo para validar la señal, no para prometer retornos.')
