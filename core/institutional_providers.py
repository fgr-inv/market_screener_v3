from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd
import requests
import streamlit as st
from core.cache_policy import ANALYST_TTL, VALUATION_TTL
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _secret(name: str, default: str = '') -> str:
    """Read a secret from Streamlit first and environment second.

    Keeping this in one place is important because Streamlit Cloud and GitHub
    Actions expose secrets differently.
    """
    try:
        v = st.secrets.get(name, default)
        if v is not None and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    v = os.getenv(name, default)
    return str(v).strip() if v is not None else default


def provider_config() -> dict:
    return {
        'POLYGON_API_KEY': _secret('POLYGON_API_KEY'),
        'FINNHUB_API_KEY': _secret('FINNHUB_API_KEY'),
        'FMP_API_KEY': _secret('FMP_API_KEY'),
        'COINGECKO_API_KEY': _secret('COINGECKO_API_KEY'),
        'COINGLASS_API_KEY': _secret('COINGLASS_API_KEY'),
        'FRED_API_KEY': _secret('FRED_API_KEY'),
        'TRADINGECONOMICS_API_KEY': _secret('TRADINGECONOMICS_API_KEY'),
        'EIA_API_KEY': _secret('EIA_API_KEY'),
        'NASDAQ_DATA_LINK_API_KEY': _secret('NASDAQ_DATA_LINK_API_KEY'),
        'DATABASE_URL': _secret('DATABASE_URL'),
        'ALPACA_API_KEY': _secret('ALPACA_API_KEY'),
        'ALPACA_SECRET_KEY': _secret('ALPACA_SECRET_KEY'),
    }


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET']),
    )
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.headers.update({'User-Agent': 'market-screener/8.5'})
    return s


def _get(url: str, params=None, headers=None, timeout=15):
    r = _session().get(url, params=params or {}, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _num(value: Any, default=np.nan):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except Exception:
        return default


def _first(mapping: dict, *keys, default=np.nan):
    for k in keys:
        if k in mapping and mapping.get(k) not in (None, ''):
            return mapping.get(k)
    return default


def polygon_short_interest(ticker):
    key = _secret('POLYGON_API_KEY')
    if not key:
        return {'available': False, 'provider': 'Polygon', 'reason': 'Missing POLYGON_API_KEY'}
    try:
        d = _get(
            'https://api.polygon.io/stocks/v1/short-interest',
            params={'ticker': ticker, 'limit': 10, 'sort': 'settlement_date.desc', 'apiKey': key},
        )
        res = d.get('results') or []
        if not res:
            return {'available': False, 'provider': 'Polygon', 'reason': 'No data'}
        x = res[0]
        return {
            'available': True,
            'provider': 'Polygon',
            'settlement_date': x.get('settlement_date'),
            'short_interest': x.get('short_interest'),
            'days_to_cover': x.get('days_to_cover'),
            'avg_daily_volume': x.get('avg_daily_volume'),
        }
    except Exception as e:
        return {'available': False, 'provider': 'Polygon', 'reason': str(e)[:160]}


def finnhub_insider_transactions(ticker):
    key = _secret('FINNHUB_API_KEY')
    if not key:
        return pd.DataFrame()
    try:
        d = _get('https://finnhub.io/api/v1/stock/insider-transactions', params={'symbol': ticker, 'token': key})
        return pd.DataFrame(d.get('data') or [])
    except Exception:
        return pd.DataFrame()


def finnhub_recommendation_trends(ticker):
    key = _secret('FINNHUB_API_KEY')
    if not key:
        return pd.DataFrame()
    try:
        d = _get('https://finnhub.io/api/v1/stock/recommendation', params={'symbol': ticker, 'token': key})
        return pd.DataFrame(d if isinstance(d, list) else [])
    except Exception:
        return pd.DataFrame()


def _fmp_get(endpoint: str, ticker: str, extra: dict | None = None) -> list[dict]:
    key = _secret('FMP_API_KEY')
    if not key:
        return []
    params = {'symbol': ticker, 'apikey': key}
    if extra:
        params.update(extra)
    try:
        d = _get(f'https://financialmodelingprep.com/stable/{endpoint}', params=params)
        return d if isinstance(d, list) else []
    except Exception:
        return []


@st.cache_data(ttl=ANALYST_TTL, show_spinner=False)
def fmp_estimates(ticker):
    rows = _fmp_get('analyst-estimates', ticker, {'period': 'annual', 'page': 0, 'limit': 10})
    if not rows:
        # Legacy fallback for older FMP plans.
        key = _secret('FMP_API_KEY')
        if key:
            try:
                d = _get(f'https://financialmodelingprep.com/api/v3/analyst-estimates/{ticker}', params={'apikey': key})
                rows = d if isinstance(d, list) else []
            except Exception:
                pass
    return pd.DataFrame(rows)


@st.cache_data(ttl=VALUATION_TTL, show_spinner=False)
def fmp_equity_snapshot(ticker: str) -> dict:
    """Best-effort FMP enrichment for equities.

    FMP availability varies by plan. The function deliberately returns only
    fields actually observed, so unavailable premium data never becomes a
    fabricated neutral score.
    """
    if not _secret('FMP_API_KEY'):
        return {'available': False, 'provider': 'FMP', 'reason': 'Missing FMP_API_KEY'}

    profile = (_fmp_get('profile', ticker) or [{}])[0]
    ratios = (_fmp_get('ratios-ttm', ticker) or [{}])[0]
    metrics = (_fmp_get('key-metrics-ttm', ticker) or [{}])[0]
    scores = (_fmp_get('financial-scores', ticker) or [{}])[0]
    growth = (_fmp_get('income-statement-growth', ticker, {'period': 'annual', 'limit': 5}) or [{}])[0]
    estimates = fmp_estimates(ticker)

    observed = any(bool(x) for x in (profile, ratios, metrics, scores, growth)) or not estimates.empty
    if not observed:
        return {'available': False, 'provider': 'FMP', 'reason': 'No accessible FMP data for this symbol/plan'}

    out = {
        'available': True,
        'provider': 'FMP',
        'Market_Cap': _num(_first(profile, 'marketCap')),
        'Sector': _first(profile, 'sector', default=''),
        'Industry': _first(profile, 'industry', default=''),
        'Beta': _num(_first(profile, 'beta')),
        'Forward_PE': _num(_first(ratios, 'forwardPERatio', 'priceToEarningsRatio')),
        'Trailing_PE': _num(_first(ratios, 'priceToEarningsRatio', 'priceEarningsRatio')),
        'Price_to_Book': _num(_first(ratios, 'priceToBookRatio')),
        'Price_to_Sales': _num(_first(ratios, 'priceToSalesRatio')),
        'EV_EBITDA': _num(_first(metrics, 'enterpriseValueOverEBITDA', 'evToEBITDA')),
        'EV_Revenue': _num(_first(metrics, 'evToSales', 'enterpriseValueOverRevenue')),
        'ROE': _num(_first(ratios, 'returnOnEquity')),
        'ROA': _num(_first(ratios, 'returnOnAssets')),
        'Gross_Margin': _num(_first(ratios, 'grossProfitMargin')),
        'Operating_Margin': _num(_first(ratios, 'operatingProfitMargin', 'operatingMargin')),
        'Profit_Margin': _num(_first(ratios, 'netProfitMargin')),
        'Current_Ratio': _num(_first(ratios, 'currentRatio')),
        'Quick_Ratio': _num(_first(ratios, 'quickRatio')),
        'Debt_Equity': _num(_first(ratios, 'debtToEquityRatio')),
        'FCF_Yield': _num(_first(metrics, 'freeCashFlowYield')),
        'ROIC': _num(_first(metrics, 'returnOnInvestedCapital')),
        'Revenue_Growth': _num(_first(growth, 'growthRevenue', 'revenueGrowth')),
        'Earnings_Growth': _num(_first(growth, 'growthNetIncome', 'netIncomeGrowth')),
        'Piotroski_Score': _num(_first(scores, 'piotroskiScore')),
        'Altman_Z_Score': _num(_first(scores, 'altmanZScore')),
        'FMP_Estimates_Available': not estimates.empty,
    }
    # Some FMP ratios are returned as percentages in specific plans while most
    # are fractions. Do not auto-rescale ambiguous values; preserve provider value.
    out['Observed_Fields'] = [k for k, v in out.items() if k not in {'available', 'provider', 'Observed_Fields'} and pd.notna(v) and v != '']
    return out


def _cg_get(path: str, params: dict | None = None) -> dict:
    key = _secret('COINGLASS_API_KEY')
    if not key:
        raise RuntimeError('Missing COINGLASS_API_KEY')
    return _get(
        'https://open-api-v4.coinglass.com' + path,
        params=params or {},
        headers={'CG-API-KEY': key},
    )


def _cg_data(path: str, params: dict | None = None):
    d = _cg_get(path, params)
    if str(d.get('code')) not in {'0', '200', '200000'} and d.get('data') is None:
        raise RuntimeError(str(d.get('msg') or d.get('message') or 'CoinGlass error'))
    return d.get('data')


def _pct_change(current, previous):
    try:
        current, previous = float(current), float(previous)
        return np.nan if previous == 0 else (current / previous - 1.0) * 100.0
    except Exception:
        return np.nan


@st.cache_data(ttl=300, show_spinner=False)
def coinglass_snapshot(symbol='BTC'):
    """CoinGlass V4 professional crypto derivatives snapshot.

    Uses aggregated OI, OI-weighted funding, aggregated liquidations and ETF
    flows when the API plan exposes them. Each component fails independently.
    """
    coin = str(symbol or 'BTC').upper().replace('-USD', '').replace('USDT', '')
    if not _secret('COINGLASS_API_KEY'):
        return {'available': False, 'provider': 'CoinGlass', 'reason': 'Missing COINGLASS_API_KEY'}

    out = {
        'available': False,
        'provider': 'CoinGlass V4',
        'symbol': coin,
        'Funding_Rate_OI_Weighted_%': np.nan,
        'Open_Interest_USD': np.nan,
        'Open_Interest_24h_%': np.nan,
        'Long_Liquidations_24h_$': np.nan,
        'Short_Liquidations_24h_$': np.nan,
        'ETF_Flow_Latest_$': np.nan,
        'ETF_Flow_5d_$': np.nan,
        'errors': [],
    }

    try:
        data = _cg_data('/api/futures/open-interest/aggregated-history', {'symbol': coin, 'interval': '4h', 'limit': 8, 'unit': 'usd'}) or []
        if isinstance(data, list) and data:
            data = sorted(data, key=lambda x: x.get('time') or 0)
            closes = [_num(x.get('close')) for x in data]
            closes = [x for x in closes if pd.notna(x)]
            if closes:
                out['Open_Interest_USD'] = closes[-1]
                out['Open_Interest_24h_%'] = _pct_change(closes[-1], closes[0]) if len(closes) > 1 else np.nan
                out['available'] = True
    except Exception as e:
        out['errors'].append('OI: ' + str(e)[:100])

    try:
        data = _cg_data('/api/futures/funding-rate/oi-weight-history', {'symbol': coin, 'interval': '4h', 'limit': 8}) or []
        if isinstance(data, list) and data:
            data = sorted(data, key=lambda x: x.get('time') or 0)
            last = data[-1]
            # CoinGlass funding values are percent units in the documented endpoint.
            out['Funding_Rate_OI_Weighted_%'] = _num(last.get('close'))
            out['available'] = True
    except Exception as e:
        out['errors'].append('Funding: ' + str(e)[:100])

    try:
        data = _cg_data(
            '/api/futures/liquidation/aggregated-history',
            {'exchange_list': 'Binance,OKX,Bybit', 'symbol': coin, 'interval': '1d', 'limit': 2},
        ) or []
        if isinstance(data, list) and data:
            last = data[-1]
            out['Long_Liquidations_24h_$'] = _num(last.get('aggregated_long_liquidation_usd'))
            out['Short_Liquidations_24h_$'] = _num(last.get('aggregated_short_liquidation_usd'))
            out['available'] = True
    except Exception as e:
        out['errors'].append('Liquidations: ' + str(e)[:100])

    etf_path = {'BTC': '/api/etf/bitcoin/flow-history', 'ETH': '/api/etf/ethereum/flow-history'}.get(coin)
    if etf_path:
        try:
            data = _cg_data(etf_path, {}) or []
            if isinstance(data, list) and data:
                # Endpoint normally returns newest/oldest depending on provider;
                # use timestamps to guarantee chronological ordering.
                rows = sorted(data, key=lambda x: x.get('timestamp') or x.get('time') or 0)
                flows = [_num(x.get('flow_usd')) for x in rows if pd.notna(_num(x.get('flow_usd')))]
                if flows:
                    out['ETF_Flow_Latest_$'] = flows[-1]
                    out['ETF_Flow_5d_$'] = float(np.nansum(flows[-5:]))
                    out['available'] = True
        except Exception as e:
            out['errors'].append('ETF flows: ' + str(e)[:100])

    if not out['available'] and not out['errors']:
        out['reason'] = 'No accessible CoinGlass data for current plan'
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def tradingeconomics_country_snapshot(country: str) -> pd.DataFrame:
    key = _secret('TRADINGECONOMICS_API_KEY')
    if not key:
        return pd.DataFrame()
    try:
        d = _get(f'https://api.tradingeconomics.com/country/{country}', params={'c': key})
        return pd.DataFrame(d if isinstance(d, list) else [])
    except Exception:
        return pd.DataFrame()


def tradingeconomics_indicator(country: str, categories: list[str]) -> dict:
    df = tradingeconomics_country_snapshot(country)
    if df.empty:
        return {'available': False, 'provider': 'Trading Economics'}
    cat_col = next((c for c in df.columns if str(c).lower() in {'category', 'indicator'}), None)
    val_col = next((c for c in df.columns if str(c).lower() in {'latestvalue', 'value', 'latest'}), None)
    if not cat_col or not val_col:
        return {'available': False, 'provider': 'Trading Economics'}
    lowered = df[cat_col].astype(str).str.lower()
    for target in categories:
        exact = df[lowered.eq(target.lower())]
        if exact.empty:
            exact = df[lowered.str.contains(target.lower(), regex=False)]
        if not exact.empty:
            r = exact.iloc[0]
            return {
                'available': True,
                'provider': 'Trading Economics',
                'country': country,
                'category': r.get(cat_col),
                'value': _num(r.get(val_col)),
                'unit': r.get('Unit', ''),
                'date': r.get('LatestValueDate', r.get('Date', '')),
            }
    return {'available': False, 'provider': 'Trading Economics'}


def provider_capabilities():
    cfg = provider_config()
    return pd.DataFrame([
        {'Provider': 'Yahoo Finance', 'Configured': True, 'Use': 'Prices, basic fundamentals, options chain', 'Integration': 'ACTIVE / FREE'},
        {'Provider': 'FRED', 'Configured': bool(cfg['FRED_API_KEY']), 'Use': 'Official US macro/rates plus selected OECD/global rate series', 'Integration': 'ACTIVE / FREE'},
        {'Provider': 'EIA', 'Configured': bool(cfg['EIA_API_KEY']), 'Use': 'US petroleum inventories and energy fundamentals', 'Integration': 'ACTIVE / FREE'},
        {'Provider': 'FMP', 'Configured': bool(cfg['FMP_API_KEY']), 'Use': 'Equity fundamentals, estimates, stock news and issuer press releases within plan limits', 'Integration': 'ACTIVE / PLAN DEPENDENT'},
        {'Provider': 'SEC EDGAR', 'Configured': True, 'Use': 'Official company submissions and material filing links; rate-limited public API', 'Integration': 'ACTIVE / FREE PUBLIC'},
        {'Provider': 'CoinGecko Demo/Public', 'Configured': bool(cfg['COINGECKO_API_KEY']), 'Use': 'Crypto market breadth, dominance, market cap and stablecoin context; public fallback works without a key', 'Integration': 'ACTIVE / FREE'},
        {'Provider': 'Binance Futures', 'Configured': True, 'Use': 'Public crypto funding, OI history and positioning', 'Integration': 'ACTIVE / FREE PUBLIC'},
        {'Provider': 'Bybit', 'Configured': True, 'Use': 'Public crypto funding, OI notional and perp basis', 'Integration': 'ACTIVE / FREE PUBLIC'},
        {'Provider': 'OKX', 'Configured': True, 'Use': 'Public crypto funding, OI and perp basis', 'Integration': 'ACTIVE / FREE PUBLIC'},
        {'Provider': 'CFTC', 'Configured': True, 'Use': 'Public Commitments of Traders raw positioning feed', 'Integration': 'ACTIVE / FREE PUBLIC'},
        {'Provider': 'Polygon', 'Configured': bool(cfg['POLYGON_API_KEY']), 'Use': 'Optional short-interest / premium market data', 'Integration': 'OPTIONAL'},
        {'Provider': 'Finnhub', 'Configured': bool(cfg['FINNHUB_API_KEY']), 'Use': 'Optional insider activity / recommendation trends', 'Integration': 'OPTIONAL'},
        {'Provider': 'CoinGlass', 'Configured': bool(cfg['COINGLASS_API_KEY']), 'Use': 'Optional paid aggregate crypto derivatives/ETF-flow enrichment; not required by V8.5', 'Integration': 'OPTIONAL PREMIUM'},
        {'Provider': 'Trading Economics', 'Configured': bool(cfg['TRADINGECONOMICS_API_KEY']), 'Use': 'Legacy optional global macro connector; not required by V8.5 free stack', 'Integration': 'OPTIONAL PREMIUM'},
        {'Provider': 'Nasdaq Data Link', 'Configured': bool(cfg['NASDAQ_DATA_LINK_API_KEY']), 'Use': 'Optional commodity/economic datasets', 'Integration': 'RESERVED'},
        {'Provider': 'Cloud DB', 'Configured': bool(cfg['DATABASE_URL']), 'Use': 'Persistent production storage', 'Integration': 'ACTIVE'},
        {'Provider': 'Alpaca read-only', 'Configured': bool(cfg['ALPACA_API_KEY'] and cfg['ALPACA_SECRET_KEY']), 'Use': 'Broker positions/account import', 'Integration': 'ACTIVE'},
    ])
