"""Run one bounded catch-up attempt for missed durable automations."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import build_automation_health, notify_automation_health
from core.automation_recovery import recovery_plan
from core.desk_store import load_desk_output, save_desk_output
from core.production_storage import storage_mode


def main():
    uid = str(os.getenv('DEV_USER_ID', 'local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS', '').lower() == 'true' and storage_mode() != 'POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled recovery.')
        return 2
    now = datetime.now(ZoneInfo('America/New_York'))
    before = build_automation_health(uid, now=now)
    plan = recovery_plan(before)
    if not plan:
        print('Automation recovery: no durable process requires catch-up.')
        notify_automation_health(uid, before, now=now)
        return 0

    failures = {}
    executed = []
    for task in plan:
        previous = load_desk_output(uid, 'automation_recovery_attempt', task['recovery_key'])
        if previous:
            print(f"Recovery skipped: {task['process']} already received its bounded retry.")
            continue
        started = {**task, 'status': 'STARTED', 'started_at': now.isoformat(),
                   'shadow_mode': True, 'no_execution': True}
        save_desk_output(uid, 'automation_recovery_attempt', started, run_key=task['recovery_key'])
        env = dict(os.environ); env['AUTOMATION_RECOVERY'] = 'true'; env['PYTHONPATH'] = os.getcwd()
        try:
            result = subprocess.run([sys.executable, '-m', task['module']], env=env,
                                    timeout=int(task['timeout_seconds']), check=False)
            status = 'RECOVERED' if result.returncode == 0 else 'FAILED'
            return_code = int(result.returncode)
        except subprocess.TimeoutExpired:
            status = 'TIMEOUT'; return_code = 124
        completed = {**started, 'status': status, 'return_code': return_code,
                     'completed_at': datetime.now(ZoneInfo('America/New_York')).isoformat()}
        save_desk_output(uid, 'automation_recovery_attempt', completed, run_key=task['recovery_key'])
        append_agent_audit(uid, 'automation_recovery_attempt', completed)
        executed.append(completed)
        if status != 'RECOVERED':
            failures[task['process']] = f"Autorrecuperación {status}; requiere revisión humana."

    after = build_automation_health(uid, now=datetime.now(ZoneInfo('America/New_York')),
                                    current_failures=failures)
    notification = notify_automation_health(uid, after)
    save_desk_output(uid, 'automation_recovery_summary', {
        'status': 'FAILED' if failures else 'RECOVERED', 'attempts': executed,
        'remaining_issues': [{'process': row.get('process'), 'status': row.get('status')}
                             for row in after.get('issues') or []],
        'notification': notification, 'shadow_mode': True, 'no_execution': True,
    }, run_key=f"recovery-summary-{now.isoformat()}")
    print(f"Automation recovery: attempted={len(executed)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
