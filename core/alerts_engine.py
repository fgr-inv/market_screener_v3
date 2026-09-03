import os
from datetime import datetime, timezone
import requests
import pandas as pd

from core.indicators import enrich_indicators
from core.market_data import classify_symbol, get_live_price
from core.asset_models import analyze_asset


def evaluate_rule(rule, price_map, spy=None):
    t=str(rule['ticker']).upper(); raw=price_map.get(t)
    if raw is None or raw.empty: return False,'No market data'
    typ_asset=classify_symbol(t)
    h=enrich_indicators(raw); r=analyze_asset(t,h,spy,'Alert',typ_asset)
    typ=rule['rule_type']; th=float(rule['threshold']); hit=False; msg=''
    if typ=='EMA62_DISTANCE':
        v=r.get('Dist_EMA62_%')
        hit=pd.notna(v) and abs(float(v))<=th; msg=f"{t}: EMA62 distance {float(v):+.2f}%" if pd.notna(v) else f'{t}: EMA62 unavailable'
    elif typ=='EMA79_DISTANCE':
        v=r.get('Dist_EMA79_%')
        hit=pd.notna(v) and abs(float(v))<=th; msg=f"{t}: EMA79 distance {float(v):+.2f}%" if pd.notna(v) else f'{t}: EMA79 unavailable'
    elif typ=='ENTRY_SCORE_ABOVE':
        v=r.get('Entry_Score')
        hit=pd.notna(v) and float(v)>=th; msg=f"{t}: Entry Score {float(v):.1f} >= {th:.1f}" if pd.notna(v) else f'{t}: Entry Score unavailable'
    elif typ=='PRICE_BELOW':
        live=get_live_price(t); px=float(live if live is not None else r['Price'])
        hit=px<=th; msg=f"{t}: price {px:.6g} <= {th:.6g}"
    elif typ=='PRICE_ABOVE':
        live=get_live_price(t); px=float(live if live is not None else r['Price'])
        hit=px>=th; msg=f"{t}: price {px:.6g} >= {th:.6g}"
    elif typ=='RR_ABOVE':
        v=r.get('RR')
        hit=pd.notna(v) and float(v)>=th; msg=f"{t}: R/R {r.get('RR_Text',v)} >= {th:.2f}" if pd.notna(v) else f'{t}: R/R unavailable'
    else:
        raise ValueError(f'Unsupported alert rule: {typ}')
    return bool(hit),msg


def _webhook_url(url=''):
    value=str(url or os.getenv('ALERT_WEBHOOK_URL','') or '').strip()
    if value: return value
    try:
        import streamlit as st
        return str(st.secrets.get('ALERT_WEBHOOK_URL','') or '').strip()
    except Exception:
        return ''


def webhook_status(url=''):
    value=_webhook_url(url)
    if not value: return {'configured':False,'provider':'NONE'}
    low=value.lower()
    provider='DISCORD' if 'discord.com/api/webhooks' in low or 'discordapp.com/api/webhooks' in low else 'SLACK' if 'hooks.slack.com' in low else 'GENERIC'
    return {'configured':True,'provider':provider}


RULE_REPORT_LABELS={
    'PRICE_BELOW':'Precio por debajo del nivel','PRICE_ABOVE':'Precio por encima del nivel',
    'ENTRY_SCORE_ABOVE':'Entry Score por encima del mínimo','RR_ABOVE':'R/R por encima del mínimo',
    'EMA62_DISTANCE':'Precio cerca de EMA62','EMA79_DISTANCE':'Precio cerca de EMA79',
}


def _report_clip(value,limit):
    text=str(value or '').strip().replace('\x00','')
    return text if len(text)<=limit else text[:max(0,limit-1)].rstrip()+'…'


def build_discord_rule_alert(alert,message,trigger_reason='EDGE',now=None):
    """Build a compact saved-alert embed without interpreting it as a trade signal."""
    ticker=str(alert.get('ticker') or 'ACTIVO').upper(); rule=str(alert.get('rule_type') or 'ALERTA')
    reason={'EDGE':'Nueva activación','COOLDOWN':'Repetición después del cooldown'}.get(str(trigger_reason),str(trigger_reason))
    fields=[{'name':'Condición','value':_report_clip(RULE_REPORT_LABELS.get(rule,rule.replace('_',' ').title()),1024),'inline':True},
            {'name':'Umbral configurado','value':_report_clip(alert.get('threshold','N/D'),1024),'inline':True},
            {'name':'Tipo de aviso','value':_report_clip(reason,1024),'inline':True}]
    note=str(alert.get('note') or '').strip()
    if note: fields.append({'name':'Tu nota','value':_report_clip(note,1024),'inline':False})
    fields.append({'name':'Próximo paso','value':'Confirmar el dato y revisar el activo en la aplicación antes de tomar una decisión.','inline':False})
    stamp=now if isinstance(now,datetime) else datetime.now(timezone.utc)
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
    color=0x2ECC71 if rule in {'PRICE_ABOVE','ENTRY_SCORE_ABOVE','RR_ABOVE'} else 0xF39C12 if rule.startswith('EMA') else 0x3498DB
    return {'author':{'name':'Market Screener Pro · Saved Alerts'},'title':_report_clip(f'🔔 {ticker} · condición alcanzada',256),
            'description':_report_clip(message,1400),'color':color,'fields':fields[:25],
            'timestamp':stamp.astimezone(timezone.utc).isoformat(),
            'footer':{'text':'SHADOW MODE · Alerta informativa · Ninguna orden fue enviada'}}


def build_discord_channel_test(now=None):
    stamp=now if isinstance(now,datetime) else datetime.now(timezone.utc)
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
    return {'author':{'name':'Market Screener Pro · Investment Desk'},
            'title':'✅ Canal de informes conectado',
            'description':'Discord está listo para recibir los nuevos informes estructurados.',
            'color':0x2ECC71,
            'fields':[{'name':'Alertas inmediatas','value':'Solo ante eventos materiales o reglas guardadas que se activen.','inline':False},
                      {'name':'Informe premarket','value':'Un resumen del CIO por cada día hábil.','inline':False}],
            'timestamp':stamp.astimezone(timezone.utc).isoformat(),
            'footer':{'text':'SHADOW MODE · Prueba de formato · Ninguna orden fue enviada'}}


def send_webhook(message, url='', discord_embed=None):
    target=_webhook_url(url)
    if not target: return False
    provider=webhook_status(target)['provider']
    if provider=='DISCORD' and isinstance(discord_embed,dict):
        payload={'username':'Investment Desk','embeds':[discord_embed],'allowed_mentions':{'parse':[]}}
    elif provider=='DISCORD': payload={'content':_report_clip(message,1950),'allowed_mentions':{'parse':[]}}
    elif provider=='SLACK': payload={'text':str(message)}
    else: payload={'text':str(message),'content':str(message)}
    try:
        request_kwargs={'json':payload,'timeout':10}
        if provider=='DISCORD': request_kwargs['params']={'wait':'true'}
        r=requests.post(target,**request_kwargs)
        return 200<=r.status_code<300
    except Exception:
        return False
