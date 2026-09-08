from pathlib import Path

import numpy as np
import pandas as pd

from core.regime_multitimeframe import analyze_regime_multitimeframe


def _bars(rows=420,start=100,end=180,freq='B',breakout=True):
    index=pd.date_range('2024-01-02',periods=rows,freq=freq)
    close=np.linspace(start,end,rows)
    frame=pd.DataFrame({'Open':close-.2,'High':close+.5,'Low':close-.5,'Close':close,
                        'Volume':np.full(rows,1_000_000.0)},index=index)
    if breakout:
        frame.iloc[-1,frame.columns.get_loc('Close')]=frame.iloc[-2].High+3
        frame.iloc[-1,frame.columns.get_loc('High')]=frame.iloc[-1].Close+.2
        frame.iloc[-1,frame.columns.get_loc('Low')]=frame.iloc[-1].Close-1.8
        frame.iloc[-1,frame.columns.get_loc('Open')]=frame.iloc[-1].Close-1.2
        frame.iloc[-1,frame.columns.get_loc('Volume')]=2_000_000
    return frame


def test_aligned_long_confirmation_uses_weekly_daily_hourly_rs_breadth_and_breakout():
    asset=_bars(); benchmark=_bars(end=130,breakout=False); sector=_bars(end=145,breakout=False)
    hourly=_bars(rows=300,start=140,end=182,freq='h',breakout=False)
    breadth=pd.DataFrame([{'Universe':'S&P 500','Score':72}])
    result=analyze_regime_multitimeframe('ABC',asset,hourly,benchmark,sector,breadth,'S&P 500','LONG','BREAKOUT_RVOL')
    assert result['gate_pass'] and result['status']=='CONFIRMED'
    assert result['weekly_bias']=='BULLISH' and result['daily_bias']=='BULLISH'
    assert result['hourly_bias']=='BULLISH' and result['breakout_quality']['score']>=55
    assert result['relative_strength_spy']['rs20_pct'] is not None
    assert result['frozen_at_signal'] and result['no_lookahead']


def test_missing_hourly_fails_closed_instead_of_becoming_neutral_pass():
    result=analyze_regime_multitimeframe('ABC',_bars(),None,_bars(end=130,breakout=False),
                                         None,pd.DataFrame([{'Universe':'S&P 500','Score':70}]),
                                         'S&P 500','LONG','BREAKOUT_RVOL')
    assert not result['gate_pass']
    assert 'HOURLY_CONFIRMATION_UNAVAILABLE' in result['contradictions']


def test_missing_breadth_and_benchmark_fail_closed():
    result=analyze_regime_multitimeframe('ABC',_bars(),_bars(rows=300,freq='h'),None,None,None,
                                         'S&P 500','LONG','DMI_ADX_TREND')
    assert not result['gate_pass']
    assert {'MARKET_REGIME_UNAVAILABLE','RELATIVE_STRENGTH_UNAVAILABLE','MARKET_BREADTH_UNAVAILABLE'}<=set(result['contradictions'])


def test_opposing_weekly_and_market_regime_block_long_signal():
    falling=_bars(start=180,end=100,breakout=False)
    hourly=_bars(rows=300,start=110,end=100,freq='h',breakout=False)
    result=analyze_regime_multitimeframe('ABC',falling,hourly,falling,None,
                                         pd.DataFrame([{'Universe':'S&P 500','Score':30}]),
                                         'S&P 500','LONG','DMI_ADX_TREND')
    assert not result['gate_pass'] and result['status']=='BLOCKED'
    assert 'WEEKLY_TREND_OPPOSES_SIGNAL' in result['contradictions']
    assert 'MARKET_REGIME_OPPOSES_SIGNAL' in result['contradictions']


def test_future_bars_do_not_change_the_frozen_prior_confirmation():
    asset=_bars(); hourly=_bars(rows=300,freq='h'); benchmark=_bars(end=140,breakout=False)
    prior=analyze_regime_multitimeframe('ABC',asset,hourly,benchmark,None,
                                        pd.DataFrame([{'Universe':'S&P 500','Score':60}]),
                                        'S&P 500','LONG','BREAKOUT_RVOL')
    future=_bars(rows=10,start=50,end=20,freq='B',breakout=False)
    future.index=pd.bdate_range(asset.index[-1]+pd.Timedelta(days=1),periods=10)
    repeated=analyze_regime_multitimeframe('ABC',pd.concat([asset,future]).loc[:asset.index[-1]],
                                           hourly,benchmark,None,pd.DataFrame([{'Universe':'S&P 500','Score':60}]),
                                           'S&P 500','LONG','BREAKOUT_RVOL')
    assert prior==repeated


def test_release_contract_exposes_mtf_without_execution_path():
    module=Path('core/regime_multitimeframe.py').read_text(encoding='utf-8')
    script=Path('scripts/run_opportunity_lifecycle.py').read_text(encoding='utf-8')
    ui=Path('views/investment_desk.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert 'download_intraday_prices' in script and 'latest_breadth' in script
    assert 'weekly_bias' in ui and 'relative_strength_spy_20d' in ui
    assert 'APP_VERSION = "11.39.9"' in config
    runtime=(module+script).lower()
    assert all(term not in runtime for term in ('place_order','submit_order','tradingclient','alpaca'))
