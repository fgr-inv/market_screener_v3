import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import core.access_control as access_control
import core.market_data as market_data
from core.macro import sector_macro_score
from core.ui import display_value, key_value_frame


ROOT=Path(__file__).resolve().parents[1]


def _ui_files():
    return [ROOT/'app.py',*sorted((ROOT/'views').glob('*.py'))]


def test_views_have_no_raw_code_json_or_exception_renderers():
    forbidden=[]
    for path in _ui_files():
        tree=ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute):
                continue
            if isinstance(node.func.value,ast.Name) and node.func.value.id=='st' and node.func.attr in {'code','json','exception'}:
                forbidden.append((path.name,node.lineno,node.func.attr))
    assert forbidden==[]


def test_views_do_not_print_raw_exception_strings():
    findings=[]
    patterns=(r'st\.error\(str\((?:exc|e)\)\)',r'st\.warning\([^\n]*(?:\{exc\}|\{e\})')
    for path in _ui_files():
        source=path.read_text(encoding='utf-8')
        for pattern in patterns:
            if re.search(pattern,source): findings.append((path.name,pattern))
    assert findings==[]


def test_mixed_key_value_tables_are_arrow_safe_strings():
    frame=key_value_frame({'number':12.5,'state':'CURRENT','missing':np.nan,'items':['a','b'],'metadata':{'source':'cache'}})
    assert frame['Value'].map(type).eq(str).all()
    assert frame.set_index('Metric').loc['missing','Value']=='N/D'
    assert display_value({'source':'cache'})=='source: cache'


def test_symbol_classification_never_needs_live_metadata(monkeypatch):
    monkeypatch.setattr(market_data.yf,'Ticker',lambda *_args,**_kwargs: (_ for _ in ()).throw(AssertionError('live lookup')))
    assert market_data.classify_symbol('META')=='Acción'
    assert market_data.classify_symbol('IBIT')=='ETF'
    assert market_data.classify_symbol('BTC-USD')=='Cripto'
    assert market_data.classify_symbol('CL=F')=='Commodity'
    assert market_data.classify_symbol('EURUSD=X')=='Forex'
    assert market_data.classify_symbol('^GSPC')=='Índice'


def test_sector_macro_score_accepts_partial_or_old_snapshot():
    partial={'Macro_Score':62,'Breadth':58,'Credit':55,'Rates':48,'Liquidity':60}
    score=sector_macro_score('Technology',partial)
    assert 0<=score<=100
    assert 0<=sector_macro_score('Energy',{})<=100


def test_interrupted_streamlit_job_lease_is_recovered(monkeypatch):
    fake_streamlit=SimpleNamespace(session_state={})
    monkeypatch.setitem(sys.modules,'streamlit',fake_streamlit)
    access_control._ACTIVE_JOBS.clear()
    user={'user_id':'lease-test','plan':'FREE'}
    first=access_control.require_job_slot(user)
    assert first and fake_streamlit.session_state['_active_job_token']==first
    second=access_control.require_job_slot(user)
    assert second and second!=first
    assert [token for token,_expiry in access_control._ACTIVE_JOBS['lease-test']]==[second]
    access_control.end_job(second,user)
    assert access_control._ACTIVE_JOBS['lease-test']==[]


def test_known_empty_result_paths_have_user_facing_guards():
    sector=(ROOT/'views'/'sector_rotation.py').read_text(encoding='utf-8')
    backtest=(ROOT/'views'/'backtesting.py').read_text(encoding='utf-8')
    dashboard=(ROOT/'views'/'dashboard.py').read_text(encoding='utf-8')
    asset=(ROOT/'views'/'asset_analysis.py').read_text(encoding='utf-8')
    assert 'if df.empty:' in sector
    assert 'if events.empty:' in backtest
    assert 'or results.empty' in dashboard
    assert "if analysis_level=='Técnico':" in asset and 'Noticias omitidas en modo Técnico' in asset
