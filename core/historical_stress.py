import numpy as np
import pandas as pd

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
    rows=[]; total=0; pnl=0
    for _,p in positions.iterrows():
        t=str(p['ticker']).upper(); raw=price_map.get(t)
        if raw is None or raw.empty: continue
        px=float(raw['Close'].dropna().iloc[-1]); val=float(p['quantity'])*px; total+=val
        shock=period_return(raw,start,end)
        if pd.isna(shock):
            shock=period_return(price_map.get('SPY'),start,end)
            method='SPY fallback'
        else: method='realized asset window'
        est=val*shock if pd.notna(shock) else np.nan
        if pd.notna(est): pnl+=est
        rows.append({'Ticker':t,'Current Value':val,'Historical Shock %':shock*100 if pd.notna(shock) else np.nan,'Estimated P&L $':est,'Method':method})
    return {'Scenario':scenario,'Window':f'{start} → {end}','Portfolio Value':total,'Estimated P&L $':pnl,'Estimated Portfolio %':pnl/total*100 if total else np.nan},pd.DataFrame(rows)
