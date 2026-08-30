import pandas as pd


def latest_changes(history, min_abs_delta=5, limit=30):
    if history is None or history.empty or 'ts' not in history or 'ticker' not in history:
        return pd.DataFrame()
    h=history.copy(); h['ts']=pd.to_datetime(h['ts'],errors='coerce'); h=h.dropna(subset=['ts'])
    dates=sorted(h['ts'].dt.date.unique())
    if len(dates)<2:
        return pd.DataFrame()
    prev_date,now_date=dates[-2],dates[-1]
    now=h[h['ts'].dt.date==now_date].sort_values('ts').groupby('ticker').tail(1)
    prev=h[h['ts'].dt.date==prev_date].sort_values('ts').groupby('ticker').tail(1)
    x=now.merge(prev,on='ticker',suffixes=('_now','_prev'))
    metrics=['opportunity','entry','trend','technical','confidence','rs_percentile']
    for m in metrics:
        if f'{m}_now' in x and f'{m}_prev' in x:
            x[f'delta_{m}']=pd.to_numeric(x[f'{m}_now'],errors='coerce')-pd.to_numeric(x[f'{m}_prev'],errors='coerce')
    primary='delta_opportunity' if 'delta_opportunity' in x else 'delta_entry' if 'delta_entry' in x else None
    if primary is None:
        return pd.DataFrame()
    x=x[x[primary].abs()>=min_abs_delta].copy()
    x['Magnitude']=x[primary].abs()
    cols=['ticker',primary,'action_prev','action_now','price_prev','price_now']
    cols=[c for c in cols if c in x.columns]
    return x.sort_values('Magnitude',ascending=False)[cols].head(limit)
