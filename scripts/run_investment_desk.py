"""Scheduled Investment Desk worker. Shadow mode only; no broker/execution code."""
from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import pandas as pd
from core.storage import load_positions,load_latest_snapshot,load_json_snapshot
from core.event_detector import detect_snapshot_events,detect_market_context_events,market_context
from core.intraday_monitor import select_monitor_tickers,build_intraday_overlay
from core.event_state import filter_actionable_events,record_event_state
from core.agent_router import route_events
from core.desk_runner import run_desk_review
from core.desk_store import load_latest_desk_output,load_desk_output,save_desk_output
from core.desk_notifications import notify_material_brief
from core.agent_audit import append_agent_audit

ROOT=Path(__file__).resolve().parents[1]

def _previous_snapshot():
    files=sorted((ROOT/'data'/'snapshots').glob('history_scores_*.parquet'))
    if len(files)<2: return pd.DataFrame()
    try: return pd.read_parquet(files[-2])
    except Exception: return pd.DataFrame()

def _run_key(events):
    raw='|'.join(sorted(str(e.get('fingerprint') or '') for e in events))
    return 'events-'+hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]

def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    now=datetime.now(ZoneInfo('America/New_York'))
    if now.weekday()>=5:
        print('Desk skipped: weekend'); return 0
    minutes=now.hour*60+now.minute
    if not (9*60+30 <= minutes <= 16*60):
        print('Desk skipped: outside US cash session'); return 0
    pos=load_positions(user_id=uid); holdings=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
    latest=load_latest_snapshot('latest_screener')
    macro=load_json_snapshot('latest_macro'); meta=load_json_snapshot('latest_meta')
    previous_scan=load_latest_desk_output(uid,'event_scan') or {}
    previous_context=((previous_scan.get('payload') or {}).get('market_context') or {})
    monitor_tickers=select_monitor_tickers(latest,holdings,max_symbols=25)
    live_overlay,live_monitor=build_intraday_overlay(latest,monitor_tickers)
    detected=detect_snapshot_events(latest,_previous_snapshot(),holdings,max_events=8)
    if live_monitor.get('status')=='CURRENT':
        detected+=detect_snapshot_events(live_overlay,latest,holdings,max_events=12)
    detected+=detect_market_context_events(macro,meta,previous_context)
    events,suppressed=filter_actionable_events(uid,detected,cooldown_minutes=240,now=now)
    scan_payload={'shadow_mode':True,'detected_events':detected,'actionable_events':events,'suppressed_events':suppressed,
                  'market_context':market_context(macro,meta),'market_time':now.isoformat()}
    scan_payload['live_monitor']=live_monitor
    save_desk_output(uid,'event_scan',scan_payload,run_key=now.strftime('%Y%m%d-%H%M'))
    append_agent_audit(uid,'cheap_event_scan',scan_payload)
    # Cheap scans run often; specialists wake only for a new, non-cooled-down event.
    if not events:
        print(f'Desk scan: no new material event | suppressed={len(suppressed)}'); return 0
    plan=route_events(events); tickers=list(plan.get('ticker_agents') or {})[:25]; run_key=_run_key(events)
    previous=load_desk_output(uid,'scheduled_review',run_key)
    if previous and previous.get('payload'):
        out=previous['payload']; print('Desk review reused: idempotent run key')
    else:
        out=run_desk_review(uid,tickers,force_fundamental=False,output_type='scheduled_review',
                            agent_plan=plan,events=events,run_key=run_key)
    notification=notify_material_brief(uid,out['brief'],run_key)
    # A failed delivery must remain retriable. The completed desk review is reused
    # through run_key, so the retry does not spend provider quota again.
    state_result=({'status':'DEFERRED_FOR_NOTIFICATION_RETRY','recorded':0,'failures':[]}
                  if notification.get('status')=='FAILED' else record_event_state(uid,events,now=now))
    append_agent_audit(uid,'material_alert_decision',{'run_key':run_key,'brief_material':out['brief'].get('material'),
                       'notification':notification,'event_state':state_result,'shadow_mode':True})
    print(out['brief']['headline']); print('reviewed:',','.join(tickers) or 'MARKET')
    print(f"notification={notification.get('status')} event_state={state_result.get('status')}")
    return 0 if state_result.get('status')!='FAILED' else 1

if __name__=='__main__': raise SystemExit(main())
