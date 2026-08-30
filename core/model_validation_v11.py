"""V11 validation, attribution and drift tools."""
from __future__ import annotations
import numpy as np
import pandas as pd


def walk_forward_summary(df,score_col='Opportunity',return_col='Fwd_63d_%',regime_col=None,min_n=5):
    if df is None or df.empty or score_col not in df or return_col not in df:return pd.DataFrame()
    x=df.copy(); x[score_col]=pd.to_numeric(x[score_col],errors='coerce');x[return_col]=pd.to_numeric(x[return_col],errors='coerce');x=x.dropna(subset=[score_col,return_col])
    if x.empty:return pd.DataFrame()
    x['Score_Bucket']=pd.cut(x[score_col],[0,50,60,70,80,90,101],right=False)
    group=['Score_Bucket']+([regime_col] if regime_col and regime_col in x else [])
    g=x.groupby(group,observed=True)[return_col]
    out=g.agg(N='size',Mean='mean',Median='median',Std='std').reset_index(); out=out[out.N>=min_n]
    # compatible hit rate calculated separately
    hit=x.assign(_hit=x[return_col]>0).groupby(group,observed=True)['_hit'].mean().mul(100).reset_index(name='Hit_Rate_%')
    return out.merge(hit,on=group,how='left')

def probability_metrics(predicted,realized):
    p=pd.to_numeric(pd.Series(predicted),errors='coerce'); y=pd.to_numeric(pd.Series(realized),errors='coerce'); x=pd.DataFrame({'p':p,'y':y}).dropna();
    if x.empty:return {}
    x.p=x.p.clip(0,1); x.y=x.y.clip(0,1)
    brier=float(np.mean((x.p-x.y)**2)); calibration=float(abs(x.p.mean()-x.y.mean()))
    return {'N':len(x),'Brier_Score':brier,'Mean_Predicted':float(x.p.mean()),'Mean_Realized':float(x.y.mean()),'Calibration_Error':calibration}

def decision_attribution(row, component_cols, realized_return):
    comps={c:pd.to_numeric(pd.Series([row.get(c)]),errors='coerce').iloc[0] for c in component_cols}
    comps={k:v for k,v in comps.items() if pd.notna(v)}
    if not comps:return pd.DataFrame()
    direction=1 if realized_return>=0 else -1
    rows=[]
    for k,v in comps.items():
        signed=(v-50)*direction
        rows.append({'Component':k,'Score':v,'ExPost_Contribution_Proxy':signed,'Helped':signed>0})
    return pd.DataFrame(rows).sort_values('ExPost_Contribution_Proxy',ascending=False)

def model_drift(history:pd.DataFrame,score_col='Opportunity',return_col='Fwd_63d_%',date_col='asof',freq='YE'):
    if history is None or history.empty or any(c not in history for c in [score_col,return_col,date_col]):return pd.DataFrame()
    x=history.copy();x[date_col]=pd.to_datetime(x[date_col],errors='coerce');x[score_col]=pd.to_numeric(x[score_col],errors='coerce');x[return_col]=pd.to_numeric(x[return_col],errors='coerce');x=x.dropna(subset=[date_col,score_col,return_col])
    if x.empty:return pd.DataFrame()
    rows=[]
    for period,g in x.groupby(x[date_col].dt.to_period('Y')):
        if len(g)<8:continue
        rows.append({'Period':str(period),'N':len(g),'Score_Return_Corr':g[score_col].corr(g[return_col]),'TopQuartile_Median_Return':g.loc[g[score_col]>=g[score_col].quantile(.75),return_col].median()})
    return pd.DataFrame(rows)

def regime_conditioned_weights(validation:pd.DataFrame,component_cols,return_col='Fwd_63d_%',regime_col='Macro_Regime'):
    if validation is None or validation.empty or regime_col not in validation:return {}
    out={}
    for regime,g in validation.groupby(regime_col):
        corrs={}
        for c in component_cols:
            if c in g and return_col in g:
                a=pd.to_numeric(g[c],errors='coerce');b=pd.to_numeric(g[return_col],errors='coerce');m=a.notna()&b.notna()
                if m.sum()>=10:corrs[c]=max(0,float(a[m].corr(b[m]) or 0))
        s=sum(corrs.values());out[regime]={k:v/s for k,v in corrs.items()} if s else {}
    return out
