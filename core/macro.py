
import numpy as np, pandas as pd
from core.utils import clamp

def _c(df):
    if df is None or df.empty or "Close" not in df: return pd.Series(dtype=float)
    return df["Close"].dropna()
def _lvl(df):
    c=_c(df); return float(c.iloc[-1]) if len(c) else np.nan
def _ret(df,d):
    c=_c(df)
    return np.nan if len(c)<=d else float(c.iloc[-1]/c.iloc[-(d+1)]-1)
def _rr(a,b,d):
    x,y=_c(a),_c(b); n=min(len(x),len(y))
    if n<=d: return np.nan
    return float((x.iloc[-1]/y.iloc[-1])/(x.iloc[-(d+1)]/y.iloc[-(d+1)])-1)

def _yield_bps(df,d):
    c=_c(df)
    if len(c)<=d: return np.nan
    delta=float(c.iloc[-1]-c.iloc[-(d+1)])
    scale=10.0 if abs(float(c.iloc[-1]))>15 else 100.0
    return delta*scale

def _components(pm,breadth=50):
    spy,iwm,rsp=pm.get("SPY"),pm.get("IWM"),pm.get("RSP")
    vix,tnx,dxy=pm.get("^VIX"),pm.get("^TNX"),pm.get("UUP")
    hyg,lqd,ief=pm.get("HYG"),pm.get("LQD"),pm.get("IEF")
    gold,oil,copper=pm.get("GLD"),pm.get("CL=F"),pm.get("HG=F")

    risk=50; v=_lvl(vix); v20=_ret(vix,20); iw=_rr(iwm,spy,20); rw=_rr(rsp,spy,20)
    if pd.notna(v): risk += 18 if v<16 else 10 if v<20 else 0 if v<25 else -15 if v<35 else -25
    if pd.notna(v20): risk += 8 if v20<-.10 else -8 if v20>.15 else 0
    if pd.notna(iw): risk += 10 if iw>.02 else -10 if iw<-.03 else 0
    if pd.notna(rw): risk += 8 if rw>.01 else -8 if rw<-.02 else 0
    risk=int(clamp(risk))

    credit=50; hi=_rr(hyg,ief,20); hl=_rr(hyg,lqd,20)
    if pd.notna(hi): credit += 22 if hi>.015 else -22 if hi<-.025 else 0
    if pd.notna(hl): credit += 14 if hl>0 else -14 if hl<-.015 else 0
    credit=int(clamp(credit))

    rates=50; t20=_ret(tnx,20); t5=_ret(tnx,5); t20bps=_yield_bps(tnx,20)
    if pd.notna(t20): rates += 18 if t20<-.05 else 8 if t20<0 else -12 if t20>.05 else 0
    if pd.notna(t5) and t5>.05: rates-=8
    rates=int(clamp(rates))

    liq=50; d20=_ret(dxy,20)
    if pd.notna(d20): liq += 18 if d20<-.02 else -18 if d20>.03 else 0
    liq=int(clamp(liq))

    growth=50; cg=_rr(copper,gold,20); c20=_ret(copper,20); iw63=_rr(iwm,spy,63)
    if pd.notna(cg): growth += 22 if cg>.04 else 10 if cg>0 else -22 if cg<-.05 else 0
    if pd.notna(c20): growth += 12 if c20>.05 else -12 if c20<-.05 else 0
    if pd.notna(iw63): growth += 10 if iw63>0 else -10 if iw63<-.03 else 0
    growth=int(clamp(growth))

    infl=50; o20=_ret(oil,20); o63=_ret(oil,63); g20=_ret(gold,20)
    if pd.notna(o20): infl += 20 if o20>.10 else 10 if o20>.04 else -10 if o20<-.10 else 0
    if pd.notna(o63) and o63>.20: infl+=10
    if pd.notna(g20) and g20>.05: infl+=5
    infl=int(clamp(infl))

    return {
        "Risk_Appetite":risk,"Credit":credit,"Rates":rates,"Liquidity":liq,"Growth":growth,
        "Inflation_Pressure":infl,"Breadth":int(clamp(breadth)),"VIX":v,
        "Copper_Gold_20d":cg,"Oil_20d":o20,"US10Y_20d":t20,"US10Y_20d_bps":t20bps,"Dollar_20d":d20,"HYG_IEF_20d":hi,
    }

def calculate_macro_snapshot(pm,breadth_level=50):
    now=_components(pm,breadth_level)
    shifted={k:(df.iloc[:-20].copy() if df is not None and len(df)>40 else df) for k,df in pm.items()}
    old=_components(shifted,breadth_level)
    def score(m):
        return int(clamp(.20*m["Breadth"]+.18*m["Credit"]+.15*m["Risk_Appetite"]+.14*m["Rates"]+.12*m["Liquidity"]+.13*m["Growth"]+.08*(100-m["Inflation_Pressure"])))
    s,so=score(now),score(old); delta=s-so
    riskreg="RISK-ON" if s>=70 else "RISK-OFF" if s<=40 else "NEUTRAL"
    gu=now["Growth"]>=50; iu=now["Inflation_Pressure"]>=55
    econ="GOLDILOCKS" if gu and not iu else "REFLATION" if gu and iu else "STAGFLATION RISK" if (not gu and iu) else "SLOWDOWN / DISINFLATION"
    mom="IMPROVING" if delta>=5 else "DETERIORATING" if delta<=-5 else "STABLE"
    out=dict(now); out.update({"Macro_Score":s,"Macro_Score_20d_Ago":so,"Macro_Delta_20d":delta,"Risk_Regime":riskreg,"Economic_Regime":econ,"Momentum":mom})
    return out

def _macro_value(m,key,*fallbacks,default=50):
    for candidate in (key,)+fallbacks:
        try:
            value=float((m or {}).get(candidate,np.nan))
            if pd.notna(value): return value
        except Exception:
            pass
    return float(default)

def sector_macro_score(sector,m):
    r=_macro_value(m,"Rates","Slow_Policy")
    c=_macro_value(m,"Credit")
    ra=_macro_value(m,"Risk_Appetite","Macro_Score")
    li=_macro_value(m,"Liquidity")
    g=_macro_value(m,"Growth","Slow_Growth")
    inf=_macro_value(m,"Inflation_Pressure","Slow_Inflation_Pressure")
    b=_macro_value(m,"Breadth")
    if sector=="Technology": s=.25*ra+.20*li+.20*r+.15*c+.10*b+.10*g
    elif sector=="Industrials": s=.30*g+.20*c+.20*b+.15*r+.15*ra
    elif sector=="Materials": s=.35*g+.20*r+.15*c+.15*b+.15*inf
    elif sector=="Energy": s=.35*inf+.20*g+.15*c+.15*r+.15*b
    elif sector in {"Utilities","Real Estate"}: s=.30*ra+.20*li+.20*c+.15*b+.15*(100-inf)
    elif sector=="Financials": s=.25*g+.25*c+.20*r+.15*b+.15*ra
    else: s=.20*r+.20*c+.18*ra+.12*li+.15*g+.15*b
    return int(clamp(round(s)))
