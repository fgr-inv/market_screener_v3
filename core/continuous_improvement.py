"""Bounded, evidence-gated confidence calibration for the Shadow Investment Desk.

The engine uses chronological train/validation splits and may only adjust an
agent/state/version confidence multiplier within a narrow range.  It cannot
change signal direction, thresholds, portfolio weights, code, or execution
capabilities.  Structural findings remain proposals for human-reviewed code.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math

from core.alerts_engine import send_webhook
from core.desk_store import load_desk_output, load_latest_desk_output, save_desk_output
from core.notification_settings import get_user_webhook
from core.skill_calibration import PRIMARY_HORIZON_BY_AGENT


POLICY_VERSION = '1.0'
MIN_SAMPLE = 30
MIN_TRAIN = 20
MIN_VALIDATION = 10
MIN_UNIQUE_TICKERS = 5
MIN_BRIER_IMPROVEMENT = .005
MIN_MULTIPLIER_CHANGE = .02
MULTIPLIER_LOW = .90
MULTIPLIER_HIGH = 1.10
AUTO_CALIBRATED_AGENTS = {'Technical Signal', 'News & Catalyst', 'Fundamental & Catalyst'}


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
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _clamp(value, low=MULTIPLIER_LOW, high=MULTIPLIER_HIGH):
    return min(float(high), max(float(low), float(value)))


def _segment_key(agent, state, version):
    return '|'.join((str(agent), str(state), str(version)))


def _latest_outcomes(outcomes):
    keyed = {}
    for row in outcomes or []:
        key = (str(row.get('decision_key') or ''), int(row.get('horizon_days') or 0))
        if not key[0] or not key[1]:
            continue
        previous = keyed.get(key)
        if previous is None or str(row.get('evaluated_at') or '') >= str(previous.get('evaluated_at') or ''):
            keyed[key] = row
    return list(keyed.values())


def _empty_policy(generated_at=None):
    return {
        'policy_version': POLICY_VERSION,
        'updated_at': _now(generated_at),
        'entries': {},
        'scope': 'confidence_multiplier_only',
        'bounds': {'minimum': MULTIPLIER_LOW, 'maximum': MULTIPLIER_HIGH},
        'shadow_mode': True,
        'no_execution': True,
    }


def _policy_payload(value):
    if not value:
        return _empty_policy()
    payload = value.get('payload') if isinstance(value, dict) and 'payload' in value else value
    if not isinstance(payload, dict):
        return _empty_policy()
    policy = _empty_policy(payload.get('updated_at'))
    policy.update(payload)
    policy['entries'] = dict(payload.get('entries') or {})
    return policy


def load_active_improvement_policy(user_id):
    return _policy_payload(load_desk_output(user_id, 'continuous_improvement_policy', 'active'))


def load_latest_improvement_review(user_id):
    return load_latest_desk_output(user_id, 'continuous_improvement_review')


def load_improvement_review(user_id, review_key):
    return load_desk_output(user_id, 'continuous_improvement_review', review_key)


def _brier(rows, multiplier):
    values = []
    for row in rows:
        confidence = _finite(row['decision'].get('raw_confidence', row['decision'].get('confidence')))
        if confidence is None:
            continue
        probability = min(.99, max(.01, confidence * float(multiplier)))
        actual = float(bool(row['outcome'].get('success')))
        values.append((probability - actual) ** 2)
    return None if not values else sum(values) / len(values)


def _mean(values):
    clean = [number for number in (_finite(value) for value in values) if number is not None]
    return None if not clean else sum(clean) / len(clean)


def build_continuous_improvement_review(decisions, outcomes, active_policy=None, generated_at=None):
    """Build a deterministic champion/challenger review and its next safe policy."""
    generated = _now(generated_at)
    decision_map = {str(row.get('decision_key') or ''): row for row in decisions or [] if row.get('decision_key')}
    groups = {}
    for outcome in _latest_outcomes(outcomes):
        decision = decision_map.get(str(outcome.get('decision_key') or ''))
        if not decision or str(outcome.get('status') or '').upper() != 'MATURED' or outcome.get('success') is None:
            continue
        agent = str(decision.get('source_agent') or outcome.get('source_agent') or 'UNKNOWN')
        state = str(decision.get('signal_state') or outcome.get('signal_state') or 'UNKNOWN')
        version = str(decision.get('skill_version') or 'UNKNOWN')
        horizon = int(outcome.get('horizon_days') or 0)
        if agent not in AUTO_CALIBRATED_AGENTS or horizon != int(PRIMARY_HORIZON_BY_AGENT.get(agent, 5)):
            continue
        confidence = _finite(decision.get('raw_confidence', decision.get('confidence')))
        if confidence is None:
            continue
        groups.setdefault((agent, state, version), []).append({'decision': decision, 'outcome': outcome})

    # Only the most recently observed skill version is eligible for each agent/state.
    current_versions = {}
    for (agent, state, version), rows in groups.items():
        marker = max(str(row['decision'].get('decision_at') or '') for row in rows)
        previous = current_versions.get((agent, state))
        if previous is None or (marker, version) > previous:
            current_versions[(agent, state)] = (marker, version)

    champion = _policy_payload(active_policy)
    next_policy = _policy_payload(json.loads(json.dumps(champion)))
    next_policy.update({'policy_version': POLICY_VERSION, 'updated_at': generated,
                        'scope': 'confidence_multiplier_only', 'shadow_mode': True, 'no_execution': True})
    candidates = []
    promotions = []
    for (agent, state, version), rows in sorted(groups.items()):
        if current_versions.get((agent, state), ('', ''))[1] != version:
            continue
        rows.sort(key=lambda row: (str(row['decision'].get('decision_at') or ''),
                                   str(row['decision'].get('decision_key') or '')))
        sample = len(rows)
        unique_tickers = len({str(row['decision'].get('ticker') or '').upper() for row in rows
                              if row['decision'].get('ticker')})
        key = _segment_key(agent, state, version)
        current_entry = (champion.get('entries') or {}).get(key) or {}
        champion_multiplier = _clamp(_finite(current_entry.get('confidence_multiplier')) or 1.0)
        base = {
            'segment_key': key, 'agent': agent, 'signal_state': state, 'skill_version': version,
            'sample': sample, 'unique_tickers': unique_tickers,
            'champion_multiplier': round(champion_multiplier, 4),
            'automatic_scope': 'CONFIDENCE_ONLY',
        }
        if sample < MIN_SAMPLE or unique_tickers < MIN_UNIQUE_TICKERS:
            base.update({'status': 'NOT_ENOUGH_DATA', 'train_sample': 0, 'validation_sample': 0,
                         'challenger_multiplier': None, 'champion_brier': None, 'challenger_brier': None,
                         'brier_improvement': None,
                         'reason': f'Requires {MIN_SAMPLE} matured outcomes and {MIN_UNIQUE_TICKERS} unique tickers.'})
            candidates.append(base)
            continue

        split = max(MIN_TRAIN, sample - max(MIN_VALIDATION, int(round(sample * .30))))
        split = min(split, sample - MIN_VALIDATION)
        train, validation = rows[:split], rows[split:]
        train_hit = sum(bool(row['outcome'].get('success')) for row in train) / len(train)
        train_confidence = _mean(row['decision'].get('raw_confidence', row['decision'].get('confidence')) for row in train)
        challenger_multiplier = _clamp(train_hit / train_confidence) if train_confidence else champion_multiplier
        champion_brier = _brier(validation, champion_multiplier)
        challenger_brier = _brier(validation, challenger_multiplier)
        improvement = ((champion_brier - challenger_brier)
                       if champion_brier is not None and challenger_brier is not None else None)
        validation_hit = sum(bool(row['outcome'].get('success')) for row in validation) / len(validation)
        validation_alpha = _mean(row['outcome'].get('signed_alpha_pct') for row in validation)
        meaningful = abs(challenger_multiplier - champion_multiplier) >= MIN_MULTIPLIER_CHANGE
        improves = improvement is not None and improvement >= MIN_BRIER_IMPROVEMENT
        upside_guard = (challenger_multiplier <= champion_multiplier or
                        (validation_hit >= .50 and validation_alpha is not None and validation_alpha > 0))
        promote = bool(meaningful and improves and upside_guard)
        if promote:
            status = 'AUTO_PROMOTED'
            reason = 'Out-of-sample Brier score improved and every confidence-only safety gate passed.'
            entry = {
                'agent': agent, 'signal_state': state, 'skill_version': version,
                'confidence_multiplier': round(challenger_multiplier, 4),
                'promoted_at': generated, 'validation_sample': len(validation),
                'brier_improvement': round(improvement, 6),
                'scope': 'confidence_only', 'rollback_multiplier': round(champion_multiplier, 4),
            }
            next_policy['entries'][key] = entry
            promotions.append(entry)
        else:
            status = 'HOLD_CHAMPION'
            reasons = []
            if not meaningful: reasons.append('change below the 2% materiality gate')
            if not improves: reasons.append('validation Brier improvement below 0.005')
            if not upside_guard: reasons.append('higher confidence blocked by non-positive validation edge')
            reason = '; '.join(reasons) + '.'
        base.update({
            'status': status, 'train_sample': len(train), 'validation_sample': len(validation),
            'train_hit_rate_pct': round(train_hit * 100, 2),
            'validation_hit_rate_pct': round(validation_hit * 100, 2),
            'validation_mean_alpha_pct': None if validation_alpha is None else round(validation_alpha, 4),
            'challenger_multiplier': round(challenger_multiplier, 4),
            'champion_brier': None if champion_brier is None else round(champion_brier, 6),
            'challenger_brier': None if challenger_brier is None else round(challenger_brier, 6),
            'brier_improvement': None if improvement is None else round(improvement, 6),
            'reason': reason,
        })
        candidates.append(base)

    eligible = [row for row in candidates if row['status'] != 'NOT_ENOUGH_DATA']
    if promotions:
        status = 'UPDATED'
    elif eligible:
        status = 'CHAMPION_RETAINED'
    elif groups:
        status = 'NOT_ENOUGH_DATA'
    else:
        status = 'NO_MATURED_EVIDENCE'
    return {
        'status': status, 'generated_at': generated, 'policy_version': POLICY_VERSION,
        'matured_primary_outcomes': sum(len(rows) for rows in groups.values()),
        'segments_reviewed': len(candidates), 'eligible_segments': len(eligible),
        'automatic_promotions': len(promotions), 'promotions': promotions,
        'candidates': candidates, 'next_policy': next_policy,
        'structural_code_changes': 'HUMAN_REVIEW_REQUIRED',
        'github_agent_ready': True,
        'policy': {
            'minimum_sample': MIN_SAMPLE, 'minimum_train': MIN_TRAIN,
            'minimum_validation': MIN_VALIDATION, 'minimum_unique_tickers': MIN_UNIQUE_TICKERS,
            'multiplier_bounds': [MULTIPLIER_LOW, MULTIPLIER_HIGH],
            'minimum_brier_improvement': MIN_BRIER_IMPROVEMENT,
            'automatic_scope': 'Only confidence calibration. Signals, thresholds, code and trading remain unchanged.',
            'rollback': 'Every promoted entry stores its prior multiplier and a later validated challenger may revert it.',
        },
        'shadow_mode': True, 'no_execution': True,
    }


def apply_improvement_policy(result, policy):
    """Apply one exact confidence-only policy entry to an AgentResult in memory."""
    if result is None:
        return result
    key = _segment_key(getattr(result, 'agent', ''), getattr(result, 'state', ''),
                       getattr(result, 'skill_version', ''))
    entry = (_policy_payload(policy).get('entries') or {}).get(key)
    if not entry:
        return result
    multiplier = _clamp(_finite(entry.get('confidence_multiplier')) or 1.0)
    original = min(1.0, max(0.0, float(getattr(result, 'confidence', 0) or 0)))
    calibrated = min(.99, max(0.0, original * multiplier))
    result.confidence = round(calibrated, 4)
    result.metadata = dict(getattr(result, 'metadata', {}) or {})
    result.metadata['continuous_improvement'] = {
        'policy_version': POLICY_VERSION, 'segment_key': key,
        'original_confidence': round(original, 4),
        'confidence_multiplier': round(multiplier, 4),
        'calibrated_confidence': round(calibrated, 4),
        'scope': 'confidence_only', 'shadow_mode': True,
    }
    return result


def save_improvement_review(user_id, review_key, report):
    review = save_desk_output(user_id, 'continuous_improvement_review', report, run_key=review_key)
    policy = save_desk_output(user_id, 'continuous_improvement_policy', report['next_policy'], run_key='active')
    return {'status': 'CURRENT', 'review': review, 'policy': policy}


def build_discord_improvement_embed(report):
    promotions = report.get('promotions') or []
    fields = [{
        'name': '📐 Límites automáticos',
        'value': 'Solo confianza por agente/estado/versión · rango 0,90–1,10 · validación cronológica separada.',
        'inline': False,
    }]
    for row in promotions[:8]:
        fields.append({
            'name': f"✅ {row.get('agent')} · {row.get('signal_state')}",
            'value': (f"Multiplicador: **{row.get('rollback_multiplier'):.2f} → {row.get('confidence_multiplier'):.2f}**\n"
                      f"Validación: {row.get('validation_sample')} · mejora Brier: {row.get('brier_improvement'):.4f}"),
            'inline': False,
        })
    if not promotions:
        fields.append({'name': '🏆 Resultado', 'value': 'El modelo actual se mantuvo: ningún candidato superó todos los controles.', 'inline': False})
    fields.append({'name': '🔒 Gobernanza',
                   'value': 'Cambios estructurales de código requieren pull request y aprobación humana. Ninguna orden fue enviada.',
                   'inline': False})
    return {
        'author': {'name': 'Market Screener Pro · Continuous Improvement'},
        'title': '🧪 Revisión semanal de mejora continua',
        'description': (f"Estado: **{report.get('status')}** · segmentos elegibles: "
                        f"**{report.get('eligible_segments', 0)}** · ajustes: **{len(promotions)}**"),
        'color': 0x2ECC71 if promotions else 0x3498DB,
        'fields': fields[:25], 'timestamp': report.get('generated_at') or _now(),
        'footer': {'text': 'SHADOW MODE · Calibración acotada · Sin cambios autónomos de código ni operaciones'},
    }


def notify_improvement_review(user_id, report, review_key, send_fn=send_webhook):
    uid = str(user_id or 'local-user')
    prior = load_desk_output(uid, 'continuous_improvement_delivery', review_key)
    if prior and bool((prior.get('payload') or {}).get('delivered')):
        return {'status': 'DUPLICATE', 'delivered': True, 'attempted': False}
    target = get_user_webhook(uid)
    if not target:
        payload = {'status': 'NOT_CONFIGURED', 'delivered': False, 'attempted': False, 'shadow_mode': True}
        save_desk_output(uid, 'continuous_improvement_delivery', payload, run_key=review_key)
        return payload
    message = (f"🧪 MEJORA CONTINUA · {report.get('status')}\n"
               f"Segmentos elegibles: {report.get('eligible_segments', 0)} · ajustes: {report.get('automatic_promotions', 0)}\n"
               "SHADOW MODE · Sin cambios autónomos de código ni operaciones.")
    try:
        delivered = bool(send_fn(message, url=target, discord_embed=build_discord_improvement_embed(report)))
    except TypeError as exc:
        if 'discord_embed' not in str(exc):
            raise
        delivered = bool(send_fn(message, url=target))
    payload = {'status': 'DELIVERED' if delivered else 'FAILED', 'delivered': delivered,
               'attempted': True, 'shadow_mode': True}
    save_desk_output(uid, 'continuous_improvement_delivery', payload, run_key=review_key)
    return payload
