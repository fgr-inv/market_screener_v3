import numpy as np
import pandas as pd
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset

HORIZONS = {"5d":5,"20d":20,"63d":63,"126d":126}


def _forward_return(close, idx, days):
    if idx+days>=len(close): return np.nan
    p0=float(close.iloc[idx]); p1=float(close.iloc[idx+days])
    return (p1/p0-1)*100 if p0 else np.nan


def backtest_symbol(ticker, raw, spy_raw=None, min_history=220, step=5, setup_filter=None, entry_min=65, trend_min=65, asset_type="Acción"):

    """Historical technical event study. Does not use today's fundamentals retroactively."""
    h=enrich_indicators(raw)
    spy=enrich_indicators(spy_raw) if spy_raw is not None and not spy_raw.empty else None
    rows=[]
    for i in range(min_history, len(h)-max(HORIZONS.values()), step):
        window=h.iloc[:i+1].copy()
        spy_window=spy.iloc[:i+1].copy() if spy is not None and len(spy)>i else None
        try:
            r=analyze_asset(ticker,window,spy_window,'Backtest',asset_type)
        except Exception:
            continue
        if r['Entry_Score']<entry_min or r['Trend_Score']<trend_min:
            continue
        if setup_filter and r['Setup']!=setup_filter:
            continue
        rec={
            'Date':h.index[i], 'Ticker':ticker, 'Setup':r['Setup'], 'Entry_Score':r['Entry_Score'],
            'Trend_Score':r['Trend_Score'],'Risk_Score':r['Risk_Score'],'RR':r['RR'],'Price':r['Price']
        }
        for label,d in HORIZONS.items():
            rec[label]=_forward_return(h['Close'],i,d)
            if spy is not None and len(spy)>i+d:
                bench=_forward_return(spy['Close'],i,d)
                rec[f'{label}_SPY']=bench
                rec[f'{label}_Alpha']=rec[label]-bench if pd.notna(rec[label]) and pd.notna(bench) else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def summarize_backtest(events, benchmark_events=None):
    if events is None or events.empty:
        return pd.DataFrame(), {}
    summary=[]
    stats={}
    for label in HORIZONS:
        s=events[label].dropna()
        if s.empty: continue
        alpha=events.get(f'{label}_Alpha',pd.Series(dtype=float)).dropna()
        summary.append({
            'Horizon':label,'Signals':len(s),'Win Rate %':round((s>0).mean()*100,1),
            'Median Return %':round(s.median(),2),'Mean Return %':round(s.mean(),2),
            'Mean Alpha vs SPY %':round(alpha.mean(),2) if len(alpha) else np.nan,
            'Alpha Win Rate %':round((alpha>0).mean()*100,1) if len(alpha) else np.nan,
            'Best %':round(s.max(),2),'Worst %':round(s.min(),2),
        })
    stats['Total Signals']=len(events)
    stats['Setups']=events['Setup'].value_counts().to_dict() if 'Setup' in events else {}
    return pd.DataFrame(summary),stats
