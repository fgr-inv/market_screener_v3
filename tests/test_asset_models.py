import numpy as np
import pandas as pd

from core.indicators import enrich_indicators
from core.asset_models import analyze_asset, normalize_asset_type, effective_asset_type
from core.opportunity import attach_scores


def _prices(n=520, start=100, end=180):
    idx=pd.date_range('2024-01-01',periods=n,freq='D')
    close=np.linspace(start,end,n)+np.sin(np.arange(n)/13)*2
    return pd.DataFrame({'Open':close-.5,'High':close+1,'Low':close-1,'Close':close,'Volume':1_000_000},index=idx)


def test_type_normalization_and_etf_routing():
    assert normalize_asset_type('Acciones')=='Acción'
    assert normalize_asset_type('Bonos / Tasas')=='Bono/Tasa'
    assert effective_asset_type('TLT','ETF')=='Bono/Tasa'
    assert effective_asset_type('GLD','ETF')=='Commodity'


def test_crypto_uses_crypto_model_and_weekly_cycle():
    h=enrich_indicators(_prices())
    r=analyze_asset('BTC-USD',h,None,'Crypto','Cripto')
    assert r['Analysis_Model']=='Crypto'
    assert 'Weekly_Cycle_Score' in r
    assert 'ATR_Units_from_EMA21' in r


def test_yield_index_is_not_labeled_as_bond_price_uptrend():
    h=enrich_indicators(_prices(start=35,end=50))
    r=analyze_asset('^TNX',h,None,'Rates','Bono/Tasa')
    assert r['Rate_Series'] is True
    assert r['Trend'].startswith('Yield')


def test_non_equity_gets_asset_opportunity_score_without_fake_fundamentals():
    h=enrich_indicators(_prices())
    r=analyze_asset('EURUSD=X',h,None,'FX','Forex')
    r.update({'Asset_Type':'Forex','Asset_Context_Score':65,'Macro_Fit':65,'RS_Percentile':60,'Confidence_Score':80})
    out=attach_scores(pd.DataFrame([r])).iloc[0]
    assert pd.notna(out['Opportunity_Score'])
    assert pd.isna(out['Quality_Score'])
