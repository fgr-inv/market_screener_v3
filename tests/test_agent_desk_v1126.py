import pandas as pd
import numpy as np
from core.agent_contracts import AgentResult,Evidence,DataStatus,VerificationStatus
from core.portfolio_risk_agent import analyze_portfolio_risk,portfolio_fit_for_candidate
from core.watchlist_engine import build_watchlist
from core.verification_agent import verify_result


def _hist(start=100, drift=.002, n=160):
    idx=pd.date_range('2026-01-01',periods=n,freq='B')
    vals=start*np.cumprod(np.full(n,1+drift))
    return pd.DataFrame({'Close':vals},index=idx)


def test_portfolio_agent_detects_concentration_and_is_verified():
    pos=pd.DataFrame([
        {'ticker':'AAA','quantity':80,'avg_cost':90,'sector':'Technology'},
        {'ticker':'BBB','quantity':10,'avg_cost':90,'sector':'Technology'},
        {'ticker':'CCC','quantity':10,'avg_cost':90,'sector':'Health Care'},
    ])
    h={'AAA':_hist(100,.002),'BBB':_hist(100,.0021),'CCC':_hist(100,-.0002)}
    r=verify_result(analyze_portfolio_risk(pos,h))
    assert r.state in {'ELEVATED','HIGH_RISK'}
    assert r.verification_status in {VerificationStatus.VERIFIED,VerificationStatus.PARTIALLY_VERIFIED}
    assert r.metadata['weights']['AAA'] > .70


def test_portfolio_fit_penalizes_existing_concentrated_position():
    pos=pd.DataFrame([{'ticker':'AAA','quantity':9,'avg_cost':90,'sector':'Technology'},{'ticker':'BBB','quantity':1,'avg_cost':90,'sector':'Health Care'}])
    r=analyze_portfolio_risk(pos,{'AAA':_hist(),'BBB':_hist()})
    fit,note=portfolio_fit_for_candidate('AAA','Technology',r)
    assert fit <= .2
    assert 'Already held' in note


def _result(agent,ticker,state,confidence=.8):
    r=AgentResult(agent,'1','skill','1',ticker,state,confidence,'ok',[Evidence('fact',1,'test',status=DataStatus.CURRENT)])
    r.verification_status=VerificationStatus.VERIFIED
    return r


def test_watchlist_combines_specialists_and_portfolio_fit():
    portfolio=AgentResult('Portfolio & Risk','1','skill','1','PORTFOLIO','BALANCED',.9,'ok',metadata={'weights':{'AAA':.35},'sector_weights':{'Technology':.6}})
    results=[_result('Technical Signal','AAA','SETUP',.9),_result('Fundamental & Catalyst','AAA','IMPROVING',.9),
             _result('Technical Signal','BBB','SETUP',.85),_result('Fundamental & Catalyst','BBB','IMPROVING',.85)]
    rows=build_watchlist(results,portfolio,sectors={'AAA':'Technology','BBB':'Health Care'})
    assert rows[0]['Ticker']=='BBB'
    assert rows[0]['Priority Score'] > rows[1]['Priority Score']
    assert rows[1]['Portfolio Fit'] < rows[0]['Portfolio Fit']
