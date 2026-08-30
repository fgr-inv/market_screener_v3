import pandas as pd
import streamlit as st

from core.market_data import download_prices
from core.factor_model import FACTOR_PROXIES, factor_exposures, portfolio_factor_exposure
from core.advanced_factor_model import multivariate_factor_exposure
from core.factor_diagnostics import factor_correlation,redundant_pairs
from core.storage import load_positions,load_latest_snapshot
from core.ui import hero, section_note

hero('Factor Lab','Exposición de mercado + diagnóstico de redundancia entre scores.','Factor Exposure V8')
market_tab,score_tab=st.tabs(['Market Factor Exposure','Score De-duplication'])

with market_tab:
    mode=st.radio('Mode',['Single Asset','Portfolio'],horizontal=True)
    if mode=='Single Asset':
        ticker=st.text_input('Ticker','NVDA').strip().upper()
        syms=[ticker]+list(set(FACTOR_PROXIES.values())|{'SPY','TLT','UUP','XLE'})
        pm=download_prices(list(dict.fromkeys(syms)),period='3y')
        tab1,tab2=st.tabs(['Proxy Betas','Multivariate'])
        with tab1:
            ex=factor_exposures(ticker,pm); st.dataframe(ex,use_container_width=True,hide_index=True)
            if not ex.empty: st.bar_chart(ex.set_index('Factor')['Beta'])
        with tab2:
            ex2,stats=multivariate_factor_exposure(ticker,pm)
            a,b,c=st.columns(3); a.metric('R²','N/D' if not stats else f"{stats.get('R2',0):.2f}"); b.metric('Residual Vol','N/D' if not stats else f"{stats.get('Residual Vol %',0):.1f}%"); c.metric('Regression Alpha','N/D' if not stats else f"{stats.get('Alpha Ann %',0):+.1f}%")
            st.dataframe(ex2,use_container_width=True,hide_index=True)
            if not ex2.empty: st.bar_chart(ex2.set_index('Factor')['Beta'])
    else:
        pos=load_positions()
        if pos.empty: st.info('Agregá posiciones en Portfolio.')
        else:
            syms=pos['ticker'].astype(str).tolist()+list(FACTOR_PROXIES.values()); pm=download_prices(list(dict.fromkeys(syms)),period='3y')
            ex=portfolio_factor_exposure(pos,pm); st.dataframe(ex,use_container_width=True,hide_index=True)
            if not ex.empty: st.bar_chart(ex.set_index('Factor')['Portfolio Beta'])
    section_note('No es Barra/Axioma. La versión multivariada reduce doble conteo entre proxies, pero un factor model institucional real requiere datos point-in-time propios.')

with score_tab:
    section_note('Busca doble conteo dentro del modelo. Correlaciones elevadas entre Trend, RS, Technical, etc. indican factores redundantes.')
    df=st.session_state.scan_results if st.session_state.scan_results is not None else load_latest_snapshot('latest_screener')
    corr=factor_correlation(df,min_obs=15); pairs=redundant_pairs(corr,.80)
    if corr.empty: st.info('No hay suficientes scores persistidos para calcular la matriz.')
    else:
        st.dataframe(corr.round(2),use_container_width=True)
        if pairs.empty: st.success('No hay pares con |correlación| ≥ 0.80 en el snapshot actual.')
        else:
            st.warning('Factores potencialmente redundantes:')
            st.dataframe(pairs,use_container_width=True,hide_index=True)
        st.caption('La correlación cross-sectional no prueba causalidad; sirve como diagnóstico para revisar pesos y evitar premiar dos veces la misma señal.')
