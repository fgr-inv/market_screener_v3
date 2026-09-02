"""Weekly evidence-gated review of Shadow Mode skill performance."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import os

from core.agent_audit import append_agent_audit
from core.production_storage import storage_mode
from core.shadow_validation import load_shadow_decisions, load_shadow_outcomes
from core.skill_calibration import (build_skill_calibration_review, load_skill_calibration_review,
                                    save_skill_calibration_review)
from core.skill_governance import build_paper_readiness_report, load_skill_governance


def main():
    uid = str(os.getenv('DEV_USER_ID', 'local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS', '').lower() == 'true' and storage_mode() != 'POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled skill calibration.')
        return 2
    now = datetime.now(ZoneInfo('America/New_York'))
    iso = now.isocalendar()
    run_key = f'skill-calibration-{iso.year}-W{iso.week:02d}'
    if load_skill_calibration_review(uid, run_key):
        print('Skill calibration skipped: review already exists for this ISO week.')
        return 0
    decisions = load_shadow_decisions(uid)
    outcomes = load_shadow_outcomes(uid)
    review = build_skill_calibration_review(decisions, outcomes, generated_at=now)
    review['paper_readiness'] = build_paper_readiness_report(
        decisions, outcomes, review, load_skill_governance(uid), storage_mode(), generated_at=now)
    persistence = save_skill_calibration_review(uid, run_key, review)
    append_agent_audit(uid, 'shadow_skill_calibration_review', {
        'run_key': run_key,
        'status': review['status'],
        'eligible_segments': review['eligible_segments'],
        'proposals': review['proposals'],
        'paper_readiness_status': review['paper_readiness']['status'],
        'persistence': persistence['status'],
        'shadow_mode': True,
    })
    if persistence['status'] == 'FAILED':
        print('ERROR: skill calibration was not fully persisted; run remains retriable.')
        return 1
    print(f"Skill calibration: status={review['status']} eligible={review['eligible_segments']} "
          f"proposals={len(review['proposals'])}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
