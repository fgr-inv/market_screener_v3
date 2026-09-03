"""Bounded intraday overlay for the cheap Investment Desk detector.

One Yahoo batch covers only current holdings plus the highest-priority cached
candidates. It does not perform fundamental, news, macro, or per-agent calls.
"""
from __future__ import annotations
import pandas as pd


def select_monitor_tickers(latest,portfolio_tickers=None,max_symbols=25,watchlist_tickers=None):
    holdings=list(dict.fromkeys(str(t).upper().strip() for t in (portfolio_tickers or []) if str(t).strip()))
    watchlist=list(dict.fromkeys(str(t).upper().strip() for t in (watchlist_tickers or []) if str(t).strip()))
    candidates=[]
    if latest is not None and not latest.empty and 'Ticker' in latest.columns:
        x=latest.copy()
        entry=pd.to_numeric(x.get('Entry_Score'),errors='coerce') if 'Entry_Score' in x else pd.Series(index=x.index,dtype=float)
        opportunity=pd.to_numeric(x.get('Opportunity_Score'),errors='coerce') if 'Opportunity_Score' in x else pd.Series(index=x.index,dtype=float)
        x['_monitor_score']=pd.concat([entry,opportunity],axis=1).max(axis=1,skipna=True).fillna(-1)
        candidates=x.sort_values('_monitor_score',ascending=False)['Ticker'].dropna().astype(str).str.upper().tolist()
    # Holdings are always first, followed by the durable desk watchlist. Cached
    # broad-screener leaders only fill unused monitoring capacity.
    return list(dict.fromkeys(holdings+watchlist+candidates))[:int(max_symbols)]


def _relative_intraday_volume(history):
    if history is None or history.empty or 'Volume' not in history: return None
    x=history.copy(); idx=pd.DatetimeIndex(x.index)
    try:
        idx=idx.tz_localize('UTC') if idx.tz is None else idx
        dates=idx.tz_convert('America/New_York').date
    except Exception:
        dates=idx.date
    x['_session_date']=dates; sessions=list(dict.fromkeys(dates))
    if len(sessions)<2: return None
    current=x[x['_session_date']==sessions[-1]]; bars=len(current)
    if bars<1: return None
    current_volume=pd.to_numeric(current['Volume'],errors='coerce').fillna(0).sum()
    comparisons=[]
    for day in sessions[:-1]:
        volume=pd.to_numeric(x[x['_session_date']==day]['Volume'],errors='coerce').fillna(0).head(bars).sum()
        if volume>0: comparisons.append(float(volume))
    baseline=sum(comparisons)/len(comparisons) if comparisons else 0
    return float(current_volume/baseline) if baseline>0 else None


def build_intraday_overlay(latest,tickers,fetcher=None):
    """Overlay cached screener rows with one bounded batch of current 5-minute bars."""
    tickers=list(dict.fromkeys(str(t).upper().strip() for t in tickers if str(t).strip()))
    if latest is None or latest.empty or not tickers:
        return pd.DataFrame(),{'status':'UNAVAILABLE','requested':len(tickers),'received':0,'source':'Yahoo Finance 5m batch'}
    if fetcher is None:
        from core.market_data import download_intraday_prices
        fetcher=download_intraday_prices
    histories,provider=fetcher(tickers)
    rows=[]; source=provider.get('source','Yahoo Finance 5m batch')
    indexed=latest.copy(); indexed['Ticker']=indexed['Ticker'].astype(str).str.upper(); indexed=indexed.set_index('Ticker',drop=False)
    for ticker in tickers:
        history=histories.get(ticker)
        if history is None or history.empty or 'Close' not in history or ticker not in indexed.index: continue
        close=pd.to_numeric(history['Close'],errors='coerce').dropna()
        if close.empty: continue
        row=indexed.loc[ticker]
        if isinstance(row,pd.DataFrame): row=row.iloc[0]
        row=row.to_dict(); row['Price']=float(close.iloc[-1]); row['Rel_Volume']=_relative_intraday_volume(history)
        row['Live_Observed_At']=str(close.index[-1]); rows.append(row)
    status='CURRENT' if rows else provider.get('status','FAILED')
    return pd.DataFrame(rows),{'status':status,'requested':len(tickers),'received':len(rows),'source':source,
                               'coverage_status':'COMPLETE' if len(rows)==len(tickers) else 'PARTIAL',
                               'provider_status':provider.get('status','NOT_CHECKED')}
