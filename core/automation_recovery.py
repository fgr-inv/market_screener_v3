"""Bounded recovery planning for scheduled Shadow Mode processes."""
from __future__ import annotations


RECOVERABLE_TASKS = {
    'daily_cio': {'module': 'scripts.run_daily_cio_brief', 'timeout_seconds': 1500},
    'daily_snapshot': {'module': 'scripts.daily_refresh', 'timeout_seconds': 3300},
    'opportunity_hunt': {'module': 'scripts.run_daily_opportunity_hunt', 'timeout_seconds': 2100},
    'shadow_validation': {'module': 'scripts.evaluate_shadow_decisions', 'timeout_seconds': 900},
    'skill_calibration': {'module': 'scripts.run_skill_calibration_review', 'timeout_seconds': 600},
    'continuous_improvement': {'module': 'scripts.run_continuous_improvement_review', 'timeout_seconds': 600},
}

ORDER = ('daily_cio', 'daily_snapshot', 'opportunity_hunt', 'shadow_validation',
         'skill_calibration', 'continuous_improvement')


def recovery_plan(health_report, max_tasks=4):
    """Select stale/missing durable jobs; frequent monitors recover naturally."""
    issues = {str(row.get('process')): row for row in (health_report or {}).get('issues') or []}
    planned = []
    for process in ORDER:
        issue = issues.get(process)
        if not issue or str(issue.get('status')) not in {'MISSING', 'STALE', 'FAILED'}:
            continue
        target = issue.get('expected_market_date') or str((health_report or {}).get('market_time') or '')[:10]
        task = RECOVERABLE_TASKS[process]
        planned.append({
            'process': process,
            'module': task['module'],
            'timeout_seconds': task['timeout_seconds'],
            'target_date': target or 'unknown',
            'recovery_key': f'recovery-{process}-{target or "unknown"}',
            'reason': str(issue.get('status')),
        })
        if len(planned) >= int(max_tasks):
            break
    return planned
