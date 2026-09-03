"""Post-close broad opportunity hunt. Research only; no execution path."""
from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd

from core.agent_audit import append_agent_audit
from core.desk_notifications import notify_material_brief
from core.desk_runner import run_desk_review
from core.desk_store import load_desk_output,save_desk_output
from core.opportunity_discovery import discover_daily_candidates,qualify_verified_opportunities
from core.storage import load_json_snapshot,load_latest_snapshot,load_positions


def snapshot_age_hours(meta,now=None):
    generated=(meta or {}).get('generated_at')
    if not generated: return None
    try:
        ts=pd.Timestamp(generated)
        if ts.tzinfo is None: ts=ts.tz_localize('UTC')
        current=pd.Timestamp(now or datetime.now(timezone.utc))
        if current.tzinfo is None: current=current.tz_localize('UTC')
        return max(0,(current.tz_convert('UTC')-ts.tz_convert('UTC')).total_seconds()/3600)
    except Exception:
        return None


def opportunity_run_key(now,snapshot_meta):
    """Remain idempotent for one snapshot while allowing a same-day refresh."""
    generated=str((snapshot_meta or {}).get('generated_at') or 'missing-snapshot')
    fingerprint=hashlib.sha256(generated.encode('utf-8')).hexdigest()[:12]
    return f'hunt-{now.date().isoformat()}-{fingerprint}'


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    now=datetime.now(ZoneInfo('America/New_York'))
    snapshot=load_latest_snapshot('latest_screener'); meta=load_json_snapshot('latest_meta')
    run_key=opportunity_run_key(now,meta)
    previous=load_desk_output(uid,'daily_opportunity_hunt',run_key)
    if previous and (previous.get('payload') or {}).get('discovery'):
        payload=previous['payload']; notification=notify_material_brief(uid,payload.get('brief') or {},run_key)
        print(f"Opportunity hunt reused | notification={notification.get('status')}")
        return 1 if notification.get('status')=='FAILED' else 0

    age=snapshot_age_hours(meta)
    if snapshot is None or snapshot.empty or age is None or age>36:
        payload={'shadow_mode':True,'status':'BLOCKED_STALE_OR_MISSING_SNAPSHOT','brief':{
            'headline':'Opportunity hunt blocked: current broad snapshot unavailable','material':False,
            'material_reasons':[],'top_opportunities':[],
            'approval_boundary':'Research only. No order was created.'},
            'discovery':{'status':'BLOCKED_STALE_OR_MISSING_SNAPSHOT','snapshot_age_hours':age,
                         'universe_rows':0 if snapshot is None else len(snapshot),
                         'verified_opportunities':[],'monitor_tickers':[]}}
        save_desk_output(uid,'daily_opportunity_hunt',payload,run_key=run_key)
        append_agent_audit(uid,'daily_opportunity_hunt_blocked',payload['discovery'])
        print(payload['brief']['headline']); return 1

    positions=load_positions(user_id=uid)
    holdings=[] if positions.empty else positions['ticker'].dropna().astype(str).str.upper().tolist()
    discovery=discover_daily_candidates(snapshot,holdings,max_candidates=18,max_per_sector=3,minimum_score=60)
    shortlist=discovery.get('candidates') or []
    tickers=[row['Ticker'] for row in shortlist]
    candidate_sectors={str(row['Ticker']).upper():str(row.get('Sector') or 'Unknown') for row in shortlist}
    if not tickers:
        payload={'shadow_mode':True,'status':'NO_QUALIFIED_CANDIDATES','tickers':[],'watchlist':[],
                 'brief':{'headline':'No candidate passed today’s evidence gates','material':False,
                          'material_reasons':[],'top_opportunities':[],
                          'approval_boundary':'Research only. No order was created.'},
                 'discovery':{**discovery,'snapshot_age_hours':round(age,1),
                              'verified_opportunities':[],'monitor_tickers':[]}}
        save_desk_output(uid,'daily_opportunity_hunt',payload,run_key=run_key)
        append_agent_audit(uid,'daily_opportunity_hunt',payload['discovery'])
        print(payload['brief']['headline']); return 0

    payload=run_desk_review(uid,tickers,force_fundamental=False,output_type='daily_opportunity_hunt',
                            run_key=run_key,candidate_sectors=candidate_sectors)
    verified=qualify_verified_opportunities(payload.get('watchlist') or [],shortlist,minimum_priority=60)
    ranked=[str(row.get('Ticker')).upper() for row in payload.get('watchlist') or [] if row.get('Ticker')]
    monitor=list(dict.fromkeys(ranked+tickers))[:30]
    payload['status']='VERIFIED_OPPORTUNITIES' if verified else 'WATCHLIST_ONLY'
    payload['discovery']={**discovery,'snapshot_age_hours':round(age,1),
                          'verified_opportunities':verified,'monitor_tickers':monitor}
    brief=payload.get('brief') or {}
    brief['top_opportunities']=verified[:5]
    brief['discovery_status']=payload['status']
    brief['discovery_universe_rows']=discovery.get('universe_rows',0)
    if verified:
        brief['headline']=f"{len(verified)} verified opportunity candidate(s) from {discovery.get('universe_rows',0)} screened equities"
    else:
        brief['headline']=f"No fully verified opportunity; {len(tickers)} candidates remain on watch"
    payload['brief']=brief
    save_desk_output(uid,'daily_opportunity_hunt',payload,run_key=run_key)
    append_agent_audit(uid,'daily_opportunity_hunt',{
        'run_key':run_key,'universe_rows':discovery.get('universe_rows',0),'shortlist':tickers,
        'verified':[row['Ticker'] for row in verified],'monitor_tickers':monitor,
        'shadow_mode':True,'no_execution':True,
    })
    notification=notify_material_brief(uid,brief,run_key)
    print(brief['headline']); print('monitor:',','.join(monitor)); print(f"notification={notification.get('status')}")
    return 1 if notification.get('status')=='FAILED' else 0


if __name__=='__main__': raise SystemExit(main())
