from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st
from core.cache_policy import MACRO_TTL


def _secret(name: str) -> str:
    try:
        v = st.secrets.get(name, '')
        if v:
            return str(v)
    except Exception:
        pass
    return os.getenv(name, '')


@st.cache_data(ttl=MACRO_TTL, show_spinner=False)
def get_us_macro_calendar(days=14):
    """Free official-ish US release calendar from FRED release dates.

    This is a schedule of data releases, not a consensus-forecast calendar.
    Forecast/actual surprise data are intentionally not fabricated.
    """
    key = _secret('FRED_API_KEY')
    if not key:
        return pd.DataFrame()
    try:
        start = date.today()
        end = start + timedelta(days=int(days))
        r = requests.get(
            'https://api.stlouisfed.org/fred/releases/dates',
            params={
                'api_key': key,
                'file_type': 'json',
                'realtime_start': start.isoformat(),
                'realtime_end': end.isoformat(),
                'include_release_dates_with_no_data': 'true',
                'limit': 1000,
                'sort_order': 'asc',
            },
            timeout=15,
            headers={'User-Agent': 'market-screener/8.5'},
        )
        r.raise_for_status()
        rows = r.json().get('release_dates', [])
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        rename = {'date': 'Date', 'release_name': 'Event', 'release_id': 'Release_ID'}
        df = df.rename(columns=rename)
        keep = [c for c in ['Date', 'Event', 'Release_ID'] if c in df]
        out = df[keep].copy()
        out['Country'] = 'United States'
        out['Source'] = 'FRED release calendar'
        return out[['Date', 'Country', 'Event', 'Release_ID', 'Source']]
    except Exception:
        return pd.DataFrame()
