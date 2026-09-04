from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core.alerts_engine import build_discord_rule_alert
from core.desk_notifications import build_discord_cio_embed
from core.market_data import _combine_universe_frames
from core.opportunity_discovery import discover_daily_candidates
from core.refresh import equity_liquidity_profile


NOW=datetime(2026,9,3,14,30,tzinfo=timezone.utc)


def _history(price=10.0,volume=1_000_000,rows=30):
    index=pd.date_range('2026-01-01',periods=rows,freq='B')
    return pd.DataFrame({'Close':np.full(rows,price),'Volume':np.full(rows,volume)},index=index)


def _candidate(ticker,source,score,sector):
    return {
        'Ticker':ticker,'Sector':sector,'Universe Source':source,'Liquidity Tier':'HIGH',
        'Average Dollar Volume 20d':50_000_000,'Preliminary_Score':score,
        'Entry_Score':75,'Trend_Score':75,'Risk_Score':70,'RS_Percentile':70,
        'Confidence_Score':75,'Sector_Score':65,'RR':2.0,'Event_Risk':'LOW',
        'Action':'WATCH','Scan_Extended_Trim':False,
    }


def _brief():
    event={'ticker':'AMD','severity':5,'event_types':['news_guidance'],'reasons':['Guidance changed'],
           'metrics':{'price_move_pct':-4.2,'relative_volume':1.8,'story':{
               'ticker':'AMD','title':'AMD updates financial outlook','category':'GUIDANCE',
               'direction':'NEGATIVE','severity':5,'thesis_impact':'POTENTIAL_THESIS_RISK',
               'publisher':'AMD Investor Relations','primary_source':True,
               'published_at':'2026-09-03T14:00:00+00:00','url':'https://example.test/amd'}}}
    market={'state':'RISK_OFF','confidence':.82,'summary':'Breadth and credit are defensive.',
            'professional_context':{'macro_score':38,'vix':27.4,'momentum':'DETERIORATING',
                                    'leaders':['Utilities'],'laggards':['Technology'],'snapshot_age_hours':2.1}}
    risk={'state':'ELEVATED','confidence':.8,'summary':'Concentration remains elevated.',
          'professional_context':{'largest_positions':[('AMD',.23),('MSFT',.15)],
                                  'largest_sectors':[('Technology',.48)],'cash_pct':8.0}}
    decision={'subject':'AMD','agent':'News & Catalyst','state':'MATERIAL_NEGATIVE','confidence':.88,
              'verification_status':'VERIFIED','key_evidence':[{'claim':'Primary-source severity','value':5}],
              'contradicting_evidence':['Price structure remains constructive.']}
    return {'headline':'One material item requires review','material':True,'events_considered':[event],
            'market_regime':market,'principal_risk':risk,'top_opportunities':[],
            'decisions_needed':[decision],'material_reasons':['AMD guidance changed']}


def test_expanded_universe_preserves_provenance_and_deduplicates():
    large=pd.DataFrame([{'Ticker':'AAA','Sector':'Technology','Universe Source':'S&P 500'}])
    mid=pd.DataFrame([{'Ticker':'AAA','Sector':'Other','Universe Source':'S&P MidCap 400'},
                      {'Ticker':'BBB','Sector':'Industrials','Universe Source':'S&P MidCap 400'}])
    combined=_combine_universe_frames(large,mid)
    assert combined['Ticker'].tolist()==['AAA','BBB']
    assert combined.set_index('Ticker').loc['AAA','Universe Source']=='S&P 500'
    assert combined.set_index('Ticker').loc['BBB','Universe Source']=='S&P MidCap 400'


def test_non_core_liquidity_gate_and_core_exemption():
    eligible=equity_liquidity_profile(_history(10,1_000_000),'S&P MidCap 400')
    illiquid=equity_liquidity_profile(_history(10,100_000),'S&P SmallCap 600')
    low_price=equity_liquidity_profile(_history(1.5,10_000_000),'Curated Liquid Supplemental')
    core=equity_liquidity_profile(_history(1.0,100),'S&P 500')
    assert eligible['eligible'] and eligible['average_dollar_volume_20d']==10_000_000
    assert not illiquid['eligible'] and illiquid['reason']=='LOW_DOLLAR_VOLUME'
    assert not low_price['eligible'] and low_price['reason']=='LOW_PRICE'
    assert core['eligible'] and core['liquidity_tier']=='CORE_INDEX'


def test_daily_shortlist_diversifies_universe_sources_when_evidence_exists():
    rows=[]
    for index in range(4): rows.append(_candidate(f'L{index}','S&P 500',95-index,f'Large {index}'))
    for index in range(3): rows.append(_candidate(f'M{index}','S&P MidCap 400',85-index,f'Mid {index}'))
    result=discover_daily_candidates(pd.DataFrame(rows),max_candidates=4,max_per_sector=2,
                                     max_per_universe=2,minimum_score=60)
    sources=[row['Universe Source'] for row in result['candidates']]
    assert sources.count('S&P 500')==2 and sources.count('S&P MidCap 400')==2
    assert all('Liquidity Tier' in row for row in result['candidates'])


def test_cio_discord_report_contains_professional_evidence_and_scenarios():
    embed=build_discord_cio_embed(_brief(),'material')
    names=[field['name'] for field in embed['fields']]
    assert names[0].startswith('🔴 AMD')
    assert '🔎 Lectura profesional' in names and '🧭 Escenarios y validación' in names
    reading=next(field['value'] for field in embed['fields'] if field['name']=='🔎 Lectura profesional')
    risk=next(field['value'] for field in embed['fields'] if field['name']=='🛡️ Riesgo principal')
    market=next(field['value'] for field in embed['fields'] if field['name']=='🌎 Contexto de mercado')
    assert 'Primary-source severity' in reading and 'Contraste' in reading
    assert 'AMD 23.0%' in risk and 'Technology 48.0%' in risk
    assert 'Macro **38/100**' in market and 'VIX **27.4**' in market


def test_saved_alert_discord_report_adds_technical_risk_portfolio_and_market_context():
    alert={'ticker':'NVDA','rule_type':'ENTRY_SCORE_ABOVE','threshold':75,'note':'Revisar entrada'}
    context={'price':182.4,'trend':'Strong Uptrend','setup':'Uptrend Pullback',
             'technical_score':82,'trend_score':88,'entry_score':79,'risk_score':71,
             'rsi14':56.2,'relative_volume':1.42,'relative_strength_63d_pct':7.8,
             'distance_ema62_pct':1.2,'distance_ema79_pct':2.4,'distance_sma200_pct':18.0,
             'entry_zone':'$176 – $184','invalidation':'< $169','target':'$211','rr':2.35,'risk':'Medium',
             'current_weight_pct':8.5,'sector':'Technology','sector_weight_pct':31.0,
             'market_regime':'RISK-ON','macro_score':72,'vix':16.4,
             'universe_source':'Nasdaq 100','liquidity_tier':'CORE_INDEX','opportunity_score':84}
    embed=build_discord_rule_alert(alert,'NVDA: Entry Score 79 >= 75','EDGE',NOW,context=context)
    fields={field['name']:field['value'] for field in embed['fields']}
    assert '📈 Lectura técnica' in fields and 'Strong Uptrend' in fields['📈 Lectura técnica']
    assert '🔬 Confluencia y participación' in fields and '1.42x' in fields['🔬 Confluencia y participación']
    assert '🛡️ Mapa de riesgo' in fields and '2.35:1' in fields['🛡️ Mapa de riesgo']
    assert '🧩 Cartera, mercado y universo' in fields and '8.5%' in fields['🧩 Cartera, mercado y universo']
    assert '🧭 Escenario y validación' in fields
    assert 'Ninguna orden fue enviada' in embed['footer']['text']


def test_v1138_contract_uses_expanded_scan_without_execution():
    root=Path(__file__).resolve().parents[1]
    config=(root/'core'/'config.py').read_text(encoding='utf-8')
    refresh=(root/'core'/'refresh.py').read_text(encoding='utf-8')
    worker=(root/'scripts'/'daily_refresh.py').read_text(encoding='utf-8')
    workflow=(root/'.github'/'workflows'/'daily_refresh.yml').read_text(encoding='utf-8')
    alerts=(root/'scripts'/'run_alerts.py').read_text(encoding='utf-8')
    screener=(root/'views'/'screener_shared.py').read_text(encoding='utf-8')
    assert 'APP_VERSION = "11.38.1"' in config
    for name in ('S&P MidCap 400','S&P SmallCap 600'):
        assert name in refresh
    assert 'scan_limit=1700' in worker and 'timeout-minutes: 60' in workflow
    assert 'max_single_fallback=24' in refresh
    assert 'US Expanded Liquid' in screener and 'S&P MidCap 400' in screener and 'S&P SmallCap 600' in screener
    assert 'evaluate_rule_with_context' in alerts and 'context=context' in alerts
    runtime=(refresh+worker+alerts).lower()
    assert all(term not in runtime for term in ('place_order','submit_order','tradingclient'))
