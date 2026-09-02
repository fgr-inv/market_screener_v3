"""Typed contracts for the V1 investment-desk agents.

The contracts deliberately keep facts, interpretation and verification separate.
They are deterministic containers; model/provider integration can be added later
without changing the hand-off format used by the UI, audit log or routines.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import math


class DataStatus(str, Enum):
    CURRENT='CURRENT'; STALE='STALE'; NOT_CHECKED='NOT_CHECKED'; UNAVAILABLE='UNAVAILABLE'; FAILED='FAILED'

class VerificationStatus(str, Enum):
    VERIFIED='VERIFIED'; PARTIALLY_VERIFIED='PARTIALLY_VERIFIED'; CONFLICTING_EVIDENCE='CONFLICTING_EVIDENCE'; STALE_DATA='STALE_DATA'; NOT_CHECKED='NOT_CHECKED'; REJECTED='REJECTED'

class SignalState(str, Enum):
    SETUP='SETUP'; WATCH='WATCH'; NO_SETUP='NO_SETUP'; BROKEN_SETUP='BROKEN_SETUP'


def utc_now(): return datetime.now(timezone.utc).isoformat()

def _clean(value):
    if isinstance(value, Enum): return value.value
    if isinstance(value, dict): return {str(k):_clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [_clean(v) for v in value]
    try:
        if isinstance(value,float) and (math.isnan(value) or math.isinf(value)): return None
    except Exception: pass
    return value

@dataclass
class Evidence:
    claim: str
    value: Any = None
    source: str = ''
    observed_at: str = field(default_factory=utc_now)
    status: DataStatus = DataStatus.NOT_CHECKED
    note: str = ''
    def to_dict(self): return _clean(asdict(self))

@dataclass
class AgentResult:
    agent: str
    agent_version: str
    skill: str
    skill_version: str
    subject: str
    state: str
    confidence: float
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    alternative_explanation: str = ''
    verification_status: VerificationStatus = VerificationStatus.NOT_CHECKED
    generated_at: str = field(default_factory=utc_now)
    metadata: dict[str,Any] = field(default_factory=dict)
    def to_dict(self): return _clean(asdict(self))
