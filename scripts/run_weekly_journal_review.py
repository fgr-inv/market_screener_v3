"""Weekly agent-quality and repeated-error retrospective."""
from datetime import datetime
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import record_automation_heartbeat
from core.desk_store import load_desk_output,save_desk_output
from core.journal_agent import build_journal_review
from core.production_storage import storage_mode
from core.shadow_validation import load_shadow_decisions,load_shadow_outcomes


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for weekly journal review.'); return 2
    now=datetime.now(ZoneInfo('America/New_York')); iso=now.isocalendar()
    run_key=f'journal-review-{iso.year}-W{iso.week:02d}'
    if load_desk_output(uid,'journal_agent_review',run_key):
        record_automation_heartbeat(uid,'journal_agent','REUSED',{'run_key':run_key},now); return 0
    report=build_journal_review(load_shadow_decisions(uid),load_shadow_outcomes(uid),now)
    saved=save_desk_output(uid,'journal_agent_review',report,run_key=run_key)
    append_agent_audit(uid,'weekly_journal_agent_review',{'run_key':run_key,'status':report['status'],
        'patterns':len(report['recurring_patterns']),'persistence':saved.get('persistence'),
        'shadow_mode':True,'no_execution':True})
    record_automation_heartbeat(uid,'journal_agent','CURRENT',{'run_key':run_key,'status':report['status']},now)
    print(report['summary'])
    return 1 if (saved.get('persistence') or {}).get('status')=='FAILED' else 0


if __name__=='__main__': raise SystemExit(main())
