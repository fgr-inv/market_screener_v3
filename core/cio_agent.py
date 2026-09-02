"""CIO / Chief-of-Staff V1. Prioritizes verified specialist work; never trades."""
from __future__ import annotations
from core.agent_contracts import VerificationStatus

AGENT_VERSION='1.0'; SKILL='daily_cio_brief'; SKILL_VERSION='1.0'

def build_cio_brief(results, max_decisions=5):
    accepted={VerificationStatus.VERIFIED.value,VerificationStatus.PARTIALLY_VERIFIED.value}
    rows=[]; blocked=[]
    for r in results or []:
        d=r.to_dict() if hasattr(r,'to_dict') else dict(r)
        if d.get('verification_status') in accepted:
            state=d.get('state')
            multiplier=1.0 if state in {'SETUP','BROKEN_SETUP','HIGH_RISK'} else .85 if state=='ELEVATED' else .65
            materiality=float(d.get('confidence') or 0) * multiplier
            rows.append((materiality,d))
        else: blocked.append(d)
    rows.sort(key=lambda x:x[0],reverse=True)
    decisions=[d for _,d in rows[:max_decisions]]
    return {
        'agent':'CIO / Chief of Staff','agent_version':AGENT_VERSION,'skill':SKILL,'skill_version':SKILL_VERSION,
        'headline':'No strong signal' if not decisions else f'{len(decisions)} verified item(s) require review',
        'decisions':decisions,'blocked_or_low_trust':blocked,
        'approval_boundary':'Research and prioritization only. User approval is required before any trade or irreversible action.',
    }
