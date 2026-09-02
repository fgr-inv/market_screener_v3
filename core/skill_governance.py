"""Human governance records and a non-executing Paper Mode readiness gate.

Governance decisions acknowledge calibration proposals but never rewrite skill
code or configuration.  The readiness report can only recommend a future human
review; it cannot enable a paper account, connect a broker, or create an order.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from core.production_storage import cloud_available, ensure_production_schema, execute_sql, query_sql


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data' / 'skill_governance'
DATA_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_RESOLUTIONS = {'DEFER', 'ACKNOWLEDGE_AND_RETAIN', 'REQUEST_REVISION'}
MIN_SHADOW_DECISIONS = 100
MIN_MATURED_20D = 50
MIN_OBSERVATION_DAYS = 60
MIN_UNIQUE_TICKERS = 10
MIN_CALIBRATED_SEGMENTS = 2


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


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def proposal_key(proposal):
    fields = (
        str((proposal or {}).get('agent') or ''),
        str((proposal or {}).get('signal_state') or ''),
        str((proposal or {}).get('skill_version') or ''),
        str((proposal or {}).get('recommendation') or ''),
    )
    return hashlib.sha256('|'.join(fields).encode('utf-8')).hexdigest()[:28]


def _path(user_id):
    return DATA_DIR / f'{_safe(user_id)}.json'


def _read(path):
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _payload_rows(df):
    rows = []
    for _, row in df.iterrows():
        try:
            rows.append(json.loads(row['payload_json']))
        except Exception:
            pass
    return rows


def load_skill_governance(user_id):
    uid = str(user_id or 'local-user')
    if cloud_available():
        ensure_production_schema()
        df = query_sql('''SELECT payload_json FROM user_skill_governance
                          WHERE user_id=:uid ORDER BY updated_at''', {'uid': uid})
        if not df.empty:
            return _payload_rows(df)
    return _read(_path(uid))


def save_skill_governance(user_id, proposal, resolution, note='', resolved_at=None):
    uid = str(user_id or 'local-user')
    resolution = str(resolution or '').upper()
    recommendation = str((proposal or {}).get('recommendation') or '').upper()
    if resolution not in ALLOWED_RESOLUTIONS:
        return {'status': 'FAILED', 'record': None, 'failures': ['invalid resolution']}
    if recommendation not in {'REVIEW', 'PAUSE_CANDIDATE'}:
        return {'status': 'FAILED', 'record': None, 'failures': ['proposal is not reviewable']}
    key = str((proposal or {}).get('proposal_key') or proposal_key(proposal))
    existing = load_skill_governance(uid)
    previous = next((row for row in existing if str(row.get('proposal_key')) == key), None)
    resolved = _now(resolved_at)
    record = {
        'user_id': uid,
        'proposal_key': key,
        'created_at': str((previous or {}).get('created_at') or resolved),
        'updated_at': resolved,
        'agent': str((proposal or {}).get('agent') or ''),
        'signal_state': str((proposal or {}).get('signal_state') or ''),
        'skill_version': str((proposal or {}).get('skill_version') or ''),
        'recommendation': recommendation,
        'resolution': resolution,
        'note': str(note or '').strip()[:1000],
        'calibration_reason': str((proposal or {}).get('reason') or ''),
        'automatic_change_applied': False,
        'paper_mode_enabled': False,
        'approval_boundary': 'Governance record only. Skill changes require a reviewed code release.',
    }
    keyed = {str(row.get('proposal_key')): row for row in existing if row.get('proposal_key')}
    keyed[key] = record
    rows = sorted(keyed.values(), key=lambda row: (str(row.get('updated_at') or ''), str(row.get('proposal_key') or '')))
    _path(uid).write_text(json.dumps(rows, ensure_ascii=False, default=str, indent=2), encoding='utf-8')

    failures = []
    if cloud_available():
        schema_ok, schema_message = ensure_production_schema()
        if not schema_ok:
            failures.append(str(schema_message))
        else:
            ok, message = execute_sql('''INSERT INTO user_skill_governance(
                user_id,proposal_key,created_at,updated_at,agent,signal_state,skill_version,
                recommendation,resolution,note,payload_json)
                VALUES (:user_id,:proposal_key,:created_at,:updated_at,:agent,:signal_state,:skill_version,
                        :recommendation,:resolution,:note,:payload_json)
                ON CONFLICT (user_id,proposal_key) DO UPDATE SET updated_at=EXCLUDED.updated_at,
                    recommendation=EXCLUDED.recommendation,resolution=EXCLUDED.resolution,
                    note=EXCLUDED.note,payload_json=EXCLUDED.payload_json''', {
                        **{field: record.get(field) for field in (
                            'user_id', 'proposal_key', 'created_at', 'updated_at', 'agent', 'signal_state',
                            'skill_version', 'recommendation', 'resolution', 'note')},
                        'payload_json': json.dumps(record, ensure_ascii=False, default=str),
                    })
            if not ok:
                failures.append(str(message))
    return {'status': 'FAILED' if failures else 'CURRENT', 'record': record, 'failures': failures}


def _gate(name, passed, value, required, detail, category='EVIDENCE'):
    return {'Gate': name, 'Status': 'PASS' if passed else 'BLOCKED', 'Value': value,
            'Required': required, 'Detail': detail, 'Category': category}


def build_paper_readiness_report(decisions, outcomes, calibration_review, governance_records,
                                 persistence_mode, generated_at=None):
    """Return an evidence checklist; never enable or transition to Paper Mode."""
    decisions = list(decisions or [])
    outcomes = list(outcomes or [])
    calibration_review = dict(calibration_review or {})
    governance_records = list(governance_records or [])
    matured_20d_keys = {str(row.get('decision_key')) for row in outcomes
                        if str(row.get('status') or '').upper() == 'MATURED'
                        and int(row.get('horizon_days') or 0) == 20 and row.get('decision_key')}
    tickers = {str(row.get('ticker') or '').upper() for row in decisions if row.get('ticker')}
    timestamps = [_parse_datetime(row.get('decision_at')) for row in decisions]
    timestamps.extend(_parse_datetime(row.get('outcome_at') or row.get('evaluated_at')) for row in outcomes
                      if str(row.get('status') or '').upper() == 'MATURED')
    timestamps = [value for value in timestamps if value is not None]
    observation_days = 0 if len(timestamps) < 2 else max(0, (max(timestamps) - min(timestamps)).days)
    proposals = list(calibration_review.get('proposals') or [])
    records = {str(row.get('proposal_key')): row for row in governance_records if row.get('proposal_key')}
    pause_proposals = [proposal for proposal in proposals if proposal.get('recommendation') == 'PAUSE_CANDIDATE']
    unresolved = []
    for proposal in proposals:
        key = str(proposal.get('proposal_key') or proposal_key(proposal))
        record = records.get(key)
        resolution = str((record or {}).get('resolution') or '')
        if proposal.get('recommendation') == 'PAUSE_CANDIDATE' or resolution != 'ACKNOWLEDGE_AND_RETAIN':
            unresolved.append({**proposal, 'proposal_key': key, 'recorded_resolution': resolution or 'NONE'})

    evidence_gates = [
        _gate('Persistent storage', str(persistence_mode).upper() == 'POSTGRES', str(persistence_mode), 'POSTGRES',
              'Scheduled evidence must survive ephemeral workers.'),
        _gate('Shadow decisions', len(decisions) >= MIN_SHADOW_DECISIONS, len(decisions), MIN_SHADOW_DECISIONS,
              'Minimum forward decision history.'),
        _gate('Matured 20d decisions', len(matured_20d_keys) >= MIN_MATURED_20D, len(matured_20d_keys), MIN_MATURED_20D,
              'Longer-horizon outcomes must be observable.'),
        _gate('Observation window', observation_days >= MIN_OBSERVATION_DAYS, observation_days, MIN_OBSERVATION_DAYS,
              'Calendar days between first decision and latest matured outcome.'),
        _gate('Ticker diversity', len(tickers) >= MIN_UNIQUE_TICKERS, len(tickers), MIN_UNIQUE_TICKERS,
              'Avoid a readiness conclusion from one concentrated name.'),
        _gate('Calibrated segments', int(calibration_review.get('eligible_segments') or 0) >= MIN_CALIBRATED_SEGMENTS,
              int(calibration_review.get('eligible_segments') or 0), MIN_CALIBRATED_SEGMENTS,
              'At least two primary agent/state/version cohorts need usable evidence.'),
    ]
    governance_gates = [
        _gate('No pause candidates', not pause_proposals, len(pause_proposals), 0,
              'A statistically weak segment must be revised and revalidated.', 'GOVERNANCE'),
        _gate('Review queue resolved', not unresolved, len(unresolved), 0,
              'REVIEW items require an explicit retain decision; pause items require a new validated version.', 'GOVERNANCE'),
    ]
    evidence_ready = all(row['Status'] == 'PASS' for row in evidence_gates)
    governance_ready = all(row['Status'] == 'PASS' for row in governance_gates)
    if not evidence_ready:
        status = 'EVIDENCE_BUILDING'
    elif not governance_ready:
        status = 'BLOCKED_REVIEW'
    else:
        status = 'READY_FOR_PAPER_REVIEW'
    return {
        'status': status,
        'generated_at': _now(generated_at),
        'ready_for_human_review': status == 'READY_FOR_PAPER_REVIEW',
        'paper_mode_enabled': False,
        'automatic_transition': False,
        'passed_gates': sum(row['Status'] == 'PASS' for row in evidence_gates + governance_gates),
        'total_gates': len(evidence_gates) + len(governance_gates),
        'gates': evidence_gates + governance_gates,
        'unresolved_proposals': unresolved,
        'approval_boundary': 'Passing every gate permits only a human architecture review. Paper Mode remains disabled until a separate approved release.',
    }
