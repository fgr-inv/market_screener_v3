from pathlib import Path
import numpy as np
import pandas as pd

from core.signal_lab import (HORIZONS, build_weekly_signal_lab_review,
    detect_signal_experiments, evaluate_signal_experiments, merge_signal_lab_ledger,
    technical_feature_frame)
from scripts.run_daily_signal_lab import build_signal_universe


def _history(rows=280, breakout=True):
    index=pd.bdate_range('2025-01-02',periods=rows)
    close=np.linspace(100,145,rows)+np.sin(np.arange(rows)/5)
    frame=pd.DataFrame({'Open':close-.2,'High':close+.5,'Low':close-.5,
                        'Close':close,'Volume':np.full(rows,1_000_000.0)},index=index)
    if breakout:
        frame.iloc[-1,frame.columns.get_loc('Close')]=155
        frame.iloc[-1,frame.columns.get_loc('High')]=156
        frame.iloc[-1,frame.columns.get_loc('Volume')]=3_000_000
    return frame


def test_breakout_variants_are_explicit_virtual_signals():
    history=_history()
    rows=detect_signal_experiments('TEST',history,history,{'universe_source':'S&P SmallCap 600'})
    breakout=[row for row in rows if row['setup_id']=='BREAKOUT_RVOL']
    assert {row['variant'] for row in breakout}=={'base','rvol_1_0','rvol_2_0'}
    assert all(row['direction']=='LONG' and row['shadow_mode'] and row['no_execution'] for row in breakout)
    assert all(row['universe_source']=='S&P SmallCap 600' for row in breakout)


def test_feature_history_does_not_change_when_future_bars_are_appended():
    history=_history(240,breakout=False)
    original=technical_feature_frame(history,history).iloc[-1]
    future=_history(250,breakout=False).iloc[-10:].copy()*7
    extended=pd.concat([history,future])
    same=technical_feature_frame(extended,extended).loc[history.index[-1]]
    for column in ('EMA20','EMA50','ATR14','RVOL','ADX','PRIOR_HIGH20','RVWAP20'):
        assert np.isclose(original[column],same[column],equal_nan=True)


def test_forward_evaluation_waits_for_each_trading_horizon_and_is_idempotent():
    initial=_history(250)
    future_index=pd.bdate_range(initial.index[-1]+pd.Timedelta(days=1),periods=30)
    future_close=np.linspace(float(initial.iloc[-1].Close)+.2,float(initial.iloc[-1].Close)+6,30)
    future=pd.DataFrame({'Open':future_close-.2,'High':future_close+.5,'Low':future_close-.5,
                         'Close':future_close,'Volume':np.full(30,1_000_000.0)},index=future_index)
    history=pd.concat([initial,future])
    signal=detect_signal_experiments('TEST',initial,initial)[0]
    outcomes=evaluate_signal_experiments([signal],{'TEST':history},history)
    assert {row['horizon_days'] for row in outcomes}==set(HORIZONS)
    assert all(row['status']=='MATURED' for row in outcomes)
    assert evaluate_signal_experiments([signal],{'TEST':history},history,outcomes)==[]
    merged=merge_signal_lab_ledger({'signals':[signal],'outcomes':outcomes},[signal],outcomes)
    assert len(merged['signals'])==1 and len(merged['outcomes'])==len(HORIZONS)


def test_weekly_review_can_only_propose_human_review():
    signals=[]; outcomes=[]
    for variant,role,alpha in [('base','CHAMPION',.1),('rvol_1_0','CHALLENGER',.8)]:
        for i in range(30):
            key=f'{variant}-{i}'
            signals.append({'signal_key':key,'ticker':f'T{i%6}','setup_id':'BREAKOUT_RVOL',
                            'variant':variant,'role':role,'signal_at':f'2026-01-{(i%28)+1:02d}'})
            outcomes.append({'signal_key':key,'horizon_days':5,'status':'MATURED','success':True,
                             'signed_alpha_pct':alpha,'mfe_pct':1.5,'mae_pct':-.4,'signal_at':signals[-1]['signal_at']})
    report=build_weekly_signal_lab_review(signals,outcomes)
    assert report['status']=='REVIEW_PROPOSED'
    assert report['automatic_rule_changes']==0
    assert report['proposals'][0]['status']=='HUMAN_REVIEW_REQUIRED'


def test_balanced_universe_includes_large_mid_small_and_cross_assets(monkeypatch):
    snapshot=pd.DataFrame([
        {'Ticker':'BIG','Universe Source':'S&P 500','Opportunity':90},
        {'Ticker':'MID','Universe Source':'S&P MidCap 400','Opportunity':88},
        {'Ticker':'SMALL','Universe Source':'S&P SmallCap 600','Opportunity':86},
    ])
    monkeypatch.setattr('scripts.run_daily_signal_lab.load_positions',lambda user_id:pd.DataFrame(columns=['ticker']))
    tickers,meta=build_signal_universe('u',snapshot)
    assert {'BIG','MID','SMALL','SPY','QQQ','IWM','BTC-USD','ETH-USD','SOL-USD'}<=set(tickers)
    assert meta['SMALL']['universe_source']=='S&P SmallCap 600'


def test_workflows_ui_and_version_keep_research_boundary():
    daily=Path('.github/workflows/daily_signal_lab.yml').read_text(encoding='utf-8')
    weekly=Path('.github/workflows/weekly_signal_lab_review.yml').read_text(encoding='utf-8')
    ui=Path('views/investment_desk.py').read_text(encoding='utf-8')
    module=Path('core/signal_lab.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert 'run_daily_signal_lab' in daily and 'run_weekly_signal_lab_review' in weekly
    version=config.split('APP_VERSION = "',1)[1].split('"',1)[0]
    assert 'Technical Signal Lab' in ui and tuple(int(part) for part in version.split('.')) >= (11,39)
    runtime=(daily+weekly+module).lower()
    assert all(term not in runtime for term in ('place_order','submit_order','tradingclient','alpaca'))
