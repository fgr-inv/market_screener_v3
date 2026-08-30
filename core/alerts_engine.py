import os
import requests
import pandas as pd
from core.indicators import enrich_indicators
from core.market_data import classify_symbol, get_live_price
from core.asset_models import analyze_asset


def evaluate_rule(rule, price_map, spy=None):
    t=rule['ticker']; raw=price_map.get(t)
    if raw is None or raw.empty: return False,'No data'
    typ_asset=classify_symbol(t)
    h=enrich_indicators(raw); r=analyze_asset(t,h,spy,'Alert',typ_asset)
    typ=rule['rule_type']; th=float(rule['threshold']); hit=False; msg=''
    if typ=='EMA62_DISTANCE':
        # Legacy rule retained for saved alerts. For non-equities, prefer ENTRY_SCORE_ABOVE.
        hit=abs(r['Dist_EMA62_%'])<=th; msg=f"{t}: EMA62 distance {r['Dist_EMA62_%']:+.2f}% ({r.get('Analysis_Model')})"
    elif typ=='EMA79_DISTANCE':
        hit=abs(r['Dist_EMA79_%'])<=th; msg=f"{t}: EMA79 distance {r['Dist_EMA79_%']:+.2f}% ({r.get('Analysis_Model')})"
    elif typ=='ENTRY_SCORE_ABOVE':
        hit=r['Entry_Score']>=th; msg=f"{t}: Entry Score {r['Entry_Score']} ({r.get('Analysis_Model')})"
    elif typ=='PRICE_BELOW':
        live=get_live_price(t); px=float(live if live is not None else r['Price'])
        hit=px<=th; msg=f"{t}: price {px:.6g} <= {th:.6g}"
    elif typ=='PRICE_ABOVE':
        live=get_live_price(t); px=float(live if live is not None else r['Price'])
        hit=px>=th; msg=f"{t}: price {px:.6g} >= {th:.6g}"
    elif typ=='RR_ABOVE':
        hit=pd.notna(r['RR']) and r['RR']>=th; msg=f"{t}: R/R {r['RR_Text']}"
    return bool(hit),msg


def send_webhook(message, url=''):
    url=url or os.getenv('ALERT_WEBHOOK_URL','')
    if not url:
        try:
            import streamlit as st
            url=str(st.secrets.get('ALERT_WEBHOOK_URL',''))
        except Exception: pass
    if not url: return False
    try:
        r=requests.post(url,json={'content':message,'text':message},timeout=8)
        return 200<=r.status_code<300
    except Exception: return False
