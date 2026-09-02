"""Verification Agent V1: rejects unsupported/stale/conflicting handoffs."""
from __future__ import annotations
from core.agent_contracts import AgentResult,DataStatus,VerificationStatus

AGENT_VERSION='1.0'; SKILL='verify_investment_signal'; SKILL_VERSION='1.0'

def verify_result(result: AgentResult) -> AgentResult:
    statuses=[e.status.value if hasattr(e.status,'value') else str(e.status) for e in result.evidence]
    current=sum(s==DataStatus.CURRENT.value for s in statuses); total=len(statuses)
    failed=any(s==DataStatus.FAILED.value for s in statuses)
    stale=any(s==DataStatus.STALE.value for s in statuses)
    available=current/max(total,1)
    if failed or total==0: status=VerificationStatus.REJECTED
    elif stale: status=VerificationStatus.STALE_DATA
    elif result.contradicting_evidence and available<.8: status=VerificationStatus.CONFLICTING_EVIDENCE
    elif available>=.8: status=VerificationStatus.VERIFIED
    elif current>0: status=VerificationStatus.PARTIALLY_VERIFIED
    else: status=VerificationStatus.NOT_CHECKED
    result.verification_status=status
    result.metadata['verification']={'current_evidence':current,'total_evidence':total,'coverage':round(available,2),'verifier_version':AGENT_VERSION}
    if status not in {VerificationStatus.VERIFIED,VerificationStatus.PARTIALLY_VERIFIED}:
        result.confidence=round(min(float(result.confidence),.49),2)
    return result
