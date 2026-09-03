import pandas as pd
import streamlit as st

from core.market_data import download_prices, classify_symbol
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset
from core.storage import load_positions, list_alerts
from core.alerts_engine import webhook_status
from core.notification_settings import get_user_webhook
from core.access_control import current_user
from core.ui import hero, section_note
from core.desk_store import load_latest_desk_output

hero('Alert Center','Monitor de señales en vivo + estado de tus alertas persistentes.','Signal Monitor')
user=current_user(); uid=user['user_id']
pos=load_positions(user_id=uid); saved=list_alerts(user_id=uid); channel=webhook_status(get_user_webhook(uid))

hunt=load_latest_desk_output(uid,'daily_opportunity_hunt') or {}
scan=load_latest_desk_output(uid,'event_scan') or {}
hunt_payload=hunt.get('payload') or {}; discovery=hunt_payload.get('discovery') or {}
scan_payload=scan.get('payload') or {}; actionable=scan_payload.get('actionable_events') or []
st.subheader('Background Desk Activity')
c1,c2,c3=st.columns(3)
c1.metric('Verified opportunities',len(discovery.get('verified_opportunities') or []))
c2.metric('Watchlist monitored',len(discovery.get('monitor_tickers') or []))
c3.metric('Latest actionable events',len(actionable))
if actionable:
    st.warning('Material background events: '+' | '.join(
        f"{event.get('ticker')}: {', '.join(event.get('reasons') or [])}" for event in actionable[:5]))
elif hunt_payload:
    st.info(hunt_payload.get('brief',{}).get('headline','Background opportunity hunt available.'))
st.caption(f"Opportunity hunt: {hunt.get('created_at','N/D')} · Intraday scan: {scan.get('created_at','N/D')}")

c1,c2,c3=st.columns(3)
c1.metric('Portfolio positions',len(pos))
c2.metric('Saved alerts',len(saved))
c3.metric('Notification channel',channel['provider'] if channel['configured'] else 'NOT CONFIGURED')

portfolio_ticks=pos['ticker'].astype(str).tolist() if not pos.empty else []
saved_ticks=saved['ticker'].astype(str).tolist() if not saved.empty else []
desk_ticks=[str(t).upper() for t in discovery.get('monitor_tickers') or []]
default=list(dict.fromkeys(portfolio_ticks+saved_ticks+desk_ticks+['BTC-USD','ETH-USD']))[:40]
text=st.text_area('Activos a vigilar',','.join(default),height=90)
threshold=st.slider('Avisar si está a ≤ X% de EMA62/79 (equities)',.5,5.0,2.0,.5)
ticks=[x.strip().upper() for x in text.replace('\n',',').split(',') if x.strip()]

if not ticks:
    st.info('Agregá activos para evaluar señales.'); st.stop()

if st.button('Actualizar señales',type='primary'):
    pm=download_prices(list(dict.fromkeys(ticks+['SPY'])),period='5y'); spy=pm.get('SPY'); alerts=[]; checked=0
    for t in ticks:
        try:
            raw=pm.get(t)
            if raw is None or raw.empty: continue
            checked+=1; typ=classify_symbol(t); r=analyze_asset(t,enrich_indicators(raw),spy,'Alert',typ); msgs=[]
            if typ in {'Acción','ETF','Índice'}:
                d62=r.get('Dist_EMA62_%'); d79=r.get('Dist_EMA79_%')
                if pd.notna(d62) and abs(float(d62))<=threshold: msgs.append(f"EMA62 {float(d62):+.2f}%")
                if pd.notna(d79) and abs(float(d79))<=threshold: msgs.append(f"EMA79 {float(d79):+.2f}%")
            if r.get('Scan_200D_Bounce'): msgs.append('SMA200 context')
            if r.get('Scan_Breakout_Base'): msgs.append('Breakout/Base')
            if r.get('Scan_Extended_Trim'): msgs.append('Extended')
            if pd.notna(r.get('Entry_Score')) and float(r['Entry_Score'])>=75 and float(r.get('Trend_Score',0) or 0)>=65: msgs.append('High Entry Score')
            if msgs:
                alerts.append({'Ticker':t,'Type':typ,'Price':r['Price'],'Trend':r['Trend'],'Entry Score':r['Entry_Score'],'RSI':r['RSI14'],'R/R':r['RR_Text'],'Setup':r['Setup'],'Signals':' · '.join(msgs)})
        except Exception as exc:
            alerts.append({'Ticker':t,'Type':'ERROR','Signals':f'{type(exc).__name__}: no se pudo evaluar'})
    st.session_state['live_alert_rows']=alerts; st.session_state['live_alert_checked']=checked

rows=st.session_state.get('live_alert_rows')
if rows:
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
elif rows is None:
    st.info('La actividad automática ya está cargada. Pulsá “Actualizar señales” solamente si querés ejecutar ahora el análisis manual de estos activos.')
else:
    st.success('No hay señales activas con los criterios seleccionados.')
if rows is not None:
    st.caption(f"Última evaluación en esta sesión: {st.session_state.get('live_alert_checked',0)} activos con datos válidos.")
section_note('The live controls on this page are manual. Saved Alerts, Daily Opportunity Hunt and the 30-minute portfolio/watchlist monitor run in GitHub Actions even while the web is closed.')
