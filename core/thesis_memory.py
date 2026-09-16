"""Versioned thesis memory derived from user theses and verified desk conclusions."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from core.desk_store import load_latest_desk_output, save_desk_output


MEMORY_VERSION = '1.0'


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def load_thesis_memory(user_id):
    record = load_latest_desk_output(user_id, 'thesis_memory') or {}
    payload = record.get('payload') or {}
    return payload if isinstance(payload, dict) else {}


def build_thesis_memory(user_id, run_id, thesis_rows, handoffs, previous=None, generated_at=None):
    previous = previous or load_thesis_memory(user_id)
    old_assets = dict(previous.get('assets') or {})
    assets = {key: dict(value) for key, value in old_assets.items()}
    generated_at = str(generated_at or _now())
    for row in thesis_rows or []:
        ticker = str(row.get('ticker') or '').upper()
        if not ticker:
            continue
        current = assets.get(ticker) or {}
        source = {
            'thesis': str(row.get('thesis') or ''),
            'catalysts': str(row.get('catalysts') or ''),
            'invalidation': str(row.get('invalidation') or ''),
            'target': str(row.get('target') or ''),
            'status': str(row.get('status') or 'ACTIVE'),
            'note': str(row.get('note') or ''),
        }
        source_digest = _digest(source)
        assets[ticker] = {
            **current, **source, 'ticker': ticker,
            'thesis_version': int(current.get('thesis_version') or 0) + (source_digest != current.get('source_digest')),
            'source_digest': source_digest,
            'last_user_update': str(row.get('updated_at') or generated_at),
            'last_reviewed_at': current.get('last_reviewed_at'),
            'last_conclusion': current.get('last_conclusion'),
            'last_state': current.get('last_state'),
            'open_contradictions': list(current.get('open_contradictions') or []),
            'history': list(current.get('history') or [])[-9:],
        }
    for handoff in handoffs or []:
        ticker = str(handoff.get('subject') or '').upper()
        if not ticker or ticker in {'MARKET', 'PORTFOLIO'}:
            continue
        current = assets.setdefault(ticker, {
            'ticker': ticker, 'thesis': '', 'catalysts': '', 'invalidation': '', 'target': '',
            'status': 'RESEARCH_ONLY', 'note': '', 'thesis_version': 0, 'history': [],
        })
        prior_state = current.get('last_state')
        state = handoff.get('state')
        conclusion = handoff.get('summary')
        changed = state != prior_state or conclusion != current.get('last_conclusion')
        if changed and current.get('last_reviewed_at'):
            current['history'] = (list(current.get('history') or []) + [{
                'reviewed_at': current.get('last_reviewed_at'),
                'state': prior_state,
                'conclusion': current.get('last_conclusion'),
                'run_id': current.get('last_run_id'),
            }])[-10:]
        current.update({
            'last_reviewed_at': generated_at,
            'last_run_id': str(run_id),
            'last_agent': handoff.get('agent'),
            'last_state': state,
            'last_conclusion': conclusion,
            'last_verification_status': handoff.get('verification_status'),
            'last_confidence': handoff.get('confidence'),
            'open_contradictions': list(handoff.get('contradictions') or []),
            'last_sources': list(handoff.get('sources') or []),
        })
    return {
        'memory_version': MEMORY_VERSION,
        'generated_at': generated_at,
        'run_id': str(run_id),
        'asset_count': len(assets),
        'assets': assets,
        'shadow_mode': True,
        'no_execution': True,
    }


def save_thesis_memory(user_id, memory):
    return save_desk_output(user_id, 'thesis_memory', memory, run_key='active')
