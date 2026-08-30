from __future__ import annotations

import numpy as np
import pandas as pd
import requests
import streamlit as st

from core.free_market_providers import free_crypto_derivatives_snapshot, coingecko_headers
from core.utils import clamp


@st.cache_data(ttl=300, show_spinner=False)
def binance_snapshot(symbol='BTCUSDT'):
    base = 'https://fapi.binance.com'
    out = {'Funding_Rate': np.nan, 'Open_Interest': np.nan, 'Long_Short_Ratio': np.nan, 'Status': 'N/D'}
    try:
        r = requests.get(base + '/fapi/v1/premiumIndex', params={'symbol': symbol}, timeout=8)
        r.raise_for_status()
        d = r.json()
        out['Funding_Rate'] = float(d.get('lastFundingRate', np.nan)) * 100
        r = requests.get(base + '/fapi/v1/openInterest', params={'symbol': symbol}, timeout=8)
        r.raise_for_status()
        out['Open_Interest'] = float(r.json().get('openInterest', np.nan))
        r = requests.get(base + '/futures/data/globalLongShortAccountRatio', params={'symbol': symbol, 'period': '1h', 'limit': 1}, timeout=8)
        r.raise_for_status()
        arr = r.json()
        if arr:
            out['Long_Short_Ratio'] = float(arr[-1].get('longShortRatio', np.nan))
        out['Status'] = 'OK'
    except Exception:
        out['Status'] = 'Unavailable'
    return out


@st.cache_data(ttl=900, show_spinner=False)
def coingecko_global():
    out = {'BTC_Dominance': np.nan, 'ETH_Dominance': np.nan, 'Market_Cap_24h_%': np.nan, 'Status': 'N/D'}
    try:
        r = requests.get('https://api.coingecko.com/api/v3/global', timeout=8, headers=coingecko_headers())
        r.raise_for_status()
        d = r.json().get('data', {})
        pct = d.get('market_cap_percentage', {})
        out['BTC_Dominance'] = pct.get('btc', np.nan)
        out['ETH_Dominance'] = pct.get('eth', np.nan)
        out['Market_Cap_24h_%'] = d.get('market_cap_change_percentage_24h_usd', np.nan)
        out['Status'] = 'OK'
    except Exception:
        out['Status'] = 'Unavailable'
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def stablecoin_market_cap():
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/coins/markets',
            params={'vs_currency': 'usd', 'category': 'stablecoins', 'per_page': 100, 'page': 1, 'sparkline': 'false'},
            timeout=10,
            headers=coingecko_headers(),
        )
        r.raise_for_status()
        data = r.json()
        return sum(float(x.get('market_cap') or 0) for x in data)
    except Exception:
        return np.nan


@st.cache_data(ttl=1800, show_spinner=False)
def btc_onchain_public():
    out = {'Hash_Rate': np.nan, 'Unique_Addresses': np.nan, 'Transactions_Per_Day': np.nan, 'Status': 'N/D'}
    mapping = {'Hash_Rate': 'hash-rate', 'Unique_Addresses': 'n-unique-addresses', 'Transactions_Per_Day': 'n-transactions'}
    ok = 0
    for key, chart in mapping.items():
        try:
            r = requests.get(f'https://api.blockchain.info/charts/{chart}', params={'timespan': '2days', 'format': 'json'}, timeout=8)
            r.raise_for_status()
            vals = r.json().get('values', [])
            if vals:
                out[key] = float(vals[-1].get('y', np.nan))
                ok += 1
        except Exception:
            pass
    out['Status'] = 'OK' if ok else 'Unavailable'
    return out


def _coin_from_symbol(symbol: str) -> str:
    s = str(symbol).upper().replace('-USD', '')
    return s[:-4] if s.endswith('USDT') else s


def crypto_derivatives_score(symbol='BTCUSDT'):
    """Professional crypto context using a zero-cost multi-exchange derivatives stack.

    The score penalizes crowded positive funding / rapidly expanding OI without
    corresponding spot confirmation, while ETF inflows and balanced leverage are
    supportive. It remains a context score, not a standalone trading signal.
    """
    coin = _coin_from_symbol(symbol)
    cg = free_crypto_derivatives_snapshot(coin)
    b = binance_snapshot(symbol if str(symbol).upper().endswith('USDT') else coin + 'USDT')
    g = coingecko_global()
    stable = stablecoin_market_cap()
    chain = btc_onchain_public() if coin == 'BTC' else {}
    score = 50

    # Prefer free multi-exchange OI-weighted funding; Binance remains a direct fallback.
    funding = cg.get('Funding_Rate_OI_Weighted_%', np.nan) if cg.get('available') else np.nan
    if pd.isna(funding):
        funding = b.get('Funding_Rate', np.nan)
    if pd.notna(funding):
        af = abs(float(funding))
        score += 6 if af < .02 else -6 if af > .05 else 0
        if float(funding) > .10:
            score -= 6

    oi24 = cg.get('Open_Interest_24h_%', np.nan)
    if pd.notna(oi24):
        score += 3 if -5 <= float(oi24) <= 8 else -6 if float(oi24) > 15 else 0

    # Aggregate liquidation history is not reliably available from the free REST stack.
    etf5 = cg.get('ETF_Flow_5d_$', np.nan)
    if pd.notna(etf5):
        score += 8 if float(etf5) > 500_000_000 else -8 if float(etf5) < -500_000_000 else 3 if float(etf5) > 0 else -3

    ls = b.get('Long_Short_Ratio')
    mc = g.get('Market_Cap_24h_%')
    if pd.notna(ls):
        score += 4 if .8 <= float(ls) <= 1.4 else -5 if float(ls) > 2 else 0
    if pd.notna(mc):
        score += 4 if float(mc) > 1 else -5 if float(mc) < -3 else 0

    deep = {
        'Primary_Derivatives_Source': cg.get('provider') if cg.get('available') else 'Binance fallback',
        **b,
        **{k: v for k, v in cg.items() if k not in {'errors'}},
        **g,
        'Stablecoin_Market_Cap_$': stable,
        **chain,
    }
    # Generic coverage aliases keep the data-quality layer provider-agnostic.
    deep['Funding_Rate'] = funding
    deep['Open_Interest'] = cg.get('Open_Interest_USD', np.nan)
    deep['Basis'] = cg.get('Perp_Basis_OI_Weighted_%', np.nan)
    deep['Liquidations'] = cg.get('Liquidations_24h_$', np.nan)
    deep['ETF_Flows'] = cg.get('ETF_Flow_5d_$', np.nan)
    deep['Free_Derivatives_Coverage_Note'] = cg.get('Coverage_Note', '')
    return int(clamp(score)), deep
