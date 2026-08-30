import numpy as np
import pandas as pd

HORIZONS={'1M':21,'3M':63,'6M':126,'12M':252}

def _ret(h,d):
    c=h['Close'].dropna() if h is not None and not h.empty else pd.Series(dtype=float)
    if len(c)<=d: return np.nan
    return (float(c.iloc[-1])/float(c.iloc[-(d+1)])-1)*100

def add_multi_horizon_rs(results,histories,price_map,sector_etfs):
    out=results.copy(); spy=price_map.get('SPY')
    spy_ret={k:_ret(spy,d) for k,d in HORIZONS.items()}
    vals=[]
    for _,r in out.iterrows():
        t=r['Ticker']; h=histories.get(t); sec=r.get('Sector')
        etf=sector_etfs.get(sec); sh=price_map.get(etf) if etf else None
        rec={}
        components=[]
        weights={'1M':.15,'3M':.35,'6M':.30,'12M':.20}
        for label,d in HORIZONS.items():
            sr=_ret(h,d); br=spy_ret[label]; rr=sr-br if pd.notna(sr) and pd.notna(br) else np.nan
            rec[f'RS_{label}_vs_SPY_%']=rr
            if pd.notna(rr): components.append((rr,weights[label]))
        sec3=_ret(sh,63); stock3=_ret(h,63)
        rec['RS_3M_vs_Sector_%']=stock3-sec3 if pd.notna(stock3) and pd.notna(sec3) else np.nan
        if components:
            denom=sum(w for _,w in components)
            rec['RS_Composite_Raw']=sum(v*w for v,w in components)/denom
        else:
            rec['RS_Composite_Raw']=np.nan
        vals.append(rec)
    rs=pd.DataFrame(vals,index=out.index)
    out=pd.concat([out,rs],axis=1)
    raw=out['RS_Composite_Raw'].replace([np.inf,-np.inf],np.nan)
    out['RS_Composite_Percentile']=(raw.rank(pct=True,method='average')*100).round(0)
    # Use composite percentile as primary RS percentile when available.
    out['RS_Percentile']=out['RS_Composite_Percentile'].fillna(out.get('RS_Percentile'))
    return out
