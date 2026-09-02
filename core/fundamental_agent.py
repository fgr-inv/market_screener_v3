"""Fundamental & Catalyst Agent V1 with shared, rate-limit-safe snapshots."""
from __future__ import annotations
import math
from core.agent_contracts import AgentResult,Evidence,DataStatus
from core.data_budget import shared_fundamental_snapshot
from core.fundamentals import get_fundamentals, get_market_valuation_snapshot

AGENT_VERSION='1.0'; SKILL='fundamental_change_review'; SKILL_VERSION='1.0'

def _num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None

def _status(v): return DataStatus.CURRENT if v not in (None,'') else DataStatus.NOT_CHECKED

def analyze_fundamental(ticker, force_refresh=False):
    ticker=str(ticker).upper().strip()
    try:
        f,budget,refreshed=shared_fundamental_snapshot(ticker,get_fundamentals,force=force_refresh)
    except Exception as exc:
        return AgentResult('Fundamental & Catalyst',AGENT_VERSION,SKILL,SKILL_VERSION,ticker,'UNAVAILABLE',0.0,
            f'{ticker}: fundamental refresh failed; no conclusion asserted.',
            [Evidence('Fundamental snapshot',None,'Fundamental data layer',status=DataStatus.FAILED,note=type(exc).__name__)],
            alternative_explanation='No thesis inference is permitted while the required data layer is unavailable.',
            metadata={'approval_boundary':'Research only. Never place or modify an order.','refresh_error':type(exc).__name__})
    # Price-sensitive multiples have a separate 1-day cache and do not force a full accounting refresh.
    try:
        overlay=get_market_valuation_snapshot(ticker) or {}
        for k,v in overlay.items():
            if k not in {'Valuation_Market_Overlay_Available','Valuation_Market_Overlay_Error'} and v is not None: f[k]=v
    except Exception: overlay={}
    score=_num(f.get('Fundamental_Score')) or 50
    rg=_num(f.get('Revenue_Growth')); eg=_num(f.get('Earnings_Growth')); pm=_num(f.get('Profit_Margin'))
    roe=_num(f.get('ROE')); fcf=_num(f.get('FCF')); pe=_num(f.get('Forward_PE'))
    available=bool(f.get('Fundamentals_Available'))
    if not available: state='UNAVAILABLE'
    elif score>=70: state='IMPROVING'
    elif score>=55: state='INTACT'
    elif score>=40: state='MIXED'
    else: state='DETERIORATING'
    core=[rg,eg,pm,roe,fcf]; coverage=sum(x is not None for x in core)/len(core)
    conf=max(0.15,min(.92,.35+.45*coverage+abs(score-50)/180)) if available else 0.0
    src=f.get('Fundamentals_Source') or 'Fundamental data layer'
    ev=[
        Evidence('Revenue growth',rg,src,status=_status(rg)), Evidence('Earnings growth',eg,src,status=_status(eg)),
        Evidence('Profit margin',pm,src,status=_status(pm)), Evidence('Return on equity',roe,src,status=_status(roe)),
        Evidence('Free cash flow',fcf,src,status=_status(fcf)), Evidence('Forward P/E',pe,src,status=_status(pe)),
        Evidence('Fundamental score',score,src,status=DataStatus.CURRENT if available else DataStatus.UNAVAILABLE),
    ]
    contradictions=[]
    if rg is not None and rg>0 and eg is not None and eg<0: contradictions.append('Revenue is growing while earnings are contracting.')
    if fcf is not None and fcf<0 and score>=55: contradictions.append('Composite fundamentals are constructive but free cash flow is negative.')
    if pe is not None and pe>40 and score>=65: contradictions.append('Business quality/growth is strong but valuation is demanding.')
    alt='Recent growth may reflect cycle, mix or easy comparisons rather than a durable improvement; confirm at the next filing/earnings update.'
    summary=f'{ticker}: {state} · fundamental quality {int(round(score))}/100 · core coverage {coverage:.0%}.'
    return AgentResult('Fundamental & Catalyst',AGENT_VERSION,SKILL,SKILL_VERSION,ticker,state,round(conf,2),summary,ev,contradictions,alt,
        metadata={'source':src,'provider_status':f.get('Fundamentals_Provider_Status',{}),
                  'data_budget':budget.to_dict(),'provider_refresh_performed':refreshed,
                  'valuation_overlay_available':bool(overlay.get('Valuation_Market_Overlay_Available')),
                  'approval_boundary':'Research only. Never place or modify an order.'})
