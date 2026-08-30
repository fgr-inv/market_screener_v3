import numpy as np
import pandas as pd
from core.advanced_factor_model import shrink_covariance


def _annual_returns(price_map,tickers,lookback=252):
    vals={}
    for t in tickers:
        raw=price_map.get(t)
        if raw is None or raw.empty: continue
        r=raw['Close'].pct_change().dropna().tail(lookback)
        if len(r)>=60: vals[t]=float(r.mean()*252)
    return pd.Series(vals)


def min_variance_weights(tickers, price_map, max_weight=.20, shrink=.35, current_weights=None, turnover_penalty=0.0):
    cov=shrink_covariance(price_map,tickers,252,shrink)
    if cov.empty: return pd.DataFrame()
    names=list(cov.index); n=len(names)
    try:
        from scipy.optimize import minimize
    except Exception:
        return pd.DataFrame()
    cw=np.array([float((current_weights or {}).get(t,0)) for t in names])
    def obj(w):
        var=float(w@cov.values@w)
        turn=float(np.abs(w-cw).sum()) if current_weights else 0
        return var+turnover_penalty*turn
    cons=[{'type':'eq','fun':lambda w: np.sum(w)-1}]
    bounds=[(0,max_weight)]*n
    x0=np.ones(n)/n
    res=minimize(obj,x0,bounds=bounds,constraints=cons,method='SLSQP')
    if not res.success: return pd.DataFrame()
    w=res.x
    vol=float(np.sqrt(w@cov.values@w))
    return pd.DataFrame({'Ticker':names,'Weight %':w*100}).sort_values('Weight %',ascending=False).assign(Portfolio_Volatility_Pct=vol*100)


def max_sharpe_weights(tickers, price_map, max_weight=.20, risk_free=.03, shrink=.35):
    cov=shrink_covariance(price_map,tickers,252,shrink)
    mu=_annual_returns(price_map,list(cov.index),252)
    if cov.empty or mu.empty: return pd.DataFrame()
    names=list(cov.index); mu=mu.reindex(names).fillna(0).values
    try:
        from scipy.optimize import minimize
    except Exception:
        return pd.DataFrame()
    def obj(w):
        ret=float(w@mu); vol=float(np.sqrt(max(w@cov.values@w,1e-12)))
        return -(ret-risk_free)/vol
    cons=[{'type':'eq','fun':lambda w: np.sum(w)-1}]
    bounds=[(0,max_weight)]*len(names)
    res=minimize(obj,np.ones(len(names))/len(names),bounds=bounds,constraints=cons,method='SLSQP')
    if not res.success: return pd.DataFrame()
    w=res.x; ret=float(w@mu); vol=float(np.sqrt(w@cov.values@w)); sharpe=(ret-risk_free)/vol if vol else np.nan
    return pd.DataFrame({'Ticker':names,'Weight %':w*100}).sort_values('Weight %',ascending=False).assign(Expected_Return_Pct=ret*100,Portfolio_Volatility_Pct=vol*100,Sharpe=sharpe)
