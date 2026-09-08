from pathlib import Path

import numpy as np
import pandas as pd

from core.opportunity_lifecycle import (MAX_WEEKLY_NEW_RISK_PCT, _size_candidate,
    build_opportunity_lifecycle, classify_sleeve, portfolio_risk_context, update_shadow_book)


NOW=pd.Timestamp('2026-09-08 20:00:00',tz='America/New_York')


def _seed(ticker='ABC',source='S&P 500',sector='Technology'):
    return {'Ticker':ticker,'Universe Source':source,'Cap Segment':'Large Cap' if source=='S&P 500' else 'Small Cap',
            'Sector':sector,'Entry Score':75,'Priority Score':80,'RR':2.0}


def _verified(ticker='ABC'):
    return {'Ticker':ticker,'Fundamental':'IMPROVING','Technical':'SETUP','Verified Specialists':3}


def _signal(ticker='ABC',key='signal-1',opportunity='opp-1'):
    return {'ticker':ticker,'setup_version':'2.0','signal_key':key,'opportunity_key':opportunity,
            'direction':'LONG','setup_id':'BREAKOUT_RVOL','signal_at':'2026-09-08T20:00:00-04:00',
            'baseline_price':100.0,'baseline_atr':2.0}


def _thesis(ticker='ABC'):
    return {'ticker':ticker,'status':'ACTIVE','thesis':'Verified catalyst and durable operating improvement.'}


def _confirmation(ticker='ABC'):
    return {ticker:{'gate_pass':True,'confirmation_score':78,'weekly_bias':'BULLISH',
                    'daily_bias':'BULLISH','hourly_bias':'BULLISH','market_regime':'BULLISH',
                    'relative_strength_spy':{'rs20_pct':3},'relative_strength_sector':{'rs20_pct':1},
                    'breadth':{'state':'STRONG'},'breakout_quality':{'score':75},
                    'structural_invalidation':'Daily structure failure.'}}


def _history(start='2026-01-02',periods=180,base=100.0):
    index=pd.bdate_range(start,periods=periods)
    close=np.linspace(base,base+5,periods)
    return pd.DataFrame({'Open':close,'High':close+.4,'Low':close-.4,'Close':close,'Volume':1_000_000},index=index)


def test_lifecycle_requires_specialist_evidence_and_current_v2_trigger():
    waiting=build_opportunity_lifecycle([_seed()],[_verified()],[],generated_at=NOW)
    assert waiting['candidates'][0]['stage']=='EVIDENCE_VERIFIED'
    ready=build_opportunity_lifecycle([_seed()],[_verified()],[_signal(),{**_signal(key='old'),'setup_version':'1.0'}],
                                      theses=[_thesis()],generated_at=NOW,confirmations=_confirmation())
    assert ready['candidates'][0]['stage']=='ENTRY_READY'
    assert ready['candidates'][0]['signal_keys']==['signal-1']
    failed=build_opportunity_lifecycle([_seed()],[{**_verified(),'Fundamental':'WEAK'}],[_signal()],generated_at=NOW)
    assert failed['candidates'][0]['stage']=='WATCHLIST'
    assert 'FUNDAMENTAL_GATE_NOT_PASSED' in failed['candidates'][0]['gate_reasons']


def test_sleeves_are_explicit_for_core_smid_and_crypto():
    assert classify_sleeve(_seed())=='CORE'
    assert classify_sleeve(_seed('MID','S&P MidCap 400'))=='SMID'
    assert classify_sleeve(_seed('BTC-USD','Crypto'))=='CRYPTO'


def test_shadow_book_sizes_risk_and_does_not_duplicate_one_opportunity():
    lifecycle=build_opportunity_lifecycle([_seed()],[_verified()],[_signal()],theses=[_thesis()],generated_at=NOW,
                                          confirmations=_confirmation())
    history=_history(periods=180)
    book=update_shadow_book(lifecycle,[_signal()],{'ABC':history},generated_at=NOW)
    assert book['status_counts']['PENDING_ENTRY']==1
    position=book['positions'][0]
    assert position['risk_budget_pct']<=MAX_WEEKLY_NEW_RISK_PCT
    assert position['planned_weight_pct']<=8.0
    again=update_shadow_book(lifecycle,[_signal()],{'ABC':history},existing=book,generated_at=NOW)
    assert len(again['positions'])==1


def test_pending_entry_fills_next_session_and_conservative_stop_wins():
    lifecycle=build_opportunity_lifecycle([_seed()],[_verified()],[_signal()],theses=[_thesis()],generated_at=NOW,
                                          confirmations=_confirmation())
    base=_history(periods=180); base=base[base.index.date<=NOW.date()]
    first=update_shadow_book(lifecycle,[_signal()],{'ABC':base},generated_at=NOW)
    next_day=pd.Timestamp('2026-09-09')
    volatile=pd.DataFrame({'Open':[101.0],'High':[110.0],'Low':[90.0],'Close':[101.0],'Volume':[2_000_000]},index=[next_day])
    second=update_shadow_book({'candidates':[]},[],{'ABC':pd.concat([base,volatile])},existing=first,
                              generated_at=pd.Timestamp('2026-09-09 20:00:00',tz='America/New_York'))
    position=second['positions'][0]
    assert position['status']=='EXITED' and position['exit_reason'] in {'STOP','STOP_GAP'}
    assert position['net_return_pct']<0


def test_correlation_and_weekly_budget_can_block_capacity():
    active=[{'ticker':'PEER','sector':'Technology','planned_weight_pct':5}]
    histories={'ABC':_history(base=100),'PEER':_history(base=200)}
    sizing,reason=_size_candidate({**_seed(),'ticker':'ABC','sleeve':'CORE'},_signal(),active,histories,0,50_000)
    assert sizing is None and reason.startswith('CORRELATION_BLOCK_PEER_')
    sizing,reason=_size_candidate({**_seed(),'ticker':'ABC','sleeve':'CORE'},_signal(),[],histories,
                                  MAX_WEEKLY_NEW_RISK_PCT,50_000)
    assert sizing is None and reason=='WEEKLY_RISK_BUDGET_EXHAUSTED'


def test_saved_portfolio_weights_constrain_duplicate_and_sector_risk():
    positions=pd.DataFrame([{'ticker':'ABC','allocation_pct':12,'quantity':0,'avg_cost':0,
                             'sector':'Technology','note':''}])
    context=portfolio_risk_context(positions,{'ABC':_history()})
    assert context[0]['planned_weight_pct']==12
    lifecycle=build_opportunity_lifecycle([_seed()],[_verified()],[_signal()],theses=[_thesis()],generated_at=NOW,
                                          confirmations=_confirmation())
    book=update_shadow_book(lifecycle,[_signal()],{'ABC':_history()},generated_at=NOW,
                            portfolio_context=context)
    assert not book['positions']
    assert book['new_rejections'][0]['reason']=='ALREADY_HELD_OR_ACTIVE'


def test_workflow_ui_watchdog_and_runtime_have_no_broker_path():
    workflow=Path('.github/workflows/opportunity_lifecycle.yml').read_text(encoding='utf-8')
    script=Path('scripts/run_opportunity_lifecycle.py').read_text(encoding='utf-8')
    module=Path('core/opportunity_lifecycle.py').read_text(encoding='utf-8')
    ui=Path('views/investment_desk.py').read_text(encoding='utf-8')
    health=Path('core/automation_health.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert 'run_opportunity_lifecycle' in workflow
    assert 'Opportunity Lifecycle & Shadow Book' in ui and 'opportunity_lifecycle' in health
    assert 'APP_VERSION = "11.39.9"' in config
    runtime=(workflow+script+module).lower()
    assert all(term not in runtime for term in ('place_order','submit_order','tradingclient','alpaca'))
    assert 'no_execution' in runtime and 'shadow_mode' in runtime
