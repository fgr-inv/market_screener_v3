import pandas as pd
import streamlit as st

from core.storage import (
    add_alert, list_alerts, delete_alert, set_alert_enabled, list_alert_states,
    alert_storage_health,
)
from core.market_data import download_prices
from core.alerts_engine import evaluate_rule
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
        return st.number_input('Precio objetivo', min_value=0.000001, value=100.0, step=1.0, format='%.6f',
                               help='La alerta se activa cuando el precio cruza/queda del lado indicado del umbral.')
    if rule_type == 'ENTRY_SCORE_ABOVE':
        return st.number_input('Entry Score mínimo', min_value=0.0, max_value=100.0, value=75.0, step=1.0)
    if rule_type == 'RR_ABOVE':
        return st.number_input('R/R mínimo', min_value=0.0, value=2.0, step=0.1, format='%.2f')
    return st.number_input('Distancia máxima (%)', min_value=0.0, value=2.0, step=0.25, format='%.2f',
                           help='Usa la distancia absoluta a la media. Ej.: 2 = dentro de ±2%.')


hero('Saved Alerts', 'Creá, probá y administrá alertas persistentes sin depender de tener la web abierta.', 'Alert Manager V11.16')

user = current_user()
uid = user['user_id']
cfg = plan_config(user['plan'])
max_alerts = cfg.get('max_saved_alerts')

health = alert_storage_health()
mode = storage_mode()
if health.get('ok'):
    storage_text = f"Storage: **{mode}** · estado: **OK**"
else:
    storage_text = f"Storage: **{mode}** · estado: **ERROR** — {health.get('message','sin detalle')}"
st.caption(storage_text)
if cloud_available():
    st.caption('Postgres comparte las alertas entre Streamlit y GitHub Actions cuando DATABASE_URL está configurado en ambos.')
else:
    st.warning('DATABASE_URL no está configurado: las alertas quedan solo en almacenamiento local y no son adecuadas para producción multiusuario.')

st.subheader('Crear alerta')
with st.form('create_saved_alert', clear_on_submit=False):
    c1, c2 = st.columns([1, 1.35])
    with c1:
        ticker = st.text_input('Ticker', 'BTC-USD', help='Ej.: META, NVDA, BTC-USD, ETH-USD').strip().upper()
        rule_label = st.selectbox('Condición', list(LABEL_TO_RULE.keys()))
        rule_type = LABEL_TO_RULE[rule_label]
        threshold = _threshold_widget(rule_type)
    with c2:
        cooldown = st.number_input('Cooldown (minutos)', min_value=0, max_value=10080, value=240, step=60,
                                   help='Solo aplica si activás “Repetir mientras siga verdadera”.')
        repeat = st.checkbox('Repetir mientras siga verdadera', value=False,
                             help='Desactivado: alerta solo en FALSE → TRUE. Activado: puede repetir tras el cooldown.')
        note = st.text_input('Nota (opcional)', '', max_chars=240, placeholder='Ej.: zona donde quiero revisar entrada')
        enabled = st.checkbox('Activar inmediatamente', value=True)
    submitted = st.form_submit_button('🔔 Crear alerta', type='primary', use_container_width=True)

if submitted:
    if not ticker:
        st.error('Ingresá un ticker válido.')
    elif max_alerts is not None and len(list_alerts(user_id=uid)) >= int(max_alerts):
        st.error(f"Alcanzaste el máximo de {max_alerts} alertas guardadas para el plan {user['plan']}.")
    else:
        try:
            alert_id = add_alert(ticker, rule_type, threshold, note, cooldown_minutes=cooldown,
                                 repeat_while_true=repeat, enabled=enabled, user_id=uid)
            st.success(f'Alerta #{alert_id} creada para {ticker}.')
            st.rerun()
        except Exception as exc:
            st.error(f'No se pudo guardar la alerta: {exc}')

st.divider()
st.subheader('Tus alertas')
alerts = list_alerts(user_id=uid)
states = list_alert_states()

if alerts.empty:
    st.info('Todavía no tenés alertas guardadas. Creá la primera arriba.')
else:
    show = alerts.merge(states, left_on='id', right_on='alert_id', how='left') if not states.empty else alerts.copy()
    display = show.copy()
    if 'rule_type' in display.columns:
        display['Condición'] = display['rule_type'].map(RULE_LABELS).fillna(display['rule_type'])
    rename = {
        'ticker': 'Ticker', 'threshold': 'Umbral', 'enabled': 'Activa', 'note': 'Nota',
        'cooldown_minutes': 'Cooldown min', 'repeat_while_true': 'Repite',
        'last_hit': 'Cumpliéndose', 'last_triggered_at': 'Último aviso',
        'last_evaluated_at': 'Última evaluación', 'last_message': 'Último mensaje', 'trigger_count': 'Avisos',
    }
    cols = ['id','Ticker','Condición','Umbral','Activa','Nota','Cooldown min','Repite',
            'Cumpliéndose','Último aviso','Última evaluación','Avisos','Último mensaje']
    display = display.rename(columns=rename)
    st.dataframe(display[[c for c in cols if c in display.columns]], use_container_width=True, hide_index=True)

    ctest, _ = st.columns([1, 2])
    with ctest:
        if st.button('▶ Evaluar ahora', use_container_width=True):
            active = alerts[alerts['enabled'] == True]
            if active.empty:
                st.warning('No hay alertas activas para evaluar.')
            else:
                with st.spinner('Evaluando alertas con datos de mercado...'):
                    ticks = active['ticker'].dropna().astype(str).unique().tolist()
                    pm = download_prices(list(dict.fromkeys(ticks + ['SPY'])), period='2y')
                    spy = pm.get('SPY')
                    rows = []
                    for _, r in active.iterrows():
                        try:
                            hit, msg = evaluate_rule(r, pm, spy)
                            rows.append({'ID': r['id'], 'Ticker': r['ticker'], 'Condición': RULE_LABELS.get(r['rule_type'], r['rule_type']),
                                         'Se cumple': bool(hit), 'Resultado': msg})
                        except Exception as exc:
                            rows.append({'ID': r['id'], 'Ticker': r['ticker'], 'Condición': r['rule_type'],
                                         'Se cumple': False, 'Resultado': f'ERROR: {exc}'})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader('Administrar')
    alert_options = {
        int(r['id']): f"#{int(r['id'])} · {r['ticker']} · {RULE_LABELS.get(r['rule_type'], r['rule_type'])} {r['threshold']}"
        for _, r in alerts.iterrows()
    }
    ids = list(alert_options)
    c1, c2 = st.columns(2)
    with c1:
        aid = st.selectbox('Alerta a activar/desactivar', ids, format_func=lambda x: alert_options[x], key='manage_alert')
        current_enabled = bool(alerts.loc[alerts['id'] == aid, 'enabled'].iloc[0])
        enabled_value = st.checkbox('Activa', value=current_enabled, key=f'enabled_{aid}')
        if st.button('Guardar estado', use_container_width=True):
            set_alert_enabled(aid, enabled_value, user_id=uid)
            st.success('Estado actualizado.')
            st.rerun()
    with c2:
        did = st.selectbox('Alerta a eliminar', ids, format_func=lambda x: alert_options[x], key='delete_alert')
        confirm = st.checkbox('Confirmo que quiero eliminarla', key=f'confirm_delete_{did}')
        if st.button('🗑️ Eliminar alerta', disabled=not confirm, use_container_width=True):
            delete_alert(did, user_id=uid)
            st.success('Alerta eliminada.')
            st.rerun()

section_note('Edge triggering: por defecto se avisa una sola vez cuando la condición pasa de FALSE a TRUE. Se rearma cuando vuelve a FALSE. “Repetir mientras siga verdadera” habilita nuevos avisos después del cooldown.')
