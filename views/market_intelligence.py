import pandas as pd
import streamlit as st
from core.market_data import download_prices, get_macro_symbols, get_sector_etfs
from core.economic_data import institutional_macro_snapshot
from core.market_intelligence import (market_state,breadth_dashboard,sector_rotation_table,cross_asset_table,
    macro_sensitivity_table,load_latest_screener,opportunity_radar)
from core.ui import hero, section_note

hero('Market Intelligence','Régimen, breadth, rotación sectorial, cross-asset, liquidez, revisiones, valoración y oportunidades en una sola pantalla.','Top-Down Market OS')
refresh=st.button('🔄 Recalcular Market Intelligence',type='primary')
syms=list(dict.fromkeys(list(get_macro_symbols().values())+list(get_sector_etfs().values())+['SPY','QQQ','IWM','RSP','TLT','HYG','GLD','UUP','CL=F','HG=F','BTC-USD']))
with st.spinner('Construyendo mapa de mercado...'):
    pm=download_prices(syms,period='2y')
    macro=st.session_state.macro_snapshot or institutional_macro_snapshot(pm,breadth_level=50)
    snap=load_latest_screener()
    state=market_state(pm,macro); breadth,rel=breadth_dashboard(pm); sectors=sector_rotation_table(pm,macro,snap); cross=cross_asset_table(pm)

c1,c2,c3,c4,c5=st.columns(5)
c1.metric('Market Regime',state['Market_Regime'],f"{state['Market_State_Score']:.0f}/100")
c2.metric('Breadth proxy',f"{state['Breadth_Proxy_Score']:.0f}/100" if pd.notna(state['Breadth_Proxy_Score']) else 'N/D')
c3.metric('Liquidity',f"{state['Liquidity_Score']:.0f}/100")
c4.metric('Credit',f"{state['Credit_Score']:.0f}/100" if pd.notna(state['Credit_Score']) else 'N/D')
c5.metric('VIX',f"{state['VIX']:.1f}" if pd.notna(state['VIX']) else 'N/D')
st.caption(f"Macro regime: {state['Macro_Regime']} · Scores 0–100. Son clasificaciones probabilísticas, no predicciones.")

st.subheader('🧭 Sector Rotation & Opportunity')
section_note('Opportunity repondera solo evidencia disponible: strength, entry, macro, revisiones y valoración relativa. No inventa 50/100 cuando falta un factor.')
st.dataframe(sectors,use_container_width=True,hide_index=True)

st.subheader('🌊 Market Breadth & Concentration')
a,b,c=st.columns(3)
a.metric('RSP vs SPY · 3M',f"{rel['RSP_vs_SPY_3M_pp']:+.1f} pp" if pd.notna(rel['RSP_vs_SPY_3M_pp']) else 'N/D')
b.metric('IWM vs SPY · 3M',f"{rel['IWM_vs_SPY_3M_pp']:+.1f} pp" if pd.notna(rel['IWM_vs_SPY_3M_pp']) else 'N/D')
c.metric('QQQ vs SPY · 3M',f"{rel['QQQ_vs_SPY_3M_pp']:+.1f} pp" if pd.notna(rel['QQQ_vs_SPY_3M_pp']) else 'N/D')
st.dataframe(breadth,use_container_width=True,hide_index=True)
st.caption('Estos tres ratios son proxies de amplitud/concentración; no se presentan como advance/decline real. El Macro Dashboard conserva el breadth por constituyentes.')

st.subheader('🌐 Cross-Asset Capital Rotation')
st.dataframe(cross,use_container_width=True,hide_index=True)

st.subheader('🧩 Macro Sensitivity Map')
st.dataframe(macro_sensitivity_table(),use_container_width=True,hide_index=True)
st.caption('Sensibilidades estructurales: +2 = fuerte beneficiario, 0 = mixto, -2 = fuerte viento en contra. No son forecasts ni señales automáticas.')

st.subheader('🎯 Opportunity Radar')
radar=opportunity_radar(snap,25)
if radar.empty:
    st.info('No hay snapshot de screener utilizable todavía. Ejecutá un screener/daily refresh para poblar el radar con Quality, Growth, Valuation, Technical, Entry y Revisions disponibles.')
else:
    st.dataframe(radar,use_container_width=True,hide_index=True)

st.subheader('📈 Earnings Revisions & Relative Valuation')
if sectors.empty or ('Revisions' not in sectors and 'Relative Valuation' not in sectors):
    st.info('Sin evidencia agregada disponible.')
else:
    cols=[c for c in ['Sector','ETF','Revisions','Relative Valuation','Opportunity'] if c in sectors]
    st.dataframe(sectors[cols],use_container_width=True,hide_index=True)
st.caption('Valuation aquí es relativa al universo/sector disponible en el último snapshot. No se etiqueta como percentil histórico si no existe historia suficiente.')

st.subheader('💧 Liquidity / Financial Conditions')
liq=pd.DataFrame([['Liquidity composite',state['Liquidity_Score']],['Credit conditions',state['Credit_Score']],['Volatility conditions',state['Volatility_Score']],['Trend',state['Trend_Score']]],columns=['Driver','Score'])
st.dataframe(liq,use_container_width=True,hide_index=True)
st.caption('La capa de liquidez combina proxies públicos de macro/mercado disponibles. Para datos económicos lentos y cobertura FRED, usar Macro Dashboard.')
