"""User-scoped forward validation for automated Investment Desk decisions.

This is an observation ledger, not a paper broker. It records what the CIO knew
at decision time and evaluates fixed trading-day horizons without creating an
order, position, fill, or P&L account.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import math
import numpy as np
import pandas as pd
from core.production_storage import cloud_available,ensure_production_schema,execute_sql,query_sql

ROOT=Path(__file__).resolve().parents[1]
DATA_DIR=ROOT/'data'/'shadow_validation'; DATA_DIR.mkdir(parents=True,exist_ok=True)
HORIZONS=(1,5,20)
MIN_RELIABLE_SAMPLE=20
DIRECTION_BY_STATE={'SETUP':'POSITIVE','IMPROVING':'POSITIVE','BROKEN_SETUP':'NEGATIVE','DETERIORATING':'NEGATIVE',
                    'MATERIAL_POSITIVE':'POSITIVE','MATERIAL_NEGATIVE':'NEGATIVE','CIO_PRIORITY':'POSITIVE'}
ACCEPTED_VERIFICATION={'VERIFIED','PARTIALLY_VERIFIED'}


def _safe(value): return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in str(value or 'local-user'))
def _now(value=None):
    ts=pd.Timestamp(value or datetime.now(timezone.utc))
    if ts.tzinfo is None: ts=ts.tz_localize('UTC')
    return ts.tz_convert('UTC')
def _finite(value):
    try:
        value=float(value); return value if math.isfinite(value) else None
    except Exception: return None
def _db_value(value):
    """Convert pandas/numpy scalars and missing values for psycopg2."""
    if value is None: return None
    if isinstance(value,np.generic): value=value.item()
    try:
        if pd.isna(value): return None
    except Exception:
        pass
    return value
def _read(path):
    if not path.exists(): return []
    try:
        value=json.loads(path.read_text(encoding='utf-8')); return value if isinstance(value,list) else []
    except Exception: return []
def _write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(rows,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
def _decisions_path(uid): return DATA_DIR/f'{_safe(uid)}_decisions.json'
def _outcomes_path(uid): return DATA_DIR/f'{_safe(uid)}_outcomes.json'
def _key(*parts): return hashlib.sha256('|'.join(str(x) for x in parts).encode('utf-8')).hexdigest()[:28]


def _payload_rows(df):
    rows=[]
    for _,row in df.iterrows():
        try: rows.append(json.loads(row['payload_json']))
        except Exception: pass
    return rows


def load_shadow_decisions(user_id):
    uid=str(user_id or 'local-user')
    if cloud_available():
        ensure_production_schema()
        df=query_sql('''SELECT payload_json FROM user_shadow_decisions
                        WHERE user_id=:uid ORDER BY decision_at''',{'uid':uid})
        if not df.empty: return _payload_rows(df)
    return _read(_decisions_path(uid))


def load_shadow_outcomes(user_id):
    uid=str(user_id or 'local-user')
    if cloud_available():
        ensure_production_schema()
        df=query_sql('''SELECT payload_json FROM user_shadow_outcomes
                        WHERE user_id=:uid ORDER BY evaluated_at''',{'uid':uid})
        if not df.empty: return _payload_rows(df)
    return _read(_outcomes_path(uid))


def _last_observation(history):
    if history is None or not isinstance(history,pd.DataFrame) or history.empty or 'Close' not in history: return None,None
    close=pd.to_numeric(history['Close'],errors='coerce').dropna()
    if close.empty: return None,None
    return _finite(close.iloc[-1]),str(close.index[-1])


def _observation_status(price,observed_at,max_age_hours=36):
    if price is None: return 'UNAVAILABLE'
    if not observed_at: return 'NOT_CHECKED'
    try:
        ts=pd.Timestamp(observed_at)
        if ts.tzinfo is None: ts=ts.tz_localize('UTC')
        age=max(0,(_now()-ts.tz_convert('UTC')).total_seconds()/3600)
        return 'CURRENT' if age<=max_age_hours else 'STALE'
    except Exception: return 'NOT_CHECKED'


def _event_observation(events,ticker):
    candidates=[]
    for event in events or []:
        if str(event.get('ticker','')).upper()!=ticker: continue
        metrics=event.get('metrics') or {}; price=_finite(metrics.get('price'))
        if price is not None: candidates.append((price,metrics.get('observed_at')))
    return candidates[-1] if candidates else (None,None)


def _decision_candidates(brief):
    candidates=[]
    for row in brief.get('decisions_needed') or []:
        state=str(row.get('state','')).upper(); verification=str(row.get('verification_status','')).upper()
        ticker=str(row.get('subject','')).upper().strip()
        if state not in DIRECTION_BY_STATE or verification not in ACCEPTED_VERIFICATION or ticker in {'','MARKET','PORTFOLIO'}: continue
        candidates.append({
            'ticker':ticker,'source_agent':str(row.get('agent') or 'Unknown'),'signal_state':state,
            'expected_direction':DIRECTION_BY_STATE[state],'confidence':_finite(row.get('confidence')),
            'raw_confidence':_finite(row.get('raw_confidence',row.get('confidence'))),
            'confidence_multiplier':_finite(row.get('confidence_multiplier')) or 1.0,
            'verification_status':verification,'summary':str(row.get('summary') or ''),'skill_version':str(row.get('skill_version') or ''),
        })
    for row in (brief.get('top_opportunities') or [])[:3]:
        score=_finite(row.get('Priority Score')); ticker=str(row.get('Ticker','')).upper().strip()
        if ticker and score is not None and score>=75:
            candidates.append({
                'ticker':ticker,'source_agent':'CIO Watchlist','signal_state':'CIO_PRIORITY','expected_direction':'POSITIVE',
                'confidence':min(score/100,1),'verification_status':'VERIFIED',
                'raw_confidence':min(score/100,1),'confidence_multiplier':1.0,
                'summary':f'{ticker} reached CIO watchlist priority {score:.1f}.','skill_version':'1.1',
            })
    return candidates


def capture_shadow_decisions(user_id,run_key,brief,price_histories=None,observed_at=None):
    """Persist eligible automated decisions exactly once per run/agent/state."""
    uid=str(user_id or 'local-user'); run_key=str(run_key or '')
    if not run_key: return {'status':'NOT_CHECKED','created':[],'skipped':0,'reason':'run_key required'}
    histories=price_histories or {}; existing=load_shadow_decisions(uid); existing_keys={str(r.get('decision_key')) for r in existing}
    benchmark,benchmark_at=_last_observation(histories.get('SPY')); created=[]; skipped=0; failures=[]
    for candidate in _decision_candidates(brief or {}):
        ticker=candidate['ticker']; decision_key=_key(uid,run_key,ticker,candidate['source_agent'],candidate['signal_state'])
        if decision_key in existing_keys: skipped+=1; continue
        price,event_at=_event_observation((brief or {}).get('events_considered'),ticker)
        history_price,history_at=_last_observation(histories.get(ticker))
        price=price if price is not None else history_price
        decision_at=str(event_at or observed_at or history_at or _now().isoformat())
        baseline_at=event_at or history_at
        row={
            'user_id':uid,'decision_key':decision_key,'run_key':run_key,'created_at':_now().isoformat(),
            'decision_at':decision_at,'ticker':ticker,**candidate,
            'baseline_price':price,'benchmark_price':benchmark,
            'baseline_observed_at':baseline_at,'benchmark_observed_at':benchmark_at,
            'baseline_status':_observation_status(price,baseline_at),
            'benchmark_status':_observation_status(benchmark,benchmark_at),'shadow_mode':True,
            'approval_boundary':'Observation only. No order, position, fill, or broker action is created.',
        }
        created.append(row); existing.append(row); existing_keys.add(decision_key)
        if cloud_available():
            ensure_production_schema()
            ok,msg=execute_sql('''INSERT INTO user_shadow_decisions(
                user_id,decision_key,run_key,created_at,decision_at,ticker,source_agent,signal_state,
                expected_direction,confidence,verification_status,baseline_price,benchmark_price,
                baseline_status,skill_version,payload_json)
                VALUES (:user_id,:decision_key,:run_key,:created_at,:decision_at,:ticker,:source_agent,:signal_state,
                        :expected_direction,:confidence,:verification_status,:baseline_price,:benchmark_price,
                        :baseline_status,:skill_version,:payload_json)
                ON CONFLICT (user_id,decision_key) DO NOTHING''',
                {**{k:row.get(k) for k in ('user_id','decision_key','run_key','created_at','decision_at','ticker','source_agent','signal_state',
                                            'expected_direction','confidence','verification_status','baseline_price','benchmark_price','baseline_status','skill_version')},
                 'payload_json':json.dumps(row,ensure_ascii=False,default=str)})
            if not ok: failures.append({'decision_key':decision_key,'error':msg})
    _write(_decisions_path(uid),existing)
    return {'status':'FAILED' if failures else 'CURRENT','created':created,'skipped':skipped,
            'total_candidates':len(created)+skipped,'failures':failures}


def _close_series(history):
    if history is None or not isinstance(history,pd.DataFrame) or history.empty or 'Close' not in history: return pd.Series(dtype=float)
    s=pd.to_numeric(history['Close'],errors='coerce').dropna().copy()
    try:
        idx=pd.DatetimeIndex(s.index)
        if idx.tz is not None: idx=idx.tz_convert('UTC').tz_localize(None)
        s.index=idx.normalize()
    except Exception: return pd.Series(dtype=float)
    return s[~s.index.duplicated(keep='last')].sort_index()


def evaluate_decisions(decisions,price_histories,horizons=HORIZONS,evaluated_at=None):
    """Pure fixed-horizon evaluation. Missing bars remain PENDING/UNAVAILABLE."""
    evaluated=_now(evaluated_at).isoformat(); spy=_close_series((price_histories or {}).get('SPY')); outcomes=[]
    for decision in decisions or []:
        ticker=str(decision.get('ticker','')).upper(); direction=1 if decision.get('expected_direction')=='POSITIVE' else -1
        baseline=_finite(decision.get('baseline_price')); benchmark=_finite(decision.get('benchmark_price'))
        try:
            decision_day=pd.Timestamp(decision.get('decision_at'))
            if decision_day.tzinfo is not None: decision_day=decision_day.tz_convert('America/New_York').tz_localize(None)
            decision_day=decision_day.normalize()
        except Exception: decision_day=None
        prices=_close_series((price_histories or {}).get(ticker))
        future=prices[prices.index>decision_day] if decision_day is not None else pd.Series(dtype=float)
        future_spy=spy[spy.index>decision_day] if decision_day is not None else pd.Series(dtype=float)
        for horizon in horizons:
            row={'user_id':decision.get('user_id'),'decision_key':decision.get('decision_key'),'ticker':ticker,
                 'source_agent':decision.get('source_agent'),'signal_state':decision.get('signal_state'),
                 'expected_direction':decision.get('expected_direction'),'confidence':decision.get('confidence'),
                 'horizon_days':int(horizon),'evaluated_at':evaluated,'status':'PENDING','outcome_at':None,
                 'asset_return_pct':None,'benchmark_return_pct':None,'alpha_pct':None,'signed_return_pct':None,
                 'signed_alpha_pct':None,'mfe_pct':None,'mae_pct':None,'success':None,'source':'Yahoo Finance daily bars'}
            baseline_status=str(decision.get('baseline_status') or ('CURRENT' if baseline is not None else 'UNAVAILABLE'))
            if baseline_status!='CURRENT':
                row['status']=baseline_status; outcomes.append(row); continue
            if baseline is None or decision_day is None:
                row['status']='UNAVAILABLE'; outcomes.append(row); continue
            if len(future)<horizon:
                outcomes.append(row); continue
            window=future.iloc[:horizon]; asset_return=(float(window.iloc[-1])/baseline-1)*100
            path=(window/baseline-1)*100*direction
            benchmark_return=None
            if benchmark is not None and len(future_spy)>=horizon:
                benchmark_return=(float(future_spy.iloc[horizon-1])/benchmark-1)*100
            alpha=None if benchmark_return is None else asset_return-benchmark_return
            signed_alpha=None if alpha is None else alpha*direction
            row.update({'status':'MATURED','outcome_at':str(window.index[-1]),'asset_return_pct':round(asset_return,4),
                        'benchmark_return_pct':None if benchmark_return is None else round(benchmark_return,4),
                        'alpha_pct':None if alpha is None else round(alpha,4),'signed_return_pct':round(asset_return*direction,4),
                        'signed_alpha_pct':None if signed_alpha is None else round(signed_alpha,4),
                        'mfe_pct':round(float(path.max()),4),'mae_pct':round(float(path.min()),4),
                        'success':bool(asset_return*direction>0)})
            outcomes.append(row)
    return outcomes


def persist_shadow_outcomes(user_id,outcomes):
    uid=str(user_id or 'local-user'); existing=load_shadow_outcomes(uid)
    keyed={(str(r.get('decision_key')),int(r.get('horizon_days') or 0)):r for r in existing}
    failures=[]
    for row in outcomes or []:
        clean={**row,'user_id':uid}; key=(str(clean.get('decision_key')),int(clean.get('horizon_days') or 0)); keyed[key]=clean
        if cloud_available():
            ensure_production_schema()
            params={k:_db_value(clean.get(k)) for k in ('user_id','decision_key','horizon_days','evaluated_at','status','outcome_at','asset_return_pct',
                                                         'benchmark_return_pct','alpha_pct','signed_return_pct','signed_alpha_pct','mfe_pct','mae_pct','success','source')}
            params['horizon_days']=int(params['horizon_days'] or 0)
            if params.get('success') is not None: params['success']=bool(params['success'])
            params['payload_json']=json.dumps(clean,ensure_ascii=False,default=str)
            ok,msg=execute_sql('''INSERT INTO user_shadow_outcomes(
                user_id,decision_key,horizon_days,evaluated_at,status,outcome_at,asset_return_pct,benchmark_return_pct,
                alpha_pct,signed_return_pct,signed_alpha_pct,mfe_pct,mae_pct,success,source,payload_json)
                VALUES (:user_id,:decision_key,:horizon_days,:evaluated_at,:status,:outcome_at,:asset_return_pct,:benchmark_return_pct,
                        :alpha_pct,:signed_return_pct,:signed_alpha_pct,:mfe_pct,:mae_pct,:success,:source,:payload_json)
                ON CONFLICT (user_id,decision_key,horizon_days) DO UPDATE SET evaluated_at=EXCLUDED.evaluated_at,
                    status=EXCLUDED.status,outcome_at=EXCLUDED.outcome_at,asset_return_pct=EXCLUDED.asset_return_pct,
                    benchmark_return_pct=EXCLUDED.benchmark_return_pct,alpha_pct=EXCLUDED.alpha_pct,
                    signed_return_pct=EXCLUDED.signed_return_pct,signed_alpha_pct=EXCLUDED.signed_alpha_pct,
                    mfe_pct=EXCLUDED.mfe_pct,mae_pct=EXCLUDED.mae_pct,success=EXCLUDED.success,
                    source=EXCLUDED.source,payload_json=EXCLUDED.payload_json''',params)
            if not ok: failures.append({'decision_key':key[0],'horizon':key[1],'error':msg})
    rows=list(keyed.values()); rows.sort(key=lambda r:(str(r.get('evaluated_at','')),str(r.get('decision_key','')),int(r.get('horizon_days') or 0)))
    _write(_outcomes_path(uid),rows)
    return {'status':'FAILED' if failures else 'CURRENT','saved':len(outcomes or []),'failures':failures}


def shadow_validation_summary(decisions,outcomes,min_reliable_sample=MIN_RELIABLE_SAMPLE):
    decisions=list(decisions or []); outcomes=list(outcomes or [])
    matured=[r for r in outcomes if r.get('status')=='MATURED']
    pending=[r for r in outcomes if r.get('status')=='PENDING']
    recorded={(str(r.get('decision_key')),int(r.get('horizon_days') or 0)) for r in outcomes}
    expected={(str(d.get('decision_key')),horizon) for d in decisions for horizon in HORIZONS if d.get('decision_key')}
    unevaluated=len(expected-recorded)
    horizons=[]
    for horizon in HORIZONS:
        rows=[r for r in matured if int(r.get('horizon_days') or 0)==horizon]
        signed=[_finite(r.get('signed_return_pct')) for r in rows]; signed=[x for x in signed if x is not None]
        alpha=[_finite(r.get('signed_alpha_pct')) for r in rows]; alpha=[x for x in alpha if x is not None]
        successes=[bool(r.get('success')) for r in rows if r.get('success') is not None]
        brier=[]
        for r in rows:
            confidence=_finite(r.get('confidence'))
            if confidence is not None and r.get('success') is not None: brier.append((confidence-float(bool(r.get('success'))))**2)
        horizons.append({
            'Horizon':f'{horizon}d','Status':'CURRENT' if len(rows)>=min_reliable_sample else 'NOT_ENOUGH_DATA',
            'Sample':len(rows),'Hit Rate %':None if not successes else round(sum(successes)/len(successes)*100,1),
            'Mean Directional Return %':None if not signed else round(sum(signed)/len(signed),2),
            'Mean Directional Alpha %':None if not alpha else round(sum(alpha)/len(alpha),2),
            'Brier Score':None if not brier else round(sum(brier)/len(brier),3),
        })
    status='NO_DECISIONS' if not decisions else 'CURRENT' if any(r['Status']=='CURRENT' for r in horizons) else 'NOT_ENOUGH_DATA'
    return {'status':status,'decisions':len(decisions),'matured_outcomes':len(matured),
            'pending_outcomes':len(pending)+unevaluated,'unevaluated_outcomes':unevaluated,
            'minimum_reliable_sample':int(min_reliable_sample),'horizons':horizons,
            'note':'Metrics are descriptive until the minimum sample is reached; no trading conclusion is asserted.'}
