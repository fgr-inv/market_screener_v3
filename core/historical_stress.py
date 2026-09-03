import numpy as np
import pandas as pd
from core.portfolio_positions import resolve_position_allocations

HISTORICAL_WINDOWS = {
    'COVID Crash 2020': ('2020-02-19','2020-03-23'),
    'Q4 2018 Selloff': ('2018-09-20','2018-12-24'),
    '2022 Inflation / Rates': ('2022-01-03','2022-10-14'),
    '2023 Regional Bank Stress': ('2023-03-08','2023-03-24'),
}


def period_return(raw,start,end):
    if raw is None or raw.empty: return np.nan
    x=raw.loc[(raw.index>=pd.Timestamp(start)) & (raw.index<=pd.Timestamp(end)),'Close'].dropna()
    if len(x)<2: return np.nan
    return float(x.iloc[-1]/x.iloc[0]-1)


def historical_stress_portfolio(positions,price_map,scenario):
    if scenario not in HISTORICAL_WINDOWS or positions is None or positions.empty:
        return {},pd.DataFrame()
    start,end=HISTORICAL_WINDOWS[scenario]
    resolved,allocation=resolve_position_allocations(positions,price_map)
    if allocation.get('status')!='CURRENT': return {'Allocation Status':allocation.get('status')},pd.DataFrame()
    total=allocation.get('dollar_total'); pnl=0 if total is not None else np.nan; impact=0; rows=[]
    for _,p in resolved.iterrows():
        t=str(p['Ticker']).upper(); raw=price_map.get(t)
        if raw is None or raw.empty: continue
        val=p.get('Market Value'); weight=float(p.get('Weight %',0) or 0)/100
        shock=period_return(raw,start,end)
        if pd.isna(shock):
            shock=period_return(price_map.get('SPY'),start,end)
            method='SPY fallback'
        else: method='realized asset window'
        if pd.notna(shock): impact+=weight*shock
        est=float(val)*shock if pd.notna(val) and pd.notna(shock) and allocation.get('basis')=='QUANTITY' else np.nan
        if pd.notna(pnl) and pd.notna(est): pnl+=est
        rows.append({'Ticker':t,'Weight %':weight*100,'Current Value':val,'Historical Shock %':shock*100 if pd.notna(shock) else np.nan,'Estimated P&L $':est,'Method':method})
    return {'Scenario':scenario,'Window':f'{start} → {end}','Portfolio Value':np.nan if total is None else total,
            'Estimated P&L $':pnl,'Estimated Portfolio %':impact*100},pd.DataFrame(rows)
