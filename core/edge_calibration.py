import numpy as np
import pandas as pd


def calibrate_score_buckets(events, score_col='Entry_Score', return_col='20d_Alpha', bins=None):
    if events is None or events.empty or score_col not in events or return_col not in events:
        return pd.DataFrame()
    x=events[[score_col,return_col]].dropna().copy()
    if x.empty: return pd.DataFrame()
    bins=bins or [0,50,60,70,80,90,101]
    x['Bucket']=pd.cut(x[score_col],bins=bins,right=False,include_lowest=True)
    rows=[]
    for bucket,g in x.groupby('Bucket',observed=True):
        if len(g)<3: continue
        s=g[return_col]
        rows.append({
            'Score Bucket':str(bucket),'Signals':len(g),'Mean Edge %':float(s.mean()),'Median Edge %':float(s.median()),
            'Win Rate %':float((s>0).mean()*100),'P10 %':float(np.percentile(s,10)),'P90 %':float(np.percentile(s,90)),
        })
    return pd.DataFrame(rows)


def bootstrap_edge(series, simulations=2000, seed=7):
    s=pd.Series(series).dropna().astype(float)
    if len(s)<5: return {}
    rng=np.random.default_rng(seed); means=[]
    vals=s.to_numpy()
    for _ in range(int(simulations)):
        means.append(float(rng.choice(vals,size=len(vals),replace=True).mean()))
    return {
        'Observed Mean %':float(s.mean()),
        'Bootstrap Mean %':float(np.mean(means)),
        'CI 5%':float(np.percentile(means,5)),
        'CI 95%':float(np.percentile(means,95)),
        'Probability Edge > 0 %':float((np.array(means)>0).mean()*100),
    }


def walk_forward_summary(events, date_col='Date', return_col='20d_Alpha', train_frac=.65):
    if events is None or events.empty or date_col not in events or return_col not in events:
        return {}
    x=events[[date_col,return_col]].dropna().sort_values(date_col)
    if len(x)<20: return {}
    cut=max(1,int(len(x)*train_frac)); train=x.iloc[:cut]; test=x.iloc[cut:]
    return {
        'Train Signals':len(train),'Test Signals':len(test),
        'Train Mean Alpha %':float(train[return_col].mean()),
        'Test Mean Alpha %':float(test[return_col].mean()),
        'Train Win Rate %':float((train[return_col]>0).mean()*100),
        'Test Win Rate %':float((test[return_col]>0).mean()*100),
    }
