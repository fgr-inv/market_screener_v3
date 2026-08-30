import numpy as np
import pandas as pd


def risk_parity_weights(tickers, price_map, max_weight=.20, lookback=126):
    vols={}
    for t in tickers:
        raw=price_map.get(t)
        if raw is None or raw.empty: continue
        r=raw['Close'].pct_change().dropna().tail(lookback)
        if len(r)<30: continue
        v=float(r.std()*np.sqrt(252))
        if v>0: vols[t]=v
    if not vols: return pd.DataFrame()
    inv={t:1/v for t,v in vols.items()}; total=sum(inv.values())
    w={t:x/total for t,x in inv.items()}
    # iterative cap + redistribute
    for _ in range(10):
        over={t:x for t,x in w.items() if x>max_weight}
        if not over: break
        excess=sum(x-max_weight for x in over.values())
        for t in over: w[t]=max_weight
        under=[t for t in w if w[t]<max_weight-1e-9]
        base=sum(w[t] for t in under)
        if not under or base<=0: break
        for t in under: w[t]+=excess*(w[t]/base)
    s=sum(w.values()); w={t:x/s for t,x in w.items()}
    return pd.DataFrame([{'Ticker':t,'Weight %':x*100,'Annual Vol %':vols[t]*100} for t,x in w.items()]).sort_values('Weight %',ascending=False)


def correlation_penalty_weights(tickers, price_map, base_weights=None, lookback=126, max_weight=.20):
    returns={}
    for t in tickers:
        raw=price_map.get(t)
        if raw is None or raw.empty: continue
        returns[t]=raw['Close'].pct_change().dropna().tail(lookback)
    if len(returns)<2: return risk_parity_weights(tickers,price_map,max_weight,lookback)
    x=pd.concat(returns,axis=1).dropna()
    corr=x.corr().abs(); avg_corr=(corr.sum()-1)/(len(corr)-1)
    vol=x.std()*np.sqrt(252)
    raw_score=1/(vol*(1+avg_corr))
    raw_score=raw_score.replace([np.inf,-np.inf],np.nan).dropna()
    w=raw_score/raw_score.sum()
    # cap and renorm approximate
    w=w.clip(upper=max_weight)
    w=w/w.sum()
    return pd.DataFrame({'Ticker':w.index,'Weight %':w.values*100,'Annual Vol %':vol[w.index].values*100,'Avg Abs Correlation':avg_corr[w.index].values}).sort_values('Weight %',ascending=False)
