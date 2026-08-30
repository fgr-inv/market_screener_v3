"""Professional research layer for single-name equity analysis.

This module deliberately separates four analyst workstreams that are often mixed in
simple screeners: peer benchmarking, estimate/revision momentum, catalyst mapping,
and scenario-based valuation/risk-reward. It uses only observable/free inputs and
marks missing evidence rather than manufacturing precision.
"""
from __future__ import annotations

from datetime import date
import math
import numpy as np
import pandas as pd


def _num(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else np.nan
    except Exception:
        return np.nan


def _clip(x, lo=0, hi=100):
    try: return float(max(lo,min(hi,float(x))))
    except Exception: return np.nan


def _parse_price(text):
    if text is None: return np.nan
    try:
        s=str(text).replace('$','').replace(',','').replace('<','').replace('>','').strip()
        if '–' in s: s=s.split('–')[0].strip()
        if '-' in s and s.count('-')==1 and not s.startswith('-'): s=s.split('-')[0].strip()
        return float(s)
    except Exception:
        return np.nan


def revision_research_snapshot(analyst: dict | None, event: dict | None=None) -> dict:
    """Turn raw Yahoo analyst fields into a sell-side style revisions/catalyst read."""
    analyst=analyst or {}; event=event or {}
    score=_num(analyst.get('EPS_Revision_Score'))
    upside=_num(analyst.get('Price_Target_Upside_%'))
    surprise=_num(analyst.get('Earnings_Surprise_%'))
    count=_num(analyst.get('Analyst_Count'))
    rev_velocity=_num(analyst.get('Revision_Velocity_%'))
    target_disp=_num(analyst.get('Target_Dispersion_%'))
    beat_rate=_num(analyst.get('Historical_Beat_Rate_%'))
    management=_num(analyst.get('Management_Execution_Score'))
    direction=str(analyst.get('Revision_Direction','N/D')).upper()
    days=event.get('days_to_earnings')
    event_risk=str(event.get('risk','UNKNOWN')).upper()

    momentum='N/D'
    if pd.notna(score):
        momentum='STRONG POSITIVE' if score>=72 else 'POSITIVE' if score>=60 else 'NEGATIVE' if score<=40 else 'NEUTRAL'
    target_view='N/D'
    if pd.notna(upside):
        target_view='LARGE UPSIDE' if upside>=25 else 'UPSIDE' if upside>=10 else 'FAIRLY PRICED' if upside>-10 else 'DOWNSIDE'
    surprise_view='N/D'
    if pd.notna(surprise):
        surprise_view='POSITIVE SURPRISE' if surprise>3 else 'NEGATIVE SURPRISE' if surprise<-3 else 'IN LINE'

    evidence=[]
    if direction=='IMPROVING': evidence.append('estimate revisions are improving')
    elif direction=='DETERIORATING': evidence.append('estimate revisions are deteriorating')
    if pd.notna(upside): evidence.append(f'consensus target implies {upside:.1f}% upside/downside')
    if pd.notna(surprise): evidence.append(f'latest reported earnings surprise was {surprise:.1f}%')
    if days is not None: evidence.append(f'earnings are {days} days away')

    # Confidence reflects evidence breadth, not bullishness.
    # Preserve the original five-field research-confidence contract. New V9 fields add depth
    # but do not dilute confidence when the original core evidence set is complete.
    observed=sum(pd.notna(x) for x in [score,upside,surprise,count]) + int(days is not None)
    confidence=round(observed/5*100)
    extended_observed=sum(pd.notna(x) for x in [score,upside,surprise,count,rev_velocity,target_disp,beat_rate,management]) + int(days is not None)
    extended_coverage=round(extended_observed/9*100)
    return {
        'Revision_Momentum':momentum,
        'Consensus_Target_View':target_view,
        'Latest_Surprise_View':surprise_view,
        'Revision_Research_Score':score,
        'Target_Upside_%':upside,
        'Latest_Earnings_Surprise_%':surprise,
        'Analyst_Count':count,
        'Revision_Velocity_%':rev_velocity,
        'Target_Dispersion_%':target_disp,
        'Historical_Beat_Rate_%':beat_rate,
        'Management_Execution_Score':management,
        'Days_to_Earnings':days,
        'Event_Risk':event_risk,
        'Revision_Research_Confidence_%':confidence,
        'Extended_Expectations_Coverage_%':extended_coverage,
        'Revision_Evidence':evidence,
    }


def catalyst_map(eq: dict | None, analyst: dict | None=None, event: dict | None=None, news: pd.DataFrame | None=None) -> dict:
    """Build a catalyst/risk map from industry model + scheduled earnings + recent news.

    News is shown as evidence only; no NLP sentiment is fabricated when source text is
    insufficient. The industry engine remains the structural catalyst source.
    """
    eq=eq or {}; analyst=analyst or {}; event=event or {}
    structural=list(eq.get('Key_Catalysts',[]) or [])
    risks=list(eq.get('Key_Risks',[]) or [])
    dated=[]
    d=event.get('days_to_earnings')
    ne=event.get('next_earnings','N/D')
    if d is not None and d>=0:
        dated.append({'Catalyst':'Quarterly earnings','Date':ne,'Days':d,'Type':'EARNINGS','Impact':'HIGH' if d<=7 else 'MEDIUM'})
    headlines=[]
    if isinstance(news,pd.DataFrame) and not news.empty:
        title_col=next((c for c in news.columns if str(c).lower() in {'title','headline'}),None)
        date_col=next((c for c in news.columns if 'date' in str(c).lower() or 'time' in str(c).lower()),None)
        if title_col:
            for _,r in news.head(8).iterrows():
                title=str(r.get(title_col,''))[:180]
                if title: headlines.append({'Headline':title,'Date':str(r.get(date_col,''))[:19] if date_col else ''})
    risk_level='HIGH' if str(event.get('risk','')).upper()=='HIGH' else 'ELEVATED' if str(event.get('risk','')).upper()=='ELEVATED' else 'NORMAL'
    return {
        'Structural_Catalysts':structural,
        'Structural_Risks':risks,
        'Dated_Catalysts':dated,
        'Recent_News_Evidence':headlines,
        'Near_Term_Catalyst_Risk':risk_level,
        'Catalyst_Coverage_%':round(100*(bool(structural)+bool(risks)+bool(dated)+bool(headlines))/4),
    }


def peer_benchmark_snapshot(row: dict | pd.Series, universe: pd.DataFrame | None) -> dict:
    """Benchmark a company against the best available comparable peer set.

    Priority is exact professional business model, then industry, then sector, and
    finally the enriched universe. This prevents a valid company from receiving an
    empty peer rank merely because only one exact-model peer survived the screener.
    The chosen comparison source is always exposed for auditability.
    """
    r=dict(row)
    key=str(r.get('Equity_Model_Key','generic'))
    out={'Peer_Group_Key':key,'Peer_Count':0,'Peer_Rank_Peer_Count':0,'Peer_Rank_Source':'UNAVAILABLE',
         'Peer_Rank_Score':np.nan,'Peer_Quality_Percentile':np.nan,
         'Peer_Valuation_Percentile':np.nan,'Peer_Revisions_Percentile':np.nan,'Peer_RS_Percentile':np.nan,
         'Peer_Summary':'Insufficient comparable companies in current screener universe.','Peer_Table':pd.DataFrame()}
    if universe is None or not isinstance(universe,pd.DataFrame) or universe.empty:
        return out

    base=universe.copy()
    if 'Ticker' in base and r.get('Ticker') is not None:
        base=base[base['Ticker'].astype(str)!=str(r.get('Ticker'))]

    def _clean(v):
        v=str(v or '').strip()
        return '' if v.lower() in {'','nan','none','n/d','unknown'} else v

    candidates=[]
    if 'Equity_Model_Key' in base.columns and _clean(key) and key.lower()!='generic':
        candidates.append(('MODEL',base[base['Equity_Model_Key'].astype(str)==key].copy()))
    industry=_clean(r.get('Industry'))
    if industry and 'Industry' in base.columns:
        candidates.append(('INDUSTRY',base[base['Industry'].astype(str)==industry].copy()))
    sector=_clean(r.get('Sector'))
    if sector and 'Sector' in base.columns:
        candidates.append(('SECTOR',base[base['Sector'].astype(str)==sector].copy()))
    candidates.append(('UNIVERSE',base.copy()))

    metrics=[('Quality_Score','Peer_Quality_Percentile'),('Valuation_Score','Peer_Valuation_Percentile'),
             ('Revision_Score','Peer_Revisions_Percentile'),('RS_Percentile','Peer_RS_Percentile')]

    chosen=None
    for source,g in candidates:
        if g is None or len(g)<2:
            continue
        comparable_metrics=0
        for col,_ in metrics:
            if col in g.columns and pd.notna(_num(r.get(col))) and pd.to_numeric(g[col],errors='coerce').notna().sum()>=2:
                comparable_metrics+=1
        if comparable_metrics:
            chosen=(source,g)
            break
    if chosen is None:
        return out

    source,g=chosen
    out['Peer_Count']=len(g)
    out['Peer_Rank_Peer_Count']=len(g)
    out['Peer_Rank_Source']=source
    percentiles=[]
    for col,label in metrics:
        if col not in g.columns or pd.isna(_num(r.get(col))):
            continue
        vals=pd.to_numeric(g[col],errors='coerce').dropna()
        if len(vals)<2:
            continue
        x=float(r.get(col)); pct=(vals<x).sum()/len(vals)*100 + (vals==x).sum()/len(vals)*50
        pct=float(_clip(pct)); out[label]=round(pct); percentiles.append(pct)
    if percentiles:
        out['Peer_Rank_Score']=round(float(np.mean(percentiles)))
        relative='Above peer median.' if out['Peer_Rank_Score']>=60 else 'Below peer median.' if out['Peer_Rank_Score']<40 else 'Near peer median.'
        out['Peer_Summary']=f'{relative} Comparison source: {source.lower()} ({len(g)} peers).'
    cols=[c for c in ['Ticker','Equity_Model','Industry','Sector','Quality_Score','Valuation_Score','Revision_Score','RS_Percentile','Opportunity_Score','Forward_PE','EV_EBITDA','FCF_Yield'] if c in g.columns]
    sort_cols=[c for c in ['Opportunity_Score','Quality_Score'] if c in g.columns]
    out['Peer_Table']=g[cols].sort_values(sort_cols,ascending=False).head(12) if cols and sort_cols else (g[cols].head(12) if cols else pd.DataFrame())
    return out


def scenario_valuation(row: dict | pd.Series, fund: dict | None=None, analyst: dict | None=None, eq: dict | None=None) -> dict:
    """Create explicit bear/base/bull price scenarios with transparent assumptions.

    This is not a DCF. With free standardized data the engine uses market structure,
    volatility, consensus targets and business/revision quality to construct a
    reproducible scenario range. It labels the method so users do not mistake it for
    intrinsic value precision.
    """
    r=dict(row); fund=fund or {}; analyst=analyst or {}; eq=eq or {}
    price=_num(r.get('Price'))
    if pd.isna(price) or price<=0:
        return {'Scenario_Method':'Unavailable','Scenario_Coverage_%':0,'Scenarios':pd.DataFrame(),'Expected_Value':np.nan}
    stop=_parse_price(r.get('Invalidation'))
    target=_parse_price(r.get('Target'))
    target_up=_num(analyst.get('Price_Target_Upside_%'))
    quality=_num(r.get('Quality_Score')); revisions=_num(r.get('Revision_Score')); trend=_num(r.get('Trend_Score')); macro=_num(r.get('Macro_Fit'))
    risk=_num(r.get('Risk_Score'))
    # Estimate a sensible downside floor from technical invalidation, otherwise 15%.
    bear=stop if pd.notna(stop) and 0<stop<price else price*.85
    # Base starts from setup target; consensus is admitted only as a secondary anchor.
    consensus=price*(1+target_up/100) if pd.notna(target_up) else np.nan
    anchors=[x for x in [target,consensus] if pd.notna(x) and x>price*.8]
    base=float(np.mean(anchors)) if anchors else price*1.12
    # Bull case scales with quality/revisions/trend but is capped to avoid fantasy targets.
    strength=np.nanmean([x for x in [quality,revisions,trend,macro] if pd.notna(x)]) if any(pd.notna(x) for x in [quality,revisions,trend,macro]) else 55
    bull_premium=.12 + max(0,strength-50)/100*.35
    bull=max(base*1.08, price*(1+bull_premium))
    bull=min(bull,price*1.80)
    bear=max(price*.55,min(bear,price*.97))
    base=max(price*.90,min(base,price*1.50))

    # Probabilities depend on evidence, but never become certainty.
    edge=(np.nanmean([x for x in [quality,revisions,trend,macro,risk] if pd.notna(x)])-50)/50 if any(pd.notna(x) for x in [quality,revisions,trend,macro,risk]) else 0
    bull_prob=_clip(30+edge*15,20,50); bear_prob=_clip(25-edge*10,15,40); base_prob=100-bull_prob-bear_prob
    if str(r.get('Event_Risk','')).upper()=='HIGH': bear_prob=min(45,bear_prob+5); bull_prob=max(15,bull_prob-3); base_prob=100-bull_prob-bear_prob
    scenarios=pd.DataFrame([
        {'Scenario':'Bear','Price':round(bear,2),'Return_%':round((bear/price-1)*100,1),'Probability_%':round(bear_prob,1),'Interpretation':'Thesis invalidation / adverse operating or macro outcome'},
        {'Scenario':'Base','Price':round(base,2),'Return_%':round((base/price-1)*100,1),'Probability_%':round(base_prob,1),'Interpretation':'Current thesis executes without heroic assumptions'},
        {'Scenario':'Bull','Price':round(bull,2),'Return_%':round((bull/price-1)*100,1),'Probability_%':round(bull_prob,1),'Interpretation':'Positive revisions/catalysts plus multiple or cycle support'},
    ])
    ev=float((scenarios['Price']*scenarios['Probability_%']/100).sum())
    downside=(price-bear)/price*100; upside=(base-price)/price*100
    asym=upside/downside if downside>0 else np.nan
    observed=sum(pd.notna(x) for x in [stop,target,target_up,quality,revisions,trend,macro,risk])
    coverage=round(observed/8*100)
    return {
        'Scenario_Method':'Market-structure + consensus + factor-conditioned scenario analysis (not a DCF)',
        'Scenario_Coverage_%':coverage,
        'Scenarios':scenarios,
        'Bear_Price':round(bear,2),'Base_Price':round(base,2),'Bull_Price':round(bull,2),
        'Expected_Value':round(ev,2),'Expected_Return_%':round((ev/price-1)*100,1),
        'Base_Risk_Reward':round(asym,2) if pd.notna(asym) else np.nan,
        'Scenario_Note':'Scenario prices are decision ranges, not guaranteed targets. Specialist valuation methods remain primary when the required data are available.'
    }


def professional_research_snapshot(row, fund=None, analyst=None, event=None, eq=None, universe=None, news=None):
    rev=revision_research_snapshot(analyst,event)
    peers=peer_benchmark_snapshot(row,universe)
    cats=catalyst_map(eq,analyst,event,news)
    scen=scenario_valuation(row,fund,analyst,eq)
    return {'Revisions':rev,'Peers':peers,'Catalysts':cats,'Scenarios':scen}
