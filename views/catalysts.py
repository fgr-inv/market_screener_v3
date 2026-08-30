import streamlit as st
from core.analyst_data import get_analyst_snapshot
from core.events import earnings_event
from core.news_data import get_news
from core.ui import hero, section_note

hero('Catalysts & Revisions','Earnings risk, revisiones de EPS, targets y noticias recientes.','Forward-Looking Layer')

ticker=st.text_input('Ticker','META').strip().upper()
if not ticker: st.stop()

with st.spinner('Cargando catalysts...'):
    a=get_analyst_snapshot(ticker)
    e=earnings_event(ticker)
    n=get_news(ticker,15)

c1,c2,c3,c4=st.columns(4)
c1.metric('EPS Revision Score','N/D' if a['EPS_Revision_Score']!=a['EPS_Revision_Score'] else f"{a['EPS_Revision_Score']}/100")
c2.metric('Revision Direction',a['Revision_Direction'])
c3.metric('Target Upside','N/D' if a['Price_Target_Upside_%']!=a['Price_Target_Upside_%'] else f"{a['Price_Target_Upside_%']:.1f}%")
c4.metric('Earnings Risk',e['risk'])

st.write(f"Próximo earnings: **{e['next_earnings']}** | Días: **{e['days_to_earnings']}**")

if not a['Revision_Detail'].empty:
    st.subheader('Revisions detail')
    st.dataframe(a['Revision_Detail'],use_container_width=True,hide_index=True)

st.subheader('Recent news')
section_note('News se usa como capa de catalysts/event risk, no como señal automática de compra.')
st.dataframe(n,use_container_width=True,hide_index=True)
