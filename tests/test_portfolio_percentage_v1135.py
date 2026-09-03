import math

import numpy as np
import pandas as pd
import duckdb

import core.storage as storage
from core.portfolio_positions import resolve_position_allocations
from core.portfolio_risk import portfolio_risk
from core.portfolio_risk_agent import analyze_portfolio_risk
from core.scenario import stress_portfolio


def _prices(last=100,seed=1):
    rng=np.random.default_rng(seed)
    close=last*np.cumprod(1+rng.normal(.0004,.01,180))
    return pd.DataFrame({'Close':close},index=pd.date_range('2026-01-01',periods=180,freq='B'))


def test_declared_percentages_remain_exact_and_remainder_is_cash():
    positions=pd.DataFrame([
        {'ticker':'AMD','quantity':0,'avg_cost':0,'allocation_pct':30,'sector':'Technology'},
        {'ticker':'BTC-USD','quantity':0,'avg_cost':0,'allocation_pct':50,'sector':'Crypto'},
    ])
    detail,meta=resolve_position_allocations(positions,{'AMD':_prices(),'BTC-USD':_prices(seed=2)})
    weights=dict(zip(detail['Ticker'],detail['Weight %']))
    assert weights=={'AMD':30.0,'BTC-USD':50.0}
    assert meta['allocation_total_pct']==80
    assert meta['cash_pct']==20
    assert meta['basis']=='ALLOCATION_PCT'


def test_quantity_positions_share_only_unassigned_percentage():
    positions=pd.DataFrame([
        {'ticker':'AMD','quantity':0,'allocation_pct':30,'sector':'Technology'},
        {'ticker':'AAA','quantity':1,'allocation_pct':None,'sector':'Industrials'},
        {'ticker':'BBB','quantity':3,'allocation_pct':None,'sector':'Health Care'},
    ])
    detail,meta=resolve_position_allocations(positions,{'AMD':_prices(),'AAA':_prices(),'BBB':_prices()})
    weights=dict(zip(detail['Ticker'],detail['Weight %']))
    assert weights['AMD']==30
    assert round(weights['AAA'],1)==17.5
    assert round(weights['BBB'],1)==52.5
    assert meta['basis']=='MIXED' and meta['cash_pct']==0


def test_overallocation_is_not_silently_normalized():
    positions=pd.DataFrame([
        {'ticker':'AAA','allocation_pct':60},{'ticker':'BBB','allocation_pct':50},
    ])
    _,meta=resolve_position_allocations(positions,{})
    assert meta['status']=='OVER_ALLOCATED'
    assert meta['allocation_total_pct']==110


def test_percentage_portfolio_drives_risk_without_fake_dollar_value():
    positions=pd.DataFrame([
        {'ticker':'AAA','quantity':0,'avg_cost':0,'allocation_pct':30,'sector':'Technology'},
        {'ticker':'BBB','quantity':0,'avg_cost':0,'allocation_pct':50,'sector':'Health Care'},
    ])
    prices={'AAA':_prices(seed=1),'BBB':_prices(seed=2),'SPY':_prices(seed=3)}
    summary,detail,_=portfolio_risk(positions,prices)
    assert summary['Allocation Total %']==80
    assert summary['Cash / Unassigned %']==20
    assert math.isnan(summary['Market Value'])
    assert dict(zip(detail['Ticker'],detail['Weight %']))=={'AAA':30.0,'BBB':50.0}
    agent=analyze_portfolio_risk(positions,prices)
    assert agent.metadata['weights']=={'AAA':.3,'BBB':.5}
    assert agent.metadata['cash_pct']==20
    stress,_=stress_portfolio(positions,prices,'custom',scenario={'AAA':-.10,'BBB':-.20})
    assert round(stress['Estimated Portfolio %'],1)==-13.0
    assert math.isnan(stress['Estimated P&L $'])


def test_percentage_position_persists_without_quantity(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'portfolio.duckdb')
    monkeypatch.setattr(storage,'cloud_available',lambda:False)
    storage.upsert_position('AMD',sector='Technology',user_id='u',allocation_pct=25)
    loaded=storage.load_positions(user_id='u')
    assert len(loaded)==1
    assert float(loaded.iloc[0]['allocation_pct'])==25
    assert float(loaded.iloc[0]['quantity'])==0


def test_existing_quantity_database_migrates_without_data_loss(tmp_path,monkeypatch):
    db=tmp_path/'legacy.duckdb'
    con=duckdb.connect(str(db))
    con.execute('''CREATE TABLE portfolio_positions (
        ticker VARCHAR PRIMARY KEY, quantity DOUBLE, avg_cost DOUBLE,
        sector VARCHAR, note VARCHAR, updated_at TIMESTAMP)''')
    con.execute('''CREATE TABLE user_portfolio_positions (
        user_id VARCHAR, ticker VARCHAR, quantity DOUBLE, avg_cost DOUBLE,
        sector VARCHAR, note VARCHAR, updated_at TIMESTAMP,
        PRIMARY KEY (user_id,ticker))''')
    con.execute("INSERT INTO user_portfolio_positions VALUES ('u','OLD',2,50,'Technology','kept',CURRENT_TIMESTAMP)")
    con.close()
    monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    monkeypatch.setattr(storage,'DB_PATH',db)
    monkeypatch.setattr(storage,'cloud_available',lambda:False)
    before=storage.load_positions(user_id='u')
    assert before.iloc[0]['ticker']=='OLD' and pd.isna(before.iloc[0]['allocation_pct'])
    storage.upsert_position('NEW',sector='Crypto',user_id='u',allocation_pct=15)
    after=storage.load_positions(user_id='u').set_index('ticker')
    assert float(after.loc['OLD','quantity'])==2
    assert float(after.loc['NEW','allocation_pct'])==15


def test_version_and_schema_are_current():
    config=open('core/config.py',encoding='utf-8').read()
    production=open('core/production_storage.py',encoding='utf-8').read()
    assert 'APP_VERSION = "11.35"' in config
    assert 'allocation_pct DOUBLE PRECISION' in production
