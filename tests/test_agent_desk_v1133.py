from datetime import datetime,timezone,timedelta
from pathlib import Path

import pandas as pd

from core.intraday_monitor import select_monitor_tickers
from core.opportunity_discovery import (discover_daily_candidates,
                                        load_active_watchlist_tickers,
                                        qualify_verified_opportunities)
from core.refresh import combine_equity_universes
from scripts.run_daily_opportunity_hunt import snapshot_age_hours


def _row(ticker,sector='Technology',score=80,**overrides):
    row={'Ticker':ticker,'Sector':sector,'Preliminary_Score':score,'Entry_Score':score,
         'Trend_Score':score,'RS_Percentile':score,'Risk_Score':70,'Confidence_Score':70,
         'Sector_Score':65,'RR':2.0,'Event_Risk':'LOW','Action':'WATCH',
         'Scan_Extended_Trim':False}
    row.update(overrides); return row


def test_daily_discovery_applies_hard_gates_and_sector_diversification():
    snapshot=pd.DataFrame([
        _row('AAA',score=88),_row('BBB',score=86),_row('CCC',score=84),
        _row('DDD',score=82),
        _row('EVENT',sector='Industrials',score=95,Event_Risk='HIGH'),
        _row('EXT',sector='Health Care',score=94,Scan_Extended_Trim=True),
        _row('WEAK',sector='Financials',score=90,Entry_Score=30),
        _row('ENERGY',sector='Energy',score=78),
    ])
    result=discover_daily_candidates(snapshot,max_candidates=10,max_per_sector=3)
    tickers=[row['Ticker'] for row in result['candidates']]
    assert result['status']=='SHORTLIST_READY'
    assert tickers[:3]==['AAA','BBB','CCC']
    assert 'DDD' not in tickers and 'ENERGY' in tickers
    assert all(t not in tickers for t in ('EVENT','EXT','WEAK'))
    assert result['rejection_counts']['sector_diversification']==1


def test_daily_discovery_does_not_treat_nan_extended_flag_as_true():
    result=discover_daily_candidates(pd.DataFrame([_row('AAA',Scan_Extended_Trim=float('nan'))]))
    assert [row['Ticker'] for row in result['candidates']]==['AAA']


def test_verified_opportunity_requires_both_specialists_and_clean_states():
    rows=[
        {'Ticker':'GOOD','Priority Score':78,'Technical':'SETUP','Fundamental':'IMPROVING','Verified Specialists':2,'Contradictions':0},
        {'Ticker':'ONE','Priority Score':90,'Technical':'SETUP','Fundamental':'IMPROVING','Verified Specialists':1,'Contradictions':0},
        {'Ticker':'BROKEN','Priority Score':88,'Technical':'BROKEN_SETUP','Fundamental':'IMPROVING','Verified Specialists':2,'Contradictions':0},
        {'Ticker':'WEAK','Priority Score':55,'Technical':'WATCH','Fundamental':'INTACT','Verified Specialists':2,'Contradictions':0},
    ]
    shortlist=[{'Ticker':'GOOD','Discovery Score':84,'Sector':'Technology'}]
    qualified=qualify_verified_opportunities(rows,shortlist)
    assert [row['Ticker'] for row in qualified]==['GOOD']
    assert qualified[0]['Opportunity Status']=='VERIFIED_CANDIDATE'
    assert qualified[0]['Opportunity Rank']==1


def test_intraday_monitor_prioritizes_holdings_then_persistent_watchlist():
    latest=pd.DataFrame([_row('CACHE1',score=99),_row('CACHE2',score=98)])
    selected=select_monitor_tickers(latest,['HOLD'],max_symbols=4,watchlist_tickers=['WATCH1','WATCH2'])
    assert selected==['HOLD','WATCH1','WATCH2','CACHE1']


def test_active_watchlist_loads_hunt_before_other_outputs_and_deduplicates():
    records={
        'daily_opportunity_hunt':{'payload':{'discovery':{'monitor_tickers':['AAA','BBB']}}},
        'daily_cio_brief':{'payload':{'watchlist':[{'Ticker':'BBB'},{'Ticker':'CCC'}]}},
        'scheduled_review':{'payload':{'brief':{'top_opportunities':[{'Ticker':'DDD'}]}}},
    }
    loader=lambda uid,typ: records.get(typ)
    assert load_active_watchlist_tickers('u',limit=4,loader=loader)==['AAA','BBB','CCC','DDD']


def test_broad_universe_combines_sources_in_priority_order():
    sp=pd.DataFrame([{'Ticker':'AAA','Sector':'A'},{'Ticker':'BBB','Sector':'B'}])
    ndx=pd.DataFrame([{'Ticker':'BBB','Sector':'Other'},{'Ticker':'CCC','Sector':'C'}])
    fallback=pd.DataFrame([{'Ticker':'DDD','Sector':'D'}])
    out=combine_equity_universes(sp,ndx,fallback,limit=3)
    assert out['Ticker'].tolist()==['AAA','BBB','CCC']
    assert out.loc[out['Ticker']=='BBB','Sector'].iloc[0]=='B'


def test_snapshot_freshness_is_explicit():
    now=datetime(2026,9,3,20,tzinfo=timezone.utc)
    meta={'generated_at':(now-timedelta(hours=2)).isoformat()}
    assert snapshot_age_hours(meta,now)==2
    assert snapshot_age_hours({},now) is None


def test_v1133_workflows_and_ui_remain_research_only():
    config=Path('core/config.py').read_text(encoding='utf-8')
    worker=Path('scripts/run_daily_opportunity_hunt.py').read_text(encoding='utf-8')
    workflow=Path('.github/workflows/daily_opportunity_hunt.yml').read_text(encoding='utf-8')
    intraday=Path('.github/workflows/investment_desk.yml').read_text(encoding='utf-8')
    view=Path('views/investment_desk.py').read_text(encoding='utf-8')
    alert_view=Path('views/alerts.py').read_text(encoding='utf-8')
    assert 'APP_VERSION = "11.33"' in config
    assert 'run_desk_review' in worker and 'qualify_verified_opportunities' in worker
    assert "cron: '10 23 * * 1-5'" in workflow
    assert "cron: '*/30 13-21 * * 1-5'" in intraday
    assert 'Daily Opportunity Hunt' in view and 'Persistent 30-minute watchlist' in view
    assert 'Background Desk Activity' in alert_view and "load_latest_desk_output(uid,'event_scan')" in alert_view
    assert all(term not in worker for term in ('TradingClient','place_order','submit_order','alpaca'))
