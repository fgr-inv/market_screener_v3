from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core.automation_recovery import recovery_plan
from core.emerging_trends import analyze_emerging_trend, cap_segment
from core.market_calendar import is_us_equity_session, previous_us_equity_session
from core.opportunity_discovery import discover_daily_candidates
from core.refresh import equity_liquidity_profile
import core.market_data as market_data


def _history(prices, volume=2_000_000):
    price=np.asarray(prices,dtype=float)
    index=pd.date_range('2025-01-02',periods=len(price),freq='B')
    direction=np.r_[False,np.diff(price)>0]
    volumes=np.where(direction,volume*1.4,volume*.8)
    return pd.DataFrame({'Open':price*.995,'High':price*1.01,'Low':price*.99,
                         'Close':price,'Volume':volumes},index=index)


def _candidate(ticker,source,cap,score=82,emerging=75,phase='EARLY_ACCELERATION',sector='Technology'):
    return {'Ticker':ticker,'Sector':sector,'Universe Source':source,'Cap Segment':cap,
            'Market Cap':5_000_000_000 if cap=='Mid Cap' else 1_000_000_000,
            'Preliminary_Score':score,'Entry_Score':52,'Trend_Score':48,
            'Emerging_Trend_Score':emerging,'Trend_Phase':phase,'RS_Percentile':70,
            'Risk_Score':70,'Confidence_Score':68,'Sector_Score':70,'RR':2.0,'Action':'WATCH',
            'Liquidity Tier':'MEDIUM','Average Dollar Volume 20d':20_000_000}


def test_cap_segments_use_market_cap_then_provenance():
    assert cap_segment(250_000_000,'')=='Micro Cap'
    assert cap_segment(1_200_000_000,'')=='Small Cap'
    assert cap_segment(6_000_000_000,'')=='Mid Cap'
    assert cap_segment(None,'S&P SmallCap 600')=='Small Cap'
    assert cap_segment(None,'S&P MidCap 400')=='Mid Cap'


def test_emerging_trend_finds_leader_and_base_without_claiming_prediction():
    benchmark=_history(np.linspace(50,65,260))
    leader=_history(np.r_[np.linspace(50,70,180),np.linspace(70,95,80)])
    base=_history(np.r_[np.linspace(50,75,200),np.linspace(72,77,60)+np.sin(np.linspace(0,8,60))*.5])
    leader_result=analyze_emerging_trend(leader,benchmark)
    base_result=analyze_emerging_trend(base,benchmark)
    assert leader_result['Trend_Phase'] in {'ESTABLISHED_LEADER','BREAKOUT_CONFIRMED'}
    assert base_result['Trend_Phase'] in {'BASE_NEAR_BREAKOUT','BREAKOUT_CONFIRMED'}
    assert leader_result['Trend_Opportunity'] and base_result['Trend_Opportunity']
    assert leader_result['Emerging_Trend_Score']>=70 and base_result['Emerging_Trend_Score']>=70


def test_small_cap_gate_is_stricter_and_micro_caps_are_excluded():
    liquid=_history(np.linspace(9,10,260),volume=1_200_000)
    thin=_history(np.linspace(9,10,260),volume=500_000)
    assert equity_liquidity_profile(liquid,'S&P SmallCap 600','Small Cap')['eligible']
    assert not equity_liquidity_profile(thin,'S&P SmallCap 600','Small Cap')['eligible']
    micro=equity_liquidity_profile(liquid,'Supplemental','Micro Cap')
    assert not micro['eligible'] and micro['reason']=='MICRO_CAP_EXCLUDED'


def test_early_trend_track_accepts_only_evidence_gated_mid_small_names():
    rows=[_candidate('MID1','FMP US Mid Cap','Mid Cap'),
          _candidate('SMALL1','FMP US Small Cap','Small Cap'),
          _candidate('WEAK','FMP US Small Cap','Small Cap',emerging=45,phase='NO_QUALIFIED_SETUP')]
    result=discover_daily_candidates(pd.DataFrame(rows),max_candidates=4,minimum_score=55)
    tickers={row['Ticker'] for row in result['candidates']}
    assert {'MID1','SMALL1'}<=tickers and 'WEAK' not in tickers
    assert all(row['Discovery Track']=='EARLY TREND' for row in result['candidates'])
    assert result['cap_segment_counts']['Small Cap']==2


def test_market_calendar_skips_weekends_and_recurring_nyse_holidays():
    assert not is_us_equity_session(date(2026,4,3))  # Good Friday
    assert not is_us_equity_session(date(2026,7,3))  # Independence Day observed
    assert is_us_equity_session(date(2026,7,6))
    assert previous_us_equity_session(date(2026,7,6))==date(2026,7,2)


def test_fmp_supplement_is_bounded_and_rejects_micro_or_foreign_rows(monkeypatch):
    class Response:
        def raise_for_status(self): return None
        def json(self):
            return [
                {'symbol':'MID','sector':'Industrials','marketCap':5_000_000_000,
                 'exchangeShortName':'NYSE'},
                {'symbol':'SMALL','sector':'Technology','marketCap':1_000_000_000,
                 'exchangeShortName':'NASDAQ'},
                {'symbol':'FOREIGN','sector':'Technology','marketCap':1_000_000_000,
                 'exchangeShortName':'LSE'},
            ]
    class Session:
        def get(self,*args,**kwargs): return Response()
    monkeypatch.setattr(market_data,'_secret',lambda *args,**kwargs:'key')
    monkeypatch.setattr(market_data,'_retry_session',lambda:Session())
    market_data.load_fmp_cap_universe.clear()
    result=market_data.load_fmp_cap_universe(max_per_segment=20)
    market_data.load_fmp_cap_universe.clear()
    assert set(result['Ticker'])=={'MID','SMALL'}
    assert set(result['Cap Segment'])=={'Mid Cap','Small Cap'}


def test_recovery_plan_only_retries_durable_processes_once_per_target():
    report={'market_time':'2026-09-03T21:00:00-04:00','issues':[
        {'process':'saved_alerts','status':'STALE'},
        {'process':'daily_snapshot','status':'MISSING','expected_market_date':'2026-09-03'},
        {'process':'opportunity_hunt','status':'STALE','expected_market_date':'2026-09-03'},
    ]}
    plan=recovery_plan(report)
    assert [row['process'] for row in plan]==['daily_snapshot','opportunity_hunt']
    assert plan[0]['recovery_key']=='recovery-daily_snapshot-2026-09-03'


def test_final_release_contract_is_shadow_only_and_resilient():
    root=Path(__file__).resolve().parents[1]
    config=(root/'core'/'config.py').read_text(encoding='utf-8')
    workflow=(root/'.github/workflows/automation_resilience.yml').read_text(encoding='utf-8')
    recovery=(root/'scripts/run_automation_recovery.py').read_text(encoding='utf-8')
    refresh=(root/'core/refresh.py').read_text(encoding='utf-8')
    assert 'APP_VERSION = "11.39.3"' in config
    assert 'schedule:' in workflow and 'contents: write' in workflow
    assert 'FMP US mid/small-cap supplement' in refresh and 'analyze_emerging_trend' in refresh
    assert 'recover missed durable processes once' in workflow.lower()
    forbidden=('TradingClient','submit_order','place_order','alpaca')
    assert all(term not in recovery for term in forbidden)
