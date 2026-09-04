"""Weekly bounded champion/challenger review for Shadow Mode confidence."""
from __future__ import annotations

from datetime import datetime
import os
from zoneinfo import ZoneInfo

from core.agent_audit import append_agent_audit
from core.automation_health import record_automation_heartbeat
from core.continuous_improvement import (
    build_continuous_improvement_review,
    load_active_improvement_policy,
    load_improvement_review,
    notify_improvement_review,
    save_improvement_review,
)
from core.production_storage import storage_mode
from core.shadow_validation import load_shadow_decisions, load_shadow_outcomes


def main():
    uid = str(os.getenv('DEV_USER_ID', 'local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS', '').lower() == 'true' and storage_mode() != 'POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled continuous improvement.')
        return 2
    now = datetime.now(ZoneInfo('America/New_York'))
    iso = now.isocalendar()
    review_key = f'continuous-improvement-{iso.year}-W{iso.week:02d}'
    previous = load_improvement_review(uid, review_key)
    if previous:
        notification = notify_improvement_review(uid, previous.get('payload') or {}, review_key)
        record_automation_heartbeat(uid, 'continuous_improvement', status='REUSED',
                                    details={'review_key': review_key, 'notification': notification.get('status')})
        print('Continuous improvement skipped: weekly review already exists.')
        return 0
    decisions = load_shadow_decisions(uid)
    outcomes = load_shadow_outcomes(uid)
    active = load_active_improvement_policy(uid)
    report = build_continuous_improvement_review(decisions, outcomes, active, generated_at=now)
    persistence = save_improvement_review(uid, review_key, report)
    notification = notify_improvement_review(uid, report, review_key)
    append_agent_audit(uid, 'continuous_improvement_review', {
        'review_key': review_key, 'status': report['status'],
        'eligible_segments': report['eligible_segments'],
        'automatic_promotions': report['automatic_promotions'],
        'notification': notification, 'persistence': persistence['status'],
        'automatic_scope': 'confidence_only', 'structural_code_changes': 'HUMAN_REVIEW_REQUIRED',
        'shadow_mode': True, 'no_execution': True,
    })
    record_automation_heartbeat(uid, 'continuous_improvement', status='CURRENT', details={
        'review_key': review_key, 'review_status': report['status'],
        'automatic_promotions': report['automatic_promotions'],
    })
    print(f"Continuous improvement: status={report['status']} "
          f"eligible={report['eligible_segments']} promoted={report['automatic_promotions']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
