"""Persistent deduplication and cooldown state for background desk events."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd
from core.production_storage import cloud_available,ensure_production_schema,execute_sql,query_sql

ROOT=Path(__file__).resolve().parents[1]
STATE_DIR=ROOT/'data'/'agent_event_state'; STATE_DIR.mkdir(parents=True,exist_ok=True)


def _safe(value): return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in str(value or 'local-user'))
def _now(value=None):
    ts=pd.Timestamp(value or datetime.now(timezone.utc))
    if ts.tzinfo is None: ts=ts.tz_localize('UTC')
    return ts.tz_convert('UTC')
def _path(user_id): return STATE_DIR/f'{_safe(user_id)}.json'


def _load_local(user_id):
    p=_path(user_id)
    if not p.exists(): return {}
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return {}


def load_event_state(user_id):
    uid=str(user_id or 'local-user')
    if cloud_available():
        ensure_production_schema()
        df=query_sql('''SELECT event_key,fingerprint,last_triggered_at FROM user_agent_event_state
                        WHERE user_id=:uid''',{'uid':uid})
        if not df.empty:
            return {str(r['event_key']):{'fingerprint':str(r['fingerprint']),'last_triggered_at':str(r['last_triggered_at'])} for _,r in df.iterrows()}
    return _load_local(uid)


def filter_actionable_events(user_id,events,cooldown_minutes=240,now=None):
    """Return new events plus explicit reasons for every suppressed event."""
    state=load_event_state(user_id); current=_now(now); actionable=[]; suppressed=[]; seen=set()
    for event in events or []:
        key=str(event.get('event_key') or event.get('ticker') or 'UNKNOWN')
        fingerprint=str(event.get('fingerprint') or '')
        batch_identity=(key,fingerprint)
        if batch_identity in seen:
            suppressed.append({'event':event,'reason':'DUPLICATE_IN_SCAN'}); continue
        seen.add(batch_identity)
        prior=state.get(key) or {}
        if fingerprint and fingerprint==str(prior.get('fingerprint') or ''):
            suppressed.append({'event':event,'reason':'DUPLICATE'}); continue
        last=prior.get('last_triggered_at')
        if last:
            try:
                elapsed=(current-_now(last)).total_seconds()/60
                if elapsed<max(float(cooldown_minutes or 0),0):
                    suppressed.append({'event':event,'reason':'COOLDOWN','minutes_remaining':round(cooldown_minutes-elapsed,1)}); continue
            except Exception:
                pass
        actionable.append(event)
    return actionable,suppressed


def record_event_state(user_id,events,now=None):
    uid=str(user_id or 'local-user'); ts=_now(now).isoformat(); local=_load_local(uid); failures=[]
    for event in events or []:
        key=str(event.get('event_key') or event.get('ticker') or 'UNKNOWN')
        fingerprint=str(event.get('fingerprint') or '')
        local[key]={'fingerprint':fingerprint,'last_triggered_at':ts}
        if cloud_available():
            ensure_production_schema()
            ok,msg=execute_sql('''INSERT INTO user_agent_event_state(user_id,event_key,fingerprint,last_triggered_at,updated_at)
                VALUES (:uid,:key,:fingerprint,:ts,:ts)
                ON CONFLICT (user_id,event_key) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,
                    last_triggered_at=EXCLUDED.last_triggered_at,updated_at=EXCLUDED.updated_at''',
                {'uid':uid,'key':key,'fingerprint':fingerprint,'ts':ts})
            if not ok: failures.append({'event_key':key,'error':msg})
    p=_path(uid); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(local,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'status':'FAILED' if failures else 'CURRENT','recorded':len(events or []),'failures':failures}
