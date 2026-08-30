"""Free FRED/ALFRED point-in-time adapter. Requires the existing FRED_API_KEY."""
from __future__ import annotations
import os, requests, pandas as pd
BASE='https://api.stlouisfed.org/fred'

def _key(key=None): return key or os.getenv('FRED_API_KEY','')
def vintage_dates(series_id,key=None,limit=10000):
    k=_key(key)
    if not k:return []
    try:
        r=requests.get(f'{BASE}/series/vintagedates',params={'series_id':series_id,'api_key':k,'file_type':'json','limit':limit},timeout=12);r.raise_for_status()
        return r.json().get('vintage_dates',[])
    except Exception:return []

def observations_as_known(series_id,asof,key=None,observation_start=None):
    k=_key(key)
    if not k:return pd.DataFrame()
    p={'series_id':series_id,'api_key':k,'file_type':'json','realtime_start':asof,'realtime_end':asof}
    if observation_start:p['observation_start']=observation_start
    try:
        r=requests.get(f'{BASE}/series/observations',params=p,timeout=12);r.raise_for_status(); rows=r.json().get('observations',[])
        df=pd.DataFrame(rows)
        if not df.empty:
            df['date']=pd.to_datetime(df['date'],errors='coerce');df['value']=pd.to_numeric(df['value'],errors='coerce')
        return df
    except Exception:return pd.DataFrame()
