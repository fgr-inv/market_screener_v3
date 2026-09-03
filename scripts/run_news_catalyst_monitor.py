"""Scheduled portfolio/watchlist news monitor. Research-only Shadow Mode."""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.agent_router import route_events
from core.desk_notifications import notify_material_brief
from core.desk_runner import run_desk_review
from core.desk_store import load_desk_output, save_desk_output
from core.event_state import filter_actionable_events, record_event_state
from core.news_catalyst_agent import catalyst_story_event, classify_catalyst_stories
from core.news_catalyst_data import collect_catalyst_stories
from core.opportunity_discovery import load_active_watchlist_tickers
from core.storage import load_positions, load_theses


def news_run_key(now):
    return f"news-{now.strftime('%Y-%m-%d-%H')}"


def should_fetch_sec(now,manual=False):
    return bool(manual or now.hour in {7,16})


def story_lookback_hours(now):
    """Bridge the weekend on Monday's first scans without extra weekend jobs."""
    return 84 if now.weekday()==0 and now.hour<=8 else 36


def _thesis_map(user_id):
    frame=load_theses(user_id=user_id)
    return {} if frame.empty else {str(row['ticker']).upper():row.to_dict() for _,row in frame.iterrows()}


def _story_groups(events):
    grouped={}
    for event in events or []:
        ticker=str(event.get('ticker','')).upper(); story=((event.get('metrics') or {}).get('story') or {})
        if ticker and story: grouped.setdefault(ticker,[]).append(story)
    return grouped


def _scan_id(events):
    raw='|'.join(sorted(str(event.get('fingerprint') or '') for event in events))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    now=datetime.now(ZoneInfo('America/New_York')); run_key=news_run_key(now)
    previous=load_desk_output(uid,'news_catalyst_scan',run_key)
    if previous and previous.get('payload'):
        payload=previous['payload']; brief=payload.get('brief') or {}
        notification=notify_material_brief(uid,brief,payload.get('review_run_key') or run_key)
        if notification.get('status')!='FAILED' and payload.get('actionable_events'):
            record_event_state(uid,payload['actionable_events'],now=now)
        print(f"News scan reused | notification={notification.get('status')}")
        return 1 if notification.get('status')=='FAILED' else 0

    positions=load_positions(user_id=uid)
    holdings=[] if positions.empty else positions['ticker'].dropna().astype(str).str.upper().tolist()
    watchlist=load_active_watchlist_tickers(uid,limit=30)
    tickers=list(dict.fromkeys(holdings+watchlist))[:40]
    if not tickers:
        print('News scan skipped: no portfolio or active watchlist tickers'); return 0

    manual=os.getenv('GITHUB_EVENT_NAME','').lower()=='workflow_dispatch'
    stories,provider_status=collect_catalyst_stories(
        tickers,include_sec=should_fetch_sec(now,manual),lookback_hours=story_lookback_hours(now))
    classified=classify_catalyst_stories(stories,holdings,_thesis_map(uid))
    detected=[catalyst_story_event(row) for row in classified
              if row.get('category')!='GENERAL' and (int(row.get('severity') or 0)>=4 or row.get('portfolio'))]
    actionable,suppressed=filter_actionable_events(uid,detected,cooldown_minutes=0,now=now)
    material_events=[event for event in actionable if int(event.get('severity') or 0)>=4]
    payload={'shadow_mode':True,'status':'NO_NEW_MATERIAL_CATALYST','market_time':now.isoformat(),
             'monitored_tickers':tickers,'portfolio_tickers':holdings,'watchlist_tickers':watchlist,
             'provider_status':provider_status,'stories':classified[:120],'detected_events':detected,
             'actionable_events':actionable,'material_events':material_events,
             'suppressed_events':suppressed,'brief':{'headline':'No new material catalyst',
             'material':False,'material_reasons':[],'approval_boundary':'Research only. No order was created.'}}

    notification={'status':'NOT_MATERIAL','delivered':False,'attempted':False}
    state_result={'status':'CURRENT','recorded':0,'failures':[]}
    if actionable:
        groups=_story_groups(actionable); plan=route_events(actionable); review_key='news-events-'+_scan_id(actionable)
        reviewed=run_desk_review(uid,list(groups),force_fundamental=False,output_type='news_catalyst_review',
                                 agent_plan=plan,events=actionable,run_key=review_key,news_by_ticker=groups)
        payload.update({'status':'MATERIAL_CATALYST_REVIEW' if material_events else 'CATALYST_REVIEW',
                        'brief':reviewed.get('brief') or payload['brief'],
                        'review':reviewed,'review_run_key':review_key})
        notification=notify_material_brief(uid,payload['brief'],review_key)
        if notification.get('status')=='FAILED':
            state_result={'status':'DEFERRED_FOR_NOTIFICATION_RETRY','recorded':0,'failures':[]}
        else:
            state_result=record_event_state(uid,actionable,now=now)
    payload['notification']=notification; payload['event_state']=state_result
    save_desk_output(uid,'news_catalyst_scan',payload,run_key=run_key)
    append_agent_audit(uid,'news_catalyst_scan',{'run_key':run_key,'monitored':len(tickers),'stories':len(classified),
                       'detected':len(detected),'actionable':len(actionable),'material':len(material_events),
                       'suppressed':len(suppressed),
                       'providers':provider_status.get('providers',[]),'notification':notification,'shadow_mode':True})
    print(f"News scan: stories={len(classified)} detected={len(detected)} actionable={len(actionable)} "
          f"notification={notification.get('status')}")
    return 1 if notification.get('status')=='FAILED' or state_result.get('status')=='FAILED' else 0


if __name__=='__main__': raise SystemExit(main())
