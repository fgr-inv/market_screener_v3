from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core.macro_sector_strategist import (EXPECTED_SECTORS,build_market_evidence,
                                           build_market_report,render_market_report_markdown,
                                           verify_market_report)
from core.market_report_delivery import build_market_report_embeds
from scripts.run_market_analysis import report_run_key


NY=ZoneInfo('America/New_York')


def _inputs():
    now=datetime(2026,9,15,20,40,tzinfo=NY)
    macro={'Economic_Regime_Slow':'GOLDILOCKS','Growth':58,'Slow_Growth':54,
           'Inflation_Pressure':48,'Slow_Inflation_Pressure':47,'Rates':45,'Credit':67,
           'Liquidity':57,'Risk_Appetite':64,'Breadth':61,'VIX':17.2,'Fed_Funds':4.25,
           '10Y_2Y':0.31,'US10Y_20d_bps':12,'Dollar_20d':0.01,'HYG_IEF_20d':0.012,
           'Oil_20d':-0.025,'Data_Quality_%':96}
    sectors=pd.DataFrame([{'Sector':sector,'ETF':f'X{index:02d}','Strength':80-index*3,
                               'Entry':60,'Macro':55,'Status':'OK'}
                              for index,sector in enumerate(EXPECTED_SECTORS)])
    rows=[]
    for index,sector in enumerate(EXPECTED_SECTORS):
        rows.extend([{'Ticker':f'T{index}A','Sector':sector,'Trend':'Uptrend','Dist_SMA200_%':8,
                      'RS_63d_%':5-index/2,'RS_1M_vs_SPY_%':2,'Action':'WATCH'},
                     {'Ticker':f'T{index}B','Sector':sector,'Trend':'Downtrend','Dist_SMA200_%':-2,
                      'RS_63d_%':1-index/2,'RS_1M_vs_SPY_%':-1,'Action':'AVOID'}])
    meta={'generated_at':now.isoformat(),'symbols_scored':len(rows)}
    return now,macro,sectors,pd.DataFrame(),pd.DataFrame(rows),meta


def test_developed_report_covers_macro_and_all_sectors_with_evidence():
    now,macro,sectors,breadth,screener,meta=_inputs()
    packet=build_market_evidence(macro,sectors,breadth,screener,meta,'daily',now=now)
    report=build_market_report(packet); markdown=render_market_report_markdown(report)
    assert report['verification']['status']=='VERIFIED'
    assert report['verification']['sector_count']==11
    assert len(report['macro_analysis'])==4 and len(report['sector_analysis'])==11
    assert len(markdown.split())>1200
    assert all(section['evidence_refs'] for section in report['sector_analysis'])
    assert all(sector in markdown for sector in EXPECTED_SECTORS)
    assert report['no_execution'] is True and report['shadow_mode'] is True


def test_verifier_rejects_an_unsupported_reference():
    now,macro,sectors,breadth,screener,meta=_inputs()
    packet=build_market_evidence(macro,sectors,breadth,screener,meta,'weekly',now=now)
    report=build_market_report(packet)
    report['evidence_refs'].append('macro:invented')
    checked=verify_market_report(report,packet)
    assert checked['verification']['status']=='REJECTED'
    assert checked['verification']['unsupported_refs']==['macro:invented']


def test_discord_delivery_is_split_and_within_provider_bounds():
    now,macro,sectors,breadth,screener,meta=_inputs()
    report=build_market_report(build_market_evidence(macro,sectors,breadth,screener,meta,'daily',now=now))
    embeds=build_market_report_embeds(report)
    assert len(embeds)==4
    assert all(len(embed.get('fields',[]))<=25 for embed in embeds)
    assert all(len(field['value'])<=1024 for embed in embeds for field in embed.get('fields',[]))


def test_run_keys_are_idempotent_per_period():
    now=datetime(2026,9,15,20,40,tzinfo=NY)
    assert report_run_key(now,'daily')=='market-analysis-daily-2026-09-15'
    assert report_run_key(now,'weekly')=='market-analysis-weekly-2026-W38'


def test_market_report_ui_workflows_and_workers_are_research_only():
    root=Path(__file__).resolve().parents[1]
    paths=('views/market_reports.py','.github/workflows/daily_market_analysis.yml',
           '.github/workflows/weekly_market_analysis.yml','scripts/run_market_analysis.py',
           'core/macro_sector_strategist.py')
    code='\n'.join((root/path).read_text(encoding='utf-8') for path in paths)
    assert 'Market Reports' in (root/'app.py').read_text(encoding='utf-8')
    assert 'scripts.run_daily_market_analysis' in code and 'scripts.run_weekly_market_analysis' in code
    assert all(term not in code.lower() for term in ('tradingclient','submit_order','place_order','alpaca'))
