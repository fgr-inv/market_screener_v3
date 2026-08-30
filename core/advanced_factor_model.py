import numpy as np
import pandas as pd

FACTOR_PROXIES = {
    'Market':'SPY','Momentum':'MTUM','Quality':'QUAL','Value':'VLUE','LowVol':'USMV',
    'SmallSize':'IWM','Growth':'VUG','RatesDuration':'TLT','Dollar':'UUP','Oil':'XLE',
}


def _returns(price_map, tickers, lookback=252):
    data={}
    for t in tickers:
        raw=price_map.get(t)
        if raw is not None and not raw.empty:
            data[t]=raw['Close'].pct_change().dropna().tail(lookback)
    return pd.concat(data,axis=1).dropna() if data else pd.DataFrame()


def multivariate_factor_exposure(ticker, price_map, lookback=252):
    raw=price_map.get(ticker)
    if raw is None or raw.empty: return pd.DataFrame(),{}
    all_t=[ticker]+list(FACTOR_PROXIES.values())
    r=_returns(price_map,all_t,lookback)
    if len(r)<60 or ticker not in r: return pd.DataFrame(),{}
    y=r[ticker].values
    Xcols=[t for t in FACTOR_PROXIES.values() if t in r.columns and t!=ticker]
    if not Xcols: return pd.DataFrame(),{}
    X=r[Xcols].values
    X=np.column_stack([np.ones(len(X)),X])
    beta=np.linalg.lstsq(X,y,rcond=None)[0]
    pred=X@beta; resid=y-pred
    ssr=float(np.sum(resid**2)); sst=float(np.sum((y-y.mean())**2))
    r2=1-ssr/sst if sst>0 else np.nan
    inv={v:k for k,v in FACTOR_PROXIES.items()}
    rows=[{'Factor':inv.get(t,t),'Proxy':t,'Beta':float(b)} for t,b in zip(Xcols,beta[1:])]
    stats={'R2':r2,'Residual Vol %':float(np.std(resid,ddof=1)*np.sqrt(252)*100),'Alpha Ann %':float(beta[0]*252*100)}
    return pd.DataFrame(rows).sort_values('Beta',ascending=False),stats


def shrink_covariance(price_map,tickers,lookback=252,shrink=0.35):
    r=_returns(price_map,tickers,lookback)
    if r.empty: return pd.DataFrame()
    sample=r.cov()*252
    diag=np.diag(np.diag(sample.values))
    shr=(1-shrink)*sample.values+shrink*diag
    return pd.DataFrame(shr,index=sample.index,columns=sample.columns)
