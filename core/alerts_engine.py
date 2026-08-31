import os
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


def send_webhook(message, url=''):
    target=_webhook_url(url)
    if not target: return False
    provider=webhook_status(target)['provider']
    payload={'content':str(message)} if provider=='DISCORD' else {'text':str(message)} if provider=='SLACK' else {'text':str(message),'content':str(message)}
    try:
        r=requests.post(target,json=payload,timeout=10)
        return 200<=r.status_code<300
    except Exception:
        return False
