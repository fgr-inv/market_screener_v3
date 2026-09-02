"""Technical Signal Agent V1: price observations -> bounded setup state."""
from __future__ import annotations
import pandas as pd
from core.agent_contracts import AgentResult,Evidence,DataStatus,SignalState
from core.technical_engine_v2 import professional_technical_snapshot

AGENT_VERSION='1.0'; SKILL='technical_entry_review'; SKILL_VERSION='1.0'

def _num(v):
    try: return float(v) if pd.notna(v) else None
    except Exception: return None

def analyze_technical(ticker, history, source='Yahoo Finance daily bars', observed_at=None):
    if history is None or history.empty or len(history)<30:
        return AgentResult('Technical Signal',AGENT_VERSION,SKILL,SKILL_VERSION,ticker,SignalState.NO_SETUP.value,0.0,
            'Insufficient current price history; no setup can be asserted.',
            [Evidence('Daily price history',None,source,observed_at or '',DataStatus.UNAVAILABLE,'Minimum 30 bars required.')])
    snap=professional_technical_snapshot(history)
    score=int(snap.get('TA_Quality_Score',50)); structure=snap.get('Market_Structure','Unclear'); weekly=snap.get('Weekly_State','N/D')
    if structure=='HH / HL' and weekly=='Bullish' and score>=65: state=SignalState.SETUP
    elif structure=='LH / LL' and weekly=='Bearish' and score<=40: state=SignalState.BROKEN_SETUP
    elif score>=55 or structure=='HH / HL': state=SignalState.WATCH
    else: state=SignalState.NO_SETUP
    conf=min(.95,max(.25, .45+abs(score-50)/100 + (.12 if weekly!='N/D' else 0)))
    last_date=observed_at or (str(history.index[-1]) if len(history) else '')
    ev=[
        Evidence('Technical quality score',score,source,last_date,DataStatus.CURRENT),
        Evidence('Market structure',structure,source,last_date,DataStatus.CURRENT),
        Evidence('Weekly state',weekly,source,last_date,DataStatus.CURRENT if weekly!='N/D' else DataStatus.NOT_CHECKED),
        Evidence('Relative volume 20d',_num(snap.get('Relative_Volume_20d')),source,last_date,DataStatus.CURRENT),
        Evidence('Distance from anchored VWAP %',_num(snap.get('Dist_AVWAP_%')),source,last_date,DataStatus.CURRENT),
    ]
    contradictions=[]
    if structure=='HH / HL' and weekly=='Bearish': contradictions.append('Daily structure is constructive while weekly confirmation is bearish.')
    if structure=='LH / LL' and weekly=='Bullish': contradictions.append('Daily structure is weak while weekly confirmation remains bullish.')
    alt='The apparent setup may be a short-lived price move unless participation and subsequent closes confirm it.'
    return AgentResult('Technical Signal',AGENT_VERSION,SKILL,SKILL_VERSION,ticker,state.value,round(conf,2),
        f'{ticker}: {state.value} · structure {structure} · weekly {weekly} · technical quality {score}/100.',ev,contradictions,alt,
        metadata={'snapshot':snap,'approval_boundary':'Analysis only. Never place or modify an order.'})
