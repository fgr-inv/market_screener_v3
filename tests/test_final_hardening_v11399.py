from concurrent.futures import ThreadPoolExecutor
import json

import numpy as np
import pandas as pd

from core.durable_io import atomic_write_json
from core.factor_risk import build_factor_risk_context, factor_profile
from core.production_storage import _connection_retryable
from core.regime_multitimeframe import event_anchored_vwap
from core.signal_lab import estimate_execution_costs
from scripts.run_quality_gate import main as quality_gate


def _history(multiplier=1.0,rows=180):
    index=pd.bdate_range('2025-01-02',periods=rows)
    market=np.linspace(100,130,rows)+np.sin(np.arange(rows)/8)
    close=100+(market-100)*multiplier
    return pd.DataFrame({'Open':close-.2,'High':close+.5,'Low':close-.5,
                         'Close':close,'Volume':np.full(rows,1_000_000.0)},index=index)


def test_atomic_json_never_leaves_a_partial_document(tmp_path):
    target=tmp_path/'state.json'
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda number: atomic_write_json(target,{'writer':number,'rows':list(range(100))}),range(30)))
    payload=json.loads(target.read_text(encoding='utf-8'))
    assert payload['writer'] in range(30) and len(payload['rows'])==100


def test_transient_database_failures_are_retryable():
    assert _connection_retryable(RuntimeError('SSL connection has been closed unexpectedly'))
    assert _connection_retryable(RuntimeError('database is locked'))
    assert not _connection_retryable(ValueError('invalid SQL column'))


def test_liquidity_costs_penalize_small_illiquid_names():
    liquid=estimate_execution_costs({'ticker':'SPY','average_dollar_volume_20d':2_000_000_000})
    illiquid=estimate_execution_costs({'ticker':'SMALL','average_dollar_volume_20d':5_000_000,
                                       'market_cap_bucket':'Small Cap','volatility_regime':'HIGH'})
    assert illiquid[1]>liquid[1]


def test_factor_profile_and_portfolio_aggregation_are_explicit():
    histories={'SPY':_history(1.0),'QQQ':_history(1.3),'IWM':_history(.8),
               'TLT':_history(-.2),'UUP':_history(.1),'HYG':_history(.5),'ABC':_history(1.5)}
    profile=factor_profile('ABC',histories)
    context=build_factor_risk_context([{'ticker':'ABC','planned_weight_pct':25}],histories)
    assert profile['market_beta'] is not None and context['known_weight_pct']==25
    assert profile['dominant_factor'] in profile['factor_betas']


def test_event_avwap_uses_only_bars_from_anchor():
    history=_history()
    anchor=history.index[-20].date()
    result=event_anchored_vwap(history,anchor)
    sample=history.iloc[-20:]
    expected=(((sample.High+sample.Low+sample.Close)/3)*sample.Volume).sum()/sample.Volume.sum()
    assert result['state'] in {'ABOVE','BELOW','AT_ANCHOR'}
    assert np.isclose(result['value'],expected)


def test_release_quality_gate_passes():
    assert quality_gate()==0
