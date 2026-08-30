import streamlit as st
from core.ui import hero
hero('Screener Hub','Elegí el screener según la pregunta que querés responder.','Specialized Screeners')
st.page_link('views/technical_screener.py',label='⚡ Technical Screener')
st.page_link('views/fundamental_screener.py',label='📚 Fundamental Screener')
st.page_link('views/combined_screener.py',label='🎯 Combined Screener')
