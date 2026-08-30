import pandas as pd
import streamlit as st
import yfinance as yf
from core.cache_policy import FUNDAMENTALS_TTL

@st.cache_data(ttl=FUNDAMENTALS_TTL, show_spinner=False)
def get_industry(ticker):
    try:
        info=yf.Ticker(ticker).info or {}
        return {'Sector':info.get('sector','Unknown'),'Industry':info.get('industry','Unknown')}
    except Exception:
        return {'Sector':'Unknown','Industry':'Unknown'}


def industry_leadership(results):
    if results is None or results.empty or 'Industry' not in results:
        return pd.DataFrame()
    metrics=[c for c in ['Trend_Score','Entry_Score','RS_Percentile','Opportunity_Score','Preliminary_Score'] if c in results]
    agg={c:'mean' for c in metrics}; agg['Ticker']='count'
    out=results.groupby(['Sector','Industry'],dropna=False).agg(agg).rename(columns={'Ticker':'Count'}).reset_index()
    sort='Opportunity_Score' if 'Opportunity_Score' in out else 'Preliminary_Score' if 'Preliminary_Score' in out else metrics[0]
    return out.sort_values(sort,ascending=False)
