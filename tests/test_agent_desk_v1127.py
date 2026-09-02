import pandas as pd
from datetime import datetime, timezone, timedelta

from core.agent_contracts import AgentResult,Evidence,DataStatus,VerificationStatus
from core.market_regime_agent import analyze_market_regime
from core.verification_agent import verify_result
from core.watchlist_engine import build_watchlist


def _meta(hours_old=1):
    return {'generated_at':(datetime.now(timezone.utc)-timedelta(hours=hours_old)).isoformat()}


def _macro(score=76):
    return {
        'Macro_Score':score,'Institutional_Regime':'RISK-ON' if score>=70 else 'RISK-OFF' if score<=40 else 'NEUTRAL',
        'Economic_Regime_Slow':'GOLDILOCKS','Momentum':'STABLE','Risk_Appetite':72,'Credit':68,
        'Breadth':64,'Rates':58,'Liquidity':61,'Growth':62,'Inflation_Pressure':42,'VIX':15.5,
    }


def _sectors():
    return pd.DataFrame([
        {'Sector':'Technology','ETF':'XLK','Overall':82,'Strength':85,'Entry':72,'Macro':84,'Status':'Leader'},
        {'Sector':'Health Care','ETF':'XLV','Overall':63,'Strength':62,'Entry':65,'Macro':61,'Status':'Neutral'},
        {'Sector':'Utilities','ETF':'XLU','Overall':38,'Strength':35,'Entry':45,'Macro':35,'Status':'Lagging'},
    ])


def _result(agent,ticker,state,confidence=.8):
    r=AgentResult(agent,'1','skill','1',ticker,state,confidence,'ok',[Evidence('fact',1,'test',status=DataStatus.CURRENT)])
    r.verification_status=VerificationStatus.VERIFIED
    return r


def test_market_agent_uses_current_central_snapshots_and_verifies():
    r=verify_result(analyze_market_regime(_macro(),_sectors(),_meta(2)))
    assert r.state=='RISK_ON'
    assert r.verification_status==VerificationStatus.VERIFIED
    assert r.metadata['leaders'][0]=='Technology'
    assert r.metadata['sector_scores']['Technology']==82
    assert 'no direct provider/API calls' in r.metadata['data_policy']


def test_market_agent_marks_old_snapshot_stale_and_verifier_blocks():
    r=verify_result(analyze_market_regime(_macro(),_sectors(),_meta(72)))
    assert any(e.status==DataStatus.STALE for e in r.evidence)
    assert r.verification_status==VerificationStatus.STALE_DATA
    assert r.confidence<=.49


def test_market_agent_missing_snapshot_is_not_neutral():
    r=verify_result(analyze_market_regime(None,_sectors(),_meta()))
    assert r.state=='UNAVAILABLE'
    assert r.verification_status==VerificationStatus.REJECTED


def test_watchlist_adds_small_sector_context_weight():
    portfolio=AgentResult('Portfolio & Risk','1','skill','1','PORTFOLIO','BALANCED',.9,'ok',metadata={'weights':{},'sector_weights':{}})
    market=analyze_market_regime(_macro(),_sectors(),_meta())
    results=[
        _result('Technical Signal','AAA','SETUP',.85),_result('Fundamental & Catalyst','AAA','IMPROVING',.85),
        _result('Technical Signal','BBB','SETUP',.85),_result('Fundamental & Catalyst','BBB','IMPROVING',.85),
    ]
    rows=build_watchlist(results,portfolio,sectors={'AAA':'Technology','BBB':'Utilities'},market_result=market)
    assert rows[0]['Ticker']=='AAA'
    assert rows[0]['Market Fit'] > rows[1]['Market Fit']
    assert rows[0]['Priority Score'] > rows[1]['Priority Score']
