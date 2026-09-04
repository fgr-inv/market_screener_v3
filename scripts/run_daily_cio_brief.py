"""Daily pre-market CIO brief. Shadow mode; no order execution."""
from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from core.storage import load_positions,load_latest_snapshot
from core.desk_runner import run_desk_review
from core.desk_store import load_desk_output,load_latest_desk_output
from core.agent_router import full_review_plan
from core.opportunity_discovery import load_active_watchlist_tickers
from core.news_catalyst_agent import catalyst_story_event
from core.desk_notifications import notify_daily_cio_brief
from core.agent_audit import append_agent_audit
from core.market_calendar import is_us_equity_session

def _recent_news_context(user_id,now,max_age_hours=30):
    current=pd.Timestamp(now)
    if current.tzinfo is None: current=current.tz_localize('America/New_York')
    material_stories=[]; seen=set()
    for output_type in ('news_catalyst_priority_scan','news_catalyst_scan'):
        record=load_latest_desk_output(user_id,output_type) or {}; payload=record.get('payload') or {}
        try:
            created=pd.Timestamp(record.get('created_at'))
            if created.tzinfo is None: created=created.tz_localize('UTC')
            if (current.tz_convert('UTC')-created.tz_convert('UTC')).total_seconds()/3600>max_age_hours: continue
        except Exception: continue
        for row in payload.get('stories') or []:
            identity=str(row.get('story_id') or row.get('url') or (row.get('ticker'),row.get('title')))
            if row.get('material') and identity not in seen:
                seen.add(identity); material_stories.append(row)
    material_stories.sort(key=lambda row:row.get('published_at') or '',reverse=True)
    events=[catalyst_story_event(row) for row in material_stories]
    grouped={}
    for event in events:
        ticker=str(event.get('ticker','')).upper(); story=((event.get('metrics') or {}).get('story') or {})
        if ticker and story: grouped.setdefault(ticker,[]).append(story)
    return events,grouped

def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    now=datetime.now(ZoneInfo('America/New_York'))
    manual=os.getenv('GITHUB_EVENT_NAME','').lower()=='workflow_dispatch'
    recovery=os.getenv('AUTOMATION_RECOVERY','').lower()=='true'
    if not is_us_equity_session(now) and not manual: print('CIO brief skipped: US equity market closed'); return 0
    if not (manual or recovery) and not (now.hour==7 and 20 <= now.minute <= 40):
        print('CIO brief skipped: not the 07:30 ET slot'); return 0
    pos=load_positions(user_id=uid); holdings=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
    snap=load_latest_snapshot('latest_screener'); candidates=[]
    if snap is not None and not snap.empty and 'Ticker' in snap.columns:
        score='Opportunity_Score' if 'Opportunity_Score' in snap.columns else ('Entry_Score' if 'Entry_Score' in snap.columns else None)
        x=snap.sort_values(score,ascending=False) if score else snap
        candidates=x['Ticker'].dropna().astype(str).str.upper().head(12).tolist()
    active_watchlist=load_active_watchlist_tickers(uid,limit=20)
    tickers=list(dict.fromkeys(holdings+active_watchlist+candidates))[:25]
    if not tickers: print('CIO brief skipped: no tickers'); return 0
    run_key=f"daily-{now.date().isoformat()}"
    previous=load_desk_output(uid,'daily_cio_brief',run_key)
    if previous and previous.get('payload'):
        notification=notify_daily_cio_brief(uid,previous['payload'].get('brief') or {},run_key)
        print(f"CIO brief reused | daily_notification={notification.get('status')}")
        return 1 if notification.get('status')=='FAILED' else 0
    events,news_by_ticker=_recent_news_context(uid,now)
    plan=full_review_plan(tickers)
    for ticker in news_by_ticker:
        if ticker in plan['ticker_agents'] and 'news' not in plan['ticker_agents'][ticker]: plan['ticker_agents'][ticker].append('news')
    out=run_desk_review(uid,tickers,False,'daily_cio_brief',run_key=run_key,agent_plan=plan,
                        events=events,news_by_ticker=news_by_ticker)
    notification=notify_daily_cio_brief(uid,out['brief'],run_key)
    append_agent_audit(uid,'daily_cio_notification',{'run_key':run_key,'notification':notification,
                       'shadow_mode':True,'no_execution':True})
    print(out['brief']['headline']); print(f"daily_notification={notification.get('status')}")
    return 1 if notification.get('status')=='FAILED' else 0

if __name__=='__main__': raise SystemExit(main())
