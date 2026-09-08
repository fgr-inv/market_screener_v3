"""Persist the evidence-gated opportunity lifecycle and virtual Shadow Book."""
from __future__ import annotations

from datetime import datetime
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import record_automation_heartbeat
from core.desk_store import load_desk_output, load_latest_desk_output, save_desk_output
from core.market_calendar import is_us_equity_session
from core.config import SECTOR_ETFS
from core.market_data import download_intraday_prices, download_prices
from core.opportunity_lifecycle import (build_lifecycle_report, build_opportunity_lifecycle,
                                        load_shadow_book, notify_lifecycle,
                                        portfolio_risk_context, save_lifecycle_state,
                                        update_shadow_book)
from core.production_storage import storage_mode
from core.regime_multitimeframe import analyze_regime_multitimeframe
from core.factor_risk import FACTOR_PROXIES, build_factor_risk_context
from core.storage import load_latest_snapshot, load_positions, load_theses


def lifecycle_run_key(now):
    return f"opportunity-lifecycle-{now.date().isoformat()}"


def _payload(record):
    return (record or {}).get('payload') or {}


def _record_market_date(record):
    value=(record or {}).get('created_at')
    if not value: return None
    try:
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=ZoneInfo('UTC'))
        return stamp.astimezone(ZoneInfo('America/New_York')).date()
    except (TypeError,ValueError):
        return None


def _event_anchor_dates(news_payload):
    output={}
    rows=(news_payload or {}).get('stories') or (news_payload or {}).get('actionable_events') or []
    for raw in rows:
        story=((raw.get('metrics') or {}).get('story') or raw)
        ticker=str(story.get('ticker') or raw.get('ticker') or '').upper()
        value=story.get('published_at') or story.get('event_at')
        if not ticker or not value: continue
        try: date=str(datetime.fromisoformat(str(value).replace('Z','+00:00')).date())
        except (TypeError,ValueError): continue
        if ticker not in output or date>output[ticker]: output[ticker]=date
    return output


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for the scheduled opportunity lifecycle.'); return 2
    now=datetime.now(ZoneInfo('America/New_York'))
    manual=os.getenv('GITHUB_EVENT_NAME','').lower()=='workflow_dispatch'
    recovery=os.getenv('AUTOMATION_RECOVERY','').lower()=='true'
    if not is_us_equity_session(now) and not (manual or recovery):
        print('Opportunity lifecycle skipped: US equity market holiday/weekend'); return 0
    run_key=lifecycle_run_key(now)
    previous=load_desk_output(uid,'opportunity_lifecycle_report',run_key)
    if previous:
        notification=notify_lifecycle(uid,_payload(previous),run_key)
        record_automation_heartbeat(uid,'opportunity_lifecycle','REUSED',
                                    {'run_key':run_key,'notification':notification.get('status')})
        print(f"Opportunity lifecycle reused | notification={notification.get('status')}")
        return 1 if notification.get('status')=='FAILED' else 0

    hunt=load_latest_desk_output(uid,'daily_opportunity_hunt')
    signal_record=load_latest_desk_output(uid,'signal_lab_daily_report')
    hunt_payload=_payload(hunt); signal_payload=_payload(signal_record)
    discovery=hunt_payload.get('discovery') or {}
    stale_upstream=(is_us_equity_session(now) and
                    (_record_market_date(hunt)!=now.date() or _record_market_date(signal_record)!=now.date()))
    if not discovery or not signal_payload or stale_upstream:
        missing=[]
        if not discovery: missing.append('daily_opportunity_hunt')
        if not signal_payload: missing.append('signal_lab_daily_report')
        if stale_upstream: missing.append('current_market_date_upstream')
        blocked={'generated_at':now.isoformat(),'status':'BLOCKED_UPSTREAM','missing':missing,
                 'stage_counts':{},'candidates':[],'book':load_shadow_book(uid),
                 'shadow_mode':True,'no_execution':True}
        save_desk_output(uid,'opportunity_lifecycle_report',blocked,run_key=run_key)
        record_automation_heartbeat(uid,'opportunity_lifecycle','FAILED',{'missing':missing})
        print('ERROR: opportunity lifecycle missing upstream output: '+','.join(missing)); return 1

    shortlist=discovery.get('candidates') or []
    verified=discovery.get('verified_opportunities') or []
    signals=signal_payload.get('signals') or []
    thesis_frame=load_theses(user_id=uid)
    theses=[] if thesis_frame is None or thesis_frame.empty else thesis_frame.to_dict('records')
    news_record=(load_latest_desk_output(uid,'news_catalyst_priority_scan') or
                 load_latest_desk_output(uid,'news_catalyst_scan'))
    existing=load_shadow_book(uid)
    news_payload=_payload(news_record); event_anchors=_event_anchor_dates(news_payload)
    active_tickers=[str(row.get('ticker','')).upper() for row in existing.get('positions',[])
                    if row.get('status') in {'PENDING_ENTRY','OPEN'}]
    positions=load_positions(user_id=uid)
    portfolio_tickers=[] if positions is None or positions.empty else positions['ticker'].dropna().astype(str).str.upper().tolist()
    candidate_tickers=[str(row.get('Ticker','')).upper() for row in shortlist]
    sector_tickers=[SECTOR_ETFS.get(str(row.get('Sector') or '')) for row in shortlist]
    sector_tickers=[ticker for ticker in sector_tickers if ticker]
    all_daily=list(dict.fromkeys(candidate_tickers+active_tickers+portfolio_tickers+sector_tickers+list(FACTOR_PROXIES.values())))
    histories=download_prices(all_daily,period='2y',
                              max_age_minutes=15,max_single_fallback=15)
    hourly,hourly_status=download_intraday_prices(list(dict.fromkeys(candidate_tickers+['SPY'])),period='60d',interval='60m')
    breadth=load_latest_snapshot('latest_breadth')
    signal_by_ticker={}
    for signal in signals:
        if str(signal.get('setup_version'))=='2.0':
            signal_by_ticker.setdefault(str(signal.get('ticker','')).upper(),signal)
    confirmations={}
    for candidate in shortlist:
        ticker=str(candidate.get('Ticker','')).upper(); signal=signal_by_ticker.get(ticker)
        if not signal: continue
        sector_history=histories.get(SECTOR_ETFS.get(str(candidate.get('Sector') or '')))
        confirmations[ticker]=analyze_regime_multitimeframe(
            ticker,histories.get(ticker),hourly.get(ticker),histories.get('SPY'),sector_history,breadth,
            candidate.get('Universe Source',''),signal.get('direction','LONG'),signal.get('setup_id',''),
            event_anchor_date=event_anchors.get(ticker))
    lifecycle=build_opportunity_lifecycle(shortlist,verified,signals,theses,news_payload,now,
                                          confirmations=confirmations)
    portfolio_context=portfolio_risk_context(positions,histories)
    factor_context=build_factor_risk_context(portfolio_context+[
        row for row in existing.get('positions',[]) if row.get('status') in {'PENDING_ENTRY','OPEN'}],histories)
    book=update_shadow_book(lifecycle,signals,histories,existing,now,portfolio_context=portfolio_context,
                            factor_context=factor_context)
    report=build_lifecycle_report(lifecycle,book,now)
    report['upstream']={'opportunity_hunt_created_at':(hunt or {}).get('created_at'),
                        'signal_lab_created_at':(signal_record or {}).get('created_at'),
                        'news_created_at':(news_record or {}).get('created_at')}
    report['saved_portfolio_constraints']=portfolio_context
    report['factor_risk']=factor_context
    report['confirmation_summary']={'evaluated':len(confirmations),
        'confirmed':sum(bool(row.get('gate_pass')) for row in confirmations.values()),
        'hourly_provider':hourly_status}
    save_lifecycle_state(uid,report,run_key)
    notification=notify_lifecycle(uid,report,run_key)
    append_agent_audit(uid,'opportunity_lifecycle',{'run_key':run_key,
        'stage_counts':report['stage_counts'],'book_status_counts':book['status_counts'],
        'confirmation_summary':report['confirmation_summary'],
        'weekly_risk_used_pct':book['weekly_risk_used_pct'],'notification':notification,
        'shadow_mode':True,'no_execution':True})
    record_automation_heartbeat(uid,'opportunity_lifecycle','CURRENT',{'run_key':run_key,
        'entry_ready':report['stage_counts'].get('ENTRY_READY',0),
        'book_status_counts':book['status_counts'],'notification':notification.get('status')})
    print(f"Opportunity lifecycle: stages={report['stage_counts']} book={book['status_counts']} notification={notification.get('status')}")
    return 1 if notification.get('status')=='FAILED' else 0


if __name__=='__main__': raise SystemExit(main())
