import pandas as pd, streamlit as st
from core.market_data import download_prices, classify_symbol
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset
from core.ui import hero

hero('Alerts','Alertas adaptadas al tipo de activo; EMA62/79 queda como referencia adicional para equities.','Signal Monitor')
default=list(dict.fromkeys(['BTC-USD','ETH-USD']+st.session_state.portfolio_tickers))
text=st.text_area('Activos a vigilar',','.join(default),height=90)
threshold=st.slider('Referencia: avisar si está a ≤ X% de EMA62/79',.5,5.0,2.0,.5)
ticks=[x.strip().upper() for x in text.replace('\n',',').split(',') if x.strip()]
pm=download_prices(list(dict.fromkeys(ticks+['SPY'])),period='5y'); spy=pm.get('SPY'); alerts=[]
for t in ticks:
    try:
        raw=pm.get(t)
        if raw is None or raw.empty: continue
        typ=classify_symbol(t); r=analyze_asset(t,enrich_indicators(raw),spy,'Alert',typ); msgs=[]
        if typ in {'Acción','ETF','Índice'}:
            if abs(r['Dist_EMA62_%'])<=threshold: msgs.append(f"EMA62 {r['Dist_EMA62_%']:+.2f}%")
            if abs(r['Dist_EMA79_%'])<=threshold: msgs.append(f"EMA79 {r['Dist_EMA79_%']:+.2f}%")
        if r.get('Scan_200D_Bounce'): msgs.append('SMA200 context')
        if r.get('Scan_Breakout_Base'): msgs.append('Breakout/Base')
        if r.get('Scan_Extended_Trim'): msgs.append('Extended')
        if r['Entry_Score']>=75 and r['Trend_Score']>=65: msgs.append('High Entry Score')
        if msgs:
            alerts.append({'Ticker':t,'Type':typ,'Model':r.get('Analysis_Model'),'Price':r['Price'],'Trend':r['Trend'],'Entry Score':r['Entry_Score'],
                           'RSI':r['RSI14'],'R/R':r['RR_Text'],'Setup':r['Setup'],'Alerts':' · '.join(msgs)})
    except Exception as exc:
        st.caption(f'{t}: no se pudo evaluar ({type(exc).__name__})')
if alerts:
    st.dataframe(pd.DataFrame(alerts),use_container_width=True,hide_index=True)
else:
    st.success('No hay alertas activas.')
st.caption('Para cripto/bonos/commodities/FX se prioriza Entry Score y el modelo específico; no se fuerza la misma distancia EMA que en acciones.')
