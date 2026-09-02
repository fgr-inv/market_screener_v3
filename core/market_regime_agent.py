"""Market Regime & Sector Agent V1.

Consumes the application's already-persisted daily macro and sector snapshots.
It intentionally performs no provider/API calls: the desk reuses the central
refresh pipeline so a specialist run does not multiply FRED/Yahoo/API quota.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math
import pandas as pd

from core.agent_contracts import AgentResult, Evidence, DataStatus

AGENT_VERSION='1.0'
SKILL='market_regime_sector_review'
SKILL_VERSION='1.0'
MAX_CURRENT_AGE_HOURS=36


def _finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _parse_ts(value):
    if not value:
        return None
    try:
        ts=pd.Timestamp(value)
        if ts.tzinfo is None:
            ts=ts.tz_localize('UTC')
        return ts.tz_convert('UTC')
    except Exception:
        return None


def _freshness(meta: dict | None, max_age_hours=MAX_CURRENT_AGE_HOURS):
    meta=meta or {}
    ts=_parse_ts(meta.get('generated_at'))
    if ts is None:
        return DataStatus.NOT_CHECKED, None, 'Snapshot timestamp unavailable.'
    now=pd.Timestamp.now(tz='UTC')
    age=max(0.0,(now-ts).total_seconds()/3600)
    if age <= max_age_hours:
        return DataStatus.CURRENT, age, f'Central market snapshot is {age:.1f}h old.'
    return DataStatus.STALE, age, f'Central market snapshot is {age:.1f}h old (>{max_age_hours}h policy).'


def _sector_rows(sectors):
    if sectors is None:
        return []
    if isinstance(sectors,pd.DataFrame):
        df=sectors.copy()
    else:
        try: df=pd.DataFrame(sectors)
        except Exception: return []
    if df.empty or 'Sector' not in df.columns:
        return []
    rows=[]
    for _,r in df.iterrows():
        sec=str(r.get('Sector','')).strip()
        if not sec: continue
        rows.append({
            'sector':sec,
            'etf':str(r.get('ETF','') or ''),
            'overall':_finite(r.get('Overall')),
            'strength':_finite(r.get('Strength')),
            'entry':_finite(r.get('Entry')),
            'macro':_finite(r.get('Macro')),
            'status':str(r.get('Status','') or ''),
        })
    rows.sort(key=lambda x:(x['overall'] is not None,x['overall'] or -1),reverse=True)
    return rows


def analyze_market_regime(macro: dict | None, sectors=None, snapshot_meta: dict | None=None, max_age_hours=MAX_CURRENT_AGE_HOURS):
    macro=macro or {}
    fresh_status,age_hours,fresh_note=_freshness(snapshot_meta,max_age_hours=max_age_hours)
    if not macro:
        return AgentResult(
            'Market Regime & Sector',AGENT_VERSION,SKILL,SKILL_VERSION,'MARKET','UNAVAILABLE',0.0,
            'No central macro snapshot is available. Run the normal market refresh before relying on regime analysis.',
            [Evidence('Central macro snapshot',None,'data/snapshots/latest_macro.json',status=DataStatus.UNAVAILABLE)],
            alternative_explanation='The market can be functioning normally while the application snapshot is missing or has not refreshed yet.',
            metadata={'sector_scores':{},'snapshot_age_hours':age_hours,'approval_boundary':'Market context only. Never place or modify an order.'}
        )

    score=_finite(macro.get('Macro_Score'))
    risk=str(macro.get('Institutional_Regime') or macro.get('Risk_Regime') or 'N/A').upper()
    econ=str(macro.get('Economic_Regime_Slow') or macro.get('Economic_Regime') or 'N/A').upper()
    momentum=str(macro.get('Momentum') or 'N/A').upper()
    breadth=_finite(macro.get('Breadth'))
    credit=_finite(macro.get('Credit'))
    appetite=_finite(macro.get('Risk_Appetite'))
    rates=_finite(macro.get('Rates'))
    liquidity=_finite(macro.get('Liquidity'))
    growth=_finite(macro.get('Slow_Growth',macro.get('Growth')))
    infl=_finite(macro.get('Slow_Inflation_Pressure',macro.get('Inflation_Pressure')))
    vix=_finite(macro.get('VIX'))

    if risk=='RISK-ON' or (score is not None and score>=70): state='RISK_ON'
    elif risk=='RISK-OFF' or (score is not None and score<=40): state='RISK_OFF'
    else: state='NEUTRAL'

    contradictions=[]
    if appetite is not None and appetite>=65 and breadth is not None and breadth<45:
        contradictions.append('Risk appetite is strong but market breadth is narrow.')
    if appetite is not None and appetite>=60 and credit is not None and credit<40:
        contradictions.append('Risk appetite is positive while credit conditions are weak.')
    if state=='RISK_ON' and momentum=='DETERIORATING':
        contradictions.append('The regime is risk-on, but 20-day macro momentum is deteriorating.')
    if state=='RISK_OFF' and momentum=='IMPROVING':
        contradictions.append('The regime is risk-off, but 20-day macro momentum is improving.')

    srows=_sector_rows(sectors)
    sector_scores={r['sector']:r['overall'] for r in srows if r['overall'] is not None}
    leaders=[r['sector'] for r in srows[:3]]
    laggards=[r['sector'] for r in srows[-3:]] if len(srows)>=3 else []

    evidence=[
        Evidence('Central snapshot freshness',None,'Daily refresh snapshot',status=fresh_status,note=fresh_note),
        Evidence('Institutional macro score',score,'latest_macro.json',status=fresh_status if score is not None else DataStatus.NOT_CHECKED),
        Evidence('Risk appetite',appetite,'latest_macro.json',status=fresh_status if appetite is not None else DataStatus.NOT_CHECKED),
        Evidence('Credit conditions',credit,'latest_macro.json',status=fresh_status if credit is not None else DataStatus.NOT_CHECKED),
        Evidence('Market breadth',breadth,'latest_macro.json',status=fresh_status if breadth is not None else DataStatus.NOT_CHECKED),
        Evidence('Rates conditions',rates,'latest_macro.json',status=fresh_status if rates is not None else DataStatus.NOT_CHECKED),
        Evidence('Liquidity conditions',liquidity,'latest_macro.json',status=fresh_status if liquidity is not None else DataStatus.NOT_CHECKED),
        Evidence('Sector rotation coverage',len(srows),'latest_sectors.parquet',status=fresh_status if srows else DataStatus.NOT_CHECKED,note=', '.join(leaders) if leaders else 'No sector ranking available.'),
    ]
    available=sum(e.status in {DataStatus.CURRENT,DataStatus.STALE} and e.value is not None for e in evidence[1:7])
    confidence=min(.95,.45+.075*available)
    if fresh_status==DataStatus.STALE: confidence=min(confidence,.55)
    elif fresh_status==DataStatus.NOT_CHECKED: confidence=min(confidence,.6)

    regime_bits=[state.replace('_','-')]
    if econ!='N/A': regime_bits.append(econ)
    if momentum!='N/A': regime_bits.append(momentum)
    summary=' · '.join(regime_bits)
    if leaders: summary += ' · leaders: '+', '.join(leaders)

    alt='A macro regime score is a context layer, not a timing signal; price leadership can diverge from macro inputs for extended periods.'
    return AgentResult(
        'Market Regime & Sector',AGENT_VERSION,SKILL,SKILL_VERSION,'MARKET',state,round(confidence,2),summary,
        evidence,contradictions,alt,
        metadata={
            'economic_regime':econ,'momentum':momentum,'macro_score':score,'growth':growth,'inflation_pressure':infl,
            'vix':vix,'leaders':leaders,'laggards':laggards,'sector_scores':sector_scores,'sector_rows':srows,
            'snapshot_age_hours':None if age_hours is None else round(age_hours,2),
            'approval_boundary':'Market context only. Never place or modify an order.',
            'data_policy':'Consumes central snapshots only; no direct provider/API calls from this agent.'
        }
    )
