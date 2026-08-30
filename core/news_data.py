import pandas as pd
import streamlit as st
import yfinance as yf
from core.cache_policy import NEWS_TTL

@st.cache_data(ttl=NEWS_TTL,show_spinner=False)
def get_news(ticker,limit=12):
    rows=[]
    try:
        items=yf.Ticker(ticker).news or []
        for item in items[:limit]:
            content=item.get('content',item) if isinstance(item,dict) else {}
            title=content.get('title') or item.get('title')
            provider=content.get('provider',{}) if isinstance(content.get('provider',{}),dict) else {}
            pub=content.get('pubDate') or item.get('providerPublishTime')
            url=None
            click=content.get('clickThroughUrl') or content.get('canonicalUrl')
            if isinstance(click,dict): url=click.get('url')
            elif isinstance(click,str): url=click
            rows.append({'Title':title,'Publisher':provider.get('displayName',item.get('publisher','')),'Published':pub,'URL':url})
    except Exception: pass
    return pd.DataFrame(rows)
