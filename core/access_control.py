"""Identity, subscription entitlements and usage quotas.

The identity source is deliberately server-side. A client cannot promote itself
by changing a query parameter or Streamlit widget. In production, the auth
provider should supply user_id/email; subscription state comes from the DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json, os, threading, time

from core.plans import normalize_plan, plan_config, is_owner, api_unit_cost
from core.production_storage import cloud_available, execute_sql, query_sql, ensure_production_schema

ROOT=Path(__file__).resolve().parents[1]
LOCAL_USAGE=ROOT/'data'/'usage_events.jsonl'
LOCAL_USAGE.parent.mkdir(parents=True,exist_ok=True)
_USAGE_LOCK=threading.Lock()


def _secret(name, default=''):
    val=os.getenv(name)
    if val not in (None,''): return val
    try:
        import streamlit as st
        return st.secrets.get(name,default)
    except Exception:
        return default


def _split(value):
    if isinstance(value,(list,tuple,set)): return {str(x).strip().lower() for x in value if str(x).strip()}
    return {x.strip().lower() for x in str(value or '').split(',') if x.strip()}


def _subscription_from_db(user_id: str):
    if not cloud_available() or not user_id: return None
    df=query_sql("""SELECT plan,status,billing_cycle,current_period_end FROM subscriptions
                    WHERE user_id=:uid ORDER BY updated_at DESC LIMIT 1""", {'uid':user_id})
    if df.empty: return None
    row=df.iloc[0].to_dict()
    if str(row.get('status','')).lower() not in {'active','trialing'}: return None
    return row


def current_user() -> dict:
    # These are placeholders for a future auth integration, but remain server-side.
    user_id=str(_secret('DEV_USER_ID','local-user') or 'local-user')
    email=str(_secret('DEV_USER_EMAIL','') or '').strip().lower()
    owner_ids=_split(_secret('OWNER_USER_IDS',''))
    owner_emails=_split(_secret('OWNER_EMAILS',''))
    explicit_role=str(_secret('DEV_USER_ROLE','') or '').strip().upper()
    dev_plan=str(_secret('DEV_USER_PLAN','FREE') or 'FREE')

    if explicit_role in {'OWNER','ADMIN'} or user_id.lower() in owner_ids or (email and email in owner_emails):
        plan='OWNER'
        source='owner_allowlist'
    else:
        sub=_subscription_from_db(user_id)
        if sub:
            plan=normalize_plan(sub.get('plan'))
            source='subscription_db'
        else:
            plan=normalize_plan(dev_plan)
            source='dev_default'
    return {'user_id':user_id,'email':email,'plan':plan,'role':'OWNER' if is_owner(plan) else 'USER','plan_source':source}


def feature_allowed(feature: str, user: dict | None=None) -> bool:
    user=user or current_user(); return bool(plan_config(user['plan']).get(feature,False))


def limit_value(key: str, user: dict | None=None, default=None):
    user=user or current_user(); return plan_config(user['plan']).get(key,default)


def _period_bounds(now=None):
    now=now or datetime.now(timezone.utc)
    day=now.strftime('%Y-%m-%d')
    month=now.strftime('%Y-%m')
    return day,month


def _local_events(user_id=None, feature=None):
    rows=[]
    try:
        with _USAGE_LOCK:
            lines=LOCAL_USAGE.read_text(encoding='utf-8').splitlines() if LOCAL_USAGE.exists() else []
        for line in lines:
            try: obj=json.loads(line)
            except Exception: continue
            if user_id and obj.get('user_id')!=user_id: continue
            if feature and obj.get('feature')!=feature: continue
            rows.append(obj)
    except Exception: pass
    return rows


def usage_counts(feature: str, user: dict | None=None) -> dict:
    user=user or current_user(); uid=user['user_id']; day,month=_period_bounds()
    if cloud_available():
        df=query_sql("""SELECT created_at,units FROM usage_events WHERE user_id=:uid AND feature=:feature
                     AND created_at >= date_trunc('month', CURRENT_TIMESTAMP)""", {'uid':uid,'feature':feature})
        if not df.empty:
            ts=df['created_at'].astype(str)
            units=df.get('units',1)
            return {'daily':int(units[ts.str.startswith(day)].sum()), 'monthly':int(units.sum())}
    rows=_local_events(uid,feature)
    return {
        'daily':sum(int(r.get('units',1)) for r in rows if str(r.get('created_at','')).startswith(day)),
        'monthly':sum(int(r.get('units',1)) for r in rows if str(r.get('created_at','')).startswith(month)),
    }


def quota_status(feature: str, user: dict | None=None) -> dict:
    user=user or current_user(); cfg=plan_config(user['plan'])
    if cfg.get('quota_exempt'):
        return {'allowed':True,'exempt':True,'daily_used':0,'monthly_used':0,'daily_limit':None,'monthly_limit':None}
    q=(cfg.get('quotas') or {}).get(feature)
    if not q:
        return {'allowed':feature_allowed(feature,user),'exempt':False,'daily_used':0,'monthly_used':0,'daily_limit':None,'monthly_limit':None}
    u=usage_counts(feature,user); dl=q.get('daily'); ml=q.get('monthly')
    ok=(dl is None or u['daily']<dl) and (ml is None or u['monthly']<ml)
    return {'allowed':ok,'exempt':False,'daily_used':u['daily'],'monthly_used':u['monthly'],'daily_limit':dl,'monthly_limit':ml}


def record_usage(feature: str, units=1, cache_hit=False, provider_cost=0.0, metadata=None, user=None):
    user=user or current_user()
    if is_owner(user['plan']):
        # Owner actions can still be logged for observability but never count toward quotas.
        billable=False
    else: billable=True
    now=datetime.now(timezone.utc).isoformat()
    payload={'user_id':user['user_id'],'feature':feature,'created_at':now,'units':int(units),
             'cache_hit':bool(cache_hit),'provider_cost':float(provider_cost or 0),'billable':billable,
             'metadata':metadata or {}}
    if cloud_available():
        ensure_production_schema()
        ok,_=execute_sql("""INSERT INTO usage_events(user_id,feature,created_at,units,cache_hit,provider_cost,billable,metadata_json)
                         VALUES (:user_id,:feature,:created_at,:units,:cache_hit,:provider_cost,:billable,:metadata_json)""",
                       {**payload,'metadata_json':json.dumps(payload['metadata'],ensure_ascii=False)})
        if ok: return True
    try:
        with _USAGE_LOCK:
            with LOCAL_USAGE.open('a',encoding='utf-8') as f: f.write(json.dumps(payload,ensure_ascii=False)+'\n')
        return True
    except Exception: return False


def require_feature(feature: str, label: str | None=None, user=None):
    user=user or current_user()
    if feature_allowed(feature,user): return True
    try:
        import streamlit as st
        st.error(f"🔒 {label or feature} no está incluido en el plan {user['plan']}.")
    except Exception: pass
    return False


def require_quota(feature: str, label: str | None=None, user=None):
    user=user or current_user(); s=quota_status(feature,user)
    if s['allowed']: return True
    try:
        import streamlit as st
        st.error(f"⛔ Límite alcanzado para {label or feature}. Hoy: {s['daily_used']}/{s['daily_limit']} · Mes: {s['monthly_used']}/{s['monthly_limit']}.")
    except Exception: pass
    return False


def set_subscription(user_id: str, plan: str, status='active', billing_cycle='monthly', provider_customer_id=None, provider_subscription_id=None, current_period_end=None):
    plan=normalize_plan(plan)
    if plan=='OWNER':
        return False,'OWNER must be granted server-side via OWNER_USER_IDS/OWNER_EMAILS, not billing.'
    if not cloud_available(): return False,'DATABASE_URL not configured'
    ensure_production_schema()
    return execute_sql("""INSERT INTO subscriptions(user_id,plan,status,billing_cycle,provider_customer_id,provider_subscription_id,current_period_end,updated_at)
        VALUES (:uid,:plan,:status,:cycle,:cid,:sid,:pend,CURRENT_TIMESTAMP)
        ON CONFLICT (user_id) DO UPDATE SET plan=EXCLUDED.plan,status=EXCLUDED.status,billing_cycle=EXCLUDED.billing_cycle,
        provider_customer_id=EXCLUDED.provider_customer_id,provider_subscription_id=EXCLUDED.provider_subscription_id,current_period_end=EXCLUDED.current_period_end,updated_at=CURRENT_TIMESTAMP""",
        {'uid':user_id,'plan':plan,'status':status,'cycle':billing_cycle,'cid':provider_customer_id,'sid':provider_subscription_id,'pend':current_period_end})


_JOB_LOCK=threading.Lock()
_ACTIVE_JOBS={}


def api_budget_status(feature: str, user: dict | None=None, cache_hit=False) -> dict:
    user=user or current_user(); limit=plan_config(user['plan']).get('api_units_per_hour')
    cost=0 if cache_hit else api_unit_cost(feature)
    if limit is None:
        return {'allowed':True,'used':0,'limit':None,'cost':cost,'exempt':True}
    uid=user['user_id']; used=0
    if cloud_available():
        df=query_sql("""SELECT COALESCE(SUM(units),0) AS used FROM usage_events
                     WHERE user_id=:uid AND feature='__api_budget__'
                     AND created_at >= CURRENT_TIMESTAMP - INTERVAL '1 hour'""", {'uid':uid})
        if not df.empty:
            try: used=int(df.iloc[0].get('used',0) or 0)
            except Exception: used=0
    else:
        cutoff=time.time()-3600
        for r in _local_events(uid,'__api_budget__'):
            try: ts=datetime.fromisoformat(str(r.get('created_at')).replace('Z','+00:00')).timestamp()
            except Exception: continue
            if ts>=cutoff: used += int(r.get('units',0) or 0)
    return {'allowed':used+cost<=int(limit),'used':used,'limit':int(limit),'cost':cost,'exempt':False}


def require_api_budget(feature: str, user: dict | None=None, cache_hit=False) -> bool:
    user=user or current_user(); s=api_budget_status(feature,user,cache_hit=cache_hit)
    if not s['allowed']:
        try:
            import streamlit as st
            st.error(f"⛔ Presupuesto horario de uso externo alcanzado: {s['used']}/{s['limit']} unidades. Volvé a intentar más tarde.")
        except Exception: pass
        return False
    if s['cost']>0 and not s.get('exempt'):
        record_usage('__api_budget__',units=s['cost'],cache_hit=False,metadata={'source_feature':feature},user=user)
    return True


def begin_job(user: dict | None=None, ttl_seconds=900) -> str | None:
    """Reserve an in-process concurrent job slot. Expired leases self-heal."""
    user=user or current_user(); max_jobs=int(plan_config(user['plan']).get('max_concurrent_jobs',1) or 1)
    uid=user['user_id']; now=time.monotonic(); token=f"{uid}:{time.time_ns()}"
    with _JOB_LOCK:
        live=[(t,exp) for t,exp in _ACTIVE_JOBS.get(uid,[]) if exp>now]
        if len(live)>=max_jobs:
            _ACTIVE_JOBS[uid]=live; return None
        live.append((token,now+float(ttl_seconds))); _ACTIVE_JOBS[uid]=live
    return token


def end_job(token: str | None, user: dict | None=None) -> None:
    if not token: return
    user=user or current_user(); uid=user['user_id']
    with _JOB_LOCK:
        _ACTIVE_JOBS[uid]=[(t,e) for t,e in _ACTIVE_JOBS.get(uid,[]) if t!=token]
    try:
        import streamlit as st
        if st.session_state.get('_active_job_token')==token:
            del st.session_state['_active_job_token']
    except Exception:
        pass


def require_job_slot(user: dict | None=None) -> str | None:
    user=user or current_user()
    # A Streamlit stop/rerun can interrupt a page after it acquired a lease.
    # Release that session's previous lease before reserving a new one so a
    # failed provider call never blocks the user for the full lease TTL.
    try:
        import streamlit as st
        previous=st.session_state.pop('_active_job_token',None)
    except Exception:
        previous=None
    if previous:
        end_job(previous,user)
    token=begin_job(user)
    if token:
        try:
            st.session_state['_active_job_token']=token
        except Exception:
            pass
        return token
    try:
        import streamlit as st
        st.error(f"⏳ Alcanzaste el máximo de {plan_config(user['plan']).get('max_concurrent_jobs',1)} trabajos simultáneos para tu plan.")
    except Exception: pass
    return None
