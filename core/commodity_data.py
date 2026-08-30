from __future__ import annotations

import os
import numpy as np
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.utils import clamp


def _secret(name: str) -> str:
    try:
        v = st.secrets.get(name, '')
        if v:
            return str(v)
    except Exception:
        pass
    return os.getenv(name, '')


def _session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=.6, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(['GET']))
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.headers.update({'User-Agent': 'market-screener/8.5'})
    return s


@st.cache_data(ttl=3600, show_spinner=False)
def eia_v2_series(route: str, series: str, frequency='weekly', length=260, api_key=''):
    """Fetch one EIA API v2 series from a route with a `series` facet."""
    key = api_key or _secret('EIA_API_KEY')
    if not key:
        return pd.DataFrame()
    try:
        url = f"https://api.eia.gov/v2/{route.strip('/')}/data/"
        params = {
            'api_key': key,
            'frequency': frequency,
            'data[0]': 'value',
            'facets[series][]': series,
            'sort[0][column]': 'period',
            'sort[0][direction]': 'desc',
            'length': int(length),
        }
        r = _session().get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json().get('response', {}).get('data', [])
        df = pd.DataFrame(data)
        if not df.empty and 'period' in df:
            df['period'] = pd.to_datetime(df['period'], errors='coerce')
        if not df.empty and 'value' in df:
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
        return df
    except Exception:
        return pd.DataFrame()


# Compatibility wrapper used by older views/tests.
@st.cache_data(ttl=3600, show_spinner=False)
def eia_series(series_id, api_key=''):
    # Older code passed a route rather than a real EIA series ID.
    if '/' in str(series_id):
        return eia_v2_series(series_id, 'WCESTUS1', api_key=api_key)
    return eia_v2_series('petroleum/sum/sndw', str(series_id), api_key=api_key)


@st.cache_data(ttl=21600, show_spinner=False)
def cftc_cot_futures_only():
    try:
        r = _session().get('https://www.cftc.gov/dea/newcot/deafut.txt', timeout=15)
        r.raise_for_status()
        if not r.text.strip():
            return pd.DataFrame()
        return pd.read_csv(pd.io.common.StringIO(r.text))
    except Exception:
        return pd.DataFrame()


def _seasonal_z(df: pd.DataFrame) -> float:
    """Approximate current inventory deviation from same-week 5y history."""
    if df is None or df.empty or 'period' not in df or 'value' not in df:
        return np.nan
    d = df[['period', 'value']].dropna().copy().sort_values('period')
    if len(d) < 60:
        return np.nan
    latest = d.iloc[-1]
    week = int(pd.Timestamp(latest['period']).isocalendar().week)
    hist = d[d['period'] < latest['period']].copy()
    hist['week'] = hist['period'].dt.isocalendar().week.astype(int)
    same = hist[hist['week'].between(max(1, week - 1), min(53, week + 1))].tail(15)['value']
    if len(same) < 5 or float(same.std(ddof=0) or 0) == 0:
        return np.nan
    return float((latest['value'] - same.mean()) / same.std(ddof=0))


def _inventory_stats(df: pd.DataFrame) -> dict:
    if df is None or df.empty or 'value' not in df:
        return {}
    d = df.dropna(subset=['value']).sort_values('period') if 'period' in df else df.dropna(subset=['value'])
    if d.empty:
        return {}
    vals = d['value'].astype(float)
    latest = float(vals.iloc[-1])
    w1 = latest - float(vals.iloc[-2]) if len(vals) >= 2 else np.nan
    w4 = latest - float(vals.iloc[-5]) if len(vals) >= 5 else np.nan
    return {'latest': latest, '1w_change': w1, '4w_change': w4, 'seasonal_z': _seasonal_z(d)}


def commodity_deep_context(ticker, eia_key=''):
    t = str(ticker).upper()
    out = {
        'Inventory_Signal': 'N/D',
        'Commercial_Crude_Stocks_kbbl': np.nan,
        'Crude_1w_Change_kbbl': np.nan,
        'Crude_4w_Change_kbbl': np.nan,
        'Crude_Seasonal_Z': np.nan,
        'Gasoline_Stocks_kbbl': np.nan,
        'Distillate_Stocks_kbbl': np.nan,
        'COT_Signal': 'N/D',
        'Term_Structure': 'Requires contract-specific futures curve feed',
        'Deep_Data_Score': 50,
        'Data_Source': 'Public/fallback',
        'Notes': [],
    }
    score = 50

    if t in {'CL=F', 'BZ=F', 'USO', 'BNO'}:
        crude = eia_v2_series('petroleum/sum/sndw', 'WCESTUS1', api_key=eia_key)
        gas = eia_v2_series('petroleum/sum/sndw', 'WGTSTUS1', api_key=eia_key)
        dist = eia_v2_series('petroleum/sum/sndw', 'WDISTUS1', api_key=eia_key)
        cs, gs, ds = _inventory_stats(crude), _inventory_stats(gas), _inventory_stats(dist)
        if cs:
            out['Data_Source'] = 'EIA API v2'
            out['Commercial_Crude_Stocks_kbbl'] = cs.get('latest', np.nan)
            out['Crude_1w_Change_kbbl'] = cs.get('1w_change', np.nan)
            out['Crude_4w_Change_kbbl'] = cs.get('4w_change', np.nan)
            out['Crude_Seasonal_Z'] = cs.get('seasonal_z', np.nan)
            draw = cs.get('1w_change', np.nan)
            out['Inventory_Signal'] = 'DRAW' if pd.notna(draw) and draw < 0 else 'BUILD' if pd.notna(draw) and draw > 0 else 'FLAT'
            # Draws are supportive; exceptionally high seasonal inventories are a headwind.
            if pd.notna(draw):
                score += 8 if draw < 0 else -8 if draw > 0 else 0
            z = cs.get('seasonal_z', np.nan)
            if pd.notna(z):
                score += 6 if z < -1 else -6 if z > 1 else 0
        else:
            out['Notes'].append('EIA inventory data unavailable; configure EIA_API_KEY in Streamlit and GitHub Actions.')
        if gs:
            out['Gasoline_Stocks_kbbl'] = gs.get('latest', np.nan)
        if ds:
            out['Distillate_Stocks_kbbl'] = ds.get('latest', np.nan)

    cotp = cftc_positioning_snapshot(t)
    if not cotp.get('available'):
        out['Notes'].append('CFTC COT positioning unavailable or contract not mapped in this run.')
    else:
        out.update({k:v for k,v in cotp.items() if k not in {'available','provider'}})
        pct=cotp.get('COT_Net_pct_OI',np.nan)
        if pd.notna(pct):
            score += 5 if 5 < pct <= 20 else -5 if pct > 20 else -5 if -20 <= pct < -5 else 5 if pct < -20 else 0

    out['Deep_Data_Score'] = int(clamp(score))
    return out

# CFTC contract-name fragments for free positioning context. The legacy futures-only
# report is current-week data, so this is a cross-sectional positioning measure,
# not a historical percentile.
_COT_MAP = {
    'CL=F':['CRUDE OIL, LIGHT SWEET','CRUDE OIL'], 'BZ=F':['BRENT'],
    'GC=F':['GOLD'], 'SI=F':['SILVER'], 'HG=F':['COPPER'],
    'NG=F':['NATURAL GAS'], 'ZC=F':['CORN'], 'ZW=F':['WHEAT'], 'ZS=F':['SOYBEANS'],
}

def cftc_positioning_snapshot(ticker: str) -> dict:
    df=cftc_cot_futures_only(); out={'available':False,'provider':'CFTC COT','COT_Net_Noncommercial':np.nan,'COT_Net_pct_OI':np.nan,'COT_Signal':'N/D'}
    if df is None or df.empty: return out
    t=str(ticker).upper(); needles=_COT_MAP.get(t,[])
    if not needles: return out
    namecol=next((c for c in df.columns if 'Market_and_Exchange_Names' in c or 'Market and Exchange Names' in c),df.columns[0])
    names=df[namecol].astype(str).str.upper(); mask=pd.Series(False,index=df.index)
    for n in needles: mask |= names.str.contains(n,regex=False,na=False)
    rows=df[mask]
    if rows.empty: return out
    r=rows.iloc[0]
    def col(tokens):
        for c in df.columns:
            u=str(c).upper().replace(' ','_')
            if all(x in u for x in tokens): return c
        return None
    longc=col(['NONCOMM','LONG']); shortc=col(['NONCOMM','SHORT']); oic=col(['OPEN','INTEREST'])
    try:
        lng=float(r[longc]) if longc else np.nan; sht=float(r[shortc]) if shortc else np.nan; oi=float(r[oic]) if oic else np.nan
        net=lng-sht if pd.notna(lng) and pd.notna(sht) else np.nan; pct=100*net/oi if pd.notna(net) and pd.notna(oi) and oi else np.nan
        out.update({'available':pd.notna(net),'COT_Net_Noncommercial':net,'COT_Net_pct_OI':pct})
        if pd.notna(pct): out['COT_Signal']='CROWDED LONG' if pct>20 else 'LONG' if pct>5 else 'CROWDED SHORT' if pct<-20 else 'SHORT' if pct<-5 else 'NEUTRAL'
    except Exception: pass
    return out
