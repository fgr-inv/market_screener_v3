"""CIO / Chief-of-Staff. Produces a compact, decision-oriented shadow brief."""
from __future__ import annotations
from core.agent_contracts import VerificationStatus

AGENT_VERSION='1.1'; SKILL='daily_cio_brief'; SKILL_VERSION='1.1'

def _compact(d):
    return {
        'subject':d.get('subject'),'agent':d.get('agent'),'state':d.get('state'),
        'confidence':d.get('confidence'),'summary':d.get('summary'),
        'verification_status':d.get('verification_status'),
        'skill_version':d.get('skill_version'),
    }


def build_cio_brief(results, max_decisions=5, watchlist=None, events=None):
    accepted={VerificationStatus.VERIFIED.value,VerificationStatus.PARTIALLY_VERIFIED.value}
    rows=[]; blocked=[]
    for r in results or []:
        d=r.to_dict() if hasattr(r,'to_dict') else dict(r)
        if d.get('verification_status') in accepted:
            state=d.get('state')
            multiplier=1.0 if state in {'SETUP','BROKEN_SETUP','HIGH_RISK','MATERIAL_NEGATIVE','MATERIAL_POSITIVE','MATERIAL_REVIEW'} else .85 if state in {'ELEVATED','MIXED_CATALYSTS'} else .65
            materiality=float(d.get('confidence') or 0) * multiplier
            rows.append((materiality,d))
        else: blocked.append(d)
    rows.sort(key=lambda x:x[0],reverse=True)
    decisions=[d for _,d in rows[:max_decisions]]
    market=next((d for _,d in rows if d.get('agent')=='Market Regime & Sector'),None)
    portfolio=[d for _,d in rows if d.get('agent')=='Portfolio & Risk']
    fundamentals=[d for _,d in rows if d.get('agent')=='Fundamental & Catalyst']
    news_items=[d for _,d in rows if d.get('agent')=='News & Catalyst']
    watchlist=list(watchlist or [])
    event_rows=list(events or [])
    conflicts=[]
    for _,d in rows:
        if d.get('contradicting_evidence') or d.get('state') in {'BROKEN_SETUP','DETERIORATING','RISK_OFF','HIGH_RISK','MATERIAL_NEGATIVE','MIXED_CATALYSTS'}:
            conflicts.append(_compact(d))
    for d in blocked:
        conflicts.append(_compact(d))

    principal_risk=None
    if portfolio:
        p=portfolio[0]
        principal_risk={'state':p.get('state'),'summary':p.get('summary'),'verification_status':p.get('verification_status')}
    elif conflicts:
        principal_risk={'state':conflicts[0].get('state'),'summary':conflicts[0].get('summary'),'verification_status':conflicts[0].get('verification_status')}

    material_reasons=[]
    for event in event_rows:
        if int(event.get('severity') or 0)>=4:
            reason=f"{event.get('ticker')}: {'; '.join(event.get('reasons') or [])}"
            story=((event.get('metrics') or {}).get('story') or {})
            if story.get('url'): reason+=f" · {story.get('url')}"
            material_reasons.append(reason)
    for d in decisions:
        if d.get('state') in {'HIGH_RISK','ELEVATED','BROKEN_SETUP','DETERIORATING','RISK_OFF','MATERIAL_NEGATIVE','MATERIAL_POSITIVE','MATERIAL_REVIEW','MIXED_CATALYSTS'} and float(d.get('confidence') or 0)>=.55:
            material_reasons.append(d.get('summary') or f"{d.get('subject')} {d.get('state')}")
    if watchlist and float(watchlist[0].get('Priority Score') or 0)>=75:
        material_reasons.append(f"{watchlist[0].get('Ticker')} reached watchlist priority {watchlist[0].get('Priority Score')}")
    material_reasons=list(dict.fromkeys(material_reasons))[:5]
    decisions_needed=[]
    for d in decisions:
        if d.get('state') in {'SETUP','BROKEN_SETUP','IMPROVING','DETERIORATING','ELEVATED','HIGH_RISK','MATERIAL_NEGATIVE','MATERIAL_POSITIVE','MATERIAL_REVIEW','MIXED_CATALYSTS'}:
            decisions_needed.append(_compact(d))
    market_section=_compact(market) if market else {
        'subject':'MARKET','agent':'Market Regime & Sector','state':'NOT_CHECKED','confidence':0,
        'summary':'Market context was not required by this routed run.','verification_status':'NOT_CHECKED',
    }
    return {
        'agent':'CIO / Chief of Staff','agent_version':AGENT_VERSION,'skill':SKILL,'skill_version':SKILL_VERSION,
        'headline':'No strong signal' if not decisions else f'{len(decisions)} verified item(s) require review',
        'market_regime':market_section,
        'principal_risk':principal_risk or {'state':'NOT_CHECKED','summary':'No verified portfolio or conflict risk was available.','verification_status':'NOT_CHECKED'},
        'top_opportunities':watchlist[:3],
        'portfolio_items':[_compact(d) for d in portfolio],
        'news_and_catalysts':[_compact(d) for d in news_items],
        'thesis_changes':[_compact(d) for d in fundamentals if d.get('state') in {'IMPROVING','DETERIORATING'}]+
                         [_compact(d) for d in news_items if d.get('state') in {'MATERIAL_NEGATIVE','MATERIAL_POSITIVE','MIXED_CATALYSTS'}],
        'avoid_or_conflicting':conflicts[:5],
        'decisions_needed':decisions_needed[:max_decisions],
        'material':bool(material_reasons),'material_reasons':material_reasons,
        'events_considered':event_rows,
        'decisions':decisions,'blocked_or_low_trust':blocked,
        'approval_boundary':'Research and prioritization only. User approval is required before any trade or irreversible action.',
    }
