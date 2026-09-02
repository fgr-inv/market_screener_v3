"""Investment Desk watchlist ranking: specialist evidence + verification + portfolio fit."""
from __future__ import annotations

ACCEPTED={'VERIFIED','PARTIALLY_VERIFIED'}

def build_watchlist(results, portfolio_result=None, sectors=None, limit=15, market_result=None):
    sectors=sectors or {}; grouped={}
    for r in results or []:
        d=r.to_dict() if hasattr(r,'to_dict') else dict(r)
        subject=str(d.get('subject','')).upper()
        if not subject or subject=='PORTFOLIO': continue
        grouped.setdefault(subject,{})[d.get('agent','Unknown')]=d
    from core.portfolio_risk_agent import portfolio_fit_for_candidate
    market_meta={} if market_result is None else (getattr(market_result,'metadata',{}) or {})
    sector_market_scores=market_meta.get('sector_scores',{}) or {}
    market_state=str(getattr(market_result,'state','') or '')
    rows=[]
    for ticker,agents in grouped.items():
        tech=agents.get('Technical Signal'); fund=agents.get('Fundamental & Catalyst')
        if not tech and not fund: continue
        verified=[x for x in (tech,fund) if x and x.get('verification_status') in ACCEPTED]
        if not verified: continue
        t_conf=float((tech or {}).get('confidence') or 0); f_conf=float((fund or {}).get('confidence') or 0)
        tech_bonus={'SETUP':1.0,'WATCH':.65,'NO_SETUP':.25,'BROKEN_SETUP':.05}.get((tech or {}).get('state'),.35)
        fund_bonus={'IMPROVING':1.0,'INTACT':.75,'MIXED':.4,'DETERIORATING':.1,'UNAVAILABLE':0}.get((fund or {}).get('state'),.35)
        specialist=(.55*(t_conf*tech_bonus)+.45*(f_conf*fund_bonus)) if tech and fund else (t_conf*tech_bonus if tech else f_conf*fund_bonus)
        fit,fit_note=portfolio_fit_for_candidate(ticker,sectors.get(ticker,'Unknown'),portfolio_result)
        sector_name=sectors.get(ticker,'Unknown')
        raw_sector_score=sector_market_scores.get(sector_name)
        try: market_fit=max(0,min(1,float(raw_sector_score)/100)) if raw_sector_score is not None else .5
        except Exception: market_fit=.5
        # Market is context, not a trade trigger: keep its weight deliberately small.
        score=100*(.70*specialist+.20*fit+.10*market_fit)
        if market_state=='RISK_OFF' and (tech or {}).get('state')=='SETUP': score-=2
        contradictions=sum(len((x or {}).get('contradicting_evidence',[]) or []) for x in (tech,fund))
        score=max(0,score-contradictions*3)
        rows.append({'Ticker':ticker,'Priority Score':round(score,1),'Technical':(tech or {}).get('state','NOT_CHECKED'),
                     'Fundamental':(fund or {}).get('state','NOT_CHECKED'),'Portfolio Fit':round(fit*100,0),
                     'Portfolio Note':fit_note,'Market Fit':round(market_fit*100,0),'Verified Specialists':len(verified),'Contradictions':contradictions})
    rows.sort(key=lambda x:x['Priority Score'],reverse=True)
    for i,row in enumerate(rows[:limit],1): row['Rank']=i
    return rows[:limit]
