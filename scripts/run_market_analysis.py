"""Build, verify, persist and deliver daily/weekly macro-sector analysis."""
from __future__ import annotations

from datetime import datetime
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import record_automation_heartbeat
from core.desk_store import load_desk_output, load_latest_desk_output, save_desk_output
from core.macro_calendar import get_us_macro_calendar
from core.macro_sector_strategist import build_market_evidence, build_market_report
from core.market_calendar import is_us_equity_session
from core.market_report_delivery import notify_market_report
from core.production_storage import storage_mode
from core.storage import load_json_snapshot, load_latest_snapshot


def report_run_key(now,frequency):
    if frequency=='weekly':
        iso=now.isocalendar(); return f'market-analysis-weekly-{iso.year}-W{iso.week:02d}'
    return f'market-analysis-daily-{now.date().isoformat()}'


def run_market_analysis(frequency='daily',now=None):
    frequency='weekly' if str(frequency).lower()=='weekly' else 'daily'
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    current=now or datetime.now(ZoneInfo('America/New_York'))
    if current.tzinfo is None: current=current.replace(tzinfo=ZoneInfo('America/New_York'))
    manual=os.getenv('GITHUB_EVENT_NAME','').lower()=='workflow_dispatch'
    scheduled=os.getenv('GITHUB_EVENT_NAME','').lower()=='schedule'
    local_minutes=current.hour*60+current.minute
    if frequency=='daily' and scheduled and not 20*60+30<=local_minutes<=21*60+10:
        print('Daily market analysis skipped: outside the 20:30-21:10 New York schedule gate'); return 0
    if frequency=='daily' and not is_us_equity_session(current) and not manual:
        print('Daily market analysis skipped: US equity market closed'); return 0
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled market analysis.'); return 2
    output_type=f'market_analysis_{frequency}'; run_key=report_run_key(current,frequency)
    existing=load_desk_output(uid,output_type,run_key)
    if existing and existing.get('payload'):
        notification=notify_market_report(uid,existing['payload'],run_key)
        print(f'{frequency} market analysis reused | delivery={notification.get("status")}')
        return 1 if notification.get('status')=='FAILED' else 0
    previous=load_latest_desk_output(uid,output_type)
    macro=load_json_snapshot('latest_macro'); meta=load_json_snapshot('latest_meta')
    sectors=load_latest_snapshot('latest_sectors'); breadth=load_latest_snapshot('latest_breadth')
    screener=load_latest_snapshot('latest_screener')
    if not macro or not meta or sectors is None or sectors.empty or screener is None or screener.empty:
        print('ERROR: required macro/sector/equity snapshots are missing.'); return 1
    try: calendar=get_us_macro_calendar(14)
    except Exception: calendar=None
    packet=build_market_evidence(macro,sectors,breadth,screener,meta,frequency,previous,current,calendar)
    report=build_market_report(packet)
    if (report.get('verification') or {}).get('status')=='REJECTED':
        print('ERROR: market report rejected by verification gate.'); return 1
    saved=save_desk_output(uid,output_type,report,run_key=run_key)
    notification=notify_market_report(uid,report,run_key)
    process=f'{frequency}_market_analysis'
    heartbeat=record_automation_heartbeat(uid,process,'CURRENT',{
        'run_key':run_key,'verification':report['verification']['status'],'delivery':notification.get('status')},current)
    append_agent_audit(uid,'macro_sector_analysis',{
        'frequency':frequency,'run_key':run_key,'verification':report['verification'],
        'delivery':notification,'persistence':saved.get('persistence'),'shadow_mode':True,'no_execution':True})
    print(f'{report["title"]} | verification={report["verification"]["status"]} '
          f'delivery={notification.get("status")}')
    return 1 if notification.get('status')=='FAILED' or (saved.get('persistence') or {}).get('status')=='FAILED' else 0


def main(): return run_market_analysis(os.getenv('REPORT_FREQUENCY','daily'))


if __name__=='__main__': raise SystemExit(main())
