"""V10 zero-cost institutional research infrastructure.

The module intentionally separates OBSERVED data, DERIVED metrics and MISSING data.
It never converts unavailable specialist fields into neutral scores.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json, math
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
STORE=ROOT/'data'/'point_in_time_v10'
STORE.mkdir(parents=True,exist_ok=True)

FORWARD_WINDOWS=(1,5,20,63,126,252)


def _num(v):
    try:
        x=float(v); return x if np.isfinite(x) else np.nan
    except Exception:return np.nan


def save_snapshot(asset:str, payload:dict, asof=None, source_map=None):
    """Append an immutable JSONL point-in-time snapshot with lineage metadata."""
    asof=pd.Timestamp(asof or datetime.now(timezone.utc)).isoformat()
    row={'asset':asset.upper(),'asof':asof,'captured_at':datetime.now(timezone.utc).isoformat(),
         'payload':payload or {},'sources':source_map or {}}
    path=STORE/f'{asset.upper().replace("/","_")}.jsonl'
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,default=str,ensure_ascii=False)+'\n')
    return path


def load_snapshots(asset:str):
    path=STORE/f'{asset.upper().replace("/","_")}.jsonl'
    if not path.exists():return pd.DataFrame()
    rows=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        try: rows.append(json.loads(line))
        except Exception: pass
    if not rows:return pd.DataFrame()
    out=pd.json_normalize(rows); out['asof']=pd.to_datetime(out['asof'],errors='coerce',utc=True)
    return out.sort_values('asof')


def attach_forward_returns(snapshots, prices, price_col='Close'):
    """Attach future returns only for ex-post validation; never for live scoring."""
    if snapshots is None or snapshots.empty or prices is None or prices.empty:return pd.DataFrame()
    x=snapshots.copy(); p=prices[[price_col]].dropna().copy(); p.index=pd.to_datetime(p.index,utc=True).normalize()
    for w in FORWARD_WINDOWS:x[f'Fwd_{w}d_%']=np.nan
    for i,r in x.iterrows():
        d=pd.Timestamp(r['asof']).normalize(); loc=p.index.searchsorted(d)
        if loc>=len(p):continue
        p0=float(p.iloc[loc][price_col])
        for w in FORWARD_WINDOWS:
            j=loc+w
            if j<len(p) and p0:x.at[i,f'Fwd_{w}d_%']=(float(p.iloc[j][price_col])/p0-1)*100
    return x


def calibration_table(df, score_col, horizon=63, bins=(0,50,60,70,80,90,101)):
    ret=f'Fwd_{horizon}d_%'
    if df is None or df.empty or score_col not in df or ret not in df:return pd.DataFrame()
    x=df[[score_col,ret]].apply(pd.to_numeric,errors='coerce').dropna()
    if x.empty:return pd.DataFrame()
    x['bucket']=pd.cut(x[score_col],bins,right=False)
    rows=[]
    for b,g in x.groupby('bucket',observed=True):
        if len(g)<3:continue
        s=g[ret]
        rows.append({'Score Bucket':str(b),'N':len(g),'Median Return %':s.median(),'Mean Return %':s.mean(),
                     'Hit Rate %':(s>0).mean()*100,'P10 %':s.quantile(.1),'P90 %':s.quantile(.9)})
    return pd.DataFrame(rows)


def probability_calibration(predicted, realized, bins=10):
    x=pd.DataFrame({'p':pd.to_numeric(predicted,errors='coerce'),'y':pd.to_numeric(realized,errors='coerce')}).dropna()
    if x.empty:return pd.DataFrame()
    x['p']=x['p'].clip(0,1); x['bucket']=pd.cut(x['p'],np.linspace(0,1,bins+1),include_lowest=True)
    return x.groupby('bucket',observed=True).agg(Predicted=('p','mean'),Realized=('y','mean'),N=('y','size')).reset_index()


def event_study(prices, event_dates, windows=(-20,-5,-1,1,5,20), price_col='Close'):
    if prices is None or prices.empty:return pd.DataFrame()
    p=prices[price_col].dropna(); p.index=pd.to_datetime(p.index).tz_localize(None).normalize()
    rows=[]
    for ed in pd.to_datetime(pd.Series(event_dates),errors='coerce').dropna():
        loc=p.index.searchsorted(ed.normalize())
        if loc>=len(p):continue
        base=float(p.iloc[loc]); row={'Event':ed.date().isoformat()}
        for w in windows:
            j=loc+w
            row[f'T{w:+d}_%']=(float(p.iloc[j])/base-1)*100 if 0<=j<len(p) and base else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def relative_value_rank(frame, positive=('Quality','Revisions','Trend','RS','Opportunity'), negative=('Risk','Valuation_Expensiveness')):
    """Cross-sectional percentile rank, missing-aware. No absent factor receives 50."""
    if frame is None or frame.empty:return pd.DataFrame()
    x=frame.copy(); components=[]
    for c in positive:
        if c in x and pd.to_numeric(x[c],errors='coerce').notna().sum()>=2:
            z=pd.to_numeric(x[c],errors='coerce').rank(pct=True)*100; x[f'RV_{c}']=z; components.append(f'RV_{c}')
    for c in negative:
        if c in x and pd.to_numeric(x[c],errors='coerce').notna().sum()>=2:
            z=(1-pd.to_numeric(x[c],errors='coerce').rank(pct=True))*100; x[f'RV_{c}']=z; components.append(f'RV_{c}')
    x['Relative_Value_Score']=x[components].mean(axis=1,skipna=True) if components else np.nan
    x['Relative_Value_Coverage_%']=x[components].notna().mean(axis=1)*100 if components else 0
    return x


def etf_lookthrough(holdings, analyses, weight_col='Weight'):
    """Aggregate constituent research into ETF-level quality without pretending missing holdings are covered."""
    if holdings is None or holdings.empty:return {}
    h=holdings.copy(); h['Ticker']=h['Ticker'].astype(str).str.upper(); h[weight_col]=pd.to_numeric(h[weight_col],errors='coerce').fillna(0)
    total=h[weight_col].sum();
    if total<=0:return {}
    h[weight_col]/=total
    metrics=['Quality','Valuation','Revisions','Trend','Opportunity','Risk']
    out={}
    covered_weight=0
    for _,r in h.iterrows():
        a=analyses.get(r['Ticker'],{}) if analyses else {}
        if a:covered_weight+=r[weight_col]
    for m in metrics:
        vals=[]; ws=[]
        for _,r in h.iterrows():
            v=_num((analyses.get(r['Ticker'],{}) if analyses else {}).get(m))
            if pd.notna(v):vals.append(v);ws.append(r[weight_col])
        out[m]=float(np.average(vals,weights=ws)) if vals and sum(ws)>0 else np.nan
    out['Lookthrough_Coverage_%']=covered_weight*100
    out['Top10_Concentration_%']=h.nlargest(10,weight_col)[weight_col].sum()*100
    out['Effective_Holdings']=float(1/(h[weight_col].pow(2).sum())) if (h[weight_col].pow(2).sum()) else np.nan
    return out


def signal_agreement(signals:dict):
    vals=[]
    for v in (signals or {}).values():
        n=_num(v)
        if pd.notna(n): vals.append((n-50)/50)
    if not vals:return {'Agreement_%':np.nan,'Dispersion':np.nan,'Direction':'N/D'}
    direction=np.sign(np.mean(vals)); agree=np.mean([np.sign(v)==direction for v in vals if v!=0])*100 if direction else 50
    return {'Agreement_%':float(agree),'Dispersion':float(np.std(vals)),'Direction':'BULLISH' if direction>0 else 'BEARISH' if direction<0 else 'MIXED'}


def evidence_lineage(inputs:dict):
    rows=[]
    now=pd.Timestamp.now(tz='UTC')
    for name,item in (inputs or {}).items():
        item=item if isinstance(item,dict) else {'value':item}
        obs=pd.to_datetime(item.get('observed_at'),errors='coerce',utc=True)
        age=(now-obs).total_seconds()/86400 if pd.notna(obs) else np.nan
        rows.append({'Metric':name,'Value':item.get('value'),'Source':item.get('source','N/D'),'Observed':obs,
                     'Age Days':age,'Status':'STALE' if pd.notna(age) and age>item.get('max_age_days',30) else 'CURRENT' if pd.notna(obs) else 'UNKNOWN'})
    return pd.DataFrame(rows)


def free_data_coverage_contracts():
    return pd.DataFrame([
        ('Equity','SEC EDGAR/XBRL','No key','filings, point-in-time accounting facts'),
        ('Macro/Rates','FRED + ALFRED','Free key','series, release dates, vintage observations'),
        ('Energy','EIA Open Data','Free key','oil/gas production, inventories, storage, flows'),
        ('Futures','CFTC COT','No key','positioning/open interest'),
        ('Crypto','CoinGecko','Demo/free key','market cap, supply, volume, metadata'),
        ('Crypto derivatives','Binance/Bybit/OKX public','No key','funding, OI, basis where exposed'),
        ('DeFi','DefiLlama','No key','chain/protocol TVL'),
        ('BTC network','Blockchain.com public','No key','hashrate, difficulty, miners, transactions'),
        ('Biotech','ClinicalTrials.gov v2','No key','trial phase/status/timing'),
        ('Healthcare','openFDA','No key/basic','labels/context; not pipeline probability'),
    ],columns=['Asset/Coverage','Provider','Access','Use'])
