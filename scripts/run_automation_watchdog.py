"""Check scheduled-process freshness and notify only on incidents/recovery."""
from __future__ import annotations

from datetime import datetime
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import build_automation_health, notify_automation_health
from core.production_storage import storage_mode


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for the automation watchdog.'); return 2
    failures={}
    alert_outcome=str(os.getenv('ALERT_RUN_STATUS','') or '').lower()
    if alert_outcome in {'failure','cancelled'}:
        failures['saved_alerts']=f'El paso de alertas terminó con estado {alert_outcome.upper()}.'
    now=datetime.now(ZoneInfo('America/New_York'))
    report=build_automation_health(uid,now=now,current_failures=failures)
    notification=notify_automation_health(uid,report,now=now)
    append_agent_audit(uid,'automation_health_check',{
        'status':report['status'],'issue_count':report['issue_count'],
        'issues':[{'process':row['process'],'status':row['status']} for row in report['issues']],
        'notification':notification,'shadow_mode':True,'no_execution':True,
    })
    print(f"Automation health={report['status']} issues={report['issue_count']} "
          f"notification={notification.get('status')}")
    for issue in report['issues']:
        print(f"- {issue['process']}: {issue['status']}")
    return 1 if report['status']=='DEGRADED' else 0


if __name__=='__main__': raise SystemExit(main())
