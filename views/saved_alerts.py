import pandas as pd
import streamlit as st

from core.storage import (
    add_alert, list_alerts, delete_alert, set_alert_enabled, list_alert_states,
    alert_storage_health,
)
from core.market_data import download_prices
from core.alerts_engine import evaluate_rule, send_webhook, webhook_status, build_discord_channel_test
from core.notification_settings import get_user_webhook, set_user_webhook, clear_user_webhook, masked_webhook
from core.production_storage import storage_mode, cloud_available
from core.ui import hero, section_note
from core.access_control import current_user
from core.plans import plan_config

RULE_LABELS = {
    'PRICE_BELOW': 'Precio por debajo de',
    'PRICE_ABOVE': 'Precio por encima de',
    'ENTRY_SCORE_ABOVE': 'Entry Score por encima de',
    'RR_ABOVE': 'R/R por encima de',
    'EMA62_DISTANCE': 'Distancia a EMA62 ≤',
    'EMA79_DISTANCE': 'Distancia a EMA79 ≤',
}
LABEL_TO_RULE = {v: k for k, v in RULE_LABELS.items()}


def _threshold_widget(rule_type: str):
    if rule_type in {'PRICE_BELOW', 'PRICE_ABOVE'}:
        return st.number_input('Precio objetivo', min_value=0.000001, value=100.0, step=1.0, format='%.6f')
    if rule_type == 'ENTRY_SCORE_ABOVE':
        return st.number_input('Entry Score mínimo', min_value=0.0, max_value=100.0, value=75.0, step=1.0)
    if rule_type == 'RR_ABOVE':
        return st.number_input('R/R mínimo', min_value=0.0, value=2.0, step=0.1, format='%.2f')
    return st.number_input('Distancia máxima (%)', min_value=0.0, value=2.0, step=0.25, format='%.2f',
                           help='Usa la distancia absoluta a la media. Ej.: 2 = dentro de ±2%.')


hero('Saved Alerts', 'Alertas persistentes con edge triggering, cooldown y ejecución automática.', 'Alert Manager V11.23')
user=current_user(); uid=user['user_id']; cfg=plan_config(user['plan']); max_alerts=cfg.get('max_saved_alerts')
health=alert_storage_health(); mode=storage_mode(); user_webhook=get_user_webhook(uid); channel=webhook_status(user_webhook)
alerts=list_alerts(user_id=uid)
states=list_alert_states()
if not states.empty and not alerts.empty:
    ids=set(pd.to_numeric(alerts['id'],errors='coerce').dropna().astype(int))
    states=states[pd.to_numeric(states['alert_id'],errors='coerce').isin(ids)]

m1,m2,m3,m4=st.columns(4)
m1.metric('Saved',len(alerts))
m2.metric('Active',int(alerts['enabled'].fillna(False).sum()) if not alerts.empty else 0)
m3.metric('Storage',mode)
m4.metric('Notifications',channel['provider'] if channel['configured'] else 'NOT CONFIGURED')

if not health.get('ok'): st.error(f"Storage error: {health.get('message','sin detalle')}")
elif cloud_available(): st.success('Persistencia Postgres activa: Streamlit y GitHub Actions comparten el mismo estado.')
else: st.warning('Modo local: sirve para desarrollo, pero Streamlit Cloud puede perder estado. Para alertas automáticas usá DATABASE_URL.')
st.subheader('Canal de notificaciones')
st.caption(f"Canal actual: {masked_webhook(uid)}")
with st.expander('Configurar webhook personal', expanded=not channel['configured']):
    webhook_input=st.text_input('Webhook URL',type='password',placeholder='Discord / Slack webhook HTTPS',help='Se guarda por usuario. No se muestra completo en la interfaz.')
    wc1,wc2=st.columns(2)
    if wc1.button('Guardar webhook',width='stretch'):
        try:
            set_user_webhook(uid,webhook_input,enabled=True); st.success('Webhook guardado.'); st.rerun()
        except Exception as exc: st.error(str(exc))
    if wc2.button('Eliminar webhook',width='stretch'):
        try:
            clear_user_webhook(uid); st.success('Webhook eliminado.'); st.rerun()
        except Exception as exc: st.error(str(exc))
if not channel['configured']:
    st.warning('No tenés un canal configurado. Las reglas se evaluarán, pero no podrán enviarte avisos.')
else:
    if st.button('Enviar notificación de prueba'):
        ok=send_webhook('✅ Market Screener: canal de alertas funcionando.',url=user_webhook,
                        discord_embed=build_discord_channel_test())
        st.success('Notificación enviada.') if ok else st.error('El webhook rechazó o no recibió la prueba.')

st.subheader('Crear alerta')
# Selector outside the form: Streamlit forms do not rerun when a selectbox changes.
rule_label=st.selectbox('Condición',list(LABEL_TO_RULE.keys()),key='saved_alert_rule')
rule_type=LABEL_TO_RULE[rule_label]
with st.form('create_saved_alert', clear_on_submit=False):
    c1,c2=st.columns([1,1.2])
    with c1:
        ticker=st.text_input('Ticker','BTC-USD',help='Ej.: META, NVDA, BTC-USD, ETH-USD').strip().upper()
        threshold=_threshold_widget(rule_type)
    with c2:
        cooldown=st.number_input('Cooldown (minutos)',min_value=0,max_value=10080,value=240,step=60,
                                 help='Solo aplica si “Repetir mientras siga verdadera” está activo.')
        repeat=st.checkbox('Repetir mientras siga verdadera',value=False)
        note=st.text_input('Nota (opcional)','',max_chars=240,placeholder='Ej.: revisar entrada si llega a esta zona')
        enabled=st.checkbox('Activar inmediatamente',value=True)
    submitted=st.form_submit_button('🔔 Crear alerta',type='primary',width='stretch')

if submitted:
    if not ticker: st.error('Ingresá un ticker válido.')
    elif max_alerts is not None and len(alerts)>=int(max_alerts): st.error(f"Alcanzaste el máximo de {max_alerts} alertas para {user['plan']}.")
    else:
        try:
            aid=add_alert(ticker,rule_type,threshold,note,cooldown_minutes=cooldown,repeat_while_true=repeat,enabled=enabled,user_id=uid)
            st.success(f'Alerta #{aid} creada para {ticker}.'); st.rerun()
        except Exception as exc: st.error(f'No se pudo guardar la alerta: {exc}')

st.divider(); st.subheader('Tus alertas')
if alerts.empty:
    st.info('Todavía no tenés alertas guardadas.')
else:
    show=alerts.merge(states,left_on='id',right_on='alert_id',how='left') if not states.empty else alerts.copy()
    display=show.copy(); display['Condición']=display['rule_type'].map(RULE_LABELS).fillna(display['rule_type'])
    rename={'ticker':'Ticker','threshold':'Umbral','enabled':'Activa','note':'Nota','cooldown_minutes':'Cooldown min','repeat_while_true':'Repite',
            'last_hit':'Cumpliéndose','last_triggered_at':'Último aviso','last_evaluated_at':'Última evaluación','last_message':'Último mensaje','trigger_count':'Avisos'}
    display=display.rename(columns=rename)
    cols=['id','Ticker','Condición','Umbral','Activa','Nota','Cooldown min','Repite','Cumpliéndose','Último aviso','Última evaluación','Avisos','Último mensaje']
    st.dataframe(display[[c for c in cols if c in display.columns]],width='stretch',hide_index=True)

    if st.button('▶ Evaluar ahora',width='content'):
        active=alerts[alerts['enabled']==True]
        if active.empty: st.warning('No hay alertas activas.')
        else:
            with st.spinner('Evaluando con datos de mercado...'):
                ticks=active['ticker'].dropna().astype(str).unique().tolist(); pm=download_prices(list(dict.fromkeys(ticks+['SPY'])),period='2y'); spy=pm.get('SPY'); rows=[]
                for _,r in active.iterrows():
                    try:
                        hit,msg=evaluate_rule(r,pm,spy); rows.append({'ID':r['id'],'Ticker':r['ticker'],'Condición':RULE_LABELS.get(r['rule_type'],r['rule_type']),'Se cumple':bool(hit),'Resultado':msg})
                    except Exception as exc:
                        rows.append({'ID':r['id'],'Ticker':r['ticker'],'Condición':r['rule_type'],'Se cumple':False,'Resultado':f'ERROR: {exc}'})
                st.dataframe(pd.DataFrame(rows),width='stretch',hide_index=True)

    st.subheader('Administrar')
    options={int(r['id']):f"#{int(r['id'])} · {r['ticker']} · {RULE_LABELS.get(r['rule_type'],r['rule_type'])} {r['threshold']}" for _,r in alerts.iterrows()}
    ids=list(options); c1,c2=st.columns(2)
    with c1:
        aid=st.selectbox('Activar/desactivar',ids,format_func=lambda x:options[x],key='manage_alert')
        current=bool(alerts.loc[alerts['id']==aid,'enabled'].iloc[0]); value=st.checkbox('Activa',value=current,key=f'enabled_{aid}')
        if st.button('Guardar estado',width='stretch'):
            try: set_alert_enabled(aid,value,user_id=uid); st.success('Estado actualizado.'); st.rerun()
            except Exception as exc: st.error(str(exc))
    with c2:
        did=st.selectbox('Eliminar',ids,format_func=lambda x:options[x],key='delete_alert')
        confirm=st.checkbox('Confirmo que quiero eliminarla',key=f'confirm_delete_{did}')
        if st.button('🗑️ Eliminar alerta',disabled=not confirm,width='stretch'):
            try: delete_alert(did,user_id=uid); st.success('Alerta eliminada.'); st.rerun()
            except Exception as exc: st.error(str(exc))

section_note('Por defecto se avisa una sola vez al pasar FALSE → TRUE. Si el envío falla, el runner conserva la alerta sin armar para reintentar en la próxima ejecución. “Repetir” permite nuevos avisos tras el cooldown.')
