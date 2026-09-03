"""Portfolio & Risk Agent V1.

Reads the user's authoritative saved positions and current price histories, then
produces portfolio-level concentration/correlation evidence. It never requests
fundamental providers and never places orders.
"""
from __future__ import annotations
import math
import pandas as pd
from core.agent_contracts import AgentResult,Evidence,DataStatus

AGENT_VERSION='1.0'; SKILL='portfolio_risk_review'; SKILL_VERSION='1.0'


def _finite(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None


def analyze_portfolio_risk(positions: pd.DataFrame, histories: dict | None=None):
    histories=histories or {}
    if positions is None or positions.empty:
        return AgentResult('Portfolio & Risk',AGENT_VERSION,SKILL,SKILL_VERSION,'PORTFOLIO','UNAVAILABLE',0.0,
            'No saved positions are available; portfolio fit cannot be evaluated.',
            [Evidence('Saved positions',0,'User portfolio storage',status=DataStatus.UNAVAILABLE)],
            alternative_explanation='A portfolio may exist at an external broker but is not yet synchronized with the authoritative app portfolio.',
            metadata={'approval_boundary':'Risk analysis only. Never place, resize or close an order.'})

    rows=[]
    for _,p in positions.iterrows():
        t=str(p.get('ticker','')).upper().strip(); h=histories.get(t)
        if not t or h is None or h.empty or 'Close' not in h: continue
        close=h['Close'].dropna()
        if close.empty: continue
        px=_finite(close.iloc[-1]); qty=_finite(p.get('quantity'))
        if px is None or qty is None: continue
        rows.append({'ticker':t,'sector':str(p.get('sector','Unknown') or 'Unknown'),'value':px*qty,'close':close})
    if not rows:
        return AgentResult('Portfolio & Risk',AGENT_VERSION,SKILL,SKILL_VERSION,'PORTFOLIO','UNAVAILABLE',0.0,
            'Positions exist but current market values could not be calculated.',
            [Evidence('Market-valued positions',0,'Saved positions + shared price cache',status=DataStatus.FAILED)],
            alternative_explanation='The saved portfolio may be valid while current price history is temporarily unavailable.',
            metadata={'approval_boundary':'Risk analysis only. Never place, resize or close an order.'})

    total=sum(r['value'] for r in rows)
    weights={r['ticker']:(r['value']/total if total>0 else 0) for r in rows}
    sector_values={}
    for r in rows: sector_values[r['sector']]=sector_values.get(r['sector'],0)+r['value']
    sector_weights={k:(v/total if total>0 else 0) for k,v in sector_values.items()}
    largest=max(weights,key=weights.get); largest_w=weights[largest]
    top_sector=max(sector_weights,key=sector_weights.get); top_sector_w=sector_weights[top_sector]
    hhi=sum(w*w for w in weights.values())

    corr=None
    series={r['ticker']:r['close'].pct_change().dropna().tail(126) for r in rows}
    if len(series)>=2:
        rets=pd.concat(series,axis=1).dropna(how='all')
        if len(rets)>=30:
            c=rets.corr(); vals=[]
            for i in range(len(c.columns)):
                for j in range(i+1,len(c.columns)):
                    v=_finite(c.iloc[i,j])
                    if v is not None: vals.append(v)
            if vals: corr=sum(vals)/len(vals)

    risk_points=0
    contradictions=[]
    if largest_w>=.20: risk_points+=2; contradictions.append(f'Largest position {largest} is {largest_w:.0%} of market value.')
    elif largest_w>=.12: risk_points+=1
    if top_sector_w>=.45: risk_points+=2; contradictions.append(f'Largest sector bucket {top_sector} is {top_sector_w:.0%} of market value.')
    elif top_sector_w>=.30: risk_points+=1
    if corr is not None and corr>=.65: risk_points+=2; contradictions.append(f'Average 6-month pairwise correlation is elevated at {corr:.2f}.')
    elif corr is not None and corr>=.45: risk_points+=1
    if hhi>=.18: risk_points+=1
    state='HIGH_RISK' if risk_points>=5 else 'ELEVATED' if risk_points>=3 else 'BALANCED'
    conf=.9 if len(rows)==len(positions) else max(.5,len(rows)/max(len(positions),1))
    ev=[
        Evidence('Portfolio market value',round(total,2),'Saved positions + shared price cache',status=DataStatus.CURRENT),
        Evidence('Largest position weight',round(largest_w,4),'Calculated from current market values',status=DataStatus.CURRENT,note=largest),
        Evidence('Largest sector weight',round(top_sector_w,4),'Saved position sector labels',status=DataStatus.CURRENT,note=top_sector),
        Evidence('Position concentration HHI',round(hhi,4),'Calculated from current portfolio weights',status=DataStatus.CURRENT),
        Evidence('Average pairwise correlation (126d)',None if corr is None else round(corr,3),'Shared daily price history',status=DataStatus.CURRENT if corr is not None else DataStatus.NOT_CHECKED),
    ]
    alt='Nominal sector labels can understate common economic drivers; holdings in different sectors may still share the same factor or thematic exposure.'
    return AgentResult('Portfolio & Risk',AGENT_VERSION,SKILL,SKILL_VERSION,'PORTFOLIO',state,round(conf,2),
        f'Portfolio risk: {state} · {len(rows)} valued positions · largest {largest} {largest_w:.0%} · top sector {top_sector} {top_sector_w:.0%}.',
        ev,contradictions,alt,metadata={'weights':weights,'sector_weights':sector_weights,'approval_boundary':'Risk analysis only. Never place, resize or close an order.'})


def portfolio_fit_for_candidate(ticker: str, sector: str, portfolio_result: AgentResult | None):
    """Return a 0..1 fit score without any provider call."""
    if portfolio_result is None or not getattr(portfolio_result,'metadata',None): return .6,'Portfolio context unavailable.'
    weights=portfolio_result.metadata.get('weights',{}) or {}; sectors=portfolio_result.metadata.get('sector_weights',{}) or {}
    if not weights: return .6,'Portfolio is empty; fit remains neutral until positions are saved.'
    t=str(ticker).upper(); sector=str(sector or 'Unknown')
    if t in weights: return max(.1,1.0-weights[t]*2.5),f'Already held at {weights[t]:.1%} of portfolio.'
    sw=float(sectors.get(sector,0) or 0)
    fit=max(.15,1.0-sw*1.5)
    return round(fit,2),f'Current {sector} exposure is {sw:.1%}.' if sector!='Unknown' else 'Sector exposure not classified.'
