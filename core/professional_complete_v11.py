"""V11 complete zero-cost analytical layer.
Pure functions; no network dependency. Missing inputs stay missing.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd


def _s(x): return pd.to_numeric(pd.Series(x),errors='coerce')
def _n(v):
    try:
        z=float(v); return z if np.isfinite(z) else np.nan
    except Exception:return np.nan

def weighted_missing(values,weights):
    pairs=[(_n(v),_n(w)) for v,w in zip(values,weights)]
    pairs=[(v,w) for v,w in pairs if pd.notna(v) and pd.notna(w) and w>0]
    if not pairs:return np.nan,0.0
    sw=sum(w for _,w in pairs); return sum(v*w for v,w in pairs)/sw, sw/sum(w for w in weights if _n(w)>0)*100

def fundamental_acceleration(history:pd.DataFrame):
    if history is None or history.empty:return {}
    out={}
    for col in ['Revenue','EPS','FCF','Gross_Margin','Operating_Margin','RPO','ARR','Capex']:
        if col not in history:continue
        s=pd.to_numeric(history[col],errors='coerce').dropna()
        if len(s)<3:continue
        growth=s.pct_change().replace([np.inf,-np.inf],np.nan).dropna()*100 if col not in ['Gross_Margin','Operating_Margin'] else s.diff().dropna()
        if len(growth)>=2:
            out[col+'_Latest_Growth']=float(growth.iloc[-1]); out[col+'_Acceleration']=float(growth.iloc[-1]-growth.iloc[-2])
    acc=[v for k,v in out.items() if k.endswith('_Acceleration') and pd.notna(v)]
    if acc:out['Fundamental_Momentum_Score']=float(np.clip(50+np.nanmean(acc)*2,0,100))
    return out

def forensic_v2(x:dict):
    rev=_n(x.get('Revenue')); rec=_n(x.get('Receivables')); inv=_n(x.get('Inventory')); ni=_n(x.get('NetIncome')); cfo=_n(x.get('OCF')); sbc=_n(x.get('SBC')); fcf=_n(x.get('FCF')); shares=_n(x.get('Shares')); prior_sh=_n(x.get('Shares_Prior'))
    flags=[]; scores=[]
    if pd.notna(ni) and abs(ni)>0 and pd.notna(cfo):
        r=cfo/ni; scores.append(np.clip(50+25*(r-1),0,100));
        if r<0.7:flags.append('CFO materially below net income')
    if rev>0 and pd.notna(sbc):
        r=sbc/rev; scores.append(np.clip(100-r*400,0,100));
        if r>0.1:flags.append('High SBC / revenue')
    if rev>0 and pd.notna(inv):
        r=inv/rev; scores.append(np.clip(90-r*100,10,100))
    if rev>0 and pd.notna(rec):
        r=rec/rev; scores.append(np.clip(90-r*100,10,100))
    if prior_sh>0 and shares>0:
        dilution=(shares/prior_sh-1)*100; scores.append(np.clip(80-dilution*4,0,100));
        if dilution>5:flags.append('Material share dilution')
    if rev>0 and pd.notna(fcf):scores.append(np.clip(50+fcf/rev*250,0,100))
    return {'Financial_Forensics_Score':float(np.mean(scores)) if scores else np.nan,'Warnings':flags,'Coverage_%':len(scores)/6*100}

def capital_allocation_v2(x:dict):
    roic=_n(x.get('ROIC')); wacc=_n(x.get('WACC')); fcf=_n(x.get('FCF')); capex=_n(x.get('Capex')); rev=_n(x.get('Revenue')); shares=_n(x.get('Shares')); prior=_n(x.get('Shares_Prior')); debt_change=_n(x.get('Debt_Change'))
    vals=[]
    if pd.notna(roic):vals.append(np.clip(50+(roic-10)*2,0,100))
    if pd.notna(roic) and pd.notna(wacc):vals.append(np.clip(50+(roic-wacc)*3,0,100))
    if rev>0 and pd.notna(fcf):vals.append(np.clip(50+fcf/rev*200,0,100))
    if shares>0 and prior>0:vals.append(np.clip(80-(shares/prior-1)*300,0,100))
    if pd.notna(debt_change):vals.append(np.clip(60-debt_change*2,0,100))
    score=float(np.mean(vals)) if vals else np.nan
    label='N/D' if pd.isna(score) else 'ELITE COMPOUNDER' if score>=85 else 'GOOD CAPITAL ALLOCATOR' if score>=70 else 'MIXED' if score>=50 else 'CAPITAL ALLOCATION RISK'
    return {'Capital_Allocation_V2':score,'Capital_Allocation_Label':label,'Coverage_%':len(vals)/5*100}

def moat_quality(x:dict):
    vals=[]
    for k,scale,center in [('ROIC',2,10),('Gross_Margin',1,40),('FCF_Margin',2,10),('Revenue_Stability',1,50),('Recurring_Revenue_%',.5,50)]:
        v=_n(x.get(k));
        if pd.notna(v): vals.append(np.clip(50+(v-center)*scale,0,100))
    return {'Moat_Quality_Score':float(np.mean(vals)) if vals else np.nan,'Coverage_%':len(vals)/5*100}

def fixed_income_regime(curves:dict):
    y2=_n(curves.get('2Y')); y10=_n(curves.get('10Y')); d2=_n(curves.get('2Y_Change_bp')); d10=_n(curves.get('10Y_Change_bp'))
    slope=y10-y2 if pd.notna(y10) and pd.notna(y2) else np.nan
    if pd.notna(d2) and pd.notna(d10):
        level=(d2+d10)/2; steep=d10-d2
        label=('BEAR ' if level>0 else 'BULL ')+('STEEPENER' if steep>0 else 'FLATTENER')
    else:label='N/D'
    return {'Curve_2s10s_%':slope,'Yield_Curve_Regime':label}

def fx_professional(pair:str, x:dict):
    vals=[]; names=[]
    for name,key,sign in [('RateDiff','Rate_Differential',1),('RealRateDiff','Real_Rate_Differential',1),('GrowthDiff','Growth_Differential',1),('Carry','Carry',1),('COT','COT_Score',1),('Trend','Trend_Score',1),('Risk','Risk_Appetite',1)]:
        v=_n(x.get(key));
        if pd.notna(v):
            score=np.clip(50+sign*v*5,0,100) if abs(v)<=10 else np.clip(v,0,100)
            vals.append(score);names.append(name)
    score=float(np.mean(vals)) if vals else np.nan
    return {'FX_Professional_Score':score,'FX_Model_Coverage_%':len(vals)/7*100,'Drivers':names}

def futures_curve_metrics(curve:pd.DataFrame):
    if curve is None or curve.empty:return {}
    c=curve.copy(); price_col='price' if 'price' in c else 'Price' if 'Price' in c else None
    if not price_col:return {}
    c[price_col]=pd.to_numeric(c[price_col],errors='coerce'); c=c.dropna(subset=[price_col])
    if len(c)<2:return {}
    p1,p2=float(c.iloc[0][price_col]),float(c.iloc[1][price_col]); p6=float(c.iloc[min(5,len(c)-1)][price_col])
    m12=(p1/p2-1)*100 if p2 else np.nan; m16=(p1/p6-1)*100 if p6 else np.nan
    return {'M1_M2_%':m12,'M1_M6_%':m16,'Curve_Regime':'BACKWARDATION' if m12>0 else 'CONTANGO','Curve_Tightness_Score':float(np.clip(50+m12*5,0,100))}

def cot_historical(current, history):
    s=pd.to_numeric(pd.Series(history),errors='coerce').dropna(); cur=_n(current)
    if pd.isna(cur) or len(s)<20:return {'COT_Percentile':np.nan,'COT_Crowding':'N/D'}
    pct=float((s<=cur).mean()*100); crowd='CROWDED LONG' if pct>=90 else 'LONG' if pct>=65 else 'CROWDED SHORT' if pct<=10 else 'SHORT' if pct<=35 else 'NEUTRAL'
    return {'COT_Percentile':pct,'COT_Crowding':crowd}

def crypto_liquidity(stablecoins:pd.DataFrame):
    if stablecoins is None or stablecoins.empty:return {}
    c='market_cap' if 'market_cap' in stablecoins else 'MarketCap' if 'MarketCap' in stablecoins else None
    d='date' if 'date' in stablecoins else None
    if not c:return {}
    x=stablecoins.copy(); x[c]=pd.to_numeric(x[c],errors='coerce')
    if d:
        x[d]=pd.to_datetime(x[d],errors='coerce'); total=x.groupby(d)[c].sum().sort_index()
    else: total=x[c].dropna()
    if len(total)<2:return {'Stablecoin_Total':float(total.iloc[-1]) if len(total) else np.nan}
    out={'Stablecoin_Total':float(total.iloc[-1])}
    for n in [7,30,90]:
        if len(total)>n:out[f'Stablecoin_Growth_{n}d_%']=(float(total.iloc[-1])/float(total.iloc[-n-1])-1)*100
    gs=[v for k,v in out.items() if 'Growth_' in k]; out['Crypto_Liquidity_Score']=float(np.clip(50+np.mean(gs)*3,0,100)) if gs else np.nan
    return out

def token_dilution(x:dict):
    circ=_n(x.get('circulating_supply')); total=_n(x.get('total_supply')); fdv=_n(x.get('fdv')); mc=_n(x.get('market_cap'))
    circp=circ/total*100 if total>0 and circ>=0 else np.nan; ratio=fdv/mc if mc>0 and pd.notna(fdv) else np.nan
    risk=[]
    if pd.notna(circp):risk.append(np.clip(100-circp,0,100))
    if pd.notna(ratio):risk.append(np.clip((ratio-1)*50,0,100))
    return {'Circulating_%':circp,'FDV_MCap':ratio,'Dilution_Risk':float(np.mean(risk)) if risk else np.nan}

def correlation_regimes(asset:pd.Series,benchmark:pd.Series):
    df=pd.concat([asset,benchmark],axis=1).dropna();
    if len(df)<30:return {}
    r=df.pct_change().dropna(); out={}
    for n in [20,60,120,252]:
        if len(r)>=n:out[f'Corr_{n}d']=float(r.iloc[-n:,0].corr(r.iloc[-n:,1]))
    down=r[r.iloc[:,1]<0]; out['Down_Market_Corr']=float(down.iloc[:,0].corr(down.iloc[:,1])) if len(down)>=10 else np.nan
    stress=r[r.iloc[:,1]<=r.iloc[:,1].quantile(.1)]; out['Stress_Corr']=float(stress.iloc[:,0].corr(stress.iloc[:,1])) if len(stress)>=8 else np.nan
    return out

def stress_portfolio(weights:dict, betas:dict, shocks:dict):
    rows=[]
    for scen,shockmap in shocks.items():
        total=0.; covered=0.
        for asset,w in weights.items():
            b=betas.get(asset,{})
            impact=0.; used=False
            for factor,shock in shockmap.items():
                beta=_n(b.get(factor))
                if pd.notna(beta):impact+=beta*shock;used=True
            if used:total+=w*impact;covered+=abs(w)
        rows.append({'Scenario':scen,'Portfolio_Impact_%':total,'Coverage_%':min(covered,1)*100})
    return pd.DataFrame(rows)

def execution_quality(price,adv_dollar,volatility,spread_bps=np.nan):
    vals=[]
    if pd.notna(_n(adv_dollar)): vals.append(np.clip(20+math.log10(max(_n(adv_dollar),1))*10,0,100))
    if pd.notna(_n(volatility)): vals.append(np.clip(100-_n(volatility),0,100))
    if pd.notna(_n(spread_bps)): vals.append(np.clip(100-_n(spread_bps)*2,0,100))
    return {'Execution_Quality':float(np.mean(vals)) if vals else np.nan,'Coverage_%':len(vals)/3*100}

def source_reconcile(name, observations, tolerance_pct=2.0):
    vals=[(o.get('source','N/D'),_n(o.get('value'))) for o in observations if pd.notna(_n(o.get('value')))]
    if not vals:return {'Metric':name,'Status':'MISSING','Value':np.nan,'Conflict':False}
    median=float(np.median([v for _,v in vals])); conflicts=[s for s,v in vals if median and abs(v/median-1)*100>tolerance_pct]
    return {'Metric':name,'Status':'CONFLICT' if conflicts else 'OK','Value':median,'Conflict':bool(conflicts),'Conflict_Sources':conflicts,'Sources':[s for s,_ in vals]}

def signal_disagreement(signals:dict):
    vals={k:_n(v) for k,v in signals.items() if pd.notna(_n(v))}
    if not vals:return {'Signal_Agreement_%':np.nan,'Conflict_Count':0,'Direction':'N/D'}
    dirs={k:1 if v>55 else -1 if v<45 else 0 for k,v in vals.items()}; nz=[v for v in dirs.values() if v]
    if not nz:return {'Signal_Agreement_%':100.,'Conflict_Count':0,'Direction':'NEUTRAL'}
    maj=1 if sum(nz)>=0 else -1; agree=sum(v==maj for v in nz)/len(nz)*100; conflicts=sum(v not in (0,maj) for v in dirs.values())
    return {'Signal_Agreement_%':agree,'Conflict_Count':conflicts,'Direction':'BULLISH' if maj>0 else 'BEARISH'}

def relative_value_global(frame:pd.DataFrame,score_cols=None):
    if frame is None or frame.empty:return pd.DataFrame()
    score_cols=score_cols or ['Opportunity','Quality','Valuation','Revisions','Trend','Macro','Portfolio_Fit']
    out=frame.copy(); used=[]
    for c in score_cols:
        if c in out and pd.to_numeric(out[c],errors='coerce').notna().sum()>=2:
            out[c+'_Pct']=pd.to_numeric(out[c],errors='coerce').rank(pct=True)*100;used.append(c+'_Pct')
    out['Global_Relative_Value']=out[used].mean(axis=1,skipna=True) if used else np.nan
    out['Global_RV_Coverage_%']=out[used].notna().mean(axis=1)*100 if used else 0
    return out
