"""Headless Investment Desk orchestrator used by UI and scheduled workers."""
from __future__ import annotations
from core.market_data import download_prices
from core.storage import load_positions,load_json_snapshot,load_latest_snapshot
from core.technical_agent import analyze_technical
from core.fundamental_agent import analyze_fundamental
from core.portfolio_risk_agent import analyze_portfolio_risk
from core.market_regime_agent import analyze_market_regime
from core.watchlist_engine import build_watchlist
from core.verification_agent import verify_result
from core.cio_agent import build_cio_brief
from core.agent_audit import append_agent_audit
from core.desk_store import save_desk_output
from core.agent_router import full_review_plan

def run_desk_review(user_id,tickers,force_fundamental=False,output_type='shadow_review',max_tickers=25,
                    agent_plan=None,events=None,run_key=None):
    uid=str(user_id or 'local-user'); tickers=list(dict.fromkeys(str(x).upper().strip() for x in tickers if str(x).strip()))[:max_tickers]
    plan=agent_plan or full_review_plan(tickers); ticker_agents=plan.get('ticker_agents') or {}; global_agents=set(plan.get('global_agents') or [])
    pos=load_positions(user_id=uid); position_ticks=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
    needs_prices='portfolio' in global_agents or any('technical' in agents for agents in ticker_agents.values())
    price_ticks=list(ticker_agents) + (position_ticks if 'portfolio' in global_agents else [])
    all_ticks=list(dict.fromkeys(price_ticks)); histories=download_prices(all_ticks,period='2y',max_age_minutes=15) if needs_prices and all_ticks else {}
    verified=[]
    append_agent_audit(uid,'events_received',{'events':events or [],'run_key':run_key,'shadow_mode':True})
    append_agent_audit(uid,'agent_router_plan',plan)
    market=None
    if 'market' in global_agents:
        append_agent_audit(uid,'agent_invoked',{'agent':'market','subject':'MARKET','run_key':run_key})
        market=verify_result(analyze_market_regime(load_json_snapshot('latest_macro'),load_latest_snapshot('latest_sectors'),load_json_snapshot('latest_meta')))
        verified.append(market); append_agent_audit(uid,'scheduled_specialist_verified',market.to_dict())
    portfolio=None
    if 'portfolio' in global_agents:
        append_agent_audit(uid,'agent_invoked',{'agent':'portfolio','subject':'PORTFOLIO','run_key':run_key})
        portfolio=verify_result(analyze_portfolio_risk(pos,histories)); verified.append(portfolio)
        append_agent_audit(uid,'scheduled_specialist_verified',portfolio.to_dict())
    for ticker in tickers:
        agents=set(ticker_agents.get(ticker,[]))
        if 'technical' in agents:
            append_agent_audit(uid,'agent_invoked',{'agent':'technical','subject':ticker,'run_key':run_key})
            result=verify_result(analyze_technical(ticker,histories.get(ticker)))
            verified.append(result); append_agent_audit(uid,'scheduled_specialist_verified',result.to_dict())
        if 'fundamental' in agents:
            append_agent_audit(uid,'agent_invoked',{'agent':'fundamental','subject':ticker,'run_key':run_key})
            result=verify_result(analyze_fundamental(ticker,force_refresh=force_fundamental))
            verified.append(result); append_agent_audit(uid,'scheduled_specialist_verified',result.to_dict())
    sectors={}
    if not pos.empty: sectors.update({str(r['ticker']).upper():str(r.get('sector','Unknown') or 'Unknown') for _,r in pos.iterrows()})
    watchlist=build_watchlist(verified,portfolio,sectors=sectors,limit=15,market_result=market)
    brief=build_cio_brief(verified,watchlist=watchlist,events=events)
    payload={'shadow_mode':True,'tickers':tickers,'events':events or [],'routing':plan,
             'agents_invoked':[{'agent':r.agent,'subject':r.subject} for r in verified],
             'market':None if market is None else market.to_dict(),
             'portfolio':None if portfolio is None else portfolio.to_dict(),'watchlist':watchlist,'brief':brief}
    append_agent_audit(uid,'scheduled_cio_brief',{'headline':brief['headline'],'material':brief['material'],'tickers':tickers,'run_key':run_key,'shadow_mode':True})
    save_desk_output(uid,output_type,payload,run_key=run_key)
    return payload
