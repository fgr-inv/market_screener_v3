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

def run_desk_review(user_id,tickers,force_fundamental=False,output_type='shadow_review',max_tickers=25):
    uid=str(user_id or 'local-user'); tickers=list(dict.fromkeys(str(x).upper().strip() for x in tickers if str(x).strip()))[:max_tickers]
    pos=load_positions(user_id=uid); position_ticks=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
    all_ticks=list(dict.fromkeys(tickers+position_ticks)); histories=download_prices(all_ticks,period='2y') if all_ticks else {}
    verified=[]
    market=verify_result(analyze_market_regime(load_json_snapshot('latest_macro'),load_latest_snapshot('latest_sectors'),load_json_snapshot('latest_meta')))
    verified.append(market)
    portfolio=verify_result(analyze_portfolio_risk(pos,histories)); verified.append(portfolio)
    for ticker in tickers:
        for result in (analyze_technical(ticker,histories.get(ticker)),analyze_fundamental(ticker,force_refresh=force_fundamental)):
            result=verify_result(result); verified.append(result); append_agent_audit(uid,'scheduled_specialist_verified',result.to_dict())
    sectors={}
    if not pos.empty: sectors.update({str(r['ticker']).upper():str(r.get('sector','Unknown') or 'Unknown') for _,r in pos.iterrows()})
    watchlist=build_watchlist(verified,portfolio,sectors=sectors,limit=15,market_result=market)
    brief=build_cio_brief(verified)
    payload={'shadow_mode':True,'tickers':tickers,'market':market.to_dict(),'portfolio':portfolio.to_dict(),'watchlist':watchlist,'brief':brief}
    append_agent_audit(uid,'scheduled_cio_brief',{'headline':brief['headline'],'tickers':tickers,'shadow_mode':True})
    save_desk_output(uid,output_type,payload)
    return payload
