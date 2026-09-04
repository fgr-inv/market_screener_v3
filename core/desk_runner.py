"""Headless Investment Desk orchestrator used by UI and scheduled workers."""
from __future__ import annotations
import pandas as pd
from core.market_data import download_prices
from core.storage import load_positions,load_theses,load_json_snapshot,load_latest_snapshot
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
from core.shadow_validation import capture_shadow_decisions
from core.news_catalyst_agent import analyze_news_catalyst
from core.continuous_improvement import load_active_improvement_policy,apply_improvement_policy

def run_desk_review(user_id,tickers,force_fundamental=False,output_type='shadow_review',max_tickers=25,
                    agent_plan=None,events=None,run_key=None,candidate_sectors=None,news_by_ticker=None):
    uid=str(user_id or 'local-user'); tickers=list(dict.fromkeys(str(x).upper().strip() for x in tickers if str(x).strip()))[:max_tickers]
    plan=agent_plan or full_review_plan(tickers); ticker_agents=plan.get('ticker_agents') or {}; global_agents=set(plan.get('global_agents') or [])
    improvement_policy=load_active_improvement_policy(uid)
    automated=output_type in {'scheduled_review','daily_cio_brief','daily_opportunity_hunt','news_catalyst_review'} and bool(run_key)
    pos=load_positions(user_id=uid); position_ticks=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
    needs_prices='portfolio' in global_agents or any({'technical','news'} & set(agents) for agents in ticker_agents.values())
    price_ticks=list(ticker_agents) + (position_ticks if 'portfolio' in global_agents else [])
    if automated and ticker_agents: price_ticks.append('SPY')
    needs_prices=needs_prices or bool(automated and ticker_agents)
    all_ticks=list(dict.fromkeys(price_ticks)); histories=download_prices(all_ticks,period='2y',max_age_minutes=15) if needs_prices and all_ticks else {}
    verified=[]
    news_by_ticker={str(ticker).upper():list(rows or []) for ticker,rows in (news_by_ticker or {}).items()}
    thesis_rows=load_theses(user_id=uid) if any('news' in agents for agents in ticker_agents.values()) else None
    theses={} if thesis_rows is None or thesis_rows.empty else {str(r['ticker']).upper():r.to_dict() for _,r in thesis_rows.iterrows()}
    append_agent_audit(uid,'events_received',{'events':events or [],'run_key':run_key,'shadow_mode':True})
    append_agent_audit(uid,'agent_router_plan',plan)
    market=None
    if 'market' in global_agents:
        append_agent_audit(uid,'agent_invoked',{'agent':'market','subject':'MARKET','run_key':run_key})
        market=verify_result(apply_improvement_policy(
            analyze_market_regime(load_json_snapshot('latest_macro'),load_latest_snapshot('latest_sectors'),load_json_snapshot('latest_meta')),
            improvement_policy))
        verified.append(market); append_agent_audit(uid,'scheduled_specialist_verified',market.to_dict())
    portfolio=None
    if 'portfolio' in global_agents:
        append_agent_audit(uid,'agent_invoked',{'agent':'portfolio','subject':'PORTFOLIO','run_key':run_key})
        portfolio=verify_result(apply_improvement_policy(analyze_portfolio_risk(pos,histories),improvement_policy)); verified.append(portfolio)
        append_agent_audit(uid,'scheduled_specialist_verified',portfolio.to_dict())
    for ticker in tickers:
        agents=set(ticker_agents.get(ticker,[]))
        if 'technical' in agents:
            append_agent_audit(uid,'agent_invoked',{'agent':'technical','subject':ticker,'run_key':run_key})
            result=verify_result(apply_improvement_policy(analyze_technical(ticker,histories.get(ticker)),improvement_policy))
            verified.append(result); append_agent_audit(uid,'scheduled_specialist_verified',result.to_dict())
        if 'fundamental' in agents:
            append_agent_audit(uid,'agent_invoked',{'agent':'fundamental','subject':ticker,'run_key':run_key})
            result=verify_result(apply_improvement_policy(analyze_fundamental(ticker,force_refresh=force_fundamental),improvement_policy))
            verified.append(result); append_agent_audit(uid,'scheduled_specialist_verified',result.to_dict())
        if 'news' in agents:
            append_agent_audit(uid,'agent_invoked',{'agent':'news','subject':ticker,'run_key':run_key})
            result=verify_result(apply_improvement_policy(
                analyze_news_catalyst(ticker,news_by_ticker.get(ticker,[]),theses.get(ticker),ticker in position_ticks),
                improvement_policy))
            verified.append(result); append_agent_audit(uid,'scheduled_specialist_verified',result.to_dict())
    snapshot_context={}
    try:
        broad_snapshot=load_latest_snapshot('latest_screener')
        if broad_snapshot is not None and not broad_snapshot.empty and 'Ticker' in broad_snapshot:
            snapshot_context={str(row.get('Ticker','')).upper():row.to_dict()
                              for _,row in broad_snapshot.iterrows() if str(row.get('Ticker','')).strip()}
    except Exception:
        snapshot_context={}
    sectors={ticker:str(row.get('Sector') or 'Unknown') for ticker,row in snapshot_context.items()}
    sectors.update({str(ticker).upper():str(sector or 'Unknown')
                    for ticker,sector in (candidate_sectors or {}).items()})
    if not pos.empty: sectors.update({str(r['ticker']).upper():str(r.get('sector','Unknown') or 'Unknown') for _,r in pos.iterrows()})
    watchlist=build_watchlist(verified,portfolio,sectors=sectors,limit=15,market_result=market)
    context_columns=(('Universe Source','Universe Source'),('Liquidity Tier','Liquidity Tier'),
                     ('Average Dollar Volume 20d','Average Dollar Volume 20d'),
                     ('Entry_Score','Entry Score'),('Trend_Score','Trend Score'),('RR','RR'))
    for row in watchlist:
        context=snapshot_context.get(str(row.get('Ticker','')).upper()) or {}
        for source,target in context_columns:
            value=context.get(source)
            if value is not None and pd.notna(value):
                row.setdefault(target,value)
    brief=build_cio_brief(verified,watchlist=watchlist,events=events)
    shadow_capture=(capture_shadow_decisions(uid,run_key,brief,histories) if automated else
                    {'status':'NOT_CHECKED','created':[],'skipped':0,'reason':'manual/non-automated review'})
    payload={'shadow_mode':True,'tickers':tickers,'events':events or [],'routing':plan,
             'agents_invoked':[{'agent':r.agent,'subject':r.subject} for r in verified],
             'market':None if market is None else market.to_dict(),
             'portfolio':None if portfolio is None else portfolio.to_dict(),'watchlist':watchlist,'brief':brief,
             'news_by_ticker':news_by_ticker,
             'shadow_decision_capture':shadow_capture}
    append_agent_audit(uid,'shadow_decisions_captured',{'run_key':run_key,'status':shadow_capture.get('status'),
                       'created':[r.get('decision_key') for r in shadow_capture.get('created',[])],
                       'skipped':shadow_capture.get('skipped',0),'shadow_mode':True})
    if automated and shadow_capture.get('status')=='FAILED':
        raise RuntimeError('Shadow decision persistence failed; automated run remains retriable.')
    append_agent_audit(uid,'scheduled_cio_brief',{'headline':brief['headline'],'material':brief['material'],'tickers':tickers,'run_key':run_key,'shadow_mode':True})
    save_desk_output(uid,output_type,payload,run_key=run_key)
    return payload
