
import numpy as np, pandas as pd
from core.indicators import enrich_indicators
from core.utils import clamp

def _breadth(df,pm,name):
    v=a20=a50=a62=a200=up=hi=lo=0
    for t in df["Ticker"].tolist():
        try:
            raw=pm.get(t)
            if raw is None or raw.empty: continue
            h=enrich_indicators(raw); last=h.iloc[-1]
            if pd.isna(last["SMA200"]): continue
            v+=1; p=float(last["Close"])
            a20+=int(p>float(last["EMA20"])); a50+=int(p>float(last["SMA50"])); a62+=int(p>float(last["EMA62"])); a200+=int(p>float(last["SMA200"]))
            up+=int(p>float(last["EMA62"])>float(last["EMA79"])>float(last["SMA200"]))
            if pd.notna(last["High252"]): hi+=int(p>=float(last["High252"])*.98)
            if pd.notna(last["Low252"]): lo+=int(p<=float(last["Low252"])*1.02)
        except Exception: pass
    if v==0: return {"Universe":name,"Valid":0,"Total":len(df),"Score":np.nan}
    vals=[x/v*100 for x in [a20,a50,a62,a200,up,hi,lo]]
    p20,p50,p62,p200,pup,ph,pl=vals
    sc=int(clamp(.18*p20+.22*p50+.18*p62+.25*p200+.12*pup+.05*clamp(50+(ph-pl)*3)))
    return {"Universe":name,"Valid":v,"Total":len(df),"> EMA20 %":round(p20,1),"> SMA50 %":round(p50,1),"> EMA62 %":round(p62,1),"> SMA200 %":round(p200,1),"Structural Uptrend %":round(pup,1),"Near 52w High %":round(ph,1),"Near 52w Low %":round(pl,1),"Score":sc}

def composite_breadth(universes,pm):
    rows=[_breadth(df,pm,name) for name,df in universes.items()]
    tab=pd.DataFrame(rows)
    # Broad-market breadth avoids letting mega-cap Nasdaq constituents dominate
    # the reading while still retaining a focused growth/technology overlay.
    weights={"S&P 500":.50,"S&P MidCap 400":.25,"S&P SmallCap 600":.15,"Nasdaq 100":.10}
    valid=[r for r in rows if pd.notna(r.get("Score")) and weights.get(r["Universe"],0)>0]
    denom=sum(weights[r["Universe"]] for r in valid)
    comp=sum(r["Score"]*weights[r["Universe"]] for r in valid)/denom if denom else np.nan
    return (round(float(comp),1) if pd.notna(comp) else np.nan),tab
