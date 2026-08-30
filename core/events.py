from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import yfinance as yf
from core.cache_policy import EVENT_TTL

@st.cache_data(ttl=EVENT_TTL,show_spinner=False)
def earnings_event(ticker):
    out={'next_earnings':'N/D','days_to_earnings':None,'risk':'UNKNOWN'}
    try:
        cal=yf.Ticker(ticker).calendar
        ed=None
        if isinstance(cal,dict):
            ed=cal.get('Earnings Date')
            if isinstance(ed,(list,tuple)) and ed: ed=ed[0]
        if ed is not None:
            ts=pd.Timestamp(ed)
            if ts.tzinfo is not None: ts=ts.tz_convert(None)
            now=pd.Timestamp.now().normalize()
            days=(ts.normalize()-now).days
            out['next_earnings']=str(ts.date()); out['days_to_earnings']=days
            out['risk']='HIGH' if 0<=days<=3 else 'ELEVATED' if 4<=days<=7 else 'NORMAL'
    except Exception: pass
    return out


def event_risk_penalty(event):
    d=event.get('days_to_earnings')
    if d is None: return 0
    if 0<=d<=1: return -15
    if 2<=d<=3: return -10
    if 4<=d<=7: return -5
    return 0
