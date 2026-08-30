from __future__ import annotations
import numpy as np
import pandas as pd
from core.position_sizing import size_position

def _ret(df):
    if df is None or df.empty or 'Close' not in df:return pd.Series(dtype=float)
    return df['Close'].pct_change().dropna()

def single_asset_portfolio_fit(ticker,price_map,positions=None,benchmark='SPY'):
    r=_ret(price_map.get(ticker)); b=_ret(price_map.get(benchmark)); beta=np.nan; vol=np.nan; downside_beta=np.nan
    if len(r)>30: vol=float(r.tail(252).std()*np.sqrt(252)*100)
    x=pd.concat([r.rename('a'),b.rename('b')],axis=1).dropna().tail(252)
    if len(x)>30 and x['b'].var()>0:
        beta=float(x.cov().loc['a','b']/x['b'].var()); xd=x[x['b']<0]
        if len(xd)>20 and xd['b'].var()>0: downside_beta=float(xd.cov().loc['a','b']/xd['b'].var())
    maxcorr=np.nan
    if isinstance(positions,pd.DataFrame) and not positions.empty and len(r)>30:
        cs=[]
        for t in positions.get('ticker',pd.Series(dtype=str)).astype(str).str.upper().unique():
            if t==ticker.upper(): continue
            y=_ret(price_map.get(t)); z=pd.concat([r,y],axis=1).dropna().tail(126)
            if len(z)>30: cs.append(float(z.corr().iloc[0,1]))
        if cs: maxcorr=max(cs)
    fit=75
    if pd.notna(maxcorr): fit += -25 if maxcorr>.85 else -12 if maxcorr>.70 else 5 if maxcorr<.40 else 0
    if pd.notna(vol): fit += -12 if vol>60 else -6 if vol>40 else 5 if vol<25 else 0
    fit=int(max(0,min(100,fit)))
    return {'Portfolio_Fit_Score':fit,'Annualized_Volatility_%':vol,'Beta_vs_SPY':beta,'Downside_Beta':downside_beta,'Max_Correlation_to_Holdings':maxcorr}

def institutional_position_size(capital,entry,stop,conviction=70,volatility_pct=np.nan,portfolio_fit=70,max_position_pct=15):
    risk_pct=.35 + max(0,min(100,float(conviction)))/100*.90
    if pd.notna(volatility_pct): risk_pct*=max(.45,min(1.25,30/max(10,float(volatility_pct))))
    risk_pct*=max(.55,min(1.15,float(portfolio_fit)/70))
    out=size_position(capital,risk_pct,entry,stop,max_position_pct=max_position_pct)
    out['risk_budget_pct']=round(risk_pct,2); out['initial_tranche_pct']=round(out.get('position_pct',0)*.5,2)
    return out
