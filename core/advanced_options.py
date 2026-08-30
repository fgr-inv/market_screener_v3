import numpy as np
import pandas as pd
import yfinance as yf


def _spot(t):
    try:
        h=t.history(period='5d',auto_adjust=True)
        return float(h['Close'].dropna().iloc[-1])
    except Exception:
        return np.nan


def _chain_expiry_metrics(t, exp, spot):
    ch=t.option_chain(exp)
    rows=[]
    for kind,df in [('CALL',ch.calls),('PUT',ch.puts)]:
        if df is None or df.empty: continue
        x=df.copy(); x['type']=kind
        for c in ['strike','impliedVolatility','openInterest','volume','bid','ask','lastPrice']:
            if c in x: x[c]=pd.to_numeric(x[c],errors='coerce')
        x['distance_%']=(x['strike']/spot-1)*100 if pd.notna(spot) and spot else np.nan
        rows.append(x)
    if not rows: return {},pd.DataFrame()
    d=pd.concat(rows,ignore_index=True)
    near=d[d['distance_%'].abs()<=10].copy()
    atm=near.iloc[(near['strike']-spot).abs().argsort()[:6]] if len(near) else pd.DataFrame()
    atm_iv=float(atm['impliedVolatility'].mean()*100) if len(atm) else np.nan
    call_oi=float(d.loc[d['type']=='CALL','openInterest'].fillna(0).sum())
    put_oi=float(d.loc[d['type']=='PUT','openInterest'].fillna(0).sum())
    # Gamma proxy: OI concentration around ATM. This is not dealer GEX.
    gamma_proxy=np.nan
    if len(near):
        oi=near['openInterest'].fillna(0)
        weights=np.exp(-near['distance_%'].abs()/3)
        gamma_proxy=float((oi*weights).sum())
    # Unusual volume heuristic vs OI
    unusual=d[(d['volume'].fillna(0)>=500) & (d['volume'].fillna(0) > 0.5*d['openInterest'].fillna(0))].copy()
    return {
        'expiration':exp,'atm_iv_%':atm_iv,'put_call_oi':put_oi/call_oi if call_oi else np.nan,
        'gamma_oi_proxy':gamma_proxy,'unusual_contracts':len(unusual)
    }, unusual


def advanced_options_snapshot(ticker, max_expiries=6):
    out={'available':False,'spot':np.nan,'term_structure':pd.DataFrame(),'unusual_flow':pd.DataFrame(),'iv_rank_proxy_%':np.nan,'max_pain':np.nan,'note':'Gamma is an OI concentration proxy, not dealer GEX.'}
    try:
        t=yf.Ticker(ticker); exps=list(t.options or [])[:max_expiries]; spot=_spot(t); out['spot']=spot
        metrics=[]; unusual=[]
        for exp in exps:
            m,u=_chain_expiry_metrics(t,exp,spot)
            if m: metrics.append(m)
            if len(u): unusual.append(u.assign(expiration=exp))
        term=pd.DataFrame(metrics)
        out['term_structure']=term
        if unusual: out['unusual_flow']=pd.concat(unusual,ignore_index=True).head(100)
        if len(term):
            vals=term['atm_iv_%'].dropna()
            if len(vals)>=2:
                current=float(vals.iloc[0]); lo=float(vals.min()); hi=float(vals.max())
                out['iv_rank_proxy_%']=50 if hi==lo else (current-lo)/(hi-lo)*100
        # Max pain proxy from nearest expiry aggregate intrinsic payout.
        if exps:
            ch=t.option_chain(exps[0]); calls=ch.calls; puts=ch.puts
            strikes=sorted(set(pd.concat([calls['strike'],puts['strike']]).dropna().astype(float)))
            best=None
            for s in strikes:
                cp=((s-calls['strike']).clip(lower=0)*pd.to_numeric(calls['openInterest'],errors='coerce').fillna(0)).sum()
                pp=((puts['strike']-s).clip(lower=0)*pd.to_numeric(puts['openInterest'],errors='coerce').fillna(0)).sum()
                pain=float(cp+pp)
                if best is None or pain<best[0]: best=(pain,s)
            if best: out['max_pain']=best[1]
        out['available']=bool(exps)
    except Exception as e:
        out['error']=str(e)[:150]
    return out
