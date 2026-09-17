"""Evidence-backed, append/amend playbooks for Shadow Investment Desk agents.

Playbooks are reflection records, not executable trading policy.  They learn
only from matured forward outcomes and may enrich later explanations, but they
cannot change a signal, threshold, thesis, portfolio limit, or code path.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math

import pandas as pd

from core.desk_store import load_desk_output, save_desk_output
from core.skill_calibration import PRIMARY_HORIZON_BY_AGENT


PLAYBOOK_VERSION = '1.0'
MIN_ENTRY_SAMPLE = 10
MEDIUM_SAMPLE = 20
HIGH_SAMPLE = 30
MIN_UNIQUE_TICKERS = 5
PRUNE_AFTER_DAYS = 30


def _now(value=None):
    stamp = pd.Timestamp(value or datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize('UTC')
    return stamp.tz_convert('UTC').isoformat()


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _entry_id(agent, state, version):
    digest = hashlib.sha256(f'{agent}|{state}|{version}'.encode('utf-8')).hexdigest()[:10].upper()
    return f'PB-{digest}'


def _payload(value):
    if not value:
        return {}
    candidate = value.get('payload') if isinstance(value, dict) and 'payload' in value else value
    return candidate if isinstance(candidate, dict) else {}


def load_active_playbooks(user_id):
    return _payload(load_desk_output(user_id, 'agent_playbooks', 'active'))


def _latest_primary_outcomes(decisions, outcomes):
    decision_map = {str(row.get('decision_key') or ''): row for row in decisions or [] if row.get('decision_key')}
    latest = {}
    for outcome in outcomes or []:
        key = str(outcome.get('decision_key') or '')
        decision = decision_map.get(key)
        if not decision or str(outcome.get('status') or '').upper() != 'MATURED' or outcome.get('success') is None:
            continue
        agent = str(decision.get('source_agent') or outcome.get('source_agent') or 'UNKNOWN')
        horizon = int(outcome.get('horizon_days') or 0)
        if horizon != int(PRIMARY_HORIZON_BY_AGENT.get(agent, 5)):
            continue
        marker = str(outcome.get('evaluated_at') or '')
        if key not in latest or marker >= str(latest[key]['outcome'].get('evaluated_at') or ''):
            latest[key] = {'decision': decision, 'outcome': outcome}
    return list(latest.values())


def _confidence(sample, unique_tickers, hit_rate):
    if sample >= HIGH_SAMPLE and unique_tickers >= 8 and (hit_rate >= .60 or hit_rate <= .40):
        return 'HIGH'
    if sample >= MEDIUM_SAMPLE and unique_tickers >= MIN_UNIQUE_TICKERS:
        return 'MEDIUM'
    return 'LOW'


def _guidance(agent, state, horizon, hit_rate, confidence):
    condition = (f'{agent} emite {state} con evidencia verificada o parcialmente verificada '
                 f'usando la versión evaluada de la habilidad')
    if confidence == 'LOW':
        action = (f'tratar la lectura como una hipótesis en observación a {horizon} días; todavía no existe '
                  'muestra suficiente para convertirla en una regla del desk')
    elif hit_rate >= .55:
        action = (f'usarla como evidencia de apoyo a {horizon} días, manteniendo la confirmación independiente '
                  'de mercado, cartera y fuente primaria antes de elevar convicción')
    else:
        action = (f'reducir su peso interpretativo a {horizon} días y exigir una confirmación independiente; '
                  'el historial observado no respalda utilizar el estado de forma aislada')
    return condition, action


def build_agent_playbooks(decisions, outcomes, previous=None, generated_at=None):
    """Build deterministic delta operations from matured Shadow evidence."""
    generated = _now(generated_at)
    old = _payload(previous)
    old_entries = dict(old.get('entries') or {})
    groups = {}
    for row in _latest_primary_outcomes(decisions, outcomes):
        decision, outcome = row['decision'], row['outcome']
        agent = str(decision.get('source_agent') or 'UNKNOWN')
        state = str(decision.get('signal_state') or 'UNKNOWN')
        version = str(decision.get('skill_version') or 'UNKNOWN')
        groups.setdefault((agent, state, version), []).append(row)

    entries = dict(old_entries)
    operations = []
    observed_ids = set()
    for (agent, state, version), rows in sorted(groups.items()):
        entry_id = _entry_id(agent, state, version)
        observed_ids.add(entry_id)
        rows.sort(key=lambda row: str(row['outcome'].get('evaluated_at') or ''))
        hits = sum(bool(row['outcome'].get('success')) for row in rows)
        misses = len(rows) - hits
        hit_rate = hits / len(rows)
        tickers = sorted({str(row['decision'].get('ticker') or '').upper() for row in rows
                          if row['decision'].get('ticker')})
        confidence = _confidence(len(rows), len(tickers), hit_rate)
        horizon = int(rows[0]['outcome'].get('horizon_days') or 0)
        when, then = _guidance(agent, state, horizon, hit_rate, confidence)
        last_evidence_at = max(str(row['outcome'].get('evaluated_at') or generated) for row in rows)
        evidence_keys = [str(row['decision'].get('decision_key')) for row in rows[-20:]]
        previous_entry = old_entries.get(entry_id) or {}
        status = 'ACTIVE' if confidence in {'MEDIUM', 'HIGH'} else 'PROPOSED'
        entry = {
            'entry_id': entry_id, 'agent': agent, 'signal_state': state, 'skill_version': version,
            'when': when, 'then': then, 'confidence': confidence, 'status': status,
            'hits': hits, 'misses': misses, 'sample': len(rows), 'unique_tickers': len(tickers),
            'hit_rate_pct': round(hit_rate * 100, 2), 'primary_horizon_days': horizon,
            'first_seen_at': previous_entry.get('first_seen_at') or last_evidence_at,
            'last_evidence_at': last_evidence_at, 'updated_at': generated,
            'evidence_decision_keys': evidence_keys,
            'evidence_summary': (f'{len(rows)} resultados Shadow maduros en {len(tickers)} activos; '
                                 f'{hits} aciertos y {misses} errores al horizonte principal de {horizon} días.'),
            'automatic_effect': 'NARRATIVE_CONTEXT_ONLY',
        }
        entries[entry_id] = entry
        if not previous_entry:
            operations.append({'operation': 'ADD', 'entry_id': entry_id, 'reason': 'New matured evidence segment.'})
        else:
            old_keys = set(previous_entry.get('evidence_decision_keys') or [])
            previous_cutoff = str(previous_entry.get('last_evidence_at') or '')
            new_rows = [row for row in rows
                        if str(row['outcome'].get('evaluated_at') or '') > previous_cutoff
                        and str(row['decision'].get('decision_key')) not in old_keys]
            for row in new_rows[-20:]:
                operations.append({'operation': 'HIT' if row['outcome'].get('success') else 'MISS',
                                   'entry_id': entry_id,
                                   'evidence': str(row['decision'].get('decision_key'))})
            if any(previous_entry.get(key) != entry.get(key) for key in ('when', 'then', 'confidence', 'status')):
                operations.append({'operation': 'AMEND', 'entry_id': entry_id,
                                   'reason': 'Evidence changed confidence, status, or the bounded guidance.'})

    current = pd.Timestamp(generated)
    for entry_id, entry in list(entries.items()):
        if entry_id in observed_ids or str(entry.get('confidence')) != 'LOW' or entry.get('status') == 'PRUNED':
            continue
        try:
            last = pd.Timestamp(entry.get('last_evidence_at'))
            if last.tzinfo is None:
                last = last.tz_localize('UTC')
            if (current - last.tz_convert('UTC')).days >= PRUNE_AFTER_DAYS:
                entry = dict(entry)
                entry.update({'status': 'PRUNED', 'updated_at': generated,
                              'prune_reason': f'Low-confidence entry without new evidence for {PRUNE_AFTER_DAYS} days.'})
                entries[entry_id] = entry
                operations.append({'operation': 'PRUNE', 'entry_id': entry_id,
                                   'reason': entry['prune_reason']})
        except Exception:
            continue

    counts = {status: sum(row.get('status') == status for row in entries.values())
              for status in ('PROPOSED', 'ACTIVE', 'PRUNED')}
    return {
        'playbook_version': PLAYBOOK_VERSION, 'generated_at': generated,
        'entries': entries, 'delta_operations': operations[-100:], 'counts': counts,
        'policy': {
            'append_or_amend_only': True, 'bulk_rewrite_forbidden': True,
            'minimum_entry_sample': MIN_ENTRY_SAMPLE,
            'automatic_effect': 'Narrative context only. No signal, threshold, thesis, code, or portfolio rule changes.',
            'human_review_required_for_hard_constraints': True,
        },
        'shadow_mode': True, 'no_execution': True,
    }


def guidance_for_result(result, playbooks):
    """Return one active exact-match entry; never mutate the result or policy."""
    if result is None:
        return None
    agent = str(getattr(result, 'agent', ''))
    state = str(getattr(result, 'state', ''))
    version = str(getattr(result, 'skill_version', ''))
    entry = (_payload(playbooks).get('entries') or {}).get(_entry_id(agent, state, version))
    return entry if entry and entry.get('status') == 'ACTIVE' else None


def save_agent_playbooks(user_id, playbooks):
    return save_desk_output(user_id, 'agent_playbooks', playbooks, run_key='active')
