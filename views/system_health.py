import os
from pathlib import Path
import pandas as pd
import streamlit as st

from core.provider_health import provider_health
from core.institutional_providers import provider_capabilities
from core.model_registry import model_label
from core.storage import load_score_history,list_alerts,list_alert_states,sync_local_state_to_cloud
from core.production_storage import cloud_available,storage_mode,ensure_production_schema
from core.point_in_time import point_in_time_status
from core.monitoring import recent_errors
from core.ui import hero,section_note

hero('System Health','Proveedores, persistencia, snapshots, errores y data integrity.','Observability V8')

c1,c2,c3,c4=st.columns(4)
c1.metric('Active model',model_label())
c2.metric('Storage',storage_mode())
c3.metric('Point-in-time index','AVAILABLE' if point_in_time_status('SP500')['available'] else 'MISSING')
c4.metric('Alerts',len(list_alerts(enabled_only=True)))

if cloud_available():
    ok,msg=ensure_production_schema()
    if ok:
        st.success('Cloud DB schema OK')
    else:
        st.error(f'Cloud DB problem: {msg}')
    if st.button('Sync local fallback state → Cloud DB'):
        st.dataframe(sync_local_state_to_cloud(),use_container_width=True,hide_index=True)
else:
    st.warning('DATABASE_URL no está configurado. La app usa DuckDB + CSV/GitHub fallback; para compartir estado entre Streamlit y Actions, Postgres/Supabase es la opción recomendada.')

if st.button('Run provider checks',type='primary'):
    st.session_state['provider_health']=provider_health()
health=st.session_state.get('provider_health')
if health is not None: st.dataframe(health,use_container_width=True,hide_index=True)

st.subheader('Provider capabilities'); st.dataframe(provider_capabilities(),use_container_width=True,hide_index=True)

root=Path(__file__).resolve().parents[1]; snap=root/'data'/'snapshots'; cache=root/'data'/'cache'/'prices'
rows=[]
for p in sorted(snap.glob('*')):
    if p.is_file(): rows.append({'File':p.name,'Size KB':round(p.stat().st_size/1024,1),'Modified':pd.Timestamp(p.stat().st_mtime,unit='s')})
st.subheader('Snapshots'); st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

m1,m2,m3=st.columns(3)
m1.metric('Price cache files',len(list(cache.glob('*'))) if cache.exists() else 0)
m2.metric('Score history rows (30d)',len(load_score_history(days=30)))
m3.metric('Alert state rows',len(list_alert_states()))

st.subheader('Recent structured errors')
errs=recent_errors(100)
if errs.empty: st.success('No structured runtime errors recorded in this filesystem.')
else: st.dataframe(errs,use_container_width=True,hide_index=True)
section_note('En Streamlit Cloud el filesystem puede ser efímero; para observability multi-instance conviene enviar logs a un servicio externo más adelante.')

st.subheader('Secrets / integrations')
keys=['FRED_API_KEY','EIA_API_KEY','FMP_API_KEY','COINGECKO_API_KEY','POLYGON_API_KEY','FINNHUB_API_KEY','NASDAQ_DATA_LINK_API_KEY','DATABASE_URL','ALPACA_API_KEY','GITHUB_REPO','GITHUB_PAT','ALERT_WEBHOOK_URL']
status=[]
for k in keys:
    exists=False
    try: exists=k in st.secrets and bool(st.secrets[k])
    except Exception: exists=bool(os.getenv(k))
    status.append({'Integration':k,'Configured':exists})
st.dataframe(pd.DataFrame(status),use_container_width=True,hide_index=True)
