"""Verification Agent V1.1: validates value, source, timestamp and status."""
from __future__ import annotations
from datetime import datetime, timezone
import math
import pandas as pd
from core.agent_contracts import AgentResult,DataStatus,VerificationStatus

AGENT_VERSION='1.1'; SKILL='verify_investment_signal'; SKILL_VERSION='1.1'


def _has_value(value):
    if value is None: return False
    if isinstance(value,str): return bool(value.strip())
    try:
        if isinstance(value,float) and not math.isfinite(value): return False
        return not bool(pd.isna(value))
    except Exception: return True


def _timestamp_status(value,max_age_hours=None):
    if not value: return 'MISSING_TIMESTAMP',None
    try:
        stamp=pd.Timestamp(value)
        if stamp.tzinfo is None: stamp=stamp.tz_localize('UTC')
        now=pd.Timestamp(datetime.now(timezone.utc)); age=(now-stamp.tz_convert('UTC')).total_seconds()/3600
        if age < -1: return 'FUTURE_TIMESTAMP',round(age,2)
        if max_age_hours is not None and age>float(max_age_hours): return 'STALE_TIMESTAMP',round(age,2)
        return 'VALID',round(max(0,age),2)
    except Exception: return 'INVALID_TIMESTAMP',None

def verify_result(result: AgentResult) -> AgentResult:
    max_age=(result.metadata or {}).get('evidence_max_age_hours')
    evidence_checks=[]
    for evidence in result.evidence:
        status=evidence.status.value if hasattr(evidence.status,'value') else str(evidence.status)
        timestamp_status,age=_timestamp_status(evidence.observed_at,max_age)
        has_value=_has_value(evidence.value)
        has_source=bool(str(evidence.source or '').strip())
        if status==DataStatus.CURRENT.value:
            if not has_source or timestamp_status in {'MISSING_TIMESTAMP','INVALID_TIMESTAMP','FUTURE_TIMESTAMP'}:
                evidence.status=DataStatus.NOT_CHECKED
            elif not has_value and not str(evidence.note or '').strip():
                evidence.status=DataStatus.NOT_CHECKED
            elif timestamp_status=='STALE_TIMESTAMP':
                evidence.status=DataStatus.STALE
        evidence_checks.append({'claim':evidence.claim,'has_value':has_value,'has_source':has_source,
                                'timestamp_status':timestamp_status,'age_hours':age,
                                'status':evidence.status.value if hasattr(evidence.status,'value') else str(evidence.status)})
    statuses=[row['status'] for row in evidence_checks]
    current=sum(s==DataStatus.CURRENT.value for s in statuses); total=len(statuses)
    failed=any(s==DataStatus.FAILED.value for s in statuses)
    unavailable=any(s==DataStatus.UNAVAILABLE.value for s in statuses)
    stale=any(s==DataStatus.STALE.value for s in statuses)
    available=current/max(total,1)
    if failed or total==0 or (current==0 and unavailable): status=VerificationStatus.REJECTED
    elif stale: status=VerificationStatus.STALE_DATA
    elif result.contradicting_evidence and available<.8: status=VerificationStatus.CONFLICTING_EVIDENCE
    elif available>=.8: status=VerificationStatus.VERIFIED
    elif current>0: status=VerificationStatus.PARTIALLY_VERIFIED
    else: status=VerificationStatus.NOT_CHECKED
    result.verification_status=status
    result.metadata['verification']={'current_evidence':current,'total_evidence':total,'coverage':round(available,2),
                                     'verifier_version':AGENT_VERSION,'evidence_checks':evidence_checks}
    if status not in {VerificationStatus.VERIFIED,VerificationStatus.PARTIALLY_VERIFIED}:
        result.confidence=round(min(float(result.confidence),.49),2)
    return result
