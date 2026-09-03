import numpy as np
import pandas as pd
from core.portfolio_positions import resolve_position_allocations

FACTOR_PROXIES = {
    'Momentum': 'MTUM',
    'Quality': 'QUAL',
    'Value': 'VLUE',
    'Low Vol': 'USMV',
    'Size/Small': 'IWM',
    'Growth': 'VUG',
    'Duration/Tech': 'QQQ',
}


def _aligned_returns(asset, factor, window=126):
    a = asset['Close'].pct_change().rename('a')
    f = factor['Close'].pct_change().rename('f')
    x = pd.concat([a, f], axis=1).dropna().tail(window)
    return x


def factor_exposures(ticker, price_map, window=126):
    asset = price_map.get(ticker)
    if asset is None or asset.empty:
        return pd.DataFrame()
    rows=[]
    for name, proxy in FACTOR_PROXIES.items():
        f = price_map.get(proxy)
        if f is None or f.empty:
            continue
        x = _aligned_returns(asset, f, window)
        if len(x) < 30 or x['f'].var() <= 0:
            continue
        beta = x.cov().loc['a','f'] / x['f'].var()
        corr = x.corr().loc['a','f']
        rows.append({'Factor': name, 'Proxy': proxy, 'Beta': float(beta), 'Correlation': float(corr)})
    return pd.DataFrame(rows).sort_values('Beta', ascending=False) if rows else pd.DataFrame()


def portfolio_factor_exposure(positions, price_map, window=126):
    if positions is None or positions.empty:
        return pd.DataFrame()
    resolved,allocation=resolve_position_allocations(positions,price_map)
    if allocation.get('status')!='CURRENT': return pd.DataFrame()
    values=[(str(r['Ticker']),float(r.get('Weight %',0) or 0)/100) for _,r in resolved.iterrows() if float(r.get('Weight %',0) or 0)>0]
    agg={}
    for t,w in values:
        ex=factor_exposures(t,price_map,window)
        for _,r in ex.iterrows():
            agg[r['Factor']]=agg.get(r['Factor'],0)+w*float(r['Beta'])
    return pd.DataFrame([{'Factor':k,'Portfolio Beta':v} for k,v in agg.items()]).sort_values('Portfolio Beta',ascending=False)
