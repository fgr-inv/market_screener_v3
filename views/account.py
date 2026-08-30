import pandas as pd
import streamlit as st
from core.ui import hero
from core.access_control import current_user, quota_status
from core.plans import PLANS, plan_config, is_owner
from core.production_storage import storage_mode, cloud_available

hero('Account & Plan','Plan, permisos y consumo de la cuenta actual.','Subscriptions & Usage')
u=current_user(); cfg=plan_config(u['plan'])
c1,c2,c3,c4=st.columns(4)
c1.metric('Plan',u['plan']); c2.metric('Role',u['role']); c3.metric('Storage',storage_mode()); c4.metric('Quota mode','EXEMPT' if is_owner(u['plan']) else 'METERED')
st.caption(f"User ID: {u['user_id']} · Plan source: {u['plan_source']} · DATABASE_URL: {'configured' if cloud_available() else 'not configured'}")
if is_owner(u['plan']):
    st.success('👑 OWNER: sin cuotas comerciales. El cache y los límites globales de proveedores siguen activos para proteger las APIs.')

rows=[]
for feature in ['technical_screener','fundamental_screener','combined_screener','asset_technical','asset_deep']:
    s=quota_status(feature,u)
    rows.append({'Feature':feature,'Today':('∞' if s.get('exempt') else s['daily_used']),'Daily limit':('∞' if s.get('exempt') else s['daily_limit']),
                 'Month':('∞' if s.get('exempt') else s['monthly_used']),'Monthly limit':('∞' if s.get('exempt') else s['monthly_limit'])})
st.subheader('Usage')
st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
st.subheader('Entitlements')
ent={k:v for k,v in cfg.items() if k!='quotas'}
st.dataframe(pd.DataFrame([{'Entitlement':k,'Value':v} for k,v in ent.items()]),use_container_width=True,hide_index=True)

st.subheader('Plan matrix')
plan_rows=[]
for name,p in PLANS.items():
    plan_rows.append({'Plan':name,'Max assets':p['max_screener_assets'],'Deep Top N':p['max_deep_candidates'],'Workers':p['max_workers'],
                      'Fundamental':p['fundamental_screener'],'Combined':p['combined_screener'],'DCF':p['dcf'],'Quota exempt':p.get('quota_exempt',False)})
st.dataframe(pd.DataFrame(plan_rows),use_container_width=True,hide_index=True)
st.caption('OWNER no se asigna desde Stripe. Configuralo server-side con OWNER_USER_IDS / OWNER_EMAILS o DEV_USER_ROLE=OWNER en desarrollo.')
