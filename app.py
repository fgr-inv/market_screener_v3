import streamlit as st
from core.config import APP_NAME,APP_VERSION
from core.state import init_state
from core.ui import inject_css

st.set_page_config(page_title=APP_NAME,page_icon='📈',layout='wide',initial_sidebar_state='expanded')
init_state(); inject_css()

try: required_password=st.secrets.get('APP_PASSWORD','')
except Exception: required_password=''
if required_password and not st.session_state.get('_authenticated'):
    st.title('🔐 Market Screener Pro')
    pwd=st.text_input('Password',type='password')
    if st.button('Enter'):
        if pwd==required_password: st.session_state['_authenticated']=True; st.rerun()
        else: st.error('Incorrect password')
    st.stop()

market=[
    st.Page('views/dashboard.py',title='Dashboard',icon='🏠',default=True),
    st.Page('views/macro_dashboard.py',title='Macro Dashboard',icon='🌍'),
    st.Page('views/sector_rotation.py',title='Sector Rotation',icon='🧭'),
    st.Page('views/cross_asset.py',title='Cross Asset',icon='🌐'),
    st.Page('views/crypto.py',title='Crypto',icon='🪙'),
]
research=[
    st.Page('views/decision_center.py',title='Decision Center',icon='🧠'),
    st.Page('views/technical_screener.py',title='Technical Screener',icon='⚡'),
    st.Page('views/fundamental_screener.py',title='Fundamental Screener',icon='📚'),
    st.Page('views/combined_screener.py',title='Combined Screener',icon='🎯'),
    st.Page('views/asset_analysis.py',title='Asset Analysis',icon='🔬'),
    st.Page('views/industry_leadership.py',title='Industry Leadership',icon='🏭'),
    st.Page('views/catalysts.py',title='Catalysts & Revisions',icon='📰'),
    st.Page('views/options_crowding.py',title='Options & Crowding',icon='📊'),
    st.Page('views/advanced_derivatives.py',title='Advanced Derivatives',icon='🧮'),
]
portfolio=[
    st.Page('views/portfolio.py',title='Portfolio & Thesis',icon='⭐'),
    st.Page('views/portfolio_risk.py',title='Portfolio Risk',icon='🛡️'),
    st.Page('views/optimizer.py',title='Portfolio Optimizer',icon='⚖️'),
    st.Page('views/stress_test.py',title='Stress Test',icon='🌪️'),
    st.Page('views/trade_journal.py',title='Trade Journal',icon='📓'),
    st.Page('views/broker_data.py',title='Broker Import',icon='🏦'),
]
quant=[
    st.Page('views/factor_lab.py',title='Factor Lab',icon='🧬'),
    st.Page('views/model_validation.py',title='Model Validation',icon='🧪'),
    st.Page('views/backtesting.py',title='Backtesting Lab',icon='🧫'),
]
operations=[
    st.Page('views/account.py',title='Account & Plan',icon='👤'),
    st.Page('views/alerts.py',title='Live Alerts',icon='🚨'),
    st.Page('views/saved_alerts.py',title='Saved Alerts',icon='🔔'),
    st.Page('views/daily_review.py',title='Daily Review',icon='🗓️'),
    st.Page('views/system_health.py',title='System Health',icon='🩺'),
    st.Page('views/data_hub.py',title='Institutional Data Hub',icon='🗄️'),
]

st.sidebar.caption(f'{APP_NAME} · V{APP_VERSION}')
st.navigation({'MARKET':market,'RESEARCH':research,'PORTFOLIO':portfolio,'QUANT':quant,'OPERATIONS':operations}).run()
