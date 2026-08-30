from __future__ import annotations

import numpy as np
import pandas as pd
import requests
from io import StringIO


# Zero-cost policy/call-rate proxies available through FRED. Several non-US
# series are OECD Main Economic Indicators mirrored by FRED. They are useful for
# carry/regime work but may update monthly, so source/frequency is disclosed.
FRED_POLICY = {
    'USD': 'FEDFUNDS',
    'EUR': 'ECBDFR',
    'GBP': 'IUDERB6',
    'JPY': 'IRSTCI01JPM156N',
    'CAD': 'IRSTCI01CAM156N',
    'AUD': 'IRSTCI01AUM156N',
    'NZD': 'IRSTCI01NZM156N',
    'CHF': 'IRSTCI01CHM156N',
    'MXN': 'IRSTCI01MXM156N',
    'BRL': 'IRSTCI01BRM156N',
    'NOK': 'IRSTCI01NOM156N',
    'SEK': 'IRSTCI01SEM156N',
    'INR': 'IRSTCI01INM156N',
    'KRW': 'IRSTCI01KRM156N',
}


def _fred(series):
    if not series:
        return np.nan
    try:
        r = requests.get(
            'https://fred.stlouisfed.org/graph/fredgraph.csv',
            params={'id': series}, timeout=10, headers={'User-Agent': 'market-screener/8.5'},
        )
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        val = pd.to_numeric(df.iloc[:, -1], errors='coerce').dropna()
        return float(val.iloc[-1]) if len(val) else np.nan
    except Exception:
        return np.nan


def _policy_rate(currency: str):
    sid = FRED_POLICY.get(currency, '')
    val = _fred(sid) if sid else np.nan
    if pd.notna(val):
        source = 'FRED official/OECD series'
        return val, source, sid
    return np.nan, 'Unavailable', sid


def parse_pair(ticker):
    s = ticker.upper().replace('=X', '').replace('/', '')
    return (s[:3], s[3:6]) if len(s) >= 6 else (None, None)


def fx_carry_context(ticker):
    base, quote = parse_pair(ticker)
    if not base or not quote:
        return {'available': False}
    br, bsrc, bsid = _policy_rate(base)
    qr, qsrc, qsid = _policy_rate(quote)
    spread = br - qr if pd.notna(br) and pd.notna(qr) else np.nan
    score = 50
    if pd.notna(spread):
        score = max(0, min(100, 50 + spread * 6))
    return {
        'available': pd.notna(spread),
        'Base': base,
        'Quote': quote,
        'Base_Policy_Rate': br,
        'Quote_Policy_Rate': qr,
        'Base_Rate_Source': bsrc,
        'Quote_Rate_Source': qsrc,
        'Base_Rate_Series': bsid,
        'Quote_Rate_Series': qsid,
        'Carry_Spread_pp': spread,
        'Carry_Score': round(score),
        'Data_Note': 'Free policy/call-rate proxies via FRED/OECD. Some non-US series are monthly and are not intraday carry curves.',
    }
