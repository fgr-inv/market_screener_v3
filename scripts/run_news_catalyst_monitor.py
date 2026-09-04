"""Scheduled portfolio/watchlist news monitor. Research-only Shadow Mode."""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import record_automation_heartbeat
from core.agent_router import route_events
from core.desk_notifications import notify_material_brief
from core.desk_runner import run_desk_review
from core.desk_store import load_desk_output, save_desk_output
from core.event_state import filter_actionable_events, record_event_state
from core.news_catalyst_agent import catalyst_story_event, classify_catalyst_stories
from core.news_catalyst_data import collect_catalyst_stories
from core.opportunity_discovery import load_active_watchlist_tickers
from core.storage import load_positions, load_theses
from core.config import CRYPTO_RESEARCH_WATCHLIST


def news_scan_mode(value=None):
    return 'priority' if str(value if value is not None else os.getenv('NEWS_SCAN_MODE','full')).lower()=='priority' else 'full'


def news_run_key(now,scan_mode='full'):
    mode=news_scan_mode(scan_mode)
    if mode=='priority':
        minute=30 if now.minute>=30 else 0
        return f"news-priority-{now.strftime('%Y-%m-%d-%H')}-{minute:02d}"
    return f"news-{now.strftime('%Y-%m-%d-%H')}"


def select_news_tickers(holdings,watchlist,scan_mode='full',limit=40):
    primary=list(dict.fromkeys(str(t).upper() for t in (holdings or []) if str(t).strip()))
    secondary=list(dict.fromkeys(str(t).upper() for t in (watchlist or []) if str(t).strip()))
    return (primary if news_scan_mode(scan_mode)=='priority' else list(dict.fromkeys(primary+secondary)))[:int(limit)]


def news_watchlist_tickers(saved_watchlist):
    """Keep the core crypto research list in the hourly full-news monitor."""
    saved=[str(t).upper() for t in (saved_watchlist or []) if str(t).strip()]
    return list(dict.fromkeys(saved+CRYPTO_RESEARCH_WATCHLIST))


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


def _provider_failures(provider_status):
    return sum(len(row.get('failures') or []) for row in (provider_status or {}).get('providers') or [])


def _record_news_heartbeats(user_id,scan_mode,status,details,now):
    processes=['portfolio_news'] if news_scan_mode(scan_mode)=='priority' else ['portfolio_news','watchlist_news']
    records=[record_automation_heartbeat(user_id,process,status=status,details=details,now=now)
             for process in processes]
    failures=[record for record in records
              if ((record or {}).get('persistence') or {}).get('status')=='FAILED']
    return {'status':'FAILED' if failures else status,'records':records,'failures':len(failures)}


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    now=datetime.now(ZoneInfo('America/New_York')); scan_mode=news_scan_mode(); run_key=news_run_key(now,scan_mode)
    output_type='news_catalyst_priority_scan' if scan_mode=='priority' else 'news_catalyst_scan'
    previous=load_desk_output(uid,output_type,run_key)
    if previous and previous.get('payload'):
        payload=previous['payload']; brief=payload.get('brief') or {}
        notification=notify_material_brief(uid,brief,payload.get('review_run_key') or run_key)
        if notification.get('status')!='FAILED' and payload.get('actionable_events'):
            record_event_state(uid,payload['actionable_events'],now=now)
        heartbeat=_record_news_heartbeats(uid,scan_mode,'REUSED',{'run_key':run_key},now)
        print(f"News scan reused | notification={notification.get('status')} heartbeat={heartbeat['status']}")
        return 1 if notification.get('status')=='FAILED' or heartbeat['status']=='FAILED' else 0

    positions=load_positions(user_id=uid)
    holdings=[] if positions.empty else positions['ticker'].dropna().astype(str).str.upper().tolist()
    watchlist=news_watchlist_tickers(load_active_watchlist_tickers(uid,limit=30))
    tickers=select_news_tickers(holdings,watchlist,scan_mode,limit=40)
    if not tickers:
        payload={'shadow_mode':True,'status':'SKIPPED_NO_TICKERS','scan_mode':scan_mode,
                 'market_time':now.isoformat(),'monitored_tickers':[],
                 'portfolio_tickers':holdings,'watchlist_tickers':watchlist,
                 'provider_status':{'providers':[]},'stories':[],'detected_events':[],
                 'actionable_events':[],'material_events':[],'suppressed_events':[],
                 'brief':{'headline':'No portfolio or active watchlist tickers','material':False,
                          'material_reasons':[],'approval_boundary':'Research only. No order was created.'}}
        saved=save_desk_output(uid,output_type,payload,run_key=run_key)
        heartbeat=_record_news_heartbeats(uid,scan_mode,'IDLE',{'run_key':run_key,'monitored':0},now)
        durable_failed=((saved.get('persistence') or {}).get('status')=='FAILED' or heartbeat['status']=='FAILED')
        print(f"News {scan_mode} scan skipped: no eligible tickers | heartbeat={heartbeat['status']}")
        return 1 if durable_failed else 0

    manual=os.getenv('GITHUB_EVENT_NAME','').lower()=='workflow_dispatch'
    stories,provider_status=collect_catalyst_stories(
        tickers,include_sec=bool(scan_mode=='full' and should_fetch_sec(now,manual)),
        lookback_hours=story_lookback_hours(now))
    classified=classify_catalyst_stories(stories,holdings,_thesis_map(uid))
    detected=[catalyst_story_event(row) for row in classified
              if row.get('category')!='GENERAL' and (int(row.get('severity') or 0)>=4 or row.get('portfolio'))]
    actionable,suppressed=filter_actionable_events(uid,detected,cooldown_minutes=0,now=now)
    material_events=[event for event in actionable if int(event.get('severity') or 0)>=4]
    payload={'shadow_mode':True,'status':'NO_NEW_MATERIAL_CATALYST','scan_mode':scan_mode,'market_time':now.isoformat(),
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
    saved=save_desk_output(uid,output_type,payload,run_key=run_key)
    provider_failures=_provider_failures(provider_status)
    completion_status='PARTIAL' if provider_failures else 'CURRENT'
    heartbeat=_record_news_heartbeats(uid,scan_mode,completion_status,{
        'run_key':run_key,'monitored':len(tickers),'stories':len(classified),'detected':len(detected),
        'actionable':len(actionable),'provider_failures':provider_failures,
    },now)
    append_agent_audit(uid,'news_catalyst_scan',{'run_key':run_key,'monitored':len(tickers),'stories':len(classified),
                       'detected':len(detected),'actionable':len(actionable),'material':len(material_events),
                       'suppressed':len(suppressed),'scan_mode':scan_mode,
                       'providers':provider_status.get('providers',[]),'notification':notification,
                       'heartbeat':heartbeat['status'],'shadow_mode':True})
    print(f"News {scan_mode} scan: stories={len(classified)} detected={len(detected)} actionable={len(actionable)} "
          f"notification={notification.get('status')} heartbeat={heartbeat['status']}")
    durable_failed=((saved.get('persistence') or {}).get('status')=='FAILED' or heartbeat['status']=='FAILED')
    return 1 if notification.get('status')=='FAILED' or state_result.get('status')=='FAILED' or durable_failed else 0


if __name__=='__main__': raise SystemExit(main())
