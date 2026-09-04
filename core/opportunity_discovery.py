"""Daily opportunity discovery and persistent desk-watchlist helpers.

The discovery layer is deliberately staged.  It ranks the broad, cheap daily
snapshot first and sends only a small, diversified shortlist to the expensive
specialist review.  Nothing in this module creates an order or a position.
"""
from __future__ import annotations

import math
import pandas as pd


def _num(value, default=None):
    try:
        value=float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _text(value, default=''):
    if value is None or (not isinstance(value,str) and pd.isna(value)):
        return default
    return str(value).strip()


def _truthy(value):
    if value is None or (not isinstance(value,str) and pd.isna(value)): return False
    if isinstance(value,str): return value.strip().lower() in {'1','true','yes','y'}
    return bool(value)


def _candidate_score(row):
    """Evidence-aware cheap score; missing inputs are reweighted, not invented."""
    components={
        'Preliminary':(_num(row.get('Preliminary_Score')),.25),
        'Entry':(_num(row.get('Entry_Score')),.18),
        'Trend':(_num(row.get('Trend_Score')),.12),
        'Emerging trend':(_num(row.get('Emerging_Trend_Score')),.15),
        'Relative strength':(_num(row.get('RS_Percentile')),.10),
        'Risk':(_num(row.get('Risk_Score')),.08),
        'Confidence':(_num(row.get('Confidence_Score')),.07),
        'Sector':(_num(row.get('Sector_Score')),.05),
    }
    observed=[(value,weight) for value,weight in components.values() if value is not None]
    if not observed:
        return None,0
    coverage=sum(weight for _,weight in observed)
    score=sum(value*weight for value,weight in observed)/coverage
    rr=_num(row.get('RR'))
    event=_text(row.get('Event_Risk')).upper()
    action=_text(row.get('Action')).upper()
    if rr is not None and rr<1.25: score-=12
    elif rr is not None and rr>=2.0: score+=3
    if event in {'HIGH','HIGH_RISK'}: score-=25
    elif event=='ELEVATED': score-=7
    if _truthy(row.get('Scan_Extended_Trim',False)): score-=15
    if 'BUY ZONE' in action or action=='BREAKOUT': score+=4
    elif action in {'AVOID','EVENT RISK — WAIT','LOW CONFIDENCE — WAIT'}: score-=15
    return round(max(0,min(100,score)),1),round(coverage*100)


def discover_daily_candidates(snapshot, portfolio_tickers=None, max_candidates=18,
                              max_per_sector=3, minimum_score=60,max_per_universe=10,
                              minimum_per_size_segment=2):
    """Return a diversified shortlist from the latest broad equity snapshot.

    Hard gates favor omission over a false positive. Portfolio names are marked
    and remain eligible, but new ideas win ties so the hunt can actually discover.
    """
    if snapshot is None or snapshot.empty or 'Ticker' not in snapshot.columns:
        return {'status':'NO_SNAPSHOT','universe_rows':0,'eligible_rows':0,'candidates':[],
                'rejection_counts':{}}
    portfolio={str(t).upper().strip() for t in (portfolio_tickers or []) if str(t).strip()}
    rows=[]; rejected={}
    for _,raw in snapshot.iterrows():
        ticker=_text(raw.get('Ticker')).upper()
        if not ticker:
            rejected['missing_ticker']=rejected.get('missing_ticker',0)+1; continue
        score,coverage=_candidate_score(raw)
        entry=_num(raw.get('Entry_Score')); trend=_num(raw.get('Trend_Score'))
        emerging=_num(raw.get('Emerging_Trend_Score'))
        phase=_text(raw.get('Trend_Phase'),'NO_QUALIFIED_SETUP').upper()
        early_track=bool(emerging is not None and emerging>=62 and
                         phase in {'BASE_NEAR_BREAKOUT','EARLY_ACCELERATION','BREAKOUT_CONFIRMED'})
        risk=_num(raw.get('Risk_Score')); confidence=_num(raw.get('Confidence_Score'))
        event=_text(raw.get('Event_Risk')).upper(); action=_text(raw.get('Action')).upper()
        reason=None
        if score is None or coverage<55: reason='insufficient_evidence'
        elif event in {'HIGH','HIGH_RISK'}: reason='high_event_risk'
        elif _truthy(raw.get('Scan_Extended_Trim',False)): reason='extended'
        elif entry is None or entry<(50 if early_track else 55): reason='weak_entry'
        elif trend is None or trend<(45 if early_track else 55): reason='weak_trend'
        elif risk is not None and risk<40: reason='weak_risk_reward'
        elif confidence is not None and confidence<45: reason='low_confidence'
        elif action in {'AVOID','EVENT RISK — WAIT','LOW CONFIDENCE — WAIT'}: reason='blocked_action'
        elif score<minimum_score: reason='below_threshold'
        if reason:
            rejected[reason]=rejected.get(reason,0)+1; continue
        sector=_text(raw.get('Sector'),'Other') or 'Other'
        why=[f'discovery score {score:.1f}',f'entry {entry:.0f}',f'trend {trend:.0f}']
        rs=_num(raw.get('RS_Percentile'))
        if rs is not None: why.append(f'RS percentile {rs:.0f}')
        if emerging is not None: why.append(f'emerging trend {emerging:.0f} ({phase.lower().replace("_"," ")})')
        rows.append({
            'Ticker':ticker,'Sector':sector,'Discovery Score':score,
            'Universe Source':_text(raw.get('Universe Source'),'Unknown'),
            'Liquidity Tier':_text(raw.get('Liquidity Tier'),'N/D'),
            'Average Dollar Volume 20d':_num(raw.get('Average Dollar Volume 20d')),
            'Market Cap':_num(raw.get('Market Cap')),
            'Cap Segment':_text(raw.get('Cap Segment'),'Unknown'),
            'Entry Score':round(entry,1),'Trend Score':round(trend,1),
            'Emerging Trend Score':None if emerging is None else round(emerging,1),
            'Trend Phase':phase,
            'Discovery Track':'EARLY TREND' if early_track else 'ESTABLISHED TREND',
            'Breakout Proximity %':_num(raw.get('Breakout_Proximity_%')),
            'Momentum Acceleration':_num(raw.get('Momentum_Acceleration')),
            'Accumulation Score':_num(raw.get('Accumulation_Score')),
            'Risk Score':None if risk is None else round(risk,1),
            'Confidence':None if confidence is None else round(confidence,1),
            'RS Percentile':None if rs is None else round(rs,1),
            'RR':_num(raw.get('RR')),'Action':_text(raw.get('Action'),'N/D'),
            'Snapshot Coverage %':coverage,'Current Holding':ticker in portfolio,
            'Expanded Universe Candidate':_text(raw.get('Universe Source')) not in {'S&P 500','Nasdaq 100'},
            'Why shortlisted':' · '.join(why),
        })
    rows.sort(key=lambda row:(row['Discovery Score'],not row['Current Holding']),reverse=True)
    selected=[]; sector_counts={}; universe_counts={}; deferred=[]; selected_tickers=set()

    def include(row):
        sector=row['Sector']; source=row.get('Universe Source','Unknown')
        if row['Ticker'] in selected_tickers or sector_counts.get(sector,0)>=int(max_per_sector): return False
        if universe_counts.get(source,0)>=int(max_per_universe): return False
        selected.append(row); selected_tickers.add(row['Ticker'])
        sector_counts[sector]=sector_counts.get(sector,0)+1
        universe_counts[source]=universe_counts.get(source,0)+1
        return True

    # Reserve representation for qualified mid/small-cap evidence. The reserve
    # never lowers a score, liquidity, risk or verification gate.
    for segment in ('Mid Cap','Small Cap'):
        used=0
        for row in rows:
            if row.get('Cap Segment')!=segment: continue
            if include(row): used+=1
            if used>=int(minimum_per_size_segment) or len(selected)>=int(max_candidates): break
    for row in rows:
        if row['Ticker'] in selected_tickers: continue
        sector=row['Sector']; source=row.get('Universe Source','Unknown'); used=sector_counts.get(sector,0)
        if used>=int(max_per_sector):
            rejected['sector_diversification']=rejected.get('sector_diversification',0)+1
            continue
        if universe_counts.get(source,0)>=int(max_per_universe):
            deferred.append(row)
            continue
        include(row)
        if len(selected)>=int(max_candidates): break
    # If other sources did not produce enough qualified names, refill from the
    # deferred source without lowering any evidence or liquidity gate.
    if len(selected)<int(max_candidates):
        for row in deferred:
            if row['Ticker'] in selected_tickers: continue
            sector=row['Sector']
            if sector_counts.get(sector,0)>=int(max_per_sector): continue
            selected.append(row); selected_tickers.add(row['Ticker']); sector_counts[sector]=sector_counts.get(sector,0)+1
            if len(selected)>=int(max_candidates): break
    if deferred:
        selected_tickers={row['Ticker'] for row in selected}
        rejected['universe_diversification']=sum(row['Ticker'] not in selected_tickers for row in deferred)
    selected.sort(key=lambda row:row['Discovery Score'],reverse=True)
    for rank,row in enumerate(selected,1): row['Discovery Rank']=rank
    cap_counts={str(key):int(value) for key,value in snapshot.get('Cap Segment',pd.Series(dtype=str)).value_counts().items()}
    phase_counts={str(key):int(value) for key,value in snapshot.get('Trend_Phase',pd.Series(dtype=str)).value_counts().items()}
    return {
        'status':'SHORTLIST_READY' if selected else 'NO_QUALIFIED_CANDIDATES',
        'universe_rows':int(len(snapshot)),'eligible_rows':len(rows),'candidates':selected,
        'cap_segment_counts':cap_counts,'trend_phase_counts':phase_counts,
        'rejection_counts':rejected,
        'policy':{'minimum_score':minimum_score,'max_candidates':max_candidates,
                  'max_per_sector':max_per_sector,'max_per_universe':max_per_universe,
                  'minimum_per_size_segment':minimum_per_size_segment,
                  'deep_review_required':True},
    }


def qualify_verified_opportunities(watchlist, shortlist=None, minimum_priority=60):
    """Label only two-specialist, non-conflicting rows as verified opportunities."""
    discovery={str(r.get('Ticker','')).upper():r for r in (shortlist or [])}
    qualified=[]
    for raw in watchlist or []:
        row=dict(raw); ticker=_text(row.get('Ticker')).upper()
        if float(_num(row.get('Priority Score'),0))<minimum_priority: continue
        if int(_num(row.get('Verified Specialists'),0))<2: continue
        if int(_num(row.get('Contradictions'),0))>1: continue
        if _text(row.get('Technical')).upper() not in {'SETUP','WATCH'}: continue
        if _text(row.get('Fundamental')).upper() not in {'IMPROVING','INTACT'}: continue
        seed=discovery.get(ticker,{})
        row['Discovery Score']=seed.get('Discovery Score')
        row['Sector']=seed.get('Sector','Other')
        row['Universe Source']=seed.get('Universe Source','Unknown')
        row['Liquidity Tier']=seed.get('Liquidity Tier','N/D')
        row['Average Dollar Volume 20d']=seed.get('Average Dollar Volume 20d')
        row['Market Cap']=seed.get('Market Cap')
        row['Cap Segment']=seed.get('Cap Segment','Unknown')
        row['Entry Score']=seed.get('Entry Score')
        row['Trend Score']=seed.get('Trend Score')
        row['Emerging Trend Score']=seed.get('Emerging Trend Score')
        row['Trend Phase']=seed.get('Trend Phase')
        row['Discovery Track']=seed.get('Discovery Track')
        row['RR']=seed.get('RR')
        row['Opportunity Status']='VERIFIED_CANDIDATE'
        row['Approval Boundary']='Research only — user decides whether to act.'
        qualified.append(row)
    qualified.sort(key=lambda row:float(row.get('Priority Score') or 0),reverse=True)
    for rank,row in enumerate(qualified,1): row['Opportunity Rank']=rank
    return qualified


def _payload_tickers(payload):
    discovery=(payload or {}).get('discovery') or {}
    groups=[discovery.get('monitor_tickers') or [],discovery.get('verified_opportunities') or [],
            (payload or {}).get('watchlist') or [],((payload or {}).get('brief') or {}).get('top_opportunities') or []]
    out=[]
    for group in groups:
        for item in group:
            ticker=item if isinstance(item,str) else item.get('Ticker')
            ticker=_text(ticker).upper()
            if ticker and ticker not in out: out.append(ticker)
    return out


def load_active_watchlist_tickers(user_id, limit=30, loader=None):
    """Load the durable generated watchlist used by the 15-minute market monitor."""
    if loader is None:
        from core.desk_store import load_latest_desk_output
        loader=load_latest_desk_output
    tickers=[]
    for output_type in ('daily_opportunity_hunt','daily_cio_brief','scheduled_review'):
        record=loader(user_id,output_type) or {}
        for ticker in _payload_tickers(record.get('payload') or {}):
            if ticker not in tickers: tickers.append(ticker)
            if len(tickers)>=int(limit): return tickers
    return tickers
