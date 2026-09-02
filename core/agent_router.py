"""Deterministic event-to-agent routing for the shadow Investment Desk."""
from __future__ import annotations

TECHNICAL_EVENTS={'strong_candidate','abnormal_volume','large_price_move','technical_score_change','technical_state_change'}
FUNDAMENTAL_EVENTS={'fundamental_change','fundamental_event'}
MARKET_EVENTS={'market_regime_change','snapshot_stale','snapshot_status_unknown'}


def route_events(events):
    ticker_agents={}; global_agents=set(); rationale=[]
    for event in events or []:
        ticker=str(event.get('ticker','')).upper(); types=set(event.get('event_types') or [])
        agents=set(); event_globals=set()
        if types & TECHNICAL_EVENTS: agents.add('technical')
        if types & FUNDAMENTAL_EVENTS: agents.add('fundamental')
        if types & MARKET_EVENTS: event_globals.add('market')
        move=abs(float((event.get('metrics') or {}).get('price_move_pct') or 0))
        if 'large_price_move' in types and move>=7: agents.add('fundamental')
        if event.get('portfolio') and agents: event_globals.add('portfolio')
        if 'large_price_move' in types: event_globals.update({'market','portfolio'})
        global_agents.update(event_globals)
        if ticker and ticker!='MARKET' and agents:
            ticker_agents.setdefault(ticker,set()).update(agents)
        rationale.append({'ticker':ticker,'event_types':sorted(types),'agents':sorted(agents | event_globals)})
    return {
        'ticker_agents':{ticker:sorted(agents) for ticker,agents in ticker_agents.items()},
        'global_agents':sorted(global_agents),
        'verification':bool(events),'cio':bool(events),'rationale':rationale,
        'shadow_mode':True,
    }


def full_review_plan(tickers):
    return {
        'ticker_agents':{str(t).upper():['technical','fundamental'] for t in tickers},
        'global_agents':['market','portfolio'],'verification':True,'cio':True,
        'rationale':[{'reason':'full_manual_or_daily_review'}],'shadow_mode':True,
    }
