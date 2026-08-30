import pandas as pd
import streamlit as st

from core.storage import load_positions,upsert_position,delete_position
from core.market_data import download_prices
from core.portfolio_risk import portfolio_risk,high_correlation_pairs
from core.themes import theme_exposure
from core.ui import hero, section_note
from core.github_sync import push_file

hero('Portfolio Risk','Peso, contribución al riesgo, concentración temática, correlaciones, beta, VaR y drawdown.','Risk Workstation V8')

with st.sidebar:
    st.header('Agregar / editar posición')
    t=st.text_input('Ticker','NVDA').strip().upper()
    q=st.number_input('Cantidad',min_value=0.0,value=10.0,step=1.0)
    c=st.number_input('Costo promedio',min_value=0.0,value=100.0,step=1.0)
    sec=st.text_input('Sector','Technology')
    if st.button('Guardar posición',type='primary',use_container_width=True):
        upsert_position(t,q,c,sec)
        push_file('data/portfolio_positions.csv','data/portfolio_positions.csv','chore: update portfolio positions')
        st.rerun()

pos=load_positions()
if pos.empty:
    st.info('Agregá posiciones desde la barra lateral.'); st.stop()

tickers=pos['ticker'].astype(str).tolist(); pm=download_prices(list(dict.fromkeys(tickers+['SPY'])),period='2y')
summary,detail,corr=portfolio_risk(pos,pm)
themes=theme_exposure(detail); pairs=high_correlation_pairs(corr)

metrics=list(summary.items()); cols=st.columns(5)
for col,(k,v) in zip(cols,metrics[:5]): col.metric(k,'N/D' if pd.isna(v) else f'{v:,.2f}')
cols=st.columns(4)
for col,(k,v) in zip(cols,metrics[5:9]): col.metric(k,'N/D' if pd.isna(v) else f'{v:,.2f}')

t1,t2,t3,t4=st.tabs(['Risk Contribution','Themes','Correlations','Positions'])
with t1:
    section_note('Peso de capital y contribución al riesgo no son lo mismo. Un activo volátil puede aportar mucho más riesgo que su peso.')
    cols=['Ticker','Sector','Weight %','Risk Contribution %','Risk / Weight','Standalone Vol %','Value','Price']
    st.dataframe(detail[[c for c in cols if c in detail]].sort_values('Risk Contribution %',ascending=False),use_container_width=True,hide_index=True)
    if 'Risk Contribution %' in detail: st.bar_chart(detail.set_index('Ticker')['Risk Contribution %'])
with t2:
    section_note('Clasificación económica transversal: detecta concentración AI/power/crypto que GICS puede ocultar.')
    st.dataframe(themes,use_container_width=True,hide_index=True)
    if not themes.empty: st.bar_chart(themes.set_index('Theme')['Weight %'])
with t3:
    st.dataframe(corr.round(2),use_container_width=True)
    if not pairs.empty:
        st.warning('Pares con correlación ≥ 0.80')
        st.dataframe(pairs,use_container_width=True,hide_index=True)
with t4:
    st.dataframe(pos,use_container_width=True,hide_index=True)
    kill=st.selectbox('Ticker a eliminar',['—']+tickers)
    if kill!='—' and st.button('Eliminar'):
        delete_position(kill); push_file('data/portfolio_positions.csv','data/portfolio_positions.csv','chore: update portfolio positions'); st.rerun()

st.subheader('Risk Diagnostics')
flags=[]
if summary.get('Largest Position %',0)>20: flags.append('⚠️ Una posición supera 20% de la cartera.')
if summary.get('Largest Sector %',0)>35: flags.append('⚠️ Un sector supera 35% de la cartera.')
if pd.notna(summary.get('Portfolio Beta')) and summary.get('Portfolio Beta',0)>1.25: flags.append('⚠️ Beta de cartera elevada.')
if not pairs.empty: flags.append(f'⚠️ {len(pairs)} pares tienen correlación ≥ 0.80.')
if not detail.empty:
    high_rc=detail[detail['Risk Contribution %']>detail['Weight %']*1.75]
    if not high_rc.empty: flags.append('⚠️ Aportan riesgo desproporcionado: '+', '.join(high_rc['Ticker'].head(8)))
if not themes.empty and themes.iloc[0]['Weight %']>30: flags.append(f"⚠️ Tema dominante: {themes.iloc[0]['Theme']} ({themes.iloc[0]['Weight %']:.1f}%).")
for f in flags: st.write(f)
if not flags: st.success('No aparecen concentraciones extremas con los umbrales V8.')
