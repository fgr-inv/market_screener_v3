"""Weekly human-gated Champion/Challenger review for technical experiments."""
from __future__ import annotations
from datetime import datetime
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import record_automation_heartbeat
from core.desk_store import load_desk_output, save_desk_output
from core.production_storage import storage_mode
from core.signal_lab import build_weekly_signal_lab_review, load_signal_lab_ledger, notify_signal_lab


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for weekly signal lab review.'); return 2
    now=datetime.now(ZoneInfo('America/New_York')); iso=now.isocalendar()
    run_key=f'signal-lab-review-{iso.year}-W{iso.week:02d}'
    prior=load_desk_output(uid,'signal_lab_weekly_review',run_key)
    if prior:
        notification=notify_signal_lab(uid,prior.get('payload') or {},run_key,weekly=True)
        record_automation_heartbeat(uid,'signal_lab_weekly','REUSED',{'run_key':run_key,'notification':notification.get('status')})
        print('Weekly signal lab review reused.'); return 0
    ledger=load_signal_lab_ledger(uid)
    report=build_weekly_signal_lab_review(ledger['signals'],ledger['outcomes'],now)
    save_desk_output(uid,'signal_lab_weekly_review',report,run_key=run_key)
    notification=notify_signal_lab(uid,report,run_key,weekly=True)
    append_agent_audit(uid,'weekly_signal_lab_review',{'run_key':run_key,'status':report['status'],
        'eligible_variants':report['eligible_variants'],'proposals':len(report['proposals']),
        'notification':notification,'automatic_rule_changes':0,'shadow_mode':True,'no_execution':True})
    record_automation_heartbeat(uid,'signal_lab_weekly','CURRENT',{'run_key':run_key,'status':report['status'],
        'proposals':len(report['proposals'])})
    print(f"Weekly signal lab: status={report['status']} eligible={report['eligible_variants']} proposals={len(report['proposals'])}")
    return 1 if notification.get('status')=='FAILED' else 0


if __name__=='__main__': raise SystemExit(main())
