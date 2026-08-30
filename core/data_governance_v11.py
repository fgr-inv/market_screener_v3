from __future__ import annotations
from datetime import datetime, timezone
import pandas as pd
import numpy as np

def freshness_table(records):
    now=pd.Timestamp.now(tz='UTC');rows=[]
    for r in records or []:
        obs=pd.to_datetime(r.get('observed_at'),errors='coerce',utc=True);age=(now-obs).total_seconds()/86400 if pd.notna(obs) else np.nan; max_age=float(r.get('max_age_days',30))
        rows.append({'Metric':r.get('metric'),'Value':r.get('value'),'Source':r.get('source'),'Observed':obs,'Age_Days':age,'Max_Age_Days':max_age,'Status':'STALE' if pd.notna(age) and age>max_age else 'CURRENT' if pd.notna(obs) else 'UNKNOWN'})
    return pd.DataFrame(rows)

def coverage_confidence(required,observed,stale=None):
    required=list(required or []); observed=set(observed or []); stale=set(stale or [])
    if not required:return {'Coverage_%':100.,'Fresh_Coverage_%':100.,'Missing':[],'Stale':[]}
    present=[x for x in required if x in observed]; fresh=[x for x in present if x not in stale]
    return {'Coverage_%':len(present)/len(required)*100,'Fresh_Coverage_%':len(fresh)/len(required)*100,'Missing':[x for x in required if x not in observed],'Stale':[x for x in present if x in stale]}

def lineage_tree(score_name,components):
    rows=[]
    for c in components or []:
        rows.append({'Score':score_name,'Component':c.get('component'),'Raw_Value':c.get('raw_value'),'Normalized':c.get('normalized'),'Weight':c.get('weight'),'Contribution':c.get('contribution'),'Source':c.get('source'),'Observed_At':c.get('observed_at')})
    return pd.DataFrame(rows)
