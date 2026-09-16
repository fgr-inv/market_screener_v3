"""Persistent research-packet and handoff contracts for Investment Desk runs.

This module records coordination state only.  It cannot publish, modify a thesis,
or execute an order.  Financial calculations remain owned by specialist modules.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

import pandas as pd

from core.agent_contracts import VerificationStatus
from core.market_data import classify_symbol


PACKET_VERSION = '1.0'
WORKFLOW_VERSION = '1.0'
FINAL_STATES = {'COMPLETE', 'PARTIAL', 'FAILED', 'STALE', 'REJECTED', 'SKIPPED'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _clean(value):
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return None
    except Exception:
        pass
    return value


def _frame_manifest(frame):
    if frame is None or not hasattr(frame, 'empty') or frame.empty:
        return {'rows': 0, 'columns': [], 'digest': None}
    columns = sorted(str(column) for column in frame.columns)
    sample = frame.head(50).copy()
    try:
        raw = sample.to_json(orient='split', date_format='iso', default_handler=str)
    except TypeError:
        raw = sample.astype(str).to_json(orient='split')
    return {
        'rows': int(len(frame)),
        'columns': columns,
        'digest': hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20],
    }


def _mapping_digest(value):
    raw = json.dumps(_clean(value or {}), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def _snapshot_age_hours(meta, generated_at):
    candidate = (meta or {}).get('generated_at') or (meta or {}).get('as_of')
    if not candidate:
        return None
    try:
        stamp = pd.Timestamp(candidate)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize('UTC')
        current = pd.Timestamp(generated_at)
        if current.tzinfo is None:
            current = current.tz_localize('UTC')
        return round(max(0.0, (current.tz_convert('UTC') - stamp.tz_convert('UTC')).total_seconds() / 3600), 2)
    except Exception:
        return None


def build_research_packet(run_id, context, ticker_agents, global_agents, generated_at=None):
    """Create a bounded manifest proving which immutable context every agent shared."""
    generated_at = str(generated_at or _now())
    tickers = sorted(str(ticker).upper() for ticker in (ticker_agents or {}))
    asset_types = {}
    for ticker in tickers:
        try:
            asset_types[ticker] = str(classify_symbol(ticker) or 'Unknown')
        except Exception:
            asset_types[ticker] = 'Unknown'
    histories = context.histories or {}
    history_manifest = {
        ticker: _frame_manifest(histories.get(ticker)) for ticker in sorted(histories)
    }
    freshness = {
        'snapshot_age_hours': _snapshot_age_hours(context.meta, generated_at),
        'price_histories_present': sum(bool(row.get('rows')) for row in history_manifest.values()),
        'price_histories_requested': len(history_manifest),
        'status': 'CURRENT',
    }
    if freshness['snapshot_age_hours'] is None:
        freshness['status'] = 'NOT_CHECKED'
    elif freshness['snapshot_age_hours'] > 36:
        freshness['status'] = 'STALE'
    sources = list(dict.fromkeys(
        str(value) for value in ((context.meta or {}).get('sources') or []) if str(value).strip()
    ))
    packet = {
        'packet_version': PACKET_VERSION,
        'run_id': str(run_id),
        'generated_at': generated_at,
        'tickers': tickers,
        'asset_types': asset_types,
        'routing': {
            'ticker_agents': {str(key): sorted(value) for key, value in (ticker_agents or {}).items()},
            'global_agents': sorted(global_agents or []),
        },
        'manifests': {
            'positions': _frame_manifest(context.positions),
            'theses': _frame_manifest(context.theses),
            'sectors': _frame_manifest(context.sectors),
            'screener': _frame_manifest(context.screener),
            'histories': history_manifest,
            'macro_digest': _mapping_digest(context.macro),
            'meta_digest': _mapping_digest(context.meta),
        },
        'freshness': freshness,
        'sources': sources,
        'api_policy': {
            'one_shared_context': True,
            'duplicate_price_downloads_forbidden': True,
            'provider_budget_enforced_by_specialists': True,
        },
        'shadow_mode': True,
        'no_execution': True,
    }
    packet['packet_digest'] = _mapping_digest(packet)
    return packet


@dataclass
class AgentHandoff:
    run_id: str
    task_id: str
    agent: str
    subject: str
    status: str
    state: str = 'NOT_CHECKED'
    summary: str = ''
    confidence: float = 0.0
    verification_status: str = 'NOT_CHECKED'
    evidence: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    confirmation: str = ''
    invalidation: str = ''
    sources: list[str] = field(default_factory=list)
    data_as_of: str = ''
    next_owner: str = 'verification'
    started_at: str = ''
    completed_at: str = field(default_factory=_now)
    error: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return _clean(asdict(self))


def handoff_from_result(run_id, result, started_at='', next_owner='cio'):
    value = result.to_dict() if hasattr(result, 'to_dict') else dict(result or {})
    verification = str(value.get('verification_status') or 'NOT_CHECKED')
    accepted = {VerificationStatus.VERIFIED.value, VerificationStatus.PARTIALLY_VERIFIED.value}
    status = 'COMPLETE' if verification == VerificationStatus.VERIFIED.value else 'PARTIAL' if verification in accepted else 'STALE' if verification == VerificationStatus.STALE_DATA.value else 'REJECTED'
    evidence = list(value.get('evidence') or [])[:12]
    sources = list(dict.fromkeys(
        str(row.get('source')) for row in evidence if str(row.get('source') or '').strip()
    ))
    timestamps = [str(row.get('observed_at')) for row in evidence if row.get('observed_at')]
    metadata = value.get('metadata') or {}
    return AgentHandoff(
        run_id=str(run_id),
        task_id=f"{value.get('agent', 'agent')}:{value.get('subject', 'subject')}",
        agent=str(value.get('agent') or 'Unknown'),
        subject=str(value.get('subject') or 'UNKNOWN'),
        status=status,
        state=str(value.get('state') or 'NOT_CHECKED'),
        summary=str(value.get('summary') or ''),
        confidence=float(value.get('confidence') or 0),
        verification_status=verification,
        evidence=evidence,
        contradictions=list(value.get('contradicting_evidence') or [])[:5],
        confirmation=str(metadata.get('confirmation') or ''),
        invalidation=str(metadata.get('invalidation') or ''),
        sources=sources,
        data_as_of=max(timestamps) if timestamps else str(value.get('generated_at') or ''),
        next_owner=str(next_owner),
        started_at=str(started_at or ''),
        metadata={
            'agent_version': value.get('agent_version'),
            'skill': value.get('skill'),
            'skill_version': value.get('skill_version'),
        },
    )


class WorkflowLedger:
    """In-memory state machine whose snapshots are persisted by the desk runner."""

    def __init__(self, run_id, plan, created_at=None):
        self.run_id = str(run_id)
        self.created_at = str(created_at or _now())
        self.updated_at = self.created_at
        self.tasks = {}
        for agent in sorted(plan.get('global_agents') or []):
            self.add(agent, agent.upper(), required=True)
        for ticker, agents in sorted((plan.get('ticker_agents') or {}).items()):
            for agent in sorted(agents):
                self.add(agent, ticker, required=True)

    @staticmethod
    def task_id(agent, subject):
        return f'{str(agent).lower()}:{str(subject).upper()}'

    def add(self, agent, subject, required=True):
        task_id = self.task_id(agent, subject)
        self.tasks.setdefault(task_id, {
            'task_id': task_id, 'agent': str(agent), 'subject': str(subject).upper(),
            'required': bool(required), 'status': 'PENDING', 'attempts': 0,
            'started_at': None, 'completed_at': None, 'error': None,
        })
        return task_id

    def start(self, agent, subject):
        task = self.tasks[self.task_id(agent, subject)]
        task.update(status='RUNNING', attempts=int(task.get('attempts') or 0) + 1,
                    started_at=_now(), completed_at=None, error=None)
        self.updated_at = _now()
        return task

    def finish(self, agent, subject, status='COMPLETE', error=None):
        if status not in FINAL_STATES:
            raise ValueError(f'Invalid final workflow status: {status}')
        task = self.tasks[self.task_id(agent, subject)]
        task.update(status=status, completed_at=_now(), error=str(error or '') or None)
        self.updated_at = _now()
        return task

    def snapshot(self):
        required = [row for row in self.tasks.values() if row['required']]
        incomplete = [row for row in required if row['status'] not in FINAL_STATES]
        failed = [row for row in required if row['status'] in {'PARTIAL', 'FAILED', 'REJECTED', 'STALE'}]
        overall = 'RUNNING' if incomplete else 'PARTIAL' if failed else 'COMPLETE'
        return {
            'workflow_version': WORKFLOW_VERSION,
            'run_id': self.run_id,
            'status': overall,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'tasks': list(self.tasks.values()),
            'counts': {
                state: sum(row['status'] == state for row in self.tasks.values())
                for state in ('PENDING', 'RUNNING', 'COMPLETE', 'PARTIAL', 'FAILED', 'STALE', 'REJECTED', 'SKIPPED')
            },
            'shadow_mode': True,
            'no_execution': True,
        }


def compare_cio_briefs(previous, current):
    """Return bounded, deterministic changes instead of repeating the prior brief."""
    previous = previous or {}
    current = current or {}
    changes = []
    for section, label in (('market_regime', 'Market regime'), ('principal_risk', 'Principal risk')):
        before = (previous.get(section) or {}).get('state')
        after = (current.get(section) or {}).get('state')
        if before and after and before != after:
            changes.append({'section': section, 'subject': label, 'before': before, 'after': after,
                            'reason': (current.get(section) or {}).get('summary')})
    def keyed(rows):
        return {str(row.get('subject') or row.get('Ticker') or '').upper(): row for row in rows or []}
    previous_decisions = keyed(previous.get('decisions_needed'))
    current_decisions = keyed(current.get('decisions_needed'))
    for subject in sorted(set(previous_decisions) | set(current_decisions)):
        before = previous_decisions.get(subject)
        after = current_decisions.get(subject)
        if before is None:
            changes.append({'section': 'decisions', 'subject': subject, 'before': None,
                            'after': after.get('state'), 'reason': 'New review item'})
        elif after is None:
            changes.append({'section': 'decisions', 'subject': subject, 'before': before.get('state'),
                            'after': None, 'reason': 'No longer requires review'})
        elif before.get('state') != after.get('state'):
            changes.append({'section': 'decisions', 'subject': subject, 'before': before.get('state'),
                            'after': after.get('state'), 'reason': after.get('summary')})
    previous_top = [str(row.get('Ticker') or row.get('subject') or '').upper() for row in previous.get('top_opportunities') or []]
    current_top = [str(row.get('Ticker') or row.get('subject') or '').upper() for row in current.get('top_opportunities') or []]
    for ticker in current_top:
        if ticker and ticker not in previous_top:
            changes.append({'section': 'opportunities', 'subject': ticker, 'before': None,
                            'after': 'TOP_OPPORTUNITY', 'reason': 'Entered the CIO shortlist'})
    return {
        'status': 'CHANGED' if changes else 'NO_MATERIAL_CHANGE',
        'items': changes[:20],
        'summary': (f'{len(changes)} material change(s) versus the previous comparable run.' if changes else
                    'No material change versus the previous comparable run.'),
    }
