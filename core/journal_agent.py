"""Deterministic post-run Journal Agent for recurring process lessons."""
from __future__ import annotations
from datetime import datetime,timezone
import math


AGENT_VERSION='1.0'


def _finite(value):
    try:
        number=float(value); return number if math.isfinite(number) else None
    except Exception: return None


def build_journal_review(decisions,outcomes,generated_at=None,min_pattern_sample=3):
    decision_map={str(row.get('decision_key')):row for row in decisions or [] if row.get('decision_key')}
    latest={}
    for outcome in outcomes or []:
        if str(outcome.get('status')).upper()!='MATURED': continue
        key=(str(outcome.get('decision_key') or ''),int(outcome.get('horizon_days') or 0))
        if not key[0]: continue
        if key not in latest or str(outcome.get('evaluated_at') or '')>=str(latest[key].get('evaluated_at') or ''):
            latest[key]=outcome
    groups={}
    for (_,horizon),outcome in latest.items():
        decision=decision_map.get(str(outcome.get('decision_key')))
        if not decision: continue
        key=(str(decision.get('source_agent') or 'Unknown'),str(decision.get('signal_state') or 'Unknown'),horizon)
        groups.setdefault(key,[]).append((decision,outcome))
    metrics=[]; patterns=[]
    for (agent,state,horizon),rows in sorted(groups.items()):
        successes=[bool(outcome.get('success')) for _,outcome in rows if outcome.get('success') is not None]
        alphas=[value for value in (_finite(outcome.get('signed_alpha_pct')) for _,outcome in rows) if value is not None]
        maes=[value for value in (_finite(outcome.get('mae_pct')) for _,outcome in rows) if value is not None]
        confidences=[value for value in (_finite(decision.get('confidence')) for decision,_ in rows) if value is not None]
        hit=None if not successes else sum(successes)/len(successes)
        row={'agent':agent,'state':state,'horizon_days':horizon,'sample':len(rows),
             'unique_tickers':len({str(decision.get('ticker') or '') for decision,_ in rows}),
             'hit_rate_pct':None if hit is None else round(hit*100,2),
             'mean_signed_alpha_pct':None if not alphas else round(sum(alphas)/len(alphas),4),
             'mean_adverse_excursion_pct':None if not maes else round(sum(maes)/len(maes),4),
             'mean_confidence_pct':None if not confidences else round(sum(confidences)/len(confidences)*100,2)}
        metrics.append(row)
        if len(rows)>=int(min_pattern_sample) and (hit is not None and hit<.45 or alphas and sum(alphas)/len(alphas)<0):
            patterns.append({'agent':agent,'state':state,'horizon_days':horizon,'sample':len(rows),
                             'finding':'Recurring underperformance pattern; keep in Shadow Mode and review evidence/thresholds.',
                             'action':'HUMAN_REVIEW_REQUIRED'})
    status='REVIEW_REQUIRED' if patterns else 'NO_MATURED_EVIDENCE' if not metrics else 'MONITOR'
    return {'agent':'Journal & Process Review','agent_version':AGENT_VERSION,'generated_at':str(generated_at or datetime.now(timezone.utc).isoformat()),
            'status':status,'metrics':metrics,'recurring_patterns':patterns,
            'summary':f'{len(metrics)} agent/state/horizon cohorts reviewed; {len(patterns)} recurring weakness pattern(s).',
            'automatic_rule_changes':0,'shadow_mode':True,'no_execution':True}
