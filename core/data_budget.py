"""Central data-budget and freshness policy for agent research.

The desk reads shared snapshots first and only refreshes slow-moving fundamentals
when the snapshot is stale.  This prevents every agent from independently
spending provider quota for the same ticker.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json, math, os, tempfile
import pandas as pd

from core.cache_policy import FUNDAMENTALS_TTL, VALUATION_TTL
from core.production_storage import cloud_available,ensure_production_schema,execute_sql,query_sql

ROOT = Path(os.getenv('AGENT_SNAPSHOT_DIR', 'data/agent_snapshots'))
FUND_DIR = ROOT / 'fundamentals'

@dataclass(frozen=True)
class BudgetDecision:
    ticker: str
    dataset: str
    action: str
    reason: str
    age_seconds: float | None
    ttl_seconds: int
    snapshot_path: str
    def to_dict(self): return asdict(self)

def _safe(v):
    if isinstance(v, dict): return {str(k): _safe(x) for k,x in v.items()}
    if isinstance(v, (list, tuple)): return [_safe(x) for x in v]
    try:
        if hasattr(v, 'item'): return _safe(v.item())
    except Exception: pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
    if isinstance(v, (str,int,float,bool)) or v is None: return v
    return str(v)

def snapshot_path(ticker: str, dataset='fundamentals') -> Path:
    ticker=''.join(c for c in str(ticker).upper().strip() if c.isalnum() or c in '.-_')
    base = FUND_DIR if dataset == 'fundamentals' else ROOT / dataset
    return base / f'{ticker}.json'

def read_snapshot(ticker: str, dataset='fundamentals'):
    ticker=str(ticker).upper().strip()
    if cloud_available():
        ensure_production_schema()
        frame=query_sql('''SELECT refreshed_at,payload_json FROM shared_agent_snapshots
                           WHERE dataset=:dataset AND ticker=:ticker LIMIT 1''',
                        {'dataset':dataset,'ticker':ticker})
        if not frame.empty:
            try:
                payload=json.loads(frame.iloc[0]['payload_json']); ts=pd.Timestamp(frame.iloc[0]['refreshed_at'])
                if ts.tzinfo is None: ts=ts.tz_localize('UTC')
                payload['_age_seconds']=max(0.0,(pd.Timestamp.now(tz='UTC')-ts.tz_convert('UTC')).total_seconds())
                payload['_persistence']='POSTGRES'
                return payload
            except Exception: pass
    p=snapshot_path(ticker,dataset)
    if not p.exists(): return None
    try:
        payload=json.loads(p.read_text(encoding='utf-8'))
        ts=datetime.fromisoformat(payload['refreshed_at'].replace('Z','+00:00'))
        age=max(0.0,(datetime.now(timezone.utc)-ts.astimezone(timezone.utc)).total_seconds())
        payload['_age_seconds']=age
        return payload
    except Exception:
        return None

def decide(ticker: str, dataset='fundamentals', ttl_seconds=None, force=False):
    ttl=int(ttl_seconds or (FUNDAMENTALS_TTL if dataset=='fundamentals' else VALUATION_TTL))
    p=snapshot_path(ticker,dataset); snap=read_snapshot(ticker,dataset)
    age=None if snap is None else float(snap.get('_age_seconds',0))
    if force:
        return BudgetDecision(str(ticker).upper(),dataset,'REFRESH','Explicit event/force refresh.',age,ttl,str(p))
    if snap is None:
        return BudgetDecision(str(ticker).upper(),dataset,'REFRESH','No shared snapshot exists.',None,ttl,str(p))
    if age <= ttl:
        return BudgetDecision(str(ticker).upper(),dataset,'CACHE','Shared snapshot is still fresh.',age,ttl,str(p))
    return BudgetDecision(str(ticker).upper(),dataset,'REFRESH','Shared snapshot is stale.',age,ttl,str(p))

def write_snapshot(ticker: str, data: dict, dataset='fundamentals', provider_status=None):
    p=snapshot_path(ticker,dataset); p.parent.mkdir(parents=True,exist_ok=True)
    payload={'ticker':str(ticker).upper(),'dataset':dataset,'refreshed_at':datetime.now(timezone.utc).isoformat(),
             'provider_status':_safe(provider_status or {}),'data':_safe(data)}
    fd,tmp=tempfile.mkstemp(prefix=p.name+'.',suffix='.tmp',dir=str(p.parent)); os.close(fd)
    try:
        Path(tmp).write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True),encoding='utf-8')
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    payload['_persistence']='LOCAL'
    if cloud_available():
        ensure_production_schema()
        ok,_=execute_sql('''INSERT INTO shared_agent_snapshots(dataset,ticker,refreshed_at,payload_json)
            VALUES (:dataset,:ticker,:refreshed_at,:payload)
            ON CONFLICT (dataset,ticker) DO UPDATE SET refreshed_at=EXCLUDED.refreshed_at,payload_json=EXCLUDED.payload_json''',
            {'dataset':dataset,'ticker':str(ticker).upper(),'refreshed_at':payload['refreshed_at'],
             'payload':json.dumps(payload,ensure_ascii=False,default=str)})
        if ok: payload['_persistence']='POSTGRES'
    return payload

def shared_fundamental_snapshot(ticker: str, loader, force=False):
    """Return (data, budget_decision, refreshed).

    Only the loader is allowed to spend provider quota, and it is called solely
    when the central snapshot policy says REFRESH.
    """
    d=decide(ticker,'fundamentals',FUNDAMENTALS_TTL,force=force)
    if d.action=='CACHE':
        snap=read_snapshot(ticker,'fundamentals') or {}
        return snap.get('data',{}), d, False
    data=loader(str(ticker).upper()) or {}
    write_snapshot(ticker,data,'fundamentals',data.get('Fundamentals_Provider_Status',{}))
    return data,d,True
