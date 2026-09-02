"""Evidence-gated calibration reviews for Shadow Mode desk skills.

The module reads the immutable decision/outcome ledger and produces governance
recommendations.  It never edits a skill, changes a signal threshold, creates a
position, or sends an order.  Every REVIEW/PAUSE_CANDIDATE remains a proposal
for explicit human review.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math

from core.production_storage import cloud_available, ensure_production_schema, execute_sql, query_sql


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data' / 'skill_calibration'
DATA_DIR.mkdir(parents=True, exist_ok=True)

MIN_SAMPLE = 20
MIN_UNIQUE_TICKERS = 5
PAUSE_MIN_SAMPLE = 40
PRIMARY_HORIZON_BY_AGENT = {
    'Technical Signal': 5,
    'Fundamental & Catalyst': 20,
    'CIO Watchlist': 20,
}


def _safe(value):
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in str(value or 'local-user'))


def _now(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _mean(values):
    values = [x for x in (_finite(v) for v in values) if x is not None]
    return None if not values else sum(values) / len(values)


def _wilson(successes, sample, z=1.96):
    """Return a 95% Wilson interval without pretending observations are independent."""
    if sample <= 0:
        return None, None
    p = successes / sample
    denominator = 1 + z * z / sample
    centre = (p + z * z / (2 * sample)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * sample)) / sample) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _primary_horizon(agent):
    return int(PRIMARY_HORIZON_BY_AGENT.get(str(agent), 5))


def _recommendation(sample, unique_tickers, alpha_sample, hit_rate, mean_alpha, brier, upper_hit,
                    min_sample, min_unique_tickers, pause_min_sample):
    if sample < min_sample:
        return 'INSUFFICIENT_EVIDENCE', f'Requires {min_sample} matured observations; currently {sample}.'
    if unique_tickers < min_unique_tickers:
        return 'INSUFFICIENT_EVIDENCE', f'Requires {min_unique_tickers} unique tickers; currently {unique_tickers}.'
    if alpha_sample < min_sample:
        return 'INSUFFICIENT_EVIDENCE', f'Requires {min_sample} SPY-relative outcomes; currently {alpha_sample}.'
    if sample >= pause_min_sample and upper_hit is not None and upper_hit < .50 and mean_alpha is not None and mean_alpha < 0:
        return 'PAUSE_CANDIDATE', 'Hit-rate upper bound is below 50% and mean directional alpha is negative.'
    review_reasons = []
    if hit_rate is not None and hit_rate < 50:
        review_reasons.append('hit rate below 50%')
    if mean_alpha is not None and mean_alpha <= 0:
        review_reasons.append('non-positive directional alpha')
    if brier is not None and brier > .25:
        review_reasons.append('Brier score above 0.25')
    if review_reasons:
        return 'REVIEW', '; '.join(review_reasons) + '.'
    return 'RETAIN', 'Primary-horizon evidence clears the current retention gates.'


def _latest_outcomes(outcomes):
    """Deduplicate retries by decision/horizon, keeping the most recent evaluation."""
    keyed = {}
    for row in outcomes or []:
        key = (str(row.get('decision_key') or ''), int(row.get('horizon_days') or 0))
        if not key[0] or not key[1]:
            continue
        previous = keyed.get(key)
        if previous is None or str(row.get('evaluated_at') or '') >= str(previous.get('evaluated_at') or ''):
            keyed[key] = row
    return list(keyed.values())


def build_skill_calibration_review(decisions, outcomes, generated_at=None, min_sample=MIN_SAMPLE,
                                   min_unique_tickers=MIN_UNIQUE_TICKERS,
                                   pause_min_sample=PAUSE_MIN_SAMPLE):
    """Build a deterministic review grouped by agent, signal state and skill version."""
    decisions = list(decisions or [])
    decision_map = {str(r.get('decision_key') or ''): r for r in decisions if r.get('decision_key')}
    groups = {}
    for outcome in _latest_outcomes(outcomes):
        if str(outcome.get('status') or '').upper() != 'MATURED':
            continue
        decision = decision_map.get(str(outcome.get('decision_key') or ''))
        if not decision or outcome.get('success') is None:
            continue
        agent = str(decision.get('source_agent') or outcome.get('source_agent') or 'UNKNOWN')
        state = str(decision.get('signal_state') or outcome.get('signal_state') or 'UNKNOWN')
        version = str(decision.get('skill_version') or 'UNKNOWN')
        horizon = int(outcome.get('horizon_days') or 0)
        if horizon <= 0:
            continue
        groups.setdefault((agent, state, version, horizon), []).append((decision, outcome))

    segments = []
    for (agent, state, version, horizon), rows in sorted(groups.items()):
        sample = len(rows)
        successes = sum(bool(outcome.get('success')) for _, outcome in rows)
        hit_rate = successes / sample * 100 if sample else None
        lower, upper = _wilson(successes, sample)
        alpha_values = [_finite(outcome.get('signed_alpha_pct')) for _, outcome in rows]
        alpha_values = [x for x in alpha_values if x is not None]
        signed_values = [_finite(outcome.get('signed_return_pct')) for _, outcome in rows]
        signed_values = [x for x in signed_values if x is not None]
        brier_values = []
        for decision, outcome in rows:
            confidence = _finite(decision.get('confidence'))
            if confidence is not None:
                confidence = min(max(confidence, 0.0), 1.0)
                brier_values.append((confidence - float(bool(outcome.get('success')))) ** 2)
        tickers = {str(decision.get('ticker') or outcome.get('ticker') or '').upper() for decision, outcome in rows}
        tickers.discard('')
        decision_dates = sorted(str(decision.get('decision_at') or '') for decision, _ in rows if decision.get('decision_at'))
        mean_alpha = _mean(alpha_values)
        brier = _mean(brier_values)
        primary = horizon == _primary_horizon(agent)
        if primary:
            recommendation, reason = _recommendation(
                sample, len(tickers), len(alpha_values), hit_rate, mean_alpha, brier,
                None if upper is None else upper, int(min_sample), int(min_unique_tickers), int(pause_min_sample),
            )
        else:
            recommendation, reason = 'CONTEXT_ONLY', f'{horizon}d is secondary context; {_primary_horizon(agent)}d is the governance horizon.'
        segments.append({
            'Agent': agent,
            'Signal State': state,
            'Skill Version': version,
            'Horizon': f'{horizon}d',
            'Horizon Days': horizon,
            'Governance Horizon': 'PRIMARY' if primary else 'SECONDARY',
            'Recommendation': recommendation,
            'Sample': sample,
            'Unique Tickers': len(tickers),
            'Alpha Sample': len(alpha_values),
            'Hit Rate %': round(hit_rate, 1) if hit_rate is not None else None,
            'Hit Rate 95% Low %': None if lower is None else round(lower * 100, 1),
            'Hit Rate 95% High %': None if upper is None else round(upper * 100, 1),
            'Mean Directional Return %': None if not signed_values else round(_mean(signed_values), 3),
            'Mean Directional Alpha %': None if mean_alpha is None else round(mean_alpha, 3),
            'Brier Score': None if brier is None else round(brier, 4),
            'First Decision': decision_dates[0] if decision_dates else None,
            'Last Decision': decision_dates[-1] if decision_dates else None,
            'Reason': reason,
        })

    primary_segments = [row for row in segments if row['Governance Horizon'] == 'PRIMARY']
    actionable = [row for row in primary_segments if row['Recommendation'] in {'RETAIN', 'REVIEW', 'PAUSE_CANDIDATE'}]
    proposals = [{
        'agent': row['Agent'],
        'signal_state': row['Signal State'],
        'skill_version': row['Skill Version'],
        'recommendation': row['Recommendation'],
        'sample': row['Sample'],
        'unique_tickers': row['Unique Tickers'],
        'reason': row['Reason'],
        'approval_status': 'PENDING_HUMAN_REVIEW',
        'automatic_change_applied': False,
    } for row in primary_segments if row['Recommendation'] in {'REVIEW', 'PAUSE_CANDIDATE'}]

    comparisons = []
    comparison_groups = {}
    for row in primary_segments:
        comparison_groups.setdefault((row['Agent'], row['Signal State'], row['Horizon Days']), []).append(row)
    for (agent, state, horizon), rows in sorted(comparison_groups.items()):
        known = [row for row in rows if row['Skill Version'] != 'UNKNOWN']
        known.sort(key=lambda row: (str(row.get('Last Decision') or ''), row['Skill Version']))
        if len(known) < 2:
            continue
        previous, latest = known[-2], known[-1]
        ready = all(row['Recommendation'] != 'INSUFFICIENT_EVIDENCE' for row in (previous, latest))
        delta_hit = None if not ready else round(latest['Hit Rate %'] - previous['Hit Rate %'], 2)
        delta_alpha = None if not ready else round(latest['Mean Directional Alpha %'] - previous['Mean Directional Alpha %'], 3)
        delta_brier = None
        if ready and latest['Brier Score'] is not None and previous['Brier Score'] is not None:
            delta_brier = round(latest['Brier Score'] - previous['Brier Score'], 4)
        if not ready:
            preferred = 'NOT_ENOUGH_DATA'
        elif delta_hit > 0 and delta_alpha > 0:
            preferred = 'LATEST'
        elif delta_hit < 0 and delta_alpha < 0:
            preferred = 'PREVIOUS'
        else:
            preferred = 'MIXED'
        comparisons.append({
            'Agent': agent, 'Signal State': state, 'Horizon': f'{horizon}d',
            'Previous Version': previous['Skill Version'], 'Latest Version': latest['Skill Version'],
            'Status': 'CURRENT' if ready else 'NOT_ENOUGH_DATA', 'Preferred': preferred,
            'Delta Hit Rate pp': delta_hit, 'Delta Directional Alpha pp': delta_alpha,
            'Delta Brier': delta_brier,
        })

    counts = {name: sum(row['Recommendation'] == name for row in primary_segments)
              for name in ('INSUFFICIENT_EVIDENCE', 'RETAIN', 'REVIEW', 'PAUSE_CANDIDATE')}
    if not decisions:
        status = 'NO_DECISIONS'
    elif not actionable:
        status = 'NOT_ENOUGH_DATA'
    elif proposals:
        status = 'REVIEW_REQUIRED'
    else:
        status = 'CURRENT'
    return {
        'status': status,
        'generated_at': _now(generated_at),
        'shadow_mode': True,
        'decision_count': len(decisions),
        'matured_outcome_count': sum(str(r.get('status') or '').upper() == 'MATURED' for r in _latest_outcomes(outcomes)),
        'primary_segments': len(primary_segments),
        'eligible_segments': len(actionable),
        'manual_review_required': bool(proposals),
        'recommendation_counts': counts,
        'segments': segments,
        'version_comparisons': comparisons,
        'proposals': proposals,
        'policy': {
            'minimum_sample': int(min_sample),
            'minimum_unique_tickers': int(min_unique_tickers),
            'pause_minimum_sample': int(pause_min_sample),
            'primary_horizons': dict(PRIMARY_HORIZON_BY_AGENT),
            'approval_boundary': 'Recommendations are descriptive proposals. No skill or trading behavior changes automatically.',
            'statistical_caveat': 'Overlapping or correlated signals reduce effective sample size; Wilson bounds are descriptive, not proof of independence.',
        },
    }


def _review_path(user_id, review_key):
    digest = hashlib.sha256(str(review_key).encode('utf-8')).hexdigest()[:20]
    return DATA_DIR / f'{_safe(user_id)}_{digest}.json'


def _latest_path(user_id):
    return DATA_DIR / f'{_safe(user_id)}_latest.json'


def _read(path):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def load_skill_calibration_review(user_id, review_key=None):
    uid = str(user_id or 'local-user')
    if cloud_available():
        ensure_production_schema()
        if review_key is None:
            df = query_sql('''SELECT review_key,created_at,payload_json FROM user_skill_calibration_reviews
                              WHERE user_id=:uid ORDER BY created_at DESC LIMIT 1''', {'uid': uid})
        else:
            df = query_sql('''SELECT review_key,created_at,payload_json FROM user_skill_calibration_reviews
                              WHERE user_id=:uid AND review_key=:review_key LIMIT 1''',
                           {'uid': uid, 'review_key': str(review_key)})
        if not df.empty:
            try:
                row = df.iloc[0]
                return {'user_id': uid, 'review_key': str(row['review_key']), 'created_at': str(row['created_at']),
                        'payload': json.loads(row['payload_json'])}
            except Exception:
                pass
    return _read(_latest_path(uid) if review_key is None else _review_path(uid, review_key))


def save_skill_calibration_review(user_id, review_key, payload):
    uid = str(user_id or 'local-user')
    key = str(review_key or '')
    if not key:
        return {'status': 'FAILED', 'record': None, 'failures': ['review_key required']}
    record = {'user_id': uid, 'review_key': key, 'created_at': _now(), 'payload': payload}
    encoded = json.dumps(record, ensure_ascii=False, default=str, indent=2)
    _review_path(uid, key).write_text(encoded, encoding='utf-8')
    _latest_path(uid).write_text(encoded, encoding='utf-8')
    failures = []
    if cloud_available():
        schema_ok, schema_message = ensure_production_schema()
        if not schema_ok:
            failures.append(str(schema_message))
        else:
            ok, message = execute_sql('''INSERT INTO user_skill_calibration_reviews(
                user_id,review_key,created_at,status,manual_review_required,payload_json)
                VALUES (:user_id,:review_key,:created_at,:status,:manual_review_required,:payload_json)
                ON CONFLICT (user_id,review_key) DO UPDATE SET created_at=EXCLUDED.created_at,
                    status=EXCLUDED.status,manual_review_required=EXCLUDED.manual_review_required,
                    payload_json=EXCLUDED.payload_json''', {
                        'user_id': uid, 'review_key': key, 'created_at': record['created_at'],
                        'status': str((payload or {}).get('status') or 'UNKNOWN'),
                        'manual_review_required': bool((payload or {}).get('manual_review_required')),
                        'payload_json': json.dumps(payload, ensure_ascii=False, default=str),
                    })
            if not ok:
                failures.append(str(message))
    return {'status': 'FAILED' if failures else 'CURRENT', 'record': record, 'failures': failures}


def load_latest_skill_calibration_review(user_id):
    return load_skill_calibration_review(user_id)
